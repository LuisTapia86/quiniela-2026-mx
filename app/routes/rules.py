from flask import Blueprint, render_template

bp = Blueprint("rules", __name__, url_prefix="")


@bp.get("/rules")
def index():
    return render_template("rules.html")


@bp.get("/terms")
def terms():
    return render_template("terms.html")


@bp.get("/privacy")
def privacy():
    return render_template("privacy.html")
