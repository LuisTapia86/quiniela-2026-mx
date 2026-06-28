"""User-facing tournament stage visibility (predictions UI only; DB keeps all matches)."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import or_, select
from sqlalchemy.sql import ColumnElement

from app.models import Match

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


def select_visible_matches(*, order_by_kickoff: bool = True):
    """Base select(Match) scoped to visible prediction stages."""
    from flask import current_app

    stmt = select(Match).where(visible_matches_where(current_app.config))
    if order_by_kickoff:
        stmt = stmt.order_by(
            Match.kickoff_at.asc().nulls_last(),
            Match.match_number.asc(),
            Match.id.asc(),
        )
    else:
        stmt = stmt.order_by(Match.match_number.asc(), Match.id.asc())
    return stmt


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


def editable_match_numbers(config: Mapping[str, Any]) -> frozenset[int]:
    raw = config.get("EDITABLE_PREDICTION_MATCH_NUMBERS")
    if raw:
        return frozenset(int(n) for n in raw)
    return frozenset(range(73, 89))


def is_match_editable(
    match: Match,
    config: Mapping[str, Any],
    *,
    global_locked: bool,
) -> bool:
    if global_locked:
        return False
    return match.match_number in editable_match_numbers(config)


def editable_matches_where(config: Mapping[str, Any]) -> ColumnElement[bool]:
    nums = editable_match_numbers(config)
    if not nums:
        return Match.id.is_(None)  # type: ignore[return-value]
    return Match.match_number.in_(nums)


def is_knockout_stage(stage: str | None) -> bool:
    """True for elimination matches (not group stage)."""
    value = (stage or "").strip().lower()
    if not value:
        return False
    return "grupo" not in value and "group" not in value


def count_editable_matches(config: Mapping[str, Any]) -> int:
    from sqlalchemy import func

    from app import db

    nums = editable_match_numbers(config)
    if not nums:
        return 0
    return (
        db.session.scalar(
            select(func.count())
            .select_from(Match)
            .where(editable_matches_where(config)),
        )
        or 0
    )
