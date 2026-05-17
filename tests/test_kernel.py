from pathlib import Path

import pytest

from roco.config.constants import MIN_DAMAGE, STARTING_ENERGY
from roco.engine import catalog_debug as debug
from roco.engine import catalog_hot as hot
from roco.engine.damage import calc_attack_damage
from roco.engine.effect_model import EffectTag, Timing
from roco.engine.enums import AbilityFlag, SkillCategory, StatusFlag, StatusType, WeatherType
from roco.engine.kernel import (
    BPS,
    DAMAGE_CONST_BPS,
    SIDE_A,
    SIDE_B,
    SKILL_CATEGORY,
    SKILL_ELEMENT,
    SKILL_ENERGY,
    SKILL_POWER,
    STAB_BPS,
    _damage,
    update,
)
from roco.engine.kernel_catalog import load_hot_catalog, validate_catalog
from roco.engine.kernel_effects import KERNEL_SUPPORTED_TAGS, StageCtx, run_skill_timing
from roco.engine.kernel_state import copy_state, make_state, move_choice, switch_choice
from roco.engine.kernel_state import pack_weather, replace_pet, set_status_count, status_stack, weather_turns, weather_type, with_status
from roco.engine.packing import DevotionIdx, MarkIdx, _set_mark, _unpack_mark


def _pet_id(name: str) -> int:
    return debug.PET_IDS_BY_NAME[name]


def _skill_id(name: str) -> int:
    return debug.SKILL_IDS_BY_NAME[name]


def test_hot_and_debug_catalog_artifacts_are_physically_split():
    assert hot.CATALOG_VERSION == debug.CATALOG_VERSION == 1
    assert hot.SCHEMA_VERSION == debug.SCHEMA_VERSION == "kernel-v1"
    assert hot.SOURCE_HASH == debug.SOURCE_HASH
    assert hasattr(hot, "PETS")
    assert hasattr(hot, "SKILL_EFFECT_ROWS")
    assert not hasattr(hot, "PET_NAMES")
    assert hasattr(debug, "PET_NAMES")
    assert load_hot_catalog() is hot


def test_hot_catalog_excludes_kernel_unsupported_effect_rows():
    supported = set(KERNEL_SUPPORTED_TAGS)
    assert all(row[0] in supported for row in hot.SKILL_EFFECT_ROWS)
    assert all(row[0] in supported for row in hot.ABILITY_EFFECT_ROWS)
    assert hasattr(hot, "SKIPPED_EFFECT_STATS")


def test_catalog_validation_rejects_version_schema_and_empty_hash():
    class VersionMismatch:
        CATALOG_VERSION = 0
        SCHEMA_VERSION = "kernel-v1"
        SOURCE_HASH = "x"

    class SchemaMismatch:
        CATALOG_VERSION = 1
        SCHEMA_VERSION = "old"
        SOURCE_HASH = "x"

    class EmptyHash:
        CATALOG_VERSION = 1
        SCHEMA_VERSION = "kernel-v1"
        SOURCE_HASH = ""

    with pytest.raises(RuntimeError, match="version"):
        validate_catalog(VersionMismatch)
    with pytest.raises(RuntimeError, match="schema"):
        validate_catalog(SchemaMismatch)
    with pytest.raises(RuntimeError, match="source hash"):
        validate_catalog(EmptyHash)


def test_choice_update_and_copy_state_smoke():
    fire = _pet_id("火花")
    water = _pet_id("水蓝蓝")
    slap = _skill_id("拍击")
    state = make_state(
        (fire,),
        (water,),
        team_a_moves=((slap,),),
        team_b_moves=((slap,),),
        rng_seed=1,
    )

    clone = copy_state(state)
    assert clone == state
    assert clone is not state
    assert clone.side_a is not state.side_a
    assert clone.side_a.pets is not state.side_a.pets

    result = update(state, move_choice(0), move_choice(0))

    assert result.state.turn == 1
    assert result.first_side == SIDE_A
    assert result.damage_a > 0
    assert result.damage_b > 0
    assert result.state.side_b.pets[0].current_hp == hot.PETS[water][1] - result.damage_a
    assert result.state.side_a.pets[0].current_energy == STARTING_ENERGY - hot.SKILLS[slap][SKILL_ENERGY]


