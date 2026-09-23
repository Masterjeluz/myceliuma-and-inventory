"""Project workspaces, vertical slice 1: minimal connection over existing storage.

A workspace is the existing ``project_ref`` column on the ``conversations``
table — no new database, no new table, no queue, no bus, no auth, no
second truth system. One workspace holds many conversations; missions
belong to a workspace through their conversation; forks and re-links are
row copies/updates on the existing ``conversations``/``messages``/
``missions`` tables.

Seeded views (no persistence, always listed): ``mycelium-ai``,
``inventory`` and ``forge-studio``. They resolve to existing pages and
the existing read bridge — this module never fetches INVENTory itself.

Provenance: message provenance JSON is copied verbatim on fork (an
import stays ``imported``, an assistant turn stays ``ai-generated`` and
unverified). Fork/attach facts are recorded through the existing event
stores (``missions`` conversation_events + ``events`` interface bus),
never as new event kinds.

All functions are fail-closed: unknown conversations/missions are
LookupError (callers map to 404), invalid ids are ValueError (422).
"""

from __future__ import annotations

import re as _re
from datetime import datetime, timezone

_WORKSPACE_RE = _re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
MAX_TITLE_CHARS = 120

#: Existing project-entities exposed as workspace views. ``href`` and
#: ``view`` point at pages/routes that already exist; nothing new is built.
SEED_WORKSPACES: tuple[dict, ...] = (
    {
        "workspace_id": "mycelium-ai",
        "title": "Mycelium AI",
        "kind": "coordinator",
        "href": "/missions",
        "view": "missions + chat: the coordinator task queue and "
                "conversations linked to this workspace",
    },
    {
        "workspace_id": "inventory",
        "title": "INVENTory",
        "kind": "world-model",
        "href": "/projects",
        "view": "read-only world model via the existing GET-only "
                "loopback bridge (:8080); browse at /projects, "
                "graph at /world",
    },
    {
        "workspace_id": "forge-studio",
        "title": "Forge Studio",
        "kind": "fabrication",
        "href": "/forge",
        "view": "editor at /forge backed by the existing CAD/mesh "
                "contracts; persistence runs through the gated "
                "writes flow",
    },
)

SEED_IDS = frozenset(seed["workspace_id"] for seed in SEED_WORKSPACES)


class WorkspaceRefusedError(ValueError):
    """Local validation refused; nothing was stored."""


class WorkspaceNotFoundError(LookupError):
    """Referenced conversation/mission/workspace does not exist."""


def check_workspace_id(value: str) -> str:
    """Workspace ids are short slugs (also covers ``proj_…`` ids)."""
    text = str(value or "").strip()
    if not _WORKSPACE_RE.match(text):
        raise WorkspaceRefusedError(
            "workspace_id must be 1..80 chars "
            "[A-Za-z0-9_-], starting alphanumerically")
    return text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _note_event(conversation_id: str, message: str,
                mission_id: str = "") -> None:
    """Best-effort fork/attach fact in the existing event stores."""
    try:
        from .missions import new_event as _new_mission_event
        from .missions import save_event as _save_mission_event
        _save_mission_event(_new_mission_event(
            conversation_id, "note", message[:2000],
            mission_id=mission_id))
    except Exception:
        pass
    try:
        from .events import new_event as _new_bus_event
        from .events import save_event as _save_bus_event
        _save_bus_event(_new_bus_event(
            "conversation.message", message[:500],
            conversation_id=conversation_id, mission_id=mission_id))
    except Exception:
        pass


