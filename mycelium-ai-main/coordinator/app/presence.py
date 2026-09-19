"""Presence ecosystem (BIG #40): what deserves Jelles' attention.

One unified attention layer over existing stores — no duplicate
state. Every item is derived live from approvals, missions,
nodes, telemetry, research, candidates, conversations, cameras,
craft, symbiosis, automation and fabrication. The ONLY thing
presence stores is the operator's own triage (SEEN/DEFERRED) in
the chat DB; everything else is read fresh on every call.

Attention item:
  {id, type, band, priority, priority_reasons, title, reason,
   source, related_entity, related_mission, related_task,
   action, open_href, created_at, updated_at, status,
   provenance}

Bands (display categories, not authority):
  needs (NEEDS YOU), waiting (WAITING), available (AVAILABLE),
  discovered (DISCOVERED), offline (OFFLINE).

Statuses:
  NEW / ACTIONABLE — derived from live sources.
  SEEN / DEFERRED — operator triage (stored; DEFER performs
    nothing, it only hides the item from NEEDS).
  RESOLVED — override exists but the source cleared (shown
    briefly from the stored snapshot, then pruned).
  EXPIRED — a DEFERRED item older than 7 days.

Priority is deterministic and rule-based (never an LLM):
base score per type + age bonus (1/hour, capped at +24), with
every point explained in priority_reasons. Same store state
always yields the same order.

Security: item ids are stable derivations of real ids
(`att_<kind>_<real_id>`); triage of an id that is not
currently derived is refused (fake ids, fake missions, replay
all fail). Presence never approves, executes, or grants
authority — YES/NO always travel through the existing gates.
All display text is clipped; rendering escapes via ui.esc.
Health content is never pulled in. Node capabilities are shown
as advertisements ("advertises X"), never as attestations.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

STATUSES = frozenset({
    "NEW", "SEEN", "DEFERRED", "ACTIONABLE", "RESOLVED", "EXPIRED",
})

BANDS = ("needs", "waiting", "available", "discovered", "offline")

BAND_META = {
    "needs": {"glyph": "🔴", "title": "NEEDS YOU"},
    "waiting": {"glyph": "🟡", "title": "WAITING"},
    "available": {"glyph": "🟢", "title": "AVAILABLE"},
    "discovered": {"glyph": "🔵", "title": "DISCOVERED"},
    "offline": {"glyph": "⚫", "title": "OFFLINE"},
}

#: Closed attention types. Band is the display category.
ITEM_TYPES = frozenset({
    "approval_desktop", "approval_write", "approval_mission",
    "mission_blocked", "mission_failed", "mission_waiting",
    "automation_waiting", "automation_failed",
    "fabrication_waiting", "fabrication_blocked",
    "node_offline", "node_stale", "telemetry_stale",
    "hardware_offline", "hardware_available",
    "capability_available", "research_finding",
    "research_waiting", "candidate_new", "contradiction",
    "observation_inbox", "discovery", "symbiosis_proposed",
    "craft_gap", "task_failed",
    # BIG #42 ecosystem hardening: unverified hardware,
    # blocked quest trails, pending finance, unknown energy.
    "hardware_unverified", "quest_blocked", "finance_pending",
    "energy_unknown",
})

TYPE_BAND = {
    "approval_desktop": "needs",
    "approval_write": "needs",
    "approval_mission": "needs",
    "mission_blocked": "needs",
    "mission_failed": "needs",
    "mission_waiting": "waiting",
    "automation_waiting": "needs",
    "automation_failed": "needs",
    "fabrication_waiting": "waiting",
    "fabrication_blocked": "needs",
    "node_offline": "offline",
    "node_stale": "offline",
    "telemetry_stale": "waiting",
    "hardware_offline": "offline",
    "hardware_available": "available",
    "capability_available": "available",
    "research_finding": "discovered",
    "research_waiting": "waiting",
    "candidate_new": "discovered",
    "contradiction": "waiting",
    "observation_inbox": "discovered",
    "discovery": "discovered",
    "symbiosis_proposed": "discovered",
    "craft_gap": "waiting",
    "task_failed": "needs",
    "hardware_unverified": "waiting",
    "quest_blocked": "needs",
    "finance_pending": "waiting",
    "energy_unknown": "waiting",
}

#: Deterministic base scores. Higher = more urgent.
BASE_SCORE = {
    "approval_desktop": 100,
    "approval_write": 100,
    "approval_mission": 100,
    "mission_blocked": 90,
    "mission_failed": 90,
    "task_failed": 90,
    "automation_failed": 90,
    "fabrication_blocked": 90,
    "automation_waiting": 85,
    "node_offline": 80,
    "fabrication_waiting": 70,
    "mission_waiting": 65,
    "node_stale": 60,
    "hardware_offline": 55,
    "telemetry_stale": 50,
    "contradiction": 50,
    "research_finding": 45,
    "research_waiting": 45,
    "candidate_new": 35,
    "observation_inbox": 30,
    "craft_gap": 30,
    "discovery": 25,
    "symbiosis_proposed": 25,
    "hardware_available": 20,
    "capability_available": 20,
    "hardware_unverified": 48,
    "finance_pending": 40,
    "energy_unknown": 40,
    "quest_blocked": 88,
}

BASE_WHY = {
    "approval_desktop": "human approval required",
    "approval_write": "human approval required",
    "approval_mission": "human approval required",
    "mission_blocked": "mission blocked",
    "mission_failed": "mission failed",
    "task_failed": "task failed",
    "automation_failed": "automation failed",
    "fabrication_blocked": "fabrication blocked",
    "automation_waiting": "automation waits for human",
    "node_offline": "node offline",
    "fabrication_waiting": "fabrication waits for a next step",
    "mission_waiting": "mission paused, waits for resume",
    "node_stale": "node stale",
    "hardware_offline": "registered hardware disconnected",
    "telemetry_stale": "telemetry older than 5 minutes",
    "contradiction": "unresolved contradiction",
    "research_finding": "new research finding",
    "research_waiting": "research waits for a capable node",
    "candidate_new": "new candidate waits for review",
    "observation_inbox": "new camera material",
    "craft_gap": "craft chain has a gap",
    "discovery": "new discovery",
    "symbiosis_proposed": "symbiosis proposed",
    "hardware_available": "hardware available",
    "capability_available": "capability available",
    "hardware_unverified": "hardware advertised but not verified",
    "finance_pending": "finance record waits for confirmation",
    "energy_unknown": "energy state unknown",
    "quest_blocked": "quest trail blocked",
}

MAX_ITEMS = 120
MAX_TITLE = 140
MAX_REASON = 240
MAX_TEXT = 160

ITEM_ID_PATTERN = re.compile(r"^att_[A-Za-z0-9_.:-]+$")
MAX_ITEM_ID = 160

TRIAGE_TTL_DAYS = 7
TRIAGE_PRUNE_DAYS = 30


class PresenceRefusedError(ValueError):
    """Presence refused; nothing was stored, nothing was done."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(text, limit: int = MAX_TEXT) -> str:
    return " ".join(str(text or "").split())[:limit]


