"""n8n integration plane (BIG #17).

n8n is the EXTERNAL integration + automation plane around
Mycelium — schedules, external APIs, webhooks, transforms,
notifications, retries at the transport edge. It is never
the coordinator: no state writes, no SQLite, no approvals,
no physical authorization, no provenance upgrades.

Direction IN (n8n → Mycelium):
  external system → n8n → IntegrationEnvelope → validation
  → provenance → domain storage (health/memory/research).

Direction OUT (Mycelium → n8n):
  Mycelium enqueues delivery labels on an outbox; n8n
  polls, delivers externally, acks. Mycelium never calls
  n8n, never forwards arbitrary URLs, never ships secrets.

Scheduler: n8n triggers KNOWN jobs only
(POST /api/v1/integrations/trigger → jobs.run_job).
"""

import hashlib
import hmac
import json
import secrets
import time

from pydantic import BaseModel, Field

from .inventory_read import Provenance

#: Closed capability set for integration identities. No
#: wildcards, no overlap with node/operator powers.
INTEGRATION_CAPABILITIES = frozenset({
    "integration:ingest",
    "integration:trigger",
    "integration:status",
})

#: Secret-shaped keys that must never cross the boundary,
#: not even inside otherwise-valid payloads. n8n holds all
#: external credentials in its own credential store.
INTEGRATION_SECRET_KEYS = frozenset({
    "refresh_token", "access_token", "id_token",
    "api_key", "api_secret", "client_secret", "private_key",
    "password", "passwd", "pwd", "secret", "webhook_secret",
    "authorization",
})

INTEGRATION_SCHEMA_VERSIONS = frozenset({"1"})

MIN_INTEGRATION_TOKEN_CHARS = 32

#: Static registry. No hardcoded sprawl in routes: every
#: integration lives here with its source, capabilities,
#: status, auth mode, allowed event types, targets and
#: mock/live honesty state.
INTEGRATIONS = {
    "garmin": {
        "integration_id": "garmin",
        "source": "garmin",
        "capabilities": ["integration:ingest",
                         "integration:status"],
        "status": "UNAVAILABLE",
        "auth_mode": "key",
        "allowed_event_types": ["health.measurements"],
        "allowed_targets": ["notify"],
        "enabled": True,
        "mock": True,
        "live_detail": "no official Garmin credentials or "
                       "reviewed live transport; use the mock "
                       "provider for tests and development",
    },
    "generic": {
        "integration_id": "generic",
        "source": "generic",
        "capabilities": ["integration:ingest",
                         "integration:trigger",
                         "integration:status"],
        "status": "AVAILABLE",
        "auth_mode": "key",
        "allowed_event_types": ["health.measurements",
                                "memory.observation"],
        "allowed_targets": ["notify"],
        "enabled": True,
        "mock": False,
        "live_detail": "generic n8n webhook source; payloads "
                       "are observations, never facts",
    },
}


class IntegrationRefusedError(ValueError):
    """Fail-closed integration validation."""


class IntegrationAuthError(ValueError):
    """Integration credential rejected. Fail closed."""


def now() -> str:
    import datetime
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def generate_integration_id() -> str:
    return f"iev_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def generate_outbox_id() -> str:
    return f"obx_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def generate_integration_token() -> str:
    """One fresh bearer token (64 hex chars). Shown once to
    the operator; only its hash is ever stored."""
    return secrets.token_hex(32)


def hash_integration_token(integration_id: str,
                           token: str) -> str:
    digest = hashlib.sha256(
        f"mycelium-integration-v1|{integration_id}|"
        f"{token}".encode("utf-8"))
    return digest.hexdigest()


def payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_spec(integration_id: str) -> dict:
    spec = INTEGRATIONS.get(integration_id or "")
    if spec is None:
        raise IntegrationRefusedError(
            f"Unknown integration '{integration_id}'")
    return dict(spec)


def list_specs() -> list[dict]:
    return [dict(spec) for spec in INTEGRATIONS.values()]


