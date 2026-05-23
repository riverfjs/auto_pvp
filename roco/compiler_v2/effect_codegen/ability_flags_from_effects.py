"""Strict loader for ability passive flag semantics.

Pak ability rows point at either ``EFFECT_CONF`` rows or direct
``BUFF_CONF`` rows.  Production derivation follows that structure:
``SKILL_CONF(type=2).skill_result`` gives the referenced ids, and
``BUFF_CONF -> BUFFBASE_CONF`` supplies the semantic axis.  The artifact
layer joins the derived ``skill_result.effect_id → AbilityFlag`` map
with the ``ability_effect_ids`` SQLite table to populate
``ABILITY_FLAGS`` in :mod:`roco.generated.catalog_hot`.

This loader is intentionally strict: unsupported multiplier or fixture
evidence format is reported loudly.  Temporary fixture files may still
pin old ``editor_name`` drift checks, but the production path does not
depend on pak ``editor_name``.

The loader returns ``dict[int, AbilityFlagOutcome]`` so callers can feed
the same map to :func:`classify.decode_effect` and to
:func:`build_effect_families._classify_one_source_id`.
"""

from __future__ import annotations

import json
from pathlib import Path

from roco.common.enums import AbilityFlag
from roco.compiler_v2.effect_codegen.outcomes import AbilityFlagOutcome

_DEFAULT_EFFECT_CONF_PATH = (
    Path(__file__).resolve().parents[3]
    / "pak-public-kit"
    / "output"
    / "data"
    / "BinData"
    / "EFFECT_CONF.json"
)
_DEFAULT_BUFF_CONF_PATH = (
    Path(__file__).resolve().parents[3]
    / "pak-public-kit"
    / "output"
    / "data"
    / "BinData"
    / "BUFF_CONF.json"
)
_DEFAULT_BUFFBASE_CONF_PATH = (
    Path(__file__).resolve().parents[3]
    / "pak-public-kit"
    / "output"
    / "data"
    / "BinData"
    / "BUFFBASE_CONF.json"
)
_DEFAULT_DESC_NOTE_CONF_PATH = (
    Path(__file__).resolve().parents[3]
    / "pak-public-kit"
    / "output"
    / "data"
    / "BinData"
    / "DESC_NOTE_CONF.json"
)
_DEFAULT_SKILL_CONF_PATH = (
    Path(__file__).resolve().parents[3]
    / "pak-public-kit"
    / "output"
    / "data"
    / "BinData"
    / "SKILL_CONF.json"
)

ABILITY_SKILL_TYPE = 2
EFFECT_ORDER_HEAL_ON_STATUS_DAMAGE = 76
BUFFBASE_ORDER_MARK_STACK_NO_REPLACE = 143
BUFFBASE_ORDER_HEAL_ON_STATUS_DAMAGE = 154

DESC_POISON = 1001
DESC_BURN = 1002
DESC_LEECH = 1008
DESC_POISON_MARK = 1014


def _load_rows(path: Path) -> dict[int, dict]:
    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    rows = data.get("RocoDataRows", data)
    return {int(k): v for k, v in rows.items()}


def _load_effect_conf() -> dict[int, dict]:
    return _load_rows(_DEFAULT_EFFECT_CONF_PATH)


def _load_buff_conf() -> dict[int, dict]:
    return _load_rows(_DEFAULT_BUFF_CONF_PATH)


def _load_buffbase_conf() -> dict[int, dict]:
    return _load_rows(_DEFAULT_BUFFBASE_CONF_PATH)


def _load_desc_note_conf() -> dict[int, dict]:
    return _load_rows(_DEFAULT_DESC_NOTE_CONF_PATH)


def _load_skill_conf() -> dict[int, dict]:
    return _load_rows(_DEFAULT_SKILL_CONF_PATH)


