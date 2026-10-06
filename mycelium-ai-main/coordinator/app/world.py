"""Living solarpunk world objects (BIG #44).

Reusable visual representations of the existing ecosystem —
NODE, PROJECT, MACHINE, ENERGY, CAMPAIGN, CRAFT, DISCOVERY,
SYMBIOSIS — each with state, activity, attention, trust
where applicable, a real href, and an accessible text
representation. Presentation only: no persistence layer, no
second source of truth, every object maps to a real record
or derived state, empty stores render as explicit empty.

Also: the world HUD (current campaign/quest, attention,
nodes, active work, discoveries — only values that exist)
and the symbiosis network + craft world + campaign world
views for the /world page.
"""

from __future__ import annotations

#: Closed world-object kinds. Each has a glyph, a solarpunk
#: accent class, and a text label (no information by icon
#: alone — every card also carries words).
WORLD_KINDS = ("NODE", "PROJECT", "MACHINE", "ENERGY",
               "CAMPAIGN", "CRAFT", "DISCOVERY", "SYMBIOSIS",
               "RESEARCH", "PRESENCE", "OBJECT", "LOCATION")

KIND_GLYPH = {
    "NODE": "⬢",
    "PROJECT": "🌿",
    "MACHINE": "⚙",
    "ENERGY": "⚡",
    "CAMPAIGN": "🗺",
    "CRAFT": "🌱",
    "DISCOVERY": "🔵",
    "SYMBIOSIS": "🔗",
    "RESEARCH": "🔬",
    "PRESENCE": "📌",
    "OBJECT": "📦",
    "LOCATION": "📍",
}


def _object(kind: str, label: str, state: str, href: str,
            detail: str = "", attention: str = "",
            trust: str = "", activity: str = "") -> dict:
    return {
        "kind": kind if kind in WORLD_KINDS else "PRESENCE",
        "glyph": KIND_GLYPH.get(kind, "•"),
        "label": str(label or "")[:100],
        "state": str(state or "")[:40],
        "href": str(href or "/world")[:200],
        "detail": str(detail or "")[:200],
        "attention": str(attention or "")[:40],
        "trust": str(trust or "")[:40],
        "activity": str(activity or "")[:80],
        # Accessible text: the whole card reads as one line.
        "text": f"{KIND_GLYPH.get(kind, '•')} {label}: "
                f"{state}"
                + (f" — {detail[:120]}" if detail else ""),
    }


def node_objects(limit: int = 12) -> list[dict]:
    """Nodes as world objects: online/quiet, current task,
    hardware trust, telemetry freshness, activity."""
    try:
        from . import main as _main
        records = _main.list_nodes()
    except Exception:
        return []
    try:
        from .hardware_links import verified_device_refs
    except Exception:
        verified_device_refs = None
    objects = []
    for record in records[:max(1, min(int(limit or 12), 20))]:
        node_id = str(record.get("node_id", ""))
        status = str(record.get("derived_status", "unknown"))
        awake = status in ("online", "busy")
        hardware = [item for item in
                    (record.get("hardware", []) or [])
                    if isinstance(item, dict)]
        connected = [item for item in hardware
                     if str(item.get("status", "")) ==
                     "connected"]
        verified_count = 0
        if verified_device_refs is not None:
            try:
                verified_count = len(verified_device_refs(
                    node_id))
            except Exception:
                verified_count = 0
        if verified_count:
            trust = (f"VERIFIED ×{verified_count}" if awake
                     else f"VERIFIED ×{verified_count} (quiet)")
        elif connected:
            trust = "OBSERVED" if awake else "ADVERTISED (quiet)"
        else:
            trust = "ADVERTISED"
        task = record.get("current_task") or {}
        activity = ""
        if isinstance(task, dict) and task.get("id"):
            activity = (f"working task #{task.get('id')} "
                        f"({task.get('kind', '')})")
        elif awake:
            activity = "idle — ready to claim"
        else:
            activity = "quiet — last heartbeat stale"
        fresh = str(record.get("telemetry_timestamp", ""))[:16]
        objects.append(_object(
            "NODE", node_id,
            "awake" if awake else "quiet",
            f"/nodes#{node_id}",
            f"{len(connected)}/{len(hardware)} hardware "
            f"connected"
            + (f" · telemetry {fresh}" if fresh else ""),
            attention=("offline" if not awake else ""),
            trust=trust, activity=activity))
    return objects