def list_workspaces(limit: int = 100) -> list[dict]:
    """Derived workspace list: seeds + every used project_ref.

    Read-only over the existing ``conversations``/``missions`` tables.
    Seeds always appear, even with zero linked conversations.
    """
    from .database import chat_connection, init_chat_database
    init_chat_database()
    count = max(1, min(int(limit or 100), 200))
    with chat_connection() as db:
        rows = db.execute(
            """SELECT project_ref AS workspace_id,
            COUNT(*) AS conversations,
            MAX(created_at) AS updated_at
            FROM conversations WHERE project_ref <> ''
            GROUP BY project_ref ORDER BY updated_at DESC
            LIMIT ?""", (count,)).fetchall()
        mission_rows = db.execute(
            """SELECT c.project_ref AS workspace_id, COUNT(*) AS n
            FROM missions m JOIN conversations c
            ON c.conversation_id = m.conversation_id
            WHERE c.project_ref <> ''
            GROUP BY c.project_ref""").fetchall()
    missions_by_ws = {row["workspace_id"]: row["n"]
                      for row in mission_rows}
    seen: dict[str, dict] = {}
    for row in rows:
        wid = str(row["workspace_id"])
        seen[wid] = {
            "workspace_id": wid,
            "title": wid,
            "kind": "linked",
            "conversations": row["conversations"],
            "missions": missions_by_ws.get(wid, 0),
            "updated_at": row["updated_at"] or "",
            "href": f"/workspaces/{wid}",
        }
    out: list[dict] = []
    for seed in SEED_WORKSPACES:
        wid = seed["workspace_id"]
        existing = seen.pop(wid, None)
        out.append({
            "workspace_id": wid,
            "title": seed["title"],
            "kind": seed["kind"],
            "conversations": existing["conversations"]
            if existing else 0,
            "missions": existing["missions"] if existing else 0,
            "updated_at": existing["updated_at"]
            if existing else "",
            "href": f"/workspaces/{wid}",
            "view": seed["view"],
        })
    out.extend(seen.values())
    return out[:count]


def get_workspace(workspace_id: str) -> dict:
    """One workspace with its conversations, missions and event tail.

    Unknown ids yield an empty (linkable) workspace rather than 404:
    attaching to a fresh slug creates it implicitly. Conversation and
    mission rows come from the existing tables; events reuse the
    existing conversation_events + interface bus reads.
    """
    wid = check_workspace_id(workspace_id)
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    with chat_connection() as db:
        conv_rows = db.execute(
            """SELECT conversation_id, title, project_ref, created_at
            FROM conversations WHERE project_ref=?
            ORDER BY created_at DESC LIMIT 50""", (wid,)).fetchall()
        mission_rows = db.execute(
            """SELECT m.mission_id, m.conversation_id, m.record,
            m.status, m.current_step, m.created_at
            FROM missions m JOIN conversations c
            ON c.conversation_id = m.conversation_id
            WHERE c.project_ref=? ORDER BY m.created_at DESC
            LIMIT 20""", (wid,)).fetchall()
        conv_ids = [row["conversation_id"] for row in conv_rows]
        events: list[dict] = []
        if conv_ids:
            placeholders = ",".join("?" * len(conv_ids))
            event_rows = db.execute(
                f"""SELECT event_id, conversation_id, event_type,
                mission_id, message, created_at
                FROM conversation_events WHERE conversation_id IN
                ({placeholders}) ORDER BY created_at DESC
                LIMIT 10""", tuple(conv_ids)).fetchall()
            events = [dict(row) for row in event_rows]
    missions: list[dict] = []
    for row in mission_rows:
        try:
            record = load(row["record"])
            goal = str(record.get("goal", ""))[:200]
        except Exception:
            goal = ""
        missions.append({
            "mission_id": row["mission_id"],
            "conversation_id": row["conversation_id"],
            "goal": goal,
            "status": row["status"],
            "href": f"/missions/{row['mission_id']}",
        })
    seed = next((s for s in SEED_WORKSPACES
                 if s["workspace_id"] == wid), None)
    return {
        "workspace_id": wid,
        "title": seed["title"] if seed else wid,
        "kind": seed["kind"] if seed else "linked",
        "href": seed["href"] if seed else f"/workspaces/{wid}",
        "view": seed["view"] if seed else "",
        "conversations": [{
            "conversation_id": row["conversation_id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "href": (f"/conversations/{row['conversation_id']}"
                     if str(row["conversation_id"]).startswith("conv_")
                     else f"/api/v1/conversations/"
                          f"{row['conversation_id']}"),
        } for row in conv_rows],
        "missions": missions,
        "events": events,
        "package_href": (
            f"/api/v1/project/package?conversation_id="
            f"{conv_ids[0]}" if conv_ids else
            "/api/v1/project/package"),
        "context_href": (
            f"/api/v1/context/packet?conversation_id="
            f"{conv_ids[0]}" if conv_ids else
            "/api/v1/context/packet"),
    }


#: Step kinds that count as Forge work (existing fabrication
#: contracts only; this module never touches geometry itself).
FORGE_STEP_KINDS = frozenset({"fabricate", "slice", "physical_print"})

#: Display rollup for queue task states. ``assigned`` means a worker
#: holds the lease (running); ``staged`` is inert staging data.
TASK_DISPLAY = {
    "queued": "queued", "assigned": "running",
    "completed": "completed", "failed": "failed",
    "blocked": "blocked", "staged": "staged",
}


