"""Hermes NPC agents: one real agent per NPC identity.

Mos is the first: a genuine Hermes agent (own session, own
context) instead of a scripted hint list. ``HERMES_NPCS`` is the
extension point for later NPCs — same shape, own session key.

Design (all existing systems, no new engine):

- Identity + session: ``npc-{npc_id}-{play_session_id}`` as the
  ``X-Hermes-Session-Key``. Stable across refresh, unique per
  player session. Hermes converges same-key calls onto one live
  server-side session.
- History: every turn is also stored in the existing
  ``conversations``/``messages`` tables under a deterministic
  ``conv-hermes-<sha>`` id (roles user/agent). No new tables;
  the gateway session stays the live memory, the chat DB is
  the durable audit trail.
- Context: every call prefixes a compact, freshly-read world
  snapshot (position, inventory, builds, clock, missions waiting,
  open research/candidates, INVENTory projects/objects). The
  agent "sees" INVENTory because Mycelium injects it — never
  because the model claims access.
- Screen: only an explicit opt-in text summary from the local
  VLM ever reaches the prompt (``screen_summary`` caller-side).
  Raw pixels never leave the vision layer.
- Actions: the agent NEVER acts directly. It proposes in prose;
  the player executes through existing UI (write proposals +
  exact-YES approvals, candidates, research, quests). Consequen-
  tial actions always need human confirmation first.
- Honesty: TEST/SIMULATED/BLOCKED/UNAVAILABLE states are part
  of the system prompt; the agent must surface them, never
  invent execution.
- No new tables, no scheduler.
"""

from .hermes_bridge import (
    HermesBridge,
    HermesRefusedError,
    HermesUnavailable,
)

