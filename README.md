# Auto PVP

PVP fixed-kernel simulator. Runtime battle code imports integer-only static
catalogs; it does not read pak files, Lua, JSON, JSONL, SQLite, or dynamic rule
registries.

## Update Path

Use this sequence when the pak dump changes:

```bash
tools/update_pak_public_kit_sparse.sh
uv run roco-refresh-artifacts
uv run pytest -q
```

`pak-public-kit` is a sparse partial submodule. The update script fetches only:

```text
pak-public-kit/output/data
pak-public-kit/output/scripts
```

`output/assets` is intentionally not checked out.

## Data Flow

```text
pak-public-kit/output/data
+ pak-public-kit/output/scripts/lua/Data/Config/Enum.lua
    |
    v
compiler_v2
    - static pak/Lua facts
    - structural effect decoders
    - engine op_meta handler axes
    |
    v
roco/generated/*
    |
    v
roco.compiler_v2.catalog_compiler
    - pak canonical records
    - compiled skill/ability effect rows
    |
    v
roco/generated/catalog_hot.py
roco/generated/catalog_debug.py
    |
    v
engine/kernel
    - hot.PETS / hot.SKILLS
    - hot.SKILL_EFFECT_ROWS / RANGES
    - HANDLERS[handler_idx](ctx, row)
```

The effect row layout is fixed end to end:

```text
(handler_idx, timing, target, flags, cond, p0, p1, p2, p3)
```

Older text sometimes called this `(handler_idx, timing, target, rate, p0-p3)`;
the runtime tuple is the 9-field row above.

## Refresh Pipeline

`uv run roco-refresh-artifacts` runs these steps in order:

1. `roco.compiler_v2.gen_prefix_map`
   Generates static pak/Lua facts and handler dispatch artifacts under
   `roco/generated/`.
2. `roco.compiler_v2.catalog_compiler`
   Builds `catalog_hot.py` and `catalog_debug.py` directly from pak-derived
   canonical records.
3. `roco.compiler_v2.build_effect_families`
   Writes generated audit output:
   `roco/generated/audit/effect_families.jsonl` and
   `_docs/effect_family_audit.md`.
4. `roco.compiler_v2.build_effect_families --check`
   Verifies the audit output is deterministic.
5. `roco.compiler_v2.pak_schema_audit`
   Writes `_docs/pak_schema_audit.md`.
6. `roco.compiler_v2.pak_schema_audit --check`
   Verifies the schema audit is deterministic.

`uv run roco-refresh-artifacts --check` is for clean-tree/CI verification. Do
not use `--check` immediately after a real pak update; a real update is expected
to produce a diff.

## Generated Artifacts

Runtime and data generated files live in `roco/generated/`:

```text
catalog_hot.py              kernel runtime catalog
catalog_debug.py            names and debug lookup tables
handler_table.py            handler_idx -> op_* function table
handler_indices.py          H_* constants
handler_order.py            append-only handler order
handler_registry.json       persisted handler registry
prefix_handler_map.json     BUFF_CONF / BUFFBASE_CONF handler maps
buffbase_params.py          BUFFBASE_CONF params
pak_ops.py                  pak op/prefix metadata
battle_globals.py           BATTLE_GLOBAL_CONFIG constants
skill_dam_types.py          SkillDamType -> element adapter
type_chart.py               pak type effectiveness table
weather_decoders.py         generated weather effect decoders
counter_skill_table.py      counter response skill lookup
buff_immunity_table.py      immunity flags derived from pak text/structure
mark_groups.py              mark cover groups
natures.py                  nature stat modifiers
canonical_adapters.py       pak -> canonical adapters
static/lua_enums.py         Lua enum snapshot
static/pak_axes.py          compiler-only effect/buff axes joined to enum names
static/manifest.py          source hashes
audit/effect_families.jsonl generated machine-readable audit
```

Top-level generated modules are runtime/data adapters. `static/pak_axes.py` is a
compiler-only effect/buff axis snapshot and intentionally does not duplicate
`battle_globals.py` or `skill_dam_types.py`.

