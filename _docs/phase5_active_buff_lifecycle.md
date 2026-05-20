# Phase 5A Active Buff Lifecycle

## Why

Up to Phase 4 the kernel had **no concept of "which buff is currently
on which pet"**.  A pak buff_id was decoded once and its effects were
OR'd straight into permanent stat lanes on ``PetState``
(``buff_stages``, ``status_flags``, ``lifedrain_bps``, …).  This made
three later goals impossible:

* derive effective immunity from active buffs (Phase 5B);
* expire / dispel a buff by id (Phase 5B, 5C);
* delete the Phase 3 ack rows for buff-driven gaps, since deletion
  requires a real runtime that holds the buff.

Phase 5A lays the data foundation: one packed integer per pet, eight
fixed lanes, each carrying ``(buff_id, source_side, source_slot,
duration)``.  No consumer is wired in this round.  No Phase 3 ack is
removed.  ``BUFF_IMMUNITY_TABLE`` (Phase 2A) is still unconsumed.

## Packed ledger schema

`PetState.active_buffs` is a single Python ``int`` (arbitrary
precision) holding **8 lanes × 64 bits = 512 bits**.  Each lane is
laid out as:

| field          | bits   | width | range                                    |
| -------------- | ------ | ----- | ---------------------------------------- |
| `buff_id`      | 0..31  | 32    | `1..0xFFFFFFFF` (0 = empty-lane sentinel) |
| `source_side`  | 32..35 | 4     | `0` or `1` (Phase 5A; field reserved 4b) |
| `source_slot`  | 36..39 | 4     | `0..7`                                   |
| `duration`     | 40..47 | 8     | `0..255`                                 |
| `reserved`     | 48..63 | 16    | must be `0`                              |

The lane shape mirrors the existing packed-int style of
``PetState.cooldowns`` and ``SideState.cost_mods`` so the fixed-update
``copy_state`` contract still holds — copying ``active_buffs`` is one
``int`` copy.

**Empty lane = `buff_id == 0`**.  Lane index 0 carries no special
meaning; an all-zero lane at slot 0 is still "empty" by the sentinel.

## API location

All packing helpers live in `roco/engine/kernel/active_buffs.py`.
`PetState` only carries the field; `state.py` stays free of
bit-shift code.  `turn_end.py` imports the one helper it needs
(`tick_active_buffs`) and nothing else.

Helper surface:

```python
pack_active_buff(buff_id, source_side, source_slot, duration) -> int
active_buff_id(lane)            -> int
active_buff_source_side(lane)   -> int
active_buff_source_slot(lane)   -> int
active_buff_duration(lane)      -> int
set_active_buff_slot(packed, slot_idx, lane) -> int
iter_active_buffs(packed) -> Iterable[(slot_idx, lane)]
add_active_buff(packed, buff_id, source_side, source_slot, duration) -> int
remove_active_buff(packed, slot_idx) -> int
tick_active_buffs(packed) -> int
```

All bit-shifts are confined to these functions.  Callers must not
hand-edit lane bits.

## Validation

Every helper raises `RuntimeError` (never silently truncates) when
input falls outside the schema:

* `pack_active_buff(buff_id=0, ...)` is rejected — 0 is the empty
  sentinel.  To clear a slot use `remove_active_buff` or a literal
  ``0``.
* Field range checks: `source_side` in `{0, 1}`, `source_slot` in
  `0..7`, `duration` in `0..255`, `buff_id` in `1..0xFFFFFFFF`.
* `set_active_buff_slot` rejects invalid `slot_idx`, lane values
  outside `0..(1<<64)-1`, negative `packed`, and any non-empty lane
  whose reserved bits (48..63) are non-zero.
* `add_active_buff` raises with `"capacity 8"` when no empty lane
  remains.  No eviction, no overwrite.

Error messages always cite the field name, observed value, and
allowed range, so a `pytest -v` failure points straight at the
violating field.

## Duration semantics

`tick_active_buffs` runs once per round, inside
`_tick_side_turn_state` (the same per-side housekeeping pass that
ticks `cooldowns` and `cost_mods`):

* `duration == 0` — **persistent**.  The lane is untouched by tick.
  Use this for "stays until dispelled" buffs.
* `duration > 1`  — duration decreases by 1; every other bit
  (buff_id, source_side, source_slot, reserved) stays exactly the
  same.
* `duration == 1` — the lane **expires** this tick.  All 64 bits of
  that lane are cleared, freeing the slot for a future
  `add_active_buff`.

