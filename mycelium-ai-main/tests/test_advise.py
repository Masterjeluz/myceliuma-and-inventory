"""Tests for POST /api/v1/advise (fase 3.1, compositie-only).

InventoryReader en OllamaAdvisor worden vervangen door fakes; geen echte
INVENTory-server, geen echt model, geen netwerk. De coordinator-database
moet onaangeroerd blijven.
"""
import os

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.inventory_read import (
    InventoryRefusedError,
    InventoryUnavailable,
    SearchResponse,
)
from coordinator.app.ollama_advisor import (
    AdviceResponse,
    OllamaAdvisor,
    OllamaRefusedError,
    OllamaUnavailable,
)

PROV = {"source_type": "user-created", "creator_id": "advise-test",
        "human_verified": False}


class FakeReader:
    def __init__(self, *args, **kwargs):
        self.calls = []
        self.behavior = "ok"

    async def search(self, q, type=None):
        self.calls.append(("search", q, type))
        if self.behavior == "unavailable":
            raise InventoryUnavailable("down")
        if self.behavior == "refused":
            raise InventoryRefusedError("nope")
        if not isinstance(q, str) or not q.strip() or len(q) > 200:
            raise InventoryRefusedError("Search query refused")
        return SearchResponse(query=q, total=1, results=[{
            "entity_type": "object", "entity_id": "obj_1", "title": "Moer",
            "snippet": "rvs", "provenance": PROV}])

    async def browse(self, type=None):
        self.calls.append(("browse", type))
        if self.behavior == "unavailable":
            raise InventoryUnavailable("down")
        if self.behavior == "refused":
            raise InventoryRefusedError("nope")
        return SearchResponse(query="", total=1, results=[{
            "entity_type": "object", "entity_id": "obj_1", "title": "Moer",
            "snippet": "rvs", "provenance": PROV}])


class FakeAdvisor:
    def __init__(self, *args, **kwargs):
        self.calls = []
        self.behavior = "ok"
        self.advice_text = "Gebruik de Moer M8."

    async def advise(self, question, records):
        self.calls.append((question, records))
        if self.behavior == "unavailable":
            raise OllamaUnavailable("down")
        if self.behavior == "refused":
            raise OllamaRefusedError("nope")
        return AdviceResponse(
            question=question, advice=self.advice_text,
            model="fake-model", records_used=len(records),
            sources=[{"entity_id": r.get("entity_id", ""),
                      "source_type": "user-created",
                      "human_verified": False} for r in records])


def advice_with_block(block: str) -> str:
    return ("Overweeg een opbergmodule te bouwen.\n\n"
            f"```json\n{block}\n```\n\nVerder vrij advies.")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    os.environ["MYCELIUM_DATABASE_PATH"] = str(tmp_path / "advise.db")
    fake_reader = FakeReader()
    fake_advisor = FakeAdvisor()
    monkeypatch.setattr(main_mod, "InventoryReader", lambda *a, **k: fake_reader)
    monkeypatch.setattr(main_mod, "OllamaAdvisor", lambda *a, **k: fake_advisor)
    with TestClient(main_mod.app) as test_client:
        test_client.fake_reader = fake_reader
        test_client.fake_advisor = fake_advisor
        yield test_client


def payload(**overrides):
    body = {"q": "moer", "question": "Wat kan ik maken?"}
    body.update(overrides)
    return body


def test_advise_success_delegates(client):
    res = client.post("/api/v1/advise", json=payload())
    assert res.status_code == 200
    assert client.fake_reader.calls == [("search", "moer", None)]
    assert len(client.fake_advisor.calls) == 1
    question, records = client.fake_advisor.calls[0]
    assert question == "Wat kan ik maken?"
    assert len(records) == 1
    assert records[0]["entity_id"] == "obj_1"
    assert records[0]["provenance"]["source_type"] == "user-created"
    data = res.json()
    assert data["advice"] == "Gebruik de Moer M8."
    assert data["records_used"] == 1
    assert data["sources"][0]["entity_id"] == "obj_1"


def test_advise_inventory_unavailable_is_502(client):
    client.fake_reader.behavior = "unavailable"
    assert client.post("/api/v1/advise", json=payload()).status_code == 502


def test_advise_ollama_unavailable_is_502(client):
    client.fake_advisor.behavior = "unavailable"
    assert client.post("/api/v1/advise", json=payload()).status_code == 502


def test_advise_inventory_refused_is_422(client):
    client.fake_reader.behavior = "refused"
    assert client.post("/api/v1/advise", json=payload()).status_code == 422


def test_advise_ollama_refused_is_422(client):
    client.fake_advisor.behavior = "refused"
    assert client.post("/api/v1/advise", json=payload()).status_code == 422


@pytest.mark.parametrize("body", [
    {},
    {"q": "moer"},
    {"q": "", "question": "Wat?"},
    {"q": "   ", "question": "Wat?"},
    {"q": "moer", "question": ""},
    {"q": "x" * 201, "question": "Wat?"},
    {"q": "moer", "question": "x" * 501},
])
def test_advise_invalid_input_is_422(client, body):
    assert client.post("/api/v1/advise", json=body).status_code == 422