HERMES_NPCS = {
    "mos": {
        "name": "Mos",
        "role": "Gids van de Mycelium-wereld",
        "system": (
            "Je bent Mos, gids van de Mycelium-wereld. Je bent een echte "
            "AI-agent (Hermes) met eigen geheugen per speler-sessie, geen "
            "script met hints. Spreek Nederlands, kort (max ~120 woorden), "
            "warm en concreet. Regels: (1) Je voert NOOIT zelf acties uit — "
            "je stelt voor, de speler bevestigt via de bestaande flows "
            "(INVENTory-voorstel + exacte YES-goedkeuring, candidates, "
            "research, quests). (2) Claim nooit dat iets geprint, gebouwd "
            "of uitgevoerd is; toestanden zijn REAL, SIMULATED, PROPOSED, "
            "BLOCKED, UNAVAILABLE of TEST — benoem ze eerlijk. "
            "(3) Feiten komen uit de meegegeven wereldcontext; verzin geen "
            "objecten, statussen of records. (4) Missie 0: help de speler "
            "één echt object uit de fysieke wereld toevoegen aan INVENTory "
            "— vraag naar naam en beschrijving, leg uit dat het voorstel "
            "erna op de Approvals-pagina met exacte YES bevestigd wordt, "
            "en stel daarna een gameplay-koppeling voor (vondst, quest, "
            "research). (5) Geheugen: wat de speler vertelt binnen deze "
            "sessie onthoud je; bij twijfel vraag je door."
        ),
    },
    "oracle": {
        "name": "Orakel",
        "role": "Lezer van Mycelium-advies",
        "system": (
            "Je bent Orakel, lezer van Mycelium-advies. Je bent een echte "
            "AI-agent (Hermes) met eigen geheugen per speler-sessie. "
            "Spreek Nederlands, kort (max ~120 woorden), rustig en beeldend. "
            "Regels: (1) Je voert NOOIT zelf acties uit — je stelt voor, "
            "de speler bevestigt via de bestaande flows (advies, research, "
            "quests, exacte YES). (2) Wat je zegt is richting, nooit feit; "
            "benoem REAL, SIMULATED, PROPOSED, BLOCKED, UNAVAILABLE of TEST "
            "eerlijk. (3) Feiten komen uit de meegegeven wereldcontext; "
            "verzin geen objecten, statussen of records. (4) Wijs bij "
            "onderzoeksvragen naar het Onderzoek-station (queue, run-once, "
            "dossier, plan). (5) Geheugen: wat de speler vertelt binnen "
            "deze sessie onthoud je; bij twijfel vraag je door."
        ),
    },
    "smid": {
        "name": "Smid",
        "role": "Hoeder van de smidse",
        "system": (
            "Je bent Smid, hoeder van de smidse. Je bent een echte AI-agent "
            "(Hermes) met eigen geheugen per speler-sessie. Spreek "
            "Nederlands, kort (max ~120 woorden), praktisch en direct. "
            "Regels: (1) Je voert NOOIT zelf acties uit en start nooit een "
            "fabricage — je leest de echte keten en stelt voor via de "
            "bestaande flows (voorstel, exacte YES, verificatie). (2) Claim "
            "nooit dat iets geprint of gebouwd is; toestanden zijn REAL, "
            "SIMULATED, PROPOSED, BLOCKED, UNAVAILABLE of TEST — benoem ze "
            "eerlijk. (3) Feiten komen uit de meegegeven wereldcontext; "
            "verzin geen modellen, printers of records. (4) Leg uit dat "
            "fysiek printen een tweede fingerprint-gebonden YES plus "
            "hardware en verificatie eist. (5) Geheugen: wat de speler "
            "vertelt binnen deze sessie onthoud je."
        ),
    },
    "archivaris": {
        "name": "Archivaris",
        "role": "Bewaker van kennis en geheugen",
        "system": (
            "Je bent Archivaris, bewaker van kennis en geheugen. Je bent "
            "een echte AI-agent (Hermes) met eigen geheugen per "
            "speler-sessie. Spreek Nederlands, kort (max ~120 woorden), "
            "precies en met herkomst. Regels: (1) Je voert NOOIT zelf "
            "acties uit — je stelt voor via candidates, research en de "
            "Kennis-pagina. (2) Elke bewering krijgt zijn bron erbij; wat "
            "geen bron heeft noem je expliciet onbevestigd. Feit-promotie "
            "eist verified_by — dat beslist de mens, nooit jij. (3) Verzin "
            "geen records, herinneringen of dossiers. (4) Toestanden zijn "
            "REAL, SIMULATED, PROPOSED, BLOCKED, UNAVAILABLE of TEST — "
            "benoem ze eerlijk. (5) Geheugen: wat de speler vertelt binnen "
            "deze sessie onthoud je; bij twijfel vraag je door."
        ),
    },
    "voorman": {
        "name": "Voorman",
        "role": "Planner van werk en missies",
        "system": (
            "Je bent Voorman, planner van werk en missies. Je bent een "
            "echte AI-agent (Hermes) met eigen geheugen per speler-sessie. "
            "Spreek Nederlands, kort (max ~120 woorden), nuchter en "
            "daadkrachtig. Regels: (1) Je voert NOOIT zelf acties uit en "
            "keurt niets goed — je toont wat loopt, wat wacht en wat de "
            "speler nog moet doen; exacte YES blijft vereist. (2) Claim "
            "nooit dat een missie, taak of quest is uitgevoerd; toestanden "
            "zijn REAL, SIMULATED, PROPOSED, BLOCKED, UNAVAILABLE of TEST. "
            "(3) Feiten komen uit de meegegeven wereldcontext; verzin geen "
            "missies, taken of statussen. (4) Wijs naar Missies, Quests en "
            "Approvals voor de echte flows. (5) Geheugen: wat de speler "
            "vertelt binnen deze sessie onthoud je."
        ),
    },
    "seinwachter": {
        "name": "Seinwachter",
        "role": "Luisteraar van nodes en signalen",
        "system": (
            "Je bent Seinwachter, luisteraar van nodes en signalen. Je bent "
            "een echte AI-agent (Hermes) met eigen geheugen per "
            "speler-sessie. Spreek Nederlands, kort (max ~120 woorden), "
            "kalm en feitelijk. Regels: (1) Je voert NOOIT zelf acties uit "
            "en start geen nodes — je leest alleen de echte registry. (2) "
            "Signalen liegen nooit: een node is er of is er niet; benoem "
            "ONLINE, STALE, OFFLINE of DISABLED eerlijk met laatste "
            "heartbeat als je die kent uit de context. (3) Verzin geen "
            "nodes, taken of telemetrie. (4) Leg uit dat nodes pull-only "
            "werken: heartbeat, claim, complete. (5) Geheugen: wat de "
            "speler vertelt binnen deze sessie onthoud je."
        ),
    },
}


def npc_session_key(npc_id: str, play_session_id: str | None) -> str:
    """Stable Hermes session key per NPC + player session."""
    npc = str(npc_id or "").strip()
    if npc not in HERMES_NPCS:
        raise HermesRefusedError(f"Unknown Hermes NPC '{npc}'")
    play = str(play_session_id or "").strip()[:80] or "shared"
    return f"npc-{npc}-{play}"


def hermes_conversation_id(session_key: str) -> str:
    """Deterministic chat-DB conversation per Hermes session key.

    No mapping table: the same session key always resolves to the
    same ``conv-hermes-<sha>`` id, so history survives refresh and
    restart while the gateway session stays the live memory."""
    import hashlib
    digest = hashlib.sha256(
        str(session_key or "").encode("utf-8")).hexdigest()[:16]
    return f"conv-hermes-{digest}"


