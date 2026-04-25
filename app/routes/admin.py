from __future__ import annotations

import csv
import io
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app import db
from app.models import Entry, Match, Payment, PaymentStatus, Prediction, Result, TournamentState, User, utcnow
from app.routes.auth import get_current_user, login_required
from app.services.match_generation import generate_world_cup_2026_matches
from app.services.matches_csv import import_matches_from_reader
from app.prize_info import entry_financials
from app.services.scoring import recalculate_all_points

bp = Blueprint("admin", __name__, url_prefix="")


def _require_admin() -> None:
    u = get_current_user()
    assert u is not None
    if not u.is_admin:
        abort(403)


def _form_blank(v: str | None) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _parse_int_score(val: str | None) -> int | None:
    if _form_blank(val):
        return None
    try:
        n = int(str(val).strip())
    except ValueError:
        return None
    if n < 0:
        return None
    return n


def _safe_status(raw: str | None) -> str:
    v = (raw or "all").strip().lower()
    if v in {"all", "pending", "approved", "rejected"}:
        return v
    return "all"


def _is_test_payment_mode() -> bool:
    return bool(current_app.config.get("TEST_MODE_PAYMENTS", False))


@bp.get("/admin")
@login_required
def dashboard():
    _require_admin()
    total_users = db.session.scalar(select(func.count()).select_from(User)) or 0
    total_entries = db.session.scalar(select(func.count()).select_from(Entry)) or 0
    approved_entries = (
        db.session.scalar(
            select(func.count())
            .select_from(Payment)
            .where(Payment.status == PaymentStatus.APPROVED),
        )
        or 0
    )
    pending_payments = (
        db.session.scalar(
            select(func.count())
            .select_from(Payment)
            .where(Payment.status == PaymentStatus.PENDING),
        )
        or 0
    )
    rejected_payments = (
        db.session.scalar(
            select(func.count())
            .select_from(Payment)
            .where(Payment.status == PaymentStatus.REJECTED),
        )
        or 0
    )
    total_matches = db.session.scalar(select(func.count()).select_from(Match)) or 0
    completed_matches = db.session.scalar(select(func.count()).select_from(Result)) or 0
    admin_fee_percent = int(current_app.config.get("ADMIN_FEE_PERCENT", 5))
    fin = entry_financials(approved_entries, current_app.config)
    state = TournamentState.get_singleton()

    return render_template(
        "admin/dashboard.html",
        total_users=total_users,
        total_entries=total_entries,
        approved_entries=approved_entries,
        pending_payments=pending_payments,
        rejected_payments=rejected_payments,
        gross_collected=fin["gross_collected"],
        admin_fee_percent=admin_fee_percent,
        admin_fee_amount=fin["admin_fee_amount"],
        prize_pool=fin["prize_pool"],
        estimate_1st=fin["estimate_1st"],
        estimate_2nd=fin["estimate_2nd"],
        estimate_3rd=fin["estimate_3rd"],
        total_matches=total_matches,
        completed_matches=completed_matches,
        predictions_locked=state.predictions_locked,
    )


@bp.post("/admin/tournament/lock")
@login_required
def tournament_lock():
    _require_admin()
    state = TournamentState.get_singleton()
    state.predictions_locked = True
    db.session.commit()
    flash("Predicciones bloqueadas para todos los usuarios.", "ok")
    return redirect(url_for("admin.dashboard"))


@bp.post("/admin/tournament/unlock")
@login_required
def tournament_unlock():
    _require_admin()
    state = TournamentState.get_singleton()
    state.predictions_locked = False
    db.session.commit()
    flash("Predicciones abiertas nuevamente.", "ok")
    return redirect(url_for("admin.dashboard"))


@bp.post("/admin/recalculate")
@login_required
def recalculate():
    _require_admin()
    recalculate_all_points()
    db.session.commit()
    flash("Puntajes recalculados correctamente.", "ok")
    return redirect(url_for("admin.dashboard"))


