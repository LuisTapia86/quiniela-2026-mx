"""Local-only tooling flags — destructive admin shortcuts must remain off in production."""

from __future__ import annotations

import os


def flask_debug_truthy() -> bool:
    return (os.environ.get("FLASK_DEBUG") or "").strip().lower() in {"1", "true", "yes", "on"}
