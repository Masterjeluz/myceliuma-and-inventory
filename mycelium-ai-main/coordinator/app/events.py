"""Coordinator event bus + notifications (BIG #9).

Lightweight, structured, pollable — no broker, no Redis, no
cloud. Events are attributable facts about what happened
("approval required", "task completed"); an event is NEVER a
command and can NEVER authorize anything.

- InterfaceEvent: closed types, bounded payload, timestamp,
  related entity/mission/task/proposal ids. Stored in the chat
  DB (conversations live there too); bounded retention per
  query, cursor replay (after=<event_id>).
- Notification: informational recipient-bound records
  (approval_required, completed, failed, ...). Reading a
  notification performs nothing; approvals still run through
  the existing approval mechanism.

Rules (tested):

- types and severities are closed; unknown fields refused;
  payloads are small capped dicts, never executable content
  (no shell/command/code/exec keys, no URLs for control).
- notifications reference entities; they never carry
  approval decisions and never execute tasks.
- no unbounded in-memory history: queries are LIMIT-capped;
  retention prunes per conversation.
"""

import secrets
import time
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

VALID_EVENT_TYPES = frozenset({
    "conversation.message",
    "mission.started",
    "mission.updated",
    "mission.completed",
    "mission.failed",
    "task.queued",
    "task.assigned",
    "task.running",
    "task.completed",
    "task.failed",
    "observation.created",
    "approval.required",
    "approval.resolved",
    "node.online",
    "node.stale",
    "node.offline",
    "interface.session",
    "voice.transcribed",
    "print.started",
    "print.completed",
    "integration.received",
    "integration.accepted",
    "integration.duplicate",
    "integration.conflict",
    "integration.rejected",
    "candidate.observed",
    "candidate.supported",
    "candidate.promoted",
    "candidate.rejected",
    "automation.started",
    "automation.progress",
    "automation.waiting",
    "automation.completed",
    "automation.failed",
    "research.queued",
    "research.routed",
    "research.fetched",
    "relation.proposed",
})

VALID_SEVERITIES = frozenset({"info", "approval_required",
                              "completed", "failed", "warning",
                              "node_status"})

MAX_PAYLOAD_KEYS = 20
MAX_PAYLOAD_VALUE_CHARS = 500
POLL_LIMIT = 100
EVENT_RETENTION = 500


class EventRefusedError(ValueError):
    """Local validation refused; nothing was stored."""


class InterfaceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=3, max_length=80)
    event_type: str = Field(min_length=1, max_length=40)
    conversation_id: str = Field(default="", max_length=80)
    mission_id: str = Field(default="", max_length=80)
    task_id: str = Field(default="", max_length=80)
    proposal_id: str = Field(default="", max_length=80)
    node_id: str = Field(default="", max_length=80)
    summary: str = Field(default="", max_length=500)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class Notification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notification_id: str = Field(min_length=3, max_length=80)
    recipient_node_id: str = Field(min_length=1, max_length=80)
    type: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=1000)
    severity: str = Field(default="info", max_length=20)
    related_entity: str = Field(default="", max_length=100)
    related_mission: str = Field(default="", max_length=80)
    related_task: str = Field(default="", max_length=80)
    created_at: str = ""
    expires_at: str = ""
    read: bool = False


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_event_id() -> str:
    return f"evt-{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def generate_notification_id() -> str:
    return f"ntf-{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def _check_payload(payload) -> dict:
    """Bus-event payloads: shared security rules, tighter
    bus limits. Raises EventRefusedError (callers unchanged)."""
    from .payloads import check_payload
    return check_payload(payload, max_keys=MAX_PAYLOAD_KEYS,
                         max_value_chars=MAX_PAYLOAD_VALUE_CHARS,
                         error=EventRefusedError)


def new_event(event_type: str, summary: str = "", *,
              conversation_id: str = "",
              mission_id: str = "", task_id: str = "",
              proposal_id: str = "", node_id: str = "",
              payload: dict | None = None) -> InterfaceEvent:
    """Build one validated event. Fail-closed on type/payload."""
    if event_type not in VALID_EVENT_TYPES:
        raise EventRefusedError(
            f"Unknown event type '{event_type}'")
    return InterfaceEvent(
        event_id=generate_event_id(), event_type=event_type,
        conversation_id=conversation_id[:80],
        mission_id=mission_id[:80],
        task_id=str(task_id or "")[:80],
        proposal_id=proposal_id[:80], node_id=node_id[:80],
        summary=str(summary or "")[:500],
        payload=_check_payload(payload), created_at=now())


