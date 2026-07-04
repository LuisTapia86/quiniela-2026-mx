"""Rules for when competitor predictions are visible to other logged-in users."""

from __future__ import annotations

from flask import current_app

from app.datetime_fmt import kickoff_as_local, server_now_local
from app.models import Match, TournamentState
from app.tournament_stages import is_knockout_stage, is_match_editable


def global_predictions_locked() -> bool:
    return TournamentState.get_singleton().predictions_locked


def competitor_prediction_visible(match: Match, *, global_locked: bool | None = None) -> bool:
    """Group stage: always visible. Knockout: visible when locked or match has started."""
    if global_locked is None:
        global_locked = global_predictions_locked()
    if not is_knockout_stage(match.stage):
        return True
    if not is_match_editable(match, current_app.config, global_locked=global_locked):
        return True
    if match.kickoff_at is not None and server_now_local() >= kickoff_as_local(match.kickoff_at):
        return True
    return False


def mask_prediction_rows_for_competitors(
    rows: list[dict],
    *,
    global_locked: bool | None = None,
) -> list[dict]:
    from app.translations import tr

    if global_locked is None:
        global_locked = global_predictions_locked()
    masked: list[dict] = []
    for row in rows:
        match: Match = row["match"]
        if competitor_prediction_visible(match, global_locked=global_locked):
            masked.append(row)
            continue
        masked.append(
            {
                **row,
                "competitor_hidden": True,
                "has_prediction": False,
                "home_score": None,
                "away_score": None,
                "penalty_winner": None,
                "prediction_text": tr("competitors.prediction_hidden"),
                "points_earned": None,
                "breakdown": None,
            }
        )
    return masked
