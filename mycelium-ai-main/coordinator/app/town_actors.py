"""Town actors: NPC-aanwezigheid als projectie (fase 5a).

Één additieve tabel ``town_actors`` + één feed ``town_activity``
in de chat-DB (zelfde patroon als town_memory). Geen tweede
brein, geen scheduler, geen executie: dit is een leesmodel.

Eerlijkheidsregel (geleend van agent-virtual-office): de status
van een NPC verandert alleen op echte signalen — taken uit de
queue die aan die NPC gebonden zijn, of een Hermes-sessie die
antwoordt. Zonder signaal is een NPC ``idle``, nooit verzonnen
``working``.

Delegeren (fase 5b) en autonomie (5c) komen hier niet: die
haken aan bij de bestaande proposal → exact-YES → queue-flow.
"""

import datetime

NPC_ORDER = ("mos", "oracle", "smid", "archivaris",
             "voorman", "seinwachter")

#: Eerlijke activiteiten (geen euphemismen, geen spinner).
ACTIVITIES = ("idle", "working", "meeting", "walking")

#: Sources die een status mogen verklaren.
SOURCES = ("queue", "hermes", "player", "system")

WORLD_W = 3840
WORLD_H = 1400


class ActorRefusedError(ValueError):
    """Validatie geweigerd; niets opgeslagen."""


def _utc_now() -> str:
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def npc_desk(npc_id: str) -> dict:
    """Vaste werkspot per NPC: een boog rond het plein.

    Deterministisch (index in NPC_ORDER), zodat een NPC thuis
    is op zijn plek — het huiselijkheidsgevoel van een kantoor
    zonder enige randomiteit of verzonnen beweging."""
    import math

    npc = str(npc_id or "").strip()
    if npc not in NPC_ORDER:
        raise ActorRefusedError(f"Unknown NPC '{npc}'")
    idx = NPC_ORDER.index(npc)
    angle = math.pi * (0.15 + 0.7 * idx / (len(NPC_ORDER) - 1))
    cx, cy, radius = WORLD_W / 2, WORLD_H / 2, 300.0
    return {"x": round(cx + radius * math.cos(angle), 1),
            "y": round(cy + radius * math.sin(angle), 1)}


def ensure_tables(db=None) -> None:
    """Additieve tabellen; idempotent, nooit destructief."""
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with (db or chat_connection()) as handle:
        handle.execute(
            """CREATE TABLE IF NOT EXISTS town_actors (
                npc_id TEXT PRIMARY KEY,
                x REAL NOT NULL,
                y REAL NOT NULL,
                activity TEXT NOT NULL DEFAULT 'idle',
                detail TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'idle',
                source TEXT NOT NULL DEFAULT 'system',
                updated_at TEXT NOT NULL
            )""")
        handle.execute(
            """CREATE TABLE IF NOT EXISTS town_activity (
                ts TEXT NOT NULL,
                npc_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT ''
            )""")


def set_actor(npc_id: str, *, x: float, y: float,
              activity: str = "idle", detail: str = "",
              status: str = "idle",
              source: str = "system") -> dict:
    """Zet één actor. Alles wordt gevalideerd; de speler
    mag een NPC verplaatsen (bijv. na een gesprek), de activiteit
    moet een eerlijke waarde en de bron een bekende."""
    import re as _re

    npc = str(npc_id or "").strip()
    if npc not in NPC_ORDER:
        raise ActorRefusedError(f"Unknown NPC '{npc}'")
    try:
        fx, fy = float(x), float(y)
    except (TypeError, ValueError):
        raise ActorRefusedError("x and y must be numbers")
    if not (0 <= fx <= WORLD_W and 0 <= fy <= WORLD_H):
        raise ActorRefusedError("position outside the world")
    activity = str(activity or "idle").strip().lower()
    if activity not in ACTIVITIES:
        raise ActorRefusedError(
            f"activity must be one of {', '.join(ACTIVITIES)}")
    status = str(status or "idle").strip().lower()
    if status not in ACTIVITIES:
        raise ActorRefusedError(
            f"status must be one of {', '.join(ACTIVITIES)}")
    source = str(source or "system").strip().lower()
    if source not in SOURCES:
        raise ActorRefusedError(
            f"source must be one of {', '.join(SOURCES)}")
    detail = _re.sub(r"\s+", " ", str(detail or ""))[:120]
    ensure_tables()
    from .database import chat_connection
    with chat_connection() as db:
        db.execute(
            """INSERT INTO town_actors
            (npc_id, x, y, activity, detail, status, source,
             updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(npc_id) DO UPDATE SET
                x=excluded.x, y=excluded.y,
                activity=excluded.activity, detail=excluded.detail,
                status=excluded.status, source=excluded.source,
                updated_at=excluded.updated_at""",
            (npc, fx, fy, activity, detail, status, source,
             _utc_now()))
    record_activity(npc, "state",
                    f"{activity}" + (f": {detail}" if detail
                                     else ""))
    return actor(npc)


