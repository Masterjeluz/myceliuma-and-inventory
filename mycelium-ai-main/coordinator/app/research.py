"""Research + universal ingestion (BIG #11-15, Phase 3).

SOURCE → FETCH → EXTRACT → NORMALIZE → UNDERSTAND →
DEDUPLICATE → RELATE → PROPOSE → APPROVE → STORE.

Sources are adapters; no source writes to INVENTory
directly. Content hashes deduplicate. Claims always cite
sources (claim → source → evidence → confidence →
interpretation); "AI says X" is never a fact.

Instagram: only legal paths. No scraping, no session
hijacking — the adapter accepts manual exports (plus a
mock for tests) and every import is labelled manual-export.
Live Instagram integration is UNAVAILABLE until a real,
user-owned API path exists.
"""

import hashlib
import secrets
import time

from pydantic import BaseModel, Field

from .inventory_read import Provenance

SOURCE_TYPES = (
    "web",
    "github",
    "youtube",
    "document",
    "image",
    "camera",
    "rss",
    "social",
    "instagram",
    "manual_export",
    "manual",
)

SOURCE_STAGES = (
    "received",
    "extracted",
    "proposed",
    "approved",
    "stored",
    "rejected",
)

INSTAGRAM_STATUS = {
    "state": "UNAVAILABLE",
    "detail": "no live Instagram integration: only manual "
              "exports (user-owned collections) plus a mock "
              "for tests. No scraping, no credential use.",
    "import_modes": ["manual_export", "mock"],
}

MAX_CONTENT_CHARS = 20000
MAX_TOPICS = 20


class ResearchRefusedError(ValueError):
    """Fail-closed research validation."""


def now() -> str:
    import datetime
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def generate_source_id() -> str:
    return f"src_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def generate_record_id() -> str:
    return f"rsch_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def content_hash_for(text: str) -> str:
    return hashlib.sha256(
        (text or "").encode("utf-8")).hexdigest()


class SourceRecord(BaseModel):
    source_id: str = Field(min_length=3, max_length=80)
    source_type: str = Field(min_length=1, max_length=20)
    external_id: str = Field(default="", max_length=200)
    reference: str = Field(default="", max_length=500)
    title: str = Field(min_length=1, max_length=300)
    author: str = Field(default="", max_length=200)
    content: str = Field(default="", max_length=MAX_CONTENT_CHARS)
    content_hash: str = Field(default="", max_length=80)
    topics: list[str] = Field(default_factory=list,
                              max_length=MAX_TOPICS)
    entities: list[str] = Field(default_factory=list,
                                max_length=MAX_TOPICS)
    status: str = Field(default="received", max_length=20)
    provenance: Provenance
    captured_at: str = Field(default="", max_length=80)
    published_at: str = Field(default="", max_length=80)


class ResearchClaim(BaseModel):
    claim: str = Field(min_length=1, max_length=1000)
    source_ids: list[str] = Field(min_length=1, max_length=10)
    evidence: str = Field(default="", max_length=2000)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    interpretation: str = Field(default="", max_length=1000)


class ResearchRecord(BaseModel):
    record_id: str = Field(min_length=3, max_length=80)
    question: str = Field(min_length=1, max_length=1000)
    claims: list[ResearchClaim] = Field(default_factory=list,
                                        max_length=30)
    source_ids: list[str] = Field(default_factory=list,
                                  max_length=30)
    synthesis: str = Field(default="", max_length=5000)
    status: str = Field(default="stored", max_length=20)
    provenance: Provenance
    created_at: str = Field(default="", max_length=80)
    updated_at: str = Field(default="", max_length=80)


def _check_reference(source_type: str, reference: str) -> str:
    text = str(reference or "")
    if len(text) > 500:
        raise ResearchRefusedError("reference too long")
    if any(char.isspace() for char in text):
        raise ResearchRefusedError(
            "reference must be one token (URL or id)")
    lowered = text.lower()
    if source_type == "instagram" and text and not (
            lowered.startswith("manual-export:") or
            lowered.startswith("mock:")):
        raise ResearchRefusedError(
            "instagram references must be manual-export: or "
            "mock: ids — no live URLs, no scraped links")
    return text


def new_source(source_type: str, title: str, *,
               content: str = "",
               external_id: str = "",
               reference: str = "",
               author: str = "",
               topics: list | None = None,
               entities: list | None = None,
               published_at: str = "",
               provenance: Provenance | None = None
               ) -> SourceRecord:
    """Receive one source. Fails closed on type, size and
    (for instagram) reference shape."""
    if source_type not in SOURCE_TYPES:
        raise ResearchRefusedError(
            f"Unknown source type '{source_type}'")
    if not isinstance(title, str) or not title.strip():
        raise ResearchRefusedError("source needs a title")
    if not isinstance(content, str) or len(content) > \
            MAX_CONTENT_CHARS:
        raise ResearchRefusedError("content is capped")
    for label, values in (("topics", topics or []),
                          ("entities", entities or [])):
        if len(values) > MAX_TOPICS or any(
                not isinstance(item, str) or not item.strip()
                or len(item) > 80 for item in values):
            raise ResearchRefusedError(
                f"{label} must be short text, capped")
    stamp = now()
    body = content or ""
    return SourceRecord(
        source_id=generate_source_id(), source_type=source_type,
        external_id=str(external_id or "")[:200],
        reference=_check_reference(source_type, reference),
        title=title.strip()[:300],
        author=str(author or "")[:200], content=body,
        content_hash=content_hash_for(body),
        topics=[item.strip()[:80] for item in (topics or [])],
        entities=[item.strip()[:80] for item in (entities or [])],
        status="received",
        provenance=provenance or Provenance(
            source_type="external-source"
            if source_type != "manual" else "user-created",
            creator_id=f"research:{source_type}",
            human_verified=False),
        captured_at=stamp, published_at=str(published_at or ""))


