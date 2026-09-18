"""Knowledge lifecycle (BIG #32): observations mature visibly.

OBSERVATION -> CANDIDATE -> SUPPORTED -> PROMOTED MEMORY
(and REJECTED as an explicit terminal state).

Candidates are the bridge between raw intake (conversation
findings, research questions, camera observations) and long-term
memory. Rules (tested, fail-closed):

- Nothing silently becomes a fact. Promotion is explicit, human
  authority is required for consequential tiers, and AI content
  verifies only through verify_memory() with a human approver.
- Provenance, source references, entity links, contradictions and
  the originating conversation/research/project survive promotion
  (carried in the memory's data/derived_from/refs).
- Verified existing memories are never overwritten: a promotion
  that overlaps a user_fact/verified memory refuses with the
  conflict list.
- Idempotent: promoting an already-promoted candidate returns the
  existing memory; re-supporting by the same supporter is a no-op.
- Concurrency safe: revision-checked updates (expected_revision);
  stale writers reload and retry explicitly.
- No numeric confidence is invented: support is a count of
  distinct sources/supporters, shown as-is.

Health content never enters candidates: health-flagged findings
refuse at creation.
"""

from __future__ import annotations

import re as _re
import secrets as _secrets
import time as _time

from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import Provenance

CANDIDATE_TYPES = (
    "idea",
    "observation",
    "claim",
    "question",
    "connection",
    "task",
    "note",
)

CANDIDATE_STATES = (
    "observation",
    "candidate",
    "supported",
    "promoted",
    "rejected",
)

ACTIVE_STATES = ("observation", "candidate", "supported")

DEFAULT_TRUTH = {
    "idea": "ai_suggestion",
    "observation": "observed",
    "claim": "ai_inference",
    "question": "ai_suggestion",
    "connection": "ai_inference",
    "task": "ai_suggestion",
    "note": "ai_suggestion",
}

MEMORY_TYPE_FOR = {
    "idea": "fact",
    "observation": "observation",
    "claim": "fact",
    "question": "fact",
    "connection": "relationship",
    "task": "fact",
    "note": "episodic",
}

NON_FACT_TRUTHS = ("ai_suggestion", "ai_inference", "observed",
                   "external_source")
FACT_TRUTHS = ("verified", "user_fact")

MAX_TITLE_CHARS = 200
MAX_SUMMARY_CHARS = 2000
MAX_EVIDENCE_ITEMS = 10
MAX_REF_ITEMS = 20


class CandidateRefusedError(ValueError):
    """Lifecycle refused; nothing was stored."""


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=3, max_length=80)
    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    summary: str = Field(default="", max_length=MAX_SUMMARY_CHARS)
    candidate_type: str = Field(min_length=1, max_length=20)
    state: str = Field(default="candidate", max_length=20)
    provenance: Provenance = Field(default_factory=Provenance)
    source_refs: list[dict] = Field(default_factory=list,
                                    max_length=MAX_REF_ITEMS)
    evidence: list[dict] = Field(default_factory=list,
                                 max_length=MAX_EVIDENCE_ITEMS)
    counter_evidence: list[dict] = Field(
        default_factory=list, max_length=MAX_EVIDENCE_ITEMS)
    entity_refs: list[str] = Field(default_factory=list,
                                   max_length=MAX_REF_ITEMS)
    project_ref: str = Field(default="", max_length=100)
    contradictions: list[dict] = Field(default_factory=list,
                                       max_length=10)
    support: list[dict] = Field(default_factory=list,
                                max_length=20)
    promoted_to: str = Field(default="", max_length=80)
    revision: int = Field(default=1, ge=1)
    created_at: str = ""
    updated_at: str = ""


def generate_candidate_id() -> str:
    return f"cand_{int(_time.time() * 1000):x}{_secrets.token_hex(4)}"


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _check_evidence(items: list | None, label: str) -> list[dict]:
    cleaned: list[dict] = []
    for item in (items or [])[:MAX_EVIDENCE_ITEMS]:
        if not isinstance(item, dict):
            raise CandidateRefusedError(
                f"{label} entries must be objects")
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        cleaned.append({
            "text": text[:500],
            "source": str(item.get("source", ""))[:120],
        })
    return cleaned


