"""Long-term memory layer (BIG #11-15, Phase 1).

Ten memory types over the existing event/state architecture —
never one giant text blob. Every entry carries provenance and
an explicit truth tier; AI output never auto-promotes to fact.

Truth tiers: user_fact > verified > observed > external_source
> ai_inference > ai_suggestion. Promotion is explicit only
(verify_memory with a human approver); contradictions are
preserved, never silently overwritten.

Retrieval reuses the existing ranking ideas (lexical +
recency + importance + project relevance, optional semantic
via the Ollama embedding provider). Consolidation proposes;
it never writes.
"""

import hashlib
import secrets
import time

from pydantic import BaseModel, Field

from .inventory_read import Provenance

MEMORY_TYPES = (
    "fact",
    "episodic",
    "project",
    "preference",
    "skill",
    "health",
    "observation",
    "research",
    "relationship",
    "derived",
)

# Explicit truth tiers. AI output enters at ai_inference/
# ai_suggestion and stays there until a human verifies.
TRUTH_TIERS = (
    "user_fact",
    "observed",
    "external_source",
    "ai_inference",
    "ai_suggestion",
    "verified",
)

AI_TIERS = ("ai_inference", "ai_suggestion")
FACT_TIERS = ("user_fact", "verified")

MAX_MEMORIES = 5000
MAX_CONTENT_CHARS = 4000
MAX_DATA_KEYS = 20
MAX_REFS = 20


class MemoryRefusedError(ValueError):
    """Fail-closed memory validation."""


def now() -> str:
    import datetime
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def generate_memory_id() -> str:
    return f"mem_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def content_fingerprint(content: str, memory_type: str) -> str:
    canonical = f"{memory_type}\n{(content or '').strip().lower()}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class MemoryEntry(BaseModel):
    memory_id: str = Field(min_length=3, max_length=80)
    memory_type: str = Field(min_length=1, max_length=20)
    truth: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=MAX_CONTENT_CHARS)
    data: dict = Field(default_factory=dict)
    source: str = Field(default="", max_length=200)
    provenance: Provenance
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    project_ref: str = Field(default="", max_length=100)
    entity_refs: list[str] = Field(default_factory=list,
                                   max_length=MAX_REFS)
    event_refs: list[str] = Field(default_factory=list,
                                  max_length=MAX_REFS)
    derived_from: list[str] = Field(default_factory=list,
                                    max_length=MAX_REFS)
    revision: int = Field(default=1, ge=1)
    status: str = Field(default="active", max_length=20)
    expiry: str = Field(default="", max_length=80)
    created_at: str = Field(default="", max_length=80)
    observed_at: str = Field(default="", max_length=80)
    updated_at: str = Field(default="", max_length=80)


def _check_entry_fields(memory_type: str, truth: str, title: str,
                        content: str, data: dict,
                        entity_refs: list, event_refs: list,
                        derived_from: list, importance: float,
                        confidence: float) -> None:
    if memory_type not in MEMORY_TYPES:
        raise MemoryRefusedError(
            f"Unknown memory type '{memory_type}'")
    if truth not in TRUTH_TIERS:
        raise MemoryRefusedError(f"Unknown truth tier '{truth}'")
    if not isinstance(title, str) or not title.strip():
        raise MemoryRefusedError("memory title must be text")
    if not isinstance(content, str) or len(content) > \
            MAX_CONTENT_CHARS:
        raise MemoryRefusedError("memory content is capped")
    if not isinstance(data, dict) or len(data) > MAX_DATA_KEYS:
        raise MemoryRefusedError("memory data is a small object")
    for refs in (entity_refs, event_refs, derived_from):
        if not isinstance(refs, list) or len(refs) > MAX_REFS:
            raise MemoryRefusedError("memory refs are capped")
        for ref in refs:
            if not isinstance(ref, str) or not ref.strip() \
                    or len(ref) > 120:
                raise MemoryRefusedError(
                    "memory refs must be short text")
    for value in (importance, confidence):
        if not isinstance(value, (int, float)) or not \
                0.0 <= float(value) <= 1.0:
            raise MemoryRefusedError(
                "importance/confidence must be 0..1")


