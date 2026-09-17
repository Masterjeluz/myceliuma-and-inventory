"""Notification center (BIG #30): one abstraction, honest transports.

Types (closed):
  research_completed, mission_waiting, approval_required, node_offline,
  task_completed, research_finding, system_attention

Transports:
  IN_APP — REAL (polling via existing notifications store; the /mobile
    and /activity pages read it; reading never approves anything).
  WEB_PUSH — UNAVAILABLE (no push service configured; explicit status,
    no credentials stored, no fake delivery claims).

Mobile clients poll GET /api/v1/notifications/* or the capability
endpoint below. No secrets ever touch the database.
"""

from __future__ import annotations

NOTIFICATION_TYPES = frozenset({
    "research_completed",
    "mission_waiting",
    "approval_required",
    "node_offline",
    "task_completed",
    "research_finding",
    "system_attention",
})

IN_APP_TRANSPORT = "IN_APP"
WEB_PUSH_TRANSPORT = "WEB_PUSH"

_SEVERITY_MAP = {
    "research_completed": "completed",
    "mission_waiting": "approval_required",
    "approval_required": "approval_required",
    "node_offline": "node_status",
    "task_completed": "completed",
    "research_finding": "info",
    "system_attention": "warning",
}

_UI_SEVERITY_MAP = {
    "completed": "info",
    "approval_required": "urgent",
    "node_status": "info",
    "failed": "urgent",
    "warning": "warning",
    "info": "info",
}


class NotifyRefusedError(ValueError):
    """Notification refused; nothing was stored."""


def capability() -> dict:
    """Honest transport capability for UI + mobile."""
    return {
        "transports": {
            IN_APP_TRANSPORT: {
                "state": "AVAILABLE",
                "how": "polling; in-app pages (/activity, /mobile) "
                       "and GET /api/v1/notifications/*",
            },
            WEB_PUSH_TRANSPORT: {
                "state": "UNAVAILABLE",
                "how": "no push service configured; native push is a "
                       "future adapter, never promised here",
            },
        },
        "types": sorted(NOTIFICATION_TYPES),
        "note": "Reading a notification performs nothing. Approvals "
                "still run through the existing approval mechanism.",
    }


def check_type(kind: str) -> str:
    cleaned = str(kind or "").strip()[:40]
    if cleaned not in NOTIFICATION_TYPES:
        raise NotifyRefusedError(
            f"Unknown notification type '{kind}'; expected one of "
            f"{sorted(NOTIFICATION_TYPES)}")
    return cleaned


def send(recipient_node_id: str, kind: str, title: str, body: str = "",
         *, related_entity: str = "", related_mission: str = "",
         related_task: str = "") -> dict:
    """Store an IN_APP notification. Returns transport receipt."""
    from .events import new_notification, save_notification
    kind = check_type(kind)
    note = new_notification(
        recipient_node_id, _SEVERITY_MAP[kind], title, body,
        severity=_UI_SEVERITY_MAP[_SEVERITY_MAP[kind]],
        related_entity=related_entity,
        related_mission=related_mission,
        related_task=related_task)
    save_notification(note)
    return {"notification_id": note.notification_id,
            "transport": IN_APP_TRANSPORT, "state": "DELIVERED_IN_APP",
            "web_push": "UNAVAILABLE"}
