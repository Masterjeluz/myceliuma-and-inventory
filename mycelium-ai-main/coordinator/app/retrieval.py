"""Hybrid world-model retrieval (BIG #4).

Candidates come from the existing InventoryReader (lexical search
plus a bounded browse so semantic-only matches also surface); an
optional EmbeddingProvider scores them by cosine similarity;
reciprocal-rank fusion merges both rankings; the top results expand
one bounded hop over existing relationships.

Modes: lexical (substring only, always available), semantic
(embeddings only, fail-closed when unavailable), hybrid (both,
with automatic lexical fallback — Mycelium never fails just
because an embedding model is missing).

Fail-fast probe: hybrid first embeds the query alone. When that
single call fails, retrieval degrades to the exact legacy
lexical path (search only — no browse, no graph) instead of
wasting enrichment calls. Only a working semantic runtime
unlocks browse candidates and relationship expansion.

Every returned record carries its audit trail: match_type
(semantic/lexical/relationship), a ranking score (ordering
signal, NOT a truth probability), and a why-string with the raw
ranks. Provenance and human_verified pass through untouched, so
FACT (verified world rows) never silently mixes with ADVICE.

Bounds (tested): candidates <= 60, expansion top-5, depth 1|2,
total results <= 50. Graph errors on one seed never kill the
whole retrieval (that seed is skipped, the rest stands).
"""

from .embeddings import EmbeddingUnavailable
from .semantic_store import (
    content_fingerprint,
    cosine_similarity,
    lookup_vector,
    store_vector,
)

MAX_CANDIDATES = 60
MAX_RESULTS = 50
EXPAND_TOP = 5
RRF_K = 60
GRAPH_DEPTHS = (1, 2)
VALID_MODES = frozenset({"lexical", "semantic", "hybrid"})


def _record_text(record: dict) -> str:
    title = str(record.get("title", "") or "")
    snippet = str(record.get("snippet", "") or "")
    return f"{title}\n{snippet}".strip()[:2000]


def _rrf(rank: int) -> float:
    return 1.0 / (RRF_K + rank)