def _check_refs(values: list | None) -> list[str]:
    cleaned: list[str] = []
    for ref in (values or [])[:MAX_REF_ITEMS]:
        text = str(ref or "").strip()
        if not text or len(text) > 120:
            raise CandidateRefusedError(
                "entity refs must be short text")
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def _check_source_refs(items: list | None) -> list[dict]:
    cleaned: list[dict] = []
    for item in (items or [])[:MAX_REF_ITEMS]:
        if not isinstance(item, dict):
            raise CandidateRefusedError(
                "source refs must be objects")
        kind = str(item.get("kind", "")).strip()[:20]
        ident = str(item.get("id", "")).strip()[:100]
        if not kind or not ident:
            raise CandidateRefusedError(
                "source refs need kind + id")
        cleaned.append({
            "kind": kind,
            "id": ident,
            "label": str(item.get("label", ""))[:160],
        })
    return cleaned


def new_candidate(title: str, candidate_type: str, *,
                  summary: str = "",
                  state: str = "candidate",
                  provenance: Provenance | None = None,
                  source_refs: list | None = None,
                  evidence: list | None = None,
                  counter_evidence: list | None = None,
                  entity_refs: list | None = None,
                  project_ref: str = "",
                  contradictions: list | None = None
                  ) -> Candidate:
    """Build one validated candidate. Health-flagged content is the
    caller's responsibility to refuse (see candidate_from_finding)."""
    cleaned_type = str(candidate_type or "").strip()
    if cleaned_type not in CANDIDATE_TYPES:
        raise CandidateRefusedError(
            f"Unknown candidate type '{candidate_type}'; expected "
            f"one of {list(CANDIDATE_TYPES)}")
    cleaned_state = str(state or "candidate").strip()
    if cleaned_state not in CANDIDATE_STATES:
        raise CandidateRefusedError(
            f"Unknown candidate state '{state}'")
    if not isinstance(title, str) or not title.strip():
        raise CandidateRefusedError("candidate title must be text")
    if len(title.strip()) > MAX_TITLE_CHARS:
        raise CandidateRefusedError(
            f"candidate title exceeds {MAX_TITLE_CHARS} characters")
    if not isinstance(summary, str):
        raise CandidateRefusedError("candidate summary must be text")
    if len(summary) > MAX_SUMMARY_CHARS:
        raise CandidateRefusedError(
            f"candidate summary exceeds {MAX_SUMMARY_CHARS} "
            "characters")
    stamp = _now()
    return Candidate(
        candidate_id=generate_candidate_id(),
        title=title.strip()[:MAX_TITLE_CHARS],
        summary=str(summary or "")[:MAX_SUMMARY_CHARS],
        candidate_type=cleaned_type, state=cleaned_state,
        provenance=provenance or Provenance(
            source_type="ai-generated", creator_id="knowledge",
            human_verified=False),
        source_refs=_check_source_refs(source_refs),
        evidence=_check_evidence(evidence, "evidence"),
        counter_evidence=_check_evidence(
            counter_evidence, "counter_evidence"),
        entity_refs=_check_refs(entity_refs),
        project_ref=str(project_ref or "")[:100],
        contradictions=[dict(item) for item in
                        (contradictions or [])[:10]
                        if isinstance(item, dict)],
        support=[], promoted_to="", revision=1,
        created_at=stamp, updated_at=stamp)


