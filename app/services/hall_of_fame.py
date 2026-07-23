"""Hall of Fame: podium views built on reusable TournamentEdition records."""
from __future__ import annotations

from typing import Any

from app.services.tournament_editions import (
    EditionArchiveCard,
    PodiumPlace,
    build_edition_card,
    current_edition_slug,
    ensure_current_edition,
    list_all_editions,
    refresh_edition_summary,
)

# Back-compat alias used by certificate sync / boot helpers.
WC2026_SLUG = None  # resolved dynamically via current_edition_slug()


def ensure_current_edition_hof():
    return ensure_current_edition()


def build_hall_of_fame() -> list[EditionArchiveCard]:
    ensure_current_edition()
    return [build_edition_card(edition) for edition in list_all_editions()]


def hall_of_fame_template_context() -> dict[str, Any]:
    cards = build_hall_of_fame()
    return {
        "editions": cards,
        "has_editions": bool(cards),
    }


# Re-exports for older imports
__all__ = [
    "PodiumPlace",
    "EditionArchiveCard",
    "WC2026_SLUG",
    "current_edition_slug",
    "ensure_current_edition",
    "ensure_current_edition_hof",
    "refresh_edition_summary",
    "build_hall_of_fame",
    "hall_of_fame_template_context",
]
