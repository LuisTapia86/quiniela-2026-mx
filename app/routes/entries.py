from __future__ import annotations

import secrets
import re
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from app import db
from app.models import (
    Entry,
    EntryStatus,
    Match,
    Payment,
    PAYMENT_CANCELLED_BY_USER_NOTE,
    PaymentStatus,
    Prediction,
    Result,
    TournamentState,
    utcnow,
)
from app.payment_gating import is_payment_banking_configured
from app.routes.auth import get_current_user, login_required
from app.services.scoring import calculate_prediction_breakdown
from app.translations import tr

bp = Blueprint("entries", __name__, url_prefix="")

_MONTHS_ES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]

_OFFICIAL_KNOCKOUT_SLOTS: dict[int, tuple[str, str]] = {
    73: ("2A", "2B"),
    74: ("1E", "B3(A/B/C/D/F)"),
    75: ("1F", "2C"),
    76: ("1C", "2F"),
    77: ("1I", "B3(C/D/F/G/H)"),
    78: ("2E", "2I"),
    79: ("1A", "B3(C/E/F/H/I)"),
    80: ("1L", "B3(E/H/I/J/K)"),
    81: ("1D", "B3(B/E/F/I/J)"),
    82: ("1G", "B3(A/E/H/I/J)"),
    83: ("2K", "2L"),
    84: ("1H", "2J"),
    85: ("1B", "B3(E/F/G/I/J)"),
    86: ("1J", "2H"),
    87: ("1K", "B3(D/E/I/J/L)"),
    88: ("2D", "2G"),
    89: ("W73", "W75"),
    90: ("W74", "W77"),
    91: ("W76", "W78"),
    92: ("W79", "W80"),
    93: ("W83", "W84"),
    94: ("W81", "W82"),
    95: ("W86", "W88"),
    96: ("W85", "W87"),
    97: ("W89", "W90"),
    98: ("W93", "W94"),
    99: ("W91", "W92"),
    100: ("W95", "W96"),
    101: ("W97", "W98"),
    102: ("W99", "W100"),
    103: ("L101", "L102"),
    104: ("W101", "W102"),
}

_OFFICIAL_KNOCKOUT_LABELS_2026: dict[int, str] = {
    73: "2.º Grupo A vs 2.º Grupo B",
    74: "1.º Grupo E vs Mejor 3.º (A/B/C/D/F)",
    75: "1.º Grupo F vs 2.º Grupo C",
    76: "1.º Grupo C vs 2.º Grupo F",
    77: "1.º Grupo I vs Mejor 3.º (C/D/F/G/H)",
    78: "2.º Grupo E vs 2.º Grupo I",
    79: "1.º Grupo A vs Mejor 3.º (C/E/F/H/I)",
    80: "1.º Grupo L vs Mejor 3.º (E/H/I/J/K)",
    81: "1.º Grupo D vs Mejor 3.º (B/E/F/I/J)",
    82: "1.º Grupo G vs Mejor 3.º (A/E/H/I/J)",
    83: "2.º Grupo K vs 2.º Grupo L",
    84: "1.º Grupo H vs 2.º Grupo J",
    85: "1.º Grupo B vs Mejor 3.º (E/F/G/I/J)",
    86: "1.º Grupo J vs 2.º Grupo H",
    87: "1.º Grupo K vs Mejor 3.º (D/E/I/J/L)",
    88: "2.º Grupo D vs 2.º Grupo G",
    89: "Ganador partido 73 vs Ganador partido 75",
    90: "Ganador partido 74 vs Ganador partido 77",
    91: "Ganador partido 76 vs Ganador partido 78",
    92: "Ganador partido 79 vs Ganador partido 80",
    93: "Ganador partido 83 vs Ganador partido 84",
    94: "Ganador partido 81 vs Ganador partido 82",
    95: "Ganador partido 86 vs Ganador partido 88",
    96: "Ganador partido 85 vs Ganador partido 87",
    97: "Ganador partido 89 vs Ganador partido 90",
    98: "Ganador partido 93 vs Ganador partido 94",
    99: "Ganador partido 91 vs Ganador partido 92",
    100: "Ganador partido 95 vs Ganador partido 96",
    101: "Ganador partido 97 vs Ganador partido 98",
    102: "Ganador partido 99 vs Ganador partido 100",
    103: "Perdedor partido 101 vs Perdedor partido 102",
    104: "Ganador partido 101 vs Ganador partido 102",
}


def _parse_group_letter(raw_group: str | None) -> str | None:
    value = (raw_group or "").strip()
    if not value:
        return None
    m = re.search(r"\b(?:grupo|group)\s+([A-L])\b", value, flags=re.IGNORECASE)
    if not m:
        return None
    return m.group(1).upper()


