"""Semantic retrieval tests (BIG #4, §21).

Provider contract, storage identity/staleness, hybrid ranking,
fallback, depth limits, provenance. Ollama HTTP is faked with
httpx.MockTransport; ranking uses a deterministic keyword
embedder — no real model anywhere.
"""

import httpx
import pytest

from coordinator.app.embeddings import (
    EmbeddingRefusedError,
    EmbeddingUnavailable,
    OllamaEmbeddingProvider,
    UnavailableEmbeddingProvider,
    check_texts,
    check_vectors,
    get_embed_provider,
)
from coordinator.app.inventory_read import Provenance, SearchResult
from coordinator.app.retrieval import hybrid_retrieve
from coordinator.app.semantic_store import (
    content_fingerprint,
    cosine_similarity,
    lookup_vector,
    pack_vector,
    store_vector,
    unpack_vector,
    vector_stats,
)


def ok_embed_handler(request):
    import json
    count = len(json.loads(request.content)["input"])
    return httpx.Response(200, json={
        "embeddings": [[0.1 * (i + 1), 0.2, 0.3] for i in range(count)]})


def make_result(entity_id="obj_1", title="Arduino Uno",
                snippet="bordje", kind="object"):
    return SearchResult(
        entity_type=kind, entity_id=entity_id, title=title,
        snippet=snippet,
        provenance=Provenance(source_type="user-created",
                              creator_id="jelles", human_verified=True),
        details={})


class KeywordEmbedder:
    """Deterministic test vectors: arduino->[1,.1,.1], sensor->[..]."""

    model = "fake-test"

    async def embed(self, texts):
        vectors = []
        for text in texts:
            lowered = text.lower()
            if "arduino" in lowered:
                vectors.append([1.0, 0.1, 0.1])
            elif "sensor" in lowered:
                vectors.append([0.1, 1.0, 0.1])
            else:
                vectors.append([0.2, 0.2, 0.9])
        return vectors


class FakeReader:
    def __init__(self, search_hits=None, browse_hits=None,
                 graph_map=None):
        self.search_hits = search_hits or []
        self.browse_hits = browse_hits or []
        self.graph_map = graph_map or {}
        self.calls = []

    async def search(self, q, type=None):
        self.calls.append(("search", q, type))
        from coordinator.app.inventory_read import SearchResponse
        return SearchResponse(query=q, results=list(self.search_hits),
                              total=len(self.search_hits))

    async def browse(self, type=None):
        self.calls.append(("browse", type))
        from coordinator.app.inventory_read import SearchResponse
        return SearchResponse(query="", results=list(self.browse_hits),
                              total=len(self.browse_hits))

    async def graph(self, entity_id, depth=1):
        self.calls.append(("graph", entity_id, depth))
        from coordinator.app.inventory_read import (
            GraphEdge, GraphNode, GraphResponse)
        nodes, edges = self.graph_map.get(entity_id, ([], []))
        return GraphResponse(entity_id=entity_id, depth=depth,
                             nodes=nodes, edges=edges)


def run(coro):
    import asyncio
    return asyncio.run(coro)


# -- provider contract --------------------------------------------------

def test_ollama_embed_ok():
    provider = OllamaEmbeddingProvider(
        transport=httpx.MockTransport(ok_embed_handler))
    vectors = run(provider.embed(["hallo", "wereld"]))
    assert len(vectors) == 2 and len(vectors[0]) == 3


def test_ollama_embed_missing_model_is_unavailable():
    def gone(request):
        return httpx.Response(404, json={"error": "not found"})

    provider = OllamaEmbeddingProvider(
        transport=httpx.MockTransport(gone))
    with pytest.raises(EmbeddingUnavailable) as caught:
        run(provider.embed(["x"]))
    assert "ollama pull" in str(caught.value)


def test_ollama_embed_connection_loss_is_unavailable():
    def down(request):
        raise httpx.ConnectError("nope")

    with pytest.raises(EmbeddingUnavailable):
        run(OllamaEmbeddingProvider(
            transport=httpx.MockTransport(down)).embed(["x"]))


