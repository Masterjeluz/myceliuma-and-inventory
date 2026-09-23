"""PASS 3: research worker loop over the existing worker route.

Covers what the research slice assumed but never pinned: lease
isolation between two workers (no double execution), stale nodes
never receiving work, and unsafe task kinds refused end-to-end
(claimed, then refused by the real executor, then failed without
side effects). Real coordinator routes + real node_client
executor throughout; no new infrastructure.
"""

import coordinator.app.main as main_mod
from fastapi.testclient import TestClient
from node_client.main import execute_safe_task

TOKEN_A = "pass3-token-a-abcdef-123456"
TOKEN_B = "pass3-token-b-abcdef-123456"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "queue.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "chat-state.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def register(client, node_id, caps, token):
    response = client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": node_id, "tier": "worker",
        "capabilities": caps, "cpu_cores": 2, "memory_mb": 4000,
        "energy_source": "grid", "node_token": token})
    assert response.status_code == 201, response.text


def make_mission(client):
    conv = client.post("/api/v1/chat", json={
        "message": "onderzoek", "project_ref": "pass3-ws"}).json()[
        "conversation_id"]
    mission = client.post("/api/v1/missions", json={
        "conversation_id": conv, "goal": "Onderzoek isolatie",
        "steps": [{"kind": "readout", "description": "lees status",
                   "parameters": {"source": "git-status"}}],
        "max_steps": 3})
    assert mission.status_code == 201, mission.text
    return mission.json()["mission_id"]


def make_fetch_task(client, mission_id, url):
    made = client.post("/api/v1/tasks", json={
        "kind": "research.fetch_url",
        "payload": {"url": url, "max_chars": 4096},
        "required_capabilities": ["research.fetch"],
        "mission_id": mission_id})
    assert made.status_code == 201, made.text
    return made.json()["id"]


def claim(client, node_id, token):
    response = client.post(f"/api/v1/tasks/claim/{node_id}",
                           params={"node_token": token})
    assert response.status_code == 200, response.text
    return response.json()


def test_lease_isolates_two_workers(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client, "worker-a", ["research.fetch"], TOKEN_A)
        register(client, "worker-b", ["research.fetch"], TOKEN_B)
        mission_id = make_mission(client)
        task_id = make_fetch_task(
            client, mission_id, "https://example.com/een")
        assert claim(client, "worker-a", TOKEN_A)["id"] == task_id
        # B cannot take the leased task: exactly one holder.
        assert claim(client, "worker-b", TOKEN_B) is None
        # Lease expiry requeues (attempt 2), never duplicates.
        from datetime import datetime, timedelta, timezone
        future = (datetime.now(timezone.utc)
                  + timedelta(seconds=3600)).isoformat()
        assert main_mod.expire_leases(future)["requeued"] >= 1
        assert claim(client, "worker-b", TOKEN_B)["id"] == task_id
        tasks = {row["id"]: row
                 for row in client.get("/api/v1/tasks").json()}
        assert tasks[task_id]["assigned_node_id"] == "worker-b"


def test_stale_worker_receives_nothing(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client, "worker-old", ["research.fetch"], TOKEN_A)
        mission_id = make_mission(client)
        make_fetch_task(client, mission_id, "https://example.com/x")
        from coordinator.app.database import (
            connection as _conn,
        )
        with _conn() as db:
            db.execute("UPDATE nodes SET last_seen=? WHERE node_id=?",
                       ("2000-01-01T00:00:00+00:00", "worker-old"))
        assert claim(client, "worker-old", TOKEN_A) is None
        tasks = client.get("/api/v1/tasks").json()
        assert tasks[0]["status"] == "queued"


def test_unsafe_kind_refused_end_to_end(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client, "worker-a", ["research.fetch"], TOKEN_A)
        mission_id = make_mission(client)
        # Capability matches so the worker CAN pull it; execution
        # must still refuse desktop input (existing gate).
        made = client.post("/api/v1/tasks", json={
            "kind": "desktop_click",
            "payload": {"x": 10, "y": 10},
            "required_capabilities": ["research.fetch"],
            "mission_id": mission_id})
        assert made.status_code == 201, made.text
        task_id = made.json()["id"]
        claimed = claim(client, "worker-a", TOKEN_A)
        assert claimed["id"] == task_id
        ok, output, error = execute_safe_task(claimed)
        assert ok is False
        assert output == {}
        assert "approval" in (error or "").lower()
        done = client.post(f"/api/v1/tasks/{task_id}/complete",
                           params={"node_id": "worker-a"}, json={
                               "success": False, "result": {},
                               "error": error})
        assert done.status_code == 204, done.text
        tasks = {row["id"]: row
                 for row in client.get("/api/v1/tasks").json()}
        assert tasks[task_id]["status"] == "failed"
        mission = client.get(
            f"/api/v1/missions/{mission_id}").json()
        assert mission["status"] == "pending_approval"
        assert mission["steps"][0]["status"] == "pending"