class IntegrationEnvelope(BaseModel):
    integration_id: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=40)
    external_event_id: str = Field(min_length=1, max_length=200)
    event_type: str = Field(min_length=1, max_length=40)
    occurred_at: str = Field(min_length=1, max_length=80)
    received_at: str = Field(default="", max_length=80)
    payload: dict = Field(default_factory=dict)
    payload_hash: str = Field(default="", max_length=80)
    provenance: Provenance
    schema_version: str = Field(default="1", max_length=10)
    idempotency_key: str = Field(min_length=1, max_length=200)


def check_envelope(raw: dict) -> IntegrationEnvelope:
    """Validate one inbound envelope. Fail-closed on every
    field: unknown integration, source spoofing, bad event
    type, executable or secret-shaped payload, upgraded
    provenance, missing idempotency."""
    if not isinstance(raw, dict):
        raise IntegrationRefusedError("envelope must be an object")
    try:
        envelope = IntegrationEnvelope.model_validate(raw)
    except Exception as error:
        raise IntegrationRefusedError(f"bad envelope: {error}")
    spec = get_spec(envelope.integration_id)
    if not spec.get("enabled"):
        raise IntegrationRefusedError(
            f"integration '{envelope.integration_id}' disabled")
    if envelope.source != spec["source"]:
        raise IntegrationRefusedError(
            "envelope source does not match the integration; "
            "sources cannot be spoofed across integrations")
    if envelope.event_type not in spec["allowed_event_types"]:
        raise IntegrationRefusedError(
            f"event type '{envelope.event_type}' not allowed "
            f"for '{envelope.integration_id}'")
    if envelope.schema_version not in INTEGRATION_SCHEMA_VERSIONS:
        raise IntegrationRefusedError(
            "unsupported schema_version")
    try:
        from datetime import datetime as _dt
        moment = _dt.fromisoformat(envelope.occurred_at)
        if moment.tzinfo is None:
            raise ValueError("naive")
    except (ValueError, TypeError):
        raise IntegrationRefusedError(
            "occurred_at must be an ISO timestamp")
    from .payloads import check_payload
    try:
        clean = check_payload(
            envelope.payload, max_keys=20, max_value_chars=500,
            error=IntegrationRefusedError)
    except IntegrationRefusedError:
        raise
    lowered = {str(key).lower() for key in clean}
    if lowered & INTEGRATION_SECRET_KEYS:
        raise IntegrationRefusedError(
            "payload carries secret-shaped keys; credentials "
            "stay in n8n, never cross into Mycelium")
    provenance = envelope.provenance
    if provenance.source_type != "external-source":
        raise IntegrationRefusedError(
            "integration provenance must be external-source")
    if provenance.human_verified:
        raise IntegrationRefusedError(
            "transport can never mark human_verified")
    if provenance.creator_id != f"n8n:{envelope.integration_id}":
        raise IntegrationRefusedError(
            "provenance creator must be the n8n integration id")
    digest = payload_hash(clean)
    if envelope.payload_hash and envelope.payload_hash != digest:
        raise IntegrationRefusedError(
            "payload_hash does not match the payload")
    stamp = now()
    return envelope.model_copy(update={
        "payload": clean, "payload_hash": digest,
        "received_at": envelope.received_at or stamp})


# -- identity store (chat DB; hashes only, never tokens) --------------------

