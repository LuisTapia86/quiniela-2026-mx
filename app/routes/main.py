from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, select

from app import db
from app.models import Entry, Match, Payment, Prediction, TournamentState, User
from app.routes.auth import _validate_display_name, get_current_user, login_required
from app.translations import tr

bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    user = get_current_user()
    if user is None:
        return render_template("landing.html")
    assert user is not None
    entries = list(
        db.session.scalars(
            select(Entry)
            .where(Entry.user_id == user.id)
            .order_by(Entry.id.desc())
        )
    )
    payments_by_entry: dict[int, Payment | None] = {}
    prediction_counts: dict[int, int] = {}
    total_matches = db.session.scalar(select(func.count()).select_from(Match)) or 0
    predictions_locked = TournamentState.get_singleton().predictions_locked
    if entries:
        eids = [e.id for e in entries]
        for p in db.session.scalars(select(Payment).where(Payment.entry_id.in_(eids))):
            payments_by_entry[p.entry_id] = p
        pred_rows = db.session.execute(
            select(Prediction.entry_id, func.count(Prediction.id))
            .where(Prediction.entry_id.in_(eids))
            .group_by(Prediction.entry_id),
        ).all()
        for entry_id, count in pred_rows:
            prediction_counts[int(entry_id)] = int(count)
        for e in entries:
            payments_by_entry.setdefault(e.id, None)
            prediction_counts.setdefault(e.id, 0)
    return render_template(
        "dashboard.html",
        entries=entries,
        payments_by_entry=payments_by_entry,
        prediction_counts=prediction_counts,
        total_matches=total_matches,
        predictions_locked=predictions_locked,
        needs_display_name=not bool((user.display_name or "").strip()),
    )


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = get_current_user()
    assert user is not None
    if request.method == "POST":
        ok_alias, alias_or_error = _validate_display_name(request.form.get("display_name"))
        if not ok_alias:
            flash(alias_or_error, "error")
            return render_template("profile.html", display_name=(request.form.get("display_name") or "").strip())
        alias = alias_or_error
        dup_user = db.session.scalar(
            select(User.id).where(func.lower(User.display_name) == alias.lower(), User.id != user.id),
        )
        if dup_user is not None:
            flash(tr("flash.auth.alias_exists"), "error")
            return render_template("profile.html", display_name=alias)
        user.display_name = alias
        db.session.commit()
        flash(tr("flash.profile.updated"), "ok")
        return redirect(url_for("main.profile"))
    return render_template("profile.html", display_name=(user.display_name or ""))


@bp.get("/health")
def health():
    return jsonify(status="ok", phase=1), 200


@bp.get("/set-language/<lang>")
def set_language(lang: str):
    chosen = (lang or "").strip().lower()
    if chosen in {"es", "en"}:
        session["lang"] = chosen
    next_url = (request.args.get("next") or request.referrer or "").strip()
    if next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(url_for("main.index"))