def test_advise_without_q_uses_browse(client):
    res = client.post("/api/v1/advise", json={
        "question": "Wat kan ik maken met mijn huidige onderdelen?"})
    assert res.status_code == 200
    assert client.fake_reader.calls == [("browse", None)]
    assert len(client.fake_advisor.calls) == 1
    question, records = client.fake_advisor.calls[0]
    assert question == "Wat kan ik maken met mijn huidige onderdelen?"
    assert len(records) == 1
    assert records[0]["entity_id"] == "obj_1"
    data = res.json()
    assert data["advice"] == "Gebruik de Moer M8."
    assert data["records_used"] == 1


def test_advise_without_q_with_type_uses_browse_with_type(client):
    res = client.post("/api/v1/advise", json={
        "question": "Wat?", "type": "projects"})
    assert res.status_code == 200
    assert client.fake_reader.calls == [("browse", "projects")]


def test_advise_without_q_browse_unavailable_is_502(client):
    client.fake_reader.behavior = "unavailable"
    assert client.post("/api/v1/advise",
                       json={"question": "Wat?"}).status_code == 502


def test_advise_without_q_browse_refused_is_422(client):
    client.fake_reader.behavior = "refused"
    assert client.post("/api/v1/advise",
                       json={"question": "Wat?"}).status_code == 422


# --- M8.3: optional validated proposal enrichment --------------------------------

def test_advise_plain_advice_has_no_proposal(client):
    res = client.post("/api/v1/advise", json=payload())
    assert res.status_code == 200
    data = res.json()
    assert data["advice"] == "Gebruik de Moer M8."
    assert data["proposal"] is None


def test_advise_valid_block_yields_validated_proposal(client):
    import json as _json
    block = _json.dumps({"proposed_action": "Bouw een opbergmodule.",
                         "expected_output": "Een schets met maten.",
                         "risks": ["hout is op"]})
    client.fake_advisor.advice_text = advice_with_block(block)
    res = client.post("/api/v1/advise", json=payload())
    assert res.status_code == 200
    data = res.json()
    assert "opbergmodule" in data["advice"]
    proposal = data["proposal"]
    assert proposal is not None
    assert proposal["adapter_id"] == "mycelium-advise"
    assert proposal["request_id"].startswith("adv-")
    assert proposal["proposal_id"] == f"prop-{proposal['request_id']}"
    assert proposal["proposed_action"] == "Bouw een opbergmodule."
    assert proposal["requires_approval"] is True
    assert proposal["provenance"]["source_type"] == "ai-generated"
    assert proposal["provenance"]["human_verified"] is False
    assert "approved" not in proposal


def test_advise_proposal_id_deterministic(client):
    import json as _json
    block = _json.dumps({"proposed_action": "Bouw een opbergmodule.",
                         "expected_output": "Een schets.",
                         "risks": []})
    client.fake_advisor.advice_text = advice_with_block(block)
    first = client.post("/api/v1/advise", json=payload()).json()["proposal"]
    second = client.post("/api/v1/advise", json=payload()).json()["proposal"]
    assert first["proposal_id"] == second["proposal_id"]
    other = client.post("/api/v1/advise",
                        json=payload(question="Iets anders?")).json()["proposal"]
    assert other["proposal_id"] != first["proposal_id"]


def test_advise_malformed_block_keeps_advice_without_proposal(client):
    client.fake_advisor.advice_text = "Voorstel: ```json\n{geen json\n```"
    res = client.post("/api/v1/advise", json=payload())
    assert res.status_code == 200
    assert res.json()["proposal"] is None


def test_advise_tampered_provenance_block_yields_no_proposal(client):
    import json as _json
    block = _json.dumps({"proposed_action": "Bouw een opbergmodule.",
                         "expected_output": "Een schets.",
                         "risks": [],
                         "provenance": {"source_type": "user-created",
                                        "creator_id": "model",
                                        "human_verified": True}})
    client.fake_advisor.advice_text = advice_with_block(block)
    res = client.post("/api/v1/advise", json=payload())
    assert res.status_code == 200
    assert res.json()["proposal"] is None


def test_advise_proposal_stored_nowhere(client):
    import json as _json
    block = _json.dumps({"proposed_action": "Bouw een opbergmodule.",
                         "expected_output": "Een schets.",
                         "risks": []})
    client.fake_advisor.advice_text = advice_with_block(block)
    assert client.post("/api/v1/advise", json=payload()).status_code == 200
    from coordinator.app.database import connection
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_advise_route_is_post_only_and_writes_nothing(client):
    assert client.get("/api/v1/advise").status_code == 405
    assert client.post("/api/v1/advise", json=payload()).status_code == 200
    advise_routes = [r for r in main_mod.app.routes
                     if getattr(r, "path", "") == "/api/v1/advise"]
    assert len(advise_routes) == 1
    assert set(advise_routes[0].methods) == {"POST"}
    from coordinator.app.database import connection
    with connection() as db:
        assert db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_ollama_env_defaults_and_loopback_intact(tmp_path, monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_TIMEOUT_SECONDS", raising=False)
    advisor = OllamaAdvisor()
    assert advisor.model == "qwen3.5:4b"
    assert advisor.base_url == "http://127.0.0.1:11434"
    assert advisor.timeout == 120.0
    monkeypatch.setenv("OLLAMA_MODEL", "mijn-model")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    advisor = OllamaAdvisor()
    assert advisor.model == "mijn-model"
    assert advisor.base_url == "http://localhost:11434"
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example.com:11434/")
    with pytest.raises(OllamaRefusedError):
        OllamaAdvisor()
