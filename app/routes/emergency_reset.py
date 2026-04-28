"""TEMPORARY: one-shot production wipe without shell. Remove this module and its blueprint after use."""

from __future__ import annotations

import secrets
from pathlib import Path

from flask import Blueprint, Response, abort, current_app, request, session
from sqlalchemy import delete, func, select

from app import db
from app.models import (
    Entry,
    Payment,
    Prediction,
    Result,
    TournamentState,
    User,
    utcnow,
)

bp = Blueprint("emergency_reset", __name__)


def _count_rows(model) -> int:
    return db.session.scalar(select(func.count()).select_from(model)) or 0


def _clear_payment_proofs_folder() -> None:
    folder = Path(current_app.config["PAYMENT_PROOFS_FOLDER"]).resolve()
    if not folder.is_dir():
        return
    for p in folder.iterdir():
        if not p.is_file():
            continue
        try:
            p.unlink()
        except OSError as exc:
            current_app.logger.warning(
                "emergency reset: could not delete proof %s (%s)",
                p.name,
                exc,
            )


@bp.get("/emergency-reset-users")
def emergency_reset_users():
    expected = (current_app.config.get("EMERGENCY_RESET_TOKEN") or "").strip()
    if not expected:
        abort(404)
    provided = request.args.get("token") or ""
    if len(provided) != len(expected):
        abort(404)
    if not secrets.compare_digest(expected, provided):
        abort(404)

    current_app.logger.warning(
        "emergency_reset_users: wiping user-generated data (temporary route)",
    )

    try:
        summary = {
            "users_deleted": _count_rows(User),
            "entries_deleted": _count_rows(Entry),
            "payments_deleted": _count_rows(Payment),
            "predictions_deleted": _count_rows(Prediction),
            "results_deleted": _count_rows(Result),
        }
        db.session.execute(delete(Prediction))
        db.session.execute(delete(Result))
        db.session.execute(delete(Payment))
        db.session.execute(delete(Entry))
        db.session.execute(delete(User))
        row = db.session.get(TournamentState, 1)
        if row is None:
            db.session.add(TournamentState(id=1, predictions_locked=False))
        else:
            row.predictions_locked = False
            row.updated_at = utcnow()
        db.session.commit()
        db.session.expire_all()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("emergency_reset_users failed")
        return Response(
            "emergency_reset_failed\n",
            status=500,
            mimetype="text/plain; charset=utf-8",
        )

    _clear_payment_proofs_folder()
    session.clear()

    current_app.logger.info("emergency_reset_users completed: %s", summary)

    body = (
        "users_deleted={users_deleted}\n"
        "entries_deleted={entries_deleted}\n"
        "payments_deleted={payments_deleted}\n"
        "predictions_deleted={predictions_deleted}\n"
        "results_deleted={results_deleted}\n".format(**summary)
    )
    return Response(body, mimetype="text/plain; charset=utf-8")
