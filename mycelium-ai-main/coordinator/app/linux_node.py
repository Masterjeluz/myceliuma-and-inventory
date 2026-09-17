"""Linux node contract (BIG #30): old laptop -> Mycelium node.

Pull-only, no inbound ports, no remote shell. The coordinator never
sends commands; the node polls, claims a matching task, executes
within its advertised capabilities, and reports back.

Honest capability starter set (only what is really implemented):
  node.status, research.search, research.fetch, analysis.ollama,
  inventory.read, file.inspect

No wildcard, no shell capability, no arbitrary-command capability.
See docs/linux-node-setup.md for the 10-step runbook.
"""

from __future__ import annotations

import platform as _platform
import sys as _sys

LINUX_CAPABILITIES = (
    "node.status",
    "research.search",
    "research.fetch",
    "analysis.ollama",
    "inventory.read",
    "file.inspect",
)

NODE_SETUP_STEPS = (
    "Check Python (>= 3.11)",
    "Install the node client (pip install -e .)",
    "Generate a node id (e.g. linux-laptop-1)",
    "Write the capability config (starter set only)",
    "Set the node token (MYCELIUM_NODE_TOKEN, never in git)",
    "Point at the coordinator URL (http://127.0.0.1:8000)",
    "Check the heartbeat (register + poll)",
    "Start the node (pull-only loop)",
    "Run the safe-task test (claim + complete)",
    "Troubleshoot (logs, staleness 60s, lease 300s x3)",
)


class LinuxNodeRefusedError(ValueError):
    """Bootstrap check refused."""


def check_capabilities(caps: list[str]) -> list[str]:
    """Fail-closed: only the starter set, no wildcards, no shell."""
    if not isinstance(caps, list) or not caps:
        raise LinuxNodeRefusedError("capabilities must be a non-empty list")
    cleaned: list[str] = []
    for cap in caps:
        text = str(cap or "").strip()[:80]
        if not text:
            raise LinuxNodeRefusedError("empty capability")
        if text in ("*", "all", "shell", "shell.exec", "exec",
                    "command.run", "remote.shell"):
            raise LinuxNodeRefusedError(
                f"capability '{text}' is never granted")
        if "*" in text:
            raise LinuxNodeRefusedError(
                f"wildcard capability '{text}' is refused")
        if text not in LINUX_CAPABILITIES:
            raise LinuxNodeRefusedError(
                f"capability '{text}' is not in the Linux starter set; "
                f"expected one of {list(LINUX_CAPABILITIES)}")
        if text not in cleaned:
            cleaned.append(text)
    if len(cleaned) > len(LINUX_CAPABILITIES):
        raise LinuxNodeRefusedError("too many capabilities")
    return cleaned


def bootstrap_check(*, python_version: str = "",
                    coordinator_url: str = "",
                    node_id: str = "",
                    capabilities: list[str] | None = None) -> dict:
    """Local pre-flight checks. Never installs or connects anything."""
    checks: dict[str, dict] = {}
    wanted = tuple(int(part) for part in
                   str(python_version or ".".join(
                       str(part) for part in _sys.version_info[:3])
                       ).split(".")[:3] if part.isdigit())
    current = (_sys.version_info.major, _sys.version_info.minor,
               _sys.version_info.micro)
    checks["python"] = {
        "ok": wanted >= (3, 11) if len(wanted) >= 2 else
        current >= (3, 11),
        "current": ".".join(str(part) for part in current),
        "detail": "Python >= 3.11 required",
    }
    url = str(coordinator_url or "").strip()
    checks["coordinator_url"] = {
        "ok": url.startswith(("http://127.0.0.1", "http://localhost",
                              "http://[::1]")),
        "value": url[:120],
        "detail": "loopback coordinator URL expected "
                  "(no remote control plane here)",
    }
    ident = str(node_id or "").strip()
    checks["node_id"] = {
        "ok": bool(ident) and len(ident) <= 80 and " " not in ident,
        "value": ident[:80],
        "detail": "fresh --node-id per machine; re-registration upserts",
    }
    try:
        caps = check_capabilities(list(capabilities or []))
        checks["capabilities"] = {"ok": True, "value": caps,
                                  "detail": "starter set only"}
    except LinuxNodeRefusedError as exc:
        checks["capabilities"] = {"ok": False, "value": [],
                                  "detail": str(exc)}
    checks["platform"] = {
        "ok": True,
        "value": f"{_platform.system()} {_platform.release()} "
                 f"{_platform.machine()}",
        "detail": "informational; any pull-only host works",
    }
    overall = all(check.get("ok") for check in checks.values())
    return {"ok": overall, "checks": checks,
            "steps": list(NODE_SETUP_STEPS)}
