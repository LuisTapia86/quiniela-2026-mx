from __future__ import annotations

import csv
import io

from flask import Blueprint, abort, current_app, make_response, render_template, send_file
from sqlalchemy import func, select

from app import db
from app.models import Entry, EntryStatus, Match, Payment, PaymentStatus, Prediction, Result, User
from app.prize_info import count_prize_pool_qualifying_entries, entry_financials
from app.routes.auth import get_current_user, login_required
from app.translations import tr

bp = Blueprint("leaderboard", __name__, url_prefix="")


def _entry_label(entry: Entry) -> str:
    number = entry.entry_number or entry.id
    alias = (entry.alias or "").strip()
    if alias:
        return tr("entry.label_with_alias", number=number, alias=alias)
    return tr("entry.label", number=number)


@bp.get("/leaderboard")
def index():
    rows = list(
        db.session.execute(
            select(Entry, User)
            .join(Payment, Payment.entry_id == Entry.id)
            .where(
                Payment.status == PaymentStatus.APPROVED,
                Entry.status == EntryStatus.ACTIVE,
            )
            .join(User, Entry.user_id == User.id)
            .order_by(Entry.total_points.desc(), Entry.created_at.asc(), Entry.id.asc())
        )
    )
    n_matches = (
        db.session.scalar(
            select(func.count()).select_from(Match)
        )
        or 0
    )
    n_with_result = (
        db.session.scalar(
            select(func.count()).select_from(Result)
        )
        or 0
    )
    n_approved = count_prize_pool_qualifying_entries()
    fin = entry_financials(n_approved, current_app.config)
    admin_pct = int(current_app.config.get("ADMIN_FEE_PERCENT", 5))

    leaderboard_rows: list[dict] = []
    prev_points: int | None = None
    rank = 0
    for i, (entry, user) in enumerate(rows, start=1):
        if prev_points is None or entry.total_points < prev_points:
            rank = i
        prev_points = entry.total_points
        n_pred = (
            db.session.scalar(
                select(func.count())
                .select_from(Prediction)
                .where(Prediction.entry_id == entry.id)
            )
            or 0
        )
        n_done = (
            db.session.scalar(
                select(func.count())
                .select_from(Prediction)
                .join(Match, Prediction.match_id == Match.id)
                .join(Result, Result.match_id == Match.id)
                .where(Prediction.entry_id == entry.id)
            )
            or 0
        )
        leaderboard_rows.append(
            {
                "rank": rank,
                "entry": entry,
                "entry_label": _entry_label(entry),
                "public_name": (user.display_name or "").strip() or f"{tr('leaderboard.player_fallback')} {entry.id}",
                "n_predictions": n_pred,
                "n_results_counted": n_done,
            }
        )
    html = render_template(
        "leaderboard/index.html",
        rows=leaderboard_rows,
        n_matches=n_matches,
        n_with_result=n_with_result,
        approved_entries_count=n_approved,
        gross_collected=fin["gross_collected"],
        admin_fee_amount=fin["admin_fee_amount"],
        prize_pool=fin["prize_pool"],
        admin_fee_percent=admin_pct,
        estimate_1st=fin["estimate_1st"],
        estimate_2nd=fin["estimate_2nd"],
        estimate_3rd=fin["estimate_3rd"],
    )
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@bp.get("/leaderboard/export.csv")
@login_required
def export_csv():
    u = get_current_user()
    if u is None or not u.is_admin:
        abort(403)
    rows = list(
        db.session.execute(
            select(Entry, User, Payment)
            .join(Payment, Payment.entry_id == Entry.id)
            .join(User, Entry.user_id == User.id)
            .order_by(Entry.total_points.desc(), Entry.created_at.asc(), Entry.id.asc()),
        ),
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "rank",
            "entry_name",
            "user_email",
            "total_points",
            "prediction_count",
            "completed_prediction_count",
            "payment_status",
            "entry_status",
        ],
    )
    prev_points: int | None = None
    rank = 0
    for i, (entry, user, payment) in enumerate(rows, start=1):
        if prev_points is None or entry.total_points < prev_points:
            rank = i
        prev_points = entry.total_points
        n_pred = (
            db.session.scalar(
                select(func.count()).select_from(Prediction).where(Prediction.entry_id == entry.id),
            )
            or 0
        )
        n_done = (
            db.session.scalar(
                select(func.count())
                .select_from(Prediction)
                .join(Match, Prediction.match_id == Match.id)
                .join(Result, Result.match_id == Match.id)
                .where(Prediction.entry_id == entry.id),
            )
            or 0
        )
        writer.writerow(
            [
                rank,
                _entry_label(entry),
                user.email,
                entry.total_points,
                n_pred,
                n_done,
                payment.status.value,
                entry.status.value,
            ],
        )
    data = io.BytesIO(out.getvalue().encode("utf-8"))
    return send_file(data, mimetype="text/csv", as_attachment=True, download_name="leaderboard_export.csv")