def campaign_objects(limit: int = 5) -> list[dict]:
    """Campaigns as world progression: counts, current quest,
    next action, blocked count."""
    try:
        from .campaigns import list_campaign_details
        campaigns = list_campaign_details(limit=limit)
    except Exception:
        return []
    objects = []
    for campaign in campaigns[:max(1, min(int(limit or 5), 8))]:
        current = campaign.get("current_quest", {}) or {}
        nxt = campaign.get("next_action", {}) or {}
        blocked = campaign.get("blocked_count", 0)
        objects.append(_object(
            "CAMPAIGN", campaign.get("title", ""),
            campaign.get("state", ""),
            "/campaigns",
            f"{campaign.get('completed_count', 0)}/"
            f"{campaign.get('total_count', 0)} quests · "
            f"current: {current.get('title', '—')[:60]}",
            attention=("blocked" if blocked else ""),
            activity=f"next: {nxt.get('step', '—')[:80]}"))
    return objects


def craft_objects(entity_id: str = "") -> list[dict]:
    """Craft chains as world objects. Sync entry: quest-linked
    entities via the game view helper (async craft_tree stays
    behind the /world and /craft pages)."""
    try:
        from .game import craft_progression
        chains = craft_progression(entity_id=entity_id,
                                   limit=5)
    except Exception:
        return []
    objects = []
    for chain in chains:
        blocked = sum(1 for stage in chain.get("stages", [])
                      if stage.get("state") == "blocked")
        objects.append(_object(
            "CRAFT", chain.get("entity_id", ""),
            f"growth {chain.get('growth', 'seed')}",
            chain.get("href", "/craft"),
            f"{chain.get('done', 0)}/{chain.get('total', 0)} "
            "stages with evidence",
            attention=("blocked" if blocked else "")))
    return objects


def energy_objects(limit: int = 8) -> list[dict]:
    """Energy as world objects — only when real records exist.
    Per-source visual language lives in glyph + words."""
    try:
        from .energy import list_records
        records = list_records(limit=limit)
    except Exception:
        return []
    source_glyph = {"solar": "☀", "battery": "🔋",
                    "grid": "🔌", "machine": "⚙",
                    "other": "⚡"}
    objects = []
    for record in records[:max(1, min(int(limit or 8), 12))]:
        value = ("UNKNOWN" if record.value is None
                 else f"{record.value} {record.unit}")
        objects.append(_object(
            "ENERGY",
            f"{source_glyph.get(record.source, '⚡')} "
            f"{record.source}/{record.kind}",
            "flowing" if record.value is not None
            else "unknown",
            "/energy",
            f"{value}"
            + (f" · {record.project_ref[:40]}"
               if record.project_ref else "")))
    return objects


def discovery_objects(limit: int = 6) -> list[dict]:
    """Fresh discoveries: open candidates + recent
    observations. Uncertainty is explicit."""
    objects = []
    try:
        from .symbiosis import proposed
        for prop in proposed(limit=limit):
            objects.append(_object(
                "DISCOVERY",
                str(prop.get("title", ""))[:80],
                "seedling — unreviewed",
                prop.get("link", "/symbiosis"),
                f"links "
                f"{', '.join(prop.get('entities', [])[:2])}"))
            if len(objects) >= max(1, min(int(limit or 6),
                                          10)):
                break
    except Exception:
        pass
    return objects


def research_objects(limit: int = 5) -> list[dict]:
    """Active research as world objects (dossiers with open
    questions + running state)."""
    objects = []
    try:
        from .research_engine import list_dossiers
        dossiers = list_dossiers(limit=limit)
    except Exception:
        return []
    for dossier in dossiers[:max(1, min(int(limit or 5), 8))]:
        try:
            data = dossier.model_dump(mode="json")
        except Exception:
            continue
        open_questions = data.get("open_questions", []) or []
        objects.append(_object(
            "RESEARCH", str(data.get("title", ""))[:80],
            str(data.get("execution_state", "stored"))[:40],
            "/research",
            f"{len(open_questions)} open question(s)"))
    return objects


def world_objects(limit: int = 24) -> list[dict]:
    """One bounded shelf of world objects across kinds. Every
    entry links somewhere real; empty kinds contribute
    nothing (no filler objects)."""
    objects: list[dict] = []
    for collector in (node_objects, campaign_objects,
                      energy_objects, discovery_objects,
                      research_objects):
        try:
            objects.extend(collector(limit=6))
        except Exception:
            continue
        if len(objects) >= max(1, min(int(limit or 24), 40)):
            break
    return objects[:max(1, min(int(limit or 24), 40))]


