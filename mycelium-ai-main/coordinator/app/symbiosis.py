"""Symbiosis (BIG #33): explicit mutual influence between entities.

A symbiosis is two or more existing entities strengthening or
influencing each other through an explicit relationship. This
module never invents relations — it projects existing stores
into one readable layer:

- SUPPORTED: a real INVENTory relationship edge between two
  entities (authoritative world truth).
- VERIFIED: that edge carries human_verified provenance.
- PROPOSED: a knowledge candidate of type "connection" that
  names both entities and still waits for human review.

Read-only. No new store, no auto-linking, no truth change.
Health-flagged content never enters.
"""

from __future__ import annotations

import re as _re

SYMBIOSIS_STATES = ("PROPOSED", "SUPPORTED", "VERIFIED")

_ENTITY_RE = _re.compile(r"^[A-Za-z]+[_-][A-Za-z0-9._-]{1,80}$")

#: Entity prefixes this layer understands. Unknown prefixes are
#: refused rather than rendered as mystery links.
KNOWN_PREFIXES = (
    "obj_", "proj_", "idea_", "rel_", "evt_", "hw_", "sns_",
    "cam_", "loc_", "mod_", "task_", "act_", "file_",
    "mem_", "mission_", "conv_", "cand_",
    # BIG #34 camera ecosystem: observations, ingest sessions.
    # Observation ids use the existing obs-/obs_ spellings.
    "obs_", "obs-", "cing_",
)


def clean_entity(entity_id: str) -> str:
    """Validate an entity id for symbiosis lookups."""
    cleaned = str(entity_id or "").strip()[:100]
    if not cleaned or not _ENTITY_RE.match(cleaned):
        raise ValueError("entity_id is required (prefix_id)")
    if not cleaned.startswith(KNOWN_PREFIXES):
        raise ValueError("unknown entity prefix")
    return cleaned


def classify_edge(provenance: dict | None) -> str:
    """SUPPORTED by default, VERIFIED with human_verified."""
    prov = provenance if isinstance(provenance, dict) else {}
    if prov.get("human_verified") is True:
        return "VERIFIED"
    return "SUPPORTED"


def _candidate_entities(candidate) -> list[str]:
    """Entity ids a connection-candidate claims to link."""
    entities: list[str] = []
    try:
        data = candidate.model_dump(mode="json")
    except Exception:
        return entities
    for key in ("entity_refs", "entities", "entity_ids",
                "linked_entities"):
        values = data.get(key) or []
        if isinstance(values, list):
            entities.extend(str(value) for value in values
                            if isinstance(value, str))
    refs = data.get("refs") or []
    if isinstance(refs, list):
        entities.extend(str(ref) for ref in refs
                        if isinstance(ref, str))
    origin = data.get("origin") or {}
    if isinstance(origin, dict):
        for key in ("entity_refs", "entities", "entity_ids"):
            values = origin.get(key) or []
            if isinstance(values, list):
                entities.extend(str(value) for value in values
                                if isinstance(value, str))
    seen: list[str] = []
    for ident in entities:
        try:
            cleaned = clean_entity(ident)
        except ValueError:
            continue
        if cleaned not in seen:
            seen.append(cleaned)
    return seen[:8]


async def for_entity(entity_id: str, depth: int = 1) -> dict:
    """Symbioses around one entity: real edges + open proposals."""
    from .ecosystem import entity_context
    cleaned = clean_entity(entity_id)
    context = await entity_context(
        cleaned, depth if depth in (1, 2) else 1)
    symbioses: list[dict] = []
    for link in context.get("connected_to", []):
        other = str(link.get("entity_id", ""))
        try:
            clean_entity(other)
        except ValueError:
            continue
        symbioses.append({
            "entity_a": cleaned,
            "entity_b": other,
            "predicate": str(link.get("predicate", "related")),
            "state": classify_edge(link.get("provenance")),
            "provenance": link.get("provenance", {}),
        })
    proposals = proposed(limit=60)
    for proposal in proposals:
        pair = proposal.get("entities", [])
        if cleaned in pair:
            other = next((ident for ident in pair
                          if ident != cleaned), "")
            symbioses.append({
                "entity_a": cleaned,
                "entity_b": other,
                "predicate": str(proposal.get("title", "possible link")),
                "state": "PROPOSED",
                "candidate_id": proposal.get("candidate_id", ""),
            })
    verified = sum(1 for item in symbioses
                   if item["state"] == "VERIFIED")
    supported = sum(1 for item in symbioses
                    if item["state"] == "SUPPORTED")
    proposed_count = sum(1 for item in symbioses
                         if item["state"] == "PROPOSED")
    return {
        "entity_id": cleaned,
        "symbioses": symbioses[:60],
        "counts": {"verified": verified, "supported": supported,
                   "proposed": proposed_count,
                   "total": len(symbioses)},
        "actions": context.get("actions", {}),
        "honesty": "SUPPORTED/VERIFIED come from real INVENTory "
                   "edges; PROPOSED comes from open connection "
                   "candidates. Nothing is inferred.",
    }


def proposed(limit: int = 20) -> list[dict]:
    """Open connection proposals from the knowledge lifecycle."""
    count = max(1, min(int(limit or 20), 60))
    try:
        from .knowledge import list_candidates
        candidates = list_candidates(limit=100)
    except Exception:
        return []
    items: list[dict] = []
    for candidate in candidates:
        try:
            data = candidate.model_dump(mode="json")
        except Exception:
            continue
        if data.get("candidate_type") != "connection":
            continue
        if data.get("state") not in ("observation", "candidate",
                                     "supported"):
            continue
        entities = _candidate_entities(candidate)
        if len(entities) < 2:
            continue
        items.append({
            "candidate_id": data.get("candidate_id", ""),
            "title": str(data.get("title", ""))[:120],
            "entities": entities,
            "state": "PROPOSED",
            "supporters": data.get("supporters", 0),
            "link": f"/knowledge?candidate_id="
                    f"{data.get('candidate_id', '')}",
        })
        if len(items) >= count:
            break
    return items
