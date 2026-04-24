from __future__ import annotations

import csv
import io

from flask import Blueprint, abort, current_app, render_template, send_file
from sqlalchemy import func, select

from app import db
from app.models import Entry, Match, Payment, PaymentStatus, Prediction, Result, User
from app.routes.auth import get_current_user, login_required

bp = Blueprint("leaderboard", __name__, url_prefix="")


def mask_email(email: str) -> str:
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


@bp.get("/leaderboard")
def index():
    rows = list(
        db.session.execute(
            select(Entry, User)
            .join(Payment, Payment.entry_id == Entry.id)
            .where(Payment.status == PaymentStatus.APPROVED)
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
    n_approved = (
        db.session.scalar(
            select(func.count())
            .select_from(Payment)
            .where(Payment.status == PaymentStatus.APPROVED)
        )
        or 0
    )
    entry_fee = int(current_app.config.get("ENTRY_FEE_MXN", 1000))
    admin_pct = int(current_app.config.get("ADMIN_FEE_PERCENT", 5))
    gross = n_approved * entry_fee
    admin_revenue = (gross * admin_pct) // 100
    prize_pool = gross - admin_revenue

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
                "email_masked": mask_email(user.email),
                "n_predictions": n_pred,
                "n_results_counted": n_done,
            }
        )
    return render_template(
        "leaderboard/index.html",
        rows=leaderboard_rows,
        n_matches=n_matches,
        n_with_result=n_with_result,
        approved_entries_count=n_approved,
        gross_collected=gross,
        admin_fee_amount=admin_revenue,
        prize_pool=prize_pool,
        admin_fee_percent=admin_pct,
    )


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
            [rank, entry.name, user.email, entry.total_points, n_pred, n_done, payment.status.value],
        )
    data = io.BytesIO(out.getvalue().encode("utf-8"))
    return send_file(data, mimetype="text/csv", as_attachment=True, download_name="leaderboard_export.csv")
