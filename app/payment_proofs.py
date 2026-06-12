from __future__ import annotations

import mimetypes
import secrets
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.models import Entry, Payment, PaymentStatus


class PaymentProofError(Exception):
    def __init__(self, message_key: str, **format_kwargs: object) -> None:
        self.message_key = message_key
        self.format_kwargs = format_kwargs


def payment_proofs_folder() -> Path:
    return Path(current_app.config["PAYMENT_PROOFS_FOLDER"]).resolve()


def resolve_payment_proof_path(stored_path: str | None) -> Path | None:
    """Return absolute path to a stored proof file, or None if invalid / missing."""
    if not stored_path or not str(stored_path).strip():
        return None
    safe_name = Path(stored_path).name
    if not safe_name or safe_name in {".", ".."}:
        return None
    base = payment_proofs_folder()
    try:
        target = (base / safe_name).resolve()
        target.relative_to(base)
    except ValueError:
        return None
    if not target.is_file():
        return None
    return target


def payment_proof_mimetype(stored_path: str) -> str | None:
    ext = Path(stored_path).suffix.lower()
    explicit = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }
    if ext in explicit:
        return explicit[ext]
    guessed, _ = mimetypes.guess_type(stored_path)
    return guessed


def entry_fee_mxn() -> int:
    return int(current_app.config.get("ENTRY_FEE_MXN", 200))


def create_pending_payment(entry: Entry, user_id: int) -> Payment:
    return Payment(
        user_id=user_id,
        entry_id=entry.id,
        amount_mxn=entry_fee_mxn(),
        status=PaymentStatus.PENDING,
    )


def save_payment_proof(
    entry: Entry,
    payment: Payment | None,
    uploaded_file: FileStorage | None,
    *,
    user_id: int,
) -> tuple[Payment, bool]:
    """Store proof in PAYMENT_PROOFS_FOLDER and update payment — same rules as user upload.

    Returns (payment, created) where created is True if a new Payment row was built.
    """
    if (
        uploaded_file is None
        or uploaded_file.filename is None
        or uploaded_file.filename.strip() == ""
    ):
        raise PaymentProofError("flash.payment.select_file")

    raw_name = secure_filename(uploaded_file.filename)
    if not raw_name or "." not in raw_name:
        raise PaymentProofError("flash.payment.invalid_name")

    ext = raw_name.rsplit(".", 1)[-1].lower()
    allowed = current_app.config.get("ALLOWED_PAYMENT_EXTENSIONS", frozenset())
    if ext not in allowed:
        raise PaymentProofError(
            "flash.payment.invalid_format",
            allowed=", ".join(sorted(allowed)),
        )

    try:
        uploaded_file.stream.seek(0, 2)
        size_bytes = int(uploaded_file.stream.tell())
        uploaded_file.stream.seek(0)
    except Exception:
        size_bytes = 0

    max_bytes = int(current_app.config.get("MAX_CONTENT_LENGTH", 5 * 1024 * 1024))
    if size_bytes > 0 and size_bytes > max_bytes:
        raise PaymentProofError(
            "flash.payment.file_too_large",
            max_mb=max(1, max_bytes // (1024 * 1024)),
        )

    store_name = f"{entry.id}_{secrets.token_hex(6)}.{ext}"
    dest_dir = payment_proofs_folder()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / store_name

    if payment and payment.proof_stored_path:
        old = dest_dir / payment.proof_stored_path
        if old != dest_path and old.is_file():
            try:
                old.unlink()
            except OSError:
                pass

    uploaded_file.save(str(dest_path))

    created = payment is None
    if created:
        payment = create_pending_payment(entry, user_id)
        payment.proof_stored_path = store_name
    else:
        assert payment is not None
        payment.proof_stored_path = store_name
        payment.status = PaymentStatus.PENDING
        payment.amount_mxn = entry_fee_mxn()

    return payment, created