def init_knowledge_tables() -> None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS knowledge_candidates (
            candidate_id TEXT PRIMARY KEY,
            record TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'candidate',
            candidate_type TEXT NOT NULL DEFAULT '',
            project_ref TEXT NOT NULL DEFAULT '',
            revision INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_candidates_state
            ON knowledge_candidates(state, updated_at);
        """)


def save_candidate(entry: Candidate,
                   expected_revision: int | None = None) -> None:
    """Persist with optimistic revision fencing."""
    from .database import chat_connection, dump
    init_knowledge_tables()
    if expected_revision is not None:
        with chat_connection() as db:
            row = db.execute(
                "SELECT revision FROM knowledge_candidates WHERE "
                "candidate_id=?", (entry.candidate_id,)).fetchone()
            if row is None or int(row["revision"]) != int(
                    expected_revision):
                raise CandidateRefusedError(
                    "candidate revision moved; reload and retry "
                    "explicitly")
    with chat_connection() as db:
        db.execute("""INSERT INTO knowledge_candidates
        (candidate_id, record, state, candidate_type, project_ref,
         revision, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(candidate_id) DO UPDATE SET record=excluded.record,
        state=excluded.state, candidate_type=excluded.candidate_type,
        project_ref=excluded.project_ref,
        revision=excluded.revision, updated_at=excluded.updated_at""",
                   (entry.candidate_id,
                    dump(entry.model_dump(mode="json")), entry.state,
                    entry.candidate_type, entry.project_ref,
                    entry.revision, entry.created_at,
                    entry.updated_at))


def _row_to_candidate(row) -> Candidate:
    from .database import load
    return Candidate.model_validate(load(row["record"]))


def get_candidate(candidate_id: str) -> Candidate | None:
    from .database import chat_connection
    init_knowledge_tables()
    with chat_connection() as db:
        row = db.execute(
            "SELECT record FROM knowledge_candidates WHERE "
            "candidate_id=?", (candidate_id,)).fetchone()
    if row is None:
        return None
    return _row_to_candidate(row)


def list_candidates(*, state: str = "", candidate_type: str = "",
                    project_ref: str = "", limit: int = 50) -> list:
    from .database import chat_connection
    init_knowledge_tables()
    count = max(1, min(int(limit or 50), 200))
    query = "SELECT record FROM knowledge_candidates"
    clauses: list[str] = []
    params: list = []
    if state:
        if state not in CANDIDATE_STATES:
            raise CandidateRefusedError(
                f"Unknown candidate state '{state}'")
        clauses.append("state=?")
        params.append(state)
    if candidate_type:
        if candidate_type not in CANDIDATE_TYPES:
            raise CandidateRefusedError(
                f"Unknown candidate type '{candidate_type}'")
        clauses.append("candidate_type=?")
        params.append(candidate_type)
    if project_ref:
        clauses.append("project_ref=?")
        params.append(str(project_ref)[:100])
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(count)
    with chat_connection() as db:
        rows = db.execute(query, params).fetchall()
    return [_row_to_candidate(row) for row in rows]


def support_count(entry: Candidate) -> int:
    return len({str(item.get("by", "")) for item in entry.support
                if str(item.get("by", "")).strip()})


def support_candidate(candidate_id: str, supporter: str, *,
                      rationale: str = "") -> Candidate:
    """One human (or named flow) backs a candidate. Two distinct
    supporters move it to supported. Same supporter twice is a
    no-op. Terminal states refuse."""
    name = str(supporter or "").strip()[:80]
    if not name:
        raise CandidateRefusedError("support needs a supporter name")
    entry = get_candidate(candidate_id)
    if entry is None:
        raise CandidateRefusedError("Unknown candidate")
    if entry.state in ("promoted", "rejected"):
        raise CandidateRefusedError(
            f"Candidate is {entry.state}; terminal states refuse "
            "support")
    if any(str(item.get("by", "")) == name for item in entry.support):
        return entry
    updated = entry.model_copy(update={
        "support": [*entry.support, {
            "by": name, "rationale": str(rationale or "")[:300],
            "at": _now()}],
        "revision": entry.revision + 1, "updated_at": _now()})
    if support_count(updated) >= 2 and updated.state in (
            "observation", "candidate"):
        updated = updated.model_copy(update={"state": "supported"})
    save_candidate(updated, expected_revision=entry.revision)
    return updated


def reject_candidate(candidate_id: str, *, reason: str = "",
                     decided_by: str = "") -> Candidate:
    entry = get_candidate(candidate_id)
    if entry is None:
        raise CandidateRefusedError("Unknown candidate")
    if entry.state in ("promoted", "rejected"):
        raise CandidateRefusedError(
            f"Candidate is already {entry.state}")
    updated = entry.model_copy(update={
        "state": "rejected",
        "support": [*entry.support, {
            "by": str(decided_by or "human")[:80],
            "rationale": f"rejected: {str(reason or '')[:300]}",
            "at": _now()}],
        "revision": entry.revision + 1, "updated_at": _now()})
    save_candidate(updated, expected_revision=entry.revision)
    return updated


def touch_candidate(candidate_id: str) -> Candidate:
    """Keep candidate: refresh without changing state."""
    entry = get_candidate(candidate_id)
    if entry is None:
        raise CandidateRefusedError("Unknown candidate")
    if entry.state in ("promoted", "rejected"):
        return entry
    updated = entry.model_copy(update={"updated_at": _now()})
    save_candidate(updated, expected_revision=entry.revision)
    return updated


_WORD_RE = _re.compile(r"[a-zA-Z0-9]{4,}")


def _keywords(text: str) -> set[str]:
    return {word.lower() for word in _WORD_RE.findall(text or "")}


def conflicting_memories(entry: Candidate, limit: int = 10) -> list:
    """Verified/user_fact memories overlapping this candidate.
    Promotion refuses while any exist — they are never silently
    overwritten."""
    from .memory import retrieve_memories
    query = f"{entry.title} {entry.summary}"[:300]
    try:
        found = retrieve_memories(query, limit=limit * 2)
    except Exception:
        return []
    wanted = _keywords(query)
    conflicts = []
    for memory in found:
        truth = memory.get("truth", "") if isinstance(
            memory, dict) else getattr(memory, "truth", "")
        if truth not in ("user_fact", "verified"):
            continue
        title = memory.get("title", "") if isinstance(
            memory, dict) else getattr(memory, "title", "")
        content = memory.get("content", "") if isinstance(
            memory, dict) else getattr(memory, "content", "")
        overlap = wanted & _keywords(f"{title} {content}")
        if overlap:
            conflicts.append(memory)
        if len(conflicts) >= max(1, limit):
            break
    return conflicts


def promote_candidate(candidate_id: str, *, truth: str = "",
                      verified_by: str = "",
                      importance: float = 0.6) -> dict:
    """Promote a candidate to memory. Explicit, idempotent,
    conflict-safe.

    - truth defaults per candidate type (ai tiers); fact tiers
      need verified_by (human) and verify_memory() semantics.
    - overlapping verified/user_fact memories refuse with the
      conflict list.
    - provenance, sources, evidence, contradictions and origin
      survive inside the memory (data.origin + derived_from).
    - emits nothing by itself; callers emit the audit event.
    """
    entry = get_candidate(candidate_id)
    if entry is None:
        raise CandidateRefusedError("Unknown candidate")
    if entry.state == "promoted" and entry.promoted_to:
        from .memory import get_memory
        existing = get_memory(entry.promoted_to)
        if existing is not None:
            return {"memory_id": existing.memory_id,
                    "truth": existing.truth, "deduped": True}
    if entry.state == "rejected":
        raise CandidateRefusedError(
            "Rejected candidates never promote; create a new one")
    wanted_truth = str(truth or "").strip() or DEFAULT_TRUTH[
        entry.candidate_type]
    if wanted_truth not in NON_FACT_TRUTHS + FACT_TRUTHS:
        raise CandidateRefusedError(
            f"Unknown truth tier '{truth}'")
    conflicts = conflicting_memories(entry)
    if conflicts:
        def _conflict_id(memory) -> str:
            if isinstance(memory, dict):
                return str(memory.get("memory_id", "?"))
            return str(getattr(memory, "memory_id", "?"))
        raise CandidateRefusedError(
            "Promotion refused: overlaps verified memory "
            f"({', '.join(_conflict_id(memory) for memory in conflicts[:5])}); "
            "resolve the conflict explicitly instead")
    from .memory import (MemoryRefusedError, get_memory, new_memory,
                         save_memory, verify_memory)
    provenance = Provenance(
        source_type=str(entry.provenance.source_type or "ai-generated"),
        creator_id=str(entry.provenance.creator_id or
                       "knowledge-promotion")[:120],
        human_verified=False,
        notes=f"promoted from {entry.candidate_id}; "
              f"{support_count(entry)} supporter(s); "
              "verification is separate")
    data = {
        "origin": {"candidate_id": entry.candidate_id,
                   "candidate_type": entry.candidate_type,
                   "state_at_promotion": entry.state,
                   "support": entry.support[:10],
                   "source_refs": entry.source_refs[:10],
                   "evidence": entry.evidence[:10],
                   "counter_evidence": entry.counter_evidence[:10],
                   "contradictions": entry.contradictions[:10]},
    }
    try:
        memory = new_memory(
            MEMORY_TYPE_FOR[entry.candidate_type], entry.title,
            truth=wanted_truth if wanted_truth in NON_FACT_TRUTHS
            else "ai_suggestion",
            content=entry.summary or entry.title,
            data=data, source=f"candidate:{entry.candidate_id}",
            provenance=provenance,
            project_ref=entry.project_ref,
            entity_refs=list(entry.entity_refs),
            derived_from=[entry.candidate_id],
            importance=max(0.0, min(1.0, float(importance))))
    except MemoryRefusedError as error:
        raise CandidateRefusedError(str(error)) from error
    if wanted_truth in FACT_TRUTHS:
        if not str(verified_by or "").strip():
            raise CandidateRefusedError(
                "Fact-tier promotion needs verified_by (a human)")
        proven = provenance.model_copy(update={
            "human_verified": True,
            "notes": provenance.notes + " | human-verified at "
                     "promotion"})
        memory = memory.model_copy(update={"provenance": proven})
        try:
            memory = verify_memory(
                memory, str(verified_by).strip()[:80])
        except MemoryRefusedError as error:
            raise CandidateRefusedError(str(error)) from error
    else:
        from .memory import content_fingerprint
        fingerprint = content_fingerprint(
            memory.title + "\n" + memory.content, memory.memory_type)
        from .memory import list_memories
        for known in list_memories(limit=5000):
            if known.fingerprint == fingerprint and \
                    known.status == "active":
                updated = entry.model_copy(update={
                    "state": "promoted",
                    "promoted_to": known.memory_id,
                    "revision": entry.revision + 1,
                    "updated_at": _now()})
                save_candidate(updated,
                               expected_revision=entry.revision)
                return {"memory_id": known.memory_id,
                        "truth": known.truth, "deduped": True}
    try:
        save_memory(memory)
    except MemoryRefusedError as error:
        raise CandidateRefusedError(str(error)) from error
    updated = entry.model_copy(update={
        "state": "promoted", "promoted_to": memory.memory_id,
        "revision": entry.revision + 1, "updated_at": _now()})
    save_candidate(updated, expected_revision=entry.revision)
    return {"memory_id": memory.memory_id, "truth": memory.truth,
            "deduped": False}


# -- intake helpers ------------------------------------------------------------

def candidate_from_finding(conversation_id: str, finding: dict,
                           *, state: str = "candidate") -> Candidate:
    """One conversation finding becomes a candidate. Health-flagged
    text refuses (health isolation); secrets were already redacted
    at import."""
    from .conversation_bridge import _HEALTH_RE as HEALTH_RE
    text = str(finding.get("text", ""))
    evidence = str(finding.get("evidence", ""))
    if HEALTH_RE.search(text) or HEALTH_RE.search(evidence):
        raise CandidateRefusedError(
            "Health-related findings never become candidates here; "
            "health stays explicitly scoped")
    kind = str(finding.get("finding_kind",
                           finding.get("kind", "")))
    type_map = {"idea": "idea", "todo": "task",
                "open_question": "question",
                "technical_claim": "claim",
                "decision": "claim", "proposed_action": "task",
                "project_mention": "connection",
                "entity_mention": "connection"}
    candidate_type = type_map.get(kind, "note")
    message_index = finding.get("message_index")
    entry = new_candidate(
        f"{kind}: {text[:140]}".strip(),
        candidate_type, summary=text[:1500], state=state,
        provenance=Provenance(
            source_type="imported",
            creator_id="conversation-analysis",
            human_verified=False,
            notes=f"from {conversation_id}"
                  + (f" message {message_index}"
                     if message_index is not None else "")),
        source_refs=[{"kind": "conversation", "id": conversation_id,
                      "label": f"message {message_index}"}],
        evidence=[{"text": evidence[:500],
                   "source": conversation_id}],
        entity_refs=([str(finding.get("entity_candidate", ""))]
                     if finding.get("entity_candidate") else []))
    save_candidate(entry)
    return entry
