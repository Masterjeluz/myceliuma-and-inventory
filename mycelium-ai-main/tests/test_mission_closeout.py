"""H3 close-out: completed H1-task -> mission-step completed.

H1 auto-dispatch stages research.fetch_url queue tasks and marks the
step dispatched; H3 adds only the missing feedback: when the linked
task(s) complete successfully, the reloaded step moves
dispatched -> completed via the existing conditional save, with the
existing step_completed mission event. No auto-advance (tick stays
responsible), no approval change, no new tables.

Real coordinator routes + tmp DBs throughout; no network.
"""

import coordinator.app.main as main_mod
from fastapi.testclient import TestClient

TOKEN = "closeout-token-abcdef-123456"
URL1 = "https://example.com/onderzoek-1"
URL2 = "https://example.com/onderzoek-2"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "closeout-queue.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "closeout-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def make_conversation(client):
    return client.post("/api/v1/chat", json={
        "message": "closeout keten", "project_ref": "closeout-ws"}).json()[
        "conversation_id"]


def make_mission(client, conv, steps, max_steps=3):
    response = client.post("/api/v1/missions", json={
        "conversation_id": conv, "goal": "Closeout keten",
        "steps": steps, "max_steps": max_steps})
    assert response.status_code == 201, response.text
    return response.json()["mission_id"]


def research_step(urls, dispatch=True):
    params = {"question": "Wat is mycelium?",
              "source_urls": list(urls)}
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


def mission_events(client, mission_id):
    return client.get(f"/api/v1/missions/{mission_id}/events").json()


def step_completed_events(client, mission_id, step_id):
    return [row for row in mission_events(client, mission_id)
            if row.get("event_type") == "step_completed"
            and row.get("step_id") == step_id]


def register_worker(client, node_id="worker-1", caps=None):
    response = client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": node_id, "tier": "worker",
        "capabilities": caps or ["research.fetch"], "cpu_cores": 2,
        "memory_mb": 4000, "energy_source": "grid",
        "node_token": TOKEN})
    assert response.status_code == 201, response.text


def dispatch(client, mission_id, step_id):
    response = client.post(
        f"/api/v1/missions/{mission_id}/dispatch",
        json={"step_id": step_id})
    assert response.status_code == 200, response.text
    return response.json()["task_ids"]


def claim(client, node_id="worker-1"):
    response = client.post(
        f"/api/v1/tasks/claim/{node_id}",
        params={"node_token": TOKEN})
    assert response.status_code == 200, response.text
    return response.json()


def complete(client, task_id, node_id="worker-1", success=True):
    body = {"success": success, "node_id": node_id}
    if success:
        body["result"] = {"url": URL1, "chars": 128}
    else:
        body["error"] = "fetch failed"
    done = client.post(f"/api/v1/tasks/{task_id}/complete",
                       params={"node_id": node_id}, json=body)
    assert done.status_code == 204, done.text


def task_status(client, task_id):
    rows = {row["id"]: row for row in client.get("/api/v1/tasks").json()}
    return rows[task_id]["status"]


