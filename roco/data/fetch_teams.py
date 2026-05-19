"""Fetch all PVP/PVE team data via Semantic MediaWiki ask API as JSONL.

Output: _data/raw/teams_raw.jsonl

Usage:
    python scripts/fetch_teams.py
"""

import argparse

from roco.data.bwiki_api import api_get
from roco.data.utils import RAW_DIR, content_hash, iter_jsonl, merge_by_key, utc_now_iso, write_jsonl

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


def _team_raw_record(page_id: str, raw_team: dict, fetched_at: str) -> dict:
    fulltext = raw_team.get("fulltext", "")
    fullurl = raw_team.get("fullurl", "")
    printouts = raw_team.get("printouts", {})
    payload = {"fulltext": fulltext, "fullurl": fullurl, "printouts": printouts}
    return {
        "kind": "team_raw",
        "page_id": page_id,
        "source_title": fulltext or page_id,
        "source_kind": "team_raw",
        "source": "wiki:smw_ask",
        "fulltext": fulltext,
        "fullurl": fullurl,
        "printouts": printouts,
        "source_hash": content_hash(payload),
        "fetched_at": fetched_at,
    }


def fetch_teams(*, fetched_at: str | None = None) -> list[dict]:
    """Fetch all teams via SMW ask. Returns raw printouts dict."""
    params = {
        "action": "ask",
        "query": QUERY,
        "format": "json",
    }
    data = api_get(params, use_post=True)
    results = data.get("query", {}).get("results", {})
    print(f"Fetched {len(results)} teams")
    fetched_at = fetched_at or utc_now_iso()
    return [_team_raw_record(page_id, raw_team, fetched_at) for page_id, raw_team in results.items()]


def _merge_team_records(incoming: list[dict], *, force: bool = False) -> list[dict]:
    out = RAW_DIR / "teams_raw.jsonl"
    existing = list(iter_jsonl(out)) if out.exists() else []
    return merge_by_key(
        existing,
        incoming,
        lambda row: str(row.get("page_id", "")),
        current_keys={str(row.get("page_id", "")) for row in incoming},
        force=force,
        mark_missing=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    records = _merge_team_records(fetch_teams(), force=args.force)
    out = RAW_DIR / "teams_raw.jsonl"
    count = write_jsonl(records, out)
    print(f"Saved {count} rows -> {out}")


if __name__ == "__main__":
    main()
