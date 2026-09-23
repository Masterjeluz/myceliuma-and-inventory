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
    # BIG #42 ecosystem workflows: hardware verification,
    # finance/energy links, quest trails.
    "hardware", "finance", "energy", "quest",
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
    "hardware": "Verifying names a human, a device and evidence; "
                "only the operator key completes it. Revoking "
                "returns the claim to ADVERTISED.",
    "finance": "Confirming keeps the figure as stated; unknown "
               "amounts stay UNKNOWN. Finance never enters "
               "generic telemetry.",
    "energy": "Recording a reading stores exactly what was "
              "observed; unknown stays UNKNOWN and can still "
              "block routing honestly.",
    "quest": "Opening the quest shows each step's live record; "
             "progress is done/total over real work, never XP.",
}


def _item(kind: str, glyph: str, what: str, why: str,
          label: str, href: str, after: str = "",
          blocked_by: list | None = None,
          unlocks: list | None = None,
          evidence: list | None = None) -> dict:
    afterwards = (after or AFTER_TEXT.get(kind, "")[:240])

    def _clean(entries) -> list:
        cleaned = []
        for entry in (entries or [])[:4]:
            if not isinstance(entry, dict):
                continue
            label_text = str(entry.get("label", ""))[:60]
            href_text = str(entry.get("href", ""))[:200]
            if label_text and href_text:
                cleaned.append({"label": label_text,
                                "href": href_text})
        return cleaned

    return {"kind": kind, "glyph": glyph, "what": what[:160],
            "why": why[:240], "next": {"label": label[:60],
                                       "href": href[:200]},
            "after": afterwards,
            # BIG #43 companion layer: what blocks this, what it
            # unlocks, and the real records behind it.
            "blocked_by": _clean(blocked_by),
            "unlocks": _clean(unlocks),
            "evidence": _clean(evidence)}


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
            first = quiet[0]
            node_id = str(first.get("node_id", "?"))
            task = first.get("current_task") or {}
            last_task = (f"task #{task.get('id')}"
                         if isinstance(task, dict) and
                         task.get("id") else "no task assigned")
            items.append(_item(
                "node", "💻",
                f"{len(quiet)} node(s) quiet: {node_id}.",
                "Nodes are pull-only helpers; a quiet node "
                "simply stops claiming work. Last heartbeat "
                f"{str(first.get('last_seen', '?'))[:16]}; "
                f"last known: {last_task}. A fresh heartbeat "
                "restores availability — nothing else can.",
                "Open nodes", "/nodes",
                blocked_by=[{
                    "label": "stale heartbeat",
                    "href": "/nodes"}],
                unlocks=[{
                    "label": "node claims work again",
                    "href": "/nodes"}],
                evidence=[{
                    "label": f"{node_id} reality",
                    "href": f"/api/v1/nodes/{node_id}/reality"},
                    {"label": "nodes", "href": "/nodes"}]))
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
            task = node.get("current_task") or {}
            last_task = (f"task #{task.get('id')}"
                         if isinstance(task, dict) and
                         task.get("id") else "no task assigned")
            items.append(_item(
                "node", "💻",
                f"Node '{name}' is {node.get('derived_status', 'offline').lower()}.",
                "Pull-only helper stopped claiming work. Last "
                f"heartbeat "
                f"{str(node.get('last_seen', '?'))[:16]}; last "
                f"known: {last_task}. Check connectivity — a "
                "fresh heartbeat is what restores it.",
                "Open nodes", "/nodes",
                blocked_by=[{
                    "label": "no heartbeat",
                    "href": "/nodes"}],
                unlocks=[{
                    "label": "node back online",
                    "href": "/nodes"}],
                evidence=[{
                    "label": f"{name} reality",
                    "href": f"/api/v1/nodes/"
                            f"{node.get('node_id', '')}/reality"}]))
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
    # BIG #42 ecosystem workflows: every suggestion explains
    # WHAT / WHY / NEXT / unlock path, derived from live stores.
    try:
        from . import main as _main42
        nodes = _main42.list_nodes()
        try:
            from .hardware_links import list_links as _hw_links
            verified_refs: set = set()
            for _link in _hw_links(status="VERIFIED", limit=200):
                verified_refs.add(
                    (_link.node_id, _link.device_ref))
        except Exception:
            verified_refs = set()
        for node in nodes:
            node_id = str(node.get("node_id", ""))
            for hw in (node.get("hardware", []) or []):
                if not isinstance(hw, dict):
                    continue
                ident = str(hw.get("identifier", ""))
                kind = str(hw.get("kind", ""))
                if not ident:
                    continue
                if (node_id, ident) in verified_refs:
                    continue
                if kind.lower() in ("gpu", "camera", "printer_3d",
                                    "tpu") or str(
                        hw.get("status", "")).lower() == \
                        "connected":
                    items.append(_item(
                        "hardware", "🔗",
                        f"{node_id} advertises {kind or 'hardware'} "
                        f"'{ident[:40]}' — not human-verified.",
                        "Advertised is not a fact. A human link "
                        "with evidence promotes it to VERIFIED; "
                        "nothing else can.",
                        "Verify hardware", "/hardware",
                        blocked_by=[],
                        unlocks=[{
                            "label": "VERIFIED device trust",
                            "href": "/hardware"}],
                        evidence=[{
                            "label": f"{node_id} reality",
                            "href": f"/api/v1/nodes/{node_id}/"
                                    "reality"}]))
                    break
            if len(items) >= 20:
                break
    except Exception:
        pass
    try:
        from .energy import list_records as _energy_list
        from .finance import list_records as _finance_list
        finance_records = _finance_list(limit=200)
        energy_records = _energy_list(limit=200)
        finance_projects = {record.project_ref for record in
                            finance_records if record.project_ref}
        energy_projects = {record.project_ref for record in
                           energy_records if record.project_ref}
        lonely = sorted(project for project in finance_projects
                        if project not in energy_projects)[:3]
        for project in lonely:
            items.append(_item(
                "energy", "⚡",
                f"Project '{project[:60]}' has a finance record "
                "but no energy source.",
                "Money without power is a plan without a plug. "
                "Record the source (or UNKNOWN) to unblock "
                "energy-aware routing.",
                "Open energy", "/energy",
                blocked_by=[{
                    "label": "missing energy record",
                    "href": "/energy"}],
                unlocks=[{
                    "label": "energy-aware routing",
                    "href": "/energy"}],
                evidence=[{
                    "label": "finance records",
                    "href": "/finance"}]))
        try:
            from .symbiosis import proposed as _sym_proposed
            waiting_links = [prop for prop in _sym_proposed(limit=60)
                             if any(str(entity).startswith(
                                 ("enr_", "fin_"))
                                 for entity in
                                 prop.get("entities", []))]
        except Exception:
            waiting_links = []
        if waiting_links:
            first = waiting_links[0]
            items.append(_item(
                "finance", "🤝",
                "An energy/finance relationship waits for "
                "confirmation.",
                f"{first.get('title', 'link')[:120]} links "
                f"{', '.join(first.get('entities', [])[:2])}. "
                "Confirm it in symbiosis review.",
                "Review symbiosis", "/symbiosis",
                blocked_by=[{
                    "label": "human review",
                    "href": "/symbiosis"}],
                unlocks=[{
                    "label": "supported connection",
                    "href": "/symbiosis"}],
                evidence=[{
                    "label": "open proposals",
                    "href": "/symbiosis"}]))
    except Exception:
        pass
    try:
        from .presence import research_readiness as _readiness42
        readiness = _readiness42()
        eligible = readiness.get("eligible", []) or []
        if eligible:
            items.append(_item(
                "research", "🔓",
                f"Research can run on {eligible[0]}: online with "
                "the required capability.",
                str(readiness.get("text", ""))[:200],
                "Queue research", "/research"))
    except Exception:
        pass
    try:
        from .quests import list_quest_details as _quest_list42
        for quest in _quest_list42(limit=20):
            if quest.get("state") in ("BLOCKED", "FAILED"):
                waiting_step = next(
                    (step for step in quest.get("steps", [])
                     if step.get("state") in
                     ("BLOCKED", "FAILED", "WAITING",
                      "MISSING")), {})
                items.append(_item(
                    "quest", "🧭",
                    f"Quest '{quest.get('title', '')[:70]}' is "
                    f"{quest.get('state', '')} at "
                    f"{quest.get('done', 0)}/"
                    f"{quest.get('total', 0)}.",
                    "A step's underlying record failed or is "
                    "blocked — open the quest to see which one "
                    "and unlock it there.",
                    "Open quest", "/quests",
                    blocked_by=[{
                        "label": waiting_step.get(
                            "label", "blocked step")[:60],
                        "href": waiting_step.get(
                            "href", "/quests")}] if waiting_step
                    else [],
                    unlocks=[{
                        "label": "quest progress",
                        "href": "/quests"}],
                    evidence=[{
                        "label": f"quest "
                                 f"{quest.get('progress', '')}",
                        "href": "/quests"}]))
                break
    except Exception:
        pass
    # BIG #43 companion: campaign context cards (WHAT/WHY/
    # NEXT/BLOCKED BY/UNLOCKS/EVIDENCE over real records).
    try:
        from .campaigns import list_campaign_details as _camps43
        for campaign in _camps43(limit=5):
            if campaign.get("state") in ("COMPLETED",):
                continue
            nxt = campaign.get("next_action", {}) or {}
            current = campaign.get("current_quest", {}) or {}
            if not nxt.get("step"):
                continue
            items.append(_item(
                "quest", "🗺",
                f"{campaign.get('title', '')[:70]}: "
                f"{nxt.get('step', '')[:70]}",
                f"Campaign {campaign.get('completed_count', 0)}/"
                f"{campaign.get('total_count', 0)} — current "
                f"quest '{current.get('title', '')[:60]}'. "
                f"{nxt.get('readiness_reason', '')[:120]}",
                "Open campaign", "/campaigns",
                blocked_by=[{
                    "label": nxt.get("readiness", "see step"),
                    "href": nxt.get("href", "/quests")}],
                unlocks=[{
                    "label": "campaign step",
                    "href": "/campaigns"}],
                evidence=[
                    {"label": entry.get("label", "")[:60],
                     "href": entry.get("href", "/quests")}
                    for entry in
                    campaign.get("evidence", [])[:3]]))
            if len(items) >= 20:
                break
    except Exception:
        pass
    # BIG #45 relationship-aware cards: why entities are
    # connected, why a link is only PROPOSED, what blocks it,
    # what would verify it, which node can help. Evidence
    # only — no duplicated relationship logic.
    try:
        from .symbiosis import proposed as _props45
        proposals = _props45(limit=10)
        if proposals:
            first = proposals[0]
            entities = first.get("entities", [])[:2]
            pair = " ↔ ".join(entities) if entities else \
                "entities"
            items.append(_item(
                "finance" if any(str(entity).startswith(
                    "fin_") for entity in entities)
                else "energy" if any(str(entity).startswith(
                    "enr_") for entity in entities)
                else "candidate", "🔗",
                f"Possible connection: {pair[:90]}.",
                f"'{first.get('title', '')[:100]}' is "
                "PROPOSED because a candidate names both "
                "sides and nobody reviewed it yet. "
                "Verification needs the gate of its kind: "
                "knowledge review, operator key, or "
                "confirmation.",
                "Review connection", "/symbiosis",
                blocked_by=[{
                    "label": "human review",
                    "href": "/symbiosis"}],
                unlocks=[{
                    "label": "supported connection",
                    "href": "/symbiosis"}],
                evidence=[{
                    "label": "open proposals",
                    "href": "/symbiosis"}]))
    except Exception:
        pass
    try:
        from .presence import research_readiness as _ready45
        readiness = _ready45()
        eligible = readiness.get("eligible", []) or []
        if eligible:
            items.append(_item(
                "research", "🔧",
                f"Node {eligible[0]} can help with open "
                "research-linked work.",
                str(readiness.get("text", ""))[:200],
                "Queue research", "/research",
                unlocks=[{
                    "label": "research findings",
                    "href": "/research"}],
                evidence=[{
                    "label": f"{eligible[0]} nodes",
                    "href": "/nodes"}]))
    except Exception:
        pass
    try:
        items.extend(_verdant_items())
    except Exception:
        pass
    try:
        missing = _missing_sensor_item()
        if missing is not None:
            items.append(missing)
    except Exception:
        pass
    return items[: max(1, min(int(limit or 12), 20))]


