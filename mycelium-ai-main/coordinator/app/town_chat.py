"""Town gesprekken (fase 3): gedeelde conversatielaag mens + NPC's.

Hergebruikt de bestaande chat-tabellen ``conversations``/``messages``
(geen nieuwe tabellen, zelfde validatie als Hermes-turns). Round-robin:
na elk mensbericht reageert hooguit één NPC (vaste beurtvolgorde, geen
lussen). NPC-antwoorden lopen via ``npc_chat``; zonder bereikbaar model
komt er een eerlijke system-noot — nooit stilte, nooit verzinsel.

Rollen in town-verband: ``human`` (jij), ``npc:<id>`` (bewoner),
``system`` (engine-mededelingen, nooit een persoon).
"""

import datetime
import secrets

TOWN_TITLE_PREFIX = "town:"
MAX_TEXT_CHARS = 2000
MAX_PARTICIPANTS = 8

NPC_ORDER = ("mos", "oracle", "smid", "archivaris", "voorman",
             "seinwachter")


class TownRefusedError(ValueError):
    """Validatie geweigerd; niets opgeslagen."""


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _check_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise TownRefusedError("Message must be non-empty text")
    if len(cleaned) > MAX_TEXT_CHARS:
        raise TownRefusedError(
            f"Message exceeds {MAX_TEXT_CHARS} characters")
    return cleaned


def _check_participants(participants) -> list:
    if not isinstance(participants, (list, tuple)) or not participants:
        raise TownRefusedError("Need at least one participant")
    cleaned = []
    for entry in participants:
        name = str(entry or "").strip()[:80]
        if not name or name in cleaned:
            continue
        cleaned.append(name)
    if not cleaned:
        raise TownRefusedError("Need at least one participant")
    if len(cleaned) > MAX_PARTICIPANTS:
        raise TownRefusedError(
            f"At most {MAX_PARTICIPANTS} participants")
    return cleaned


def open_town_conversation(title: str = "",
                           participants=None) -> dict:
    """Open een stadsgesprek. Geeft {conversation_id, title,
    participants, created} terug."""
    from .database import chat_connection, init_chat_database
    people = _check_participants(
        participants if participants is not None else ["you"])
    name = str(title or "").strip()[:120] or "Town square"
    conversation_id = f"town_{secrets.token_hex(8)}"
    created = _utc_now()
    init_chat_database()
    with chat_connection() as db:
        db.execute(
            """INSERT INTO conversations
            (conversation_id, title, project_ref, created_at)
            VALUES (?, ?, ?, ?)""",
            (conversation_id, f"{TOWN_TITLE_PREFIX} {name}",
             "solarpunk", created))
    return {"conversation_id": conversation_id, "title": name,
            "participants": people, "created": created[:19]}


def list_town_messages(conversation_id: str, limit: int = 50) -> list:
    """Laatste berichten, oudste eerst. Onbekend gesprek -> KeyError.

    Tabelrollen (user/agent/system) worden terugvertaald naar
    town-rollen via de opgeslagen ``town_role``-source."""
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    with chat_connection() as db:
        row = db.execute(
            "SELECT conversation_id FROM conversations WHERE "
            "conversation_id=?", (str(conversation_id),)).fetchone()
        if row is None:
            raise KeyError(f"Unknown conversation '{conversation_id}'")
        rows = db.execute(
            """SELECT role, content, created_at, sources FROM messages
            WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?""",
            (str(conversation_id), max(1, min(int(limit or 50), 200)))
            ).fetchall()
    out = []
    for item in reversed(rows):
        try:
            sources = load(item["sources"]) or []
        except Exception:
            sources = []
        town_role = ""
        for entry in sources:
            if isinstance(entry, dict) and entry.get("town_role"):
                town_role = str(entry["town_role"])
                break
        if not town_role:
            town_role = {"user": "human", "agent": "npc:?",
                         "system": "system"}.get(
                str(item["role"]), str(item["role"]))
        out.append({"role": town_role,
                    "content": str(item["content"]),
                    "created": str(item["created_at"] or "")[:19]})
    return out