def test_switch_priority_beats_move_speed():
    fire = _pet_id("火花")
    cat = _pet_id("喵喵")
    water = _pet_id("水蓝蓝")
    impact = _skill_id("冲击")
    slap = _skill_id("拍击")
    state = make_state(
        (fire, cat),
        (water,),
        team_a_moves=((impact,), (slap,)),
        team_b_moves=((slap,),),
        rng_seed=1,
    )

    result = update(state, switch_choice(1), move_choice(0))

    assert result.first_side == SIDE_A
    assert result.state.side_a.active == 1
    assert result.damage_b > 0


def test_order_uses_speed_then_seeded_tie_break():
    fire = _pet_id("火花")
    water = _pet_id("水蓝蓝")
    impact = _skill_id("冲击")
    slap = _skill_id("拍击")

    faster = update(
        make_state((fire,), (water,), team_a_moves=((impact,),), team_b_moves=((slap,),)),
        move_choice(0),
        move_choice(0),
    )
    assert faster.first_side == SIDE_A

    tie_a = update(
        make_state((fire,), (fire,), team_a_moves=((impact,),), team_b_moves=((impact,),), rng_seed=1),
        move_choice(0),
        move_choice(0),
    )
    tie_b = update(
        make_state((fire,), (fire,), team_a_moves=((impact,),), team_b_moves=((impact,),), rng_seed=2),
        move_choice(0),
        move_choice(0),
    )

    assert tie_a.first_side == SIDE_A
    assert tie_b.first_side == SIDE_B


def test_damage_matches_existing_formula_for_single_hit():
    fire = _pet_id("火花")
    water = _pet_id("水蓝蓝")
    impact = _skill_id("冲击")
    state = make_state((fire,), (water,), team_a_moves=((impact,),), team_b_moves=((impact,),))
    result = update(state, move_choice(0), move_choice(0))
    skill = hot.SKILLS[impact]
    actor = hot.PETS[fire]
    target = hot.PETS[water]
    type_mult = hot.TYPE_CHART_BPS[skill[SKILL_ELEMENT]][target[7]] / BPS
    if skill[SKILL_ELEMENT] == actor[7]:
        type_mult *= STAB_BPS / BPS
    expected = calc_attack_damage(skill[SKILL_POWER], actor[2], target[4], type_mult)

    assert skill[SKILL_CATEGORY] == SkillCategory.PHYSICAL.value
    assert result.damage_a == expected


def test_effect_row_stage_and_damage_rounding_semantics():
    fire = _pet_id("火花")
    water = _pet_id("水蓝蓝")
    state = make_state((fire,), (water,))
    actor = state.side_a.pets[0]
    target = state.side_b.pets[0]
    actor_row = hot.PETS[fire]
    target_row = hot.PETS[water]
    normal_element = 0
    skill = (999, normal_element, SkillCategory.PHYSICAL.value, 0, 50, 0, 1)
    ctx = StageCtx()
    ctx.reset(SIDE_A, 0, SIDE_B, 0, 999)
    run_skill_timing(
        ((EffectTag.DAMAGE.value, Timing.CALC_DAMAGE.value, 0, 0, 0, 37, 3, 0, 0),),
        (0, 1),
        Timing.CALC_DAMAGE.value,
        ctx,
    )
    ctx.power_bps = 15000
    ctx.damage_bps = 5000
    ctx.flat_damage = 7
    adjusted_power = (37 * ctx.power_bps) // BPS
    per_hit = (
        actor_row[2]
        * adjusted_power
        * DAMAGE_CONST_BPS
        * hot.TYPE_CHART_BPS[normal_element][target_row[7]]
        * BPS
        * BPS
    ) // (target_row[4] * BPS * BPS * BPS * BPS)
    expected = ((max(MIN_DAMAGE, per_hit) * 3 + 7) * 5000) // BPS

    assert ctx.power == 37
    assert ctx.hit_count == 3
    assert _damage(actor, target, skill, ctx) == expected