def test_embed_refused_inputs():
    provider = OllamaEmbeddingProvider(
        transport=httpx.MockTransport(ok_embed_handler))
    with pytest.raises(EmbeddingRefusedError):
        run(provider.embed([]))
    with pytest.raises(EmbeddingRefusedError):
        run(provider.embed(["x"] * 65))
    with pytest.raises(EmbeddingRefusedError):
        OllamaEmbeddingProvider(base_url="http://example.com")
    with pytest.raises(EmbeddingRefusedError):
        get_embed_provider("quantum")


def test_unavailable_provider_always_fails_closed():
    with pytest.raises(EmbeddingUnavailable):
        run(UnavailableEmbeddingProvider().embed(["x"]))


def test_zero_vectors_refused():
    with pytest.raises(EmbeddingRefusedError):
        check_vectors([[0.0, 0.0]])
    with pytest.raises(EmbeddingRefusedError):
        check_texts([])


# -- storage identity & staleness ----------------------------------------

def test_pack_roundtrip_and_cosine():
    blob = pack_vector([1.0, 0.0, -2.5])
    assert unpack_vector(blob, 3) == pytest.approx([1.0, 0.0, -2.5])
    assert unpack_vector(blob, 2) is None
    assert unpack_vector(b"xx", 3) is None
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([], [1]) == 0.0


def test_fingerprint_hit_and_stale_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "sem.db"))
    fingerprint = content_fingerprint("object", "obj_1", "Arduino",
                                      "bord", {"source_type": "user-created",
                                               "human_verified": True},
                                      "fake-test")
    assert lookup_vector("object", "obj_1", fingerprint, "fake-test",
                         3) is None
    store_vector("object", "obj_1", fingerprint, "fake-test",
                 [1.0, 0.0, 0.0])
    assert lookup_vector("object", "obj_1", fingerprint, "fake-test",
                         3) == pytest.approx([1.0, 0.0, 0.0])
    # changed source content -> new fingerprint -> miss (never stale)
    changed = content_fingerprint("object", "obj_1", "Arduino MEGA",
                                  "bord", {"source_type": "user-created",
                                           "human_verified": True},
                                  "fake-test")
    assert changed != fingerprint
    assert lookup_vector("object", "obj_1", changed, "fake-test",
                         3) is None
    # same fingerprint, other model/dim -> miss
    assert lookup_vector("object", "obj_1", fingerprint, "other",
                         3) is None
    assert lookup_vector("object", "obj_1", fingerprint, "fake-test",
                         5) is None
    assert vector_stats()["fake-test"]["count"] == 1


# -- hybrid retrieval -----------------------------------------------------

def test_lexical_only_is_call_identical(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "sem2.db"))
    reader = FakeReader(search_hits=[make_result()])
    result = run(hybrid_retrieve("arduino", reader, None,
                                 mode="lexical"))
    assert result["mode_used"] == "lexical"
    assert reader.calls == [("search", "arduino", None)]
    assert result["results"][0]["match_type"] == "lexical"
    assert result["results"][0]["provenance"]["human_verified"] is True


def test_hybrid_ranks_semantic_first(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "sem3.db"))
    sensor = make_result("sns_9", "Temperatuursensor", "sensor dht22",
                         kind="sensor")
    board = make_result("obj_1", "Arduino Uno", "bordje")
    reader = FakeReader(search_hits=[sensor, board],
                        browse_hits=[board])
    result = run(hybrid_retrieve("arduino uno", reader,
                                 KeywordEmbedder(), mode="hybrid"))
    assert result["mode_used"] == "hybrid"
    assert result["semantic_available"] is True
    assert result["results"][0]["entity_id"] == "obj_1"
    assert result["results"][0]["match_type"] == "semantic"
    assert any(call[0] == "browse" for call in reader.calls)


def test_hybrid_falls_back_when_semantic_down(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "sem4.db"))
    reader = FakeReader(search_hits=[make_result()])
    result = run(hybrid_retrieve(
        "arduino", reader, UnavailableEmbeddingProvider(),
        mode="hybrid"))
    assert result["mode_used"] == "lexical"
    assert result["semantic_available"] is False
    assert reader.calls == [("search", "arduino", None)]
    assert len(result["results"]) == 1


def test_semantic_mode_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "sem5.db"))
    with pytest.raises(EmbeddingUnavailable):
        run(hybrid_retrieve("x", FakeReader(), UnavailableEmbeddingProvider(),
                            mode="semantic"))


