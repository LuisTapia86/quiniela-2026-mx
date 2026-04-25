from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app import db
from app.models import Entry, Match, Prediction, Result


def get_outcome(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "home"
    if away_score > home_score:
        return "away"
    return "draw"


def calculate_prediction_points(
    pred_home: int, pred_away: int, result_home: int, result_away: int
) -> int:
    if pred_home == result_home and pred_away == result_away:
        return 6
    total = 0
    if get_outcome(pred_home, pred_away) == get_outcome(result_home, result_away):
        total += 3
    if (pred_home - pred_away) == (result_home - result_away):
        total += 1
    return total


def recalculate_entry_points(entry_id: int) -> int:
    entry = db.session.get(Entry, entry_id)
    if entry is None:
        return 0
    preds = list(
        db.session.scalars(
            select(Prediction)
            .options(joinedload(Prediction.match).joinedload(Match.result))
            .where(Prediction.entry_id == entry_id)
        )
    )
    total = 0
    for p in preds:
        res: Result | None = p.match.result if p.match is not None else None
        if res is None:
            p.points_earned = 0
        else:
            pts = calculate_prediction_points(
                p.home_goals, p.away_goals, res.home_score, res.away_score
            )
            p.points_earned = pts
            total += pts
    entry.total_points = total
    return total


def recalculate_all_points() -> None:
    eids = db.session.scalars(select(Entry.id)).all()
    for eid in eids:
        recalculate_entry_points(int(eid))