def _is_group_stage(stage: str | None) -> bool:
    value = (stage or "").strip().lower()
    return "grupo" in value or "group" in value


def _stage_title(match: Match) -> str:
    value = (match.stage or "").strip().lower()
    if _is_group_stage(match.stage):
        return "Fase de grupos"
    if "round of 32" in value or "dieciseisavos" in value:
        return "Dieciseisavos de final"
    if "round of 16" in value or "octavos" in value:
        return "Octavos de final"
    if "quarter" in value or "cuartos" in value:
        return "Cuartos de final"
    if "semifinal" in value:
        return "Semifinal"
    if "third" in value or "tercer" in value:
        return "Tercer lugar"
    if "final" in value:
        if re.fullmatch(r"L\d+", (match.home_team or "").strip()) and re.fullmatch(r"L\d+", (match.away_team or "").strip()):
            return "Tercer lugar"
        return "Final"
    return match.stage or "Eliminatoria"


def get_official_knockout_label(match_number: int) -> tuple[str, str] | None:
    return _OFFICIAL_KNOCKOUT_SLOTS.get(match_number)


def get_official_knockout_display_label(match_number: int) -> str | None:
    return _OFFICIAL_KNOCKOUT_LABELS_2026.get(match_number)


def format_knockout_slot(value: str | None) -> str:
    token = (value or "").strip()
    if not token:
        return "Por definir"
    lowered = token.lower()
    if lowered in {"a definir", "por definir"}:
        return "Por definir"
    m_wl = re.fullmatch(r"([WL])\s*(\d+)", token, flags=re.IGNORECASE)
    if m_wl:
        code = m_wl.group(1).upper()
        num = int(m_wl.group(2))
        return f"Ganador partido {num}" if code == "W" else f"Perdedor partido {num}"
    m_rank = re.fullmatch(r"([12])\s*([A-L])", token, flags=re.IGNORECASE)
    if m_rank:
        return f"{m_rank.group(1)}.º Grupo {m_rank.group(2).upper()}"
    m_best3_named = re.fullmatch(r"B3\(([A-L/\s]+)\)", token, flags=re.IGNORECASE)
    if m_best3_named:
        groups = re.sub(r"\s+", "", m_best3_named.group(1)).upper()
        return f"Mejor 3.º ({groups})"
    compact = re.sub(r"[^A-Za-z0-9]", "", token).upper()
    m_best3 = re.fullmatch(r"3([A-L]{1,12})", compact)
    if m_best3:
        groups = "/".join(list(m_best3.group(1)))
        return f"Mejor 3.º ({groups})"
    return token


def _date_label_es(match: Match) -> str:
    if match.kickoff_at is None:
        return "Fecha por definir"
    dt = match.kickoff_at
    return f"{dt.day} {_MONTHS_ES[dt.month - 1]} {dt.year}"

@bp.route("/entries/new", methods=["GET", "POST"])
@login_required
def new():
    user = get_current_user()
    assert user is not None
    if request.method == "POST":
        alias = (request.form.get("alias") or "").strip()
        if len(alias) > 120:
            flash(tr("flash.entry.alias_too_long"), "error")
            return render_template("entries/new.html", alias=alias)
        next_entry_number = (
            db.session.scalar(
                select(func.max(Entry.entry_number)).where(Entry.user_id == user.id),
            )
            or 0
        ) + 1
        e = Entry(
            user_id=user.id,
            name=alias or f"Entrada #{next_entry_number}",
            entry_number=next_entry_number,
            alias=alias or None,
            status=EntryStatus.ACTIVE,
        )
        db.session.add(e)
        db.session.commit()
        flash(tr("flash.entry.created"), "ok")
        return redirect(url_for("main.index"))
    return render_template("entries/new.html", alias="")


@bp.post("/entries/<int:entry_id>/cancel")
@login_required
def cancel_entry(entry_id: int):
    user = get_current_user()
    assert user is not None
    entry = db.session.get(Entry, entry_id)
    if entry is None:
        abort(404)
    if entry.user_id != user.id:
        abort(403)
    if entry.status != EntryStatus.ACTIVE:
        flash(tr("flash.entry.already_inactive"), "error")
        return redirect(url_for("main.index"))
    payment = db.session.scalar(select(Payment).where(Payment.entry_id == entry_id))
    if payment is not None and payment.status == PaymentStatus.APPROVED:
        flash(tr("flash.entry.cancel_approved_forbidden"), "error")
        return redirect(url_for("main.index"))
    entry.status = EntryStatus.CANCELLED_BY_USER
    entry.cancelled_at = utcnow()
    if payment is not None and payment.status == PaymentStatus.PENDING:
        payment.status = PaymentStatus.REJECTED
        payment.admin_note = PAYMENT_CANCELLED_BY_USER_NOTE
        payment.updated_at = utcnow()
    db.session.commit()
    flash(tr("flash.entry.cancelled_ok"), "ok")
    return redirect(url_for("main.index"))


