"""Fetch raw wikitext for pets/skills/marks as JSONL records.

Usage:
    python scripts/fetch_details.py pets                  # all, serial
    python scripts/fetch_details.py pets --limit 5        # first 5 only (for testing)
    python scripts/fetch_details.py pets --workers 5      # parallel, 5 concurrent
    python scripts/fetch_details.py skills --limit 10 -w 5
"""

import sys
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from roco.data.utils import INDEX_DIR, RAW_DIR, fetch_page_wikitext, iter_jsonl, write_jsonl


def fetch_one(title: str) -> tuple[str, str | None, str | None]:
    """Returns (title, wikitext_or_none, error_or_none)."""
    try:
        return title, fetch_page_wikitext(title), None
    except Exception as e:
        return title, None, str(e)


def _index_titles(target: str) -> list[str]:
    index_path = INDEX_DIR / f"{target}.jsonl"
    if not index_path.exists():
        print(f"Index file not found: {index_path}")
        print(f"Run 'python -m roco.data.fetch_index {target}' first.")
        sys.exit(1)
    records = sorted(iter_jsonl(index_path), key=lambda row: int(row.get("sort_order", 0)))
    return [str(row["title"]) for row in records]


def _load_existing(path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {str(row["name"]): row for row in iter_jsonl(path)}


def fetch_all(target: str, limit: int | None, workers: int = 1) -> None:
    titles = _index_titles(target)
    if limit:
        titles = titles[:limit]

    result: dict[str, str] = {}
    total = len(titles)
    errors: list[str] = []

    if workers == 1:
        for i, title in enumerate(titles, 1):
            print(f"[{i}/{total}] {title}", flush=True)
            try:
                result[title] = fetch_page_wikitext(title)
            except Exception as e:
                print(f"  ERROR: {e}", flush=True)
                errors.append(title)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch_one, t): t for t in titles}
            done = 0
            for fut in as_completed(futures):
                done += 1
                title, wikitext, err = fut.result()
                print(f"[{done}/{total}] {title}" + (f"  ERROR: {err}" if err else ""), flush=True)
                if wikitext:
                    result[title] = wikitext
                else:
                    errors.append(title)

    out_path = RAW_DIR / f"{target}_raw.jsonl"
    raw_kind = target[:-1] if target.endswith("s") else target

    # Merge with existing data if this is a partial fetch
    if out_path.exists() and limit:
        existing = _load_existing(out_path)
        for title, wikitext in result.items():
            existing[title] = {
                "kind": raw_kind,
                "name": title,
                "source": "wiki:wikitext",
                "raw_text": wikitext,
            }
        records = sorted(existing.values(), key=lambda row: titles.index(row["name"]) if row["name"] in titles else total)
    else:
        records = [
            {
                "kind": raw_kind,
                "name": title,
                "source": "wiki:wikitext",
                "raw_text": result[title],
            }
            for title in titles
            if title in result
        ]

    count = write_jsonl(records, out_path)
    print(f"Saved {count} entries to {out_path}")
    if errors:
        print(f"Failed ({len(errors)}): {', '.join(errors[:10])}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=["pets", "skills", "marks"])
    parser.add_argument("--limit", "-n", type=int, default=None)
    parser.add_argument("--workers", "-w", type=int, default=1)
    args = parser.parse_args()
    fetch_all(args.target, args.limit, args.workers)


if __name__ == "__main__":
    main()
