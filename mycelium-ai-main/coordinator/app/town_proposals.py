"""Town delegatie (fase 5b) + autonomie-dial (fase 5c).

Een NPC stelt werk voor in woorden (Hermes → Ollama, zelfde
keten als chat); het voorstel wordt een opgeslagen record met
de vier velden van het approval-queue-pattern (actie,
rechtvaardiging, blast radius, confidence). Pas na expliciete
beslissing — letterlijk ``YES``, al het andere is afwijzen —
wordt er één queue-taak aangemaakt (zelfde rij-vorm als
queue_play_task: status queued, nooit toewijzen, nooit
uitvoeren). Nodes pullen; de coordinator pusht nooit.

Autonomie (5c) is een dial, geen schakelaar:
``TOWN_AUTONOMY="voorman:research.fetch_url,smid:system_inventory"``.
Alleen kinds uit NPC_AUTONOMOUS_KINDS (de drie al
auto-executable kinds) mogen op de lijst; hardware,
desktop-invoer en alles buiten de lijst weigeren bij het
lezen. Default is de lege lijst: niets autonoom. Elke
auto-beslissing wordt gelogd als audit-regel, zodat "wie
heeft wat goedgekeurd" altijd een volledig antwoord heeft.
"""

import datetime
import json
import re
import secrets

#: Queue-kinds die een NPC mag voorstellen. Geen hardware,
#: geen desktop-invoer, geen fabricage — alleen lezen en
#: onderzoek dat op elke node met de juiste capability kan
#: draaien.
NPC_PROPOSABLE_KINDS = frozenset({
    "research.fetch_url",
    "system_inventory",
    "research",
    "analysis",
})

#: Kinds die ooit autonoom mogen draaien (de drie al
#: auto-executable kinds). Alles buiten deze set wordt
#: bij het lezen van TOWN_AUTONOMY geweigerd.
NPC_AUTONOMOUS_KINDS = frozenset({
    "research.fetch_url",
    "system_inventory",
    "desktop_screenshot",
})

AUTONOMY_ENV_VAR = "TOWN_AUTONOMY"

PROPOSAL_STATUSES = ("proposed", "approved",
                     "rejected", "auto-queued")

NPC_IDS = ("mos", "oracle", "smid", "archivaris",
           "voorman", "seinwachter")


class ProposalRefusedError(ValueError):
    """Validatie geweigerd; niets opgeslagen."""


def _utc_now() -> str:
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def ensure_tables() -> None:
    """Additieve tabel; idempotent, nooit destructief."""
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS town_proposals (
                proposal_id TEXT PRIMARY KEY,
                npc_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                goal TEXT NOT NULL,
                justification TEXT NOT NULL,
                blast_radius TEXT NOT NULL,
                confidence REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed',
                decided_by TEXT NOT NULL DEFAULT '',
                decided_at TEXT NOT NULL DEFAULT '',
                queue_task_id INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )""")


def _check_npc(npc_id: str) -> str:
    npc = str(npc_id or "").strip()
    if npc not in NPC_IDS:
        raise ProposalRefusedError(f"Unknown NPC '{npc}'")
    return npc


def _check_kind(kind: str) -> str:
    clean = str(kind or "").strip()
    if clean not in NPC_PROPOSABLE_KINDS:
        raise ProposalRefusedError(
            f"kind must be one of "
            f"{', '.join(sorted(NPC_PROPOSABLE_KINDS))}")
    return clean


def _check_bounded(value: str, name: str,
                   max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    if not cleaned:
        raise ProposalRefusedError(
            f"{name} must be non-empty text")
    if len(cleaned) > max_chars:
        raise ProposalRefusedError(
            f"{name} exceeds {max_chars} characters")
    return cleaned


def autonomy_rules() -> dict:
    """Lees TOWN_AUTONOMY. Geeft {npc: [kinds]}; alles
    buiten NPC_AUTONOMOUS_KINDS wordt stilzwijgend
    overgeslagen — een regel die niet mag, telt niet."""
    import os as _os
    raw = str(_os.environ.get(
        AUTONOMY_ENV_VAR, "") or "")
    out: dict[str, list[str]] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" not in entry:
            continue
        npc, kind = (part.strip()
                     for part in entry.split(":", 1))
        if npc not in NPC_IDS:
            continue
        if kind not in NPC_AUTONOMOUS_KINDS:
            continue
        out.setdefault(npc, [])
        if kind not in out[npc]:
            out[npc].append(kind)
    return out


def is_autonomous(npc_id: str, kind: str) -> bool:
    """Mag deze NPC dit kind zonder YES queue'n?"""
    return str(kind or "") in autonomy_rules().get(
        str(npc_id or ""), [])


