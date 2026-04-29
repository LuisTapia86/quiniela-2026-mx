import os
from datetime import timedelta
from pathlib import Path


class Config:
    _env = (os.environ.get("FLASK_ENV") or os.environ.get("APP_ENV") or "").strip().lower()
    _debug_env = (os.environ.get("FLASK_DEBUG") or "0").strip().lower()
    _debug_on = _debug_env in {"1", "true", "yes", "on"}
    _is_production = _env == "production"
    _is_dev_or_test = _env in {"development", "test"} or _debug_on
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me-in-production")
    PERMANENT_SESSION_LIFETIME = timedelta(hours=1)
    SESSION_REFRESH_EACH_REQUEST = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _is_production or not _debug_on
    TEST_MODE_PAYMENTS = _is_dev_or_test and not _is_production
    TEST_MODE_PREDICTIONS_BYPASS = TEST_MODE_PAYMENTS
    BASE_DIR = Path(__file__).resolve().parent
    INSTANCE_DIR = BASE_DIR / "instance"
    _default_db = (INSTANCE_DIR / "app.db").resolve().as_posix()
    _local_sqlite_uri = f"sqlite:///{_default_db}"
    # Render and some hosts use postgres://; SQLAlchemy expects postgresql://
    _database_url = os.environ.get("DATABASE_URL")
    if _database_url and _database_url.startswith("postgres://"):
        _database_url = _database_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _database_url or _local_sqlite_uri
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = BASE_DIR / "instance" / "uploads"
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB; payment proofs + other uploads
    BRAND_NAME = "Quiniela World Cup 2026 MX"
    ADMIN_FEE_PERCENT = 5
    ENTRY_FEE_MXN = 1000
    # Share of the prize pool (100% - admin) for TOP 3; ties split that amount.
    PRIZE_TOP1_PERCENT = 60
    PRIZE_TOP2_PERCENT = 25
    PRIZE_TOP3_PERCENT = 15
    PAYMENT_PROOFS_FOLDER = BASE_DIR / "instance" / "uploads" / "payment_proofs"
    # Extensions without leading dot; lowercased on validation
    ALLOWED_PAYMENT_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "pdf"})
    PAYMENT_BENEFICIARY_NAME = os.environ.get("PAYMENT_BENEFICIARY_NAME", "Luis Javier Tapia Lara")
    PAYMENT_BANK = os.environ.get("PAYMENT_BANK", "Banamex")
    PAYMENT_CLABE = os.environ.get("PAYMENT_CLABE", "002580904146344260")
    PAYMENT_ACCOUNT = os.environ.get("PAYMENT_ACCOUNT", "4634426")
    API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY", "")
    API_FOOTBALL_BASE_URL = os.environ.get("API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io")
    API_FOOTBALL_WORLD_CUP_SEASON = int(os.environ.get("API_FOOTBALL_WORLD_CUP_SEASON", "2026") or "2026")
    _league_id_raw = (os.environ.get("API_FOOTBALL_WORLD_CUP_LEAGUE_ID") or "").strip()
    API_FOOTBALL_WORLD_CUP_LEAGUE_ID = int(_league_id_raw) if _league_id_raw else None

    # Email (verification, etc.) — Flask-Mail uses MAIL_* variables
    MAIL_SERVER = (os.environ.get("MAIL_SERVER") or "").strip() or None
    _mail_port = (os.environ.get("MAIL_PORT") or "587").strip()
    MAIL_PORT = int(_mail_port) if _mail_port.isdigit() else 587
    MAIL_USE_TLS = (os.environ.get("MAIL_USE_TLS") or "true").strip().lower() in {"1", "true", "yes", "on"}
    MAIL_USE_SSL = (os.environ.get("MAIL_USE_SSL") or "false").strip().lower() in {"1", "true", "yes", "on"}
    MAIL_USERNAME = (os.environ.get("MAIL_USERNAME") or "").strip() or None
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")  # intentionally may be unset
    _mail_sender = (os.environ.get("MAIL_DEFAULT_SENDER") or "").strip()
    MAIL_DEFAULT_SENDER = _mail_sender or None

    # Public site URL for verification links when building emails (e.g. https://your-app.onrender.com)
    SITE_URL = (os.environ.get("SITE_URL") or "").strip().rstrip("/")
