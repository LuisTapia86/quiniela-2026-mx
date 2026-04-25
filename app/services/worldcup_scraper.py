from __future__ import annotations

from datetime import datetime
import re

import requests
from bs4 import BeautifulSoup
from sqlalchemy import select

from app import db
from app.models import Match

WIKIPEDIA_FIXTURES_URL = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup"
REQUEST_TIMEOUT_SECONDS = 30

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


class WorldCupScraperError(RuntimeError):
    pass


def _safe_text(value: object) -> str:
    return str(value or "").strip()


def _clean_wiki_text(value: object) -> str:
    text = _safe_text(value).replace("\xa0", " ")
    text = re.sub(r"\[[0-9]+\]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_team_name_for_key(name: str) -> str:
    return _clean_wiki_text(name).casefold()


def _normalize_team_display(name: str) -> str:
    return _clean_wiki_text(name)


def _normalize_stage_name(name: str) -> str:
    stage = _clean_wiki_text(name)
    return stage or "World Cup 2026"


def _parse_wikipedia_datetime(value: str) -> datetime | None:
    clean = _clean_wiki_text(value)
    if not clean:
        return None
    clean = clean.replace("−", "-")
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})(?:,\s*(\d{1,2}):(\d{2}))?", clean)
    if not m:
        return None
    day = int(m.group(1))
    month = _MONTHS.get(m.group(2).lower())
    year = int(m.group(3))
    if month is None:
        return None
    hour = int(m.group(4) or 0)
    minute = int(m.group(5) or 0)
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def _extract_numeric_match_number(text: str) -> int | None:
    m = re.search(r"\b(?:match\s*)?(\d{1,3})\b", _clean_wiki_text(text), flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _fixture_key(home: str, away: str, kickoff_at: datetime | None) -> tuple[str, str, str]:
    kickoff_key = kickoff_at.isoformat() if kickoff_at else ""
    return (_normalize_team_name_for_key(home), _normalize_team_name_for_key(away), kickoff_key)


def _renumber_matches_sequentially() -> None:
    all_matches = list(
        db.session.scalars(
            select(Match).order_by(Match.kickoff_at.asc().nulls_last(), Match.id.asc()),
        ),
    )
    temp_base = 100000
    for idx, row in enumerate(all_matches, start=1):
        row.match_number = temp_base + idx
    db.session.flush()
    for idx, row in enumerate(all_matches, start=1):
        row.match_number = idx


def _request_page(url: str) -> str:
    try:
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; quiniela-mundialista/1.0)",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
    except requests.RequestException as exc:
        raise WorldCupScraperError(f"network_error: {exc}") from exc
    if resp.status_code >= 400:
        raise WorldCupScraperError(f"http_{resp.status_code}")
    return resp.text


def _is_fixture_stage(stage: str) -> bool:
    s = stage.casefold()
    return "group" in s or "knockout" in s or "round of" in s or "quarter-final" in s or "semi-final" in s or "final" in s


