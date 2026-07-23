"""Official Hall of Fame page (multi-edition podium)."""
from __future__ import annotations

from flask import Blueprint, render_template

from app.services.hall_of_fame import hall_of_fame_template_context

bp = Blueprint("hall_of_fame", __name__, url_prefix="")


@bp.get("/hall-of-fame")
def index():
    ctx = hall_of_fame_template_context()
    return render_template("hall_of_fame/index.html", **ctx)
