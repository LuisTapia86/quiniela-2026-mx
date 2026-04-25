from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import db
from app.models import Match


def _group_round_robin_matches(group_teams: list[str]) -> list[tuple[str, str]]:
    t1, t2, t3, t4 = group_teams
    return [
        (t1, t2),
        (t3, t4),
        (t1, t3),
        (t2, t4),
        (t1, t4),
        (t2, t3),
    ]


def build_world_cup_2026_matches() -> list[tuple[int, str, str, str, datetime]]:
    teams = [f"Team {i:02d}" for i in range(1, 49)]
    groups: dict[str, list[str]] = {}
    letters = "ABCDEFGHIJKL"
    idx = 0
    for letter in letters:
        groups[letter] = teams[idx : idx + 4]
        idx += 4

    kickoff = datetime(2026, 6, 11, 16, 0, tzinfo=timezone.utc)
    slot = timedelta(hours=4)
    match_no = 1
    out: list[tuple[int, str, str, str, datetime]] = []

    for letter in letters:
        for home, away in _group_round_robin_matches(groups[letter]):
            out.append((match_no, "Group", home, away, kickoff))
            match_no += 1
            kickoff += slot

    r32_pairs = [
        ("A1", "B3"), ("C1", "D3"), ("E1", "F3"), ("G1", "H3"),
        ("I1", "J3"), ("K1", "L3"), ("B1", "A3"), ("D1", "C3"),
        ("F1", "E3"), ("H1", "G3"), ("J1", "I3"), ("L1", "K3"),
        ("A2", "B2"), ("C2", "D2"), ("E2", "F2"), ("G2", "H2"),
    ]
    for home, away in r32_pairs:
        out.append((match_no, "Round of 32", home, away, kickoff))
        match_no += 1
        kickoff += slot

    for i in range(1, 9):
        out.append((match_no, "Round of 16", f"W{72 + ((i - 1) * 2) + 1}", f"W{72 + ((i - 1) * 2) + 2}", kickoff))
        match_no += 1
        kickoff += slot

    for i in range(1, 5):
        out.append((match_no, "Quarterfinals", f"W{88 + ((i - 1) * 2) + 1}", f"W{88 + ((i - 1) * 2) + 2}", kickoff))
        match_no += 1
        kickoff += slot

    out.append((match_no, "Semifinals", "W97", "W98", kickoff))
    match_no += 1
    kickoff += slot
    out.append((match_no, "Semifinals", "W99", "W100", kickoff))
    match_no += 1
    kickoff += slot

    out.append((match_no, "Final", "L101", "L102", kickoff))
    match_no += 1
    kickoff += slot
    out.append((match_no, "Final", "W101", "W102", kickoff))

    return out


def generate_world_cup_2026_matches() -> int:
    created = 0
    for match_number, stage, home, away, kickoff_at in build_world_cup_2026_matches():
        exists = db.session.scalar(select(Match.id).where(Match.match_number == match_number))
        if exists is not None:
            continue
        db.session.add(
            Match(
                match_number=match_number,
                stage=stage,
                home_team=home,
                away_team=away,
                kickoff_at=kickoff_at,
            ),
        )
        created += 1
    if created:
        db.session.commit()
    return created