async def hybrid_retrieve(query: str, reader, embedder=None, *,
                          mode: str = "hybrid", depth: int = 1,
                          limit: int = 20,
                          expand_top: int = EXPAND_TOP) -> dict:
    """Ranked world context for one query. See module docstring."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Retrieval query must be non-empty text")
    if mode not in VALID_MODES:
        raise ValueError(f"Unknown retrieval mode '{mode}'")
    if isinstance(depth, bool) or depth not in GRAPH_DEPTHS:
        raise ValueError("Expansion depth must be 1 or 2")
    limit = max(1, min(int(limit), MAX_RESULTS))

    found = await reader.search(query.strip()[:200])
    candidates: list[dict] = []
    seen: set[str] = set()
    lexical_rank: dict[str, int] = {}
    for record in list(found.results):
        entity_id = str(record.entity_id)
        if entity_id in seen:
            continue
        seen.add(entity_id)
        lexical_rank[entity_id] = len(candidates)
        candidates.append(record)
        if len(candidates) >= MAX_CANDIDATES:
            break

    want_semantic = mode in ("semantic", "hybrid") and embedder is not None
    semantic_rank: dict[str, int] = {}
    semantic_available = False
    embed_model = ""
    query_vector: list[float] | None = None
    if want_semantic:
        try:
            query_vector = (await embedder.embed(
                [query.strip()[:2000]]))[0]
            embed_model = getattr(embedder, "model", "")
            semantic_available = True
        except EmbeddingUnavailable:
            if mode == "semantic":
                raise
            semantic_available = False
    if semantic_available:
        try:
            for record in list((await reader.browse(None)).results):
                entity_id = str(record.entity_id)
                if entity_id in seen:
                    continue
                seen.add(entity_id)
                lexical_rank[entity_id] = len(candidates)
                candidates.append(record)
                if len(candidates) >= MAX_CANDIDATES:
                    break
            ranked = await _semantic_rank_vectors(
                query_vector, candidates, embedder)
            for position, entity_id in enumerate(ranked):
                semantic_rank[entity_id] = position
        except EmbeddingUnavailable:
            if mode == "semantic":
                raise
            semantic_available = False
            semantic_rank = {}

    fused: list[tuple[float, int, int, str, str]] = []
    for entity_id in seen:
        lex_rank = lexical_rank.get(entity_id, MAX_CANDIDATES)
        sem_rank = semantic_rank.get(entity_id, MAX_CANDIDATES)
        score = _rrf(lex_rank)
        parts = [f"lexical_rank={lexical_rank.get(entity_id, '-')}", ]
        if semantic_available and entity_id in semantic_rank:
            score += _rrf(sem_rank)
            parts.append(f"semantic_rank={sem_rank}")
            match = ("semantic" if sem_rank <= lex_rank else "lexical")
        else:
            match = "lexical"
        parts.append(f"rrf={score:.4f}")
        fused.append((score, sem_rank, lex_rank, entity_id,
                      match + ";" + " ".join(parts)))
    # Deterministic order: fused score, then semantic rank (semantic
    # wins ties in hybrid mode), then lexical rank. No set-order
    # dependence anywhere.
    fused.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
    by_id = {str(record.entity_id): record for record in candidates}
    results: list[dict] = []
    for score, _, _, entity_id, why in fused:
        record = by_id[entity_id]
        match_type = why.split(";", 1)[0]
        results.append(_enriched(record, match_type, round(score, 4),
                                "ranking signal, not truth probability; "
                                + why.split(";", 1)[1]))
        if len(results) >= limit:
            break

    expansions = 0
    # Relationship expansion is a hybrid-only enrichment: the legacy
    # lexical path stays exactly search-only (call-identical).
    if depth and results and semantic_available:
        expansions = await _expand_relationships(
            reader, results, depth, limit, expand_top)

    return {
        "query": query.strip()[:200],
        "mode_requested": mode,
        "mode_used": ("hybrid" if semantic_available
                      else "lexical") if mode == "hybrid" else mode,
        "semantic_available": semantic_available,
        "embed_model": embed_model,
        "results": results[:limit],
        "expansions": expansions,
    }


async def _semantic_rank_vectors(query_vector: list[float],
                                 candidates: list,
                                 embedder) -> list[str]:
    """Cosine order over cached + freshly embedded vectors.

    The query vector comes from the fail-fast probe (no second
    query call). Candidate misses embed in ONE batch call.
    """
    model = getattr(embedder, "model", "") or "unknown"
    dim = len(query_vector)
    texts: list[str] = []
    pending: list = []
    scored: list[tuple[float, str]] = []
    for record in candidates:
        provenance = record.provenance
        prov_dict = (provenance.model_dump(mode="json")
                     if hasattr(provenance, "model_dump") else {})
        fingerprint = content_fingerprint(
            record.entity_type, str(record.entity_id), record.title,
            record.snippet, prov_dict, model)
        cached = lookup_vector(record.entity_type,
                               str(record.entity_id), fingerprint,
                               model, dim)
        if cached is not None:
            scored.append((cosine_similarity(query_vector, cached),
                           str(record.entity_id)))
        else:
            pending.append((record, fingerprint))
            texts.append(_record_text(_as_dict(record)))
    if pending:
        vectors = await embedder.embed(texts)
        for (record, fingerprint), vector in zip(pending, vectors):
            if len(vector) != dim:
                continue
            store_vector(record.entity_type, str(record.entity_id),
                         fingerprint, model, vector)
            scored.append((cosine_similarity(query_vector, vector),
                           str(record.entity_id)))
    scored.sort(key=lambda entry: entry[0], reverse=True)
    return [entity_id for _, entity_id in scored]


def _as_dict(record) -> dict:
    if isinstance(record, dict):
        return record
    return {"title": getattr(record, "title", ""),
            "snippet": getattr(record, "snippet", "")}


def _enriched(record, match_type: str, score: float,
              why: str) -> dict:
    provenance = record.provenance
    prov_dict = (provenance.model_dump(mode="json")
                 if hasattr(provenance, "model_dump") else {})
    return {
        "entity_type": record.entity_type,
        "entity_id": str(record.entity_id),
        "title": record.title,
        "snippet": record.snippet,
        "provenance": prov_dict,
        "match_type": match_type,
        "score": score,
        "why": why,
    }


async def _expand_relationships(reader, results: list, depth: int,
                                limit: int, expand_top: int) -> int:
    present = {entry["entity_id"] for entry in results}
    added = 0
    for entry in list(results)[:max(1, expand_top)]:
        if len(results) >= limit:
            break
        try:
            graph = await reader.graph(entry["entity_id"], depth)
        except Exception:
            continue
        nodes = {node.entity_id: node for node in graph.nodes}
        for edge in graph.edges:
            for target_id in (edge.from_id, edge.to_id):
                if target_id in present or len(results) >= limit:
                    continue
                node = nodes.get(target_id)
                if node is None:
                    continue
                provenance = node.provenance
                prov_dict = (provenance.model_dump(mode="json")
                             if hasattr(provenance, "model_dump") else {})
                present.add(target_id)
                added += 1
                results.append({
                    "entity_type": node.entity_type,
                    "entity_id": str(node.entity_id),
                    "title": node.title,
                    "snippet": "",
                    "provenance": prov_dict,
                    "match_type": "relationship",
                    "score": round(entry["score"] * 0.5, 4),
                    "why": (f"via {edge.predicate} from "
                            f"{entry['entity_id']}; derived rank, "
                            f"not truth probability"),
                })
    return added
