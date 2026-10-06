"""BIG47 living-workshop bridge: game-originated work over existing systems.

Read the boundary carefully:

- No new queue, no new worker, no new mission engine, no new memory.
  This module only composes EXISTING stores/routes:
  tasks queue (claim/complete/lease), nodes registry, automation runs,
  missions, bus events, Ollama env config, workshop/printer stores.
- POST /play/code-task QUEUES bounded code.* task data. It never
  assigns, never executes, never approves: the existing claim path
  (queued -> assigned, capability + lease + fencing checks) stays the
  only hand-off, and the existing complete path stays the only close.
- Physical safety is untouched: printers/robots/drones/desktop actions
  are not reachable from here. Only code.review / code.patch /
  code.test kinds queue; anything else refuses BEFORE any insert.
- GET /play/status is read-only and never raises: every section is
  best-effort so the game renders REAL / SIMULATED / UNAVAILABLE
  honestly instead of failing the whole snapshot.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from .database import connection, dump, load

# Game-originated work stays inside the code-worker contract, and only
# the three bounded kinds the worker actually executes. code.* at large
# (e.g. hypothetical code.exec) never queues from the game.
PLAY_CODE_KINDS: dict[str, list[str]] = {
    "code.review": ["code.review"],
    "code.patch": ["code.patch"],
    "code.test": ["code.test"],
}

PLAY_CODE_KIND_PATTERN = r"^[a-zA-Z0-9._-]+$"
MAX_GOAL_LENGTH = 500


class PlayCodeTaskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=2, max_length=80,
                      pattern=PLAY_CODE_KIND_PATTERN)
    goal: str = Field(min_length=1, max_length=MAX_GOAL_LENGTH)
    mission_id: str | None = Field(default=None, max_length=80)
    step_id: str | None = Field(default=None, max_length=80)


class PlayRefusedError(ValueError):
    """Game task validation refused; nothing was queued."""


#: Mission step kinds a play task may bind to. Analysis steps carry
#: an explicit goal that maps onto the live code_worker claim loop;
#: every other kind keeps its inline runner and gates. Only
#: code.review binds — patch/test stay operator-queued general work.
PLAY_STEP_KINDS = frozenset({"analysis"})
PLAY_STEP_TASK_KIND = "code.review"


def check_play_kind(kind: str) -> tuple[str, list[str]]:
    """Allow-list gate for game-originated tasks. Fail-closed."""
    cleaned = str(kind or "").strip()
    if cleaned not in PLAY_CODE_KINDS:
        raise PlayRefusedError(
            f"Play queues only {sorted(PLAY_CODE_KINDS)}; "
            f"refusing '{cleaned[:80]}'")
    return cleaned, list(PLAY_CODE_KINDS[cleaned])


def check_play_goal(goal: str) -> str:
    cleaned = str(goal or "").strip()
    if not cleaned:
        raise PlayRefusedError("Play task needs a goal; nothing to do")
    if len(cleaned) > MAX_GOAL_LENGTH:
        raise PlayRefusedError(
            f"Play goal exceeds {MAX_GOAL_LENGTH} characters")
    return cleaned


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def queue_play_task(kind: str, goal: str,
                    mission_id: str | None = None,
                    step_id: str | None = None) -> dict:
    """Queue one bounded code.* task from the game. Returns id/status.

    Same row shape as POST /api/v1/tasks (status 'queued', routing
    requirements validated + merged, payload keeps no shadow copy).
    Raises PlayRefusedError (422) or ValueError on unknown mission
    (422); MissionConflictError (409) when the mission/step state
    forbids binding. Never assigns, never executes.

    With step_id the task binds to a real mission step: the step
    must be a pending analysis step of the given mission on an
    approved/running mission, and the task kind must be code.review.
    The step moves to "dispatched" through the existing conditional
    mission save — the existing _closeout_dispatched_step then
    closes it after worker completion, with no new closeout logic.
    Re-queueing a dispatched step with a live task returns the
    existing task (idempotent, existing=True).
    """
    from .routing import check_requirements
    clean_kind, caps = check_play_kind(kind)
    clean_goal = check_play_goal(goal)
    clean_mission = (str(mission_id or "").strip() or None)
    clean_step = (str(step_id or "").strip() or None)
    if clean_step is not None and clean_mission is None:
        raise PlayRefusedError(
            "Step binding needs its mission_id; refusing "
            "cross-mission binding")
    if clean_mission is not None:
        from .missions import load_mission
        if load_mission(clean_mission) is None:
            raise ValueError("unknown mission_id")
    if clean_step is not None:
        return _queue_step_task(clean_kind, caps, clean_goal,
                                clean_mission or "", clean_step)
    requirements = check_requirements(
        {"required_capabilities": caps})
    payload = {"goal": clean_goal,
               "origin": "play",
               "actor": "game-jelles"}
    with connection() as db:
        cursor = db.execute(
            """INSERT INTO tasks (kind,payload,required_capabilities,
            preferred_tier,priority,status,created_at,routing,mission_id)
            VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
            (clean_kind, dump(payload), dump(caps), None, 0,
             _utc_now(),
             dump(requirements.model_dump(mode="json")),
             clean_mission))
        task_id = cursor.lastrowid
    return {"id": task_id, "status": "queued", "kind": clean_kind,
            "mission_id": clean_mission}


def _live_step_tasks(mission_id: str, step_id: str) -> list[int]:
    """Queued/assigned task ids already linked to a mission step."""
    try:
        with connection() as db:
            rows = db.execute(
                "SELECT id, payload FROM tasks WHERE mission_id=? "
                "AND status IN ('queued','assigned')",
                (mission_id,)).fetchall()
    except Exception:
        return []
    found = []
    for row in rows:
        try:
            payload = load(row["payload"] or "{}")
        except Exception:
            continue
        if (isinstance(payload, dict)
                and str(payload.get("mission_step_id", "")
                        or "").strip() == step_id):
            found.append(int(row["id"]))
    return found


