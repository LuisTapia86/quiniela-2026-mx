from __future__ import annotations

import re
from functools import wraps
from typing import Any, Callable, TypeVar

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.models import User

bp = Blueprint("auth", __name__)

F = TypeVar("F", bound=Callable[..., Any])

_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")


def get_current_user() -> User | None:
    uid = session.get("user_id")
    if uid is None:
        return None
    try:
        return db.session.get(User, int(uid))
    except (TypeError, ValueError):
        return None


def login_required(f: F) -> F:
    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if get_current_user() is None:
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def _is_safe_redirect(target: str) -> bool:
    if not target or not target.startswith("/"):
        return False
    return not target.startswith("//") and "://" not in target


@bp.route("/register", methods=["GET", "POST"])
def register():
    if get_current_user() is not None:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if not email or not _EMAIL_RE.match(email):
            flash("Introduce un correo electrónico válido.", "error")
            return render_template("auth/register.html", email=email)
        if len(password) < 6:
            flash("La contraseña debe tener al menos 6 caracteres.", "error")
            return render_template("auth/register.html", email=email)
        if db.session.query(User.id).filter_by(email=email).first() is not None:
            flash("Ese correo ya está registrado.", "error")
            return render_template("auth/register.html", email=email)
        user = User(
            email=email,
            password_hash=generate_password_hash(password),
        )
        db.session.add(user)
        db.session.commit()
        flash("Cuenta creada. Inicia sesión.", "ok")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", email="")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if get_current_user() is not None:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()
        if user is None or not check_password_hash(user.password_hash, password):
            flash("Correo o contraseña incorrectos.", "error")
            return render_template("auth/login.html", email=email)
        session.clear()
        session["user_id"] = user.id
        session.permanent = True
        next_url = (request.form.get("next") or request.args.get("next") or "").strip()
        if _is_safe_redirect(next_url):
            return redirect(next_url)
        return redirect(url_for("main.index"))
    return render_template("auth/login.html", email="")


@bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
