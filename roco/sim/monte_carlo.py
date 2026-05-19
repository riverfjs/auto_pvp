"""Monte Carlo PVP simulator backed by the fixed kernel catalog."""

from __future__ import annotations

import argparse
import random
import sqlite3
from collections import Counter
from typing import NamedTuple

from roco.common.constants import DEFAULT_MAX_TURNS
from roco.data.utils import DB_DIR
from roco.engine.generated import catalog_debug as debug
from roco.engine.generated import catalog_hot as hot
from roco.engine.facade.battle import BattleEngine
from roco.engine.common.choices import SIDE_A, SIDE_B, Choice, focus_choice, move_choice, switch_choice
from roco.common.constants import TYPE_DOUBLE_RESIST_BPS, TYPE_DOUBLE_WEAK_BPS
from roco.engine.kernel.catalog import (
    PET_PRIMARY,
    PET_SECONDARY,
    SKILL_ELEMENT,
    SKILL_POWER,
)
from roco.engine.kernel.ctx import BPS
from roco.engine.kernel.state import KernelState


class TeamSpec(NamedTuple):
    pet_ids: tuple[int, ...]
    move_rows: tuple[tuple[int, ...], ...]
    bloodlines: tuple[int, ...]
    bloodline_magic_id: int


class Policy:
    def select_move(self, state: KernelState, side_id: int) -> Choice:
        raise NotImplementedError


class RandomPolicy(Policy):
    def select_move(self, state: KernelState, side_id: int) -> Choice:
        valid_moves = _get_valid_moves(state, side_id)
        switches = _get_switches(state, side_id)
        if random.random() < 0.7 and valid_moves:
            return move_choice(random.choice(valid_moves))
        if switches:
            return switch_choice(random.choice(switches))
        return focus_choice()


class GreedyPolicy(Policy):
    def select_move(self, state: KernelState, side_id: int) -> Choice:
        valid = _get_valid_moves(state, side_id)
        if not valid:
            return focus_choice()
        side = _side(state, side_id)
        moves = side.moves[side.active]
        return move_choice(max(valid, key=lambda idx: hot.SKILLS[moves[idx]][SKILL_POWER]))


class TypeAdvantagePolicy(Policy):
    def select_move(self, state: KernelState, side_id: int) -> Choice:
        valid = _get_valid_moves(state, side_id)
        if not valid:
            return focus_choice()
        side = _side(state, side_id)
        target = _active_pet(state, SIDE_B if side_id == SIDE_A else SIDE_A)
        target_row = hot.PETS[target.pet_id]
        moves = side.moves[side.active]
        return move_choice(
            max(
                valid,
                key=lambda idx: _type_bps(
                    hot.SKILLS[moves[idx]][SKILL_ELEMENT],
                    target_row[PET_PRIMARY],
                    target_row[PET_SECONDARY],
                ),
            )
        )


class FixedPolicy(Policy):
    def __init__(self):
        self._counter: dict[int, int] = {}

    def select_move(self, state: KernelState, side_id: int) -> Choice:
        valid = _get_valid_moves(state, side_id)
        if not valid:
            return focus_choice()
        idx = self._counter.get(side_id, 0)
        self._counter[side_id] = idx + 1
        return move_choice(valid[idx % len(valid)])


POLICIES: dict[str, type[Policy]] = {
    "random": RandomPolicy,
    "greedy": GreedyPolicy,
    "type": TypeAdvantagePolicy,
    "fixed": FixedPolicy,
}


def load_team_from_db(team_id: str, conn: sqlite3.Connection) -> TeamSpec | None:
    team_row = conn.execute("SELECT bloodline_magic_id FROM teams WHERE id = ?", (team_id,)).fetchone()
    slots = conn.execute(
        "SELECT id, slot, pet_id, pet_name, bloodline_id FROM team_pets WHERE team_id = ? ORDER BY slot",
        (team_id,),
    ).fetchall()
    pet_ids: list[int] = []
    move_rows: list[tuple[int, ...]] = []
    bloodlines: list[int] = []
    for slot in slots:
        pet_id = slot["pet_id"] or debug.PET_IDS_BY_NAME.get(slot["pet_name"], 0)
        if not pet_id or pet_id >= len(hot.PETS):
            continue
        skill_rows = conn.execute(
            "SELECT skill_id, skill_name FROM team_pet_skills WHERE team_pet_id = ? ORDER BY slot",
            (slot["id"],),
        ).fetchall()
        moves = tuple(
            sid
            for sid in (
                row["skill_id"] or debug.SKILL_IDS_BY_NAME.get(row["skill_name"], 0)
                for row in skill_rows
            )
            if sid and sid < len(hot.SKILLS)
        )
        pet_ids.append(pet_id)
        move_rows.append(tuple((moves or hot.PET_SKILLS[pet_id])[:4]))
        bloodlines.append(slot["bloodline_id"] if slot["bloodline_id"] is not None else hot.PETS[pet_id][PET_PRIMARY])
    if not pet_ids:
        return None
    magic_id = int(team_row["bloodline_magic_id"] or 1) if team_row else 1
    return TeamSpec(tuple(pet_ids), tuple(move_rows), tuple(bloodlines), magic_id)


def load_all_pvp_teams(conn: sqlite3.Connection) -> dict[str, tuple[str, TeamSpec]]:
    rows = conn.execute(
        "SELECT id, title FROM teams WHERE team_type = 'pvp' ORDER BY upload_date DESC"
    ).fetchall()
    result: dict[str, tuple[str, TeamSpec]] = {}
    for row in rows:
        team = load_team_from_db(row["id"], conn)
        if team:
            result[row["id"]] = (row["title"], team)
    return result