def test_relationship_expansion_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "sem6.db"))
    from coordinator.app.inventory_read import (
        GraphEdge, GraphNode, Provenance as Prov)
    parent = make_result("obj_1", "Arduino Uno", "arduino bord")
    neighbour = GraphNode(entity_type="project", entity_id="proj_7",
                          title="Weerstation",
                          provenance=Prov(human_verified=False))
    parent_node = GraphNode(entity_type="object", entity_id="obj_1",
                            title="Arduino Uno", provenance=Prov())
    edge = GraphEdge(id="rel_1", from_id="obj_1", predicate="used_in",
                     to_id="proj_7", provenance=Prov())
    reader = FakeReader(search_hits=[parent],
                        graph_map={"obj_1": ([parent_node, neighbour],
                                             [edge])})
    result = run(hybrid_retrieve("arduino", reader, KeywordEmbedder(),
                                 mode="hybrid", depth=1, limit=10))
    kinds = {entry["entity_id"]: entry["match_type"]
             for entry in result["results"]}
    assert kinds["proj_7"] == "relationship"
    assert result["expansions"] == 1
    with pytest.raises(ValueError):
        run(hybrid_retrieve("x", reader, None, depth=5))
    with pytest.raises(ValueError):
        run(hybrid_retrieve("  ", reader, None))
    with pytest.raises(ValueError):
        run(hybrid_retrieve("x", reader, None, mode="telepathie"))


def test_scores_are_ranking_signals_not_truth(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "sem7.db"))
    reader = FakeReader(search_hits=[make_result(), make_result(
        "obj_2", "Moer M8", "moertje")])
    result = run(hybrid_retrieve("arduino", reader, KeywordEmbedder(),
                                 mode="hybrid", limit=2))
    assert len(result["results"]) == 2
    for entry in result["results"]:
        assert "not truth probability" in entry["why"]
        assert entry["score"] >= 0


def _api_client(tmp_path, monkeypatch, reader=None, provider=None):
    import os
    from fastapi.testclient import TestClient

    import coordinator.app.main as main_mod
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH", str(tmp_path / "api-c.db"))
    monkeypatch.setattr(main_mod, "_world_reader",
                        lambda: reader or FakeReader([make_result()]))
    if provider is not None:
        monkeypatch.setattr(main_mod, "get_provider",
                            lambda name=None, **k: provider)
    with TestClient(main_mod.app) as test_client:
        yield test_client


class FakeChatProvider:
    def __init__(self, advice="Gebruik de Arduino."):
        self._advice = advice

    async def advise(self, question, records):
        from coordinator.app.ollama_advisor import AdviceResponse
        return AdviceResponse(question=question, advice=self._advice,
                              model="fake", records_used=len(records),
                              sources=[])


def test_chat_reports_retrieval_mode_and_matches(tmp_path, monkeypatch):
    for test_client in _api_client(tmp_path, monkeypatch,
                                   provider=FakeChatProvider()):
        body = test_client.post("/api/v1/chat", json={
            "message": "Wat kan ik maken?"}).json()
        assert body["retrieval_mode"] in ("lexical", "hybrid")
        assert body["sources"][0]["entity_id"] == "obj_1"
        assert "match_type" in body["sources"][0]
        assert "score" in body["sources"][0]


def test_chat_unknown_mode_refused(tmp_path, monkeypatch):
    for test_client in _api_client(tmp_path, monkeypatch,
                                   provider=FakeChatProvider()):
        assert test_client.post("/api/v1/chat", json={
            "message": "x", "mode": "telepathie"}).status_code == 422


def test_advise_reports_retrieval_mode(tmp_path, monkeypatch):
    import coordinator.app.main as main_mod

    class FakeAdvisor:
        async def advise(self, question, records):
            from coordinator.app.ollama_advisor import AdviceResponse
            return AdviceResponse(question=question, advice="advies",
                                  model="fake", records_used=len(records),
                                  sources=[])

    monkeypatch.setattr(main_mod, "OllamaAdvisor",
                        lambda *a, **k: FakeAdvisor())
    for test_client in _api_client(tmp_path, monkeypatch):
        body = test_client.post("/api/v1/advise", json={
            "q": "arduino", "question": "Wat?"}).json()
        assert body["retrieval_mode"] in ("lexical", "hybrid")
