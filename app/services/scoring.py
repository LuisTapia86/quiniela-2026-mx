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


def calculate_prediction_breakdown(
    pred_home: int, pred_away: int, result_home: int, result_away: int
) -> dict:
    exact = pred_home == result_home and pred_away == result_away
    pred_outcome = get_outcome(pred_home, pred_away)
    real_outcome = get_outcome(result_home, result_away)
    correct_outcome = pred_outcome == real_outcome
    correct_goal_diff = (pred_home - pred_away) == (result_home - result_away)

    reasons: list[str] = []
    reason_codes: list[str] = []

    if exact:
        reasons.append("Marcador exacto: +5")
        reasons.append("Diferencia de goles correcta: +1")
        reason_codes.extend(["exact_score", "correct_goal_difference"])
        total = 6
    else:
        total = 0
        if correct_outcome:
            if real_outcome == "draw":
                reasons.append("Empate correcto: +3")
                reason_codes.append("correct_draw")
            else:
                reasons.append("Ganador correcto: +3")
                reason_codes.append("correct_winner")
            total += 3
        if correct_goal_diff:
            reasons.append("Diferencia de goles correcta: +1")
            reason_codes.append("correct_goal_difference")
            total += 1

    return {
        "total": total,
        "exact_score": exact,
        "correct_outcome": correct_outcome,
        "correct_goal_difference": correct_goal_diff,
        "reasons": reasons,
        "reason_codes": reason_codes,
    }


def summarize_prediction_audit(rows: list[dict]) -> dict:
    """Aggregate per-match breakdown rows for admin audit (uses existing row data only)."""
    total_points = 0
    matches_with_result = 0
    exact_count = 0
    outcome_correct_count = 0
    goal_diff_count = 0
    zero_points_count = 0

    for row in rows:
        if row.get("result_pending") or not row.get("has_prediction"):
            continue
        matches_with_result += 1
        pts = row.get("points_earned")
        if pts is None:
            continue
        total_points += int(pts)
        bd = row.get("breakdown")
        if not bd:
            if pts == 0:
                zero_points_count += 1
            continue
        if bd.get("exact_score"):
            exact_count += 1
        elif bd.get("correct_outcome"):
            outcome_correct_count += 1
        codes = bd.get("reason_codes") or []
        if "correct_goal_difference" in codes and not bd.get("exact_score"):
            goal_diff_count += 1
        if pts == 0:
            zero_points_count += 1

    return {
        "total_points": total_points,
        "matches_with_result": matches_with_result,
        "exact_count": exact_count,
        "outcome_correct_count": outcome_correct_count,
        "goal_diff_count": goal_diff_count,
        "zero_points_count": zero_points_count,
    }


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
