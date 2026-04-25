from __future__ import annotations

import secrets
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import select
from werkzeug.utils import secure_filename

from app import db
from app.models import Entry, Match, Payment, PaymentStatus, Prediction, TournamentState
from app.payment_gating import is_payment_banking_configured
from app.routes.auth import get_current_user, login_required
from app.translations import tr

bp = Blueprint("entries", __name__, url_prefix="")

MX_TZ = ZoneInfo("America/Mexico_City")


@bp.route("/entries/new", methods=["GET", "POST"])
@login_required
def new():
    user = get_current_user()
    assert user is not None
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name or len(name) > 120:
            flash(tr("flash.entry.name_required"), "error")
            return render_template("entries/new.html", name=name)
        e = Entry(user_id=user.id, name=name)
        db.session.add(e)
        db.session.commit()
        flash(tr("flash.entry.created"), "ok")
        return redirect(url_for("main.index"))
    return render_template("entries/new.html", name="")


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

    if request.method == "POST" and not banking_configured:
        flash(f"{tr('payment.safe_gate')} {tr('payment.safe_gate.en')}", "error")
        return redirect(url_for("entries.entry_payment", entry_id=entry_id))

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

    pay = db.session.scalar(select(Payment).where(Payment.entry_id == entry_id))
    bypass_in_dev = bool(current_app.config.get("TEST_MODE_PREDICTIONS_BYPASS", False))
    if (pay is None or pay.status != PaymentStatus.APPROVED) and not bypass_in_dev:
        flash(tr("entry.payment_required"), "error")
        return redirect(url_for("entries.entry_payment", entry_id=entry_id))

    state = TournamentState.get_singleton()
    locked = state.predictions_locked
    matches = list(
        db.session.scalars(
            select(Match).order_by(Match.match_number.asc(), Match.id.asc())
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
        rows.append(
            {
                "match": m,
                "home": p.home_goals if p else 0,
                "away": p.away_goals if p else 0,
            }
        )
    return render_template(
        "predictions/edit.html",
        entry=entry,
        rows=rows,
        locked=locked,
        completed_predictions=completed_predictions,
        total_matches=len(matches),
        format_kickoff=_format_kickoff,
    )


def _format_kickoff(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt_aware = dt.replace(tzinfo=ZoneInfo("UTC"))
    else:
        dt_aware = dt
    local = dt_aware.astimezone(MX_TZ)
    return f"{local.strftime('%d/%m/%Y, %H:%M')} (CDMX)"
