"""Parse raw SMW team JSONL into canonical team JSONL.

Output: _data/canonical/teams.jsonl

Usage:
    python scripts/parse_teams.py
"""

import re
from roco.data.utils import CANONICAL_DIR, RAW_DIR, iter_jsonl, write_jsonl

# Mapping: SMW printout key → English field name (used as flat key in raw data)
SMW_TO_EN = {
    "阵容标题": "title",
    "阵容类型": "type",
    "阵容血脉魔法": "bloodline_magic",
    "阵容介绍": "description",
    "阵容作者": "author",
    "阵容上传日期": "upload_date",
    "阵容编号": "id",
}

# Extract short name from full pet name (去掉括号中的形态)
# e.g. "棋绮后（黑子）" → "棋绮后"
SHORT_NAME_RE = re.compile(r"(.+?)（.+）$")


def short_name(name: str) -> str:
    m = SHORT_NAME_RE.match(name)
    return m.group(1) if m else name


def parse_one(raw_team: dict) -> dict | None:
    """Parse a single team's SMW printouts into structured dict."""
    po = raw_team.get("printouts", {})
    team: dict = {}

    # Top-level fields
    for smw_key, en_key in SMW_TO_EN.items():
        vals = po.get(smw_key, [])
        team[en_key] = vals[0] if vals else ""

    if not team.get("title"):
        return None

    # Per-pet slots
    pets: list[dict] = []
    for i in range(1, 7):
        name_vals = po.get(f"阵容精灵{i}", [])
        if not name_vals or not name_vals[0]:
            continue

        name = name_vals[0]
        pet = {
            "slot": i,
            "name": name,
            "name_short": short_name(name),
            "bloodline": po.get(f"阵容精灵{i}血脉", [""])[0],
            "nature": po.get(f"阵容精灵{i}性格", [""])[0],
            "ivs": _parse_csv(po.get(f"阵容精灵{i}个体值", [""])[0]),
            "moves": [
                po.get(f"阵容精灵{i}技能{j}", [""])[0]
                for j in range(1, 5)
            ],
        }
        # Filter empty moves
        pet["moves"] = [m for m in pet["moves"] if m]
        pets.append(pet)

    team["pets"] = pets
    team["team_url"] = raw_team.get("fullurl", "")
    team["kind"] = "team"
    return team


def _parse_csv(val: str) -> list[str]:
    return [v.strip() for v in val.split(",") if v.strip()] if val else []


def main() -> None:
    raw_path = RAW_DIR / "teams_raw.jsonl"
    if not raw_path.exists():
        print(f"Missing {raw_path}. Run fetch_teams.py first.")
        return

    teams: list[dict] = []
    errors: list[str] = []

    for raw_team in iter_jsonl(raw_path):
        page_id = str(raw_team.get("page_id", ""))
        team = parse_one(raw_team)
        if team is None:
            errors.append(page_id)
        else:
            teams.append(team)

    out_path = CANONICAL_DIR / "teams.jsonl"
    count = write_jsonl(teams, out_path)
    print(f"Parsed {count} teams -> {out_path}")
    if errors:
        print(f"Skipped ({len(errors)}): {', '.join(errors[:5])}")


if __name__ == "__main__":
    main()