def load_ability_flags_from_effects(
    rules_path: Path | None = None,
    effect_conf: dict[int, dict] | None = None,
    buff_conf: dict[int, dict] | None = None,
    buffbase_conf: dict[int, dict] | None = None,
    desc_note_conf: dict[int, dict] | None = None,
    skill_conf: dict[int, dict] | None = None,
) -> dict[int, AbilityFlagOutcome]:
    """Load ability-flag semantics into ``effect_id → outcome``.

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

    ``rules_path`` is retained only for validation tests with temporary
    fixture records; the default production path derives directly from
    pak structure.
    """
    conf = effect_conf if effect_conf is not None else _load_effect_conf()
    buff_rows = buff_conf if buff_conf is not None else _load_buff_conf()

    if rules_path is None:
        base_rows = buffbase_conf if buffbase_conf is not None else _load_buffbase_conf()
        desc_rows = desc_note_conf if desc_note_conf is not None else _load_desc_note_conf()
        default_tables = (
            effect_conf is None
            and buff_conf is None
            and buffbase_conf is None
            and desc_note_conf is None
            and skill_conf is None
        )
        skill_rows = skill_conf if skill_conf is not None else (
            _load_skill_conf() if default_tables else None
        )
        ability_refs = _ability_skill_result_refs(skill_rows) if skill_rows is not None else None
        return _derive_ability_flags(conf, buff_rows, base_rows, desc_rows, ability_refs)

    out: dict[int, AbilityFlagOutcome] = {}
    first_seen_line: dict[int, int] = {}
    for line_no, rec in _iter_rule_records(rules_path, conf, buff_rows):
        effect_id = int(rec.get("effect_id", 0))
        if effect_id <= 0:
            raise RuntimeError(
                f"ability flag fixture line {line_no}: "
                f"effect_id must be a positive integer"
            )
        if effect_id in first_seen_line:
            raise RuntimeError(
                f"ability flag fixture line {line_no}: "
                f"duplicate effect_id {effect_id} (already defined on line "
                f"{first_seen_line[effect_id]})"
            )
        first_seen_line[effect_id] = line_no

        source_table = str(rec.get("source_table") or "EFFECT_CONF")
        if source_table == "BUFF_CONF":
            real = buff_rows.get(effect_id)
            if real is None:
                raise RuntimeError(
                    f"ability flag fixture line {line_no}: "
                    f"effect_id {effect_id} not in BUFF_CONF"
                )
            _validate_buff_flag_record(line_no, effect_id, rec, real)
            flag_name = str(rec.get("flag", ""))
            out[effect_id] = AbilityFlagOutcome(effect_id=effect_id, flag_name=flag_name)
            continue

        if source_table != "EFFECT_CONF":
            raise RuntimeError(
                f"ability flag fixture line {line_no}: "
                f"source_table {source_table!r} is not supported"
            )

        if effect_id not in conf:
            raise RuntimeError(
                f"ability flag fixture line {line_no}: "
                f"effect_id {effect_id} not in EFFECT_CONF"
            )

        real_editor_name = str(conf[effect_id].get("editor_name", ""))
        pak_editor_name = str(rec.get("pak_editor_name", ""))
        if pak_editor_name != real_editor_name:
            raise RuntimeError(
                f"ability flag fixture line {line_no}: "
                f"pak_editor_name {pak_editor_name!r} does not match "
                f"EFFECT_CONF[{effect_id}].editor_name {real_editor_name!r}"
            )

        flag_name = str(rec.get("flag", ""))
        if not flag_name:
            raise RuntimeError(
                f"ability flag fixture line {line_no}: "
                f"flag must be a non-empty string"
            )
        try:
            AbilityFlag[flag_name]
        except KeyError:
            raise RuntimeError(
                f"ability flag fixture line {line_no}: "
                f"flag {flag_name!r} is not an AbilityFlag member; "
                f"valid names: {sorted(m.name for m in AbilityFlag)}"
            ) from None

        evidence = str(rec.get("evidence", ""))
        expected_prefix = f"EFFECT_CONF.json[{effect_id}].editor_name="
        if not evidence.startswith(expected_prefix):
            raise RuntimeError(
                f"ability flag fixture line {line_no}: "
                f"evidence must start with {expected_prefix!r}; got {evidence!r}"
            )

        effect_param = conf[effect_id].get("effect_param")
        if not isinstance(effect_param, list) or len(effect_param) != 2:
            raise RuntimeError(
                f"ability flag fixture line {line_no}: "
                f"EFFECT_CONF[{effect_id}].effect_param expected length 2, "
                f"got {effect_param!r}. New effect_param shape requires "
                f"schema extension before this loader can accept it."
            )
        slot0 = effect_param[0]
        if not isinstance(slot0, dict) or list(slot0.keys()) != ["params"]:
            raise RuntimeError(
                f"ability flag fixture line {line_no}: "
                f"EFFECT_CONF[{effect_id}].effect_param[0] expected "
                f"{{'params': [...]}} shape, got {slot0!r}"
            )
        slot0_values = slot0["params"]
        if (
            not isinstance(slot0_values, list)
            or not slot0_values
            or not all(isinstance(v, int) for v in slot0_values)
        ):
            raise RuntimeError(
                f"ability flag fixture line {line_no}: "
                f"EFFECT_CONF[{effect_id}].effect_param[0].params expected "
                f"a non-empty list of ints, got {slot0_values!r}"
            )
        slot1 = effect_param[1]
        if not isinstance(slot1, dict) or list(slot1.keys()) != ["params"]:
            raise RuntimeError(
                f"ability flag fixture line {line_no}: "
                f"EFFECT_CONF[{effect_id}].effect_param[1] expected "
                f"{{'params': [...]}} shape, got {slot1!r}"
            )
        if slot1["params"] != [1]:
            raise RuntimeError(
                f"ability flag fixture line {line_no}: "
                f"EFFECT_CONF[{effect_id}].effect_param[1].params expected "
                f"exactly [1], got {slot1['params']!r}. New multiplier shape "
                f"requires schema extension before this loader can accept it."
            )

        out[effect_id] = AbilityFlagOutcome(effect_id=effect_id, flag_name=flag_name)
    return out