def new_notification(recipient_node_id: str, type: str,
                     title: str, body: str = "", *,
                     severity: str = "info",
                     related_entity: str = "",
                     related_mission: str = "",
                     related_task: str = "",
                     ttl_seconds: int = 7 * 24 * 3600
                     ) -> Notification:
    """Build one informational notification. Reading it performs
    nothing; approvals still need the approval mechanism."""
    from .nodes import check_node_id
    try:
        recipient = check_node_id(recipient_node_id)
    except ValueError as error:
        raise EventRefusedError(str(error)) from error
    if type not in VALID_SEVERITIES:
        raise EventRefusedError(
            f"Unknown notification type '{type}'; expected one of "
            f"{sorted(VALID_SEVERITIES)}")
    if severity not in ("info", "warning", "urgent"):
        raise EventRefusedError(f"Unknown severity '{severity}'")
    if not isinstance(title, str) or not title.strip():
        raise EventRefusedError("Notification needs a title")
    try:
        ttl = int(ttl_seconds)
    except (TypeError, ValueError):
        raise EventRefusedError("ttl must be an integer")
    if ttl <= 0 or ttl > 30 * 24 * 3600:
        raise EventRefusedError("ttl must be 1..30 days")
    from datetime import timedelta
    created = datetime.now(timezone.utc)
    return Notification(
        notification_id=generate_notification_id(),
        recipient_node_id=recipient, type=type,
        title=title.strip()[:200], body=str(body or "")[:1000],
        severity=severity,
        related_entity=str(related_entity or "")[:100],
        related_mission=str(related_mission or "")[:80],
        related_task=str(related_task or "")[:80],
        created_at=created.isoformat(),
        expires_at=(created + timedelta(seconds=ttl)).isoformat())


# -- store (chat DB; queue DB untouched, INVENTory untouched) ------------

def save_event(event: InterfaceEvent) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO interface_events
        (event_id, event_type, conversation_id, mission_id,
         task_id, proposal_id, node_id, summary, payload,
         created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (event.event_id, event.event_type,
                     event.conversation_id, event.mission_id,
                     event.task_id, event.proposal_id,
                     event.node_id, event.summary,
                     dump(event.payload), event.created_at))


def list_events(limit: int = 50, after: str = "",
                event_type: str = "") -> list[InterfaceEvent]:
    """Bounded poll with cursor replay. after=<event_id> returns
    newer rows only (rowid order)."""
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    count = max(1, min(int(limit or 50), POLL_LIMIT))
    with chat_connection() as db:
        after_rowid = 0
        if after:
            found = db.execute(
                "SELECT rowid FROM interface_events WHERE "
                "event_id=?", (after,)).fetchone()
            if found is not None:
                after_rowid = found["rowid"]
        query = ("SELECT * FROM interface_events WHERE rowid>?")
        params: list = [after_rowid]
        if event_type:
            if event_type not in VALID_EVENT_TYPES:
                raise EventRefusedError(
                    f"Unknown event type '{event_type}'")
            query += " AND event_type=?"
            params.append(event_type)
        query += " ORDER BY rowid ASC LIMIT ?"
        params.append(count)
        rows = db.execute(query, params).fetchall()
    return [InterfaceEvent(
        event_id=row["event_id"], event_type=row["event_type"],
        conversation_id=row["conversation_id"],
        mission_id=row["mission_id"], task_id=row["task_id"],
        proposal_id=row["proposal_id"], node_id=row["node_id"],
        summary=row["summary"],
        payload=load(row["payload"]) if row["payload"] else {},
        created_at=row["created_at"]) for row in rows]


def save_notification(notification: Notification) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO notifications
        (notification_id, recipient_node_id, type, title, body,
         severity, related_entity, related_mission, related_task,
         created_at, expires_at, read) VALUES
        (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                    (notification.notification_id,
                     notification.recipient_node_id,
                     notification.type, notification.title,
                     notification.body, notification.severity,
                     notification.related_entity,
                     notification.related_mission,
                     notification.related_task,
                     notification.created_at,
                     notification.expires_at))


def list_notifications(recipient_node_id: str,
                       limit: int = 50,
                       unread_only: bool = False
                       ) -> list[Notification]:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    count = max(1, min(int(limit or 50), POLL_LIMIT))
    with chat_connection() as db:
        query = ("SELECT * FROM notifications WHERE "
                 "recipient_node_id=?")
        params: list = [recipient_node_id]
        if unread_only:
            query += " AND read=0"
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(count)
        rows = db.execute(query, params).fetchall()
    return [Notification(**{**dict(row),
                            "read": bool(row["read"])})
            for row in rows]


def mark_notification_read(notification_id: str,
                           recipient_node_id: str) -> bool:
    """Mark one notification read (scoped to its recipient).
    Informational bookkeeping only."""
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        changed = db.execute(
            "UPDATE notifications SET read=1 WHERE "
            "notification_id=? AND recipient_node_id=?",
            (notification_id, recipient_node_id)).rowcount
    return changed == 1


def prune_events(keep: int = EVENT_RETENTION) -> int:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute(
            "SELECT COUNT(*) AS n FROM interface_events").fetchone()
        excess = max(0, row["n"] - keep)
        if excess:
            db.execute(
                "DELETE FROM interface_events WHERE rowid IN "
                "(SELECT rowid FROM interface_events ORDER BY "
                "rowid ASC LIMIT ?)", (excess,))
    return excess
