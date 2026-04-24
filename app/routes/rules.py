from flask import Blueprint, render_template

bp = Blueprint("rules", __name__, url_prefix="")


@bp.get("/rules")
def index():
    return render_template("rules.html")