def world_hud() -> dict:
    """Lightweight world HUD. Only values that actually exist —
    counts are live store counts, never scores."""
    hud: dict = {"campaign": {}, "quest": {}, "attention": {},
                 "nodes": {}, "work": {}, "discoveries": {}}
    try:
        from .campaigns import list_campaign_details
        campaigns = list_campaign_details(limit=5)
        if campaigns:
            first = campaigns[0]
            hud["campaign"] = {
                "title": first.get("title", "")[:80],
                "progress": f"{first.get('completed_count', 0)}/"
                            f"{first.get('total_count', 0)}",
                "href": "/campaigns"}
            current = first.get("current_quest", {}) or {}
            if current.get("quest_id"):
                hud["quest"] = {
                    "title": current.get("title", "")[:80],
                    "progress": current.get("progress", ""),
                    "href": current.get("href", "/quests")}
    except Exception:
        pass
    try:
        from .presence import attention_snapshot
        snapshot = attention_snapshot(limit=60)
        counts = snapshot.get("counts", {}) or {}
        hud["attention"] = {
            "needs": int(counts.get("needs", 0)),
            "waiting": int(counts.get("waiting", 0)),
            "discovered": int(counts.get("discovered", 0)),
            "offline": int(counts.get("offline", 0)),
            "href": "/presence"}
    except Exception:
        pass
    try:
        from . import main as _main
        records = _main.list_nodes()
        awake = sum(1 for record in records
                    if str(record.get("derived_status", ""))
                    in ("online", "busy"))
        hud["nodes"] = {"awake": awake, "total": len(records),
                        "href": "/nodes"}
        busy = sum(1 for record in records
                   if isinstance(record.get("current_task"),
                                 dict)
                   and (record.get("current_task") or {}).get(
                       "id"))
        hud["work"] = {"busy_nodes": busy, "href": "/activity"}
    except Exception:
        pass
    try:
        from .symbiosis import proposed
        hud["discoveries"] = {
            "open": len(proposed(limit=60)),
            "href": "/symbiosis"}
    except Exception:
        pass
    return hud


# -- symbiosis network (presentation tree over real edges) --------------

def _kind_group(entity_id: str) -> str:
    ident = str(entity_id or "")
    if ident.startswith("proj_"):
        return "PROJECT"
    if ident.startswith(("hw_", "sns_", "cam_")):
        return "MACHINE"
    if ident.startswith("enr_"):
        return "ENERGY"
    if ident.startswith("fin_"):
        return "FINANCE"
    if ident.startswith(("mat_", "obj_")):
        return "MATERIAL"
    if ident.startswith("idea_"):
        return "IDEA"
    return "LINK"


async def symbiosis_network(entity_id: str = "",
                            limit: int = 12) -> dict:
    """PROJECT with branch children (ENERGY/MACHINE/MATERIAL/
    FINANCE/...) carrying state + strength + href. Async (uses
    the real symbiosis engine). Presentation only."""
    try:
        from .symbiosis import clean_entity, for_entity
        cleaned = clean_entity(entity_id) if entity_id else ""
    except ValueError:
        raise
    children: list[dict] = []
    counts = {"verified": 0, "supported": 0, "proposed": 0,
              "total": 0}
    if cleaned:
        from .symbiosis import for_entity as _for_entity
        result = await _for_entity(cleaned, 1)
        counts = dict(result.get("counts", counts))
        for link in result.get("symbioses", [])[:max(
                1, min(int(limit or 12), 30))]:
            other = str(link.get("entity_b", ""))
            state = str(link.get("state", "SUPPORTED"))
            children.append({
                "entity_id": other,
                "group": _kind_group(other),
                "predicate": str(link.get("predicate",
                                          "related"))[:40],
                "state": state,
                "strength": ("established" if state ==
                             "VERIFIED" else "growing"
                             if state == "SUPPORTED" else
                             "seedling"),
                "href": f"/world?entity_id={other}",
            })
    return {"root": cleaned, "root_href": "/symbiosis",
            "counts": counts, "children": children,
            "honesty": "Real edges + open proposals. "
                       "Seedlings are uncertain until "
                       "reviewed."}