def issue_integration_key(integration_id: str,
                          capabilities: list | None = None
                          ) -> str:
    """Create (or rotate) the bearer key for one registered
    integration. Returns the plaintext ONCE; only the hash
    is stored. Unknown integrations refuse."""
    spec = get_spec(integration_id)
    wanted = set(capabilities or spec["capabilities"])
    if not wanted or not wanted <= INTEGRATION_CAPABILITIES:
        raise IntegrationRefusedError(
            "capabilities must be a non-empty subset of the "
            "integration set; no wildcards")
    if not wanted <= set(spec["capabilities"]):
        raise IntegrationRefusedError(
            f"integration '{integration_id}' cannot grant "
            "capabilities outside its spec")
    from .database import chat_connection, dump, init_chat_database
    token = generate_integration_token()
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO integration_identities
        (integration_id, key_hash, capabilities, enabled,
         created_at) VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(integration_id) DO UPDATE SET
         key_hash=excluded.key_hash,
         capabilities=excluded.capabilities,
         enabled=1, created_at=excluded.created_at""",
                     (integration_id,
                      hash_integration_token(integration_id,
                                             token),
                      dump(sorted(wanted)), now()))
    return token


def verify_integration_key(integration_id: str,
                           presented: str | None
                           ) -> list[str]:
    """Return granted capabilities or raise. Disabled,
    unknown or mismatched identities refuse without detail."""
    from .database import chat_connection, init_chat_database, load
    if not presented or not isinstance(presented, str):
        raise IntegrationAuthError("integration credential "
                                   "rejected")
    init_chat_database()
    with chat_connection() as db:
        row = db.execute(
            "SELECT key_hash, capabilities, enabled FROM "
            "integration_identities WHERE integration_id=?",
            (integration_id,)).fetchone()
    if row is None or not row["enabled"]:
        raise IntegrationAuthError("integration credential "
                                   "rejected")
    expected = hash_integration_token(integration_id, presented)
    if not hmac.compare_digest(expected, row["key_hash"]):
        raise IntegrationAuthError("integration credential "
                                   "rejected")
    try:
        caps = load(row["capabilities"])
    except ValueError:
        raise IntegrationAuthError("integration credential "
                                   "rejected")
    return [str(item) for item in caps
            if item in INTEGRATION_CAPABILITIES]


def require_capability(integration_id: str, presented: str | None,
                       capability: str) -> None:
    granted = verify_integration_key(integration_id, presented)
    if capability not in granted:
        raise IntegrationAuthError(
            f"integration lacks '{capability}'")


# -- idempotent ingestion -----------------------------------------------------

def _find_prior(integration_id: str,
                idempotency_key: str) -> dict | None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute(
            "SELECT * FROM integration_events WHERE "
            "integration_id=? AND (idempotency_key=? OR "
            "idempotency_key LIKE ? ESCAPE '\\') ORDER BY "
            "rowid ASC LIMIT 1",
            (integration_id, idempotency_key,
             _like_escape(idempotency_key) + "#%")).fetchone()
    return dict(row) if row is not None else None


def _like_escape(text: str) -> str:
    return str(text or "").replace("\\", "\\\\").replace(
        "%", "\\%").replace("_", "\\_")


def _record(status: str, envelope: IntegrationEnvelope,
            detail: str = "") -> dict:
    """Append one ledger row. The first (received) row keeps
    the bare idempotency key under the UNIQUE index; every
    follow-up outcome carries a per-attempt suffix so
    repeated duplicates never collide with each other."""
    from sqlite3 import IntegrityError

    from .database import chat_connection, init_chat_database
    init_chat_database()
    event_id = generate_integration_id()
    key = envelope.idempotency_key
    if status != "received":
        # Per-attempt suffix from the random tail of the new
        # event id (never the timestamp head: same-millisecond
        # attempts must not collide with each other).
        key = f"{key}#{status}-{event_id[-8:]}"
    record = {
        "event_id": event_id,
        "integration_id": envelope.integration_id,
        "source": envelope.source,
        "external_event_id": envelope.external_event_id,
        "idempotency_key": key,
        "event_type": envelope.event_type,
        "payload_hash": envelope.payload_hash,
        "status": status,
        "detail": str(detail or "")[:500],
        "created_at": now(),
    }
    with chat_connection() as db:
        try:
            db.execute("""INSERT INTO integration_events
            (event_id, integration_id, source,
             external_event_id, idempotency_key, event_type,
             payload_hash, status, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (record["event_id"],
                          record["integration_id"],
                          record["source"],
                          record["external_event_id"],
                          record["idempotency_key"],
                          record["event_type"],
                          record["payload_hash"],
                          record["status"], record["detail"],
                          record["created_at"]))
        except IntegrityError:
            raise IntegrationRefusedError(
                "concurrent duplicate; re-read the ledger")
    return record


