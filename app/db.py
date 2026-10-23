"""Database connection and schema for Taskmaster Menu."""
import os
import sqlite3
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
DB_PATH = DATA_DIR / "taskmaster.db"
PHOTO_DIR = DATA_DIR / "photos"

SCHEMA = """
CREATE TABLE IF NOT EXISTS player_groups (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS players (
    id          INTEGER PRIMARY KEY,
    token       TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    photo_path  TEXT,
    group_id    INTEGER NOT NULL REFERENCES player_groups(id),
    removed     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY,
    title       TEXT    NOT NULL,
    stage       TEXT    NOT NULL DEFAULT 'group'
                CHECK (stage IN ('group', 'final')),
    group_id    INTEGER REFERENCES player_groups(id),
    status      TEXT    NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'active', 'revealed')),
    sort_order  INTEGER NOT NULL DEFAULT 0,
    opened_at   TEXT,
    revealed_at TEXT
);

CREATE TABLE IF NOT EXISTS task_performers (
    task_id     INTEGER NOT NULL REFERENCES tasks(id),
    player_id   INTEGER NOT NULL REFERENCES players(id),
    status      TEXT    NOT NULL DEFAULT 'in'
                CHECK (status IN ('in', 'sat_out', 'dq')),
    PRIMARY KEY (task_id, player_id)
);

CREATE TABLE IF NOT EXISTS scores (
    task_id      INTEGER NOT NULL REFERENCES tasks(id),
    judge_id     INTEGER NOT NULL REFERENCES players(id),
    performer_id INTEGER NOT NULL REFERENCES players(id),
    stars        INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
    locked_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (task_id, judge_id, performer_id)
);

CREATE TABLE IF NOT EXISTS adjustments (
    id          INTEGER PRIMARY KEY,
    player_id   INTEGER NOT NULL REFERENCES players(id),
    task_id     INTEGER REFERENCES tasks(id),
    points      INTEGER NOT NULL,
    reason      TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- The database itself guarantees only one task is active at a time.
CREATE UNIQUE INDEX IF NOT EXISTS one_active_task
    ON tasks(status) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    token      TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

"""


def connect() -> sqlite3.Connection:
    """Open a new connection. Call this once per operation and close it after."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create folders, tables, and the two default groups if missing."""
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        count = conn.execute("SELECT COUNT(*) FROM player_groups").fetchone()[0]
        if count == 0:
            conn.executemany(
                "INSERT INTO player_groups (name, sort_order) VALUES (?, ?)",
                [("Group 1", 1), ("Group 2", 2)],
            )
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('tv_mode', 'lobby')")            
        conn.commit()
    finally:
        conn.close()