"""Fetch raw wikitext for pets/skills/marks as JSONL records.

Usage:
    python scripts/fetch_details.py pets                  # all, serial
    python scripts/fetch_details.py pets --limit 5        # first 5 only (for testing)
    python scripts/fetch_details.py pets --workers 5      # parallel, 5 concurrent
    python scripts/fetch_details.py skills --limit 10 -w 5
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from roco.data.utils import (
    INDEX_DIR,
    RAW_DIR,
    content_hash,
    fetch_page_wikitext,
    iter_jsonl,
    merge_by_key,
    utc_now_iso,
    WikiPageMissing,
    write_jsonl,
)


def fetch_one(title: str) -> tuple[str, str | None, str | None, bool]:
    """Returns (title, wikitext_or_none, error_or_none, missing_page)."""
    try:
        return title, fetch_page_wikitext(title), None, False
    except WikiPageMissing as e:
        return title, None, str(e), True
    except Exception as e:
        return title, None, str(e), False


def _index_titles(target: str) -> list[str]:
    index_path = INDEX_DIR / f"{target}.jsonl"
    if not index_path.exists():
        print(f"Index file not found: {index_path}")
        print(f"Run 'python -m roco.data.fetch_index {target}' first.")
        raise SystemExit(1)
    records = sorted(iter_jsonl(index_path), key=lambda row: int(row.get("sort_order", 0)))
    records = [row for row in records if not row.get("missing_from_index")]
    return [str(row["title"]) for row in records]


def _raw_record(target: str, title: str, wikitext: str, fetched_at: str) -> dict:
    raw_kind = target[:-1] if target.endswith("s") else target
    return {
        "kind": raw_kind,
        "name": title,
        "source_title": title,
        "source_kind": raw_kind,
        "source": "wiki:wikitext",
        "raw_text": wikitext,
        "source_hash": content_hash({"raw_text": wikitext}),
        "fetched_at": fetched_at,
    }


def _missing_raw_record(target: str, title: str, error: str, fetched_at: str) -> dict:
    raw_kind = target[:-1] if target.endswith("s") else target
    return {
        "kind": raw_kind,
        "name": title,
        "source_title": title,
        "source_kind": raw_kind,
        "source": "wiki:wikitext",
        "raw_text": "",
        "missing_source_page": True,
        "source_error": error,
        "source_hash": content_hash({"missing_source_page": True, "source_error": error}),
        "fetched_at": fetched_at,
    }


def _merge_raw_records(
    target: str,
    index_titles: list[str],
    fetched_titles: list[str],
    result: dict[str, str],
    missing: dict[str, str] | None = None,
    *,
    force: bool,
    fetched_at: str,
) -> list[dict]:
    out_path = RAW_DIR / f"{target}_raw.jsonl"
    incoming = [_raw_record(target, title, result[title], fetched_at) for title in fetched_titles if title in result]
    missing = missing or {}
    incoming.extend(_missing_raw_record(target, title, missing[title], fetched_at) for title in fetched_titles if title in missing)
    existing = list(iter_jsonl(out_path)) if out_path.exists() else []
    merged = merge_by_key(
        existing,
        incoming,
        lambda row: str(row.get("name", row.get("source_title", ""))),
        current_keys=set(index_titles),
        force=force,
        mark_missing=len(fetched_titles) == len(index_titles),
    )
    order = {title: index for index, title in enumerate(index_titles)}
    return sorted(
        merged,
        key=lambda row: (
            order.get(str(row.get("name", row.get("source_title", ""))), len(order) + 1),
            str(row.get("name", row.get("source_title", ""))),
        ),
    )


def fetch_all(target: str, limit: int | None, workers: int = 1, *, force: bool = False) -> None:
    titles = _index_titles(target)
    all_titles = titles
    if limit:
        titles = titles[:limit]

    result: dict[str, str] = {}
    missing: dict[str, str] = {}
    total = len(titles)
    errors: list[str] = []

    if workers == 1:
        for i, title in enumerate(titles, 1):
            print(f"[{i}/{total}] {title}", flush=True)
            try:
                result[title] = fetch_page_wikitext(title)
            except WikiPageMissing as e:
                print(f"  MISSING: {e}", flush=True)
                missing[title] = str(e)
            except Exception as e:
                print(f"  ERROR: {e}", flush=True)
                errors.append(title)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch_one, t): t for t in titles}
            done = 0
            for fut in as_completed(futures):
                done += 1
                title, wikitext, err, is_missing = fut.result()
                label = "MISSING" if is_missing else "ERROR"
                print(f"[{done}/{total}] {title}" + (f"  {label}: {err}" if err else ""), flush=True)
                if wikitext:
                    result[title] = wikitext
                elif is_missing and err:
                    missing[title] = err
                else:
                    errors.append(title)

    if errors:
        print(f"Failed ({len(errors)}): {', '.join(errors[:10])}")
        raise SystemExit(2)

    out_path = RAW_DIR / f"{target}_raw.jsonl"
    records = _merge_raw_records(target, all_titles, titles, result, missing, force=force, fetched_at=utc_now_iso())

    count = write_jsonl(records, out_path)
    print(f"Saved {count} entries to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=["pets", "skills", "marks"])
    parser.add_argument("--limit", "-n", type=int, default=None)
    parser.add_argument("--workers", "-w", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    fetch_all(args.target, args.limit, args.workers, force=args.force)


if __name__ == "__main__":
    main()
