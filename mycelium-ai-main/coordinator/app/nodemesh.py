"""Node mesh foundation (BIG #33): safe remote coordination.

Goal: Node A asks the coordinator to involve Node B (or B+C+D)
without ever controlling another machine directly.

Rules (fail-closed, tested):

- The coordinator stays the authority: every delegation is a
  regular task with capability routing, lease, and provenance.
- No shell, no RCE, no eval, no arbitrary command. Task kinds
  come from a closed allow-list of known-safe executors.
- No wildcard capabilities. `*` or empty requirements refuse.
- Both nodes must be registered; the target capability must be
  advertised by at least one node (by prefix, never by name
  trust — routing still decides at claim time).
- Bounded payloads: JSON-serializable refs only (ids, URLs
  already validated upstream), ≤4KB, no secrets (no keys,
  tokens, passwords by name).
- Result flows back through the normal task completion path
  with provenance naming the requesting node.

This module validates and describes; it never executes, never
opens sockets, never stores. Actual dispatch reuses the
existing task queue (`POST /api/v1/tasks`), so leases,
attempt caps, and node authentication keep applying.
"""

from __future__ import annotations

import json as _json

#: Task kinds a node may request for another node. Closed list:
#: fetch/extract/analyze over coordinator-validated inputs.
ALLOWED_TASK_KINDS = (
    "research.fetch_url",
    "research.extract",
    "analysis.summarize",
    "analysis.compare",
    "inventory.lookup",
    "vision.describe",
)

#: Capability prefixes that may be targeted. A request names a
#: full capability; the prefix must be known and the capability
#: must be advertised by a registered node.
ALLOWED_CAPABILITY_PREFIXES = (
    "research.", "analysis.", "inventory.", "camera.",
    "vision.", "mesh.", "cob.", "cad.", "system_inventory",
)

_SECRET_HINTS = ("token", "secret", "password", "passwd",
                 "api_key", "apikey", "bearer", "credential",
                 "private_key", "client_secret")


def validate_delegation(requesting_node: str,
                        task_kind: str,
                        capability: str,
                        payload: dict | None = None) -> dict:
    """Validate a node→coordinator→node request. Raises ValueError."""
    requester = str(requesting_node or "").strip()[:80]
    kind = str(task_kind or "").strip()[:80]
    raw_cap = str(capability or "").strip()
    if len(raw_cap) > 120:
        raise ValueError("capability too long (≤120)")
    cap = raw_cap
    if not requester:
        raise ValueError("requesting_node is required")
    if kind not in ALLOWED_TASK_KINDS:
        raise ValueError(f"task kind not delegable: {kind}")
    if not cap or cap == "*" or "*" in cap:
        raise ValueError("wildcard capabilities are refused")
    if not cap.startswith(ALLOWED_CAPABILITY_PREFIXES):
        raise ValueError(f"capability not delegable: {cap}")
    data = dict(payload or {})
    try:
        raw = _json.dumps(data)
    except (TypeError, ValueError):
        raise ValueError("payload must be JSON-serializable")
    if len(raw) > 4096:
        raise ValueError("payload too large (≤4KB)")
    lowered = raw.lower()
    for hint in _SECRET_HINTS:
        if hint in lowered:
            raise ValueError("payload must not carry secrets")
    from . import main as _main
    try:
        nodes = _main.list_nodes()
    except Exception:
        raise ValueError("node registry unavailable")
    known = {str(row.get("node_id")) for row in nodes}
    if requester not in known:
        raise ValueError("requesting node is not registered")
    advertised = [str(capability) for row in nodes
                  for capability in
                  (row.get("capabilities") or [])]
    if not any(str(entry) == cap or
               str(entry).startswith(cap) or
               cap.startswith(str(entry))
               for entry in advertised):
        raise ValueError("no registered node advertises "
                         "that capability")
    return {"requesting_node": requester, "task_kind": kind,
            "capability": cap, "payload": data,
            "route": "node → coordinator → eligible node(s)",
            "authority": "coordinator (lease + provenance)",
            "honesty": "Validation only. Dispatch still uses "
                       "POST /api/v1/tasks; any node claims by "
                       "capability, never by remote control."}


def mesh_topology() -> dict:
    """Nodes, roles, and capability edges for the mesh view."""
    from . import main as _main
    from .ecosystem import node_roles
    try:
        nodes = _main.list_nodes()
    except Exception:
        return {"nodes": [], "edges": [], "error": "unavailable"}
    simple = [{"node_id": str(row.get("node_id")),
               "tier": str(row.get("tier", "")),
               "status": str(row.get("derived_status", "")),
               "capabilities": [str(cap) for cap in
                                (row.get("capabilities") or [])][:12],
               "roles": node_roles(row)}
              for row in nodes[:30]]
    edges: list[dict] = []
    for left in simple:
        for right in simple:
            if left["node_id"] == right["node_id"]:
                continue
            shared = [cap for cap in left["capabilities"]
                      if any(cap == other or
                             cap.split(".")[0] ==
                             other.split(".")[0]
                             for other in right["capabilities"])]
            if shared and len(edges) < 60:
                edges.append({"from": left["node_id"],
                              "to": right["node_id"],
                              "via": "coordinator",
                              "shared": shared[:3]})
    return {"nodes": simple, "edges": edges,
            "allowed_kinds": list(ALLOWED_TASK_KINDS),
            "honesty": "Edges are shared-capability hints. All "
                       "traffic goes through the coordinator task "
                       "queue — nodes never dial each other."}