def propose_task(npc_id: str, kind: str, goal: str,
                 justification: str, blast_radius: str,
                 confidence: float) -> dict:
    """Bewaar één voorstel (status proposed — of auto-queued
    als de dial dat toestaat). Voert niets uit; queue'n
    gebeurt pas bij YES (of bij een geldige autonomie-regel).
    """
    npc = _check_npc(npc_id)
    clean_kind = _check_kind(kind)
    clean_goal = _check_bounded(goal, "goal", 300)
    clean_why = _check_bounded(
        justification, "justification", 300)
    clean_blast = _check_bounded(
        blast_radius, "blast_radius", 200)
    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        raise ProposalRefusedError(
            "confidence must be a number")
    if not 0.0 <= conf <= 1.0:
        raise ProposalRefusedError(
            "confidence must be between 0 and 1")
    ensure_tables()
    proposal_id = f"tprop-{secrets.token_hex(6)}"
    created = _utc_now()
    auto = is_autonomous(npc, clean_kind)
    status = "auto-queued" if auto else "proposed"
    decided_by = ("standing-rule:TOWN_AUTONOMY"
                  if auto else "")
    queue_task_id = 0
    if auto:
        queue_task_id = queue_town_task(
            clean_kind, clean_goal, npc)["id"]
    from .database import chat_connection
    with chat_connection() as db:
        db.execute(
            """INSERT INTO town_proposals
            (proposal_id, npc_id, kind, goal, justification,
             blast_radius, confidence, status, decided_by,
             decided_at, queue_task_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (proposal_id, npc, clean_kind, clean_goal,
             clean_why, clean_blast, conf, status,
             decided_by,
             created if auto else "", queue_task_id,
             created))
    try:
        from .town_actors import record_activity
        what = (f"stelt voor: {clean_goal}"
                if not auto else
                f"autonoom gequeued: {clean_goal}")
        record_activity(npc, "proposal", what)
    except Exception:
        pass
    return get_proposal(proposal_id)


def get_proposal(proposal_id: str) -> dict:
    """Één voorstel of KeyError."""
    pid = str(proposal_id or "").strip()
    if not pid:
        raise KeyError("empty proposal id")
    try:
        from .database import chat_connection, init_chat_database
        init_chat_database()
        with chat_connection() as db:
            row = db.execute(
                """SELECT proposal_id, npc_id, kind, goal,
                   justification, blast_radius, confidence,
                   status, decided_by, decided_at,
                   queue_task_id, created_at
                   FROM town_proposals WHERE proposal_id=?""",
                (pid,)).fetchone()
    except Exception:
        raise KeyError(f"Unknown proposal '{pid}'")
    if row is None:
        raise KeyError(f"Unknown proposal '{pid}'")
    return dict(row)


def list_proposals(limit: int = 50) -> list:
    """Voorstellen, nieuwste eerst. Leest nooit fouten."""
    try:
        from .database import chat_connection, init_chat_database
        init_chat_database()
        with chat_connection() as db:
            rows = db.execute(
                """SELECT proposal_id, npc_id, kind, goal,
                   justification, blast_radius, confidence,
                   status, decided_by, decided_at,
                   queue_task_id, created_at
                   FROM town_proposals ORDER BY created_at DESC
                   LIMIT ?""",
                (max(1, min(int(limit or 50), 100)),
                 )).fetchall()
    except Exception:
        return []
    return [dict(row) for row in rows]


def decide_proposal(proposal_id: str, decision: str,
                    decided_by: str = "you") -> dict:
    """Exact-YES: alleen letterlijk ``YES`` keurt goed en
    queued één taak. Al het andere (ja, ok, YES!, leeg)
    is afwijzen. Een beslist voorstel beslist nooit opnieuw
    (409-semantiek via ProposalRefusedError)."""
    current = get_proposal(proposal_id)
    if current["status"] in ("approved", "rejected",
                             "auto-queued", "queued"):
        raise ProposalRefusedError(
            f"proposal is already {current['status']}")
    who = re.sub(r"\s+", " ",
                 str(decided_by or "")).strip()[:40] or "you"
    if str(decision or "") == "YES":
        queued = queue_town_task(
            current["kind"], current["goal"],
            current["npc_id"])
        status, task_id = "approved", queued["id"]
    else:
        status, task_id = "rejected", 0
    stamped = _utc_now()
    from .database import chat_connection
    with chat_connection() as db:
        db.execute(
            """UPDATE town_proposals SET status=?,
               decided_by=?, decided_at=?, queue_task_id=?
               WHERE proposal_id=?""",
            (status, who, stamped, task_id,
             current["proposal_id"]))
    try:
        from .town_actors import record_activity
        record_activity(
            current["npc_id"], "decision",
            f"{who} besliste {status}: "
            f"{current['goal'][:80]}")
    except Exception:
        pass
    return get_proposal(proposal_id)


def queue_town_task(kind: str, goal: str,
                    npc_id: str) -> dict:
    """Eén queue-taak voor een goedgekeurd voorstel.

    Zelfde rij-vorm als queue_play_task (status queued,
    routing gevalideerd, provenance town:{npc}). Nooit
    toewijzen, nooit uitvoeren — nodes pullen."""
    from .database import connection, dump
    from .routing import check_requirements
    npc = _check_npc(npc_id)
    clean_kind = _check_kind(kind)
    clean_goal = _check_bounded(goal, "goal", 300)
    requirements = check_requirements(
        {"required_capabilities": [clean_kind]})
    payload = {"goal": clean_goal, "origin": "town",
               "actor": f"town-{npc}",
               "town_proposal": "see town_proposals"}
    with connection() as db:
        cursor = db.execute(
            """INSERT INTO tasks (kind,payload,
            required_capabilities,preferred_tier,priority,
            status,created_at,routing,mission_id)
            VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
            (clean_kind, dump(payload), dump([clean_kind]),
             None, 0, _utc_now(),
             dump(requirements.model_dump(mode="json")),
             None))
        task_id = cursor.lastrowid
    return {"id": task_id, "status": "queued",
            "kind": clean_kind}


