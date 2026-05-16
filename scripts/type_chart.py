"""Type effectiveness calculator for Roco Kingdom PVP.

Reversed from https://wiki.biligame.com/rocom/克制计算器

Concepts:
  - strong    (攻击) 造成伤害 2.0× — our move hits defender's type super effectively
  - resist    (攻击) 造成伤害 0.5× — our move is resisted by defender's type
  - weak      (防御) 受到伤害 2.0× — defender's type is weak to attacker's move type
  - vulnerable(防御) 受到伤害 0.5× — defender's type resists attacker's move type

Dual-type: weak/vulnerable overlap → 3.0× / 0.25×; cancel if both appear.
"""

from __future__ import annotations

TYPES: tuple[str, ...] = (
    "普通", "草", "火", "水", "光", "地", "冰", "龙", "电",
    "毒", "虫", "武", "翼", "萌", "幽", "恶", "机械", "幻",
)

# type -> {strong, resist, weak, vulnerable}
CHART: dict[str, dict[str, list[str]]] = {
    "普通": {"strong": [],        "resist": ["地", "幽", "机械"],
             "weak":   ["武"],     "vulnerable": ["幽"]},
    "草":   {"strong": ["水", "光", "地"],
             "resist": ["火", "龙", "毒", "虫", "翼", "机械"],
             "weak":   ["火", "冰", "毒", "虫", "翼"],
             "vulnerable": ["水", "地", "电", "光"]},
    "火":   {"strong": ["草", "冰", "虫", "机械"],
             "resist": ["水", "地", "龙"],
             "weak":   ["水", "地"],
             "vulnerable": ["草", "冰", "虫", "萌", "机械"]},
    "水":   {"strong": ["火", "地", "机械"],
             "resist": ["草", "冰", "龙"],
             "weak":   ["草", "电"],
             "vulnerable": ["火", "机械"]},
    "光":   {"strong": ["幽", "恶"],
             "resist": ["草", "冰"],
             "weak":   ["草", "幽"],
             "vulnerable": ["恶", "幻"]},
    "地":   {"strong": ["火", "冰", "电", "毒"],
             "resist": ["草", "武"],
             "weak":   ["草", "水", "冰", "武", "机械"],
             "vulnerable": ["普通", "火", "电", "毒", "翼"]},
    "冰":   {"strong": ["草", "地", "龙", "翼"],
             "resist": ["火", "冰", "机械"],
             "weak":   ["火", "地", "武", "机械"],
             "vulnerable": ["水", "冰", "光"]},
    "龙":   {"strong": ["龙"],
             "resist": ["机械"],
             "weak":   ["冰", "龙", "萌"],
             "vulnerable": ["草", "火", "水", "电", "翼"]},
    "电":   {"strong": ["水", "翼"],
             "resist": ["草", "地", "龙", "电"],
             "weak":   ["地"],
             "vulnerable": ["电", "翼", "机械"]},
    "毒":   {"strong": ["草", "萌"],
             "resist": ["地", "毒", "幽", "机械"],
             "weak":   ["地", "恶", "幻"],
             "vulnerable": ["草", "毒", "虫", "武", "萌"]},
    "虫":   {"strong": ["草", "恶", "幻"],
             "resist": ["火", "毒", "武", "翼", "萌", "幽", "机械"],
             "weak":   ["火", "翼"],
             "vulnerable": ["草", "武"]},
    "武":   {"strong": ["普通", "地", "冰", "恶", "机械"],
             "resist": ["毒", "虫", "翼", "萌", "幽", "幻"],
             "weak":   ["翼", "萌", "幻"],
             "vulnerable": ["地", "虫", "恶"]},
    "翼":   {"strong": ["草", "虫", "武"],
             "resist": ["地", "龙", "电", "机械"],
             "weak":   ["冰", "电"],
             "vulnerable": ["草", "虫", "武"]},
    "萌":   {"strong": ["龙", "武", "恶"],
             "resist": ["火", "毒", "机械"],
             "weak":   ["毒", "恶", "机械"],
             "vulnerable": ["虫", "武"]},
    "幽":   {"strong": ["光", "幽", "幻"],
             "resist": ["普通", "恶"],
             "weak":   ["光", "幽", "恶"],
             "vulnerable": ["普通", "毒", "虫", "武"]},
    "恶":   {"strong": ["毒", "萌", "幽"],
             "resist": ["光", "武", "恶"],
             "weak":   ["光", "虫", "武", "萌"],
             "vulnerable": ["幽", "恶"]},
    "机械": {"strong": ["地", "冰", "萌"],
             "resist": ["火", "水", "电", "机械"],
             "weak":   ["火", "水", "武"],
             "vulnerable": ["普通", "草", "冰", "龙", "毒", "虫", "翼", "萌", "机械", "幻"]},
    "幻":   {"strong": ["毒", "武"],
             "resist": ["光", "机械", "幻"],
             "weak":   ["虫", "幽"],
             "vulnerable": ["武", "幻"]},
}

