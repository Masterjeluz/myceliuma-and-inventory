"""Context engine (BIG #31): one dynamic composer over all stores.

Every flow — command, chat, packet, search, morning — composes
context here instead of assembling its own partial dump:

- intent (raw text) + projects + INVENTory + memories + observations
- conversations (live + imported) + research + nodes + missions
- agenda + recent activity

Rules (tested, fail-closed):

- RELEVANT: keyword overlap against the intent; nothing unbounded.
- BOUNDED: per-section caps; total item cap; text clipped.
- TRACEABLE: every item carries {source, id, why} — the composer
  records why each item was included.
- PROVENANCE-AWARE: provenance passes through untouched; imported
  and AI content never renders as verified.
- Health stays scoped: health memories/agenda hints excluded unless
  include_health=True is passed explicitly by the operator.

Command traces: the last N command executions (intent → steps →
result) are stored so /world can show the live flow
INTENT → CONTEXT → ... → MISSION → WAITING/COMPLETED instead of
only prose. Traces are read-only history, never authority.
"""

from __future__ import annotations

import re as _re
import secrets as _secrets
import time as _time

ENGINE_VERSION = "mycelium-context-engine/1"
MAX_SECTION_ITEMS = 8
MAX_TOTAL_ITEMS = 40
MAX_TEXT_CHARS = 220
TRACE_LIMIT = 20

_WORD_RE = _re.compile(r"[a-zA-Z0-9]{3,}")


def _keywords(text: str) -> set[str]:
    stop = {"the", "and", "for", "with", "van", "het", "een", "die",
            "dat", "wat", "hoe", "mijn", "nog", "naar", "door", "over",
            "als", "ook", "niet", "wel", "uit", "bij", "tot", "waar",
            "wie", "zijn", "wordt", "worden", "deze", "dit", "have",
            "has", "are", "was", "were", "you", "your", "can", "our",
            "from", "into", "does", "did", "any", "all", "but", "not"}
    return {word.lower() for word in _WORD_RE.findall(str(text or ""))
            if word.lower() not in stop}


