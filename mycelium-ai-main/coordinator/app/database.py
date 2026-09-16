import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path


#: Serializes schema setup. DDL (executescript with CREATE
#: TABLE/INDEX) cannot run concurrently against one file;
#: this lock makes first-touch init a critical section.
#: Data writes never take this lock — they serialize in
#: the engine via WAL + busy_timeout instead.
_INIT_LOCK = threading.Lock()


def database_path() -> str:
    path = os.environ.get("MYCELIUM_DATABASE_PATH", "data/mycelium.db")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


#: Conservative busy timeout for local concurrent writers
#: (claim + campaign + sync-apply + jobs). Writers wait
#: instead of failing with "database is locked"; no retry
#: loop masks real contention, the engine serializes it.
BUSY_TIMEOUT_MS = 15000


def _open_db(path: str) -> sqlite3.Connection:
    """One deterministic connection setup for every database
    file: WAL journal mode (readers never block writers),
    busy timeout (writers wait instead of failing), row
    factory. Short-lived connections only — never shared
    across threads, never held open across requests."""
    db = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000.0)
    db.row_factory = sqlite3.Row
    db.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    db.execute("PRAGMA journal_mode=WAL")
    return db


@contextmanager
def connection():
    db = _open_db(database_path())
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_database() -> None:
    with _INIT_LOCK:
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
        CREATE INDEX IF NOT EXISTS idx_tasks_status
            ON tasks(status, priority DESC, id ASC);
        CREATE INDEX IF NOT EXISTS idx_nodes_last_seen
            ON nodes(last_seen);
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
        ("coordinator_capable", "INTEGER NOT NULL DEFAULT 0"),
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
    db = _open_db(chat_database_path())
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_chat_database() -> None:
    with _INIT_LOCK:
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
        CREATE TABLE IF NOT EXISTS interface_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            conversation_id TEXT NOT NULL DEFAULT '',
            mission_id TEXT NOT NULL DEFAULT '',
            task_id TEXT NOT NULL DEFAULT '',
            proposal_id TEXT NOT NULL DEFAULT '',
            node_id TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            payload TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_type
            ON interface_events(event_type, created_at);
        CREATE TABLE IF NOT EXISTS notifications (
            notification_id TEXT PRIMARY KEY,
            recipient_node_id TEXT NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            severity TEXT NOT NULL DEFAULT 'info',
            related_entity TEXT NOT NULL DEFAULT '',
            related_mission TEXT NOT NULL DEFAULT '',
            related_task TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL DEFAULT '',
            read INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_ntf_recipient
            ON notifications(recipient_node_id, created_at);
        CREATE TABLE IF NOT EXISTS interface_sessions (
            session_id TEXT PRIMARY KEY,
            interface_id TEXT NOT NULL,
            node_id TEXT NOT NULL DEFAULT '',
            conversation_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS voice_approvals (
            approval_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            target_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS live_sessions (
            session_id TEXT PRIMARY KEY,
            interface TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT '',
            capabilities TEXT NOT NULL DEFAULT '[]',
            context_scope TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS dist_events (
            event_id TEXT PRIMARY KEY,
            origin_node_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            entity_type TEXT NOT NULL DEFAULT '',
            entity_revision TEXT NOT NULL DEFAULT '',
            base_revision TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            provenance TEXT NOT NULL DEFAULT '{}',
            epoch INTEGER NOT NULL DEFAULT 0,
            payload_hash TEXT NOT NULL DEFAULT '',
            applied_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_dist_entity
            ON dist_events(entity_id, applied_at);
        CREATE TABLE IF NOT EXISTS dist_conflicts (
            conflict_id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            base_revision TEXT NOT NULL DEFAULT '',
            first_event_id TEXT NOT NULL,
            second_event_id TEXT NOT NULL,
            first_origin TEXT NOT NULL DEFAULT '',
            second_origin TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_dist_conflict_entity
            ON dist_conflicts(entity_id, status);
        CREATE TABLE IF NOT EXISTS coordinator_lease (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            epoch INTEGER NOT NULL DEFAULT 0,
            holder_node_id TEXT NOT NULL DEFAULT '',
            fencing_token TEXT NOT NULL DEFAULT '',
            expires_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
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
        CREATE TABLE IF NOT EXISTS memories (
            memory_id TEXT PRIMARY KEY,
            memory_type TEXT NOT NULL DEFAULT 'fact',
            truth TEXT NOT NULL DEFAULT 'ai_suggestion',
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            data TEXT NOT NULL DEFAULT '{}',
            source TEXT NOT NULL DEFAULT '',
            provenance TEXT NOT NULL DEFAULT '{}',
            confidence REAL NOT NULL DEFAULT 0.5,
            importance REAL NOT NULL DEFAULT 0.5,
            project_ref TEXT NOT NULL DEFAULT '',
            entity_refs TEXT NOT NULL DEFAULT '[]',
            event_refs TEXT NOT NULL DEFAULT '[]',
            derived_from TEXT NOT NULL DEFAULT '[]',
            revision INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'active',
            expiry TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            fingerprint TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_memories_type
            ON memories(memory_type, status);
        CREATE INDEX IF NOT EXISTS idx_memories_project
            ON memories(project_ref, status);
        CREATE INDEX IF NOT EXISTS idx_memories_updated
            ON memories(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memories_truth
            ON memories(truth, status);
        CREATE TABLE IF NOT EXISTS health_measurements (
            measurement_id TEXT PRIMARY KEY,
            metric TEXT NOT NULL DEFAULT '',
            value REAL NOT NULL DEFAULT 0.0,
            unit TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'manual',
            provenance TEXT NOT NULL DEFAULT '{}',
            observed_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            dedup_key TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_health_metric
            ON health_measurements(metric, observed_at);
        CREATE TABLE IF NOT EXISTS foods (
            food_id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            nutrients TEXT NOT NULL DEFAULT '{}',
            vegan_status TEXT NOT NULL DEFAULT 'unknown',
            vegan_evidence TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'manual',
            provenance TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meals (
            meal_id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            items TEXT NOT NULL DEFAULT '[]',
            source TEXT NOT NULL DEFAULT 'manual',
            provenance TEXT NOT NULL DEFAULT '{}',
            observed_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_sources (
            source_id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL DEFAULT 'manual',
            external_id TEXT NOT NULL DEFAULT '',
            reference TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            author TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            topics TEXT NOT NULL DEFAULT '[]',
            provenance TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'stored',
            captured_at TEXT NOT NULL,
            published_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_research_sources_hash
            ON research_sources(content_hash);
        CREATE INDEX IF NOT EXISTS idx_research_sources_type
            ON research_sources(source_type, captured_at);
        CREATE TABLE IF NOT EXISTS research_records (
            record_id TEXT PRIMARY KEY,
            question TEXT NOT NULL DEFAULT '',
            claims TEXT NOT NULL DEFAULT '[]',
            source_ids TEXT NOT NULL DEFAULT '[]',
            synthesis TEXT NOT NULL DEFAULT '',
            provenance TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'stored',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS skills (
            skill_id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            prerequisites TEXT NOT NULL DEFAULT '[]',
            related_skills TEXT NOT NULL DEFAULT '[]',
            stage TEXT NOT NULL DEFAULT 'discovered',
            proficiency TEXT NOT NULL DEFAULT 'unknown',
            evidence TEXT NOT NULL DEFAULT '[]',
            source TEXT NOT NULL DEFAULT '',
            provenance TEXT NOT NULL DEFAULT '{}',
            project_refs TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS skill_candidates (
            candidate_id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            evidence TEXT NOT NULL DEFAULT '[]',
            project_ref TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'proposed',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cad_documents (
            document_id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            parts TEXT NOT NULL DEFAULT '[]',
            parameters TEXT NOT NULL DEFAULT '{}',
            operations TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'draft',
            provenance TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS filament_spools (
            spool_id TEXT PRIMARY KEY,
            material TEXT NOT NULL DEFAULT '',
            color TEXT NOT NULL DEFAULT '',
            diameter_mm REAL NOT NULL DEFAULT 1.75,
            weight_remaining_g REAL NOT NULL DEFAULT 0.0,
            compatible_profiles TEXT NOT NULL DEFAULT '[]',
            source TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            provenance TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS robots (
            robot_id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            robot_type TEXT NOT NULL DEFAULT 'other',
            capabilities TEXT NOT NULL DEFAULT '[]',
            location TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'idle',
            safety_state TEXT NOT NULL DEFAULT 'safe',
            node_id TEXT NOT NULL DEFAULT '',
            provenance TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS drones (
            drone_id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            capabilities TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'grounded',
            safety_state TEXT NOT NULL DEFAULT 'safe',
            home_location TEXT NOT NULL DEFAULT '',
            provenance TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS familiars (
            familiar_id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT 'digital',
            capabilities TEXT NOT NULL DEFAULT '[]',
            linked_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'idle',
            provenance TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS twin_links (
            link_id TEXT PRIMARY KEY,
            physical_ref TEXT NOT NULL DEFAULT '',
            digital_ref TEXT NOT NULL DEFAULT '',
            link_type TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0.5,
            last_observed_at TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            provenance TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_runs (
            run_id TEXT PRIMARY KEY,
            job_name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'completed',
            detail TEXT NOT NULL DEFAULT '',
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS integration_identities (
            integration_id TEXT PRIMARY KEY,
            key_hash TEXT NOT NULL DEFAULT '',
            capabilities TEXT NOT NULL DEFAULT '[]',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS integration_events (
            event_id TEXT PRIMARY KEY,
            integration_id TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            external_event_id TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL DEFAULT '',
            payload_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'received',
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS
            idx_integration_idem
            ON integration_events(integration_id,
                                  idempotency_key);
        CREATE INDEX IF NOT EXISTS idx_integration_status
            ON integration_events(integration_id, status);
        CREATE TABLE IF NOT EXISTS integration_outbox (
            outbox_id TEXT PRIMARY KEY,
            target_label TEXT NOT NULL DEFAULT '',
            payload TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            created_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            acked_at TEXT NOT NULL DEFAULT '',
            acked_by TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_outbox_status
            ON integration_outbox(status, created_at);
        """)


def dump(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def load(value: str) -> object:
    return json.loads(value)
