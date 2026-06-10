"""Spanish team names → official Unicode flag emojis (regional-indicator pairs)."""

from __future__ import annotations

import unicodedata

# WC2026 teams (Spanish CSV names) → ISO 3166-1 alpha-2 (internal only; never rendered)
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


def _normalize_team_key(name: str) -> str:
    return unicodedata.normalize("NFC", (name or "").strip().lower())


def _iso_to_flag_emoji(iso: str) -> str:
    """ISO alpha-2 → regional-indicator flag pair (e.g. MX → U+1F1F2 U+1F1FD)."""
    code = (iso or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in code)


def team_flag(team_name: str | None) -> str:
    """Return flag emoji for a team name. Never returns raw ISO codes like MX or ZA."""
    key = _normalize_team_key(team_name or "")
    if key in _PLACEHOLDER_NAMES:
        return ""
    iso = _TEAM_ISO.get(key)
    if not iso:
        return ""
    flag = _iso_to_flag_emoji(iso)
    # Guard: must not leak 2-letter ISO codes into templates
    if len(flag) == 2 and flag.isascii() and flag.isalpha():
        flag = _iso_to_flag_emoji(flag)
    return flag
