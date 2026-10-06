"""World observations: multi-node perception without ownership.

One camera (or node, screen, sensor) never owns an object: many
``wobs_`` rows may reference the same ``entity_ref``. Each row
carries its own node, source, confidence, provenance and time,
so agents can weigh converging observations.

Complements ``cameras.CameraObservation`` (media-bound: device,
kind, media_ref) instead of competing with it: a world
observation may *reference* a camera observation or file via
``media_ref``, but stores no media itself. No vision, no
detection, no adapters here — rows are recorded explicitly by
nodes, game flows or the operator.

Storage follows the existing chat-DB pattern (record JSON +
query columns), same as ``camera_observations``.
"""

import secrets
import time
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import ENTITY_ID_PREFIXES

MAX_NODE_ID_LENGTH = 80
MAX_SOURCE_LENGTH = 40
MAX_ENTITY_REF_LENGTH = 120
MAX_NOTE_LENGTH = 500
MAX_MEDIA_REF_LENGTH = 200
VALID_SOURCES = ("camera", "screen", "sensor", "node", "game",
                 "operator")


class WorldObservationRefusedError(ValueError):
    """World observation validation refused; nothing was stored."""


class WorldObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    obs_id: str = Field(min_length=4, max_length=80)
    node_id: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=40)
    entity_ref: str = Field(default="", max_length=120)
    x: float | None = None
    y: float | None = None
    z: float | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    provenance: dict = Field(default_factory=dict)
    note: str = Field(default="", max_length=500)
    media_ref: str = Field(default="", max_length=200)
    created_at: str = ""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_obs_id() -> str:
    return f"wobs_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def _check_node_id(node_id) -> str:
    cleaned = str(node_id or "").strip()[:MAX_NODE_ID_LENGTH]
    if not cleaned:
        raise WorldObservationRefusedError(
            "node_id must be non-empty text")
    return cleaned


def _check_source(source) -> str:
    cleaned = str(source or "").strip()[:MAX_SOURCE_LENGTH]
    if cleaned not in VALID_SOURCES:
        raise WorldObservationRefusedError(
            f"Unknown source '{cleaned}'; expected one of "
            f"{sorted(VALID_SOURCES)}")
    return cleaned


def _check_entity_ref(entity_ref) -> str:
    cleaned = str(entity_ref or "").strip()[:MAX_ENTITY_REF_LENGTH]
    if not cleaned:
        return ""
    if not cleaned.startswith(ENTITY_ID_PREFIXES):
        raise WorldObservationRefusedError(
            f"Entity ref '{cleaned[:32]}' has an unknown prefix; "
            "refusing")
    return cleaned


def _check_position(x, y) -> tuple[float | None, float | None]:
    if x is None and y is None:
        return None, None
    if x is None or y is None:
        raise WorldObservationRefusedError(
            "position needs both x and y, or neither")
    try:
        clean_x = float(x)
        clean_y = float(y)
    except (TypeError, ValueError):
        raise WorldObservationRefusedError(
            "position x/y must be numbers")
    return clean_x, clean_y


def new_observation(node_id: str, source: str, *,
                    entity_ref: str = "", x=None, y=None, z=None,
                    confidence: float = 0.5,
                    provenance: dict | None = None,
                    note: str = "", media_ref: str = "") -> WorldObservation:
    """Validate + build one observation. Stores nothing."""
    try:
        clean_confidence = float(confidence)
    except (TypeError, ValueError):
        raise WorldObservationRefusedError(
            "confidence must be a number 0..1")
    if not 0.0 <= clean_confidence <= 1.0:
        raise WorldObservationRefusedError(
            "confidence must be between 0 and 1")
    clean_x, clean_y = _check_position(x, y)
    clean_z: float | None
    if z is None:
        clean_z = None
    else:
        if clean_x is None:
            raise WorldObservationRefusedError(
                "z needs x and y alongside it")
        try:
            clean_z = float(z)
        except (TypeError, ValueError):
            raise WorldObservationRefusedError(
                "position z must be a number")
    raw_provenance = provenance if isinstance(provenance, dict) else {}
    clean_note = str(note or "")
    if len(clean_note) > MAX_NOTE_LENGTH:
        raise WorldObservationRefusedError(
            f"note exceeds {MAX_NOTE_LENGTH} characters")
    clean_media = str(media_ref or "")
    if len(clean_media) > MAX_MEDIA_REF_LENGTH:
        raise WorldObservationRefusedError(
            f"media_ref exceeds {MAX_MEDIA_REF_LENGTH} characters")
    return WorldObservation(
        obs_id=generate_obs_id(),
        node_id=_check_node_id(node_id),
        source=_check_source(source),
        entity_ref=_check_entity_ref(entity_ref),
        x=clean_x, y=clean_y, z=clean_z,
        confidence=clean_confidence,
        provenance={str(key)[:80]: str(value)[:300]
                    for key, value in list(raw_provenance.items())[:20]},
        note=clean_note,
        media_ref=clean_media,
        created_at=now(),
    )


def _ensure(db) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS world_observations (
            obs_id TEXT PRIMARY KEY,
            node_id TEXT NOT NULL,
            entity_ref TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            record TEXT NOT NULL DEFAULT '{}'
        );
        """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_wobs_entity
            ON world_observations(entity_ref, created_at);
        """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_wobs_node
            ON world_observations(node_id, created_at);
        """)


def save_observation(observation: WorldObservation) -> WorldObservation:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        _ensure(db)
        db.execute(
            "INSERT INTO world_observations (obs_id, node_id, "
            "entity_ref, created_at, record) VALUES (?, ?, ?, ?, ?)",
            (observation.obs_id, observation.node_id,
             observation.entity_ref, observation.created_at,
             observation.model_dump_json()))
    return observation


def list_observations(limit: int = 50, entity_ref: str = "",
                      node_id: str = "") -> list[dict]:
    """Newest first. Optional entity/node filter. No ownership:
    many rows may share one entity_ref."""
    from .database import chat_connection, init_chat_database
    init_chat_database()
    count = max(1, min(int(limit or 50), 200))
    query = ("SELECT record FROM world_observations")
    clauses: list[str] = []
    params: list = []
    if entity_ref:
        clauses.append("entity_ref = ?")
        params.append(str(entity_ref).strip()[:MAX_ENTITY_REF_LENGTH])
    if node_id:
        clauses.append("node_id = ?")
        params.append(str(node_id).strip()[:MAX_NODE_ID_LENGTH])
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(count)
    import json as _json
    with chat_connection() as db:
        _ensure(db)
        rows = db.execute(query, tuple(params)).fetchall()
    out = []
    for row in rows:
        try:
            out.append(_json.loads(row["record"]))
        except (ValueError, KeyError, TypeError):
            continue
    return out
