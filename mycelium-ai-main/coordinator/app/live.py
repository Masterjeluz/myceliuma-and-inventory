"""Mycelium Live: capability-scoped interface sessions (BIG #10).

Live is not a second coordinator and not a second chatbot. It
is a thin, capability-scoped session over the existing
services: a Live session selects context, proposes through
the existing proposal flows, and reads results — always
through the same FACT → … → VERIFICATION chain.

Session model:

- session_id (``live-``), interface, actor identity,
  capabilities (closed set below, least privilege),
  context scope, created/expires timestamps, active flag,
  audit/event references.

Capability model (closed; unknown refuses):

- read: inventory.read, graph.read, project.read, task.read,
  mission.read, camera.read, node.read, git.read, git.diff
- propose: inventory.propose_write, research.propose,
  project.propose_change, desktop.propose_input,
  3d.propose_transform, task.propose, mission.propose,
  git.commit
- git.push exists as a NAMESPACED capability but is NEVER
  granted: live_can("git.push") is always False. A commit
  additionally needs the existing approval flow and never
  pushes automatically.

Rules (tested):

- sessions expire (default 1h, hard cap 24h); expired or
  revoked sessions refuse; capabilities never expand after
  creation (no escalation path exists in this module).
- context packing is bounded: scope + query + entity focus +
  budget assemble slices (project, object, mission,
  observations, relationships, tasks, nodes, files, git,
  events) from existing readers. No dumps, no file contents,
  no secrets, no absolute sensitive paths.
- a Live session never executes, approves, or verifies
  anything itself: it gates which existing endpoints the
  interface may call for this session.
"""

import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

LIVE_READ_CAPABILITIES = frozenset({
    "inventory.read",
    "graph.read",
    "project.read",
    "task.read",
    "mission.read",
    "camera.read",
    "node.read",
    "git.read",
    "git.diff",
})

LIVE_PROPOSE_CAPABILITIES = frozenset({
    "inventory.propose_write",
    "research.propose",
    "project.propose_change",
    "desktop.propose_input",
    "3d.propose_transform",
    "task.propose",
    "mission.propose",
    "git.commit",
})

#: git.push is a known capability name that is NEVER granted.
#: It exists so denials are explicit and auditable.
GIT_PUSH_CAPABILITY = "git.push"

LIVE_ALL_KNOWN = (LIVE_READ_CAPABILITIES | LIVE_PROPOSE_CAPABILITIES
                  | frozenset({GIT_PUSH_CAPABILITY}))

LIVE_SESSION_TTL_SECONDS = 3600
LIVE_SESSION_MAX_TTL_SECONDS = 24 * 3600

MAX_CONTEXT_BUDGET = 20000
MAX_SCOPE_KEYS = 12


class LiveRefusedError(ValueError):
    """Local validation refused; nothing was opened or packed."""


class LiveSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=3, max_length=80)
    interface: str = Field(min_length=1, max_length=40)
    actor: str = Field(min_length=1, max_length=80)
    capabilities: list[str] = Field(default_factory=list,
                                    max_length=20)
    context_scope: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    expires_at: str = ""
    active: bool = True


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_live_session_id() -> str:
    return f"live-{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def check_capabilities(values) -> list[str]:
    if not isinstance(values, (list, tuple)):
        raise LiveRefusedError("capabilities must be a list")
    if len(values) > 20:
        raise LiveRefusedError("at most 20 capabilities")
    cleaned: list[str] = []
    for entry in values:
        if not isinstance(entry, str):
            raise LiveRefusedError(
                "capabilities must be strings")
        text = entry.strip()
        if text == GIT_PUSH_CAPABILITY:
            raise LiveRefusedError(
                "git.push is never granted to Live sessions")
        if text not in LIVE_ALL_KNOWN:
            raise LiveRefusedError(
                f"unknown Live capability '{text[:60]}'")
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def open_session(interface: str, actor: str, capabilities,
                 context_scope: dict | None = None,
                 ttl_seconds: int = LIVE_SESSION_TTL_SECONDS
                 ) -> LiveSession:
    """Open one capability-scoped Live session. Least privilege:
    only listed capabilities, never expanded later."""
    if not isinstance(interface, str) or not interface.strip() \
            or len(interface) > 40:
        raise LiveRefusedError("interface must be 1..40 chars")
    if not isinstance(actor, str) or not actor.strip() \
            or len(actor) > 80:
        raise LiveRefusedError("actor must be 1..80 chars")
    caps = check_capabilities(capabilities or [])
    scope = _check_scope(context_scope)
    try:
        ttl = int(ttl_seconds)
    except (TypeError, ValueError):
        raise LiveRefusedError("ttl must be an integer")
    if ttl <= 0 or ttl > LIVE_SESSION_MAX_TTL_SECONDS:
        raise LiveRefusedError(
            f"ttl must be 1..{LIVE_SESSION_MAX_TTL_SECONDS}")
    created = datetime.now(timezone.utc)
    return LiveSession(
        session_id=generate_live_session_id(),
        interface=interface.strip(), actor=actor.strip(),
        capabilities=caps, context_scope=scope,
        created_at=created.isoformat(),
        expires_at=(created + timedelta(seconds=ttl)).isoformat())


