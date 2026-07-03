"""User-facing tournament stage visibility (predictions UI only; DB keeps all matches)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Mapping

from sqlalchemy import and_, or_, select
from sqlalchemy.sql import ColumnElement

from app.datetime_fmt import _as_utc
from app.models import Match, utcnow

PREDICTION_LOCK_BEFORE_KICKOFF = timedelta(hours=1)

# Friendly config labels → stage values stored in Match.stage (WC2026 CSV).
_STAGE_CANONICAL: dict[str, str] = {
    "group stage": "Fase de grupos",
    "group": "Fase de grupos",
    "fase de grupos": "Fase de grupos",
    "round of 32": "Eliminatoria de 32",
    "eliminatoria de 32": "Eliminatoria de 32",
    "round of 16": "Octavos de final",
    "octavos de final": "Octavos de final",
    "quarterfinals": "Cuartos de final",
    "quarter-finals": "Cuartos de final",
    "cuartos de final": "Cuartos de final",
    "semifinals": "Semifinales",
    "semifinales": "Semifinales",
    "third place match": "Eliminatoria por el tercer lugar",
    "third place": "Eliminatoria por el tercer lugar",
    "eliminatoria por el tercer lugar": "Eliminatoria por el tercer lugar",
    "final": "Final",
}


def resolve_visible_db_stages(config: Mapping[str, Any]) -> tuple[str, ...]:
    """Return DB stage strings currently visible for user predictions."""
    raw = config.get("VISIBLE_PREDICTION_STAGES") or ("Group Stage",)
    resolved: list[str] = []
    seen: set[str] = set()
    for label in raw:
        key = (label or "").strip().lower()
        db_stage = _STAGE_CANONICAL.get(key, (label or "").strip())
        if db_stage and db_stage not in seen:
            seen.add(db_stage)
            resolved.append(db_stage)
    return tuple(resolved)


def match_stage_is_visible(stage: str | None, config: Mapping[str, Any]) -> bool:
    value = (stage or "").strip()
    if not value:
        return False
    visible = {s.lower() for s in resolve_visible_db_stages(config)}
    canonical = _STAGE_CANONICAL.get(value.lower(), value)
    return canonical.lower() in visible


def visible_matches_where(config: Mapping[str, Any]) -> ColumnElement[bool]:
    """SQLAlchemy filter: Match rows in currently visible stages."""
    stages = resolve_visible_db_stages(config)
    if not stages:
        return Match.id.is_(None)  # type: ignore[return-value]
    return or_(*[Match.stage == stage for stage in stages])


def matches_chronological_order():
    """Standard match list order: kickoff time, then match_number tie-break."""
    return (
        Match.kickoff_at.asc().nulls_last(),
        Match.match_number.asc(),
        Match.id.asc(),
    )


def select_visible_matches():
    """Base select(Match) scoped to visible prediction stages."""
    from flask import current_app

    stmt = select(Match).where(visible_matches_where(current_app.config))
    return stmt.order_by(*matches_chronological_order())


def count_visible_matches(config: Mapping[str, Any]) -> int:
    from sqlalchemy import func

    from app import db

    stages = resolve_visible_db_stages(config)
    if not stages:
        return 0
    return (
        db.session.scalar(
            select(func.count())
            .select_from(Match)
            .where(visible_matches_where(config)),
        )
        or 0
    )


def match_prediction_lock_at(match: Match):
    """UTC-aware moment when predictions close (kickoff minus 1 hour)."""
    if match.kickoff_at is None:
        return None
    return _as_utc(match.kickoff_at) - PREDICTION_LOCK_BEFORE_KICKOFF


def is_match_auto_locked(match: Match) -> bool:
    lock_at = match_prediction_lock_at(match)
    if lock_at is None:
        return False
    return utcnow() >= lock_at


def editable_matches_where(
    config: Mapping[str, Any],
    *,
    global_locked: bool = False,
) -> ColumnElement[bool]:
    """SQL filter: visible-stage matches still open for predictions."""
    if global_locked:
        return Match.id.is_(None)  # type: ignore[return-value]
    cutoff = utcnow().replace(tzinfo=None) + PREDICTION_LOCK_BEFORE_KICKOFF
    kickoff_open = or_(Match.kickoff_at.is_(None), Match.kickoff_at > cutoff)
    return and_(visible_matches_where(config), kickoff_open)


def is_match_editable(
    match: Match,
    config: Mapping[str, Any],
    *,
    global_locked: bool,
) -> bool:
    if global_locked:
        return False
    if not match_stage_is_visible(match.stage, config):
        return False
    return not is_match_auto_locked(match)


def count_editable_matches(config: Mapping[str, Any], *, global_locked: bool = False) -> int:
    from sqlalchemy import func

    from app import db

    if global_locked:
        return 0
    return (
        db.session.scalar(
            select(func.count())
            .select_from(Match)
            .where(editable_matches_where(config, global_locked=global_locked)),
        )
        or 0
    )


def is_knockout_stage(stage: str | None) -> bool:
    """True for elimination matches (not group stage)."""
    value = (stage or "").strip().lower()
    if not value:
        return False
    return "grupo" not in value and "group" not in value
