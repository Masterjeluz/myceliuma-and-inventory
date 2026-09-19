"""Mobile Mycelium (BIG #36): the phone as command surface.

/mobile answers "What can I do right now?" and "Is Mycelium
waiting for me?" over the existing ecosystem — it is a
surface, not a second application. This module only READS
and shapes; every YES/NO posts to the existing web routes
(desktop decision, writes approve, mission ops), so mobile
and desktop share identical gates.

Sections: NOW, WAITING FOR YOU (triage cards), ACTIVE,
INPUT, GUIDE ME, CAMERA, CONTINUE ELSEWHERE, CRAFT,
SYMBIOSIS, NODES (+ mesh path), RECENT. Nothing stored,
nothing invented, nothing bypassed.
"""

from __future__ import annotations

TRIAGE_KINDS = ("desktop", "write", "mission")


def _clip(text, limit: int = 160) -> str:
    return " ".join(str(text or "").split())[:limit]


def _as_dict(record) -> dict:
    if isinstance(record, dict):
        return record
    try:
        return record.model_dump(mode="json")
    except Exception:
        pass
    try:
        return dict(record)
    except Exception:
        return {}


def approval_cards(limit: int = 10) -> list[dict]:
    """Unified triage across desktop actions, write proposals
    and missions. Each card carries WHAT/WHY/SOURCE/SCOPE plus
    what YES does and does NOT do. Bounded, never raises."""
    from . import main as _main
    cards: list[dict] = []

    def _parse_record(raw) -> dict:
        if isinstance(raw, str):
            try:
                from .database import load
                return load(raw)
            except Exception:
                return {}
        return _as_dict(raw)

    try:
        desktop = _main._desktop_list(limit=20,
                                      status="pending_approval")
    except Exception:
        desktop = []
    for entry in desktop[:10]:
        record = _parse_record(entry.get("record", {}))
        action = record.get("action", {})
        action_id = str(action.get("action_id", ""))[:80]
        action_type = str(action.get("action_type", ""))[:60]
        params = action.get("parameters", {})
        cards.append({
            "kind": "desktop",
            "id": action_id or entry.get("action_id", "?"),
            "what": _clip(f"Desktop action: {action_type or '?'}",
                          120),
            "why": _clip(params.get("reason",
                                    "The desktop agent proposed this "
                                    "screen/mouse/keyboard step.")),
            "source": "desktop agent proposal",
            "scope": _clip(f"one bounded {action_type or '?'} "
                           "operation; lease 300s, max 3 attempts"),
            "will_happen": "YES executes this single step with "
                            "observation; anything else needs a new "
                            "approval.",
            "will_not_happen": "No persistence, no other machine, "
                                "no standing permission.",
            "yes_action": f"/web/desktop/{action_id}/decision",
            "no_action": f"/web/desktop/{action_id}/decision",
            "open_href": "/agents",
            "state": "pending_approval",
        })
    try:
        writes = [item for item in _main._write_list(limit=30)
                  if item.get("status") == "proposed"]
    except Exception:
        writes = []
    for item in writes[:10]:
        proposal_id = str(item.get("proposal_id", ""))[:80]
        mutation = str(item.get("summary", ""))[:80]
        detail = ""
        try:
            record = _main._write_load(proposal_id) or {}
            proposal = record.get("record", {})
            payload = proposal.get("payload", {})
            target = proposal.get("target", "") or \
                payload.get("printer_id", "") or \
                payload.get("entity_type", "")
            detail = str(target)[:80]
        except Exception:
            detail = ""
        cards.append({
            "kind": "write",
            "id": proposal_id,
            "what": _clip(f"Write proposal: {mutation or '?'}"
                          f"{' → ' + detail if detail else ''}",
                          120),
            "why": "A flow proposed a persistent or physical "
                   "change and stopped for your decision.",
            "source": "writes inbox proposal",
            "scope": _clip(f"exactly the payload of {proposal_id}; "
                           "execution + verification stay separate"),
            "will_happen": "YES permits this payload only; "
                            "execution and independent verification "
                            "follow as their own steps.",
            "will_not_happen": "No other payload, no auto-verify, "
                                "no physical e-stop semantics.",
            "yes_action": f"/web/writes/{proposal_id}/approve",
            "no_action": f"/web/writes/{proposal_id}/approve",
            "open_href": "/writes",
            "state": "proposed",
        })
    try:
        from .missions import list_missions
        missions = [mission for mission in list_missions(limit=30)
                    if mission.status in ("pending_approval",
                                          "paused")]
    except Exception:
        missions = []
    for mission in missions[:10]:
        data = _as_dict(mission)
        mission_id = str(data.get("mission_id", ""))[:80]
        steps = data.get("steps", [])
        cards.append({
            "kind": "mission",
            "id": mission_id,
            "what": _clip(f"Mission: {data.get('goal', '?')}",
                          120),
            "why": _clip(f"Plan with {len(steps)} step(s) waits "
                         "inside an approved-plan boundary."),
            "source": "mission plan",
            "scope": _clip(f"{len(steps)} step(s), one at a time, "
                           "each with its own gates"),
            "will_happen": "YES starts/resumes this plan; each "
                            "consequential step asks again.",
            "will_not_happen": "No standing autonomy, no gate "
                                "skipping, no background running.",
            "yes_action": f"/web/missions/{mission_id}/approve",
            "no_action": f"/web/missions/{mission_id}/cancel",
            "open_href": f"/missions/{mission_id}",
            "state": str(data.get("status", "")),
        })
    return cards[: max(1, min(int(limit or 10), 20))]


