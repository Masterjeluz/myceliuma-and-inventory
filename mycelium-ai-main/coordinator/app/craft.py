"""Craft Tree (BIG #33): from idea to made thing, on real records.

Stages (presentational order, every node clickable to its real
record):

    IDEA -> PROJECT -> REQUIREMENTS -> MATERIALS -> COMPONENTS
    -> MACHINES -> 3D MODEL -> FABRICATION -> RESULT
    -> OBSERVATION -> IMPROVEMENT -> NEW PROJECT

Nothing is invented: each stage lists entities that explicitly
reference the focus entity (inventory neighborhood, linked
research dossiers, missions using it as context, files,
observations, fabrications). Gaps name what is missing and
where to act ("No 3D model linked yet — open the 3D
workshop"), never fake nodes.
"""

from __future__ import annotations

from .symbiosis import clean_entity

#: Presentational stage order with the growth glyph per stage.
STAGES = (
    ("idea", "🌱", "Idea"),
    ("project", "🌿", "Project"),
    ("requirements", "📋", "Requirements"),
    ("materials", "🪵", "Materials"),
    ("components", "🔩", "Components"),
    ("machines", "⚙️", "Machines"),
    ("model_3d", "🧊", "3D model"),
    ("fabrication", "🛠", "Fabrication"),
    ("result", "🎁", "Result"),
    ("observation", "👁", "Observation"),
    ("improvement", "🌱", "Improvement"),
    ("new_project", "🌳", "New project"),
)

_IDEAS = ("idea",)
_PROJECTS = ("project",)
_MATERIALS = ("object", "file")
_COMPONENTS = ("object", "hardware", "sensor", "actuator")
_MACHINES = ("hardware", "node", "printer", "device")
_MODELS = ("file", "model", "artifact")
_FABRICATION = ("print_job", "artifact", "fabrication")
_OBSERVATIONS = ("observation", "event", "memory", "candidate")


def _bucket(node_type: str) -> str:
    kind = str(node_type or "").lower()
    if kind in _IDEAS:
        return "idea"
    if kind in _PROJECTS:
        return "project"
    if kind in _MATERIALS and kind == "file":
        return "materials"
    if kind in _COMPONENTS:
        return "components"
    if kind in _MACHINES:
        return "machines"
    if kind in _MODELS:
        return "model_3d"
    if kind in _FABRICATION:
        return "fabrication"
    if kind in _OBSERVATIONS:
        return "observation"
    if kind in ("mission", "research", "conversation"):
        return "requirements"
    if kind == "object":
        return "materials"
    return "requirements"


def _node_link(node: dict) -> dict:
    ident = str(node.get("id", ""))
    kind = str(node.get("type", node.get("kind", "")))
    label = str(node.get("label", ident))[:80]
    source = str(node.get("source", ""))
    if ident.startswith(("obj_", "proj_", "idea_", "loc_",
                         "hw_", "file_")):
        href = f"/world?entity_id={ident}"
    elif ident.startswith("mem_"):
        href = "/memory"
    elif ident.startswith("mission_"):
        href = f"/missions/{ident}"
    elif ident.startswith("conv_"):
        href = f"/conversations/{ident}"
    elif ident.startswith("cand_"):
        href = "/knowledge"
    else:
        href = "/world"
    return {"id": ident, "kind": kind, "label": label,
            "source": source, "href": href}


async def craft_tree(entity_id: str, depth: int = 1) -> dict:
    """Build the craft tree around one focus entity."""
    from .ecosystem import entity_context
    cleaned = clean_entity(entity_id)
    context = await entity_context(
        cleaned, depth if depth in (1, 2) else 1)
    stages: dict[str, list[dict]] = {
        key: [] for key, _, _ in STAGES
    }
    entity_node = context.get("entity") or {}
    if entity_node:
        bucket = _bucket(entity_node.get("type"))
        stages[bucket].append(_node_link({
            "id": cleaned,
            "type": entity_node.get("type", ""),
            "label": entity_node.get("label", cleaned),
            "source": entity_node.get("source", "inventory"),
        }))
    graph_nodes: dict[str, dict] = {}
    try:
        from . import main as _main
        graph, _ = await _main._graph_data(
            cleaned, depth if depth in (1, 2) else 1,
            {"missions", "nodes", "research", "observations",
             "printers", "memory", "candidates",
             "conversations"})
        for node in graph.get("nodes", []):
            if str(node.get("id")) == cleaned:
                continue
            graph_nodes[str(node.get("id"))] = node
    except Exception:
        graph_nodes = {}
    for node in graph_nodes.values():
        link = _node_link(node)
        bucket = _bucket(node.get("type", node.get("kind")))
        if len(stages[bucket]) < 12:
            stages[bucket].append(link)
    gaps: list[dict] = []
    if not stages["idea"]:
        gaps.append({"missing": "idea",
                     "hint": "No seed idea linked yet.",
                     "href": "/conversations"})
    if not stages["project"]:
        gaps.append({"missing": "project",
                     "hint": "No project carries this yet.",
                     "href": "/projects"})
    if not stages["components"] and not stages["materials"]:
        gaps.append({"missing": "materials",
                     "hint": "No materials or components linked.",
                     "href": "/search"})
    if not stages["machines"]:
        gaps.append({"missing": "machines",
                     "hint": "No machine or node can build this yet.",
                     "href": "/nodes"})
    if not stages["model_3d"]:
        gaps.append({"missing": "model_3d",
                     "hint": "No 3D model linked yet.",
                     "href": "/workshop/3d"})
    if not stages["fabrication"]:
        gaps.append({"missing": "fabrication",
                     "hint": "Nothing fabricated from this yet.",
                     "href": "/fabrication"})
    if not stages["observation"]:
        gaps.append({"missing": "observation",
                     "hint": "No observation feeds back yet.",
                     "href": "/cameras"})
    present = sum(1 for key in stages if stages[key])
    if present >= 10:
        growth = "bloom"
    elif present >= 6:
        growth = "growing"
    elif present >= 3:
        growth = "sprout"
    else:
        growth = "seed"
    ordered = [{"key": key, "glyph": glyph, "title": title,
                "nodes": stages[key]}
               for key, glyph, title in STAGES]
    return {
        "entity_id": cleaned,
        "stages": ordered,
        "gaps": gaps,
        "growth": growth,
        "stages_present": present,
        "error": context.get("error", ""),
        "honesty": "Every node is a real record that references "
                   "this entity. Gaps are missing links, not "
                   "predictions.",
    }


