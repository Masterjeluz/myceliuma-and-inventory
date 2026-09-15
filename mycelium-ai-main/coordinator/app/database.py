import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def database_path() -> str:
    path = os.environ.get("MYCELIUM_DATABASE_PATH", "data/mycelium.db")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connection():
    db = sqlite3.connect(database_path())
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_database() -> None:
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            node_id TEXT PRIMARY KEY,
            hostname TEXT NOT NULL,
            tier TEXT NOT NULL,
            capabilities TEXT NOT NULL,
            cpu_cores INTEGER NOT NULL,
            memory_mb INTEGER NOT NULL,
            energy_source TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'online'
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            required_capabilities TEXT NOT NULL,
            preferred_tier TEXT,
            priority INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'queued',
            assigned_node_id TEXT,
            result TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            assigned_at TEXT,
            lease_until TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0
        );
        """)
        _ensure_task_columns(db)


def _ensure_task_columns(db) -> None:
    """Additive, idempotent migration for pre-M7.4 databases.

    Existing tables gain the M7.4 columns without touching stored rows
    beyond safe defaults (attempt_count 0, no assignment, no lease).
    """
    existing = {row["name"] for row in db.execute("PRAGMA table_info(tasks)").fetchall()}
    if "assigned_at" not in existing:
        db.execute("ALTER TABLE tasks ADD COLUMN assigned_at TEXT")
    if "lease_until" not in existing:
        db.execute("ALTER TABLE tasks ADD COLUMN lease_until TEXT")
    if "attempt_count" not in existing:
        db.execute("ALTER TABLE tasks ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0")


def dump(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def load(value: str) -> object:
    return json.loads(value)
