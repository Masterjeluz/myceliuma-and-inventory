"""Task-ownership tests: one agent cannot close another's work.

Completing requires the assigned identity (query or body, matching
how existing workers already send it). Anonymous and foreign
completions are refused exactly like unknown tasks. Stale nodes
claim nothing; assigned tasks are invisible to other claimants.
"""

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN_A = "owner-token-aaaaaaaa"
TOKEN_B = "owner-token-bbbbbbbb"


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "own.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "own-state.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def register(test_client, node_id, token):
    res = test_client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": "own", "tier": "worker",
        "capabilities": ["code.patch"], "executors": ["exec:code"],
        "node_token": token})
    assert res.status_code == 201, res.text


def queue(test_client):
    res = test_client.post("/api/v1/tasks", json={
        "kind": "code.patch", "required_capabilities": ["code.patch"],
        "payload": {"goal": "Own me"}})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def claim(test_client, node_id, token):
    res = test_client.post(
        f"/api/v1/tasks/claim/{node_id}?node_token={token}")
    assert res.status_code == 200, res.text
    return res.json()


def complete(test_client, task_id, body):
    return test_client.post(f"/api/v1/tasks/{task_id}/complete",
                            json=body)


def done_body(node_id=None):
    body = {"success": True, "result": {"summary": "done"},
            "error": None}
    if node_id is not None:
        body["node_id"] = node_id
    return body


def test_anonymous_complete_refused(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        register(test_client, "own-a", TOKEN_A)
        task_id = queue(test_client)
        assert claim(test_client, "own-a", TOKEN_A)["id"] == task_id
        res = complete(test_client, task_id, done_body())
        assert res.status_code == 404, res.text
        listed = test_client.get("/api/v1/tasks").json()
        assert listed[0]["status"] == "assigned"


def test_foreign_complete_refused(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        register(test_client, "own-a", TOKEN_A)
        register(test_client, "own-b", TOKEN_B)
        task_id = queue(test_client)
        assert claim(test_client, "own-a", TOKEN_A)["id"] == task_id
        res = complete(test_client, task_id, done_body("own-b"))
        assert res.status_code == 404, res.text
        listed = test_client.get("/api/v1/tasks").json()
        assert listed[0]["status"] == "assigned"
        assert listed[0]["assigned_node_id"] == "own-a"


def test_owner_complete_via_body(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        register(test_client, "own-a", TOKEN_A)
        task_id = queue(test_client)
        claim(test_client, "own-a", TOKEN_A)
        res = complete(test_client, task_id, done_body("own-a"))
        assert res.status_code == 204, res.text
        assert test_client.get("/api/v1/tasks").json()[0][
            "status"] == "completed"


def test_owner_complete_via_query(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        register(test_client, "own-a", TOKEN_A)
        task_id = queue(test_client)
        claim(test_client, "own-a", TOKEN_A)
        res = test_client.post(
            f"/api/v1/tasks/{task_id}/complete?node_id=own-a",
            json={"success": True, "result": {}, "error": None})
        assert res.status_code == 204, res.text


def test_second_agent_cannot_claim_assigned_task(tmp_path,
                                                 monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        register(test_client, "own-a", TOKEN_A)
        register(test_client, "own-b", TOKEN_B)
        queue(test_client)
        assert claim(test_client, "own-a", TOKEN_A) is not None
        assert claim(test_client, "own-b", TOKEN_B) is None


def test_stale_node_claims_nothing(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        register(test_client, "own-a", TOKEN_A)
        queue(test_client)
        from coordinator.app.database import connection
        with connection() as db:
            db.execute("UPDATE nodes SET last_seen=? "
                       "WHERE node_id=?",
                       ("2000-01-01T00:00:00+00:00", "own-a"))
        assert claim(test_client, "own-a", TOKEN_A) is None


def test_completion_emits_audit_event(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        register(test_client, "own-a", TOKEN_A)
        task_id = queue(test_client)
        claim(test_client, "own-a", TOKEN_A)
        complete(test_client, task_id, done_body("own-a"))
        events = test_client.get("/api/v1/events").json()
        finished = [entry for entry in events
                    if entry.get("event_type") == "task.completed"]
        assert finished, "completion must stay on the audit bus"
        assert finished[0].get("node_id") == "own-a"