def _parse_wikipedia_fixture_tables(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    fixtures: list[dict] = []
    current_stage = "World Cup 2026"

    for node in soup.select("h2, h3, h4, table.wikitable"):
        if node.name in {"h2", "h3", "h4"}:
            header = _clean_wiki_text(node.get_text(" ", strip=True))
            if header:
                current_stage = header
            continue
        if node.name != "table":
            continue
        stage = _normalize_stage_name(current_stage)
        if not _is_fixture_stage(stage):
            continue

        rows = node.select("tr")
        if not rows:
            continue

        headers = [_clean_wiki_text(c.get_text(" ", strip=True)).lower() for c in rows[0].find_all(["th", "td"])]
        if not headers:
            continue

        home_idx = None
        away_idx = None
        date_idx = None
        for idx, col in enumerate(headers):
            if "team 1" in col or "home" in col:
                home_idx = idx
            elif "team 2" in col or "away" in col:
                away_idx = idx
            elif "date" in col or "time" in col:
                date_idx = idx
        if home_idx is None or away_idx is None:
            continue

        for row in rows[1:]:
            cells = row.find_all(["th", "td"])
            values = [_clean_wiki_text(c.get_text(" ", strip=True)) for c in cells]
            max_idx = max(home_idx, away_idx)
            if len(values) <= max_idx:
                continue
            home = _normalize_team_display(values[home_idx])
            away = _normalize_team_display(values[away_idx])
            if not home or not away or home == "v" or away == "v":
                continue
            date_raw = values[date_idx] if date_idx is not None and date_idx < len(values) else ""
            fixtures.append(
                {
                    "source": "wikipedia",
                    "external_match_id": "",
                    "match_number": _extract_numeric_match_number(values[0] if values else ""),
                    "stage": stage,
                    "home_team": home,
                    "away_team": away,
                    "kickoff_at": _parse_wikipedia_datetime(date_raw),
                    "venue": "",
                },
            )

    fixtures.sort(key=lambda r: (r.get("kickoff_at") or datetime.max, r.get("match_number") or 999))
    return fixtures


def _collect_public_fixtures() -> tuple[list[dict], str]:
    html = _request_page(WIKIPEDIA_FIXTURES_URL)
    fixtures = _parse_wikipedia_fixture_tables(html)
    if not fixtures:
        raise WorldCupScraperError("wiki_no_rows")
    return fixtures, "wikipedia"


def fetch_fixtures_from_public_source() -> dict:
    fixtures, source_used = _collect_public_fixtures()

    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    existing_by_external = {}
    existing_by_key = {
        _fixture_key(m.home_team, m.away_team, m.kickoff_at): m
        for m in db.session.scalars(select(Match))
    }
    existing_by_match_number = {
        int(m.match_number): m
        for m in db.session.scalars(select(Match))
        if m.match_number is not None
    }
    next_match_number = (
        db.session.scalar(select(Match.match_number).order_by(Match.match_number.desc()).limit(1)) or 0
    ) + 1

    for idx, row in enumerate(fixtures, start=1):
        home = _safe_text(row.get("home_team"))
        away = _safe_text(row.get("away_team"))
        if not home or not away:
            skipped += 1
            errors.append(f"row_{idx}: missing teams")
            continue

        ext_id = _safe_text(row.get("external_match_id"))
        kickoff_at = row.get("kickoff_at")
        if kickoff_at is not None and not isinstance(kickoff_at, datetime):
            kickoff_at = None
        stage = _normalize_stage_name(_safe_text(row.get("stage")))
        match_number_raw = row.get("match_number")
        match_number = match_number_raw if isinstance(match_number_raw, int) and match_number_raw > 0 else None

        match = None
        if ext_id:
            match = existing_by_external.get(ext_id)
        if match is None:
            match = existing_by_key.get(_fixture_key(home, away, kickoff_at))
        if match is None and match_number is not None:
            match = existing_by_match_number.get(match_number)

        if match is None:
            match = Match(
                match_number=match_number or next_match_number,
                external_match_id=ext_id or None,
                stage=stage,
                home_team=home,
                away_team=away,
                kickoff_at=kickoff_at,
            )
            db.session.add(match)
            created += 1
            if match_number is None:
                next_match_number += 1
        else:
            changed = False
            if ext_id and match.external_match_id != ext_id:
                match.external_match_id = ext_id
                changed = True
            if match.stage != stage:
                match.stage = stage
                changed = True
            if match.home_team != home:
                match.home_team = home
                changed = True
            if match.away_team != away:
                match.away_team = away
                changed = True
            if match.kickoff_at != kickoff_at:
                match.kickoff_at = kickoff_at
                changed = True
            if changed:
                updated += 1
            else:
                skipped += 1

    if created or updated:
        db.session.flush()
        _renumber_matches_sequentially()
        db.session.commit()
    else:
        db.session.rollback()

    return {
        "source": source_used,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "fixtures_total": len(fixtures),
    }