@bp.route("/admin/results", methods=["GET", "POST"])
@login_required
def results():
    _require_admin()
    matches = list(
        db.session.scalars(
            select(Match)
            .options(joinedload(Match.result))
            .order_by(Match.match_number.asc(), Match.id.asc())
        )
    )
    if request.method == "POST":
        any_error = False
        for m in matches:
            raw_h = request.form.get(f"result_home_{m.id}")
            raw_a = request.form.get(f"result_away_{m.id}")
            if _form_blank(raw_h) and _form_blank(raw_a):
                continue
            h, a = _parse_int_score(raw_h), _parse_int_score(raw_a)
            if h is None or a is None:
                any_error = True
                break
        if any_error:
            flash("Los goles de resultado deben ser enteros ≥ 0. Deja vacío o completa local y visita.", "error")
        else:
            for m in matches:
                raw_h = request.form.get(f"result_home_{m.id}")
                raw_a = request.form.get(f"result_away_{m.id}")
                if _form_blank(raw_h) and _form_blank(raw_a):
                    continue
                h, a = _parse_int_score(raw_h), _parse_int_score(raw_a)
                assert h is not None and a is not None
                r = m.result
                if r is None:
                    r = Result(match_id=m.id, home_score=h, away_score=a)  # type: ignore[arg-type]
                    db.session.add(r)
                else:
                    r.home_score = h
                    r.away_score = a
            db.session.flush()
            recalculate_all_points()
            db.session.commit()
            flash("Resultados guardados y puntos recalculados.", "ok")
            return redirect(url_for("admin.results"))
    completed_matches = sum(1 for m in matches if m.result is not None)
    return render_template(
        "admin/results.html",
        matches=matches,
        completed_matches=completed_matches,
        total_matches=len(matches),
    )


@bp.route("/admin/matches/import", methods=["GET", "POST"])
@login_required
def matches_import():
    _require_admin()
    summary = None
    if request.method == "POST":
        f = request.files.get("csv_file")
        if f is None or not f.filename:
            flash("Selecciona un archivo CSV.", "error")
        else:
            try:
                text = f.read().decode("utf-8-sig")
                summary = import_matches_from_reader(io.StringIO(text))
                db.session.commit()
                flash("Importación procesada.", "ok")
            except UnicodeDecodeError:
                flash("El archivo debe estar en UTF-8.", "error")
    return render_template("admin/matches_import.html", summary=summary)


@bp.get("/admin/matches/template")
@login_required
def matches_template():
    _require_admin()
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["match_number", "stage", "home_team", "away_team", "kickoff_at"])
    w.writerow([1, "Fase de grupos", "Mexico", "South Africa", "2026-06-11 18:00"])
    w.writerow([2, "Fase de grupos", "Canada", "TBD", "2026-06-12 20:00"])
    w.writerow([3, "Fase de grupos", "USA", "TBD", "2026-06-12 22:00"])
    w.writerow([4, "Fase de grupos", "Argentina", "TBD", "2026-06-13 18:00"])
    w.writerow([5, "Fase de grupos", "Brazil", "TBD", "2026-06-14 18:00"])
    data = io.BytesIO(output.getvalue().encode("utf-8"))
    return send_file(
        data,
        mimetype="text/csv",
        as_attachment=True,
        download_name="matches_template.csv",
    )


@bp.get("/admin/matches")
@login_required
def matches():
    _require_admin()
    rows = db.session.execute(
        select(
            Match,
            func.count(Prediction.id).label("prediction_count"),
        )
        .outerjoin(Prediction, Prediction.match_id == Match.id)
        .group_by(Match.id)
        .order_by(Match.match_number.asc(), Match.id.asc()),
    ).all()
    return render_template("admin/matches.html", rows=rows)


@bp.get("/admin/payments")
@login_required
def payments():
    _require_admin()
    status = _safe_status(request.args.get("status"))
    q = (request.args.get("q") or "").strip()

    stmt = (
        select(Payment)
        .options(
            joinedload(Payment.user),
            joinedload(Payment.entry),
        )
        .order_by(Payment.created_at.desc(), Payment.id.desc())
    )
    if status != "all":
        stmt = stmt.where(Payment.status == PaymentStatus(status))
    if q:
        search = f"%{q.lower()}%"
        stmt = stmt.join(User, Payment.user_id == User.id).join(Entry, Payment.entry_id == Entry.id).where(
            or_(func.lower(User.email).like(search), func.lower(Entry.name).like(search)),
        )

    payments = list(
        db.session.scalars(stmt)
    )
    counts = {
        "all": db.session.scalar(select(func.count()).select_from(Payment)) or 0,
        "pending": (
            db.session.scalar(
                select(func.count()).select_from(Payment).where(Payment.status == PaymentStatus.PENDING),
            )
            or 0
        ),
        "approved": (
            db.session.scalar(
                select(func.count()).select_from(Payment).where(Payment.status == PaymentStatus.APPROVED),
            )
            or 0
        ),
        "rejected": (
            db.session.scalar(
                select(func.count()).select_from(Payment).where(Payment.status == PaymentStatus.REJECTED),
            )
            or 0
        ),
    }
    return render_template(
        "admin/payments.html",
        payments=payments,
        current_status=status,
        q=q,
        counts=counts,
        test_mode_payments=_is_test_payment_mode(),
    )


