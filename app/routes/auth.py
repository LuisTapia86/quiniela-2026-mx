from __future__ import annotations

import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable, TypeVar

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func, select
from werkzeug.security import check_password_hash, generate_password_hash

from app import db, limiter
from app.email_service import (
    mail_is_configured,
    send_password_reset_email,
    send_verification_email,
)
from app.models import User, utcnow
from app.translations import get_lang, tr

bp = Blueprint("auth", __name__)

F = TypeVar("F", bound=Callable[..., Any])

_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")
_DISPLAY_NAME_RE = re.compile(r"^[A-Za-z0-9 _-]{3,40}$")
_ADMIN_SESSION_TIMEOUT_SECONDS = 30 * 60
_PASSWORD_RESET_MAX_AGE = timedelta(hours=1)
_RESET_PASSWORD_MIN_LEN = 8


def _dt_utc_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _password_reset_token_valid(user: User) -> bool:
    if not user.password_reset_token or user.password_reset_sent_at is None:
        return False
    sent = _dt_utc_aware(user.password_reset_sent_at)
    now = _dt_utc_aware(utcnow())
    return now <= sent + _PASSWORD_RESET_MAX_AGE


def _user_for_valid_password_reset(token: str) -> User | None:
    """Return user if token exists and not expired; clear expired tokens."""
    if not token or len(token) > 256:
        return None
    user = db.session.scalar(select(User).where(User.password_reset_token == token))
    if user is None:
        return None
    if not _password_reset_token_valid(user):
        user.password_reset_token = None
        user.password_reset_sent_at = None
        db.session.commit()
        return None
    return user


def get_current_user() -> User | None:
    if _session_expired_for_admin():
        session.clear()
        return None
    uid = session.get("user_id")
    if uid is None:
        return None
    try:
        return db.session.get(User, int(uid))
    except (TypeError, ValueError):
        return None


def _session_expired_for_admin() -> bool:
    if not session.get("is_admin"):
        return False
    last_seen_raw = session.get("last_seen_at")
    if last_seen_raw is None:
        return True
    try:
        last_seen = float(last_seen_raw)
    except (TypeError, ValueError):
        return True
    return (time.time() - last_seen) > _ADMIN_SESSION_TIMEOUT_SECONDS


