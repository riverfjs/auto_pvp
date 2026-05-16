"""Fetch all PVP/PVE team data via Semantic MediaWiki ask API (one query).

Output: _data/raw/teams_raw.json

Usage:
    python scripts/fetch_teams.py
"""

from roco.data.utils import API_BASE, RAW_DIR, save_json, api_get

# All relevant SMW properties — fetched in a single ask query
PROPS = [
    "阵容标题",
    "阵容类型",
    "阵容血脉魔法",
    "阵容介绍",
    "阵容作者",
    "阵容上传日期",
    "阵容编号",
]
# Per-pet fields (6 slots)
for i in range(1, 7):
    PROPS += [
        f"阵容精灵{i}",
        f"阵容精灵{i}血脉",
        f"阵容精灵{i}性格",
        f"阵容精灵{i}个体值",
        f"阵容精灵{i}技能1",
        f"阵容精灵{i}技能2",
        f"阵容精灵{i}技能3",
        f"阵容精灵{i}技能4",
    ]

PROP_STR = "|?" + "|?".join(PROPS)
QUERY = f"[[分类:精灵阵容]]{PROP_STR}|limit=500|sort=阵容上传日期|order=desc"


def fetch_teams() -> dict:
    """Fetch all teams via SMW ask. Returns raw printouts dict."""
    params = {
        "action": "ask",
        "query": QUERY,
        "format": "json",
    }
    data = api_get(params, use_post=True)
    results = data.get("query", {}).get("results", {})
    print(f"Fetched {len(results)} teams")
    return results


def main() -> None:
    raw = fetch_teams()
    out = RAW_DIR / "teams_raw.json"
    save_json(raw, out)
    print(f"Saved → {out}")


if __name__ == "__main__":
    main()
