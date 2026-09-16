"""Durable distributed state foundation (BIG #10, deel 1).

Event/change-log based synchronization instead of database
copies: origins emit small envelopes, receivers apply them
idempotently, conflicts become explicit records. No blind
last-write-wins for important state.

Envelope fields:

- event_id (stable, ``dsevt_`` + time-hex + randomness)
- origin_node_id (who emitted; never trusted blindly)
- entity_id / entity_type (what it concerns)
- entity_revision (opaque revision supplied by the origin,
  e.g. INVENTory ``updated_at``; compared as text)
- base_revision (revision this change was built on; empty
  means "create/unknown")
- event_type (closed set below)
- timestamp (origin clock, ISO)
- payload (small capped dict, never executable content)
- provenance (preserved end to end)
- epoch (coordinator fencing epoch when relevant, else 0)

Apply semantics (all fail-closed):

- unknown event_id → record + apply, advance cursor;
- known event_id → acknowledge as duplicate, no second
  mutation (idempotent);
- same entity + same base_revision + different payload hash
  from another origin → conflict record, neither version
  silently changed, both provenances preserved;
- same entity + newer-or-equal base already applied with
  identical payload hash → duplicate, no mutation;
- out-of-order arrival is safe: ordering never decides truth,
  only base_revision matching does.

Deterministic merge exists ONLY for the whitelisted
technical-metadata keys below (cursor positions, last-seen
hints); everything else conflicts explicitly.

INVENTory stays source of truth for world entities: these
envelopes carry change notifications and coordinator state,
never a second copy of world rows. Mycelium never opens the
INVENTory SQLite file; the bridge stays HTTP.
"""

import hashlib
import json
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import Provenance

DistEventType = Literal[
    "entity.observed",
    "entity.proposed",
    "task.state",
    "node.presence",
    "coordinator.epoch",
    "sync.cursor",
    "sync.conflict",
    "sync.resolved",
]
VALID_DIST_EVENT_TYPES = frozenset({
    "entity.observed",
    "entity.proposed",
    "task.state",
    "node.presence",
    "coordinator.epoch",
    "sync.cursor",
    "sync.conflict",
    "sync.resolved",
})

#: Payload keys eligible for deterministic technical merge.
#: Everything else conflicts explicitly on concurrent change.
MERGEABLE_METADATA_KEYS = frozenset({
    "cursor",
    "last_seen",
    "attempt_count_hint",
})

BANNED_DIST_PAYLOAD_KEYS = frozenset({
    "command", "commands", "exec", "execute", "shell", "code",
    "script", "url", "callback", "webhook", "sql", "query",
})

MAX_DIST_PAYLOAD_KEYS = 30
MAX_DIST_PAYLOAD_VALUE_CHARS = 1000
MAX_ENTITY_ID_CHARS = 100
MAX_REVISION_CHARS = 120
SYNC_BATCH_LIMIT = 100


class DistStateRefusedError(ValueError):
    """Local validation refused; nothing was recorded or applied."""


class DistEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=3, max_length=80)
    origin_node_id: str = Field(min_length=1, max_length=80)
    entity_id: str = Field(min_length=1, max_length=MAX_ENTITY_ID_CHARS)
    entity_type: str = Field(min_length=1, max_length=40)
    entity_revision: str = Field(default="", max_length=MAX_REVISION_CHARS)
    base_revision: str = Field(default="", max_length=MAX_REVISION_CHARS)
    event_type: str = Field(min_length=1, max_length=40)
    timestamp: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance = Field(default_factory=Provenance)
    epoch: int = Field(default=0, ge=0)


