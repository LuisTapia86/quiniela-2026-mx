from __future__ import annotations

import os
from html import escape
from typing import NamedTuple

import requests
from flask import current_app, url_for

RESEND_API_ENDPOINT = "https://api.resend.com/emails"


class EmailSendResult(NamedTuple):
    """Returned by verification and password-reset helpers for routing/flash UX."""

    url: str
    delivered: bool  # True when Resend accepted the message (2xx).


def transactional_email_configured() -> bool:
    """Transactional mail uses Resend over HTTPS — requires API key + from address."""
    key = (current_app.config.get("RESEND_API_KEY") or "").strip()
    sender = (current_app.config.get("MAIL_DEFAULT_SENDER") or "").strip()
    return bool(key and sender)


def _production_env() -> bool:
    return (
        os.environ.get("FLASK_ENV") or os.environ.get("APP_ENV") or ""
    ).strip().lower() == "production"


def send_email_via_resend(to_email: str, subject: str, html_body: str) -> bool:
    """POST to Resend HTTP API — no Flask-Mail / SMTP."""
    api_key = (current_app.config.get("RESEND_API_KEY") or "").strip()
    sender = (current_app.config.get("MAIL_DEFAULT_SENDER") or "").strip()

    if not api_key:
        current_app.logger.error("RESEND_API_KEY missing")
        return False

    if not sender:
        current_app.logger.error("MAIL_DEFAULT_SENDER missing")
        return False

    try:
        response = requests.post(
            RESEND_API_ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": sender,
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            },
            timeout=10,
        )

        if response.status_code >= 400:
            current_app.logger.error(f"Resend error: {response.text}")
            return False

        return True

    except Exception as exc:  # pragma: no cover - network variability
        current_app.logger.error(f"Resend exception: {exc}")
        return False


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


def send_verification_email(
    to_email: str,
    token: str,
    *,
    lang: str | None = None,
) -> EmailSendResult:
    verify_url = verification_absolute_url(token)
    lng = (lang or "es").strip().lower()[:2]

    plain_lines = (
        ("Verifica tu correo:", "Si el enlace falla, cópialo en el navegador.", "Si no registraste cuenta, ignora este mensaje.")
        if lng == "es"
        else ("Verify your email:", "If the link breaks, paste it into your browser.", "If you did not register, ignore this message.")
    )

    subject = "[Quiniela] Confirma tu correo" if lng == "es" else "[Quiniela] Confirm your email"
    safe_link = escape(verify_url)

    html_body = (
        f"<p>{plain_lines[0]}</p>"
        f"<p><a href=\"{safe_link}\">{safe_link}</a></p>"
        f"<p>{plain_lines[1]}</p>"
        f"<p>{plain_lines[2]}</p>"
    )

    delivered = False
    if transactional_email_configured():
        delivered = send_email_via_resend(to_email, subject, html_body)
    elif _production_env():
        current_app.logger.error(
            "RESEND_API_KEY or MAIL_DEFAULT_SENDER missing; skipping verification send to %s",
            to_email,
        )

    current_app.logger.info("Email verification link for %s: %s", to_email, verify_url)
    return EmailSendResult(verify_url, delivered)


def reset_password_absolute_url(token: str) -> str:
    path = url_for("auth.reset_password", token=token)
    base = (current_app.config.get("SITE_URL") or "").strip().rstrip("/")
    if base:
        return f"{base}{path}"
    try:
        return url_for("auth.reset_password", token=token, _external=True)
    except RuntimeError:
        return path


def send_password_reset_email(
    to_email: str,
    token: str,
    *,
    lang: str | None = None,
) -> EmailSendResult:
    reset_url = reset_password_absolute_url(token)
    lng = (lang or "es").strip().lower()[:2]

    expiry = (
        "El enlace caduca en 1 hora. Si no pediste este correo, ignora este mensaje."
        if lng == "es"
        else "This link expires in 1 hour. If you did not request this, ignore this message."
    )
    btn = (
        "Restablecer contraseña" if lng == "es" else "Reset password"
    )
    intro = (
        "Restablece tu contraseña usando el enlace de abajo."
        if lng == "es"
        else "Reset your password using the link below."
    )

    subject = "[Quiniela] Restablecer contraseña" if lng == "es" else "[Quiniela] Reset password"
    safe_link = escape(reset_url)

    html_body = (
        f"<p>{intro}</p>"
        f"<p><a href=\"{safe_link}\">{escape(btn)}</a></p>"
        f"<p>{escape(expiry)}</p>"
    )

    delivered = False
    if transactional_email_configured():
        delivered = send_email_via_resend(to_email, subject, html_body)
    elif _production_env():
        current_app.logger.error(
            "RESEND_API_KEY or MAIL_DEFAULT_SENDER missing; skipping password reset send to %s",
            to_email,
        )

    current_app.logger.info("Password reset link for %s: %s", to_email, reset_url)
    return EmailSendResult(reset_url, delivered)


# Deprecated name — Resend replaces SMTP-only checks.
mail_is_configured = transactional_email_configured
