"""Living game layer view (BIG #43).

`game_state()` is a READ-ONLY derived view over the existing
ecosystem — quests, campaigns, presence, craft, symbiosis,
nodes, energy, fabrications, discoveries. It aggregates; it
never stores game truth, never approves, never executes.

Presentation mapping (semantics preserved, never renamed):
- presence NEEDS → player decisions (approvals, blocked work)
- WAITING → quests waiting on something real
- AVAILABLE → resources the workshop offers
- DISCOVERED → discoveries / knowledge opportunities
- OFFLINE → sleeping, quiet nodes

Every entry keeps its real href. No XP, no rewards, no
fabricated statistics: counts come from the stores, empty
stores render as explicit empty.
"""

from __future__ import annotations

BAND_GAME_LABEL = {
    "needs": "needs you — player decisions",
    "waiting": "waiting — quests held by something real",
    "available": "available — workshop resources",
    "discovered": "discovered — knowledge opportunities",
    "offline": "quiet — sleeping nodes",
}


def symbiosis_progression(limit: int = 12) -> dict:
    """Symbiosis as progression: verified connections read as
    strong, supported as growing, proposed as seedlings.
    Display only — states come from the stores."""
    try:
        from .symbiosis import proposed
        open_proposals = proposed(limit=limit)
    except Exception:
        open_proposals = []
    return {
        "open": [{
            "title": str(prop.get("title", ""))[:120],
            "entities": prop.get("entities", [])[:4],
            "state": "PROPOSED",
            "strength": "seedling",
            "href": prop.get("link", "/symbiosis"),
        } for prop in open_proposals],
        "honesty": "PROPOSED links are seedlings (uncertain); "
                   "SUPPORTED/VERIFIED edges in the symbiosis "
                   "view read as growing/strong. Nothing is "
                   "promoted here.",
    }


def craft_progression(entity_id: str = "",
                      limit: int = 5) -> list[dict]:
    """Craft chains as gameplay progress for entities linked to
    open quests. Evidence-backed states only."""
    chains: list[dict] = []
    refs: list[str] = []
    if entity_id:
        refs = [str(entity_id)[:100]]
    else:
        try:
            from .quests import list_quests
            for quest in list_quests(limit=10):
                for step in quest.steps:
                    if step.kind == "entity" and step.ref:
                        refs.append(step.ref)
        except Exception:
            refs = []
    seen: set = set()
    for ref in refs:
        if ref in seen or len(chains) >= max(1, min(
                int(limit or 5), 10)):
            continue
        seen.add(ref)
        try:
            from .craft import craft_tree, stage_states
            tree = craft_tree(ref, 1)
            states = stage_states(tree)
        except Exception:
            continue
        done = sum(1 for stage in states
                   if stage.get("state") == "complete")
        chains.append({
            "entity_id": ref,
            "growth": tree.get("growth", "seed"),
            "done": done,
            "total": len(states),
            "stages": [{
                "key": stage.get("key", ""),
                "state": stage.get("state", ""),
                "glyph": stage.get("glyph", "○"),
            } for stage in states],
            "href": f"/craft?entity_id={ref}",
        })
    return chains


def presence_as_stakes(limit: int = 60) -> dict:
    """Presence bands translated to game-readable stakes. Same
    items, same hrefs, same priority — only the framing words
    change, and the original band name stays on each item."""
    try:
        from .presence import attention_snapshot
        snapshot = attention_snapshot(limit=limit)
    except Exception:
        return {"bands": {}, "labels": BAND_GAME_LABEL}
    bands: dict = {}
    for band, items in (snapshot.get("bands", {}) or {}).items():
        framed = []
        for item in items[:12]:
            framed.append({
                "id": item.get("id", ""),
                "title": item.get("title", "")[:140],
                "reason": item.get("reason", "")[:240],
                "band": band,
                "reads_as": BAND_GAME_LABEL.get(band, band),
                "href": item.get("open_href", "/presence"),
                "priority": item.get("priority", 0),
            })
        bands[band] = framed
    return {"bands": bands, "counts": snapshot.get("counts", {}),
            "labels": BAND_GAME_LABEL}


#: Closed growth levels. Presentation only — derived, never
#: stored, never a permission, never an execution gate.
LEVELS = ("SEEDLING", "ROOTED", "GROVE")


def derive_level(*, verified_objects: int | None = 0,
                 verified_files: int | None = 0,
                 completed_quests: int | None = 0) -> dict:
    """Derive one growth level from verified counts only.

    Pure: no database, no I/O, no persistence, no side
    effects, deterministic. UNVERIFIED and REVOKED records
    must never reach these inputs (callers count verified
    outcomes only). UNKNOWN (None) is not zero: it caps the
    level at SEEDLING with explicit unknown evidence.
    """
    inputs = {"verified_objects": verified_objects,
              "verified_files": verified_files,
              "completed_quests": completed_quests}
    evidence: list[str] = []
    unknown = [key for key, value in inputs.items()
               if value is None]
    if unknown:
        for key in sorted(unknown):
            evidence.append(f"{key}: UNKNOWN (not 0)")
        return {"level": "SEEDLING", "inputs": inputs,
                "evidence": evidence,
                "provenance": "derived"}
    try:
        objects = max(0, int(verified_objects or 0))
        files = max(0, int(verified_files or 0))
        quests = max(0, int(completed_quests or 0))
    except (TypeError, ValueError):
        return {"level": "SEEDLING", "inputs": inputs,
                "evidence": ["inputs unreadable; treating as "
                             "UNKNOWN, not 0"],
                "provenance": "derived"}
    evidence.append(f"{objects} verified object(s)")
    evidence.append(f"{files} verified file(s)")
    evidence.append(f"{quests} completed quest(s)")
    if objects >= 5 and files >= 5 and quests >= 2:
        level = "GROVE"
    elif (objects >= 1 and files >= 1) or quests >= 1:
        level = "ROOTED"
    else:
        level = "SEEDLING"
    return {"level": level, "inputs": inputs,
            "evidence": evidence, "provenance": "derived"}


