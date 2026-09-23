"""Lease-sweep endpoint tests: POST /api/v1/maintenance/sweep-leases.

Drives the full HTTP path (register/claim/propose/decide/dispatch),
moves only lease clocks directly in the test databases, then sweeps.
No worker runs, nothing is ever completed or executed by these tests.
"""

import json

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.main import MAX_ATTEMPTS

TOKEN = "sweep-token-1234"
PAST = "2000-01-01T00:00:00+00:00"


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "sweep.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "sweep-state.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def register(test_client, node_id="sweep-node"):
    res = test_client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": "sweep", "tier": "worker",
        "capabilities": ["code.patch"], "executors": ["exec:code"],
        "cpu_cores": 4, "memory_mb": 8192, "node_token": TOKEN})
    assert res.status_code == 201, res.text


def queue(test_client, kind="code.patch", goal="Fix it"):
    res = test_client.post("/api/v1/tasks", json={
        "kind": kind, "required_capabilities": ["code.patch"],
        "payload": {"goal": goal}})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def claim(test_client, node_id="sweep-node"):
    res = test_client.post(
        f"/api/v1/tasks/claim/{node_id}?node_token={TOKEN}")
    assert res.status_code == 200, res.text
    return res.json()


def task_row(task_id):
    from coordinator.app.database import connection
    with connection() as db:
        return db.execute("SELECT * FROM tasks WHERE id=?",
                          (task_id,)).fetchone()


def set_lease(task_id, lease_until=None, attempts=None):
    from coordinator.app.database import connection
    with connection() as db:
        if attempts is None:
            db.execute("UPDATE tasks SET lease_until=? WHERE id=?",
                       (lease_until, task_id))
        else:
            db.execute("UPDATE tasks SET lease_until=?, "
                       "attempt_count=? WHERE id=?",
                       (lease_until, attempts, task_id))


def sweep(test_client):
    res = test_client.post("/api/v1/maintenance/sweep-leases")
    assert res.status_code == 200, res.text
    return res.json()


def test_expired_task_lease_requeued(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        register(test_client)
        task_id = queue(test_client)
        assert claim(test_client)["id"] == task_id
        assert task_row(task_id)["status"] == "assigned"
        set_lease(task_id, PAST)
        body = sweep(test_client)
        assert body["tasks"]["requeued"] == 1
        assert set(body["tasks"]) == {"requeued", "failed",
                                      "blocked"}
        stored = task_row(task_id)
        assert stored["status"] == "queued"
        assert stored["assigned_node_id"] is None
        assert stored["result"] is None  # never executed


def test_active_task_lease_untouched(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        register(test_client)
        task_id = queue(test_client)
        assert claim(test_client)["id"] == task_id
        body = sweep(test_client)
        assert body["tasks"] == {"requeued": 0, "failed": 0,
                                 "blocked": 0}
        assert task_row(task_id)["status"] == "assigned"


def test_exhausted_task_lease_fails_not_requeued(tmp_path,
                                                 monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        register(test_client)
        task_id = queue(test_client)
        assert claim(test_client)["id"] == task_id
        set_lease(task_id, PAST, attempts=MAX_ATTEMPTS)
        body = sweep(test_client)
        assert body["tasks"]["failed"] == 1
        assert body["tasks"]["requeued"] == 0
        assert task_row(task_id)["status"] == "failed"


def test_expired_desktop_lease_recovered(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        created = test_client.post(
            "/api/v1/desktop/actions",
            json={"action_type": "click",
                  "parameters": {"x": 10, "y": 10},
                  "action_id": "dact-sweep"})
        assert created.status_code == 201, created.text
        decided = test_client.post(
            "/api/v1/desktop/actions/dact-sweep/decision",
            json={"response": "YES", "decided_by": "sweep"})
        assert decided.json()["status"] == "approved"
        dispatched = test_client.post(
            "/api/v1/desktop/actions/dact-sweep/dispatch")
        assert dispatched.json()["status"] == "dispatched"
        _expire_desktop_lease("dact-sweep")
        body = sweep(test_client)
        assert body["desktop_actions"]["recovered"] == 1
        assert set(body["desktop_actions"]) == {"recovered",
                                                "blocked"}
        again = test_client.get(
            "/api/v1/desktop/actions/dact-sweep")
        assert again.json()["status"] == "approved"


def test_active_desktop_lease_untouched(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        created = test_client.post(
            "/api/v1/desktop/actions",
            json={"action_type": "click",
                  "parameters": {"x": 10, "y": 10},
                  "action_id": "dact-active"})
        assert created.status_code == 201, created.text
        test_client.post(
            "/api/v1/desktop/actions/dact-active/decision",
            json={"response": "YES", "decided_by": "sweep"})
        test_client.post(
            "/api/v1/desktop/actions/dact-active/dispatch")
        body = sweep(test_client)
        assert body["desktop_actions"] == {"recovered": 0,
                                           "blocked": 0}
        again = test_client.get(
            "/api/v1/desktop/actions/dact-active")
        assert again.json()["status"] == "dispatched"


def test_exhausted_desktop_lease_blocked(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        created = test_client.post(
            "/api/v1/desktop/actions",
            json={"action_type": "click",
                  "parameters": {"x": 10, "y": 10},
                  "action_id": "dact-tired"})
        assert created.status_code == 201, created.text
        test_client.post(
            "/api/v1/desktop/actions/dact-tired/decision",
            json={"response": "YES", "decided_by": "sweep"})
        test_client.post(
            "/api/v1/desktop/actions/dact-tired/dispatch")
        _expire_desktop_lease("dact-tired", attempts=3)
        body = sweep(test_client)
        assert body["desktop_actions"]["blocked"] == 1
        again = test_client.get(
            "/api/v1/desktop/actions/dact-tired")
        assert again.json()["status"] == "blocked"


def test_sweep_summary_shape_and_no_side_tasks(tmp_path,
                                               monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        body = sweep(test_client)
        assert set(body) == {"tasks", "desktop_actions"}
        assert body["tasks"] == {"requeued": 0, "failed": 0,
                                 "blocked": 0}
        assert body["desktop_actions"] == {"recovered": 0,
                                           "blocked": 0}
        listed = test_client.get("/api/v1/tasks")
        assert listed.json() == []


def _expire_desktop_lease(action_id, attempts=None):
    """Test-only clock move: backdate lease_until inside the stored
    desktop-action record (chat DB). Production code untouched."""
    from coordinator.app.database import chat_connection
    with chat_connection() as db:
        row = db.execute("SELECT record FROM desktop_actions "
                         "WHERE action_id=?", (action_id,)).fetchone()
        assert row is not None
        record = json.loads(row["record"])
        record["lease_until"] = PAST
        if attempts is not None:
            record["attempt_count"] = attempts
        db.execute("UPDATE desktop_actions SET record=? "
                   "WHERE action_id=?",
                   (json.dumps(record), action_id))