def _persist_hermes_turn(session_key: str, npc_key: str, npc_name: str,
                         user_text: str, reply_text: str) -> str:
    """Store one turn (user + agent) in conversations/messages.

    Best-effort by design: history must never break a chat turn,
    so every failure degrades to gateway-only memory. Reuses the
    existing tables and validation — no new schema. Returns the
    conversation id (stable per session key, even on failure)."""
    conversation_id = hermes_conversation_id(session_key)
    try:
        import datetime

        from .conversations import MAX_CONTENT_CHARS, new_message
        from .database import (
            chat_connection,
            dump,
            init_chat_database,
        )
        created = datetime.datetime.now(
            datetime.timezone.utc).isoformat()
        # Creator marks the Hermes origin; role agent can never
        # claim human verification (enforced by new_message).
        from .conversations import default_provenance_for
        user_message = new_message(
            conversation_id, "user", str(user_text or "")[:MAX_CONTENT_CHARS],
            provenance=default_provenance_for("user", f"hermes-{npc_key}"))
        agent_message = new_message(
            conversation_id, "agent",
            str(reply_text or "")[:MAX_CONTENT_CHARS],
            provenance=default_provenance_for("agent", f"hermes-{npc_key}"))
        init_chat_database()
        with chat_connection() as db:
            db.execute(
                """INSERT INTO conversations
                (conversation_id, title, project_ref, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO NOTHING""",
                (conversation_id,
                 f"{npc_name} · {str(session_key or '')[:40]}"[:120],
                 "", created))
            for stored in (user_message, agent_message):
                db.execute(
                    """INSERT INTO messages
                    (message_id, conversation_id, role, content,
                     created_at, provenance, sources)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (stored.message_id, conversation_id, stored.role,
                     stored.content, created,
                     dump(stored.provenance.model_dump(mode="json")),
                     dump([])))
    except Exception:
        pass
    return conversation_id


def hermes_history(session_key: str, limit: int = 50) -> list[dict]:
    """Durable turns for one Hermes session, oldest first. Never raises."""
    try:
        from .database import chat_connection, init_chat_database
        conversation_id = hermes_conversation_id(session_key)
        init_chat_database()
        with chat_connection() as db:
            rows = db.execute(
                """SELECT role, content, created_at FROM messages
                WHERE conversation_id=? ORDER BY created_at ASC LIMIT ?""",
                (conversation_id, max(1, min(int(limit or 50), 50)))
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []


def _inventory_objects_sample() -> str:
    """Echte obj_-records (max 5) via GET-only loopback. Dezelfde
    grenzen als de bestaande bridge; nooit een uitzondering, nooit
    verzonnen objecten."""
    try:
        import os

        import httpx

        from .inventory_read import _validate_base_url as _check_url
        base = _check_url(os.environ.get(
            "INVENTORY_BASE_URL", "http://127.0.0.1:8080"))
        with httpx.Client(timeout=5.0,
                          follow_redirects=False) as client:
            response = client.get(f"{base}/api/v1/objects")
        if response.status_code != 200:
            return ""
        data = response.json()
        if not isinstance(data, list):
            return ""
        items = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            oid = str(entry.get("id", ""))
            if not oid.startswith("obj_"):
                continue
            items.append(f"{entry.get('name', oid)} ({oid})")
            if len(items) >= 5:
                break
        if not items:
            return "INVENTory-objecten: geen (lege wereld)."
        return "INVENTory-objecten: " + "; ".join(items) + "."
    except Exception:
        return ""


def build_npc_context(play_session_id: str | None = None) -> str:
    """Compact world snapshot for the agent. Never raises: every
    section is best-effort so one offline backend never breaks
    the chat."""
    lines = []
    sid = str(play_session_id or "").strip()
    if sid:
        try:
            from .play_workshop import get_play_inventory
            inv = get_play_inventory(sid)
            items = inv.get("items", {}) or {}
            have = ", ".join(f"{item}x{qty}"
                             for item, qty in sorted(items.items())
                             if qty) or "leeg"
            lines.append(f"Speler-voorraad: {have}.")
            builds = inv.get("builds", []) or []
            kinds = {}
            for build in builds:
                kind = str(build.get("kind", "?"))
                kinds[kind] = kinds.get(kind, 0) + 1
            made = ", ".join(f"{kind}x{num}"
                             for kind, num in sorted(kinds.items()))
            lines.append(f"Gebouwd: {made or 'nog niets'}.")
        except Exception:
            lines.append("Speler-voorraad: onleesbaar.")
        try:
            from .play_workshop import get_play_flags
            flags = get_play_flags(sid).get("flags", []) or []
            lines.append(f"Wereld-voortgang: {', '.join(flags) or 'start'}.")
        except Exception:
            pass
    try:
        from .play_workshop import play_journal
        journal = play_journal()
        counts = journal.get("counts", {}) or {}
        lines.append(
            "Mycelium: "
            f"{counts.get('missions_active', 0)} actieve missies, "
            f"{counts.get('missions_waiting', 0)} wachtend op YES, "
            f"{counts.get('research_open', 0)} open onderzoeken, "
            f"{counts.get('candidates_open', 0)} open vondsten, "
            f"{counts.get('projects_open', 0)} INVENTory-projecten, "
            f"{counts.get('memories_remembered', 0)} herinneringen."
        )
        projects = [p.get("title", "?")
                    for p in (journal.get("projects", []) or [])[:5]]
        if projects:
            lines.append("INVENTory-projecten: " + "; ".join(projects) + ".")
        state = (journal.get("inventory", {}) or {}).get("state", "")
        if state and state != "ok":
            lines.append(f"INVENTory-backend: {state} (eerlijk, niets verzonnen).")
    except Exception:
        lines.append("Mycelium-overzicht: onleesbaar.")
    sample = _inventory_objects_sample()
    if sample:
        lines.append(sample)
    lines.append(_observations_sample())
    screen = _screen_state_sample()
    if screen:
        lines.append(screen)
    return "\n".join(line for line in lines if line)


def _screen_state_sample() -> str:
    """Latest screen observation as READ context: monitor/node/
    screenshot reference/timestamp. Reading only — the agent can
    never act on the screen through this context. Never raises."""
    try:
        from .world_observations import list_observations
        rows = list_observations(limit=20) or []
    except Exception:
        return ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("source", "")) != "screen":
            continue
        provenance = row.get("provenance", {}) or {}
        detail = ""
        if isinstance(provenance, dict):
            detail = str(provenance.get("window", "")
                         or provenance.get("monitor", "") or "")[:80]
        return ("Schermstatus (alleen lezen, nooit handelen): "
                f"node {row.get('node_id', '?')}, "
                f"screenshot {row.get('media_ref', '?') or 'geen'}, "
                f"{row.get('created_at', '?')}"
                + (f", {detail}" if detail else "") + ".")
    return ""


def _observations_sample() -> str:
    """Recent world observations (max 5) as READ context. Many
    rows may share one entity_ref — that is converging evidence,
    never ownership. Never raises."""
    try:
        from .world_observations import list_observations
        rows = list_observations(limit=5) or []
    except Exception:
        return ""
    if not rows:
        return ""
    parts = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = str(row.get("entity_ref", "") or "onbekend")
        parts.append(
            f"{entity} via {row.get('node_id', '?')}/"
            f"{row.get('source', '?')} "
            f"(zekerheid {row.get('confidence', '?')})"
        )
    if not parts:
        return ""
    return ("Waarnemingen (alleen lezen, geen eigendom): "
            + "; ".join(parts) + ".")


def npc_chat(npc_id: str, message: str,
             play_session_id: str | None = None,
             max_tokens: int = 500,
             screen_summary: str | None = None) -> dict:
    """One chat turn with a Hermes NPC. Returns the bridge result
    plus ``npc_id``, ``npc_name`` and the durable ``conversation_id``.

    ``screen_summary`` is caller-provided VLM text (opt-in only);
    raw pixels never reach this function. The turn is stored in
    conversations/messages best-effort — storage failure never
    breaks the reply."""
    npc_key = str(npc_id or "").strip()
    if npc_key not in HERMES_NPCS:
        raise HermesRefusedError(f"Unknown Hermes NPC '{npc_key}'")
    text = str(message or "")
    if not text.strip():
        raise HermesRefusedError("Message must be non-empty text")
    if len(text) > 2000:
        raise HermesRefusedError("Message exceeds 2000 characters")
    npc = HERMES_NPCS[npc_key]
    session_key = npc_session_key(npc_key, play_session_id)
    context = build_npc_context(play_session_id)
    extra = str(screen_summary or "").strip()[:1000]
    if extra:
        context = (context + "\n" + extra) if context else extra
    prompt = (
        f"[Systeem: {npc['system']}]\n"
        f"[Wereldcontext, zojuist gelezen:\n{context}]\n"
        f"[Speler zegt:]\n{text.strip()}"
    )
    bridge = HermesBridge()
    try:
        count = max(1, min(int(max_tokens or 500), 2000))
    except (TypeError, ValueError):
        raise HermesRefusedError("max_tokens must be an integer")
    try:
        out = bridge.send(session_key, prompt,
                          max_tokens=count)
    except HermesRefusedError:
        raise
    except HermesUnavailable:
        raise
    out["npc_id"] = npc_key
    out["npc_name"] = npc["name"]
    reply = str(out.get("text", "") or "")
    out["conversation_id"] = _persist_hermes_turn(
        session_key, npc_key, npc["name"], text.strip(), reply)
    return out
