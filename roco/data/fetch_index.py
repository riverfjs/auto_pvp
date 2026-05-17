"""Fetch all pet / skill / mark page titles as JSONL records.

Usage:
    python scripts/fetch_index.py pets
    python scripts/fetch_index.py skills
    python scripts/fetch_index.py marks
    python scripts/fetch_index.py all
"""

import re
import sys
from roco.data.utils import (
    CATEGORY_PETS,
    CATEGORY_SKILLS,
    MARK_SOURCE_PAGE,
    INDEX_DIR,
    fetch_category_members,
    fetch_page_wikitext,
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


def main() -> None:
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["all"]
    if "all" in targets:
        targets = ["pets", "skills", "marks"]

    for target in targets:
        if target == "pets":
            titles = fetch_pets()
        elif target == "skills":
            titles = fetch_skills()
        elif target == "marks":
            titles = fetch_marks()
        else:
            print(f"Unknown target: {target} (use pets / skills / marks / all)")
            sys.exit(1)
        records = (
            {"kind": "index", "target": target, "title": title, "sort_order": i}
            for i, title in enumerate(titles)
        )
        out_path = INDEX_DIR / f"{target}.jsonl"
        count = write_jsonl(records, out_path)
        print(f"Saved {count} index rows -> {out_path}")

    print("Done.")


if __name__ == "__main__":
    main()