#: Chain states (BIG #41 craft foundation). COMPLETE means
#: linked evidence is present (never "work finished");
#: ACTIVE means linked work is in flight; BLOCKED means a
#: linked record failed or blocked; MISSING means the stage
#: is empty. Evidence ids are always listed.
STAGE_STATE_GLYPHS = {
    "complete": "✓",
    "active": "●",
    "missing": "○",
    "blocked": "!",
}

_MISSION_ACTIVE = ("approved", "running", "paused",
                   "pending_approval")
_MISSION_BLOCKED = ("failed", "blocked")
_FABJOB_ACTIVE = ("observed", "verifying")
_FABJOB_BLOCKED = ("blocked", "failed")
_FAB_ACTIVE = ("proposed", "approved", "ready", "waiting")
_FAB_BLOCKED = ("failed", "blocked")


def _live_work_status() -> tuple[dict, dict, dict]:
    """Live work statuses keyed by record id. Best-effort:
    empty maps on any failure (stages then show evidence-only
    states, never blocked/active without proof)."""
    missions: dict[str, str] = {}
    try:
        from .missions import list_missions
        for mission in list_missions(limit=100):
            missions[str(mission.mission_id)] = str(
                mission.status or "")
    except Exception:
        pass
    jobs: dict[str, str] = {}
    try:
        from .workshop3d import list_fabjobs
        for job in list_fabjobs(limit=100):
            if isinstance(job, dict) and job.get("job_id"):
                jobs[str(job["job_id"])] = str(
                    job.get("stage", ""))
    except Exception:
        pass
    fabs: dict[str, str] = {}
    try:
        from . import main as _main
        for record in _main.list_fabrications(50):
            fab_id = str(getattr(
                record, "fabrication_id",
                getattr(record, "job_id", "")))
            if fab_id:
                fabs[fab_id] = str(getattr(record, "status",
                                           ""))
    except Exception:
        pass
    return missions, jobs, fabs


def stage_states(tree: dict) -> list[dict]:
    """Annotate craft-tree stages with chain states. Pure
    derivation over a craft_tree() result + live work maps."""
    missions, jobs, fabs = _live_work_status()
    gaps = {str(gap.get("missing", "")): gap
            for gap in (tree.get("gaps", []) or [])
            if isinstance(gap, dict)}
    annotated: list[dict] = []
    for stage in tree.get("stages", []) or []:
        key = str(stage.get("key", ""))
        nodes = [node for node in (stage.get("nodes", []) or [])
                 if isinstance(node, dict)]
        if not nodes:
            annotated.append({
                "key": key, "state": "missing",
                "glyph": STAGE_STATE_GLYPHS["missing"],
                "evidence": [],
                "missing": gaps.get(key, {})})
            continue
        evidence: list[str] = []
        blocked: list[str] = []
        active: list[str] = []
        for node in nodes:
            ident = str(node.get("id", ""))
            if not ident:
                continue
            status = missions.get(ident, jobs.get(
                ident, fabs.get(ident, "")))
            if not status:
                evidence.append(ident)
                continue
            if status in _MISSION_BLOCKED + _FABJOB_BLOCKED + \
                    _FAB_BLOCKED:
                blocked.append(f"{ident} [{status}]")
            elif status in _MISSION_ACTIVE + _FABJOB_ACTIVE + \
                    _FAB_ACTIVE:
                active.append(f"{ident} [{status}]")
            else:
                evidence.append(f"{ident} [{status}]")
        if blocked:
            state = "blocked"
        elif active:
            state = "active"
        else:
            state = "complete"
        annotated.append({
            "key": key, "state": state,
            "glyph": STAGE_STATE_GLYPHS[state],
            "evidence": (blocked + active + evidence)[:12],
            "missing": gaps.get(key, {})})
    return annotated
