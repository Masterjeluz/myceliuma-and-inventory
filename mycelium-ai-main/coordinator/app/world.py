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
               "RESEARCH", "PRESENCE")

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
