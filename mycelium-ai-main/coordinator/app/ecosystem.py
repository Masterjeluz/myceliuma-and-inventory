"""Living ecosystem helpers (BIG #30): entity context + activity voice.

- entity_context(): CONNECTED TO view for any world entity — inventory
  neighborhood (authoritative) plus overlay links from Mycelium domains
  (missions using it as context, research linked_entities, observations
  describing it, fabrication artifacts, registry nodes/printers).
  Never invents database facts: overlay links only attach when the
  source record explicitly references the entity.
- ecosystem_summary(): bounded counts across stores for the /world
  cockpit (projects, memories, missions, research, nodes, cameras,
  fabrications, events). Every number comes from a real store call.
- activity_voice(): maps bus events + notifications to warm, honest
  Mycelium voice ("Ik heb iets gevonden.", "Hier wacht ik op jou.")
  with links to real context. Technical detail stays in the payload.
"""

from __future__ import annotations

MYCELIUM_VOICE = {
    "research_completed": "Ik heb iets gevonden.",
    "observation_created": "Ik zag iets nieuws.",
    "node_online": "Een nieuwe helper is erbij.",
    "node_offline": "Ik ben een helper kwijt.",
    "approval_required": "Hier wacht ik op jou.",
    "mission_waiting": "Hier wacht ik op jou.",
    "memory_candidate": "Dit is nog maar een kandidaat.",
    "conversation_imported": "Ik heb een gesprek bewaard als context.",
    "fabrication_update": "Er is iets veranderd in de werkplaats.",
    "task_completed": "Dit is afgerond — verificatie blijft apart.",
    "system_attention": "Dit onderdeel bestaat nog niet helemaal.",
    "default": "Er gebeurde iets in het ecosysteem.",
}

_EVENT_VOICE = {
    "mission.completed": "research_completed",
    "mission.updated": "mission_waiting",
    "mission.started": "mission_waiting",
    "mission.failed": "system_attention",
    "task.completed": "task_completed",
    "task.failed": "system_attention",
    "task.queued": "mission_waiting",
    "task.assigned": "mission_waiting",
    "observation.created": "observation_created",
    "approval.required": "approval_required",
    "approval.resolved": "task_completed",
    "node.online": "node_online",
    "node.stale": "node_offline",
    "node.offline": "node_offline",
    "print.completed": "fabrication_update",
    "print.started": "fabrication_update",
    "conversation.message": "conversation_imported",
    "integration.received": "conversation_imported",
}


def voice_for_event(event_type: str) -> str:
    key = _EVENT_VOICE.get(str(event_type or ""), "default")
    return MYCELIUM_VOICE.get(key, MYCELIUM_VOICE["default"])


def context_links(entity_id: str) -> dict[str, str]:
    """Real endpoints an entity can act through (no fake actions)."""
    ident = str(entity_id or "")
    links: dict[str, str] = {
        "open_world": f"/world?entity_id={ident}",
    }
    if ident.startswith("proj_"):
        links["open_project"] = f"/projects?project_id={ident}"
        links["research"] = "/research"
    if ident.startswith("obj_"):
        links["research"] = "/research"
        links["workshop_3d"] = "/workshop/3d"
    if ident.startswith("cam_"):
        links["camera_api"] = f"/api/v1/cameras/{ident}/observations"
        links["availability"] = f"/api/v1/cameras/{ident}/availability"
    if ident.startswith("file_"):
        links["world"] = f"/world?entity_id={ident}"
    if ident.startswith("mem_"):
        links["memory"] = "/memory"
    if ident.startswith("mission_"):
        links["mission"] = f"/missions/{ident}"
    if ident.startswith("conv_"):
        links["conversation"] = f"/conversations/{ident}"
    return links