def greenlight_for(status: str) -> str:
    """Human greenlight label derived from mission status only."""
    key = str(status or "")
    if key == "pending_approval":
        return "wacht op YES"
    if key in ("approved", "running"):
        return "greenlit"
    if key == "paused":
        return "gepauzeerd"
    if key == "completed":
        return "afgerond"
    return key or "onbekend"


def workstream_overview(workspace_id: str) -> dict:
    """All live workstreams in one workspace, read-only.

    One workstream per mission: conversation + steps + queue tasks
    + research runs + pending proposals + greenlight, all resolved
    from the existing stores. Workers and the Forge registry are
    shared (pull-only nodes, one registry) and labelled as such.
    Every section is best-effort: a failing source yields an empty
    list, never a broken overview, never a write.
    """
    wid = check_workspace_id(workspace_id)
    base = get_workspace(wid)
    conv_ids = [item["conversation_id"]
                for item in base["conversations"]]
    mission_ids = [item["mission_id"] for item in base["missions"]]

    missions = _workstream_missions(wid)
    mission_ids = [item["mission_id"] for item in missions]
    tasks = _workstream_tasks(mission_ids)
    workers = _workstream_workers()
    research = _workstream_research(wid)
    proposals = _workstream_proposals(mission_ids)
    forge = _workstream_forge(missions)
    bus_events = _workstream_bus_events(conv_ids, mission_ids)
    tree = conversation_tree(wid)
    pending = _workstream_pending(missions, proposals, research)

    by_mission: dict[str, dict] = {}
    for item in missions:
        mid = item["mission_id"]
        conv_open = open_href_for(item["conversation_id"])
        forge_open = "/forge" if item.get("has_forge_steps") else ""
        run_links = [{
            "run_id": run["run_id"],
            "dossier_id": run["dossier_id"],
            "href": "/research",
        } for run in research if run["mission_id"] == mid]
        by_mission[mid] = {
            **item,
            "greenlight": greenlight_for(item["status"]),
            "tasks": [task for task in tasks
                      if task["mission_id"] == mid],
            "research": [run for run in research
                         if run["mission_id"] == mid],
            "proposals": [prop for prop in proposals
                          if prop["mission_id"] == mid],
            "open": {
                "mission": item["href"],
                "conversation": conv_open,
                "forge": forge_open,
                "research": "/research" if run_links else "",
                "approve": (item["href"]
                            if item["status"] == "pending_approval"
                            else ""),
            },
            "research_links": run_links,
        }
    counts: dict[str, int] = {}
    for task in tasks:
        key = TASK_DISPLAY.get(task["status"], task["status"])
        counts[key] = counts.get(key, 0) + 1
    conversations = [{**item,
                      "open_href": open_href_for(
                          item["conversation_id"])}
                     for item in base["conversations"]]
    return {
        "workspace_id": wid,
        "title": base["title"],
        "kind": base["kind"],
        "conversations": conversations,
        "tree": tree,
        "workstreams": list(by_mission.values()),
        "tasks": tasks,
        "task_counts": counts,
        "workers": workers,
        "research": research,
        "forge": forge,
        "proposals": proposals,
        "pending": pending,
        "events": base["events"],
        "bus_events": bus_events,
        "package_href": base["package_href"],
        "context_href": base["context_href"],
    }


def _workstream_pending(missions: list[dict], proposals: list[dict],
                        research: list[dict]) -> dict:
    """Pending human actions, all pointing at existing gates.

    Mission approvals open the mission page (APPROVE button);
    desktop items open /approvals; writes open /writes; research
    reports use the existing workspace report action. Nothing
    here approves or executes anything by itself.
    """
    mission_approvals = [{
        "kind": "mission", "label": item["goal"] or item["mission_id"],
        "mission_id": item["mission_id"],
        "status": item["status"],
        "href": item["href"],
    } for item in missions
        if item["status"] == "pending_approval"][:20]
    desktop = [{
        "kind": "desktop", "label": prop["proposal_id"][:40],
        "mission_id": prop["mission_id"], "status": prop["status"],
        "href": "/approvals",
    } for prop in proposals if prop["kind"] == "desktop"][:20]
    writes = [{
        "kind": "write", "label": prop["proposal_id"][:40],
        "mission_id": prop["mission_id"], "status": prop["status"],
        "href": "/writes",
    } for prop in proposals if prop["kind"] == "write"][:20]
    reports = [{
        "kind": "research-report", "label": run["question"][:80],
        "mission_id": run["mission_id"], "run_id": run["run_id"],
        "status": f"dossier {run['dossier_id'][:20]} wacht op review",
        "href": "/research",
    } for run in research
        if run["dossier_id"] and not run["reported"]][:20]
    total = (len(mission_approvals) + len(desktop) + len(writes)
             + len(reports))
    return {"mission_approvals": mission_approvals, "desktop": desktop,
            "writes": writes, "research_reports": reports,
            "total": total}


