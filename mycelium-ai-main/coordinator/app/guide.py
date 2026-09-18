"""Mycelium Guide (BIG #33): what needs Jelles, derived live.

The guide is not a chatbot and never invents advice. It reads
existing state on every call and returns WHAT / WHY / NEXT
items that link to real pages:

- approvals waiting (desktop, writes, missions)
- knowledge candidates waiting for review
- conversation missed items (unresolved questions, ideas)
- research dossiers with open questions
- camera inbox files ready for analysis
- fabrications waiting for a next step
- nodes that went quiet
- projects that have no mission carrying them

Read-only. Bounded. Nothing stored, nothing promoted.
"""

from __future__ import annotations

GUIDE_KINDS = (
    "approval", "candidate", "conversation", "research",
    "camera", "fabrication", "node", "project", "mission",
)


def _item(kind: str, glyph: str, what: str, why: str,
          label: str, href: str) -> dict:
    return {"kind": kind, "glyph": glyph, "what": what[:160],
            "why": why[:240], "next": {"label": label[:60],
                                       "href": href[:200]}}


def guide_items(limit: int = 12) -> list[dict]:
    """Compute guide items from live stores. Never raises."""
    items: list[dict] = []
    try:
        from . import main as _main
        status = _main.coordinator_status()
        approvals = status.get("pending_approvals", {})
        waiting = sum(int(approvals.get(key, 0)) for key in
                      ("desktop_actions", "write_proposals",
                       "missions"))
        if waiting:
            items.append(_item(
                "approval", "🟡",
                f"{waiting} thing(s) waiting for your YES.",
                "Approvals never auto-resolve. Nothing moves "
                "until you decide.",
                "Review approvals", "/agents"))
    except Exception:
        pass
    try:
        from .knowledge import list_candidates
        candidates = list_candidates(limit=50)
        if candidates:
            items.append(_item(
                "candidate", "🌱",
                f"{len(candidates)} candidate(s) wait for review.",
                "Observations stay candidates until you support "
                "or promote them.",
                "Open knowledge", "/knowledge"))
    except Exception:
        pass
    try:
        from .ecosystem import discoveries
        found = discoveries(limit=6)
        missed = found.get("items", [])
        if missed:
            first = missed[0]
            items.append(_item(
                "conversation", "💬",
                f"{len(missed)} possible missed item(s) in "
                f"{found.get('imports_considered', '?')} "
                "conversation(s).",
                str(first.get("text", ""))[:200],
                "Review conversation",
                str(first.get("link", "/conversations"))))
        open_questions = found.get("research_open_questions", [])
        if open_questions:
            first = open_questions[0]
            items.append(_item(
                "research", "🔬",
                f"{len(open_questions)} open research question(s).",
                str(first.get("question", ""))[:200],
                "Open dossier",
                str(first.get("link", "/research"))))
    except Exception:
        pass
    try:
        from .vision_ingest import list_inbox_files
        inbox = list_inbox_files(limit=5)
        if inbox:
            items.append(_item(
                "camera", "📷",
                f"{len(inbox)} camera file(s) wait in the inbox.",
                "New visual material becomes an observation "
                "only after ingest.",
                "Open cameras", "/cameras"))
    except Exception:
        pass
    try:
        from . import main as _main
        waiting_fab = [record for record in
                       _main.list_fabrications(50)
                       if record.status in ("proposed", "approved",
                                            "ready", "waiting")]
        if waiting_fab:
            items.append(_item(
                "fabrication", "🛠",
                f"{len(waiting_fab)} fabrication(s) wait "
                "for a next step.",
                "Physical work only moves with your explicit "
                "approval.",
                "Open fabrication", "/fabrication"))
    except Exception:
        pass
    try:
        from . import main as _main
        quiet = [record for record in _main.list_nodes()
                 if record.get("derived_status") in
                 ("stale", "offline")]
        if quiet:
            items.append(_item(
                "node", "💻",
                f"{len(quiet)} node(s) quiet: "
                f"{quiet[0].get('node_id', '?')}.",
                "Nodes are pull-only helpers; a quiet node "
                "simply stops claiming work.",
                "Open nodes", "/nodes"))
    except Exception:
        pass
    try:
        from . import main as _main
        from .missions import list_missions
        missions = list_missions(limit=100)
        mission_text = " ".join(
            f"{m.goal} {m.context or ''}" for m in missions)[:4000]
        reader = _main._world_reader()
        import anyio as _anyio

        async def _projects() -> list:
            try:
                browsed = await reader.browse("projects")
                return browsed.results or []
            except Exception:
                return []

        try:
            projects = _anyio.run(_projects)
        except Exception:
            projects = []
        orphan = None
        for record in projects[:20]:
            ident = str(record.entity_id)
            if ident not in mission_text:
                orphan = ident
                break
        if orphan and len(projects) >= 1:
            items.append(_item(
                "project", "🌿",
                "A project has no mission carrying it.",
                f"{orphan} appears in no mission goal or "
                "context yet.",
                "Open craft tree",
                f"/craft?entity_id={orphan}"))
        running = [m for m in missions
                   if m.status in ("approved", "running")]
        if not running and missions:
            items.append(_item(
                "mission", "🧭",
                "No mission is currently running.",
                "Paused work waits; pick one quest to wake up.",
                "Open missions", "/missions"))
    except Exception:
        pass
    return items[: max(1, min(int(limit or 12), 20))]
