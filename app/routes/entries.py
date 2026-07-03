from __future__ import annotations

import re

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

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
from app.entry_names import validate_entry_display_name
from app.payment_gating import is_payment_banking_configured
from app.payment_proofs import PaymentProofError, create_pending_payment, save_payment_proof
from app.routes.auth import get_current_user, login_required
from app.services.scoring import calculate_prediction_breakdown
from app.tournament_stages import is_knockout_stage, is_match_editable, select_visible_matches
from app.translations import tr

bp = Blueprint("entries", __name__, url_prefix="")


def _entry_fee_mxn() -> int:
    return int(current_app.config.get("ENTRY_FEE_MXN", 200))


def _create_pending_payment(entry: Entry, user_id: int) -> Payment:
    return create_pending_payment(entry, user_id)



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


def _uses_db_team_names(match_number: int) -> bool:
    """R32 (73–88) and Octavos (89–96): show home_team / away_team from DB."""
    return 73 <= match_number <= 96


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
        db.session.flush()
        db.session.add(_create_pending_payment(e, user.id))
        db.session.commit()
        flash(tr("flash.entry.created"), "ok")
        return redirect(url_for("main.index"))
    return render_template("entries/new.html", alias="")


def _rename_redirect(fallback: str):
    next_url = (request.form.get("next") or "").strip()
    if next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(fallback)


@bp.post("/entries/<int:entry_id>/rename")
@login_required
def rename_entry(entry_id: int):
    user = get_current_user()
    assert user is not None
    entry = db.session.get(Entry, entry_id)
    if entry is None:
        abort(404)
    if entry.user_id != user.id:
        abort(403)
    if entry.status != EntryStatus.ACTIVE:
        flash(tr("flash.entry.already_inactive"), "error")
        return _rename_redirect(url_for("main.index"))
    ok, result = validate_entry_display_name(request.form.get("name"))
    if not ok:
        flash(result, "error")
        return _rename_redirect(url_for("main.index"))
    entry.alias = result
    entry.name = result
    db.session.commit()
    flash(tr("flash.entry.renamed"), "ok")
    return _rename_redirect(url_for("main.index"))


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
            if payment is None:
                payment = _create_pending_payment(entry, user.id)
                db.session.add(payment)
                db.session.commit()
            flash(tr("flash.payment.awaiting_admin"), "ok")
            return redirect(url_for("entries.entry_payment", entry_id=entry.id))
        try:
            payment, created = save_payment_proof(entry, payment, f, user_id=user.id)
        except PaymentProofError as err:
            flash(tr(err.message_key, **err.format_kwargs), "error")
            return _payment_page()
        if created:
            db.session.add(payment)
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
            select_visible_matches()
            .options(joinedload(Match.result))
        )
    )
    preds = list(
        db.session.scalars(select(Prediction).where(Prediction.entry_id == entry.id))
    )
    by_match_id: dict[int, Prediction] = {p.match_id: p for p in preds}

    if request.method == "POST" and not locked:
        form_field_count = len(request.form)
        current_app.logger.info(
            "predictions_save_attempt entry_id=%s user_id=%s matches=%s form_fields=%s ua=%s",
            entry.id,
            user.id,
            len(matches),
            form_field_count,
            (request.user_agent.string or "")[:120],
        )
        saved, save_error = _save_predictions(entry, matches, by_match_id)
        if saved:
            current_app.logger.info(
                "predictions_save_success entry_id=%s user_id=%s",
                entry.id,
                user.id,
            )
            flash(tr("flash.predictions.saved"), "ok")
            return redirect(url_for("entries.predictions", entry_id=entry.id, saved=1))
        current_app.logger.warning(
            "predictions_save_failed entry_id=%s user_id=%s error=%s form_fields=%s",
            entry.id,
            user.id,
            save_error or "unknown",
            form_field_count,
        )
        if save_error:
            flash(save_error, "error")
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
            save_feedback=save_error,
        )

    if request.method == "POST" and locked:
        abort(403)

    return _render_predictions(entry, matches, by_match_id, locked=locked)


def _parse_score(val: str | None) -> int | None:
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    raw = str(val).strip()
    if "." in raw:
        raw = raw.split(".", 1)[0]
    try:
        n = int(raw)
    except ValueError:
        return None
    if n < 0:
        return None
    return n


def parse_penalty_winner_choice(raw: str | None, match: Match) -> str | None:
    return _parse_penalty_winner(raw, match)


def _parse_penalty_winner(raw: str | None, match: Match) -> str | None:
    value = (raw or "").strip()
    if not value:
        return None
    allowed = {(match.home_team or "").strip(), (match.away_team or "").strip()}
    if value in allowed:
        return value
    return None


