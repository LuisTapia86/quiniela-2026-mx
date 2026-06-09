"""Display helpers: UTC datetimes from the DB → America/Mexico_City for UI."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MEXICO_TZ = ZoneInfo("America/Mexico_City")

_MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
_MONTHS_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_mexico_city(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return _as_utc(dt).astimezone(MEXICO_TZ)


def _format_time_ampm(hour: int, minute: int) -> str:
    h12 = hour % 12 or 12
    suffix = "a.m." if hour < 12 else "p.m."
    return f"{h12}:{minute:02d} {suffix}"


def format_mexico_local(dt: datetime | None, lang: str = "es") -> str:
    """Format a UTC (or naive UTC) datetime for Mexico local display."""
    local = to_mexico_city(dt)
    if local is None:
        return "—"
    months = _MONTHS_ES if lang == "es" else _MONTHS_EN
    month = months[local.month - 1]
    time_part = _format_time_ampm(local.hour, local.minute)
    if lang == "es":
        return f"{local.day} {month} {local.year}, {time_part}"
    return f"{month} {local.day}, {local.year}, {time_part}"