`roco/generated/audit/effect_families.jsonl` is not a rule file. It is generated
audit data. Do not edit it by hand.

## Pak Lookup CLI

`uv run roco-pak` is the inspection surface for pak data. It reads
`pak-public-kit/output/data` directly and does not import the engine or generated
runtime catalog.

```bash
uv run roco-pak pet 音速犬
uv run roco-pak skill 火焰箭
uv run roco-pak skill 毒沼
uv run roco-pak ability 专注力
```

The CLI supports:

- pet name/id -> base skills, bloodline skills, skill-stone skills, abilities
- skill name/id -> pets that can learn it, including skill-stone unlock sources
- ability name/id -> owning pets

Skill-stone unlock text is joined from pak tables:
`LEVEL_SKILL_CONF`, `BAG_ITEM_CONF`, `handbook-rewards.json`, and
`PET_HANDBOOK`.

## Engine Runtime

The hot path is in `roco/engine/kernel`.

`mechanics.update(state, c1, c2)` executes:

```text
start_turn -> order -> execute -> damage -> after_move -> end_turn -> check_winner
```

The engine imports:

```python
from roco.generated import catalog_hot as hot
from roco.generated.handler_table import HANDLERS
```

At runtime:

```text
skill_id
  -> hot.SKILL_EFFECT_RANGES[skill_id]
  -> hot.SKILL_EFFECT_ROWS[start:end]
  -> run_skill_timing(...)
  -> HANDLERS[handler_idx](ctx, row)
```

Engine files contain concrete battle logic only. They should not maintain
pak id, effect id, buff id, buffbase order, prefix, or JSONL dispatch tables.

## Compiler Rules

Compiler v2 uses pak structure first:

```text
EFFECT_CONF.effect_order
BUFFBASE_CONF.buffbase_order
BUFF_CONF.buff_base_ids
SKILL_CONF.skill_result
Lua Enum names for numeric-axis labels
```

Allowed compiler logic:

- source readers and emitters
- structural decoders based on pak axes and parameter shape
- small explicit policy adapters when pak does not encode runtime behavior
- engine-owned `op_meta` declarations resolved through generated Lua enum data

Forbidden long-term pattern:

- hand-maintained `effect_id -> handler`
- hand-maintained `buff_id -> handler`
- hand-maintained `buffbase_order -> handler`
- JSONL files acting as runtime dispatch rules
- engine importing pak/Lua/JSON/SQLite

## Directory Map

```text
pak-public-kit/              sparse submodule: output/data + output/scripts only
tools/                       maintenance scripts, including sparse pak update
roco/generated/              generated runtime/data artifacts
roco/generated/audit/        generated machine-readable audits
roco/compiler_v2/            pak/Lua readers, emitters, structural decoders
roco/compiler_v2/static_artifacts/
                             generated static artifact emitters split by domain
roco/compiler_v2/rules/      hand-maintained migration inputs only, not dispatch source
roco/data/                   pak/team canonicalization and refresh orchestration
roco/pak_query/              independent pak lookup CLI
roco/engine/kernel/          fixed integer battle kernel
roco/engine/facade/          user-facing name/id boundary
_docs/effect_family_audit.md generated human-readable effect coverage audit
_docs/pak_schema_audit.md    generated pak schema/axis audit
_docs/damage-formula.md      hand-written damage formula note
```

## Development Commands

```bash
uv run roco-refresh-artifacts
uv run pytest -q
```

Only regenerate the static pak/Lua layer:

```bash
uv run python -m roco.compiler_v2.gen_prefix_map
```

Add a new runtime handler:

1. Write an `op_*` function under `roco/engine/kernel`.
2. Add `op_meta` declarations only when the handler owns a pak axis.
3. Run `uv run roco-refresh-artifacts`.
4. Add or update focused tests.

## Reference

The fixed-kernel shape is inspired by [pkmn/engine](https://github.com/pkmn/engine).