def _check_scope(scope) -> dict:
    if scope is None:
        return {}
    if not isinstance(scope, dict):
        raise LiveRefusedError("context scope must be an object")
    if len(scope) > MAX_SCOPE_KEYS:
        raise LiveRefusedError(
            f"at most {MAX_SCOPE_KEYS} scope keys")
    allowed = {"project_id", "entity_id", "entity_type",
               "mission_id", "conversation_id", "node_id",
               "include_observations", "include_events",
               "include_git", "include_tasks", "include_files"}
    unknown = set(scope) - allowed
    if unknown:
        raise LiveRefusedError(
            f"context scope carries unknown keys: "
            f"{sorted(unknown)}")
    cleaned: dict[str, Any] = {}
    for key, value in scope.items():
        if isinstance(value, bool):
            cleaned[key] = value
        elif isinstance(value, str) and len(value) <= 120:
            cleaned[key] = value.strip()
        else:
            raise LiveRefusedError(
                f"context scope value for '{key}' must be short "
                "text or boolean")
    return cleaned


def session_live(session: LiveSession,
                 now_str: str | None = None) -> bool:
    """True only for an active, unexpired session."""
    if not isinstance(session, LiveSession) or not session.active:
        return False
    try:
        stamp = _parse_time(now_str) if now_str else \
            datetime.now(timezone.utc)
        return _parse_time(session.expires_at) > stamp
    except (ValueError, TypeError):
        return False


def _parse_time(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def live_can(session: LiveSession, capability: str,
             now_str: str | None = None) -> bool:
    """Capability gate. git.push is always False, expired
    sessions always False, unknown capabilities False."""
    if capability == GIT_PUSH_CAPABILITY:
        return False
    if not session_live(session, now_str):
        return False
    return capability in (session.capabilities or [])


def pack_context(session: LiveSession, sources: dict,
                 query: str = "", budget: int = 8000) -> dict:
    """Assemble a bounded context package from caller-supplied
    source slices. This module never fetches anything itself:
    the caller (main.py wiring) pulls each slice through the
    existing readers, so all read gates keep applying. File
    contents, secrets and absolute paths are stripped here as
    a second boundary."""
    if not session_live(session):
        raise LiveRefusedError("session is not live")
    try:
        total = max(512, min(int(budget or 8000),
                             MAX_CONTEXT_BUDGET))
    except (TypeError, ValueError):
        raise LiveRefusedError("budget must be an integer")
    if not isinstance(sources, dict):
        raise LiveRefusedError("sources must be an object")
    package: dict[str, Any] = {
        "session_id": session.session_id,
        "query": str(query or "")[:500],
        "sections": {},
        "budget": total,
        "truncated": False,
    }
    used = 0
    for section in ("project", "object", "mission", "observations",
                    "relationships", "tasks", "nodes", "files",
                    "git", "events"):
        raw = sources.get(section)
        if raw is None:
            continue
        text = _render_section(section, raw)
        if used + len(text) > total:
            package["truncated"] = True
            break
        package["sections"][section] = text[:4000]
        used += len(text)
    package["used"] = used
    return package


def _render_section(section: str, raw) -> str:
    if isinstance(raw, dict):
        items = [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)[:25]
    else:
        items = [{"value": str(raw)[:500]}]
    lines = []
    for item in items:
        if not isinstance(item, dict):
            lines.append(_clean_text(str(item))[:300])
            continue
        kept = []
        for key in ("id", "entity_id", "observation_id",
                    "mission_id", "node_id", "type",
                    "entity_type", "title", "name", "label",
                    "status", "event_type", "branch",
                    "human_verified", "source_type",
                    "created_at"):
            if key in item:
                kept.append(f"{key}={_clean_text(item[key])[:160]}")
        if kept:
            lines.append("; ".join(kept))
    return f"[{section}]\n" + "\n".join(lines)[:4000]


def _clean_text(value) -> str:
    import os as _os
    import re as _re
    text = str(value or "")
    text = _re.sub(r"[A-Za-z]:\\[^\s\"']*|\\\\[^\s\"']+",
                   "[redacted-path]", text)
    home = _os.path.expanduser("~")
    if home and home in text:
        text = text.replace(home, "[redacted-path]")
    lowered = text.lower()
    for marker in ("api_key", "apikey", "secret", "password",
                   "token", "bearer", "credential"):
        if marker in lowered:
            return "[redacted-secret]"
    return text


# -- store (chat DB; queue DB untouched, INVENTory untouched) -----------

def save_live_session(session: LiveSession) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO live_sessions
        (session_id, interface, actor, capabilities,
         context_scope, created_at, expires_at, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET active=excluded.active""",
                    (session.session_id, session.interface,
                     session.actor,
                     dump(list(session.capabilities)),
                     dump(dict(session.context_scope)),
                     session.created_at, session.expires_at,
                     1 if session.active else 0))


def load_live_session(session_id: str) -> LiveSession | None:
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM live_sessions "
                         "WHERE session_id=?",
                         (session_id,)).fetchone()
    if row is None:
        return None
    try:
        capabilities = load(row["capabilities"] or "[]")
        scope = load(row["context_scope"] or "{}")
    except ValueError:
        return None
    return LiveSession(
        session_id=row["session_id"], interface=row["interface"],
        actor=row["actor"],
        capabilities=list(capabilities or []),
        context_scope=dict(scope or {}),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        active=bool(row["active"]))


def revoke_live_session(session_id: str) -> bool:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        changed = db.execute(
            "UPDATE live_sessions SET active=0 WHERE session_id=?",
            (session_id,)).rowcount
    return changed == 1