def _save_predictions(
    entry: Entry,
    matches: list[Match],
    by_match_id: dict[int, Prediction],
) -> tuple[bool, str | None]:
    parsed: list[tuple[Match, int, int, str | None]] = []
    for m in matches:
        raw_h = (request.form.get(f"home_{m.id}") or "").strip()
        raw_a = (request.form.get(f"away_{m.id}") or "").strip()
        editable = is_match_editable(m, current_app.config, global_locked=False)

        if not editable:
            if raw_h == "" and raw_a == "":
                continue
            existing = by_match_id.get(m.id)
            h = _parse_score(raw_h) if raw_h != "" else None
            a = _parse_score(raw_a) if raw_a != "" else None
            if h is None or a is None:
                if raw_h != "" or raw_a != "":
                    current_app.logger.warning(
                        "predictions_save_locked_rejected entry_id=%s match_number=%s",
                        entry.id,
                        m.match_number,
                    )
                    return False, tr("flash.predictions.match_locked")
                continue
            if existing is None:
                current_app.logger.warning(
                    "predictions_save_locked_rejected entry_id=%s match_number=%s new_prediction",
                    entry.id,
                    m.match_number,
                )
                return False, tr("flash.predictions.match_locked")
            if h != existing.home_goals or a != existing.away_goals:
                current_app.logger.warning(
                    "predictions_save_locked_rejected entry_id=%s match_number=%s tamper",
                    entry.id,
                    m.match_number,
                )
                return False, tr("flash.predictions.match_locked")
            raw_pw = request.form.get(f"penalty_winner_{m.id}")
            if raw_pw is not None and _parse_penalty_winner(raw_pw, m) != (existing.penalty_winner or None):
                current_app.logger.warning(
                    "predictions_save_locked_rejected entry_id=%s match_number=%s penalty_tamper",
                    entry.id,
                    m.match_number,
                )
                return False, tr("flash.predictions.match_locked")
            continue

        if raw_h == "" and raw_a == "":
            continue
        if raw_h == "" or raw_a == "":
            return False, tr("flash.predictions.complete_pair")
        h, a = _parse_score(raw_h), _parse_score(raw_a)
        if h is None or a is None:
            return False, tr("flash.predictions.integer_goals")

        penalty_winner: str | None = None
        knockout = is_knockout_stage(m.stage)
        existing = by_match_id.get(m.id)
        scores_changed = existing is None or h != existing.home_goals or a != existing.away_goals
        raw_pw = request.form.get(f"penalty_winner_{m.id}")
        if knockout and h == a:
            parsed_pw = _parse_penalty_winner(raw_pw, m)
            if raw_pw and parsed_pw is None:
                return False, tr("flash.predictions.penalty_invalid")
            if scores_changed and not parsed_pw:
                return False, tr("flash.predictions.penalty_required")
            penalty_winner = parsed_pw or (existing.penalty_winner if existing else None)
        elif knockout:
            penalty_winner = None

        parsed.append((m, h, a, penalty_winner))
    current_app.logger.info(
        "predictions_save_parsed entry_id=%s parsed_count=%s",
        entry.id,
        len(parsed),
    )
    for m, h, a, penalty_winner in parsed:
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
                    penalty_winner=penalty_winner,
                )
            )
        else:
            pred.home_goals = h
            pred.away_goals = a
            pred.penalty_winner = penalty_winner
    try:
        db.session.commit()
    except Exception:  # pragma: no cover
        db.session.rollback()
        raise
    return True, None


def build_prediction_rows(
    matches: list[Match],
    by_match_id: dict[int, Prediction],
    *,
    global_locked: bool = False,
    count_progress_editable_only: bool = True,
) -> tuple[list[dict], int]:
    rows: list[dict] = []
    completed_predictions = 0
    last_date_key: str | None = None
    knockout_debug_logged = False
    for m in matches:
        editable = is_match_editable(m, current_app.config, global_locked=global_locked)
        p = by_match_id.get(m.id)
        if p is not None and (editable or not count_progress_editable_only):
            if count_progress_editable_only:
                if editable:
                    completed_predictions += 1
            else:
                completed_predictions += 1
        result: Result | None = m.result
        breakdown = None
        result_pending = result is None
        is_knockout = is_knockout_stage(m.stage)
        if p is not None and result is not None:
            breakdown = calculate_prediction_breakdown(
                p.home_goals,
                p.away_goals,
                result.home_score,
                result.away_score,
                pred_penalty_winner=p.penalty_winner,
                result_penalty_winner=result.penalty_winner,
                knockout=is_knockout,
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

        use_db_teams = _uses_db_team_names(m.match_number)
        if is_group or use_db_teams:
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

        pred_penalty = p.penalty_winner if p else None
        if p is not None:
            pred_text = f"{p.home_goals}-{p.away_goals}"
            if is_knockout and p.home_goals == p.away_goals and pred_penalty:
                pred_text = f"{pred_text} ({pred_penalty})"
        else:
            pred_text = "—"

        rows.append(
            {
                "match": m,
                "is_group_stage": is_group,
                "is_knockout": is_knockout,
                "use_db_teams": use_db_teams,
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
                "home": p.home_goals if p else None,
                "away": p.away_goals if p else None,
                "home_score": p.home_goals if p else None,
                "away_score": p.away_goals if p else None,
                "has_prediction": p is not None,
                "penalty_winner": pred_penalty,
                "prediction_text": pred_text,
                "result_text": (
                    (
                        f"{result.home_score}-{result.away_score}"
                        + (
                            f" ({result.penalty_winner})"
                            if is_knockout
                            and result.home_score == result.away_score
                            and result.penalty_winner
                            else ""
                        )
                    )
                    if result is not None
                    else tr("pred.pending_result")
                ),
                "result_pending": result_pending,
                "points_earned": points_earned,
                "breakdown": breakdown,
                "editable": editable,
                "lock_status_label": (
                    tr("pred.match_status.open") if editable else tr("pred.match_status.closed")
                ),
            }
        )
    return rows, completed_predictions


def _render_predictions(
    entry: Entry,
    matches: list[Match],
    by_match_id: dict[int, Prediction],
    *,
    locked: bool,
    save_feedback: str | None = None,
):
    rows, completed_predictions = build_prediction_rows(
        matches,
        by_match_id,
        global_locked=locked,
    )
    total_editable = sum(1 for m in matches if is_match_editable(m, current_app.config, global_locked=locked))
    return render_template(
        "predictions/edit.html",
        entry=entry,
        rows=rows,
        locked=locked,
        completed_predictions=completed_predictions,
        total_matches=total_editable,
        has_editable_matches=total_editable > 0,
        save_feedback=save_feedback,
        saved_banner=request.args.get("saved") == "1",
    )
