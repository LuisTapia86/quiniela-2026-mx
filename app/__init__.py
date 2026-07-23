import os
from pathlib import Path

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import func, inspect, select, text

from config import Config
from app.translations import get_lang, t

db = SQLAlchemy()
mail = Mail()
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
    u.email_verified = True
    db.session.commit()
    app.logger.info(
        "Admin bootstrap: admin access granted to existing user; clear ADMIN_BOOTSTRAP_EMAIL in production when finished",
    )


def _emergency_admin_from_env(app: Flask) -> None:
    """Create or reset a single admin user when emergency env vars are set."""
    raw_email = os.environ.get("EMERGENCY_ADMIN_EMAIL")
    raw_password = os.environ.get("EMERGENCY_ADMIN_PASSWORD")
    if raw_email is None or raw_password is None:
        return
    email = (raw_email or "").strip().lower()
    password = raw_password or ""
    if not email or "@" not in email:
        app.logger.warning("EMERGENCY_ADMIN_EMAIL is set but invalid; ignored")
        return
    if not password:
        app.logger.warning("EMERGENCY_ADMIN_PASSWORD is set but empty; ignored")
        return

    from werkzeug.security import generate_password_hash

    from app.models import User

    password_hash = generate_password_hash(password)
    user = User.query.filter_by(email=email).first()
    if user is None:
        user = User(
            email=email,
            display_name="Admin",
            password_hash=password_hash,
            is_admin=True,
            email_verified=True,
            must_change_password=False,
        )
        db.session.add(user)
    else:
        user.is_admin = True
        user.email_verified = True
        user.must_change_password = False
        user.password_hash = password_hash

    db.session.commit()
    app.logger.info("Emergency admin ready: %s", email)


def _ensure_user_display_name_column() -> None:
    inspector = inspect(db.engine)
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "display_name" in cols:
        return
    db.session.execute(text("ALTER TABLE users ADD COLUMN display_name VARCHAR(50)"))
    db.session.commit()


def _ensure_user_display_name_width() -> None:
    inspector = inspect(db.engine)
    cols = {c["name"]: c for c in inspector.get_columns("users")}
    if "display_name" not in cols:
        return
    col_type = str(cols["display_name"].get("type", "")).lower()
    if "50" in col_type:
        return
    if db.engine.dialect.name == "postgresql":
        db.session.execute(text("ALTER TABLE users ALTER COLUMN display_name TYPE VARCHAR(50)"))
        db.session.commit()


def _ensure_user_email_verification_columns() -> None:
    """Add email verification columns; existing accounts are treated as verified (launch safety)."""
    cols = {c["name"] for c in inspect(db.engine).get_columns("users")}
    dialect = db.engine.dialect.name
    if "email_verified" not in cols:
        if dialect == "postgresql":
            db.session.execute(
                text(
                    "ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT TRUE",
                ),
            )
        else:
            db.session.execute(
                text(
                    "ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT 1",
                ),
            )
        db.session.commit()
        cols = {c["name"] for c in inspect(db.engine).get_columns("users")}
    if "email_verification_token" not in cols:
        db.session.execute(
            text("ALTER TABLE users ADD COLUMN email_verification_token VARCHAR(128)"),
        )
        db.session.commit()
        cols = {c["name"] for c in inspect(db.engine).get_columns("users")}
    if "email_verification_sent_at" not in cols:
        db.session.execute(
            text("ALTER TABLE users ADD COLUMN email_verification_sent_at TIMESTAMP"),
        )
        db.session.commit()
    # Legacy NULL = already registered before verification existed → keep access
    if dialect == "postgresql":
        db.session.execute(
            text("UPDATE users SET email_verified = TRUE WHERE email_verified IS NULL"),
        )
    else:
        db.session.execute(
            text("UPDATE users SET email_verified = 1 WHERE email_verified IS NULL"),
        )
    db.session.commit()


def _ensure_user_password_reset_columns() -> None:
    cols = {c["name"] for c in inspect(db.engine).get_columns("users")}
    if "password_reset_token" not in cols:
        db.session.execute(
            text("ALTER TABLE users ADD COLUMN password_reset_token VARCHAR(128)"),
        )
        db.session.commit()
    if "password_reset_sent_at" not in cols:
        db.session.execute(
            text("ALTER TABLE users ADD COLUMN password_reset_sent_at TIMESTAMP"),
        )
        db.session.commit()


def _ensure_user_must_change_password_column() -> None:
    cols = {c["name"] for c in inspect(db.engine).get_columns("users")}
    if "must_change_password" in cols:
        return
    dialect = db.engine.dialect.name
    if dialect == "postgresql":
        db.session.execute(
            text(
                "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT FALSE NOT NULL",
            ),
        )
    else:
        db.session.execute(
            text(
                "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT 0 NOT NULL",
            ),
        )
    db.session.commit()
    if dialect == "postgresql":
        db.session.execute(text("UPDATE users SET must_change_password = FALSE WHERE must_change_password IS NULL"))
    else:
        db.session.execute(text("UPDATE users SET must_change_password = 0 WHERE must_change_password IS NULL"))
    db.session.commit()


def _ensure_match_group_name_column() -> None:
    inspector = inspect(db.engine)
    cols = {c["name"] for c in inspector.get_columns("matches")}
    if "group_name" in cols:
        return
    db.session.execute(text("ALTER TABLE matches ADD COLUMN group_name VARCHAR(20)"))
    db.session.commit()