def _workstream_missions(wid: str) -> list[dict]:
    """Missions with full step lists (existing missions table)."""
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    try:
        with chat_connection() as db:
            rows = db.execute(
                """SELECT m.mission_id, m.conversation_id, m.record,
                m.status, m.current_step, m.created_at
                FROM missions m JOIN conversations c
                ON c.conversation_id = m.conversation_id
                WHERE c.project_ref=? ORDER BY m.created_at ASC
                LIMIT 20""", (wid,)).fetchall()
    except Exception:
        return []
    out = []
    for row in rows:
        try:
            record = load(row["record"])
        except Exception:
            continue
        steps = []
        for step in list(record.get("steps", []))[:20]:
            if not isinstance(step, dict):
                continue
            steps.append({
                "kind": str(step.get("kind", ""))[:20],
                "status": str(step.get("status", ""))[:20],
                "description": str(
                    step.get("description", ""))[:140],
            })
        out.append({
            "mission_id": row["mission_id"],
            "conversation_id": row["conversation_id"],
            "goal": str(record.get("goal", ""))[:200],
            "status": row["status"],
            "current_step": row["current_step"],
            "steps": steps,
            "has_forge_steps": any(
                step["kind"] in FORGE_STEP_KINDS for step in steps),
            "href": f"/missions/{row['mission_id']}",
        })
    return out


def _workstream_tasks(mission_ids: list[str]) -> list[dict]:
    """Queue tasks bound to workspace missions (existing queue DB)."""
    if not mission_ids:
        return []
    from .database import connection
    try:
        with connection() as db:
            placeholders = ",".join("?" * len(mission_ids))
            rows = db.execute(
                f"""SELECT id, kind, status, assigned_node_id,
                mission_id, created_at FROM tasks WHERE mission_id IN
                ({placeholders}) ORDER BY id ASC LIMIT 100""",
                tuple(mission_ids)).fetchall()
    except Exception:
        return []
    return [{
        "task_id": row["id"],
        "kind": str(row["kind"] or "")[:80],
        "status": str(row["status"] or "")[:20],
        "assigned_node_id": str(row["assigned_node_id"] or ""),
        "mission_id": str(row["mission_id"] or ""),
        "created_at": str(row["created_at"] or "")[:19],
    } for row in rows]


def _workstream_workers() -> list[dict]:
    """Fresh nodes from the existing registry (shared, pull-only).

    Workers are not per-workspace: every available node may claim
    any matching task. The list is therefore global and labelled
    shared; per-workstream assignment shows on the tasks.
    """
    from .database import connection, load
    from .nodes import derive_status
    try:
        with connection() as db:
            rows = db.execute(
                """SELECT node_id, status, last_seen, capabilities
                FROM nodes ORDER BY last_seen DESC
                LIMIT 50""").fetchall()
    except Exception:
        return []
    out = []
    for row in rows:
        try:
            caps = load(row["capabilities"] or "[]")
            if not isinstance(caps, list):
                caps = []
        except Exception:
            caps = []
        try:
            derived = derive_status(
                str(row["status"] or ""),
                str(row["last_seen"] or ""))
        except Exception:
            derived = "unknown"
        out.append({
            "node_id": row["node_id"],
            "status": derived,
            "available": derived in ("online", "busy"),
            "capabilities": [str(cap)[:40] for cap in caps[:20]],
            "scope": "shared",
        })
    return out


def _workstream_research(wid: str) -> list[dict]:
    """Research runs opened for this workspace (existing engine)."""
    try:
        from .research_engine import list_runs
        runs = list_runs(limit=50)
    except Exception:
        return []
    out = []
    for run in runs:
        if run.project_ref != wid:
            continue
        metadata = run.metadata or {}
        out.append({
            "run_id": run.run_id,
            "question": run.question[:200],
            "status": run.status,
            "execution_state": run.execution_state,
            "mission_id": run.mission_id or "",
            "dossier_id": run.dossier_id or "",
            "sources": len(run.source_ids or []),
            "claims": len(run.claims or []),
            "reported": bool(metadata.get("reported_to")),
            "href": f"/api/v1/research/runs/{run.run_id}",
        })
        if len(out) >= 20:
            break
    return out


