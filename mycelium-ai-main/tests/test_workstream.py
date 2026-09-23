"""Multi-workstream, vertical slice 1 (E2E over existing chain).

One workspace runs independent workstreams side by side: a research
stream (workspace -> conversation -> mission -> fetch task -> worker
-> dossier -> report) next to a Forge stream (conversation fork ->
fabricate mission -> approve -> tick), each claimed/approved/
reported without touching the other. The workstreams view is a
read-only aggregation; workers and the Forge registry are shared
and labelled as such.

World reads and providers are faked; the worker socket is mocked
at the httpx boundary only. Nothing reaches INVENTory, Wikipedia,
Ollama or a real model.
"""

import httpx

import coordinator.app.main as main_mod
import node_client.main as node_main
from coordinator.app.ollama_advisor import AdviceResponse
from fastapi.testclient import TestClient

WS = "multi-ws"
QUESTION_A = "Is hennepvezel geschikt als isolatie voor een camper?"
SEED_A = "https://example.com/hennep-multi"
TOKEN_1 = "multi-token-1-abcdef-123456"
TOKEN_2 = "multi-token-2-abcdef-123456"
NODE_1 = "linux-1"
NODE_2 = "linux-2"
FETCHED_TEXT = (
    "Hennepvezel isoleert goed en is dampopen. "
    "Natuurlijk materiaal met hoge warmtecapaciteit.")


class FakeReader:
    async def search(self, q, type=None):
        from coordinator.app.inventory_read import SearchResponse
        return SearchResponse(query=q, results=[], total=0)

    async def browse(self, type=None):
        return await self.search("", type)


class FakeProvider:
    async def advise(self, question, records):
        return AdviceResponse(
            question=question, advice="advies zonder voorstel",
            model="fake-local", records_used=len(records), sources=[])


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "queue.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "chat-state.db"))
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "fab"))
    monkeypatch.setattr(main_mod, "_world_reader",
                        lambda: FakeReader())
    monkeypatch.setattr(main_mod, "get_provider",
                        lambda name=None, **k: FakeProvider())
    with TestClient(main_mod.app) as test_client:
        yield test_client


def register(client, node_id, caps, token):
    response = client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": node_id, "tier": "worker",
        "capabilities": caps, "node_token": token})
    assert response.status_code == 201, response.text


def chat(client, message, project_ref=WS):
    response = client.post("/api/v1/chat", json={
        "message": message, "project_ref": project_ref})
    assert response.status_code == 200, response.text
    return response.json()


def mock_socket(monkeypatch, text=FETCHED_TEXT):
    def handler(request):
        return _FakeResponse(
            200, {"content-type": "text/plain; charset=utf-8"},
            text.encode("utf-8"))
    monkeypatch.setattr(
        httpx, "Client", lambda *a, **k: _MockClient(handler))


class _FakeResponse:
    def __init__(self, status_code, headers, content):
        self.status_code = status_code
        self.headers = headers
        self.content = content


class _MockClient:
    def __init__(self, handler):
        self._handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, headers=None):
        from unittest.mock import Mock
        request = Mock(url=url, headers=headers or {})
        return self._handler(request)


def build_two_streams(client):
    """A: research stream. B: conversation + mission + task. Returns ids."""
    register(client, NODE_1, ["research.fetch"], TOKEN_1)
    register(client, NODE_2, ["system_inventory", "research.fetch"],
             TOKEN_2)
    conv_a = chat(client, "draad A")["conversation_id"]
    conv_b = chat(client, "draad B")["conversation_id"]
    forked = client.post(
        f"/api/v1/conversations/{conv_b}/fork", json={}).json()
    # B. Two independent missions in two conversations.
    started = client.post(
        f"/api/v1/workspaces/{WS}/research", json={
            "question": QUESTION_A, "route": "node-first",
            "seed_urls": [SEED_A], "conversation_id": conv_a,
            "max_sources": 6})
    assert started.status_code == 201, started.text
    started = started.json()
    mission_b = client.post("/api/v1/missions", json={
        "conversation_id": conv_b,
        "goal": "Werkplaats inventariseren",
        "steps": [
            {"kind": "readout", "description": "lees git status",
             "parameters": {"source": "git-status"}},
            {"kind": "proposal",
             "description": "stel opruimplan voor",
             "parameters": {"proposal": "ruim de werkplaats op"}}],
        "max_steps": 5})
    assert mission_b.status_code == 201, mission_b.text
    mission_b = mission_b.json()
    task_b = client.post("/api/v1/tasks", json={
        "kind": "system_inventory", "payload": {"goal": "inventaris"},
        "required_capabilities": ["system_inventory"],
        "mission_id": mission_b["mission_id"]})
    assert task_b.status_code == 201, task_b.text
    return {
        "conv_a": conv_a, "conv_b": conv_b,
        "conv_fork": forked["conversation_id"],
        "mission_a": started["mission_id"],
        "run_a": started["run_id"],
        "task_a": started["task_ids"][0],
        "mission_b": mission_b["mission_id"],
        "task_b": task_b.json()["id"],
    }