def ingest_envelope(raw: dict) -> dict:
    """Validate → dedupe → map to domain storage. Returns
    accepted/duplicate/conflict with the stored record.
    Same key + same hash → duplicate. Same key +
    different hash → conflict (stored, never overwritten).
    Rejected envelopes never touch domain state."""
    envelope = check_envelope(raw)
    prior = _find_prior(envelope.integration_id,
                        envelope.idempotency_key)
    if prior is not None:
        if prior["payload_hash"] == envelope.payload_hash:
            return {"outcome": "duplicate",
                    "record": _record(
                        "duplicate", envelope,
                        f"already processed as "
                        f"{prior['event_id']}")}
        return {"outcome": "conflict",
                "record": _record(
                    "conflict", envelope,
                    f"same idempotency key as "
                    f"{prior['event_id']} with a different "
                    f"payload; kept side by side, never "
                    f"overwritten")}
    try:
        record = _record("received", envelope)
    except IntegrationRefusedError:
        # Lost a concurrent race on the same key: the other
        # writer owns it; converge on its outcome.
        prior = _find_prior(envelope.integration_id,
                            envelope.idempotency_key)
        if prior is not None and \
                prior["payload_hash"] == envelope.payload_hash:
            return {"outcome": "duplicate", "record": prior}
        return {"outcome": "conflict", "record": prior or {}}
    try:
        applied = _apply_to_domain(envelope)
    except (IntegrationRefusedError, ValueError) as error:
        record = _record("rejected", envelope, str(error))
        return {"outcome": "rejected", "record": record}
    accepted = _record("accepted", envelope, str(applied))
    accepted["applied"] = applied
    return {"outcome": "accepted", "record": accepted}


def _apply_to_domain(envelope: IntegrationEnvelope) -> dict:
    """Closed domain routing. Unknown (source, event_type)
    pairs refuse — the webhook cannot reach anything else."""
    key = (envelope.integration_id, envelope.event_type)
    if key in (("garmin", "health.measurements"),
               ("generic", "health.measurements")):
        return _apply_health_measurements(envelope)
    if key == ("generic", "memory.observation"):
        return _apply_memory_observation(envelope)
    raise IntegrationRefusedError(
        f"no domain mapping for '{envelope.event_type}'")


def _transport_notes(envelope: IntegrationEnvelope) -> str:
    spec = get_spec(envelope.integration_id)
    label = "MOCK" if spec.get("mock") else "LIVE"
    return (f"via n8n ({envelope.integration_id}); external "
            f"event {envelope.external_event_id}; {label}; "
            f"observation only, never fact")


def _apply_health_measurements(envelope: IntegrationEnvelope
                               ) -> dict:
    from .health import new_measurement, save_measurement
    items = envelope.payload.get("measurements", [])
    if not isinstance(items, list) or not items or \
            len(items) > 50:
        raise IntegrationRefusedError(
            "health.measurements needs 1..50 measurements")
    imported = 0
    duplicates = 0
    for item in items:
        if not isinstance(item, dict):
            raise IntegrationRefusedError(
                "measurements must be objects")
        measurement = new_measurement(
            str(item.get("metric", "")),
            item.get("value", 0),
            source="wearable"
            if envelope.integration_id == "garmin"
            else "external",
            observed_at=str(item.get("observed_at", "")),
            provenance=Provenance(
                source_type="external-source",
                creator_id=f"n8n:{envelope.integration_id}",
                human_verified=False,
                notes=_transport_notes(envelope)))
        if save_measurement(measurement):
            imported += 1
        else:
            duplicates += 1
    return {"imported": imported, "duplicates": duplicates}


def _apply_memory_observation(envelope: IntegrationEnvelope
                              ) -> dict:
    from .memory import new_memory, save_memory
    title = str(envelope.payload.get("title", "")).strip()
    content = str(envelope.payload.get("content", "")).strip()
    if not title:
        raise IntegrationRefusedError(
            "memory.observation needs a title")
    entry = new_memory(
        "observation", title[:200], truth="external_source",
        content=content[:2000],
        source=f"n8n:{envelope.integration_id}",
        provenance=Provenance(
            source_type="external-source",
            creator_id=f"n8n:{envelope.integration_id}",
            human_verified=False,
            notes=_transport_notes(envelope)))
    save_memory(entry)
    return {"memory_id": entry.memory_id}