def _iter_rule_records(
    rules_path: Path | None,
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
) -> list[tuple[int, dict]]:
    if rules_path is None:
        return []
    out: list[tuple[int, dict]] = []
    with rules_path.open("r", encoding="utf-8") as fp:
        for line_no, raw in enumerate(fp, 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            try:
                out.append((line_no, json.loads(raw)))
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"ability_flags_from_effects rules line {line_no}: "
                    f"invalid JSON ({exc})"
                ) from None
    return out


def _derive_ability_flags(
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
    buffbase_conf: dict[int, dict],
    desc_note_conf: dict[int, dict],
    ability_refs: set[int] | None,
) -> dict[int, AbilityFlagOutcome]:
    out: dict[int, AbilityFlagOutcome] = {}
    desc_notes = _desc_notes(desc_note_conf)

    for effect_id, rec in sorted(effect_conf.items()):
        if ability_refs is not None and effect_id not in ability_refs:
            continue
        flag = _flag_from_effect_row(rec, buff_conf, desc_notes)
        if flag is not None:
            _put_flag(out, effect_id, flag, "EFFECT_CONF")

    for buff_id, rec in sorted(buff_conf.items()):
        if ability_refs is not None and buff_id not in ability_refs:
            continue
        flag = _flag_from_buff_row(rec, buff_conf, buffbase_conf, desc_notes)
        if flag is not None:
            _put_flag(out, buff_id, flag, "BUFF_CONF")

    return out


def _ability_skill_result_refs(skill_conf: dict[int, dict]) -> set[int]:
    refs: set[int] = set()
    for rec in skill_conf.values():
        if int(rec.get("type") or 0) != ABILITY_SKILL_TYPE:
            continue
        for entry in rec.get("skill_result") or []:
            if not isinstance(entry, dict):
                continue
            effect_id = _maybe_int(entry.get("effect_id"))
            if effect_id > 0:
                refs.add(effect_id)
    return refs


def _desc_notes(desc_note_conf: dict[int, dict]) -> dict[int, str]:
    return {
        desc_id: str(rec.get("note", "")).strip()
        for desc_id, rec in desc_note_conf.items()
        if isinstance(rec, dict)
    }


def _flag_from_effect_row(
    rec: dict,
    buff_conf: dict[int, dict],
    desc_notes: dict[int, str],
) -> str | None:
    if int(rec.get("type") or 0) != 3:
        return None
    if int(rec.get("effect_order") or 0) != EFFECT_ORDER_HEAL_ON_STATUS_DAMAGE:
        return None
    params = rec.get("effect_param")
    if not isinstance(params, list) or len(params) != 2:
        return None
    if _slot_values(params, 1) != (1,):
        return None
    return _flag_for_status_refs(_slot_values(params, 0), buff_conf, desc_notes)


def _flag_from_buff_row(
    rec: dict,
    buff_conf: dict[int, dict],
    buffbase_conf: dict[int, dict],
    desc_notes: dict[int, str],
) -> str | None:
    if int(rec.get("type") or 0) != 3:
        return None
    base_ids = tuple(_maybe_int(v) for v in rec.get("buff_base_ids") or ())
    base_ids = tuple(v for v in base_ids if v > 0)
    if not base_ids:
        return None

    orders: list[int] = []
    status_refs: list[int] = []
    for base_id in base_ids:
        base = buffbase_conf.get(base_id)
        if not isinstance(base, dict):
            continue
        order = int(base.get("buffbase_order") or 0)
        orders.append(order)
        if order == BUFFBASE_ORDER_HEAL_ON_STATUS_DAMAGE:
            params = base.get("buffbase_param")
            if isinstance(params, list) and _slot_values(params, 1) == (1,):
                status_refs.extend(_slot_values(params, 0))

    if orders and all(order == BUFFBASE_ORDER_HEAL_ON_STATUS_DAMAGE for order in orders):
        return _flag_for_status_refs(tuple(status_refs), buff_conf, desc_notes)

    if (
        len(base_ids) > 1
        and orders
        and all(order == BUFFBASE_ORDER_MARK_STACK_NO_REPLACE for order in orders)
    ):
        return "MARK_STACK_NO_REPLACE"

    return None