def test_a_workspace_holds_many_conversations(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_two_streams(client)
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        assert view["workspace_id"] == WS
        assert {ids["conv_a"], ids["conv_b"],
                ids["conv_fork"]} <= {
            item["conversation_id"]
            for item in view["conversations"]}


def test_b_two_independent_missions(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_two_streams(client)
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        by_id = {stream["mission_id"]: stream
                 for stream in view["workstreams"]}
        assert ids["mission_a"] in by_id
        assert ids["mission_b"] in by_id
        assert by_id[ids["mission_a"]]["conversation_id"] == \
            ids["conv_a"]
        assert by_id[ids["mission_b"]]["conversation_id"] == \
            ids["conv_b"]
        assert by_id[ids["mission_b"]]["greenlight"] == \
            "wacht op YES"


def test_c_both_missions_queued(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_two_streams(client)
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        assert view["task_counts"].get("queued", 0) == 2
        by_task = {task["task_id"]: task
                   for task in view["tasks"]}
        assert by_task[ids["task_a"]]["mission_id"] == \
            ids["mission_a"]
        assert by_task[ids["task_b"]]["mission_id"] == \
            ids["mission_b"]


def test_d_claim_one_without_blocking_other(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_two_streams(client)
        claimed_a = client.post(
            f"/api/v1/tasks/claim/{NODE_1}",
            params={"node_token": TOKEN_1}).json()
        assert claimed_a["id"] == ids["task_a"]
        claimed_b = client.post(
            f"/api/v1/tasks/claim/{NODE_2}",
            params={"node_token": TOKEN_2}).json()
        assert claimed_b["id"] == ids["task_b"]
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        assert view["task_counts"].get("running", 0) == 2
        states = {task["task_id"]: task for task in view["tasks"]}
        assert states[ids["task_a"]]["assigned_node_id"] == NODE_1
        assert states[ids["task_b"]]["assigned_node_id"] == NODE_2


def test_e_research_stream_works(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_two_streams(client)
        claimed = client.post(
            f"/api/v1/tasks/claim/{NODE_1}",
            params={"node_token": TOKEN_1}).json()
        assert claimed["id"] == ids["task_a"]
        mock_socket(monkeypatch)
        ok, result, error = node_main.execute_safe_task({
            "kind": "research.fetch_url",
            "payload": {"url": SEED_A, "max_chars": 65536}})
        assert ok is True, error
        done = client.post(
            f"/api/v1/tasks/{ids['task_a']}/complete",
            params={"node_id": NODE_1}, json={
                "success": True,
                "result": {"url": result["url"],
                           "text": result["text"]},
                "error": None})
        assert done.status_code == 204, done.text
        executed = client.post(
            f"/api/v1/research/runs/{ids['run_a']}/execute",
            json={"provider": "test",
                  "test_pages": {"isolatie": [
                      "Hennepdossier",
                      "Hennepvezel isoleert goed en is dampopen."]},
                  "max_sources": 6}).json()
        assert executed["status"] == "completed", executed
        reported = client.post(
            f"/api/v1/workspaces/{WS}/research/"
            f"{ids['run_a']}/report").json()
        assert reported["reported"] is True
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        stream_a = {stream["mission_id"]: stream
                    for stream in view["workstreams"]}[ids["mission_a"]]
        assert len(stream_a["research"]) == 1
        assert stream_a["research"][0]["dossier_id"] == \
            executed["dossier_id"]


def test_f_forge_stream_runs_beside_research(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_two_streams(client)
        mission_c = client.post("/api/v1/missions", json={
            "conversation_id": ids["conv_fork"],
            "goal": "Forge bracket 20mm",
            "steps": [{"kind": "fabricate",
                       "description": "genereer test-bracket",
                       "parameters": {
                           "description": "test bracket 20mm",
                           "method": "procedural-test"}}],
            "max_steps": 3})
        assert mission_c.status_code == 201, mission_c.text
        mission_c = mission_c.json()
        approved = client.post(
            f"/api/v1/missions/{mission_c['mission_id']}/approve",
            json={"response": "YES", "decided_by": "human"})
        assert approved.status_code == 200, approved.text
        ticked = client.post(
            f"/api/v1/missions/{mission_c['mission_id']}/tick")
        assert ticked.status_code == 200, ticked.text
        mission = client.get(
            f"/api/v1/missions/{mission_c['mission_id']}").json()
        assert mission["steps"][0]["status"] == "completed"
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        assert mission_c["mission_id"] in {
            item["mission_id"] for item in view["forge"]["missions"]}
        stream_c = {stream["mission_id"]: stream
                    for stream in view["workstreams"]}[
            mission_c["mission_id"]]
        assert stream_c["greenlight"] == "afgerond"
        page = client.get(f"/workspaces/{WS}").text
        assert "ACTIVE WORKSTREAMS" in page
        assert "Forge bracket 20mm" in page


def test_g_events_show_both_streams(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_two_streams(client)
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        bus_missions = {item["mission_id"]
                        for item in view["bus_events"]}
        assert ids["mission_a"] in bus_missions
        assert ids["mission_b"] in bus_missions
        conv_seen = {item["conversation_id"]
                     for item in view["events"]}
        assert ids["conv_a"] in conv_seen
        assert ids["conv_b"] in conv_seen


def test_h_result_of_a_leaves_b_untouched(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_two_streams(client)
        claimed = client.post(
            f"/api/v1/tasks/claim/{NODE_1}",
            params={"node_token": TOKEN_1}).json()
        assert claimed["id"] == ids["task_a"]
        before_mission = client.get(
            f"/api/v1/missions/{ids['mission_b']}").json()
        before_messages = client.get(
            f"/api/v1/conversations/{ids['conv_b']}").json()
        mock_socket(monkeypatch)
        ok, result, error = node_main.execute_safe_task({
            "kind": "research.fetch_url",
            "payload": {"url": SEED_A, "max_chars": 65536}})
        assert ok is True, error
        client.post(f"/api/v1/tasks/{ids['task_a']}/complete",
                    params={"node_id": NODE_1}, json={
                        "success": True,
                        "result": {"url": result["url"],
                                   "text": result["text"]},
                        "error": None})
        client.post(
            f"/api/v1/research/runs/{ids['run_a']}/execute",
            json={"provider": "test",
                  "test_pages": {"blad": ["T", "Hennep isoleert."]},
                  "max_sources": 6})
        client.post(f"/api/v1/workspaces/{WS}/research/"
                    f"{ids['run_a']}/report")
        after_mission = client.get(
            f"/api/v1/missions/{ids['mission_b']}").json()
        after_messages = client.get(
            f"/api/v1/conversations/{ids['conv_b']}").json()
        assert after_mission == before_mission
        assert len(after_messages["messages"]) == \
            len(before_messages["messages"])


def test_i_greenlight_a_leaves_b(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_two_streams(client)
        approved = client.post(
            f"/api/v1/missions/{ids['mission_a']}/approve",
            json={"response": "YES", "decided_by": "human"})
        assert approved.status_code == 200, approved.text
        mission_b = client.get(
            f"/api/v1/missions/{ids['mission_b']}").json()
        assert mission_b["status"] == "pending_approval"
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        by_id = {stream["mission_id"]: stream
                 for stream in view["workstreams"]}
        assert by_id[ids["mission_a"]]["greenlight"] == "greenlit"
        assert by_id[ids["mission_b"]]["greenlight"] == \
            "wacht op YES"


def test_overview_fail_closed_and_workers_shared(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.get(
            "/api/v1/workspaces/!!-bad/workstreams").status_code == 422
        empty = client.get(
            "/api/v1/workspaces/vers-ws/workstreams").json()
        assert empty["workstreams"] == []
        assert empty["tasks"] == []
        assert empty["research"] == []
        register(client, NODE_1, ["research.fetch"], TOKEN_1)
        shared = client.get(
            "/api/v1/workspaces/vers-ws/workstreams").json()
        assert any(worker["node_id"] == NODE_1
                   for worker in shared["workers"])
        assert all(worker["scope"] == "shared"
                   for worker in shared["workers"])