async def entity_context(entity_id: str, depth: int = 1) -> dict:
    """CONNECTED TO view: inventory neighborhood + explicit overlays."""
    from . import main as _main
    cleaned = str(entity_id or "").strip()[:100]
    if not cleaned:
        raise ValueError("entity_id is required")
    flags = {"missions", "nodes", "research", "observations", "printers"}
    graph, error = await _main._graph_data(cleaned, depth
                                           if depth in (1, 2) else 1,
                                           flags)
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    connected: list[dict] = []
    for edge in edges:
        if edge.get("from") == cleaned or edge.get("to") == cleaned:
            other = edge.get("to") if edge.get("from") == cleaned \
                else edge.get("from")
            connected.append({"entity_id": other,
                              "predicate": edge.get("predicate", ""),
                              "provenance": edge.get("provenance", {})})
    kinds: dict[str, int] = {}
    for node in nodes:
        kinds[str(node.get("type", "?"))] = kinds.get(
            str(node.get("type", "?")), 0) + 1
    entity_node = next((node for node in nodes
                        if node.get("id") == cleaned), None)
    return {
        "entity_id": cleaned,
        "entity": entity_node,
        "connected_to": connected[:40],
        "neighbor_kinds": kinds,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "actions": context_links(cleaned),
        "error": error,
        "honesty": "Inventory-relaties zijn feiten; dashed overlays "
                   "(missies/research/observaties/nodes) zijn Mycelium-"
                   "context met eigen provenance, geen tweede waarheid.",
    }


def ecosystem_summary() -> dict:
    """Bounded real counts for the /world cockpit."""
    summary: dict = {"counts": {}, "warnings": []}
    counts = summary["counts"]
    try:
        from . import main as _main
        reader = _main._world_reader()
        import anyio as _anyio

        async def _browse(kind: str) -> int:
            try:
                found = await reader.browse(kind)
                return len(found.results or [])
            except Exception:
                return -1

        async def _all() -> dict[str, int]:
            out = {}
            for kind in ("projects", "objects", "ideas", "files"):
                out[kind] = await _browse(kind)
            return out

        try:
            counts.update(_anyio.run(_all))
        except Exception:
            counts.update({kind: -1 for kind in
                           ("projects", "objects", "ideas", "files")})
    except Exception:
        counts.update({kind: -1 for kind in
                       ("projects", "objects", "ideas", "files")})
    try:
        from .memory import list_memories
        all_mems = list_memories(limit=5000)
        counts["memories"] = len(all_mems)
        counts["memory_candidates"] = sum(
            1 for entry in all_mems if entry.truth in
            ("ai_suggestion", "ai_inference"))
    except Exception:
        counts["memories"] = -1
        summary["warnings"].append("memories unavailable")
    try:
        from .missions import list_missions
        missions = list_missions(limit=200)
        counts["missions"] = len(missions)
        counts["missions_waiting"] = sum(
            1 for mission in missions if mission.status in
            ("pending_approval", "paused", "blocked"))
    except Exception:
        counts["missions"] = -1
    try:
        from .research_engine import list_dossiers, list_runs
        counts["research_runs"] = len(list_runs(limit=200))
        counts["research_dossiers"] = len(list_dossiers(limit=50))
    except Exception:
        counts["research_runs"] = -1
    try:
        from . import main as _main
        counts["nodes"] = len(_main.list_nodes())
        counts["events"] = len(_main.bus_events(limit=100))
    except Exception:
        counts["nodes"] = -1
    try:
        from .cameras import list_devices
        counts["cameras"] = len(list_devices())
    except Exception:
        counts["cameras"] = -1
    try:
        from .fabrication import list_fabrications
        counts["fabrications"] = len(list_fabrications(200))
    except Exception:
        counts["fabrications"] = -1
    try:
        from .conversation_bridge import list_imports
        counts["conversation_imports"] = len(list_imports(limit=200))
    except Exception:
        counts["conversation_imports"] = -1
    return summary