def extract_source(entry: SourceRecord) -> SourceRecord:
    """EXTRACT+NORMALIZE: whitespace-normalized excerpt stats
    and keyword topics the caller supplied stay; nothing is
    invented. received → extracted."""
    if entry.status != "received":
        raise ResearchRefusedError(
            "extract runs once on received sources")
    words = entry.content.split()
    excerpt = " ".join(words[:60])
    topics = list(entry.topics)
    if len(words) > 500 and "longform" not in topics \
            and len(topics) < MAX_TOPICS:
        topics.append("longform")
    return entry.model_copy(update={
        "status": "extracted",
        "content": entry.content,
        "topics": topics,
        "provenance": entry.provenance.model_copy(update={
            "notes": ((entry.provenance.notes or "") +
                      " | excerpt: "
                      + excerpt[:200]).strip(" |")[:500]})})


def save_source(entry: SourceRecord) -> bool:
    """Store unless the content hash already exists (dedup).
    Returns True on store, False on duplicate."""
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT source_id FROM "
                         "research_sources WHERE content_hash=? "
                         "LIMIT 1",
                         (entry.content_hash,)).fetchone()
        if row is not None:
            return False
        db.execute("""INSERT INTO research_sources
        (source_id, source_type, external_id, reference,
         title, author, content, content_hash, topics,
         provenance, status, captured_at, published_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO NOTHING""",
                     (entry.source_id, entry.source_type,
                      entry.external_id, entry.reference,
                      entry.title, entry.author, entry.content,
                      entry.content_hash, dump(entry.topics),
                      dump(entry.provenance.model_dump(
                          mode="json")),
                      entry.status, entry.captured_at,
                      entry.published_at))
    return True


def _row_to_source(row) -> SourceRecord:
    from .database import load
    return SourceRecord(
        source_id=row["source_id"],
        source_type=row["source_type"],
        external_id=row["external_id"],
        reference=row["reference"], title=row["title"],
        author=row["author"], content=row["content"],
        content_hash=row["content_hash"],
        topics=load(row["topics"]), entities=[],
        status=row["status"],
        provenance=Provenance(**load(row["provenance"])),
        captured_at=row["captured_at"],
        published_at=row["published_at"])


def get_source(source_id: str) -> SourceRecord | None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM research_sources WHERE "
                         "source_id=?", (source_id,)).fetchone()
    return _row_to_source(row) if row is not None else None


def get_source_by_hash(content_hash: str) -> SourceRecord | None:
    """Find a stored source by content hash (repeat-research
    reuse). Empty hash never matches."""
    if not content_hash:
        return None
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM research_sources WHERE "
                         "content_hash=? LIMIT 1",
                         (content_hash,)).fetchone()
    return _row_to_source(row) if row is not None else None


def list_sources(*, source_type: str = "",
                 limit: int = 50) -> list[SourceRecord]:
    from .database import chat_connection, init_chat_database
    if source_type and source_type not in SOURCE_TYPES:
        raise ResearchRefusedError(
            f"Unknown source type '{source_type}'")
    init_chat_database()
    with chat_connection() as db:
        if source_type:
            rows = db.execute(
                "SELECT * FROM research_sources WHERE "
                "source_type=? ORDER BY captured_at DESC "
                "LIMIT ?", (source_type, max(
                    1, min(int(limit or 50), 200)))).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM research_sources ORDER BY "
                "captured_at DESC LIMIT ?",
                (max(1, min(int(limit or 50), 200)),)).fetchall()
    return [_row_to_source(row) for row in rows]


def advance_source(source_id: str, to_stage: str, *,
                   approved_by: str = "") -> SourceRecord:
    """Move one stage forward. approved/stored need a human
    approver; stages never skip."""
    order = list(SOURCE_STAGES)
    if to_stage not in order:
        raise ResearchRefusedError(
            f"Unknown stage '{to_stage}'")
    entry = get_source(source_id)
    if entry is None:
        raise ResearchRefusedError("source not found")
    current_index = order.index(entry.status) \
        if entry.status in order else -1
    if order.index(to_stage) != current_index + 1:
        raise ResearchRefusedError(
            "stages advance one step at a time")
    if to_stage in ("approved", "stored") and not \
            str(approved_by or "").strip():
        raise ResearchRefusedError(
            f"stage '{to_stage}' needs a human approver")
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("UPDATE research_sources SET status=? WHERE "
                   "source_id=?", (to_stage, source_id))
    return get_source(source_id)


