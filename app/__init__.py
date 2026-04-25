import os

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

from config import Config

db = SQLAlchemy()


def _admin_bootstrap_from_env(app: Flask) -> None:
    """If ADMIN_BOOTSTRAP_EMAIL is set, grant admin to that user (no HTTP route)."""
    raw = os.environ.get("ADMIN_BOOTSTRAP_EMAIL")
    if raw is None:
        return
    email = (raw or "").strip().lower()
    if not email or "@" not in email:
        app.logger.warning("ADMIN_BOOTSTRAP_EMAIL is set but invalid; ignored")
        return
    from app.models import User

    u = User.query.filter_by(email=email).first()
    if u is None:
        return
    if u.is_admin:
        return
    u.is_admin = True
    db.session.commit()
    app.logger.info(
        "Admin bootstrap: admin access granted to existing user; clear ADMIN_BOOTSTRAP_EMAIL in production when finished",
    )


def create_app(config_object: type = Config) -> Flask:
    app = Flask(
        __name__,
        instance_relative_config=True,
    )
    app.config.from_object(config_object)

    config_object.INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    config_object.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    config_object.PAYMENT_PROOFS_FOLDER.mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    from app import models  # noqa: F401
    from app.cli import register_cli
    from app.routes import (
        admin_bp,
        api_bp,
        auth_bp,
        entries_bp,
        leaderboard_bp,
        main_bp,
        rules_bp,
    )
    from app.routes.auth import get_current_user

    app.register_blueprint(auth_bp)
    app.register_blueprint(entries_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(leaderboard_bp)
    app.register_blueprint(rules_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    register_cli(app)

    @app.context_processor
    def _inject_current_user() -> dict:
        return {"current_user": get_current_user()}

    with app.app_context():
        db.create_all()
        _admin_bootstrap_from_env(app)

    return app
