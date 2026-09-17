"""Local-first agenda importer (BIG #28 §15).

Generic ICS import with preview-before-import, UID-based
duplicate detection, and explicit source provenance. No Google
Calendar required; URL feeds only when explicitly configured
(and only loopback-safe fetching through the existing bridge
policy — remote ICS fetch is NOT implemented; paste or upload
the .ics text instead).

Model: ``agenda_sources`` (one row per import: label, origin,
imported_at) and ``agenda_events`` (uid, source, title,
start/end, location, description, recurrence, provenance).

Rules:

- Imported events are read-only world/context data. Editing
  goes through no write path at all in V1 (there is none).
- No invented events: every row comes from a parsed VEVENT
  with a UID (generated deterministically from content when
  the file omits one, labelled as derived).
- Duplicate = same UID within the same source; re-imports
  update the row instead of duplicating it.
- Parser is stdlib-only, bounded (MAX_EVENTS, MAX_CHARS),
  and refuses malformed input instead of guessing.
"""

import hashlib
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

MAX_ICS_CHARS = 500_000
MAX_EVENTS = 500
MAX_FIELD_CHARS = 2000


class AgendaRefusedError(ValueError):
    """Agenda input refused; nothing stored."""


@dataclass(frozen=True)
class AgendaEvent:
    event_id: str = ""
    uid: str = ""
    title: str = ""
    start: str = ""
    end: str = ""
    location: str = ""
    description: str = ""
    recurrence: str = ""
    source_label: str = ""
    provenance_note: str = ""


@dataclass
class AgendaPreview:
    source_label: str = ""
    events: list = field(default_factory=list)
    duplicates: int = 0
    refused: str = ""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_ics(text: str, *, source_label: str = "import") -> AgendaPreview:
    """Parse .ics text into a preview. Pure function, no storage."""
    if not isinstance(text, str) or not text.strip():
        raise AgendaRefusedError("ICS import needs non-empty .ics text")
    if len(text) > MAX_ICS_CHARS:
        raise AgendaRefusedError(
            f"ICS text too large ({len(text)} chars, "
            f"max {MAX_ICS_CHARS})")
    unfolded = _unfold(text)
    if "BEGIN:VCALENDAR" not in unfolded:
        raise AgendaRefusedError(
            "Not an ICS calendar (missing BEGIN:VCALENDAR)")
    blocks = re.findall(
        r"BEGIN:VEVENT(.*?)END:VEVENT", unfolded,
        flags=re.DOTALL | re.IGNORECASE)
    if not blocks:
        raise AgendaRefusedError("No VEVENT entries found")
    if len(blocks) > MAX_EVENTS:
        raise AgendaRefusedError(
            f"Too many events ({len(blocks)}, max {MAX_EVENTS})")
    label = (source_label or "import").strip()[:120] or "import"
    events: list[AgendaEvent] = []
    for block in blocks:
        props = _properties(block)
        uid = props.get("UID", "").strip()[:300]
        title = _clean(props.get("SUMMARY", ""))[:200] or "(no title)"
        start = _clean(props.get("DTSTART", ""))[:64]
        end = _clean(props.get("DTEND", ""))[:64]
        if not uid:
            derived = hashlib.sha256(
                f"{title}|{start}|{end}".encode(
                    "utf-8", "replace")).hexdigest()[:16]
            uid = f"derived-{derived}"
        events.append(AgendaEvent(
            event_id=f"evt_{secrets.token_hex(4)}",
            uid=uid, title=title, start=start, end=end,
            location=_clean(props.get("LOCATION", ""))[:300],
            description=_clean(props.get("DESCRIPTION", ""))[:2000],
            recurrence=_clean(props.get("RRULE", ""))[:300],
            source_label=label,
            provenance_note=(
                "ics-import; read-only context, never a commitment "
                "fact" + ("; uid derived from content"
                          if uid.startswith("derived-") else ""))))
    return AgendaPreview(source_label=label, events=events)