def _workstream_proposals(mission_ids: list[str]) -> list[dict]:
    """Pending proposal-shaped items bound to workspace missions.

    Write steps bind a stored write proposal (existing
    write_proposals table); desktop steps bind a gated desktop
    action (existing action_bindings); proposal steps are
    artifacts awaiting the existing approval flow. Only
    non-terminal items surface; everything else is history.
    """
    if not mission_ids:
        return []
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    try:
        with chat_connection() as db:
            placeholders = ",".join("?" * len(mission_ids))
            mission_rows = db.execute(
                f"""SELECT mission_id, record FROM missions
                WHERE mission_id IN ({placeholders})""",
                tuple(mission_ids)).fetchall()
            bindings = db.execute(
                f"""SELECT action_id, mission_id, step_id
                FROM action_bindings WHERE mission_id IN
                ({placeholders})""", tuple(mission_ids)).fetchall()
            bound_ids = [row["action_id"] for row in bindings]
            actions: dict = {}
            if bound_ids:
                holders = ",".join("?" * len(bound_ids))
                for row in db.execute(
                        f"""SELECT action_id, record, status
                        FROM desktop_actions WHERE action_id IN
                        ({holders})""", tuple(bound_ids)).fetchall():
                    actions[row["action_id"]] = row["status"]
            write_ids: set[str] = set()
            for row in mission_rows:
                try:
                    record = load(row["record"])
                except Exception:
                    continue
                for step in list(record.get("steps", [])):
                    if not isinstance(step, dict):
                        continue
                    params = step.get("parameters", {})
                    if not isinstance(params, dict):
                        continue
                    candidate = str(params.get("proposal_id", ""))
                    if step.get("kind") in (
                            "write", "physical_print") and candidate:
                        write_ids.add(candidate)
            writes: dict = {}
            if write_ids:
                holders = ",".join("?" * len(write_ids))
                for row in db.execute(
                        f"""SELECT proposal_id, status
                        FROM write_proposals WHERE proposal_id IN
                        ({holders})""", tuple(write_ids)).fetchall():
                    writes[row["proposal_id"]] = row["status"]
    except Exception:
        return []
    out = []
    for row in mission_rows:
        try:
            record = load(row["record"])
        except Exception:
            continue
        for step in list(record.get("steps", [])):
            if not isinstance(step, dict):
                continue
            kind = str(step.get("kind", ""))
            step_id = str(step.get("step_id", ""))
            params = step.get("parameters", {})
            if not isinstance(params, dict):
                params = {}
            if kind in ("write", "physical_print"):
                proposal_id = str(params.get("proposal_id", ""))
                state = writes.get(proposal_id, "unknown")
                if state not in ("proposed", "approved"):
                    continue
                out.append({
                    "kind": "write", "proposal_id": proposal_id,
                    "status": state, "step_id": step_id,
                    "mission_id": row["mission_id"],
                    "href": "/writes",
                })
            elif kind == "proposal":
                if str(step.get("status", "")) in (
                        "completed", "failed", "blocked", "skipped"):
                    continue
                out.append({
                    "kind": "proposal",
                    "proposal_id": step_id or row["mission_id"],
                    "status": "artifact-awaiting-review",
                    "step_id": step_id,
                    "mission_id": row["mission_id"],
                    "href": f"/missions/{row['mission_id']}",
                })
    for row in bindings:
        state = actions.get(row["action_id"], "unknown")
        if state != "pending_approval":
            continue
        out.append({
            "kind": "desktop", "proposal_id": row["action_id"],
            "status": state, "step_id": row["step_id"],
            "mission_id": row["mission_id"], "href": "/approvals",
        })
    return out[:40]


def _workstream_forge(missions: list[dict]) -> dict:
    """Forge work in this workspace + shared registry counts.

    Per-workspace truth is missions carrying fabricate/slice/
    physical_print steps (existing step kinds). The model registry
    itself is global; counts are labelled shared with a link.
    """
    carrying = [item for item in missions
                if item.get("has_forge_steps")]
    registry: dict = {"models": 0, "fabjobs": 0, "scope": "shared"}
    try:
        from .workshop3d import list_fabjobs, list_models
        registry["models"] = len(list_models(limit=50))
        registry["fabjobs"] = len(list_fabjobs(limit=50))
    except Exception:
        pass
    return {
        "missions": [{
            "mission_id": item["mission_id"],
            "goal": item["goal"],
            "status": item["status"],
            "steps": [step for step in item["steps"]
                      if step["kind"] in FORGE_STEP_KINDS],
            "href": item["href"],
        } for item in carrying],
        "registry": registry,
        "href": "/forge",
    }


