"""Insert sample data for local development. Run: flask --app run seed-matches"""
from __future__ import annotations

from datetime import datetime, timezone

from app import db
from app.models import Match

SAMPLE_MATCHES: list[tuple[int, str, str, str, datetime | None]] = [
    (
        1,
        "Fase de grupos",
        "Mexico",
        "South Africa",
        datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc),
    ),
    (
        2,
        "Fase de grupos",
        "Canada",
        "TBD",
        datetime(2026, 6, 12, 20, 0, tzinfo=timezone.utc),
    ),
    (
        3,
        "Fase de grupos",
        "USA",
        "TBD",
        datetime(2026, 6, 12, 22, 0, tzinfo=timezone.utc),
    ),
    (
        4,
        "Fase de grupos",
        "Argentina",
        "TBD",
        datetime(2026, 6, 13, 18, 0, tzinfo=timezone.utc),
    ),
    (
        5,
        "Fase de grupos",
        "Brazil",
        "TBD",
        datetime(2026, 6, 14, 18, 0, tzinfo=timezone.utc),
    ),
]


def seed_sample_matches() -> int:
    """Insert 5 sample matches if their match_number is not present. Returns rows inserted."""
    added = 0
    for match_number, stage, home_team, away_team, kickoff_at in SAMPLE_MATCHES:
        exists = (
            db.session.query(Match.id)
            .filter(Match.match_number == match_number)
            .first()
        )
        if exists is not None:
            continue
        m = Match(
            match_number=match_number,
            stage=stage,
            home_team=home_team,
            away_team=away_team,
            kickoff_at=kickoff_at,
        )
        db.session.add(m)
        added += 1
    if added:
        db.session.commit()
    return added
