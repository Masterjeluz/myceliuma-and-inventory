"""H1 auto-dispatch: mission step -> queue task -> node -> receipt.

Approved/running missions with a dispatchable research step
(parameters.dispatch is True + explicit source_urls) stage
research.fetch_url queue tasks; the step becomes dispatched and
tick waits. Claim/complete/lease/ownership gates are untouched.
H3 (result -> step close-out) closes the step once every linked
task completed successfully (see tests/test_mission_closeout.py).

Real coordinator routes + tmp DBs throughout; no network (fetch
execution is never invoked — receipts are simulated by the
claiming worker, exactly like a node reporting back).
"""

import coordinator.app.main as main_mod
from fastapi.testclient import TestClient

TOKEN = "dispatch-token-abcdef-123456"
URL = "https://example.com/onderzoek"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "dispatch-queue.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "dispatch-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def make_conversation(client):
    return client.post("/api/v1/chat", json={
        "message": "dispatch keten", "project_ref": "dispatch-ws"}).json()[
        "conversation_id"]


def make_mission(client, conv, steps, max_steps=3):
    response = client.post("/api/v1/missions", json={
        "conversation_id": conv, "goal": "Dispatch keten",
        "steps": steps, "max_steps": max_steps})
    assert response.status_code == 201, response.text
    return response.json()["mission_id"]


def research_step(dispatch=True):
    params = {"question": "Wat is mycelium?",
              "source_urls": [URL]}
    if dispatch:
        params["dispatch"] = True
    return {"kind": "research", "description": "haal bron op",
            "parameters": params}


def approve(client, mission_id):
    response = client.post(f"/api/v1/missions/{mission_id}/approve",
                           json={"response": "YES"})
    assert response.status_code == 200, response.text


def mission_state(client, mission_id):
    return client.get(f"/api/v1/missions/{mission_id}").json()


def tasks_for_mission(client, mission_id):
    return [row for row in client.get("/api/v1/tasks").json()
            if row.get("mission_id") == mission_id]


def register_worker(client, node_id="worker-1"):
    response = client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": node_id, "tier": "worker",
        "capabilities": ["research.fetch"], "cpu_cores": 2,
        "memory_mb": 4000, "energy_source": "grid",
        "node_token": TOKEN})
    assert response.status_code == 201, response.text


def test_dispatch_happy_path(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        mission_id = make_mission(
            client, make_conversation(client), [research_step()])
        approve(client, mission_id)
        step_id = mission_state(
            client, mission_id)["steps"][0]["step_id"]
        response = client.post(
            f"/api/v1/missions/{mission_id}/dispatch",
            json={"step_id": step_id})
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["task_ids"]) == 1
        task_id = body["task_ids"][0]
        rows = tasks_for_mission(client, mission_id)
        assert len(rows) == 1
        task = rows[0]
        assert task["id"] == task_id
        assert task["status"] == "queued"
        assert task["kind"] == "research.fetch_url"
        assert task["payload"]["mission_step_id"] == step_id
        assert task["payload"]["url"] == URL
        assert "mycelium" in task["payload"]["question"].lower()
        state = mission_state(client, mission_id)
        assert state["steps"][0]["status"] == "dispatched"
        events = client.get(
            f"/api/v1/missions/{mission_id}/events").json()
        assert any(row.get("event_type") == "task_dispatched"
                   and row.get("step_id") == step_id
                   for row in events)


