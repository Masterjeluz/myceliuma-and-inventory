"""MOKERPASS click-path tests (items A-I).

Every test drives the real UI bridge (/web/*) onto the real backend
endpoint and asserts gates still hold. No hardware, no shell,
no model calls: safe digital paths only.
"""


def _moker_client(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "moker.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "moker-chat.db"))
    from fastapi.testclient import TestClient
    import coordinator.app.main as main_mod
    with TestClient(main_mod.app) as test_client:
        yield test_client


def _moker_node(client, node_id="moker-node"):
    token = f"moker-token-{node_id}-123456"
    response = client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": node_id, "tier": "seed",
        "capabilities": ["system_inventory"], "node_token": token})
    assert response.status_code == 201, response.text
    response = client.post(f"/api/v1/nodes/{node_id}/heartbeat",
                           json={"available": True,
                                 "node_token": token})
    assert response.status_code == 204, response.text
    return token


def test_moker_a_system_job_run(tmp_path, monkeypatch):
    for client in _moker_client(tmp_path, monkeypatch):
        page = client.get("/system")
        assert page.status_code == 200
        assert "watcher_scan" in page.text
        assert "/web/jobs/run" in page.text
        run = client.post("/web/jobs/run", data={"job_name": "watcher_scan"},
                          follow_redirects=False)
        assert run.status_code == 303
        assert run.headers["location"] == "/system"
        runs = client.get("/api/v1/jobs/runs",
                          params={"job_name": "watcher_scan"})
        assert runs.status_code == 200
        assert len(runs.json()) >= 1
        bad = client.post("/web/jobs/run", data={"job_name": "nope"},
                          follow_redirects=False)
        assert bad.status_code == 303
        empty = client.post("/web/jobs/run", data={"job_name": ""},
                            follow_redirects=False)
        assert empty.status_code == 303


def test_moker_b_writes_execute_verify_gates(tmp_path, monkeypatch):
    for client in _moker_client(tmp_path, monkeypatch):
        import coordinator.app.main as main_mod
        from coordinator.app.controlled_writes import propose_write
        main_mod._write_save(propose_write(
            "wrt-moker1", "inventory.create", "object",
            {"name": "Moker"}, actor="t"), "proposed")
        # Execute before approval: gate refuses, status unchanged.
        blocked = client.post("/web/writes/wrt-moker1/execute",
                              follow_redirects=False)
        assert blocked.status_code == 303
        assert main_mod._write_load("wrt-moker1")["status"] == "proposed"
        # Verify before result: gate refuses, status unchanged.
        early = client.post("/web/writes/wrt-moker1/verify",
                            follow_redirects=False)
        assert early.status_code == 303
        assert main_mod._write_load("wrt-moker1")["status"] == "proposed"
        # Exact YES approves through the existing gate.
        yes = client.post("/web/writes/wrt-moker1/approve",
                          data={"response": "YES"},
                          follow_redirects=False)
        assert yes.status_code == 303
        assert main_mod._write_load("wrt-moker1")["status"] == "approved"
        # Execute with INVENTory down: backend 502, bridge redirects,
        # status stays approved (no bypass, no crash, no fake success).
        executed = client.post("/web/writes/wrt-moker1/execute",
                               follow_redirects=False)
        assert executed.status_code == 303
        assert main_mod._write_load("wrt-moker1")["status"] == "approved"
        page = client.get("/writes")
        assert page.status_code == 200
        assert "Execute" in page.text and "Verify" in page.text


def test_moker_c_agents_desktop_dispatch(tmp_path, monkeypatch):
    for client in _moker_client(tmp_path, monkeypatch):
        proposed = client.post("/api/v1/desktop/actions", json={
            "action_id": "dact-moker1", "action_type": "click",
            "parameters": {"x": 100, "y": 200}})
        assert proposed.status_code == 201, proposed.text
        decided = client.post(
            "/api/v1/desktop/actions/dact-moker1/decision",
            json={"response": "YES", "decided_by": "moker"})
        assert decided.status_code == 200, decided.text
        page = client.get("/agents")
        assert page.status_code == 200
        assert "Dispatch" in page.text
        dispatched = client.post(
            "/web/desktop/dact-moker1/dispatch", follow_redirects=False)
        assert dispatched.status_code == 303
        assert dispatched.headers["location"] == "/agents"
        state = client.get("/api/v1/desktop/actions/dact-moker1").json()
        assert state["status"] == "dispatched"
        # Dispatch on a pending action: gate refuses, status unchanged.
        client.post("/api/v1/desktop/actions", json={
            "action_id": "dact-moker2", "action_type": "click",
            "parameters": {"x": 10, "y": 20}})
        early = client.post("/web/desktop/dact-moker2/dispatch",
                            follow_redirects=False)
        assert early.status_code == 303
        pending = client.get("/api/v1/desktop/actions/dact-moker2").json()
        assert pending["status"] == "pending_approval"


