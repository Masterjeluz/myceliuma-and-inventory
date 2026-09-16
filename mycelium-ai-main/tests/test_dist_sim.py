"""Distributed multi-node smoke (BIG #8, §22).

Three deterministic cases over real coordinator routes:

1. vision task routes to node_vision, claims, completes,
   result recorded (verification-style readback of the task).
2. node_vision stale: same non-physical task reroutes to (or
   waits for) another compatible node; vision node rejected.
3. physical task whose node disappears after lease: blocked,
   operator-required, never silently duplicated.
"""

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.sim_nodes import sim_registration


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "sim.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "sim-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def sim_token(node_id: str) -> str:
    return f"sim-token-{node_id}-123"


def register_all(test_client):
    for node_id in ("node_desktop", "node_vision", "node_cpu"):
        response = test_client.post(
            "/api/v1/nodes/register",
            json={**sim_registration(node_id),
                  "node_token": sim_token(node_id)})
        assert response.status_code == 201, response.text


def heartbeat(test_client, node_id):
    assert test_client.post(
        f"/api/v1/nodes/{node_id}/heartbeat",
        json={"available": True,
              "node_token": sim_token(node_id)}).status_code == 204


def claim(test_client, node_id):
    return test_client.post(
        f"/api/v1/tasks/claim/{node_id}",
        params={"node_token": sim_token(node_id)}).json()


def test_case_1_vision_task_flows(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        register_all(test_client)
        task = test_client.post("/api/v1/tasks", json={
            "kind": "vision.describe",
            "required_capabilities": ["vision.describe"],
            "requirements": {"required_model_types": ["vlm"]},
            "payload": {"routing": {
                "required_capabilities": ["vision.describe"],
                "required_model_types": ["vlm"]}},
        }).json()
        assigned = test_client.post(
            f"/api/v1/tasks/{task['id']}/assign",
            json={"policy": {
                "require_authenticated": False}}).json()
        assert assigned["assigned_node_id"] == "node_vision"
        claimed = claim(test_client, "node_vision")
        assert claimed["id"] == task["id"]
        assert test_client.post(
            f"/api/v1/tasks/{task['id']}/complete",
            params={"node_id": "node_vision"},
            json={"success": True,
                  "result": {"observation": "simulated workbench",
                             "executor": "exec:vision",
                             "node_id": "node_vision"}}).status_code == 204
        stored = next(item for item in
                      test_client.get("/api/v1/tasks").json()
                      if item["id"] == task["id"])
        assert stored["status"] == "completed"
        assert stored["result"]["result"]["node_id"] == "node_vision"
        assert stored["assigned_node_id"] == "node_vision"
        detail = test_client.get(
            f"/api/v1/tasks/by-id/{task['id']}").json()
        assert detail["routing_decision"]["selected_node_id"] == \
            "node_vision"


def test_case_2_stale_vision_node_reroutes(tmp_path, monkeypatch):
    from coordinator.app.database import connection
    for test_client in make_client(tmp_path, monkeypatch):
        register_all(test_client)
        with connection() as db:
            db.execute(
                "UPDATE nodes SET last_seen=? WHERE node_id=?",
                ("2020-01-01T00:00:00+00:00", "node_vision"))
        task = test_client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": ["exec:system_inventory"],
        }).json()
        # node_cpu is fresh and capable; the stale vision node
        # must not receive anything.
        assigned = test_client.post(
            f"/api/v1/tasks/{task['id']}/assign",
            json={"policy": {
                "require_authenticated": False}}).json()
        assert assigned["assigned_node_id"] == "node_cpu"
        assert claim(test_client, "node_vision") is None
        claimed = claim(test_client, "node_cpu")
        assert claimed["id"] == task["id"]


def test_case_3_physical_disappearance_blocks(tmp_path, monkeypatch):
    from coordinator.app.database import connection
    from coordinator.app.main import expire_leases
    for test_client in make_client(tmp_path, monkeypatch):
        register_all(test_client)
        task = test_client.post("/api/v1/tasks", json={
            "kind": "printer_run",
            "required_capabilities": ["printer.simulated"],
            "requirements": {"required_capabilities": [
                "printer.simulated"],
                "physical_action": True},
        }).json()
        # Extend node_cpu advertisement for this run only.
        heartbeat(test_client, "node_cpu")
        with connection() as db:
            db.execute(
                "UPDATE nodes SET capabilities=? WHERE node_id=?",
                ('["printer.simulated"]', "node_cpu"))
        assigned = test_client.post(
            f"/api/v1/tasks/{task['id']}/assign",
            json={"policy": {
                "require_authenticated": False}}).json()
        assert assigned["assigned_node_id"] == "node_cpu"
        claimed = claim(test_client, "node_cpu")
        assert claimed["id"] == task["id"]
        # Node disappears mid-lease: expire, then prove no reroute.
        with connection() as db:
            db.execute(
                "UPDATE tasks SET lease_until=? WHERE id=?",
                ("2020-01-01T00:00:00+00:00", task["id"]))
            db.execute(
                "UPDATE nodes SET last_seen=?",
                ("2020-01-01T00:00:00+00:00",))
        summary = expire_leases("2026-01-01T00:00:00+00:00")
        assert summary["blocked"] == 1
        assert summary["requeued"] == 0
        with connection() as db:
            status = db.execute(
                "SELECT status FROM tasks WHERE id=?",
                (task["id"],)).fetchone()["status"]
        assert status == "blocked"
        # Even a fresh capable node never re-claims it.
        heartbeat(test_client, "node_cpu")
        assert claim(test_client, "node_cpu") is None
