from __future__ import annotations

from flask import Blueprint, abort, render_template
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app import db
from app.competitor_visibility import global_predictions_locked, mask_prediction_rows_for_competitors
from app.models import Entry, EntryStatus, Match, Payment, PaymentStatus, Prediction, User
from app.routes.auth import login_required
from app.routes.entries import build_prediction_rows
from app.services.scoring import summarize_prediction_audit
from app.tournament_stages import select_visible_matches
from app.translations import tr

bp = Blueprint("competitors", __name__, url_prefix="/competidores")


def _competitor_public_name(user: User, entry: Entry) -> str:
    name = (user.display_name or "").strip()
    if name:
        return name
    return tr("competitors.player_fallback", number=entry.entry_number or entry.id)


def _approved_active_entry(entry_id: int) -> tuple[Entry, User] | None:
    row = db.session.execute(
        select(Entry, User)
        .join(Payment, Payment.entry_id == Entry.id)
        .join(User, Entry.user_id == User.id)
        .where(
            Entry.id == entry_id,
            Entry.status == EntryStatus.ACTIVE,
            Payment.status == PaymentStatus.APPROVED,
        ),
    ).first()
    if row is None:
        return None
    return row[0], row[1]


@bp.get("/quinielas")
@login_required
def entries_list():
    rows = list(
        db.session.execute(
            select(Entry, User, Payment)
            .join(Payment, Payment.entry_id == Entry.id)
            .join(User, Entry.user_id == User.id)
            .where(
                Entry.status == EntryStatus.ACTIVE,
                Payment.status == PaymentStatus.APPROVED,
            )
            .order_by(Entry.total_points.desc(), Entry.created_at.asc(), Entry.id.asc()),
        ),
    )
    entries = [
        {
            "entry": entry,
            "user": user,
            "payment": payment,
            "public_name": _competitor_public_name(user, entry),
        }
        for entry, user, payment in rows
    ]
    return render_template("competitors/entries_list.html", entries=entries)


@bp.get("/quinielas/<int:entry_id>")
@login_required
def entry_detail(entry_id: int):
    resolved = _approved_active_entry(entry_id)
    if resolved is None:
        abort(404)
    entry, user = resolved
    global_locked = global_predictions_locked()

    matches = list(
        db.session.scalars(
            select_visible_matches().options(joinedload(Match.result)),
        ),
    )
    preds = list(
        db.session.scalars(select(Prediction).where(Prediction.entry_id == entry.id)),
    )
    by_match_id = {p.match_id: p for p in preds}
    rows, completed_predictions = build_prediction_rows(
        matches,
        by_match_id,
        global_locked=global_locked,
        count_progress_editable_only=False,
    )
    rows = mask_prediction_rows_for_competitors(rows, global_locked=global_locked)
    audit_summary = summarize_prediction_audit(rows)

    return render_template(
        "competitors/entry_detail.html",
        entry=entry,
        public_name=_competitor_public_name(user, entry),
        rows=rows,
        completed_predictions=completed_predictions,
        total_matches=len(matches),
        audit_summary=audit_summary,
    )
