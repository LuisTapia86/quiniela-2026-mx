from flask import Blueprint, jsonify, render_template
from sqlalchemy import func, select

from app import db
from app.models import Entry, Match, Payment, Prediction, TournamentState
from app.routes.auth import get_current_user, login_required

bp = Blueprint("main", __name__)


@bp.get("/")
@login_required
def index():
    user = get_current_user()
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
    )


@bp.get("/health")
def health():
    return jsonify(status="ok", phase=1), 200