def _deeplink(note: dict) -> str:
    """Real object behind a notification. Never a dead end."""
    mission = str(note.get("related_mission", ""))
    entity = str(note.get("related_entity", ""))
    task = str(note.get("related_task", ""))
    kind = str(note.get("type", ""))
    if mission:
        return f"/missions/{mission}"
    if entity:
        if entity.startswith(("mdl_", "mat_", "fabjob_")):
            return "/3d"
        if entity.startswith(("obs-", "obs_", "cam_", "cing_")):
            return f"/cameras/{entity}" \
                if entity.startswith("cam_") else "/cameras"
        if entity.startswith("mem_"):
            return "/memory"
        if entity.startswith("conv_"):
            return f"/conversations/{entity}"
        if entity.startswith("cand_"):
            return "/knowledge"
        return f"/world?entity_id={entity}"
    if task:
        return "/activity"
    mapping = {
        "approval_required": "/agents",
        "mission_waiting": "/missions",
        "candidate_waiting": "/knowledge",
        "research_completed": "/research",
        "research_ready": "/research",
        "research_finding": "/research",
        "new_observation": "/cameras",
        "camera_ready": "/cameras",
        "new_connection": "/symbiosis",
        "fabrication_ready": "/fabrication",
        "node_offline": "/nodes",
        "node_connected": "/nodes",
        "task_completed": "/missions",
        "conversation_analyzed": "/conversations",
        "morning_report": "/morning",
        "system_attention": "/activity",
        # BIG #40 Presence ecosystem
        "mission_blocked": "/missions",
        "contradiction_detected": "/conversations",
        "automation_waiting": "/automation",
        "fabrication_waiting": "/fabrication",
    }
    return mapping.get(kind, "/activity")


def notification_cards(node: str = "", limit: int = 10) -> list[dict]:
    """IN_APP notifications with working deeplinks. WEB_PUSH is
    reported UNAVAILABLE, never faked."""
    from . import main as _main
    count = max(1, min(int(limit or 10), 20))
    items: list[dict] = []
    cleaned = str(node or "").strip()[:80]
    if not cleaned:
        try:
            notes = _main.list_notifications_for_report(limit=count)
        except Exception:
            notes = []
        for note in notes:
            data = _as_dict(note)
            items.append({
                "title": _clip(data.get("title", ""), 120),
                "type": str(data.get("type", "")),
                "body": _clip(data.get("body", ""), 160),
                "href": _deeplink(data),
                "at": str(data.get("created_at", ""))[:16],
            })
        return items
    try:
        from .events import list_notifications
        notes = list_notifications(cleaned, limit=count)
    except Exception:
        notes = []
    for note in notes:
        data = _as_dict(note)
        items.append({
            "title": _clip(data.get("title", ""), 120),
            "type": str(data.get("type", "")),
            "body": _clip(data.get("body", ""), 160),
            "href": _deeplink(data),
            "at": str(data.get("created_at", ""))[:16],
        })
    return items


