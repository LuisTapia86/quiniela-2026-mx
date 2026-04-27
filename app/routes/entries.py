from __future__ import annotations

import secrets
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
        rows.append(
            {
                "match": m,
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
