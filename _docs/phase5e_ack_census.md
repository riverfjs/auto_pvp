# Phase 5E: ack census + next-family selection

**Date**: 2026-05-20 · **Base commits**: `36de19e` (5C-iii AbilityFlagOutcome) → `45451b8` (5D after_move split)
**Scope**: investigation only — no runtime / generated / canonical / rules changes, no ack deletions.

## 1. Headline numbers (current strict build)

- Total ack rows: **45** (`roco/compiler/rules/effect_gap_acknowledgements.jsonl`).
- `used_dropped abilities`: **24** (down from 28 pre-5C-iii).
- `used_dropped skills`: **21** (unchanged).
- Strict bidirectional gate: passes; 0 stale ack, 0 unack-used-gap.
- `pytest`: 255 passed.

The ack file is `used`-only (skill_effect_gaps / ability_effect_gaps that some `team_pets` row actually references); unused gaps live in DB but never need acks.

## 2. Aggregation by family_key

| family_key                          | acks | source breakdown   | shape note                                                  |
|-------------------------------------|------|--------------------|-------------------------------------------------------------|
| `effect_conf:t3:o34`                | 9    | 9 ability          | entry-time "team historical skill-use counter" → buff       |
| `buff_conf_direct:prefix_2040`      | 8    | 3 ability, 5 skill | active-buff lifecycle (蓄力 / 萌化 / 应对 / 系别 变换)      |
| `effect_conf:t3:o22`                | 3    | 3 ability          | entry-time "team composition" → buff                        |
| `effect_conf:t3:o64`                | 3    | 3 ability          | "carried-skill-type count" → per-type damage/cost mod       |
| `effect_conf:t3:o77`                | 2    | 2 ability          | entry-time "self/enemy at 1 MP" → all-stat buff             |
| `effect_conf:t3:o43`                | 2    | 2 skill            | skill-conditional self-effect (HP threshold gate)           |
| `effect_conf:t1:o53`                | 2    | 2 skill            | per-poison-stack stat multiplier (compound buff)            |
| `effect_conf:t3:o70` / `o75` / `o66` / `o61` / `o81` / `o79` / `o83` / `o84` / `o59` / `o16` | 1 each | mixed | one-off bespoke semantics                |
| `effect_conf:t1:o52` / `o33` / `o32` / `o4`             | 1 each | skill                | bespoke compound / no-buff t1                                  |
| `buff_conf_direct:prefix_2003`      | 1    | 1 skill            | 隐藏条款 deferred (see 5C-ii doc)                            |

**Two clusters carry most of the ack mass**: t3 entry-time-trigger families (o22 / o34 / o61 / o64 / o77 = **18 acks**, all ability source) and the prefix_2040 active-buff family (**8 acks** mixed).

## 3. AbilityFlag bit population state

`roco/common/enums.py::AbilityFlag` defines 30 named bits. Current `roco.generated.catalog_hot.ABILITY_FLAGS`:

- **Populated** (via `ability_flags_from_effects.jsonl` + 5C-iii codegen): `HEAL_ON_BURN_DAMAGE` (1 ability), `HEAL_ON_POISON_DAMAGE` (1 ability).
- **Unpopulated** (28 bits): everything else.
- **Unconsumed by kernel** (0 grep hits under `roco/engine/`): `REVIVE`, `CUTE_NO_CAP`, `HALF_METEOR_FULL_DAMAGE`, `CHARGE_FREE_SKILL`, `BURST_EXTEND`. Populating these would be ineffective; the runtime path needs to be written first.
- **Consumed but unpopulated** (~25 bits): runtime is ready but no source ever lights the bit. Examples include `BURN_NO_DECAY`, `EXTRA_POISON_TICK`, `EXTRA_FREEZE_ON_FREEZE`, `CUTE_LETHAL_SHIELD`, `BUFF_EXTRA_LAYERS`, `FIRST_ACTION_EXTRA_USE`, `HEAL_HP_PER_ENERGY_GAIN`, `SHARE_GAINS`, `MARK_STACK_NO_REPLACE`, `COPY_SWITCH_STATE`, `BARREL_ACTIVE`, etc.

## 4. Special line 1 — are there more 5C-iii-clean AbilityFlagOutcome candidates?

**Answer: no clean follow-ups in the current ack file.**

The 5C-iii pattern required all four of:

1. `AbilityFlag` bit exists and runtime consumes it.
2. Pak source row is in `EFFECT_CONF` (not BUFF_CONF / SKILL_CONF metadata / pet table).
3. `effect_param[1] == [1]` (no multiplier semantics).
4. Trigger condition is a passive status type, encodable as a single bit.

Scanning the 45 acked rows against each unpopulated bit:

| candidate bit             | ack hit?                                        | blocker                                                                |
|---------------------------|-------------------------------------------------|------------------------------------------------------------------------|
| `CHARGE_FREE_SKILL`       | row 6 (200174 嫉妒)                              | source is `BUFF_CONF[20400210]` (prefix_2040), not EFFECT_CONF          |
| `BUFF_EXTRA_LAYERS`       | no ack                                          | population would need a BUFF_CONF or per-pet metadata source            |
| `BURN_NO_DECAY` / `EXTRA_POISON_TICK` / `EXTRA_FREEZE_ON_FREEZE` | no ack | pak does not appear to encode these as standalone EFFECT_CONF rows      |
| `MARK_STACK_NO_REPLACE`   | no ack                                          | likely pet/ability metadata, not effect-row driven                      |
| `FIRST_ACTION_EXTRA_USE`  | no ack                                          | same                                                                    |
| `REVIVE`                  | 5 EFFECT_CONF rows match by editor_name keyword | none are in acks (no `team_pet` references them), and kernel has 0 consumers |

No remaining ack row maps to "single AbilityFlag bit, `EFFECT_CONF` shape, multiplier == 1". The 5C-iii vein is mined.

## 5. Special line 2 — `effect_id 1004076` / `buff_id 20030330` (蓄力 / 积蓄)

Already audited in `_docs/phase5c_ii_cuxu_family_audit.md` (commit `cd91f0f`). Findings recap:

- `EFFECT_CONF[1004076].editor_name = "驱散蓄力"` — dispels a 蓄力 buff. Not exchange-moves.
- `BUFF_CONF[20030330].editor_name = "免疫积蓄"` — immunity to 积蓄 accumulation. Not exchange-moves.
- The two acks (rows 42, 43) are both held by skill `7180200 隐藏条款` whose desc reads "与敌方交换携带的技能". The pak `skill_result` references these buff/effect ids, but neither has the swap semantic the description claims.
- Hypothesis: pak encodes "exchange moves" as something other than the listed buff/effect pair (perhaps a pak-side handler keyed on a different ID), but we have not located it. Without the real semantic source, wiring 1004076 / 20030330 to `H_EXCHANGE_MOVES` would be semantic speculation and was rejected during the 5C-ii investigation.

**Status**: still deferred. Closing these two requires either (a) deeper pak-side exhaustive search for skills referencing a swap-moves primitive, or (b) accepting that the actual semantic is encoded elsewhere (e.g., skill-specific scripted handler) and pivoting to that source.

## 6. Special line 3 — which acks really need mechanics / timing dispatcher rework?

Bucketing by what infrastructure they need:

### 6a. Entry-time conditional buff trigger (16 ack rows)

Families `effect_conf:t3:o22 / o34 / o61 / o64 / o77`. All ability source.

Pak shape evidence (inspecting `EFFECT_CONF.json` directly for one row per family):

```
o22  effect_id=1022004  param=[[13],[0],[0],[20010016],[299901]]            # 队伍每有1个虫系
o34  effect_id=1034012  param=[[5],[0],[0],[1],[20320225],[299901],[-1],[0]] # 队伍每使用1次水系技能
o61  effect_id=1061002  param=[[20011010],[299901]]                         # 每次进入战斗
o64  effect_id=1064010  param=[[5],[0],[0],[0],[20320420],[299901]]         # 每携带1个水系技能
o77  effect_id=1077001  param=[[0],[1],[1],[20011531]]                      # 自身魔力=1出场
```

Common structure across all five families:

- A trigger-condition prefix (variable length, family-specific positional meaning).
- A `BUFF_CONF[buff_id]` reference identifying the buff to apply on trigger.
- A trailing `299901` sentinel in o22 / o34 / o61 / o64 (likely a cap/maxiter constant — semantic to be confirmed).

This is the same pattern the prior pak effect rebuild established for active buffs: "trigger → BUFF_CONF[buff_id]". The runtime hook is "on switch-in, walk the entering pet's ability effect rows, evaluate trigger conditions, apply matching buff_deltas". No `mechanics.py` rewrite required — the entry hook lives in `roco/engine/kernel/switch.py::swap_in` (already exists for COPY_SWITCH_STATE / BARREL_ACTIVE).

What is **not yet decoded**:

- Positional meaning of each param slot per family (element id? skill category? side ref? counter scope?).
- Whether `299901` is a constant or a cap value.
- Whether the trigger requires a side-level historical counter (t3:o34's "team has used N times") or only a static query (t3:o22 / o61 / o64 / o77).
- Whether the "result buff_id" should be applied as `buff_stages` delta, or via a new active-buff entry, or via direct stat-multiplier.

This is the largest pure-data investigation slice. Once decoded, ~16 acks can be closed by adding a new outcome type (e.g. `EntryConditionalBuffOutcome`) + a small entry-hook reducer.

### 6b. Active-buff lifecycle expansion (prefix_2040, 8 ack rows)

The pak effect rebuild already established `buff_base_id` as kernel ops. The 8 prefix_2040 acks reference buff_base_ids `2040013 / 2040021 / 2040038 / 2040039–2040047 / 2040069` — each tied to a distinct lifecycle behavior:

- `2040021` (嫉妒): 蓄力 buff that permits any carried skill.
- `2040013` (守护者): 萌化 counter input for entry cost reduction.
- `2040038` (击鼓传花): 脱离 → buff inheritance on next entry.
- `2040039 / 2040040` (月光合奏): 萌化 stacks → combo modifier.
- `2040041` (月牙雪糕): freeze stacks → 星陨印记 conversion.
- `2040042–2040047` (天光): weather element → skill element shift.
- `2040069` (升龙咆哮 / 吹炎 / 龙之利爪): 蓄力 timing buff (multi-skill).

Each buff_base_id corresponds to a different kernel touchpoint. There is no single primitive to add; each is a bespoke active-buff behavior. This family is the natural successor to the existing `IMMUNITY_FORCE_SWITCH` / `active_buffs` ledger work, but burns through acks slowly (one buff_base_id per implementation knife).

### 6c. Bespoke t1 / t3 (11 ack rows)

Per-effect-id bespoke logic with no shared infrastructure: o43 (HP-conditional combo/debuff), o59 (priority-comparison combo), o66 (turn-start skill shuffle + cost mod), o70 (capture-ball metadata), o75 (inherit dead teammate IV), o79 (fixed-cost), o81 (bench energy), o83 (anti-swap), o84 (蓄力 + 应对), o16 (random devotion); compound t1 families o4 / o32 / o33 / o52 / o53.

None of these match a clean shared shape. Each requires a separate decoder/handler.

### 6d. `prefix_2003` (1 ack — special)

Sibling of the 5C-ii 蓄力 family; deferred until the actual exchange-moves source is located. Not a `mechanics.py` problem in itself; an unknown-source problem.

**Bottom line for line 3**: `mechanics.py` does NOT need to be rewritten to burn any of the 45 remaining acks. The biggest infra investments are (i) entry-time conditional buff trigger (one new outcome + entry-hook reducer in `switch.py`) and (ii) per-buff_base_id active-buff lifecycle (no shared abstraction; one knife per buff). Timing/dispatcher rework is a refactor in pursuit of code clarity, not ack burn-down.

## 7. Recommended next knife (one only)

**Phase 5F: decode the entry-time conditional buff trigger schema — investigation only.**

Why this one:
- Single largest ack cluster left (16 of 45, all ability source).
- Already aligned with the active-buff system the prior pak effect rebuild established (`BUFF_CONF[buff_id]` is the result payload).
- Entry-hook infrastructure already lives in `switch.py::swap_in`, so the runtime cost is small once schema is known.
- The investigation produces a doc + (optionally) a fresh rules jsonl draft — no kernel / generated changes, no ack deletions, low risk.

What 5F should produce (no implementation):

1. Full positional decode per family (o22 / o34 / o61 / o64 / o77) of `effect_param[0..n]`. Cross-reference each row against the canonical desc string in `_data/canonical/abilities.jsonl` to confirm the param-to-semantic mapping.
2. Identification of which side-level state each family reads:
   - static team composition (likely o22 / o64)
   - per-side cumulative skill-use counter by type/category (likely o34)
   - per-pet entry counter (likely o61)
   - current MP state at entry (likely o77)
3. Resolution of the `299901` sentinel — constant, cap, or trigger flag.
4. Concrete proposed shape of an `EntryConditionalBuffOutcome` (or split outcomes per family) — the new fourth-pipeline analogue to `AbilityFlagOutcome`.
5. A risk table for the subsequent implementation knife: which side-state is missing today, what new fields PetState / SideState need, where in `switch.py` the hook attaches.

Explicit 5F non-goals:
- No `roco/engine/kernel/**` edits.
- No `roco/compiler/rules/**` edits.
- No `_data/canonical/**` edits.
- No `roco/generated/**` edits.
- No ack deletions.

If 5F's findings reveal that **any one family** of the five is cleanly decodable in isolation (e.g., t3:o22 team composition only — static, no counter), the follow-up implementation knife should take only that single family — same conservative discipline as 5C-iii.

## 8. Explicit non-recommendations

- **Do not start with prefix_2040.** Eight acks but eight distinct bespoke behaviors; no shared infra; mehler ack-per-knife than 5F.
- **Do not start mechanics.py refactor.** No ack relief, high risk, blocks the entry-hook work above.
- **Do not revive 5C-ii 蓄力 family.** Two acks, unknown source for the real semantic; investigation cost > yield.
- **Do not lit unconsumed AbilityFlag bits** (`REVIVE` / `CUTE_NO_CAP` / `HALF_METEOR_FULL_DAMAGE` / `CHARGE_FREE_SKILL` / `BURST_EXTEND`). Wire the runtime path first; that is its own knife.