def _workstream_bus_events(conv_ids: list[str],
                           mission_ids: list[str]) -> list[dict]:
    """Interface bus events touching this workspace (bounded scan)."""
    if not conv_ids and not mission_ids:
        return []
    wanted_conv = set(conv_ids)
    wanted_mission = set(mission_ids)
    try:
        from .events import list_events
        found = list_events(limit=100)
    except Exception:
        return []
    out = []
    for event in found:
        if (event.conversation_id in wanted_conv
                or event.mission_id in wanted_mission):
            out.append({
                "event_id": event.event_id,
                "event_type": event.event_type,
                "conversation_id": event.conversation_id,
                "mission_id": event.mission_id,
                "summary": event.summary[:200],
                "created_at": event.created_at[:19],
            })
        if len(out) >= 20:
            break
    return out


#: Strict patterns for our own fork bookkeeping messages in
#: conversation_events. Only exact matches on records this module
#: wrote become tree edges; anything else is shown flat, never
#: guessed.
_FORK_ID_RE = r"(conv\-[A-Za-z0-9]+|conv\_[A-Za-z0-9]+)"
_FORKED_FROM_RE = _re.compile(r"^Forked from " + _FORK_ID_RE + r"\b")
_FORKED_TO_RE = _re.compile(r"^Forked to " + _FORK_ID_RE + r"\b")


def open_href_for(conversation_id: str) -> str:
    """Continue-route for one conversation (existing pages only).

    Live ``conv-`` chats continue in /chat; imported ``conv_``
    conversations open in the archive. Anything else falls back
    to the read-only JSON view.
    """
    text = str(conversation_id or "")
    if text.startswith("conv-"):
        return f"/chat?id={text}"
    if text.startswith("conv_"):
        return f"/conversations/{text}"
    return f"/api/v1/conversations/{text}"


def conversation_tree(workspace_id: str) -> dict:
    """Conversation tree from existing rows only.

    Nodes come from the ``conversations`` table (with message
    counts); parent edges come exclusively from this module's own
    fork bookkeeping in ``conversation_events`` and only when both
    endpoints still live in this workspace. No match, no claim:
    unmatched conversations are roots, never invented children.
    """
    wid = check_workspace_id(workspace_id)
    from .database import chat_connection, init_chat_database
    init_chat_database()
    try:
        with chat_connection() as db:
            rows = db.execute(
                """SELECT c.conversation_id, c.title, c.created_at,
                COUNT(m.message_id) AS messages
                FROM conversations c LEFT JOIN messages m
                ON m.conversation_id = c.conversation_id
                WHERE c.project_ref=? GROUP BY c.conversation_id
                ORDER BY c.created_at ASC LIMIT 50""",
                (wid,)).fetchall()
            conv_ids = [row["conversation_id"] for row in rows]
            notes: list = []
            if conv_ids:
                placeholders = ",".join("?" * len(conv_ids))
                notes = db.execute(
                    f"""SELECT conversation_id, message
                    FROM conversation_events WHERE conversation_id IN
                    ({placeholders}) AND (message LIKE 'Forked from %'
                    OR message LIKE 'Forked to %') LIMIT 200""",
                    tuple(conv_ids)).fetchall()
    except Exception:
        return {"nodes": {}, "roots": [], "children": {},
                "edges": []}
    known = {row["conversation_id"] for row in rows}
    parent_of: dict[str, str] = {}
    for note in notes:
        owner = str(note["conversation_id"] or "")
        text = str(note["message"] or "")
        from_match = _FORKED_FROM_RE.match(text)
        if from_match and owner in known:
            candidate = from_match.group(1)
            if candidate in known and candidate != owner:
                parent_of.setdefault(owner, candidate)
            continue
        to_match = _FORKED_TO_RE.match(text)
        if to_match and owner in known:
            candidate = to_match.group(1)
            if candidate in known and candidate != owner:
                parent_of.setdefault(candidate, owner)
    nodes = {row["conversation_id"]: {
        "conversation_id": row["conversation_id"],
        "title": row["title"] or row["conversation_id"],
        "created_at": row["created_at"] or "",
        "messages": row["messages"],
        "parent": parent_of.get(row["conversation_id"], ""),
        "open_href": open_href_for(row["conversation_id"]),
    } for row in rows}
    children: dict[str, list[str]] = {key: [] for key in nodes}
    for child, parent in parent_of.items():
        if child in children and parent in children:
            children[parent].append(child)
    for key in children:
        children[key].sort(
            key=lambda cid: nodes[cid]["created_at"])
    roots = sorted(
        (key for key in nodes if key not in parent_of),
        key=lambda cid: nodes[cid]["created_at"])
    edges = [[parent, child]
             for child, parent in sorted(parent_of.items())]
    return {"nodes": nodes, "roots": roots, "children": children,
            "edges": edges}


