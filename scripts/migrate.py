"""Create / reset the SQLite database schema.

Usage:
    python scripts/migrate.py          # create _db/data.db
    python scripts/migrate.py --reset  # drop all tables and recreate
"""

import sqlite3
import argparse
from scripts.utils import DB_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS pets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    form_name       TEXT    DEFAULT '',
    stage           TEXT    NOT NULL,          -- Ⅰ阶 / Ⅱ阶 / 最终形态 / 首领形态
    form_type       TEXT    DEFAULT '',         -- 原始形态 / 地区形态 / 首领形态
    element_primary TEXT    NOT NULL,
    element_secondary TEXT  DEFAULT '',
    ability_name    TEXT    DEFAULT '',
    ability_desc    TEXT    DEFAULT '',
    hp              INTEGER NOT NULL,
    atk_phys        INTEGER NOT NULL,
    atk_mag         INTEGER NOT NULL,
    def_phys        INTEGER NOT NULL,
    def_mag         INTEGER NOT NULL,
    speed           INTEGER NOT NULL,
    height          TEXT    DEFAULT '',
    weight          TEXT    DEFAULT '',
    distribution    TEXT    DEFAULT '',
    description     TEXT    DEFAULT '',
    is_shiny        INTEGER DEFAULT 0,
    evolution_cond  TEXT    DEFAULT '',
    version         TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS skills (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    element     TEXT    NOT NULL,
    category    TEXT    NOT NULL,              -- 物攻 / 魔攻 / 防御 / 状态
    energy      INTEGER NOT NULL,
    power       INTEGER NOT NULL,
    effect      TEXT    DEFAULT '',
    flavor_text TEXT    DEFAULT '',
    version     TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS pet_skills (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    pet_id       INTEGER NOT NULL REFERENCES pets(id),
    skill_id     INTEGER REFERENCES skills(id),
    skill_name   TEXT    NOT NULL,
    skill_type   TEXT    NOT NULL,             -- 技能 / 血脉技能 / 可学技能石
    unlock_level INTEGER,
    sort_order   INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pet_skills_pet   ON pet_skills(pet_id);
CREATE INDEX IF NOT EXISTS idx_pet_skills_skill ON pet_skills(skill_id);

CREATE TABLE IF NOT EXISTS yinji (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT    NOT NULL UNIQUE,
    type      TEXT    NOT NULL,                -- 正面 / 负面
    effect    TEXT    DEFAULT '',
    mechanism TEXT    DEFAULT ''               -- JSON array
);

CREATE TABLE IF NOT EXISTS yinji_skills (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    yinji_id    INTEGER NOT NULL REFERENCES yinji(id),
    skill_name  TEXT    NOT NULL,
    description TEXT    DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_yinji_skills_yinji ON yinji_skills(yinji_id);

CREATE TABLE IF NOT EXISTS teams (
    id              TEXT    PRIMARY KEY,
    title           TEXT    NOT NULL,
    author          TEXT    DEFAULT '',
    type            TEXT    NOT NULL,              -- pvp / pve
    bloodline_magic TEXT    DEFAULT '',
    description     TEXT    DEFAULT '',
    upload_date     TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS team_pets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     TEXT    NOT NULL REFERENCES teams(id),
    slot        INTEGER NOT NULL,                  -- 1-6
    pet_name    TEXT    NOT NULL,
    name_short  TEXT    DEFAULT '',
    bloodline   TEXT    DEFAULT '',
    nature      TEXT    DEFAULT '',
    ivs         TEXT    DEFAULT '',                -- comma-separated
    move1       TEXT    DEFAULT '',
    move2       TEXT    DEFAULT '',
    move3       TEXT    DEFAULT '',
    move4       TEXT    DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_team_pets_team ON team_pets(team_id);
CREATE INDEX IF NOT EXISTS idx_team_pets_name ON team_pets(pet_name);
"""


def migrate(reset: bool = False) -> sqlite3.Connection:
    db_path = DB_DIR / "data.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    if reset:
        conn.executescript("DROP TABLE IF EXISTS team_pets")
        conn.executescript("DROP TABLE IF EXISTS teams")
        conn.executescript("DROP TABLE IF EXISTS yinji_skills")
        conn.executescript("DROP TABLE IF EXISTS yinji")
        conn.executescript("DROP TABLE IF EXISTS pet_skills")
        conn.executescript("DROP TABLE IF EXISTS skills")
        conn.executescript("DROP TABLE IF EXISTS pets")

    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    conn = migrate(args.reset)
    print(f"Migrated → {DB_DIR / 'data.db'}")
    conn.close()


if __name__ == "__main__":
    main()