def _missing_sensor_item() -> dict | None:
    """Eerlijke ontbrekende capability: geen enkele node adverteert
    verbonden sensor-hardware → bodem/water-meten is FUTURE. Zodra
    een sensor verschijnt, verdwijnt dit item vanzelf."""
    try:
        from . import main as _main
        records = _main.list_nodes() or []
    except Exception:
        return None
    for record in records:
        hardware = record.get("hardware", []) or []
        for item in hardware:
            if not isinstance(item, dict):
                continue
            if str(item.get("kind", "")).lower() == "sensor" \
                    and str(item.get("status", "")).lower() == \
                    "connected":
                return None
    return _item(
        "hardware", "📡",
        "Geen sensor-hardware verbonden — bodem/water meten "
        "is FUTURE.",
        "Ecology-meting vereist een node met verbonden sensor; "
        "alleen camera/snapshot bestaat echt.",
        "Bekijk hardware", "/hardware",
        evidence=[{"label": "node-hardware",
                   "href": "/nodes"}])


def _verdant_items() -> list[dict]:
    """Verdant-signalen als Guide-items met hun natuurlijke kinds.

    Geen nieuw kind, geen wereldontwaking-claim: solar-metingen als
    energy-item, ecology-dossiers als research-items. Alleen lokale
    stores (sync); INVENTory-termen blijven voorbehouden aan de
    /play-Verdant (async bridge). Lege stores = geen items.
    """
    from .world import VERDANT_TERMS
    found: list[dict] = []
    try:
        from .energy import list_records
        solar = list_records(source="solar", limit=50) or []
        if solar:
            found.append(_item(
                "energy", "☀",
                f"{len(solar)} solar-meting(en) in Mycelium.",
                "Echte metingen — de Verdant-bioom in /play "
                "ontwaakt hierdoor mee.",
                "Bekijk energy", "/energy",
                unlocks=[{"label": "Verdant in /play",
                           "href": "/play"}],
                evidence=[{"label": "energy records",
                           "href": "/energy"}]))
    except Exception:
        pass
    try:
        from .research_engine import list_dossiers
        for dossier in list_dossiers(limit=10) or []:
            try:
                data = dossier.model_dump(mode="json")
            except Exception:
                continue
            haystack = (f"{data.get('title', '')} "
                        f"{data.get('question', '')} "
                        f"{' '.join(data.get('open_questions', []) or [])}"
                        ).lower()
            if not any(term in haystack
                       for term in VERDANT_TERMS):
                continue
            dossier_id = str(data.get("dossier_id", "") or "")
            if not dossier_id:
                continue
            found.append(_item(
                "research", "🌿",
                f"Ecology-dossier: {str(data.get('title', ''))[:80]}.",
                "Echt onderzoek — voedt de Verdant-bioom in /play.",
                "Open dossier", f"/research/{dossier_id}",
                evidence=[{"label": "dossier",
                           "href": f"/research/{dossier_id}"}]))
            if len(found) >= 3:
                break
    except Exception:
        pass
    return found
