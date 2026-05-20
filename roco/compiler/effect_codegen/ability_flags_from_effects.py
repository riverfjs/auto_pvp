"""Strict loader for ``rules/ability_flags_from_effects.jsonl``.

The rules table maps pak ``EFFECT_CONF.id`` to a :class:`AbilityFlag`
member *name*; the codegen layer (:mod:`roco.compiler.codegen.ability_flags_codegen`)
joins that mapping with the ``ability_effect_ids`` SQLite table to
populate ``ABILITY_FLAGS`` in :mod:`roco.generated.catalog_hot`.

This loader is **the** authority for that bridge.  It is intentionally
strict: any drift between the rules file and pak (renamed editor_name,
unknown flag name, unsupported multiplier, evidence format) is reported
loud with the file line so a stale rule cannot silently mask reality.

Default JSON sources:

* Rules: ``roco/compiler/rules/ability_flags_from_effects.jsonl``
* Pak ``EFFECT_CONF``:
  ``pak-public-kit/output/data/BinData/EFFECT_CONF.json``.  There is no
  canonical effects.jsonl in this project — do not look for one.

The loader returns ``dict[int, AbilityFlagOutcome]`` so callers can feed
the same map to :func:`classify.decode_effect` and to
:func:`build_effect_families._classify_one_source_id`.
"""

from __future__ import annotations

import json
from pathlib import Path

from roco.common.enums import AbilityFlag
from roco.compiler.effect_codegen.outcomes import AbilityFlagOutcome


_DEFAULT_RULES_PATH = (
    Path(__file__).resolve().parents[2]
    / "compiler"
    / "rules"
    / "ability_flags_from_effects.jsonl"
)
_DEFAULT_EFFECT_CONF_PATH = (
    Path(__file__).resolve().parents[3]
    / "pak-public-kit"
    / "output"
    / "data"
    / "BinData"
    / "EFFECT_CONF.json"
)


def _load_effect_conf() -> dict[int, dict]:
    with _DEFAULT_EFFECT_CONF_PATH.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    rows = data.get("RocoDataRows", data)
    return {int(k): v for k, v in rows.items()}


