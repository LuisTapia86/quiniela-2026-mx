import os
from pathlib import Path

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import inspect, select, text

from config import Config
from app.translations import get_lang, t

db = SQLAlchemy()
limiter = Limiter(key_func=get_remote_address, default_limits=[])
csrf = CSRFProtect()


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


def _ensure_user_display_name_column() -> None:
    inspector = inspect(db.engine)
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "display_name" in cols:
        return
    db.session.execute(text("ALTER TABLE users ADD COLUMN display_name VARCHAR(40)"))
    db.session.commit()


def _ensure_match_group_name_column() -> None:
    inspector = inspect(db.engine)
    cols = {c["name"] for c in inspector.get_columns("matches")}
    if "group_name" in cols:
        return
    db.session.execute(text("ALTER TABLE matches ADD COLUMN group_name VARCHAR(20)"))
    db.session.commit()


def _ensure_entry_columns_and_backfill() -> None:
    inspector = inspect(db.engine)
    cols = {c["name"] for c in inspector.get_columns("entries")}
    if "entry_number" not in cols:
        db.session.execute(text("ALTER TABLE entries ADD COLUMN entry_number INTEGER"))
        db.session.commit()
    if "alias" not in cols:
        db.session.execute(text("ALTER TABLE entries ADD COLUMN alias VARCHAR(120)"))
        db.session.commit()

    from app.models import Entry

    entry_rows = list(
        db.session.scalars(
            select(Entry).order_by(Entry.user_id.asc(), Entry.created_at.asc(), Entry.id.asc()),
        ),
    )
    current_user_id: int | None = None
    current_number = 0
    changed = False
    for row in entry_rows:
        if row.user_id != current_user_id:
            current_user_id = row.user_id
            current_number = 1
        else:
            current_number += 1
        if row.entry_number != current_number:
            row.entry_number = current_number
            changed = True
        alias = (row.alias or "").strip()
        if not alias:
            legacy_name = (row.name or "").strip()
            if legacy_name:
                row.alias = legacy_name
                changed = True
    if changed:
        db.session.commit()


def _ensure_entry_status_columns() -> None:
    inspector = inspect(db.engine)
    cols = {c["name"] for c in inspector.get_columns("entries")}
    if "status" not in cols:
        db.session.execute(text("ALTER TABLE entries ADD COLUMN status VARCHAR(32)"))
        db.session.commit()
    cols = {c["name"] for c in inspect(db.engine).get_columns("entries")}
    if "status" in cols:
        db.session.execute(
            text("UPDATE entries SET status = 'active' WHERE status IS NULL OR status = ''"),
        )
        db.session.commit()
    if "cancelled_at" not in cols:
        db.session.execute(text("ALTER TABLE entries ADD COLUMN cancelled_at TIMESTAMP"))
        db.session.commit()
    if "cancellation_reason" not in cols:
        db.session.execute(
            text("ALTER TABLE entries ADD COLUMN cancellation_reason VARCHAR(500)"),
        )
        db.session.commit()


def create_app(config_object: type = Config) -> Flask:
    app = Flask(
        __name__,
        instance_relative_config=True,
    )
    app.config.from_object(config_object)
    app_env = (os.environ.get("FLASK_ENV") or os.environ.get("APP_ENV") or "").strip().lower()
    if app_env == "production" and app.config.get("SECRET_KEY") == "dev-change-me-in-production":
        raise RuntimeError("SECRET_KEY must be configured in production.")

    config_object.INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    config_object.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    config_object.PAYMENT_PROOFS_FOLDER.mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    limiter.init_app(app)
    csrf.init_app(app)

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
        logo_path = Path(app.static_folder or "") / "img" / "logo.svg"

        def entry_title(entry) -> str:
            if entry is None:
                return ""
            number = entry.entry_number or entry.id
            alias = (entry.alias or "").strip()
            if alias:
                return t("entry.label_with_alias", number=number, alias=alias)
            return t("entry.label", number=number)

        return {
            "current_user": get_current_user(),
            "t": t,
            "lang": get_lang(),
            "has_logo": logo_path.is_file(),
            "entry_title": entry_title,
        }

    with app.app_context():
        db.create_all()
        _ensure_user_display_name_column()
        _ensure_match_group_name_column()
        _ensure_entry_columns_and_backfill()
        _ensure_entry_status_columns()
        _admin_bootstrap_from_env(app)

    return app