def new_memory(memory_type: str, title: str, *,
               truth: str = "ai_suggestion",
               content: str = "",
               data: dict | None = None,
               source: str = "",
               provenance: Provenance | None = None,
               confidence: float = 0.5,
               importance: float = 0.5,
               project_ref: str = "",
               entity_refs: list | None = None,
               event_refs: list | None = None,
               derived_from: list | None = None,
               expiry: str = "",
               observed_at: str = "") -> MemoryEntry:
    """Build one validated memory entry. AI callers land on
    ai_inference/ai_suggestion by default; fact tiers require
    an explicit human source (checked in verify/creation)."""
    entity_refs = list(entity_refs or [])
    event_refs = list(event_refs or [])
    derived_from = list(derived_from or [])
    _check_entry_fields(memory_type, truth, title, content,
                        data or {}, entity_refs, event_refs,
                        derived_from, importance, confidence)
    if truth in FACT_TIERS:
        prov = provenance or Provenance(
            source_type="user-created", creator_id="memory",
            human_verified=False)
        if prov.source_type == "ai-generated" and not \
                prov.human_verified:
            raise MemoryRefusedError(
                "AI content cannot enter a fact tier without "
                "human verification; use verify_memory()")
    stamp = now()
    return MemoryEntry(
        memory_id=generate_memory_id(),
        memory_type=memory_type, truth=truth,
        title=title.strip()[:200], content=content or "",
        data=dict(data or {}), source=str(source or "")[:200],
        provenance=provenance or Provenance(
            source_type="sensor-observed" if truth == "observed"
            else "ai-generated", creator_id="memory",
            human_verified=False),
        confidence=float(confidence),
        importance=float(importance),
        project_ref=str(project_ref or "")[:100],
        entity_refs=entity_refs, event_refs=event_refs,
        derived_from=derived_from, revision=1,
        status="active", expiry=str(expiry or ""),
        created_at=stamp, observed_at=observed_at or stamp,
        updated_at=stamp)


def verify_memory(entry: MemoryEntry, verified_by: str,
                  *, confidence: float = 0.9) -> MemoryEntry:
    """Explicit promotion to verified. Human approver required;
    AI content without a human stays where it is."""
    if not isinstance(verified_by, str) or not \
            verified_by.strip():
        raise MemoryRefusedError(
            "verification needs a human approver")
    if entry.provenance.source_type == "ai-generated" and not \
            entry.provenance.human_verified:
        raise MemoryRefusedError(
            "AI content verifies only with human_verified "
            "provenance")
    return entry.model_copy(update={
        "truth": "verified", "revision": entry.revision + 1,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "updated_at": now(),
        "provenance": entry.provenance.model_copy(update={
            "human_verified": True,
            "verified_by": verified_by.strip()[:80]})})


# -- store (chat DB, additive table) ------------------------------------