@bp.route("/entries/<int:entry_id>/payment", methods=["GET", "POST"])
@login_required
def entry_payment(entry_id: int):
    user = get_current_user()
    assert user is not None
    entry = db.session.get(Entry, entry_id)
    if entry is None:
        abort(404)
    if entry.user_id != user.id:
        abort(403)
    if entry.status != EntryStatus.ACTIVE:
        flash(tr("flash.entry_payment.inactive"), "error")
        return redirect(url_for("main.index"))

    payment = db.session.scalar(select(Payment).where(Payment.entry_id == entry_id))
    banking_configured = is_payment_banking_configured(current_app.config)

    def _payment_page(**extra):
        ctx = {
            "entry": entry,
            "user": user,
            "payment": payment,
            "payment_banking_configured": banking_configured,
        }
        ctx.update(extra)
        return render_template("entries/payment.html", **ctx)

    if request.method == "POST":
        f = request.files.get("proof")
        if f is None or f.filename is None or f.filename.strip() == "":
            flash(tr("flash.payment.select_file"), "error")
            return _payment_page()
        raw_name = secure_filename(f.filename)
        if not raw_name or "." not in raw_name:
            flash(tr("flash.payment.invalid_name"), "error")
            return _payment_page()
        ext = raw_name.rsplit(".", 1)[-1].lower()
        allowed = current_app.config.get("ALLOWED_PAYMENT_EXTENSIONS", frozenset())
        if ext not in allowed:
            flash(
                tr("flash.payment.invalid_format", allowed=", ".join(sorted(allowed))),
                "error",
            )
            return _payment_page()
        try:
            f.stream.seek(0, 2)
            size_bytes = int(f.stream.tell())
            f.stream.seek(0)
        except Exception:
            size_bytes = 0
        max_bytes = int(current_app.config.get("MAX_CONTENT_LENGTH", 5 * 1024 * 1024))
        if size_bytes > 0 and size_bytes > max_bytes:
            flash(
                tr("flash.payment.file_too_large", max_mb=max(1, max_bytes // (1024 * 1024))),
                "error",
            )
            return _payment_page()
        store_name = f"{entry.id}_{secrets.token_hex(6)}.{ext}"
        dest_dir = Path(current_app.config["PAYMENT_PROOFS_FOLDER"])
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / store_name
        if payment and payment.proof_stored_path:
            old = dest_dir / payment.proof_stored_path
            if old != dest_path and old.is_file():
                try:
                    old.unlink()
                except OSError:
                    pass
        f.save(str(dest_path))
        fee = int(current_app.config.get("ENTRY_FEE_MXN", 1000))
        if payment is None:
            payment = Payment(
                user_id=user.id,
                entry_id=entry.id,
                amount_mxn=fee,
                proof_stored_path=store_name,
                status=PaymentStatus.PENDING,
            )
            db.session.add(payment)
        else:
            payment.proof_stored_path = store_name
            payment.status = PaymentStatus.PENDING
            payment.amount_mxn = fee
        db.session.commit()
        flash(tr("flash.payment.received"), "ok")
        return redirect(url_for("entries.entry_payment", entry_id=entry.id))

    return _payment_page()


@bp.route("/entries/<int:entry_id>/predictions", methods=["GET", "POST"])
@login_required
def predictions(entry_id: int):
    user = get_current_user()
    assert user is not None
    entry = db.session.get(Entry, entry_id)
    if entry is None:
        abort(404)
    if entry.user_id != user.id:
        abort(403)
    if entry.status != EntryStatus.ACTIVE:
        flash(tr("flash.predictions.entry_cancelled"), "error")
        return redirect(url_for("main.index"))

    state = TournamentState.get_singleton()
    locked = state.predictions_locked
    matches = list(
        db.session.scalars(
            select(Match)
            .options(joinedload(Match.result))
            .order_by(Match.match_number.asc(), Match.id.asc())
        )
    )
    preds = list(
        db.session.scalars(select(Prediction).where(Prediction.entry_id == entry.id))
    )
    by_match_id: dict[int, Prediction] = {p.match_id: p for p in preds}

    if request.method == "POST" and not locked:
        if _save_predictions(entry, matches):
            flash(tr("flash.predictions.saved"), "ok")
            return redirect(url_for("entries.predictions", entry_id=entry.id))
        by_match_id = {
            p.match_id: p
            for p in list(
                db.session.scalars(
                    select(Prediction).where(Prediction.entry_id == entry.id)
                )
            )
        }
        return _render_predictions(
            entry,
            matches,
            by_match_id,
            locked=locked,
        )

    if request.method == "POST" and locked:
        abort(403)

    return _render_predictions(entry, matches, by_match_id, locked=locked)


def _parse_score(val: str | None) -> int | None:
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return 0
    try:
        n = int(str(val).strip())
    except ValueError:
        return None
    if n < 0:
        return None
    return n


def _save_predictions(entry: Entry, matches: list[Match]) -> bool:
    parsed: list[tuple[Match, int, int]] = []
    for m in matches:
        raw_h = request.form.get(f"home_{m.id}")
        raw_a = request.form.get(f"away_{m.id}")
        h, a = _parse_score(raw_h), _parse_score(raw_a)
        if h is None or a is None:
            flash(tr("flash.predictions.integer_goals"), "error")
            return False
        parsed.append((m, h, a))
    for m, h, a in parsed:
        pred = (
            db.session.execute(
                select(Prediction).where(
                    Prediction.entry_id == entry.id,
                    Prediction.match_id == m.id,
                )
            )
            .scalars()
            .first()
        )
        if pred is None:
            db.session.add(
                Prediction(
                    entry_id=entry.id,
                    match_id=m.id,
                    home_goals=h,
                    away_goals=a,
                )
            )
        else:
            pred.home_goals = h
            pred.away_goals = a
    try:
        db.session.commit()
    except Exception:  # pragma: no cover
        db.session.rollback()
        raise
    return True


def _render_predictions(
    entry: Entry,
    matches: list[Match],
    by_match_id: dict[int, Prediction],
    *,
    locked: bool,
):
    rows: list[dict] = []
    completed_predictions = 0
    last_date_key: str | None = None
    knockout_debug_logged = False
    for m in matches:
        p = by_match_id.get(m.id)
        if p is not None:
            completed_predictions += 1
        result: Result | None = m.result
        breakdown = None
        result_pending = result is None
        if p is not None and result is not None:
            breakdown = calculate_prediction_breakdown(
                p.home_goals,
                p.away_goals,
                result.home_score,
                result.away_score,
            )
        points_earned = p.points_earned if p is not None and result is not None else None
        is_group = _is_group_stage(m.stage)
        stage_title = _stage_title(m)
        group_letter = _parse_group_letter(m.group_name)
        group_context = ""
        slot_subtitle = ""
        if m.kickoff_at is None:
            date_key = "Fecha por definir"
        else:
            date_key = m.kickoff_at.date().isoformat()
        date_break = date_key != last_date_key
        if date_break:
            last_date_key = date_key
        date_label = _date_label_es(m)
        if is_group and group_letter:
            group_context = f"Grupo {group_letter}"

        if is_group:
            slot_home = (m.home_team or "").strip() or "Por definir"
            slot_away = (m.away_team or "").strip() or "Por definir"
            match_label = f"{slot_home} vs {slot_away}"
            uses_official_2026 = False
        else:
            official_slots = get_official_knockout_label(m.match_number)
            raw_home = m.home_team
            raw_away = m.away_team
            official_label = get_official_knockout_display_label(m.match_number)
            if official_slots is not None:
                slot_home = format_knockout_slot(official_slots[0])
                slot_away = format_knockout_slot(official_slots[1])
            else:
                slot_home = format_knockout_slot(raw_home)
                slot_away = format_knockout_slot(raw_away)
            match_label = official_label or f"{slot_home} vs {slot_away}"
            uses_official_2026 = official_label is not None
            if not knockout_debug_logged:
                current_app.logger.info(
                    "Predictions knockout label debug: match_number=%s raw_home_team=%r raw_away_team=%r formatted=%r",
                    m.match_number,
                    raw_home,
                    raw_away,
                    match_label,
                )
                knockout_debug_logged = True

        rows.append(
            {
                "match": m,
                "is_group_stage": is_group,
                "group_context": group_context,
                "stage_title": stage_title,
                "slot_line": match_label,
                "match_label": match_label,
                "raw_home": m.home_team,
                "raw_away": m.away_team,
                "uses_official_2026": uses_official_2026,
                "slot_subtitle": slot_subtitle,
                "date_break": date_break,
                "date_label": date_label,
                "home": p.home_goals if p else 0,
                "away": p.away_goals if p else 0,
                "has_prediction": p is not None,
                "prediction_text": f"{p.home_goals}-{p.away_goals}" if p is not None else "—",
                "result_text": f"{result.home_score}-{result.away_score}" if result is not None else tr("pred.pending_result"),
                "result_pending": result_pending,
                "points_earned": points_earned,
                "breakdown": breakdown,
            }
        )
    return render_template(
        "predictions/edit.html",
        entry=entry,
        rows=rows,
        locked=locked,
        completed_predictions=completed_predictions,
        total_matches=len(matches),
    )
