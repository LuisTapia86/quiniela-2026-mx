"""Spanish team names → official Unicode flag emojis (regional-indicator pairs)."""

from __future__ import annotations

import unicodedata

# WC2026 teams (Spanish CSV names) → flag emoji literals
_TEAM_FLAG_EMOJI: dict[str, str] = {
    "alemania": "🇩🇪",
    "arabia saudita": "🇸🇦",
    "argelia": "🇩🇿",
    "argentina": "🇦🇷",
    "australia": "🇦🇺",
    "austria": "🇦🇹",
    "bosnia y herzegovina": "🇧🇦",
    "brasil": "🇧🇷",
    "belgica": "🇧🇪",
    "bélgica": "🇧🇪",
    "cabo verde": "🇨🇻",
    "canada": "🇨🇦",
    "canadá": "🇨🇦",
    "catar": "🇶🇦",
    "chequia": "🇨🇿",
    "colombia": "🇨🇴",
    "corea del sur": "🇰🇷",
    "costa de marfil": "🇨🇮",
    "croacia": "🇭🇷",
    "curazao": "🇨🇼",
    "ecuador": "🇪🇨",
    "egipto": "🇪🇬",
    "escocia": "🇬🇧",
    "espana": "🇪🇸",
    "españa": "🇪🇸",
    "estados unidos": "🇺🇸",
    "francia": "🇫🇷",
    "ghana": "🇬🇭",
    "haiti": "🇭🇹",
    "haití": "🇭🇹",
    "inglaterra": "🇬🇧",
    "irak": "🇮🇶",
    "iran": "🇮🇷",
    "irán": "🇮🇷",
    "japon": "🇯🇵",
    "japón": "🇯🇵",
    "jordania": "🇯🇴",
    "marruecos": "🇲🇦",
    "mexico": "🇲🇽",
    "méxico": "🇲🇽",
    "noruega": "🇳🇴",
    "nueva zelanda": "🇳🇿",
    "panama": "🇵🇦",
    "panamá": "🇵🇦",
    "paraguay": "🇵🇾",
    "paises bajos": "🇳🇱",
    "países bajos": "🇳🇱",
    "portugal": "🇵🇹",
    "rd congo": "🇨🇩",
    "senegal": "🇸🇳",
    "sudafrica": "🇿🇦",
    "sudáfrica": "🇿🇦",
    "suecia": "🇸🇪",
    "suiza": "🇨🇭",
    "turquia": "🇹🇷",
    "turquía": "🇹🇷",
    "tunez": "🇹🇳",
    "túnez": "🇹🇳",
    "uruguay": "🇺🇾",
    "uzbekistan": "🇺🇿",
    "uzbekistán": "🇺🇿",
}

_PLACEHOLDER_NAMES = frozenset(
    {
        "",
        "a definir",
        "por definir",
        "tbd",
    },
)


def _normalize_team_key(name: str) -> str:
    return unicodedata.normalize("NFC", (name or "").strip().lower())


def team_flag(team_name: str | None) -> str:
    key = _normalize_team_key(team_name or "")
    if key in _PLACEHOLDER_NAMES:
        return ""
    return _TEAM_FLAG_EMOJI.get(key, "")


def mapped_team_names() -> tuple[str, ...]:
    """All team names with a configured flag (for reports/tests)."""
    return tuple(sorted(_TEAM_FLAG_EMOJI.keys()))