def activity_feed(limit: int = 30) -> list[dict]:
    """Living activity stream with Mycelium voice + real links."""
    from . import main as _main
    items: list[dict] = []
    try:
        events = _main.bus_events(limit=limit)
    except Exception:
        events = []
    for event in events:
        event_type = getattr(event, "event_type", "?")
        items.append({
            "voice": voice_for_event(event_type),
            "event_type": event_type,
            "summary": getattr(event, "summary", "")[:200],
            "created_at": getattr(event, "created_at", ""),
            "mission_id": getattr(event, "mission_id", ""),
            "node_id": getattr(event, "node_id", ""),
            "link": (f"/missions/{event.mission_id}"
                     if getattr(event, "mission_id", "") else
                     "/activity"),
        })
    try:
        notes = _main.list_notifications_for_report(limit=10)
        for note in notes:
            title = getattr(note, "title", str(note))[:160]
            mission = getattr(note, "related_mission", "")
            entity = getattr(note, "related_entity", "")
            task = getattr(note, "related_task", "")
            if mission:
                link = f"/missions/{mission}"
            elif entity:
                link = f"/world?entity_id={entity}"
            elif task:
                link = "/activity"
            else:
                link = "/activity"
            items.append({
                "voice": "Hier wacht ik op jou.",
                "event_type": "notification",
                "summary": title,
                "created_at": getattr(note, "created_at", ""),
                "mission_id": mission,
                "node_id": "",
                "link": link,
            })
    except Exception:
        pass
    return items[: max(1, min(int(limit or 30), 60))]


#: Node roles derived from advertised capabilities (BIG #31). A
#: machine does not need to do everything; roles describe what a
#: node volunteers for. Never authority, always description.
ROLE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("RESEARCH", ("research.",)),
    ("ANALYSIS", ("analysis.",)),
    ("INVENTORY", ("inventory.",)),
    ("CAMERA", ("camera.", "vision")),
    ("3D", ("mesh", "slice", "print", "fab", "cad")),
    ("INPUT", ("desktop_", "phone.", "screen", "microphone")),
)


def node_roles(record: dict) -> list[str]:
    """Roles for one node-registry record. Empty caps → GENERAL."""
    caps = [str(cap or "") for cap in (record.get("capabilities")
                                       or [])]
    roles: list[str] = []
    for role, prefixes in ROLE_RULES:
        if any(any(cap.startswith(prefix) for prefix in prefixes)
               for cap in caps):
            roles.append(role)
    if record.get("tier") == "seed" and "GENERAL" not in roles:
        roles.append("GENERAL")
    return roles or ["GENERAL"]