def load_ability_flags_from_effects(
    rules_path: Path | None = None,
    effect_conf: dict[int, dict] | None = None,
) -> dict[int, AbilityFlagOutcome]:
    """Parse ``ability_flags_from_effects.jsonl`` into ``effect_id → outcome``.

    Strict validation (every check raises ``RuntimeError`` with file + line):

    * ``#``-prefixed lines and blank lines are skipped.
    * ``effect_id`` must exist in ``effect_conf``.
    * ``pak_editor_name`` must equal ``effect_conf[effect_id].editor_name``
      character-for-character (drift guard).
    * ``flag`` must be a member name of :class:`AbilityFlag`.
    * ``evidence`` must start with ``EFFECT_CONF.json[<effect_id>].editor_name=``.
    * Duplicate ``effect_id`` rejected with both line numbers.
    * ``effect_param`` shape: exactly 2 slots, ``[0]`` non-empty list of
      ints, ``[1]`` strictly equal to ``[1]``.  Anything else (multipliers
      ``!= 1``, missing slot, wrong length) is rejected loudly — extending
      the multiplier semantics requires an explicit schema bump.

    ``rules_path`` / ``effect_conf`` are injectable so tests can drive the
    loader against tmp files + stub tables without touching real pak data.
    """
    path = rules_path if rules_path is not None else _DEFAULT_RULES_PATH
    conf = effect_conf if effect_conf is not None else _load_effect_conf()

    out: dict[int, AbilityFlagOutcome] = {}
    first_seen_line: dict[int, int] = {}
    with path.open("r", encoding="utf-8") as fp:
        for line_no, raw in enumerate(fp, 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"ability_flags_from_effects.jsonl line {line_no}: "
                    f"invalid JSON ({exc})"
                ) from None

            effect_id = int(rec.get("effect_id", 0))
            if effect_id <= 0:
                raise RuntimeError(
                    f"ability_flags_from_effects.jsonl line {line_no}: "
                    f"effect_id must be a positive integer"
                )
            if effect_id in first_seen_line:
                raise RuntimeError(
                    f"ability_flags_from_effects.jsonl line {line_no}: "
                    f"duplicate effect_id {effect_id} (already defined on line "
                    f"{first_seen_line[effect_id]})"
                )
            first_seen_line[effect_id] = line_no

            if effect_id not in conf:
                raise RuntimeError(
                    f"ability_flags_from_effects.jsonl line {line_no}: "
                    f"effect_id {effect_id} not in EFFECT_CONF"
                )

            real_editor_name = str(conf[effect_id].get("editor_name", ""))
            pak_editor_name = str(rec.get("pak_editor_name", ""))
            if pak_editor_name != real_editor_name:
                raise RuntimeError(
                    f"ability_flags_from_effects.jsonl line {line_no}: "
                    f"pak_editor_name {pak_editor_name!r} does not match "
                    f"EFFECT_CONF[{effect_id}].editor_name {real_editor_name!r}"
                )

            flag_name = str(rec.get("flag", ""))
            if not flag_name:
                raise RuntimeError(
                    f"ability_flags_from_effects.jsonl line {line_no}: "
                    f"flag must be a non-empty string"
                )
            try:
                AbilityFlag[flag_name]
            except KeyError:
                raise RuntimeError(
                    f"ability_flags_from_effects.jsonl line {line_no}: "
                    f"flag {flag_name!r} is not an AbilityFlag member; "
                    f"valid names: {sorted(m.name for m in AbilityFlag)}"
                ) from None

            evidence = str(rec.get("evidence", ""))
            expected_prefix = f"EFFECT_CONF.json[{effect_id}].editor_name="
            if not evidence.startswith(expected_prefix):
                raise RuntimeError(
                    f"ability_flags_from_effects.jsonl line {line_no}: "
                    f"evidence must start with {expected_prefix!r}; got {evidence!r}"
                )

            effect_param = conf[effect_id].get("effect_param")
            if not isinstance(effect_param, list) or len(effect_param) != 2:
                raise RuntimeError(
                    f"ability_flags_from_effects.jsonl line {line_no}: "
                    f"EFFECT_CONF[{effect_id}].effect_param expected length 2, "
                    f"got {effect_param!r}. New effect_param shape requires "
                    f"schema extension before this loader can accept it."
                )
            # Pak stores each slot as ``{"params": [...]}``; unwrap once
            # and validate the inner shape.  Anything else (bare list,
            # missing "params" key, extra keys, non-int values) fails.
            slot0 = effect_param[0]
            if not isinstance(slot0, dict) or list(slot0.keys()) != ["params"]:
                raise RuntimeError(
                    f"ability_flags_from_effects.jsonl line {line_no}: "
                    f"EFFECT_CONF[{effect_id}].effect_param[0] expected "
                    f"{{'params': [...]}} shape, got {slot0!r}"
                )
            slot0_values = slot0["params"]
            if not isinstance(slot0_values, list) or not slot0_values or not all(isinstance(v, int) for v in slot0_values):
                raise RuntimeError(
                    f"ability_flags_from_effects.jsonl line {line_no}: "
                    f"EFFECT_CONF[{effect_id}].effect_param[0].params expected "
                    f"a non-empty list of ints, got {slot0_values!r}"
                )
            slot1 = effect_param[1]
            if not isinstance(slot1, dict) or list(slot1.keys()) != ["params"]:
                raise RuntimeError(
                    f"ability_flags_from_effects.jsonl line {line_no}: "
                    f"EFFECT_CONF[{effect_id}].effect_param[1] expected "
                    f"{{'params': [...]}} shape, got {slot1!r}"
                )
            if slot1["params"] != [1]:
                raise RuntimeError(
                    f"ability_flags_from_effects.jsonl line {line_no}: "
                    f"EFFECT_CONF[{effect_id}].effect_param[1].params expected "
                    f"exactly [1], got {slot1['params']!r}. New multiplier shape "
                    f"requires schema extension before this loader can accept it."
                )

            out[effect_id] = AbilityFlagOutcome(effect_id=effect_id, flag_name=flag_name)
    return out


def normalized_payload(table: dict[int, AbilityFlagOutcome]) -> tuple[tuple[int, str], ...]:
    """Stable-sorted ``(effect_id, flag_name)`` tuple for SOURCE_HASH inputs.

    Sorted by ``effect_id`` so the payload is deterministic across runs;
    any addition / removal / flag rename in the rules file changes the
    payload and therefore the hash.
    """
    return tuple(sorted(
        ((eid, outcome.flag_name) for eid, outcome in table.items()),
        key=lambda pair: pair[0],
    ))