def symbiosis_seedlings(limit: int = 8) -> list[dict]:
    """Open proposals grouped for the world shelf (sync)."""
    try:
        from .symbiosis import proposed
        proposals = proposed(limit=limit)
    except Exception:
        return []
    return [{
        "entity_id": str(prop.get("title", ""))[:80],
        "group": "SEEDLING",
        "predicate": "proposed",
        "state": "PROPOSED",
        "strength": "seedling",
        "href": prop.get("link", "/symbiosis"),
    } for prop in proposals[:max(1, min(int(limit or 8),
                                        12))]]


# -- fungi network (derived presentation layer) -----------------------
#
# Deterministische derivatie over bestaande stores: dezelfde input
# levert dezelfde wereld. Geen randomness, geen nieuwe tabellen,
# geen tweede waarheid — iedere node linkt naar zijn echte record.
# Kleine verandering = kleine groei; nieuwe NPC/project/capability
# = nieuwe tak. Lege stores dragen niets bij (geen filler).

FUNGI_BRANCHES = ("quest", "campaign", "mission", "observation",
                  "candidate", "hardware", "knowledge", "node")

FUNGI_GLYPHS = {
    "seed": "🏠",
    "quest": "🧭",
    "campaign": "🗺",
    "mission": "📜",
    "observation": "📷",
    "candidate": "🌱",
    "hardware": "🔧",
    "knowledge": "📚",
    "node": "⬢",
}


def _fungi_node(node_id: str, branch: str, label: str,
                href: str, weight: int = 1,
                parent: str = "fungi-seed") -> dict:
    return {
        "id": str(node_id or "")[:120],
        "branch": branch if branch in FUNGI_BRANCHES + ("seed",)
        else "knowledge",
        "glyph": FUNGI_GLYPHS.get(branch, "•"),
        "label": str(label or "")[:100],
        "href": str(href or "/world")[:200],
        "weight": max(1, min(int(weight or 1), 9)),
        "parent": str(parent or "fungi-seed")[:120],
    }


