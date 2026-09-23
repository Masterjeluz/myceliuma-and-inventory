"""Ephemeral remote-control sessions (REMOTE INPUT SLICES 1+2).

Browser UI -> coordinator -> node pull -> OS input. Mouse movement,
click, keyboard, scroll, drag (down/move/up) and text-only
clipboard — nothing else.

Transport reuses the existing pull pattern (like
``desktop/actions/next``): the coordinator never pushes, the node
polls. What is new is deliberately minimal and ephemeral:

- sessions live in a process-local registry (no database table,
  no queue, no persistence). A coordinator restart drops every
  session: fail-closed by construction.
- each session holds at most ONE pending move (latest wins,
  consumed on poll) plus a BOUNDED fifo of discrete actions
  (cap MAX_ACTIONS, refuse-when-full: no silent loss, no
  backlog). No event log, no history, no replay.
- clipboard is one ephemeral slot (last write / last read),
  never a history, never persisted.
- expiry is enforced on access (no sweeper, no scheduler).

Gates (all fail-closed):

- CONNECT is the explicit human YES (one click, like the
  existing YES gates). No auto-connect, no auto-execute.
- the node must be registered, online/fresh and must advertise
  the needed capability: existing ``desktop.mouse.move``,
  ``desktop.mouse.click``, ``desktop.mouse.scroll``,
  ``desktop.keyboard.type``, ``desktop.keyboard.press``;
  drag additionally needs move+click; clipboard needs the new
  minimal ``desktop.clipboard.write`` / ``desktop.clipboard.read``
  (no pre-existing clipboard vocabulary existed).
- the node poll presents its node_token through the existing
  ``authenticate()``; a wrong token is refused.
- every action is validated with the existing
  ``computer_actions.validate_parameters`` contracts (click,
  key_press, hotkey, type_text, scroll); mouse_down/up mirror
  the same coordinate/button rules; clipboard is text-only.
- node freshness is re-checked on every input and every poll:
  a stale node auto-closes the session, further input refused.
- DISCONNECT closes the session; afterwards the node poll
  answers 410 Gone (so a node holding a drag button releases
  it) and every input refuses.
- no filesystem, no shell, no code, no binary blobs anywhere.

This module is pure except for the small process-local
registry (guarded by a lock); time is injected for tests.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any


class RemoteInputRefusedError(ValueError):
    """Fail-closed refusal: unknown/offline/unsupported/invalid."""


class RemoteInputGoneError(ValueError):
    """Session existed but is closed/expired: node should stop polling."""


#: Absolute session lifetime after CONNECT (explicit re-CONNECT needed).
SESSION_TTL_SECONDS = 600
#: Idle expiry: no move AND no poll inside this window closes the session.
SESSION_IDLE_SECONDS = 120
#: Capability that gates remote mouse (existing vocabulary, no new string).
MOUSE_CAPABILITY = "desktop.mouse.move"

#: Per-action capability gates. Existing desktop.* vocabulary is
#: reused; only clipboard needed new minimal strings (nothing
#: clipboard-like existed). mouse_down/up ride on the click
#: family: drag = move-capability + button-capability.
CLICK_CAPABILITY = "desktop.mouse.click"
SCROLL_CAPABILITY = "desktop.mouse.scroll"
KEYBOARD_TYPE_CAPABILITY = "desktop.keyboard.type"
KEYBOARD_PRESS_CAPABILITY = "desktop.keyboard.press"
CLIPBOARD_WRITE_CAPABILITY = "desktop.clipboard.write"
CLIPBOARD_READ_CAPABILITY = "desktop.clipboard.read"

#: Closed input-action vocabulary (one route, no free-form kinds).
INPUT_KINDS = frozenset({
    "click", "key_press", "hotkey", "type_text", "scroll",
    "mouse_down", "mouse_up", "clipboard_set",
})

#: Discrete-action fifo bound: refuse-when-full, never silent loss.
MAX_ACTIONS = 64

#: Text-only clipboard bound (chars). No files, no blobs, no history.
MAX_CLIPBOARD_CHARS = 65536

#: mouse buttons (mirrors computer_actions, no second dialect).
MOUSE_BUTTONS = frozenset({"left", "right", "middle"})

SESSION_ID_CHARS = 32


def _now() -> float:
    return time.time()


def new_session_id() -> str:
    return secrets.token_hex(SESSION_ID_CHARS // 2)


@dataclass
class RemoteInputSession:
    """One ephemeral control session. Never persisted, never logged."""

    session_id: str
    node_id: str
    created_at: float
    expires_at: float
    last_activity: float
    status: str = "open"
    pending: dict[str, Any] | None = None
    actions: list = field(default_factory=list)
    delivered_seq: int = 0
    accepted_moves: int = 0
    accepted_actions: int = 0
    clipboard_request: bool = False
    last_clipboard: str | None = None


def check_session_owner(node_id: str) -> str:
    from .nodes import check_node_id

    return check_node_id(node_id)


def open_session(node_id: str, *, now: float | None = None) -> RemoteInputSession:
    """Create one open session for an already-vetted node.

    Node vetting (registered/online/capable) happens in main.py
    against the registry; this only builds the record.
    """
    moment = now if now is not None else _now()
    ident = check_session_owner(node_id)
    return RemoteInputSession(
        session_id=new_session_id(),
        node_id=ident,
        created_at=moment,
        expires_at=moment + SESSION_TTL_SECONDS,
        last_activity=moment,
    )


def session_expired(session: RemoteInputSession, now: float) -> bool:
    if session.status != "open":
        return True
    if now >= session.expires_at:
        return True
    if now - session.last_activity >= SESSION_IDLE_SECONDS:
        return True
    return False


def require_live(session: RemoteInputSession, now: float) -> RemoteInputSession:
    """Fail-closed liveness gate. Expired sessions are marked closed."""
    if session_expired(session, now):
        session.status = "closed"
        session.pending = None
        raise RemoteInputGoneError("session closed or expired")
    return session


def check_move(session: RemoteInputSession, x: Any, y: Any,
               *, now: float | None = None) -> dict[str, int]:
    """Validate one mouse move with the existing contract.

    Uses computer_actions.validate_parameters("move_mouse", ...):
    integers 0..16384, no extra fields, no shell, no code.
    Latest wins: replaces any undelivered pending move.
    """
    from .computer_actions import validate_parameters

    moment = now if now is not None else _now()
    require_live(session, moment)
    try:
        checked = validate_parameters(
            "move_mouse", {"x": x, "y": y})
    except (ValueError, TypeError) as error:
        raise RemoteInputRefusedError(str(error)) from error
    session.accepted_moves += 1
    move = {"x": int(checked["x"]), "y": int(checked["y"]),
            "seq": session.accepted_moves}
    session.pending = move
    session.last_activity = moment
    return move


def take_pending(session: RemoteInputSession, *,
                 now: float | None = None) -> dict[str, int] | None:
    """Consume the pending move for one node poll (latest wins)."""
    moment = now if now is not None else _now()
    require_live(session, moment)
    move = session.pending
    session.pending = None
    if move is not None:
        session.delivered_seq = int(move.get("seq", 0))
    session.last_activity = moment
    return dict(move) if move is not None else None


def capability_for_kind(kind: str) -> set[str]:
    """Capabilities one input kind needs. Unknown kinds fail closed."""
    if kind == "click":
        return {CLICK_CAPABILITY}
    if kind in ("key_press", "hotkey"):
        return {KEYBOARD_PRESS_CAPABILITY}
    if kind == "type_text":
        return {KEYBOARD_TYPE_CAPABILITY}
    if kind == "scroll":
        return {SCROLL_CAPABILITY}
    if kind in ("mouse_down", "mouse_up"):
        return {MOUSE_CAPABILITY, CLICK_CAPABILITY}
    if kind == "clipboard_set":
        return {CLIPBOARD_WRITE_CAPABILITY}
    raise RemoteInputRefusedError(
        f"unknown input kind '{str(kind)[:40]}'")


def _check_button(value: Any) -> str:
    if not isinstance(value, str) or value.lower() not in MOUSE_BUTTONS:
        raise RemoteInputRefusedError(
            "button must be left/right/middle")
    return value.lower()


def check_clipboard_text(value: Any) -> str:
    """Text-only clipboard gate: bounded, no control chars except
    newline/CR/tab. No files, no paths special-cased, no blobs."""
    if not isinstance(value, str):
        raise RemoteInputRefusedError("clipboard text must be text")
    if not value:
        raise RemoteInputRefusedError("clipboard text must be non-empty")
    if len(value) > MAX_CLIPBOARD_CHARS:
        raise RemoteInputRefusedError(
            f"clipboard text exceeds {MAX_CLIPBOARD_CHARS} chars")
    for char in value:
        if ord(char) < 32 and char not in ("\n", "\r", "\t"):
            raise RemoteInputRefusedError(
                "clipboard text has control characters")
    return value


def check_input_action(kind: Any, params: Any) -> dict[str, Any]:
    """Validate one discrete input action with existing contracts.

    click/key_press/hotkey/type_text/scroll reuse
    computer_actions.validate_parameters directly (no second
    dialect). mouse_down/up mirror the click coordinate/button
    rules. clipboard_set is text-only. Vertical scroll only
    (dx must be 0): horizontal scroll is out of slice scope.
    """
    from .computer_actions import validate_parameters

    if not isinstance(kind, str) or kind not in INPUT_KINDS:
        raise RemoteInputRefusedError(
            f"unknown input kind '{str(kind)[:40]}'")
    if not isinstance(params, dict):
        raise RemoteInputRefusedError("input params must be an object")
    if kind in ("click", "key_press", "hotkey", "type_text",
                "scroll"):
        try:
            checked = validate_parameters(kind, dict(params))
        except (ValueError, TypeError) as error:
            raise RemoteInputRefusedError(str(error)) from error
        if kind == "scroll" and int(checked.get("dx", 0)) != 0:
            raise RemoteInputRefusedError(
                "only vertical scroll in this slice (dx must be 0)")
        return {"kind": kind, **checked}
    if kind in ("mouse_down", "mouse_up"):
        allowed = {"x", "y", "button"}
        for key in params:
            if key not in allowed:
                raise RemoteInputRefusedError(
                    f"unknown parameter '{key}' for '{kind}'")
        if "x" not in params or "y" not in params:
            raise RemoteInputRefusedError(
                f"'{kind}' needs x and y")
        x = params.get("x")
        y = params.get("y")
        for name, value in (("x", x), ("y", y)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise RemoteInputRefusedError(
                    f"parameter '{name}' must be an integer")
            if not 0 <= value <= 16384:
                raise RemoteInputRefusedError(
                    f"parameter '{name}' must be 0..16384")
        return {"kind": kind, "x": int(x), "y": int(y),
                "button": _check_button(params.get("button", "left"))}
    if kind == "clipboard_set":
        allowed = {"text"}
        for key in params:
            if key not in allowed:
                raise RemoteInputRefusedError(
                    f"unknown parameter '{key}' for 'clipboard_set'")
        return {"kind": kind,
                "text": check_clipboard_text(params.get("text"))}
    raise RemoteInputRefusedError(
        f"unknown input kind '{str(kind)[:40]}'")  # pragma: no cover


def queue_action(session: RemoteInputSession, kind: Any, params: Any,
                 *, now: float | None = None) -> dict[str, Any]:
    """Validate + fifo one discrete action. Refuse-when-full:
    no silent loss, no unbounded growth."""
    moment = now if now is not None else _now()
    require_live(session, moment)
    checked = check_input_action(kind, params)
    if len(session.actions) >= MAX_ACTIONS:
        raise RemoteInputRefusedError(
            f"action buffer full ({MAX_ACTIONS}); refusing")
    session.accepted_actions += 1
    checked = dict(checked)
    checked["seq"] = session.accepted_actions
    session.actions.append(checked)
    session.last_activity = moment
    return checked


def take_actions(session: RemoteInputSession, *,
                 now: float | None = None) -> list:
    """Drain the discrete-action fifo for one node poll, in order."""
    moment = now if now is not None else _now()
    require_live(session, moment)
    drained = list(session.actions)
    session.actions = []
    if drained:
        session.delivered_seq = int(drained[-1].get("seq", 0))
    session.last_activity = moment
    return drained


def request_clipboard(session: RemoteInputSession, *,
                      now: float | None = None) -> None:
    """Browser asks the node for its clipboard text (one-shot flag)."""
    moment = now if now is not None else _now()
    require_live(session, moment)
    session.clipboard_request = True
    session.last_activity = moment


def store_clipboard(session: RemoteInputSession, text: Any, *,
                    now: float | None = None) -> None:
    """Node-delivered clipboard text: validated single ephemeral slot."""
    moment = now if now is not None else _now()
    require_live(session, moment)
    if not session.clipboard_request:
        raise RemoteInputRefusedError(
            "unsolicited clipboard text; refusing")
    try:
        session.last_clipboard = check_clipboard_text(text)
    except RemoteInputRefusedError as error:
        session.clipboard_request = False
        raise error
    session.clipboard_request = False
    session.last_activity = moment


def take_clipboard(session: RemoteInputSession, *,
                   now: float | None = None) -> str | None:
    """Browser reads the delivered text once (consume-on-read)."""
    moment = now if now is not None else _now()
    require_live(session, moment)
    text = session.last_clipboard
    session.last_clipboard = None
    session.last_activity = moment
    return text


def close_session(session: RemoteInputSession) -> RemoteInputSession:
    """DISCONNECT: further moves and polls are refused."""
    session.status = "closed"
    session.pending = None
    return session


def describe(session: RemoteInputSession, now: float) -> dict[str, Any]:
    """Operator-facing status. Never exposes internals beyond state."""
    live = (session.status == "open"
            and not session_expired(session, now))
    return {
        "session_id": session.session_id,
        "node_id": session.node_id,
        "status": "open" if live else "closed",
        "expires_at": session.expires_at,
        "accepted_moves": session.accepted_moves,
        "accepted_actions": session.accepted_actions,
        "delivered_seq": session.delivered_seq,
        "has_pending": session.pending is not None,
        "pending_actions": len(session.actions),
        "clipboard_request": bool(session.clipboard_request),
        "has_clipboard": session.last_clipboard is not None,
    }


class SessionRegistry:
    """Process-local, lock-guarded session store. No persistence."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, RemoteInputSession] = {}

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def put(self, session: RemoteInputSession) -> None:
        with self._lock:
            self._sessions[session.session_id] = session

    def get(self, session_id: str) -> RemoteInputSession | None:
        if not isinstance(session_id, str) or not session_id:
            return None
        with self._lock:
            return self._sessions.get(session_id)

    def open_for_node(self, node_id: str) -> RemoteInputSession | None:
        """Live session already open for this node (idempotent CONNECT)."""
        moment = _now()
        with self._lock:
            for session in self._sessions.values():
                if (session.node_id == node_id
                        and session.status == "open"
                        and not session_expired(session, moment)):
                    return session
        return None

    def latest_for_node(self, node_id: str) -> RemoteInputSession | None:
        """Newest session for this node, open or closed.

        Lets the poll answer 410 Gone for a known-but-closed
        session (so a node holding a drag button releases it)
        while never-seen nodes stay quiet (null).
        """
        newest: RemoteInputSession | None = None
        with self._lock:
            for session in self._sessions.values():
                if session.node_id != node_id:
                    continue
                if newest is None or (
                        session.created_at >= newest.created_at):
                    newest = session
        return newest

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


#: Process singleton. Restart wipes it: fail-closed by construction.
REGISTRY = SessionRegistry()