def actor(npc_id: str) -> dict | None:
    """Één actor of None. Leest nooit fouten, geeft nooit
    verzonnen rijen."""
    npc = str(npc_id or "").strip()
    if npc not in NPC_ORDER:
        return None
    try:
        from .database import chat_connection, init_chat_database
        init_chat_database()
        with chat_connection() as db:
            row = db.execute(
                """SELECT npc_id, x, y, activity, detail, status,
                   source, updated_at FROM town_actors
                   WHERE npc_id=?""", (npc,)).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    return dict(row)


def _idle_row(npc_id: str) -> dict:
    """Eerlijke idle-rij op de vaste werkspot."""
    desk = npc_desk(npc_id)
    return {"npc_id": npc_id, "x": desk["x"],
            "y": desk["y"], "activity": "idle",
            "detail": "", "status": "idle",
            "source": "system", "updated_at": ""}


def list_actors() -> list:
    """Alle bekende NPC's: een rij als die er is, anders een
    eerlijke idle-rij op hun vaste werkspot."""
    return [row if row is not None else _idle_row(npc)
            for npc in NPC_ORDER
            for row in (actor(npc),)]


def record_activity(npc_id: str, kind: str,
                    detail: str = "") -> None:
    """Append één feed-regel; feed is gebonden (laatste 500).
    Best-effort: de feed mag nooit een staatwijziging breken."""
    try:
        ensure_tables()
        from .database import chat_connection
        npc = str(npc_id or "").strip()
        kind = str(kind or "state").strip().lower()[:40]
        detail = str(detail or "")[:200]
        if not kind or npc not in NPC_ORDER:
            return
        with chat_connection() as db:
            db.execute(
                """INSERT INTO town_activity (ts, npc_id, kind,
                   detail) VALUES (?, ?, ?, ?)""",
                (_utc_now(), npc, kind, detail))
            db.execute(
                """DELETE FROM town_activity WHERE rowid NOT IN
                (SELECT rowid FROM town_activity
                 ORDER BY rowid DESC LIMIT 500)""")
    except Exception:
        pass


def activity_feed(limit: int = 20) -> list:
    """Recente feed, nieuwste eerst. Leest nooit fouten."""
    try:
        from .database import chat_connection, init_chat_database
        init_chat_database()
        with chat_connection() as db:
            rows = db.execute(
                """SELECT ts, npc_id, kind, detail FROM
                   town_activity ORDER BY rowid DESC LIMIT ?""",
                (max(1, min(int(limit or 20), 100)),)).fetchall()
    except Exception:
        return []
    return [dict(row) for row in reversed(rows)]


def sync_from_signals(tasks=None) -> list:
    """Status afleiden uit echte signalen (lezen alleen).

    ``tasks`` is de queue-uitvoer van ``list_tasks()`` (de
    caller levert die; geen import van main.py om cirkels te
    vermijden). Een NPC met een assigned/queued taak is
    ``working`` — dat is een echt signaal. Een NPC zonder
    signaal blijft/zo wordt ``idle``. Geen enkele andere
    status wordt verzonnen."""
    busy = {}
    for item in tasks or []:
        if not isinstance(item, dict):
            continue
        goal = str(item.get("goal", "") or "")
        owner = str(item.get("node_id", "") or "")
        state = str(item.get("status", "") or "")
        if state not in ("queued", "assigned"):
            continue
        for npc in NPC_ORDER:
            if f"town:{npc}" in goal or f"town-{npc}" in owner:
                busy[npc] = (state, goal[:120])
                break
    out = []
    for npc in NPC_ORDER:
        row = actor(npc)
        if npc in busy:
            state, goal = busy[npc]
            row = set_actor(
                npc,
                x=(row or npc_desk(npc))["x"],
                y=(row or npc_desk(npc))["y"],
                activity="working",
                detail=f"taak {state}: {goal}"[:120],
                status="working", source="queue")
        elif row is not None and row["source"] == "queue":
            row = set_actor(
                npc, x=row["x"], y=row["y"],
                activity="idle", detail="", status="idle",
                source="system")
        out.append(row)
    return [entry if entry is not None
            else _idle_row(npc)
            for entry, npc in zip(out, NPC_ORDER)]