def derive_fungi_network(limit: int = 120) -> dict:
    """Leid het fungi-netwerk af uit bestaande records.

    Puur afgeleide presentatie: campagnes/missies/quests als takken,
    observaties als worteltips, kandidaten als sporen, hardware en
    nodes als draden. Deterministisch (gesorteerd, begrensd) en
    eerlijk (alleen wat echt bestaat; lege stores = geen groei).
    """
    cap = max(10, min(int(limit or 120), 300))
    nodes: list[dict] = [_fungi_node(
        "fungi-seed", "seed", "Homebase-mycelium", "/play",
        weight=3, parent="")]
    grown: dict[str, int] = {branch: 0 for branch in
                             FUNGI_BRANCHES}

    def _add(node: dict) -> None:
        if len(nodes) < cap and node["id"] not in {
                entry["id"] for entry in nodes}:
            nodes.append(node)
            if node["branch"] in grown:
                grown[node["branch"]] += 1

    try:
        from .campaigns import list_campaign_details
        mission_parents: dict[str, str] = {}
        for camp in sorted(
                list_campaign_details(limit=10) or [],
                key=lambda c: str(c.get("campaign_id", ""))):
            camp_id = str(camp.get("campaign_id", ""))
            if not camp_id:
                continue
            _add(_fungi_node(
                f"fungi-camp-{camp_id}", "campaign",
                str(camp.get("title", camp_id))[:100],
                "/campaigns", weight=2 + min(
                    int(camp.get("completed_count", 0) or 0), 5)))
            for view in sorted(
                    camp.get("quests", []) or [],
                    key=lambda v: str(v.get("quest_id", "")))[:6]:
                qid = str(view.get("quest_id", ""))
                if not qid or view.get("state") == "MISSING":
                    continue
                _add(_fungi_node(
                    f"fungi-quest-{qid}", "quest",
                    str(view.get("title", qid))[:100],
                    str(view.get("href", "/quests"))[:200],
                    weight=3 if view.get("state") == "COMPLETED"
                    else 1,
                    parent=f"fungi-camp-{camp_id}"))
                # Causale tak: quest-step met echte mission-ref
                # parent de missie onder de quest (geen verzonnen
                # edges; alleen refs die de quest-def al bevat).
                for step in view.get("steps", []) or []:
                    if not isinstance(step, dict):
                        continue
                    if step.get("kind") != "mission":
                        continue
                    ref = str(step.get("ref", "") or "")
                    if ref and ref not in mission_parents:
                        mission_parents[ref] = f"fungi-quest-{qid}"
    except Exception:
        mission_parents = {}
        pass
    try:
        from .missions import list_missions
        for mission in sorted(
                list_missions(limit=50) or [],
                key=lambda m: str(m.mission_id)):
            status = str(mission.status)
            if status == "completed":
                # Historisch resultaat: zichtbaar als afgerond (✓),
                # nooit opnieuw uitvoerbaar — representatie only.
                _add(_fungi_node(
                    f"fungi-mission-{mission.mission_id}", "mission",
                    f"✓ {str(mission.goal or mission.mission_id)[:96]}",
                    f"/missions/{mission.mission_id}", weight=3,
                    parent=mission_parents.get(
                        str(mission.mission_id), "fungi-seed")))
                continue
            if status not in (
                    "approved", "running", "pending_approval"):
                continue
            _add(_fungi_node(
                f"fungi-mission-{mission.mission_id}", "mission",
                str(mission.goal or mission.mission_id)[:100],
                f"/missions/{mission.mission_id}", weight=1,
                parent=mission_parents.get(
                    str(mission.mission_id), "fungi-seed")))
    except Exception:
        pass
    try:
        from .cameras import list_devices, list_observations
        seen: set[str] = set()
        for device in sorted(
                d.device_id for d in list_devices() or []):
            try:
                obs = list_observations(device, limit=6) or []
            except Exception:
                continue
            for ob in sorted(
                    obs, key=lambda o: str(o.observation_id)):
                oid = str(ob.observation_id)
                if oid in seen:
                    continue
                seen.add(oid)
                _add(_fungi_node(
                    f"fungi-obs-{oid}", "observation",
                    str(ob.media_ref or oid)[:100],
                    f"/cameras/{device}", weight=1))
    except Exception:
        pass
    try:
        from .knowledge import list_candidates
        for cand in sorted(
                list_candidates(limit=60) or [],
                key=lambda c: str(c.candidate_id)):
            if str(cand.state) not in (
                    "observation", "candidate", "supported"):
                continue
            _add(_fungi_node(
                f"fungi-cand-{cand.candidate_id}", "candidate",
                str(cand.title or cand.candidate_id)[:100],
                "/knowledge", weight=1))
    except Exception:
        pass
    try:
        from .hardware_links import list_links
        for link in sorted(
                list_links(status="VERIFIED", limit=60) or [],
                key=lambda entry: str(entry.link_id)):
            _add(_fungi_node(
                f"fungi-hw-{link.link_id}", "hardware",
                f"{link.node_id}/{link.device_ref}"[:100],
                "/hardware", weight=2))
    except Exception:
        pass
    return {
        "nodes": nodes,
        "counts": grown,
        "total": len(nodes),
        "provenance": {"source_type": "derived",
                       "creator_id": "fungi-network",
                       "human_verified": False},
        "honesty": ("Afgeleid uit bestaande records; zelfde input, "
                    "zelfde netwerk. Lege stores groeien niet."),
    }


# -- world representations (WORLD REPRESENTATION v1) ------------------
# Dunne read-only afbeelding van echte records als game-entiteiten.
# De bron blijft canoniek: geen opslag, geen kopie, geen mutatie.
# Ontbreekt een record → geen representatie (never fake).
# Verwijderen in de game bestaat niet; INVENTory-verwijdering loopt
# alleen via bestaande INVENTory-contracten.

#: Kleine whitelist: alleen deze INVENTory-typen krijgen een
#: representatie. entity_type → WORLD_KINDS-soort.
WORLD_REPR_WHITELIST = {
    "hardware": "MACHINE",
    "object": "OBJECT",
    "project": "PROJECT",
    "location": "LOCATION",
}

#: Eerlijke statuswoorden voor representaties. Nooit een fysieke
#: status verzinnen: wat niet uit provenance blijkt, is REAL
#: (INVENTory-feit) of lager.
REPR_STATUSES = ("REAL", "OBSERVED", "VERIFIED", "PROPOSED",
                 "UNAVAILABLE", "FUTURE")

#: Workshop-plank: deterministische slots in de homebase-zone.
#: Buiten muren/solids/NPC's; posities volgen uit de index, nooit
#: uit randomness of opgeslagen state.
REPR_SHELF = {"x0": 100, "dx": 110, "y0": 90, "dy": 80,
              "per_row": 4, "max": 8, "zone": "homebase-workshop"}

