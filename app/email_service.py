from __future__ import annotations

from flask import current_app, url_for
from flask_mail import Message

from app import mail


def mail_is_configured() -> bool:
    return bool(current_app.config.get("MAIL_SERVER") and current_app.config.get("MAIL_DEFAULT_SENDER"))


def verification_absolute_url(token: str) -> str:
    """Absolute URL for the verification link (SITE_URL preferred on Render)."""
    path = url_for("auth.verify_email", token=token)
    base = (current_app.config.get("SITE_URL") or "").strip().rstrip("/")
    if base:
        return f"{base}{path}"
    try:
        return url_for("auth.verify_email", token=token, _external=True)
    except RuntimeError:
        return path


def send_verification_email(to_email: str, token: str, *, lang: str | None = None) -> str:
    """Send verification mail if SMTP is configured; always return the link for logging/UI.

    *lang*: optional locale hint ('es' / 'en') for email body wording.
    """
    verify_url = verification_absolute_url(token)
    lng = (lang or "es").strip().lower()[:2]

    body = (
        f"{'Verifica tu correo:' if lng == 'es' else 'Verify your email:'}\n{verify_url}\n\n"
        f"{'En / If the link breaks, copy it into your browser.' if lng != 'es' else 'Si el enlace falla, cópialo en el navegador.'}\n"
        f"If you did not register, ignore this message. / Si no registraste cuenta, ignora este mensaje.\n"
    )
    subject = (
        "[Quiniela] Confirma tu correo"
        if lng == "es"
        else "[Quiniela] Confirm your email"
    )

    if mail_is_configured():
        sender = current_app.config.get("MAIL_DEFAULT_SENDER")
        msg = Message(subject=subject, recipients=[to_email], body=body, sender=sender)
        try:
            mail.send(msg)
        except Exception:
            current_app.logger.exception("Flask-Mail send failed for verification to %s", to_email)

    current_app.logger.info("Email verification URL for %s: %s", to_email, verify_url)

    return verify_url


def reset_password_absolute_url(token: str) -> str:
    path = url_for("auth.reset_password", token=token)
    base = (current_app.config.get("SITE_URL") or "").strip().rstrip("/")
    if base:
        return f"{base}{path}"
    try:
        return url_for("auth.reset_password", token=token, _external=True)
    except RuntimeError:
        return path


def send_password_reset_email(to_email: str, token: str, *, lang: str | None = None) -> str:
    """Send password reset mail; always return the link for logging (no SMTP crash)."""
    reset_url = reset_password_absolute_url(token)
    lng = (lang or "es").strip().lower()[:2]
    body = (
        f"{'Restablece tu contraseña:' if lng == 'es' else 'Reset your password:'}\n{reset_url}\n\n"
        f"{ 'El enlace caduca en 1 hora. / Expires in 1 hour.' if lng == 'es' else 'This link expires in 1 hour. / Caduca en 1 hora.'}\n\n"
        f"If you did not ask for this, ignore. / Si no lo pediste, ignora este mensaje.\n"
    )
    subject = "[Quiniela] Restablecer contraseña" if lng == "es" else "[Quiniela] Reset password"

    if mail_is_configured():
        sender = current_app.config.get("MAIL_DEFAULT_SENDER")
        msg = Message(subject=subject, recipients=[to_email], body=body, sender=sender)
        try:
            mail.send(msg)
        except Exception:
            current_app.logger.exception("Flask-Mail send failed for password reset to %s", to_email)

    current_app.logger.info("Password reset URL for %s: %s", to_email, reset_url)
    return reset_url
