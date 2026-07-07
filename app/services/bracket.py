"""Automatic knockout bracket advancement (deterministic, additive).

After an admin saves official results, winners (and semifinal losers) are pushed
into the home/away slots of the next scheduled match. Only Match.home_team and
Match.away_team are ever modified — results and predictions are never touched.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app import db
from app.models import Match

# Placeholder written back when a source match is not yet decided.
UNDECIDED_PLACEHOLDER = "A definir"

# (source_match, destination_match, destination_slot, outcome)
# outcome: "winner" or "loser". Order is bracket order (ascending source).
BRACKET_RULES: list[tuple[int, int, str, str]] = [
    # Round of 16 winners -> Quarterfinals (97–100)
    (89, 97, "home", "winner"),
    (90, 97, "away", "winner"),
    (93, 98, "home", "winner"),
    (94, 98, "away", "winner"),
    (91, 99, "home", "winner"),
    (92, 99, "away", "winner"),
    (95, 100, "home", "winner"),
    (96, 100, "away", "winner"),
    # Quarterfinal winners -> Semifinals (101–102)
    (97, 101, "home", "winner"),
    (98, 101, "away", "winner"),
    (99, 102, "home", "winner"),
    (100, 102, "away", "winner"),
    # Semifinal winners -> Final (104); losers -> Third place (103)
    (101, 104, "home", "winner"),
    (102, 104, "away", "winner"),
    (101, 103, "home", "loser"),
    (102, 103, "away", "loser"),
]


def decided_teams(match: Match | None) -> tuple[str | None, str | None]:
    """Return (winner, loser) team names for a finished match, else (None, None).

    Regular time decides the outcome; on a tie the penalty winner is used.
    """
    if match is None:
        return None, None
    result = match.result
    if result is None:
        return None, None
    home_score = result.home_score
    away_score = result.away_score
    if home_score is None or away_score is None:
        return None, None
    home = (match.home_team or "").strip()
    away = (match.away_team or "").strip()
    if not home or not away or home == UNDECIDED_PLACEHOLDER or away == UNDECIDED_PLACEHOLDER:
        return None, None
    if home_score > away_score:
        return match.home_team, match.away_team
    if away_score > home_score:
        return match.away_team, match.home_team
    penalty_winner = (result.penalty_winner or "").strip()
    if penalty_winner == home:
        return match.home_team, match.away_team
    if penalty_winner == away:
        return match.away_team, match.home_team
    return None, None


def advance_bracket() -> int:
    """Recompute knockout destination teams from current results. Returns #slots changed.

    Idempotent and deterministic: destinations are fully derived from source
    results, so re-running (e.g. after a result is edited) corrects downstream
    matches automatically. Only home_team/away_team are written.
    """
    matches = {
        m.match_number: m
        for m in db.session.scalars(select(Match).options(joinedload(Match.result)))
    }
    changed = 0
    for source_num, dest_num, slot, outcome in BRACKET_RULES:
        dest = matches.get(dest_num)
        if dest is None:
            continue
        winner, loser = decided_teams(matches.get(source_num))
        team = winner if outcome == "winner" else loser
        new_value = team or UNDECIDED_PLACEHOLDER
        field = f"{slot}_team"
        if getattr(dest, field) != new_value:
            setattr(dest, field, new_value)
            changed += 1
    return changed
