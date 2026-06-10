from __future__ import annotations

import re

ENTRY_NAME_MIN = 3
ENTRY_NAME_MAX = 50

_DEFAULT_NAME_RE = re.compile(r"^Entrada #\d+$", re.IGNORECASE)


def editable_entry_name(entry) -> str:
    alias = (getattr(entry, "alias", None) or "").strip()
    if alias:
        return alias
    name = (getattr(entry, "name", None) or "").strip()
    if not name or name == "Mi quiniela" or _DEFAULT_NAME_RE.match(name):
        return ""
    return name


def validate_entry_display_name(raw: str | None) -> tuple[bool, str]:
    from app.translations import tr

    value = (raw or "").strip()
    if not value:
        return False, tr("flash.entry.rename_empty")
    if len(value) < ENTRY_NAME_MIN:
        return False, tr("flash.entry.rename_too_short", min=ENTRY_NAME_MIN)
    if len(value) > ENTRY_NAME_MAX:
        return False, tr("flash.entry.rename_too_long", max=ENTRY_NAME_MAX)
    return True, value
