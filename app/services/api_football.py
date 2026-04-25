from __future__ import annotations

from datetime import datetime

import requests
from sqlalchemy import select

from app import db
from app.models import Match, Prediction, Result
from app.services.scoring import recalculate_all_points

FINISHED_STATUS_SHORT = {"FT", "AET", "PEN"}


class ApiFootballError(RuntimeError):
    pass


def _parse_kickoff(raw: str | None) -> datetime | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _request_api(base_url: str, api_key: str, endpoint: str, params: dict) -> dict:
    try:
        response = requests.get(
            f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}",
            headers={"x-apisports-key": api_key, "Accept": "application/json"},
            params=params,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise ApiFootballError(f"network_error: {exc}") from exc
    if response.status_code == 429:
        raise ApiFootballError("rate_limit")
    if response.status_code >= 400:
        raise ApiFootballError(f"http_{response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ApiFootballError("invalid_json") from exc
    if not isinstance(payload, dict):
        raise ApiFootballError("invalid_response")
    return payload


def get_world_cup_league_candidates(base_url: str, api_key: str, *, season: int) -> list[dict]:
    payload = _request_api(base_url, api_key, "/leagues", {"search": "World Cup", "season": season})
    rows = payload.get("response") or []
    out: list[dict] = []
    for row in rows:
        league = row.get("league") or {}
        country = row.get("country") or {}
        seasons = row.get("seasons") or []
        coverage = seasons[-1].get("coverage") if seasons else None
        out.append(
            {
                "league_id": league.get("id"),
                "league_name": league.get("name"),
                "country": country.get("name") or "",
                "season": season,
                "coverage": coverage or {},
            },
        )
    return out


def fetch_world_cup_fixtures(base_url: str, api_key: str, *, season: int, league_id: int) -> list[dict]:
    payload = _request_api(base_url, api_key, "/fixtures", {"league": league_id, "season": season})
    rows = payload.get("response") or []
    fixtures: list[dict] = []
    for row in rows:
        fixture = row.get("fixture") or {}
        league = row.get("league") or {}
        teams = row.get("teams") or {}
        goals = row.get("goals") or {}
        status = (fixture.get("status") or {})
        ext_id = fixture.get("id")
        home = (teams.get("home") or {}).get("name")
        away = (teams.get("away") or {}).get("name")
        if not ext_id or not home or not away:
            continue
        fixtures.append(
            {
                "external_match_id": str(ext_id),
                "home_team": str(home),
                "away_team": str(away),
                "kickoff_at": _parse_kickoff(fixture.get("date")),
                "stage": str(league.get("round") or "World Cup"),
                "goals_home": goals.get("home"),
                "goals_away": goals.get("away"),
                "status_short": str(status.get("short") or ""),
                "status_long": str(status.get("long") or ""),
            },
        )
    fixtures.sort(key=lambda f: (f["kickoff_at"] or datetime.max, f["external_match_id"]))
    return fixtures


def _renumber_matches_sequentially() -> None:
    all_matches = list(
        db.session.scalars(
            select(Match).order_by(Match.kickoff_at.asc().nulls_last(), Match.id.asc()),
        ),
    )
    # Two-pass assignment avoids UNIQUE collisions on match_number while renumbering.
    temp_base = 100000
    for idx, m in enumerate(all_matches, start=1):
        m.match_number = temp_base + idx
    db.session.flush()
    for idx, m in enumerate(all_matches, start=1):
        m.match_number = idx


def import_fixtures_upsert(
    base_url: str,
    api_key: str,
    *,
    season: int,
    league_id: int,
    allow_clear_without_predictions: bool = True,
) -> dict:
    fixtures = fetch_world_cup_fixtures(base_url, api_key, season=season, league_id=league_id)
    if not fixtures:
        raise ApiFootballError("no_fixtures")

    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    has_predictions = db.session.scalar(select(Prediction.id).limit(1)) is not None
    if allow_clear_without_predictions and not has_predictions:
        db.session.query(Result).delete()
        db.session.query(Match).delete()
        db.session.flush()

    existing_by_external = {
        m.external_match_id: m
        for m in db.session.scalars(select(Match).where(Match.external_match_id.is_not(None)))
    }
    temp_match_number = (db.session.scalar(select(Match.match_number).order_by(Match.match_number.desc()).limit(1)) or 0) + 1

    for row in fixtures:
        ext_id = row["external_match_id"]
        match = existing_by_external.get(ext_id)
        if match is None:
            match = Match(
                match_number=temp_match_number,
                external_match_id=ext_id,
            )
            temp_match_number += 1
            db.session.add(match)
            created += 1
        else:
            updated += 1
        match.stage = row["stage"]
        match.home_team = row["home_team"]
        match.away_team = row["away_team"]
        match.kickoff_at = row["kickoff_at"]
    if created or updated:
        _renumber_matches_sequentially()
        db.session.commit()
    else:
        skipped = len(fixtures)
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "fixtures_total": len(fixtures),
    }


def sync_results_from_api(base_url: str, api_key: str, *, season: int, league_id: int) -> dict:
    fixtures = fetch_world_cup_fixtures(base_url, api_key, season=season, league_id=league_id)
    if not fixtures:
        raise ApiFootballError("no_fixtures")

    by_external = {
        (m.external_match_id or ""): m
        for m in db.session.scalars(select(Match).where(Match.external_match_id.is_not(None)))
    }
    results_synced = 0
    skipped = 0
    errors: list[str] = []

    for row in fixtures:
        if row["status_short"] not in FINISHED_STATUS_SHORT:
            continue
        match = by_external.get(row["external_match_id"])
        if match is None:
            skipped += 1
            continue
        gh = row["goals_home"]
        ga = row["goals_away"]
        if gh is None or ga is None:
            skipped += 1
            continue
        res = match.result
        if res is None:
            db.session.add(Result(match_id=match.id, home_score=int(gh), away_score=int(ga)))
        else:
            res.home_score = int(gh)
            res.away_score = int(ga)
        results_synced += 1

    if results_synced:
        db.session.flush()
        recalculate_all_points()
    db.session.commit()
    return {
        "results_synced": results_synced,
        "skipped": skipped,
        "errors": errors,
        "fixtures_total": len(fixtures),
    }