def list_ingested(*, integration_id: str = "", status: str = "",
                  limit: int = 50) -> list[dict]:
    from .database import chat_connection, init_chat_database
    allowed_status = ("received", "accepted", "duplicate",
                      "conflict", "rejected", "failed")
    if status and status not in allowed_status:
        raise IntegrationRefusedError(
            f"Unknown status '{status}'")
    if integration_id:
        get_spec(integration_id)
    init_chat_database()
    clauses, params = [], []
    if integration_id:
        clauses.append("integration_id=?")
        params.append(integration_id)
    if status:
        clauses.append("status=?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with chat_connection() as db:
        rows = db.execute(
            f"SELECT event_id, integration_id, source, "
            f"external_event_id, idempotency_key, event_type, "
            f"payload_hash, status, detail, created_at FROM "
            f"integration_events {where} ORDER BY created_at "
            f"DESC LIMIT ?",
            (*params, max(1, min(int(limit or 50), 200)))
        ).fetchall()
    return [dict(row) for row in rows]


# -- outbox (Mycelium → n8n; poll model, never callbacks) ---------------------

def enqueue_delivery(target_label: str, payload: dict, *,
                     created_by: str) -> dict:
    """Queue one delivery label for n8n to poll. Labels are
    allow-listed per integration spec; no URLs, no secrets,
    no arbitrary destinations cross here."""
    if not isinstance(target_label, str) or not target_label:
        raise IntegrationRefusedError("target_label must be text")
    allowed = {label for spec in INTEGRATIONS.values()
               for label in spec["allowed_targets"]}
    if target_label not in allowed:
        raise IntegrationRefusedError(
            f"target '{target_label}' is not allow-listed")
    from .payloads import check_payload
    clean = check_payload(payload or {}, max_keys=20,
                          max_value_chars=2000,
                          error=IntegrationRefusedError)
    if not isinstance(created_by, str) or not created_by.strip():
        raise IntegrationRefusedError("created_by must be text")
    from .database import chat_connection, dump, init_chat_database
    record = {"outbox_id": generate_outbox_id(),
              "target_label": target_label,
              "payload": clean, "status": "pending",
              "created_by": created_by.strip()[:80],
              "created_at": now(), "acked_at": "",
              "acked_by": ""}
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO integration_outbox
        (outbox_id, target_label, payload, status,
         created_by, created_at, acked_at, acked_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                     (record["outbox_id"],
                      record["target_label"],
                      dump(record["payload"]), record["status"],
                      record["created_by"], record["created_at"],
                      "", ""))
    return record


def list_outbox(*, status: str = "pending",
                limit: int = 50) -> list[dict]:
    from .database import chat_connection, init_chat_database, load
    if status not in ("pending", "acked", "failed"):
        raise IntegrationRefusedError(
            f"Unknown outbox status '{status}'")
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute(
            "SELECT * FROM integration_outbox WHERE status=? "
            "ORDER BY created_at ASC LIMIT ?",
            (status, max(1, min(int(limit or 50), 200)))
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = load(row["payload"])
        except ValueError:
            item["payload"] = {}
        out.append(item)
    return out


def ack_outbox(outbox_id: str, integration_id: str,
               *, failed: bool = False) -> dict:
    """n8n acknowledges delivery. Unknown ids 404 at the
    route; double-acks return the stored state (idempotent)."""
    get_spec(integration_id)
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM integration_outbox "
                         "WHERE outbox_id=?",
                         (outbox_id,)).fetchone()
        if row is None:
            raise IntegrationRefusedError("outbox id not found")
        if row["status"] != "pending":
            return dict(row)
        status = "failed" if failed else "acked"
        db.execute("UPDATE integration_outbox SET status=?, "
                   "acked_at=?, acked_by=? WHERE outbox_id=?",
                   (status, now(), integration_id, outbox_id))
        updated = db.execute(
            "SELECT * FROM integration_outbox WHERE outbox_id=?",
            (outbox_id,)).fetchone()
    return dict(updated)


# -- scheduler trigger (known jobs only) --------------------------------------

def trigger_job(job_name: str, params: dict | None = None, *,
                run_key: str = "") -> dict:
    """Run one KNOWN job by name. n8n says which registered
    job runs — never what code runs. Semantics (bounded,
    idempotent, recorded) come from jobs.run_job."""
    from .jobs import run_job
    try:
        return run_job(job_name, params, run_key=run_key)
    except Exception as error:
        raise IntegrationRefusedError(f"job refused: {error}")
