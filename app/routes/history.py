"""History archive of finished tournament editions."""
from __future__ import annotations

from flask import Blueprint, abort, render_template

from app.services.tournament_editions import history_archive_context, history_index_context

bp = Blueprint("history", __name__, url_prefix="")


@bp.get("/history")
def index():
    return render_template("history/index.html", **history_index_context())


@bp.get("/history/<string:slug>")
def archive(slug: str):
    ctx = history_archive_context(slug)
    if ctx is None:
        abort(404)
    return render_template("history/archive.html", **ctx)
