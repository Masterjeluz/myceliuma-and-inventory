"""Mission -> task binding tests: traceability only, never execution.

mission_id on a queue task must reference a real mission, survive
claim/lease/complete untouched, and never cause any automatic
execution. Tasks without mission_id keep working unchanged.
"""

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN = "bind-token-123456"


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "bind.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "bind-state.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def register(test_client, node_id="bind-node"):
    res = test_client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": "bind", "tier": "worker",
        "capabilities": ["code.patch"], "executors": ["exec:code"],
        "node_token": TOKEN})
    assert res.status_code == 201, res.text


def make_mission(test_client, goal="Bind the trace"):
    chat = test_client.post("/api/v1/chat", json={"message": "hi"})
    assert chat.status_code == 200, chat.text
    res = test_client.post("/api/v1/missions", json={
        "conversation_id": chat.json()["conversation_id"],
        "goal": goal,
        "steps": [{"kind": "readout", "description": "Lees",
                   "parameters": {"source": "project"}}]})
    assert res.status_code == 201, res.text
    return res.json()["mission_id"]


def queue(test_client, body):
    res = test_client.post("/api/v1/tasks", json=body)
    return res


def task_row(task_id):
    from coordinator.app.database import connection
    with connection() as db:
        return db.execute("SELECT * FROM tasks WHERE id=?",
                          (task_id,)).fetchone()


def test_mission_task_carries_mission_id(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        mission_id = make_mission(test_client)
        res = queue(test_client, {
            "kind": "code.patch",
            "required_capabilities": ["code.patch"],
            "payload": {"goal": "Patch it"},
            "mission_id": mission_id})
        assert res.status_code == 201, res.text
        task_id = res.json()["id"]
        assert task_row(task_id)["mission_id"] == mission_id
        listed = test_client.get("/api/v1/tasks").json()
        assert listed[0]["mission_id"] == mission_id
        single = test_client.get(
            f"/api/v1/tasks/by-id/{task_id}").json()
        assert single["mission_id"] == mission_id


def test_general_task_without_mission_id_still_works(tmp_path,
                                                     monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        register(test_client)
        res = queue(test_client, {
            "kind": "code.patch",
            "required_capabilities": ["code.patch"],
            "payload": {"goal": "General work"}})
        assert res.status_code == 201, res.text
        task_id = res.json()["id"]
        assert task_row(task_id)["mission_id"] is None
        claimed = test_client.post(
            f"/api/v1/tasks/claim/bind-node?node_token={TOKEN}")
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["id"] == task_id


def test_unknown_mission_id_refused(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        res = queue(test_client, {
            "kind": "code.patch",
            "required_capabilities": ["code.patch"],
            "payload": {"goal": "Orphan"},
            "mission_id": "mission_does_not_exist"})
        assert res.status_code == 422, res.text
        assert test_client.get("/api/v1/tasks").json() == []


def test_mission_id_survives_claim_and_complete(tmp_path,
                                                monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        register(test_client)
        mission_id = make_mission(test_client)
        task_id = queue(test_client, {
            "kind": "code.patch",
            "required_capabilities": ["code.patch"],
            "payload": {"goal": "Trace me"},
            "mission_id": mission_id}).json()["id"]
        claimed = test_client.post(
            f"/api/v1/tasks/claim/bind-node?node_token={TOKEN}")
        assert claimed.json()["id"] == task_id
        assert task_row(task_id)["mission_id"] == mission_id
        done = test_client.post(
            f"/api/v1/tasks/{task_id}/complete", json={
                "success": True, "result": {"summary": "patched"},
                "error": None, "node_id": "bind-node"})
        assert done.status_code == 204, done.text
        stored = task_row(task_id)
        assert stored["status"] == "completed"
        assert stored["mission_id"] == mission_id


def test_mission_id_survives_lease_sweep(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        register(test_client)
        mission_id = make_mission(test_client)
        task_id = queue(test_client, {
            "kind": "code.patch",
            "required_capabilities": ["code.patch"],
            "payload": {"goal": "Lease me"},
            "mission_id": mission_id}).json()["id"]
        test_client.post(
            f"/api/v1/tasks/claim/bind-node?node_token={TOKEN}")
        from coordinator.app.database import connection
        with connection() as db:
            db.execute("UPDATE tasks SET lease_until=? WHERE id=?",
                       ("2000-01-01T00:00:00+00:00", task_id))
        swept = test_client.post("/api/v1/maintenance/sweep-leases")
        assert swept.status_code == 200, swept.text
        assert swept.json()["tasks"]["requeued"] == 1
        stored = task_row(task_id)
        assert stored["status"] == "queued"
        assert stored["mission_id"] == mission_id


def test_mission_id_alone_causes_no_execution(tmp_path,
                                              monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        mission_id = make_mission(test_client)
        task_id = queue(test_client, {
            "kind": "code.patch",
            "required_capabilities": ["code.patch"],
            "payload": {"goal": "Stay queued"},
            "mission_id": mission_id}).json()["id"]
        stored = task_row(task_id)
        assert stored["status"] == "queued"
        assert stored["assigned_node_id"] is None
        assert stored["result"] is None
