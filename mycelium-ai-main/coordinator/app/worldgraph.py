"""Mycelium World Graph foundation (BIG #4).

One uniform representation over two sources of truth that stay
separate: INVENTory owns world entities (object, project, idea,
hardware, sensor, camera, location, model, task, actuator, file)
plus their relationships; Mycelium owns mission/agent/node
records. This module never merges them into a new store — it
projects both into nodes/edges for navigation and future UI.

Node: {id, type, label, source, metadata}
Edge: {from, predicate, to, provenance}

Bounds (tested): seed expansion depth 1|2 through the existing
reader (bounded there too), mission/agent fan-out capped, total
nodes/edges capped. No full-database graph by default.
"""

from .missions import list_missions

MAX_NODES = 200
MAX_EDGES = 400
GRAPH_DEPTHS = (1, 2)

INVENTORY_NODE_TYPES = frozenset({
    "object", "project", "idea", "hardware", "sensor", "camera",
    "location", "model", "task", "actuator", "file",
})
MYCELIUM_NODE_TYPES = frozenset({"mission", "agent", "node"})

#: Overlay node types owned by Mycelium (BIG #10 uniform layer).
#: INVENTory types above stay authoritative; these never pretend
#: to be world entities.
OVERLAY_NODE_TYPES = frozenset({
    "mission", "agent", "node", "observation", "artifact",
    "print_job", "printer", "live_session",
})

MAX_NODE_OVERLAY = 50


def _inventory_node(node) -> dict:
    provenance = node.provenance
    prov = (provenance.model_dump(mode="json")
            if hasattr(provenance, "model_dump") else {})
    return {
        "id": str(node.entity_id),
        "type": node.entity_type,
        "label": node.title,
        "source": "inventory",
        "metadata": {"human_verified": bool(prov.get(
            "human_verified", False)),
            "source_type": str(prov.get("source_type", "unknown"))},
    }


def _inventory_edge(edge) -> dict:
    provenance = edge.provenance
    prov = (provenance.model_dump(mode="json")
            if hasattr(provenance, "model_dump") else {})
    return {
        "from": str(edge.from_id),
        "predicate": edge.predicate,
        "to": str(edge.to_id),
        "provenance": prov,
    }


async def build_world_graph(reader, entity_id: str, depth: int = 1, *,
                            include_missions: bool = False,
                            agent_nodes: list[dict] | None = None,
                            observations: list[dict] | None = None,
                            fabrication: list[dict] | None = None,
                            registry_nodes: list[dict] | None = None,
                            printers: list[dict] | None = None
                            ) -> dict:
    """Project inventory graph + optional Mycelium overlay."""
    if isinstance(depth, bool) or depth not in GRAPH_DEPTHS:
        raise ValueError("Graph depth must be 1 or 2")
    graph = await reader.graph(entity_id, depth)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for node in graph.nodes:
        if node.entity_type not in INVENTORY_NODE_TYPES:
            continue
        nodes[str(node.entity_id)] = _inventory_node(node)
        if len(nodes) >= MAX_NODES:
            break
    for edge in graph.edges:
        if len(edges) >= MAX_EDGES:
            break
        edges.append(_inventory_edge(edge))
    if include_missions:
        _overlay_missions(nodes, edges)
    if observations:
        _overlay_observations(nodes, edges, observations)
    if fabrication:
        _overlay_fabrication(nodes, edges, fabrication)
    if registry_nodes:
        _overlay_registry_nodes(nodes, edges, registry_nodes)
    if printers:
        _overlay_printers(nodes, edges, printers)
    for agent in (agent_nodes or [])[:50]:
        node_id = str(agent.get("node_id", ""))
        if not node_id or node_id in nodes:
            continue
        nodes[node_id] = {
            "id": node_id,
            "type": "agent",
            "label": node_id,
            "source": "mycelium",
            "metadata": {"capabilities": list(
                agent.get("capabilities", []))[:30]},
        }
        if len(nodes) >= MAX_NODES:
            break
    return {"entity_id": entity_id, "depth": depth,
            "nodes": list(nodes.values())[:MAX_NODES],
            "edges": edges[:MAX_EDGES]}


def _overlay_missions(nodes: dict, edges: list) -> None:
    for mission in list_missions(limit=50):
        if mission.mission_id in nodes:
            continue
        nodes[mission.mission_id] = {
            "id": mission.mission_id,
            "type": "mission",
            "label": mission.goal[:120],
            "source": "mycelium",
            "metadata": {"status": mission.status,
                         "current_step": mission.current_step,
                         "total_steps": len(mission.steps)},
        }
        for record in (mission.context_records or [])[:10]:
            entity_id = str(record.get("entity_id", ""))
            if not entity_id or entity_id not in nodes:
                continue
            if len(edges) >= MAX_EDGES:
                return
            edges.append({
                "from": mission.mission_id,
                "predicate": "uses_context",
                "to": entity_id,
                "provenance": {"source_type": "user-created",
                               "creator_id": "mission-control",
                               "human_verified": True},
            })
        if len(nodes) >= MAX_NODES:
            return


MAX_OBSERVATION_NODES = 20
MAX_FABRICATION_NODES = 20

#: Fabrication edge predicates. Closed: only derivation and
#: execution links the flow actually records.
FABRICATION_PREDICATES = frozenset({
    "derived_from", "sliced_to", "executed_as", "produced",
    "observed_by",
})