Empty lanes are also a no-op.  Pure function over packed ints; no
side effects.

## Turn-end integration

The tick is placed in `_tick_side_turn_state` in
`roco/engine/kernel/residual/turn_end.py`, next to the existing
cooldown / cost-mod ticks.  Two reasons for the position:

1. It runs **after** weather/status damage has already been computed
   this turn.  If we ticked before damage, an expiring buff would
   disappear before damage code consulted it.
2. It sits next to the other "duration countdown" maintenance
   (cooldowns, cost_mods) so the per-turn maintenance lives in a
   single block.

Because every pet defaults to `active_buffs == 0`, the new tick is
**behaviour-neutral** for the entire existing test suite: lanes are
empty, tick yields the same packed int back, nothing changes.

## Duplicate policy

`add_active_buff` in Phase 5A does **not** dedupe.  A second call
with the same `buff_id` fills the next empty lane rather than
refreshing the existing lane's duration.

Refresh, replace-on-reapply, "same family stacks", "different
sources stack independently" — these are family-specific behaviours
that the first real consumer (Phase 5B / 5C) will define.  Defining
them now would freeze a guess.  Phase 5A only ships "first empty
lane" semantics.

## Explicitly out of scope for 5A

* No `dispel_active_buffs_matching` helper.
* No reading of `BUFF_IMMUNITY_TABLE` at runtime.
* No new handler (`H_BUFF_IMMUNITY`, …) or op wiring.
* No deletion of `effect_gap_acknowledgements.jsonl` rows.
* No reducer refactor (`apply_*_deltas`); that is Phase 5D.
* No SideState / KernelState / StageCtx changes.
* No `PetState` changes beyond the appended `active_buffs` field.

## Future consumers (non-binding intent)

These are how 5B / 5C / 5D are *expected* to use the ledger.  Nothing
below is implemented in 5A; the ledger is intentionally consumer-free.

* **Phase 5B — immunity**: derive effective immunity flags by
  iterating `iter_active_buffs(pet.active_buffs)` and OR'ing
  `BUFF_IMMUNITY_TABLE.get(buff_id, 0)`.  Guards in
  `apply_status_effect` / force-switch / energy-drain / leech ops.
* **Phase 5C — timing hooks**: add helper consumers from
  `TIMING_FAINT` / teammate-death / bench-status / entry-scaling
  paths that inspect the ledger for entry- and event-driven buffs.
* **Possible later**: a `dispel_active_buffs_matching(pred)` helper
  once the first concrete dispel family lands.

Every ack deletion driven by these consumers must satisfy the
Phase 5 three-rule gate:

1. Real runtime implementation,
2. A kernel test for that buff / effect,
3. Pak evidence already cited in `effect_gap_acknowledgements.jsonl`
   for the ack row being removed.

The ledger alone deletes no acks.

## TIMING_PASSIVE_COND deferred (Phase 5C-i note)

`TIMING_PASSIVE_COND` (cast_moment 26) is defined in
`roco/engine/kernel/op_rows.py` but **no dispatcher currently runs
ability rows at that timing**.  `tick_ability_turn_end` only calls
`run_skill_timing(..., TIMING_TURN_END=12, ctx)`; `mechanics._execute`
only dispatches BEFORE_MOVE / CALC_DAMAGE / TAKE_DAMAGE / AFTER_MOVE.

Pak buff `20030160` (zero-energy auto self-switch) is registered on
ability `200166` at **both** cast_moment 11 (TIMING_AFTER_MOVE) and
cast_moment 26 (TIMING_PASSIVE_COND).  Phase 5C-i wires the base_id
seed `2003016 → H_AUTO_SWITCH_ON_ZERO_ENERGY`, which lets the
decoder classify both rows and removes the matching ack entries
under the strict bidirectional gate.  The cast_moment 11 row runs
via the existing `_run_ability_timing(actor, TIMING_AFTER_MOVE, ctx)`
path and delivers the buff's behaviour.  The cast_moment 26 row is
decoder-classified to the same handler but runtime-inert — it sits
in `ABILITY_EFFECT_ROWS` and never executes.

This is acceptable because pak registers the same buff at two
timings and either dispatcher would do the same thing; honest naming
matters more than dual coverage.  Wiring `TIMING_PASSIVE_COND` is a
separate phase — pak says nothing about whether 26 belongs at
turn_end, after_move, or in a per-residual pass, and guessing would
freeze the wrong contract.  Future phase: investigate pak's intent
for cast_moment 26 (cross-reference other rows that use it) before
choosing a dispatcher position.
