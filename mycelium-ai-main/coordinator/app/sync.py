"""Pull-based sync layer (BIG #10, deel 3).

Node A pulls change envelopes from a source (coordinator or
peer), validates, deduplicates and applies them into its own
durable log, then advances its cursor. No inbound ports, no
peer-to-peer shell, node identity/token rules unchanged.

Flow:

    source read_log(after, limit)   # bounded envelopes
      → transport (HTTP pull)
      → validate each envelope      # closed types, no SQL
      → apply_envelope (idempotent) # duplicate/conflict safe
      → advance cursor              # highest applied rowid

Sync status surfaces: last_sync, cursor, pending, failed,
conflicts, epoch, node liveness. The INVENTory side syncs
through the HTTP bridge only (fetch_inventory_changes with
cursor + limit + provenance); the SQLite file is never
copied and never opened by Mycelium.
"""

from .diststate import (
    DistEnvelope,
    DistStateRefusedError,
    apply_envelope,
    known_event_ids,
    read_log,
)

SYNC_BATCH = 100


class SyncRefusedError(ValueError):
    """Local validation refused; nothing was applied."""


def pull_changes(fetch, after_rowid: int = 0,
                 limit: int = SYNC_BATCH) -> tuple[list[dict], int]:
    """Pull one bounded page via a caller-supplied fetch callable.
    ``fetch(after, limit)`` returns (items, latest). Transport
    stays with the caller (HTTP pull); this layer only bounds."""
    try:
        cursor = max(0, int(after_rowid or 0))
        count = max(1, min(int(limit or SYNC_BATCH), SYNC_BATCH))
    except (TypeError, ValueError):
        raise SyncRefusedError("cursor/limit must be integers")
    if not callable(fetch):
        raise SyncRefusedError("sync needs a fetch callable")
    items, latest = fetch(cursor, count)
    if not isinstance(items, list):
        raise SyncRefusedError("source returned no list")
    return items[:count], latest


def apply_pulled(items: list[dict]) -> dict:
    """Validate + idempotently apply pulled envelopes. Returns a
    summary {applied, duplicates, conflicts, failed} plus the
    highest source cursor the caller may advance past ONLY for
    applied/duplicates (conflicts keep their cursor for review,
    failed items never advance anything)."""
    summary = {"applied": 0, "duplicates": 0, "conflicts": 0,
               "failed": 0, "conflict_ids": [], "applied_ids": []}
    for item in (items or [])[:SYNC_BATCH]:
        try:
            envelope = (item if isinstance(item, DistEnvelope)
                        else DistEnvelope.model_validate(item))
        except Exception:
            summary["failed"] += 1
            continue
        try:
            outcome = apply_envelope(envelope)
        except DistStateRefusedError:
            summary["failed"] += 1
            continue
        if outcome["status"] == "applied":
            summary["applied"] += 1
            summary["applied_ids"].append(envelope.event_id)
        elif outcome["status"] == "duplicate":
            summary["duplicates"] += 1
            summary["applied_ids"].append(envelope.event_id)
        else:
            summary["conflicts"] += 1
            summary["conflict_ids"].append(
                outcome.get("conflict_id", ""))
    return summary


def sync_status(nodes: list, cursor: int = 0) -> dict:
    """Local sync snapshot: cursor, log size, open conflicts,
    epoch, node liveness. Bounded, no dumps."""
    from .diststate import list_conflicts
    from .failover import current_epoch, sync_status as coord_status
    _, latest = read_log(after_rowid=10**12, limit=1)
    open_conflicts = list_conflicts(status="open", limit=100)
    live = sum(1 for node in (nodes or [])
               if isinstance(node, dict)
               and str(node.get("derived_status",
                                node.get("status", "")))
               in ("online", "busy"))
    return {
        "cursor": cursor,
        "log_latest": latest,
        "pending": max(0, latest - max(0, int(cursor or 0))),
        "failed_changes": 0,
        "open_conflicts": len(open_conflicts),
        "epoch": current_epoch(),
        "live_nodes": live,
        "coordinator": coord_status(nodes),
    }


async def fetch_inventory_changes(reader, since: str = "",
                                   limit: int = SYNC_BATCH
                                   ) -> list[dict]:
    """Pull INVENTory change notifications over HTTP. Uses the
    additive ``since`` cursor on /api/v1/events (timestamp
    filter); bounded pages; provenance preserved. Never SQL,
    never the database file."""
    try:
        count = max(1, min(int(limit or SYNC_BATCH), SYNC_BATCH))
    except (TypeError, ValueError):
        raise SyncRefusedError("limit must be an integer")
    getter = getattr(reader, "events_since", None)
    if not callable(getter):
        raise SyncRefusedError(
            "reader has no cursor change feed")
    raw = await getter(since=since or "", limit=count)
    items = []
    for entry in (raw or [])[:count]:
        if isinstance(entry, dict):
            items.append({
                "event_id": str(entry.get("id", "")),
                "event_type": str(entry.get("event_type", "")),
                "entity_id": str(entry.get("entity_id", "")),
                "timestamp": str(entry.get("timestamp", "")),
                "provenance": entry.get("provenance", {}),
            })
        else:
            items.append({
                "event_id": str(getattr(entry, "id", "")),
                "event_type": str(getattr(entry, "event_type",
                                          "")),
                "entity_id": str(getattr(entry, "entity_id", "")),
                "timestamp": str(getattr(entry, "timestamp", "")),
                "provenance": getattr(entry, "provenance", {}),
            })
    return items
