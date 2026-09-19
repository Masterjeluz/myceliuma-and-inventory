"""Mycelium Guide (BIG #33): what needs Jelles, derived live.

The guide is not a chatbot and never invents advice. It reads
existing state on every call and returns WHAT / WHY / NEXT
items that link to real pages:

- approvals waiting (desktop, writes, missions)
- knowledge candidates waiting for review
- conversation missed items (unresolved questions, ideas)
- research dossiers with open questions
- camera inbox files ready for analysis
- fabrications waiting for a next step
- nodes that went quiet
- projects that have no mission carrying them

Read-only. Bounded. Nothing stored, nothing promoted.
"""

from __future__ import annotations

GUIDE_KINDS = (
    "approval", "candidate", "conversation", "research",
    "camera", "fabrication", "node", "project", "mission",
    "workshop",
)


#: AFTERWARDS per kind (BIG #40 explanation layer): what
#: truthfully happens after the NEXT step. Mechanics only —
#: no invented outcomes, no promises.
AFTER_TEXT = {
    "approval": "After your YES the existing decision "
                "endpoint runs exactly that payload; the item "
                "then leaves the waiting list. NO closes it "
                "without effect.",
    "candidate": "Support keeps it a reviewed candidate; "
                 "promote turns it into memory. Either way it "
                 "leaves this list.",
    "conversation": "Queued research returns findings you "
                    "review line by line; nothing promotes "
                    "itself.",
    "research": "Completed dossiers wait for your review; "
                "claims become candidates only when you say "
                "so.",
    "camera": "Ingest turns files into observations; a VLM "
              "description turns them into reviewable text.",
    "fabrication": "Your approval moves exactly the proposed "
                   "payload; execution and independent "
                   "verification follow as their own steps.",
    "node": "Nodes are pull-only helpers; restored "
            "connectivity lets them claim work again. "
            "Nothing is ever pushed to a node.",
    "project": "Opening a mission for the project gives it a "
               "carrier; each step still asks its own gates.",
    "mission": "Resuming wakes one quest; consequential "
              "steps stop for YES again.",
    "workshop": "Linking material and project starts a real "
               "craft chain you can verify step by step.",
}


def _item(kind: str, glyph: str, what: str, why: str,
          label: str, href: str, after: str = "") -> dict:
    afterwards = (after or AFTER_TEXT.get(kind, "")[:240])
    return {"kind": kind, "glyph": glyph, "what": what[:160],
            "why": why[:240], "next": {"label": label[:60],
                                       "href": href[:200]},
            "after": afterwards}