#: Vaste NPC-ankers als voorbereidingslaag: dezelfde waarden als de
#: huidige kaart, maar als data-record zodat NPC's later uit dezelfde
#: representatiestroom kunnen komen. Luma/Forge-data zelf is
#: ongewijzigd; dit is alleen positie-als-data.
NPC_ANCHORS = (
    {"id": "luma", "name": "Luma", "x": 1180, "y": 420,
     "color": "#c9d66b", "glyph": "🎥"},
    {"id": "forge", "name": "Forge", "x": 1380, "y": 380,
     "color": "#d9a441", "glyph": "🛠️"},
)


def npc_anchors() -> list[dict]:
    """Vaste NPC-kaartankers als data (voorbereiding, geen gedrag)."""
    return [dict(entry) for entry in NPC_ANCHORS]


def _repr_status(provenance: dict) -> str:
    """Provenance → eerlijke status. Fail-closed naar REAL voor
    canonieke INVENTory-feiten zonder verdere claims."""
    provenance = provenance if isinstance(provenance, dict) else {}
    if provenance.get("human_verified") is True:
        return "VERIFIED"
    source = str(provenance.get("source_type", "") or "")
    if source == "sensor-observed":
        return "OBSERVED"
    if source in ("ai-generated", "unverified"):
        return "PROPOSED"
    return "REAL"


def _repr_slot(index: int) -> tuple[int, int]:
    """Deterministische plank-positie voor een index."""
    shelf = REPR_SHELF
    row, col = divmod(max(0, int(index)),
                      max(1, shelf["per_row"]))
    return (shelf["x0"] + col * shelf["dx"],
            shelf["y0"] + row * shelf["dy"])


def derive_world_representations(
        records: list[dict] | None) -> list[dict]:
    """Pure mapping echte records → game-entiteiten.

    Input: SearchResult-achtige dicts {entity_type, entity_id,
    title, snippet, provenance}. Output per representatie: id,
    source_type, source_id, entity_type, kind, zone, x, y, glyph,
    label, interaction, href, status, detail. Deterministisch
    (sort op source_id), gededuped, begrensd. Onbekende typen of
    prefixloze ids worden geweigerd, niet geraden.
    """
    seen: set[str] = set()
    cleaned: list[dict] = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        entity_type = str(record.get("entity_type", "") or "")
        if entity_type not in WORLD_REPR_WHITELIST:
            continue
        source_id = str(record.get("entity_id", "") or "").strip()
        if "_" not in source_id:
            continue
        prefix = source_id.split("_", 1)[0] + "_"
        try:
            from .inventory_read import ENTITY_ID_PREFIXES
            if prefix not in ENTITY_ID_PREFIXES:
                continue
        except Exception:
            continue
        if source_id in seen:
            continue
        seen.add(source_id)
        cleaned.append(record)
    cleaned.sort(key=lambda entry: str(entry.get("entity_id")))
    representations = []
    for index, record in enumerate(cleaned[:REPR_SHELF["max"]]):
        source_id = str(record.get("entity_id", ""))
        entity_type = str(record.get("entity_type", ""))
        kind = WORLD_REPR_WHITELIST[entity_type]
        provenance = record.get("provenance", {})
        if not isinstance(provenance, dict):
            try:
                provenance = dict(provenance)
            except Exception:
                provenance = {}
        x, y = _repr_slot(index)
        representations.append({
            "id": f"wrld-{source_id}",
            "source_type": "inventory",
            "source_id": source_id,
            "entity_type": entity_type,
            "kind": kind,
            "zone": REPR_SHELF["zone"],
            "x": x,
            "y": y,
            "glyph": KIND_GLYPH.get(kind, "•"),
            "label": str(record.get("title", "") or source_id)[:80],
            "interaction": "inspect",
            "href": f"/world?entity_id={source_id}",
            "status": _repr_status(provenance),
            "detail": str(record.get("snippet", "") or "")[:160],
        })
    return representations


async def inventory_spotlight(reader, per_type: int = 2) -> list:
    """Begrensde INVENTory-steekproef voor de wereldlaag: eerste
    records per whitelist-collectie via bestaande browse(). Lege of
    onbereikbare stores geven een lege lijst (geen filler)."""
    try:
        from .inventory_read import LIST_TYPES
        collections = [collection for collection, singular in
                       sorted(LIST_TYPES.items())
                       if singular in WORLD_REPR_WHITELIST]
    except Exception:
        return []
    found = []
    for collection in collections:
        try:
            response = await reader.browse(collection)
        except Exception:
            continue
        for result in (response.results or [])[:max(
                1, min(int(per_type or 2), 3))]:
            try:
                found.append(result.model_dump(mode="json"))
            except Exception:
                continue
    return found


