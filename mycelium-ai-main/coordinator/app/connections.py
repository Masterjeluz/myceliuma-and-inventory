"""Living ecosystem connections (BIG #45).

A read-only aggregation over the existing relationship
systems — symbiosis edges, open proposals, finance/energy
project links, hardware links, quest step refs, campaign
chains, research runs, node tasks. No parallel graph, no
second source of truth, no invented relationships: every
connection names its origin store and links to the real
record.

Connection shape:
  source_id / source_kind / target_id / target_kind:
    real ids on both ends (prefix-grouped for display)
  predicate: closed SYMBIOSIS_PREDICATES or "related"
    (display mapping only — never stored anywhere)
  state: PROPOSED | SUPPORTED | VERIFIED for symbiosis
    origins; LINKED | WORKING | AVAILABLE | QUIET |
    POSSIBLE for associations (honestly labeled, never
    forced into relationship states)
  origin: which store produced this (symbiosis-edge,
    symbiosis-proposal, finance-link, energy-link,
    hardware-link, quest-step, campaign-chain,
    research-run, node-task, node-capability)
  href / evidence / detail: where to open and verify it

DISCOVERY ≠ RELATIONSHIP: POSSIBLE entries render as
"possible connection" until accepted through the existing
gate (knowledge review, human link, confirmation).
"""

from __future__ import annotations

#: Closed association states for non-symbiosis origins.
#: Relationship states (PROPOSED/SUPPORTED/VERIFIED) are
#: owned by the symbiosis engine and hardware-link store.
ASSOCIATION_STATES = ("LINKED", "WORKING", "AVAILABLE",
                      "QUIET", "POSSIBLE")


def domain_of(entity_id: str) -> str:
    """Display domain for an id (prefix groups). Unknown
    prefixes group as OTHER — never refused here (callers
    validate first)."""
    ident = str(entity_id or "")
    if ident.startswith("proj_"):
        return "PROJECT"
    if ident.startswith("idea_"):
        return "IDEA"
    if ident.startswith(("obj_", "mat_")):
        return "ITEM"
    if ident.startswith(("hw_", "sns_", "cam_")):
        return "MACHINE"
    if ident.startswith(("node_", "node-")) or \
            ("_" not in ident and "-" not in ident and
             ident and ident[0].isalnum()):
        # Bare registry names (node ids) group as NODE only
        # when they carry no known entity prefix.
        if not any(ident.startswith(prefix) for prefix in
                   ("proj_", "idea_", "obj_", "mat_", "hw_",
                    "sns_", "cam_", "fin_", "enr_", "hv_",
                    "qst_", "cmp_", "mission_", "dos_",
                    "res_", "auto_", "mem_", "conv_",
                    "cand_", "obs_", "obs-", "cing_",
                    "mdl_", "fabjob_", "task_", "act_",
                    "file_", "loc_", "mod_", "rel_",
                    "evt_")):
            return "NODE"
        return "OTHER"
    if ident.startswith("enr_"):
        return "ENERGY"
    if ident.startswith("fin_"):
        return "FINANCE"
    if ident.startswith(("dos_", "res_")):
        return "RESEARCH"
    if ident.startswith("mission_"):
        return "MISSION"
    if ident.startswith("qst_"):
        return "QUEST"
    if ident.startswith("cmp_"):
        return "CAMPAIGN"
    if ident.startswith("hv_"):
        return "HARDWARE"
    return "OTHER"


def _connection(source_id: str, target_id: str, predicate: str,
                state: str, origin: str, href: str,
                evidence: str = "", detail: str = "") -> dict:
    try:
        from .symbiosis import display_predicate
        shown = display_predicate(predicate)
    except Exception:
        shown = "related"
    return {
        "source_id": source_id,
        "source_kind": domain_of(source_id),
        "target_id": target_id,
        "target_kind": domain_of(target_id),
        "predicate": shown,
        "state": state,
        "origin": origin,
        "href": str(href or "")[:200],
        "evidence": str(evidence or "")[:200],
        "detail": str(detail or "")[:240],
    }


def _is_known_prefix(entity_id: str) -> bool:
    try:
        from .symbiosis import clean_entity
        clean_entity(entity_id)
        return True
    except ValueError:
        return False


