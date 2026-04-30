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

_ROUND32_PAIR_MAP: dict[int, tuple[str, str, str]] = {
    73: ("1A", "Mejor 3° (C/D/E)", "Ganador del grupo A vs uno de los mejores terceros"),
    74: ("2A", "2B", "Segundo del grupo A vs segundo del grupo B"),
    75: ("1B", "Mejor 3° (A/C/D)", "Ganador del grupo B vs uno de los mejores terceros"),
    76: ("1C", "Mejor 3° (E/F/G)", "Ganador del grupo C vs uno de los mejores terceros"),
    77: ("1D", "Mejor 3° (A/B/F)", "Ganador del grupo D vs uno de los mejores terceros"),
    78: ("2C", "2D", "Segundo del grupo C vs segundo del grupo D"),
    79: ("1E", "Mejor 3° (A/B/C/D)", "Ganador del grupo E vs uno de los mejores terceros"),
    80: ("1F", "Mejor 3° (E/F/G/H)", "Ganador del grupo F vs uno de los mejores terceros"),
    81: ("1G", "Mejor 3° (B/C/D)", "Ganador del grupo G vs uno de los mejores terceros"),
    82: ("2E", "2F", "Segundo del grupo E vs segundo del grupo F"),
    83: ("1H", "Mejor 3° (A/C/E)", "Ganador del grupo H vs uno de los mejores terceros"),
    84: ("1I", "Mejor 3° (B/D/F)", "Ganador del grupo I vs uno de los mejores terceros"),
    85: ("1J", "Mejor 3° (C/E/G)", "Ganador del grupo J vs uno de los mejores terceros"),
    86: ("2G", "2H", "Segundo del grupo G vs segundo del grupo H"),
    87: ("1K", "Mejor 3° (D/F/H)", "Ganador del grupo K vs uno de los mejores terceros"),
    88: ("1L", "Mejor 3° (A/E/H)", "Ganador del grupo L vs uno de los mejores terceros"),
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


def _human_slot(raw: str) -> str:
    token = (raw or "").strip()
    if not token:
        return "—"
    m_wl = re.fullmatch(r"([WL])(\d+)", token, flags=re.IGNORECASE)
    if m_wl:
        code = m_wl.group(1).upper()
        num = int(m_wl.group(2))
        return f"Ganador M{num}" if code == "W" else f"Perdedor M{num}"
    m_rank = re.fullmatch(r"([123])([A-L])", token, flags=re.IGNORECASE)
    if m_rank:
        return f"{m_rank.group(1)}{m_rank.group(2).upper()}"
    m_best3 = re.fullmatch(r"3([A-L]+)", token, flags=re.IGNORECASE)
    if m_best3:
        groups = "/".join(list(m_best3.group(1).upper()))
        return f"Mejor 3° ({groups})"
    return token

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
    group_seen_order: list[str] = []
    group_match_count: dict[str, int] = {}
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
        group_break = False
        slot_subtitle = ""
        if is_group and group_letter:
            if group_letter not in group_seen_order:
                group_seen_order.append(group_letter)
                group_break = len(group_seen_order) > 1
            count_for_group = group_match_count.get(group_letter, 0) + 1
            group_match_count[group_letter] = count_for_group
            matchday = ((count_for_group - 1) // 2) + 1
            group_context = f"Grupo {group_letter} • Jornada {matchday}"

        if stage_title == "Dieciseisavos de final" and m.match_number in _ROUND32_PAIR_MAP:
            slot_home, slot_away, slot_subtitle = _ROUND32_PAIR_MAP[m.match_number]
            slot_line = f"{slot_home} vs {slot_away}"
        else:
            slot_home = _human_slot(m.home_team)
            slot_away = _human_slot(m.away_team)
            slot_line = f"{slot_home} vs {slot_away}"

        rows.append(
            {
                "match": m,
                "is_group_stage": is_group,
                "group_context": group_context,
                "stage_title": stage_title,
                "slot_line": slot_line,
                "slot_subtitle": slot_subtitle,
                "group_break": group_break,
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