def ecosystem_overview() -> dict:
    """One coherent ecosystem model (BIG #41 V2 foundation).

    Answers WHAT EXISTS / CONNECTED / HAPPENING / NEEDS
    ATTENTION / NEXT / NODES CAN DO / BLOCKED / GROWING by
    composing existing stores (inventory counts, symbiosis,
    mesh, living state, presence, progression). No new store,
    no invented data: every section names its source, and any
    failing source degrades to an explicit -1/empty with the
    reason attached. Read-only.
    """
    out: dict = {"sources": {}, "warnings": []}

    def _put(key, value, source):
        out[key] = value
        out["sources"][key] = source

    # WHAT EXISTS — authoritative inventory counts + layers.
    try:
        summary = ecosystem_summary()
        _put("exists", summary.get("counts", {}),
             "inventory bridge + local stores "
             "(ecosystem_summary)")
        for warning in summary.get("warnings", []):
            out["warnings"].append(str(warning))
    except Exception as error:
        _put("exists", {}, f"unavailable ({error})")
        out["warnings"].append("inventory counts unavailable")
    # WHAT IS CONNECTED — symbiosis proposals + mesh edges.
    connected: dict = {"symbiosis_proposed": -1,
                       "mesh_edges": -1, "mesh_nodes": -1}
    try:
        from .symbiosis import proposed
        connected["symbiosis_proposed"] = len(proposed(limit=60))
    except Exception:
        out["warnings"].append("symbiosis proposals unavailable")
    try:
        from .nodemesh import mesh_topology
        topo = mesh_topology()
        connected["mesh_edges"] = len(topo.get("edges", []))
        connected["mesh_nodes"] = len(topo.get("nodes", []))
    except Exception:
        out["warnings"].append("mesh topology unavailable")
    _put("connected", connected,
         "knowledge candidates (PROPOSED) + node mesh")
    # WHAT IS HAPPENING — living state line + recent events.
    try:
        from .living_state import current_state
        state = current_state()
        happening = {"state": state.get("state", "?"),
                     "line": state.get("line", ""),
                     "reasons": state.get("reasons", [])[:5]}
    except Exception:
        happening = {"state": "?", "line": "", "reasons": []}
        out["warnings"].append("living state unavailable")
    try:
        from . import main as _main
        happening["recent"] = [
            {"type": event.event_type,
             "summary": str(event.summary or "")[:120],
             "at": str(event.created_at or "")[:16]}
            for event in _main.bus_events(limit=5)]
    except Exception:
        happening["recent"] = []
    _put("happening", happening,
         "living_state + event bus (last 5)")
    # WHAT NEEDS ATTENTION + WHAT CAN I DO NEXT — presence.
    try:
        from .presence import attention_snapshot
        from .presence import morning_presence_sections
        snapshot = attention_snapshot(limit=60)
        counts = snapshot.get("counts", {})
        top_needs = [
            {"id": item["id"], "title": item["title"],
             "href": item["open_href"]}
            for item in snapshot.get("bands", {}).get("needs",
                                                      [])[:3]]
        _put("needs_attention",
             {"counts": counts, "top": top_needs},
             "presence engine (12 live collectors)")
        sections = morning_presence_sections()
        _put("next", sections.get("presence_next", [])[:5],
             "presence suggested-next-actions")
    except Exception as error:
        _put("needs_attention", {"counts": {}, "top": []},
             f"unavailable ({error})")
        _put("next", [], "presence unavailable")
    # WHAT CAN MY NODES DO — online capabilities per node.
    nodes_can_do: list[dict] = []
    try:
        from . import main as _main2
        try:
            from .hardware_links import verified_device_refs as \
                _verified_refs42
        except Exception:
            _verified_refs42 = None
        for record in _main2.list_nodes():
            if record.get("derived_status") not in ("online",
                                                    "busy"):
                continue
            _verified = 0
            if _verified_refs42 is not None:
                try:
                    _verified = len(_verified_refs42(
                        str(record.get("node_id", ""))))
                except Exception:
                    _verified = 0
            nodes_can_do.append({
                "node_id": str(record.get("node_id", "")),
                "health": str(record.get("health_status",
                                         "UNKNOWN")),
                "capabilities": list(
                    record.get("capabilities", []) or [])[:12],
                "hardware": sorted({
                    str(item.get("kind", ""))
                    for item in (record.get("hardware", []) or [])
                    if isinstance(item, dict)
                    and str(item.get("status", "")) == "connected"
                })[:8],
                "hardware_verified": _verified,
                "current_task": record.get("current_task")})
            if len(nodes_can_do) >= 15:
                break
    except Exception:
        out["warnings"].append("node registry unavailable")
    _put("nodes_can_do", nodes_can_do,
         "node registry (advertised, online only; "
         "hardware_verified counts human links)")
    # WHAT IS BLOCKED — needs-band items of blocking types.
    blocked: list[dict] = []
    try:
        from .presence import attention_snapshot as _snap
        for item in _snap(limit=120)["items"]:
            if item.get("type", "") in (
                    "mission_blocked", "mission_failed",
                    "task_failed", "automation_failed",
                    "fabrication_blocked"):
                blocked.append({"id": item["id"],
                                "title": item["title"],
                                "href": item["open_href"]})
            if len(blocked) >= 10:
                break
    except Exception:
        out["warnings"].append("blocked-work scan unavailable")
    _put("blocked", blocked, "presence blocking types")
    # WHAT IS GROWING — progression, store-backed only.
    try:
        from .presence import progression
        prog = progression()
        _put("growing",
             {"quests_open": len(prog.get("quests", [])),
              "discoveries_24h": prog.get("discoveries_24h", 0),
              "observations_24h": prog.get("observations_24h",
                                            0),
              "growth_24h": prog.get("growth_24h", 0),
              "activity_24h": prog.get("activity_24h", 0),
              "capabilities_unlocked": prog.get(
                  "capabilities_unlocked", [])[:20]},
             "presence progression (no XP, real counts)")
    except Exception:
        _put("growing", {}, "progression unavailable")
    # BIG #42 ecosystem hardening: hardware trust, finance,
    # energy, quest trails. Additive sections; each names its
    # source and degrades to explicit empty.
    try:
        from .hardware_links import list_links as _hw_links42
        _all_hw = _hw_links42(limit=200)
        _put("hardware",
             {"links": len(_all_hw),
              "verified": sum(1 for link in _all_hw
                              if link.status == "VERIFIED"),
              "proposed": sum(1 for link in _all_hw
                              if link.status == "PROPOSED"),
              "revoked": sum(1 for link in _all_hw
                             if link.status == "REVOKED")},
             "hardware links store (human-verified only)")
    except Exception:
        _put("hardware", {}, "hardware links unavailable")
    try:
        from .finance import summarize as _fin_sum42
        _put("finance", _fin_sum42(),
             "finance records (counts; amounts scoped)")
    except Exception:
        _put("finance", {}, "finance records unavailable")
    try:
        from .energy import summarize as _en_sum42
        _put("energy", _en_sum42(),
             "energy records (UNKNOWN stays unknown)")
    except Exception:
        _put("energy", {}, "energy records unavailable")
    try:
        from .quests import list_quest_details as _quests42
        _quests = _quests42(limit=50)
        _put("quests",
             {"open": sum(1 for quest in _quests
                          if quest.get("state") not in
                          ("COMPLETED",)),
              "completed": sum(1 for quest in _quests
                               if quest.get("state") ==
                               "COMPLETED"),
              "trails": [{"quest_id": quest.get("quest_id", ""),
                          "title": quest.get("title", "")[:80],
                          "state": quest.get("state", ""),
                          "progress": quest.get("progress",
                                                "0/0")}
                         for quest in _quests[:10]]},
             "quest trails (derived from live records)")
    except Exception:
        _put("quests", {}, "quest trails unavailable")
    from datetime import datetime, timezone
    out["generated_at"] = datetime.now(timezone.utc).isoformat()
    out["provenance"] = {"source_type": "derived",
                         "creator_id": "ecosystem-overview",
                         "human_verified": False}
    return out