def _check_entity(entity_id: str) -> str:
    """Known prefixes pass (empty result downstream means
    absent); bare names must exist in a registry — a
    registered node or a device_ref named by a live hardware
    link. Syntax alone never suffices, otherwise ghost ids
    would read 200-empty instead of 422."""
    cleaned = str(entity_id or "").strip()[:100]
    if not cleaned:
        raise ValueError("entity_id is required")
    if _is_known_prefix(cleaned):
        return cleaned
    try:
        from .database import connection as _conn
        with _conn() as db:
            row = db.execute(
                "SELECT node_id FROM nodes WHERE node_id=?",
                (cleaned,)).fetchone()
        if row is not None:
            return cleaned
    except Exception:
        pass
    if _known_device_ref(cleaned):
        return cleaned
    raise ValueError(
        f"unknown entity '{cleaned[:40]}'")


# -- per-store collectors (sync unless noted) ----------------------------

def _finance_links(entity_id: str) -> list[dict]:
    """Finance records whose project_ref names this entity.
    Amounts NEVER included (record id/kind/status only)."""
    try:
        from .finance import list_records
        records = list_records(project_ref=entity_id,
                               limit=50)
    except Exception:
        return []
    out = []
    for record in records:
        out.append(_connection(
            record.record_id, entity_id, "allocated_to",
            "LINKED", "finance-link", "/finance",
            evidence=f"{record.kind} [{record.status}]",
            detail=f"Finance {record.kind} "
                   f"{record.status.lower()}; amounts stay "
                   f"on the scoped finance page."))
    return out


def _energy_links(entity_id: str) -> list[dict]:
    """Energy records naming this project/device. Values are
    shown as recorded or UNKNOWN — never invented."""
    try:
        from .energy import list_records
        mine = list_records(project_ref=entity_id, limit=50)
        try:
            device = list_records(device_ref=entity_id,
                                  limit=50)
        except Exception:
            device = []
        records = mine + [record for record in device
                          if record.record_id not in
                          {item.record_id for item in mine}]
    except Exception:
        return []
    out = []
    for record in records:
        predicate = "powers" if (
            record.kind == "production") else "related_to"
        value = ("UNKNOWN" if record.value is None
                 else f"{record.value} {record.unit}")
        out.append(_connection(
            record.record_id, entity_id, predicate,
            "LINKED", "energy-link", "/energy",
            evidence=f"{record.source}/{record.kind} = "
                     f"{value}",
            detail="Recorded observation; unknown stays "
                   "unknown."))
    return out


def _known_device_ref(entity_id: str) -> bool:
    """True when a live (non-revoked) hardware link names this
    device_ref. Registry-existence only — the link store is
    the source of truth, nothing is inferred."""
    try:
        from .hardware_links import list_links
        for link in list_links(limit=200):
            if link.device_ref == entity_id and link.status in (
                    "PROPOSED", "VERIFIED"):
                return True
    except Exception:
        return False
    return False


def _hardware_links(entity_id: str) -> list[dict]:
    """Live (non-revoked) hardware links for this node or
    device. REVOKED links never appear."""
    try:
        from .hardware_links import list_links
        proposed = list_links(node_id=entity_id, limit=50)
        mine = [link for link in proposed
                if link.status in ("PROPOSED", "VERIFIED")]
        if not mine:
            # Device side: the store has no device filter, so
            # scan live links for this device_ref instead.
            mine = [link for link in list_links(limit=200)
                    if link.device_ref == entity_id and
                    link.status in ("PROPOSED", "VERIFIED")]
    except Exception:
        mine = []
    out = []
    for link in mine:
        other = link.device_ref if link.node_id == entity_id \
            else link.node_id
        out.append(_connection(
            link.link_id, other, "related_to", link.status,
            "hardware-link", "/hardware",
            evidence=f"{link.device_kind or 'device'} "
                     f"by {link.verified_by or link.human_ref}",
            detail="Human link; VERIFIED only by operator."))
    return out


def _quest_links(entity_id: str) -> list[dict]:
    """Quest steps referencing this record (+ which quests).
    Step state is NOT duplicated — hrefs lead to /quests."""
    try:
        from .quests import list_quests
        quests = list_quests(limit=50)
    except Exception:
        return []
    out = []
    for quest in quests:
        for step in quest.steps:
            if step.ref == entity_id and step.kind != "note":
                out.append(_connection(
                    quest.quest_id, entity_id, "related_to",
                    "LINKED", "quest-step",
                    f"/quests#{quest.quest_id}",
                    evidence=f"quest "
                             f"'{quest.title[:60]}' step "
                             f"'{step.label[:60]}'",
                    detail="Quest references this record; "
                           "state derives on the quest page."))
                break
    return out


