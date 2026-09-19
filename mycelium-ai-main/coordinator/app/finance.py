"""Finance ecosystem foundation (BIG #42).

Minimal, first-class finance records. This is NOT accounting
software: just enough to make money a real ecosystem entity that
projects, missions, symbiosis, guide and the morning report can
reference honestly.

- No fake records: rows are only created through the explicit API
  with operator-supplied figures. Unknown amounts stay NULL and
  render as UNKNOWN — never zero, never invented.
- Kinds (closed): income | expense | budget.
- Status (closed): DRAFT | CONFIRMED | ARCHIVED.
- Privacy: amounts live ONLY in this store + its dedicated
  endpoints. Generic packets carry counts; amounts are included
  only when the packet's project_id matches the record's
  project_ref. Telemetry never carries finance data.

Storage: chat DB table finance_records (additive, idempotent).
"""

from __future__ import annotations

import re as _re
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

FINANCE_KINDS = ("income", "expense", "budget")
FINANCE_STATUSES = ("DRAFT", "CONFIRMED", "ARCHIVED")

_CURRENCY_RE = _re.compile(r"^[A-Z]{3}$")


class FinanceRefusedError(ValueError):
    """Local validation refused; nothing was stored."""


class FinanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=4, max_length=80)
    kind: str = Field(min_length=1, max_length=16)
    title: str = Field(min_length=1, max_length=200)
    amount_minor: int | None = None
    currency: str = Field(default="EUR", max_length=3)
    project_ref: str = Field(default="", max_length=120)
    status: str = Field(default="DRAFT", max_length=16)
    note: str = Field(default="", max_length=1000)
    created_at: str = ""
    updated_at: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_record_id() -> str:
    return f"fin_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def init_finance_tables(db) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS finance_records (
            record_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            amount_minor INTEGER DEFAULT NULL,
            currency TEXT NOT NULL DEFAULT 'EUR',
            project_ref TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'DRAFT',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            provenance TEXT NOT NULL DEFAULT '{}'
        );
        """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_finance_project
            ON finance_records(project_ref, status);
        """)


def _ensure(db) -> None:
    init_finance_tables(db)


def new_record(*, kind: str, title: str,
               amount_minor: int | None = None,
               currency: str = "EUR", project_ref: str = "",
               note: str = "", recorded_by: str = "operator",
               provenance: dict | None = None) -> FinanceRecord:
    cleaned_kind = str(kind or "").strip().lower()[:16]
    if cleaned_kind not in FINANCE_KINDS:
        raise FinanceRefusedError(
            f"Unknown finance kind '{kind}'; expected one of "
            f"{list(FINANCE_KINDS)}")
    cleaned_title = str(title or "").strip()
    if not cleaned_title:
        raise FinanceRefusedError("Finance record needs a title")
    if len(cleaned_title) > 200:
        raise FinanceRefusedError("Finance title is too long")
    amount = None
    if amount_minor is not None:
        try:
            amount = int(amount_minor)
        except (TypeError, ValueError) as error:
            raise FinanceRefusedError(
                "amount_minor must be an integer or omitted") from error
        if amount < 0:
            raise FinanceRefusedError("amount_minor cannot be negative")
        if amount > 10**15:
            raise FinanceRefusedError("amount_minor is unrealistically large")
    cur = str(currency or "EUR").strip().upper()[:3]
    if not _CURRENCY_RE.match(cur):
        raise FinanceRefusedError(
            "currency must be a 3-letter code (e.g. EUR)")
    project = str(project_ref or "").strip()[:120]
    stamp = now()
    actor = str(recorded_by or "operator").strip()[:120] or "operator"
    prov = dict(provenance) if isinstance(provenance, dict) else {}
    prov.update({"source_type": "human-recorded",
                 "creator_id": actor, "human_verified": False})
    return FinanceRecord(
        record_id=generate_record_id(), kind=cleaned_kind,
        title=cleaned_title[:200], amount_minor=amount,
        currency=cur, project_ref=project, status="DRAFT",
        note=str(note or "").strip()[:1000],
        created_at=stamp, updated_at=stamp, provenance=prov)


