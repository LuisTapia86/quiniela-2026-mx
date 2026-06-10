"""Spanish team names → ISO 3166-1 alpha-2 for local SVG flags in static/flags/."""

from __future__ import annotations

import unicodedata
from pathlib import Path

# WC2026 teams (Spanish CSV names) → ISO 3166-1 alpha-2
_TEAM_ISO: dict[str, str] = {
    "alemania": "DE",
    "arabia saudita": "SA",
    "argelia": "DZ",
    "argentina": "AR",
    "australia": "AU",
    "austria": "AT",
    "bosnia y herzegovina": "BA",
    "brasil": "BR",
    "belgica": "BE",
    "bélgica": "BE",
    "cabo verde": "CV",
    "canada": "CA",
    "canadá": "CA",
    "catar": "QA",
    "chequia": "CZ",
    "colombia": "CO",
    "corea del sur": "KR",
    "costa de marfil": "CI",
    "croacia": "HR",
    "curazao": "CW",
    "ecuador": "EC",
    "egipto": "EG",
    "escocia": "GB",
    "espana": "ES",
    "españa": "ES",
    "estados unidos": "US",
    "francia": "FR",
    "ghana": "GH",
    "haiti": "HT",
    "haití": "HT",
    "inglaterra": "GB",
    "irak": "IQ",
    "iran": "IR",
    "irán": "IR",
    "japon": "JP",
    "japón": "JP",
    "jordania": "JO",
    "marruecos": "MA",
    "mexico": "MX",
    "méxico": "MX",
    "noruega": "NO",
    "nueva zelanda": "NZ",
    "panama": "PA",
    "panamá": "PA",
    "paraguay": "PY",
    "paises bajos": "NL",
    "países bajos": "NL",
    "portugal": "PT",
    "rd congo": "CD",
    "senegal": "SN",
    "sudafrica": "ZA",
    "sudáfrica": "ZA",
    "suecia": "SE",
    "suiza": "CH",
    "turquia": "TR",
    "turquía": "TR",
    "tunez": "TN",
    "túnez": "TN",
    "uruguay": "UY",
    "uzbekistan": "UZ",
    "uzbekistán": "UZ",
}

_PLACEHOLDER_NAMES = frozenset(
    {
        "",
        "a definir",
        "por definir",
        "tbd",
    },
)

_FLAGS_DIR: Path | None = None


def _normalize_team_key(name: str) -> str:
    return unicodedata.normalize("NFC", (name or "").strip().lower())


def team_iso_code(team_name: str | None) -> str:
    """Lowercase ISO code for a team, or empty string."""
    key = _normalize_team_key(team_name or "")
    if key in _PLACEHOLDER_NAMES:
        return ""
    iso = _TEAM_ISO.get(key)
    return iso.lower() if iso else ""


def _flags_directory() -> Path:
    global _FLAGS_DIR
    if _FLAGS_DIR is None:
        from flask import current_app

        _FLAGS_DIR = Path(current_app.static_folder or "") / "flags"
    return _FLAGS_DIR


def team_flag_static_path(team_name: str | None) -> str:
    """Relative static path (flags/xx.svg) when the SVG exists, else empty."""
    iso = team_iso_code(team_name)
    if not iso:
        return ""
    svg = _flags_directory() / f"{iso}.svg"
    if not svg.is_file():
        return ""
    return f"flags/{iso}.svg"


def unique_iso_codes() -> frozenset[str]:
    return frozenset(iso.lower() for iso in _TEAM_ISO.values())
