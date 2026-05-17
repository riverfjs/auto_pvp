from types import MappingProxyType
from pathlib import Path

import pytest

from roco.engine.battle import BattleEngine
from roco.engine.effect_compile import compile_skill_effects
from roco.engine.effect_model import AbilityEffect, EffectSpec, EffectTag, Timing
from roco.engine.events import EventCtx, GameEvent
from roco.engine.skill_tags import classify
from roco.engine.state import MoveDecision, PersistentPet, SkillCategory, SkillData, Stats, StatusFlag, StatusType, WeatherType


def _stats(hp=200, atk=100, atk_m=100, df=80, df_m=80, spd=60):
    return {
        Stats.HP: hp,
        Stats.ATK_PHYS: atk,
        Stats.ATK_MAG: atk_m,
        Stats.DEF_PHYS: df,
        Stats.DEF_MAG: df_m,
        Stats.SPEED: spd,
    }


def _skill(name="打击", element="普通", category=SkillCategory.PHYSICAL, energy=1, power=50, effect="造成物伤"):
    skill = SkillData(name=name, element=element, category=category, energy=energy, power=power, effect=effect)
    classify(skill)
    skill.effects = compile_skill_effects(0, skill)
    return skill


def _pet(name, *, spd=60, element="普通", moves=None):
    return PersistentPet(name=name, stats=_stats(spd=spd), types=(element, ""), moves=tuple(moves or (_skill(),)))


def _ability(tag: EffectTag, params=None, timing=Timing.PASSIVE):
    return (AbilityEffect(0, EffectSpec(tag, timing, MappingProxyType(params or {}))),)


def _attack_damage(engine: BattleEngine) -> int:
    return next(event.detail["damage"] for event in engine.state.log if event.action == "attack")


def test_skill_without_effect_rows_is_data_error():
    raw = SkillData("旧技能", "普通", SkillCategory.PHYSICAL, 1, 50, "造成物伤")
    engine = BattleEngine([_pet("A", spd=100, moves=(raw,))], [_pet("B", spd=50)])

    with pytest.raises(ValueError, match="no compiled effect rows"):
        engine.step(MoveDecision("move", 0), MoveDecision("move", 0))


def test_damage_pipeline_stages_fire_and_can_modify_damage():
    control = BattleEngine([_pet("A", spd=100)], [_pet("B", spd=50)])
    control.step(MoveDecision("move", 0), MoveDecision("move", 0))
    base_damage = _attack_damage(control)

    engine = BattleEngine([_pet("A", spd=100)], [_pet("B", spd=50)])
    stages: list[str] = []

    engine.bus.on(GameEvent.CHECK_HIT, lambda ctx: stages.append("CHECK_HIT"), priority=1)
    engine.bus.on(GameEvent.CALC_DAMAGE, lambda ctx: (stages.append("CALC_DAMAGE"), setattr(ctx, "power_mod", 2.0)), priority=1)
    engine.bus.on(GameEvent.ADJUST_DAMAGE, lambda ctx: (stages.append("ADJUST_DAMAGE"), setattr(ctx, "damage_mult", 0.5)), priority=1)
    engine.bus.on(GameEvent.APPLY_DAMAGE, lambda ctx: (stages.append("APPLY_DAMAGE"), setattr(ctx, "damage", ctx.damage + 7)), priority=1)

    engine.step(MoveDecision("move", 0), MoveDecision("move", 0))

    assert stages[:4] == ["CHECK_HIT", "CALC_DAMAGE", "ADJUST_DAMAGE", "APPLY_DAMAGE"]
    assert _attack_damage(engine) == base_damage + 7


def test_same_speed_tie_break_is_seeded_random():
    a = [_pet("A", spd=80)]
    b = [_pet("B", spd=80)]

    first_a = BattleEngine(a, b, rng_seed=0)
    first_a.step(MoveDecision("move", 0), MoveDecision("move", 0))

    first_b = BattleEngine([_pet("A", spd=80)], [_pet("B", spd=80)], rng_seed=1)
    first_b.step(MoveDecision("move", 0), MoveDecision("move", 0))

    assert first_a.state.last_action_order == ("a", "b")
    assert first_b.state.last_action_order == ("b", "a")


def test_sandstorm_halves_ground_skill_cost():
    ground = _skill("地刺", "地", SkillCategory.PHYSICAL, energy=5, power=40)
    engine = BattleEngine([_pet("A", spd=100, element="地", moves=(ground,))], [_pet("B", spd=50)])
    engine.state.weather_type = WeatherType.SANDSTORM
    engine.state.weather_turns = 2

    engine.step(MoveDecision("move", 0), MoveDecision("move", 0))

    assert engine.state.team_a[0].current_energy == 8


def test_burn_no_decay_flag_grows_burn_like_nrc_ai():
    engine = BattleEngine(
        [_pet("burned", spd=100)],
        [PersistentPet("coal", _stats(spd=50), ("火", ""), (_skill(),), ability_effects=_ability(EffectTag.BURN_NO_DECAY))],
    )
    burned = engine.state.team_a[0]
    burned.status_flags |= StatusFlag.BURN
    burned.set_status_count(StatusType.BURN, 4)

    engine.bus.emit(EventCtx(GameEvent.TURN_END, engine.state))

    assert burned.get_status_count(StatusType.BURN) == 6


def test_extra_poison_tick_flag_doubles_poison_damage():
    engine = BattleEngine(
        [_pet("poisoned", spd=100)],
        [PersistentPet("mix", _stats(spd=50), ("毒", ""), (_skill(),), ability_effects=_ability(EffectTag.EXTRA_POISON_TICK))],
    )
    poisoned = engine.state.team_a[0]
    poisoned.status_flags |= StatusFlag.POISON
    poisoned.set_status_count(StatusType.POISON, 2)

    engine.bus.emit(EventCtx(GameEvent.TURN_END, engine.state))

    assert poisoned.current_hp == poisoned.max_hp - 24


def test_engine_hot_path_has_no_dynamic_registry_or_cooldown_dict_unpack():
    root = Path(__file__).resolve().parents[1]
    for rel in (
        "roco/engine/battle.py",
        "roco/engine/skill_exec.py",
        "roco/engine/effect_exec.py",
        "roco/engine/events.py",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        assert "_unpack_cooldown" not in text
        assert "EventCtx.data" not in text
        assert "HANDLERS.get" not in text
        assert "_handlers: dict" not in text
        assert "default_factory" not in text