def _campaign_links(entity_id: str) -> list[dict]:
    """Campaigns whose quest chain touches this record."""
    try:
        from .campaigns import list_campaigns
        from .quests import get_quest
        campaigns = list_campaigns(limit=20)
    except Exception:
        return []
    out = []
    for campaign in campaigns:
        hit = None
        for quest_id in campaign.quest_ids:
            try:
                quest = get_quest(quest_id)
            except Exception:
                continue
            if quest is None:
                continue
            if quest_id == entity_id or any(
                    step.ref == entity_id and
                    step.kind != "note"
                    for step in quest.steps):
                hit = quest
                break
        if hit is not None:
            out.append(_connection(
                campaign.campaign_id, entity_id, "contains",
                "LINKED", "campaign-chain", "/campaigns",
                evidence=f"campaign "
                         f"'{campaign.title[:60]}' via quest "
                         f"'{hit.title[:60]}'",
                detail="Campaign chain reaches this record."))
    return out


def _research_links(entity_id: str) -> list[dict]:
    """Research runs/dossiers naming this record. Runs carry
    project_ref + linked_entities; dossiers carry
    related_entities."""
    out = []
    try:
        from . import research_engine as _re
        list_runs = getattr(_re, "list_runs", None)
        list_dossiers = getattr(_re, "list_dossiers", None)
    except Exception:
        return []
    if callable(list_runs):
        try:
            runs = list_runs(limit=50)
        except Exception:
            runs = []
        for run in runs or []:
            try:
                data = run.model_dump(mode="json") \
                    if hasattr(run, "model_dump") else dict(run)
            except Exception:
                continue
            refs = set()
            if data.get("project_ref"):
                refs.add(str(data["project_ref"]))
            for key in ("linked_entities", "entity_refs"):
                for entry in (data.get(key) or []):
                    if isinstance(entry, str):
                        refs.add(entry)
            run_id = str(data.get("run_id", "") or
                         data.get("record_id", ""))
            if entity_id in refs and run_id:
                out.append(_connection(
                    run_id or entity_id, entity_id,
                    "evidence_for", "LINKED", "research-run",
                    "/research",
                    evidence="research run references this "
                             "record",
                    detail="Research finding, not a fact."))
    if callable(list_dossiers):
        try:
            dossiers = list_dossiers(limit=50)
        except Exception:
            dossiers = []
        for dossier in dossiers or []:
            try:
                data = dossier.model_dump(mode="json") \
                    if hasattr(dossier, "model_dump") \
                    else dict(dossier)
            except Exception:
                continue
            related = {str(entry) for entry in
                       (data.get("related_entities") or [])
                       if isinstance(entry, str)}
            dossier_id = str(data.get("dossier_id", ""))
            if entity_id in related and dossier_id:
                out.append(_connection(
                    dossier_id, entity_id, "evidence_for",
                    "LINKED", "research-run", "/research",
                    evidence="dossier references this record",
                    detail="Research finding, not a fact."))
    return out


def _node_links(entity_id: str) -> list[dict]:
    """Node associations: current work, capability offers,
    quiet state. Explicitly NOT ownership — advertisements
    unless observed/verified per trust rules."""
    try:
        from . import main as _main
        records = _main.list_nodes()
    except Exception:
        return []
    out = []
    for record in records:
        node_id = str(record.get("node_id", ""))
        if node_id != entity_id:
            continue
        status = str(record.get("derived_status", "unknown"))
        task = record.get("current_task") or {}
        # _assigned_tasks_map emits task_id; older readers
        # expect id — accept both, invent neither.
        tid = (task.get("id") or task.get("task_id")
               if isinstance(task, dict) else None)
        if tid:
            out.append(_connection(
                node_id, f"task_{tid}",
                "related_to", "WORKING", "node-task",
                f"/api/v1/tasks/by-id/{tid}",
                evidence=f"{task.get('kind', '')} "
                         f"(lease-bound)",
                detail="Node works on this task; tasks are "
                       "assigned, nodes are never owned."))
        caps = list(record.get("capabilities", []) or [])[:6]
        if status in ("online", "busy") and caps:
            out.append(_connection(
                node_id, entity_id, "related_to",
                "AVAILABLE", "node-capability", "/nodes",
                evidence=f"advertises {', '.join(caps[:3])}",
                detail="Capability advertisement, not an "
                       "attestation."))
        if status not in ("online", "busy"):
            out.append(_connection(
                node_id, entity_id, "related_to", "QUIET",
                "node-capability", "/nodes",
                evidence=f"derived {status}",
                detail="Quiet node claims nothing."))
    return out


