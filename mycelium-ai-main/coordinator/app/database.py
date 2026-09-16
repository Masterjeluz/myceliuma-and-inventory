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
        _ensure_node_columns(db)


def _ensure_node_columns(db) -> None:
    """Additive, idempotent migration for distributed nodes (BIG #8).

    Auth hash, display name, model/executor advertisements,
    resource hints and locality zone. All nullable/defaulted so
    existing positional INSERTs (9 values) keep working.
    """
    existing = {row["name"] for row in db.execute("PRAGMA table_info(nodes)").fetchall()}
    for column, ddl in (
        ("auth_token_hash", "TEXT DEFAULT NULL"),
        ("display_name", "TEXT DEFAULT ''"),
        ("models", "TEXT DEFAULT '[]'"),
        ("executors", "TEXT DEFAULT '[]'"),
        ("resources", "TEXT DEFAULT '{}'"),
        ("locality_zone", "TEXT DEFAULT 'local_network'"),
        ("last_auth", "TEXT DEFAULT ''"),
    ):
        if column not in existing:
            db.execute(f"ALTER TABLE nodes ADD COLUMN {column} {ddl}")


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
    if "routing" not in existing:
        db.execute("ALTER TABLE tasks ADD COLUMN routing TEXT DEFAULT '{}'")
    if "routing_decision" not in existing:
        db.execute("ALTER TABLE tasks ADD COLUMN routing_decision TEXT DEFAULT '{}'")


CHAT_DATABASE_ENV_VAR = "MYCELIUM_CHAT_DATABASE_PATH"


def chat_database_path() -> str:
    path = os.environ.get(CHAT_DATABASE_ENV_VAR, "data/mycelium-chat.db")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def chat_connection():
    """Separate SQLite file for chat/agent interaction state.

    The task-queue database keeps exactly its nodes/tasks tables (an
    existing test pins this); conversations, messages and desktop
    actions live here instead. Same JSON conventions, same additive
    discipline, lazily initialized on first use.
    """
    db = sqlite3.connect(chat_database_path())
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_chat_database() -> None:
    with chat_connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            project_ref TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            message_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            provenance TEXT NOT NULL,
            sources TEXT NOT NULL DEFAULT '[]'
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages(conversation_id, created_at);
        CREATE TABLE IF NOT EXISTS desktop_actions (
            action_id TEXT PRIMARY KEY,
            record TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_approval',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS missions (
            mission_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL DEFAULT '',
            record TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_approval',
            current_step INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_missions_conversation
            ON missions(conversation_id, created_at);
        CREATE TABLE IF NOT EXISTS conversation_events (
            event_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            mission_id TEXT NOT NULL DEFAULT '',
            step_id TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_conversation
            ON conversation_events(conversation_id, created_at);
        CREATE TABLE IF NOT EXISTS action_bindings (
            action_id TEXT PRIMARY KEY,
            mission_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            bound_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS semantic_vectors (
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            model TEXT NOT NULL,
            dim INTEGER NOT NULL,
            vector BLOB NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (entity_type, entity_id, model)
        );
        CREATE INDEX IF NOT EXISTS idx_vectors_model
            ON semantic_vectors(model, updated_at);
        CREATE TABLE IF NOT EXISTS camera_devices (
            device_id TEXT PRIMARY KEY,
            record TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS camera_observations (
            observation_id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            record TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cam_obs_device
            ON camera_observations(device_id, created_at);
        CREATE TABLE IF NOT EXISTS vision_analyses (
            analysis_id TEXT PRIMARY KEY,
            observation_id TEXT NOT NULL,
            record TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_vision_obs
            ON vision_analyses(observation_id, created_at);
        CREATE TABLE IF NOT EXISTS printer_devices (
            printer_id TEXT PRIMARY KEY,
            record TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fabrications (
            fabrication_id TEXT PRIMARY KEY,
            record TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'started',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_fab_status
            ON fabrications(status, created_at);
        CREATE TABLE IF NOT EXISTS write_proposals (
            proposal_id TEXT PRIMARY KEY,
            record TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'proposed',
            approval TEXT NOT NULL DEFAULT '{}',
            result TEXT NOT NULL DEFAULT '{}',
            verification TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)


def dump(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def load(value: str) -> object:
    return json.loads(value)