def post_town_message(conversation_id: str, speaker: str,
                      role: str, text: str,
                      npc_id: str = "") -> dict:
    """Bewaar één bericht + hooguit één NPC-beurt.

    role: "human" (jij) of "npc:<id>" (bewoner schrijft
    zelf nooit; NPC-tekst via hun beurt). Na een
    mensbericht reageert de opgegeven NPC (loop-naar-
    toe-praten) of, zonder keus, de eerstvolgende NPC
    uit NPC_ORDER (round-robin). Zonder model een
    system-noot. Geeft {message, npc_turn} terug
    (npc_turn None als geen beurt).
    """
    from .conversations import (
        MAX_CONTENT_CHARS,
        default_provenance_for,
        new_message,
    )
    from .database import chat_connection, dump, init_chat_database
    cleaned = _check_text(text)
    who = str(speaker or "").strip()[:80] or "you"
    if role not in ("human", "system") and not role.startswith("npc:"):
        raise TownRefusedError(
            "role must be human, npc:<id> or system")
    init_chat_database()
    with chat_connection() as db:
        row = db.execute(
            "SELECT conversation_id FROM conversations WHERE "
            "conversation_id=?", (str(conversation_id),)).fetchone()
        if row is None:
            raise KeyError(f"Unknown conversation '{conversation_id}'")
    created = _utc_now()
    table_role = {"human": "user", "system": "system"}.get(role, "agent")
    stored = new_message(
        str(conversation_id), table_role,
        cleaned[:MAX_CONTENT_CHARS],
        provenance=default_provenance_for(
            "user" if role == "human" else "agent",
            f"town-{who}"),
        sources=[{"town_role": role}])
    with chat_connection() as db:
        db.execute(
            """INSERT INTO messages
            (message_id, conversation_id, role, content,
             created_at, provenance, sources)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (stored.message_id, str(conversation_id), stored.role,
             stored.content, created,
             dump(stored.provenance.model_dump(mode="json")),
             dump([{"town_role": role}])))
    npc_turn = None
    if role == "human":
        npc_turn = _npc_round_robin(
            str(conversation_id), cleaned, npc_id=npc_id)
    try:
        from .town_memory import record_memory
        record_memory(f"town:{who}", f"{who}: {cleaned}", 0.5,
                      kind="chat")
    except Exception:
        pass
    return {"message": {"role": role, "content": stored.content,
                        "created": created[:19]},
            "npc_turn": npc_turn}


def _npc_round_robin(conversation_id: str, human_text: str,
                     npc_id: str = "") -> dict | None:
    """Gekozen NPC (loop-naar-toe) of de eerstvolgende
    uit NPC_ORDER. Eén beurt max."""
    target = str(npc_id or "").strip()
    if target in NPC_ORDER:
        return _npc_says(conversation_id, target, human_text)
    history = list_town_messages(conversation_id, limit=20)
    spoken = [item["role"] for item in history
              if item["role"].startswith("npc:")]
    last_npc = spoken[-1][4:] if spoken else None
    if last_npc in NPC_ORDER:
        nxt = NPC_ORDER[(NPC_ORDER.index(last_npc) + 1) % len(NPC_ORDER)]
    else:
        nxt = NPC_ORDER[0]
    return _npc_says(conversation_id, nxt, human_text)


def _npc_says(conversation_id: str, npc_id: str,
              human_text: str) -> dict:
    """Eén NPC-beurt: Hermes, dan Ollama, dan een eerlijke noot."""
    from .conversations import (
        MAX_CONTENT_CHARS,
        default_provenance_for,
        new_message,
    )
    from .database import chat_connection, dump, init_chat_database
    try:
        from .hermes_npc import HERMES_NPCS, npc_chat
        if npc_id not in HERMES_NPCS:
            raise TownRefusedError(f"Unknown NPC '{npc_id}'")
        out = npc_chat(npc_id, human_text)
        reply = str(out.get("text", "") or "").strip()
        if not reply:
            raise TownRefusedError("Empty NPC reply")
        role, creator = f"npc:{npc_id}", f"town-{npc_id}"
    except Exception:
        try:
            from .ollama_chat import ollama_say
            reply = ollama_say(npc_id, human_text)
            role, creator = f"npc:{npc_id}", f"town-ollama-{npc_id}"
        except Exception as error:
            reply = (f"… ({npc_id} is stil: "
                     f"{str(error)[:120] or 'geen model bereikbaar'})")
            role, creator = "system", "town-engine"
    created = _utc_now()
    table_role, town_role = ("agent", f"npc:{npc_id}") if role.startswith(
        "npc:") else ("system", "system")
    stored = new_message(
        conversation_id, table_role, reply[:MAX_CONTENT_CHARS],
        provenance=default_provenance_for("agent", creator),
        sources=[{"town_role": town_role}])
    with chat_connection() as db:
        db.execute(
            """INSERT INTO messages
            (message_id, conversation_id, role, content,
             created_at, provenance, sources)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (stored.message_id, conversation_id, stored.role,
             stored.content, created,
             dump(stored.provenance.model_dump(mode="json")),
             dump([{"town_role": town_role}])))
    try:
        from .town_memory import record_memory
        record_memory(f"npc:{npc_id}", f"{npc_id}: {reply}", 0.6,
                      kind="chat")
    except Exception:
        pass
    return {"role": town_role, "content": stored.content,
            "created": created[:19]}
