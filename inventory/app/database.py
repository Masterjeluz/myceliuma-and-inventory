import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def database_path() -> str:
    path = os.environ.get("INVENTORY_DATABASE_PATH", "data/inventory.db")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connection():
    db = sqlite3.connect(database_path(), timeout=15.0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 15000;")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_database() -> None:
    """Initialize all database tables with WAL mode enabled."""
    with connection() as db:
        db.execute("PRAGMA journal_mode=WAL;")
        db.execute("PRAGMA synchronous=NORMAL;")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS objects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            quantity INTEGER NOT NULL DEFAULT 1,
            provenance TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_objects_created_at ON objects(created_at DESC);

        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'planned',
            provenance TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects(created_at DESC);

        CREATE TABLE IF NOT EXISTS ideas (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'raw',
            provenance TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ideas_created_at ON ideas(created_at DESC);

        CREATE TABLE IF NOT EXISTS relationships (
            id TEXT PRIMARY KEY,
            from_id TEXT NOT NULL,
            predicate TEXT NOT NULL,
            to_id TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            provenance TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_rel_from ON relationships(from_id);
        CREATE INDEX IF NOT EXISTS idx_rel_to ON relationships(to_id);

        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            data TEXT NOT NULL DEFAULT '{}',
            provenance TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_id);
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);

        CREATE TABLE IF NOT EXISTS hardware (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            manufacturer TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'unknown',
            capabilities TEXT NOT NULL DEFAULT '[]',
            interfaces TEXT NOT NULL DEFAULT '[]',
            metadata TEXT NOT NULL DEFAULT '{}',
            provenance TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hardware_created_at ON hardware(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_hardware_category ON hardware(category);

        CREATE TABLE IF NOT EXISTS sensors (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            sensor_type TEXT NOT NULL,
            manufacturer TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT '',
            measurement_type TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'unknown',
            capabilities TEXT NOT NULL DEFAULT '[]',
            interfaces TEXT NOT NULL DEFAULT '[]',
            metadata TEXT NOT NULL DEFAULT '{}',
            provenance TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sensors_created_at ON sensors(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sensors_type ON sensors(sensor_type);

        CREATE TABLE IF NOT EXISTS cameras (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            camera_type TEXT NOT NULL,
            manufacturer TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            resolution TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'unknown',
            capabilities TEXT NOT NULL DEFAULT '[]',
            interfaces TEXT NOT NULL DEFAULT '[]',
            metadata TEXT NOT NULL DEFAULT '{}',
            provenance TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cameras_created_at ON cameras(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cameras_type ON cameras(camera_type);

        CREATE TABLE IF NOT EXISTS locations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location_type TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'unknown',
            metadata TEXT NOT NULL DEFAULT '{}',
            provenance TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_locations_created_at ON locations(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_locations_type ON locations(location_type);

        CREATE TABLE IF NOT EXISTS models (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT '',
            model_identifier TEXT NOT NULL DEFAULT '',
            model_type TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            version TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'unknown',
            capabilities TEXT NOT NULL DEFAULT '[]',
            interfaces TEXT NOT NULL DEFAULT '[]',
            metadata TEXT NOT NULL DEFAULT '{}',
            provenance TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_models_created_at ON models(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_models_type ON models(model_type);

        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            task_type TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            priority INTEGER NOT NULL DEFAULT 0,
            input_requirements TEXT NOT NULL DEFAULT '[]',
            expected_output TEXT NOT NULL DEFAULT '',
            parameters TEXT NOT NULL DEFAULT '{}',
            metadata TEXT NOT NULL DEFAULT '{}',
            provenance TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(task_type);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

        CREATE TABLE IF NOT EXISTS actuators (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            actuator_type TEXT NOT NULL,
            manufacturer TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'unknown',
            capabilities TEXT NOT NULL DEFAULT '[]',
            interfaces TEXT NOT NULL DEFAULT '[]',
            parameters TEXT NOT NULL DEFAULT '{}',
            metadata TEXT NOT NULL DEFAULT '{}',
            provenance TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_actuators_created_at ON actuators(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_actuators_type ON actuators(actuator_type);

        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            file_kind TEXT NOT NULL,
            mime_type TEXT NOT NULL DEFAULT '',
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'unknown',
            metadata TEXT NOT NULL DEFAULT '{}',
            provenance TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_files_created_at ON files(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_files_kind ON files(file_kind);
        CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);
        """)
        _init_fts(db)
        rebuild_fts(db)


# =============================================================================
# FTS5 foundation (M4.1) — additive full-text index over existing entities.
#
# The canonical tables above remain the single source of truth. The *_fts
# virtual tables below are a derived, rebuildable search index:
# - new/changed/deleted rows are synced automatically via triggers;
# - rebuild_fts() re-indexes all existing rows (also called by
#   init_database, so older databases gain FTS without any migration);
# - entity_id is UNINDEXED: it links a match back to the canonical row
#   without polluting the full-text index.
# No query API lives here; sanitizing user queries belongs to M4.2.
# =============================================================================

FTS_TABLES = ("objects_fts", "projects_fts", "ideas_fts", "relationships_fts",
              "hardware_fts", "sensors_fts", "cameras_fts", "locations_fts",
              "models_fts", "tasks_fts", "actuators_fts", "files_fts")


def _init_fts(db) -> None:
    db.executescript("""
    CREATE VIRTUAL TABLE IF NOT EXISTS objects_fts USING fts5(
        entity_id UNINDEXED, name, description, provenance
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS projects_fts USING fts5(
        entity_id UNINDEXED, name, description, provenance
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS ideas_fts USING fts5(
        entity_id UNINDEXED, name, description, provenance
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS relationships_fts USING fts5(
        entity_id UNINDEXED, from_id, predicate, to_id, metadata
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS hardware_fts USING fts5(
        entity_id UNINDEXED, name, description, manufacturer, model, category
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS sensors_fts USING fts5(
        entity_id UNINDEXED, name, description, manufacturer, model, sensor_type
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS cameras_fts USING fts5(
        entity_id UNINDEXED, name, description, manufacturer, model, camera_type
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS locations_fts USING fts5(
        entity_id UNINDEXED, name, description, location_type
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS models_fts USING fts5(
        entity_id UNINDEXED, name, description, provider, model_identifier, model_type
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(
        entity_id UNINDEXED, name, description, task_type, status
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS actuators_fts USING fts5(
        entity_id UNINDEXED, name, description, manufacturer, model, actuator_type
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
        entity_id UNINDEXED, name, description, file_kind, mime_type
    );

    CREATE TRIGGER IF NOT EXISTS objects_fts_insert AFTER INSERT ON objects BEGIN
        INSERT INTO objects_fts(entity_id, name, description, provenance)
        VALUES (new.id, new.name, new.description, new.provenance);
    END;
    CREATE TRIGGER IF NOT EXISTS objects_fts_delete AFTER DELETE ON objects BEGIN
        DELETE FROM objects_fts WHERE entity_id = old.id;
    END;
    CREATE TRIGGER IF NOT EXISTS objects_fts_update AFTER UPDATE ON objects BEGIN
        DELETE FROM objects_fts WHERE entity_id = old.id;
        INSERT INTO objects_fts(entity_id, name, description, provenance)
        VALUES (new.id, new.name, new.description, new.provenance);
    END;

    CREATE TRIGGER IF NOT EXISTS projects_fts_insert AFTER INSERT ON projects BEGIN
        INSERT INTO projects_fts(entity_id, name, description, provenance)
        VALUES (new.id, new.name, new.description, new.provenance);
    END;
    CREATE TRIGGER IF NOT EXISTS projects_fts_delete AFTER DELETE ON projects BEGIN
        DELETE FROM projects_fts WHERE entity_id = old.id;
    END;
    CREATE TRIGGER IF NOT EXISTS projects_fts_update AFTER UPDATE ON projects BEGIN
        DELETE FROM projects_fts WHERE entity_id = old.id;
        INSERT INTO projects_fts(entity_id, name, description, provenance)
        VALUES (new.id, new.name, new.description, new.provenance);
    END;

    CREATE TRIGGER IF NOT EXISTS ideas_fts_insert AFTER INSERT ON ideas BEGIN
        INSERT INTO ideas_fts(entity_id, name, description, provenance)
        VALUES (new.id, new.name, new.description, new.provenance);
    END;
    CREATE TRIGGER IF NOT EXISTS ideas_fts_delete AFTER DELETE ON ideas BEGIN
        DELETE FROM ideas_fts WHERE entity_id = old.id;
    END;
    CREATE TRIGGER IF NOT EXISTS ideas_fts_update AFTER UPDATE ON ideas BEGIN
        DELETE FROM ideas_fts WHERE entity_id = old.id;
        INSERT INTO ideas_fts(entity_id, name, description, provenance)
        VALUES (new.id, new.name, new.description, new.provenance);
    END;

    CREATE TRIGGER IF NOT EXISTS relationships_fts_insert AFTER INSERT ON relationships BEGIN
        INSERT INTO relationships_fts(entity_id, from_id, predicate, to_id, metadata)
        VALUES (new.id, new.from_id, new.predicate, new.to_id, new.metadata);
    END;
    CREATE TRIGGER IF NOT EXISTS relationships_fts_delete AFTER DELETE ON relationships BEGIN
        DELETE FROM relationships_fts WHERE entity_id = old.id;
    END;
    CREATE TRIGGER IF NOT EXISTS relationships_fts_update AFTER UPDATE ON relationships BEGIN
        DELETE FROM relationships_fts WHERE entity_id = old.id;
        INSERT INTO relationships_fts(entity_id, from_id, predicate, to_id, metadata)
        VALUES (new.id, new.from_id, new.predicate, new.to_id, new.metadata);
    END;

    CREATE TRIGGER IF NOT EXISTS hardware_fts_insert AFTER INSERT ON hardware BEGIN
        INSERT INTO hardware_fts(entity_id, name, description, manufacturer, model, category)
        VALUES (new.id, new.name, new.description, new.manufacturer, new.model, new.category);
    END;
    CREATE TRIGGER IF NOT EXISTS hardware_fts_delete AFTER DELETE ON hardware BEGIN
        DELETE FROM hardware_fts WHERE entity_id = old.id;
    END;
    CREATE TRIGGER IF NOT EXISTS hardware_fts_update AFTER UPDATE ON hardware BEGIN
        DELETE FROM hardware_fts WHERE entity_id = old.id;
        INSERT INTO hardware_fts(entity_id, name, description, manufacturer, model, category)
        VALUES (new.id, new.name, new.description, new.manufacturer, new.model, new.category);
    END;

    CREATE TRIGGER IF NOT EXISTS sensors_fts_insert AFTER INSERT ON sensors BEGIN
        INSERT INTO sensors_fts(entity_id, name, description, manufacturer, model, sensor_type)
        VALUES (new.id, new.name, new.description, new.manufacturer, new.model, new.sensor_type);
    END;
    CREATE TRIGGER IF NOT EXISTS sensors_fts_delete AFTER DELETE ON sensors BEGIN
        DELETE FROM sensors_fts WHERE entity_id = old.id;
    END;
    CREATE TRIGGER IF NOT EXISTS sensors_fts_update AFTER UPDATE ON sensors BEGIN
        DELETE FROM sensors_fts WHERE entity_id = old.id;
        INSERT INTO sensors_fts(entity_id, name, description, manufacturer, model, sensor_type)
        VALUES (new.id, new.name, new.description, new.manufacturer, new.model, new.sensor_type);
    END;

    CREATE TRIGGER IF NOT EXISTS cameras_fts_insert AFTER INSERT ON cameras BEGIN
        INSERT INTO cameras_fts(entity_id, name, description, manufacturer, model, camera_type)
        VALUES (new.id, new.name, new.description, new.manufacturer, new.model, new.camera_type);
    END;
    CREATE TRIGGER IF NOT EXISTS cameras_fts_delete AFTER DELETE ON cameras BEGIN
        DELETE FROM cameras_fts WHERE entity_id = old.id;
    END;
    CREATE TRIGGER IF NOT EXISTS cameras_fts_update AFTER UPDATE ON cameras BEGIN
        DELETE FROM cameras_fts WHERE entity_id = old.id;
        INSERT INTO cameras_fts(entity_id, name, description, manufacturer, model, camera_type)
        VALUES (new.id, new.name, new.description, new.manufacturer, new.model, new.camera_type);
    END;

    CREATE TRIGGER IF NOT EXISTS locations_fts_insert AFTER INSERT ON locations BEGIN
        INSERT INTO locations_fts(entity_id, name, description, location_type)
        VALUES (new.id, new.name, new.description, new.location_type);
    END;
    CREATE TRIGGER IF NOT EXISTS locations_fts_delete AFTER DELETE ON locations BEGIN
        DELETE FROM locations_fts WHERE entity_id = old.id;
    END;
    CREATE TRIGGER IF NOT EXISTS locations_fts_update AFTER UPDATE ON locations BEGIN
        DELETE FROM locations_fts WHERE entity_id = old.id;
        INSERT INTO locations_fts(entity_id, name, description, location_type)
        VALUES (new.id, new.name, new.description, new.location_type);
    END;

    CREATE TRIGGER IF NOT EXISTS models_fts_insert AFTER INSERT ON models BEGIN
        INSERT INTO models_fts(entity_id, name, description, provider, model_identifier, model_type)
        VALUES (new.id, new.name, new.description, new.provider, new.model_identifier, new.model_type);
    END;
    CREATE TRIGGER IF NOT EXISTS models_fts_delete AFTER DELETE ON models BEGIN
        DELETE FROM models_fts WHERE entity_id = old.id;
    END;
    CREATE TRIGGER IF NOT EXISTS models_fts_update AFTER UPDATE ON models BEGIN
        DELETE FROM models_fts WHERE entity_id = old.id;
        INSERT INTO models_fts(entity_id, name, description, provider, model_identifier, model_type)
        VALUES (new.id, new.name, new.description, new.provider, new.model_identifier, new.model_type);
    END;

    CREATE TRIGGER IF NOT EXISTS tasks_fts_insert AFTER INSERT ON tasks BEGIN
        INSERT INTO tasks_fts(entity_id, name, description, task_type, status)
        VALUES (new.id, new.name, new.description, new.task_type, new.status);
    END;
    CREATE TRIGGER IF NOT EXISTS tasks_fts_delete AFTER DELETE ON tasks BEGIN
        DELETE FROM tasks_fts WHERE entity_id = old.id;
    END;
    CREATE TRIGGER IF NOT EXISTS tasks_fts_update AFTER UPDATE ON tasks BEGIN
        DELETE FROM tasks_fts WHERE entity_id = old.id;
        INSERT INTO tasks_fts(entity_id, name, description, task_type, status)
        VALUES (new.id, new.name, new.description, new.task_type, new.status);
    END;

    CREATE TRIGGER IF NOT EXISTS actuators_fts_insert AFTER INSERT ON actuators BEGIN
        INSERT INTO actuators_fts(entity_id, name, description, manufacturer, model, actuator_type)
        VALUES (new.id, new.name, new.description, new.manufacturer, new.model, new.actuator_type);
    END;
    CREATE TRIGGER IF NOT EXISTS actuators_fts_delete AFTER DELETE ON actuators BEGIN
        DELETE FROM actuators_fts WHERE entity_id = old.id;
    END;
    CREATE TRIGGER IF NOT EXISTS actuators_fts_update AFTER UPDATE ON actuators BEGIN
        DELETE FROM actuators_fts WHERE entity_id = old.id;
        INSERT INTO actuators_fts(entity_id, name, description, manufacturer, model, actuator_type)
        VALUES (new.id, new.name, new.description, new.manufacturer, new.model, new.actuator_type);
    END;

    CREATE TRIGGER IF NOT EXISTS files_fts_insert AFTER INSERT ON files BEGIN
        INSERT INTO files_fts(entity_id, name, description, file_kind, mime_type)
        VALUES (new.id, new.name, new.description, new.file_kind, new.mime_type);
    END;
    CREATE TRIGGER IF NOT EXISTS files_fts_delete AFTER DELETE ON files BEGIN
        DELETE FROM files_fts WHERE entity_id = old.id;
    END;
    CREATE TRIGGER IF NOT EXISTS files_fts_update AFTER UPDATE ON files BEGIN
        DELETE FROM files_fts WHERE entity_id = old.id;
        INSERT INTO files_fts(entity_id, name, description, file_kind, mime_type)
        VALUES (new.id, new.name, new.description, new.file_kind, new.mime_type);
    END;
    """)


def rebuild_fts(db=None) -> dict:
    """Re-index all canonical rows into FTS. Safe to run at any time.

    Returns per-table indexed row counts. Accepts an open connection (used by
    init_database) or opens one when called standalone.
    """
    if db is None:
        with connection() as handle:
            return rebuild_fts(handle)
    db.execute("DELETE FROM objects_fts")
    db.execute(
        "INSERT INTO objects_fts(entity_id, name, description, provenance)"
        " SELECT id, name, description, provenance FROM objects"
    )
    db.execute("DELETE FROM projects_fts")
    db.execute(
        "INSERT INTO projects_fts(entity_id, name, description, provenance)"
        " SELECT id, name, description, provenance FROM projects"
    )
    db.execute("DELETE FROM ideas_fts")
    db.execute(
        "INSERT INTO ideas_fts(entity_id, name, description, provenance)"
        " SELECT id, name, description, provenance FROM ideas"
    )
    db.execute("DELETE FROM relationships_fts")
    db.execute(
        "INSERT INTO relationships_fts(entity_id, from_id, predicate, to_id, metadata)"
        " SELECT id, from_id, predicate, to_id, metadata FROM relationships"
    )
    db.execute("DELETE FROM hardware_fts")
    db.execute(
        "INSERT INTO hardware_fts(entity_id, name, description, manufacturer, model, category)"
        " SELECT id, name, description, manufacturer, model, category FROM hardware"
    )
    db.execute("DELETE FROM sensors_fts")
    db.execute(
        "INSERT INTO sensors_fts(entity_id, name, description, manufacturer, model, sensor_type)"
        " SELECT id, name, description, manufacturer, model, sensor_type FROM sensors"
    )
    db.execute("DELETE FROM cameras_fts")
    db.execute(
        "INSERT INTO cameras_fts(entity_id, name, description, manufacturer, model, camera_type)"
        " SELECT id, name, description, manufacturer, model, camera_type FROM cameras"
    )
    db.execute("DELETE FROM locations_fts")
    db.execute(
        "INSERT INTO locations_fts(entity_id, name, description, location_type)"
        " SELECT id, name, description, location_type FROM locations"
    )
    db.execute("DELETE FROM models_fts")
    db.execute(
        "INSERT INTO models_fts(entity_id, name, description, provider, model_identifier, model_type)"
        " SELECT id, name, description, provider, model_identifier, model_type FROM models"
    )
    db.execute("DELETE FROM tasks_fts")
    db.execute(
        "INSERT INTO tasks_fts(entity_id, name, description, task_type, status)"
        " SELECT id, name, description, task_type, status FROM tasks"
    )
    db.execute("DELETE FROM actuators_fts")
    db.execute(
        "INSERT INTO actuators_fts(entity_id, name, description, manufacturer, model, actuator_type)"
        " SELECT id, name, description, manufacturer, model, actuator_type FROM actuators"
    )
    db.execute("DELETE FROM files_fts")
    db.execute(
        "INSERT INTO files_fts(entity_id, name, description, file_kind, mime_type)"
        " SELECT id, name, description, file_kind, mime_type FROM files"
    )
    return {
        "objects_fts": db.execute("SELECT COUNT(*) FROM objects_fts").fetchone()[0],
        "projects_fts": db.execute("SELECT COUNT(*) FROM projects_fts").fetchone()[0],
        "ideas_fts": db.execute("SELECT COUNT(*) FROM ideas_fts").fetchone()[0],
        "relationships_fts": db.execute("SELECT COUNT(*) FROM relationships_fts").fetchone()[0],
        "hardware_fts": db.execute("SELECT COUNT(*) FROM hardware_fts").fetchone()[0],
        "sensors_fts": db.execute("SELECT COUNT(*) FROM sensors_fts").fetchone()[0],
        "cameras_fts": db.execute("SELECT COUNT(*) FROM cameras_fts").fetchone()[0],
        "locations_fts": db.execute("SELECT COUNT(*) FROM locations_fts").fetchone()[0],
        "models_fts": db.execute("SELECT COUNT(*) FROM models_fts").fetchone()[0],
        "tasks_fts": db.execute("SELECT COUNT(*) FROM tasks_fts").fetchone()[0],
        "actuators_fts": db.execute("SELECT COUNT(*) FROM actuators_fts").fetchone()[0],
        "files_fts": db.execute("SELECT COUNT(*) FROM files_fts").fetchone()[0],
    }


# =============================================================================
# Search helpers (M4.2) — read-only access to the FTS foundation.
#
# sanitize_fts_query() treats user input as plain text: every token becomes a
# double-quoted FTS5 phrase, so quotes, wildcards, column filters and boolean
# operators lose their special meaning instead of crashing the query.
# search_fts() only ever interpolates hardcoded table names; the MATCH
# expression travels as a bound parameter. Unknown entity types are refused.
# =============================================================================

SEARCHABLE_TYPES = {
    "objects": "objects_fts",
    "projects": "projects_fts",
    "ideas": "ideas_fts",
    "relationships": "relationships_fts",
    "hardware": "hardware_fts",
    "sensors": "sensors_fts",
    "cameras": "cameras_fts",
    "locations": "locations_fts",
    "models": "models_fts",
    "tasks": "tasks_fts",
    "actuators": "actuators_fts",
    "files": "files_fts",
}

SEARCH_MAX_RESULTS = 50
SEARCH_MAX_QUERY_LENGTH = 200


def sanitize_fts_query(query) -> str | None:
    """Turn free text into a safe FTS5 MATCH expression, or None when unusable."""
    if not isinstance(query, str):
        return None
    if len(query) > SEARCH_MAX_QUERY_LENGTH:
        return None
    tokens = [token.replace('"', "") for token in query.split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        return None
    return " ".join(f'"{token}"' for token in tokens)


def search_fts(query, entity_types=None, limit=SEARCH_MAX_RESULTS) -> list:
    """Search the FTS tables; returns [(entity_type, entity_id)].

    ``query`` must be a pre-sanitized MATCH expression. Table names come
    exclusively from SEARCHABLE_TYPES; user input never reaches the SQL string.
    """
    types = list(entity_types) if entity_types else list(SEARCHABLE_TYPES)
    for entity_type in types:
        if entity_type not in SEARCHABLE_TYPES:
            raise ValueError(f"Unknown searchable type: {entity_type!r}")
    try:
        limit = max(1, min(int(limit), SEARCH_MAX_RESULTS))
    except (TypeError, ValueError):
        limit = SEARCH_MAX_RESULTS
    hits: list = []
    with connection() as db:
        for entity_type in types:
            table = SEARCHABLE_TYPES[entity_type]
            rows = db.execute(
                f"SELECT entity_id FROM {table} WHERE {table} MATCH ? LIMIT ?",
                (query, limit),
            ).fetchall()
            hits.extend((entity_type, row["entity_id"]) for row in rows)
    return hits[:limit]


def dump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def load(value: str) -> Any:
    return json.loads(value)
