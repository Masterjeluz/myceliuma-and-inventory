"""Distributed security tripwires (BIG #8).

Unknown/disabled/unauthenticated nodes, stale claims,
wildcard and injection refusal, credential hygiene, identity
binding, lease ownership, bounded retry, no cloud, no public
bind, no privilege escalation.
"""

import pathlib

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

APP = pathlib.Path(__file__).resolve().parent.parent / "coordinator" / "app"


def source_of(*names: str) -> str:
    return "\n".join(
        (APP / name).read_text(encoding="utf-8") for name in names)


OPERATOR_KEY = "op-key-dist-security-123"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "sec.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "sec-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", OPERATOR_KEY)
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_unknown_node_rejected(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        assert test_client.post(
            "/api/v1/tasks/claim/node-ghost").status_code == 404
        assert test_client.post(
            "/api/v1/nodes/node-ghost/heartbeat",
            json={"available": True}).status_code == 404
        assert test_client.get(
            "/api/v1/nodes/node-ghost").status_code == 404
        # Disable without operator key refuses first.
        assert test_client.post(
            "/api/v1/nodes/node-ghost/disable",
            json={}).status_code == 403
        assert test_client.post(
            "/api/v1/nodes/node-ghost/disable",
            json={"operator_key": OPERATOR_KEY}).status_code == 404


def test_invalid_credential_rejected(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-s1", "hostname": "h",
            "capabilities": [],
            "node_token": "right-token-123456"})
        assert test_client.post(
            "/api/v1/tasks/claim/node-s1",
            params={"node_token": "wrong-token"}).status_code == 403
        assert test_client.post(
            "/api/v1/nodes/node-s1/heartbeat",
            json={"available": True,
                  "node_token": "wrong-token"}).status_code == 403
        # Re-register rebinding requires the old credential.
        assert test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-s1", "hostname": "h",
            "capabilities": [], "node_token": "new-token-234567"}
        ).status_code == 403


def test_node_cannot_claim_another_identity(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        for node_id, token in (("node-a", "token-a-123456789"),
                                ("node-b", "token-b-123456789")):
            test_client.post("/api/v1/nodes/register", json={
                "node_id": node_id, "hostname": "h",
                "capabilities": ["exec:system_inventory"],
                "node_token": token})
        task = test_client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": [
                "exec:system_inventory"]}).json()
        assigned = test_client.post(
            f"/api/v1/tasks/{task['id']}/assign",
            json={"policy": {}}).json()
        assert assigned["assigned_node_id"] in ("node-a", "node-b")
        other = "node-b" if assigned["assigned_node_id"] == \
            "node-a" else "node-a"
        other_token = "token-b-123456789" if other == "node-b" else \
            "token-a-123456789"
        # Wrong node, right own token: assignment pins ownership.
        assert test_client.post(
            f"/api/v1/tasks/claim/{other}",
            params={"node_token": other_token}).json() is None


def test_stale_node_cannot_claim(tmp_path, monkeypatch):
    from coordinator.app.database import connection
    for test_client in make_client(tmp_path, monkeypatch):
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-old", "hostname": "h",
            "capabilities": ["exec:system_inventory"],
            "node_token": "stale-token-123456"})
        test_client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": ["exec:system_inventory"]})
        with connection() as db:
            db.execute(
                "UPDATE nodes SET last_seen=? WHERE node_id=?",
                ("2020-01-01T00:00:00+00:00", "node-old"))
        assert test_client.post(
            "/api/v1/tasks/claim/node-old",
            params={
                "node_token": "stale-token-123456"}).json() is None


def test_task_cannot_grant_capabilities(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-plain", "hostname": "h",
            "capabilities": [],
            "node_token": "plain-token-123456"})
        # A task demanding an unadvertised capability matches nothing.
        task = test_client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": ["printer.execute"]}).json()
        assert test_client.post(
            "/api/v1/tasks/claim/node-plain",
            params={"node_token": "plain-token-123456"}
        ).json() is None
        preview = test_client.post("/api/v1/tasks/route", json={
            "requirements": {"required_capabilities": [
                "printer.execute"]},
            "policy": {"require_authenticated": False}}).json()
        assert preview["selected_node_id"] is None
        # Task payload cannot inject executors or commands.
        evil = test_client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "payload": {"routing": {
                "required_executor": "exec:printer"},
                "command": "rm -rf /",
                "exec": "/bin/sh"}})
        assert evil.status_code == 201
        assert test_client.post(
            "/api/v1/tasks/claim/node-plain",
            params={"node_token": "plain-token-123456"}
        ).json() is None


