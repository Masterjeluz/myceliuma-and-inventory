"""Embedding cache in the chat/agent database (BIG #4).

Derived index, same discipline as FTS in INVENTory: the world model
stays source of truth, vectors are rebuildable cache. Identity of
one vector:

- source entity (type + id)
- content fingerprint (title + snippet + provenance signal)
- embedding model name
- dimension
- stored_at

Staleness is structural, never silent: a lookup only hits when the
fingerprint recomputed from the CURRENT record matches the stored
one. Changed source -> fingerprint mismatch -> miss -> re-embed.
A dimension mismatch (model swapped under the same name) is also a
miss. Pruning keeps the table bounded (latest N rows per model).

Vectors are packed little-endian float32 blobs (struct only — no
numpy). Cosine similarity is plain stdlib math.
"""

import hashlib
import struct
import time

from .database import chat_connection, init_chat_database

MAX_ROWS_PER_MODEL = 2000
MAX_DIM = 4096


def content_fingerprint(entity_type: str, entity_id: str, title: str,
                        snippet: str, provenance: dict,
                        model: str) -> str:
    """Fingerprint of everything one vector claims to represent."""
    prov = provenance if isinstance(provenance, dict) else {}
    canonical = "|".join([
        str(entity_type or ""), str(entity_id or ""),
        str(title or "")[:500], str(snippet or "")[:1000],
        str(prov.get("source_type", "unknown")),
        str(bool(prov.get("human_verified", False))),
        str(model or ""),
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def pack_vector(vector: list[float]) -> bytes:
    if not vector or len(vector) > MAX_DIM:
        raise ValueError("Vector size out of range")
    return struct.pack(f"<{len(vector)}f", *[float(x) for x in vector])


def unpack_vector(blob: bytes, dim: int) -> list[float] | None:
    if not isinstance(blob, (bytes, bytearray)):
        return None
    if not 1 <= dim <= MAX_DIM:
        return None
    if len(blob) != dim * 4:
        return None
    try:
        return list(struct.unpack(f"<{dim}f", bytes(blob)))
    except struct.error:
        return None


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = sum(a * a for a in left) ** 0.5
    norm_right = sum(b * b for b in right) ** 0.5
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_left * norm_right)))


def lookup_vector(entity_type: str, entity_id: str, fingerprint: str,
                  model: str, dim: int) -> list[float] | None:
    """Hit only on full identity match; everything else is a miss."""
    init_chat_database()
    with chat_connection() as db:
        row = db.execute(
            """SELECT vector, fingerprint, dim FROM semantic_vectors
            WHERE entity_type=? AND entity_id=? AND model=?""",
            (entity_type, entity_id, model)).fetchone()
    if row is None:
        return None
    if row["fingerprint"] != fingerprint or row["dim"] != dim:
        return None
    return unpack_vector(row["vector"], dim)


def store_vector(entity_type: str, entity_id: str, fingerprint: str,
                 model: str, vector: list[float]) -> None:
    dim = len(vector)
    blob = pack_vector(vector)
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO semantic_vectors
        (entity_type, entity_id, fingerprint, model, dim, vector,
         updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_type, entity_id, model) DO UPDATE SET
        fingerprint=excluded.fingerprint, dim=excluded.dim,
        vector=excluded.vector, updated_at=excluded.updated_at""",
                   (entity_type, entity_id, fingerprint, model, dim,
                    blob, int(time.time())))
        db.execute(
            """DELETE FROM semantic_vectors WHERE rowid NOT IN (
            SELECT rowid FROM semantic_vectors WHERE model=?
            ORDER BY updated_at DESC LIMIT ?) AND model=?""",
            (model, MAX_ROWS_PER_MODEL, model))


def vector_stats() -> dict:
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute(
            """SELECT model, COUNT(*) AS n, MAX(updated_at) AS latest
            FROM semantic_vectors GROUP BY model""").fetchall()
    return {row["model"]: {"count": row["n"], "latest": row["latest"]}
            for row in rows}
