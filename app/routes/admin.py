from __future__ import annotations

import csv
import io
from pathlib import Path
import re

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    send_file,
    url_for,
)
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app import db
from app.models import Entry, Match, Payment, PaymentStatus, Prediction, Result, TournamentState, User, utcnow
from app.routes.auth import get_current_user, login_required
from app.services.api_football import (
    ApiFootballError,
    get_world_cup_league_candidates,
    import_fixtures_upsert,
    sync_results_from_api,
)
from app.services.match_generation import generate_world_cup_2026_matches
from app.services.matches_csv import import_matches_from_reader
from app.prize_info import entry_financials
from app.services.scoring import recalculate_all_points
from app.services.worldcup_scraper import WorldCupScraperError, fetch_fixtures_from_public_source
from app.translations import tr

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


@bp.get("/admin/users")
@login_required
def users():
    _require_admin()
    q = (request.args.get("q") or "").strip()

    entries_count_sq = (
        select(
            Entry.user_id.label("user_id"),
            func.count(Entry.id).label("entries_count"),
        )
        .group_by(Entry.user_id)
        .subquery()
    )
    approved_entries_sq = (
        select(
            Entry.user_id.label("user_id"),
            func.count(Entry.id).label("approved_entries_count"),
        )
        .join(Payment, Payment.entry_id == Entry.id)
        .where(Payment.status == PaymentStatus.APPROVED)
        .group_by(Entry.user_id)
        .subquery()
    )
    # Entries with no payment row OR payment still pending (not approved/rejected-only path)
    pending_payment_entries_sq = (
        select(
            Entry.user_id.label("user_id"),
            func.count(Entry.id).label("pending_payment_entries_count"),
        )
        .select_from(Entry)
        .outerjoin(Payment, Payment.entry_id == Entry.id)
        .where(or_(Payment.id.is_(None), Payment.status == PaymentStatus.PENDING))
        .group_by(Entry.user_id)
        .subquery()
    )
    rejected_entries_sq = (
        select(
            Entry.user_id.label("user_id"),
            func.count(Entry.id).label("rejected_entries_count"),
        )
        .select_from(Entry)
        .join(Payment, Payment.entry_id == Entry.id)
        .where(Payment.status == PaymentStatus.REJECTED)
        .group_by(Entry.user_id)
        .subquery()
    )

    stmt = (
        select(
            User,
            func.coalesce(entries_count_sq.c.entries_count, 0).label("entries_count"),
            func.coalesce(approved_entries_sq.c.approved_entries_count, 0).label("approved_entries_count"),
            func.coalesce(pending_payment_entries_sq.c.pending_payment_entries_count, 0).label(
                "pending_payment_entries_count",
            ),
            func.coalesce(rejected_entries_sq.c.rejected_entries_count, 0).label("rejected_entries_count"),
        )
        .outerjoin(entries_count_sq, entries_count_sq.c.user_id == User.id)
        .outerjoin(approved_entries_sq, approved_entries_sq.c.user_id == User.id)
        .outerjoin(pending_payment_entries_sq, pending_payment_entries_sq.c.user_id == User.id)
        .outerjoin(rejected_entries_sq, rejected_entries_sq.c.user_id == User.id)
        .order_by(User.created_at.desc(), User.id.desc())
    )
    if q:
        search = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.email).like(search),
                func.lower(func.coalesce(User.display_name, "")).like(search),
            ),
        )

    rows = list(db.session.execute(stmt))
    return render_template("admin/users.html", rows=rows, q=q)


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
    w.writerow(["match_number", "stage", "group_name", "home_team", "away_team", "kickoff_at"])
    w.writerow([1, "Fase de grupos", "Grupo A", "Mexico", "South Africa", "2026-06-11 18:00"])
    w.writerow([2, "Fase de grupos", "Grupo A", "Canada", "TBD", "2026-06-12 20:00"])
    w.writerow([3, "Fase de grupos", "Grupo B", "USA", "TBD", "2026-06-12 22:00"])
    w.writerow([4, "Fase de grupos", "Grupo C", "Argentina", "TBD", "2026-06-13 18:00"])
    w.writerow([5, "Fase de grupos", "Grupo C", "Brazil", "TBD", "2026-06-14 18:00"])
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


@bp.post("/admin/import-public-fixtures")
@login_required
def import_public_fixtures():
    _require_admin()
    try:
        summary = fetch_fixtures_from_public_source()
    except WorldCupScraperError as exc:
        flash(f"{tr('admin.public_import.failed')}: {exc}", "error")
        return redirect(url_for("admin.matches"))
    except Exception:
        current_app.logger.exception("Public fixtures import failed")
        flash(tr("admin.public_import.failed"), "error")
        return redirect(url_for("admin.matches"))
    flash(
        tr(
            "admin.public_import.success",
            source=summary.get("source", "public"),
            created=summary.get("created", 0),
            updated=summary.get("updated", 0),
            skipped=summary.get("skipped", 0),
            errors=len(summary.get("errors") or []),
        ),
        "ok",
    )
    return redirect(url_for("admin.matches"))


