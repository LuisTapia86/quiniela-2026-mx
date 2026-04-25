from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import TextIO

from sqlalchemy import or_, select

from app import db
from app.models import Match

_REQUIRED_COLUMNS = {"match_number", "stage", "home_team", "away_team", "kickoff_at"}


def _delete_placeholder_matches_without_predictions() -> None:
    placeholder_stmt = (
        select(Match)
        .where(
            or_(
                Match.home_team.like("Team%"),
                Match.away_team.like("Team%"),
                Match.away_team == "TBD",
            ),
        )
        .where(~Match.predictions.any())
    )
    for match in db.session.scalars(placeholder_stmt):
        db.session.delete(match)
    db.session.flush()


def parse_kickoff(raw: str) -> datetime:
    value = (raw or "").strip()
    if not value:
        raise ValueError("kickoff_at vacío")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"kickoff_at inválido: {raw}")


def import_matches_from_reader(reader: TextIO) -> dict:
    csv_reader = csv.DictReader(reader)
    if not csv_reader.fieldnames:
        return {"created": 0, "updated": 0, "skipped": 0, "errors": ["CSV sin encabezados."]}
    fields = {f.strip() for f in csv_reader.fieldnames if f}
    missing = sorted(_REQUIRED_COLUMNS - fields)
    has_group_name = "group_name" in fields
    if missing:
        return {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [f"Faltan columnas requeridas: {', '.join(missing)}"],
        }

    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []
    _delete_placeholder_matches_without_predictions()

    for i, row in enumerate(csv_reader, start=2):
        try:
            match_number = int((row.get("match_number") or "").strip())
            stage = (row.get("stage") or "").strip()
            group_name = (row.get("group_name") or "").strip() if has_group_name else ""
            home = (row.get("home_team") or "").strip()
            away = (row.get("away_team") or "").strip()
            kickoff = parse_kickoff(row.get("kickoff_at") or "")
            if match_number <= 0 or not stage or not home or not away:
                skipped += 1
                errors.append(f"Línea {i}: datos incompletos.")
                continue
            m = db.session.scalar(select(Match).where(Match.match_number == match_number))
            if m is None:
                db.session.add(
                    Match(
                        match_number=match_number,
                        stage=stage,
                        group_name=group_name or None,
                        home_team=home,
                        away_team=away,
                        kickoff_at=kickoff,
                    ),
                )
                created += 1
            else:
                m.stage = stage
                m.group_name = group_name or None
                m.home_team = home
                m.away_team = away
                m.kickoff_at = kickoff
                updated += 1
        except Exception as exc:  # pragma: no cover
            skipped += 1
            errors.append(f"Línea {i}: {exc}")

    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}


def import_matches_from_path(path: str | Path) -> dict:
    p = Path(path)
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        return import_matches_from_reader(f)
