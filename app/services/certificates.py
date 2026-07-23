"""Winner certificates: same ranking as the public leaderboard; prize overlays only."""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from flask import current_app
from sqlalchemy import select

from app import db
from app.datetime_fmt import server_now_local
from app.models import Entry, EntryStatus, Payment, PaymentStatus, User, WinnerCertificate, utcnow
from app.prize_info import count_prize_pool_qualifying_entries, entry_financials

TOURNAMENT_NAME = "Quiniela Mundialista 2026 MX"
TOURNAMENT_YEAR = 2026
CERTIFICATE_HEADER = "QUINIELA MUNDIALISTA 2026 MX"
ORGANIZER_NAME = "Luis Tapia"

POSITION_TITLES = {
    1: "CERTIFICADO DE CAMPEÓN",
    2: "RECONOCIMIENTO AL SEGUNDO LUGAR",
    3: "RECONOCIMIENTO AL TERCER LUGAR",
}

POSITION_LABELS = {
    1: "primer lugar",
    2: "segundo lugar",
    3: "tercer lugar",
}

_MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


@dataclass(frozen=True)
class RankedWinner:
    rank: int
    entry: Entry
    user: User
    public_name: str
    total_points: int


def _new_public_token() -> str:
    return secrets.token_urlsafe(24)


def format_recognition_date(d: date) -> str:
    return f"{d.day} de {_MONTHS_ES[d.month - 1]} de {d.year}"


def default_recognition_date() -> date:
    return server_now_local().date()


def prize_for_position(position: int, config: Mapping[str, Any] | None = None) -> int:
    """Reuse existing prize-pool estimates (not hardcoded in templates)."""
    cfg = config if config is not None else current_app.config
    n = count_prize_pool_qualifying_entries()
    fin = entry_financials(n, cfg)
    if position == 1:
        return int(fin["estimate_1st"])
    if position == 2:
        return int(fin["estimate_2nd"])
    if position == 3:
        return int(fin["estimate_3rd"])
    return 0


def fetch_ranked_leaderboard() -> list[RankedWinner]:
    """Same eligibility, sort, and competition ranking as ``leaderboard.index``."""
    rows = list(
        db.session.execute(
            select(Entry, User)
            .join(Payment, Payment.entry_id == Entry.id)
            .where(
                Payment.status == PaymentStatus.APPROVED,
                Entry.status == EntryStatus.ACTIVE,
            )
            .join(User, Entry.user_id == User.id)
            .order_by(Entry.total_points.desc(), Entry.created_at.asc(), Entry.id.asc()),
        ),
    )
    ranked: list[RankedWinner] = []
    prev_points: int | None = None
    rank = 0
    for i, (entry, user) in enumerate(rows, start=1):
        if prev_points is None or entry.total_points < prev_points:
            rank = i
        prev_points = entry.total_points
        name = (user.display_name or "").strip()
        ranked.append(
            RankedWinner(
                rank=rank,
                entry=entry,
                user=user,
                public_name=name,
                total_points=int(entry.total_points or 0),
            ),
        )
    return ranked


def top3_winners(ranked: list[RankedWinner] | None = None) -> list[RankedWinner]:
    """Entries whose competition rank is 1, 2, or 3 (ties may yield more than three people)."""
    rows = ranked if ranked is not None else fetch_ranked_leaderboard()
    return [r for r in rows if r.rank in (1, 2, 3)]


def _default_certificate_display_name(public_name: str) -> str:
    """Never embed internal database IDs in certificate-facing text."""
    name = (public_name or "").strip()
    return (name or "Participante")[:120]


def sync_top3_certificates(*, refresh_prizes: bool = False) -> list[WinnerCertificate]:
    """Create/update active certificates for current TOP 3; deactivate others.

    Does not change user profiles, scores, ranking tables, predictions, or payments.
    Editable certificate fields (display_name, prize_amount, recognition_date) are
    preserved unless the certificate is newly created (or ``refresh_prizes`` for prize).
    """
    winners = top3_winners()
    winner_entry_ids = {w.entry.id for w in winners}
    existing = {
        c.entry_id: c
        for c in db.session.scalars(select(WinnerCertificate)).all()
    }

    edition_id = None
    try:
        from app.models import TournamentEdition
        from app.services.tournament_editions import current_edition_slug

        edition = db.session.scalar(
            select(TournamentEdition).where(TournamentEdition.slug == current_edition_slug()),
        )
        if edition is not None:
            edition_id = edition.id
    except Exception:
        edition_id = None

    for cert in existing.values():
        if cert.entry_id not in winner_entry_ids and cert.is_active:
            cert.is_active = False
            cert.updated_at = utcnow()

    result: list[WinnerCertificate] = []
    for w in winners:
        cert = existing.get(w.entry.id)
        default_prize = prize_for_position(w.rank)
        if cert is None:
            cert = WinnerCertificate(
                entry_id=w.entry.id,
                tournament_edition_id=edition_id,
                final_position=w.rank,
                display_name=_default_certificate_display_name(w.public_name),
                prize_amount=default_prize,
                recognition_date=default_recognition_date(),
                public_token=_new_public_token(),
                is_active=True,
            )
            db.session.add(cert)
        else:
            cert.final_position = w.rank
            cert.is_active = True
            if edition_id is not None and cert.tournament_edition_id is None:
                cert.tournament_edition_id = edition_id
            if refresh_prizes:
                cert.prize_amount = default_prize
            if not (cert.display_name or "").strip():
                cert.display_name = _default_certificate_display_name(w.public_name)
            if cert.recognition_date is None:
                cert.recognition_date = default_recognition_date()
            if not cert.public_token:
                cert.public_token = _new_public_token()
            cert.updated_at = utcnow()
        result.append(cert)

    db.session.commit()
    return sorted(result, key=lambda c: (c.final_position, c.id))


def get_active_certificates() -> list[WinnerCertificate]:
    return list(
        db.session.scalars(
            select(WinnerCertificate)
            .where(WinnerCertificate.is_active.is_(True))
            .order_by(WinnerCertificate.final_position.asc(), WinnerCertificate.id.asc()),
        ),
    )


def get_certificate_by_token(token: str) -> WinnerCertificate | None:
    tok = (token or "").strip()
    if not tok:
        return None
    return db.session.scalar(
        select(WinnerCertificate).where(
            WinnerCertificate.public_token == tok,
            WinnerCertificate.is_active.is_(True),
        ),
    )


def certificate_view_context(cert: WinnerCertificate, *, include_model: bool = False) -> dict[str, Any]:
    """Safe fields for templates (no email, no internal payment/user IDs)."""
    entry = cert.entry
    points = int(entry.total_points or 0) if entry is not None else 0
    position = int(cert.final_position)
    recognition = cert.recognition_date or default_recognition_date()
    ctx: dict[str, Any] = {
        "display_name": (cert.display_name or "").strip() or "Participante",
        "final_position": position,
        "position_title": POSITION_TITLES.get(position, "RECONOCIMIENTO"),
        "position_label": POSITION_LABELS.get(position, f"{position}.º lugar"),
        "total_points": points,
        "prize_amount": int(cert.prize_amount or 0),
        "recognition_date": recognition,
        "recognition_date_formatted": format_recognition_date(recognition),
        "tournament_name": TOURNAMENT_NAME,
        "tournament_year": TOURNAMENT_YEAR,
        "certificate_header": CERTIFICATE_HEADER,
        "organizer_name": ORGANIZER_NAME,
        "public_token": cert.public_token,
        "champion_extra": position == 1,
    }
    if include_model:
        ctx["certificate"] = cert
    return ctx