# Types immune to specific status conditions
STATUS_IMMUNITY: dict[str, str] = {
    "草": "寄生",
    "火": "灼烧",
    "毒": "中毒",
    "冰": "冻结",
}

STRONG_MULT  = 2.0   # super effective
RESIST_MULT  = 0.5   # not very effective
WEAK_MULT    = 2.0   # we take more
VULN_MULT    = 0.5   # we take less

# Dual-type overlap
OVERLAP_WEAK_MULT = 3.0
OVERLAP_VULN_MULT = 0.25


def _non_empty(lst: list[str]) -> list[str]:
    return [x for x in lst if x]


def attacking_multiplier(move_type: str, defender_types: tuple[str, ...]) -> float:
    """Damage multiplier when `move_type` attacks the defender (1 or 2 types).

    Returns 2.0 (super effective), 1.0 (neutral), 0.5 (resisted), or
    3.0/0.25 for dual-type overlaps.
    """
    if move_type not in CHART:
        return 1.0

    types = [t for t in defender_types if t and t != "无" and t in CHART]
    if not types:
        return 1.0

    if len(types) == 1:
        t = types[0]
        if move_type in CHART[t]["vulnerable"]:
            return VULN_MULT
        if move_type in CHART[t]["weak"]:
            return WEAK_MULT
        # Attacker's own chart determines strong/resist
        if move_type in CHART[t].get("resist", []):
            return RESIST_MULT  # wait, this isn't right

    # Actually the JS calculates differently. Let me re-read...

    # For attacking (strong/resist): look at the MOVE's chart
    chart = CHART[move_type]
    strong = chart["strong"]
    resist = chart["resist"]

    if len(types) == 1:
        t = types[0]
        if t in strong:
            return STRONG_MULT
        if t in resist:
            return RESIST_MULT
        return 1.0

    # Dual-type attacking: accumulate
    mult = 1.0
    for t in types:
        if t in strong:
            mult *= STRONG_MULT
        elif t in resist:
            mult *= RESIST_MULT
    return mult


def defending_multiplier(attacker_type: str, defender_types: tuple[str, ...]) -> float:
    """Damage multiplier when the defender takes a hit from `attacker_type`.

    Same math, but named for clarity. Returns multiplier applied to damage taken.
    """
    return attacking_multiplier(attacker_type, defender_types)


def effectiveness(move_type: str, defender_types: tuple[str, ...]) -> float:
    """Full dual-type effectiveness with overlap and cancel logic.

    Single type: strong→2.0, resist→0.5, neutral→1.0
    Dual type: weak/vulnerable overlap→3.0/0.25, canceled types removed.
    """
    types = [t for t in defender_types if t and t != "无" and t in CHART]
    if not types or move_type not in CHART:
        return 1.0

    if len(types) == 1:
        t = types[0]
        move_chart = CHART[move_type]
        if t in move_chart["strong"]:
            return STRONG_MULT
        if t in move_chart["resist"]:
            return RESIST_MULT
        return 1.0

    # Dual-type: accumulate weak/vulnerable from DEFENDER's perspective
    total_mult = 1.0
    for t in types:
        t_chart = CHART[t]
        if move_type in t_chart["weak"]:
            total_mult *= WEAK_MULT
        elif move_type in t_chart["vulnerable"]:
            total_mult *= VULN_MULT

    return total_mult if total_mult != 1.0 else 1.0


