"""Conversation intelligence (BIG #37): traces of thought.

Turns imported conversations into structured, reviewable
intelligence WITHOUT a second import system: everything reads
the existing bridge (imports, messages, deterministic analysis)
and writes only through existing flows (knowledge candidates,
research queue drafts, connection candidates, IN_APP
notifications, bus events).

Pipeline: IMPORT → NORMALIZE → SEGMENT → THEMES → DECISIONS
→ PROMISES → QUESTIONS → CONTRADICTIONS → MISSED → RESEARCH
→ ENTITY LINKS → SYMBIOSIS → HUMAN REVIEW → ECOSYSTEM.

Rules (fail-closed, tested):

- Analysis is deterministic and extractive (method
  `extractive-local`, no LLM involved). Output is
  OBSERVATION or CANDIDATE — never fact, never auto-promoted.
- Health-flagged text never becomes a candidate (same
  `_HEALTH_RE` screen the knowledge flow uses).
- Imported content is untrusted: findings are escaped data at
  render; nothing imported can approve, execute, verify, or
  change truth tiers. Secrets were redacted at import.
- Cross-conversation dedupe by sha256 fingerprint: the same
  statement never becomes two candidates.
- Materialize actions are explicit and idempotent: candidate
  (knowledge flow), research-queue (draft run), link
  (connection candidate). Research execution still needs its
  own mission YES.
- Promises never claim completion without mission/event
  evidence; status stays UNKNOWN otherwise.
- Contradictions never pick a winner; status UNRESOLVED
  until a human resolves via the knowledge flow.
- Bounded everywhere: messages, findings, themes, items.
"""

from __future__ import annotations

import hashlib as _hashlib
import re as _re
import secrets as _secrets

METHOD = "extractive-local"
ANALYSIS_STATE = "REAL"

INTEL_KINDS = (
    "theme",
    "decision",
    "promise",
    "contradiction",
    "missed",
    "research_proposal",
    "entity_link",
    "symbiosis",
)

INTEL_STATE = {"theme": "OBSERVATION"}

PROMISE_RE = _re.compile(
    r"(?i)\b(ik zal|ik ga|we zullen|we gaan|i['’]ll|we['’]ll|"
    r"tomorrow i|morgen ga ik|next we|volgende (week|keer)|"
    r"need to|moet(en)? nog|let['’]s build|laten we (bouwen|maken)|"
    r"we should|we zouden moeten|ik beloof|promise)\b")

DECISION_STRONG_RE = _re.compile(
    r"(?i)\b(besloten|decided|akkoord|agreed|conclusie|conclusion)\b")

RESEARCH_CUE_RE = _re.compile(
    r"(?i)\b(onderzoek|investigat|uitzoeken|research|verdiepen|"
    r"nakijken|check (out|of)|vergelijk|compare|hoe werkt|how does)\b")

MISSED_CATEGORY = {
    "idea": "IDEA",
    "todo": "TASK",
    "open_question": "QUESTION",
    "technical_claim": "RESEARCH",
    "decision": "DECISION",
    "proposed_action": "TASK",
    "project_mention": "RELATIONSHIP",
    "entity_mention": "OBJECT",
    "repeated_topic": "RISK",
    "possible_contradiction": "DEPENDENCY",
}

STOPWORDS = frozenset("""
de het een van en in op te dat is zijn was worden voor met als ook
niet geen dit die dat deze door over uit bij naar tot wil kunnen
moet zal zullen heeft hebben had hadden maar want dus omdat toen
dan daar hier wat wie waar hoe waarom welke er eenmaal even nog
al reeds zeer veel weinig meer meest minder eigen andere allen
the and for with from that this these those are was were been has
have had will would should could shall may might must can cannot
not but what when where which while withour your you your yours
they them their then than too very just about into over after
before between through during each other some such only also
will just don like know think new used using make made because
moeten moet werkt werken gaat gaan doet doen laten laat wordt
worden komt komen staat staan lijkt lijken blijft blijven geeft
geven neemt nemen ziet zien vindt vinden
""".split())


