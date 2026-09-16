"""Digital twin foundation (BIG #11-15, Phase 5).

physical entity ↔ digital entity ↔ observations ↔ sensors
↔ files ↔ events. Links are explicit records with source,
confidence and last-observed time — the digital side never
claims to be automatically current. Staleness is computed,
not assumed.

Structure (HOME → rooms/workshop/garden/…) is expressed
through INVENTory locations + relationships; this module
only links and scores freshness.
"""

import secrets
import time

from pydantic import BaseModel, Field

from .inventory_read import Provenance

TWIN_LINK_TYPES = (
    "represents",
    "observes",
    "controls",
    "stored_at",
    "part_of",
)

TWIN_STATUSES = ("active", "stale", "retired")


class TwinRefusedError(ValueError):
    """Fail-closed twin validation."""


def now() -> str:
    import datetime
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def generate_link_id() -> str:
    return f"twn_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


class TwinLink(BaseModel):
    link_id: str = Field(min_length=3, max_length=80)
    physical_ref: str = Field(min_length=1, max_length=200)
    digital_ref: str = Field(min_length=1, max_length=120)
    link_type: str = Field(min_length=1, max_length=20)
    source: str = Field(default="", max_length=200)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    last_observed_at: str = Field(default="", max_length=80)
    status: str = Field(default="active", max_length=20)
    provenance: Provenance
    updated_at: str = Field(default="", max_length=80)


def new_link(physical_ref: str, digital_ref: str,
             link_type: str, *, source: str = "",
             confidence: float = 0.5,
             last_observed_at: str = "",
             provenance: Provenance | None = None) -> TwinLink:
    if not isinstance(physical_ref, str) or not \
            physical_ref.strip():
        raise TwinRefusedError("link needs a physical ref")
    if not isinstance(digital_ref, str) or not \
            digital_ref.strip():
        raise TwinRefusedError("link needs a digital ref")
    if link_type not in TWIN_LINK_TYPES:
        raise TwinRefusedError(
            f"Unknown link type '{link_type}'")
    stamp = now()
    return TwinLink(
        link_id=generate_link_id(),
        physical_ref=physical_ref.strip()[:200],
        digital_ref=digital_ref.strip()[:120],
        link_type=link_type, source=str(source or "")[:200],
        confidence=float(confidence),
        last_observed_at=last_observed_at or stamp,
        status="active",
        provenance=provenance or Provenance(
            source_type="sensor-observed",
            creator_id="digital-twin", human_verified=False),
        updated_at=stamp)


def _row_to_link(row) -> TwinLink:
    from .database import load
    return TwinLink(
        link_id=row["link_id"],
        physical_ref=row["physical_ref"],
        digital_ref=row["digital_ref"],
        link_type=row["link_type"], source=row["source"],
        confidence=row["confidence"],
        last_observed_at=row["last_observed_at"],
        status=row["status"],
        provenance=Provenance(**load(row["provenance"])),
        updated_at=row["updated_at"])


def save_link(link: TwinLink,
              expected_updated_at: str | None = None) -> None:
    """Persist a twin link. With expected_updated_at set, a
    moved row refuses (optimistic concurrency for future
    callers); routes keep working unchanged."""
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    if expected_updated_at is not None:
        with chat_connection() as db:
            row = db.execute(
                "SELECT updated_at FROM twin_links WHERE "
                "link_id=?", (link.link_id,)).fetchone()
            if row is None or row["updated_at"] != \
                    expected_updated_at:
                raise TwinRefusedError(
                    "twin link moved; reload and retry "
                    "explicitly")
    with chat_connection() as db:
        db.execute("""INSERT INTO twin_links
        (link_id, physical_ref, digital_ref, link_type,
         source, confidence, last_observed_at, status,
         provenance, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(link_id) DO UPDATE SET
         confidence=excluded.confidence,
         last_observed_at=excluded.last_observed_at,
         status=excluded.status,
         updated_at=excluded.updated_at""",
                     (link.link_id, link.physical_ref,
                      link.digital_ref, link.link_type,
                      link.source, link.confidence,
                      link.last_observed_at, link.status,
                      dump(link.provenance.model_dump(
                          mode="json")), link.updated_at))


def list_links(*, status: str = "") -> list[TwinLink]:
    from .database import chat_connection, init_chat_database
    if status and status not in TWIN_STATUSES:
        raise TwinRefusedError(f"Unknown status '{status}'")
    init_chat_database()
    with chat_connection() as db:
        if status:
            rows = db.execute("SELECT * FROM twin_links WHERE "
                              "status=? ORDER BY updated_at DESC "
                              "LIMIT 200",
                              (status,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM twin_links ORDER "
                              "BY updated_at DESC LIMIT 200"
                              ).fetchall()
    return [_row_to_link(row) for row in rows]


def observe_link(link_id: str, *, source: str = "",
                 confidence: float = 0.5) -> TwinLink | None:
    """Refresh one link's observation stamp. Observation only:
    no state is claimed beyond 'seen now'."""
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM twin_links WHERE "
                         "link_id=?", (link_id,)).fetchone()
        if row is None:
            return None
        link = _row_to_link(row)
        updated = link.model_copy(update={
            "last_observed_at": now(), "status": "active",
            "confidence": max(0.0, min(1.0,
                                       float(confidence))),
            "source": str(source or link.source)[:200],
            "updated_at": now()})
        db.execute("UPDATE twin_links SET last_observed_at=?, "
                   "status='active', confidence=?, source=?, "
                   "updated_at=? WHERE link_id=?",
                   (updated.last_observed_at,
                    updated.confidence, updated.source,
                    updated.updated_at, link_id))
    return updated


def staleness_report(*, stale_hours: float = 24.0) -> dict:
    """Fresh/stale/unknown per link with the method shown.
    Stale links flip to status stale (observation hygiene,
    not a content change)."""
    import datetime
    current = datetime.datetime.now(datetime.timezone.utc)
    try:
        bound = float(stale_hours)
    except (TypeError, ValueError):
        raise TwinRefusedError("stale_hours must be numeric")
    fresh, stale, unknown = [], [], []
    for link in list_links():
        try:
            moment = datetime.datetime.fromisoformat(
                link.last_observed_at)
            if moment.tzinfo is None:
                moment = moment.replace(
                    tzinfo=datetime.timezone.utc)
            age_hours = (current - moment).total_seconds() / 3600.0
        except (ValueError, TypeError):
            unknown.append(link.link_id)
            continue
        if age_hours > bound:
            stale.append({"link_id": link.link_id,
                          "age_hours": round(age_hours, 1),
                          "physical_ref": link.physical_ref,
                          "digital_ref": link.digital_ref})
        else:
            fresh.append(link.link_id)
    if stale:
        from .database import chat_connection, init_chat_database
        init_chat_database()
        with chat_connection() as db:
            for entry in stale:
                db.execute("UPDATE twin_links SET status="
                           "'stale' WHERE link_id=?",
                           (entry["link_id"],))
    return {"fresh": fresh, "stale": stale, "unknown": unknown,
            "method": f"last_observed_at older than "
                      f"{bound}h counts as stale",
            "warning": "fresh means recently observed, never "
                       "automatically current"}
