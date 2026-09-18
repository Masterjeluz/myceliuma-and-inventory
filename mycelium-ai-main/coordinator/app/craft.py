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
