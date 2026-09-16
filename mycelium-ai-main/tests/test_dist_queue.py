"""Node registry + queue API tests (BIG #8).

Register/heartbeat/detail/disable/enable, task create with
requirements, dry-run routing, assignment, claim revalidation,
physical-task lease safety and retry bounds — over HTTP.
"""

import os

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.sim_nodes import sim_registration


OPERATOR_KEY = "op-key-dist-queue-123"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "dist.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "dist-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", OPERATOR_KEY)
    with TestClient(main_mod.app) as test_client:
        yield test_client


def register_all(test_client):
    for node_id in ("node_desktop", "node_vision", "node_cpu"):
        response = test_client.post(
            "/api/v1/nodes/register",
            json={**sim_registration(node_id),
                  "node_token": f"sim-token-{node_id}-123"})
        assert response.status_code == 201, response.text


def test_register_detail_and_list_hide_credentials(tmp_path,
                                                   monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        response = test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-auth1", "hostname": "h", "tier": "seed",
            "capabilities": ["camera.snapshot"],
            "models": [{"model_id": "model:v",
                        "model_type": "vlm"}],
            "executors": ["exec:vision"],
            "resources": {"energy_source": "solar",
                          "energy_level": 70},
            "locality_zone": "local_network",
            "display_name": "Vision node",
            "node_token": "sekreet-token-123"})
        assert response.status_code == 201, response.text
        detail = test_client.get(
            "/api/v1/nodes/node-auth1").json()
        assert detail["display_name"] == "Vision node"
        assert detail["models"][0]["model_id"] == "model:v"
        assert detail["derived_status"] == "online"
        body = str(detail) + str(test_client.get(
            "/api/v1/nodes").json())
        assert "sekreet" not in body
        assert "auth_token_hash" not in body
        assert test_client.get(
            "/api/v1/nodes/node-missing").status_code == 404


def test_token_bind_and_enforce(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-t1", "hostname": "h",
            "capabilities": [],
            "node_token": "token-abc-123456789"})
        # Wrong token on re-register: 403, nothing logged/leaked.
        denied = test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-t1", "hostname": "h",
            "capabilities": [], "node_token": "wrong-token-xyz123"})
        assert denied.status_code == 403
        # Heartbeat without token: 403.
        assert test_client.post(
            "/api/v1/nodes/node-t1/heartbeat",
            json={"available": True}).status_code == 403
        # Heartbeat with token: 204.
        assert test_client.post(
            "/api/v1/nodes/node-t1/heartbeat",
            json={"available": True,
                  "node_token": "token-abc-123456789"}
        ).status_code == 204
        # Claim without token: 403.
        assert test_client.post(
            "/api/v1/tasks/claim/node-t1").status_code == 403
        # Unknown node heartbeat stays 404.
        assert test_client.post(
            "/api/v1/nodes/node-ghost/heartbeat",
            json={"available": True}).status_code == 404


def test_legacy_nodes_keep_working(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        # New identities without a token are refused outright:
        # choosing a node_id alone creates no authority.
        assert test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-old", "hostname": "h",
            "capabilities": ["exec:system_inventory"]
        }).status_code == 403
        # Pre-existing legacy rows (bound before the token
        # mandate) keep heartbeating and claiming, frozen.
        from coordinator.app.database import connection
        with connection() as db:
            db.execute(
                "INSERT INTO nodes (node_id, hostname, tier, "
                "capabilities, cpu_cores, memory_mb, "
                "energy_source, last_seen, status) VALUES (?, "
                "?, ?, ?, ?, ?, ?, ?, ?)",
                ("node-old", "h", "seed", '["exec:'
                 'system_inventory"]', 1, 0, "unknown",
                 "2026-09-16T00:00:00+00:00", "online"))
        assert test_client.post(
            "/api/v1/nodes/node-old/heartbeat",
            json={"available": True}).status_code == 204
        task = test_client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": [
                "exec:system_inventory"]}).json()
        claimed = test_client.post(
            "/api/v1/tasks/claim/node-old").json()
        assert claimed["id"] == task["id"]