def save_record(record: FinanceRecord) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        _ensure(db)
        db.execute(
            """INSERT INTO finance_records
            (record_id, kind, title, amount_minor, currency,
             project_ref, status, note, created_at, updated_at,
             provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_id) DO UPDATE SET
             title=excluded.title, amount_minor=excluded.amount_minor,
             currency=excluded.currency,
             project_ref=excluded.project_ref, status=excluded.status,
             note=excluded.note, updated_at=excluded.updated_at,
             provenance=excluded.provenance""",
            (record.record_id, record.kind, record.title,
             record.amount_minor, record.currency, record.project_ref,
             record.status, record.note, record.created_at,
             record.updated_at, dump(record.provenance)))
    _audit("finance.recorded",
           f"Finance {record.kind} '{record.title}' "
           f"[{record.status}]",
           payload={"record_id": record.record_id,
                    "kind": record.kind})


def _row_to_record(row) -> FinanceRecord:
    from .database import load
    try:
        prov = load(row["provenance"])
    except Exception:
        prov = {}
    if not isinstance(prov, dict):
        prov = {}
    return FinanceRecord(
        record_id=row["record_id"], kind=row["kind"] or "expense",
        title=row["title"] or "", amount_minor=row["amount_minor"],
        currency=row["currency"] or "EUR",
        project_ref=row["project_ref"] or "",
        status=row["status"] or "DRAFT", note=row["note"] or "",
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "", provenance=prov)


def get_record(record_id: str) -> FinanceRecord | None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    cleaned = str(record_id or "").strip()[:80]
    if not cleaned:
        return None
    with chat_connection() as db:
        _ensure(db)
        row = db.execute(
            "SELECT * FROM finance_records WHERE record_id=?",
            (cleaned,)).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_records(*, project_ref: str = "", kind: str = "",
                 status: str = "", limit: int = 100) -> list[FinanceRecord]:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    count = max(1, min(int(limit or 100), 200))
    clauses: list = []
    args: list = []
    if project_ref:
        clauses.append("project_ref=?")
        args.append(str(project_ref)[:120])
    if kind:
        if str(kind).strip().lower() not in FINANCE_KINDS:
            raise FinanceRefusedError(f"Unknown finance kind '{kind}'")
        clauses.append("kind=?")
        args.append(str(kind).strip().lower())
    if status:
        if str(status).strip().upper() not in FINANCE_STATUSES:
            raise FinanceRefusedError(
                f"Unknown finance status '{status}'")
        clauses.append("status=?")
        args.append(str(status).strip().upper())
    query = "SELECT * FROM finance_records"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY updated_at DESC LIMIT ?"
    args.append(count)
    with chat_connection() as db:
        _ensure(db)
        rows = db.execute(query, tuple(args)).fetchall()
    return [_row_to_record(row) for row in rows]


def set_status(record_id: str, status: str) -> FinanceRecord | None:
    cleaned = str(status or "").strip().upper()[:16]
    if cleaned not in FINANCE_STATUSES:
        raise FinanceRefusedError(
            f"Unknown finance status '{status}'")
    record = get_record(record_id)
    if record is None:
        return None
    record.status = cleaned
    record.updated_at = now()
    save_record(record)
    return record


def summarize(*, project_ref: str = "") -> dict:
    """Counts + per-kind totals for CONFIRMED rows with known amounts.
    Unknown amounts are counted, never summed."""
    records = list_records(project_ref=project_ref, limit=200)
    out: dict = {"total": len(records), "by_kind": {},
                 "unknown_amounts": 0}
    for record in records:
        bucket = out["by_kind"].setdefault(
            record.kind, {"count": 0, "known_minor": 0,
                          "known_count": 0})
        bucket["count"] += 1
        if record.amount_minor is None:
            out["unknown_amounts"] += 1
        elif record.status == "CONFIRMED":
            bucket["known_minor"] += int(record.amount_minor)
            bucket["known_count"] += 1
    return out


def _audit(event_type: str, summary: str, *,
           payload: dict | None = None) -> None:
    try:
        from .events import new_event, save_event
        save_event(new_event(event_type, summary,
                             payload=payload or {}))
    except Exception:
        pass
