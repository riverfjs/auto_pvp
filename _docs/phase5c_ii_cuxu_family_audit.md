# Phase 5C-ii — 隐藏条款 三行结构 / cuxu·jixu (蓄力·积蓄) family audit

## Why this doc exists

`effect_gap_acknowledgements.jsonl` still carries two rows that both cite skill
`7180200 隐藏条款` (desc *"与敌方交换携带的技能。"*) as evidence:

| ack row             | source                                                       |
| ------------------- | ------------------------------------------------------------ |
| `buff_id=20030330`  | `BUFF_CONF` direct ref, `family_key=buff_conf_direct:prefix_2003` |
| `effect_id=1004076` | `EFFECT_CONF` compound, `family_key=effect_conf:t1:o4`       |

The natural-looking move during Phase 5C-ii was: *"the skill desc says exchange
moves; the runtime already does the swap via `EFFECT_CONF[1047002]`; just seed
`base_id=2003033 → H_EXCHANGE_MOVES` and the prefix-2003 ack disappears."*

This doc records why that move was **rejected**, and what the next family knife
will need.

## Pak structure for skill 7180200 (cast_moment 11, target_type 2)

Three `skill_result` rows share `cast_moment=11` / `target_type=2` /
`success_rate=10000`:

| effect/buff | pak editor_name | status |
| ----------- | --------------- | ------ |
| `EFFECT_CONF[1047002]`   | **交换双方技能** | already wired to `H_EXCHANGE_MOVES` via `roco/compiler/rules/exact_effects.jsonl` |
| `EFFECT_CONF[1004076]`   | **驱散蓄力**     | deferred ack (`effect_conf:t1:o4`)                                              |
| `BUFF_CONF[20030330]`    | **免疫积蓄**     | deferred ack (`buff_conf_direct:prefix_2003`); `buff_base_ids=[2003033]`, no pak desc, `buff_group_reduce=[{reduce_type:2, reduce_param:[2,1]}]` |

So skill 7180200 actually delivers three different things at once:

1. **Swap moves** (1047002) — implemented.
2. **Dispel "charge"** (1004076 "驱散蓄力") — unimplemented.
3. **Immune to "buildup"** (20030330 "免疫积蓄") — unimplemented.

The skill-level desc `"与敌方交换携带的技能。"` only describes (1). Pak
piggy-backs (2) and (3) on the same skill cast — their pak names belong to a
separate "蓄力 / 积蓄" (charge / buildup) family.

## Why `2003033 → H_EXCHANGE_MOVES` is rejected

It would work, idempotently:

- `op_exchange_moves` (`roco/engine/kernel/op_mods/skill.py:51-52`) sets
  `ctx.swap_moves = 1` and reads no row payload.
- The single consumer at `roco/engine/kernel/residual/after_move.py:188-192`
  guards with `if ctx.swap_moves:` and swaps `actor.moves ↔ target.moves`
  (active slots).  Running the op N times during a single action still results
  in **exactly one swap** — the flag is a boolean, not a counter.
- `StageCtx.swap_moves` is defaulted to `0` (`roco/engine/kernel/ctx.py:66`) and
  re-zeroed every action by `StageCtx.reset()`
  (`roco/engine/kernel/ctx.py:126-128`), so the flag cannot leak across actions.
- `op_exchange_moves` does **not** touch `PetState.active_buffs`; the swap is
  a one-shot stateless effect.

But "idempotent / runtime-safe" is not the same as "pak-first justified."
BUFF_CONF[20030330]'s pak editor_name is **免疫积蓄**, not 交换技能.  Routing
it through `H_EXCHANGE_MOVES` would mean: *every time a "buildup immunity"
buff fires, the swap-moves consumer rereads its flag and noops* — true, but
the ledger now claims that "免疫积蓄 ⇒ exchange moves," which contradicts the
only pak handle we have on the buff (its name).

Shared `desc_quote` between the two ack rows also isn't evidence: pak puts the
skill desc on every `skill_result` of that skill, even when the rows have
distinct semantics.

Phase 5C-ii therefore declines the convenience wire and defers both rows to a
dedicated **cuxu·jixu family** knife.

## Runtime pointers (for the family knife)

- `op_exchange_moves` body: `roco/engine/kernel/op_mods/skill.py:51-52`
- `ctx.swap_moves` default: `roco/engine/kernel/ctx.py:66`
- `StageCtx.reset` (clears `swap_moves` to 0 each action):
  `roco/engine/kernel/ctx.py:126-128`
- `ctx.swap_moves` consumer (the actual swap):
  `roco/engine/kernel/residual/after_move.py:188-192`
- Handler index: `H_EXCHANGE_MOVES = 71`
  (`roco/generated/handler_indices.py`)
- Skill 7180200 in catalog: `roco/generated/catalog_hot.py` `SKILL_EFFECT_ROWS`
  currently emits a single row `[71, 11, 2, 10000, 0, 0, 0, 0]` from
  effect 1047002.  Effects 1004076 and 20030330 remain decoder gaps.

`PetState.active_buffs` (Phase 5A ledger) is **not** consumed by the
exchange-moves path.  Whether 免疫积蓄 should ride the ledger (likely yes
— "immunity to something" maps cleanly onto a duration-tracked active buff)
is a design question for the family knife.

## What the cuxu·jixu family knife will need

1. **Survey pak**.  Grep `pak-public-kit/output/data/BinData/EFFECT_CONF.json`
   and `BUFF_CONF.json` for every `editor_name` containing one of
   `蓄力 / 积蓄 / 驱散`.  Collect the full set of effect_ids and buff_ids,
   along with referencing skill / ability counts, before designing handlers.

2. **Decide handler shape**.  Likely additions:
   - one or more new `op_*` handlers for "dispel charge" and "apply
     buildup-immunity buff";
   - `BUFF_CONF[20030330]` (and family-mates) probably belongs in
     `PetState.active_buffs` so the immunity lingers per pak duration rules;
   - `IMMUNITY_SPECS` may grow a new bit (e.g. `IMMUNITY_BUILDUP`) joined into
     `STATUS_IMMUNITY_FLAGS_BY_STATUS_TYPE` only if pak buildup is modelled as
     a `StatusType`.

3. **Tests**.  End-to-end via `mechanics.update` for skill 7180200, covering
   all three rows in one shot:
   - moves swap (1047002) — currently has **zero** kernel-test coverage;
     the family knife should backfill this even though 1047002 is already
     wired;
   - dispel cuxu (1004076) — assert pak's "charge" representation is cleared
     on the target;
   - jixu immunity (20030330) — assert the active-buff ledger gets the lane
     and that subsequent charge-applying ops are no-ops while the lane lives.

4. **Ack cleanup**.  Both `effect_id=1004076` and `buff_id=20030330` ack rows
   become deletable only after (1) real runtime, (2) the kernel test above,
   (3) the pak evidence already cited in each ack row's `evidence` block.

## Lessons reaffirmed

- Before wiring a deferred ack, read the referenced `BUFF_CONF` /
  `EFFECT_CONF` row directly — not just the upstream skill / ability desc.
  Pak frequently bundles unrelated effects under one skill desc.
- "Runtime is provably idempotent" is a safety property, not a semantic
  proof.  pak-first means the pak-side name has to match the kernel-side
  meaning.
- `note` fields in `effect_gap_acknowledgements.jsonl` flow into
  `_docs/effect_family_audit.md` verbatim, so keep them one short sentence
  plus a pointer.  Long-form belongs in a dedicated doc like this one.