#: Entity prefix that links a workspace to INVENTory projects.
#: Only exact ``proj_`` ids from existing rows count — never
#: name similarity, never guesses.
PROJECT_PREFIX = "proj_"


def inventory_project_refs(workspace_id: str) -> list[dict]:
    """INVENTory project ids demonstrably tied to this workspace.

    Three existing-row sources, all read-only:

    - the workspace id itself, when it IS a ``proj_`` id;
    - ``proj_`` entity ids in this workspace's mission
      ``context_records``;
    - ``proj_`` ids in this workspace's research run
      ``linked_entities``.

    Returns ``[{entity_id, via}]`` sorted by id. Resolution
    (single GET per id) happens at the read-path caller with the
    existing bridge; this function never touches the network and
    never writes.
    """
    wid = check_workspace_id(workspace_id)
    found: dict[str, str] = {}
    if wid.startswith(PROJECT_PREFIX):
        found[wid] = "workspace-id"
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    try:
        with chat_connection() as db:
            rows = db.execute(
                """SELECT m.record FROM missions m
                JOIN conversations c
                ON c.conversation_id = m.conversation_id
                WHERE c.project_ref=? LIMIT 50""",
                (wid,)).fetchall()
    except Exception:
        rows = []
    for row in rows:
        try:
            record = load(row["record"])
        except Exception:
            continue
        entries = record.get("context_records", [])
        if not isinstance(entries, list):
            continue
        for entry in entries[:20]:
            if not isinstance(entry, dict):
                continue
            candidate = str(entry.get("entity_id", ""))
            if candidate.startswith(PROJECT_PREFIX) \
                    and 4 < len(candidate) <= 80:
                found.setdefault(candidate, "mission-context")
    try:
        from .research_engine import list_runs
        runs = list_runs(limit=50)
    except Exception:
        runs = []
    for run in runs:
        try:
            if run.project_ref != wid:
                continue
            linked = run.linked_entities or []
        except Exception:
            continue
        for link in list(linked)[:20]:
            candidate = str(getattr(link, "entity_id", "") or "")
            if candidate.startswith(PROJECT_PREFIX) \
                    and 4 < len(candidate) <= 80:
                found.setdefault(candidate, "research-link")
    return [{"entity_id": key, "via": found[key]}
            for key in sorted(found)]


def ensure_conversation(workspace_id: str, title: str) -> dict:
    """Create one conversation row inside a workspace.

    Same existing ``conversations`` table the chat path writes;
    the row starts empty and fills through the normal message,
    mission and event stores.
    """
    wid = check_workspace_id(workspace_id)
    from .conversations import generate_conversation_id
    from .database import chat_connection, init_chat_database
    clean = str(title or "").strip()[:MAX_TITLE_CHARS] or wid
    init_chat_database()
    conversation_id = generate_conversation_id()
    with chat_connection() as db:
        db.execute(
            """INSERT INTO conversations
            (conversation_id, title, project_ref, created_at)
            VALUES (?, ?, ?, ?)""",
            (conversation_id, clean, wid, _now()))
    _note_event(conversation_id,
                f"Conversation opened in workspace '{wid}'.")
    return {"conversation_id": conversation_id,
            "workspace_id": wid, "title": clean}