# -- Verdant: voorwaardelijke ecology-biome (v1) ----------------------
# Ontwaakvoorwaarde uit bestaande data, geen ecology-schema nodig:
# INVENTory-records met ecology-conventie in naam/beschrijving (via
# bestaande FTS-search), Mycelium solar-metingen (energy_records) en
# onderzoeksdossiers met ecology-vragen. Lege stores = DORMANT.
# Deterministisch, traceerbaar (elk signaal draagt zijn bron-id).

#: Strakke conventie-termen. Generieke woorden (water, plant) zijn
#: bewust uitgesloten: die zouden misleidend ontwaken.
VERDANT_TERMS = ("hydroponics", "compost", "greenhouse",
                 "irrigation", "aquaponics")

#: Rect van de bioom-zone op de kaart (bestaande Verdant-slot).
VERDANT_RECT = {"x": 300, "y": 1150, "w": 150, "h": 90,
                "cx": 375, "cy": 1195, "radius": 150}

NPC_ACTIVITY_STATES = ("idle", "waiting", "processing",
                       "result_available", "needs_attention",
                       "blocked", "completed")


def verdant_state_from(parts: dict | None) -> dict:
    """Pure Verdant-toestand uit signaaldelen.

    parts: {inventory: [{entity_type, entity_id, title}],
    solar: int, research: [{dossier_id, title}]}.
    Elk signaal is traceerbaar; zonder signalen DORMANT.
    """
    parts = parts if isinstance(parts, dict) else {}
    signals: list[dict] = []
    for hit in parts.get("inventory", []) or []:
        if not isinstance(hit, dict):
            continue
        source_id = str(hit.get("entity_id", "") or "")
        if not source_id:
            continue
        signals.append({
            "kind": "inventory",
            "source_id": source_id,
            "entity_type": str(hit.get("entity_type", ""))[:40],
            "label": str(hit.get("title", "") or source_id)[:80],
            "href": f"/world?entity_id={source_id}",
            "detail": str(hit.get("entity_type", ""))[:40]})
    try:
        solar = int(parts.get("solar", 0) or 0)
    except (TypeError, ValueError):
        solar = 0
    if solar > 0:
        signals.append({
            "kind": "energy",
            "label": f"{solar} solar-meting(en)",
            "href": "/energy",
            "detail": "energy_records source=solar"})
    for dossier in parts.get("research", []) or []:
        if not isinstance(dossier, dict):
            continue
        dossier_id = str(dossier.get("dossier_id", "") or "")
        if not dossier_id:
            continue
        signals.append({
            "kind": "research",
            "label": str(dossier.get("title", "") or
                         dossier_id)[:80],
            "href": f"/research/{dossier_id}",
            "detail": "open ecology-vraag"})
    signals.sort(key=lambda s: (s["kind"], s["label"]))
    state = "AWAKENED" if signals else "DORMANT"
    return {
        "state": state,
        "signals": signals[:12],
        "count": len(signals),
        "honesty": ("Ontwaakt alleen bij echte records; "
                    "lege stores = dormant."),
        "provenance": {"source_type": "derived",
                       "creator_id": "verdant-state",
                       "human_verified": False},
    }


def verdant_rep_from(signals: list | None,
                     shelf_ids: set | None = None,
                     existing: list | None = None) -> dict | None:
    """Eén beloopbare representatie voor een ontwaakte bioom.

    Eerste inventory-signaal met whitelisted entity_type wordt een
    representatie op het bioom-centrum (zelfde id-vorm als de plank,
    zone "verdant"). Overgeslagen als het record al op de plank
    staat, het type niet op de whitelist staat of de bioom niet
    ontwaakt — nooit een fake object.
    """
    shelf_ids = set(shelf_ids or [])
    for signal in signals or []:
        if not isinstance(signal, dict):
            continue
        if signal.get("kind") != "inventory":
            continue
        source_id = str(signal.get("source_id", "") or "")
        entity_type = str(signal.get("entity_type", "") or "")
        if (not source_id or source_id in shelf_ids
                or entity_type not in WORLD_REPR_WHITELIST):
            continue
        kind = WORLD_REPR_WHITELIST[entity_type]
        return {
            "id": f"wrld-{source_id}",
            "source_type": "inventory",
            "source_id": source_id,
            "entity_type": entity_type,
            "kind": kind,
            "zone": "verdant",
            "x": int(VERDANT_RECT["cx"]),
            "y": int(VERDANT_RECT["cy"]),
            "glyph": KIND_GLYPH.get(kind, "•"),
            "label": str(signal.get("label", "")
                       or source_id)[:80],
            "interaction": "inspect",
            "href": f"/world?entity_id={source_id}",
            "status": "REAL",
            "detail": "Verdant-signaal — echt record",
        }
    return None