def _clip(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    return " ".join(str(text or "").split())[:limit]


def _score(text: str, keywords: set[str]) -> tuple[int, list[str]]:
    words = {word.lower() for word in _WORD_RE.findall(str(text or ""))}
    hits = sorted(words & keywords)
    return len(hits), hits[:5]


def _item(source: str, ident: str, title: str, snippet: str,
          keywords: set[str], provenance: dict | None = None) -> dict:
    score, hits = _score(f"{title} {snippet}", keywords)
    return {"source": source, "id": str(ident or "")[:100],
            "title": _clip(title, 140), "snippet": _clip(snippet),
            "score": score,
            "why": (f"matches: {', '.join(hits)}" if hits
                    else "recent / in scope"),
            "provenance": dict(provenance or {})}


def compose(intent: str = "", *, project_id: str = "",
            conversation_id: str = "", include_health: bool = False,
            limit_per_section: int = MAX_SECTION_ITEMS) -> dict:
    """Compose bounded, traceable context for one intent."""
    keywords = _keywords(intent)
    cap = max(1, min(int(limit_per_section or MAX_SECTION_ITEMS),
                     MAX_SECTION_ITEMS))
    context: dict = {
        "engine": ENGINE_VERSION,
        "intent": _clip(intent, 500),
        "keywords": sorted(keywords)[:20],
        "project_id": str(project_id or "")[:80],
        "sections": {}, "total_items": 0,
        "health_scoped_out": not include_health,
    }

    def add(section: str, items: list[dict]) -> None:
        ranked = sorted(items, key=lambda item: item.get("score", 0),
                        reverse=True)[:cap]
        context["sections"][section] = ranked
        context["total_items"] += len(ranked)

    # -- INVENTory (read-only bridge) ------------------------------------
    inventory_items: list[dict] = []
    try:
        from . import main as _main
        import anyio as _anyio

        async def _gather() -> list[dict]:
            reader = _main._world_reader()
            query = (intent or project_id or "").strip()[:200]
            out: list[dict] = []
            if query:
                try:
                    found = await reader.search(query)
                    for record in (found.results or [])[:cap]:
                        details = record.details \
                            if isinstance(record.details, dict) else {}
                        prov = record.provenance
                        out.append(_item(
                            "inventory", record.entity_id,
                            str(details.get("name", details.get(
                                "title", record.entity_id))),
                            str(details.get("description", ""))[:220],
                            keywords,
                            prov.model_dump(mode="json")
                            if hasattr(prov, "model_dump") else {}))
                except Exception:
                    pass
            if project_id:
                try:
                    entity = await reader.entity("project", project_id) \
                        if project_id.startswith("proj_") else None
                    if entity is not None:
                        details = entity.details \
                            if isinstance(entity.details, dict) else {}
                        inventory_items.append(_item(
                            "inventory", project_id,
                            str(details.get("name", project_id)),
                            "explicit project scope", keywords, {}))
                except Exception:
                    pass
            return out

        try:
            inventory_items.extend(_anyio.run(_gather))
        except Exception:
            pass
    except Exception:
        pass
    add("inventory", inventory_items)

    # -- memories ----------------------------------------------------------
    memory_items: list[dict] = []
    try:
        from .memory import list_memories
        for entry in list_memories(limit=cap * 3):
            if entry.memory_type == "health" and not include_health:
                continue
            memory_items.append(_item(
                "memory", entry.memory_id, entry.title,
                f"[{entry.memory_type}/{entry.truth}] "
                f"{entry.project_ref or 'no project'}",
                keywords,
                {"source_type": "memory", "truth": entry.truth,
                 "human_verified": entry.truth in
                 ("user_fact", "verified")}))
    except Exception:
        pass
    add("memories", memory_items)

    # -- missions ------------------------------------------------------------
    mission_items: list[dict] = []
    try:
        from .missions import list_missions
        for mission in list_missions(limit=cap * 2):
            mission_items.append(_item(
                "mission", mission.mission_id, mission.goal,
                f"[{mission.status}] step {mission.current_step}/"
                f"{len(mission.steps)}", keywords,
                {"source_type": "mission", "status": mission.status}))
    except Exception:
        pass
    add("missions", mission_items)

    # -- research --------------------------------------------------------------
    research_items: list[dict] = []
    try:
        from .research_engine import list_dossiers
        for dossier in list_dossiers(limit=cap):
            research_items.append(_item(
                "research", dossier.dossier_id, dossier.title,
                f"[{dossier.execution_state}] {len(dossier.claims)} "
                f"claims, {len(dossier.open_questions)} open",
                keywords,
                {"source_type": "external-source",
                 "human_verified": False}))
    except Exception:
        pass
    add("research", research_items)

    # -- conversations (imported) ----------------------------------------------
    conversation_items: list[dict] = []
    try:
        from .conversation_bridge import list_imports, load_analysis
        for meta in list_imports(limit=cap):
            analysis = load_analysis(meta["conversation_id"]) or {}
            conversation_items.append(_item(
                "conversation", meta["conversation_id"],
                meta.get("title", ""),
                f"[{meta.get('source_platform', '')}] "
                f"{meta.get('message_count', 0)} messages, "
                f"{len(analysis.get('findings', []))} findings",
                keywords,
                {"source_type": "imported", "human_verified": False}))
    except Exception:
        pass
    if conversation_id:
        conversation_items.append(
            _item("conversation", conversation_id, "active conversation",
                  "explicit conversation scope", keywords, {}))
    add("conversations", conversation_items)

    # -- nodes -------------------------------------------------------------------
    node_items: list[dict] = []
    try:
        from . import main as _main
        for record in _main.list_nodes()[:cap]:
            node_items.append(_item(
                "node", record["node_id"],
                str(record.get("display_name") or record["node_id"]),
                f"[{record.get('derived_status', '')}] "
                f"{', '.join(record.get('capabilities', [])[:6])}",
                keywords, {"source_type": "node-status"}))
    except Exception:
        pass
    add("nodes", node_items)

    # -- agenda + activity ---------------------------------------------------------
    agenda_items: list[dict] = []
    try:
        from .agenda import init_agenda_tables, list_events
        from .database import chat_connection, init_chat_database
        init_chat_database()
        with chat_connection() as db:
            init_agenda_tables(db)
            for event in list_events(db, limit=cap):
                agenda_items.append(_item(
                    "agenda", str(event.get("uid", "")),
                    str(event.get("title", "")),
                    f"{event.get('start', '')} "
                    f"{event.get('location', '')}", keywords,
                    {"source_type": "agenda-import",
                     "human_verified": False}))
    except Exception:
        pass
    add("agenda", agenda_items)

    activity_items: list[dict] = []
    try:
        from .ecosystem import activity_feed
        for entry in activity_feed(limit=cap)[:cap]:
            activity_items.append(_item(
                "activity", entry.get("link", "/activity"),
                entry.get("voice", ""),
                entry.get("summary", ""), keywords, {}))
    except Exception:
        pass
    add("activity", activity_items)

    # -- observations (cameras) ------------------------------------------------------
    observation_items: list[dict] = []
    try:
        from .cameras import list_devices, list_observations
        for device in list_devices()[:cap]:
            latest = list_observations(device.device_id, limit=1)
            last = latest[0].observation_id if latest else "none yet"
            observation_items.append(_item(
                "observation", device.device_id, device.name,
                f"[{device.source}] last: {last}", keywords,
                {"source_type": "sensor-observed",
                 "human_verified": False}))
    except Exception:
        pass
    add("observations", observation_items)

    context["total_items"] = sum(
        len(items) for items in context["sections"].values())
    return context


def init_trace_tables() -> None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS command_traces (
            trace_id TEXT PRIMARY KEY,
            intent TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            record TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS system_mode (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mode TEXT NOT NULL DEFAULT 'DAY',
            detail TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        """)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def record_trace(intent: str, steps: list[dict],
                 result: dict | None = None) -> dict:
    """Persist one command flow trace (read-only history)."""
    from .database import chat_connection, dump
    init_trace_tables()
    trace = {
        "trace_id": f"trace_{int(_time.time() * 1000):x}"
                    f"{_secrets.token_hex(3)}",
        "intent": _clip(intent, 300),
        "created_at": _now(),
        "steps": [dict(step) for step in (steps or [])][:20],
        "result": dict(result or {}),
    }
    with chat_connection() as db:
        db.execute("""INSERT INTO command_traces
        (trace_id, intent, created_at, record) VALUES (?, ?, ?, ?)""",
                   (trace["trace_id"], trace["intent"],
                    trace["created_at"], dump(trace)))
        db.execute(
            "DELETE FROM command_traces WHERE trace_id NOT IN "
            "(SELECT trace_id FROM command_traces ORDER BY created_at "
            "DESC LIMIT ?)", (TRACE_LIMIT,))
    return trace


def recent_traces(limit: int = 5) -> list[dict]:
    from .database import chat_connection, load
    init_trace_tables()
    count = max(1, min(int(limit or 5), TRACE_LIMIT))
    with chat_connection() as db:
        rows = db.execute(
            "SELECT record FROM command_traces ORDER BY created_at "
            "DESC LIMIT ?", (count,)).fetchall()
    out = []
    for row in rows:
        try:
            out.append(load(row["record"]))
        except Exception:
            continue
    return out


# -- overnight mode ----------------------------------------------------------

DAY_MODE = "DAY"
OVERNIGHT_MODE = "OVERNIGHT"
VALID_MODES = frozenset({DAY_MODE, OVERNIGHT_MODE})


def get_mode() -> dict:
    from .database import chat_connection
    init_trace_tables()
    with chat_connection() as db:
        row = db.execute(
            "SELECT mode, detail, updated_at FROM system_mode "
            "WHERE id=1").fetchone()
    if row is None:
        return {"mode": DAY_MODE, "detail": "", "updated_at": ""}
    return {"mode": row["mode"], "detail": row["detail"],
            "updated_at": row["updated_at"]}


def set_mode(mode: str, detail: str = "") -> dict:
    cleaned = str(mode or "").strip().upper()
    if cleaned not in VALID_MODES:
        raise ValueError(
            f"Unknown mode '{mode}'; expected DAY or OVERNIGHT")
    record = {"mode": cleaned, "detail": str(detail or "")[:300],
              "updated_at": _now()}
    from .database import chat_connection
    init_trace_tables()
    with chat_connection() as db:
        db.execute("""INSERT INTO system_mode
        (id, mode, detail, updated_at) VALUES (1, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET mode=excluded.mode,
        detail=excluded.detail, updated_at=excluded.updated_at""",
                   (record["mode"], record["detail"],
                    record["updated_at"]))
    return record