def test_kernel_after_move_status_and_status_ticks():
    fire = _pet_id("火花")
    water = _pet_id("水蓝蓝")
    burn_skill = _skill_id("焚烧烙印")
    poison_skill = _skill_id("剧毒")

    burned = update(
        make_state((fire,), (water,), team_a_moves=((burn_skill,),)),
        move_choice(0),
        move_choice(0),
    ).state.side_b.pets[0]
    burn_damage = min(hot.PETS[water][1], 1000) * 5 * 200 * hot.TYPE_CHART_BPS[2][hot.PETS[water][7]] // (BPS * BPS)
    assert burned.current_hp == hot.PETS[water][1] - burn_damage
    assert status_stack(burned, StatusType.BURN) == 3
    assert burned.status_flags & int(StatusFlag.BURN)

    poisoned = update(
        make_state((fire,), (water,), team_a_moves=((poison_skill,),)),
        move_choice(0),
        move_choice(0),
    ).state.side_b.pets[0]
    poison_damage = hot.PETS[water][1] * 3 * 300 // BPS
    assert poisoned.current_hp == hot.PETS[water][1] - poison_damage
    assert status_stack(poisoned, StatusType.POISON) == 3
    assert poisoned.status_flags & int(StatusFlag.POISON)


def test_kernel_status_immunity_and_ability_tick_modifiers():
    fire = _pet_id("火花")
    water = _pet_id("水蓝蓝")
    burn_skill = _skill_id("焚烧烙印")
    state = make_state((water,), (fire,), team_a_moves=((burn_skill,),))
    result = update(state, move_choice(0), move_choice(0))
    assert status_stack(result.state.side_b.pets[0], StatusType.BURN) == 0
    assert result.state.side_b.pets[0].current_hp == hot.PETS[fire][1]

    burned_state = make_state((water,), (fire,), team_a_moves=((0,),), team_b_moves=((0,),))
    burned = with_status(burned_state.side_a.pets[0], StatusType.BURN, 4)
    burner = burned_state.side_b.pets[0]._replace(ability_flags=int(AbilityFlag.BURN_NO_DECAY))
    burned_state = burned_state._replace(
        side_a=replace_pet(burned_state.side_a, 0, burned),
        side_b=replace_pet(burned_state.side_b, 0, burner),
    )
    burned_result = update(burned_state, move_choice(0), move_choice(0))
    assert status_stack(burned_result.state.side_a.pets[0], StatusType.BURN) == 6

    poisoned_state = make_state((water,), (fire,), team_a_moves=((0,),), team_b_moves=((0,),))
    poisoned = with_status(poisoned_state.side_a.pets[0], StatusType.POISON, 2)
    poisoner = poisoned_state.side_b.pets[0]._replace(ability_flags=int(AbilityFlag.EXTRA_POISON_TICK))
    poisoned_state = poisoned_state._replace(
        side_a=replace_pet(poisoned_state.side_a, 0, poisoned),
        side_b=replace_pet(poisoned_state.side_b, 0, poisoner),
    )
    poisoned_result = update(poisoned_state, move_choice(0), move_choice(0))
    assert poisoned_result.state.side_a.pets[0].current_hp == hot.PETS[water][1] - (hot.PETS[water][1] * 2 * 300 // BPS) * 2


def test_kernel_weather_cost_damage_and_lifecycle():
    fire = _pet_id("火花")
    water = _pet_id("水蓝蓝")
    sand = _skill_id("沙涌")
    ground = _skill_id("地刺")
    water_bolt = _skill_id("水弹")

    sand_state = update(
        make_state((fire,), (water,), team_a_moves=((sand,),)),
        move_choice(0),
        move_choice(0),
    ).state
    assert weather_type(sand_state.weather) == WeatherType.SANDSTORM.value
    assert weather_turns(sand_state.weather) == 4
    assert sand_state.side_a.pets[0].current_hp == hot.PETS[fire][1] - hot.PETS[fire][1] // 16
    assert sand_state.side_b.pets[0].current_hp == hot.PETS[water][1] - hot.PETS[water][1] // 16

    cost_state = update(
        make_state((fire,), (water,), team_a_moves=((ground,),), weather=WeatherType.SANDSTORM.value, weather_duration=2),
        move_choice(0),
        move_choice(0),
    ).state
    assert cost_state.side_a.pets[0].current_energy == STARTING_ENERGY - hot.SKILLS[ground][SKILL_ENERGY] // 2

    dry = update(
        make_state((water,), (fire,), team_a_moves=((water_bolt,),), team_b_moves=((0,),)),
        move_choice(0),
        move_choice(0),
    )
    rain = update(
        make_state((water,), (fire,), team_a_moves=((water_bolt,),), team_b_moves=((0,),), weather=WeatherType.RAIN.value, weather_duration=2),
        move_choice(0),
        move_choice(0),
    )
    assert rain.damage_a > dry.damage_a


def test_kernel_snow_and_leech_turn_end_ticks():
    fire = _pet_id("火花")
    water = _pet_id("水蓝蓝")
    leech_skill = _skill_id("孢子")

    snow_state = update(
        make_state((fire,), (water,), weather=WeatherType.SNOW.value, weather_duration=2),
        move_choice(0),
        move_choice(0),
    ).state
    assert weather_type(snow_state.weather) == WeatherType.SNOW.value
    assert weather_turns(snow_state.weather) == 1
    assert snow_state.side_a.pets[0].frostbite == hot.PETS[fire][1] // 12
    assert status_stack(snow_state.side_a.pets[0], StatusType.FREEZE) == 2

    leech_state = make_state((fire,), (water,), team_a_moves=((leech_skill,),))
    damaged_actor = leech_state.side_a.pets[0]._replace(current_hp=hot.PETS[fire][1] - 10)
    leech_state = leech_state._replace(side_a=replace_pet(leech_state.side_a, 0, damaged_actor))
    leech_result = update(leech_state, move_choice(0), move_choice(0)).state
    leech_damage = hot.PETS[water][1] * 800 // BPS
    assert leech_result.side_b.pets[0].current_hp == hot.PETS[water][1] - leech_damage
    assert leech_result.side_a.pets[0].current_hp == min(hot.PETS[fire][1], hot.PETS[fire][1] - 10 + leech_damage)
    assert status_stack(leech_result.side_b.pets[0], StatusType.LEECH) == 1


def test_kernel_mark_primitives_and_same_polarity_replacement():
    fire = _pet_id("火花")
    water = _pet_id("水蓝蓝")
    moisture = _skill_id("打湿")
    wind = _skill_id("风起")

    wet_state = update(
        make_state((fire,), (water,), team_a_moves=((moisture,),), team_b_moves=((0,),)),
        move_choice(0),
        move_choice(0),
    ).state
    assert _unpack_mark(wet_state.side_a.marks, MarkIdx.MOISTURE) == 1

    wind_state = wet_state._replace(side_a=wet_state.side_a._replace(moves=((wind, 0, 0, 0),)))
    wind_state = update(wind_state, move_choice(0), move_choice(0)).state
    assert _unpack_mark(wind_state.side_a.marks, MarkIdx.MOISTURE) == 0
    assert _unpack_mark(wind_state.side_a.marks, MarkIdx.WIND) == 1


def test_kernel_marks_affect_speed_cost_damage_and_entry():
    fire = _pet_id("火花")
    cat = _pet_id("喵喵")
    water = _pet_id("水蓝蓝")
    impact = _skill_id("冲击")
    ground = _skill_id("地刺")
    slow_marks = _set_mark(0, MarkIdx.SLOW, 5)
    moisture_marks = _set_mark(0, MarkIdx.MOISTURE, 1)
    meteor_marks = _set_mark(0, MarkIdx.METEOR, 2)
    thorn_spirit = _set_mark(_set_mark(0, MarkIdx.THORN, 1), MarkIdx.SPIRIT, 1)

    slow_state = make_state((fire,), (fire,), team_a_moves=((impact,),), team_b_moves=((impact,),), rng_seed=1)
    slow_state = slow_state._replace(side_a=slow_state.side_a._replace(marks=slow_marks))
    assert update(slow_state, move_choice(0), move_choice(0)).first_side == SIDE_B

    cost_state = make_state((fire,), (water,), team_a_moves=((ground,),), team_b_moves=((0,),))
    cost_state = cost_state._replace(side_a=cost_state.side_a._replace(marks=moisture_marks))
    cost_result = update(cost_state, move_choice(0), move_choice(0)).state
    assert cost_result.side_a.pets[0].current_energy == STARTING_ENERGY - (hot.SKILLS[ground][SKILL_ENERGY] - 1)

    base = update(
        make_state((fire,), (water,), team_a_moves=((impact,),), team_b_moves=((0,),)),
        move_choice(0),
        move_choice(0),
    )
    meteor_state = make_state((fire,), (water,), team_a_moves=((impact,),), team_b_moves=((0,),))
    meteor_state = meteor_state._replace(side_b=meteor_state.side_b._replace(marks=meteor_marks))
    meteor = update(meteor_state, move_choice(0), move_choice(0))
    assert meteor.damage_a == base.damage_a + 60

    switch_state = make_state((fire, cat), (water,), team_a_moves=((impact,), (impact,)), team_b_moves=((0,),))
    switch_state = switch_state._replace(side_a=switch_state.side_a._replace(marks=thorn_spirit))
    switched = update(switch_state, switch_choice(1), move_choice(0)).state.side_a.pets[1]
    assert switched.current_hp == hot.PETS[cat][1] - hot.PETS[cat][1] * 600 // BPS
    assert switched.current_energy == STARTING_ENERGY - 1


def test_kernel_mark_turn_end_poison_and_solar_ticks():
    fire = _pet_id("火花")
    water = _pet_id("水蓝蓝")
    marks = _set_mark(_set_mark(0, MarkIdx.POISON, 2), MarkIdx.SOLAR, 1)
    state = make_state((fire,), (water,), team_a_moves=((0,),), team_b_moves=((0,),))
    pet = state.side_a.pets[0]._replace(current_energy=5)
    state = state._replace(side_a=replace_pet(state.side_a._replace(marks=marks), 0, pet))

    result = update(state, move_choice(0), move_choice(0)).state.side_a.pets[0]

    assert result.current_hp == hot.PETS[fire][1] - hot.PETS[fire][1] * 2 * 300 // BPS
    assert result.current_energy == 8


def test_kernel_barrel_neutralizes_type_and_transfers_on_switch():
    fire = _pet_id("火花")
    cat = _pet_id("喵喵")
    water = _pet_id("水蓝蓝")
    ember = _skill_id("火苗")
    impact = _skill_id("冲击")

    base = update(
        make_state((fire,), (cat,), team_a_moves=((ember,),), team_b_moves=((0,),)),
        move_choice(0),
        move_choice(0),
    )
    barrel_state = make_state((fire,), (cat,), team_a_moves=((ember,),), team_b_moves=((0,),))
    barrel_actor = barrel_state.side_a.pets[0]._replace(ability_flags=int(AbilityFlag.BARREL_ACTIVE))
    barrel_state = barrel_state._replace(side_a=replace_pet(barrel_state.side_a, 0, barrel_actor))
    barrel = update(barrel_state, move_choice(0), move_choice(0))

    assert barrel.damage_a < base.damage_a
    assert not (barrel.state.side_a.pets[0].ability_flags & int(AbilityFlag.BARREL_ACTIVE))

    switch_state = make_state((fire, water), (cat,), team_a_moves=((impact,), (impact,)), team_b_moves=((0,),))
    leaving = switch_state.side_a.pets[0]._replace(ability_flags=int(AbilityFlag.BARREL_ACTIVE))
    switch_state = switch_state._replace(side_a=replace_pet(switch_state.side_a, 0, leaving))
    switched = update(switch_state, switch_choice(1), move_choice(0)).state

    assert switched.side_a.active == 1
    assert switched.side_a.barrel_pending == 0
    assert switched.side_a.pets[1].ability_flags & int(AbilityFlag.BARREL_ACTIVE)


def test_kernel_devotion_reduces_cost_and_boosts_devotion_skills():
    fire = _pet_id("火花")
    water = _pet_id("水蓝蓝")
    swarm = _skill_id("虫群过境")
    devotion = (
        (1 << (DevotionIdx.JIAMEI.value * 4))
        | (1 << (DevotionIdx.FEIDUAN.value * 4))
        | (1 << (DevotionIdx.CHONGQUN.value * 4))
    )

    base = update(
        make_state((fire,), (water,), team_a_moves=((swarm,),), team_b_moves=((0,),)),
        move_choice(0),
        move_choice(0),
    )
    boosted_state = make_state((fire,), (water,), team_a_moves=((swarm,),), team_b_moves=((0,),))
    boosted_state = boosted_state._replace(side_a=boosted_state.side_a._replace(devotion=devotion))
    boosted = update(boosted_state, move_choice(0), move_choice(0))

    assert boosted.damage_a > base.damage_a
    assert boosted.state.side_a.pets[0].current_energy == STARTING_ENERGY - (hot.SKILLS[swarm][SKILL_ENERGY] - 1)


def test_kernel_faint_reduces_magic_auto_switches_and_skips_replacement_action():
    fire = _pet_id("火花")
    water = _pet_id("水蓝蓝")
    cat = _pet_id("喵喵")
    impact = _skill_id("冲击")
    state = make_state((fire,), (water, cat), team_a_moves=((impact,),), team_b_moves=((impact,), (impact,)))
    weak = state.side_b.pets[0]._replace(current_hp=1)
    state = state._replace(side_b=replace_pet(state.side_b, 0, weak))

    result = update(state, move_choice(0), move_choice(0))

    assert result.state.side_b.pets[0].fainted == 1
    assert result.state.side_b.active == 1
    assert result.state.side_b.magic == 3
    assert result.damage_b == 0

    fake_state = make_state((fire,), (water, cat), team_a_moves=((impact,),), team_b_moves=((0,), (0,)))
    fake = fake_state.side_b.pets[0]._replace(current_hp=1, ability_flags=int(AbilityFlag.FAKE_DEATH))
    fake_state = fake_state._replace(side_b=replace_pet(fake_state.side_b, 0, fake))
    fake_result = update(fake_state, move_choice(0), move_choice(0))
    assert fake_result.state.side_b.magic == 4


def test_kernel_cute_boosts_damage_shields_and_transfers_on_faint():
    fire = _pet_id("火花")
    water = _pet_id("水蓝蓝")
    impact = _skill_id("冲击")

    base = update(
        make_state((fire,), (water,), team_a_moves=((impact,),), team_b_moves=((0,),)),
        move_choice(0),
        move_choice(0),
    )
    cute_state = make_state((fire,), (water,), team_a_moves=((impact,),), team_b_moves=((0,),))
    cute_actor = cute_state.side_a.pets[0]._replace(cute=4)
    cute_state = cute_state._replace(side_a=replace_pet(cute_state.side_a, 0, cute_actor))
    cute_damage = update(cute_state, move_choice(0), move_choice(0))
    assert cute_damage.damage_a > base.damage_a

    shield_state = make_state((fire,), (water,), team_a_moves=((impact,),), team_b_moves=((0,),))
    shield_target = shield_state.side_b.pets[0]._replace(current_hp=1, cute=5)
    shield_state = shield_state._replace(side_b=replace_pet(shield_state.side_b, 0, shield_target))
    shield = update(shield_state, move_choice(0), move_choice(0)).state.side_b.pets[0]
    assert shield.current_hp == 1
    assert shield.cute == 0
    assert shield.fainted == 0

    transfer_state = make_state((fire,), (water,), team_a_moves=((impact,),), team_b_moves=((0,),))
    killer = transfer_state.side_a.pets[0]._replace(cute=1)
    target = transfer_state.side_b.pets[0]._replace(current_hp=1, cute=2)
    transfer_state = transfer_state._replace(
        side_a=replace_pet(transfer_state.side_a, 0, killer),
        side_b=replace_pet(transfer_state.side_b, 0, target),
    )
    transfer = update(transfer_state, move_choice(0), move_choice(0)).state
    assert transfer.side_a.pets[0].cute == 3
    assert transfer.side_b.pets[0].cute == 0


def test_kernel_hot_path_guard_has_no_dynamic_event_or_param_layer():
    root = Path(__file__).resolve().parents[1]
    forbidden_terms = (
        "EventBus",
        "bus.on",
        "emit(",
        "importlib",
        "__import__",
        "MappingProxyType",
        "json.loads",
        "params.get",
        "record_event",
        "BattleEvent",
    )
    for rel in (
        "roco/engine/kernel.py",
        "roco/engine/kernel_state.py",
        "roco/engine/kernel_effects.py",
        "roco/engine/kernel_catalog.py",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in text
    effect_exec = (root / "roco/engine/kernel_effects.py").read_text(encoding="utf-8")
    assert "OP_TABLE[row[ROW_TAG]]" in effect_exec
    assert "OP_TABLE.get" not in effect_exec


def test_old_event_bus_hot_path_modules_are_retired():
    root = Path(__file__).resolve().parents[1]
    retired = (
        "roco/engine/events.py",
        "roco/engine/skill_exec.py",
        "roco/engine/effect_exec.py",
        "roco/engine/ability.py",
        "roco/systems/weather.py",
        "roco/systems/marks.py",
        "roco/systems/burst.py",
        "roco/systems/barrel.py",
        "roco/systems/devotion.py",
        "roco/systems/cute.py",
        "roco/systems/skill_leech.py",
    )
    for rel in retired:
        assert not (root / rel).exists()

    forbidden_terms = (
        "EventBus",
        "EventCtx",
        "GameEvent",
        "roco.systems",
        "skill_exec",
        "effect_exec",
        "importlib",
    )
    for rel in (
        "roco/engine/battle.py",
        "roco/sim/monte_carlo.py",
        "README.md",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in text