async def collect_verdant_signals(reader) -> dict:
    """Verzamel Verdant-signalen uit bestaande stores. Alles
    best-effort; falende store = geen signaal (fail-closed naar
    DORMANT, nooit raden)."""
    parts: dict = {"inventory": [], "solar": 0, "research": []}
    try:
        for term in VERDANT_TERMS:
            try:
                response = await reader.search(term)
            except Exception:
                continue
            for result in (response.results or [])[:10]:
                try:
                    data = result.model_dump(mode="json")
                except Exception:
                    continue
                if data.get("entity_id"):
                    parts["inventory"].append(data)
            if len(parts["inventory"]) >= 20:
                break
    except Exception:
        pass
    try:
        from .energy import list_records
        records = list_records(source="solar", limit=50) or []
        parts["solar"] = len(records)
    except Exception:
        pass
    try:
        from .research_engine import list_dossiers
        for dossier in list_dossiers(limit=10) or []:
            try:
                data = dossier.model_dump(mode="json")
            except Exception:
                continue
            haystack = f"{data.get('title', '')} " \
                       f"{data.get('question', '')} " \
                       f"{' '.join(data.get('open_questions', []) or [])}"
            lowered = haystack.lower()
            if any(term in lowered for term in VERDANT_TERMS):
                parts["research"].append({
                    "dossier_id": data.get("dossier_id", ""),
                    "title": data.get("title", "")})
    except Exception:
        pass
    seen: set[str] = set()
    unique = []
    for hit in parts["inventory"]:
        key = str(hit.get("entity_id", ""))
        if key and key not in seen:
            seen.add(key)
            unique.append(hit)
    parts["inventory"] = unique[:20]
    return parts


def derive_npc_activity(summary: dict | None) -> dict:
    """Pure NPC-activity uit echte backend-samenvatting.

    summary: {candidate_open, supported_count, inbox_count,
    missions_active, quest_completed, fab_open, fab_draft,
    fab_blocked}. Geen timers, geen simulatie — alleen afleiding
    van bestaande toestand.
    """
    summary = summary if isinstance(summary, dict) else {}

    def _int(key: str) -> int:
        try:
            return int(summary.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    candidate_open = _int("candidate_open")
    supported_count = _int("supported_count")
    inbox_count = _int("inbox_count")
    missions_active = bool(summary.get("missions_active", False))
    quest_completed = bool(summary.get("quest_completed", False))
    fab_open = bool(summary.get("fab_open", False))
    fab_draft = bool(summary.get("fab_draft", False))
    fab_blocked = bool(summary.get("fab_blocked", False))
    if candidate_open > 0:
        luma = ("needs_attention",
                f"{candidate_open} kandidaat/kandidaten "
                "wachten op review")
    elif supported_count > 0:
        luma = ("result_available",
                f"{supported_count} ondersteunde kandidaat/"
                "kandidaten klaar voor promotie")
    elif inbox_count > 0:
        luma = ("waiting",
                f"{inbox_count} inbox-bestand(en) wachten op ingest")
    elif missions_active:
        luma = ("processing", "missie(s) onderweg")
    elif quest_completed:
        luma = ("completed", "Documenteer-één-object afgerond")
    else:
        luma = ("idle", "rustig — geen openstaande signalen")
    if fab_blocked:
        forge = ("blocked", "fabricatie geblokkeerd/gefaald — "
                            "zie werkplaats")
    elif fab_open:
        forge = ("processing", "fabricatiemissie(s) onderweg")
    elif fab_draft:
        forge = ("waiting", "concept-missie(s) beschikbaar")
    else:
        forge = ("idle", "werkplaats gereed")
    return {
        "luma": {"state": luma[0], "reason": luma[1]},
        "forge": {"state": forge[0], "reason": forge[1]},
    }
