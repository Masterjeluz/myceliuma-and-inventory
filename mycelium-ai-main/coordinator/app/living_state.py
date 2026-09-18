"""Living state (BIG #31): one honest global indicator.

Derived from real stores on every read — never stored, never
guessed:

- QUIET: nothing waiting, nothing running.
- RESEARCHING: a research run is collecting/extracting/synthesizing.
- THINKING: a mission is approved/running (brain at work).
- CONNECTING: fresh conversation analysis or unlinked findings exist.
- DISTRIBUTED: 2+ nodes online.
- WAITING FOR JELLES: any exact-YES approval pending (desktop,
  writes, missions). Waiting wins over every other state.
- COMPLETE: a mission/task completed in the last hour.
- BLOCKED: something failed/blocked recently.

The indicator renders in the topbar of every page and backs
GET /api/v1/state. Reduced-motion and readability stay as in
ui.py; the state is one short Dutch/English line, never hype.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

STATES = ("QUIET", "RESEARCHING", "THINKING", "CONNECTING",
          "DISTRIBUTED", "WAITING", "COMPLETE", "BLOCKED")

GLYPHS = {
    "QUIET": "🌱",
    "RESEARCHING": "🔎",
    "THINKING": "🧠",
    "CONNECTING": "🔗",
    "DISTRIBUTED": "💻",
    "WAITING": "🟡",
    "COMPLETE": "✓",
    "BLOCKED": "⚠",
}

LINES = {
    "QUIET": "Quiet — alles wacht op jou.",
    "RESEARCHING": "Ik ben iets aan het onderzoeken.",
    "THINKING": "Ik ben aan het werk.",
    "CONNECTING": "Ik vond iets dat nog nergens aan hangt.",
    "DISTRIBUTED": "Er werken nodes mee.",
    "WAITING": "Hier wacht ik op jou.",
    "COMPLETE": "Iets is net afgerond.",
    "BLOCKED": "Iets zit vast — kijk even mee.",
}


def _parse_time(value: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value or ""))
    except (ValueError, TypeError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def current_state() -> dict:
    """Compute the living state from live stores. Read-only."""
    now = datetime.now(timezone.utc)
    reasons: list[str] = []
    waiting = 0
    try:
        from . import main as _main
        status = _main.coordinator_status()
        approvals = status.get("pending_approvals", {})
        waiting = sum(int(approvals.get(key, 0)) for key in
                      ("desktop_actions", "write_proposals", "missions"))
        if waiting:
            reasons.append(f"{waiting} openstaande goedkeuring(en)")
    except Exception:
        pass
    candidates_waiting = 0
    try:
        from .knowledge import list_candidates
        candidates_waiting = len(list_candidates(limit=200))
        if candidates_waiting:
            reasons.append(
                f"{candidates_waiting} kandidaat/kandidaten wachten "
                "op review")
    except Exception:
        pass
    running_missions = 0
    try:
        from .missions import list_missions
        for mission in list_missions(limit=50):
            if mission.status in ("approved", "running"):
                running_missions += 1
    except Exception:
        pass
    active_runs = 0
    try:
        from .research_engine import list_runs
        for run in list_runs(limit=20):
            if run.status in ("collecting", "extracting",
                              "synthesizing"):
                active_runs += 1
    except Exception:
        pass
    online_nodes = 0
    try:
        from . import main as _main
        online_nodes = sum(
            1 for record in _main.list_nodes()
            if record.get("derived_status") == "online")
    except Exception:
        pass
    recent_complete = False
    recent_blocked = False
    new_observations = 0
    new_candidates = 0
    new_connections = 0
    try:
        from .events import list_events
        for event in list_events(limit=40):
            moment = _parse_time(event.created_at)
            if moment is None or now - moment > timedelta(hours=24):
                continue
            if event.event_type == "observation.created":
                new_observations += 1
            if event.event_type in ("candidate.observed",
                                    "candidate.supported"):
                new_candidates += 1
            if event.event_type in ("relation.proposed",
                                    "candidate.promoted"):
                new_connections += 1
            if now - moment > timedelta(hours=1):
                continue
            if event.event_type in ("mission.completed",
                                    "task.completed",
                                    "print.completed"):
                recent_complete = True
            if event.event_type in ("mission.failed", "task.failed",
                                    "mission.updated"):
                recent_blocked = True
    except Exception:
        pass
    fabrication_waiting = 0
    try:
        from . import main as _main
        for record in _main.list_fabrications(50):
            if record.status in ("proposed", "approved",
                                 "ready", "waiting"):
                fabrication_waiting += 1
    except Exception:
        pass
    camera_ready = False
    try:
        from .vision_ingest import list_inbox_files
        camera_ready = bool(list_inbox_files(limit=1))
    except Exception:
        pass
    if new_observations:
        reasons.append(
            f"{new_observations} nieuwe observatie(s) vandaag")
    if new_candidates:
        reasons.append(
            f"{new_candidates} kandidaat-activiteit vandaag")
    if new_connections:
        reasons.append(
            f"{new_connections} nieuwe verbinding(en) vandaag")
    if fabrication_waiting:
        reasons.append(
            f"{fabrication_waiting} fabricatie wacht")
    if camera_ready:
        reasons.append("cameramateriaal klaar voor analyse")
    unlinked = 0
    try:
        from .conversation_bridge import list_imports, load_analysis
        for meta in list_imports(limit=10):
            analysis = load_analysis(meta["conversation_id"]) or {}
            unlinked += len(analysis.get("findings", []))
            if unlinked:
                break
    except Exception:
        pass
    if waiting:
        state = "WAITING"
    elif recent_blocked:
        state = "BLOCKED"
    elif active_runs:
        state = "RESEARCHING"
        reasons.append(f"{active_runs} lopende research-run(s)")
    elif running_missions:
        state = "THINKING"
        reasons.append(f"{running_missions} actieve missie(s)")
    elif unlinked:
        state = "CONNECTING"
        reasons.append("open analyse zonder koppeling")
    elif online_nodes >= 2:
        state = "DISTRIBUTED"
        reasons.append(f"{online_nodes} nodes online")
    elif recent_complete:
        state = "COMPLETE"
    else:
        state = "QUIET"
    return {"state": state, "glyph": GLYPHS[state],
            "line": LINES[state], "reasons": reasons[:5],
            "waiting_approvals": waiting,
            "candidates_waiting": candidates_waiting,
            "running_missions": running_missions,
            "active_research_runs": active_runs,
            "online_nodes": online_nodes,
            "new_observations_24h": new_observations,
            "new_candidates_24h": new_candidates,
            "new_connections_24h": new_connections,
            "fabrication_waiting": fabrication_waiting,
            "camera_ready": camera_ready}
