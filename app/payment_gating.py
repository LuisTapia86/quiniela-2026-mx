from __future__ import annotations

from typing import Any, Mapping

_PAYMENT_KEYS = ("PAYMENT_BENEFICIARY_NAME", "PAYMENT_BANK", "PAYMENT_CLABE")


def is_payment_banking_configured(config: Mapping[str, Any]) -> bool:
    """True when all transfer fields are set and are not TODO placeholders."""
    for k in _PAYMENT_KEYS:
        v = (config.get(k) or "").strip()
        if not v:
            return False
        if "TODO" in v.upper():
            return False
    return True