def test_arbitrary_paths_and_commands_refused(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        for bad_req in ({"required_capabilities": ["/bin/sh"]},
                        {"required_capabilities": ["a; rm"]},
                        {"required_executor": "/usr/bin/x"},
                        {"preferred_model_ids": ["../../etc/passwd"]}):
            assert test_client.post("/api/v1/tasks", json={
                "kind": "system_inventory",
                "requirements": bad_req}).status_code == 422, bad_req
        for bad_reg in ({"capabilities": ["/bin/sh"]},
                        {"executors": ["exec:../x"]},
                        {"models": [{"model_id": "http://x/y",
                                     "model_type": "llm"}]}):
            body = {"node_id": "node-evil", "hostname": "h",
                    "node_token": "evil-token-123456"}
            body.update(bad_reg)
            assert test_client.post(
                "/api/v1/nodes/register",
                json=body).status_code == 422, bad_reg


def test_credentials_never_logged_or_returned(tmp_path, monkeypatch,
                                              caplog):
    import logging
    for test_client in make_client(tmp_path, monkeypatch):
        with caplog.at_level(logging.INFO,
                             logger="mycelium.coordinator"):
            test_client.post("/api/v1/nodes/register", json={
                "node_id": "node-log", "hostname": "h",
                "capabilities": [],
                "node_token": "super-secret-999"})
            test_client.post(
                "/api/v1/nodes/node-log/heartbeat",
                json={"available": True,
                      "node_token": "super-secret-999"})
        assert "super-secret-999" not in caplog.text
        for payload in (test_client.get("/api/v1/nodes").json(),
                        test_client.get(
                            "/api/v1/nodes/node-log").json(),
                        test_client.get("/").text):
            assert "super-secret-999" not in str(payload)
            assert "auth_token_hash" not in str(payload)


def test_lease_ownership_preserved(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        for node_id in ("node-o1", "node-o2"):
            test_client.post("/api/v1/nodes/register", json={
                "node_id": node_id, "hostname": "h",
                "capabilities": ["exec:system_inventory"],
                "node_token": f"owner-token-{node_id}-123"})
        task = test_client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": [
                "exec:system_inventory"]}).json()
        assert test_client.post(
            "/api/v1/tasks/claim/node-o1",
            params={
                "node_token": "owner-token-node-o1-123"}
        ).json()["id"] == task["id"]
        # Foreign completion is refused.
        assert test_client.post(
            f"/api/v1/tasks/{task['id']}/complete",
            params={"node_id": "node-o2"},
            json={"success": True, "result": {}}).status_code == 404
        # Owner completes within lease.
        assert test_client.post(
            f"/api/v1/tasks/{task['id']}/complete",
            params={"node_id": "node-o1"},
            json={"success": True, "result": {}}).status_code == 204


def test_retry_bounded_for_software_tasks(tmp_path, monkeypatch):
    from coordinator.app.database import connection
    from coordinator.app.main import MAX_ATTEMPTS, expire_leases
    for test_client in make_client(tmp_path, monkeypatch):
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-r1", "hostname": "h",
            "capabilities": ["exec:system_inventory"],
            "node_token": "retry-token-123456"})
        task = test_client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": [
                "exec:system_inventory"]}).json()
        for _ in range(MAX_ATTEMPTS):
            assert test_client.post(
                "/api/v1/tasks/claim/node-r1",
                params={
                    "node_token": "retry-token-123456"}
            ).json() is not None
            with connection() as db:
                db.execute(
                    "UPDATE tasks SET lease_until=? WHERE id=?",
                    ("2020-01-01T00:00:00+00:00", task["id"]))
            expire_leases("2026-01-01T00:00:00+00:00")
        with connection() as db:
            row = db.execute(
                "SELECT status, attempt_count FROM tasks WHERE id=?",
                (task["id"],)).fetchone()
        assert row["attempt_count"] == MAX_ATTEMPTS
        with connection() as db:
            db.execute(
                "UPDATE tasks SET status='assigned', lease_until=? "
                "WHERE id=?",
                ("2020-01-01T00:00:00+00:00", task["id"]))
        summary = expire_leases("2026-01-01T00:00:00+00:00")
        assert summary["failed"] == 1
        with connection() as db:
            assert db.execute(
                "SELECT status FROM tasks WHERE id=?",
                (task["id"],)).fetchone()["status"] == "failed"


def test_no_cloud_no_public_bind_no_shell():
    source = (APP / "routing.py").read_text(encoding="utf-8") + \
        (APP / "nodes.py").read_text(encoding="utf-8") + \
        (APP / "sim_nodes.py").read_text(encoding="utf-8")
    for token in ("https://", "boto", "kubernetes", "celery",
                  "redis", "subprocess", "os.system", "eval(",
                  "0.0.0.0", "port_forward", "public"):
        assert token not in source, f"forbidden token: {token}"
    main_source = (APP / "main.py").read_text(encoding="utf-8")
    assert "127.0.0.1" in main_source


def test_no_privilege_escalation_surface():
    source = (APP / "routing.py").read_text(encoding="utf-8")
    # Routing compares advertisements; it never registers nodes,
    # writes capabilities or touches the database.
    for token in ("escalat", "INSERT", "UPDATE", "DELETE",
                  "register_node", "grant_capability"):
        assert token not in source, f"forbidden token: {token}"
    nodes_source = (APP / "nodes.py").read_text(encoding="utf-8")
    assert "escalat" not in nodes_source
