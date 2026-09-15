"""Tests for POST /api/v1/tasks/from-proposal (M8.5, explicit translation).

Stateless like M8.4: the operator supplies the full proposal, its
ApprovalResult and the fingerprint recorded at approval time. Conversion
runs exclusively through the existing M6.4 proposal_to_task(). The result
carries status "approved" only: no queue, no staging, no DB writes.
"""
import os

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.adapter_contracts import AdapterProposal
from coordinator.app.approval import approve, decide, request_approval
from coordinator.app.inventory_read import SearchResponse
from coordinator.app.ollama_advisor import AdviceResponse
from coordinator.app.proposal_tasks import proposal_fingerprint

AI_PROV = {"source_type": "ai-generated",
           "creator_id": "advisor:mycelium-advise",
           "human_verified": False}


def make_proposal(**overrides):
    data = {"proposal_id": "prop-adv-0123456789abcdef",
            "request_id": "adv-0123456789abcdef",
            "adapter_id": "mycelium-advise",
            "proposed_action": "Bouw een opbergmodule.",
            "expected_output": "Een schets met maten.",
            "risks": ["hout is op"],
            "provenance": dict(AI_PROV),
            "requires_approval": True}
    data.update(overrides)
    return AdapterProposal(**data)


def triple(response="YES", **proposal_overrides):
    prop = make_proposal(**proposal_overrides)
    approval = decide(request_approval(prop), prop, response)
    return {"proposal": prop.model_dump(mode="json"),
            "approval": approval.model_dump(mode="json"),
            "approved_fingerprint": proposal_fingerprint(prop)}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    os.environ["MYCELIUM_DATABASE_PATH"] = str(tmp_path / "from_proposal.db")
    with TestClient(main_mod.app) as test_client:
        yield test_client


def db_counts():
    from coordinator.app.database import connection
    with connection() as db:
        return (db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
                db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])


# --- happy path ------------------------------------------------------------------

def test_valid_approved_proposal_translates(client):
    res = client.post("/api/v1/tasks/from-proposal", json=triple())
    assert res.status_code == 200
    data = res.json()
    assert data["task_id"] == "ctask-prop-adv-0123456789abcdef"
    assert data["proposal_id"] == "prop-adv-0123456789abcdef"
    assert data["request_id"] == "adv-0123456789abcdef"
    assert data["adapter_id"] == "mycelium-advise"
    assert data["task_type"] == "other"
    assert data["expected_output"] == "Een schets met maten."
    assert data["status"] == "approved"
    assert data["approval_reference"]["decision"] == "approved"


def test_custom_task_options_pass_through(client):
    res = client.post("/api/v1/tasks/from-proposal", json={
        **triple(), "task_id": "my-task-1", "task_type": "inspect",
        "input": {"object_id": "obj_1"}})
    assert res.status_code == 200
    data = res.json()
    assert data["task_id"] == "my-task-1"
    assert data["task_type"] == "inspect"
    assert data["input"] == {"object_id": "obj_1"}


# --- fail-closed -------------------------------------------------------------------

def test_rejected_approval_fails(client):
    assert client.post("/api/v1/tasks/from-proposal",
                       json=triple(response="NO")).status_code == 422


def test_approved_false_fails(client):
    prop = make_proposal()
    bad = {"proposal_id": prop.proposal_id, "request_id": prop.request_id,
           "decision": "rejected", "approved": False,
           "proposal_provenance": dict(AI_PROV)}
    payload = triple()
    payload["approval"] = bad
    assert client.post("/api/v1/tasks/from-proposal",
                       json=payload).status_code == 422


def test_tampered_proposal_after_approval_fails(client):
    payload = triple()
    payload["proposal"]["proposed_action"] = "Sloop alles."
    assert client.post("/api/v1/tasks/from-proposal",
                       json=payload).status_code == 422


def test_wrong_proposal_id_fails(client):
    payload = triple()
    payload["proposal"]["proposal_id"] = "prop-adv-anders"
    assert client.post("/api/v1/tasks/from-proposal",
                       json=payload).status_code == 422


def test_wrong_request_id_fails(client):
    payload = triple()
    payload["approval"]["request_id"] = "adv-anders"
    assert client.post("/api/v1/tasks/from-proposal",
                       json=payload).status_code == 422


def test_approval_for_other_proposal_fails(client):
    payload = triple()
    other = make_proposal(proposal_id="prop-adv-ffff",
                          request_id="adv-ffff")
    other_approval = approve(request_approval(other), other)
    payload["approval"] = other_approval.model_dump(mode="json")
    payload["approved_fingerprint"] = proposal_fingerprint(other)
    assert client.post("/api/v1/tasks/from-proposal",
                       json=payload).status_code == 422


@pytest.mark.parametrize("field,value", [
    ("requires_approval", False),
    ("proposed_action", ""),
    ("model_id", "proj_x"),
])
def test_invalid_proposal_fails(client, field, value):
    prop = make_proposal()
    data = prop.model_dump(mode="json")
    data[field] = value
    payload = triple()
    payload["proposal"] = data
    assert client.post("/api/v1/tasks/from-proposal",
                       json=payload).status_code == 422


def test_short_fingerprint_fails(client):
    payload = triple()
    payload["approved_fingerprint"] = "abc"
    assert client.post("/api/v1/tasks/from-proposal",
                       json=payload).status_code == 422


# --- provenance and side-effect freedom ----------------------------------------------

def test_provenance_preserved_and_unverified(client):
    data = client.post("/api/v1/tasks/from-proposal",
                       json=triple()).json()
    assert data["provenance"]["source_type"] == "ai-generated"
    assert data["provenance"]["creator_id"] == "advisor:mycelium-advise"
    assert data["provenance"]["human_verified"] is False


def test_no_db_record_no_queue_no_staging(client):
    data = client.post("/api/v1/tasks/from-proposal",
                       json=triple()).json()
    assert data["status"] == "approved"
    for key in ("queue", "queued", "staged", "staging", "promotion",
                "dispatched", "dispatch", "lease", "assigned"):
        assert key not in data
    assert db_counts() == (0, 0)


def test_route_is_post_only(client):
    assert client.get("/api/v1/tasks/from-proposal").status_code == 405
    routes = [r for r in main_mod.app.routes
              if getattr(r, "path", "") == "/api/v1/tasks/from-proposal"]
    assert len(routes) == 1
    assert set(routes[0].methods) == {"POST"}
    assert db_counts() == (0, 0)


# --- full chain: advise -> approvals -> from-proposal ----------------------------------

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


def test_full_chain_advise_approvals_task(client, monkeypatch):
    monkeypatch.setattr(main_mod, "InventoryReader",
                        lambda *a, **k: FakeReader())
    monkeypatch.setattr(main_mod, "OllamaAdvisor",
                        lambda *a, **k: FakeAdvisor())
    advised = client.post("/api/v1/advise",
                          json={"q": "moer", "question": "Wat bouwen?"}).json()
    assert advised["proposal"] is not None
    decided = client.post("/api/v1/approvals", json={
        "proposal": advised["proposal"], "response": "YES"}).json()
    assert decided["approved"] is True
    returned = AdapterProposal(**advised["proposal"])
    task = client.post("/api/v1/tasks/from-proposal", json={
        "proposal": advised["proposal"], "approval": decided,
        "approved_fingerprint": proposal_fingerprint(returned)}).json()
    assert task["status"] == "approved"
    assert task["proposal_id"] == advised["proposal"]["proposal_id"]
    assert task["provenance"]["human_verified"] is False
    assert db_counts() == (0, 0)