def login_required(f: F) -> F:
    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        user = get_current_user()
        if user is None:
            return redirect(url_for("auth.login", next=request.path))
        session["last_seen_at"] = time.time()
        session.permanent = True
        return f(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def _is_safe_redirect(target: str) -> bool:
    if not target or not target.startswith("/"):
        return False
    return not target.startswith("//") and "://" not in target


def _normalize_display_name(raw: str | None) -> str:
    return " ".join((raw or "").strip().split())


def _validate_display_name(raw: str | None) -> tuple[bool, str]:
    value = _normalize_display_name(raw)
    if not value:
        return False, tr("flash.auth.alias_required")
    if not _DISPLAY_NAME_RE.fullmatch(value):
        return False, tr("flash.auth.alias_invalid")
    if "@" in value or _EMAIL_RE.match(value):
        return False, tr("flash.auth.alias_no_email")
    return True, value


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("8 per minute")
def register():
    if get_current_user() is not None:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        display_name_raw = request.form.get("display_name")
        password = request.form.get("password") or ""
        if not email or not _EMAIL_RE.match(email):
            flash(tr("flash.auth.invalid_email"), "error")
            return render_template("auth/register.html", email=email, display_name=_normalize_display_name(display_name_raw))
        ok_alias, alias_or_error = _validate_display_name(display_name_raw)
        if not ok_alias:
            flash(alias_or_error, "error")
            return render_template("auth/register.html", email=email, display_name=_normalize_display_name(display_name_raw))
        display_name = alias_or_error
        if len(password) < 6:
            flash(tr("flash.auth.password_short"), "error")
            return render_template("auth/register.html", email=email, display_name=display_name)
        if db.session.query(User.id).filter_by(email=email).first() is not None:
            flash(tr("flash.auth.email_exists"), "error")
            return render_template("auth/register.html", email=email, display_name=display_name)
        if db.session.query(User.id).filter(func.lower(User.display_name) == display_name.lower()).first() is not None:
            flash(tr("flash.auth.alias_exists"), "error")
            return render_template("auth/register.html", email=email, display_name=display_name)
        tok = secrets.token_urlsafe(32)
        user = User(
            email=email,
            display_name=display_name,
            password_hash=generate_password_hash(password),
            email_verified=False,
            email_verification_token=tok,
            email_verification_sent_at=utcnow(),
        )
        db.session.add(user)
        db.session.commit()
        verify_url = send_verification_email(user.email, tok, lang=get_lang())
        if current_app.debug and not mail_is_configured():
            session["dev_verify_url_once"] = verify_url
        return redirect(url_for("auth.email_verification_sent"))
    return render_template("auth/register.html", email="", display_name="")


@bp.get("/register/email-sent")
def email_verification_sent():
    verify_url = session.pop("dev_verify_url_once", None)
    dev_verify_url = (
        verify_url if (current_app.debug and verify_url and not mail_is_configured()) else None
    )
    return render_template("auth/email_verification_sent.html", dev_verify_url=dev_verify_url)


@bp.route("/verify-email/<token>")
@limiter.limit("30 per minute")
def verify_email(token: str):
    if not token or len(token) > 256:
        flash(tr("flash.auth.verify_invalid"), "error")
        return redirect(url_for("auth.login"))
    user = db.session.scalar(select(User).where(User.email_verification_token == token))
    if user is None:
        flash(tr("flash.auth.verify_invalid"), "error")
        return redirect(url_for("auth.login"))
    user.email_verified = True
    user.email_verification_token = None
    user.email_verification_sent_at = None
    db.session.commit()
    flash(tr("flash.auth.verify_ok"), "ok")
    return redirect(url_for("auth.login"))


@bp.route("/resend-verification", methods=["GET", "POST"])
@limiter.limit("8 per minute")
def resend_verification():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        if email and _EMAIL_RE.match(email):
            u = User.query.filter_by(email=email).first()
            if u is not None and u.email_verified is False:
                tok = secrets.token_urlsafe(32)
                u.email_verification_token = tok
                u.email_verification_sent_at = utcnow()
                db.session.commit()
                send_verification_email(u.email, tok, lang=get_lang())
        flash(tr("flash.auth.resend_generic"), "ok")
        return redirect(url_for("auth.resend_verification"))
    return render_template("auth/resend_verification.html")


@bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("8 per minute")
def forgot_password():
    if get_current_user() is not None:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        if email and _EMAIL_RE.match(email):
            u = User.query.filter_by(email=email).first()
            if u is not None:
                tok = secrets.token_urlsafe(32)
                u.password_reset_token = tok
                u.password_reset_sent_at = utcnow()
                db.session.commit()
                reset_url = send_password_reset_email(u.email, tok, lang=get_lang())
                if current_app.debug and not mail_is_configured():
                    session["dev_pw_reset_once"] = reset_url
        # Same message regardless of whether the address exists or is valid (no enumeration).
        flash(tr("flash.auth.forgot_generic"), "ok")
        return redirect(url_for("auth.forgot_password"))
    dev_reset_url = session.pop("dev_pw_reset_once", None)
    dev_link = (
        dev_reset_url
        if current_app.debug and dev_reset_url and not mail_is_configured()
        else None
    )
    return render_template("auth/forgot_password.html", dev_reset_url=dev_link)


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("20 per minute")
def reset_password(token: str):
    if get_current_user() is not None:
        return redirect(url_for("main.index"))
    user = _user_for_valid_password_reset(token)
    if request.method == "GET":
        if user is None:
            flash(tr("flash.auth.reset_invalid"), "error")
            return redirect(url_for("auth.login"))
        return render_template("auth/reset_password.html", token=token)
    # POST
    user = _user_for_valid_password_reset(token)
    if user is None:
        flash(tr("flash.auth.reset_invalid"), "error")
        return redirect(url_for("auth.login"))
    pw = request.form.get("password") or ""
    pw2 = request.form.get("password_confirm") or ""
    if len(pw) < _RESET_PASSWORD_MIN_LEN:
        flash(tr("flash.auth.reset_password_short"), "error")
        return render_template("auth/reset_password.html", token=token)
    if pw != pw2:
        flash(tr("flash.auth.reset_password_mismatch"), "error")
        return render_template("auth/reset_password.html", token=token)
    user.password_hash = generate_password_hash(pw)
    user.password_reset_token = None
    user.password_reset_sent_at = None
    db.session.commit()
    flash(tr("flash.auth.reset_password_ok"), "ok")
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if get_current_user() is not None:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()
        if user is None or not check_password_hash(user.password_hash, password):
            flash(tr("flash.auth.bad_credentials"), "error")
            return render_template("auth/login.html", email=email, show_verify_help=False)
        if user.email_verified is False:
            flash(tr("flash.auth.must_verify_login"), "error")
            return render_template("auth/login.html", email=email, show_verify_help=True)
        session.clear()
        session["user_id"] = user.id
        session.permanent = True
        session["is_admin"] = bool(user.is_admin)
        session["last_seen_at"] = time.time()
        next_url = (request.form.get("next") or request.args.get("next") or "").strip()
        if _is_safe_redirect(next_url):
            return redirect(next_url)
        return redirect(url_for("main.index"))
    return render_template("auth/login.html", email="", show_verify_help=False)


@bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