class DistConflict(BaseModel):
    """Explicit conflict record. Both versions preserved, neither
    silently changed; resolution happens later by a human or an
    approved flow, never automatically."""

    model_config = ConfigDict(extra="forbid")

    conflict_id: str = Field(min_length=3, max_length=80)
    entity_id: str = Field(min_length=1, max_length=MAX_ENTITY_ID_CHARS)
    base_revision: str = Field(default="", max_length=MAX_REVISION_CHARS)
    first_event_id: str = Field(min_length=3, max_length=80)
    second_event_id: str = Field(min_length=3, max_length=80)
    first_origin: str = Field(default="", max_length=80)
    second_origin: str = Field(default="", max_length=80)
    status: str = Field(default="open", max_length=20)
    created_at: str = ""
    notes: str = Field(default="", max_length=1000)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_dist_event_id() -> str:
    return f"dsevt_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def generate_conflict_id() -> str:
    return f"dscon_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _check_payload(payload) -> dict:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise DistStateRefusedError("payload must be an object")
    if len(payload) > MAX_DIST_PAYLOAD_KEYS:
        raise DistStateRefusedError(
            f"at most {MAX_DIST_PAYLOAD_KEYS} payload keys")
    for key, value in payload.items():
        if not isinstance(key, str) or not key.strip() \
                or len(key) > 80:
            raise DistStateRefusedError(
                "payload keys must be short text")
        if key.strip().lower() in BANNED_DIST_PAYLOAD_KEYS:
            raise DistStateRefusedError(
                f"payload key '{key}' is not allowed in "
                "distributed envelopes")
        if isinstance(value, str) and len(value) > \
                MAX_DIST_PAYLOAD_VALUE_CHARS:
            raise DistStateRefusedError("payload values are capped")
        if not isinstance(value, (str, int, float, bool, type(None),
                                  list, dict)):
            raise DistStateRefusedError(
                f"payload value for '{key}' has an unsupported type")
    return dict(payload)


def new_envelope(origin_node_id: str, entity_id: str,
                 entity_type: str, event_type: str, *,
                 entity_revision: str = "",
                 base_revision: str = "",
                 payload: dict | None = None,
                 provenance: Provenance | None = None,
                 epoch: int = 0) -> DistEnvelope:
    """Build one validated envelope. Fail-closed on every field."""
    if not isinstance(origin_node_id, str) or not origin_node_id.strip():
        raise DistStateRefusedError("origin_node_id must be text")
    if not isinstance(entity_id, str) or not entity_id.strip() \
            or len(entity_id) > MAX_ENTITY_ID_CHARS:
        raise DistStateRefusedError("entity_id must be 1..100 chars")
    if not isinstance(entity_type, str) or not entity_type.strip() \
            or len(entity_type) > 40:
        raise DistStateRefusedError("entity_type must be 1..40 chars")
    if event_type not in VALID_DIST_EVENT_TYPES:
        raise DistStateRefusedError(
            f"Unknown distributed event type '{event_type}'")
    try:
        clean_epoch = int(epoch)
    except (TypeError, ValueError):
        raise DistStateRefusedError("epoch must be an integer")
    if clean_epoch < 0:
        raise DistStateRefusedError("epoch must be >= 0")
    return DistEnvelope(
        event_id=generate_dist_event_id(),
        origin_node_id=origin_node_id.strip()[:80],
        entity_id=entity_id.strip(),
        entity_type=entity_type.strip(),
        entity_revision=str(entity_revision or "")[
            :MAX_REVISION_CHARS],
        base_revision=str(base_revision or "")[:MAX_REVISION_CHARS],
        event_type=event_type,
        timestamp=now(),
        payload=_check_payload(payload),
        provenance=provenance or Provenance(
            source_type="sensor-observed",
            creator_id=f"dist:{origin_node_id.strip()[:80]}",
            human_verified=False,
            notes="distributed change envelope; application is "
                  "idempotent and never auto-verified"),
        epoch=clean_epoch)


def new_conflict(entity_id: str, base_revision: str,
                 first_id: str, second_id: str,
                 first_origin: str = "",
                 second_origin: str = "",
                 notes: str = "") -> DistConflict:
    return DistConflict(
        conflict_id=generate_conflict_id(),
        entity_id=entity_id, base_revision=base_revision,
        first_event_id=first_id, second_event_id=second_id,
        first_origin=first_origin[:80],
        second_origin=second_origin[:80],
        created_at=now(), notes=str(notes or "")[:1000])


