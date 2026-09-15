"""Desktop-agent identity and capabilities (BIG #2).

One stable identity per machine+user: ``desktop_<12 hex>`` derived
from hostname and username. Stable across restarts (leases and
dispatch ownership depend on it), but free of hardware serials, MAC
addresses or other sensitive identifiers.

Capabilities reuse the existing fine-grained desktop namespace from
computer_actions — no second dialect, no wildcards:

- agent:desktop (the agent itself)
- desktop.screen.read, desktop.mouse.move, desktop.mouse.click,
  desktop.mouse.scroll, desktop.keyboard.type, desktop.keyboard.press

Rules (tested): unknown capabilities and wildcards are refused at
startup; the read-only set observes without ever advertising input.
"""

import getpass
import hashlib
import socket

from coordinator.app.computer_actions import (
    AGENT_DESKTOP,
    KEYBOARD_PRESS,
    KEYBOARD_TYPE,
    MOUSE_CLICK,
    MOUSE_MOVE,
    MOUSE_SCROLL,
    SCREEN_READ,
)

AGENT_ID_PREFIX = "desktop_"

FULL_CAPABILITIES = [
    AGENT_DESKTOP,
    SCREEN_READ,
    MOUSE_MOVE,
    MOUSE_CLICK,
    MOUSE_SCROLL,
    KEYBOARD_TYPE,
    KEYBOARD_PRESS,
]

READONLY_CAPABILITIES = [AGENT_DESKTOP, SCREEN_READ]

KNOWN_CAPABILITIES = frozenset(FULL_CAPABILITIES)


def stable_agent_id() -> str:
    """Stable local id without hardware identifiers."""
    try:
        host = socket.gethostname()
    except OSError:
        host = "unknown-host"
    try:
        user = getpass.getuser()
    except (OSError, KeyError):
        user = "unknown-user"
    digest = hashlib.sha256(
        f"{host}|{user}".encode("utf-8")).hexdigest()[:12]
    return f"{AGENT_ID_PREFIX}{digest}"


def check_capabilities(capabilities) -> list[str]:
    """Fail-closed capability check for agent startup."""
    if not isinstance(capabilities, (list, tuple)) or not capabilities:
        raise ValueError("Agent needs at least one capability")
    cleaned: list[str] = []
    for entry in capabilities:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError("Capabilities must be non-empty text")
        text = entry.strip()
        if "*" in text:
            raise ValueError(
                f"Capability '{text}' uses a wildcard; refusing")
        if text not in KNOWN_CAPABILITIES:
            raise ValueError(f"Unknown capability '{text}'; refusing")
        if text not in cleaned:
            cleaned.append(text)
    return cleaned
