from flask import Flask
from flask_sqlalchemy import SQLAlchemy

from config import Config

db = SQLAlchemy()


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

    return app
