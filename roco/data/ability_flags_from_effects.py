"""Strict loader for ability passive flag semantics.

Pak ability rows point at either ``EFFECT_CONF`` rows or direct
``BUFF_CONF`` rows.  Production derivation follows that structure:
``SKILL_CONF(type=2).skill_result`` gives the referenced ids, and
``BUFF_CONF -> BUFFBASE_CONF`` supplies the semantic axis.  The artifact layer
joins the derived ``skill_result.effect_id → AbilityFlag`` map with generated
``ability_effect_ids`` provenance rows to populate the runtime catalog.

This loader is intentionally strict: unsupported multiplier or fixture
evidence format is reported loudly.  Temporary fixture files may still
pin old ``editor_name`` drift checks, but the production path does not
depend on pak ``editor_name``.

The loader returns ``dict[int, AbilityFlagRule]`` so data/catalog builders can
join the map with pak ability provenance.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from roco.common.enums import AbilityFlag
from roco.data.ability_flag_rules import AbilityFlagRule
from roco.compiler_v2.sources import LuaEnumSource

_DEFAULT_EFFECT_CONF_PATH = (
    Path(__file__).resolve().parents[2]
    / "pak-public-kit"
    / "output"
    / "data"
    / "BinData"
    / "EFFECT_CONF.json"
)
_DEFAULT_BUFF_CONF_PATH = (
    Path(__file__).resolve().parents[2]
    / "pak-public-kit"
    / "output"
    / "data"
    / "BinData"
    / "BUFF_CONF.json"
)
_DEFAULT_BUFFBASE_CONF_PATH = (
    Path(__file__).resolve().parents[2]
    / "pak-public-kit"
    / "output"
    / "data"
    / "BinData"
    / "BUFFBASE_CONF.json"
)
_DEFAULT_DESC_NOTE_CONF_PATH = (
    Path(__file__).resolve().parents[2]
    / "pak-public-kit"
    / "output"
    / "data"
    / "BinData"
    / "DESC_NOTE_CONF.json"
)
_DEFAULT_SKILL_CONF_PATH = (
    Path(__file__).resolve().parents[2]
    / "pak-public-kit"
    / "output"
    / "data"
    / "BinData"
    / "SKILL_CONF.json"
)


@lru_cache(maxsize=None)
def _enum_value(enum_name: str, symbol: str) -> int:
    return int(LuaEnumSource().enums((enum_name,))[enum_name][symbol])


ABILITY_SKILL_TYPE = _enum_value("SkillActiveType", "SAT_FEATURE")
EFFECT_ORDER_SHUFFLE_SKILLS_REDUCE_LAST = _enum_value("EffectType", "ET_SHUFFLE_SKILLS")
EFFECT_ORDER_HEAL_ON_STATUS_DAMAGE = _enum_value("EffectType", "ET_DOT_SUCK")
EFFECT_ORDER_SET_ENERGY = _enum_value("EffectType", "ET_SET_ENERGY")
BUFFBASE_ORDER_ASSIGN = _enum_value("BuffType", "BFT_ASSIGN")
BUFFBASE_ORDER_MARK_STACK_NO_REPLACE = _enum_value("BuffType", "BFT_O_FORTYTHREE")
BUFFBASE_ORDER_HEAL_ON_STATUS_DAMAGE = _enum_value("BuffType", "BFT_O_FIFTYFOUR")
BUFFBASE_ORDER_ATTR_CHANGE = _enum_value("BuffType", "BFT_ATTR_CHANGE")
BUFFBASE_ORDER_CHECK_BUFF_LAYER = _enum_value("BuffType", "BFT_CHECK_BUFF_LAYER")
BUFFBASE_ORDER_BURN_DECAY_GROWTH = _enum_value("BuffType", "BFT_O_ELEVEN")

_DESC_NOTE_LABELS = {
    "poison": "中毒",
    "burn": "灼烧",
    "freeze": "冻结",
    "leech": "寄生",
    "poison_mark": "中毒印记",
    "meteor_mark": "星陨印记",
}


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
) -> dict[int, AbilityFlagRule]:
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
        ability_consumers = _ability_skill_result_consumers(skill_rows) if skill_rows is not None else None
        return _derive_ability_flags(conf, buff_rows, base_rows, desc_rows, ability_consumers)

    out: dict[int, AbilityFlagRule] = {}
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
            out[effect_id] = AbilityFlagRule(effect_id=effect_id, flag_name=flag_name)
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

        out[effect_id] = AbilityFlagRule(effect_id=effect_id, flag_name=flag_name)
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
    ability_consumers: dict[int, tuple[dict, ...]] | None,
) -> dict[int, AbilityFlagRule]:
    out: dict[int, AbilityFlagRule] = {}
    desc_notes = _desc_notes(desc_note_conf)
    desc_refs = _desc_refs(desc_notes)

    for effect_id, rec in sorted(effect_conf.items()):
        flag = _flag_from_effect_row(rec, buff_conf, desc_notes, desc_refs)
        if flag is not None:
            if ability_consumers is not None and effect_id not in ability_consumers:
                if flag != "START_ZERO_ENERGY":
                    continue
            _put_flag(out, effect_id, flag, "EFFECT_CONF")

    for buff_id, rec in sorted(buff_conf.items()):
        if ability_consumers is not None and buff_id not in ability_consumers:
            continue
        flag = _flag_from_buff_row(
            rec,
            effect_conf,
            buff_conf,
            buffbase_conf,
            desc_notes,
            desc_refs,
            ability_consumers.get(buff_id, ()) if ability_consumers is not None else (),
        )
        if flag is not None:
            _put_flag(out, buff_id, flag, "BUFF_CONF")

    return out


def _ability_skill_result_consumers(skill_conf: dict[int, dict]) -> dict[int, tuple[dict, ...]]:
    refs: dict[int, list[dict]] = {}
    for rec in skill_conf.values():
        if int(rec.get("type") or 0) != ABILITY_SKILL_TYPE:
            continue
        for entry in rec.get("skill_result") or []:
            if not isinstance(entry, dict):
                continue
            effect_id = _maybe_int(entry.get("effect_id"))
            if effect_id > 0:
                refs.setdefault(effect_id, []).append(rec)
    return {effect_id: tuple(rows) for effect_id, rows in refs.items()}


def _desc_notes(desc_note_conf: dict[int, dict]) -> dict[int, str]:
    return {
        desc_id: str(rec.get("note", "")).strip()
        for desc_id, rec in desc_note_conf.items()
        if isinstance(rec, dict)
    }


def _desc_refs(desc_notes: dict[int, str]) -> dict[str, int]:
    refs: dict[str, int] = {}
    for key, label in _DESC_NOTE_LABELS.items():
        matches = [desc_id for desc_id, note in desc_notes.items() if note == label]
        if len(matches) != 1:
            raise RuntimeError(
                f"DESC_NOTE_CONF expected exactly one note {label!r} for {key}; "
                f"found {matches!r}"
            )
        refs[key] = matches[0]
    return refs


def _flag_from_effect_row(
    rec: dict,
    buff_conf: dict[int, dict],
    desc_notes: dict[int, str],
    desc_refs: dict[str, int],
) -> str | None:
    if int(rec.get("type") or 0) != 3:
        return None
    order = int(rec.get("effect_order") or 0)
    params = rec.get("effect_param")
    if order == EFFECT_ORDER_SHUFFLE_SKILLS_REDUCE_LAST:
        if params is None:
            return "SHUFFLE_SKILLS_REDUCE_LAST"
        if isinstance(params, list) and len(params) <= 1 and _slot_int_values(params, 0) in ((), (0,)):
            return "SHUFFLE_SKILLS_REDUCE_LAST"
        return None
    if order == EFFECT_ORDER_SET_ENERGY:
        if isinstance(params, list) and _slot_int_values(params, 0) == (0,):
            return "START_ZERO_ENERGY"
        return None
    if order != EFFECT_ORDER_HEAL_ON_STATUS_DAMAGE:
        return None
    if not isinstance(params, list) or len(params) != 2:
        return None
    if _slot_values(params, 1) != (1,):
        return None
    return _flag_for_status_refs(_slot_values(params, 0), buff_conf, desc_notes, desc_refs)


def _flag_from_buff_row(
    rec: dict,
    effect_conf: dict[int, dict],
    buff_conf: dict[int, dict],
    buffbase_conf: dict[int, dict],
    desc_notes: dict[int, str],
    desc_refs: dict[str, int],
    ability_rows: tuple[dict, ...] = (),
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
        return _flag_for_status_refs(tuple(status_refs), buff_conf, desc_notes, desc_refs)

    if (
        len(base_ids) > 1
        and orders
        and all(order == BUFFBASE_ORDER_MARK_STACK_NO_REPLACE for order in orders)
    ):
        return "MARK_STACK_NO_REPLACE"

    assigned_refs = _assigned_refs_for_base_ids(base_ids, buffbase_conf)
    if assigned_refs:
        assigned_flags = {
            flag
            for ref in assigned_refs
            for flag in (_flag_from_effect_row(effect_conf.get(ref, {}), buff_conf, desc_notes, desc_refs),)
            if flag
        }
        if assigned_flags == {"START_ZERO_ENERGY"}:
            return "START_ZERO_ENERGY"

    if _is_freeze_counts_as_meteor(rec, buff_conf, buffbase_conf, desc_notes, desc_refs, ability_rows):
        return "FREEZE_COUNTS_AS_METEOR"

    if _is_burn_decay_growth(rec, buffbase_conf):
        return "BURN_NO_DECAY"

    return None


def _is_burn_decay_growth(rec: dict, buffbase_conf: dict[int, dict]) -> bool:
    base_ids = tuple(_maybe_int(v) for v in rec.get("buff_base_ids") or ())
    base_ids = tuple(v for v in base_ids if v > 0)
    if len(base_ids) != 1:
        return False
    base = buffbase_conf.get(base_ids[0])
    if not isinstance(base, dict) or int(base.get("buffbase_order") or 0) != BUFFBASE_ORDER_BURN_DECAY_GROWTH:
        return False
    params = base.get("buffbase_param")
    return (
        isinstance(params, list)
        and _slot_values(params, 0) == (20070020,)
        and _slot_int_values(params, 1) == (-1,)
        and _slot_int_values(params, 2) == (0,)
    )


def _assigned_refs_for_base_ids(
    base_ids: tuple[int, ...],
    buffbase_conf: dict[int, dict],
) -> tuple[int, ...]:
    refs: list[int] = []
    for base_id in base_ids:
        base = buffbase_conf.get(base_id)
        if not isinstance(base, dict) or int(base.get("buffbase_order") or 0) != BUFFBASE_ORDER_ASSIGN:
            continue
        params = base.get("buffbase_param")
        if not isinstance(params, list):
            continue
        refs.extend(_slot_values(params, 0))
    return tuple(refs)


def _is_freeze_counts_as_meteor(
    rec: dict,
    buff_conf: dict[int, dict],
    buffbase_conf: dict[int, dict],
    desc_notes: dict[int, str],
    desc_refs: dict[str, int],
    ability_rows: tuple[dict, ...],
) -> bool:
    """Detect the pak order-40 virtual counter behind 月牙雪糕.

    The numeric structure supplies the mechanics shape: a passive
    ``BFT_CHECK_BUFF_LAYER`` row watches a zero-value virtual layer and
    emits another zero-value virtual layer while an attack is being
    resolved.  The raw pak ability description supplies the only explicit
    domain labels for that virtual layer pair: freeze and meteor mark.
    Both sides are required so this cannot classify unrelated prefix_2040
    buffs such as 嫉妒.
    """
    if not _ability_desc_mentions_freeze_meteor(desc_notes, desc_refs, ability_rows):
        return False
    base_ids = tuple(_maybe_int(v) for v in rec.get("buff_base_ids") or ())
    base_ids = tuple(v for v in base_ids if v > 0)
    if len(base_ids) != 1:
        return False
    base = buffbase_conf.get(base_ids[0])
    if not isinstance(base, dict) or int(base.get("buffbase_order") or 0) != BUFFBASE_ORDER_CHECK_BUFF_LAYER:
        return False
    params = base.get("buffbase_param")
    if not isinstance(params, list):
        return False
    source_refs = _slot_values(params, 0)
    target_refs = _slot_values(params, 2)
    return (
        len(source_refs) == 1
        and _slot_values(params, 1) == (1,)
        and len(target_refs) == 1
        and _slot_int_values(params, 3) == (0,)
        and _slot_int_values(params, 4) == (4,)
        and _is_zero_attr_virtual_buff(source_refs[0], buff_conf, buffbase_conf)
        and _is_zero_attr_virtual_buff(target_refs[0], buff_conf, buffbase_conf)
    )


def _ability_desc_mentions_freeze_meteor(
    desc_notes: dict[int, str],
    desc_refs: dict[str, int],
    ability_rows: tuple[dict, ...],
) -> bool:
    freeze = desc_notes[desc_refs["freeze"]]
    meteor_id = desc_refs["meteor_mark"]
    meteor = desc_notes[meteor_id]
    for row in ability_rows:
        desc = str(row.get("desc") or "")
        if freeze and freeze not in desc:
            continue
        if f"<desc_id={meteor_id}>" in desc or (meteor and meteor in desc):
            return True
    return False


def _is_zero_attr_virtual_buff(
    buff_id: int,
    buff_conf: dict[int, dict],
    buffbase_conf: dict[int, dict],
) -> bool:
    rec = buff_conf.get(buff_id)
    if not isinstance(rec, dict) or int(rec.get("type") or 0) != 3:
        return False
    base_ids = tuple(_maybe_int(v) for v in rec.get("buff_base_ids") or ())
    base_ids = tuple(v for v in base_ids if v > 0)
    if len(base_ids) != 1:
        return False
    base = buffbase_conf.get(base_ids[0])
    if not isinstance(base, dict) or int(base.get("buffbase_order") or 0) != BUFFBASE_ORDER_ATTR_CHANGE:
        return False
    params = base.get("buffbase_param")
    return (
        isinstance(params, list)
        and _slot_values(params, 0) == (29,)
        and _slot_int_values(params, 1) == (0,)
        and _slot_int_values(params, 2) == (0,)
    )


def _flag_for_status_refs(
    refs: tuple[int, ...],
    buff_conf: dict[int, dict],
    desc_notes: dict[int, str],
    desc_refs: dict[str, int],
) -> str | None:
    tags = {
        tag
        for ref in refs
        for tag in (_status_tag_for_buff(ref, buff_conf, desc_notes, desc_refs),)
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
    desc_refs: dict[str, int],
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
        if desc_notes[desc_refs["burn"]] in labels:
            return "burn"
        if desc_notes[desc_refs["poison"]] in labels:
            return "poison"
        if desc_notes[desc_refs["leech"]] in labels:
            return "leech"
        return None

    if buff_type == 4 and desc_notes[desc_refs["poison_mark"]] in labels:
        return "poison"

    return None


def _put_flag(
    out: dict[int, AbilityFlagRule],
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
    out[source_id] = AbilityFlagRule(effect_id=source_id, flag_name=flag_name)


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


def _slot_int_values(params: list, index: int) -> tuple[int, ...]:
    if index >= len(params):
        return ()
    raw = params[index]
    if isinstance(raw, dict):
        raw = raw.get("params")
    if isinstance(raw, list):
        return tuple(_maybe_int(item) for item in raw)
    return (_maybe_int(raw),)


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


def normalized_payload(table: dict[int, AbilityFlagRule]) -> tuple[tuple[int, str], ...]:
    """Stable-sorted ``(effect_id, flag_name)`` tuple for SOURCE_HASH inputs.

    Sorted by ``effect_id`` so the payload is deterministic across runs;
    any addition / removal / flag rename in the derived map changes the
    payload and therefore the hash.
    """
    return tuple(sorted(
        ((eid, outcome.flag_name) for eid, outcome in table.items()),
        key=lambda pair: pair[0],
    ))
