"""Write/verify HTTP API tests (BIG #5).

Full chain over the coordinator routes with a faked INVENTory:
propose -> approve -> execute -> verify, plus gate enforcement
(409/422) and the project package endpoint.
"""

import json
import os

import httpx
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


class FakeStore:
    def __init__(self):
        self.objects: dict = {}
        self.counter = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/objects":
            body = json.loads(request.content.decode())
            self.counter += 1
            entity_id = f"obj_api{self.counter:03d}"
            record = {"id": entity_id, "name": body["name"],
                      "description": body.get("description", ""),
                      "quantity": body.get("quantity", 1),
                      "provenance": body.get("provenance", {}),
                      "created_at": "2026-01-01T00:00:00+00:00",
                      "updated_at": "2026-01-01T00:00:00+00:00"}
            self.objects[entity_id] = record
            return httpx.Response(201, json=record)
        if path.startswith("/api/v1/objects/"):
            entity_id = path.rsplit("/", 1)[-1]
            record = self.objects.get(entity_id)
            if record is None:
                return httpx.Response(404, json={"detail": "no"})
            if request.method == "PATCH":
                body = json.loads(request.content.decode())
                for key in ("name", "description", "quantity"):
                    if key in body:
                        record[key] = body[key]
            return httpx.Response(200, json=record)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"detail": "no route"})


def make_client(tmp_path, monkeypatch):
    store = FakeStore()
    transport = httpx.MockTransport(store.handler)
    os.environ["MYCELIUM_DATABASE_PATH"] = str(tmp_path / "w.db")
    os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = str(
        tmp_path / "w-chat.db")
    from coordinator.app.inventory_read import InventoryReader
    from coordinator.app.inventory_writes import InventoryWriter
    monkeypatch.setattr(main_mod, "_world_reader",
                        lambda: InventoryReader(transport=transport))
    monkeypatch.setattr(main_mod, "InventoryWriter",
                        lambda *a, **k: InventoryWriter(
                            transport=transport))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_full_chain_propose_approve_execute_verify(tmp_path,
                                                   monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        created = test_client.post("/api/v1/writes/inventory", json={
            "proposal_id": "wrt-api1", "mutation": "create",
            "entity_type": "object",
            "fields": {"name": "API bout", "quantity": 7}})
        assert created.status_code == 201, created.text
        assert created.json()["status"] == "proposed"
        assert len(created.json()["fingerprint"]) == 64

        # Execute before approval is refused.
        early = test_client.post("/api/v1/writes/wrt-api1/execute")
        assert early.status_code == 409

        approved = test_client.post(
            "/api/v1/writes/wrt-api1/approve",
            json={"response": "YES", "decided_by": "jelles"})
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"

        # Second decision is refused (exactly-once approval).
        again = test_client.post(
            "/api/v1/writes/wrt-api1/approve",
            json={"response": "YES"})
        assert again.status_code == 409

        executed = test_client.post("/api/v1/writes/wrt-api1/execute")
        assert executed.status_code == 200, executed.text
        body = executed.json()
        assert body["status"] == "executed"
        assert body["result"]["after"]["title"] == "API bout"
        assert body["result"]["provenance"]["human_verified"] is False

        verified = test_client.post("/api/v1/writes/wrt-api1/verify")
        assert verified.status_code == 200, verified.text
        vbody = verified.json()
        assert vbody["verification"]["outcome"] == "passed"

        # Repeat calls are idempotent reads, not re-executions.
        assert test_client.post(
            "/api/v1/writes/wrt-api1/execute").status_code == 200
        assert test_client.post(
            "/api/v1/writes/wrt-api1/verify").status_code == 200


def test_rejection_blocks_execution(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        created = test_client.post("/api/v1/writes/inventory", json={
            "proposal_id": "wrt-api2", "mutation": "create",
            "entity_type": "object", "fields": {"name": "x"}})
        assert created.status_code == 201
        denied = test_client.post(
            "/api/v1/writes/wrt-api2/approve",
            json={"response": "nee"})
        assert denied.json()["status"] == "rejected"
        refused = test_client.post("/api/v1/writes/wrt-api2/execute")
        assert refused.status_code == 409


def test_invalid_mutation_refused_at_proposal(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        response = test_client.post("/api/v1/writes/inventory", json={
            "proposal_id": "wrt-api3", "mutation": "delete",
            "entity_type": "object", "fields": {}})
        assert response.status_code == 422
        smuggled = test_client.post("/api/v1/writes/inventory", json={
            "proposal_id": "wrt-api4", "mutation": "create",
            "entity_type": "object",
            "fields": {"name": "x",
                       "provenance": {"source_type": "ai-generated",
                                      "creator_id": "qwen",
                                      "human_verified": True}}})
        assert smuggled.status_code == 422


def test_verify_before_execute_refused(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        test_client.post("/api/v1/writes/inventory", json={
            "proposal_id": "wrt-api5", "mutation": "create",
            "entity_type": "object", "fields": {"name": "x"}})
        test_client.post("/api/v1/writes/wrt-api5/approve",
                         json={"response": "YES"})
        response = test_client.post("/api/v1/writes/wrt-api5/verify")
        assert response.status_code == 409


def test_unknown_proposal_is_404(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        assert test_client.get(
            "/api/v1/writes/wrt-missing").status_code == 404


def test_project_package_endpoint(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        response = test_client.get("/api/v1/project/package",
                                   params={"q": "bout"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["name"]
        assert "entities" in body
        assert "missions" in body
        assert "git" in body
        assert "summary" in body
        assert len(body["entities"]) <= 10
