from __future__ import annotations

import re
import time
from functools import wraps
from typing import Any, Callable, TypeVar

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from app import db, limiter
from app.models import User
from app.translations import tr

bp = Blueprint("auth", __name__)

F = TypeVar("F", bound=Callable[..., Any])

_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")
_DISPLAY_NAME_RE = re.compile(r"^[A-Za-z0-9 _-]{3,40}$")
_ADMIN_SESSION_TIMEOUT_SECONDS = 30 * 60


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
        user = User(
            email=email,
            display_name=display_name,
            password_hash=generate_password_hash(password),
        )
        db.session.add(user)
        db.session.commit()
        flash(tr("flash.auth.account_created"), "ok")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", email="", display_name="")


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
            return render_template("auth/login.html", email=email)
        session.clear()
        session["user_id"] = user.id
        session.permanent = True
        session["is_admin"] = bool(user.is_admin)
        session["last_seen_at"] = time.time()
        next_url = (request.form.get("next") or request.args.get("next") or "").strip()
        if _is_safe_redirect(next_url):
            return redirect(next_url)
        return redirect(url_for("main.index"))
    return render_template("auth/login.html", email="")


@bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