class IntelRefusedError(ValueError):
    """Intelligence validation refused; nothing was stored."""


def fingerprint(kind: str, text: str) -> str:
    norm = _re.sub(r"\s+", " ", str(text or "").strip().lower())
    return _hashlib.sha256(
        f"{kind}\x00{norm}".encode("utf-8")).hexdigest()


def generate_intel_id() -> str:
    return f"cintel_{int(__import__('time').time() * 1000):x}" \
        f"{_secrets.token_hex(3)}"


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def init_intel_tables() -> None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS conversation_intel (
            intel_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            record TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cintel_conv
            ON conversation_intel(conversation_id, kind);
        CREATE INDEX IF NOT EXISTS idx_cintel_fp
            ON conversation_intel(fingerprint);
        """)


def _save_intel(record: dict) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_intel_tables()
    init_chat_database()
    with chat_connection() as db:
        db.execute(
            """INSERT INTO conversation_intel
            (intel_id, conversation_id, kind, fingerprint, record,
             created_at) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(intel_id) DO UPDATE SET
            record=excluded.record""",
            (record["intel_id"], record["conversation_id"],
             record["kind"], record["fingerprint"],
             dump(record), record.get("created_at", _now())))


def list_intel(conversation_id: str = "", limit: int = 100,
               kind: str = "") -> list[dict]:
    from .database import chat_connection, init_chat_database, load
    init_intel_tables()
    init_chat_database()
    count = max(1, min(int(limit or 100), 300))
    query = ("SELECT record FROM conversation_intel "
             "ORDER BY created_at DESC LIMIT ?")
    params: list = [count]
    clauses = []
    if conversation_id:
        clauses.append("conversation_id=?")
        params.insert(0, str(conversation_id)[:80])
    if kind:
        clauses.append("kind=?")
        params.insert(len(clauses) - 1, str(kind)[:40])
    if clauses:
        query = ("SELECT record FROM conversation_intel WHERE "
                 + " AND ".join(clauses) +
                 " ORDER BY created_at DESC LIMIT ?")
    with chat_connection() as db:
        rows = db.execute(query, params).fetchall()
    return [load(row["record"]) for row in rows]


def known_fingerprints(limit: int = 500) -> set[str]:
    from .database import chat_connection, init_chat_database
    init_intel_tables()
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute(
            "SELECT fingerprint FROM conversation_intel "
            "ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit or 500), 2000)),)).fetchall()
    return {str(row["fingerprint"]) for row in rows}


def _words(text: str) -> list[str]:
    return [word.strip(".,;:!?()[]\"'").lower()
            for word in str(text or "").split()]


def _health_screen(*texts: str) -> None:
    from .conversation_bridge import _HEALTH_RE as HEALTH_RE
    blob = "\n".join(str(part or "") for part in texts)
    if HEALTH_RE.search(blob):
        raise IntelRefusedError(
            "Health-related text never becomes intelligence "
            "candidates; health stays explicitly scoped")


def _progress_evidence(keywords: list[str]) -> str:
    """Mission/event evidence for a repeated topic or promise.
    Returns evidence text or '' (UNKNOWN stays UNKNOWN)."""
    terms = [word.lower() for word in keywords
             if len(word) >= 5][:6]
    if not terms:
        return ""
    try:
        from .missions import list_missions
        for mission in list_missions(limit=100):
            haystack = f"{mission.goal} {mission.context or ''}" \
                .lower()
            hits = [term for term in terms if term in haystack]
            if hits and mission.status in ("completed", "approved",
                                           "running"):
                return (f"mission {mission.mission_id} "
                        f"[{mission.status}] mentions "
                        f"{hits[:3]}")
    except Exception:
        pass
    try:
        from . import main as _main
        for event in _main.bus_events(limit=200):
            haystack = f"{event.event_type} {event.summary}" \
                .lower()
            hits = [term for term in terms if term in haystack]
            if hits:
                return (f"event {event.event_type} mentions "
                        f"{hits[:3]}")
    except Exception:
        pass
    return ""


def _entity_names(findings: list[dict]) -> list[str]:
    names: list[str] = []
    for item in findings or []:
        if item.get("kind") == "entity_mention":
            candidate = str(item.get("entity_candidate", ""))
            if candidate and candidate not in names:
                names.append(candidate)
    return names[:10]


def _related_projects(terms: list[str]) -> list[str]:
    """Bounded substring match over inventory projects."""
    from . import main as _main
    words = [word.lower() for word in terms
             if len(word) >= 4][:8]
    if not words:
        return []
    reader = _main._world_reader()
    import anyio as _anyio

    async def _browse() -> list:
        try:
            found = await reader.browse("projects")
            return found.results or []
        except Exception:
            return []

    try:
        records = _anyio.run(_browse)
    except Exception:
        return []
    matched: list[str] = []
    for record in records[:60]:
        details = record.details \
            if isinstance(record.details, dict) else {}
        haystack = " ".join(
            str(details.get(key, "")) for key in
            ("name", "title", "goal")).lower()
        if any(word in haystack for word in words):
            matched.append(str(record.entity_id))
            if len(matched) >= 5:
                break
    return matched


def analyze_conversation(conversation_id: str) -> dict:
    """Full intelligence pass over one import. Deterministic,
    idempotent by fingerprint, stored as intel records."""
    from .conversation_bridge import (
        get_import, import_messages, load_analysis, missed_items)
    cleaned = str(conversation_id or "").strip()[:80]
    if not cleaned:
        raise IntelRefusedError("conversation_id is required")
    meta = get_import(cleaned)
    if meta is None:
        raise IntelRefusedError("Unknown imported conversation")
    try:
        messages = import_messages(cleaned)[:100]
    except Exception as error:
        raise IntelRefusedError(str(error)) from error
    if not messages:
        raise IntelRefusedError("Imported conversation has no messages")
    analysis = load_analysis(cleaned) or {}
    findings = analysis.get("findings", [])
    try:
        missed = missed_items(cleaned, analysis)
    except Exception:
        missed = []
    seen = known_fingerprints()
    created = 0

    def _store(kind: str, text: str, evidence: str,
               message_index, extra: dict | None = None) -> dict:
        nonlocal created
        finger = fingerprint(kind, text)
        item = {"intel_id": generate_intel_id(),
                "conversation_id": cleaned, "kind": kind,
                "fingerprint": finger,
                "state": INTEL_STATE.get(kind, "CANDIDATE"),
                "method": METHOD, "analysis_state": ANALYSIS_STATE,
                "text": str(text or "")[:500],
                "evidence": str(evidence or "")[:500],
                "message_index": message_index,
                "created_at": _now(),
                "materialized": {},
                **(extra or {})}
        if finger not in seen:
            seen.add(finger)
            _save_intel(item)
            created += 1
        return item

    themes = _extract_themes(messages, findings, _store)
    decisions = _extract_decisions(messages, findings, _store)
    promises = _extract_promises(messages, _store)
    contradictions = _extract_contradictions(
        messages, findings, cleaned, _store)
    missed_items_out = _extract_missed(missed, _store)
    research = _extract_research(messages, findings, _store)
    links = _extract_links(messages, findings, _store)
    symbiosis = _extract_symbiosis(
        messages, findings, cleaned, _store)
    result = {
        "conversation_id": cleaned,
        "method": METHOD, "analysis_state": ANALYSIS_STATE,
        "note": "Deterministic extractive analysis. Everything "
                "is OBSERVATION or CANDIDATE; no LLM involved; "
                "nothing stored as fact.",
        "counts": {"themes": len(themes),
                   "decisions": len(decisions),
                   "promises": len(promises),
                   "contradictions": len(contradictions),
                   "missed": len(missed_items_out),
                   "research_proposals": len(research),
                   "entity_links": len(links),
                   "symbiosis": len(symbiosis)},
        "themes": themes, "decisions": decisions,
        "promises": promises, "contradictions": contradictions,
        "missed": missed_items_out, "research": research,
        "entity_links": links, "symbiosis": symbiosis,
        "new_records": created,
    }
    _notify("conversation_analyzed",
            f"Conversation analyzed: {meta.get('title', cleaned)[:80]}",
            f"{sum(result['counts'].values())} intelligence items "
            f"({created} new). Review before anything becomes fact.",
            related_entity=cleaned)
    return result


def _extract_themes(messages, findings, store) -> list[dict]:
    counts: dict[str, int] = {}
    supporting: dict[str, list[int]] = {}
    for index, message in enumerate(messages):
        for word in _words(message.get("content", "")):
            if len(word) < 4 or word in STOPWORDS:
                continue
            counts[word] = counts.get(word, 0) + 1
            supporting.setdefault(word, [])
            if index not in supporting[word]:
                supporting[word].append(index)
    ranked = sorted(counts.items(), key=lambda pair: (
        -pair[1], pair[0]))[:12]
    entities = _entity_names(findings)
    out = []
    for term, count in ranked:
        if count < 2:
            continue
        related = [name for name in entities
                   if term in name.lower()][:5]
        try:
            projects = _related_projects([term])
        except Exception:
            projects = []
        out.append(store(
            "theme",
            f"Theme '{term}' ({count} mentions)",
            f"messages {supporting[term][:8]}",
            supporting[term][0] if supporting[term] else None,
            {"term": term, "mentions": count,
             "messages": supporting[term][:12],
             "related_entities": related,
             "related_projects": projects,
             "confidence": "high" if count >= 4 else "medium"}))
    return out


def _extract_decisions(messages, findings, store) -> list[dict]:
    out = []
    for item in findings or []:
        if item.get("kind") != "decision":
            continue
        text = str(item.get("text", ""))
        try:
            _health_screen(text, item.get("evidence", ""))
        except IntelRefusedError:
            continue
        strong = bool(DECISION_STRONG_RE.search(text))
        entities = [str(item.get("entity_candidate", ""))
                    for item in [item]
                    if item.get("entity_candidate")]
        out.append(store(
            "decision", text[:300], str(item.get("evidence", "")),
            item.get("message_index"),
            {"confidence": "high" if strong else "medium",
             "role": str(item.get("message_role", "")),
             "related_entities": entities[:5],
             "resolution": "UNRESOLVED"}))
    return out


def _extract_promises(messages, store) -> list[dict]:
    out = []
    for index, message in enumerate(messages):
        content = str(message.get("content", ""))
        if not PROMISE_RE.search(content):
            continue
        sentences = [part.strip() for part in _re.split(
            r"(?<=[.!?\u2026])\s+|\n+", content) if part.strip()]
        for sentence in sentences[:8]:
            if not PROMISE_RE.search(sentence):
                continue
            try:
                _health_screen(sentence)
            except IntelRefusedError:
                continue
            role = str(message.get("role", "user"))
            owner = "Jelles" if role == "user" else "assistant"
            evidence = _progress_evidence(_words(sentence))
            # Never invent an owner name from free text; role only.
            out.append(store(
                "promise", sentence[:300],
                f"message {index} ({role})", index,
                {"owner": owner, "role": role,
                 "status": "IN_PROGRESS" if evidence
                 else "UNKNOWN",
                 "completion_evidence": evidence or
                 "no mission/event evidence found — status UNKNOWN"}))
            if len(out) >= 15:
                return out
    return out


def _extract_contradictions(messages, findings, conversation_id,
                            store) -> list[dict]:
    out = []
    for item in findings or []:
        if item.get("kind") != "possible_contradiction":
            continue
        text = str(item.get("text", ""))
        evidence = str(item.get("evidence", ""))
        indices = [int(part) for part in _re.findall(
            r"\d+", evidence)][:2]
        side_a = side_b = ""
        for number in indices:
            if 0 <= number < len(messages):
                snippet = str(messages[number].get("content", "")) \
                    [:220]
                if not side_a:
                    side_a = snippet
                else:
                    side_b = snippet
        try:
            _health_screen(text, side_a, side_b)
        except IntelRefusedError:
            continue
        out.append(store(
            "contradiction", text[:300], evidence,
            item.get("message_index"),
            {"side_a": side_a, "side_b": side_b,
             "status": "UNRESOLVED"}))
    # Cross-check: repeated_topic pairs with opposing markers.
    if len(out) < 5:
        lowered = [str(msg.get("content", "")).lower()
                   for msg in messages]
        for word in ("printer", "camera", "node", "research",
                     "project", "planning", "aanpak"):
            pos = [idx for idx, text in enumerate(lowered)
                   if word in text and ("werkt" in text or
                                        "goed" in text or "doen" in text)]
            neg = [idx for idx, text in enumerate(lowered)
                   if word in text and ("niet" in text or
                                        "geen" in text or
                                        "stopt" in text)]
            if pos and neg and pos[0] != neg[0]:
                text = (f"Mogelijke tegenspraak over '{word}': "
                        f"message {pos[0]} vs {neg[0]}")
                try:
                    _health_screen(text)
                except IntelRefusedError:
                    continue
                out.append(store(
                    "contradiction", text,
                    f"messages {pos[0]} vs {neg[0]}", neg[0],
                    {"side_a": str(messages[pos[0]].get(
                        "content", ""))[:220],
                     "side_b": str(messages[neg[0]].get(
                         "content", ""))[:220],
                     "status": "UNRESOLVED"}))
                if len(out) >= 5:
                    break
    return out


def _extract_missed(missed, store) -> list[dict]:
    out = []
    for item in missed or []:
        kind = str(item.get("kind", ""))
        category = MISSED_CATEGORY.get(kind, "TASK")
        text = str(item.get("text", ""))
        try:
            _health_screen(text, item.get("evidence", ""))
        except IntelRefusedError:
            continue
        out.append(store(
            "missed", f"[{category}] {text[:280]}",
            str(item.get("evidence", "")),
            item.get("message_index"),
            {"category": category,
             "source_kind": kind}))
    return out


def _extract_research(messages, findings, store) -> list[dict]:
    out = []
    for item in findings or []:
        text = str(item.get("text", ""))
        if item.get("kind") == "open_question" or \
                RESEARCH_CUE_RE.search(text):
            try:
                _health_screen(text, item.get("evidence", ""))
            except IntelRefusedError:
                continue
            entities = [str(item.get("entity_candidate", ""))
                        for item in [item]
                        if item.get("entity_candidate")]
            out.append(store(
                "research_proposal", text[:300],
                str(item.get("evidence", "")),
                item.get("message_index"),
                {"question": text[:300],
                 "reason": "open or investigative statement in "
                           "conversation",
                 "related_entities": entities[:5],
                 "priority": "MEDIUM"}))
            if len(out) >= 10:
                break
    return out


def _extract_links(messages, findings, store) -> list[dict]:
    out = []
    try:
        from .camera_ecosystem import possible_matches
    except Exception:
        possible_matches = None
    for name in _entity_names(findings):
        matches = []
        if possible_matches is not None:
            try:
                matches = possible_matches(name, limit=3)
            except Exception:
                matches = []
        for match in matches:
            out.append(store(
                "entity_link",
                f"Possible link: '{name}' → "
                f"{match.get('title', match.get('entity_id', ''))}",
                f"entity mention + inventory match "
                f"({match.get('why', '')})",
                None,
                {"mention": name,
                 "entity_id": match.get("entity_id", ""),
                 "match_why": str(match.get("why", ""))[:200]}))
            if len(out) >= 10:
                return out
    return out


def _extract_symbiosis(messages, findings, conversation_id,
                       store) -> list[dict]:
    out = []
    entities = _entity_names(findings)
    projects: list[str] = []
    try:
        projects = _related_projects(
            _words(" ".join(str(msg.get("content", ""))
                            for msg in messages[:20])))
    except Exception:
        projects = []
    pairs: list[tuple[str, str, str]] = []
    for entity in entities[:6]:
        for project in projects[:4]:
            pairs.append((entity, project,
                          f"both surface in {conversation_id}"))
    entity_pairs = [(entities[i], entities[j],
                     "co-mentioned in one conversation")
                    for i in range(min(4, len(entities)))
                    for j in range(i + 1, min(5, len(entities)))]
    for left, right, why in (pairs + entity_pairs)[:10]:
        try:
            _health_screen(left, right)
        except IntelRefusedError:
            continue
        out.append(store(
            "symbiosis",
            f"Possible symbiosis: {left} ↔ {right}",
            why, None,
            {"entity_a": left, "entity_b": right, "why": why,
             "status": "PROPOSED"}))
    return out


def _notify(kind: str, title: str, body: str = "",
            related_entity: str = "") -> None:
    """Best-effort IN_APP fan-out to registered nodes."""
    try:
        from . import main as _main
        from .notify_center import send as _send
        nodes = _main.list_nodes()[:10]
    except Exception:
        return
    for row in nodes:
        node_id = str(row.get("node_id", ""))
        if not node_id:
            continue
        try:
            _send(node_id, kind, title[:200], body[:1000],
                  related_entity=related_entity[:100])
        except Exception:
            continue


def materialize(conversation_id: str, intel_fingerprint: str,
                action: str) -> dict:
    """Turn one intel item into ecosystem state. Explicit,
    idempotent, gated downstream:

    - candidate → knowledge candidate (support/promote/reject
      stay human).
    - research-queue → draft research run (execution needs its
      own mission YES).
    - link → connection candidate (PROPOSED symbiosis).
    """
    from .knowledge import (CandidateRefusedError, list_candidates,
                            new_candidate, save_candidate)
    from .inventory_read import Provenance
    cleaned = str(conversation_id or "").strip()[:80]
    finger = str(intel_fingerprint or "").strip()[:64]
    if not cleaned or not finger:
        raise IntelRefusedError(
            "conversation_id and fingerprint are required")
    if action not in ("candidate", "research-queue", "link"):
        raise IntelRefusedError(
            "action must be candidate, research-queue or link")
    items = [item for item in list_intel(cleaned, limit=300)
             if item.get("fingerprint") == finger]
    if not items:
        raise IntelRefusedError("intel item not found")
    item = items[0]
    _health_screen(item.get("text", ""), item.get("evidence", ""))
    marker = {"kind": "intel-fingerprint", "id": finger,
              "label": item.get("kind", "")}
    try:
        existing = list_candidates(limit=500)
    except Exception:
        existing = []
    for entry in existing:
        try:
            data = entry.model_dump(mode="json")
        except Exception:
            continue
        refs = data.get("source_refs") or []
        if any(isinstance(ref, dict) and
               ref.get("kind") == "intel-fingerprint" and
               ref.get("id") == finger for ref in refs):
            return {"status": "already-materialized",
                    "candidate_id": data.get("candidate_id", ""),
                    "fingerprint": finger}
    kind = str(item.get("kind", ""))
    if action == "research-queue":
        if kind != "research_proposal":
            raise IntelRefusedError(
                "only research proposals queue research runs")
        from .research_engine import new_run, save_run
        question = str(item.get("question",
                                item.get("text", "")))[:500]
        if not question:
            raise IntelRefusedError("proposal carries no question")
        run = new_run(question, requested_by="conversation-intel",
                      metadata={"priority": "MEDIUM",
                                "provider": "wikipedia",
                                "max_sources": 6, "route": "local",
                                "intel_fingerprint": finger,
                                "conversation_id": cleaned})
        save_run(run)
        item["materialized"] = {"action": action,
                                "run_id": run.run_id,
                                "at": _now()}
        _save_intel(item)
        return {"status": "queued", "run_id": run.run_id,
                "fingerprint": finger}
    type_map = {"decision": "claim", "promise": "task",
                "contradiction": "claim", "missed": "task",
                "research_proposal": "question",
                "entity_link": "connection",
                "symbiosis": "connection", "theme": "note"}
    candidate_type = type_map.get(kind, "note")
    title = str(item.get("text", ""))[:140]
    entity_refs: list[str] = []
    if action == "link":
        if kind == "entity_link":
            target = str(item.get("entity_id", ""))
            if not target:
                raise IntelRefusedError(
                    "entity link carries no target")
            entity_refs = [target]
            mention = str(item.get("mention", ""))
            if mention and mention != target:
                try:
                    from .symbiosis import clean_entity
                    clean_entity(mention)
                    entity_refs.insert(0, mention)
                except ValueError:
                    pass
        elif kind == "symbiosis":
            entity_refs = [str(item.get("entity_a", "")),
                           str(item.get("entity_b", ""))]
            entity_refs = [ref for ref in entity_refs if ref]
        else:
            raise IntelRefusedError(
                "only entity links and symbioses link directly")
    else:
        for key in ("related_entities",):
            for ref in item.get(key, []) or []:
                if str(ref).startswith(
                        ("obj_", "proj_", "idea_", "hw_", "file_",
                         "loc_", "mod_")) and ref not in entity_refs:
                    entity_refs.append(str(ref))
    evidence = [{"text": str(item.get("evidence", ""))[:500],
                 "source": cleaned}]
    if kind == "contradiction":
        evidence.append({"text": "B: " + str(item.get(
            "side_b", ""))[:300], "source": cleaned})
    try:
        entry = new_candidate(
            title, candidate_type,
            summary=f"{item.get('text', '')[:800]} "
                    f"(status {item.get('status', '')})",
            state="candidate",
            provenance=Provenance(
                source_type="imported",
                creator_id="conversation-intelligence",
                human_verified=False,
                notes=f"from {cleaned}; method {METHOD}"),
            source_refs=[{"kind": "conversation", "id": cleaned,
                          "label": "conversation"}, marker],
            evidence=evidence,
            entity_refs=entity_refs[:10])
        save_candidate(entry)
    except CandidateRefusedError as error:
        raise IntelRefusedError(str(error)) from error
    item["materialized"] = {"action": action,
                            "candidate_id": entry.candidate_id,
                            "at": _now()}
    _save_intel(item)
    try:
        from .events import new_event as _bus_new
        from .events import save_event as _bus_save
        _bus_save(_bus_new(
            "candidate.observed",
            f"Intel {kind} from {cleaned}: {title[:100]}"))
    except Exception:
        pass
    _notify("candidate_waiting",
            f"Conversation intel ready for review ({kind})",
            title[:200], related_entity=cleaned)
    return {"status": "materialized",
            "candidate_id": entry.candidate_id,
            "fingerprint": finger}


def cross_conversation(limit: int = 10) -> dict:
    """Aggregate intel across imports with fingerprint dedupe +
    repetition detection (theme in ≥2 conversations without
    visible progress → REVISIT observation)."""
    from .conversation_bridge import list_imports
    count = max(1, min(int(limit or 10), 20))
    try:
        imports = list_imports(limit=count)
    except Exception:
        imports = []
    by_fingerprint: dict[str, dict] = {}
    for meta in imports:
        conversation_id = meta.get("conversation_id", "")
        try:
            items = list_intel(conversation_id, limit=200)
        except Exception:
            continue
        for item in items:
            finger = str(item.get("fingerprint", ""))
            if not finger or finger in by_fingerprint:
                if finger:
                    by_fingerprint[finger].setdefault(
                        "conversations", [])
                    if conversation_id not in \
                            by_fingerprint[finger]["conversations"]:
                        by_fingerprint[finger][
                            "conversations"].append(conversation_id)
                continue
            record = dict(item)
            record["conversations"] = [conversation_id]
            by_fingerprint[finger] = record
    unique = list(by_fingerprint.values())
    themes: dict[str, dict] = {}
    for item in unique:
        if item.get("kind") != "theme":
            continue
        term = str(item.get("term", ""))
        if term:
            themes.setdefault(term, {"term": term,
                                     "conversations": []})
            for conversation_id in item.get("conversations", []):
                if conversation_id not in \
                        themes[term]["conversations"]:
                    themes[term]["conversations"].append(
                        conversation_id)
    revisits: list[dict] = []
    for term, record in sorted(themes.items()):
        if len(record["conversations"]) < 2:
            continue
        evidence = _progress_evidence([term])
        if not evidence:
            revisits.append({
                "term": term,
                "conversations": record["conversations"][:6],
                "text": f"Dit onderwerp komt meerdere keren terug "
                        f"({len(record['conversations'])} "
                        f"conversations), maar ik zie geen recente "
                        f"voortgang.",
                "status": "OBSERVATION"})
    return {"imports_considered": len(imports),
            "unique_items": len(unique),
            "themes": sorted(themes.values(),
                             key=lambda entry: -len(
                                 entry["conversations"]))[:15],
            "revisits": revisits[:10],
            "contradictions": [
                item for item in unique
                if item.get("kind") == "contradiction"][:10],
            "open_promises": [
                item for item in unique
                if item.get("kind") == "promise" and
                item.get("status") in ("UNKNOWN", "IN_PROGRESS")
            ][:15]}


def timeline(conversation_id: str, limit: int = 40) -> list[dict]:
    """Visual timeline from real message order + import stamps.
    Unknown timestamps stay unknown."""
    from .conversation_bridge import get_import, import_messages
    cleaned = str(conversation_id or "").strip()[:80]
    meta = get_import(cleaned)
    if meta is None:
        raise IntelRefusedError("Unknown imported conversation")
    try:
        items = sorted(
            list_intel(cleaned, limit=300),
            key=lambda entry: (
                entry.get("message_index")
                if isinstance(entry.get("message_index"), int)
                else 10 ** 9))
    except Exception:
        items = []
    try:
        count = len(import_messages(cleaned))
    except Exception:
        count = 0
    out = [{
        "at": str(meta.get("imported_at", ""))[:16] or "unknown",
        "kind": "import",
        "text": f"Imported ({count} messages)",
    }]
    for item in items[: max(1, min(int(limit or 40), 80))]:
        index = item.get("message_index")
        out.append({
            "at": f"message {index}" if isinstance(index, int)
            else "unknown",
            "kind": str(item.get("kind", "")),
            "text": str(item.get("text", ""))[:160],
        })
    return out


def intel_graph(conversation_id: str,
                limit: int = 40) -> dict:
    """Overlay-shaped nodes/edges for one conversation: the
    conversation node plus theme/decision/promise/question/
    research nodes with dashed provenance edges."""
    cleaned = str(conversation_id or "").strip()[:80]
    try:
        items = list_intel(cleaned, limit=limit)
    except Exception:
        items = []
    nodes = [{
        "id": cleaned, "type": "conversation",
        "label": cleaned[:60], "source": "mycelium",
        "metadata": {"human_verified": False}}]
    edges: list[dict] = []
    type_map = {"theme": "theme", "decision": "decision",
                "promise": "promise",
                "research_proposal": "research",
                "missed": "question",
                "contradiction": "question",
                "entity_link": "candidate",
                "symbiosis": "candidate"}
    for item in items[: max(1, min(int(limit or 40), 60))]:
        node_id = f"cintel_{item.get('fingerprint', '')[:16]}"
        if not item.get("fingerprint"):
            continue
        nodes.append({
            "id": node_id,
            "type": type_map.get(str(item.get("kind", "")),
                                 "candidate"),
            "label": str(item.get("text", ""))[:60],
            "source": "mycelium",
            "metadata": {"human_verified": False,
                         "intel_kind": str(item.get("kind", "")),
                         "state": str(item.get("state", ""))},
        })
        edges.append({
            "from": cleaned, "predicate": "surfaces", "to": node_id,
            "provenance": {"source_type": "ai-generated",
                           "creator_id": "conversation-intel",
                           "human_verified": False},
        })
    return {"nodes": nodes, "edges": edges,
            "honesty": "Intel overlay: context, never truth. "
                       "Dashed provenance throughout."}