def _draft_text(npc_id: str, request_text: str) -> str:
    """Eén model-beurt voor het voorstel: Hermes eerst,
    Ollama daarna. Zonder model geen voorstel."""
    from .hermes_npc import HERMES_NPCS
    if npc_id not in HERMES_NPCS:
        raise ProposalRefusedError(
            f"Unknown NPC '{npc_id}'")
    kinds = ", ".join(sorted(NPC_PROPOSABLE_KINDS))
    prompt = (
        "[Systeem: stel werk voor. Antwoord met ALLEEN "
        "één ```json blok, geen andere tekst. Vorm: "
        '{"kind": "...", "goal": "...", "justification": '
        '"...", "blast_radius": "...", "confidence": 0.0-1.0}. '
        f"kind moet exact een van zijn: {kinds}. goal: wat "
        "de taak moet opleveren (max 300 tekens). "
        "justification: waarom nu (max 300 tekens). "
        "blast_radius: wat het raakt en hoe omkeerbaar "
        "(max 200 tekens). confidence: 0-1.]\n"
        f"[Werkverzoek:]\n{request_text.strip()[:500]}")
    try:
        from .hermes_npc import npc_chat
        out = npc_chat(npc_id, prompt)
        text = str(out.get("text", "") or "").strip()
        if text:
            return text
        raise ProposalRefusedError("Empty NPC reply")
    except Exception:
        pass
    try:
        from .ollama_chat import ollama_say
        return ollama_say(npc_id, prompt)
    except Exception as error:
        raise ProposalRefusedError(
            f"No model reachable for drafting "
            f"({str(error)[:80]})")


def extract_proposal_spec(text: str) -> dict:
    """Eén ```json blok → spec-dict, strikt gevalideerd.
    Vormfout, ontbrekende velden of oversized tekst maken
    het hele voorstel ongeldig — nooit raden, nooit
    aanvullen (zelfde filosofie als advisor_proposals)."""
    match = re.search(r"```json\s*(\{.*?\})\s*```",
                      str(text or ""), re.S)
    if not match:
        raise ProposalRefusedError(
            "No ```json block in the draft")
    try:
        spec = json.loads(match.group(1))
    except Exception:
        raise ProposalRefusedError(
            "Draft JSON block is not valid JSON")
    if not isinstance(spec, dict):
        raise ProposalRefusedError(
            "Draft JSON block must be an object")
    return {
        "kind": _check_kind(spec.get("kind")),
        "goal": _check_bounded(
            spec.get("goal"), "goal", 300),
        "justification": _check_bounded(
            spec.get("justification"), "justification",
            300),
        "blast_radius": _check_bounded(
            spec.get("blast_radius"), "blast_radius",
            200),
        "confidence": _confidence(spec.get("confidence")),
    }


def _confidence(value) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        raise ProposalRefusedError(
            "confidence must be a number")
    if not 0.0 <= conf <= 1.0:
        raise ProposalRefusedError(
            "confidence must be between 0 and 1")
    return conf


def draft_proposal(npc_id: str,
                   request_text: str) -> dict:
    """NPC stelt voor in woorden → opgeslagen voorstel.

    request ≤ 500 tekens, NPC uit de cast, spec strikt
    gevalideerd. Geen model → geweigerd (409), geen
    nep-voorstel."""
    npc = _check_npc(npc_id)
    request = _check_bounded(request_text, "request", 500)
    spec = extract_proposal_spec(_draft_text(npc, request))
    return propose_task(npc, spec["kind"], spec["goal"],
                        spec["justification"],
                        spec["blast_radius"],
                        spec["confidence"])
