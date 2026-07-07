"""Automatic knockout bracket advancement (deterministic, additive).

After an admin saves official results, winners (and semifinal losers) are pushed
into the home/away slots of the next scheduled match. Only Match.home_team and
Match.away_team are ever modified — results and predictions are never touched.
"""

from __future__ import annotations

from sqlalchemy import select

from app import db
from app.models import Match, Result

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


def decided_teams(match: Match | None, result: Result | None) -> tuple[str | None, str | None]:
    """Return (winner, loser) team names for a finished match, else (None, None).

    Regular time decides the outcome; on a tie the penalty winner is used. The
    result is passed explicitly (read from a fresh Result query) rather than via
    match.result, so freshly-saved results are always seen even if the cached
    relationship on the Match instance is stale.
    """
    if match is None or result is None:
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
    """Advance decided winners/losers into their next match. Returns #slots changed.

    Deterministic and idempotent: a destination slot is only written when the
    source match is decided. If a source is undecided, the destination is left
    untouched — this preserves teams imported from the CSV and never regresses a
    real team back to a placeholder. Re-running after a result changes rewrites
    the affected downstream slots with the new winner. Only home_team/away_team
    are modified; results and predictions are never touched.
    """
    matches = {m.match_number: m for m in db.session.scalars(select(Match))}
    results_by_match_id = {r.match_id: r for r in db.session.scalars(select(Result))}
    changed = 0
    for source_num, dest_num, slot, outcome in BRACKET_RULES:
        dest = matches.get(dest_num)
        if dest is None:
            continue
        source = matches.get(source_num)
        result = results_by_match_id.get(source.id) if source is not None else None
        winner, loser = decided_teams(source, result)
        team = winner if outcome == "winner" else loser
        if not team:
            continue
        field = f"{slot}_team"
        if getattr(dest, field) != team:
            setattr(dest, field, team)
            changed += 1
    return changed