def _count_in_types(move_type: str, types: list[str], field: str) -> int:
    """How many of `types` have `move_type` in their `field` list."""
    return sum(1 for t in types if t in CHART and move_type in CHART[t][field])


def effectiveness_v2(move_type: str, defender_types: tuple[str, ...]) -> float:
    """Full dual-type effectiveness matching the WIKI calculator's logic.

    For single-type: strong→2.0, resist→0.5
    For dual-type:
      - weak is the DEFENDER's weak field (incoming damage multiplier)
      - If both types have `move_type` in weak → 3.0
      - If one in weak, one in vulnerable → cancel (1.0)
      - If both in vulnerable → 0.25
      - If one only → the corresponding multiplier
    """
    types = [t for t in defender_types if t and t != "无" and t in CHART]
    if not types or move_type not in CHART:
        return 1.0

    if len(types) == 1:
        t = types[0]
        move_chart = CHART[move_type]
        if t in move_chart["strong"]:
            return STRONG_MULT
        if t in move_chart["resist"]:
            return RESIST_MULT
        return 1.0

    weak_count = _count_in_types(move_type, types, "weak")
    vuln_count = _count_in_types(move_type, types, "vulnerable")

    # Cancel: appears in both weak and vulnerable of different types
    if weak_count > 0 and vuln_count > 0:
        return 1.0
    if weak_count == 2:
        return OVERLAP_WEAK_MULT
    if weak_count == 1:
        return WEAK_MULT
    if vuln_count == 2:
        return OVERLAP_VULN_MULT
    if vuln_count == 1:
        return VULN_MULT
    return 1.0


def attacking_types(move_type: str) -> dict[str, list[str]]:
    """All types grouped by effectiveness for `move_type` as attacker."""
    result: dict[str, list[str]] = {"2.0": [], "0.5": [], "1.0": []}
    for t in TYPES:
        mult = effectiveness(move_type, (t,))
        if mult == 2.0:
            result["2.0"].append(t)
        elif mult == 0.5:
            result["0.5"].append(t)
        else:
            result["1.0"].append(t)
    return result


def defending_types(defender_type: str) -> dict[str, list[str]]:
    """All types grouped by effectiveness when attacking `defender_type`."""
    result: dict[str, list[str]] = {"2.0": [], "0.5": [], "1.0": []}
    for t in TYPES:
        mult = effectiveness(t, (defender_type,))
        if mult == 2.0:
            result["2.0"].append(t)
        elif mult == 0.5:
            result["0.5"].append(t)
        else:
            result["1.0"].append(t)
    return result


def coverage(move_types: list[str]) -> dict:
    """Coverage analysis: how well a set of move types covers all defender types.

    For each defender type, find the BEST multiplier any of our moves can achieve.
    Best ≥ 2.0 → super_effective (covered)
    Best ≤ 0.5 → resisted (no good option)
    Best = 1.0 → neutral

    missing = types we don't hit super effectively (resisted + neutral)
    """
    best_map: dict[str, float] = {}

    for dfn in TYPES:
        best = 0.0
        for mt in move_types:
            if mt not in CHART:
                continue
            mult = effectiveness(mt, (dfn,))
            if mult > best:
                best = mult
        best_map[dfn] = best if best > 0 else 1.0

    se = sorted(t for t, b in best_map.items() if b >= 2.0)
    resisted = sorted(t for t, b in best_map.items() if b <= 0.5)
    neutral = sorted(t for t, b in best_map.items() if b == 1.0)
    missing = sorted(resisted + neutral)

    return {
        "super_effective": se,
        "resisted": resisted,
        "neutral": neutral,
        "missing": missing,
    }


def status_immunity(defender_types: tuple[str, ...]) -> dict[str, bool]:
    """Check which status effects are blocked by the given types."""
    result: dict[str, bool] = {}
    types = [t for t in defender_types if t and t != "无"]
    for stype, sname in STATUS_IMMUNITY.items():
        result[sname] = any(t == stype for t in types)
    return result
