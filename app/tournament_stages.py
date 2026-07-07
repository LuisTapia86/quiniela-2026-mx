"""User-facing tournament stage visibility (predictions UI only; DB keeps all matches)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Mapping

from sqlalchemy import and_, or_, select
from sqlalchemy.sql import ColumnElement

from app.datetime_fmt import kickoff_as_local, server_now_local
from app.models import Match

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


# Placeholder used for knockout slots whose team is not decided yet.
UNDEFINED_TEAM_PLACEHOLDER = "A definir"


def both_teams_known(match: Match) -> bool:
    """True when both teams are real (not the 'A definir' placeholder / empty)."""
    home = (match.home_team or "").strip()
    away = (match.away_team or "").strip()
    if not home or not away:
        return False
    return home != UNDEFINED_TEAM_PLACEHOLDER and away != UNDEFINED_TEAM_PLACEHOLDER


def manual_unlock_match_numbers(config: Mapping[str, Any]) -> frozenset[int]:
    raw = config.get("MANUAL_UNLOCK_PREDICTION_MATCH_NUMBERS") or ()
    return frozenset(int(n) for n in raw)


def manual_lock_match_numbers(config: Mapping[str, Any]) -> frozenset[int]:
    raw = config.get("MANUAL_LOCK_PREDICTION_MATCH_NUMBERS") or ()
    return frozenset(int(n) for n in raw)


def match_prediction_lock_at(match: Match):
    """Local (Mexico City) moment when predictions close (kickoff minus 1 hour)."""
    kickoff = kickoff_as_local(match.kickoff_at)
    if kickoff is None:
        return None
    return kickoff - PREDICTION_LOCK_BEFORE_KICKOFF


def is_match_auto_locked(match: Match) -> bool:
    lock_at = match_prediction_lock_at(match)
    if lock_at is None:
        return False
    return server_now_local() >= lock_at


def editable_matches_where(
    config: Mapping[str, Any],
    *,
    global_locked: bool = False,
) -> ColumnElement[bool]:
    """SQL filter: visible-stage matches still open (naive kickoff_at = Mexico local)."""
    if global_locked:
        return Match.id.is_(None)  # type: ignore[return-value]
    cutoff = server_now_local().replace(tzinfo=None) + PREDICTION_LOCK_BEFORE_KICKOFF
    kickoff_open = or_(Match.kickoff_at.is_(None), Match.kickoff_at > cutoff)
    teams_known = and_(
        Match.home_team.is_not(None),
        Match.away_team.is_not(None),
        Match.home_team != UNDEFINED_TEAM_PLACEHOLDER,
        Match.away_team != UNDEFINED_TEAM_PLACEHOLDER,
    )
    clause: ColumnElement[bool] = and_(visible_matches_where(config), kickoff_open, teams_known)
    locked_nums = manual_lock_match_numbers(config)
    if locked_nums:
        clause = and_(clause, Match.match_number.not_in(locked_nums))
    return clause


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
    if match.match_number in manual_lock_match_numbers(config):
        return False
    if not both_teams_known(match):
        return False
    if match.match_number in manual_unlock_match_numbers(config):
        return True
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