def test_1_dispatched_task_completed_closes_step(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register_worker(client)
        mission_id = make_mission(
            client, make_conversation(client),
            [research_step([URL1])])
        approve(client, mission_id)
        step_id = mission_state(
            client, mission_id)["steps"][0]["step_id"]
        task_id = dispatch(client, mission_id, step_id)[0]
        assert claim(client)["id"] == task_id
        complete(client, task_id)
        assert task_status(client, task_id) == "completed"
        state = mission_state(client, mission_id)
        assert state["steps"][0]["status"] == "completed"
        assert len(step_completed_events(
            client, mission_id, step_id)) == 1


def test_2_two_tasks_close_only_when_all_done(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register_worker(client)
        mission_id = make_mission(
            client, make_conversation(client),
            [research_step([URL1, URL2])])
        approve(client, mission_id)
        step_id = mission_state(
            client, mission_id)["steps"][0]["step_id"]
        task_ids = dispatch(client, mission_id, step_id)
        assert len(task_ids) == 2
        first = claim(client)
        assert first["id"] in task_ids
        complete(client, first["id"])
        assert task_status(client, first["id"]) == "completed"
        # First done, second still open: step stays dispatched.
        assert mission_state(client, mission_id)[
            "steps"][0]["status"] == "dispatched"
        assert step_completed_events(
            client, mission_id, step_id) == []
        second = claim(client)
        assert second["id"] in task_ids and second["id"] != first["id"]
        complete(client, second["id"])
        assert mission_state(client, mission_id)[
            "steps"][0]["status"] == "completed"
        assert len(step_completed_events(
            client, mission_id, step_id)) == 1


def test_3_failed_sibling_keeps_step_dispatched(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register_worker(client)
        mission_id = make_mission(
            client, make_conversation(client),
            [research_step([URL1, URL2])])
        approve(client, mission_id)
        step_id = mission_state(
            client, mission_id)["steps"][0]["step_id"]
        task_ids = dispatch(client, mission_id, step_id)
        assert len(task_ids) == 2
        failed = claim(client)
        complete(client, failed["id"], success=False)
        assert task_status(client, failed["id"]) == "failed"
        other = claim(client)
        complete(client, other["id"], success=True)
        assert task_status(client, other["id"]) == "completed"
        state = mission_state(client, mission_id)
        assert state["steps"][0]["status"] == "dispatched"
        assert step_completed_events(
            client, mission_id, step_id) == []


def test_4_task_without_step_link_changes_nothing(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register_worker(client, caps=["research.fetch", "code.patch"])
        mission_id = make_mission(
            client, make_conversation(client),
            [research_step([URL1])])
        approve(client, mission_id)
        step_id = mission_state(
            client, mission_id)["steps"][0]["step_id"]
        before = mission_state(client, mission_id)["steps"][0]
        res = client.post("/api/v1/tasks", json={
            "kind": "code.patch",
            "required_capabilities": ["code.patch"],
            "payload": {"goal": "los werk zonder H1-metadata"}})
        assert res.status_code == 201, res.text
        task_id = res.json()["id"]
        assert claim(client)["id"] == task_id
        complete(client, task_id)
        assert task_status(client, task_id) == "completed"
        after = mission_state(client, mission_id)["steps"][0]
        assert after == before
        assert step_completed_events(
            client, mission_id, step_id) == []


def test_5_invalid_step_id_no_crash_no_change(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register_worker(client)
        mission_id = make_mission(
            client, make_conversation(client),
            [research_step([URL1])])
        approve(client, mission_id)
        step_id = mission_state(
            client, mission_id)["steps"][0]["step_id"]
        res = client.post("/api/v1/tasks", json={
            "kind": "research.fetch_url",
            "required_capabilities": ["research.fetch"],
            "payload": {"url": URL1, "mission_step_id": "step_bestaat_niet"},
            "mission_id": mission_id})
        assert res.status_code == 201, res.text
        task_id = res.json()["id"]
        assert claim(client)["id"] == task_id
        # Must not crash; task stays completed.
        done = client.post(
            f"/api/v1/tasks/{task_id}/complete",
            params={"node_id": "worker-1"},
            json={"success": True, "result": {"url": URL1},
                  "node_id": "worker-1"})
        assert done.status_code == 204, done.text
        assert task_status(client, task_id) == "completed"
        # No random step touched.
        state = mission_state(client, mission_id)
        assert state["steps"][0]["step_id"] == step_id
        assert state["steps"][0]["status"] == "pending"
        assert step_completed_events(
            client, mission_id, step_id) == []


def test_6_already_completed_step_no_duplicate_event(tmp_path,
                                                     monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register_worker(client)
        mission_id = make_mission(
            client, make_conversation(client),
            [research_step([URL1])])
        approve(client, mission_id)
        step_id = mission_state(
            client, mission_id)["steps"][0]["step_id"]
        task_id = dispatch(client, mission_id, step_id)[0]
        assert claim(client)["id"] == task_id
        complete(client, task_id)
        assert len(step_completed_events(
            client, mission_id, step_id)) == 1
        # A late duplicate task for the same (already closed) step
        # completes fine but writes no second event.
        res = client.post("/api/v1/tasks", json={
            "kind": "research.fetch_url",
            "required_capabilities": ["research.fetch"],
            "payload": {"url": URL1, "mission_step_id": step_id},
            "mission_id": mission_id})
        assert res.status_code == 201, res.text
        late_id = res.json()["id"]
        assert claim(client)["id"] == late_id
        complete(client, late_id)
        assert task_status(client, late_id) == "completed"
        assert mission_state(client, mission_id)[
            "steps"][0]["status"] == "completed"
        assert len(step_completed_events(
            client, mission_id, step_id)) == 1


def test_7_conflict_no_silent_overwrite(tmp_path, monkeypatch):
    from coordinator.app.missions import MissionConflictError
    for client in make_client(tmp_path, monkeypatch):
        register_worker(client)
        mission_id = make_mission(
            client, make_conversation(client),
            [research_step([URL1])])
        approve(client, mission_id)
        step_id = mission_state(
            client, mission_id)["steps"][0]["step_id"]
        task_id = dispatch(client, mission_id, step_id)[0]
        assert claim(client)["id"] == task_id

        def _refuse(*args, **kwargs):
            raise MissionConflictError("injected race")

        original_save = main_mod.save_mission
        monkeypatch.setattr(main_mod, "save_mission", _refuse)
        done = client.post(
            f"/api/v1/tasks/{task_id}/complete",
            params={"node_id": "worker-1"},
            json={"success": True, "result": {"url": URL1},
                  "node_id": "worker-1"})
        # Completion itself never crashes on a mission race.
        assert done.status_code == 204, done.text
        # Restore only the patched symbol (undo() would also drop
        # the tmp-DB env vars while the client still needs them).
        monkeypatch.setattr(main_mod, "save_mission", original_save)
        assert task_status(client, task_id) == "completed"
        # No blind overwrite: the step is untouched.
        assert mission_state(client, mission_id)[
            "steps"][0]["status"] == "dispatched"
        assert step_completed_events(
            client, mission_id, step_id) == []


def test_8_full_chain_tick_dispatch_claim_complete(tmp_path,
                                                   monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register_worker(client)
        mission_id = make_mission(
            client, make_conversation(client),
            [research_step([URL1])])
        approve(client, mission_id)
        step_id = mission_state(
            client, mission_id)["steps"][0]["step_id"]
        ticked = client.post(f"/api/v1/missions/{mission_id}/tick")
        assert ticked.status_code == 200, ticked.text
        assert ticked.json()["outcome"] == "waiting"
        rows = [row for row in client.get("/api/v1/tasks").json()
                if row.get("mission_id") == mission_id]
        assert len(rows) == 1
        task_id = rows[0]["id"]
        assert rows[0]["payload"]["mission_step_id"] == step_id
        assert rows[0]["status"] == "queued"
        assert claim(client)["id"] == task_id
        complete(client, task_id)
        assert task_status(client, task_id) == "completed"
        assert mission_state(client, mission_id)[
            "steps"][0]["status"] == "completed"
        assert len(step_completed_events(
            client, mission_id, step_id)) == 1


def test_9_manual_completion_without_h1_metadata(tmp_path,
                                                 monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register_worker(client, node_id="plain-node",
                        caps=["code.patch"])
        res = client.post("/api/v1/tasks", json={
            "kind": "code.patch",
            "required_capabilities": ["code.patch"],
            "payload": {"goal": "handmatig werk"}})
        assert res.status_code == 201, res.text
        task_id = res.json()["id"]
        claimed = client.post(
            "/api/v1/tasks/claim/plain-node",
            params={"node_token": TOKEN})
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["id"] == task_id
        done = client.post(
            f"/api/v1/tasks/{task_id}/complete",
            params={"node_id": "plain-node"},
            json={"success": True, "result": {"summary": "klaar"},
                  "node_id": "plain-node"})
        assert done.status_code == 204, done.text
        rows = {row["id"]: row
                for row in client.get("/api/v1/tasks").json()}
        assert rows[task_id]["status"] == "completed"


def test_10_closeout_does_not_run_next_step(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register_worker(client)
        steps = [research_step([URL1]),
                 {"kind": "readout", "description": "Lees project",
                  "parameters": {"source": "project"}}]
        mission_id = make_mission(
            client, make_conversation(client), steps, max_steps=5)
        approve(client, mission_id)
        ids = [entry["step_id"] for entry in
               mission_state(client, mission_id)["steps"]]
        task_id = dispatch(client, mission_id, ids[0])[0]
        assert claim(client)["id"] == task_id
        complete(client, task_id)
        state = mission_state(client, mission_id)
        # H3 closed step 1 only; step 2 untouched, pointer untouched.
        assert state["steps"][0]["status"] == "completed"
        assert state["steps"][1]["status"] == "pending"
        assert state["steps"][1]["result_text"] == ""
        assert state["current_step"] == 0
        # The existing executor/tick does the onward progress.
        ticked = client.post(f"/api/v1/missions/{mission_id}/tick")
        assert ticked.status_code == 200, ticked.text
        progressed = mission_state(client, mission_id)
        assert progressed["steps"][1]["status"] == "completed"
        assert progressed["current_step"] >= 1