def test_moker_d_task_assign_and_e_sweep(tmp_path, monkeypatch):
    for client in _moker_client(tmp_path, monkeypatch):
        token = _moker_node(client)
        task_id = client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": ["system_inventory"]}).json()["id"]
        detail = client.get(f"/tasks/{task_id}")
        assert detail.status_code == 200
        assert f"/web/tasks/{task_id}/assign" in detail.text
        assigned = client.post(f"/web/tasks/{task_id}/assign",
                               data={"node_id": "moker-node"},
                               follow_redirects=False)
        assert assigned.status_code == 303
        assert assigned.headers["location"] == f"/tasks/{task_id}"
        record = client.get(f"/api/v1/tasks/by-id/{task_id}").json()
        assert record["assigned_node_id"] == "moker-node"
        # Unknown node: bridge redirects, task stays queued.
        task_b = client.post("/api/v1/tasks", json={
            "kind": "system_inventory"}).json()["id"]
        refused = client.post(f"/web/tasks/{task_b}/assign",
                              data={"node_id": "ghost-node"},
                              follow_redirects=False)
        assert refused.status_code == 303
        assert client.get(
            f"/api/v1/tasks/by-id/{task_b}").json()["status"] == "queued"
        # Sweep bridge: explicit click, safe on any state.
        page = client.get("/tasks")
        assert "/web/maintenance/sweep" in page.text
        swept = client.post("/web/maintenance/sweep",
                            follow_redirects=False)
        assert swept.status_code == 303
        assert swept.headers["location"] == "/tasks"


def test_moker_f_mission_to_task(tmp_path, monkeypatch):
    for client in _moker_client(tmp_path, monkeypatch):
        mission = client.post("/api/v1/missions", json={
            "conversation_id": "conv-moker",
            "goal": "moker mission",
            "steps": [{"kind": "readout",
                       "description": "read project",
                       "parameters": {"source": "project"}}]})
        assert mission.status_code in (200, 201), mission.text
        mission_id = mission.json()["mission_id"]
        page = client.get(f"/missions/{mission_id}")
        assert page.status_code == 200
        assert f"/web/missions/{mission_id}/tasks" in page.text
        created = client.post(f"/web/missions/{mission_id}/tasks",
                              data={"kind": "system_inventory",
                                    "capabilities": "system_inventory"},
                              follow_redirects=False)
        assert created.status_code == 303
        assert created.headers["location"].startswith("/tasks/")
        task_id = created.headers["location"].rsplit("/", 1)[-1]
        record = client.get(f"/api/v1/tasks/by-id/{task_id}").json()
        assert record["mission_id"] == mission_id
        unknown = client.post("/web/missions/mission_nope/tasks",
                              data={"kind": "system_inventory"},
                              follow_redirects=False)
        assert unknown.status_code == 303
        assert unknown.headers["location"] == "/missions"
        empty = client.post(f"/web/missions/{mission_id}/tasks",
                            data={"kind": ""}, follow_redirects=False)
        assert empty.status_code == 303
        assert empty.headers["location"] == f"/missions/{mission_id}"


def test_moker_g_dossier_to_task(tmp_path, monkeypatch):
    for client in _moker_client(tmp_path, monkeypatch):
        from coordinator.app.research_engine import (
            build_dossier, new_run, save_dossier, save_run)
        run = new_run("Mokervraag over zonnepanelen?")
        save_run(run)
        dossier = build_dossier(run, summary="samenvatting")
        save_dossier(dossier)
        page = client.get(f"/research/{dossier.dossier_id}")
        assert page.status_code == 200
        assert (f"/web/research/dossiers/{dossier.dossier_id}/task"
                in page.text)
        created = client.post(
            f"/web/research/dossiers/{dossier.dossier_id}/task",
            data={"kind": "research.fetch_url", "question_index": ""},
            follow_redirects=False)
        assert created.status_code == 303
        assert created.headers["location"].startswith("/tasks/")
        task_id = created.headers["location"].rsplit("/", 1)[-1]
        payload = client.get(
            f"/api/v1/tasks/by-id/{task_id}").json()["payload"]
        assert payload["dossier_id"] == dossier.dossier_id
        assert payload["run_id"] == run.run_id
        unknown = client.post("/web/research/dossiers/dos_nope/task",
                              data={"kind": "research.fetch_url"},
                              follow_redirects=False)
        assert unknown.status_code == 303
        assert unknown.headers["location"] == "/research"


def test_moker_h_file_bridge(tmp_path, monkeypatch):
    from coordinator.app.inventory_read import GET_TYPES, InventoryReader
    assert GET_TYPES["file"] == "files"
    import httpx

    def handler(request):
        assert request.url.path == "/api/v1/files/file_x"
        return httpx.Response(200, json={
            "id": "file_x", "name": "plan.pdf",
            "provenance": {"source_type": "manual",
                           "creator_id": "jelles",
                           "human_verified": True,
                           "verified_by": "jelles"}})

    import asyncio
    reader = InventoryReader(
        base_url="http://127.0.0.1:8080",
        transport=httpx.MockTransport(handler))
    record = asyncio.run(reader.get("file", "file_x"))
    assert record.entity_type == "file"
    assert record.entity_id == "file_x"
    assert record.title == "plan.pdf"
    assert record.provenance.human_verified is True
