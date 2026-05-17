"""Fetch all pet / skill / mark page titles as JSONL records.

Usage:
    python scripts/fetch_index.py pets
    python scripts/fetch_index.py skills
    python scripts/fetch_index.py marks
    python scripts/fetch_index.py all
"""

import argparse
import re
from roco.data.utils import (
    CATEGORY_PETS,
    CATEGORY_SKILLS,
    MARK_SOURCE_PAGE,
    INDEX_DIR,
    fetch_category_members,
    fetch_page_wikitext,
    iter_jsonl,
    write_jsonl,
)

# Matches [[印记名称]] links in the 印记 source page
MARK_LINK_RE = re.compile(r"\[\[([^\]]+?)\]\]")


def fetch_pets() -> list[str]:
    print("Fetching pet list from Category:精灵 ...")
    titles = fetch_category_members(CATEGORY_PETS)
    print(f"  -> {len(titles)} pets found")
    return titles


def fetch_skills() -> list[str]:
    print("Fetching skill list from Category:技能 ...")
    titles = fetch_category_members(CATEGORY_SKILLS)
    print(f"  -> {len(titles)} skills found")
    return titles


def fetch_marks() -> list[str]:
    print(f"Fetching mark list from page [[{MARK_SOURCE_PAGE}]] ...")
    text = fetch_page_wikitext(MARK_SOURCE_PAGE)
    # Extract all [[link]] targets that contain "印记"
    names: list[str] = []
    seen = set()
    for match in MARK_LINK_RE.finditer(text):
        name = match.group(1).strip()
        if "印记" in name and name not in seen:
            seen.add(name)
            names.append(name)
    print(f"  -> {len(names)} marks found")
    return names


def _index_record(target: str, title: str, sort_order: int) -> dict:
    return {
        "kind": "index",
        "target": target,
        "title": title,
        "sort_order": sort_order,
    }


def _merge_index_records(target: str, titles: list[str], *, force: bool = False) -> list[dict]:
    out_path = INDEX_DIR / f"{target}.jsonl"
    incoming = [_index_record(target, title, i) for i, title in enumerate(titles)]
    if force or not out_path.exists():
        return incoming

    old = {str(row.get("title", "")): row for row in iter_jsonl(out_path) if row.get("title")}
    result: list[dict] = []
    seen: set[str] = set()
    for row in incoming:
        title = str(row["title"])
        previous = old.get(title, {})
        merged = dict(previous)
        merged.update(row)
        merged.pop("missing_from_index", None)
        result.append(merged)
        seen.add(title)

    missing = []
    for title, row in old.items():
        if title in seen:
            continue
        kept = dict(row)
        kept["missing_from_index"] = True
        missing.append(kept)
    missing.sort(key=lambda row: (int(row.get("sort_order", len(titles))), str(row.get("title", ""))))
    return result + missing


def fetch_target(target: str, *, force: bool = False) -> None:
    if target == "pets":
        titles = fetch_pets()
    elif target == "skills":
        titles = fetch_skills()
    elif target == "marks":
        titles = fetch_marks()
    else:
        raise ValueError(f"Unknown target: {target}")

    out_path = INDEX_DIR / f"{target}.jsonl"
    records = _merge_index_records(target, titles, force=force)
    count = write_jsonl(records, out_path)
    print(f"Saved {count} index rows -> {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("targets", nargs="*", default=["all"], choices=["pets", "skills", "marks", "all"])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    targets = args.targets
    if "all" in targets:
        targets = ["pets", "skills", "marks"]

    for target in targets:
        fetch_target(target, force=args.force)

    print("Done.")


if __name__ == "__main__":
    main()
