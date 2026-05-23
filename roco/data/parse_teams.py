"""Parse raw SMW team JSONL into canonical team records.

The build pipeline consumes these records in memory.  The CLI is an explicit
debug export helper and does not participate in the normal artifact refresh.
"""

import argparse
import re
from pathlib import Path

from roco.data.utils import RAW_DIR, iter_jsonl, with_canonical_hash, write_jsonl

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
    team["source_page_id"] = raw_team.get("page_id", "")
    team["kind"] = "team"
    return team


def _parse_csv(val: str) -> list[str]:
    return [v.strip() for v in val.split(",") if v.strip()] if val else []


def build_teams_from_raw(raw_path=None) -> list[dict]:
    path = raw_path or (RAW_DIR / "teams_raw.jsonl")
    if not path.exists():
        return []
    teams: list[dict] = []
    for raw_team in iter_jsonl(path):
        team = parse_one(raw_team)
        if team is not None:
            teams.append(with_canonical_hash(team, raw_team))
    return teams


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-path", type=Path, default=RAW_DIR / "teams_raw.jsonl")
    parser.add_argument("--out", type=Path, required=True, help="Debug JSONL export path.")
    args = parser.parse_args()

    raw_path = args.raw_path
    if not raw_path.exists():
        print(f"Missing {raw_path}. Run fetch_teams.py first.")
        return

    teams = build_teams_from_raw(raw_path)
    count = write_jsonl(teams, args.out)
    print(f"Parsed {count} teams -> {args.out}")


if __name__ == "__main__":
    main()
