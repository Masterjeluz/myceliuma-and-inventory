"""Energy ecosystem foundation (BIG #42).

Minimal energy domain: sources, production, consumption, storage
and current state, linked to projects/devices. Do not invent
measurements — unknown values stay NULL and render as UNKNOWN.

- Sources (closed): solar | battery | grid | machine | other.
- Kinds (closed): production | consumption | storage | state.
- A record is one observation or standing fact with provenance;
  current state for a project/device is derived (latest state-kind
  row), never stored twice.

Storage: chat DB table energy_records (additive, idempotent).
"""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ENERGY_SOURCES = ("solar", "battery", "grid", "machine", "other")
ENERGY_KINDS = ("production", "consumption", "storage", "state")


class EnergyRefusedError(ValueError):
    """Local validation refused; nothing was stored."""


class EnergyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=4, max_length=80)
    source: str = Field(min_length=1, max_length=16)
    kind: str = Field(min_length=1, max_length=16)
    value: float | None = None
    unit: str = Field(default="", max_length=24)
    project_ref: str = Field(default="", max_length=120)
    device_ref: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=1000)
    observed_at: str = ""
    created_at: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_record_id() -> str:
    return f"enr_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def init_energy_tables(db) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS energy_records (
            record_id TEXT PRIMARY KEY,
            source TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT '',
            value REAL DEFAULT NULL,
            unit TEXT NOT NULL DEFAULT '',
            project_ref TEXT NOT NULL DEFAULT '',
            device_ref TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            observed_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            provenance TEXT NOT NULL DEFAULT '{}'
        );
        """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_energy_project
            ON energy_records(project_ref, observed_at);
        """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_energy_device
            ON energy_records(device_ref, observed_at);
        """)


def _ensure(db) -> None:
    init_energy_tables(db)


def new_record(*, source: str, kind: str,
               value: float | None = None, unit: str = "",
               project_ref: str = "", device_ref: str = "",
               note: str = "", recorded_by: str = "operator",
               observed_at: str = "",
               provenance: dict | None = None) -> EnergyRecord:
    cleaned_source = str(source or "").strip().lower()[:16]
    if cleaned_source not in ENERGY_SOURCES:
        raise EnergyRefusedError(
            f"Unknown energy source '{source}'; expected one of "
            f"{list(ENERGY_SOURCES)}")
    cleaned_kind = str(kind or "").strip().lower()[:16]
    if cleaned_kind not in ENERGY_KINDS:
        raise EnergyRefusedError(
            f"Unknown energy kind '{kind}'; expected one of "
            f"{list(ENERGY_KINDS)}")
    amount = None
    if value is not None:
        try:
            amount = float(value)
        except (TypeError, ValueError) as error:
            raise EnergyRefusedError(
                "value must be a number or omitted") from error
        if amount != amount or amount in (float("inf"), float("-inf")):
            raise EnergyRefusedError("value must be finite")
        if abs(amount) > 10**15:
            raise EnergyRefusedError("value is unrealistically large")
    stamp = now()
    actor = str(recorded_by or "operator").strip()[:120] or "operator"
    prov = dict(provenance) if isinstance(provenance, dict) else {}
    prov.update({"source_type": "human-recorded",
                 "creator_id": actor, "human_verified": False})
    return EnergyRecord(
        record_id=generate_record_id(), source=cleaned_source,
        kind=cleaned_kind, value=amount,
        unit=str(unit or "").strip()[:24],
        project_ref=str(project_ref or "").strip()[:120],
        device_ref=str(device_ref or "").strip()[:120],
        note=str(note or "").strip()[:1000],
        observed_at=str(observed_at or "").strip()[:40] or stamp,
        created_at=stamp, provenance=prov)


def save_record(record: EnergyRecord) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        _ensure(db)
        db.execute(
            """INSERT INTO energy_records
            (record_id, source, kind, value, unit, project_ref,
             device_ref, note, observed_at, created_at, provenance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_id) DO UPDATE SET
             value=excluded.value, unit=excluded.unit,
             note=excluded.note, provenance=excluded.provenance""",
            (record.record_id, record.source, record.kind,
             record.value, record.unit, record.project_ref,
             record.device_ref, record.note, record.observed_at,
             record.created_at, dump(record.provenance)))
    _audit("energy.recorded",
           f"Energy {record.source}/{record.kind} "
           f"({record.project_ref or record.device_ref or 'unlinked'})",
           payload={"record_id": record.record_id,
                    "source": record.source, "kind": record.kind})


def _row_to_record(row) -> EnergyRecord:
    from .database import load
    try:
        prov = load(row["provenance"])
    except Exception:
        prov = {}
    if not isinstance(prov, dict):
        prov = {}
    return EnergyRecord(
        record_id=row["record_id"], source=row["source"] or "other",
        kind=row["kind"] or "state", value=row["value"],
        unit=row["unit"] or "",
        project_ref=row["project_ref"] or "",
        device_ref=row["device_ref"] or "",
        note=row["note"] or "",
        observed_at=row["observed_at"] or "",
        created_at=row["created_at"] or "", provenance=prov)


def get_record(record_id: str) -> EnergyRecord | None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    cleaned = str(record_id or "").strip()[:80]
    if not cleaned:
        return None
    with chat_connection() as db:
        _ensure(db)
        row = db.execute(
            "SELECT * FROM energy_records WHERE record_id=?",
            (cleaned,)).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_records(*, project_ref: str = "", device_ref: str = "",
                 source: str = "", kind: str = "",
                 limit: int = 100) -> list[EnergyRecord]:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    count = max(1, min(int(limit or 100), 200))
    clauses: list = []
    args: list = []
    if project_ref:
        clauses.append("project_ref=?")
        args.append(str(project_ref)[:120])
    if device_ref:
        clauses.append("device_ref=?")
        args.append(str(device_ref)[:120])
    if source:
        if str(source).strip().lower() not in ENERGY_SOURCES:
            raise EnergyRefusedError(
                f"Unknown energy source '{source}'")
        clauses.append("source=?")
        args.append(str(source).strip().lower())
    if kind:
        if str(kind).strip().lower() not in ENERGY_KINDS:
            raise EnergyRefusedError(f"Unknown energy kind '{kind}'")
        clauses.append("kind=?")
        args.append(str(kind).strip().lower())
    query = "SELECT * FROM energy_records"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY observed_at DESC LIMIT ?"
    args.append(count)
    with chat_connection() as db:
        _ensure(db)
        rows = db.execute(query, tuple(args)).fetchall()
    return [_row_to_record(row) for row in rows]


def current_state(*, project_ref: str = "",
                  device_ref: str = "") -> dict:
    """Latest state-kind rows (up to 5) + known/unknown counts.
    Never invents: empty refs give explicit empty."""
    records = list_records(project_ref=project_ref,
                           device_ref=device_ref, kind="state",
                           limit=5)
    states = []
    for record in records:
        states.append({
            "record_id": record.record_id,
            "source": record.source,
            "value": record.value if record.value is not None
            else "UNKNOWN",
            "unit": record.unit,
            "observed_at": record.observed_at,
        })
    return {"states": states,
            "state": "UNKNOWN" if not states else "KNOWN",
            "count": len(states)}


def summarize(*, project_ref: str = "") -> dict:
    records = list_records(project_ref=project_ref, limit=200)
    by_source: dict = {}
    unknown = 0
    for record in records:
        bucket = by_source.setdefault(
            record.source, {"count": 0, "kinds": {}})
        bucket["count"] += 1
        bucket["kinds"][record.kind] = \
            bucket["kinds"].get(record.kind, 0) + 1
        if record.value is None:
            unknown += 1
    return {"total": len(records), "by_source": by_source,
            "unknown_values": unknown}


def _audit(event_type: str, summary: str, *,
           payload: dict | None = None) -> None:
    try:
        from .events import new_event, save_event
        save_event(new_event(event_type, summary,
                             payload=payload or {}))
    except Exception:
        pass
