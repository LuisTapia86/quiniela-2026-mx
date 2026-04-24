import os
from datetime import timedelta
from pathlib import Path


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me-in-production")
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    BASE_DIR = Path(__file__).resolve().parent
    INSTANCE_DIR = BASE_DIR / "instance"
    _default_db = (INSTANCE_DIR / "app.db").resolve().as_posix()
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", f"sqlite:///{_default_db}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = BASE_DIR / "instance" / "uploads"
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB; payment proofs + other uploads
    ADMIN_FEE_PERCENT = 5
    ENTRY_FEE_MXN = 1000
    PAYMENT_PROOFS_FOLDER = BASE_DIR / "instance" / "uploads" / "payment_proofs"
    # Extensions without leading dot; lowercased on validation
    ALLOWED_PAYMENT_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "pdf"})
    PAYMENT_BENEFICIARY_NAME = os.environ.get("PAYMENT_BENEFICIARY_NAME", "TODO_NOMBRE_BENEFICIARIO")
    PAYMENT_BANK = os.environ.get("PAYMENT_BANK", "TODO_BANCO")
    PAYMENT_CLABE = os.environ.get("PAYMENT_CLABE", "TODO_CLABE")