def _parse_time(value: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value or ""))
    except (ValueError, TypeError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _age_hours(created_at: str) -> int:
    moment = _parse_time(created_at)
    if moment is None:
        return 0
    delta = datetime.now(timezone.utc) - moment
    if delta.total_seconds() < 0:
        return 0
    return int(delta.total_seconds() // 3600)


def score_item(item_type: str, created_at: str = "",
               extra: int = 0) -> tuple[int, list[str]]:
    """Deterministic priority + human-readable reasons.

    Pure function (no I/O): base score per closed type, +1 per
    hour of age capped at +24, plus an explicit extra with the
    caller's reason appended by the caller. Same inputs always
    yield the same output.
    """
    if item_type not in ITEM_TYPES:
        raise PresenceRefusedError(
            f"Unknown attention type '{item_type}'")
    base = BASE_SCORE.get(item_type, 10)
    reasons = [f"{BASE_WHY.get(item_type, item_type)} (+{base})"]
    age = _age_hours(created_at)
    bonus = min(24, age)
    if bonus:
        reasons.append(f"waiting {age}h (+{bonus})")
    if extra:
        reasons.append(f"linked strain (+{extra})")
    return base + bonus + extra, reasons


def _item(item_id: str, item_type: str, title: str, reason: str,
          source: str, action: dict | None = None,
          open_href: str = "", related_entity: str = "",
          related_mission: str = "", related_task: str = "",
          created_at: str = "", updated_at: str = "",
          extra_score: int = 0,
          extra_reason: str = "") -> dict:
    if item_type not in ITEM_TYPES:
        raise PresenceRefusedError(
            f"Unknown attention type '{item_type}'")
    if (not re.match(ITEM_ID_PATTERN, item_id)
            or len(item_id) > MAX_ITEM_ID):
        raise PresenceRefusedError(
            "Attention id must be att_<real-id>")
    priority, reasons = score_item(item_type, created_at,
                                   extra_score)
    if extra_reason:
        reasons.append(extra_reason)
    return {
        "id": item_id,
        "type": item_type,
        "band": TYPE_BAND[item_type],
        "priority": priority,
        "priority_reasons": reasons,
        "title": _clip(title, MAX_TITLE),
        "reason": _clip(reason, MAX_REASON),
        "source": _clip(source, 80),
        "related_entity": str(related_entity or "")[:100],
        "related_mission": str(related_mission or "")[:80],
        "related_task": str(related_task or "")[:80],
        "action": dict(action or {}),
        "open_href": str(open_href or "")[:200],
        "created_at": str(created_at or "")[:40],
        "updated_at": str(updated_at or created_at or "")[:40],
        "status": "ACTIONABLE" if action else "NEW",
        "provenance": {"source_type": "derived",
                       "creator_id": "presence-engine",
                       "human_verified": False},
    }


def _yes_no_open(yes_href: str, no_href: str,
                 open_href: str) -> dict:
    return {"YES": {"label": "YES", "href": yes_href,
                    "method": "POST"},
            "NO": {"label": "NO", "href": no_href,
                   "method": "POST"},
            "OPEN": {"label": "OPEN", "href": open_href,
                     "method": "GET"}}


def _open_defer(open_href: str) -> dict:
    return {"OPEN": {"label": "OPEN", "href": open_href,
                     "method": "GET"},
            "DEFER": {"label": "DEFER",
                      "href": "/api/v1/presence/defer",
                      "method": "POST"}}


# -- collectors (each best-effort, never raises) -------------------------------

def _collect_approvals(items: list) -> None:
    try:
        from . import main as _main
        status = _main.coordinator_status()
    except Exception:
        return
    approvals = status.get("pending_approvals", {})
    if not approvals:
        return
    try:
        desktop = _main._desktop_list(limit=20,
                                      status="pending_approval")
    except Exception:
        desktop = []
    for entry in desktop[:10]:
        try:
            record = entry.get("record", {})
            if isinstance(record, str):
                from .database import load
                record = load(record)
            action = record.get("action", {})
            action_id = str(action.get("action_id", ""))
            if not action_id:
                continue
            items.append(_item(
                f"att_approval_desktop_{action_id}",
                "approval_desktop",
                f"Desktop action waits: "
                f"{action.get('action_type', '?')}",
                str((action.get("parameters", {}) or {}).get(
                    "reason", "The desktop agent proposed one "
                    "bounded step.")),
                "desktop agent proposal",
                action=_yes_no_open(
                    f"/web/desktop/{action_id}/decision",
                    f"/web/desktop/{action_id}/decision",
                    "/agents"),
                open_href="/agents",
                created_at=str(entry.get("created_at", "")),
                updated_at=str(entry.get("created_at", ""))))
        except Exception:
            continue
    try:
        writes = [item for item in _main._write_list(limit=30)
                  if item.get("status") == "proposed"]
    except Exception:
        writes = []
    for entry in writes[:10]:
        try:
            proposal_id = str(entry.get("proposal_id", ""))
            if not proposal_id:
                continue
            items.append(_item(
                f"att_approval_write_{proposal_id}",
                "approval_write",
                f"Write proposal waits: "
                f"{entry.get('summary', '?')}",
                "A flow proposed a persistent or physical "
                "change and stopped for your decision.",
                "writes inbox proposal",
                action=_yes_no_open(
                    f"/web/writes/{proposal_id}/approve",
                    f"/web/writes/{proposal_id}/approve",
                    "/writes"),
                open_href="/writes",
                created_at=str(entry.get("created_at", "")),
                updated_at=str(entry.get("created_at", ""))))
        except Exception:
            continue
    try:
        from .missions import list_missions
        missions = [m for m in list_missions(limit=30)
                    if m.status == "pending_approval"]
    except Exception:
        missions = []
    for mission in missions[:10]:
        try:
            items.append(_item(
                f"att_approval_mission_{mission.mission_id}",
                "approval_mission",
                f"Mission waits: {mission.goal}",
                "A plan waits inside an approved-plan boundary. "
                "YES starts it; each consequential step asks "
                "again.",
                "mission plan",
                action=_yes_no_open(
                    f"/web/missions/{mission.mission_id}/approve",
                    f"/web/missions/{mission.mission_id}/cancel",
                    f"/missions/{mission.mission_id}"),
                open_href=f"/missions/{mission.mission_id}",
                related_mission=mission.mission_id,
                created_at=str(getattr(
                    mission, "created_at", "")),
                updated_at=str(getattr(
                    mission, "created_at", ""))))
        except Exception:
            continue


def _collect_missions(items: list) -> None:
    try:
        from .missions import list_missions
        missions = list_missions(limit=50)
    except Exception:
        return
    for mission in missions:
        try:
            status = str(mission.status or "")
            if status == "blocked":
                items.append(_item(
                    f"att_mission_blocked_{mission.mission_id}",
                    "mission_blocked",
                    f"Mission blocked: {mission.goal}",
                    "A bound or refusal stopped the plan. "
                    "Inspect before re-driving.",
                    "mission control",
                    action=_open_defer(
                        f"/missions/{mission.mission_id}"),
                    open_href=f"/missions/{mission.mission_id}",
                    related_mission=mission.mission_id))
            elif status == "failed":
                items.append(_item(
                    f"att_mission_failed_{mission.mission_id}",
                    "mission_failed",
                    f"Mission failed: {mission.goal}",
                    "A step failed safely; nothing executed "
                    "beyond the plan.",
                    "mission control",
                    action=_open_defer(
                        f"/missions/{mission.mission_id}"),
                    open_href=f"/missions/{mission.mission_id}",
                    related_mission=mission.mission_id))
            elif status == "paused":
                items.append(_item(
                    f"att_mission_waiting_{mission.mission_id}",
                    "mission_waiting",
                    f"Mission paused: {mission.goal}",
                    "Paused work waits; pick this quest to wake "
                    "it up.",
                    "mission control",
                    action=_open_defer(
                        f"/missions/{mission.mission_id}"),
                    open_href=f"/missions/{mission.mission_id}",
                    related_mission=mission.mission_id))
        except Exception:
            continue


def _collect_nodes(items: list) -> None:
    try:
        from . import main as _main
        nodes = _main.list_nodes()
    except Exception:
        return
    for node in nodes:
        try:
            node_id = str(node.get("node_id", ""))
            if not node_id:
                continue
            name = (node.get("display_name")
                    or node.get("hostname") or node_id)
            derived = str(node.get("derived_status", ""))
            health = str(node.get("health_status", "UNKNOWN"))
            if derived in ("offline",) or health == "OFFLINE":
                items.append(_item(
                    f"att_node_offline_{node_id}",
                    "node_offline",
                    f"Node '{name}' is offline.",
                    "A pull-only helper stopped claiming work. "
                    "Queued tasks wait for a capable node.",
                    "node registry",
                    action=_open_defer("/nodes"),
                    open_href="/nodes",
                    updated_at=str(node.get("last_seen", ""))))
            elif derived == "stale" or health == "STALE":
                items.append(_item(
                    f"att_node_stale_{node_id}",
                    "node_stale",
                    f"Node '{name}' is stale.",
                    "No heartbeat for over 60 seconds. Check "
                    "connectivity before routing work to it.",
                    "node registry",
                    action=_open_defer("/nodes"),
                    open_href="/nodes",
                    updated_at=str(node.get("last_seen", ""))))
            elif health == "DEGRADED":
                items.append(_item(
                    f"att_telemetry_stale_{node_id}",
                    "telemetry_stale",
                    f"Node '{name}' telemetry is stale.",
                    "Telemetry older than 5 minutes. Routing "
                    "treats this node as degraded.",
                    "node telemetry",
                    action=_open_defer("/nodes"),
                    open_href="/nodes",
                    updated_at=str(node.get(
                        "telemetry_timestamp", ""))))
            if health != "ONLINE":
                continue
            for hw in (node.get("hardware") or []):
                if not isinstance(hw, dict):
                    continue
                ident = str(hw.get("identifier", ""))
                kind = str(hw.get("kind", "?"))
                if not ident:
                    continue
                safe = re.sub(r"[^A-Za-z0-9_.:-]+", "_",
                              ident)[:80]
                if str(hw.get("status", "")) == "disconnected":
                    items.append(_item(
                        f"att_hw_offline_{node_id}_{safe}",
                        "hardware_offline",
                        f"Hardware '{ident}' ({kind}) on "
                        f"'{name}' disconnected.",
                        "Previously seen, currently gone. Tasks "
                        "needing it wait honestly.",
                        "node hardware report",
                        action=_open_defer("/nodes"),
                        open_href="/nodes"))
                elif str(hw.get("status", "")) == "connected":
                    items.append(_item(
                        f"att_hw_available_{node_id}_{safe}",
                        "hardware_available",
                        f"Hardware '{ident}' ({kind}) on "
                        f"'{name}' available.",
                        "Connected and routable for tasks that "
                        "require it.",
                        "node hardware report",
                        action=_open_defer("/nodes"),
                        open_href="/nodes"))
            for comp in (node.get("compute_capabilities") or []):
                if not isinstance(comp, dict):
                    continue
                cap = str(comp.get("capability", ""))
                if (cap in ("ollama", "gpu_available")
                        and str(comp.get("status", ""))
                        == "available"):
                    items.append(_item(
                        f"att_cap_available_{node_id}_{cap}",
                        "capability_available",
                        f"Node '{name}' offers {cap}.",
                        "Routable now for tasks that require "
                        "this capability.",
                        "node compute report",
                        action=_open_defer("/nodes"),
                        open_href="/nodes"))
        except Exception:
            continue


def _collect_automation(items: list) -> None:
    try:
        from .automation import list_runs
        runs = list_runs(limit=50)
    except Exception:
        return
    for run in runs:
        try:
            state = str(run.state or "")
            if state == "waiting_for_human":
                waiting = run.waiting or {}
                gate = ""
                try:
                    gate = str((waiting.get("gate", {}) or {})
                               .get("kind", ""))
                except Exception:
                    gate = ""
                items.append(_item(
                    f"att_auto_waiting_{run.run_id}",
                    "automation_waiting",
                    f"Automation waits: {run.goal}",
                    f"Gate unmet: {gate or waiting.get('reason', 'gate unmet')}. "
                    "Resume re-checks the live store.",
                    "automation engine",
                    action=_open_defer(
                        f"/automation/{run.run_id}"),
                    open_href=f"/automation/{run.run_id}",
                    created_at=str(getattr(
                        run, "created_at", "")),
                    updated_at=str(getattr(
                        run, "updated_at", ""))))
            elif state == "waiting_for_agent":
                items.append(_item(
                    f"att_auto_waiting_{run.run_id}",
                    "automation_waiting",
                    f"Automation waits for agent: {run.goal}",
                    "The run waits for agent-side input. Lower "
                    "urgency than human gates.",
                    "automation engine",
                    action=_open_defer(
                        f"/automation/{run.run_id}"),
                    open_href=f"/automation/{run.run_id}",
                    extra_score=-45,
                    extra_reason="agent-side wait (-45)"))
            elif state in ("failed", "blocked"):
                items.append(_item(
                    f"att_auto_failed_{run.run_id}",
                    "automation_failed",
                    f"Automation {state}: {run.goal}",
                    "A bound or refusal stopped the run. "
                    "Inspect before re-driving.",
                    "automation engine",
                    action=_open_defer(
                        f"/automation/{run.run_id}"),
                    open_href=f"/automation/{run.run_id}"))
        except Exception:
            continue


def _collect_fabrication(items: list) -> None:
    try:
        from . import main as _main
        fabs = _main.list_fabrications(50)
    except Exception:
        fabs = []
    for record in fabs:
        try:
            status = str(getattr(record, "status", ""))
            fab_id = str(getattr(
                record, "fabrication_id",
                getattr(record, "job_id", "?")))
            if status in ("proposed", "approved", "ready",
                          "waiting"):
                items.append(_item(
                    f"att_fab_waiting_{fab_id}",
                    "fabrication_waiting",
                    f"Fabrication {fab_id} waits [{status}].",
                    "Physical work only moves with your "
                    "explicit approval.",
                    "fabrication flow",
                    action=_open_defer("/fabrication"),
                    open_href="/fabrication"))
            elif status in ("failed", "blocked"):
                items.append(_item(
                    f"att_fab_blocked_{fab_id}",
                    "fabrication_blocked",
                    f"Fabrication {fab_id} {status}.",
                    "Something in the chain refused — inspect "
                    "before retrying.",
                    "fabrication flow",
                    action=_open_defer("/fabrication"),
                    open_href="/fabrication"))
        except Exception:
            continue
    try:
        from .workshop3d import list_fabjobs
        jobs = list_fabjobs(limit=50)
    except Exception:
        jobs = []
    for job in jobs:
        try:
            if not isinstance(job, dict):
                continue
            stage = str(job.get("stage", ""))
            job_id = str(job.get("job_id", "?"))
            if stage in ("observed", "verifying"):
                items.append(_item(
                    f"att_fab3d_waiting_{job_id}",
                    "fabrication_waiting",
                    f"Print job {job_id[:24]} waits for human "
                    "verification.",
                    "Camera evidence exists but is not "
                    "reviewed. Verify or send it back.",
                    "3D workshop",
                    action=_open_defer("/3d"),
                    open_href="/3d"))
            elif stage == "blocked":
                items.append(_item(
                    f"att_fab3d_blocked_{job_id}",
                    "fabrication_blocked",
                    f"Print job {job_id[:24]} is blocked.",
                    "Something in the chain refused — inspect "
                    "before retrying.",
                    "3D workshop",
                    action=_open_defer("/3d"),
                    open_href="/3d"))
        except Exception:
            continue


def _collect_research(items: list) -> None:
    try:
        from .research_engine import list_dossiers
        dossiers = list_dossiers(limit=10)
    except Exception:
        dossiers = []
    for dossier in dossiers:
        try:
            state = str(getattr(
                dossier, "execution_state", ""))
            if state in ("COMPLETED", "READY", "completed"):
                claims = len(getattr(dossier, "claims", [])
                             or [])
                items.append(_item(
                    f"att_research_{dossier.dossier_id}",
                    "research_finding",
                    f"Research ready: {dossier.title}",
                    f"{claims} claim(s) with evidence. Review "
                    "before promoting anything.",
                    "research engine",
                    action=_open_defer("/research"),
                    open_href="/research",
                    created_at=str(getattr(
                        dossier, "created_at", "")),
                    updated_at=str(getattr(
                        dossier, "created_at", ""))))
        except Exception:
            continue
    # Node-aware research readiness (BIG #39 hardware reality).
    readiness = research_readiness()
    if readiness["eligible"]:
        return
    if readiness["checked"]:
        items.append(_item(
            "att_research_waiting_nodes",
            "research_waiting",
            "Research is waiting: no eligible node.",
            readiness["text"],
            "task routing",
            action=_open_defer("/nodes"),
            open_href="/nodes"))


def research_readiness() -> dict:
    """Which nodes could run research right now, and why not.

    Pure routing explanation over live registry state: eligible
    node ids plus per-node rejection reasons. Never executes.
    """
    try:
        from . import main as _main
        from .routing import check_requirements, route_task
        nodes = _main.list_nodes()
        requirements = check_requirements({
            "required_capabilities": ["research.fetch",
                                      "analysis.ollama"]})
        decision = route_task(requirements, [
            {**node,
             "capabilities": node.get("capabilities", []),
             "models": node.get("models", []),
             "executors": node.get("executors", []),
             "resources": node.get("resources", {}),
             "locality_zone": node.get("locality_zone",
                                       "local_network"),
             "status": node.get("derived_status", "unknown"),
             "fresh": node.get("derived_status") in (
                 "online", "busy"),
             "authenticated": node.get("last_auth") == "token",
             "hardware": node.get("hardware", []),
             "compute_capabilities": node.get(
                 "compute_capabilities", []),
             "telemetry_timestamp": node.get(
                 "telemetry_timestamp", ""),
             "health_status": node.get("health_status",
                                       "UNKNOWN")}
            for node in nodes if node.get("node_id")])
    except Exception:
        return {"eligible": [], "unavailable": [],
                "text": "Routing unavailable.", "checked": False}
    unavailable = [{"node_id": entry.node_id,
                    "reasons": list(entry.reasons)}
                   for entry in decision.rejected]
    if decision.selected_node_id is not None:
        return {"eligible": decision.eligible_nodes,
                "unavailable": unavailable,
                "text": f"{decision.selected_node_id} can run "
                        "research now.",
                "checked": True}
    detail = "; ".join(
        f"{entry['node_id']}: "
        f"{entry['reasons'][0] if entry['reasons'] else '?'}"
        for entry in unavailable[:3])
    return {"eligible": [],
            "unavailable": unavailable,
            "text": f"No eligible node with Ollama + fetch. "
                    f"{detail}" if detail else
                    "No nodes registered.",
            "checked": True}


def _collect_knowledge(items: list) -> None:
    try:
        from .knowledge import list_candidates
        candidates = list_candidates(limit=100)
    except Exception:
        return
    for entry in candidates[:15]:
        try:
            data = entry.model_dump(mode="json")
        except Exception:
            continue
        try:
            if str(data.get("state", "")) not in (
                    "observation", "candidate", "supported"):
                continue
            items.append(_item(
                f"att_candidate_{data.get('candidate_id', '?')}",
                "candidate_new",
                f"Candidate waits: {data.get('title', '?')}",
                "Observations stay candidates until you "
                "support or promote them.",
                "knowledge lifecycle",
                action=_open_defer("/knowledge"),
                open_href="/knowledge",
                related_entity=", ".join(
                    str(ref) for ref in
                    (data.get("entity_refs", []) or [])[:3]),
                created_at=str(data.get("created_at", "")),
                updated_at=str(data.get("updated_at", ""))))
        except Exception:
            continue


def _collect_intel(items: list) -> None:
    try:
        from .conversation_intel import cross_conversation
        aggregate = cross_conversation(limit=10)
    except Exception:
        return
    for entry in aggregate.get("contradictions", [])[:5]:
        try:
            if entry.get("status") != "UNRESOLVED":
                continue
            finger = str(entry.get("fingerprint", ""))[:16]
            if not finger:
                continue
            conversations = entry.get("conversations", [])[:2]
            items.append(_item(
                f"att_contradiction_{finger}",
                "contradiction",
                "A contradiction needs your attention.",
                str(entry.get("text", "")),
                "conversation intelligence",
                action=_open_defer(
                    f"/conversations/{conversations[0]}"
                    if conversations else "/conversations"),
                open_href=f"/conversations/{conversations[0]}"
                if conversations else "/conversations"))
        except Exception:
            continue
    try:
        from .ecosystem import discoveries
        found = discoveries(limit=6)
    except Exception:
        found = {}
    for entry in (found.get("items", []) or [])[:5]:
        try:
            text = str(entry.get("text", ""))
            if not text:
                continue
            link = str(entry.get("link", "/conversations"))
            items.append(_item(
                f"att_discovery_{abs(hash(text)) % 10**8:08d}",
                "discovery",
                "Possible missed item in a conversation.",
                text,
                "conversation discovery",
                action=_open_defer(link),
                open_href=link))
        except Exception:
            continue


def _collect_camera(items: list) -> None:
    try:
        from .vision_ingest import list_inbox_files
        inbox = list_inbox_files(limit=50)
    except Exception:
        return
    if inbox:
        items.append(_item(
            "att_camera_inbox",
            "observation_inbox",
            f"{len(inbox)} camera file(s) wait in the inbox.",
            "New visual material becomes an observation "
            "only after ingest.",
            "camera inbox",
            action=_open_defer("/cameras"),
            open_href="/cameras"))


def _collect_symbiosis(items: list) -> None:
    try:
        from .symbiosis import proposed
        proposals = proposed(limit=5)
    except Exception:
        return
    for entry in proposals[:5]:
        try:
            title = str(entry.get("title", ""))
            if not title:
                continue
            items.append(_item(
                f"att_symbiosis_{abs(hash(title)) % 10**8:08d}",
                "symbiosis_proposed",
                f"Symbiosis proposed: {title}",
                "AI-suggested relation from a connection "
                "candidate; needs your review.",
                "symbiosis engine",
                action=_open_defer(
                    str(entry.get("link", "/knowledge"))),
                open_href=str(entry.get("link",
                                        "/knowledge"))))
        except Exception:
            continue


def _collect_craft(items: list) -> None:
    try:
        from .workshop3d import list_models
        from .knowledge import list_candidates
        models = list_models(limit=50)
        candidates = list_candidates(limit=300)
    except Exception:
        return
    linked: set[str] = set()
    for entry in candidates:
        try:
            data = entry.model_dump(mode="json")
        except Exception:
            continue
        if data.get("candidate_type") != "connection":
            continue
        for ref in data.get("entity_refs") or []:
            if str(ref).startswith("mdl_"):
                linked.add(str(ref))
    for model in models[:20]:
        try:
            model_id = str(model.get("model_id", ""))
            if not model_id or model_id in linked:
                continue
            items.append(_item(
                f"att_craft_gap_{model_id}",
                "craft_gap",
                f"{model.get('filename', '?')[:60]} has no "
                "material or project.",
                "A model alone builds nothing — link material "
                "and a project to start a craft chain.",
                "3D workshop",
                action=_open_defer("/3d"),
                open_href="/3d",
                related_entity=model_id))
            if len([i for i in items
                    if i["type"] == "craft_gap"]) >= 3:
                break
        except Exception:
            continue


def _collect_ecosystem(items: list) -> None:
    """BIG #42 ecosystem hardening: unverified hardware, blocked
    quests, pending finance, unknown energy. All best-effort,
    all link to their real record."""
    try:
        from . import main as _main
        nodes = _main.list_nodes()
    except Exception:
        nodes = []
    try:
        from .hardware_links import list_links as _hw_links
        verified_refs = {(link.node_id, link.device_ref)
                         for link in _hw_links(status="VERIFIED",
                                                limit=200)}
        proposed_count = len(_hw_links(status="PROPOSED",
                                       limit=200))
    except Exception:
        verified_refs = set()
        proposed_count = 0
    unverified = []
    for node in nodes:
        node_id = str(node.get("node_id", ""))
        for hw in (node.get("hardware", []) or []):
            if not isinstance(hw, dict):
                continue
            ident = str(hw.get("identifier", ""))
            if ident and (node_id, ident) not in verified_refs:
                unverified.append((node_id, ident,
                                   str(hw.get("kind", ""))))
    for node_id, ident, kind in unverified[:3]:
        items.append(_item(
            f"att_hardware_unverified_{node_id}_{ident}"[:150],
            "hardware_unverified",
            f"{node_id} advertises {kind or 'hardware'} "
            f"'{ident[:40]}' — not human-verified.",
            "Advertised is not a fact; only a human link "
            "verifies it.",
            "node registry",
            action=_open_defer("/hardware"),
            open_href="/hardware",
            created_at=node.get("last_seen", "") if isinstance(
                node, dict) else "",
            updated_at=""))
    if proposed_count and not unverified:
        items.append(_item(
            "att_hardware_unverified_proposed",
            "hardware_unverified",
            f"{proposed_count} hardware link(s) wait for "
            "operator verification.",
            "Proposed links verify nothing until a human with "
            "the operator key confirms them.",
            "hardware links",
            action=_open_defer("/hardware"),
            open_href="/hardware"))
    try:
        from .quests import list_quest_details as _quests
        for quest in _quests(limit=20):
            if quest.get("state") in ("BLOCKED", "FAILED"):
                items.append(_item(
                    f"att_quest_blocked_{quest.get('quest_id', '')}"
                    [:150],
                    "quest_blocked",
                    f"Quest '{quest.get('title', '')[:70]}' is "
                    f"{quest.get('state', '')} at "
                    f"{quest.get('done', 0)}/"
                    f"{quest.get('total', 0)}.",
                    "A step's underlying record failed or is "
                    "blocked.",
                    "quest trails",
                    action=_open_defer("/quests"),
                    open_href="/quests"))
                break
    except Exception:
        pass
    try:
        from .finance import list_records as _finance
        drafts = [record for record in _finance(limit=100)
                  if record.status == "DRAFT"][:3]
        for record in drafts:
            items.append(_item(
                f"att_finance_pending_{record.record_id}"[:150],
                "finance_pending",
                f"Finance {record.kind} '{record.title[:60]}' "
                "waits for confirmation.",
                "Draft figures confirm nothing until reviewed.",
                "finance records",
                action=_open_defer("/finance"),
                open_href="/finance"))
            break
    except Exception:
        pass
    try:
        from .energy import list_records as _energy
        unknowns = [record for record in _energy(limit=100)
                    if record.value is None][:2]
        for record in unknowns:
            items.append(_item(
                f"att_energy_unknown_{record.record_id}"[:150],
                "energy_unknown",
                f"Energy {record.source}/{record.kind} has no "
                "measurement (UNKNOWN).",
                "Unknown energy honestly blocks energy-aware "
                "decisions until observed.",
                "energy records",
                action=_open_defer("/energy"),
                open_href="/energy"))
            break
    except Exception:
        pass


def _collect_failures(items: list) -> None:
    """Failed tasks/missions from the last 24h bus (honest,
    bounded, no new queries)."""
    try:
        from .events import list_events
        events = list_events(limit=100)
    except Exception:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for event in events:
        try:
            if event.event_type not in ("task.failed",
                                        "mission.failed"):
                continue
            moment = _parse_time(event.created_at)
            if moment is None or moment < cutoff:
                continue
            if event.event_type == "task.failed":
                task_id = str(event.task_id or "?")
                items.append(_item(
                    f"att_task_failed_{task_id}",
                    "task_failed",
                    f"Task {task_id} failed.",
                    str(event.summary or "The task failed "
                        "safely; nothing executed beyond its "
                        "bounds."),
                    "task queue",
                    action=_open_defer("/activity"),
                    open_href="/activity",
                    related_task=task_id,
                    created_at=event.created_at,
                    updated_at=event.created_at))
        except Exception:
            continue


# -- triage store (operator decisions only) --------------------------------------

def _triage_db():
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS attention_triage ("
            "item_id TEXT PRIMARY KEY, status TEXT NOT NULL, "
            "decided_by TEXT NOT NULL DEFAULT 'jelles', "
            "title TEXT NOT NULL DEFAULT '', "
            "kind TEXT NOT NULL DEFAULT '', "
            "updated_at TEXT NOT NULL)")
    from .database import chat_connection as _conn
    return _conn()


def get_triage() -> dict[str, dict]:
    """All stored triage rows keyed by item id. Read-only."""
    try:
        with _triage_db() as db:
            rows = db.execute(
                "SELECT item_id, status, decided_by, title, "
                "kind, updated_at FROM attention_triage").fetchall()
    except Exception:
        return {}
    return {row["item_id"]: dict(row) for row in rows}


def check_item_id(item_id: str) -> str:
    cleaned = str(item_id or "").strip()[:MAX_ITEM_ID]
    if not re.match(ITEM_ID_PATTERN, cleaned):
        raise PresenceRefusedError(
            "Unknown attention item (bad id shape)")
    return cleaned


def set_triage(item_id: str, status: str,
               decided_by: str = "jelles",
               title: str = "", kind: str = "") -> dict:
    """Store SEEN/DEFERRED for a currently-derived item.

    Refuses unknown statuses, malformed ids, and ids that are
    not live right now (fake ids, resolved items, replay).
    DEFER performs nothing — it only hides the item.
    """
    cleaned_id = check_item_id(item_id)
    cleaned_status = str(status or "").strip().upper()
    if cleaned_status not in ("SEEN", "DEFERRED"):
        raise PresenceRefusedError(
            "Triage stores SEEN or DEFERRED only")
    live = {item["id"] for item in attention_items(limit=200)}
    if cleaned_id not in live:
        raise PresenceRefusedError(
            "Unknown attention item (not live)")
    who = str(decided_by or "jelles").strip()[:80] or "jelles"
    stamp = now()
    with _triage_db() as db:
        db.execute(
            "INSERT INTO attention_triage (item_id, status, "
            "decided_by, title, kind, updated_at) VALUES "
            "(?, ?, ?, ?, ?, ?) ON CONFLICT(item_id) DO UPDATE "
            "SET status=excluded.status, "
            "decided_by=excluded.decided_by, "
            "title=excluded.title, kind=excluded.kind, "
            "updated_at=excluded.updated_at",
            (cleaned_id, cleaned_status, who,
             str(title or "")[:MAX_TITLE],
             str(kind or "")[:40], stamp))
        db.execute(
            "DELETE FROM attention_triage WHERE updated_at < ?",
            ((datetime.now(timezone.utc)
              - timedelta(days=TRIAGE_PRUNE_DAYS)).isoformat(),))
    return {"item_id": cleaned_id, "status": cleaned_status,
            "decided_by": who, "updated_at": stamp}


# -- aggregation ------------------------------------------------------------------

def _apply_triage(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Join live items with stored triage. Returns (visible,
    cleared). DEFERRED items hide from NEEDS/WAITING bands but
    stay visible as deferred; source-gone overrides surface as
    RESOLVED/EXPIRED in cleared."""
    triage = get_triage()
    live_ids = {item["id"] for item in items}
    visible: list[dict] = []
    for item in items:
        override = triage.get(item["id"])
        if override and override.get("status") == "DEFERRED":
            moment = _parse_time(override.get("updated_at", ""))
            if (moment is not None and datetime.now(
                    timezone.utc) - moment > timedelta(
                        days=TRIAGE_TTL_DAYS)):
                item["status"] = "EXPIRED"
            else:
                item["status"] = "DEFERRED"
        elif override and override.get("status") == "SEEN":
            item["status"] = "SEEN"
        visible.append(item)
    cleared: list[dict] = []
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=TRIAGE_TTL_DAYS)
    for item_id, row in triage.items():
        if item_id in live_ids:
            continue
        moment = _parse_time(row.get("updated_at", ""))
        if moment is None or moment < cutoff:
            continue
        cleared.append({
            "id": item_id,
            "type": "resolved",
            "band": "discovered",
            "priority": 0,
            "priority_reasons": ["source cleared"],
            "title": row.get("title") or item_id,
            "reason": "This stopped needing attention.",
            "source": "presence memory",
            "related_entity": "",
            "related_mission": "",
            "related_task": "",
            "action": {},
            "open_href": "/activity",
            "created_at": row.get("updated_at", ""),
            "updated_at": row.get("updated_at", ""),
            "status": "RESOLVED",
            "provenance": {"source_type": "derived",
                           "creator_id": "presence-engine",
                           "human_verified": False},
        })
    return visible, cleared


def attention_items(limit: int = MAX_ITEMS) -> list[dict]:
    """Derive all attention items from live stores. Never raises;
    deterministic order: priority desc, type asc, id asc."""
    items: list[dict] = []
    for collector in (_collect_approvals, _collect_missions,
                      _collect_nodes, _collect_automation,
                      _collect_fabrication, _collect_research,
                      _collect_knowledge, _collect_intel,
                      _collect_camera, _collect_symbiosis,
                      _collect_craft, _collect_failures,
                      _collect_ecosystem):
        try:
            collector(items)
        except Exception:
            continue
    # Deduplicate by stable id (first wins = highest source
    # precedence: approvals first).
    seen: dict[str, dict] = {}
    for item in items:
        seen.setdefault(item["id"], item)
    ordered = sorted(seen.values(),
                     key=lambda entry: (-entry["priority"],
                                        entry["type"],
                                        entry["id"]))
    return ordered[:max(1, min(int(limit or MAX_ITEMS), 200))]


def attention_snapshot(limit: int = MAX_ITEMS) -> dict:
    """Bands + cleared + counts for API and pages."""
    items = attention_items(limit=limit)
    visible, cleared = _apply_triage(items)
    bands: dict[str, list[dict]] = {band: [] for band in BANDS}
    for item in visible:
        # DEFERRED items leave the urgent bands but stay listed.
        if item.get("status") == "DEFERRED":
            bands["waiting"].append(item)
        else:
            bands[item.get("band", "discovered")].append(item)
    counts = {band: len(entries)
              for band, entries in bands.items()}
    counts["cleared"] = len(cleared)
    counts["total"] = len(visible)
    return {"items": visible, "bands": bands, "cleared": cleared,
            "counts": counts, "generated_at": now(),
            "provenance": {"source_type": "derived",
                           "creator_id": "presence-engine",
                           "human_verified": False}}


# -- progression (game-layer foundation; real state only) --------------------------

def progression() -> dict:
    """Quests, discoveries, growth, capabilities, activity —
    every number backed by a live store, nothing invented."""
    quests: list[dict] = []
    try:
        from .missions import list_missions
        for mission in list_missions(limit=20):
            if mission.status not in ("approved", "running",
                                      "pending_approval",
                                      "paused"):
                continue
            steps = getattr(mission, "steps", []) or []
            done = sum(1 for step in steps
                       if str(getattr(step, "status", ""))
                       in ("done", "completed", "skipped"))
            quests.append({
                "title": str(mission.goal or "?")[:100],
                "done": done, "total": len(steps),
                "status": str(mission.status or ""),
                "href": f"/missions/{mission.mission_id}",
                "kind": "mission"})
            if len(quests) >= 5:
                break
    except Exception:
        pass
    try:
        from .automation import list_runs
        for run in list_runs(limit=20):
            if run.state in ("completed", "failed",
                             "cancelled"):
                continue
            steps = getattr(run, "steps", []) or []
            done = sum(1 for step in steps
                       if str(getattr(step, "status", ""))
                       == "done")
            quests.append({
                "title": f"Automation: {run.goal}"[:100],
                "done": done, "total": len(steps),
                "status": str(run.state or ""),
                "href": f"/automation/{run.run_id}",
                "kind": "automation"})
            if len(quests) >= 8:
                break
    except Exception:
        pass
    discoveries_24h = 0
    observations_24h = 0
    growth_24h = 0
    activity_24h = 0
    try:
        from .events import list_events
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=24)
        for event in list_events(limit=200):
            moment = _parse_time(event.created_at)
            if moment is None or moment < cutoff:
                continue
            activity_24h += 1
            if event.event_type == "observation.created":
                observations_24h += 1
            if event.event_type in ("candidate.observed",
                                    "candidate.supported",
                                    "relation.proposed"):
                discoveries_24h += 1
            if event.event_type in ("candidate.supported",
                                    "candidate.promoted"):
                growth_24h += 1
    except Exception:
        pass
    capabilities: list[str] = []
    online_nodes = 0
    try:
        from . import main as _main
        for record in _main.list_nodes():
            if record.get("derived_status") not in ("online",
                                                    "busy"):
                continue
            online_nodes += 1
            for cap in record.get("capabilities", []) or []:
                text = str(cap)
                if text and text not in capabilities:
                    capabilities.append(text)
            if len(capabilities) >= 20:
                break
    except Exception:
        pass
    return {"quests": quests,
            "discoveries_24h": discoveries_24h,
            "observations_24h": observations_24h,
            "growth_24h": growth_24h,
            "activity_24h": activity_24h,
            "online_nodes": online_nodes,
            "capabilities_unlocked": sorted(capabilities)[:20]}


# -- overnight digest (read-only) ----------------------------------------------------

def overnight_digest(hours: int = 12) -> dict:
    """What changed while Jelles was away. Observation only:
    event counts per type in the window + current waiting
    totals. Never executes, never proposes, never approves."""
    window = max(1, min(int(hours or 12), 48))
    cutoff = datetime.now(timezone.utc) - timedelta(
        hours=window)
    by_type: dict[str, int] = {}
    samples: dict[str, str] = {}
    try:
        from .events import list_events
        for event in list_events(limit=200):
            moment = _parse_time(event.created_at)
            if moment is None or moment < cutoff:
                continue
            by_type[event.event_type] = by_type.get(
                event.event_type, 0) + 1
            samples.setdefault(event.event_type,
                               str(event.summary or "")[:120])
    except Exception:
        pass
    waiting_now = 0
    try:
        from . import main as _main
        approvals = _main.coordinator_status().get(
            "pending_approvals", {})
        waiting_now = sum(int(approvals.get(key, 0))
                          for key in ("desktop_actions",
                                      "write_proposals",
                                      "missions"))
    except Exception:
        pass
    lines = [f"{event_type}: {count}"
             for event_type, count in sorted(by_type.items())]
    return {"window_hours": window,
            "changes": by_type,
            "samples": samples,
            "lines": lines[:20],
            "waiting_now": waiting_now,
            "generated_at": now()}


# -- morning sections (bounded strings for reports) ------------------------------------

def morning_presence_sections() -> dict[str, list[str]]:
    """Seven presence sections for the morning report. All
    derived from live state right here, right now."""
    snapshot = attention_snapshot(limit=120)
    bands = snapshot["bands"]
    overnight = overnight_digest(hours=12)
    prog = progression()

    def _line(item: dict) -> str:
        return (f"{item['title']} — {item['reason']} "
                f"[{item['open_href']}]")[:280]

    needs = [_line(item) for item in bands["needs"][:8]] or [
        "Nothing needs you right now."]
    discoveries = [
        _line(item) for item in bands["discovered"][:6]]
    # Craft gaps are growth-relevant discoveries of missing
    # links (BIG #41): honestly worded, capped at two.
    discoveries += [
        _line(item) for item in bands["waiting"]
        if item["type"] == "craft_gap"][:2]
    discoveries = discoveries[:8] or ["No new discoveries."]
    resources = [
        _line(item) for item in bands["available"][:8]] or [
        "No special resources online right now."]
    blocked = [_line(item) for item in
               bands["needs"][:20]
               if item["type"] in ("mission_blocked",
                                   "mission_failed",
                                   "task_failed",
                                   "automation_failed",
                                   "fabrication_blocked")]
    blocked = blocked[:8] or ["Nothing is blocked."]
    offline = ([_line(item) for item in bands["offline"][:8]
                ] + [_line(item) for item in bands["waiting"]
                     if item["type"] == "telemetry_stale"][:4])
    offline = offline[:8] or ["All known hardware is quiet."]
    next_actions = []
    for item in bands["needs"][:5]:
        action = item.get("action", {}) or {}
        first = next(iter(action.values()), {})
        href = first.get("href", item["open_href"])
        next_actions.append(
            f"{item['title']} → {first.get('label', 'OPEN')} "
            f"at {href}"[:280])
    next_actions = next_actions or [
        "Nothing urgent — check the guide for open threads."]
    return {
        "presence_needs": needs,
        "presence_overnight": overnight["lines"][:8] or [
            "Nothing changed overnight."],
        "presence_discoveries": discoveries,
        "presence_resources": resources,
        "presence_blocked": blocked,
        "presence_offline": offline,
        "presence_next": next_actions,
    }


# -- notification fan-out (explicit, deduplicated) --------------------------------------

#: Attention type → IN_APP notification kind. Types without a
#: mapping stay presence-only (never notify).
NOTIFY_KIND = {
    "approval_desktop": "approval_required",
    "approval_write": "approval_required",
    "approval_mission": "mission_waiting",
    "mission_blocked": "mission_blocked",
    "mission_failed": "system_attention",
    "task_failed": "system_attention",
    "automation_waiting": "automation_waiting",
    "automation_failed": "system_attention",
    "fabrication_waiting": "fabrication_waiting",
    "fabrication_blocked": "system_attention",
    "node_offline": "node_offline",
    "node_stale": "node_stale",
    "telemetry_stale": "telemetry_stale",
    "hardware_offline": "hardware_disconnected",
    "hardware_available": "hardware_connected",
    "capability_available": "capability_available",
    "research_finding": "research_finding",
    "research_waiting": "capability_unavailable",
    "candidate_new": "candidate_waiting",
    "contradiction": "contradiction_detected",
    "observation_inbox": "new_observation",
    "symbiosis_proposed": "new_connection",
}

PRESENCE_RECIPIENT = "jelles"


def sync_presence_notifications(limit: int = 5) -> dict:
    """Fan out top attention items as IN_APP notifications.

    Explicit call only (API button, never background).
    Deduplicates: an unread notification with the same kind +
    title is never sent twice. Returns receipts + skips.
    WEB_PUSH is never involved (UNAVAILABLE by design).
    """
    from .events import list_notifications
    from .notify_center import send, severity_for
    count = max(1, min(int(limit or 5), 10))
    try:
        existing = {(note.type, note.title)
                    for note in list_notifications(
                        PRESENCE_RECIPIENT, limit=50,
                        unread_only=True)}
    except Exception:
        existing = set()
    snapshot = attention_snapshot(limit=60)
    ordered = sorted(
        snapshot["items"],
        key=lambda entry: (-entry["priority"], entry["type"],
                           entry["id"]))
    sent: list[dict] = []
    skipped = 0
    for item in ordered:
        if len(sent) >= count:
            break
        kind = NOTIFY_KIND.get(item["type"])
        if not kind:
            continue
        if item.get("status") == "DEFERRED":
            skipped += 1
            continue
        try:
            bucket = severity_for(kind)
        except Exception:
            skipped += 1
            continue
        if (bucket, item["title"]) in existing:
            skipped += 1
            continue
        try:
            receipt = send(
                PRESENCE_RECIPIENT, kind, item["title"],
                f"{item['reason']} Next: {item['open_href']}",
                related_entity=item["related_entity"],
                related_mission=item["related_mission"],
                related_task=item["related_task"])
        except Exception:
            skipped += 1
            continue
        existing.add((bucket, item["title"]))
        sent.append({"item_id": item["id"], "kind": kind,
                     **receipt})
    return {"sent": sent, "skipped": skipped,
            "transport": "IN_APP", "web_push": "UNAVAILABLE",
            "generated_at": now()}