@bp.post("/admin/matches/cleanup-placeholders")
@login_required
def cleanup_placeholder_matches():
    _require_admin()
    group_slot_pattern = re.compile(r"^[A-L][1-3]$", flags=re.IGNORECASE)

    def _is_placeholder_team(raw: str | None) -> bool:
        team = (raw or "").strip()
        if not team:
            return False
        low = team.casefold()
        if team.startswith("Team "):
            return True
        if low in {"tbd", "a definir"}:
            return True
        if group_slot_pattern.fullmatch(team):
            return True
        if low.startswith("winner match") or low.startswith("ganador partido"):
            return True
        return False

    placeholder_match_ids = [
        m.id
        for m in db.session.scalars(select(Match))
        if _is_placeholder_team(m.home_team) or _is_placeholder_team(m.away_team)
    ]
    if not placeholder_match_ids:
        flash("No se encontraron partidos de prueba Team/TBD para limpiar.", "ok")
        return redirect(url_for("admin.matches"))

    db.session.query(Prediction).filter(Prediction.match_id.in_(placeholder_match_ids)).delete(synchronize_session=False)
    db.session.query(Result).filter(Result.match_id.in_(placeholder_match_ids)).delete(synchronize_session=False)
    deleted_matches = db.session.query(Match).filter(Match.id.in_(placeholder_match_ids)).delete(synchronize_session=False)
    db.session.commit()
    flash(f"Partidos de prueba eliminados: {deleted_matches}.", "ok")
    return redirect(url_for("admin.matches"))


@bp.post("/admin/matches/reset-all")
@login_required
def reset_all_matches():
    _require_admin()
    db.session.query(Prediction).delete(synchronize_session=False)
    db.session.query(Result).delete(synchronize_session=False)
    db.session.query(Match).delete(synchronize_session=False)
    db.session.commit()
    flash("Todos los partidos, predicciones y resultados fueron eliminados.", "ok")
    return redirect(url_for("admin.matches"))


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
        flash("ID de entrada inválido.", "error")
        return redirect(url_for("admin.payments", status=status, q=q))
    entry = db.session.get(Entry, entry_id)
    if entry is None:
        flash(f"No existe la entrada #{entry_id}.", "error")
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
    flash(f"Pago de prueba aprobado para entrada #{entry.id}.", "ok")
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


@bp.post("/admin/import-real-matches")
@login_required
def import_real_matches():
    _require_admin()
    confirm = (request.form.get("confirm_overwrite") or "").strip().lower()
    if confirm not in {"yes", "true", "1", "on"}:
        flash(tr("admin.real_import.confirm_required"), "error")
        return redirect(url_for("admin.matches_import"))
    api_key = (current_app.config.get("API_FOOTBALL_KEY") or "").strip()
    if not api_key:
        flash(tr("admin.real_import.missing_key"), "error")
        return redirect(url_for("admin.matches_import"))
    season_raw = (request.form.get("season") or "2026").strip()
    try:
        season = int(season_raw)
    except ValueError:
        flash(tr("admin.real_import.invalid_season"), "error")
        return redirect(url_for("admin.matches_import"))
    league_id_raw = current_app.config.get("API_FOOTBALL_WORLD_CUP_LEAGUE_ID")
    if league_id_raw is None:
        flash(tr("admin.api.league_or_season_invalid"), "error")
        return redirect(url_for("admin.matches_import"))
    league_id = int(league_id_raw)
    try:
        summary = import_fixtures_upsert(
            current_app.config.get("API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io"),
            api_key,
            season=season,
            league_id=league_id,
        )
    except ApiFootballError as exc:
        flash(f"{tr('admin.real_import.failed')}: {exc}", "error")
        return redirect(url_for("admin.matches_import"))
    except Exception:
        current_app.logger.exception("API-Football real import failed")
        flash(tr("admin.real_import.failed"), "error")
        return redirect(url_for("admin.matches_import"))
    flash(tr("admin.real_import.success", count=summary.get("fixtures_total", 0)), "ok")
    return redirect(url_for("admin.matches"))