async def entity_connections(entity_id: str,
                             depth: int = 1) -> dict:
    """Unified connections for one entity: symbiosis edges +
    proposals + every store link above. Async (symbiosis
    engine reads the world graph)."""
    cleaned = _check_entity(entity_id)
    connections: list[dict] = []
    counts = {"verified": 0, "supported": 0, "proposed": 0,
              "linked": 0, "working": 0, "available": 0,
              "quiet": 0, "possible": 0, "total": 0}
    # Shape is already gated by _check_entity above; a
    # symbiosis ValueError here only means "no world edges
    # for this id" (e.g. bare node names), so it degrades
    # to empty like any other failing source.
    try:
        from .symbiosis import for_entity
        result = await for_entity(
            cleaned, depth if depth in (1, 2) else 1)
        for link in result.get("symbioses", []):
            other = str(link.get("entity_b", ""))
            state = str(link.get("state", "SUPPORTED"))
            origin = "symbiosis-proposal" if state == \
                "PROPOSED" else "symbiosis-edge"
            href = link.get("candidate_id", "") and \
                "/symbiosis" or \
                f"/world?entity_id={other}"
            connections.append(_connection(
                cleaned, other,
                str(link.get("predicate", "related")), state,
                origin, href,
                evidence=("open proposal" if state ==
                          "PROPOSED" else "world edge"),
                detail=("Possible connection until reviewed"
                        if state == "PROPOSED" else
                        "Real world relation.")))
            counts["total"] += 1
            if state == "VERIFIED":
                counts["verified"] += 1
            elif state == "SUPPORTED":
                counts["supported"] += 1
            else:
                counts["proposed"] += 1
    except Exception:
        pass
    for collector, bucket in (
            (_finance_links, "linked"),
            (_energy_links, "linked"),
            (_hardware_links, None),
            (_quest_links, "linked"),
            (_campaign_links, "linked"),
            (_research_links, "linked"),
            (_node_links, None)):
        try:
            found = collector(cleaned)
        except Exception:
            continue
        for entry in found:
            connections.append(entry)
            counts["total"] += 1
            if bucket:
                counts[bucket] += 1
            elif entry["state"] == "VERIFIED":
                counts["verified"] += 1
            elif entry["state"] == "WORKING":
                counts["working"] += 1
            elif entry["state"] == "AVAILABLE":
                counts["available"] += 1
            elif entry["state"] == "QUIET":
                counts["quiet"] += 1
            else:
                counts["linked"] += 1
    # Cap + dedupe (same source/target/origin once).
    seen: set = set()
    capped: list[dict] = []
    for entry in connections:
        key = (entry["source_id"], entry["target_id"],
               entry["origin"])
        if key in seen:
            continue
        seen.add(key)
        capped.append(entry)
        if len(capped) >= 60:
            break
    return {"entity_id": cleaned, "connections": capped,
            "counts": counts,
            "honesty": "Every entry names its origin store. "
                       "PROPOSED/POSSIBLE are uncertain until "
                       "reviewed; nothing is inferred."}


# -- multi-project network -----------------------------------------------

def project_refs(limit: int = 30) -> list[str]:
    """Project ids the stores actually name: finance/energy
    project_refs, quest entity steps, research runs. Bounded,
    sorted, deduped."""
    refs: set = set()
    try:
        from .finance import list_records as _fin
        for record in _fin(limit=200):
            if record.project_ref:
                refs.add(record.project_ref[:100])
    except Exception:
        pass
    try:
        from .energy import list_records as _enr
        for record in _enr(limit=200):
            if record.project_ref:
                refs.add(record.project_ref[:100])
    except Exception:
        pass
    try:
        from .quests import list_quests
        for quest in list_quests(limit=50):
            for step in quest.steps:
                if step.kind == "entity" and step.ref.startswith(
                        "proj_"):
                    refs.add(step.ref[:100])
    except Exception:
        pass
    try:
        from . import research_engine as _re
        list_runs = getattr(_re, "list_runs", None)
        if callable(list_runs):
            for run in list_runs(limit=50) or []:
                try:
                    data = run.model_dump(mode="json") \
                        if hasattr(run, "model_dump") \
                        else dict(run)
                except Exception:
                    continue
                if data.get("project_ref"):
                    refs.add(str(data["project_ref"])[:100])
    except Exception:
        pass
    return sorted(refs)[:max(1, min(int(limit or 30), 30))]


