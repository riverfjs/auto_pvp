"""Create or reset the normalized SQLite data store.

The database is a warehouse for pak-derived canonical data. Battle runtime
loads a compiled catalog from these integer ids and packed flags instead of
querying string-heavy JSON/dict data in the hot path.
"""

from __future__ import annotations

import argparse
import sqlite3

from pathlib import Path

from roco.data.utils import DB_DIR
from roco.compiler.effect_model import PakOp, Timing
from roco.common.enums import ELEMENT_NAMES


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS elements (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS abilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    flags INTEGER NOT NULL DEFAULT 0,
    source_version TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS pets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    form_name TEXT DEFAULT '',
    stage TEXT DEFAULT '',
    form_type TEXT DEFAULT '',
    lineage_key TEXT DEFAULT '',
    element_primary_id INTEGER NOT NULL REFERENCES elements(id),
    element_secondary_id INTEGER REFERENCES elements(id),
    ability_id INTEGER REFERENCES abilities(id),
    ability_description TEXT DEFAULT '',
    hp INTEGER NOT NULL,
    atk_phys INTEGER NOT NULL,
    atk_mag INTEGER NOT NULL,
    def_phys INTEGER NOT NULL,
    def_mag INTEGER NOT NULL,
    speed INTEGER NOT NULL,
    height TEXT DEFAULT '',
    weight TEXT DEFAULT '',
    distribution TEXT DEFAULT '',
    description TEXT DEFAULT '',
    is_shiny INTEGER NOT NULL DEFAULT 0,
    evolution_cond TEXT DEFAULT '',
    source_version TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    element_id INTEGER NOT NULL REFERENCES elements(id),
    category_code INTEGER NOT NULL,
    category_name TEXT NOT NULL,
    energy INTEGER NOT NULL,
    power INTEGER NOT NULL,
    effect_text TEXT DEFAULT '',
    flavor_text TEXT DEFAULT '',
    flags INTEGER NOT NULL DEFAULT 0,
    source_version TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS pet_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pet_id INTEGER NOT NULL REFERENCES pets(id) ON DELETE CASCADE,
    skill_id INTEGER REFERENCES skills(id),
    skill_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    unlock_level INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pet_skills_pet ON pet_skills(pet_id);
CREATE INDEX IF NOT EXISTS idx_pet_skills_skill ON pet_skills(skill_id);

CREATE TABLE IF NOT EXISTS pet_transforms (
    source_pet_id INTEGER PRIMARY KEY REFERENCES pets(id) ON DELETE CASCADE,
    leader_pet_id INTEGER NOT NULL REFERENCES pets(id) ON DELETE CASCADE,
    reason TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_pet_transforms_leader ON pet_transforms(leader_pet_id);

CREATE TABLE IF NOT EXISTS skill_effects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    timing_code INTEGER NOT NULL,
    tag_code INTEGER NOT NULL,
    flags INTEGER NOT NULL DEFAULT 0,
    params_json TEXT NOT NULL DEFAULT '{}',
    condition TEXT DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_skill_effects_skill ON skill_effects(skill_id);

CREATE TABLE IF NOT EXISTS ability_effects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ability_id INTEGER NOT NULL REFERENCES abilities(id) ON DELETE CASCADE,
    timing_code INTEGER NOT NULL,
    tag_code INTEGER NOT NULL,
    flags INTEGER NOT NULL DEFAULT 0,
    params_json TEXT NOT NULL DEFAULT '{}',
    condition TEXT DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ability_effects_ability ON ability_effects(ability_id);

CREATE TABLE IF NOT EXISTS effect_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    primitive TEXT NOT NULL,
    timing_code INTEGER,
    params_json TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '',
    used_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_effect_gaps_source ON effect_gaps(source_type, source_name);

CREATE TABLE IF NOT EXISTS statuses (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    packed_index INTEGER NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS marks (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    packed_index INTEGER NOT NULL UNIQUE,
    polarity TEXT NOT NULL,
    stacking TEXT NOT NULL DEFAULT '',
    effect_text TEXT DEFAULT '',
    mechanism_json TEXT NOT NULL DEFAULT '[]',
    effects_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS mark_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mark_id INTEGER NOT NULL REFERENCES marks(id) ON DELETE CASCADE,
    skill_name TEXT NOT NULL,
    description TEXT DEFAULT '',
    UNIQUE(mark_id, skill_name, description)
);
CREATE INDEX IF NOT EXISTS idx_mark_sources_skill ON mark_sources(skill_name);

CREATE TABLE IF NOT EXISTS weathers (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    packed_value INTEGER NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS weather_effects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    weather_id INTEGER NOT NULL REFERENCES weathers(id) ON DELETE CASCADE,
    timing_code INTEGER NOT NULL,
    tag_code INTEGER NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bloodlines (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    element_id INTEGER REFERENCES elements(id)
);

CREATE TABLE IF NOT EXISTS bloodline_magics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    uses_per_battle INTEGER NOT NULL DEFAULT 0,
    description TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS bloodline_magic_effects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    magic_id INTEGER NOT NULL REFERENCES bloodline_magics(id) ON DELETE CASCADE,
    timing_code INTEGER NOT NULL,
    tag_code INTEGER NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT DEFAULT '',
    team_type TEXT NOT NULL,
    bloodline_magic TEXT DEFAULT '',
    bloodline_magic_id INTEGER REFERENCES bloodline_magics(id),
    description TEXT DEFAULT '',
    upload_date TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS team_pets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    slot INTEGER NOT NULL,
    pet_id INTEGER REFERENCES pets(id),
    pet_name TEXT NOT NULL,
    name_short TEXT DEFAULT '',
    bloodline TEXT DEFAULT '',
    bloodline_id INTEGER REFERENCES bloodlines(id),
    nature TEXT DEFAULT '',
    ivs_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE(team_id, slot)
);
CREATE INDEX IF NOT EXISTS idx_team_pets_team ON team_pets(team_id);
CREATE INDEX IF NOT EXISTS idx_team_pets_name ON team_pets(pet_name);

CREATE TABLE IF NOT EXISTS team_pet_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_pet_id INTEGER NOT NULL REFERENCES team_pets(id) ON DELETE CASCADE,
    slot INTEGER NOT NULL,
    skill_id INTEGER REFERENCES skills(id),
    skill_name TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_team_pet_skills_pet ON team_pet_skills(team_pet_id);
"""


DROP_ORDER = (
    "team_pet_skills",
    "team_pets",
    "teams",
    "bloodline_magic_effects",
    "bloodline_magics",
    "bloodlines",
    "weather_effects",
    "weathers",
    "mark_sources",
    "marks",
    "statuses",
    "effect_gaps",
    "ability_effects",
    "skill_effects",
    "pet_transforms",
    "pet_skills",
    "skills",
    "pets",
    "abilities",
    "elements",
)


ELEMENT_CODES = (
    "normal", "grass", "fire", "water", "light", "ground", "ice", "dragon",
    "electric", "poison", "bug", "fighting", "flying", "cute", "ghost",
    "dark", "mechanical", "illusion",
)


def _seed_static_rows(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO elements (id, code, name, sort_order) VALUES (?, ?, ?, ?)",
        [(i, code, name, i) for i, (code, name) in enumerate(zip(ELEMENT_CODES, ELEMENT_NAMES))],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO statuses (id, code, name, packed_index) VALUES (?, ?, ?, ?)",
        [
            (0, "burn", "灼烧", 0),
            (1, "poison", "中毒", 1),
            (2, "freeze", "冻结", 2),
            (3, "leech", "寄生", 3),
        ],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO weathers (id, code, name, packed_value) VALUES (?, ?, ?, ?)",
        [
            (0, "none", "无天气", 0),
            (1, "rain", "雨天", 1),
            (2, "sandstorm", "沙暴", 2),
            (3, "snow", "雪天", 3),
        ],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO weather_effects (weather_id, timing_code, tag_code, params_json, sort_order) VALUES (?, ?, ?, ?, ?)",
        [
            (1, Timing.CALC_DAMAGE.value, PakOp.EFF_DAMAGE.value, '{"element":"水","mult":1.5}', 0),
            (2, Timing.TURN_END.value, PakOp.EFF_DAMAGE.value, '{"fraction":0.0625,"immune":["地","机械"]}', 0),
            (3, Timing.TURN_END.value, PakOp.FREEZE_STATUS.value, '{"stacks":2}', 0),
        ],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO bloodlines (id, code, name, kind, element_id) VALUES (?, ?, ?, ?, ?)",
        [(i, code, name, "element", i) for i, (code, name) in enumerate(zip(ELEMENT_CODES, ELEMENT_NAMES))]
        + [
            (18, "leader", "首领", "leader", None),
        ],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO bloodline_magics (id, code, name, uses_per_battle, description) VALUES (?, ?, ?, ?, ?)",
        [
            (1, "willpower_strike", "愿力冲击", 2, "以当前精灵血脉属性发动愿力冲击。"),
            (2, "leader_transform", "进化之力", 1, "首领血脉进化接口，形态数据缺失时由 audit 暴露。"),
        ],
    )


def migrate(reset: bool = False, db_path: str | Path | None = None) -> sqlite3.Connection:
    db_path = Path(db_path) if db_path else DB_DIR / "data.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    if reset:
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in DROP_ORDER:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript(SCHEMA)
    _seed_static_rows(conn)
    conn.commit()
    return conn


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    conn = migrate(args.reset)
    print(f"Migrated -> {DB_DIR / 'data.db'}")
    conn.close()


if __name__ == "__main__":
    main()
