"""Helpers for tournament lifecycle (ACTIVE / FINISHED / ARCHIVED)."""
from __future__ import annotations

from app.models import TournamentState, TournamentStatus


def get_tournament_state() -> TournamentState:
    state = TournamentState.get_singleton()
    if state.ensure_closed_locks():
        from app import db

        db.session.commit()
    return state


def tournament_status() -> TournamentStatus:
    state = get_tournament_state()
    status = state.status
    if isinstance(status, TournamentStatus):
        return status
    raw = (str(status or "")).strip().upper()
    try:
        return TournamentStatus(raw)
    except ValueError:
        return TournamentStatus.FINISHED


def tournament_is_finished() -> bool:
    return get_tournament_state().is_finished


def tournament_is_writable() -> bool:
    return get_tournament_state().is_writable


def predictions_are_locked() -> bool:
    """Global prediction lock: explicit lock flag or closed tournament."""
    state = get_tournament_state()
    return bool(state.predictions_locked) or state.is_finished