async def project_network(project_ids: list,
                          limit_per_project: int = 12) -> dict:
    """Cross-project network over real links only. Clusters
    per project; cross-links where two projects share the
    SAME record (shared finance/energy/hardware/node/quest
    ref) — never word similarity."""
    cleaned: list[str] = []
    for raw in (project_ids or [])[:6]:
        ident = str(raw or "").strip()[:100]
        if not ident:
            continue
        try:
            _check_entity(ident)
        except ValueError:
            raise ValueError(
                f"unknown project '{ident[:40]}'")
        if ident not in cleaned:
            cleaned.append(ident)
    if not cleaned:
        raise ValueError("at least one project is required")
    clusters: list[dict] = []
    record_projects: dict = {}
    for project in cleaned:
        try:
            result = await entity_connections(
                project, depth=1)
        except Exception:
            result = {"entity_id": project, "connections": [],
                      "counts": {}}
        children = []
        for entry in result.get("connections", [])[:max(
                1, min(int(limit_per_project or 12), 20))]:
            other = entry["target_id"] \
                if entry["source_id"] == project \
                else entry["source_id"]
            children.append({
                "entity_id": other,
                "group": entry["target_kind"]
                if entry["source_id"] == project
                else entry["source_kind"],
                "predicate": entry["predicate"],
                "state": entry["state"],
                "origin": entry["origin"],
                "href": entry["href"],
            })
            record_projects.setdefault(other, set()).add(
                project)
        clusters.append({
            "project": project,
            "counts": result.get("counts", {}),
            "children": children,
            "href": f"/world?entity_id={project}",
        })
    cross: list[dict] = []
    for record, projects in record_projects.items():
        if len(projects) >= 2:
            cross.append({
                "record": record,
                "group": domain_of(record),
                "projects": sorted(projects),
                "href": f"/world?entity_id={record}"
                if _is_known_prefix(record) else "/activity",
                "detail": "Same record linked to several "
                          "projects.",
            })
            if len(cross) >= 20:
                break
    return {"projects": cleaned, "clusters": clusters,
            "cross_links": cross,
            "honesty": "Clusters come from store links; "
                       "cross-links only where projects share "
                       "the same record."}


# -- campaign ecosystem ----------------------------------------------------

def campaign_ecosystem(campaign_id: str) -> dict:
    """A campaign's ecosystem context: its quest chain plus
    the real records those quests reference, grouped by
    domain. Sync. Only records the chain actually names."""
    from .campaigns import campaign_detail, get_campaign
    cleaned = str(campaign_id or "").strip()[:80]
    campaign = get_campaign(cleaned)
    if campaign is None:
        raise ValueError("Campaign not found")
    detail = campaign_detail(campaign)
    groups: dict = {}
    for view in detail.get("quests", []):
        for step in view.get("steps", []):
            ref = str(step.get("ref", ""))
            if not ref or step.get("kind") == "note":
                continue
            group = domain_of(ref)
            bucket = groups.setdefault(group, [])
            if ref not in {entry["ref"] for entry in bucket}:
                bucket.append({
                    "ref": ref,
                    "step": str(step.get("label", ""))[:80],
                    "quest": str(view.get("title", ""))[:80],
                    "href": str(step.get("href",
                                         "/quests"))[:200],
                })
            if len(bucket) >= 12:
                continue
    return {"campaign_id": cleaned,
            "title": detail.get("title", ""),
            "state": detail.get("state", ""),
            "progress": f"{detail.get('completed_count', 0)}/"
                        f"{detail.get('total_count', 0)}",
            "groups": groups,
            "href": "/campaigns"}


# -- connection detail (WHAT/WHY/SOURCE/STATUS/EVIDENCE/NEXT) ---------------

