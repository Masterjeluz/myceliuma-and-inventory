"""Tests for POST /api/v1/approvals (M8.4, explicit operator approval).

Stateless by design: the full proposal travels with the decision because
M8.3 proposals are never stored. Binding is verified on content through
the existing M6.3 gate. No task is created, nothing is staged, queued or
dispatched, and the coordinator database stays untouched.
"""
import os

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.inventory_read import SearchResponse
from coordinator.app.ollama_advisor import AdviceResponse

PROV = {"source_type": "ai-generated", "creator_id": "advisor:mycelium-advise",
        "human_verified": False}


def proposal(**overrides):
    data = {"proposal_id": "prop-adv-0123456789abcdef",
            "request_id": "adv-0123456789abcdef",
            "adapter_id": "mycelium-advise",
            "proposed_action": "Bouw een opbergmodule.",
            "expected_output": "Een schets met maten.",
            "risks": ["hout is op"],
            "provenance": dict(PROV),
            "requires_approval": True}
    data.update(overrides)
    return data


def body(**overrides):
    payload = {"proposal": proposal(), "response": "YES"}
    payload.update(overrides)
    return payload


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH", str(tmp_path / "approvals.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def db_counts():
    from coordinator.app.database import connection
    with connection() as db:
        return (db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
                db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])


# --- decisions -----------------------------------------------------------------

def test_explicit_yes_approves(client):
    res = client.post("/api/v1/approvals", json=body())
    assert res.status_code == 200
    data = res.json()
    assert data["decision"] == "approved"
    assert data["approved"] is True
    assert data["proposal_id"] == "prop-adv-0123456789abcdef"
    assert data["request_id"] == "adv-0123456789abcdef"
    assert data["decided_by"] == "human"


def test_explicit_no_rejects(client):
    res = client.post("/api/v1/approvals", json=body(response="NO"))
    assert res.status_code == 200
    data = res.json()
    assert data["decision"] == "rejected"
    assert data["approved"] is False
    assert data["note"] == "human answered NO"


@pytest.mark.parametrize("response", ["yes", "YES ", " YES", "NO ", "maybe",
                                      "JA", "1", "Y", "N"])
def test_anything_but_exact_yes_denies(client, response):
    res = client.post("/api/v1/approvals", json=body(response=response))
    assert res.status_code == 200
    data = res.json()
    assert data["decision"] == "rejected"
    assert data["approved"] is False
    assert "default deny" in data["note"]


def test_empty_response_refused(client):
    assert client.post("/api/v1/approvals",
                       json=body(response="")).status_code == 422


def test_decided_by_honored_and_blank_refused(client):
    res = client.post("/api/v1/approvals",
                      json=body(decided_by="jelles"))
    assert res.status_code == 200
    assert res.json()["decided_by"] == "jelles"
    assert client.post("/api/v1/approvals",
                       json=body(decided_by="   ")).status_code == 422


# --- binding and unknown proposals fail closed ----------------------------------

def test_binding_echoes_submitted_content(client):
    first = client.post("/api/v1/approvals", json=body()).json()
    other = proposal(proposal_id="prop-adv-ffff",
                     request_id="adv-ffff")
    second = client.post("/api/v1/approvals",
                         json=body(proposal=other)).json()
    assert (first["proposal_id"], first["request_id"]) == (
        "prop-adv-0123456789abcdef", "adv-0123456789abcdef")
    assert (second["proposal_id"], second["request_id"]) == (
        "prop-adv-ffff", "adv-ffff")


@pytest.mark.parametrize("bad_proposal", [
    proposal(requires_approval=False),
    proposal(provenance={**PROV, "human_verified": True}),
    proposal(proposal_id="bad id!"),
    proposal(request_id="x"),
    proposal(adapter_id=""),
    proposal(proposed_action=""),
    proposal(model_id="proj_x"),
    proposal(task_id="nope"),
    {"proposal_id": "prop-adv-1", "request_id": "adv-1"},
])
def test_unknown_or_invalid_proposal_refused(client, bad_proposal):
    assert client.post("/api/v1/approvals",
                       json=body(proposal=bad_proposal)).status_code == 422


# --- approval changes nothing and starts nothing ---------------------------------

def test_approval_keeps_provenance_unverified(client):
    data = client.post("/api/v1/approvals", json=body()).json()
    assert data["proposal_provenance"]["source_type"] == "ai-generated"
    assert data["proposal_provenance"]["human_verified"] is False


def test_approval_creates_no_task_and_writes_nothing(client):
    data = client.post("/api/v1/approvals", json=body()).json()
    assert set(data) == {"proposal_id", "request_id", "decision", "approved",
                         "decided_by", "note", "proposal_provenance"}
    for key in ("task_id", "status", "approval_reference", "proposal_fingerprint",
                "staged", "queued", "dispatched"):
        assert key not in data
    assert db_counts() == (0, 0)


def test_approvals_route_is_post_only(client):
    assert client.get("/api/v1/approvals").status_code == 405
    routes = [r for r in main_mod.app.routes
              if getattr(r, "path", "") == "/api/v1/approvals"]
    assert len(routes) == 1
    assert set(routes[0].methods) == {"POST"}
    assert db_counts() == (0, 0)


# --- advise-to-approval chain (operator copies proposal, decides) ------------------

class FakeReader:
    async def search(self, q, type=None):
        return SearchResponse(query=q, total=1, results=[{
            "entity_type": "object", "entity_id": "obj_1", "title": "Moer",
            "snippet": "rvs", "provenance": {"source_type": "user-created",
                                              "creator_id": "t",
                                              "human_verified": True}}])

    async def browse(self, type=None):
        return await self.search("x", type)


class FakeAdvisor:
    async def advise(self, question, records):
        import json as _json
        block = _json.dumps({"proposed_action": "Bouw een opbergmodule.",
                             "expected_output": "Een schets.",
                             "risks": []})
        return AdviceResponse(
            question=question,
            advice=f"Advies.\n\n```json\n{block}\n```",
            model="fake-model", records_used=len(records),
            sources=[{"entity_id": "obj_1", "source_type": "user-created",
                      "human_verified": False}])


def test_advise_then_explicit_approval_chain(client, monkeypatch):
    monkeypatch.setattr(main_mod, "InventoryReader", lambda *a, **k: FakeReader())
    monkeypatch.setattr(main_mod, "OllamaAdvisor", lambda *a, **k: FakeAdvisor())
    advised = client.post("/api/v1/advise",
                          json={"q": "moer", "question": "Wat bouwen?"}).json()
    assert advised["proposal"] is not None
    approved = client.post("/api/v1/approvals", json={
        "proposal": advised["proposal"], "response": "YES"}).json()
    assert approved["approved"] is True
    assert approved["proposal_id"] == advised["proposal"]["proposal_id"]
    rejected = client.post("/api/v1/approvals", json={
        "proposal": advised["proposal"], "response": "NO"}).json()
    assert rejected["approved"] is False
    assert db_counts() == (0, 0)