def _ensure_penalty_winner_columns() -> None:
    for table in ("predictions", "results"):
        cols = {c["name"] for c in inspect(db.engine).get_columns(table)}
        if "penalty_winner" in cols:
            continue
        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN penalty_winner VARCHAR(100)"))
        db.session.commit()


def _entry_table_column_names() -> set[str]:
    return {c["name"] for c in inspect(db.engine).get_columns("entries")}


def _ensure_entry_table_columns() -> None:
    """Add missing columns to ``entries`` using raw SQL only (no ORM on Entry).

    Must run before any ORM query that maps to ``entries``, so PostgreSQL
    and older databases that predate the soft-delete/cancellation columns
    do not throw UndefinedColumn.
    """
    cols = _entry_table_column_names()
    if "entry_number" not in cols:
        db.session.execute(text("ALTER TABLE entries ADD COLUMN entry_number INTEGER"))
        db.session.commit()
        cols = _entry_table_column_names()
    if "alias" not in cols:
        db.session.execute(text("ALTER TABLE entries ADD COLUMN alias VARCHAR(120)"))
        db.session.commit()
        cols = _entry_table_column_names()
    if "status" not in cols:
        # Default must match EntryStatus value strings (UPPERCASE) for the ORM.
        db.session.execute(
            text("ALTER TABLE entries ADD COLUMN status VARCHAR(40) DEFAULT 'ACTIVE'"),
        )
        db.session.commit()
    if "cancelled_at" not in _entry_table_column_names():
        db.session.execute(text("ALTER TABLE entries ADD COLUMN cancelled_at TIMESTAMP NULL"))
        db.session.commit()
    if "cancellation_reason" not in _entry_table_column_names():
        db.session.execute(
            text("ALTER TABLE entries ADD COLUMN cancellation_reason TEXT NULL"),
        )
        db.session.commit()

    _normalize_entry_status_values_raw_sql()


def _normalize_entry_status_values_raw_sql() -> None:
    """Map legacy lowercase / mixed case status strings to UPPER EntryStatus values.

    Run only with raw SQL (no Entry ORM) so loads never raise LookupError.
    """
    if "status" not in _entry_table_column_names():
        return
    # Order: most specific first; idempotent re-applies to already-upper values.
    stmts = [
        "UPDATE entries SET status = 'VOIDED_BY_ADMIN' "
        "WHERE LOWER(TRIM(COALESCE(status, ''))) = 'voided_by_admin'",
        "UPDATE entries SET status = 'CANCELLED_BY_USER' "
        "WHERE LOWER(TRIM(COALESCE(status, ''))) = 'cancelled_by_user'",
        "UPDATE entries SET status = 'ACTIVE' "
        "WHERE status IS NULL OR TRIM(COALESCE(status, '')) = '' "
        "OR LOWER(TRIM(COALESCE(status, ''))) = 'active'",
    ]
    for s in stmts:
        db.session.execute(text(s))
    db.session.commit()


def _ensure_winner_certificates_table() -> None:
    """Create winner_certificates if missing (safe on PostgreSQL + SQLite; additive only)."""
    from app.models import WinnerCertificate

    inspector = inspect(db.engine)
    if "winner_certificates" in inspector.get_table_names():
        return
    WinnerCertificate.__table__.create(bind=db.engine, checkfirst=True)

def _backfill_entry_number_and_alias() -> None:
    """ORM backfill: run only after ``_ensure_entry_table_columns()`` (all columns present)."""
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
    mail.init_app(app)
    limiter.init_app(app)
    csrf.init_app(app)

    from app import models  # noqa: F401
    from app.cli import register_cli
    from app.routes import (
        admin_bp,
        api_bp,
        auth_bp,
        certificates_bp,
        competitors_bp,
        entries_bp,
        leaderboard_bp,
        main_bp,
        rules_bp,
    )
    from app.routes.auth import get_current_user

    app.register_blueprint(auth_bp)
    app.register_blueprint(entries_bp)
    app.register_blueprint(competitors_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(leaderboard_bp)
    app.register_blueprint(certificates_bp)
    app.register_blueprint(rules_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    register_cli(app)

    from app.datetime_fmt import format_mexico_local

    @app.template_filter("mx_local")
    def _mx_local_datetime_filter(dt):
        return format_mexico_local(dt, get_lang())

    from app.team_flags import team_flag_static_path as _team_flag_static_path

    @app.template_filter("team_flag_src")
    def _team_flag_src_filter(team_name):
        return _team_flag_static_path(team_name)

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

        def entry_editable_name(entry) -> str:
            from app.entry_names import editable_entry_name

            return editable_entry_name(entry)

        return {
            "current_user": get_current_user(),
            "t": t,
            "lang": get_lang(),
            "has_logo": logo_path.is_file(),
            "entry_title": entry_title,
            "entry_editable_name": entry_editable_name,
        }

    with app.app_context():
        db.create_all()
        _ensure_user_display_name_column()
        _ensure_user_display_name_width()
        _ensure_user_email_verification_columns()
        _ensure_user_password_reset_columns()
        _ensure_user_must_change_password_column()
        _ensure_match_group_name_column()
        _ensure_penalty_winner_columns()
        _ensure_entry_table_columns()
        _ensure_winner_certificates_table()
        _backfill_entry_number_and_alias()
        _admin_bootstrap_from_env(app)
        _emergency_admin_from_env(app)

    return app