async def connection_detail(entity_a: str,
                            entity_b: str) -> dict:
    """Explain one relationship in Guide vocabulary. Finds
    the underlying record; fabricates nothing."""
    first = _check_entity(entity_a)
    second = _check_entity(entity_b)
    if first == second:
        raise ValueError("a relationship needs two ends")
    try:
        result = await entity_connections(first, depth=1)
    except Exception:
        result = {"connections": []}
    match = None
    for entry in result.get("connections", []):
        pair = {entry["source_id"], entry["target_id"]}
        if {first, second} <= pair or second in pair:
            match = entry
            break
    if match is None:
        raise ValueError(
            f"No recorded connection between "
            f"'{first[:40]}' and '{second[:40]}'")
    origin = match["origin"]
    state = match["state"]
    if origin == "symbiosis-proposal":
        source, why, nxt = (
            "open connection candidate",
            "Someone (or Mycelium) proposed that these belong "
            "together; it is unreviewed.",
            ("Review the proposal", "/symbiosis"))
    elif origin == "symbiosis-edge":
        source, why, nxt = (
            "world relation edge",
            "The world graph stores this relation between "
            "the two entities.",
            ("Open neighbourhood",
             f"/world?entity_id={first}"))
    elif origin == "finance-link":
        source, why, nxt = (
            "finance record",
            "A finance record names this project as its "
            "scope.",
            ("Review finance", "/finance"))
    elif origin == "energy-link":
        source, why, nxt = (
            "energy record",
            "An energy observation names this project or "
            "device.",
            ("Review energy", "/energy"))
    elif origin == "hardware-link":
        if state == "VERIFIED":
            why = ("A human verified this device with "
                   "evidence; operator key on record.")
            nxt = ("Hardware links", "/hardware")
        else:
            why = ("A human proposed this link; it verifies "
                   "nothing until the operator confirms.")
            nxt = ("Verify hardware", "/hardware")
        source = "hardware link"
    elif origin == "quest-step":
        source, why, nxt = (
            "quest trail step",
            "A quest step references this record; quest "
            "state derives from it.",
            ("Open quest", match["href"] or "/quests"))
    elif origin == "campaign-chain":
        source, why, nxt = (
            "campaign chain",
            "A campaign's quest chain reaches this record.",
            ("Open campaigns", "/campaigns"))
    elif origin == "research-run":
        source, why, nxt = (
            "research run",
            "Research referenced this record; findings are "
            "not facts.",
            ("Open research", "/research"))
    else:
        source, why, nxt = (
            "node association",
            match.get("detail") or
            "Node state derived from the registry.",
            ("Open nodes", "/nodes"))
    return {
        "what": f"{match['source_kind']} → "
                f"{match['target_kind']}: "
                f"{first[:60]} {match['predicate']} "
                f"{second[:60]}",
        "why": why,
        "source": source,
        "status": state,
        "evidence": match.get("evidence", ""),
        "next": {"label": nxt[0], "href": nxt[1]},
        "href": match.get("href", ""),
    }


# -- possible connections (discovery, explicitly not relations) --------------

async def possible_connections(entity_id: str = "",
                               limit: int = 8) -> list[dict]:
    """Candidates, open proposals, craft gaps and unlinked
    quest steps as POSSIBLE connections with their gate href.
    Discovery, never relationship."""
    count = max(1, min(int(limit or 8), 16))
    possible: list[dict] = []
    try:
        from .symbiosis import proposed
        for prop in proposed(limit=count):
            if entity_id and entity_id not in prop.get(
                    "entities", []):
                continue
            possible.append({
                "title": str(prop.get("title", ""))[:120],
                "entities": prop.get("entities", [])[:4],
                "state": "POSSIBLE",
                "gate": "knowledge review",
                "href": prop.get("link", "/symbiosis"),
            })
    except Exception:
        pass
    if entity_id:
        try:
            from .craft import craft_tree
            tree = await craft_tree(entity_id, 1)
            for gap in tree.get("gaps", []):
                possible.append({
                    "title": str(gap.get("hint", ""))[:120],
                    "entities": [entity_id],
                    "state": "POSSIBLE",
                    "gate": "craft gap",
                    "href": str(gap.get("href",
                                        "/craft"))[:200],
                })
                if len(possible) >= count:
                    break
        except Exception:
            pass
    try:
        from .quests import list_quests
        for quest in list_quests(limit=20):
            for step in quest.steps:
                if step.kind != "note" and not step.ref:
                    possible.append({
                        "title": f"Quest step "
                                 f"'{step.label[:60]}' needs "
                                 f"a record",
                        "entities": [quest.quest_id],
                        "state": "POSSIBLE",
                        "gate": "quest link",
                        "href": f"/quests#{quest.quest_id}",
                    })
                    break
            if len(possible) >= count:
                break
    except Exception:
        pass
    return possible[:count]