@bp.post("/admin/payments/test-approve")
@login_required
def payment_test_approve():
    _require_admin()
    if not _is_test_payment_mode():
        abort(404)
    status = _safe_status(request.args.get("status"))
    q = (request.args.get("q") or "").strip()
    raw_entry_id = (request.form.get("entry_id") or "").strip()
    try:
        entry_id = int(raw_entry_id)
    except ValueError:
        flash("ID de quiniela inválido.", "error")
        return redirect(url_for("admin.payments", status=status, q=q))
    entry = db.session.get(Entry, entry_id)
    if entry is None:
        flash(f"No existe la quiniela #{entry_id}.", "error")
        return redirect(url_for("admin.payments", status=status, q=q))
    payment = db.session.scalar(select(Payment).where(Payment.entry_id == entry.id))
    amount = int(current_app.config.get("ENTRY_FEE_MXN", 1000))
    if payment is None:
        payment = Payment(
            user_id=entry.user_id,
            entry_id=entry.id,
            amount_mxn=amount,
            status=PaymentStatus.APPROVED,
            admin_note="TEST MODE: aprobación manual sin comprobante",
        )
        db.session.add(payment)
    else:
        payment.user_id = entry.user_id
        payment.amount_mxn = amount
        payment.status = PaymentStatus.APPROVED
        payment.admin_note = "TEST MODE: aprobación manual sin comprobante"
        payment.updated_at = utcnow()
    db.session.commit()
    flash(f"Pago de prueba aprobado para quiniela #{entry.id}.", "ok")
    return redirect(url_for("admin.payments", status=status, q=q))


@bp.post("/admin/payments/<int:payment_id>/approve")
@login_required
def payment_approve(payment_id: int):
    _require_admin()
    p = db.session.get(Payment, payment_id)
    if p is None:
        abort(404)
    note = (request.form.get("admin_note") or "").strip() or None
    p.status = PaymentStatus.APPROVED
    p.admin_note = note
    p.updated_at = utcnow()
    db.session.commit()
    flash(f"Pago #{p.id} aprobado.", "ok")
    return redirect(url_for("admin.payments", status=request.args.get("status"), q=request.args.get("q")))


@bp.post("/admin/payments/<int:payment_id>/reject")
@login_required
def payment_reject(payment_id: int):
    _require_admin()
    p = db.session.get(Payment, payment_id)
    if p is None:
        abort(404)
    note = (request.form.get("admin_note") or "").strip() or None
    p.status = PaymentStatus.REJECTED
    p.admin_note = note
    p.updated_at = utcnow()
    db.session.commit()
    flash(f"Pago #{p.id} rechazado.", "ok")
    return redirect(url_for("admin.payments", status=request.args.get("status"), q=request.args.get("q")))


@bp.get("/admin/payments/<int:payment_id>/proof")
@login_required
def payment_proof(payment_id: int):
    _require_admin()
    p = db.session.get(Payment, payment_id)
    if p is None or not p.proof_stored_path:
        abort(404)
    base = Path(current_app.config["PAYMENT_PROOFS_FOLDER"]).resolve()
    try:
        target = (base / p.proof_stored_path).resolve()
        target.relative_to(base)
    except ValueError:
        abort(404)
    if not target.is_file():
        abort(404)
    return send_file(target, as_attachment=False, download_name=p.proof_stored_path)


@bp.get("/admin/seed-matches")
@login_required
def seed_matches_admin():
    _require_admin()
    generate_world_cup_2026_matches()
    flash("Matches created", "ok")
    return redirect(url_for("admin.matches"))