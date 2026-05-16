"""Fetch raw wikitext for pets/skills. Supports incremental/batch fetching.

Usage:
    python scripts/fetch_details.py pets                  # all, serial
    python scripts/fetch_details.py pets --limit 5        # first 5 only (for testing)
    python scripts/fetch_details.py pets --workers 5      # parallel, 5 concurrent
    python scripts/fetch_details.py skills --limit 10 -w 5
"""

import sys
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from roco.data.utils import INDEX_DIR, RAW_DIR, fetch_page_wikitext, load_json, save_json


def fetch_one(title: str) -> tuple[str, str | None, str | None]:
    """Returns (title, wikitext_or_none, error_or_none)."""
    try:
        return title, fetch_page_wikitext(title), None
    except Exception as e:
        return title, None, str(e)


def fetch_all(target: str, limit: int | None, workers: int = 1) -> None:
    index_path = INDEX_DIR / f"{target}.json"
    if not index_path.exists():
        print(f"Index file not found: {index_path}")
        print("Run 'python scripts/fetch_index.py {target}' first.")
        sys.exit(1)

    titles: list[str] = load_json(index_path)
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

    out_path = RAW_DIR / f"{target}_raw.json"
    # Merge with existing data if this is a partial fetch
    if out_path.exists() and limit:
        existing = load_json(out_path)
        existing.update(result)
        result = existing

    save_json(result, out_path)
    print(f"Saved {len(result)} entries to {out_path}")
    if errors:
        print(f"Failed ({len(errors)}): {', '.join(errors[:10])}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=["pets", "skills", "yinji"])
    parser.add_argument("--limit", "-n", type=int, default=None)
    parser.add_argument("--workers", "-w", type=int, default=1)
    args = parser.parse_args()
    fetch_all(args.target, args.limit, args.workers)


if __name__ == "__main__":
    main()
