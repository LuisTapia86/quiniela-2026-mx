"""Tournament statistics page (read-only historical aggregates)."""
from __future__ import annotations

from flask import Blueprint, render_template

from app.services.statistics import compute_tournament_statistics

bp = Blueprint("statistics", __name__, url_prefix="")


@bp.get("/statistics")
def index():
    stats = compute_tournament_statistics()
    return render_template("statistics/index.html", **stats)
