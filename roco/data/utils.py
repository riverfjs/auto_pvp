"""Shared I/O and hashing utilities for canonical data files."""

import json
import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Iterator

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "_data"
RAW_DIR = DATA_DIR / "raw"
CANONICAL_DIR = DATA_DIR / "canonical"
RULES_DIR = DATA_DIR / "rules"
DB_DIR = ROOT / "_db"


def save_json(data, path: Path) -> None:
    """Save data as JSON to path, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path: Path) -> dict | list:
    """Load JSON from path."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_jsonl(records: Iterable[dict], path: Path) -> int:
    """Write one JSON object per line and return the record count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            if not isinstance(record, dict):
                raise TypeError(f"JSONL records must be objects, got {type(record).__name__}")
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
            count += 1
    return count


def stable_json(data: object) -> str:
    """Serialize data deterministically for hashes and stable JSONL diffs."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(data: object) -> str:
    """SHA-256 hash of deterministic JSON content."""
    return hashlib.sha256(stable_json(data).encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_hash(record: Mapping[str, object]) -> str:
    payload = {key: value for key, value in record.items() if key != "canonical_hash"}
    return content_hash(payload)


def with_canonical_hash(record: dict, source: Mapping[str, object] | None = None) -> dict:
    """Attach source_hash and canonical_hash to a canonical JSONL record."""
    if source is not None:
        if source_hash := source.get("source_hash"):
            record["source_hash"] = source_hash
        source_title = (
            source.get("source_title")
            or source.get("name")
            or source.get("fulltext")
            or source.get("page_id")
            or ""
        )
        if source_title:
            record["source_title"] = source_title
        if source_kind := source.get("source_kind", source.get("kind", "")):
            record["source_kind"] = source_kind
        if source.get("missing_from_index"):
            record["missing_from_index"] = True
    record["canonical_hash"] = canonical_hash(record)
    return record


def merge_by_key(
    existing: Iterable[dict],
    incoming: Iterable[dict],
    key_fn: Callable[[dict], str],
    *,
    current_keys: set[str] | None = None,
    force: bool = False,
    mark_missing: bool = False,
) -> list[dict]:
    """Merge JSONL rows by key, preserving unchanged existing rows."""
    old = {key_fn(row): row for row in existing if key_fn(row)}
    result: list[dict] = []
    emitted: set[str] = set()
    for row in incoming:
        key = key_fn(row)
        if not key:
            continue
        previous = old.get(key)
        if (
            previous is not None
            and not force
            and previous.get("source_hash")
            and previous.get("source_hash") == row.get("source_hash")
        ):
            kept = dict(previous)
            kept.pop("missing_from_index", None)
            result.append(kept)
        else:
            result.append(row)
        emitted.add(key)
    for key, row in old.items():
        if key in emitted:
            continue
        if force:
            continue
        kept = dict(row)
        if mark_missing and (current_keys is None or key not in current_keys):
            kept["missing_from_index"] = True
        result.append(kept)
    return result


def iter_jsonl(path: Path) -> Iterator[dict]:
    """Yield JSON objects from a JSONL file, skipping blank lines."""
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_no} is not a JSON object")
            yield record


def load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file into a list of object records."""
    return list(iter_jsonl(path))