def _unfold(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    merged: list[str] = []
    for line in lines:
        if line[:1] in (" ", "\t") and merged:
            merged[-1] += line[1:]
        else:
            merged.append(line)
    return "\n".join(merged)


def _properties(block: str) -> dict:
    props: dict[str, str] = {}
    for line in block.split("\n"):
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        name = name.split(";")[0].strip().upper()
        if name and name not in props:
            props[name] = value.strip().replace("\\n", "\n").replace(
                "\\,", ",").replace("\\;", ";")[:MAX_FIELD_CHARS]
    return props


def _clean(value: str) -> str:
    return " ".join(str(value or "").split())


# -- storage (chat/agent database; additive tables, same discipline) --

def init_agenda_tables(db) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS agenda_sources (
            source_id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            origin TEXT NOT NULL DEFAULT 'ics-import',
            event_count INTEGER NOT NULL DEFAULT 0,
            imported_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agenda_events (
            event_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            uid TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            start TEXT NOT NULL DEFAULT '',
            end_time TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            recurrence TEXT NOT NULL DEFAULT '',
            provenance TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(source_id, uid)
        );
        CREATE INDEX IF NOT EXISTS idx_agenda_start
            ON agenda_events(start);
        """)


def store_preview(db, preview: AgendaPreview,
                  *, origin: str = "ics-import") -> dict:
    """Store a previewed import with UID dedup. Re-importing the
    same label reuses the source row, so same-UID events update
    instead of duplicating. Returns counts."""
    if not preview.events:
        raise AgendaRefusedError("Nothing to import")
    existing_source = db.execute(
        "SELECT source_id FROM agenda_sources WHERE label=? "
        "ORDER BY imported_at DESC LIMIT 1",
        (preview.source_label,)).fetchone()
    if existing_source is None:
        source_id = f"agsrc_{secrets.token_hex(4)}"
        db.execute(
            "INSERT INTO agenda_sources (source_id, label, origin, "
            "event_count, imported_at) VALUES (?, ?, ?, ?, ?)",
            (source_id, preview.source_label, origin[:80],
             len(preview.events), now()))
    else:
        source_id = existing_source["source_id"]
    inserted = 0
    updated = 0
    for event in preview.events:
        existing = db.execute(
            "SELECT event_id FROM agenda_events WHERE source_id=? "
            "AND uid=?", (source_id, event.uid)).fetchone()
        if existing is None:
            db.execute(
                """INSERT INTO agenda_events (event_id, source_id,
                uid, title, start, end_time, location, description,
                recurrence, provenance, created_at) VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event.event_id, source_id, event.uid,
                 event.title, event.start, event.end,
                 event.location, event.description,
                 event.recurrence, event.provenance_note, now()))
            inserted += 1
        else:
            db.execute(
                """UPDATE agenda_events SET title=?, start=?,
                end_time=?, location=?, description=?,
                recurrence=? WHERE event_id=?""",
                (event.title, event.start, event.end,
                 event.location, event.description,
                 event.recurrence, existing["event_id"]))
            updated += 1
    db.execute(
        "UPDATE agenda_sources SET event_count=?, imported_at=? "
        "WHERE source_id=?",
        (inserted + updated, now(), source_id))
    return {"source_id": source_id, "inserted": inserted,
            "updated": updated, "total": len(preview.events)}


def list_events(db, *, limit: int = 100,
                upcoming_only: bool = False) -> list[dict]:
    """List stored agenda events. Read-only context, never facts."""
    rows = db.execute(
        "SELECT * FROM agenda_events ORDER BY start ASC LIMIT ?",
        (max(1, min(int(limit or 100), 500)),)).fetchall()
    events = [dict(row) for row in rows]
    if upcoming_only:
        today = time.strftime("%Y%m%d")
        events = [row for row in events
                  if str(row.get("start", "")) >= today]
    return events


def list_sources(db) -> list[dict]:
    return [dict(row) for row in db.execute(
        "SELECT * FROM agenda_sources ORDER BY imported_at DESC"
        " LIMIT 50").fetchall()]
