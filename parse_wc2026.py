import csv
import re
from datetime import datetime

INPUT_FILE = "Pasted text.txt"
OUTPUT_FILE = "wc2026_matches_clean.csv"
YEAR = 2026

GROUP_STAGE = "Fase de grupos"
KNOCKOUT_STAGES = {
    "Eliminatoria de 32",
    "Octavos de final",
    "Cuartos de final",
    "Semifinales",
    "Eliminatoria por el tercer lugar",
    "Final",
}


def _clean_text(text: str) -> str:
    value = (text or "").strip().replace("\xa0", " ").replace("\u202f", " ")
    return re.sub(r"\s+", " ", value)


def _dedupe_doubled_name(name: str) -> str:
    value = _clean_text(name)
    if not value:
        return value
    half = len(value) // 2
    if len(value) % 2 == 0 and value[:half] == value[half:]:
        return value[:half]
    return value


def _is_date(text: str) -> bool:
    return re.fullmatch(r"\d{1,2}/\d{1,2}", _clean_text(text)) is not None


def _is_time(text: str) -> bool:
    value = _clean_text(text).lower().replace(".", "")
    return re.fullmatch(r"\d{1,2}:\d{2}\s*[ap]\s*m", value) is not None


def _to_24h(time_text: str) -> tuple[int, int]:
    value = _clean_text(time_text).lower().replace(".", "")
    m = re.fullmatch(r"(\d{1,2}):(\d{2})\s*([ap])\s*m", value)
    if not m:
        raise ValueError(f"Hora inválida: {time_text}")
    hour = int(m.group(1))
    minute = int(m.group(2))
    meridiem = m.group(3)
    if hour == 12:
        hour = 0
    if meridiem == "p":
        hour += 12
    return hour, minute


def _build_kickoff(date_text: str, time_text: str) -> str:
    day_str, month_str = _clean_text(date_text).split("/")
    hour, minute = _to_24h(time_text)
    dt = datetime(YEAR, int(month_str), int(day_str), hour, minute)
    return dt.strftime("%Y-%m-%d %H:%M")


def _load_lines() -> list[str]:
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        return [_clean_text(line) for line in f if _clean_text(line)]


def _detect_stage(line: str) -> str | None:
    clean = _clean_text(line)
    if "Fase de grupos" in clean:
        return GROUP_STAGE
    for stage in KNOCKOUT_STAGES:
        if stage == clean:
            return stage
    return None


def _next_match_block(lines: list[str], start_idx: int) -> tuple[int, str, str, str, str] | None:
    if start_idx >= len(lines) or not _is_date(lines[start_idx]):
        return None
    date_text = lines[start_idx]
    time_idx = start_idx + 1
    while time_idx < len(lines) and not _is_time(lines[time_idx]):
        if _is_date(lines[time_idx]) or _detect_stage(lines[time_idx]) or lines[time_idx].startswith("Grupo "):
            return None
        time_idx += 1
    if time_idx >= len(lines):
        return None
    team_idx = time_idx + 1
    teams: list[str] = []
    while team_idx < len(lines) and len(teams) < 2:
        value = lines[team_idx]
        if _is_date(value) or _is_time(value) or _detect_stage(value) or value.startswith("Grupo "):
            team_idx += 1
            continue
        teams.append(value)
        team_idx += 1
    if len(teams) < 2:
        return None
    return team_idx, date_text, lines[time_idx], teams[0], teams[1]


def parse_matches(lines: list[str]) -> list[dict]:
    matches: list[dict] = []
    current_stage = GROUP_STAGE
    current_group = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        detected_stage = _detect_stage(line)
        if detected_stage:
            current_stage = detected_stage
            if detected_stage in KNOCKOUT_STAGES:
                current_group = ""
            i += 1
            continue
        if line.startswith("Grupo "):
            current_group = _clean_text(line)
            i += 1
            continue
        if not _is_date(line):
            i += 1
            continue
        block = _next_match_block(lines, i)
        if block is None:
            i += 1
            continue
        next_idx, date_text, time_text, home_raw, away_raw = block
        kickoff_at = _build_kickoff(date_text, time_text)
        if current_stage in KNOCKOUT_STAGES:
            home_team = "A definir"
            away_team = "A definir"
            group_name = ""
        else:
            home_team = _dedupe_doubled_name(home_raw)
            away_team = _dedupe_doubled_name(away_raw)
            group_name = current_group
        if not home_team or not away_team:
            i += 1
            continue
        matches.append(
            {
                "match_number": len(matches) + 1,
                "stage": current_stage,
                "group_name": group_name,
                "home_team": home_team,
                "away_team": away_team,
                "kickoff_at": kickoff_at,
            },
        )
        i = next_idx
    return matches


def write_csv(matches: list[dict]) -> None:
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["match_number", "stage", "group_name", "home_team", "away_team", "kickoff_at"],
        )
        writer.writeheader()
        writer.writerows(matches)


def main() -> None:
    lines = _load_lines()
    matches = parse_matches(lines)
    write_csv(matches)

    print(f"CSV guardado en: {OUTPUT_FILE}")
    print(f"Total de filas generadas: {len(matches)}")
    if len(matches) != 104:
        print(f"WARNING: expected 104 matches but got {len(matches)}")
    print("\nPrimeras 10 filas:")
    for row in matches[:10]:
        print(row)
    print("\nUltimas 10 filas:")
    for row in matches[-10:]:
        print(row)


if __name__ == "__main__":
    main()