def mergeable_update(current: dict, incoming: dict) -> dict | None:
    """Deterministic merge for whitelisted technical metadata.
    Returns the merged dict, or None when the incoming payload
    carries anything outside the mergeable set (→ conflict)."""
    if not isinstance(current, dict) or not isinstance(incoming,
                                                       dict):
        return None
    if any(key not in MERGEABLE_METADATA_KEYS for key in incoming):
        return None
    merged = dict(current)
    for key in MERGEABLE_METADATA_KEYS:
        if key in incoming:
            merged[key] = incoming[key]
    return merged


# -- durable log (chat DB; queue DB untouched, INVENTory untouched) --

def save_envelope(envelope: DistEnvelope) -> bool:
    """Record one envelope. Returns True when newly applied,
    False when it was already known (idempotent duplicate)."""
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        existing = db.execute(
            "SELECT event_id FROM dist_events WHERE event_id=?",
            (envelope.event_id,)).fetchone()
        if existing is not None:
            return False
        db.execute("""INSERT INTO dist_events
        (event_id, origin_node_id, entity_id, entity_type,
         entity_revision, base_revision, event_type, timestamp,
         payload, provenance, epoch, payload_hash, applied_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (envelope.event_id, envelope.origin_node_id,
                     envelope.entity_id, envelope.entity_type,
                     envelope.entity_revision,
                     envelope.base_revision, envelope.event_type,
                     envelope.timestamp,
                     dump(envelope.payload),
                     dump(envelope.provenance.model_dump(
                         mode="json")),
                     envelope.epoch,
                     payload_hash(envelope.payload), now()))
    return True


def known_event_ids(event_ids: list[str]) -> set[str]:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    known: set[str] = set()
    with chat_connection() as db:
        for event_id in list(event_ids or [])[:SYNC_BATCH_LIMIT * 2]:
            row = db.execute(
                "SELECT event_id FROM dist_events WHERE event_id=?",
                (event_id,)).fetchone()
            if row is not None:
                known.add(event_id)
    return known


def entity_history(entity_id: str,
                   limit: int = 50) -> list[DistEnvelope]:
    """Applied envelopes for one entity, oldest first."""
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute(
            """SELECT * FROM dist_events WHERE entity_id=?
            ORDER BY rowid ASC LIMIT ?""",
            (entity_id, max(1, min(limit, SYNC_BATCH_LIMIT)))).fetchall()
    return [_row_to_envelope(row, load) for row in rows]


def _row_to_envelope(row, load) -> DistEnvelope:
    from .inventory_read import Provenance as Prov
    raw_prov = load(row["provenance"]) if row["provenance"] else {}
    try:
        provenance = Prov.model_validate(
            raw_prov if isinstance(raw_prov, dict) else {})
    except ValueError:
        provenance = Prov()
    return DistEnvelope(
        event_id=row["event_id"],
        origin_node_id=row["origin_node_id"],
        entity_id=row["entity_id"],
        entity_type=row["entity_type"],
        entity_revision=row["entity_revision"] or "",
        base_revision=row["base_revision"] or "",
        event_type=row["event_type"],
        timestamp=row["timestamp"],
        payload=load(row["payload"]) if row["payload"] else {},
        provenance=provenance,
        epoch=row["epoch"] or 0)


def detect_conflict(envelope: DistEnvelope) -> DistConflict | None:
    """Compare one incoming envelope against applied history for
    the same entity. Returns a conflict when another origin
    changed the same base revision differently; None otherwise
    (including pure duplicates, handled by save_envelope)."""
    history = entity_history(envelope.entity_id,
                             limit=SYNC_BATCH_LIMIT)
    incoming_hash = payload_hash(envelope.payload)
    for applied in history:
        if applied.event_id == envelope.event_id:
            return None
        if payload_hash(applied.payload) == incoming_hash:
            continue
        if (envelope.base_revision
                and applied.base_revision == envelope.base_revision
                and applied.origin_node_id != envelope.origin_node_id):
            return new_conflict(
                envelope.entity_id, envelope.base_revision,
                applied.event_id, envelope.event_id,
                applied.origin_node_id, envelope.origin_node_id,
                notes="concurrent change of the same base "
                      "revision; both versions preserved")
    return None


def apply_envelope(envelope: DistEnvelope) -> dict:
    """Idempotent apply: duplicate → acknowledged, conflict →
    recorded (envelope still stored for audit, never silently
    merged), else applied. Returns a status dict."""
    if not isinstance(envelope, DistEnvelope):
        raise DistStateRefusedError("apply needs a DistEnvelope")
    # Re-validate pulled payloads: they bypass new_envelope(), so
    # banned keys (shell/command/exec/...) must refuse here too.
    _check_payload(envelope.payload)
    conflict = detect_conflict(envelope)
    if conflict is not None:
        save_envelope(envelope)
        save_conflict(conflict)
        return {"status": "conflict",
                "event_id": envelope.event_id,
                "conflict_id": conflict.conflict_id}
    if not save_envelope(envelope):
        return {"status": "duplicate",
                "event_id": envelope.event_id}
    return {"status": "applied", "event_id": envelope.event_id}


def save_conflict(conflict: DistConflict) -> None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO dist_conflicts
        (conflict_id, entity_id, base_revision, first_event_id,
         second_event_id, first_origin, second_origin, status,
         created_at, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(conflict_id) DO NOTHING""",
                    (conflict.conflict_id, conflict.entity_id,
                     conflict.base_revision, conflict.first_event_id,
                     conflict.second_event_id, conflict.first_origin,
                     conflict.second_origin, conflict.status,
                     conflict.created_at, conflict.notes))


