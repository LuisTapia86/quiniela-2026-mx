from flask import Blueprint, jsonify
from sqlalchemy import text

from app import db
from app.models import Match, User

bp = Blueprint("api", __name__)


@bp.get("/health")
def health():
    db.session.execute(text("SELECT 1"))
    return jsonify(status="ok", database=True)


@bp.get("/meta")
def meta():
    user_count = db.session.query(db.func.count(User.id)).scalar() or 0
    match_count = db.session.query(db.func.count(Match.id)).scalar() or 0
    return jsonify(users=user_count, matches=match_count, phase=1)