def test_disable_enable(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-d1", "hostname": "h",
            "capabilities": ["exec:system_inventory"],
            "node_token": "disable-token-123456"})
        # Operator key required: unauthenticated callers fail.
        assert test_client.post(
            "/api/v1/nodes/node-d1/disable",
            json={}).status_code == 403
        assert test_client.post(
            "/api/v1/nodes/node-d1/disable",
            json={"operator_key": OPERATOR_KEY}).json()[
                "status"] == "disabled"
        # Disabled nodes cannot heartbeat or claim.
        assert test_client.post(
            "/api/v1/nodes/node-d1/heartbeat",
            json={"available": True,
                  "node_token": "disable-token-123456"}
        ).status_code == 403
        task = test_client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": [
                "exec:system_inventory"]}).json()
        assert test_client.post(
            "/api/v1/tasks/claim/node-d1",
            params={
                "node_token": "disable-token-123456"}).json() is None
        # Re-registering a disabled node keeps it disabled.
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-d1", "hostname": "h",
            "capabilities": ["exec:system_inventory"],
            "node_token": "disable-token-123456"})
        assert test_client.get(
            "/api/v1/nodes/node-d1").json()[
                "derived_status"] == "disabled"
        assert test_client.post(
            "/api/v1/nodes/node-d1/enable",
            json={"operator_key": OPERATOR_KEY}).json()[
                "status"] == "online"
        claimed = test_client.post(
            "/api/v1/tasks/claim/node-d1",
            params={
                "node_token": "disable-token-123456"}).json()
        assert claimed["id"] == task["id"]
        assert test_client.post(
            "/api/v1/nodes/node-ghost/disable",
            json={"operator_key": OPERATOR_KEY}).status_code == 404