def _overlay_observations(nodes: dict, edges: list,
                          observations: list[dict]) -> None:
    """Camera observations as Mycelium-owned overlay nodes.

    Camera -captured-> observation, plus -describes-> inventory
    entity edges only when the caller supplies an explicit
    entity link (e.g. from a verified write). Observations are
    never a second source of truth: INVENTory nodes stay
    authoritative, these nodes carry sensor-observed,
    unverified provenance.
    """
    for item in list(observations or [])[:MAX_OBSERVATION_NODES]:
        if not isinstance(item, dict):
            continue
        obs_id = str(item.get("observation_id", ""))
        device_id = str(item.get("device_id", ""))
        if not obs_id or obs_id in nodes:
            continue
        provenance = item.get("provenance", {})
        if hasattr(provenance, "model_dump"):
            provenance = provenance.model_dump(mode="json")
        if not isinstance(provenance, dict):
            provenance = {}
        nodes[obs_id] = {
            "id": obs_id,
            "type": "observation",
            "label": f"observatie {obs_id} ({device_id})",
            "source": "mycelium",
            "metadata": {
                "device_id": device_id,
                "media_ref": str(item.get("media_ref", "")),
                "created_at": str(item.get("created_at", "")),
                "human_verified": bool(provenance.get(
                    "human_verified", False)),
                "source_type": str(provenance.get(
                    "source_type", "sensor-observed")),
            },
        }
        if len(edges) >= MAX_EDGES:
            return
        if device_id:
            edges.append({
                "from": device_id,
                "predicate": "captured",
                "to": obs_id,
                "provenance": {"source_type": "sensor-observed",
                               "creator_id": f"camera:{device_id}",
                               "human_verified": False},
            })
        describes = str(item.get("describes_entity_id", "") or "")
        if describes and describes in nodes:
            if len(edges) >= MAX_EDGES:
                return
            edges.append({
                "from": obs_id,
                "predicate": "describes",
                "to": describes,
                "provenance": {"source_type": "ai-generated",
                               "creator_id": "vision-flow",
                               "human_verified": False},
            })
        if len(nodes) >= MAX_NODES:
            return


def _overlay_fabrication(nodes: dict, edges: list,
                         artifacts: list[dict]) -> None:
    """Fabrication chain as Mycelium-owned overlay nodes.

    Artifact nodes (mesh/gcode files, print jobs, physical
    instances) link with closed predicates (derived_from,
    sliced_to, executed_as, produced, observed_by). Links only
    attach to nodes already present or added here — never a
    graph dump, never a second truth store.
    """
    for item in list(artifacts or [])[:MAX_FABRICATION_NODES]:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("id", ""))
        kind = str(item.get("kind", "artifact"))
        if not node_id or node_id in nodes:
            continue
        nodes[node_id] = {
            "id": node_id,
            "type": kind,
            "label": str(item.get("label", node_id))[:120],
            "source": "mycelium",
            "metadata": {
                "status": str(item.get("status", ""))[:40],
                "sha256": str(item.get("sha256", ""))[:64],
            },
        }
        for link in list(item.get("links", []))[:10]:
            if not isinstance(link, dict):
                continue
            predicate = str(link.get("predicate", ""))
            target = str(link.get("to", ""))
            if (predicate not in FABRICATION_PREDICATES
                    or not target or target not in nodes):
                continue
            if len(edges) >= MAX_EDGES:
                return
            edges.append({
                "from": node_id,
                "predicate": predicate,
                "to": target,
                "provenance": {"source_type": "ai-generated",
                               "creator_id": "fabrication-flow",
                               "human_verified": False},
            })
        if len(nodes) >= MAX_NODES:
            return


MAX_REGISTRY_NODES = 50


def _overlay_registry_nodes(nodes: dict, edges: list,
                            registry: list[dict]) -> None:
    """Coordinator node registry as overlay (BIG #10 uniform
    layer). Nodes carry derived status, capability/model counts
    and revision hints (last_seen); they never merge with
    INVENTory entities."""
    for item in list(registry or [])[:MAX_REGISTRY_NODES]:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id", ""))
        if not node_id or node_id in nodes:
            continue
        capabilities = item.get("capabilities", [])
        models = item.get("models", [])
        nodes[node_id] = {
            "id": node_id,
            "type": "node",
            "label": str(item.get("display_name")
                         or item.get("hostname", "")
                         or node_id)[:120],
            "source": "mycelium",
            "metadata": {
                "status": str(item.get("derived_status",
                                       item.get("status", ""))),
                "tier": str(item.get("tier", "")),
                "capabilities": len(capabilities)
                if isinstance(capabilities, list) else 0,
                "models": len(models)
                if isinstance(models, list) else 0,
                "revision": str(item.get("last_seen", "")),
                "last_seen": str(item.get("last_seen", "")),
            },
        }
        if len(nodes) >= MAX_NODES:
            return


def _overlay_printers(nodes: dict, edges: list,
                      printers: list[dict]) -> None:
    """Printer devices as overlay (BIG #10 uniform layer)."""
    for item in list(printers or [])[:MAX_REGISTRY_NODES]:
        if not isinstance(item, dict):
            continue
        printer_id = str(item.get("printer_id", ""))
        if not printer_id or printer_id in nodes:
            continue
        nodes[printer_id] = {
            "id": printer_id,
            "type": "printer",
            "label": str(item.get("name", printer_id))[:120],
            "source": "mycelium",
            "metadata": {
                "status": str(item.get("status", "")),
                "capabilities": list(
                    item.get("capabilities", []))[:10],
            },
        }
        twin = str(item.get("inventory_hardware_id", ""))
        if twin and twin in nodes:
            if len(edges) >= MAX_EDGES:
                return
            edges.append({
                "from": printer_id,
                "predicate": "twinned_with",
                "to": twin,
                "provenance": {"source_type": "user-created",
                               "creator_id": "printer-registry",
                               "human_verified": False},
            })
        if len(nodes) >= MAX_NODES:
            return