def discoveries(limit: int = 20) -> dict:
    """'Te tonen aan Jelles': open questions + missed items across
    imports, plus unlinked research questions. Evidence-backed
    only; nothing stored, nothing promoted."""
    from .conversation_bridge import (list_imports, load_analysis,
                                      missed_items)
    count = max(1, min(int(limit or 20), 40))
    items: list[dict] = []
    try:
        imports = list_imports(limit=10)
    except Exception:
        imports = []
    for meta in imports:
        conversation_id = meta["conversation_id"]
        try:
            analysis = load_analysis(conversation_id) or {}
            missed = missed_items(conversation_id, analysis)
        except Exception:
            continue
        for item in missed[:4]:
            items.append({
                "conversation_id": conversation_id,
                "title": meta.get("title", "")[:80],
                "kind": item.get("kind", ""),
                "text": str(item.get("text", ""))[:200],
                "evidence": str(item.get("evidence", ""))[:160],
                "link": f"/conversations/{conversation_id}",
            })
            if len(items) >= count:
                break
        if len(items) >= count:
            break
    research_open: list[dict] = []
    try:
        from .research_engine import list_dossiers
        for dossier in list_dossiers(limit=5):
            for question in dossier.open_questions[:2]:
                research_open.append({
                    "dossier_id": dossier.dossier_id,
                    "question": question[:200],
                    "link": f"/research/{dossier.dossier_id}",
                })
    except Exception:
        pass
    return {"items": items[:count],
            "research_open_questions": research_open[:10],
            "imports_considered": len(imports)}
