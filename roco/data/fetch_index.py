"""Fetch all pet / skill / yinji page titles.

Usage:
    python scripts/fetch_index.py pets
    python scripts/fetch_index.py skills
    python scripts/fetch_index.py yinji
    python scripts/fetch_index.py all
"""

import re
import sys
from roco.utils import (
    CATEGORY_PETS,
    CATEGORY_SKILLS,
    YINJI_SOURCE_PAGE,
    INDEX_DIR,
    fetch_category_members,
    fetch_page_wikitext,
    save_json,
)

# Matches [[印记名称]] links in the 印记 source page
YINJI_LINK_RE = re.compile(r"\[\[([^\]]+?)\]\]")


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


def fetch_yinji() -> list[str]:
    print(f"Fetching yinji list from page [[{YINJI_SOURCE_PAGE}]] ...")
    text = fetch_page_wikitext(YINJI_SOURCE_PAGE)
    # Extract all [[link]] targets that contain "印记"
    names: list[str] = []
    seen = set()
    for match in YINJI_LINK_RE.finditer(text):
        name = match.group(1).strip()
        if "印记" in name and name not in seen:
            seen.add(name)
            names.append(name)
    print(f"  -> {len(names)} yinji found")
    return names


def main() -> None:
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["all"]
    if "all" in targets:
        targets = ["pets", "skills", "yinji"]

    for target in targets:
        if target == "pets":
            titles = fetch_pets()
            save_json(titles, INDEX_DIR / "pets.json")
        elif target == "skills":
            titles = fetch_skills()
            save_json(titles, INDEX_DIR / "skills.json")
        elif target == "yinji":
            titles = fetch_yinji()
            save_json(titles, INDEX_DIR / "yinji.json")
        else:
            print(f"Unknown target: {target} (use pets / skills / yinji / all)")
            sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()