def _flag_for_status_refs(
    refs: tuple[int, ...],
    buff_conf: dict[int, dict],
    desc_notes: dict[int, str],
) -> str | None:
    tags = {
        tag
        for ref in refs
        for tag in (_status_tag_for_buff(ref, buff_conf, desc_notes),)
        if tag
    }
    if tags == {"burn"}:
        return "HEAL_ON_BURN_DAMAGE"
    if tags == {"poison"}:
        return "HEAL_ON_POISON_DAMAGE"
    return None


def _status_tag_for_buff(
    buff_id: int,
    buff_conf: dict[int, dict],
    desc_notes: dict[int, str],
) -> str | None:
    rec = buff_conf.get(buff_id)
    if not isinstance(rec, dict):
        return None
    labels = {
        str(rec.get("name") or "").strip(),
        str(rec.get("add_des") or "").strip(),
    }
    labels.discard("")
    buff_type = int(rec.get("type") or 0)

    if buff_type == 2:
        if desc_notes.get(DESC_BURN) in labels:
            return "burn"
        if desc_notes.get(DESC_POISON) in labels:
            return "poison"
        if desc_notes.get(DESC_LEECH) in labels:
            return "leech"
        return None

    if buff_type == 4 and desc_notes.get(DESC_POISON_MARK) in labels:
        return "poison"

    return None


def _put_flag(
    out: dict[int, AbilityFlagOutcome],
    source_id: int,
    flag_name: str,
    source_table: str,
) -> None:
    try:
        AbilityFlag[flag_name]
    except KeyError:
        raise RuntimeError(
            f"{source_table}[{source_id}] derived flag {flag_name!r} "
            "is not an AbilityFlag member"
        ) from None
    existing = out.get(source_id)
    if existing is not None and existing.flag_name != flag_name:
        raise RuntimeError(
            f"{source_table}[{source_id}] derives conflicting ability flags: "
            f"{existing.flag_name!r} vs {flag_name!r}"
        )
    out[source_id] = AbilityFlagOutcome(effect_id=source_id, flag_name=flag_name)


def _slot_values(params: list, index: int) -> tuple[int, ...]:
    if index >= len(params):
        return ()
    raw = params[index]
    if isinstance(raw, dict):
        raw = raw.get("params")
    if isinstance(raw, list):
        return tuple(v for v in (_maybe_int(item) for item in raw) if v > 0)
    value = _maybe_int(raw)
    return (value,) if value > 0 else ()


def _maybe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _validate_buff_flag_record(
    line_no: int,
    buff_id: int,
    rec: dict,
    real: dict,
) -> None:
    real_editor_name = str(real.get("editor_name", ""))
    pak_editor_name = str(rec.get("pak_editor_name", ""))
    if pak_editor_name != real_editor_name:
        raise RuntimeError(
            f"ability flag fixture line {line_no}: "
            f"pak_editor_name {pak_editor_name!r} does not match "
            f"BUFF_CONF[{buff_id}].editor_name {real_editor_name!r}"
        )

    flag_name = str(rec.get("flag", ""))
    if not flag_name:
        raise RuntimeError(
            f"ability flag fixture line {line_no}: "
            f"flag must be a non-empty string"
        )
    try:
        AbilityFlag[flag_name]
    except KeyError:
        raise RuntimeError(
            f"ability flag fixture line {line_no}: "
            f"flag {flag_name!r} is not an AbilityFlag member; "
            f"valid names: {sorted(m.name for m in AbilityFlag)}"
        ) from None

    evidence = str(rec.get("evidence", ""))
    expected_prefix = f"BUFF_CONF.json[{buff_id}].editor_name="
    if not evidence.startswith(expected_prefix):
        raise RuntimeError(
            f"ability flag fixture line {line_no}: "
            f"evidence must start with {expected_prefix!r}; got {evidence!r}"
        )

    base_ids = real.get("buff_base_ids")
    if not isinstance(base_ids, list) or not base_ids:
        raise RuntimeError(
            f"ability flag fixture line {line_no}: "
            f"BUFF_CONF[{buff_id}].buff_base_ids expected a non-empty list, "
            f"got {base_ids!r}"
        )
    if int(real.get("type") or 0) != 3:
        raise RuntimeError(
            f"ability flag fixture line {line_no}: "
            f"BUFF_CONF[{buff_id}].type expected 3 for passive ability buff, "
            f"got {real.get('type')!r}"
        )


def normalized_payload(table: dict[int, AbilityFlagOutcome]) -> tuple[tuple[int, str], ...]:
    """Stable-sorted ``(effect_id, flag_name)`` tuple for SOURCE_HASH inputs.

    Sorted by ``effect_id`` so the payload is deterministic across runs;
    any addition / removal / flag rename in the derived map changes the
    payload and therefore the hash.
    """
    return tuple(sorted(
        ((eid, outcome.flag_name) for eid, outcome in table.items()),
        key=lambda pair: pair[0],
    ))
