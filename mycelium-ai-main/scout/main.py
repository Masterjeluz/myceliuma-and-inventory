"""Mycelium autonomy scout: look once, create at most one task.

Outbound-only helper beside code_worker/. One process run is one
interval: it reads presence + tasks (+ nodes for fleet matching),
applies deterministic rules, and POSTs at most one new queued task
when real work is missing. No coordinator daemon, no scheduler, no
new database, no approval paths touched.

Safety: only explicitly allowed read-only task kinds are ever
created (system_inventory, research.fetch_url, inventory.lookup,
analysis.*, code.*). Dedupe is by stable key carried in the task
payload: no open equivalent task, no creation (fail closed).
Anything uncertain — HTTP error, unreadable shape, no capable
online node, unreliable dedupe — means no task.
"""

import argparse
import asyncio
import logging
import os

import httpx

logger = logging.getLogger("scout")

ALLOWED_KIND_PREFIXES = ("system_inventory", "research.fetch_url",
                         "inventory.lookup", "analysis.", "code.")

# Read endpoints plus exactly one write: queued-task creation.
# Approval, write, physical, verify, desktop, dispatch, mission
# and task-claim/complete endpoints are absent on purpose: the
# scout discovers work, it never approves or executes anything.
ALLOWED_CALLS = (
    ("GET", "/api/v1/presence", None),
    ("GET", "/api/v1/tasks", None),
    ("GET", "/api/v1/nodes", None),
    ("POST", "/api/v1/tasks", None),
)

OPEN_STATUSES = ("queued", "assigned")


class ScoutRefusedError(ValueError):
    """Local policy refused an action; nothing was sent."""


def check_call(method: str, path: str) -> str:
    """Fail-closed endpoint gate. Returns the path when allowed."""
    clean = str(path or "").split("?", 1)[0]
    for allowed_method, prefix, suffix in ALLOWED_CALLS:
        if str(method or "").upper() != allowed_method:
            continue
        if clean != prefix and not clean.startswith(prefix + "/"):
            continue
        if suffix is not None and not clean.endswith(suffix):
            continue
        if prefix == "/api/v1/tasks" and suffix is None \
                and str(method or "").upper() != "GET" \
                and clean != prefix:
            # Only bare POST /api/v1/tasks (creation); claim,
            # complete and everything else under /tasks refused.
            continue
        return clean
    raise ScoutRefusedError(
        f"Scout never calls {method} {clean}; refusing")


def check_kind(kind: str) -> str:
    """Only explicitly allowed read-only kinds may be created."""
    cleaned = str(kind or "").strip()
    if any(cleaned == prefix or cleaned.startswith(prefix)
           for prefix in ALLOWED_KIND_PREFIXES):
        return cleaned
    raise ScoutRefusedError(
        f"Task kind '{cleaned}' is not scout-creatable "
        f"(allowed: {list(ALLOWED_KIND_PREFIXES)}); refusing")


async def api_call(client: httpx.AsyncClient, method: str,
                   url: str, json: dict | None = None):
    """Single gated HTTP call. Policy first, network second."""
    from urllib.parse import urlsplit
    check_call(method, urlsplit(url).path)
    try:
        if method.upper() == "GET":
            response = await client.get(url)
        else:
            response = await client.post(url, json=json or {})
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise ScoutRefusedError(
            f"coordinator call failed, failing closed: "
            f"{error}") from error
    if not response.content:
        return None
    return response.json()


async def fetch_state(client: httpx.AsyncClient,
                      base_url: str) -> dict:
    """Read presence, tasks and nodes. Any failure aborts the run."""
    presence = await api_call(
        client, "GET", f"{base_url}/presence") or {}
    tasks = await api_call(client, "GET", f"{base_url}/tasks")
    nodes = await api_call(client, "GET", f"{base_url}/nodes")
    if not isinstance(presence, dict):
        raise ScoutRefusedError("presence unreadable; refusing")
    if not isinstance(tasks, list):
        raise ScoutRefusedError("task list unreadable; refusing")
    if not isinstance(nodes, list):
        raise ScoutRefusedError("node list unreadable; refusing")
    return {"presence": presence, "tasks": tasks, "nodes": nodes}


def open_dedupe_keys(tasks: list) -> set[str]:
    """Stable keys of still-open tasks, from their own payloads."""
    keys: set[str] = set()
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        if str(task.get("status", "")) not in OPEN_STATUSES:
            continue
        payload = task.get("payload", {})
        if not isinstance(payload, dict):
            continue
        key = str(payload.get("scout_dedupe_key", "") or "")
        if key:
            keys.add(key)
    return keys


def online_capabilities(nodes: list) -> set[str]:
    """Capabilities advertised by right-now online nodes only."""
    caps: set[str] = set()
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("derived_status", "") or "") not in (
                "online", "busy"):
            continue
        for cap in node.get("capabilities", []) or []:
            if isinstance(cap, str) and cap.strip():
                caps.add(cap.strip())
    return caps


