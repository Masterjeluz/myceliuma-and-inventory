"""FASE 2 tests (BIG #16): global fencing.

Invariant: a writer holding an old fencing epoch cannot
perform coordinator-owned mutations. No lease yet means
bootstrap: epoch-0 writers pass unchanged.
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.failover import (
    FencingError,
    require_writer_epoch,
)


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "fence.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "fence-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def register(client, node_id):
    response = client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": "h",
        "capabilities": ["exec:system_inventory"],
        "coordinator_capable": True,
        "node_token": f"fencing-token-{node_id}-123"})
    assert response.status_code == 201, response.text


def claim_as(client, node_id):
    return client.post(
        f"/api/v1/tasks/claim/{node_id}",
        params={"node_token": f"fencing-token-{node_id}-123"}).json()


def envelope(event_id, epoch):
    return {"event_id": event_id,
            "origin_node_id": "node-a",
            "entity_id": "obj_9", "entity_type": "object",
            "entity_revision": "rev-1", "base_revision": "",
            "event_type": "entity.observed", "timestamp": "",
            "payload": {"note": "x"}, "provenance": {},
            "epoch": epoch}


def test_no_lease_bootstrap_unchanged(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert require_writer_epoch(0) == 0
        applied = client.post("/api/v1/sync/apply", json={
            "items": [envelope("dsevt_f0", 0)]}).json()
        assert applied["applied"] == 1


def test_stale_epoch_envelope_refused(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client, "node-f1")
        assert client.post("/api/v1/coordinator/campaign",
                           json={"node_id": "node-f1"}
                           ).status_code == 200
        with pytest.raises(FencingError):
            require_writer_epoch(0)
        assert require_writer_epoch(1) == 1
        outcome = client.post("/api/v1/sync/apply", json={
            "items": [envelope("dsevt_f1", 0)]}).json()
        assert outcome["failed"] == 1
        assert outcome["applied"] == 0
        current = client.post("/api/v1/sync/apply", json={
            "items": [envelope("dsevt_f2", 1)]}).json()
        assert current["applied"] == 1


def test_complete_fenced_after_epoch_change(tmp_path,
                                            monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client, "node-f1")
        task = client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": [
                "exec:system_inventory"]}).json()
        assigned = client.post(
            f"/api/v1/tasks/{task['id']}/assign",
            json={"policy": {
                "require_authenticated": False}}).json()
        assert assigned["routing"]["epoch"] == 0
        claimed = claim_as(client, "node-f1")
        assert claimed["id"] == task["id"]
        client.post("/api/v1/coordinator/campaign",
                    json={"node_id": "node-f1"})
        # Completing the old-epoch assignment refuses loudly.
        response = client.post(
            f"/api/v1/tasks/{task['id']}/complete",
            params={"node_id": "node-f1"},
            json={"success": True})
        assert response.status_code == 409
        # Fresh work under the live epoch completes fine.
        task2 = client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": [
                "exec:system_inventory"]}).json()
        assigned2 = client.post(
            f"/api/v1/tasks/{task2['id']}/assign",
            json={"policy": {
                "require_authenticated": False}}).json()
        assert assigned2["routing"]["epoch"] == 1
        claimed2 = claim_as(client, "node-f1")
        assert claimed2["id"] == task2["id"]
        assert client.post(
            f"/api/v1/tasks/{task2['id']}/complete",
            params={"node_id": "node-f1"},
            json={"success": True}).status_code == 204
