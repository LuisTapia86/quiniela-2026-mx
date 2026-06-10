"""Spanish team names → official Unicode regional-indicator flags (ISO 3166-1 alpha-2)."""

from __future__ import annotations

import unicodedata

# WC2026 CSV team names (Spanish) → ISO 3166-1 alpha-2
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
    value = unicodedata.normalize("NFC", (name or "").strip().lower())
    return value


def _iso_to_flag(iso: str) -> str:
    code = (iso or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code)


def team_flag(team_name: str | None) -> str:
    key = _normalize_team_key(team_name or "")
    if key in _PLACEHOLDER_NAMES:
        return ""
    iso = _TEAM_ISO.get(key)
    if iso is None:
        return ""
    return _iso_to_flag(iso)
