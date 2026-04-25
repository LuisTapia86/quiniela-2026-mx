from __future__ import annotations

from typing import Any, Mapping


def entry_financials(approved_count: int, config: Mapping[str, Any]) -> dict[str, int]:
    """Gross, admin cut, net prize pool, and TOP 3 estimates in MXN (integer division)."""
    entry_fee = int(config.get("ENTRY_FEE_MXN", 1000))
    admin_pct = int(config.get("ADMIN_FEE_PERCENT", 5))
    p1 = int(config.get("PRIZE_TOP1_PERCENT", 60))
    p2 = int(config.get("PRIZE_TOP2_PERCENT", 25))
    p3 = int(config.get("PRIZE_TOP3_PERCENT", 15))
    gross = approved_count * entry_fee
    admin_amt = (gross * admin_pct) // 100
    pool = gross - admin_amt
    return {
        "gross_collected": gross,
        "admin_fee_amount": admin_amt,
        "prize_pool": pool,
        "estimate_1st": (pool * p1) // 100,
        "estimate_2nd": (pool * p2) // 100,
        "estimate_3rd": (pool * p3) // 100,
    }
