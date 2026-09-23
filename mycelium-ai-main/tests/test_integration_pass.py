"""INTEGRATION PASS end-to-end tests (flows A-H).

Every flow runs against the real backend on tmp DBs through the real
HTTP API + real UI pages. No hardware, no desktop actions, no shell,
no model downloads: safe digital kinds only (system_inventory).

FLOW A  UI -> mission -> task -> agent -> completion -> event
FLOW B  inventory bridge -> worldgraph -> world UI (honest offline)
FLOW C  research/memory -> provenance -> context packet
FLOW D  mission -> task -> context packet -> code_worker gate
FLOW E  agent ownership -> completion authorization
FLOW F  scheduler (on-demand jobs) -> sweep -> event -> UI
FLOW G  /play -> backend state -> visible result
FLOW H  approval -> gated action -> audit event
PLUS    new integration-pass routes (tasks/approvals/system/SSE/router)
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from code_worker.main import check_call, WorkerRefusedError

TOKEN_A = "integ-token-node-a-123456"
TOKEN_B = "integ-token-node-b-123456"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "integ.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "integ-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def register(client, node_id, caps, token):
    response = client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": node_id, "tier": "seed",
        "capabilities": caps, "node_token": token})
    assert response.status_code == 201, response.text


def heartbeat(client, node_id, token):
    response = client.post(f"/api/v1/nodes/{node_id}/heartbeat",
                           json={"available": True,
                                 "node_token": token})
    assert response.status_code == 204, response.text


def make_mission(client, goal="integration mission"):
    response = client.post("/api/v1/missions", json={
        "conversation_id": "conv-integ",
        "goal": goal,
        "steps": [{"kind": "readout", "description": "read git status",
                   "parameters": {"source": "git-status"}}]})
    assert response.status_code in (200, 201), response.text
    body = response.json()
    assert body["status"] == "pending_approval"
    return body["mission_id"]


def approve_mission(client, mission_id):
    response = client.post(f"/api/v1/missions/{mission_id}/approve",
                           json={"response": "YES",
                                 "decided_by": "integ-test"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"


# -- FLOW A ---------------------------------------------------------------

def test_flow_a_mission_task_agent_completion_event(tmp_path,
                                                    monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client, "node-a", ["system_inventory"], TOKEN_A)
        heartbeat(client, "node-a", TOKEN_A)
        mission_id = make_mission(client)
        approve_mission(client, mission_id)

        created = client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": ["system_inventory"],
            "mission_id": mission_id})
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]

        claimed = client.post("/api/v1/tasks/claim/node-a",
                              params={"node_token": TOKEN_A})
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["id"] == task_id

        done = client.post(f"/api/v1/tasks/{task_id}/complete", json={
            "success": True, "result": {"operating_system": "Linux"},
            "node_id": "node-a"})
        assert done.status_code == 204, done.text

        events = client.get("/api/v1/events?type=task.completed&limit=50")
        assert events.status_code == 200
        assert any(entry["task_id"] == str(task_id)
                   for entry in events.json())

        detail = client.get(f"/tasks/{task_id}")
        assert detail.status_code == 200
        assert "completed" in detail.text
        assert mission_id[:24] in detail.text

        mission_page = client.get(f"/missions/{mission_id}")
        assert mission_page.status_code == 200
        assert f"/tasks/{task_id}" in mission_page.text


# -- FLOW E ---------------------------------------------------------------

def test_flow_e_completion_ownership(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client, "node-a", ["system_inventory"], TOKEN_A)
        register(client, "node-b", ["system_inventory"], TOKEN_B)
        heartbeat(client, "node-a", TOKEN_A)
        heartbeat(client, "node-b", TOKEN_B)
        task_id = client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": ["system_inventory"]}).json()["id"]
        claimed = client.post("/api/v1/tasks/claim/node-a",
                              params={"node_token": TOKEN_A})
        assert claimed.json()["id"] == task_id

        foreign = client.post(f"/api/v1/tasks/{task_id}/complete",
                              json={"success": True, "result": {},
                                    "node_id": "node-b"})
        assert foreign.status_code == 404
        anonymous = client.post(f"/api/v1/tasks/{task_id}/complete",
                                json={"success": True, "result": {}})
        assert anonymous.status_code in (404, 422)
        own = client.post(f"/api/v1/tasks/{task_id}/complete",
                          json={"success": True, "result": {},
                                "node_id": "node-a"})
        assert own.status_code == 204


# -- FLOW H ---------------------------------------------------------------

def test_flow_h_approval_gates_and_audits(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        mission_id = make_mission(client, goal="gated plan")
        pending = client.get("/approvals")
        assert pending.status_code == 200
        assert mission_id[:24] in pending.text

        approve_mission(client, mission_id)
        events = client.get("/api/v1/events?type=approval.resolved&limit=50")
        assert events.status_code == 200
        assert any(entry["mission_id"] == mission_id
                   for entry in events.json())

        cleared = client.get("/approvals")
        assert cleared.status_code == 200
        assert "0</b> waiting" in cleared.text or \
            mission_id[:24] not in cleared.text


# -- FLOW F ---------------------------------------------------------------

def test_flow_f_jobs_sweep_and_ui(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        jobs = client.get("/api/v1/jobs")
        assert jobs.status_code == 200
        swept = client.post("/api/v1/maintenance/sweep-leases")
        assert swept.status_code == 200
        assert set(swept.json()) >= {"tasks", "desktop_actions"}
        for page in ("/automation", "/activity", "/system"):
            response = client.get(page)
            assert response.status_code == 200, page


# -- FLOW C ---------------------------------------------------------------

def test_flow_c_memory_provenance_context(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        saved = client.post("/api/v1/memory", json={
            "memory_type": "fact",
            "title": "bounded context packets",
            "content": "seed nodes like bounded context packets",
            "topics": ["integration"]})
        assert saved.status_code in (200, 201), saved.text
        packet = client.get("/api/v1/context/packet",
                            params={"goal": "integration mission"})
        assert packet.status_code == 200
        body = packet.json()
        assert "goal" in body or "sections" in body or \
            "context" in body
        memory_page = client.get("/memory")
        assert memory_page.status_code == 200


# -- FLOW D ---------------------------------------------------------------

def test_flow_d_task_context_reaches_worker_gate(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        mission_id = make_mission(client)
        task_id = client.post("/api/v1/tasks", json={
            "kind": "system_inventory", "mission_id": mission_id
        }).json()["id"]
        packet = client.get("/api/v1/context/packet",
                            params={"goal": "system_inventory"})
        assert packet.status_code == 200
        # The worker allow-list admits context reads, never approvals.
        assert check_call("GET", "/api/v1/context/packet") == \
            "/api/v1/context/packet"
        with pytest.raises(WorkerRefusedError):
            check_call("POST", "/api/v1/approvals")
        detail = client.get(f"/tasks/{task_id}")
        assert detail.status_code == 200
        assert "context/packet" in detail.text


# -- FLOW B ---------------------------------------------------------------

def test_flow_b_world_honest_without_inventory(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        search = client.get("/api/v1/world/search",
                            params={"q": "seed"})
        assert search.status_code in (200, 502)
        if search.status_code == 502:
            assert "unavailable" in search.json()["detail"].lower()
        world = client.get("/world")
        assert world.status_code == 200


# -- FLOW G ---------------------------------------------------------------

def test_flow_g_play_reflects_backend(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        mission_id = make_mission(client, goal="play-visible quest")
        approve_mission(client, mission_id)
        page = client.get("/play")
        assert page.status_code == 200
        assert "PLAYDATA" in page.text
        assert "play-visible quest" in page.text
        assert "live-strip" in page.text
        game = client.get("/game")
        assert game.status_code == 200


# -- new integration-pass routes ------------------------------------------

def test_tasks_dashboard_and_create_bridge(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        task_id = client.post("/api/v1/tasks", json={
            "kind": "system_inventory"}).json()["id"]
        overview = client.get("/tasks")
        assert overview.status_code == 200
        assert f"/tasks/{task_id}" in overview.text
        filtered = client.get("/tasks", params={"status": "queued"})
        assert filtered.status_code == 200
        missing = client.get("/tasks/999999")
        assert missing.status_code == 404

        created = client.post("/web/tasks",
                              data={"kind": "system_inventory",
                                    "capabilities": "",
                                    "mission_id": ""},
                              follow_redirects=False)
        assert created.status_code == 303
        assert created.headers["location"].startswith("/tasks/")

        refused = client.post("/web/tasks",
                              data={"kind": "!!!bad kind!!!",
                                    "capabilities": "", "mission_id": ""},
                              follow_redirects=False)
        assert refused.status_code == 303
        assert refused.headers["location"] == "/tasks"


def test_model_routes_and_system_page(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        routes = client.get("/api/v1/models/routes")
        assert routes.status_code == 200
        body = routes.json()
        assert body["code_pin"]
        assert body["routes"]["chat"]["provider"] == "ollama"
        tool = body["routes"]["tool_execution"]
        assert tool["routed"] is False
        assert "never auto-routes" in tool["reason"]
        assert body["proven_local_tool_models"] == []
        system = client.get("/system")
        assert system.status_code == 200
        assert "Model routing" in system.text


def test_event_stream_snapshot_and_validation(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        client.post("/api/v1/tasks", json={"kind": "system_inventory"})
        stream = client.get("/api/v1/events/stream",
                            params={"limit": 5, "once": "true"})
        assert stream.status_code == 200
        assert "text/event-stream" in stream.headers["content-type"]
        assert "data:" in stream.text
        assert "task.queued" in stream.text
        bad = client.get("/api/v1/events/stream",
                         params={"type": "bogus", "once": "true"})
        assert bad.status_code == 422


def test_nodes_and_agents_show_queue_truth(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client, "node-a", ["system_inventory"], TOKEN_A)
        heartbeat(client, "node-a", TOKEN_A)
        task_id = client.post("/api/v1/tasks", json={
            "kind": "system_inventory",
            "required_capabilities": ["system_inventory"]}).json()["id"]
        client.post("/api/v1/tasks/claim/node-a",
                    params={"node_token": TOKEN_A})
        nodes = client.get("/nodes")
        assert nodes.status_code == 200
        assert f"/tasks/{task_id}" in nodes.text
        agents = client.get("/agents")
        assert agents.status_code == 200
        assert f"/tasks/{task_id}" in agents.text
        assert "Queue workers" in agents.text
