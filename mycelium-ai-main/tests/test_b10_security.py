"""BIG #10 security tripwires.

Old epochs, duplicate events, preserved conflicts, fencing
on assign/claim, Live capability denial, push separation,
bounded sync, traversal protection.
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b10.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b10-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def register(test_client, node_id, capable=True, token=None):
    body = {"node_id": node_id, "hostname": "h",
            "capabilities": ["exec:system_inventory"],
            "coordinator_capable": capable}
    if token:
        body["node_token"] = token
    response = test_client.post("/api/v1/nodes/register",
                                json=body)
    assert response.status_code == 201, response.text


def test_old_epoch_write_refused(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        register(test_client, "node-old1")
        assert test_client.post("/api/v1/coordinator/campaign",
                                json={
                                    "node_id": "node-old1"}
                                ).status_code == 200
        task = test_client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": [
                "exec:system_inventory"]}).json()
        assigned = test_client.post(
            f"/api/v1/tasks/{task['id']}/assign",
            json={"policy": {
                "require_authenticated": False}}).json()
        assert assigned["routing"]["epoch"] == 1
        # New epoch rotates authority: the old assignment fences.
        register(test_client, "node-old2")
        test_client.post("/api/v1/coordinator/release",
                         json={"node_id": "node-old1"})
        from coordinator.app.database import connection
        with connection() as db:
            db.execute("UPDATE nodes SET status='disabled' "
                       "WHERE node_id='node-old1'")
        assert test_client.post("/api/v1/coordinator/campaign",
                                json={
                                    "node_id": "node-old2"}
                                ).status_code == 200
        status = test_client.get(
            "/api/v1/coordinator/status").json()
        assert status["epoch"] == 2
        assert status["holder"] == "node-old2"
        assert test_client.post(
            "/api/v1/tasks/claim/node-old1").json() is None
        assert test_client.post(
            "/api/v1/tasks/claim/node-old2").json() is None


def test_fresh_assignment_claims_after_election(tmp_path,
                                                monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        register(test_client, "node-f1")
        test_client.post("/api/v1/coordinator/campaign",
                         json={"node_id": "node-f1"})
        task = test_client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": [
                "exec:system_inventory"]}).json()
        assigned = test_client.post(
            f"/api/v1/tasks/{task['id']}/assign",
            json={"policy": {
                "require_authenticated": False}}).json()
        assert assigned["routing"]["epoch"] == 1
        claimed = test_client.post(
            "/api/v1/tasks/claim/node-f1").json()
        assert claimed["id"] == task["id"]


def test_duplicate_sync_event_no_double_apply(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        item = {"event_id": "dsevt_dup1",
                "origin_node_id": "node-a",
                "entity_id": "obj_9", "entity_type": "object",
                "entity_revision": "rev-1", "base_revision": "",
                "event_type": "entity.observed", "timestamp": "",
                "payload": {"note": "x"}, "provenance": {},
                "epoch": 0}
        first = test_client.post("/api/v1/sync/apply",
                                 json={"items": [item, item]}).json()
        assert first["applied"] == 1
        assert first["duplicates"] == 1
        second = test_client.post("/api/v1/sync/apply",
                                  json={"items": [item]}).json()
        assert second == {"applied": 0, "duplicates": 1,
                          "conflicts": 0, "failed": 0,
                          "conflict_ids": [], "applied_ids": [item[
                              "event_id"]]}


def test_conflict_preserved_not_merged(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        base = {"event_id": "dsevt_c0",
                "origin_node_id": "node-a",
                "entity_id": "obj_7", "entity_type": "object",
                "entity_revision": "rev-1", "base_revision": "",
                "event_type": "entity.observed", "timestamp": "",
                "payload": {}, "provenance": {}, "epoch": 0}
        assert test_client.post("/api/v1/sync/apply",
                                json={"items": [base]}).json()[
                                    "applied"] == 1
        mine = dict(base, event_id="dsevt_c1",
                    entity_revision="rev-2a",
                    base_revision="rev-1",
                    payload={"color": "red"})
        theirs = dict(base, event_id="dsevt_c2",
                      origin_node_id="node-b",
                      entity_revision="rev-2b",
                      base_revision="rev-1",
                      payload={"color": "blue"})
        assert test_client.post("/api/v1/sync/apply",
                                json={"items": [mine]}).json()[
                                    "applied"] == 1
        outcome = test_client.post("/api/v1/sync/apply",
                                   json={"items": [theirs]}).json()
        assert outcome["conflicts"] == 1
        conflicts = test_client.get(
            "/api/v1/dist/conflicts").json()
        assert len(conflicts) == 1
        assert conflicts[0]["status"] == "open"
        resolved = test_client.post(
            f"/api/v1/dist/conflicts/{conflicts[0]['conflict_id']}"
            "/resolve").json()
        assert resolved["status"] == "resolved"
        assert test_client.post(
            f"/api/v1/dist/conflicts/{conflicts[0]['conflict_id']}"
            "/resolve").status_code == 404


def test_live_capability_denied(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        session_id = test_client.post("/api/v1/live/sessions",
                                      json={
                                          "interface": "web",
                                          "actor": "jelles",
                                          "capabilities": [
                                              "task.read"]}).json()[
                                                  "session_id"]
        assert test_client.post("/api/v1/live/propose", json={
            "session_id": session_id, "kind": "inventory_write",
            "target": "inventory:object",
            "payload": {"entity_type": "object",
                        "fields": {"name": "x"}}}).status_code == 403
        assert test_client.post("/api/v1/live/context", json={
            "session_id": "live-missing"}).status_code == 404
        test_client.post(
            f"/api/v1/live/sessions/{session_id}/revoke")
        assert test_client.post("/api/v1/live/context", json={
            "session_id": session_id}).status_code == 403


def test_sync_bounded_and_validated(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        page = test_client.get("/api/v1/sync/changes",
                               params={"after": 0,
                                       "limit": 5}).json()
        assert page["items"] == []
        assert page["latest"] == 0
        assert test_client.get("/api/v1/sync/changes",
                               params={"after": "nope"}
                               ).status_code == 422
        evil = test_client.post("/api/v1/sync/apply", json={
            "items": [{"event_id": "dsevt_e1",
                       "origin_node_id": "node-a",
                       "entity_id": "obj_1",
                       "entity_type": "object",
                       "event_type": "entity.observed",
                       "payload": {"command": "rm"}}]}).json()
        assert evil["failed"] == 1
        status = test_client.get("/api/v1/sync/status",
                                 params={"cursor": 0}).json()
        assert status["pending"] == 0
        assert "epoch" in status


def test_no_shell_sql_cloud_in_new_modules():
    import pathlib
    app = pathlib.Path(__file__).resolve().parent.parent / \
        "coordinator" / "app"
    source = "\n".join(
        (app / name).read_text(encoding="utf-8")
        for name in ("diststate.py", "failover.py", "sync.py",
                     "live.py", "watcher.py", "reports.py",
                     "domains.py"))
    for token in ("subprocess", "os.system", "eval(",
                  "import sqlite3", "https://", "boto",
                  "kubernetes", "0.0.0.0"):
        assert token not in source, f"forbidden token: {token}"
