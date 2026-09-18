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
    "print_job", "printer", "live_session", "research",
    "memory", "candidate", "conversation",
})

#: Truth classes for filtering (BIG #32). Inventory nodes map by
#: provenance; overlays map by kind. Health-tagged content is
#: refused at the overlay builders, never filtered client-side.
TRUTH_FILTERS = frozenset({
    "all", "verified", "memory", "candidate", "observation",
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
                            printers: list[dict] | None = None,
                            research_runs: list[dict] | None = None,
                            memories: list[dict] | None = None,
                            candidates: list[dict] | None = None,
                            conversations: list[dict] | None = None,
                            truth: str = "all",
                            source: str = "all",
                            kind: str = "all",
                            since: str = "",
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
    if research_runs:
        _overlay_research(nodes, edges, research_runs)
    if observations:
        _overlay_observations(nodes, edges, observations)
    if fabrication:
        _overlay_fabrication(nodes, edges, fabrication)
    if registry_nodes:
        _overlay_registry_nodes(nodes, edges, registry_nodes)
    if printers:
        _overlay_printers(nodes, edges, printers)
    if memories:
        _overlay_memories(nodes, edges, memories)
    if candidates:
        _overlay_candidates(nodes, edges, candidates)
    if conversations:
        _overlay_conversations(nodes, edges, conversations)
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
    filtered = filter_graph(
        {"entity_id": entity_id, "depth": depth,
         "nodes": list(nodes.values())[:MAX_NODES],
         "edges": edges[:MAX_EDGES]},
        truth=truth, source=source, kind=kind, since=since)
    filtered["filters"] = {"truth": truth, "source": source,
                           "kind": kind, "since": since}
    return filtered


def _truth_class(node: dict) -> str:
    """Map one graph node to a truth filter class."""
    kind = str(node.get("type", ""))
    if kind == "candidate":
        return "candidate"
    if kind in ("observation",):
        return "observation"
    if kind in ("memory",):
        return "memory"
    if node.get("source") == "inventory":
        metadata = node.get("metadata", {})
        if isinstance(metadata, dict) and metadata.get(
                "human_verified"):
            return "verified"
        return "memory"
    return "memory"


def filter_graph(graph: dict, *, truth: str = "all",
                 source: str = "all", kind: str = "all",
                 since: str = "") -> dict:
    """Bounded post-filter over a built graph. Pure: no fetching,
    caps preserved, edges pruned to surviving nodes."""
    cleaned_truth = str(truth or "all").strip().lower()
    if cleaned_truth not in TRUTH_FILTERS:
        raise ValueError(
            f"Unknown truth filter '{truth}'; expected one of "
            f"{sorted(TRUTH_FILTERS)}")
    cleaned_source = str(source or "all").strip().lower()
    cleaned_kind = str(kind or "all").strip().lower()
    cutoff = str(since or "").strip()[:10]
    if cleaned_truth == "all" and cleaned_source == "all" and \
            cleaned_kind == "all" and not cutoff:
        return {"entity_id": graph.get("entity_id", ""),
                "depth": graph.get("depth", 1),
                "nodes": list(graph.get("nodes", []))[:MAX_NODES],
                "edges": list(graph.get("edges", []))[:MAX_EDGES]}
    keep: dict[str, dict] = {}
    for node in graph.get("nodes", []):
        if cleaned_truth != "all" and _truth_class(node) != \
                cleaned_truth:
            continue
        if cleaned_source != "all" and str(
                node.get("source", "")).lower() != cleaned_source:
            continue
        if cleaned_kind != "all" and str(
                node.get("type", "")).lower() != cleaned_kind:
            continue
        if cutoff:
            stamp = str((node.get("metadata", {}) or {}).get(
                "created_at", node.get("metadata", {}).get(
                    "updated_at", "")) or "")[:10]
            if stamp and stamp < cutoff:
                continue
        keep[str(node.get("id", ""))] = node
        if len(keep) >= MAX_NODES:
            break
    edges = [edge for edge in graph.get("edges", [])
             if str(edge.get("from", "")) in keep
             and str(edge.get("to", "")) in keep][:MAX_EDGES]
    return {"entity_id": graph.get("entity_id", ""),
            "depth": graph.get("depth", 1),
            "nodes": list(keep.values()),
            "edges": edges}


MAX_MEMORY_NODES = 20
MAX_CANDIDATE_NODES = 20
MAX_CONVERSATION_NODES = 10


def _overlay_memories(nodes: dict, edges: list,
                      memories: list[dict]) -> None:
    """Memory entries as overlay (never health: callers must pass
    health-scoped lists; entries with memory_type health refuse)."""
    for item in list(memories or [])[:MAX_MEMORY_NODES]:
        if not isinstance(item, dict):
            continue
        if str(item.get("memory_type", "")) == "health":
            continue
        memory_id = str(item.get("memory_id", ""))
        if not memory_id or memory_id in nodes:
            continue
        nodes[memory_id] = {
            "id": memory_id,
            "type": "memory",
            "label": str(item.get("title", memory_id))[:120],
            "source": "mycelium",
            "metadata": {
                "memory_type": str(item.get("memory_type", "")),
                "truth": str(item.get("truth", "")),
                "human_verified": str(item.get("truth", "")) in (
                    "user_fact", "verified"),
                "project_ref": str(item.get("project_ref", "")),
            },
        }
        for ref in list(item.get("entity_refs", []))[:10]:
            target = str(ref or "")
            if not target or target not in nodes:
                continue
            if len(edges) >= MAX_EDGES:
                return
            edges.append({
                "from": memory_id,
                "predicate": "remembers",
                "to": target,
                "provenance": {"source_type": "memory",
                               "creator_id": "memory-layer",
                               "human_verified": str(item.get(
                                   "truth", "")) in (
                                       "user_fact", "verified")},
            })
        if len(nodes) >= MAX_NODES:
            return


def _overlay_candidates(nodes: dict, edges: list,
                        candidates: list[dict]) -> None:
    """Knowledge candidates as overlay with lifecycle state."""
    for item in list(candidates or [])[:MAX_CANDIDATE_NODES]:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id", ""))
        if not candidate_id or candidate_id in nodes:
            continue
        nodes[candidate_id] = {
            "id": candidate_id,
            "type": "candidate",
            "label": str(item.get("title", candidate_id))[:120],
            "source": "mycelium",
            "metadata": {
                "candidate_type": str(
                    item.get("candidate_type", "")),
                "state": str(item.get("state", "")),
                "supporters": len(item.get("support", []) or []),
                "project_ref": str(item.get("project_ref", "")),
                "created_at": str(item.get("created_at", "")),
                "updated_at": str(item.get("updated_at", "")),
            },
        }
        for ref in list(item.get("entity_refs", []))[:10]:
            target = str(ref or "")
            if not target or target not in nodes:
                continue
            if len(edges) >= MAX_EDGES:
                return
            edges.append({
                "from": candidate_id,
                "predicate": "may_relate_to",
                "to": target,
                "provenance": {"source_type": "ai-generated",
                               "creator_id": "knowledge-lifecycle",
                               "human_verified": False},
            })
        if len(nodes) >= MAX_NODES:
            return


def _overlay_conversations(nodes: dict, edges: list,
                           imports: list[dict]) -> None:
    """Imported conversations as overlay (context, never truth)."""
    for item in list(imports or [])[:MAX_CONVERSATION_NODES]:
        if not isinstance(item, dict):
            continue
        conversation_id = str(item.get("conversation_id", ""))
        if not conversation_id or conversation_id in nodes:
            continue
        nodes[conversation_id] = {
            "id": conversation_id,
            "type": "conversation",
            "label": str(item.get("title", conversation_id))[:120],
            "source": "mycelium",
            "metadata": {
                "source_platform": str(
                    item.get("source_platform", "")),
                "message_count": item.get("message_count", 0),
                "imported_at": str(item.get("imported_at", "")),
                "human_verified": False,
            },
        }
        if len(nodes) >= MAX_NODES:
            return


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
MAX_RESEARCH_NODES = 20


def _overlay_research(nodes: dict, edges: list,
                      runs: list[dict]) -> None:
    """Research runs as Mycelium-owned overlay nodes.

    Question -> run -> claims -> sources -> entities. Run nodes
    link to INVENTory entities only through the run's own
    linked_entities (user/project context or stated
    candidates); INVENTory stays the source of truth, these
    nodes carry external-source, unverified provenance.
    """
    for item in list(runs or [])[:MAX_RESEARCH_NODES]:
        if not isinstance(item, dict):
            continue
        run_id = str(item.get("run_id", ""))
        if not run_id or run_id in nodes:
            continue
        nodes[run_id] = {
            "id": run_id,
            "type": "research",
            "label": str(item.get("question", ""))[:120],
            "source": "mycelium",
            "metadata": {"status": item.get("status", ""),
                         "execution_state": item.get(
                             "execution_state", "UNAVAILABLE"),
                         "sources": len(item.get("source_ids",
                                                 []) or []),
                         "claims": len(item.get("claims", [])
                                       or [])},
        }
        for link in (item.get("linked_entities", "") or [])[:10]:
            entity_id = str((link or {}).get("entity_id", ""))
            if not entity_id or entity_id not in nodes:
                continue
            if len(edges) >= MAX_EDGES:
                return
            edges.append({
                "from": run_id,
                "predicate": "researches",
                "to": entity_id,
                "provenance": {"source_type": "external-source",
                               "creator_id": f"research:{run_id}",
                               "human_verified": False},
            })
        if len(nodes) >= MAX_NODES:
            return

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
