"""Loader + spec table for the BUFF_CONF-direct immunity rules.

The single source of truth for immunity flag bits is :data:`IMMUNITY_SPECS`
in this module: tag (rule key) ↔ const_name (generated symbol) ↔ bit
(packed-flag bit) ↔ keyword (Chinese substring that must appear in the
pak ``BUFF_CONF.desc`` text).  Adding a new immunity means appending one
row at the end of the tuple — never reordering.

Downstream consumers (the codegen for ``roco/generated/buff_immunity_table.py``
and the catalog) import :data:`IMMUNITY_SPECS` from here.  The loader
defined in this module is purely a strict JSONL validator + builder that
returns ``dict[int, int]`` (buff_id → packed flags); it does not touch
the kernel or the runtime decoder pipeline.

Phase 2A only ships this data layer; runtime kernel integration is
deferred until the engine has an active-buff lifecycle model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple


class ImmunitySpec(NamedTuple):
    tag: str
    const_name: str
    bit: int
    keyword: str


# Order matters: bit values are explicit; never renumber.  Append-only.
IMMUNITY_SPECS: tuple[ImmunitySpec, ...] = (
    ImmunitySpec("force_switch", "IMMUNITY_FORCE_SWITCH", 0x01, "吹飞"),
    ImmunitySpec("poison",       "IMMUNITY_POISON",       0x02, "中毒"),
    ImmunitySpec("burn",         "IMMUNITY_BURN",         0x04, "灼烧"),
    ImmunitySpec("freeze",       "IMMUNITY_FREEZE",       0x08, "冻结"),
    ImmunitySpec("leech",        "IMMUNITY_LEECH",        0x10, "寄生"),
    ImmunitySpec("energy_drain", "IMMUNITY_ENERGY_DRAIN", 0x20, "倾泻"),
)


def _validate_specs() -> None:
    """Module-import-time invariants on :data:`IMMUNITY_SPECS`.

    Catches duplicate tags / const names / bits and non-power-of-two bits;
    those are merge-conflict-class regressions that would silently miscount
    flags.
    """
    tags = [s.tag for s in IMMUNITY_SPECS]
    consts = [s.const_name for s in IMMUNITY_SPECS]
    bits = [s.bit for s in IMMUNITY_SPECS]
    if len(set(tags)) != len(tags):
        raise RuntimeError(f"IMMUNITY_SPECS has duplicate tags: {tags}")
    if len(set(consts)) != len(consts):
        raise RuntimeError(f"IMMUNITY_SPECS has duplicate const_names: {consts}")
    if len(set(bits)) != len(bits):
        raise RuntimeError(f"IMMUNITY_SPECS has duplicate bits: {bits}")
    for s in IMMUNITY_SPECS:
        if s.bit <= 0 or (s.bit & (s.bit - 1)) != 0:
            raise RuntimeError(
                f"IMMUNITY_SPECS bit must be a positive power of two; got "
                f"{s.bit!r} for tag {s.tag!r}"
            )
        if not s.keyword:
            raise RuntimeError(f"IMMUNITY_SPECS keyword empty for tag {s.tag!r}")


_validate_specs()


_DEFAULT_RULES_PATH = (
    Path(__file__).resolve().parents[2]
    / "compiler"
    / "rules"
    / "buff_immunity.jsonl"
)
_DEFAULT_BUFF_CONF_PATH = (
    Path(__file__).resolve().parents[3]
    / "pak-public-kit"
    / "output"
    / "data"
    / "BinData"
    / "BUFF_CONF.json"
)


def _load_buff_conf() -> dict[int, dict]:
    with _DEFAULT_BUFF_CONF_PATH.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    rows = data.get("RocoDataRows", data)
    return {int(k): v for k, v in rows.items()}


def _tag_to_spec() -> dict[str, ImmunitySpec]:
    return {s.tag: s for s in IMMUNITY_SPECS}


def load_buff_immunity_table(
    rules_path: Path | None = None,
    buff_conf: dict[int, dict] | None = None,
) -> dict[int, int]:
    """Parse ``buff_immunity.jsonl`` into ``buff_id → packed_flags``.

    Strict validation:

    * Each row's ``buff_id`` must exist in the supplied (or default-loaded)
      ``buff_conf``.
    * ``pak_desc`` must equal ``buff_conf[buff_id]["desc"]`` character for
      character — no normalisation.
    * Every tag in ``immunities`` must appear in :data:`IMMUNITY_SPECS`,
      and the corresponding ``keyword`` must be a substring of
      ``pak_desc``.
    * ``evidence`` must start with ``BUFF_CONF.json[<buff_id>].desc=``.

    Returns ``{buff_id: packed_flags}``.

    ``rules_path`` / ``buff_conf`` are injectable so tests can drive the
    loader against a tmp file + stub table without touching the real
    rules or pak data.
    """
    path = rules_path if rules_path is not None else _DEFAULT_RULES_PATH
    conf = buff_conf if buff_conf is not None else _load_buff_conf()
    tag_specs = _tag_to_spec()

    out: dict[int, int] = {}
    first_seen_line: dict[int, int] = {}
    with path.open("r", encoding="utf-8") as fp:
        for line_no, raw in enumerate(fp, 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            rec = json.loads(raw)
            buff_id = int(rec["buff_id"])
            if buff_id in first_seen_line:
                raise RuntimeError(
                    f"buff_immunity.jsonl line {line_no}: duplicate buff_id "
                    f"{buff_id} (already defined on line "
                    f"{first_seen_line[buff_id]})"
                )
            first_seen_line[buff_id] = line_no
            if buff_id not in conf:
                raise RuntimeError(
                    f"buff_immunity.jsonl line {line_no}: buff_id {buff_id} "
                    f"not in BUFF_CONF"
                )
            pak_desc = str(rec.get("pak_desc", ""))
            if len(pak_desc) > 256:
                raise RuntimeError(
                    f"buff_immunity.jsonl line {line_no}: pak_desc longer than "
                    f"256 chars"
                )
            real_desc = str(conf[buff_id].get("desc", ""))
            if pak_desc != real_desc:
                raise RuntimeError(
                    f"buff_immunity.jsonl line {line_no}: pak_desc {pak_desc!r} "
                    f"does not match BUFF_CONF[{buff_id}].desc {real_desc!r}"
                )
            tags = rec.get("immunities") or []
            if not isinstance(tags, list) or not tags:
                raise RuntimeError(
                    f"buff_immunity.jsonl line {line_no}: ``immunities`` must "
                    f"be a non-empty list"
                )
            flags = 0
            for tag in tags:
                if tag not in tag_specs:
                    raise RuntimeError(
                        f"buff_immunity.jsonl line {line_no}: unknown immunity "
                        f"tag {tag!r}; allowed: {sorted(tag_specs)}"
                    )
                spec = tag_specs[tag]
                if spec.keyword not in pak_desc:
                    raise RuntimeError(
                        f"buff_immunity.jsonl line {line_no}: immunity tag "
                        f"{tag!r} requires keyword {spec.keyword!r} to appear "
                        f"in pak_desc {pak_desc!r}"
                    )
                flags |= spec.bit
            evidence = str(rec.get("evidence", ""))
            expected_prefix = f"BUFF_CONF.json[{buff_id}].desc="
            if not evidence.startswith(expected_prefix):
                raise RuntimeError(
                    f"buff_immunity.jsonl line {line_no}: evidence must start "
                    f"with {expected_prefix!r}; got {evidence!r}"
                )
            out[buff_id] = flags
    return out