def fork_conversation(conversation_id: str,
                      target_workspace: str = "") -> dict:
    """Fork one conversation: copy row + messages under a new id.

    The fork keeps the source workspace unless an explicit target is
    given, carries the same provenance per message, and continues
    independently afterwards (new ``conv-`` id, own message rows).
    """
    from .conversations import generate_conversation_id
    from .conversations import generate_message_id
    from .database import chat_connection, init_chat_database
    init_chat_database()
    target = (check_workspace_id(target_workspace)
              if str(target_workspace or "").strip() else "")
    with chat_connection() as db:
        source = db.execute(
            "SELECT * FROM conversations WHERE conversation_id=?",
            (conversation_id,)).fetchone()
        if source is None:
            raise WorkspaceNotFoundError(
                f"Conversation '{conversation_id}' not found")
        messages = db.execute(
            """SELECT role, content, provenance, sources
            FROM messages WHERE conversation_id=?
            ORDER BY created_at ASC LIMIT 200""",
            (conversation_id,)).fetchall()
        new_id = generate_conversation_id()
        workspace = target or str(source["project_ref"] or "")
        title = (str(source["title"] or "") + " (fork)")[:MAX_TITLE_CHARS]
        created = _now()
        db.execute(
            """INSERT INTO conversations
            (conversation_id, title, project_ref, created_at)
            VALUES (?, ?, ?, ?)""",
            (new_id, title, workspace, created))
        for item in messages:
            db.execute(
                """INSERT INTO messages
                (message_id, conversation_id, role, content,
                 created_at, provenance, sources)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (generate_message_id(), new_id, item["role"],
                 item["content"], created, item["provenance"],
                 item["sources"]))
    _note_event(conversation_id,
                f"Forked to {new_id}; the fork continues on its own.")
    _note_event(new_id,
                f"Forked from {conversation_id} "
                f"({len(messages)} message(s) carried over, "
                "provenance unchanged).")
    return {
        "conversation_id": new_id,
        "forked_from": conversation_id,
        "workspace_id": workspace,
        "title": title,
        "messages_carried": len(messages),
        "href": f"/api/v1/conversations/{new_id}",
    }


def attach_conversation(conversation_id: str,
                        workspace_id: str) -> dict:
    """(Re-)link a conversation to a workspace: one UPDATE.

    Moving to a fresh slug creates that workspace implicitly, so a
    conversation/mission/result can later be re-linked to the same
    project without any new store.
    """
    wid = check_workspace_id(workspace_id)
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute(
            "SELECT project_ref FROM conversations "
            "WHERE conversation_id=?", (conversation_id,)).fetchone()
        if row is None:
            raise WorkspaceNotFoundError(
                f"Conversation '{conversation_id}' not found")
        previous = str(row["project_ref"] or "")
        if previous != wid:
            db.execute(
                "UPDATE conversations SET project_ref=? "
                "WHERE conversation_id=?", (wid, conversation_id))
    if previous != wid:
        _note_event(conversation_id,
                    f"Linked to workspace '{wid}'"
                    + (f" (was '{previous}')" if previous else
                       " (was unlinked)") + ".")
    return {
        "conversation_id": conversation_id,
        "workspace_id": wid,
        "previous_workspace": previous,
        "moved": previous != wid,
    }


def attach_mission(mission_id: str, conversation_id: str) -> dict:
    """(Re-)link a mission to a conversation (hence its workspace).

    The mission row and its JSON record move together; the mission_id
    is unchanged so provenance and bindings survive. The target
    conversation must exist; its workspace becomes the mission's.
    """
    from .database import chat_connection, init_chat_database
    from .missions import load_mission, save_mission
    target = str(conversation_id or "").strip()
    if not target:
        raise WorkspaceRefusedError("conversation_id is required")
    init_chat_database()
    with chat_connection() as db:
        row = db.execute(
            "SELECT project_ref FROM conversations "
            "WHERE conversation_id=?", (target,)).fetchone()
        if row is None:
            raise WorkspaceNotFoundError(
                f"Conversation '{target}' not found")
        workspace = str(row["project_ref"] or "")
    mission = load_mission(mission_id)
    if mission is None:
        raise WorkspaceNotFoundError(
            f"Mission '{mission_id}' not found")
    previous = str(mission.conversation_id or "")
    if previous != target:
        try:
            record = load_mission(mission_id)
            updated = record.model_copy(
                update={"conversation_id": target})
        except Exception as exc:
            raise WorkspaceRefusedError(
                f"Mission record unreadable: {exc}") from exc
        save_mission(updated)
        _note_event(previous,
                    f"Mission {mission_id} moved to {target} "
                    f"(workspace '{workspace or '-'}').",
                    mission_id=mission_id)
        _note_event(target,
                    f"Mission {mission_id} linked here from "
                    f"{previous or 'nowhere'}; mission_id unchanged.",
                    mission_id=mission_id)
    return {
        "mission_id": mission_id,
        "conversation_id": target,
        "previous_conversation": previous,
        "workspace_id": workspace,
        "moved": previous != target,
    }