def packet_preview(goal: str = "", project_id: str = "",
                   conversation_id: str = "") -> dict:
    """Small live summary behind CONTINUE ELSEWHERE. The full
    packet comes from the existing builder, never rebuilt."""
    from .context_packet import build_context_packet
    packet = build_context_packet(
        goal=goal[:200], project_id=project_id[:80],
        conversation_id=conversation_id[:80])
    entities = packet.get("entities", [])
    if isinstance(entities, dict):
        entity_count = len(entities)
    elif isinstance(entities, list):
        entity_count = len(entities)
    else:
        entity_count = 0
    return {
        "goal": packet.get("goal", ""),
        "missions": len(packet.get("missions", []) or []),
        "entities": entity_count,
        "memories": len(packet.get("memories", []) or []),
        "open_questions": len(
            packet.get("open_questions", []) or []),
        "href_md": "/api/v1/context/packet.md",
        "href_json": "/api/v1/context/packet",
        "href_continue": "/api/v1/context/continue",
    }


def camera_panel() -> dict:
    """BIG34 flow state for the phone: inbox → sessions →
    observations → candidates. Counts only, links to Camera Lab."""
    try:
        from .vision_ingest import list_inbox_files
        inbox = list_inbox_files(limit=50)
    except Exception:
        inbox = []
    try:
        from .camera_ecosystem import list_sessions
        sessions = list_sessions(limit=5)
    except Exception:
        sessions = []
    try:
        from .cameras import list_devices, list_observations
        undescribed = 0
        for device in list_devices()[:10]:
            try:
                undescribed += len(list_observations(
                    device.device_id, limit=10))
            except Exception:
                continue
    except Exception:
        undescribed = 0
    try:
        from .knowledge import list_candidates
        waiting = sum(
            1 for entry in list_candidates(limit=100)
            if (entry.provenance.creator_id or "") in
            ("camera-vlm", "camera-ecosystem"))
    except Exception:
        waiting = 0
    return {"inbox": len(inbox),
            "sessions": len(sessions),
            "observations": undescribed,
            "candidates_waiting": waiting,
            "href": "/cameras"}


def craft_panel(limit: int = 5) -> list[dict]:
    """Workshop presence for recently linked entities: real
    checklists with ✓/●/○ states. Bounded."""
    try:
        from .knowledge import list_candidates
        candidates = list_candidates(limit=200)
    except Exception:
        return []
    entities: list[str] = []
    for entry in candidates:
        try:
            data = entry.model_dump(mode="json")
        except Exception:
            continue
        if data.get("candidate_type") != "connection":
            continue
        for ref in data.get("entity_refs") or []:
            if str(ref).startswith(("proj_", "obj_", "mdl_")) \
                    and ref not in entities:
                entities.append(str(ref))
        if len(entities) >= max(1, min(int(limit or 5), 8)):
            break
    out: list[dict] = []
    try:
        from .workshop3d import workshop_presence
        for entity_id in entities[:5]:
            try:
                presence = workshop_presence(entity_id)
            except Exception:
                continue
            out.append({
                "entity_id": entity_id,
                "done": presence.get("done", 0),
                "total": presence.get("total", 0),
                "checklist": presence.get("checklist", []),
                "gaps": presence.get("gaps", [])[:3],
                "href": f"/craft?entity_id={entity_id}",
            })
    except Exception:
        pass
    return out


def symbiosis_panel(limit: int = 5) -> list[dict]:
    """Top PROPOSED symbioses with WHY/SOURCE/STATUS + YES path."""
    try:
        from .symbiosis import proposed
        items = proposed(limit=limit)
    except Exception:
        return []
    out = []
    for item in items[: max(1, min(int(limit or 5), 10))]:
        out.append({
            "title": str(item.get("title", ""))[:120],
            "entities": item.get("entities", [])[:4],
            "supporters": item.get("supporters", 0),
            "status": "PROPOSED",
            "why": "AI-suggested relation from a connection "
                   "candidate; needs your review.",
            "href": str(item.get("link", "/knowledge")),
        })
    return out