def guide_items(limit: int = 12) -> list[dict]:
    """Compute guide items from live stores. Never raises."""
    items: list[dict] = []
    try:
        from . import main as _main
        status = _main.coordinator_status()
        approvals = status.get("pending_approvals", {})
        waiting = sum(int(approvals.get(key, 0)) for key in
                      ("desktop_actions", "write_proposals",
                       "missions"))
        if waiting:
            items.append(_item(
                "approval", "🟡",
                f"{waiting} thing(s) waiting for your YES.",
                "Approvals never auto-resolve. Nothing moves "
                "until you decide.",
                "Review approvals", "/agents"))
    except Exception:
        pass
    try:
        from .knowledge import list_candidates
        candidates = list_candidates(limit=50)
        if candidates:
            items.append(_item(
                "candidate", "🌱",
                f"{len(candidates)} candidate(s) wait for review.",
                "Observations stay candidates until you support "
                "or promote them.",
                "Open knowledge", "/knowledge"))
    except Exception:
        pass
    try:
        from .ecosystem import discoveries
        found = discoveries(limit=6)
        missed = found.get("items", [])
        if missed:
            first = missed[0]
            items.append(_item(
                "conversation", "💬",
                f"{len(missed)} possible missed item(s) in "
                f"{found.get('imports_considered', '?')} "
                "conversation(s).",
                str(first.get("text", ""))[:200],
                "Review conversation",
                str(first.get("link", "/conversations"))))
        open_questions = found.get("research_open_questions", [])
        if open_questions:
            first = open_questions[0]
            items.append(_item(
                "research", "🔬",
                f"{len(open_questions)} open research question(s).",
                str(first.get("question", ""))[:200],
                "Open dossier",
                str(first.get("link", "/research"))))
    except Exception:
        pass
    try:
        from .vision_ingest import list_inbox_files
        inbox = list_inbox_files(limit=5)
        if inbox:
            items.append(_item(
                "camera", "📷",
                f"{len(inbox)} camera file(s) wait in the inbox.",
                "New visual material becomes an observation "
                "only after ingest.",
                "Open cameras", "/cameras"))
    except Exception:
        pass
    try:
        from .cameras import list_devices, list_observations
        from .vision_flow import list_analyses
        fresh: list[tuple[str, str]] = []
        for device in list_devices()[:10]:
            for observation in list_observations(
                    device.device_id, limit=10)[:10]:
                try:
                    analyses = list_analyses(
                        observation.observation_id, limit=1)
                except Exception:
                    analyses = []
                if not analyses:
                    fresh.append((device.device_id,
                                  observation.observation_id))
                    break
            if len(fresh) >= 3:
                break
        if fresh:
            device_id, observation_id = fresh[0]
            items.append(_item(
                "camera", "👁",
                f"{len(fresh)} observation(s) wait for a VLM "
                "description.",
                "Photos stay mute until described (REAL) or "
                "honestly marked (UNAVAILABLE).",
                "Describe now",
                f"/cameras/{device_id}"))
    except Exception:
        pass
    try:
        from . import main as _main
        waiting_fab = [record for record in
                       _main.list_fabrications(50)
                       if record.status in ("proposed", "approved",
                                            "ready", "waiting")]
        if waiting_fab:
            items.append(_item(
                "fabrication", "🛠",
                f"{len(waiting_fab)} fabrication(s) wait "
                "for a next step.",
                "Physical work only moves with your explicit "
                "approval.",
                "Open fabrication", "/fabrication"))
    except Exception:
        pass
    try:
        from . import main as _main
        quiet = [record for record in _main.list_nodes()
                 if record.get("derived_status") in
                 ("stale", "offline")]
        if quiet:
            items.append(_item(
                "node", "💻",
                f"{len(quiet)} node(s) quiet: "
                f"{quiet[0].get('node_id', '?')}.",
                "Nodes are pull-only helpers; a quiet node "
                "simply stops claiming work.",
                "Open nodes", "/nodes"))
    except Exception:
        pass
    # BIG #39: Hardware Reality Layer - hardware-aware guidance
    try:
        from . import main as _main
        nodes_data = _main.list_nodes()
        # Online nodes with Ollama
        ollama_nodes = [n for n in nodes_data
                        if n.get("health_status") == "ONLINE"
                        and any(c.get("capability") == "ollama"
                                for c in (n.get("compute_capabilities") or [])
                                if isinstance(c, dict))]
        if ollama_nodes:
            node = ollama_nodes[0]
            name = node.get("display_name") or node.get("hostname") or node.get("node_id")
            items.append(_item(
                "node", "🧠",
                f"Research node '{name}' is online with Ollama.",
                "Local LLM inference available for research tasks.",
                "Open nodes", "/nodes"))
        # Online nodes with GPU
        gpu_nodes = [n for n in nodes_data
                     if n.get("health_status") == "ONLINE"
                     and any(c.get("capability") == "gpu_available"
                             for c in (n.get("compute_capabilities") or [])
                             if isinstance(c, dict))]
        if gpu_nodes:
            node = gpu_nodes[0]
            name = node.get("display_name") or node.get("hostname") or node.get("node_id")
            items.append(_item(
                "node", "🎮",
                f"Compute node '{name}' has GPU available.",
                "GPU acceleration for inference and training workloads.",
                "Open nodes", "/nodes"))
        # Nodes with cameras
        camera_nodes = [n for n in nodes_data
                        if n.get("health_status") == "ONLINE"
                        and any(h.get("kind") == "camera"
                                for h in (n.get("hardware") or [])
                                if isinstance(h, dict) and h.get("status") == "connected")]
        if camera_nodes:
            node = camera_nodes[0]
            name = node.get("display_name") or node.get("hostname") or node.get("node_id")
            cam_count = sum(1 for h in (node.get("hardware") or [])
                            if isinstance(h, dict) and h.get("kind") == "camera" and h.get("status") == "connected")
            items.append(_item(
                "node", "📷",
                f"Node '{name}' has {cam_count} camera(s) connected.",
                "Visual observation and analysis available.",
                "Open nodes", "/nodes"))
        # Nodes with 3D printers
        printer_nodes = [n for n in nodes_data
                         if n.get("health_status") == "ONLINE"
                         and any(h.get("kind") == "printer_3d"
                                 for h in (n.get("hardware") or [])
                                 if isinstance(h, dict) and h.get("status") == "connected")]
        if printer_nodes:
            node = printer_nodes[0]
            name = node.get("display_name") or node.get("hostname") or node.get("node_id")
            items.append(_item(
                "node", "🖨",
                f"Fabrication node '{name}' has 3D printer connected.",
                "Physical printing capability available.",
                "Open nodes", "/nodes"))
        # Offline nodes that were previously online
        offline_nodes = [n for n in nodes_data
                         if n.get("derived_status") in ("offline", "stale")
                         and n.get("health_status") in ("OFFLINE", "STALE")]
        if offline_nodes:
            node = offline_nodes[0]
            name = node.get("display_name") or node.get("hostname") or node.get("node_id")
            items.append(_item(
                "node", "💻",
                f"Node '{name}' is {node.get('derived_status', 'offline').lower()}.",
                "Pull-only helper stopped claiming work. Check connectivity.",
                "Open nodes", "/nodes"))
        # Registered hardware not currently connected
        registered_hw = []
        for n in nodes_data:
            for h in (n.get("hardware") or []):
                if isinstance(h, dict) and h.get("status") == "disconnected":
                    registered_hw.append((n, h))
        if registered_hw:
            node, hw = registered_hw[0]
            name = node.get("display_name") or node.get("hostname") or node.get("node_id")
            items.append(_item(
                "node", "🔌",
                f"Hardware '{hw.get('identifier', '?')}' ({hw.get('kind', '?')}) on '{name}' is registered but disconnected.",
                "Device was previously seen but not currently connected.",
                "Open nodes", "/nodes"))
        # Research waiting / unlock: one honest readiness check
        # shared with presence (BIG #41 Guide 2.0). The old inline
        # check passed raw registry rows without fresh/auth
        # flags, so it cried wolf on healthy meshes.
        try:
            from .presence import research_readiness
            readiness = research_readiness()
        except Exception:
            readiness = {"eligible": [], "unavailable": [],
                         "text": "Routing unavailable.",
                         "checked": False}
        if readiness.get("checked") and not readiness.get(
                "eligible"):
            items.append(_item(
                "node", "🔬",
                "Research is waiting: no eligible node with Ollama + fetch.",
                readiness.get("text", "Tasks queue until a "
                                       "capable, fresh, authenticated "
                                       "node appears."),
                "Open nodes", "/nodes"))
        elif readiness.get("eligible"):
            first = readiness["eligible"][0]
            items.append(_item(
                "node", "🔓",
                f"Research unlocked: '{first}' can run it now.",
                "A capable, fresh, authenticated node is "
                "available. Queue research and it routes there.",
                "Queue research", "/research"))
        # WHAT IS BLOCKING ME: failed/blocked automation + missions
        try:
            from .automation import list_runs as _auto_runs
            stuck = [run for run in _auto_runs(limit=20)
                     if run.state in ("failed", "blocked")][:2]
        except Exception:
            stuck = []
        for run in stuck:
            items.append(_item(
                "mission", "⚠",
                f"Automation {run.state}: {run.goal[:90]}",
                "A bound or refusal stopped the run. Unlock it "
                "by inspecting the exact failure, then resume "
                "or cancel — the gate re-checks live state.",
                "Inspect run", f"/automation/{run.run_id}"))
        try:
            from .missions import list_missions as _list_missions
            dead = [m for m in _list_missions(limit=50)
                    if m.status in ("failed", "blocked")][:2]
        except Exception:
            dead = []
        for mission in dead:
            items.append(_item(
                "mission", "⚠",
                f"Mission {mission.status}: "
                f"{mission.goal[:90]}",
                "A step failed safely; nothing executed beyond "
                "the plan. Unlock it by reviewing the failed "
                "step, then resume or cancel.",
                "Open mission",
                f"/missions/{mission.mission_id}"))
    except Exception:
        pass
    try:
        from . import main as _main
        from .missions import list_missions
        missions = list_missions(limit=100)
        mission_text = " ".join(
            f"{m.goal} {m.context or ''}" for m in missions)[:4000]
        reader = _main._world_reader()
        import anyio as _anyio

        async def _projects() -> list:
            try:
                browsed = await reader.browse("projects")
                return browsed.results or []
            except Exception:
                return []

        try:
            projects = _anyio.run(_projects)
        except Exception:
            projects = []
        orphan = None
        for record in projects[:20]:
            ident = str(record.entity_id)
            if ident not in mission_text:
                orphan = ident
                break
        if orphan and len(projects) >= 1:
            items.append(_item(
                "project", "🌿",
                "A project has no mission carrying it.",
                f"{orphan} appears in no mission goal or "
                "context yet.",
                "Open craft tree",
                f"/craft?entity_id={orphan}"))
        running = [m for m in missions
                   if m.status in ("approved", "running")]
        if not running and missions:
            items.append(_item(
                "mission", "🧭",
                "No mission is currently running.",
                "Paused work waits; pick one quest to wake up.",
                "Open missions", "/missions"))
    except Exception:
        pass
    try:
        from .workshop3d import list_fabjobs, list_models
        models = list_models(limit=50)
        jobs = list_fabjobs(limit=50)
        try:
            from .knowledge import list_candidates
            candidates = list_candidates(limit=300)
        except Exception:
            candidates = []
        linked_models: set[str] = set()
        model_projects: dict[str, set[str]] = {}
        for entry in candidates:
            try:
                data = entry.model_dump(mode="json")
            except Exception:
                continue
            if data.get("candidate_type") != "connection":
                continue
            refs = data.get("entity_refs") or []
            for ref in refs:
                if str(ref).startswith("mdl_"):
                    linked_models.add(str(ref))
                    model_projects.setdefault(str(ref), set()).update(
                        other for other in refs
                        if str(other).startswith("proj_"))
        bare = [model for model in models
                if model.get("model_id") not in linked_models]
        if bare:
            items.append(_item(
                "workshop", "🧊",
                f"{bare[0]['filename'][:60]} has a model but no "
                "material or project.",
                "A model alone builds nothing — link material "
                "and a project to start a craft chain.",
                "Open 3D workbench", "/3d"))
        awaiting = [job for job in jobs
                    if job.get("stage") in ("observed", "verifying")]
        if awaiting:
            items.append(_item(
                "workshop", "📷",
                f"Fab job {awaiting[0]['job_id'][:24]} waits for "
                "human verification.",
                "Camera evidence exists but is not reviewed. "
                "Verify or send it back.",
                "Verify the print", "/3d"))
        blocked = [job for job in jobs
                   if job.get("stage") == "blocked"]
        if blocked:
            items.append(_item(
                "workshop", "■",
                f"Fab job {blocked[0]['job_id'][:24]} is blocked.",
                "Something in the chain refused — inspect before "
                "retrying.",
                "Inspect the job", "/3d"))
        reusable = [(model_id, projects) for model_id, projects
                    in model_projects.items() if len(projects) >= 2]
        if reusable:
            model_id, projects = reusable[0]
            items.append(_item(
                "workshop", "🔗",
                f"Model {model_id[:16]} serves "
                f"{len(projects)} projects.",
                "One model, several craft chains — check whether "
                "they can share material and machine time.",
                "Open symbiosis", "/symbiosis"))
    except Exception:
        pass
    try:
        from .conversation_bridge import list_imports
        from .conversation_intel import (
            cross_conversation, list_intel)
        imports = list_imports(limit=10)
        fresh = None
        for meta in imports:
            conversation_id = meta.get("conversation_id", "")
            try:
                intel = list_intel(conversation_id, limit=100)
            except Exception:
                continue
            kinds: dict[str, int] = {}
            for entry in intel:
                kind = str(entry.get("kind", ""))
                kinds[kind] = kinds.get(kind, 0) + 1
            missed = kinds.get("missed", 0)
            research = kinds.get("research_proposal", 0)
            contradictions = kinds.get("contradiction", 0)
            if missed or research or contradictions:
                fresh = (meta, missed, research, contradictions)
                break
        if fresh is not None:
            meta, missed, research, contradictions = fresh
            conversation_id = meta.get("conversation_id", "")
            items.append(_item(
                "conversation", "🔍",
                f"{meta.get('title', '')[:60]}: {missed} missed, "
                f"{research} research, {contradictions} "
                f"contradictions.",
                "Analysis found reviewable structure — nothing "
                "promotes itself.",
                "Review intelligence",
                f"/conversations/{conversation_id}"))
        try:
            aggregate = cross_conversation(limit=10)
        except Exception:
            aggregate = {"revisits": [],
                         "contradictions": []}
        revisits = aggregate.get("revisits", [])
        if revisits:
            first = revisits[0]
            items.append(_item(
                "conversation", "🔁",
                f"'{first.get('term', '')[:50]}' returns in "
                f"{len(first.get('conversations', []))} "
                f"conversations without progress.",
                "Repeated without visible progress — revisit or "
                "park it explicitly.",
                "Revisit?", "/conversations"))
        open_contradictions = [
            item for item in aggregate.get("contradictions", [])
            if item.get("status") == "UNRESOLVED"][:5]
        if open_contradictions and not revisits:
            first = open_contradictions[0]
            conversations = first.get("conversations", [])
            items.append(_item(
                "conversation", "⚖",
                "A contradiction needs your attention.",
                str(first.get("text", ""))[:200],
                "Resolve it",
                f"/conversations/{conversations[0]}"
                if conversations else "/conversations"))
    except Exception:
        pass
    try:
        from .automation import list_runs
        for run in list_runs(limit=50):
            if run.state == "waiting_for_human":
                waiting = run.waiting or {}
                items.append(_item(
                    "mission", "🟡",
                    f"Automation waits: {run.goal[:90]}",
                    str(waiting.get("reason", "gate unmet"))[:200],
                    "Resume run", f"/automation/{run.run_id}"))
            elif run.state == "blocked":
                items.append(_item(
                    "mission", "⚠",
                    f"Automation blocked: {run.goal[:90]}",
                    "A bound or refusal stopped the run; inspect "
                    "before re-driving.",
                    "Inspect run", f"/automation/{run.run_id}"))
            elif run.state == "failed":
                items.append(_item(
                    "mission", "✕",
                    f"Automation failed: {run.goal[:90]}",
                    "A step failed safely; nothing executed "
                    "beyond the plan.",
                    "Review run", f"/automation/{run.run_id}"))
            if len(items) >= 20:
                break
    except Exception:
        pass
    return items[: max(1, min(int(limit or 12), 20))]