def fleet_can_claim(online_caps: set[str],
                    required: list[str]) -> bool:
    """True only if the live fleet covers every requirement."""
    return bool(required) and all(
        str(cap) in online_caps for cap in required)


def decide(state: dict) -> dict | None:
    """Pure decision: at most one task spec, else None.

    Rules run in fixed order; the first applicable rule wins.
    Every rule needs: a real signal, a stable dedupe key, and a
    live fleet able to claim it. Doubt anywhere returns None.
    """
    if not isinstance(state, dict):
        return None
    presence = state.get("presence", {})
    tasks = state.get("tasks", [])
    nodes = state.get("nodes", [])
    if not isinstance(presence, dict) or not isinstance(tasks, list) \
            or not isinstance(nodes, list):
        return None
    taken = open_dedupe_keys(tasks)
    fleet = online_capabilities(nodes)

    # Rule 1: stale/offline fleet members exist and nobody is
    # refreshing telemetry -> one system_inventory sweep.
    try:
        counts = presence.get("counts", {}) or {}
        offline = int(counts.get("offline", 0) or 0)
    except (TypeError, ValueError):
        return None
    if offline > 0 and "fleet-telemetry" not in taken:
        required = ["system_inventory"]
        if fleet_can_claim(fleet, required):
            return {"kind": "system_inventory",
                    "required_capabilities": required,
                    "payload": {
                        "goal": "Rapporteer vloot-telemetrie "
                                "(read-only status-ronde).",
                        "scout_dedupe_key": "fleet-telemetry"},
                    "priority": 1}

    # Rule 2: first NEEDS-band attention item without an open
    # equivalent task -> one analysis summary for the operator.
    bands = presence.get("bands", {}) or {}
    needs = bands.get("needs", []) or []
    if isinstance(needs, list):
        for item in needs:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id", "") or "")
            if not item_id:
                continue
            key = f"att-{item_id}"
            if key in taken:
                continue
            required = ["analysis.summarize"]
            if not fleet_can_claim(fleet, required):
                continue
            title = str(item.get("title", "") or item_id)[:120]
            return {"kind": "analysis.summarize",
                    "required_capabilities": required,
                    "payload": {
                        "goal": f"Vat attention-item samen: {title}",
                        "attention_id": item_id,
                        "scout_dedupe_key": key},
                    "priority": 1}
    return None


async def create_task(client: httpx.AsyncClient, base_url: str,
                      spec: dict) -> int:
    """POST exactly the decided spec after re-validating it."""
    if not isinstance(spec, dict):
        raise ScoutRefusedError("no task spec; refusing")
    kind = check_kind(spec.get("kind", ""))
    required = spec.get("required_capabilities", [])
    if not isinstance(required, list) or not required:
        raise ScoutRefusedError(
            "task needs explicit capabilities; refusing")
    payload = spec.get("payload", {})
    if not isinstance(payload, dict) or \
            not str(payload.get("scout_dedupe_key", "") or ""):
        raise ScoutRefusedError(
            "task needs a stable dedupe key; refusing")
    try:
        priority = int(spec.get("priority", 1))
    except (TypeError, ValueError):
        raise ScoutRefusedError("priority unreadable; refusing")
    created = await api_call(client, "POST",
                             f"{base_url}/tasks",
                             json={"kind": kind,
                                   "required_capabilities": [
                                       str(c) for c in required],
                                   "payload": dict(payload),
                                   "priority": max(-10, min(
                                       priority, 10))})
    if not isinstance(created, dict) \
            or not isinstance(created.get("id"), int):
        raise ScoutRefusedError(
            "coordinator answered without task id; refusing")
    return int(created["id"])


async def run_once(client: httpx.AsyncClient,
                   base_url: str) -> str:
    """One interval: look, decide, create at most one task."""
    try:
        state = await fetch_state(client, base_url)
    except ScoutRefusedError as error:
        logger.warning("scout aborted: %s", error)
        return "aborted"
    try:
        spec = decide(state)
    except Exception as error:
        logger.warning("scout undecided: %s", error)
        return "aborted"
    if spec is None:
        return "idle"
    try:
        task_id = await create_task(client, base_url, spec)
    except ScoutRefusedError as error:
        logger.warning("scout refused: %s", error)
        return "aborted"
    logger.info("scout created task %s (%s)", task_id,
                spec.get("kind"))
    return f"created:{task_id}"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mycelium autonomy scout (one look, at most "
                    "one task)")
    parser.add_argument("--coordinator",
                        default="http://localhost:8000")
    parser.add_argument("--dry-run", action="store_true",
                        help="Decide and print, never POST")
    return parser.parse_args()


async def run(config: argparse.Namespace) -> str:
    base_url = config.coordinator.rstrip("/") + "/api/v1"
    async with httpx.AsyncClient(timeout=10) as client:
        if config.dry_run:
            try:
                state = await fetch_state(client, base_url)
                spec = decide(state)
            except ScoutRefusedError as error:
                print(f"scout: aborted ({error})")
                return "aborted"
            print(f"scout: decision={spec}")
            return "idle" if spec is None else "would-create"
        return await run_once(client, base_url)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(run(arguments())))