def nodes_panel() -> dict:
    """ONLINE/DEGRADED/STALE/OFFLINE/UNKNOWN + telemetry +
    hardware + compute. The PHONE→COORDINATOR→NODES path."""
    try:
        from . import main as _main
        nodes_data = _main.list_nodes()
    except Exception:
        return {"nodes": [], "path": []}
    nodes = []
    for entry in nodes_data[:15]:
        telemetry = entry.get("telemetry", {})
        hardware = entry.get("hardware", [])
        compute = entry.get("compute_capabilities", [])
        health = entry.get("health_status", "UNKNOWN")
        hw_connected = sum(1 for h in hardware if isinstance(h, dict) and h.get("status") == "connected") if isinstance(hardware, list) else 0
        comp_available = sum(1 for c in compute if isinstance(c, dict) and c.get("status") == "available") if isinstance(compute, list) else 0
        nodes.append({
            "node_id": entry.get("node_id", ""),
            "display_name": entry.get("display_name", "") or entry.get("hostname", ""),
            "status": entry.get("derived_status", ""),
            "health": health,
            "tier": entry.get("tier", ""),
            "roles": entry.get("roles", []),
            "capabilities": entry.get("capabilities", [])[:8],
            "telemetry": {
                "cpu_percent": telemetry.get("cpu_percent") if isinstance(telemetry, dict) else None,
                "memory_percent": telemetry.get("memory_percent") if isinstance(telemetry, dict) else None,
                "disk_percent": telemetry.get("disk_percent") if isinstance(telemetry, dict) else None,
                "temperature_celsius": telemetry.get("temperature_celsius") if isinstance(telemetry, dict) else None,
                "uptime_seconds": telemetry.get("uptime_seconds") if isinstance(telemetry, dict) else None,
                "timestamp": entry.get("telemetry_timestamp", ""),
            },
            "hardware": {
                "count": len(hardware) if isinstance(hardware, list) else 0,
                "connected": hw_connected,
                "kinds": [h.get("kind") for h in hardware if isinstance(h, dict)] if isinstance(hardware, list) else [],
            },
            "compute": {
                "count": len(compute) if isinstance(compute, list) else 0,
                "available": comp_available,
                "capabilities": [c.get("capability") for c in compute if isinstance(c, dict)] if isinstance(compute, list) else [],
            },
            "energy": entry.get("energy_state", {}) if isinstance(entry.get("energy_state"), dict) else {},
            "current_task": entry.get("current_task")
            if isinstance(entry.get("current_task"), dict) else None,
            "last_seen": entry.get("last_seen", ""),
        })
    return {
        "nodes": nodes,
        "path": [
            "PHONE asks the coordinator (this page posts "
            "to existing routes only)",
            "COORDINATOR validates, queues and leases work",
            "eligible NODE claims by capability, executes, "
            "reports back",
            "RESULT returns here; Jelles reviews before "
            "anything persists",
        ],
        "href": "/nodes",
    }


def progress_panel() -> dict:
    """Quest progress from real backend states only: active
    missions + fab jobs. Same language everywhere."""
    quests: list[dict] = []
    try:
        from .missions import list_missions
        for mission in list_missions(limit=20):
            data = _as_dict(mission)
            if data.get("status") not in ("approved", "running",
                                          "pending_approval",
                                          "paused"):
                continue
            steps = data.get("steps", [])
            done = sum(1 for step in steps if _as_dict(step).get(
                "status") in ("done", "completed", "skipped"))
            quests.append({
                "title": _clip(data.get("goal", "?"), 100),
                "done": done, "total": len(steps),
                "status": str(data.get("status", "")),
                "href": f"/missions/{data.get('mission_id', '')}",
            })
            if len(quests) >= 5:
                break
    except Exception:
        pass
    try:
        from .workshop3d import list_fabjobs
        for job in list_fabjobs(limit=20):
            if job.get("stage") in ("verified", "cancelled"):
                continue
            quests.append({
                "title": _clip(f"Fab job {job.get('job_id', '?')}",
                               100),
                "done": -1, "total": -1,
                "status": str(job.get("stage", "")),
                "href": "/3d",
            })
            if len(quests) >= 8:
                break
    except Exception:
        pass
    try:
        from .automation import list_runs
        for run in list_runs(limit=20):
            if run.state in ("completed", "failed", "cancelled"):
                continue
            done = sum(1 for step in run.steps
                       if step.status == "done")
            quests.append({
                "title": _clip(f"Automation: {run.goal}", 100),
                "done": done, "total": len(run.steps),
                "status": str(run.state),
                "href": f"/automation/{run.run_id}",
            })
            if len(quests) >= 10:
                break
    except Exception:
        pass
    return {"quests": quests}