def run_single_battle(
    team_a: TeamSpec,
    team_b: TeamSpec,
    policy_a: Policy,
    policy_b: Policy,
    max_turns: int = DEFAULT_MAX_TURNS,
) -> dict:
    engine = BattleEngine.from_team_ids(
        team_a.pet_ids,
        team_b.pet_ids,
        team_a_moves=team_a.move_rows,
        team_b_moves=team_b.move_rows,
        team_a_bloodlines=team_a.bloodlines,
        team_b_bloodlines=team_b.bloodlines,
        team_a_bloodline_magic_id=team_a.bloodline_magic_id,
        team_b_bloodline_magic_id=team_b.bloodline_magic_id,
        rng_seed=random.getrandbits(32),
        max_turns=max_turns,
    )
    while not engine.is_finished():
        engine.step(policy_a.select_move(engine.state, SIDE_A), policy_b.select_move(engine.state, SIDE_B))
    return {"winner": engine.get_winner(), "turns": engine.state.turn}


def run_monte_carlo(
    team_a: TeamSpec,
    team_b: TeamSpec,
    policy_a: Policy,
    policy_b: Policy,
    n: int = 100,
    max_turns: int = DEFAULT_MAX_TURNS,
) -> dict:
    wins: Counter = Counter()
    turns_list: list[int] = []
    for _ in range(n):
        result = run_single_battle(team_a, team_b, policy_a, policy_b, max_turns)
        wins[result["winner"]] += 1
        turns_list.append(result["turns"])
    return {
        "wins_a": wins.get("a", 0),
        "wins_b": wins.get("b", 0),
        "draws": wins.get("draw", 0),
        "win_rate_a": wins.get("a", 0) / n,
        "avg_turns": sum(turns_list) / len(turns_list),
        "n": n,
    }


def run_matchup_matrix(
    teams: dict[str, tuple[str, TeamSpec]],
    n: int = 50,
    policy_name: str = "random",
) -> dict:
    team_ids = list(teams.keys())
    policy_cls = POLICIES[policy_name]
    results: dict = {"teams": [], "matrix": {}}
    for tid in team_ids:
        results["teams"].append({"id": tid, "title": teams[tid][0]})

    total = len(team_ids) * len(team_ids)
    done = 0
    for tid_a in team_ids:
        title_a, team_a = teams[tid_a]
        for tid_b in team_ids:
            done += 1
            if tid_a == tid_b:
                continue
            key = f"{tid_a[:8]} vs {tid_b[:8]}"
            mc = run_monte_carlo(team_a, teams[tid_b][1], policy_cls(), policy_cls(), n=n)
            results["matrix"][key] = {
                "team_a": title_a,
                "team_b": teams[tid_b][0],
                "win_rate_a": round(mc["win_rate_a"], 3),
                "draws": mc["draws"],
                "avg_turns": round(mc["avg_turns"], 1),
            }
            print(f"[{done}/{total}] {key}: {mc['win_rate_a']:.1%}", flush=True)
    return results


def _side(state: KernelState, side_id: int):
    return state.side_a if side_id == SIDE_A else state.side_b


def _active_pet(state: KernelState, side_id: int):
    side = _side(state, side_id)
    return side.pets[side.active]


def _get_valid_moves(state: KernelState, side_id: int) -> tuple[int, ...]:
    side = _side(state, side_id)
    moves = side.moves[side.active]
    return tuple(idx for idx, skill_id in enumerate(moves) if skill_id > 0)


def _get_switches(state: KernelState, side_id: int) -> tuple[int, ...]:
    side = _side(state, side_id)
    return tuple(
        idx
        for idx, pet in enumerate(side.pets)
        if idx != side.active and pet.fainted == 0
    )


def _type_bps(move_element: int, primary: int, secondary: int) -> int:
    first = hot.TYPE_CHART_BPS[move_element][primary]
    if secondary < 0:
        return first
    second = hot.TYPE_CHART_BPS[move_element][secondary]
    if first > BPS and second > BPS:
        return TYPE_DOUBLE_WEAK_BPS
    if first < BPS and second < BPS:
        return TYPE_DOUBLE_RESIST_BPS
    if (first > BPS and second < BPS) or (first < BPS and second > BPS):
        return BPS
    return first if first != BPS else second


def main() -> None:
    parser = argparse.ArgumentParser(description="Monte Carlo PVP battle simulator")
    parser.add_argument("--n", type=int, default=10, help="Battles per matchup")
    parser.add_argument("--teams", type=int, default=0, help="Limit to first N teams")
    parser.add_argument("--policy", choices=list(POLICIES), default="random")
    parser.add_argument("--db", default=str(DB_DIR / "data.db"))
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    teams = load_all_pvp_teams(conn)
    if args.teams > 0:
        teams = {key: teams[key] for key in list(teams)[:args.teams]}

    print(f"Loaded {len(teams)} PVP teams")
    print(f"Running {args.n} battles per matchup (policy={args.policy})...")
    results = run_matchup_matrix(teams, n=args.n, policy_name=args.policy)

    print("\n=== Win Rate Matrix ===")
    header = f"{'Team A':<16} {'Team B':<16} {'WR(A)':>8}"
    print(header)
    print("-" * len(header))
    for _key, val in sorted(results["matrix"].items(), key=lambda x: -x[1]["win_rate_a"]):
        if val["win_rate_a"] >= 0.50:
            print(f"{val['team_a']:<16} {val['team_b']:<16} {val['win_rate_a']:>7.1%}")
    conn.close()


if __name__ == "__main__":
    main()
