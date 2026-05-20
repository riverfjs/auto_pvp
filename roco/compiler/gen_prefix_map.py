"""Auto-generate handler indices + prefix->handler mapping + pak rules.

Outputs (all under roco/generated/):
  - handler_indices.py        H_* constants from handler_registry.json
  - handler_order.py          HANDLER_ORDER tuple consumed by ops.py
  - handler_registry.json     append-only registry of op_* function names
  - prefix_handler_map.json   buff prefix family -> handler index
  - pak_rules.py              constants extracted from BATTLE_GLOBAL_CONFIG

Run at build time:  uv run python -m roco.compiler.gen_prefix_map
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAK_DATA = ROOT / "pak-public-kit" / "output" / "data" / "BinData"
GEN_DIR = ROOT / "roco" / "generated"
RULES_DIR = ROOT / "roco" / "compiler" / "rules"
REGISTRY_PATH = GEN_DIR / "handler_registry.json"
INDICES_PATH = GEN_DIR / "handler_indices.py"
ORDER_PATH = GEN_DIR / "handler_order.py"
TABLE_PATH = GEN_DIR / "handler_table.py"
PREFIX_MAP_PATH = GEN_DIR / "prefix_handler_map.json"
PAK_RULES_PATH = GEN_DIR / "pak_rules.py"
MARK_GROUPS_PATH = GEN_DIR / "mark_groups.py"
PAK_OPS_PATH = GEN_DIR / "pak_ops.py"
TYPE_CHART_PATH = GEN_DIR / "type_chart.py"
WEATHER_DECODERS_PATH = GEN_DIR / "weather_decoders.py"
COUNTER_SKILL_TABLE_PATH = GEN_DIR / "counter_skill_table.py"


# pak ``effect_param[0]`` weather code → kernel ``WeatherType`` enum value.
# Hand-curated because pak ships no machine-readable cross-reference; keeping
# it as a tight 4-entry table here (instead of in JSONL) is the smallest
# version of "data, not Python source" — anybody touching weather decoding
# updates this table once and ``generate_weather_decoders`` does the rest.
_PAK_WEATHER_TO_KERNEL = {
    1: "NONE",       # 晴天 (clears weather)
    3: "RAIN",       # 求雨
    5: "SNOW",       # 暴风雪
    6: "SANDSTORM",  # 沙暴
}

# Default initial turn count per kernel ``WeatherType`` when pak supplies 0.
# The first end-of-turn tick decrements once, so a value of 8 here matches
# the canonical 7-turns-remaining state the kernel tests assert.
_WEATHER_DEFAULT_TURNS = {
    "NONE": 0,
    "RAIN": 8,
    "SNOW": 8,
    "SANDSTORM": 8,
}
# Hand-curated prefix/base_id → handler seed used to bootstrap
# ``generate_prefix_map``.  Editable JSONL keeps the semantic decisions
# (which pak prefix family maps to which kernel handler) as data, not as
# Python source.  ``gen_prefix_map`` only loads, validates, and emits.
PREFIX_SEED_PATH = RULES_DIR / "prefix_handlers.jsonl"

_OP_MODULES = (
    # op_mods is a package split by topic; gen scans each submodule
    # directly so each op_* function ends up imported by its real source
    # path in the generated handler_table.
    "roco.engine.kernel.op_mods.damage",
    "roco.engine.kernel.op_mods.buffs",
    "roco.engine.kernel.op_mods.skill",
    "roco.engine.kernel.op_mods.combat",
    "roco.engine.kernel.op_resources",
    "roco.engine.kernel.op_marks",
    "roco.engine.kernel.op_status",
    "roco.engine.kernel.op_cute",
)


# ---------------------------------------------------------------------------
# Handler discovery + registry
# ---------------------------------------------------------------------------

def _module_funcs() -> dict[str, list[str]]:
    """Return {mod_name: [op_func_names]} via AST parse — no imports."""
    result: dict[str, list[str]] = {}
    for mod_name in _OP_MODULES:
        path = ROOT / (mod_name.replace(".", "/") + ".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        result[mod_name] = [
            n.name for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("op_")
        ]
    return result


def _discover_handlers() -> set[str]:
    return {name for names in _module_funcs().values() for name in names}


def _load_registry() -> list[str]:
    if REGISTRY_PATH.exists():
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        return data["handlers"]
    return ["_noop"]


def _update_registry(existing: list[str], discovered: set[str]) -> list[str]:
    known = set(existing)
    new_handlers = sorted(discovered - known)
    return existing + new_handlers


def _save_registry(handlers: list[str]) -> None:
    data = {
        "_meta": {"version": 1, "description": "Append-only handler registry."},
        "handlers": handlers,
    }
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _func_to_const(name: str) -> str:
    if name == "_noop":
        return "H_NOOP"
    if name.startswith("op_"):
        return "H_" + name[3:].upper()
    return "H_" + name.upper()


def generate_handler_indices() -> dict[str, int]:
    discovered = _discover_handlers()
    existing = _load_registry()
    handlers = _update_registry(existing, discovered)
    _save_registry(handlers)

    missing = set(handlers[1:]) - discovered
    if missing:
        print(f"WARNING: registry has handlers not in code: {missing}", file=sys.stderr)

    index_map: dict[str, int] = {}
    lines = ["# Auto-generated from handler_registry.json — do not edit.", ""]
    for idx, func_name in enumerate(handlers):
        const = _func_to_const(func_name)
        index_map[const] = idx
        lines.append(f"{const} = {idx}")
    lines.append("")
    INDICES_PATH.write_text("\n".join(lines), encoding="utf-8")

    order_lines = [
        "# Auto-generated from handler_registry.json — do not edit.",
        "",
        "HANDLER_ORDER: tuple[str, ...] = (",
    ]
    for name in handlers:
        order_lines.append(f"    {name!r},")
    order_lines.append(")")
    order_lines.append("")
    ORDER_PATH.write_text("\n".join(order_lines), encoding="utf-8")

    _write_handler_table(handlers)
    return index_map


def _write_handler_table(handlers: list[str]) -> None:
    """Emit a static HANDLERS tuple with explicit per-module imports.

    Replaces runtime dir()-based assembly in ops.py with a generated table
    every op_* function is imported by name.
    """
    func_to_module: dict[str, str] = {}
    for mod_name, names in _module_funcs().items():
        for name in names:
            func_to_module[name] = mod_name

    by_module: dict[str, list[str]] = {m: [] for m in _OP_MODULES}
    for func_name in handlers:
        if func_name == "_noop":
            continue
        mod_name = func_to_module.get(func_name)
        if mod_name is None:
            raise RuntimeError(f"handler '{func_name}' not found in any op_* module")
        by_module[mod_name].append(func_name)

    lines = [
        "# Auto-generated from handler_registry.json — do not edit.",
        "# Regenerate with: uv run python -m roco.compiler.gen_prefix_map",
        "",
        "from roco.engine.kernel.ctx import StageCtx",
        "",
    ]
    for mod_name in _OP_MODULES:
        names = by_module[mod_name]
        if not names:
            continue
        lines.append(f"from {mod_name} import (")
        for n in names:
            lines.append(f"    {n},")
        lines.append(")")
    lines.extend([
        "",
        "",
        "def _noop(_ctx: StageCtx, _row: tuple[int, ...]) -> None:",
        "    pass",
        "",
        "",
        "HANDLERS: tuple = (",
    ])
    for idx, name in enumerate(handlers):
        lines.append(f"    {name},  # {idx}")
    lines.extend([
        ")",
        "",
        "HANDLER_COUNT = len(HANDLERS)",
        "",
    ])
    TABLE_PATH.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Prefix -> handler mapping from BUFF_CONF
# ---------------------------------------------------------------------------

def _build_seed(h: dict[str, int]) -> tuple[dict[int, int], dict[int, int]]:
    """Load the hand-curated prefix / base_id → handler seed from JSONL.

    The JSONL is the editable source of truth for semantic decisions
    (which pak prefix family maps to which kernel handler).  Each record
    is either ``{"prefix": <int>, "handler": "H_*", "alias": "..."}`` or
    ``{"base_id": <int>, "handler": "H_*", "note": "..."}``.

    Unknown handler names raise immediately so renames in the kernel
    cannot silently drop a prefix from the seed.
    """
    prefix_seed: dict[int, int] = {}
    base_id_seed: dict[int, int] = {}
    with PREFIX_SEED_PATH.open("r", encoding="utf-8") as fp:
        for line_no, raw in enumerate(fp, 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            rec = json.loads(raw)
            handler_name = rec.get("handler")
            if handler_name not in h:
                raise RuntimeError(
                    f"prefix_handlers.jsonl line {line_no}: unknown handler "
                    f"'{handler_name}' (not in handler_indices)"
                )
            handler_idx = h[handler_name]
            if "prefix" in rec:
                prefix_seed[int(rec["prefix"])] = handler_idx
            elif "base_id" in rec:
                base_id_seed[int(rec["base_id"])] = handler_idx
            else:
                raise RuntimeError(
                    f"prefix_handlers.jsonl line {line_no}: record needs "
                    "either 'prefix' or 'base_id'"
                )
    return prefix_seed, base_id_seed


def generate_prefix_map(handler_indices: dict[str, int], pak_data_dir: Path = PAK_DATA) -> dict:
    prefix_seed, base_id_seed = _build_seed(handler_indices)

    buff_path = pak_data_dir / "BUFF_CONF.json"
    with buff_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("RocoDataRows", data)

    all_prefixes: set[int] = set()
    all_base_ids: set[int] = set()
    for rec in rows.values():
        for bid in rec.get("buff_base_ids") or []:
            if bid:
                all_base_ids.add(bid)
                all_prefixes.add(bid // 1000)

    prefix_map: dict[int, int] = {}
    unmapped: list[int] = []
    for pfx in sorted(all_prefixes):
        if pfx in prefix_seed:
            prefix_map[pfx] = prefix_seed[pfx]
        else:
            prefix_map[pfx] = 0
            unmapped.append(pfx)

    return {
        "prefix_map": {str(k): v for k, v in sorted(prefix_map.items())},
        "base_id_map": {str(k): v for k, v in sorted(base_id_seed.items())},
        "stats": {
            "total_base_ids": len(all_base_ids),
            "total_prefixes": len(all_prefixes),
            "mapped_prefixes": len(all_prefixes) - len(unmapped),
            "unmapped_prefixes": unmapped,
        },
    }


# ---------------------------------------------------------------------------
# Pak-derivable game-rule constants (BATTLE_GLOBAL_CONFIG)
# ---------------------------------------------------------------------------

# Map our constant name -> pak BATTLE_GLOBAL_CONFIG key.
# Only constants whose semantics match pak's encoding are listed here.
# Kernel-specific composites (e.g. TYPE_DOUBLE_RESIST_BPS from multiplicative
# stack of two single-resist mults) stay in common/constants.py.
_PAK_RULES_KEYS = {
    "TYPE_NEUTRAL_BPS":        "restraint_percent",
    "TYPE_WEAK_BPS":           "double_restraint_percent",
    "TYPE_DOUBLE_WEAK_BPS":    "triple_restraint_percent",
    "TYPE_RESIST_BPS":         "restrained_percent",
    # ``double_restrained_percent`` in pak = 7500 BPS (0.75×), used by the
    # kernel as the multiplier when both defender types resist the move.
    # The previous hand-coded value was 3333 (1/3×), which deliberately
    # differed from pak; restore pak truth as the source.
    "TYPE_DOUBLE_RESIST_BPS":  "double_restrained_percent",
    "DAMAGE_PERCENT_LIMIT":    "damage_percent_limit",
    "SKILL_DAMAGE_MAX":        "skill_damage_max",
    "PVP_LEVEL":               "battle_pvp_level",
}


def generate_weather_decoders(pak_data_dir: Path = PAK_DATA) -> int:
    """Emit ``roco/generated/weather_decoders.py`` — one row per pak
    weather setter (``effect_order=28`` ``type=3``).

    Each entry reads pak ``effect_param[0]`` as the pak-internal weather
    code, looks it up in :data:`_PAK_WEATHER_TO_KERNEL`, and pairs the
    kernel ``WeatherType`` enum value with a default duration from
    :data:`_WEATHER_DEFAULT_TURNS`.  Effects whose pak weather code is
    not in the table are skipped — they show up as audit gaps and the
    pak→kernel table needs an entry before they decode.
    """
    from roco.common.enums import WeatherType

    rows = json.loads((pak_data_dir / "EFFECT_CONF.json").read_text(encoding="utf-8"))
    pak_effects = rows.get("RocoDataRows", rows)

    decoded: list[tuple[int, str, int, int]] = []  # (effect_id, kernel_name, kernel_value, default_turns)
    for eid_str, rec in pak_effects.items():
        if rec.get("effect_order") != 28 or rec.get("type") != 3:
            continue
        params = rec.get("effect_param") or []
        if not params or not isinstance(params[0], dict):
            continue
        inner = params[0].get("params") or []
        if not inner:
            continue
        try:
            pak_code = int(inner[0])
        except (TypeError, ValueError):
            continue
        kernel_name = _PAK_WEATHER_TO_KERNEL.get(pak_code)
        if kernel_name is None:
            continue
        kernel_value = int(getattr(WeatherType, kernel_name).value)
        default_turns = _WEATHER_DEFAULT_TURNS.get(kernel_name, 0)
        decoded.append((int(eid_str), kernel_name, kernel_value, default_turns))

    decoded.sort()

    lines = [
        "# Auto-generated from EFFECT_CONF.json — do not edit.",
        "# Regenerate with: uv run python -m roco.compiler.gen_prefix_map",
        "",
        "from roco.generated.handler_indices import H_WEATHER",
        "",
        "# ``effect_id -> (handler_idx, weather_kernel_id, default_turns, 0, 0, timing_override)``",
        "WEATHER_EFFECT_DECODERS: dict[int, tuple[int, int, int, int, int, int]] = {",
    ]
    for eid, kernel_name, kernel_value, default_turns in decoded:
        lines.append(
            f"    {eid}: (H_WEATHER, {kernel_value}, {default_turns}, 0, 0, 0),  # pak {kernel_name}"
        )
    lines.append("}")
    lines.append("")
    WEATHER_DECODERS_PATH.write_text("\n".join(lines), encoding="utf-8")
    return len(decoded)


def generate_type_chart(pak_data_dir: Path = PAK_DATA) -> int:
    """Emit ``roco/generated/type_chart.py`` — single-defender BPS chart.

    ``TYPE_DICTIONARY.json`` carries one row per element with sparse
    ``type_restraint{N}`` fields:

    * ``+1`` → this element deals super-effective damage to element N
      (``TYPE_WEAK_BPS`` = 20000 = 2.0×).
    * ``-1`` → this element is resisted by element N
      (``TYPE_RESIST_BPS`` = 5000 = 0.5×).
    * missing → neutral (``TYPE_NEUTRAL_BPS`` = 10000 = 1.0×).

    Dual-type composition (3.0× / 0.25× overlap rules) is handled by the
    kernel at runtime against the single-defender values in this table.

    Rows are emitted in the kernel's :data:`ELEMENT_NAMES` order so
    ``TYPE_CHART_BPS[attacker_id][defender_id]`` indexes directly with
    the element ids that show up in :class:`hot.PETS`.
    """
    from roco.common.enums import ELEMENT_NAMES
    from roco.generated.pak_rules import (
        TYPE_NEUTRAL_BPS,
        TYPE_RESIST_BPS,
        TYPE_WEAK_BPS,
    )

    rows = json.loads((pak_data_dir / "TYPE_DICTIONARY.json").read_text(encoding="utf-8"))
    pak_rows = rows.get("RocoDataRows", rows)

    by_short_name: dict[str, dict] = {}
    for rec in pak_rows.values():
        short = rec.get("short_name")
        if short:
            by_short_name[short] = rec

    n = len(ELEMENT_NAMES)
    pak_ids_in_order: list[int] = []
    for name in ELEMENT_NAMES:
        rec = by_short_name.get(name)
        if rec is None:
            raise RuntimeError(f"TYPE_DICTIONARY missing short_name={name!r}")
        pak_ids_in_order.append(int(rec["id"]))

    chart: list[list[int]] = [[TYPE_NEUTRAL_BPS] * n for _ in range(n)]
    for attacker_idx, attacker_name in enumerate(ELEMENT_NAMES):
        rec = by_short_name[attacker_name]
        for defender_idx, defender_pak_id in enumerate(pak_ids_in_order):
            sign = rec.get(f"type_restraint{defender_pak_id}", 0)
            if sign == 1:
                chart[attacker_idx][defender_idx] = TYPE_WEAK_BPS
            elif sign == -1:
                chart[attacker_idx][defender_idx] = TYPE_RESIST_BPS

    lines = [
        "# Auto-generated from TYPE_DICTIONARY.json — do not edit.",
        "# Regenerate with: uv run python -m roco.compiler.gen_prefix_map",
        "",
        f"# Element order matches roco.common.enums.ELEMENT_NAMES (length {n}).",
        "TYPE_CHART_BPS: tuple[tuple[int, ...], ...] = (",
    ]
    for attacker_idx, attacker_name in enumerate(ELEMENT_NAMES):
        row_str = ", ".join(str(v) for v in chart[attacker_idx])
        lines.append(f"    ({row_str}),  # {attacker_idx:2d} {attacker_name}")
    lines.append(")")
    lines.append("")
    TYPE_CHART_PATH.write_text("\n".join(lines), encoding="utf-8")
    return n


def generate_pak_ops(pak_data_dir: Path = PAK_DATA) -> int:
    """Emit ``roco/generated/pak_ops.py`` — pak prefix family debug names.

    Aliases come from :data:`PREFIX_SEED_PATH`; prefixes that appear in
    pak BUFF_CONF but have no seed entry get a generic ``PREFIX_<n>``
    label so the table is exhaustive.  ``PAK_PREFIX_NAMES`` is the only
    place the compiler/data layer should look up "what does this pak
    prefix mean" — no hand-written enum mirrors pak schema any more.
    """
    aliases: dict[int, str] = {}
    with PREFIX_SEED_PATH.open("r", encoding="utf-8") as fp:
        for raw in fp:
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            rec = json.loads(raw)
            if "prefix" in rec and rec.get("alias"):
                aliases[int(rec["prefix"])] = rec["alias"]

    buff_path = pak_data_dir / "BUFF_CONF.json"
    rows = json.loads(buff_path.read_text(encoding="utf-8")).get("RocoDataRows", {})
    all_prefixes: set[int] = set()
    for rec in rows.values():
        for bid in rec.get("buff_base_ids") or []:
            if bid:
                all_prefixes.add(bid // 1000)

    lines = [
        "# Auto-generated from BUFF_CONF.json + prefix_handlers.jsonl — do not edit.",
        "# Regenerate with: uv run python -m roco.compiler.gen_prefix_map",
        "",
        "# Synthetic ``EFFECT_CONF.type`` markers (not pak buff prefixes).",
        "EFF_BUFF_APPLY = 10001",
        "EFF_DAMAGE = 10002",
        "EFF_STATE_CHANGE = 10003",
        "",
        "PAK_PREFIX_NAMES: dict[int, str] = {",
    ]
    for pfx in sorted(all_prefixes):
        name = aliases.get(pfx, f"PREFIX_{pfx}")
        lines.append(f"    {pfx}: {name!r},")
    lines.append("}")
    lines.append("")
    PAK_OPS_PATH.write_text("\n".join(lines), encoding="utf-8")
    return len(all_prefixes)


def generate_mark_groups(
    handler_indices: dict[str, int],
    prefix_result: dict,
    pak_data_dir: Path = PAK_DATA,
) -> tuple[tuple[int, ...], ...]:
    """Derive mark cover groups from pak ``buff_groupsigns``.

    Two mark handlers belong to the same cover group when at least one
    BUFF_CONF row classified to each handler shares a non-zero
    ``buff_groupsigns`` entry.  Pak puts wind/moisture/meteor on
    ``groupsign=26``; setting any of them clears the others.

    Emits ``roco/generated/mark_groups.py`` with a ``MARK_COVER_GROUPS``
    tuple of ``MarkIdx`` tuples.  ``op_marks._op_mark`` reads it to
    enforce cover-group exclusivity.
    """
    h_poison_mark = handler_indices.get("H_POISON_MARK")
    h_momentum_mark = handler_indices.get("H_MOMENTUM_MARK")
    if h_poison_mark is None or h_momentum_mark is None:
        MARK_GROUPS_PATH.write_text(
            "# Auto-generated — do not edit. Regenerate with gen_prefix_map.\n"
            "from roco.common.packing import MarkIdx  # noqa: F401\n"
            "MARK_COVER_GROUPS: tuple = ()\n",
            encoding="utf-8",
        )
        return ()
    mark_range = set(range(h_poison_mark, h_momentum_mark + 1))

    base_id_map = {int(k): v for k, v in prefix_result["base_id_map"].items()}
    prefix_map = {int(k): v for k, v in prefix_result["prefix_map"].items()}

    buff_path = pak_data_dir / "BUFF_CONF.json"
    rows = json.loads(buff_path.read_text(encoding="utf-8")).get("RocoDataRows", {})

    groups: dict[int, set[int]] = {}
    for rec in rows.values():
        base_ids = rec.get("buff_base_ids") or []
        handler = 0
        for bid in base_ids:
            if not bid:
                continue
            if bid in base_id_map and base_id_map[bid] in mark_range:
                handler = base_id_map[bid]
                break
            pfx = bid // 1000
            if pfx in prefix_map and prefix_map[pfx] in mark_range:
                handler = prefix_map[pfx]
                break
        if handler == 0:
            continue
        for sign in rec.get("buff_groupsigns") or []:
            if sign:
                groups.setdefault(int(sign), set()).add(handler)

    handler_to_mark = {
        handler_indices[k]: k.removeprefix("H_").removesuffix("_MARK")
        for k in handler_indices
        if k.endswith("_MARK") and k != "H_POISON_MARK_END"
    }

    cover_groups: list[tuple[str, ...]] = []
    for sign, handlers in sorted(groups.items()):
        if len(handlers) < 2:
            continue
        names = tuple(sorted(handler_to_mark[h] for h in handlers if h in handler_to_mark))
        if len(names) >= 2:
            cover_groups.append(names)

    lines = [
        "# Auto-generated from BUFF_CONF.buff_groupsigns — do not edit.",
        "# Regenerate with: uv run python -m roco.compiler.gen_prefix_map",
        "",
        "from roco.common.packing import MarkIdx",
        "",
        "MARK_COVER_GROUPS: tuple[tuple[MarkIdx, ...], ...] = (",
    ]
    for names in cover_groups:
        body = ", ".join(f"MarkIdx.{n}" for n in names)
        lines.append(f"    ({body}),")
    lines.append(")")
    lines.append("")
    MARK_GROUPS_PATH.write_text("\n".join(lines), encoding="utf-8")
    return tuple(cover_groups)


# Pak ``skill_dam_type`` → kernel ``Element`` value.  Same mapping pak uses
# everywhere; collapsing 7+8 → GROUND matches the canonical name table in
# ``parse_pak.SKILL_DAM_TYPE_TO_ELEMENT``.  Pak ``damage_type`` 2/3 → kernel
# ``SkillCategory`` PHYSICAL/MAGICAL; pak ``Skill_Type`` 2/3 distinguish
# STATUS/DEFENSE for non-attack response skills (still get a kernel category
# code so ``mechanics`` can route them through ``damage()`` if needed).
_PAK_SKILL_DAM_TYPE_TO_ELEMENT = {
    2: 0,   # 普通 NORMAL
    3: 1,   # 草 GRASS
    4: 2,   # 火 FIRE
    5: 3,   # 水 WATER
    6: 4,   # 光 LIGHT
    7: 5,   # 地 GROUND
    8: 5,   # 地 GROUND (pak alias)
    9: 6,   # 冰 ICE
    10: 7,  # 龙 DRAGON
    11: 8,  # 电 ELECTRIC
    12: 9,  # 毒 POISON
    13: 10, # 虫 BUG
    14: 11, # 武 FIGHTING
    15: 12, # 翼 FLYING
    16: 13, # 萌 CUTE
    17: 14, # 幽 GHOST
    18: 15, # 恶 DARK
    19: 16, # 机械 MECHANICAL
    20: 17, # 幻 ILLUSION
}


def generate_counter_skill_table(pak_data_dir: Path = PAK_DATA) -> int:
    """Emit ``roco/generated/counter_skill_table.py``.

    The pak counter-trigger family (effect_ids 1031xxx) carries a 70xxxxx
    response skill_id in ``effect_param[0]``.  When ``op_install_counter``
    arms a side's ``counter_skill_id``, the kernel reads this table to
    resolve the response skill's combat stats (power, element, category,
    damage type code, priority).  Built directly from SKILL_CONF so adding
    a new "应对！X" pak skill only requires a parse_pak re-run.
    """
    effect_path = pak_data_dir / "EFFECT_CONF.json"
    skill_path = pak_data_dir / "SKILL_CONF.json"
    effect_rows = json.loads(effect_path.read_text(encoding="utf-8")).get("RocoDataRows", {})
    skill_rows = json.loads(skill_path.read_text(encoding="utf-8")).get("RocoDataRows", {})

    counter_skill_ids: set[int] = set()
    for eid_str, rec in effect_rows.items():
        eid = int(eid_str)
        if not (1031000 <= eid <= 1031999):
            continue
        params = rec.get("effect_param") or rec.get("params") or []
        if not params or not isinstance(params[0], dict):
            continue
        inner = params[0].get("params") or []
        if not inner:
            continue
        csid = int(inner[0])
        if 7000000 <= csid < 8000000:
            counter_skill_ids.add(csid)

    table: list[tuple[int, int, int, int, int, int, str]] = []
    for csid in sorted(counter_skill_ids):
        row = skill_rows.get(str(csid))
        if row is None:
            continue  # missing in pak; defender just won't counter
        dam_para = row.get("dam_para") or [0]
        power = int(dam_para[0] if isinstance(dam_para, list) and dam_para else 0)
        skill_dam_type = int(row.get("skill_dam_type") or 0)
        element = _PAK_SKILL_DAM_TYPE_TO_ELEMENT.get(skill_dam_type, 0)
        pak_damage_type = int(row.get("damage_type") or 0)
        pak_skill_type = int(row.get("Skill_Type") or 0)
        # Kernel category: physical=1 magical=2 defense=3 status=4.  Map
        # pak damage_type=2 → physical, =3 → magical; for non-attack
        # response skills fall back to Skill_Type=3 → defense, =2 → status.
        if pak_damage_type == 2:
            category = 1
        elif pak_damage_type == 3:
            category = 2
        elif pak_skill_type == 3:
            category = 3
        elif pak_skill_type == 2:
            category = 4
        else:
            category = 0
        priority = int(row.get("skill_priority") or 0)
        name = str(row.get("name") or "")
        table.append((csid, power, element, category, pak_damage_type, priority, name))

    lines = [
        "# Auto-generated from SKILL_CONF.json + EFFECT_CONF.json — do not edit.",
        "# Regenerate with: uv run python -m roco.compiler.gen_prefix_map",
        "",
        "# counter_skill_id -> (power, element, category, dam_type, priority)",
        "COUNTER_SKILL_TABLE: dict[int, tuple[int, int, int, int, int]] = {",
    ]
    for csid, power, element, category, dam_type, priority, name in table:
        lines.append(f"    {csid}: ({power}, {element}, {category}, {dam_type}, {priority}),  # {name}")
    lines.append("}")
    lines.append("")
    COUNTER_SKILL_TABLE_PATH.write_text("\n".join(lines), encoding="utf-8")
    return len(table)


def generate_pak_rules(pak_data_dir: Path = PAK_DATA) -> dict[str, int]:
    p = pak_data_dir / "BATTLE_GLOBAL_CONFIG.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    rows = data.get("RocoDataRows", data)
    by_key = {v.get("key"): v.get("num") for v in rows.values() if v.get("key")}

    out: dict[str, int] = {}
    missing: list[str] = []
    for const, pak_key in _PAK_RULES_KEYS.items():
        val = by_key.get(pak_key)
        if isinstance(val, (int, float)):
            out[const] = int(val)
        else:
            missing.append(f"{const} ({pak_key})")

    lines = [
        "# Auto-generated from BATTLE_GLOBAL_CONFIG.json — do not edit.",
        "# Regenerate with: uv run python -m roco.compiler.gen_prefix_map",
        "",
    ]
    for k, v in out.items():
        lines.append(f"{k} = {v}")
    lines.append("")
    PAK_RULES_PATH.write_text("\n".join(lines), encoding="utf-8")

    if missing:
        print(f"WARNING: pak_rules missing values for: {missing}", file=sys.stderr)
    return out


def main() -> None:
    h = generate_handler_indices()
    print(f"handler_indices.py: {len(h)} constants -> {INDICES_PATH}")
    print(f"handler_table.py:   {len(h)} handlers   -> {TABLE_PATH}")

    result = generate_prefix_map(h)
    PREFIX_MAP_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    stats = result["stats"]
    print(f"prefix_handler_map.json: {stats['total_prefixes']} prefixes "
          f"({stats['mapped_prefixes']} mapped, {len(stats['unmapped_prefixes'])} unmapped) -> {PREFIX_MAP_PATH}")
    if stats["unmapped_prefixes"]:
        print(f"  unmapped: {stats['unmapped_prefixes']}", file=sys.stderr)

    rules = generate_pak_rules()
    print(f"pak_rules.py: {len(rules)} constants -> {PAK_RULES_PATH}")

    groups = generate_mark_groups(h, result)
    print(f"mark_groups.py: {len(groups)} cover groups -> {MARK_GROUPS_PATH}")

    pak_op_count = generate_pak_ops()
    print(f"pak_ops.py: {pak_op_count} prefixes -> {PAK_OPS_PATH}")

    chart_size = generate_type_chart()
    print(f"type_chart.py: {chart_size}x{chart_size} BPS table -> {TYPE_CHART_PATH}")

    weather_count = generate_weather_decoders()
    print(f"weather_decoders.py: {weather_count} pak weather effects -> {WEATHER_DECODERS_PATH}")

    counter_count = generate_counter_skill_table()
    print(f"counter_skill_table.py: {counter_count} counter response skills -> {COUNTER_SKILL_TABLE_PATH}")


if __name__ == "__main__":
    main()
