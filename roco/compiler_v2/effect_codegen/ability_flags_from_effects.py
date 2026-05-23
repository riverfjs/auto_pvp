"""Strict loader for ability passive flag semantics.

Pak ``EFFECT_CONF`` / direct ``BUFF_CONF`` rows identify small
passive-ability families.  The artifact layer joins the derived
``skill_result.effect_id → AbilityFlag`` map with the ``ability_effect_ids``
SQLite table to populate ``ABILITY_FLAGS`` in
:mod:`roco.generated.catalog_hot`.

This loader is intentionally strict: any drift in pak editor_name,
unsupported multiplier, or fixture evidence format is reported loudly.

The loader returns ``dict[int, AbilityFlagOutcome]`` so callers can feed
the same map to :func:`classify.decode_effect` and to
:func:`build_effect_families._classify_one_source_id`.
"""

from __future__ import annotations

from pathlib import Path
import json

from roco.common.enums import AbilityFlag
from roco.compiler_v2.effect_codegen.outcomes import AbilityFlagOutcome

_EDITOR_NAME_TO_FLAG: tuple[tuple[str, str], ...] = (
    ("中毒变寄生", "HEAL_ON_POISON_DAMAGE"),
    ("灼烧变寄生", "HEAL_ON_BURN_DAMAGE"),
)
_BUFF_EDITOR_NAME_TO_FLAG: tuple[tuple[str, str], ...] = (
    ("改变赋予印记鲤拉鳐", "MARK_STACK_NO_REPLACE"),
)
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


def _load_effect_conf() -> dict[int, dict]:
    with _DEFAULT_EFFECT_CONF_PATH.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    rows = data.get("RocoDataRows", data)
    return {int(k): v for k, v in rows.items()}


def _load_buff_conf() -> dict[int, dict]:
    with _DEFAULT_BUFF_CONF_PATH.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    rows = data.get("RocoDataRows", data)
    return {int(k): v for k, v in rows.items()}


def load_ability_flags_from_effects(
    rules_path: Path | None = None,
    effect_conf: dict[int, dict] | None = None,
    buff_conf: dict[int, dict] | None = None,
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
    fixture records; the default production path derives records from pak.
    """
    conf = effect_conf if effect_conf is not None else _load_effect_conf()
    buff_rows = buff_conf if buff_conf is not None else (
        _load_buff_conf() if rules_path is None else {}
    )

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
        flag_by_editor_name = dict(_EDITOR_NAME_TO_FLAG)
        buff_flag_by_editor_name = dict(_BUFF_EDITOR_NAME_TO_FLAG)
        out: list[tuple[int, dict]] = []
        for effect_id, rec in sorted(effect_conf.items()):
            editor_name = str(rec.get("editor_name", ""))
            flag = flag_by_editor_name.get(editor_name)
            if flag is None:
                continue
            out.append((
                len(out) + 1,
                {
                    "effect_id": effect_id,
                    "pak_editor_name": editor_name,
                    "flag": flag,
                    "evidence": f"EFFECT_CONF.json[{effect_id}].editor_name={editor_name!r}",
                },
            ))
        for buff_id, rec in sorted(buff_conf.items()):
            editor_name = str(rec.get("editor_name", ""))
            flag = buff_flag_by_editor_name.get(editor_name)
            if flag is None:
                continue
            out.append((
                len(out) + 1,
                {
                    "source_table": "BUFF_CONF",
                    "effect_id": buff_id,
                    "pak_editor_name": editor_name,
                    "flag": flag,
                    "evidence": f"BUFF_CONF.json[{buff_id}].editor_name={editor_name!r}",
                },
            ))
        return out
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