def game_state() -> dict:
    """One derived game-state view. Best-effort per section:
    failing sources degrade to explicit empty, never invented."""
    out: dict = {"sections": {}, "warnings": []}

    def _put(key, value, source):
        out["sections"][key] = {"data": value, "source": source}

    try:
        from .living_state import current_state
        state = current_state()
        _put("world",
             {"state": state.get("state", "?"),
              "line": state.get("line", ""),
              "glyph": state.get("glyph", "")},
             "living_state.current_state")
    except Exception as error:
        _put("world", {}, f"unavailable ({error})")
        out["warnings"].append("living state unavailable")
    try:
        from .campaigns import list_campaign_details
        campaigns = list_campaign_details(limit=20)
        _put("campaigns", campaigns,
             "campaign defs + live quest derivation")
    except Exception as error:
        campaigns = []
        _put("campaigns", [], f"unavailable ({error})")
        out["warnings"].append("campaigns unavailable")
    try:
        current_quest: dict = {}
        for campaign in campaigns:
            nxt = campaign.get("current_quest", {}) or {}
            if nxt.get("quest_id"):
                current_quest = {
                    **nxt,
                    "campaign_id": campaign.get(
                        "campaign_id", ""),
                    "campaign_title": campaign.get(
                        "title", "")[:120],
                }
                break
        if not current_quest:
            from .quests import list_quest_details
            for quest in list_quest_details(limit=10):
                if quest.get("state") not in ("COMPLETED",):
                    current_quest = {
                        "quest_id": quest.get("quest_id", ""),
                        "title": quest.get("title", "")[:120],
                        "state": quest.get("state", ""),
                        "progress": quest.get("progress",
                                              "0/0"),
                        "href": f"/quests#{quest.get('quest_id', '')}",
                    }
                    break
        _put("current_quest", current_quest,
             "first open quest (campaign first)")
    except Exception as error:
        _put("current_quest", {}, f"unavailable ({error})")
    try:
        _put("presence", presence_as_stakes(limit=60),
             "presence engine (same items, game framing)")
    except Exception as error:
        _put("presence", {"bands": {}, "labels": BAND_GAME_LABEL},
             f"unavailable ({error})")
    try:
        _put("craft", craft_progression(limit=5),
             "craft trees of quest-linked entities")
    except Exception as error:
        _put("craft", [], f"unavailable ({error})")
    try:
        _put("symbiosis", symbiosis_progression(limit=12),
             "open symbiosis proposals")
    except Exception as error:
        _put("symbiosis", {"open": []}, f"unavailable ({error})")
    try:
        from . import main as _main
        nodes = []
        for record in _main.list_nodes():
            nodes.append({
                "node_id": str(record.get("node_id", "")),
                "status": str(record.get("derived_status",
                                         "unknown")),
                "health": str(record.get("health_status",
                                         "UNKNOWN")),
                "reads_as": "quiet"
                if str(record.get("derived_status", ""))
                not in ("online", "busy") else "awake",
                "current_task": record.get("current_task"),
                "href": f"/nodes#{record.get('node_id', '')}",
            })
            if len(nodes) >= 15:
                break
        _put("nodes", nodes, "node registry")
    except Exception as error:
        _put("nodes", [], f"unavailable ({error})")
    try:
        from .energy import summarize as _energy_sum
        _put("energy", _energy_sum(), "energy records")
    except Exception as error:
        _put("energy", {}, f"unavailable ({error})")
    try:
        from . import main as _main2
        fabs = _main2.list_fabrications(10)
        workshop = []
        for item in fabs:
            try:
                data = item.model_dump(mode="json") \
                    if hasattr(item, "model_dump") else dict(item)
            except Exception:
                continue
            status = str(data.get("status", ""))
            workshop.append({
                "fabrication_id": str(data.get(
                    "fabrication_id", ""))[:40],
                "status": status,
                "reads_as": "workshop activity"
                if status in ("started", "approved", "ready",
                              "waiting") else "workshop record",
            })
        _put("workshop", workshop, "fabrication records")
    except Exception as error:
        _put("workshop", [], f"unavailable ({error})")
    try:
        from .ecosystem import discoveries
        found = discoveries(limit=6)
        _put("discoveries",
             {"items": found.get("items", [])[:6],
              "imports_considered": found.get(
                  "imports_considered", 0)},
             "conversation discoveries")
    except Exception as error:
        _put("discoveries", {"items": []},
             f"unavailable ({error})")
    from datetime import datetime, timezone
    out["generated_at"] = datetime.now(timezone.utc).isoformat()
    out["provenance"] = {"source_type": "derived",
                         "creator_id": "living-game-layer",
                         "human_verified": False}
    out["honesty"] = ("A view, not a database. Every entry "
                      "links to its real record; empty stores "
                      "render empty. No XP, no rewards.")
    return out
