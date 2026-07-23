"""Public read-only winner certificates (safe shareable URLs)."""
from __future__ import annotations

from flask import Blueprint, abort, render_template, url_for

from app.services.certificates import certificate_view_context, get_certificate_by_token

bp = Blueprint("certificates", __name__, url_prefix="")


@bp.get("/certificado/<string:token>")
def public_view(token: str):
    cert = get_certificate_by_token(token)
    if cert is None:
        abort(404)
    ctx = certificate_view_context(cert)
    return render_template(
        "certificates/view.html",
        **ctx,
        is_admin_view=False,
        public_url=url_for("certificates.public_view", token=cert.public_token, _external=True),
    )
