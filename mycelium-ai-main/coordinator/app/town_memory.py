"""Town geheugen (fase 4): Smallville-patroon in het klein —
observeren -> onthouden -> ophalen -> reflecteren.

Eén additieve tabel ``town_memories`` in de bestaande chat-DB (zelfde
eigendom als conversations/messages, geen tweede database). Recall
sorteert op belang en daarna recency; embedding-relevantie volgt
later. Reflecteren heeft een model nodig en weigert eerlijk (409)
zolang er geen bereikbaar is — nooit een nep-reflectie.
"""

import datetime
import secrets

MAX_TEXT_CHARS = 2000
VALID_KINDS = frozenset({"note", "chat", "reflection", "observation"})


class TownRefusedError(ValueError):
    """Validatie geweigerd of reflectie onmogelijk; niets opgeslagen."""


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def ensure_tables() -> None:
    """Additieve init; veilig om bij elke call te draaien."""
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""
        CREATE TABLE IF NOT EXISTS town_memories (
            memory_id TEXT PRIMARY KEY,
            agent TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'note',
            text TEXT NOT NULL,
            importance REAL NOT NULL DEFAULT 0.5,
            created_at TEXT NOT NULL
        )""")
        db.execute("""CREATE INDEX IF NOT EXISTS idx_town_memories_agent
            ON town_memories(agent, importance DESC, created_at DESC)""")


def record_memory(agent: str, text: str, importance: float = 0.5,
                  kind: str = "note") -> dict:
    """Bewaar één herinnering. Geeft {memory_id, agent, created} terug."""
    who = str(agent or "").strip()[:80]
    if not who:
        raise TownRefusedError("agent must be non-empty text")
    cleaned = str(text or "").strip()
    if not cleaned:
        raise TownRefusedError("memory text must be non-empty")
    if len(cleaned) > MAX_TEXT_CHARS:
        raise TownRefusedError(
            f"memory text exceeds {MAX_TEXT_CHARS} characters")
    if kind not in VALID_KINDS:
        raise TownRefusedError(
            f"unknown memory kind '{kind}'")
    try:
        weight = max(0.0, min(float(importance), 1.0))
    except (TypeError, ValueError):
        raise TownRefusedError("importance must be a number 0..1")
    memory_id = f"mem_{secrets.token_hex(8)}"
    created = _utc_now()
    ensure_tables()
    from .database import chat_connection
    with chat_connection() as db:
        db.execute(
            """INSERT INTO town_memories
            (memory_id, agent, kind, text, importance, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (memory_id, who, kind, cleaned, weight, created))
    return {"memory_id": memory_id, "agent": who,
            "created": created[:19]}


def recall_memories(agent: str, limit: int = 10) -> list:
    """Belangrijkste herinneringen eerst, recency als tiebreak."""
    ensure_tables()
    from .database import chat_connection
    with chat_connection() as db:
        rows = db.execute(
            """SELECT kind, text, importance, created_at
            FROM town_memories WHERE agent=?
            ORDER BY importance DESC, created_at DESC LIMIT ?""",
            (str(agent or "").strip()[:80],
             max(1, min(int(limit or 10), 100)))).fetchall()
    return [{"kind": str(item["kind"]), "text": str(item["text"]),
             "importance": float(item["importance"]),
             "created": str(item["created_at"] or "")[:19]}
            for item in rows]


def reflect(agent: str, limit: int = 10) -> dict:
    """Vat herinneringen samen tot een reflectie (bewaard als memory).

    Heeft een bereikbaar taalmodel nodig. Dat is er nu niet (geen
    Ollama, geen Hermes-key) — dus eerlijk weigeren met 409 in de
    route. Zodra een model bereikbaar is, landt de synthese-aanroep
    hier, met de recall hierboven als context.
    """
    _ = (limit, recall_memories(str(agent or "").strip()[:80], 10))
    raise TownRefusedError(
        "reflection needs a reachable language model; none is "
        "configured (no Ollama, no Hermes key)")