def _queue_step_task(kind: str, caps: list[str], goal: str,
                     mission_id: str, step_id: str) -> dict:
    """Queue a play task bound to a mission step (see queue_play_task)."""
    from .missions import (MissionConflictError, load_mission,
                           new_event, save_event, save_mission,
                           set_step)
    from .routing import check_requirements
    if kind != PLAY_STEP_TASK_KIND:
        raise PlayRefusedError(
            f"Step binding is {PLAY_STEP_TASK_KIND} only; "
            f"refusing '{kind}'")
    mission = load_mission(mission_id)
    if mission is None:  # pragma: no cover - checked by caller
        raise ValueError("unknown mission_id")
    step = next((entry for entry in mission.steps
                 if entry.step_id == step_id), None)
    if step is None:
        raise ValueError(
            f"Step '{step_id}' not found in mission '{mission_id}'")
    if str(step.kind) not in PLAY_STEP_KINDS:
        raise PlayRefusedError(
            f"Step '{step_id}' (kind '{step.kind}') never takes "
            f"play tasks; refusing")
    if str(step.status) in ("completed", "failed", "blocked",
                            "skipped"):
        raise PlayRefusedError(
            f"Step '{step_id}' is {step.status}; terminal steps "
            "take no new tasks")
    if str(mission.status) not in ("approved", "running"):
        raise MissionConflictError(
            f"Mission '{mission_id}' is {mission.status}; step "
            "binding needs an approved or running mission")
    live = _live_step_tasks(mission_id, step_id)
    if live and str(step.status) == "dispatched":
        return {"id": live[0], "status": "queued",
                "kind": PLAY_STEP_TASK_KIND,
                "mission_id": mission_id, "step_id": step_id,
                "existing": True}
    requirements = check_requirements(
        {"required_capabilities": caps})
    payload = {"goal": goal,
               "mission_step_id": step_id,
               "origin": "play",
               "actor": "game-jelles"}
    with connection() as db:
        cursor = db.execute(
            """INSERT INTO tasks (kind,payload,required_capabilities,
            preferred_tier,priority,status,created_at,routing,mission_id)
            VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
            (kind, dump(payload), dump(caps), None, 0,
             _utc_now(),
             dump(requirements.model_dump(mode="json")),
             mission_id))
        task_id = cursor.lastrowid
    old_status, old_step = mission.status, mission.current_step
    updated = set_step(mission, step_id, status="dispatched",
                       started_at=step.started_at or _utc_now())
    save_mission(updated, expected=(old_status, old_step))
    save_event(new_event(
        mission.conversation_id, "task_dispatched",
        f"Stap {step.sequence + 1} als play-taak {task_id} "
        "gedispatched.",
        mission_id=mission.mission_id, step_id=step_id,
        metadata={"task_id": task_id, "origin": "play"}))
    return {"id": task_id, "status": "queued", "kind": kind,
            "mission_id": mission_id, "step_id": step_id}


def _task_summary() -> dict:
    out: dict = {"counts": {"queued": 0, "assigned": 0,
                            "completed": 0, "failed": 0},
                 "open": []}
    try:
        with connection() as db:
            rows = db.execute(
                "SELECT id, kind, status, assigned_node_id, "
                "mission_id, created_at, completed_at FROM tasks "
                "ORDER BY id DESC LIMIT 8").fetchall()
            counts = db.execute(
                "SELECT status, COUNT(*) AS n FROM tasks "
                "GROUP BY status").fetchall()
        for row in counts:
            status = str(row["status"] or "")
            if status in out["counts"]:
                out["counts"][status] = int(row["n"] or 0)
        for row in rows:
            out["open"].append({
                "id": row["id"], "kind": str(row["kind"] or ""),
                "status": str(row["status"] or ""),
                "node": str(row["assigned_node_id"] or ""),
                "mission_id": str(row["mission_id"] or ""),
                "created": str(row["created_at"] or "")[:16],
                "done": str(row["completed_at"] or "")[:16],
                "stage": _task_stage(str(row["status"] or ""))})
    except Exception:
        pass
    return out


def _task_stage(status: str) -> str:
    """Map the REAL queue status onto the shared workshop lifecycle.

    Only existing backend states appear; nothing is invented.
    """
    return {"queued": "QUEUED",
            "assigned": "ASSIGNED/RUNNING",
            "completed": "RESULT/VERIFIED (see task result)",
            "failed": "RESULT (failed — see task error)",
            "staged": "PROPOSED (not dispatchable)"}.get(
        status, status or "UNKNOWN")


def _node_summary() -> dict:
    out: dict = {"nodes": [], "code_capable": 0}
    try:
        from .nodes import derive_status
        with connection() as db:
            rows = db.execute(
                "SELECT node_id, tier, capabilities, status, "
                "last_seen, executors FROM nodes "
                "ORDER BY last_seen DESC LIMIT 12").fetchall()
            try:
                assigned = db.execute(
                    "SELECT id, assigned_node_id FROM tasks "
                    "WHERE status='assigned' AND assigned_node_id "
                    "IS NOT NULL").fetchall()
                busy = {str(row["assigned_node_id"] or "")
                        for row in assigned}
            except Exception:
                busy = set()
        for row in rows:
            try:
                caps = load(row["capabilities"] or "[]")
            except Exception:
                caps = []
            if not isinstance(caps, list):
                caps = []
            derived = derive_status(str(row["status"] or ""),
                                    str(row["last_seen"] or ""))
            code_ok = any(str(cap).startswith("code.")
                          for cap in caps)
            if code_ok and derived in ("online", "busy"):
                out["code_capable"] += 1
            out["nodes"].append({
                "node_id": str(row["node_id"] or ""),
                "tier": str(row["tier"] or ""),
                "state": derived,
                "busy": str(row["node_id"] or "") in busy,
                "code_capable": bool(code_ok),
                "seen": str(row["last_seen"] or "")[:16]})
    except Exception:
        pass
    return out


def _automation_summary() -> dict:
    out: dict = {"open": [], "states": {}}
    try:
        from .automation import list_runs, run_to_json
        for run in list_runs(limit=8) or []:
            try:
                data = run_to_json(run)
            except Exception:
                continue
            state = str(data.get("state", "") or "")
            out["states"][state] = out["states"].get(state, 0) + 1
            out["open"].append({
                "run_id": str(data.get("run_id", "")),
                "goal": str(data.get("goal", ""))[:120],
                "state": state,
                "done": data.get("steps_done", 0),
                "total": data.get("steps_total", 0),
                "stage": _automation_stage(state)})
    except Exception:
        pass
    return out


def _automation_stage(state: str) -> str:
    return {"running": "APPROVED/RUNNING (explicit drive only)",
            "completed": "RESULT/VERIFIED (see run record)",
            "failed": "RESULT (failed)",
            "cancelled": "RESULT (cancelled)"}.get(
        state, state or "UNKNOWN")


def _mission_summary() -> dict:
    out: dict = {"active": 0, "waiting_approval": 0, "items": []}
    try:
        from .missions import list_missions
        for mission in list_missions(limit=50) or []:
            status = str(mission.status or "")
            if status in ("approved", "running"):
                out["active"] += 1
            if status == "pending_approval":
                out["waiting_approval"] += 1
            if status in ("approved", "running", "pending_approval",
                          "draft", "completed"):
                out["items"].append({
                    "id": str(mission.mission_id or ""),
                    "goal": str(mission.goal or "")[:120],
                    "status": status,
                    "stage": _mission_stage(status)})
        out["items"].sort(key=lambda item: item["id"])
        out["items"] = out["items"][:8]
    except Exception:
        pass
    return out


def _mission_stage(status: str) -> str:
    return {"draft": "DISCOVERED/PROPOSED",
            "pending_approval": "WAITING_FOR_APPROVAL",
            "approved": "APPROVED/QUEUED",
            "running": "RUNNING",
            "paused": "WAITING_FOR_APPROVAL (paused)",
            "completed": "RESULT/VERIFIED",
            "failed": "RESULT (failed)",
            "blocked": "RESULT (blocked)"}.get(
        status, status or "UNKNOWN")


def _event_tail(limit: int = 5) -> list[dict]:
    try:
        from .events import bus_events
        items = []
        for event in bus_events(limit=limit) or []:
            items.append({
                "type": str(event.event_type or ""),
                "summary": str(event.summary or "")[:160],
                "created": str(event.created_at or "")[:16]})
        return items
    except Exception:
        return []


# M1 (BIG56) — live readiness-probes voor de game-Journal.
#
# Elke probe is een echte, actuele controle zonder cache: Ollama via
# GET /api/tags (proces-beschikbaarheid onderscheiden van
# model-beschikbaarheid — nooit groen verzinnen), INVENTory via
# GET /api/v1/health, Hermes via GET /health (alleen aanwezigheid
# van de key wordt gerapporteerd, de key zelf nooit), nodes uit het
# lokale register (afgeleide staleness, geen netwerk). Alleen
# bestaande endpoints, loopback-validatie hergebruikt uit de
# bestaande bridges, korte timeouts, nooit raisen.
LIVE_PROBE_TIMEOUT_SECONDS = 3.0


def _probe_ollama(env) -> dict:
    try:
        from .ollama_advisor import (BASE_URL_ENV_VAR, DEFAULT_BASE_URL,
                                     DEFAULT_MODEL, MODEL_ENV_VAR,
                                     _validate_base_url)
    except Exception:
        return {"state": "UNAVAILABLE",
                "detail": "advisor config unavailable"}
    base_url = env.get(BASE_URL_ENV_VAR, DEFAULT_BASE_URL)
    model = str(env.get(MODEL_ENV_VAR, DEFAULT_MODEL))[:80]
    try:
        checked = _validate_base_url(base_url)
    except Exception as error:
        return {"state": "UNAVAILABLE", "base_url": str(base_url)[:80],
                "model": model,
                "detail": f"base URL geweigerd ({error})"}
    try:
        import httpx as _httpx
        with _httpx.Client(timeout=LIVE_PROBE_TIMEOUT_SECONDS,
                           follow_redirects=False) as client:
            response = client.get(f"{checked}/api/tags")
    except Exception:
        return {"state": "UNAVAILABLE", "base_url": checked,
                "model": model,
                "detail": f"geen Ollama-proces op {checked} "
                          f"(start Ollama of zet {BASE_URL_ENV_VAR})"}
    if response.status_code != 200:
        return {"state": "UNAVAILABLE", "base_url": checked,
                "model": model,
                "detail": f"Ollama-tags antwoordde "
                          f"HTTP {response.status_code}"}
    try:
        names = [str(item.get("name", ""))
                 for item in response.json().get("models", [])]
    except Exception:
        names = []
    want_base = model.split(":")[0]
    listed = any(name == model or name.split(":")[0] == want_base
                 for name in names if name)
    if listed:
        return {"state": f"REAL (model {model} aanwezig)",
                "base_url": checked, "model": model}
    return {"state": f"PROCES-ONLY (model {model} niet gepulled)",
            "base_url": checked, "model": model,
            "detail": f"proces bereikbaar, model ontbreekt "
                      f"(ollama pull {model})"}


def _probe_inventory() -> dict:
    try:
        from .inventory_read import (BASE_URL_ENV_VAR, DEFAULT_BASE_URL,
                                     MAX_TIMEOUT_SECONDS,
                                     _validate_base_url)
    except Exception:
        return {"state": "UNAVAILABLE",
                "detail": "bridge unavailable"}
    import os as _os
    base_url = _os.environ.get(BASE_URL_ENV_VAR, DEFAULT_BASE_URL)
    try:
        checked = _validate_base_url(base_url)
    except Exception as error:
        return {"state": "UNAVAILABLE",
                "base_url": str(base_url)[:80],
                "detail": f"base URL geweigerd ({error})"}
    try:
        import httpx as _httpx
        budget = min(LIVE_PROBE_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS)
        with _httpx.Client(timeout=budget,
                           follow_redirects=False) as client:
            response = client.get(f"{checked}/api/v1/health")
    except Exception:
        return {"state": "UNAVAILABLE", "base_url": checked,
                "detail": f"INVENTory offline op {checked} "
                          f"(niets verzonnen)"}
    if response.status_code != 200:
        return {"state": "UNAVAILABLE", "base_url": checked,
                "detail": f"INVENTory-health antwoordde "
                          f"HTTP {response.status_code}"}
    return {"state": "OK", "base_url": checked}


def _probe_hermes(env) -> dict:
    try:
        from .hermes_bridge import (API_KEY_ENV_VAR, BASE_URL_ENV_VAR,
                                    DEFAULT_BASE_URL, HermesBridge,
                                    HermesRefusedError, HermesUnavailable)
    except Exception:
        return {"state": "UNAVAILABLE",
                "detail": "hermes bridge unavailable"}
    base_url = env.get(BASE_URL_ENV_VAR, DEFAULT_BASE_URL)
    key = env.get(API_KEY_ENV_VAR, "")
    if not isinstance(key, str) or not key.strip():
        return {"state": "KEY-MISSING",
                "base_url": str(base_url)[:80],
                "detail": f"zet {API_KEY_ENV_VAR}; Mos-chat uit, "
                          f"missie-drive werkt wel"}
    try:
        bridge = HermesBridge(base_url=base_url, api_key=key,
                              timeout=LIVE_PROBE_TIMEOUT_SECONDS)
        bridge.health()
    except (HermesRefusedError, HermesUnavailable) as error:
        return {"state": "UNAVAILABLE",
                "base_url": str(base_url)[:80],
                "detail": str(error)[:160]}
    except Exception as error:
        return {"state": "UNAVAILABLE",
                "base_url": str(base_url)[:80],
                "detail": f"{type(error).__name__}"[:160]}
    return {"state": "REAL", "base_url": bridge.base_url}


def _probe_nodes() -> dict:
    try:
        nodes = _node_summary().get("nodes", []) or []
    except Exception:
        return {"state": "onleesbaar", "live": 0, "total": 0}
    live = sum(1 for node in nodes
               if str(node.get("state", "")) in ("online", "busy"))
    return {"state": f"{live} live / {len(nodes)} geregistreerd",
            "live": live, "total": len(nodes)}


def _liveness() -> dict:
    """Ollama + INVENTory + Hermes + nodes: echte, actuele controles.

    Vroeger rapporteerde dit alleen configuratie
    ("REAL (live check at ...)"); M1 prikt echt door (zonder
    inferentie-aanroep — alleen /api/tags, /api/v1/health en
    /health) zodat de game nooit groen verzint en
    proces-beschikbaarheid nooit verwart met
    model-beschikbaarheid. Blijft nooit raisen: elke sectie
    degradeert naar een eerlijke UNAVAILABLE/KEY-MISSING-staat.
    """
    import os as _os
    return {"ollama": _probe_ollama(_os.environ),
            "inventory": _probe_inventory(),
            "hermes": _probe_hermes(_os.environ),
            "nodes": _probe_nodes()}


def fabrication_chain() -> list[dict]:
    """Per-transition REAL / SIMULATED / UNAVAILABLE / BLOCKED states.

    Every verdict derives from existing stores; nothing is probed,
    nothing moves. Execution stays BLOCKED until exact YES +
    fingerprint + TTL + adapter + hardware, enforced by the
    existing fab/write gates (this table only REPORTS it).
    """
    chain: list[dict] = []

    def _add(step: str, state: str, via: str, detail: str = "") -> None:
        chain.append({"step": step, "state": state, "via": via,
                      "detail": detail[:200]})

    models = 0
    try:
        from .workshop3d import list_models
        models = len(list_models(limit=200) or [])
    except Exception:
        models = 0
    _add("idea", "REAL", "existing ideas store",
         "ideas CRUD + relationships")
    _add("project", "REAL", "existing projects store",
         "project CRUD + statuses")
    _add("materials", "REAL", "existing workshop links",
         "workshop model/material links")
    _add("model/CAD", "REAL", "procedural box/cylinder adapter",
         f"{models} model(s) registered; OpenSCAD/FreeCAD/Blender "
         "UNAVAILABLE")
    _add("mesh", "REAL", "existing mesh validate/preview",
         "numeric verdicts, no viewport")
    _add("validation", "REAL", "existing assess/inspect",
         "printability verdicts as data")
    _add("Forge", "REAL", "existing forge studio (read-mostly)",
         "save/open/propose over cad stores")
    _add("slicing", "SIMULATED", "existing slicer badge",
         "test-slice produces refs; no real G-code execution")
    _add("proposal", "REAL", "existing prints/propose + writes flow",
         "inert until exact YES")
    _add("approval", "BLOCKED", "existing exact-YES + fingerprint + TTL",
         "operator YES required, never auto")
    printers = 0
    adapter = False
    try:
        from .printer3d import (adapter_for_printer,
                                list_stored_printers)
        stored = list(list_stored_printers() or [])
        printers = len(stored)
        for printer in stored:
            try:
                if adapter_for_printer(printer.printer_id) is not None:
                    adapter = True
                    break
            except Exception:
                continue
    except Exception:
        printers = 0
    if not printers:
        _add("execution", "UNAVAILABLE", "no printer registered",
             "register hardware first; mission-YES never starts "
             "the machine")
    elif not adapter:
        _add("execution", "BLOCKED", "printer known, no adapter",
             "adapter + exact YES + hardware required")
    else:
        _add("execution", "BLOCKED", "adapter + exact YES + hardware",
             "gated execute; telemetry + camera verify after")
    _add("observation", "REAL", "existing camera inbox/observations",
         "file ingest + describe as data")
    _add("verification", "REAL", "existing writes verify flow",
         "independent readback; execution alone never verifies")
    _add("event", "REAL", "existing bus events",
         "task/mission/write events feed the game")
    return chain


def _world_summary() -> dict:
    """Live world counts for the game (no reload needed).

    Read-only derivation over the same stores the page snapshot
    uses: fungi network totals + completed missions as visible
    historical results. Never raises.
    """
    out: dict = {"fungi_total": 0, "fungi_completed": 0,
                 "branches": {}}
    try:
        from .world import derive_fungi_network
        net = derive_fungi_network(limit=120) or {}
        out["fungi_total"] = int(net.get("total", 0) or 0)
        out["branches"] = dict(net.get("counts", {}) or {})
        done = 0
        for node in net.get("nodes", []) or []:
            if not isinstance(node, dict):
                continue
            label = str(node.get("label", "") or "")
            if label.startswith("✓ "):
                done += 1
        out["fungi_completed"] = done
    except Exception:
        pass
    return out


def play_status() -> dict:
    """One read-only snapshot for the /play workshop view."""
    return {"tasks": _task_summary(),
            "nodes": _node_summary(),
            "automation": _automation_summary(),
            "missions": _mission_summary(),
            "events": _event_tail(),
            "liveness": _liveness(),
            "world": _world_summary(),
            "fabrication": fabrication_chain()}


# -- player sessions (BIG48) ------------------------------------------------
# Minimal persistent presence: session_id + x/y/zone + timestamps.
# No auth, no accounts. Position saves from the game client are
# throttled server-side (POSITION_MIN_INTERVAL_S); throttled calls
# return saved=False with the stored position instead of failing.
# Table lives in the main coordinator DB, created additively by
# init_database (CREATE TABLE IF NOT EXISTS).

import re as _re
import secrets as _secrets

SESSION_ID_RE = _re.compile(r"^[A-Za-z0-9_-]{1,80}$")
PLAY_WORLD_W = 3840.0
PLAY_WORLD_H = 1400.0
PLAY_SPAWN = {"x": 800.0, "y": 500.0, "zone": "Homebase"}
POSITION_MIN_INTERVAL_S = 2.0


class PlaySessionRefusedError(ValueError):
    """Player session validation refused; nothing was stored."""


def _check_session_id(session_id: str) -> str:
    cleaned = str(session_id or "").strip()[:80]
    if not cleaned or not SESSION_ID_RE.match(cleaned):
        raise PlaySessionRefusedError(
            "session_id must match ^[A-Za-z0-9_-]{1,80}$")
    return cleaned


def _clamp_position(x, y) -> tuple[float, float]:
    try:
        clean_x = max(0.0, min(float(x), PLAY_WORLD_W))
    except (TypeError, ValueError):
        raise PlaySessionRefusedError("x must be a number")
    try:
        clean_y = max(0.0, min(float(y), PLAY_WORLD_H))
    except (TypeError, ValueError):
        raise PlaySessionRefusedError("y must be a number")
    return clean_x, clean_y


def _check_angle(angle) -> float:
    """Facing direction in radians, wrapped to [0, 2pi).
    Non-numbers refuse; the view must come from the
    player, never from a guess."""
    import math as _math
    try:
        value = float(angle)
    except (TypeError, ValueError):
        raise PlaySessionRefusedError("angle must be a number")
    if not _math.isfinite(value):
        raise PlaySessionRefusedError("angle must be finite")
    return value % (2.0 * _math.pi)


def _row_to_session(row) -> dict:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    return {"session_id": str(row["session_id"]),
            "x": float(row["x"] or 0.0),
            "y": float(row["y"] or 0.0),
            "a": float(row["angle"] or 0.0)
            if "angle" in keys else 0.0,
            "zone": str(row["zone"] or ""),
            "created": str(row["created_at"] or "")[:19],
            "updated": str(row["updated_at"] or "")[:19]}


def open_play_session(session_id: str | None = None) -> dict:
    """Create or resume a player session. Returns session + resumed."""
    from .database import connection, init_database
    init_database()
    stamp = _utc_now()
    if session_id:
        cleaned = _check_session_id(session_id)
        with connection() as db:
            row = db.execute(
                "SELECT * FROM play_sessions WHERE session_id=?",
                (cleaned,)).fetchone()
        if row is not None:
            data = _row_to_session(row)
            data["resumed"] = True
            return data
    fresh = f"play_{_secrets.token_hex(8)}"
    with connection() as db:
        db.execute(
            "INSERT INTO play_sessions (session_id, x, y, zone, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (fresh, PLAY_SPAWN["x"], PLAY_SPAWN["y"],
             PLAY_SPAWN["zone"], stamp, stamp))
    return {"session_id": fresh, "x": PLAY_SPAWN["x"],
            "y": PLAY_SPAWN["y"], "a": 0.0,
            "zone": PLAY_SPAWN["zone"],
            "created": stamp[:19], "updated": stamp[:19],
            "resumed": False}


def save_play_position(session_id: str, x, y,
                       zone: str = "", angle=None) -> dict:
    """Store a player position + optional facing (throttled).
    Unknown session -> KeyError. angle=None leaves the stored
    facing untouched (callers like /side send none)."""
    from datetime import datetime, timezone
    from .database import connection, init_database
    init_database()
    cleaned = _check_session_id(session_id)
    clean_x, clean_y = _clamp_position(x, y)
    clean_zone = str(zone or "")[:120]
    clean_angle = (None if angle is None
                   else _check_angle(angle))
    with connection() as db:
        row = db.execute(
            "SELECT *, "
            "COALESCE(moved_at, '') AS position_at "
            "FROM play_sessions WHERE session_id=?",
            (cleaned,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown play session '{cleaned}'")
        try:
            last = datetime.fromisoformat(
                str(row["position_at"] or ""))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - last
                   ).total_seconds()
        except (ValueError, TypeError):
            age = POSITION_MIN_INTERVAL_S
        if age < POSITION_MIN_INTERVAL_S:
            data = _row_to_session(row)
            data["saved"] = False
            return data
        stamp = _utc_now()
        if clean_angle is None:
            db.execute(
                "UPDATE play_sessions SET x=?, y=?, zone=?, "
                "updated_at=?, moved_at=? "
                "WHERE session_id=?",
                (clean_x, clean_y, clean_zone,
                 stamp, stamp, cleaned))
        else:
            db.execute(
                "UPDATE play_sessions SET x=?, y=?, zone=?, "
                "angle=?, updated_at=?, moved_at=? "
                "WHERE session_id=?",
                (clean_x, clean_y, clean_zone, clean_angle,
                 stamp, stamp, cleaned))
    with connection() as db:
        stored = db.execute(
            "SELECT * FROM play_sessions WHERE session_id=?",
            (cleaned,)).fetchone()
    data = _row_to_session(stored)
    data.update({"saved": True, "updated": stamp[:19]})
    return data


# -- gather / craft / build (BIG53) --------------------------------------
# Core game loop state: session-owned resources, crafted goods and
# placed structures. Same ownership precedent as play_sessions —
# game state, never a backend record (no candidates/missions/
# INVENTory writes here). Server validates everything: known
# sessions, known nodes/recipes, quantities, cooldowns, bounds.

PLAY_ITEMS = ("wood", "fiber", "stone", "stick", "torch",
              "plank", "fence", "crystal", "reed", "scrap",
              "lamp", "chest", "room", "compass", "mast")

#: node_id prefix -> resource item. Node ids look like stump-1.
NODE_YIELDS = {"stump": "wood", "fiber": "fiber", "rock": "stone",
               "crystal": "crystal", "reed": "reed",
               "scrap": "scrap"}

NODE_ID_RE = _re.compile(r"^[a-z]{3,10}-[0-9]{1,3}$")

#: seconds before the same node yields again for one session.
GATHER_COOLDOWN_S = 90.0

#: recipe -> {ingredient: qty}. Craft consumes, then adds 1 item.
PLAY_RECIPES = {"stick": {"wood": 2},
                "torch": {"stick": 1, "fiber": 1},
                "plank": {"wood": 3},
                "fence": {"wood": 2, "stone": 1},
                "lamp": {"stick": 1, "crystal": 1},
                "chest": {"wood": 4, "stone": 2},
                "room": {"plank": 2, "fence": 2},
                "compass": {"crystal": 1, "stone": 1},
                "mast": {"scrap": 2, "crystal": 1}}

#: crafted goods that can be placed in the world (consumes 1).
PLAY_PLACEABLE = ("plank", "torch", "fence", "lamp", "chest",
                  "room", "mast")

#: side-view world bounds for placed structures (BIG55: 3840).
SIDE_WORLD_W = 3840.0
SIDE_WORLD_H = 540.0

#: NPC ids the settlement system knows (client gates spawn
#: requirements visibly; server only records valid houses).
PLAY_NPCS = ("mos", "smid", "archivaris", "voorman",
             "seinwachter", "oracle")

#: server-side flag names worth keeping (quest/encounter/world).
PLAY_FLAGS = ("moved", "gathered", "crafted", "placed",
              "puffer", "quest", "remembered", "housed",
              "codex", "node_found", "modderhart",
              "diepteklok", "stormvlaag", "mystery",
              "outpost", "lamp_lit", "chest_used")

#: world clock: 1440 minutes per day, starts day 1 at 08:00.
CLOCK_DAY_MINUTES = 1440
CLOCK_TICK_MINUTES = 10
CLOCK_TICK_INTERVAL_S = 60.0


def _require_session(db, session_id: str) -> str:
    cleaned = _check_session_id(session_id)
    row = db.execute(
        "SELECT session_id FROM play_sessions WHERE session_id=?",
        (cleaned,)).fetchone()
    if row is None:
        raise KeyError(f"Unknown play session '{cleaned}'")
    return cleaned


def _inventory_qty(db, session_id: str, item: str) -> int:
    row = db.execute(
        "SELECT qty FROM play_inventory WHERE session_id=? AND "
        "item=?", (session_id, item)).fetchone()
    return int(row["qty"] or 0) if row is not None else 0


def _add_item(db, session_id: str, item: str, delta: int,
              stamp: str) -> int:
    if item not in PLAY_ITEMS:
        raise PlaySessionRefusedError(
            f"Unknown item '{item}'")
    qty = _inventory_qty(db, session_id, item) + delta
    if qty < 0:
        raise PlaySessionRefusedError(
            f"Not enough {item} (need {-delta})")
    if qty == 0:
        db.execute("DELETE FROM play_inventory WHERE "
                   "session_id=? AND item=?", (session_id, item))
    else:
        db.execute("INSERT INTO play_inventory (session_id, "
                   "item, qty, updated_at) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT(session_id, item) DO UPDATE SET "
                   "qty=excluded.qty, updated_at=excluded."
                   "updated_at", (session_id, item, qty, stamp))
    return qty


def get_play_inventory(session_id: str) -> dict:
    """Read-only session inventory + placed builds. Unknown -> KeyError."""
    from .database import connection, init_database
    init_database()
    with connection() as db:
        cleaned = _require_session(db, session_id)
        rows = db.execute(
            "SELECT item, qty FROM play_inventory WHERE "
            "session_id=? ORDER BY item", (cleaned,)).fetchall()
        builds = db.execute(
            "SELECT build_id, kind, x, y FROM play_builds WHERE "
            "session_id=? ORDER BY created_at",
            (cleaned,)).fetchall()
    return {"session_id": cleaned,
            "items": {str(row["item"]): int(row["qty"] or 0)
                      for row in rows},
            "builds": [{"build_id": str(row["build_id"]),
                        "kind": str(row["kind"]),
                        "x": float(row["x"] or 0.0),
                        "y": float(row["y"] or 0.0)}
                       for row in builds]}


def gather_node(session_id: str, node_id: str) -> dict:
    """Yield 1 resource from a known node. Cooldown 90s per
    (session, node). Unknown session -> KeyError."""
    from datetime import datetime, timezone
    from .database import connection, init_database
    init_database()
    cleaned_node = str(node_id or "").strip()[:32]
    if not NODE_ID_RE.match(cleaned_node):
        raise PlaySessionRefusedError(
            "node_id must look like stump-1")
    prefix = cleaned_node.rsplit("-", 1)[0]
    item = NODE_YIELDS.get(prefix)
    if item is None:
        raise PlaySessionRefusedError(
            f"Unknown node '{cleaned_node}'")
    with connection() as db:
        cleaned = _require_session(db, session_id)
        row = db.execute(
            "SELECT gathered_at FROM play_gather WHERE "
            "session_id=? AND node_id=?",
            (cleaned, cleaned_node)).fetchone()
        if row is not None:
            try:
                last = datetime.fromisoformat(
                    str(row["gathered_at"] or ""))
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - last
                       ).total_seconds()
            except (ValueError, TypeError):
                age = GATHER_COOLDOWN_S
            if age < GATHER_COOLDOWN_S:
                wait = int(GATHER_COOLDOWN_S - age)
                raise PlaySessionRefusedError(
                    f"Node rust nog {wait}s uit")
        stamp = _utc_now()
        db.execute("INSERT INTO play_gather (session_id, "
                   "node_id, gathered_at) VALUES (?, ?, ?) "
                   "ON CONFLICT(session_id, node_id) DO UPDATE "
                   "SET gathered_at=excluded.gathered_at",
                   (cleaned, cleaned_node, stamp))
        qty = _add_item(db, cleaned, item, 1, stamp)
    return {"session_id": cleaned, "node_id": cleaned_node,
            "item": item, "qty": qty, "gathered": True}


def craft_recipe(session_id: str, recipe: str) -> dict:
    """Consume ingredients, add 1 crafted good. Unknown session
    -> KeyError; missing goods -> PlaySessionRefusedError."""
    from .database import connection, init_database
    init_database()
    cleaned_recipe = str(recipe or "").strip()[:32]
    needs = PLAY_RECIPES.get(cleaned_recipe)
    if needs is None:
        raise PlaySessionRefusedError(
            f"Unknown recipe '{cleaned_recipe}'")
    with connection() as db:
        cleaned = _require_session(db, session_id)
        for ingredient, amount in needs.items():
            if _inventory_qty(db, cleaned, ingredient) < amount:
                raise PlaySessionRefusedError(
                    f"Not enough {ingredient} "
                    f"(need {amount})")
        stamp = _utc_now()
        for ingredient, amount in needs.items():
            _add_item(db, cleaned, ingredient, -amount, stamp)
        qty = _add_item(db, cleaned, cleaned_recipe, 1, stamp)
    return {"session_id": cleaned, "recipe": cleaned_recipe,
            "qty": qty, "crafted": True}


def place_build(session_id: str, kind: str, x, y) -> dict:
    """Consume 1 placeable good, record a structure. Unknown
    session -> KeyError; out of bounds / nothing owned -> 422."""
    from .database import connection, init_database
    init_database()
    cleaned_kind = str(kind or "").strip()[:32]
    if cleaned_kind not in PLAY_PLACEABLE:
        raise PlaySessionRefusedError(
            f"Cannot place '{cleaned_kind}'")
    try:
        clean_x = max(0.0, min(float(x), SIDE_WORLD_W))
    except (TypeError, ValueError):
        raise PlaySessionRefusedError("x must be a number")
    try:
        clean_y = max(0.0, min(float(y), SIDE_WORLD_H))
    except (TypeError, ValueError):
        raise PlaySessionRefusedError("y must be a number")
    with connection() as db:
        cleaned = _require_session(db, session_id)
        if _inventory_qty(db, cleaned, cleaned_kind) < 1:
            raise PlaySessionRefusedError(
                f"No {cleaned_kind} to place")
        stamp = _utc_now()
        _add_item(db, cleaned, cleaned_kind, -1, stamp)
        build_id = f"bld_{_secrets.token_hex(8)}"
        db.execute("INSERT INTO play_builds (build_id, "
                   "session_id, kind, x, y, created_at) VALUES "
                   "(?, ?, ?, ?, ?, ?)",
                   (build_id, cleaned, cleaned_kind, clean_x,
                    clean_y, stamp))
        if cleaned_kind == "chest":
            db.execute("INSERT INTO play_chests (chest_id, "
                       "session_id, x, y, created_at) VALUES "
                       "(?, ?, ?, ?, ?)",
                       (build_id, cleaned, clean_x, clean_y,
                        stamp))
    return {"session_id": cleaned, "build_id": build_id,
            "kind": cleaned_kind, "x": clean_x, "y": clean_y,
            "placed": True}


# -- chests / NPC / flags / world clock (BIG55) ----------------------
# Game-owned persistence, same precedent as play_sessions: chests
# are world objects with server-validated contents; NPC assignment
# records valid houses (spawn requirements stay visible
# client-side); flags keep quest/encounter progress across
# refresh; the clock is game time (never wall-clock state).

FLAG_RE = _re.compile(r"^[a-z_]{1,40}$")
NPC_ID_RE = _re.compile(r"^[a-z]{2,20}$")


def _check_flag(flag: str) -> str:
    cleaned = str(flag or "").strip()[:40]
    if not FLAG_RE.match(cleaned):
        raise PlaySessionRefusedError(
            "flag must match ^[a-z_]{1,40}$")
    if cleaned not in PLAY_FLAGS:
        raise PlaySessionRefusedError(
            f"Unknown flag '{cleaned}'")
    return cleaned


def get_play_flags(session_id: str) -> dict:
    """Read-only flag set. Unknown session -> KeyError."""
    from .database import connection, init_database
    init_database()
    with connection() as db:
        cleaned = _require_session(db, session_id)
        rows = db.execute(
            "SELECT flag FROM play_flags WHERE session_id=?",
            (cleaned,)).fetchall()
    return {"session_id": cleaned,
            "flags": sorted(str(row["flag"]) for row in rows)}


def set_play_flag(session_id: str, flag: str) -> dict:
    """Idempotent flag set. Unknown session -> KeyError."""
    from .database import connection, init_database
    init_database()
    cleaned_flag = _check_flag(flag)
    with connection() as db:
        cleaned = _require_session(db, session_id)
        stamp = _utc_now()
        db.execute("INSERT INTO play_flags (session_id, flag, "
                   "set_at) VALUES (?, ?, ?) "
                   "ON CONFLICT(session_id, flag) DO UPDATE SET "
                   "set_at=excluded.set_at",
                   (cleaned, cleaned_flag, stamp))
    return {"session_id": cleaned, "flag": cleaned_flag,
            "set": True}


def get_chest(session_id: str, chest_id: str) -> dict:
    """Read-only chest contents. Foreign chests 404."""
    from .database import connection, init_database
    init_database()
    cleaned_chest = str(chest_id or "").strip()[:80]
    with connection() as db:
        cleaned = _require_session(db, session_id)
        row = db.execute(
            "SELECT * FROM play_chests WHERE chest_id=? AND "
            "session_id=?", (cleaned_chest, cleaned)).fetchone()
        if row is None:
            raise KeyError(f"Unknown chest '{cleaned_chest}'")
        items = db.execute(
            "SELECT item, qty FROM play_chest_items WHERE "
            "chest_id=? ORDER BY item", (cleaned_chest,)).fetchall()
    return {"chest_id": cleaned_chest, "x": float(row["x"] or 0),
            "y": float(row["y"] or 0),
            "items": {str(item["item"]): int(item["qty"] or 0)
                      for item in items}}


def move_chest_item(session_id: str, chest_id: str, item: str,
                    qty, to_chest: bool) -> dict:
    """Deposit (to_chest=True) or withdraw one item kind.
    Ownership, known items and quantities enforced."""
    from .database import connection, init_database
    init_database()
    cleaned_item = str(item or "").strip()[:32]
    if cleaned_item not in PLAY_ITEMS:
        raise PlaySessionRefusedError(
            f"Unknown item '{cleaned_item}'")
    try:
        amount = int(qty)
    except (TypeError, ValueError):
        raise PlaySessionRefusedError("qty must be an integer")
    if amount < 1 or amount > 99:
        raise PlaySessionRefusedError("qty must be 1..99")
    cleaned_chest = str(chest_id or "").strip()[:80]
    with connection() as db:
        cleaned = _require_session(db, session_id)
        row = db.execute(
            "SELECT chest_id FROM play_chests WHERE chest_id=? "
            "AND session_id=?",
            (cleaned_chest, cleaned)).fetchone()
        if row is None:
            raise KeyError(f"Unknown chest '{cleaned_chest}'")
        stamp = _utc_now()
        if to_chest:
            if _inventory_qty(db, cleaned, cleaned_item) < amount:
                raise PlaySessionRefusedError(
                    f"Not enough {cleaned_item}")
            _add_item(db, cleaned, cleaned_item, -amount, stamp)
            have = db.execute(
                "SELECT qty FROM play_chest_items WHERE "
                "chest_id=? AND item=?",
                (cleaned_chest, cleaned_item)).fetchone()
            total = (int(have["qty"] or 0) if have else 0) + amount
            db.execute("INSERT INTO play_chest_items (chest_id, "
                       "item, qty, updated_at) VALUES (?, ?, ?, ?) "
                       "ON CONFLICT(chest_id, item) DO UPDATE SET "
                       "qty=excluded.qty, "
                       "updated_at=excluded.updated_at",
                       (cleaned_chest, cleaned_item, total, stamp))
        else:
            have = db.execute(
                "SELECT qty FROM play_chest_items WHERE "
                "chest_id=? AND item=?",
                (cleaned_chest, cleaned_item)).fetchone()
            if have is None or int(have["qty"] or 0) < amount:
                raise PlaySessionRefusedError(
                    f"Chest holds no {amount}x {cleaned_item}")
            left = int(have["qty"]) - amount
            if left == 0:
                db.execute("DELETE FROM play_chest_items WHERE "
                           "chest_id=? AND item=?",
                           (cleaned_chest, cleaned_item))
            else:
                db.execute("UPDATE play_chest_items SET qty=?, "
                           "updated_at=? WHERE chest_id=? AND "
                           "item=?", (left, stamp, cleaned_chest,
                                      cleaned_item))
            _add_item(db, cleaned, cleaned_item, amount, stamp)
    return {"session_id": cleaned, "chest_id": cleaned_chest,
            "item": cleaned_item, "qty": amount,
            "deposited" if to_chest else "withdrawn": True}


def assign_npc(session_id: str, npc_id: str,
               house_build_id: str) -> dict:
    """Settle an NPC into a player-built room. The room build must
    exist and be kind 'room'; NPC must be known. Spawn
    requirements stay visible client-side; the server records
    only valid houses."""
    from .database import connection, init_database
    init_database()
    cleaned_npc = str(npc_id or "").strip()[:20]
    if not NPC_ID_RE.match(cleaned_npc) \
            or cleaned_npc not in PLAY_NPCS:
        raise PlaySessionRefusedError(
            f"Unknown NPC '{cleaned_npc}'")
    cleaned_house = str(house_build_id or "").strip()[:80]
    with connection() as db:
        cleaned = _require_session(db, session_id)
        room = db.execute(
            "SELECT kind FROM play_builds WHERE build_id=? AND "
            "session_id=?", (cleaned_house, cleaned)).fetchone()
        if room is None or str(room["kind"]) != "room":
            raise PlaySessionRefusedError(
                "House must be a placed room of this session")
        taken = db.execute(
            "SELECT npc_id FROM play_npc WHERE "
            "house_build_id=? AND session_id=?",
            (cleaned_house, cleaned)).fetchone()
        if taken is not None and str(taken["npc_id"]) != cleaned_npc:
            raise PlaySessionRefusedError(
                "Room already houses another NPC")
        stamp = _utc_now()
        db.execute("INSERT INTO play_npc (npc_id, session_id, "
                   "house_build_id, status, updated_at) VALUES "
                   "(?, ?, ?, 'settled', ?) "
                   "ON CONFLICT(npc_id, session_id) DO UPDATE SET "
                   "house_build_id=excluded.house_build_id, "
                   "status='settled', "
                   "updated_at=excluded.updated_at",
                   (cleaned_npc, cleaned, cleaned_house, stamp))
    return {"session_id": cleaned, "npc_id": cleaned_npc,
            "house_build_id": cleaned_house, "settled": True}


def list_npc(session_id: str) -> dict:
    """Read-only settlement state. Unknown session -> KeyError."""
    from .database import connection, init_database
    init_database()
    with connection() as db:
        cleaned = _require_session(db, session_id)
        rows = db.execute(
            "SELECT npc_id, house_build_id, status FROM play_npc "
            "WHERE session_id=? ORDER BY npc_id",
            (cleaned,)).fetchall()
    return {"session_id": cleaned,
            "npc": [{"npc_id": str(row["npc_id"]),
                     "house_build_id": str(row["house_build_id"]),
                     "status": str(row["status"])}
                    for row in rows]}


def tick_clock(session_id: str) -> dict:
    """Advance game time +10 min, at most once per 60s wall time.
    Day/phase derive; never wall-clock state."""
    from datetime import datetime, timezone
    from .database import connection, init_database
    init_database()
    with connection() as db:
        cleaned = _require_session(db, session_id)
        row = db.execute(
            "SELECT day, minute, updated_at FROM world_clock "
            "WHERE session_id=?", (cleaned,)).fetchone()
        stamp = _utc_now()
        if row is None:
            day, minute = 1, 480
            db.execute("INSERT INTO world_clock (session_id, "
                       "day, minute, updated_at) VALUES (?, ?, "
                       "?, ?)", (cleaned, day, minute, stamp))
            return {"session_id": cleaned, "day": day,
                    "minute": minute, "phase": _clock_phase(minute),
                    "advanced": False}
        try:
            last = datetime.fromisoformat(
                str(row["updated_at"] or ""))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - last
                   ).total_seconds()
        except (ValueError, TypeError):
            age = CLOCK_TICK_INTERVAL_S
        day, minute = int(row["day"] or 1), int(row["minute"] or 0)
        if age < CLOCK_TICK_INTERVAL_S:
            return {"session_id": cleaned, "day": day,
                    "minute": minute, "phase": _clock_phase(minute),
                    "advanced": False}
        minute += CLOCK_TICK_MINUTES
        if minute >= CLOCK_DAY_MINUTES:
            minute -= CLOCK_DAY_MINUTES
            day += 1
        db.execute("UPDATE world_clock SET day=?, minute=?, "
                   "updated_at=? WHERE session_id=?",
                   (day, minute, stamp, cleaned))
    return {"session_id": cleaned, "day": day, "minute": minute,
            "phase": _clock_phase(minute), "advanced": True}


def _clock_phase(minute: int) -> str:
    if 360 <= minute < 1080:
        return "day"
    if 1080 <= minute < 1320:
        return "dusk"
    if minute >= 1320 or minute < 120:
        return "night"
    return "dawn"


NOTE_KEY_RE = _re.compile(r"^[a-z0-9_]{1,40}$")


def get_play_notes(session_id: str) -> dict:
    """Read-only quest notes. Unknown session -> KeyError."""
    from .database import connection, init_database
    init_database()
    with connection() as db:
        cleaned = _require_session(db, session_id)
        rows = db.execute(
            "SELECT note_key, text, priority FROM play_notes "
            "WHERE session_id=? ORDER BY priority DESC, note_key",
            (cleaned,)).fetchall()
    return {"session_id": cleaned,
            "notes": [{"key": str(row["note_key"]),
                       "text": str(row["text"] or "")[:500],
                       "priority": int(row["priority"] or 0)}
                      for row in rows]}


def set_play_note(session_id: str, key: str, text,
                  priority=False) -> dict:
    """Upsert one quest note (max 500 chars). Unknown -> KeyError."""
    from .database import connection, init_database
    init_database()
    cleaned_key = str(key or "").strip()[:40]
    if not NOTE_KEY_RE.match(cleaned_key):
        raise PlaySessionRefusedError(
            "note key must match ^[a-z0-9_]{1,40}$")
    cleaned_text = str(text or "")[:500]
    prio = 1 if priority in (True, 1, "1") else 0
    with connection() as db:
        cleaned = _require_session(db, session_id)
        stamp = _utc_now()
        db.execute("INSERT INTO play_notes (session_id, "
                   "note_key, text, priority, updated_at) VALUES "
                   "(?, ?, ?, ?, ?) "
                   "ON CONFLICT(session_id, note_key) DO UPDATE SET "
                   "text=excluded.text, priority=excluded.priority,"
                   "updated_at=excluded.updated_at",
                   (cleaned, cleaned_key, cleaned_text, prio,
                    stamp))
    return {"session_id": cleaned, "key": cleaned_key,
            "priority": prio, "saved": True}


# -- journal / command center (BIG50) -----------------------------------
# Read-only ranked view over EXISTING stores: one active mission,
# waiting approvals, open quests, open research, open candidates.
# No new tables, no new missions, no approvals here — actions are
# described (label + method + path) so the game can call the
# existing endpoints. Never raises (best-effort per section).

_TERMINAL_RUN_STATES = frozenset(
    {"completed", "blocked", "failed", "cancelled", "unavailable"})


# BIG51 — game-first Journal: echte INVENTory-projecten (GAPMATRIX
# F1) en onthouden kennis (GAPMATRIX F2) als read-only compositie.
# Geen nieuwe tabellen, geen nieuwe missies, geen approvals:
# acties beschrijven alleen bestaande endpoints. Brainstormideeën
# worden nooit missies; projecten worden nooit verzonnen
# (offline → UNAVAILABLE, leeg → eerlijk leeg).

#: Uitleg per INVENTory-projectstatus (bronrecord blijft leidend).
_PROJECT_WHY = {
    "idea": "Idee — richting, nog geen plan.",
    "planned": "Voorgesteld — nog niet gestart.",
    "active": "Loopt — echte voortgang leeft in INVENTory.",
    "paused": "Gepauzeerd — wacht op mens of middel.",
    "completed": "Afgerond — bewijs staat in INVENTory.",
    "archived": "Gearchiveerd — alleen naslag.",
}

#: Bridge-grens (zelfde als inventory_read): nooit meer dan 5s.
_INVENTORY_TIMEOUT = 5.0


def _default_inventory_projects() -> dict:
    """Echte proj_-records via GET-only loopback.

    Retourneert altijd een dict met state ok|empty|unavailable —
    nooit een uitzondering, nooit verzonnen projecten. Dezelfde
    grenzen als de bestaande bridge: HTTP GET only, loopback hosts
    only (gevalideerd via inventory_read), timeout ≤ 5s, redirects
    nooit gevolgd.
    """
    try:
        import os

        import httpx

        from .inventory_read import _validate_base_url as _check_url
        base = _check_url(os.environ.get(
            "INVENTORY_BASE_URL", "http://127.0.0.1:8080"))
        with httpx.Client(timeout=min(_INVENTORY_TIMEOUT, 5.0),
                          follow_redirects=False) as client:
            response = client.get(f"{base}/api/v1/projects")
        if response.status_code == 404:
            return {"state": "unavailable",
                    "reason": "INVENTory kent geen projectcollectie",
                    "items": []}
        if response.status_code != 200:
            return {"state": "unavailable",
                    "reason": f"INVENTory HTTP {response.status_code}",
                    "items": []}
        try:
            data = response.json()
        except ValueError:
            return {"state": "unavailable",
                    "reason": "INVENTory gaf ongeldige JSON",
                    "items": []}
        if not isinstance(data, list):
            return {"state": "unavailable",
                    "reason": "INVENTory gaf ongeldige JSON",
                    "items": []}
        items = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            pid = str(entry.get("id", ""))
            if not pid.startswith("proj_"):
                continue
            status = str(entry.get("status", "planned"))
            href = f"/world?entity_id={pid}&depth=1"
            items.append({
                "kind": "project",
                "id": pid,
                "title": str(entry.get("name", pid))[:160],
                "status": status,
                "href": href,
                "why": _PROJECT_WHY.get(
                    status,
                    "INVENTory-project — status uit bronrecord."),
                "action": _journal_link("Inspecteren", href),
                "source": pid,
            })
            if len(items) >= 5:
                break
        if not items:
            return {"state": "empty",
                    "reason": "Geen projecten in INVENTory "
                              "(lege wereld) — niets verzonnen.",
                    "items": []}
        return {"state": "ok", "reason": "", "items": items}
    except Exception as error:
        return {"state": "unavailable",
                "reason": f"INVENTory onbereikbaar "
                          f"({str(error)[:120]})",
                "items": []}


def _journal_knowledge() -> tuple[list[dict], dict]:
    """Voltooide dossiers + onthouden memories (bestaande records).

    Alleen dossiers met echte inhoud (completed/REAL/TEST met
    bronnen of claims) — verder niets. Memory is de bestaande
    auto-remember (external_source, interpretatie, nooit feit).
    """
    entries: list[dict] = []
    counts = {"dossiers_completed": 0, "memories_remembered": 0,
              "memories_test": 0, "memories_real": 0}
    try:
        from .research_engine import list_dossiers, load_run
        for dossier in list_dossiers(limit=10) or []:
            state = str(getattr(dossier, "execution_state", ""))
            if state not in ("completed", "REAL", "TEST"):
                continue
            if not getattr(dossier, "sources", None) \
                    and not getattr(dossier, "claims", None):
                continue
            counts["dossiers_completed"] += 1
            memory_id = ""
            try:
                run = load_run(str(getattr(dossier, "run_id", "")))
                if run is not None:
                    memory_id = str(getattr(run, "memory_id", "")
                                    or "")
            except Exception:
                memory_id = ""
            if memory_id:
                counts["memories_remembered"] += 1
            # BIG52: herkomst expliciet — TEST-sporen zijn proef,
            # nooit geverifieerde kennis. Zelfs REAL blijft
            # external_source-interpretatie, nooit feit. Onbekende
            # labels krijgen geen REAL-bewijs en tellen als proef.
            is_test = (state != "REAL")
            if memory_id and not is_test:
                counts["memories_real"] += 1
            elif memory_id:
                counts["memories_test"] += 1
            entries.append({
                "kind": "knowledge",
                "id": str(getattr(dossier, "dossier_id", "")),
                "title": str(getattr(dossier, "title", "")
                             or getattr(dossier, "question", ""))[:160],
                "status": state,
                "origin": state,
                "href": "/research",
                "why": (f"Proefherkomst {state} — interpretatie, "
                        f"nooit feit; bouw er geen vertrouwen op. "
                        f"Onthouden als {memory_id}."
                        if memory_id and is_test else
                        f"Herkomst REAL — nog steeds "
                        f"external_source-interpretatie, geen "
                        f"geverifieerd feit. "
                        f"Onthouden als {memory_id}."
                        if memory_id else
                        "Afgerond dossier — nog niet onthouden "
                        "als geheugen."),
                "action": (_journal_link("Geheugen", "/memory")
                           if memory_id else
                           _journal_link("Openen", "/research")),
                "memory_id": memory_id,
                "source": str(getattr(dossier, "run_id", "")),
            })
            if len(entries) >= 3:
                break
    except Exception:
        pass
    return entries, counts


# BIG52 — resterende weg als game-questlijn (GAPMATRIX F3–F5).
#
# Modelgat (eerlijk gerapporteerd, geen data toegevoegd): Quest en
# Campaign kunnen een ontwikkelbacklog NIET bijhouden. Quest-steps
# dragen geen eigen staat; `note`-steps zonder ref zijn permanent
# MISSING (`derive_step_state`: "note without linked record", en
# zelfs mét ref blijft een note MISSING), `entity`-steps blijven
# WAITING en missie/task-steps eisten een ECHT record. Een Quest
# voor "nog te bouwen werk" zou dus nooit COMPLETE kunnen worden —
# voltooiing zou verzonnen zijn. Missies aanmaken voor F3–F5 zou
# uitvoerbare missies verzinnen (verboden); brainstormideeën horen
# nergens thuis als quests.
#
# Kleinste bestaande-model-oplossing: deze read-only questlijn in
# het Journal — een VIEW over code/docs-waarheid, geen tweede
# backlogdatabase, geen nieuwe records. Status per item is
# ontwikkelwerk-status (open/in uitvoering) met live bewijs uit
# bestaande reads; nooit een verzonnen voltooiing. Operationele
# missies blijven in de bestaande missie-secties staan.

def _journal_roadmap() -> tuple[list[dict], dict]:
    """GAPMATRIX F3–F5 als questlijn. Alleen lezen; bewijs uit
    bestaande stores/routes; bron per item."""
    items: list[dict] = []
    counts = {"roadmap_open": 0}
    evidence = ""
    try:
        chain = fabrication_chain() or []
        tallies: dict[str, int] = {}
        for step in chain:
            state = str(step.get("state", "?"))
            tallies[state] = tallies.get(state, 0) + 1
        if tallies:
            evidence = ("keten live: " + ", ".join(
                f"{state} {num}" for state, num in sorted(
                    tallies.items())))
    except Exception:
        evidence = ""
    open_runs = 0
    try:
        from .automation import list_runs
        open_runs = len([run for run in list_runs(limit=50) or []
                         if str(getattr(run, "status", ""))
                         not in ("completed", "failed",
                                 "cancelled")])
    except Exception:
        open_runs = 0
    items = [
        {"kind": "roadmap", "id": "gap-F3",
         "title": "F3 — Werkbank toont live fabricageketen",
         "status": "in uitvoering",
         "href": "/side",
         "why": ("Ontwikkelwerk (geen record — voortgang staat "
                 "in code, niet in een backend-tabel). "
                 + (evidence + ". " if evidence else "") +
                 "Open de werkbank in de wereld voor de "
                 "read-only keten."),
         "action": _journal_link("Werkbank", "/side"),
         "source": "GAPMATRIX F3 + docs/fabrication.md"},
        {"kind": "roadmap", "id": "gap-F4",
         "title": "F4 — Automation-drive vanuit Journal-missie",
         "status": "in uitvoering",
         "href": "/automation",
         "why": (f"Deels gedaan (M1): Journal-missies hebben "
                 f"dispatch/drive-acties (tick, dispatch van de "
                 f"huidige stap, drive van gelinkte runs) op "
                 f"bestaande routes; nu {open_runs} open run(s). "
                 f"Resterend: runs zonder missie-link blijven "
                 f"alleen via /automation drijfbaar."),
         "action": _journal_link("Automation", "/automation"),
         "source": "GAPMATRIX F4 + docs/living-automation.md"},
        {"kind": "roadmap", "id": "gap-F5",
         "title": "F5 — Terraria-skin over ongewijzigde data",
         "status": "open",
         "href": "/canvas",
         "why": ("Ontwikkelwerk, presentatie-only (geen record, "
                 "geen datawijziging). Volgende actie: "
                 "tiles/sprites-skin over bestaande views."),
         "action": _journal_link("Canvas", "/canvas"),
         "source": "GAPMATRIX F5 + MYCELIUM_CANVAS_DIRECTION.md"},
    ]
    counts["roadmap_open"] = len(items)
    return items, counts


def _journal_action(label: str, method: str, path: str,
                    body: dict | None = None) -> dict:
    """Eén Journal-actie: bestaande route, bestaande gate.

    Alleen label/method/path(+optionele JSON-body voor routes die
    een body eisen, zoals dispatch met step_id of drive met
    budget_steps). Voert niets uit — de game POST het pad, de
    bestaande route + gate beslist.
    """
    action: dict = {"label": label, "method": method, "path": path}
    if body is not None:
        action["body"] = dict(body)
    return action


def _journal_drive_actions(mission_id: str, step) -> list[dict]:
    """M1 (BIG56): dispatch + automation-drive naast tick.

    Alleen acties op bestaande routes met bestaande gates:
    - dispatch van de huidige stap (alleen dispatchable kind en
      niet-terminaal; de route weigert de rest met 409/422);
    - drive van gelinkte open automation-runs (max 2; de route
      hercontroleert alles at drive time).
    Nooit iets voor pending/draft-missies: zonder exacte YES
    bestaat er geen drive (de routes weigeren unapproved).
    """
    linked: list[dict] = []
    try:
        from .automation import list_runs
        for run in list_runs(limit=50) or []:
            if str(getattr(run, "mission_id", "") or "") != mission_id:
                continue
            state = str(getattr(run, "state", "")
                        or getattr(run, "status", "") or "")
            if state in ("completed", "failed", "cancelled"):
                continue
            linked.append(_journal_action(
                f"Drive automation ({state or 'open'})", "POST",
                f"/api/v1/automation/runs/{run.run_id}/drive",
                {"budget_steps": 10}))
            if len(linked) >= 2:
                break
    except Exception:
        linked = []
    return linked


def _journal_link(label: str, href: str) -> dict:
    return {"label": label, "method": "GET", "path": href}


def play_journal(inventory_fetcher=None) -> dict:
    """Ranked priorities + active mission for the in-game Journal.

    inventory_fetcher is alleen een testhaak (default: echte
    GET-only loopback bridge). Een fetcher retourneert dezelfde
    vorm als _default_inventory_projects."""
    out: dict = {"active": None, "waiting": [], "quests": [],
                 "research": [], "candidates": [], "projects": [],
                 "knowledge": [], "roadmap": [],
                 "inventory": {"state": "unknown", "reason": ""},
                 "counts": {}}
    try:
        from .missions import (DISPATCHABLE_KINDS, current_step_of,
                               list_missions)
        actives = []
        waiting = []
        for mission in list_missions(limit=50) or []:
            status = str(mission.status or "")
            if status in ("approved", "running"):
                actives.append(mission)
            elif status in ("pending_approval", "draft"):
                waiting.append(mission)
        out["counts"]["missions_active"] = len(actives)
        out["counts"]["missions_waiting"] = len(waiting)
        if actives:
            mission = actives[0]
            mission_id = str(mission.mission_id or "")
            try:
                step = current_step_of(mission)
            except Exception:
                step = None
            done = sum(1 for entry in mission.steps
                       if str(entry.status) in ("completed", "skipped"))
            tick = _journal_action(
                "Tik om te drijven", "POST",
                f"/api/v1/missions/{mission_id}/tick")
            actions = [tick]
            step_id = ""
            step_kind = ""
            step_status = ""
            if step is not None:
                step_id = str(getattr(step, "step_id", "") or "")
                step_kind = str(getattr(step, "kind", "") or "")
                step_status = str(getattr(step, "status", "") or "")
                if (step_id and step_kind in DISPATCHABLE_KINDS
                        and step_status not in ("completed", "skipped",
                                                "failed")):
                    actions.append(_journal_action(
                        "Dispatch stap naar queue", "POST",
                        f"/api/v1/missions/{mission_id}/dispatch",
                        {"step_id": step_id}))
            actions.extend(_journal_drive_actions(mission_id, step))
            out["active"] = {
                "kind": "mission",
                "id": mission_id,
                "title": str(mission.goal or "")[:160],
                "status": str(mission.status or ""),
                "progress": f"{done}/{len(mission.steps)}",
                "href": f"/missions/{mission_id}",
                "step": ({
                    "step_id": step_id,
                    "kind": step_kind,
                    "description": str(
                        step.description or "")[:160],
                    "status": step_status,
                } if step is not None else None),
                "why": "Actieve missie: tik drijft goedgekeurd werk "
                       "tot de eerstvolgende gate; dispatch zet de "
                       "huidige stap als queue-taak klaar voor een "
                       "node.",
                "action": tick,
                "actions": actions,
            }
        for mission in waiting[:3]:
            status = str(mission.status or "")
            out["waiting"].append({
                "kind": "mission",
                "id": str(mission.mission_id or ""),
                "title": str(mission.goal or "")[:160],
                "status": status,
                "href": f"/missions/{mission.mission_id}",
                "why": ("Wacht op exacte YES — niets start vanzelf."
                        if status == "pending_approval" else
                        "Concept — beschikbaar, geen voortgang."),
                "action": (_journal_action(
                    "YES — starten", "POST",
                    f"/api/v1/missions/{mission.mission_id}/approve")
                    if status == "pending_approval" else
                    _journal_link("Openen",
                                  f"/missions/{mission.mission_id}")),
            })
    except Exception:
        pass
    try:
        from .quests import list_quest_details
        opened = []
        for detail in list_quest_details(limit=20) or []:
            if str(detail.get("state", "")) == "COMPLETED":
                continue
            opened.append({
                "kind": "quest",
                "id": str(detail.get("quest_id", "")),
                "title": str(detail.get("title", ""))[:160],
                "status": str(detail.get("state", "")),
                "progress": str(detail.get("progress", "")),
                "href": "/quests",
                "why": "Open quest: voortgang komt uit echte "
                       "onderliggende records.",
                "action": _journal_link("Openen", "/quests"),
            })
            if len(opened) >= 5:
                break
        out["quests"] = opened
        out["counts"]["quests_open"] = len(opened)
    except Exception:
        pass
    try:
        from .research_engine import list_runs
        opened = []
        for run in list_runs(limit=20) or []:
            status = str(getattr(run, "status", "") or "")
            if status in _TERMINAL_RUN_STATES:
                continue
            opened.append({
                "kind": "research",
                "id": str(getattr(run, "run_id", "")),
                "title": str(getattr(
                    run, "question", ""))[:160],
                "status": status,
                "href": "/research",
                "why": "Open onderzoek: uitvoeren draait de echte "
                       "provider.",
                "action": _journal_link("Openen", "/research"),
            })
            if len(opened) >= 3:
                break
        out["research"] = opened
        out["counts"]["research_open"] = len(opened)
    except Exception:
        pass
    try:
        from .knowledge import ACTIVE_STATES, list_candidates
        opened = []
        for cand in list_candidates(limit=30) or []:
            if str(cand.state or "") not in ACTIVE_STATES:
                continue
            opened.append({
                "kind": "candidate",
                "id": str(cand.candidate_id or ""),
                "title": str(cand.title or "")[:160],
                "status": str(cand.state or ""),
                "href": "/knowledge",
                "why": "Open vondst: support telt (2 nodig), "
                       "promote maakt geheugen.",
                "action": _journal_link("Openen", "/knowledge"),
            })
            if len(opened) >= 5:
                break
        out["candidates"] = opened
        out["counts"]["candidates_open"] = len(opened)
    except Exception:
        pass
    try:
        fetch = inventory_fetcher or _default_inventory_projects
        section = fetch() or {}
        items = section.get("items", []) or []
        out["projects"] = items
        out["inventory"] = {
            "state": str(section.get("state", "unavailable")),
            "reason": str(section.get("reason", ""))[:200],
        }
        out["counts"]["projects_open"] = len(items)
    except Exception as error:
        out["projects"] = []
        out["inventory"] = {
            "state": "unavailable",
            "reason": f"INVENTory onbereikbaar ({str(error)[:120]})",
        }
        out["counts"]["projects_open"] = 0
    knowledge, kcounts = _journal_knowledge()
    out["knowledge"] = knowledge
    out["counts"].update(kcounts)
    roadmap, rcounts = _journal_roadmap()
    out["roadmap"] = roadmap
    out["counts"].update(rcounts)
    return out
