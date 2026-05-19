from roco.config.constants import STARTING_ENERGY
from roco.engine.generated import catalog_debug as debug
from roco.engine.generated import catalog_hot as hot
from roco.engine.facade.battle import BattleEngine
from roco.engine.common.choices import SIDE_A, SIDE_B, move_choice, switch_choice
from roco.engine.kernel.catalog import SKILL_ENERGY


def _pet_id(name: str) -> int:
    return debug.PET_IDS_BY_NAME[name]


def _skill_id(name: str) -> int:
    return debug.SKILL_IDS_BY_NAME[name]


def test_battle_engine_facade_runs_kernel_state_only():
    fire = _pet_id("火花")
    water = _pet_id("水蓝蓝")
    slap = _skill_id("拍击")
    engine = BattleEngine.from_team_ids(
        (fire,),
        (water,),
        team_a_moves=((slap,),),
        team_b_moves=((slap,),),
    )

    state = engine.step(move_choice(0), move_choice(0))

    assert state.turn == 1
    assert state.side_a.pets[0].current_energy == STARTING_ENERGY - hot.SKILLS[slap][SKILL_ENERGY]
    assert state.side_b.pets[0].current_hp < hot.PETS[water][1]
    assert not hasattr(engine, "bus")


def test_battle_engine_name_facade_resolves_only_at_boundary():
    engine = BattleEngine.from_names(
        ("火花", "喵喵"),
        ("水蓝蓝",),
        team_a_moves=(("拍击",), ("拍击",)),
        team_b_moves=(("抓挠",),),
    )

    assert engine.get_valid_moves(SIDE_A) == (0,)
    assert engine.get_available_switches(SIDE_A) == (1,)
    assert engine.active_pet(SIDE_A).pet_id == _pet_id("火花")

    engine.step(switch_choice(1), move_choice(0))

    assert engine.get_active_slot(SIDE_A) == 1
    assert engine.active_pet(SIDE_A).pet_id == _pet_id("喵喵")


def test_battle_engine_winner_and_turn_limit_draw():
    fire = _pet_id("火花")
    water = _pet_id("水蓝蓝")
    engine = BattleEngine.from_team_ids(
        (fire,),
        (water,),
        team_a_moves=((0,),),
        team_b_moves=((0,),),
        max_turns=1,
    )

    engine.step(move_choice(0), move_choice(0))

    assert engine.is_finished()
    assert engine.get_winner() == "draw"


def test_battle_engine_uses_kernel_side_ids_for_queries():
    fire = _pet_id("火花")
    water = _pet_id("水蓝蓝")
    impact = _skill_id("猛烈撞击")
    engine = BattleEngine.from_team_ids(
        (fire,),
        (water,),
        team_a_moves=((impact,),),
        team_b_moves=((impact,),),
    )

    assert engine.active_pet(SIDE_A).pet_id == fire
    assert engine.active_pet(SIDE_B).pet_id == water
    assert engine.get_valid_moves(SIDE_A) == (0,)
    assert engine.get_valid_moves(SIDE_B) == (0,)
