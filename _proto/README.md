# Vendored proto schemas

8 battle-related `.proto` files copied from
[P0pola/Roco-Kingdom-World-Data](https://github.com/P0pola/Roco-Kingdom-World-Data)
(`PB/proto_out/`).  They define:

* `xls_enum.proto` — `EffectType` (89 entries, matches
  `EFFECT_CONF.effect_order` 1:1), `BuffType` (143 entries, matches
  `BUFFBASE_CONF.buffbase_order` 1:1), `SkillDamType`, plus 100+
  other gameplay enums.  The canonical naming source for everything
  the compiler currently calls a "magic number" axis.
* `battle_data.proto` — battle messages + `PET_BIT_TYPE` /
  `BATTLER_BIT_TYPE` / `BATTLEFIELD_BIT_TYPE` (pkmn/engine-style
  bit flags), `DamageParam`, `RestraintType`, `SKILL_RESULT_TYPE`.
* `battle_buff_data.proto` — `BuffData_N` messages defining the
  runtime payload shape per `buffbase_order`.
* `battle_proto.proto` — battle notify messages (round start,
  perform start, settle).
* `com_battle.proto`, `com_battle_enum.proto`, `com_pet.proto`,
  `com_pet_skill.proto` — supporting types.

## Not used by the current compiler

The compiler today reads pak JSON / Lua directly and dispatches via
the handler-axis decorators (see `roco/engine/kernel/op_meta.py`).
These proto files are **reference material**, not a build
dependency — they live here so:

* Cross-checking what `effect_order=N` *means* (look up
  `ET_<NAME>` in `xls_enum.proto`) doesn't require a network fetch.
* The eventual agent layer (`roco/agent/`, planned) can deserialize
  server battle messages without re-vendoring at that point.

## Sync

Files copied verbatim on 2026-05-20.  If pak/proto evolves upstream,
re-fetch via:

```
git -C ~/code/auto-pvp-ref/Roco-Kingdom-World-Data pull
cp ~/code/auto-pvp-ref/Roco-Kingdom-World-Data/PB/proto_out/{xls_enum,battle_data,battle_buff_data,battle_proto,com_battle_enum,com_battle,com_pet,com_pet_skill}.proto _proto/
```