def list_conflicts(status: str = "", limit: int = 50
                   ) -> list[DistConflict]:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        if status:
            if status not in ("open", "resolved"):
                raise DistStateRefusedError(
                    f"Unknown conflict status '{status}'")
            rows = db.execute(
                """SELECT * FROM dist_conflicts WHERE status=?
                ORDER BY created_at DESC LIMIT ?""",
                (status, max(1, min(limit, 100)))).fetchall()
        else:
            rows = db.execute(
                """SELECT * FROM dist_conflicts ORDER BY created_at
                DESC LIMIT ?""",
                (max(1, min(limit, 100)),)).fetchall()
    return [DistConflict(**{key: row[key] for key in (
        "conflict_id", "entity_id", "base_revision",
        "first_event_id", "second_event_id", "first_origin",
        "second_origin", "status", "created_at",
        "notes")}) for row in rows]


def resolve_conflict(conflict_id: str, resolution: str) -> bool:
    """Mark one conflict resolved (human/approved flow only).
    The versions themselves are never rewritten here."""
    if resolution not in ("resolved",):
        raise DistStateRefusedError(
            "conflicts resolve only as 'resolved'")
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        changed = db.execute(
            "UPDATE dist_conflicts SET status='resolved' WHERE "
            "conflict_id=? AND status='open'",
            (conflict_id,)).rowcount
    return changed == 1


def read_log(after_rowid: int = 0,
             limit: int = SYNC_BATCH_LIMIT) -> tuple[list[dict], int]:
    """Bounded cursor read over the durable log. Returns
    (envelopes-as-dicts, latest rowid). No dumps."""
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    count = max(1, min(int(limit or SYNC_BATCH_LIMIT),
                       SYNC_BATCH_LIMIT))
    try:
        cursor = max(0, int(after_rowid or 0))
    except (TypeError, ValueError):
        raise DistStateRefusedError("cursor must be an integer")
    with chat_connection() as db:
        rows = db.execute(
            """SELECT rowid, * FROM dist_events WHERE rowid>?
            ORDER BY rowid ASC LIMIT ?""",
            (cursor, count)).fetchall()
        latest = db.execute(
            "SELECT MAX(rowid) AS m FROM dist_events").fetchone()
    items = []
    for row in rows:
        record = dict(row)
        record.pop("rowid", None)
        try:
            record["payload"] = load(record.get("payload") or "{}")
        except ValueError:
            record["payload"] = {}
        items.append(record)
    return items, (latest["m"] or 0) if latest else 0