def new_research_record(question: str,
                        claims: list[dict], *,
                        synthesis: str = "",
                        provenance: Provenance | None = None
                        ) -> ResearchRecord:
    """QUESTION → claims → synthesis. Every claim cites ≥1
    stored source; uncited claims refuse."""
    if not isinstance(question, str) or not question.strip():
        raise ResearchRefusedError("research needs a question")
    if not isinstance(claims, list) or not claims or \
            len(claims) > 30:
        raise ResearchRefusedError(
            "research needs 1..30 cited claims")
    parsed: list[ResearchClaim] = []
    cited: set[str] = set()
    for raw in claims:
        try:
            claim = raw if isinstance(raw, ResearchClaim) \
                else ResearchClaim(**raw)
        except Exception as error:
            raise ResearchRefusedError(
                f"bad claim: {error}")
        for source_id in claim.source_ids:
            if get_source(source_id) is None:
                raise ResearchRefusedError(
                    f"claim cites unknown source {source_id}")
            cited.add(source_id)
        parsed.append(claim)
    stamp = now()
    return ResearchRecord(
        record_id=generate_record_id(),
        question=question.strip()[:1000], claims=parsed,
        source_ids=sorted(cited),
        synthesis=str(synthesis or "")[:5000],
        status="stored",
        provenance=provenance or Provenance(
            source_type="ai-generated",
            creator_id="research",
            human_verified=False,
            notes="claims cite sources; synthesis is "
                  "interpretation, not fact"),
        created_at=stamp, updated_at=stamp)


def save_research_record(record: ResearchRecord) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO research_records
        (record_id, question, claims, source_ids, synthesis,
         provenance, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(record_id) DO NOTHING""",
                     (record.record_id, record.question,
                      dump([claim.model_dump(mode="json")
                            for claim in record.claims]),
                      dump(record.source_ids), record.synthesis,
                      dump(record.provenance.model_dump(
                          mode="json")),
                      record.status, record.created_at,
                      record.updated_at))


def get_research_record(record_id: str) -> ResearchRecord | None:
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM research_records WHERE "
                         "record_id=?", (record_id,)).fetchone()
    if row is None:
        return None
    return ResearchRecord(
        record_id=row["record_id"], question=row["question"],
        claims=[ResearchClaim(**item)
                for item in load(row["claims"])],
        source_ids=load(row["source_ids"]),
        synthesis=row["synthesis"],
        provenance=Provenance(**load(row["provenance"])),
        status=row["status"], created_at=row["created_at"],
        updated_at=row["updated_at"])


# -- instagram: manual-export ingestion -----------------------------------

def instagram_export_to_sources(export: dict, *,
                                collection: str = ""
                                ) -> list[SourceRecord]:
    """Map a user-owned manual export to source records.
    Bounded, labelled, no network. Anything that is not an
    explicit manual export refuses."""
    if not isinstance(export, dict):
        raise ResearchRefusedError("export must be an object")
    if str(export.get("export_kind", "")) != "manual_export":
        raise ResearchRefusedError(
            "only explicit manual exports ingest; live "
            "Instagram access is unavailable")
    items = export.get("items", [])
    if not isinstance(items, list) or len(items) > 100:
        raise ResearchRefusedError(
            "export holds 0..100 items")
    # The mock flag survives ingestion: mock exports stay
    # visibly mock down to storage, never laundered into
    # "user-owned manual export".
    mocked = bool(export.get("mock"))
    sources = []
    for item in items[:100]:
        if not isinstance(item, dict):
            continue
        caption = str(item.get("caption", ""))[:2000]
        sources.append(new_source(
            "instagram",
            str(item.get("title", "Instagram import"))[:300],
            content=caption,
            external_id=str(item.get("id", ""))[:200],
            reference=f"{'mock' if mocked else 'manual-export'}:"
                      f"{collection or item.get('collection', '')}"
                      f":{item.get('id', '')}"[:500],
            author=str(item.get("author", ""))[:200],
            topics=[str(topic)[:80]
                    for topic in (item.get("topics") or [])][:20],
            provenance=Provenance(
                source_type="external-source",
                creator_id="instagram:mock" if mocked else
                "instagram:manual-export",
                human_verified=False,
                notes="mock export for tests; not a live "
                      "integration" if mocked else
                      "user-owned manual export; content is "
                      "inspiration, not fact")))
    return sources


def mock_instagram_export(count: int = 3) -> dict:
    """Deterministic mock export for tests/dev. Labelled mock;
    never presented as a live integration."""
    topics = ["3d-printing", "solarpunk", "vegan-food"]
    return {
        "export_kind": "manual_export",
        "mock": True,
        "items": [{
            "id": f"mock-ig-{index + 1}",
            "title": f"Mock inspiration {index + 1}",
            "author": "mock-creator",
            "collection": topics[index % len(topics)],
            "caption": f"Mock saved post about "
                       f"{topics[index % len(topics)]}",
            "topics": [topics[index % len(topics)]],
        } for index in range(max(1, min(int(count), 10)))],
    }
