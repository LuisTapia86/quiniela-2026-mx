"""Reusable tournament edition helpers for History + Hall of Fame."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from flask import current_app, url_for
from sqlalchemy import func, or_, select

from app import db
from app.models import (
    Entry,
    EntryStatus,
    Payment,
    PaymentStatus,
    TournamentEdition,
    TournamentStatus,
    WinnerCertificate,
    utcnow,
)
from app.prize_info import count_prize_pool_qualifying_entries, entry_financials
from app.services.certificates import (
    default_recognition_date,
    format_recognition_date,
    get_active_certificates,
    sync_top3_certificates,
)
from app.tournament_lifecycle import tournament_status


@dataclass(frozen=True)
class PodiumPlace:
    position: int
    display_name: str
    total_points: int
    prize_amount: int
    photo_url: str | None
    public_token: str | None
    recognition_date: date | None
    recognition_date_formatted: str


@dataclass(frozen=True)
class EditionArchiveCard:
    edition: TournamentEdition
    champion: PodiumPlace | None
    runner_up: PodiumPlace | None
    third_place: PodiumPlace | None
    status_label: str
    logo_url: str | None
    start_date_formatted: str
    end_date_formatted: str
    edition_label_display: str


def current_edition_slug() -> str:
    raw = (current_app.config.get("CURRENT_TOURNAMENT_SLUG") or "").strip()
    if raw:
        return raw
    year = int(current_app.config.get("API_FOOTBALL_WORLD_CUP_SEASON", 2026) or 2026)
    return f"edition-{year}"


def _default_logo_static_path() -> str | None:
    static_root = Path(current_app.static_folder or "")
    for candidate in ("img/logo-icon.png", "img/logo-icon-cropped.png", "img/logo.svg"):
        if (static_root / candidate).is_file():
            return candidate
    return None


def _count_distinct_participants() -> int:
    n = db.session.scalar(
        select(func.count(func.distinct(Entry.user_id)))
        .select_from(Entry)
        .join(Payment, Payment.entry_id == Entry.id)
        .where(
            Entry.status == EntryStatus.ACTIVE,
            Payment.status == PaymentStatus.APPROVED,
        ),
    )
    return int(n or 0)


def _format_date(d: date | None) -> str:
    if d is None:
        return "—"
    return format_recognition_date(d)


def _status_label(status: TournamentStatus | str) -> str:
    from app.translations import tr

    raw = status.value if isinstance(status, TournamentStatus) else str(status or "")
    raw = raw.strip().upper()
    if raw == TournamentStatus.ACTIVE.value:
        return tr("hall_of_fame.status.active")
    if raw == TournamentStatus.ARCHIVED.value:
        return tr("hall_of_fame.status.archived")
    return tr("hall_of_fame.status.finished")


def place_from_cert(cert: WinnerCertificate | None) -> PodiumPlace | None:
    if cert is None:
        return None
    points = int(cert.entry.total_points or 0) if cert.entry is not None else 0
    recognition = cert.recognition_date
    photo = (cert.photo_path or "").strip() or None
    return PodiumPlace(
        position=int(cert.final_position),
        display_name=(cert.display_name or "").strip() or "Participante",
        total_points=points,
        prize_amount=int(cert.prize_amount or 0),
        photo_url=photo,
        public_token=cert.public_token,
        recognition_date=recognition,
        recognition_date_formatted=format_recognition_date(recognition) if recognition else "—",
    )


def first_cert_by_position(certs: list[WinnerCertificate], position: int) -> WinnerCertificate | None:
    for cert in certs:
        if int(cert.final_position) == position:
            return cert
    return None


def edition_certs(edition_id: int) -> list[WinnerCertificate]:
    return list(
        db.session.scalars(
            select(WinnerCertificate)
            .where(
                WinnerCertificate.tournament_edition_id == edition_id,
                WinnerCertificate.is_active.is_(True),
            )
            .order_by(WinnerCertificate.final_position.asc(), WinnerCertificate.id.asc()),
        ),
    )


def refresh_edition_summary(edition: TournamentEdition) -> TournamentEdition:
    """Snapshot live pool stats onto the edition row."""
    entries_count = count_prize_pool_qualifying_entries()
    participants = _count_distinct_participants()
    fin = entry_financials(entries_count, current_app.config)
    edition.entries_count = entries_count
    edition.participants_count = participants
    edition.prize_pool_mxn = int(fin["prize_pool"])

    champ = db.session.scalar(
        select(WinnerCertificate)
        .where(
            WinnerCertificate.tournament_edition_id == edition.id,
            WinnerCertificate.is_active.is_(True),
            WinnerCertificate.final_position == 1,
        )
        .order_by(WinnerCertificate.id.asc()),
    )
    if champ is not None and champ.entry is not None:
        edition.champion_points = int(champ.entry.total_points or 0)
        if champ.recognition_date is not None:
            edition.recognition_date = champ.recognition_date
            if edition.end_date is None:
                edition.end_date = champ.recognition_date
    elif edition.recognition_date is None:
        edition.recognition_date = default_recognition_date()

    status = tournament_status()
    if status in {TournamentStatus.FINISHED, TournamentStatus.ARCHIVED}:
        edition.status = status
        if edition.end_date is None:
            edition.end_date = edition.recognition_date or default_recognition_date()
    edition.updated_at = utcnow()
    return edition


def ensure_current_edition() -> TournamentEdition:
    """Ensure the active/config edition row exists and certificates are linked."""
    slug = current_edition_slug()
    year = int(current_app.config.get("API_FOOTBALL_WORLD_CUP_SEASON", 2026) or 2026)
    brand = (current_app.config.get("BRAND_NAME") or f"Quiniela {year}").strip()
    edition = db.session.scalar(select(TournamentEdition).where(TournamentEdition.slug == slug))
    if edition is None:
        logo = _default_logo_static_path()
        today = default_recognition_date()
        edition = TournamentEdition(
            slug=slug,
            name=brand,
            edition_label=f"{year}",
            champion_title=f"{brand} Champion",
            year=year,
            logo_path=logo,
            start_date=None,
            end_date=today,
            status=TournamentStatus.FINISHED,
            recognition_date=today,
            sort_order=year,
        )
        db.session.add(edition)
        db.session.flush()
    else:
        if not (edition.logo_path or "").strip():
            edition.logo_path = _default_logo_static_path()
        if not (edition.edition_label or "").strip():
            edition.edition_label = str(edition.year)
        if edition.end_date is None and edition.recognition_date is not None:
            edition.end_date = edition.recognition_date

    certs = get_active_certificates()
    if not certs:
        certs = sync_top3_certificates()
    for cert in certs:
        if cert.tournament_edition_id is None:
            cert.tournament_edition_id = edition.id
            cert.updated_at = utcnow()

    refresh_edition_summary(edition)
    db.session.commit()
    return edition


def logo_url_for(edition: TournamentEdition) -> str | None:
    path = (edition.logo_path or "").strip()
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://") or path.startswith("/"):
        return path
    return url_for("static", filename=path)


def build_edition_card(edition: TournamentEdition) -> EditionArchiveCard:
    certs = edition_certs(edition.id)
    label = (edition.edition_label or "").strip() or str(edition.year)
    return EditionArchiveCard(
        edition=edition,
        champion=place_from_cert(first_cert_by_position(certs, 1)),
        runner_up=place_from_cert(first_cert_by_position(certs, 2)),
        third_place=place_from_cert(first_cert_by_position(certs, 3)),
        status_label=_status_label(edition.status),
        logo_url=logo_url_for(edition),
        start_date_formatted=_format_date(edition.start_date),
        end_date_formatted=_format_date(edition.end_date or edition.recognition_date),
        edition_label_display=label,
    )


def list_finished_editions() -> list[TournamentEdition]:
    ensure_current_edition()
    return list(
        db.session.scalars(
            select(TournamentEdition)
            .where(
                or_(
                    TournamentEdition.status == TournamentStatus.FINISHED,
                    TournamentEdition.status == TournamentStatus.ARCHIVED,
                ),
            )
            .order_by(
                TournamentEdition.sort_order.desc(),
                TournamentEdition.year.desc(),
                TournamentEdition.id.desc(),
            ),
        ),
    )


def list_all_editions() -> list[TournamentEdition]:
    ensure_current_edition()
    return list(
        db.session.scalars(
            select(TournamentEdition).order_by(
                TournamentEdition.sort_order.desc(),
                TournamentEdition.year.desc(),
                TournamentEdition.id.desc(),
            ),
        ),
    )


def get_edition_by_slug(slug: str) -> TournamentEdition | None:
    tok = (slug or "").strip()
    if not tok:
        return None
    return db.session.scalar(select(TournamentEdition).where(TournamentEdition.slug == tok))


def history_index_context() -> dict[str, Any]:
    editions = list_finished_editions()
    cards = [build_edition_card(e) for e in editions]
    return {"cards": cards, "has_cards": bool(cards)}


def history_archive_context(slug: str) -> dict[str, Any] | None:
    edition = get_edition_by_slug(slug)
    if edition is None or not edition.is_closed:
        return None
    card = build_edition_card(edition)
    return {"card": card, "edition": edition}