def test_invalid_advertisement_refused(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        for bad in ({"capabilities": ["*"]},
                    {"executors": ["desktop"]},
                    {"models": [{"model_id": "x",
                                  "model_type": "llm"}]},
                    {"resources": {"energy_source": "coal"}},
                    {"locality_zone": "internet"}):
            body = {"node_id": "node-bad", "hostname": "h",
                    "node_token": "advertisement-token-123"}
            body.update(bad)
            assert test_client.post(
                "/api/v1/nodes/register",
                json=body).status_code == 422, bad


def test_route_and_assign(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        register_all(test_client)
        # Rotate node_vision to a dedicated token: strict default
        # policy then selects only the authenticated node.
        assert test_client.post(
            "/api/v1/nodes/node_vision/rotate-token",
            json={"current_token": "sim-token-node_vision-123",
                  "new_token": "vision-token-123"}).json()[
                      "bound"] is True
        body = sim_registration("node_vision")
        body["node_token"] = "vision-token-123"
        assert test_client.post(
            "/api/v1/nodes/register", json=body).status_code == 201
        assert test_client.post(
            "/api/v1/nodes/node_vision/heartbeat",
            json={"available": True,
                  "node_token": "vision-token-123"}).status_code == 204
        preview = test_client.post("/api/v1/tasks/route", json={
            "requirements": {
                "required_capabilities": ["vision.describe"]},
            "policy": {}}).json()
        assert preview["selected_node_id"] == "node_vision"
        assert any("vision.describe" in reason
                   for reason in preview["reasons"])
        assert any(entry["node_id"] == "node_cpu"
                   for entry in preview["rejected"])
        task = test_client.post("/api/v1/tasks", json={
            "kind": "vision.describe",
            "required_capabilities": ["vision.describe"],
            "requirements": {"required_model_types": ["vlm"]}}
        ).json()
        assigned = test_client.post(
            f"/api/v1/tasks/{task['id']}/assign", json={}).json()
        assert assigned["assigned_node_id"] == "node_vision"
        assert assigned["routing"]["selected_node_id"] == \
            "node_vision"
        # The assignee can claim (with token); others cannot take it.
        assert test_client.post(
            "/api/v1/tasks/claim/node_cpu",
            params={
                "node_token": "sim-token-node_cpu-123"}).json() is None
        claimed = test_client.post(
            "/api/v1/tasks/claim/node_vision",
            params={"node_token": "vision-token-123"}).json()
        assert claimed["id"] == task["id"]
        # Explicit wrong node refuses with reasons.
        task2 = test_client.post("/api/v1/tasks", json={
            "kind": "vision.describe",
            "required_capabilities": ["vision.describe"]}).json()
        refused = test_client.post(
            f"/api/v1/tasks/{task2['id']}/assign",
            json={"node_id": "node_cpu"})
        assert refused.status_code == 422
        assert test_client.post(
            "/api/v1/tasks/999999/assign",
            json={}).status_code == 404


def test_claim_revalidates_routing_requirements(tmp_path,
                                                monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        register_all(test_client)
        task = test_client.post("/api/v1/tasks", json={
            "kind": "vision.describe",
            "required_capabilities": ["vision.describe"],
            "requirements": {"required_model_types": ["ocr"]}}
        ).json()
        # node_vision has the capability but no ocr model.
        assert test_client.post(
            "/api/v1/tasks/claim/node_vision",
            params={
                "node_token": "sim-token-node_vision-123"}
        ).json() is None
        listed = test_client.get("/api/v1/tasks").json()
        entry = next(item for item in listed
                     if item["id"] == task["id"])
        assert entry["routing"]["required_model_types"] == ["ocr"]
        assert entry["status"] == "queued"


def test_stale_node_rejected_from_routing(tmp_path, monkeypatch):
    from coordinator.app.database import connection
    for test_client in make_client(tmp_path, monkeypatch):
        register_all(test_client)
        with connection() as db:
            db.execute(
                "UPDATE nodes SET last_seen=? WHERE node_id=?",
                ("2020-01-01T00:00:00+00:00", "node_vision"))
        preview = test_client.post("/api/v1/tasks/route", json={
            "requirements": {
                "required_capabilities": ["vision.describe"]},
            "policy": {"require_authenticated": False}}).json()
        assert preview["selected_node_id"] is None
        assert any(entry["node_id"] == "node_vision"
                   for entry in preview["rejected"])
        # Fresh again: selectable.
        test_client.post("/api/v1/nodes/node_vision/heartbeat",
                         json={"available": True,
                               "node_token":
                               "sim-token-node_vision-123"})
        preview = test_client.post("/api/v1/tasks/route", json={
            "requirements": {
                "required_capabilities": ["vision.describe"]},
            "policy": {"require_authenticated": False}}).json()
        assert preview["selected_node_id"] == "node_vision"


def test_physical_lease_becomes_blocked(tmp_path, monkeypatch):
    from coordinator.app.main import expire_leases
    for test_client in make_client(tmp_path, monkeypatch):
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-p1", "hostname": "h",
            "capabilities": ["printer.execute"],
            "node_token": "printer-token-123456"})
        task = test_client.post("/api/v1/tasks", json={
            "kind": "printer.execute",
            "required_capabilities": ["printer.execute"],
            "requirements": {"physical_action": True}}).json()
        claimed = test_client.post(
            "/api/v1/tasks/claim/node-p1",
            params={"node_token": "printer-token-123456"}).json()
        assert claimed["id"] == task["id"]
        # Node disappears: lease expiry must NOT requeue.
        from coordinator.app.database import connection
        with connection() as db:
            db.execute(
                "UPDATE tasks SET lease_until=? WHERE id=?",
                ("2020-01-01T00:00:00+00:00", task["id"]))
        summary = expire_leases("2026-01-01T00:00:00+00:00")
        assert summary["blocked"] == 1
        with connection() as db:
            status = db.execute(
                "SELECT status FROM tasks WHERE id=?",
                (task["id"],)).fetchone()["status"]
        assert status == "blocked"
        # Blocked physical work never claims again.
        assert test_client.post(
            "/api/v1/tasks/claim/node-p1",
            params={
                "node_token": "printer-token-123456"}).json() is None