def test_dispatch_via_tick(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        mission_id = make_mission(
            client, make_conversation(client), [research_step()])
        approve(client, mission_id)
        step_id = mission_state(
            client, mission_id)["steps"][0]["step_id"]
        response = client.post(
            f"/api/v1/missions/{mission_id}/tick")
        assert response.status_code == 200, response.text
        assert response.json()["outcome"] == "waiting"
        rows = tasks_for_mission(client, mission_id)
        assert len(rows) == 1
        assert rows[0]["payload"]["mission_step_id"] == step_id
        assert mission_state(client, mission_id)[
            "steps"][0]["status"] == "dispatched"


def test_dispatch_idempotent(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        mission_id = make_mission(
            client, make_conversation(client), [research_step()])
        approve(client, mission_id)
        step_id = mission_state(
            client, mission_id)["steps"][0]["step_id"]
        first = client.post(
            f"/api/v1/missions/{mission_id}/dispatch",
            json={"step_id": step_id}).json()
        second = client.post(
            f"/api/v1/missions/{mission_id}/dispatch",
            json={"step_id": step_id}).json()
        assert second["task_ids"] == first["task_ids"]
        assert len(tasks_for_mission(client, mission_id)) == 1


def test_dispatch_refuses_unapproved(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        mission_id = make_mission(
            client, make_conversation(client), [research_step()])
        step_id = mission_state(
            client, mission_id)["steps"][0]["step_id"]
        response = client.post(
            f"/api/v1/missions/{mission_id}/dispatch",
            json={"step_id": step_id})
        assert response.status_code == 409, response.text
        assert tasks_for_mission(client, mission_id) == []
        assert mission_state(client, mission_id)[
            "steps"][0]["status"] == "pending"


def test_dispatch_unknown_step_404(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        mission_id = make_mission(
            client, make_conversation(client), [research_step()])
        approve(client, mission_id)
        response = client.post(
            f"/api/v1/missions/{mission_id}/dispatch",
            json={"step_id": "stp_nonexistent"})
        assert response.status_code == 404, response.text
        assert tasks_for_mission(client, mission_id) == []


def test_dispatch_forbidden_kind_422(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        mission_id = make_mission(client, make_conversation(client), [{
            "kind": "analysis", "description": "denk na",
            "parameters": {"dispatch": True}}])
        approve(client, mission_id)
        step_id = mission_state(
            client, mission_id)["steps"][0]["step_id"]
        response = client.post(
            f"/api/v1/missions/{mission_id}/dispatch",
            json={"step_id": step_id})
        assert response.status_code == 422, response.text
        assert tasks_for_mission(client, mission_id) == []
        assert mission_state(client, mission_id)[
            "steps"][0]["status"] == "pending"


def test_dispatch_full_queue_chain(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register_worker(client)
        mission_id = make_mission(
            client, make_conversation(client), [research_step()])
        approve(client, mission_id)
        step_id = mission_state(
            client, mission_id)["steps"][0]["step_id"]
        task_id = client.post(
            f"/api/v1/missions/{mission_id}/dispatch",
            json={"step_id": step_id}).json()["task_ids"][0]
        claimed = client.post(
            "/api/v1/tasks/claim/worker-1",
            params={"node_token": TOKEN}).json()
        assert claimed["id"] == task_id
        # Simulated node receipt (no network fetch in tests).
        done = client.post(f"/api/v1/tasks/{task_id}/complete",
                           params={"node_id": "worker-1"}, json={
                               "success": True,
                               "result": {"url": URL, "chars": 128}})
        assert done.status_code == 204, done.text
        rows = {row["id"]: row
                for row in client.get("/api/v1/tasks").json()}
        assert rows[task_id]["status"] == "completed"
        # H3 close-out: a completed H1 task closes its step.
        state = mission_state(client, mission_id)
        assert state["steps"][0]["status"] == "completed"
        events = client.get(
            f"/api/v1/missions/{mission_id}/events").json()
        assert any(row.get("event_type") == "step_completed"
                   and row.get("step_id") == step_id
                   for row in events)
        assert state["status"] in ("approved", "running")


def test_dispatch_race_single_task(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        mission_id = make_mission(
            client, make_conversation(client), [research_step()])
        approve(client, mission_id)
        step_id = mission_state(
            client, mission_id)["steps"][0]["step_id"]
        first = client.post(
            f"/api/v1/missions/{mission_id}/dispatch",
            json={"step_id": step_id})
        second = client.post(
            f"/api/v1/missions/{mission_id}/dispatch",
            json={"step_id": step_id})
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert second.json()["task_ids"] == first.json()["task_ids"]
        assert len(tasks_for_mission(client, mission_id)) == 1
        # The conditional mission save stays leading: a stale
        # expected state must refuse instead of overwriting.
        from coordinator.app.missions import (
            MissionConflictError,
            load_mission,
            save_mission,
        )
        mission = load_mission(mission_id)
        try:
            save_mission(mission, expected=("approved", 99))
        except MissionConflictError:
            refused = True
        else:
            refused = False
        assert refused


def test_dispatch_zero_eligible_nodes(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        mission_id = make_mission(
            client, make_conversation(client), [research_step()])
        approve(client, mission_id)
        step_id = mission_state(
            client, mission_id)["steps"][0]["step_id"]
        body = client.post(
            f"/api/v1/missions/{mission_id}/dispatch",
            json={"step_id": step_id}).json()
        assert len(body["task_ids"]) == 1
        assert body["eligible_nodes"] == []
        rows = tasks_for_mission(client, mission_id)
        assert len(rows) == 1
        assert rows[0]["status"] == "queued"


def test_no_flag_keeps_inline_behavior(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        mission_id = make_mission(client, make_conversation(client), [{
            "kind": "research", "description": "zonder dispatch",
            "parameters": {"research_run_id": "res_nonexistent123"}}])
        approve(client, mission_id)
        response = client.post(
            f"/api/v1/missions/{mission_id}/tick")
        assert response.status_code == 200, response.text
        # Inline runner attempted (missing run -> blocked), never
        # dispatched: no queue task, step not dispatched.
        assert tasks_for_mission(client, mission_id) == []
        assert mission_state(client, mission_id)[
            "steps"][0]["status"] != "dispatched"