def intel_panel(limit: int = 6) -> dict:
    """Conversation intelligence for the phone: open threads,
    decisions awaiting CONFIRM, contradictions, research
    proposals. Read-only; actions link to /conversations."""
    try:
        from .conversation_intel import cross_conversation
        aggregate = cross_conversation(limit=10)
    except Exception:
        return {"threads": [], "decisions": [], "research": []}
    threads = [{
        "text": str(item.get("text", ""))[:160],
        "conversations": item.get("conversations", [])[:4],
        "href": f"/conversations/{item.get('conversations', [''])[0]}"
        if item.get("conversations") else "/conversations",
    } for item in aggregate.get("contradictions", [])[:4]]
    decisions: list[dict] = []
    research: list[dict] = []
    try:
        from .conversation_bridge import list_imports
        from .conversation_intel import list_intel
        for meta in list_imports(limit=6):
            conversation_id = meta.get("conversation_id", "")
            try:
                items = list_intel(conversation_id, limit=60)
            except Exception:
                continue
            for entry in items:
                kind = str(entry.get("kind", ""))
                if kind == "decision" and len(decisions) < 3:
                    decisions.append({
                        "text": str(entry.get("text", ""))[:160],
                        "href": f"/conversations/{conversation_id}",
                    })
                elif kind == "research_proposal" and \
                        len(research) < 3:
                    research.append({
                        "text": str(entry.get("text", ""))[:160],
                        "href": f"/conversations/{conversation_id}",
                    })
            if len(decisions) >= 3 and len(research) >= 3:
                break
    except Exception:
        pass
    return {"threads": threads, "decisions": decisions,
            "research": research}


def dashboard(node: str = "") -> dict:
    """One bounded snapshot for /mobile + the JSON endpoint."""
    from . import main as _main
    try:
        from .guide import guide_items
        guide = guide_items(limit=6)
    except Exception:
        guide = []
    try:
        living = _main.coordinator_status()
    except Exception:
        living = {}
    try:
        cards = approval_cards(limit=10)
    except Exception:
        cards = []
    try:
        from .presence import attention_snapshot, progression
        from datetime import datetime as _dt
        snapshot = attention_snapshot(limit=60)
        greeting = ("GOOD MORNING" if _dt.now().hour < 12
                    else "NOW")
    except Exception:
        snapshot = {"bands": {band: [] for band in
                              ("needs", "waiting", "available",
                               "discovered", "offline")},
                    "counts": {}, "cleared": []}
        greeting = "NOW"
    try:
        prog = progression()
    except Exception:
        prog = {"quests": []}
    return {
        "waiting_count": len(cards),
        "cards": cards[:6],
        "greeting": greeting,
        "presence": {"bands": snapshot.get("bands", {}),
                     "counts": snapshot.get("counts", {}),
                     "cleared": snapshot.get("cleared", [])[:5]},
        "progression": {"quests": prog.get("quests", [])[:5],
                        "activity_24h": prog.get("activity_24h",
                                                 0)},
        "guide": guide,
        "camera": camera_panel(),
        "craft": craft_panel(),
        "symbiosis": symbiosis_panel(),
        "nodes": nodes_panel(),
        "progress": progress_panel(),
        "intel": intel_panel(),
        "notifications": notification_cards(node, limit=8),
        "packet": packet_preview(),
        "living": {
            "nodes_online": ((living.get("nodes") or {}).get(
                "online", "?")),
            "pending_approvals": living.get("pending_approvals",
                                            {}),
        },
    }