@bp.get("/admin/api-football")
@login_required
def api_football_panel():
    _require_admin()
    return render_template(
        "admin/api_football.html",
        api_configured=bool((current_app.config.get("API_FOOTBALL_KEY") or "").strip()),
        base_url=current_app.config.get("API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io"),
        season=int(current_app.config.get("API_FOOTBALL_WORLD_CUP_SEASON", 2026)),
        configured_league_id=current_app.config.get("API_FOOTBALL_WORLD_CUP_LEAGUE_ID"),
        candidates=session.get("api_football_candidates") or [],
        last_summary=session.get("api_football_last_summary") or {},
    )


@bp.post("/admin/api-football/search-leagues")
@login_required
def api_football_search_leagues():
    _require_admin()
    api_key = (current_app.config.get("API_FOOTBALL_KEY") or "").strip()
    if not api_key:
        flash(tr("admin.real_import.missing_key"), "error")
        return redirect(url_for("admin.api_football_panel"))
    season_raw = (request.form.get("season") or str(current_app.config.get("API_FOOTBALL_WORLD_CUP_SEASON", 2026))).strip()
    try:
        season = int(season_raw)
    except ValueError:
        flash(tr("admin.real_import.invalid_season"), "error")
        return redirect(url_for("admin.api_football_panel"))
    try:
        candidates = get_world_cup_league_candidates(
            current_app.config.get("API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io"),
            api_key,
            season=season,
        )
    except ApiFootballError as exc:
        flash(f"{tr('admin.api.search_failed')}: {exc}", "error")
        return redirect(url_for("admin.api_football_panel"))
    session["api_football_candidates"] = candidates
    flash(tr("admin.api.search_ok", count=len(candidates)), "ok")
    return redirect(url_for("admin.api_football_panel"))


@bp.post("/admin/api-football/import-fixtures")
@login_required
def api_football_import_fixtures():
    _require_admin()
    api_key = (current_app.config.get("API_FOOTBALL_KEY") or "").strip()
    if not api_key:
        flash(tr("admin.real_import.missing_key"), "error")
        return redirect(url_for("admin.api_football_panel"))
    season_raw = (request.form.get("season") or str(current_app.config.get("API_FOOTBALL_WORLD_CUP_SEASON", 2026))).strip()
    league_id_raw = (request.form.get("league_id") or str(current_app.config.get("API_FOOTBALL_WORLD_CUP_LEAGUE_ID") or "")).strip()
    try:
        season = int(season_raw)
        league_id = int(league_id_raw)
    except ValueError:
        flash(tr("admin.api.league_or_season_invalid"), "error")
        return redirect(url_for("admin.api_football_panel"))
    try:
        summary = import_fixtures_upsert(
            current_app.config.get("API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io"),
            api_key,
            season=season,
            league_id=league_id,
            allow_clear_without_predictions=True,
        )
    except ApiFootballError as exc:
        flash(f"{tr('admin.api.import_failed')}: {exc}", "error")
        return redirect(url_for("admin.api_football_panel"))
    session["api_football_last_summary"] = {
        "created": summary.get("created", 0),
        "updated": summary.get("updated", 0),
        "skipped": summary.get("skipped", 0),
        "results_synced": 0,
        "errors": summary.get("errors", []),
    }
    flash(tr("admin.api.import_ok"), "ok")
    return redirect(url_for("admin.api_football_panel"))


@bp.post("/admin/api-football/sync-results")
@login_required
def api_football_sync_results():
    _require_admin()
    api_key = (current_app.config.get("API_FOOTBALL_KEY") or "").strip()
    if not api_key:
        flash(tr("admin.real_import.missing_key"), "error")
        return redirect(url_for("admin.api_football_panel"))
    season_raw = (request.form.get("season") or str(current_app.config.get("API_FOOTBALL_WORLD_CUP_SEASON", 2026))).strip()
    league_id_raw = (request.form.get("league_id") or str(current_app.config.get("API_FOOTBALL_WORLD_CUP_LEAGUE_ID") or "")).strip()
    try:
        season = int(season_raw)
        league_id = int(league_id_raw)
    except ValueError:
        flash(tr("admin.api.league_or_season_invalid"), "error")
        return redirect(url_for("admin.api_football_panel"))
    try:
        summary = sync_results_from_api(
            current_app.config.get("API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io"),
            api_key,
            season=season,
            league_id=league_id,
        )
    except ApiFootballError as exc:
        flash(f"{tr('admin.api.sync_failed')}: {exc}", "error")
        return redirect(url_for("admin.api_football_panel"))
    last = session.get("api_football_last_summary") or {}
    session["api_football_last_summary"] = {
        "created": last.get("created", 0),
        "updated": last.get("updated", 0),
        "skipped": summary.get("skipped", 0),
        "results_synced": summary.get("results_synced", 0),
        "errors": summary.get("errors", []),
    }
    flash(tr("admin.api.sync_ok", count=summary.get("results_synced", 0)), "ok")
    return redirect(url_for("admin.api_football_panel"))