def save_memory(entry: MemoryEntry) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO memories
        (memory_id, memory_type, truth, title, content, data,
         source, provenance, confidence, importance,
         project_ref, entity_refs, event_refs, derived_from,
         revision, status, expiry, created_at, observed_at,
         updated_at, fingerprint)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
         ?, ?, ?, ?, ?, ?)
        ON CONFLICT(memory_id) DO UPDATE SET
         truth=excluded.truth, title=excluded.title,
         content=excluded.content, data=excluded.data,
         confidence=excluded.confidence,
         importance=excluded.importance,
         project_ref=excluded.project_ref,
         entity_refs=excluded.entity_refs,
         event_refs=excluded.event_refs,
         derived_from=excluded.derived_from,
         revision=excluded.revision, status=excluded.status,
         expiry=excluded.expiry, updated_at=excluded.updated_at,
         fingerprint=excluded.fingerprint""",
                     (entry.memory_id, entry.memory_type,
                      entry.truth, entry.title, entry.content,
                      dump(entry.data), entry.source,
                      dump(entry.provenance.model_dump(
                          mode="json")),
                      entry.confidence, entry.importance,
                      entry.project_ref,
                      dump(entry.entity_refs),
                      dump(entry.event_refs),
                      dump(entry.derived_from),
                      entry.revision, entry.status,
                      entry.expiry, entry.created_at,
                      entry.observed_at, entry.updated_at,
                      content_fingerprint(
                          entry.title + "\n" + entry.content,
                          entry.memory_type)))


def _row_to_entry(row) -> MemoryEntry:
    from .database import load
    return MemoryEntry(
        memory_id=row["memory_id"],
        memory_type=row["memory_type"], truth=row["truth"],
        title=row["title"], content=row["content"],
        data=load(row["data"]), source=row["source"],
        provenance=Provenance(**load(row["provenance"])),
        confidence=row["confidence"],
        importance=row["importance"],
        project_ref=row["project_ref"],
        entity_refs=load(row["entity_refs"]),
        event_refs=load(row["event_refs"]),
        derived_from=load(row["derived_from"]),
        revision=row["revision"], status=row["status"],
        expiry=row["expiry"], created_at=row["created_at"],
        observed_at=row["observed_at"],
        updated_at=row["updated_at"])


def get_memory(memory_id: str) -> MemoryEntry | None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM memories WHERE "
                         "memory_id=?", (memory_id,)).fetchone()
    return _row_to_entry(row) if row is not None else None


def delete_memory(memory_id: str) -> bool:
    """Tombstone, never a hard delete: provenance and links
    stay intact for audit."""
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        cursor = db.execute("UPDATE memories SET status="
                            "'deleted', updated_at=? WHERE "
                            "memory_id=? AND status='active'",
                            (now(), memory_id))
    return cursor.rowcount > 0


def list_memories(*, memory_type: str = "", truth: str = "",
                  project_ref: str = "",
                  include_deleted: bool = False,
                  limit: int = 50) -> list[MemoryEntry]:
    from .database import chat_connection, init_chat_database
    if memory_type and memory_type not in MEMORY_TYPES:
        raise MemoryRefusedError(
            f"Unknown memory type '{memory_type}'")
    if truth and truth not in TRUTH_TIERS:
        raise MemoryRefusedError(f"Unknown truth tier '{truth}'")
    init_chat_database()
    clauses = [] if include_deleted else ["status='active'"]
    params: list = []
    if memory_type:
        clauses.append("memory_type=?")
        params.append(memory_type)
    if truth:
        clauses.append("truth=?")
        params.append(truth)
    if project_ref:
        clauses.append("project_ref=?")
        params.append(project_ref)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with chat_connection() as db:
        rows = db.execute(
            f"SELECT * FROM memories {where} ORDER BY "
            f"updated_at DESC LIMIT ?",
            (*params, max(1, min(int(limit or 50), 200)))
        ).fetchall()
    return [_row_to_entry(row) for row in rows]


# -- retrieval ------------------------------------------------------------

def _lexical_score(query: str, entry: MemoryEntry) -> float:
    words = [word for word in query.lower().split()
             if len(word) > 2]
    if not words:
        return 0.0
    haystack = f"{entry.title}\n{entry.content}".lower()
    hits = sum(1 for word in words if word in haystack)
    return hits / len(words)


def _recency_score(entry: MemoryEntry, now_ts: float) -> float:
    try:
        import datetime
        observed = datetime.datetime.fromisoformat(
            entry.observed_at)
        if observed.tzinfo is None:
            observed = observed.replace(
                tzinfo=datetime.timezone.utc)
        age_days = max(0.0, (now_ts - observed.timestamp())
                       / 86400.0)
    except (ValueError, TypeError, OSError):
        return 0.0
    return 1.0 / (1.0 + age_days / 30.0)


def retrieve_memories(query: str, *,
                      memory_types: list | None = None,
                      project_ref: str = "",
                      truth: str = "",
                      limit: int = 10,
                      semantic: bool = False) -> list[dict]:
    """Bounded recall: lexical + recency + importance +
    project relevance. Optional semantic re-rank over the
    lexical shortlist via the existing embedding provider;
    lexical stays the fallback (no second search engine)."""
    import time as _time
    candidates: list[MemoryEntry] = []
    for memory_type in (memory_types or list(MEMORY_TYPES)):
        try:
            candidates.extend(list_memories(
                memory_type=memory_type, truth=truth,
                project_ref=project_ref, limit=60))
        except MemoryRefusedError:
            raise
    seen: set[str] = set()
    unique = [entry for entry in candidates
              if not (entry.memory_id in seen or
                      seen.add(entry.memory_id))]
    now_ts = _time.time()
    scored = []
    for entry in unique[:200]:
        lexical = _lexical_score(query or "", entry)
        if query and query.strip() and lexical <= 0.0:
            continue
        score = (0.45 * lexical
                 + 0.25 * _recency_score(entry, now_ts)
                 + 0.20 * entry.importance
                 + 0.10 * (1.0 if project_ref and
                           entry.project_ref == project_ref
                           else 0.0))
        scored.append((score, lexical, entry))
    if semantic and scored:
        try:
            scored = _semantic_rerank(query, scored)
        except Exception:
            pass
    scored.sort(key=lambda item: item[0], reverse=True)
    return [{"memory_id": entry.memory_id,
             "memory_type": entry.memory_type,
             "truth": entry.truth, "title": entry.title,
             "project_ref": entry.project_ref,
             "confidence": entry.confidence,
             "score": round(score, 4)}
            for score, _lex, entry in
            scored[:max(1, min(int(limit or 10), 50))]]


def _semantic_rerank(query: str, scored: list) -> list:
    """Re-rank the lexical shortlist with cosine similarity
    from the existing embedding provider. Bounded (≤60
    candidates); failure returns the input unchanged."""
    from .embeddings import get_embed_provider
    from .semantic_store import cosine_similarity
    provider = get_embed_provider("ollama")
    import asyncio
    texts = [f"{entry.title}\n{entry.content}"[:2000]
             for _, _, entry in scored[:60]]
    vectors = asyncio.run(
        provider.embed([query[:2000], *texts]))
    if not vectors or len(vectors) < 2:
        return scored
    query_vec, doc_vecs = vectors[0], vectors[1:]
    fused = []
    for (score, lexical, entry), vector in zip(
            scored[:len(doc_vecs)], doc_vecs):
        try:
            similarity = cosine_similarity(query_vec, vector)
        except Exception:
            similarity = 0.0
        fused.append((0.5 * score + 0.5 * max(
            0.0, similarity), lexical, entry))
    fused.extend(scored[len(doc_vecs):])
    return fused


# -- consolidation (propose, never write) ---------------------------------

def propose_consolidation(raw_texts: list[str], *,
                          project_ref: str = "",
                          source: str = "consolidation") -> dict:
    """Raw texts → candidate memories + dedup + contradiction
    flags. Returns a proposal; stores nothing. Contradictions
    are preserved for human review, never auto-resolved."""
    if not isinstance(raw_texts, list) or not raw_texts:
        raise MemoryRefusedError(
            "consolidation needs raw texts")
    if len(raw_texts) > 50:
        raise MemoryRefusedError(
            "consolidation is bounded to 50 texts")
    existing = {(entry.memory_type,
                 content_fingerprint(
                     entry.title + "\n" + entry.content,
                     entry.memory_type))
                for entry in list_memories(limit=200)}
    candidates: list[dict] = []
    duplicates = 0
    for text in raw_texts[:50]:
        if not isinstance(text, str) or not text.strip():
            continue
        fingerprint = content_fingerprint(text, "observation")
        if ("observation", fingerprint) in existing:
            duplicates += 1
            continue
        existing.add(("observation", fingerprint))
        candidate = new_memory(
            "observation", text.strip()[:120],
            truth="observed", content=text.strip()[:2000],
            source=source, project_ref=project_ref)
        candidates.append(candidate.model_dump(mode="json"))
    contradictions = detect_contradictions(
        [MemoryEntry(**item) for item in candidates])
    return {"candidates": candidates, "duplicates": duplicates,
            "contradictions": contradictions,
            "project_ref": project_ref}


def detect_contradictions(entries: list[MemoryEntry]) -> list[dict]:
    """Structural contradiction flags: same entity_ref with a
    different value for the same data key. Heuristic and
    explicit — a human decides."""
    flags: list[dict] = []
    by_key: dict[tuple, list] = {}
    for entry in entries:
        for ref in entry.entity_refs:
            for key, value in (entry.data or {}).items():
                by_key.setdefault((ref, key), []).append(
                    (entry.memory_id, value))
    for (ref, key), pairs in by_key.items():
        values = {repr(value) for _, value in pairs}
        if len(values) > 1:
            flags.append({
                "entity_ref": ref, "field": key,
                "memory_ids": [mid for mid, _ in pairs],
                "note": "same entity/field, different values; "
                        "kept side by side for review"})
    return flags
