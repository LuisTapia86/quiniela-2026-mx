"""Historical tournament statistics computed read-only from predictions + results."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app import db
from app.models import Entry, EntryStatus, Match, Payment, PaymentStatus, Prediction, User
from app.services.scoring import calculate_prediction_breakdown, get_outcome
from app.tournament_stages import is_knockout_stage


@dataclass(frozen=True)
class StatLeader:
    display_name: str
    value: float | int
    value_label: str
    detail: str = ""


@dataclass(frozen=True)
class RoundStat:
    stage_label: str
    average_points: float
    predictions_count: int
    exact_count: int


def _public_name(user: User, entry: Entry) -> str:
    name = (user.display_name or "").strip()
    if name:
        return name
    alias = (entry.alias or "").strip()
    if alias:
        return alias
    return f"Entrada #{entry.entry_number or entry.id}"


def _stage_label(stage: str | None) -> str:
    raw = (stage or "").strip()
    return raw or "Sin etapa"


def _eligible_entries() -> list[tuple[Entry, User]]:
    rows = db.session.execute(
        select(Entry, User)
        .join(Payment, Payment.entry_id == Entry.id)
        .join(User, Entry.user_id == User.id)
        .where(
            Entry.status == EntryStatus.ACTIVE,
            Payment.status == PaymentStatus.APPROVED,
        )
        .order_by(Entry.total_points.desc(), Entry.id.asc()),
    ).all()
    return [(e, u) for e, u in rows]


def _load_scored_predictions(entry_ids: list[int]) -> list[Prediction]:
    if not entry_ids:
        return []
    return list(
        db.session.scalars(
            select(Prediction)
            .options(joinedload(Prediction.match).joinedload(Match.result))
            .where(Prediction.entry_id.in_(entry_ids)),
        ),
    )


def compute_tournament_statistics() -> dict[str, Any]:
    """Pure read aggregation — does not write or mutate prediction/score rows."""
    eligible = _eligible_entries()
    entry_meta = {e.id: (e, u) for e, u in eligible}
    entry_ids = list(entry_meta.keys())
    preds = _load_scored_predictions(entry_ids)

    per_entry: dict[int, dict[str, Any]] = {
        eid: {
            "exact": 0,
            "correct_winner": 0,  # correct non-draw outcome (home/away winner)
            "correct_outcome": 0,  # any correct 1X2 including draws
            "penalty": 0,
            "group_points": 0,
            "knockout_points": 0,
            "scored_matches": 0,
            "points_from_scored": 0,
        }
        for eid in entry_ids
    }

    total_predictions = 0
    total_exact = 0
    total_scored = 0
    total_correct_outcome = 0

    # stage_key -> {points_sum, count, exact}
    stage_agg: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"points_sum": 0, "count": 0, "exact": 0},
    )

    for pred in preds:
        total_predictions += 1
        match = pred.match
        if match is None or match.result is None:
            continue
        res = match.result
        knockout = is_knockout_stage(match.stage)
        bd = calculate_prediction_breakdown(
            pred.home_goals,
            pred.away_goals,
            res.home_score,
            res.away_score,
            pred_penalty_winner=pred.penalty_winner,
            result_penalty_winner=res.penalty_winner,
            knockout=knockout,
        )
        eid = pred.entry_id
        if eid not in per_entry:
            continue
        bucket = per_entry[eid]
        bucket["scored_matches"] += 1
        pts = int(bd["total"])
        bucket["points_from_scored"] += pts
        total_scored += 1

        if bd["exact_score"]:
            bucket["exact"] += 1
            total_exact += 1
        if bd["correct_outcome"]:
            bucket["correct_outcome"] += 1
            total_correct_outcome += 1
            real = get_outcome(res.home_score, res.away_score)
            if real != "draw":
                bucket["correct_winner"] += 1
        if bd.get("correct_penalty_winner"):
            bucket["penalty"] += 1

        if knockout:
            bucket["knockout_points"] += pts
        else:
            bucket["group_points"] += pts

        stage = _stage_label(match.stage)
        stage_agg[stage]["points_sum"] = int(stage_agg[stage]["points_sum"]) + pts
        stage_agg[stage]["count"] = int(stage_agg[stage]["count"]) + 1
        if bd["exact_score"]:
            stage_agg[stage]["exact"] = int(stage_agg[stage]["exact"]) + 1

    def leader_by(
        key: str,
        *,
        as_percent: bool = False,
        prefer_total_points_tiebreak: bool = False,
    ) -> StatLeader | None:
        best_eid = None
        best_val: float | None = None
        for eid, stats in per_entry.items():
            if key == "accuracy":
                scored = stats["scored_matches"]
                if scored <= 0:
                    continue
                val = (stats["correct_outcome"] / scored) * 100.0
            elif key == "total_points":
                val = float(entry_meta[eid][0].total_points or 0)
            else:
                val = float(stats[key])
            if best_val is None or val > best_val + 1e-9:
                best_val = val
                best_eid = eid
            elif best_val is not None and abs(val - best_val) < 1e-9 and prefer_total_points_tiebreak:
                if (entry_meta[eid][0].total_points or 0) > (entry_meta[best_eid][0].total_points or 0):
                    best_eid = eid
        if best_eid is None or best_val is None:
            return None
        entry, user = entry_meta[best_eid]
        name = _public_name(user, entry)
        if as_percent:
            label = f"{best_val:.1f}%"
        elif key == "total_points":
            label = f"{int(best_val)} pts"
        else:
            label = str(int(best_val))
        return StatLeader(display_name=name, value=best_val, value_label=label)

    accuracies: list[float] = []
    for stats in per_entry.values():
        scored = stats["scored_matches"]
        if scored > 0:
            accuracies.append((stats["correct_outcome"] / scored) * 100.0)
    avg_accuracy = (sum(accuracies) / len(accuracies)) if accuracies else 0.0
    highest_accuracy = max(accuracies) if accuracies else 0.0

    round_stats: list[RoundStat] = []
    for stage, agg in stage_agg.items():
        count = int(agg["count"])
        if count <= 0:
            continue
        avg = float(agg["points_sum"]) / count
        round_stats.append(
            RoundStat(
                stage_label=stage,
                average_points=avg,
                predictions_count=count,
                exact_count=int(agg["exact"]),
            ),
        )
    round_stats.sort(key=lambda r: r.average_points, reverse=True)
    best_round = round_stats[0] if round_stats else None
    worst_round = round_stats[-1] if round_stats else None

    most_accurate = leader_by("accuracy", as_percent=True)
    highest_score = leader_by("total_points")
    most_exact = leader_by("exact")
    most_winners = leader_by("correct_winner")
    most_penalties = leader_by("penalty")
    best_group = leader_by("group_points")
    best_knockout = leader_by("knockout_points")

    return {
        "most_accurate": most_accurate,
        "highest_score": highest_score,
        "most_exact": most_exact,
        "most_correct_winners": most_winners,
        "most_penalties": most_penalties,
        "best_group": best_group,
        "best_knockout": best_knockout,
        "best_round": best_round,
        "worst_round": worst_round,
        "highest_accuracy": highest_accuracy,
        "average_accuracy": avg_accuracy,
        "total_predictions": total_predictions,
        "total_exact": total_exact,
        "total_scored_predictions": total_scored,
        "total_correct_outcomes": total_correct_outcome,
        "eligible_entries": len(entry_ids),
        "has_data": bool(entry_ids) and total_predictions > 0,
    }
