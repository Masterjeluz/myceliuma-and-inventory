"""Workspace development cockpit (E2E over existing stores).

The workspace detail page works as a cockpit: ACTIVE WORKSTREAMS
with OPEN deep-links into existing routes, a MAIN conversation
tree from proven fork bookkeeping only, PENDING HUMAN ACTIONS
pointing at existing gates, ACTIVITY from existing events, and
SHARED RESOURCES (workers, Forge, research, INVENTory) with
fail-soft UNAVAILABLE. No new table, queue, bus, scheduler,
engine or approval flow anywhere in this pass.

World reads and providers are faked; the worker socket is mocked
at the httpx boundary only. No INVENTory server runs here, so the
shared INVENTory panel must honestly read UNAVAILABLE.
"""

import httpx

import coordinator.app.main as main_mod
import node_client.main as node_main
from coordinator.app.ollama_advisor import AdviceResponse
from fastapi.testclient import TestClient

WS = "cockpit-ws"
QUESTION = "Is hennepvezel geschikt als isolatie voor een camper?"
SEED = "https://example.com/hennep-cockpit"
TOKEN_1 = "cockpit-token-1-abcdef-123456"
TOKEN_2 = "cockpit-token-2-abcdef-123456"
NODE_1 = "linux-1"
NODE_2 = "linux-2"
FETCHED_TEXT = "Hennepvezel isoleert goed en is dampopen."


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


def build_cockpit(client):
    """Research stream + plain mission + fabricate mission. Returns ids."""
    register(client, NODE_1, ["research.fetch"], TOKEN_1)
    register(client, NODE_2, ["system_inventory"], TOKEN_2)
    conv_a = chat(client, "draad A")["conversation_id"]
    conv_b = chat(client, "draad B")["conversation_id"]
    forked = client.post(
        f"/api/v1/conversations/{conv_b}/fork", json={}).json()
    started = client.post(
        f"/api/v1/workspaces/{WS}/research", json={
            "question": QUESTION, "route": "node-first",
            "seed_urls": [SEED], "conversation_id": conv_a,
            "max_sources": 6})
    assert started.status_code == 201, started.text
    started = started.json()
    mission_b = client.post("/api/v1/missions", json={
        "conversation_id": conv_b,
        "goal": "Werkplaats inventariseren",
        "steps": [{"kind": "readout",
                   "description": "lees git status",
                   "parameters": {"source": "git-status"}}],
        "max_steps": 5})
    assert mission_b.status_code == 201, mission_b.text
    mission_b = mission_b.json()
    mission_c = client.post("/api/v1/missions", json={
        "conversation_id": forked["conversation_id"],
        "goal": "Forge bracket 20mm",
        "steps": [{"kind": "fabricate",
                   "description": "genereer test-bracket",
                   "parameters": {"description": "test bracket",
                                  "method": "procedural-test"}}],
        "max_steps": 3})
    assert mission_c.status_code == 201, mission_c.text
    mission_c = mission_c.json()
    return {
        "conv_a": conv_a, "conv_b": conv_b,
        "conv_fork": forked["conversation_id"],
        "mission_a": started["mission_id"],
        "run_a": started["run_id"],
        "task_a": started["task_ids"][0],
        "mission_b": mission_b["mission_id"],
        "mission_c": mission_c["mission_id"],
    }


def test_a_all_conversations_shown(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_cockpit(client)
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        assert {ids["conv_a"], ids["conv_b"],
                ids["conv_fork"]} <= {
            item["conversation_id"]
            for item in view["conversations"]}
        page = client.get(f"/workspaces/{WS}").text
        assert page.count("convtree") >= 1
        for cid in (ids["conv_a"], ids["conv_b"],
                    ids["conv_fork"]):
            assert cid[:20] in page or cid in page


def test_b_multiple_workstreams_shown(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_cockpit(client)
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        by_id = {stream["mission_id"]: stream
                 for stream in view["workstreams"]}
        assert {ids["mission_a"], ids["mission_b"],
                ids["mission_c"]} <= set(by_id)
        page = client.get(f"/workspaces/{WS}").text
        assert "ACTIVE WORKSTREAMS" in page
        assert "Werkplaats inventariseren" in page
        assert "Forge bracket 20mm" in page


def test_c_streams_stay_independent(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_cockpit(client)
        # Forge stream approves + ticks while research waits.
        approved = client.post(
            f"/api/v1/missions/{ids['mission_c']}/approve",
            json={"response": "YES", "decided_by": "human"})
        assert approved.status_code == 200, approved.text
        ticked = client.post(
            f"/api/v1/missions/{ids['mission_c']}/tick")
        assert ticked.status_code == 200, ticked.text
        mission_a = client.get(
            f"/api/v1/missions/{ids['mission_a']}").json()
        mission_b = client.get(
            f"/api/v1/missions/{ids['mission_b']}").json()
        assert mission_a["status"] == "pending_approval"
        assert mission_b["status"] == "pending_approval"
        mission_c = client.get(
            f"/api/v1/missions/{ids['mission_c']}").json()
        assert mission_c["steps"][0]["status"] == "completed"
        # Research stream still claims independently afterwards.
        claimed = client.post(
            f"/api/v1/tasks/claim/{NODE_1}",
            params={"node_token": TOKEN_1}).json()
        assert claimed["id"] == ids["task_a"]


def test_d_fork_appears_separately(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_cockpit(client)
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        tree = view["tree"]
        assert tree["nodes"][ids["conv_fork"]]["parent"] == \
            ids["conv_b"]
        assert ids["conv_fork"] in tree["children"][ids["conv_b"]]
        assert ids["conv_a"] in tree["roots"]
        assert ids["conv_b"] in tree["roots"]
        page = client.get(f"/workspaces/{WS}").text
        assert "fork van" in page


def test_e_original_untouched_by_fork(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        conv = chat(client, "origineel")["conversation_id"]
        before = client.get(
            f"/api/v1/conversations/{conv}").json()
        forked = client.post(
            f"/api/v1/conversations/{conv}/fork", json={}).json()
        assert forked["conversation_id"] != conv
        after = client.get(
            f"/api/v1/conversations/{conv}").json()
        assert [item["message_id"] for item in after["messages"]] == \
            [item["message_id"] for item in before["messages"]]
        assert [item["content"] for item in after["messages"]] == \
            [item["content"] for item in before["messages"]]


def test_f_open_links_use_existing_routes(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_cockpit(client)
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        by_id = {stream["mission_id"]: stream
                 for stream in view["workstreams"]}
        for mid in (ids["mission_a"], ids["mission_b"],
                    ids["mission_c"]):
            opening = by_id[mid]["open"]
            assert client.get(opening["mission"]).status_code == 200
            assert client.get(
                opening["conversation"]).status_code == 200
        assert by_id[ids["mission_c"]]["open"]["forge"] == "/forge"
        assert by_id[ids["mission_a"]]["open"]["research"] == \
            "/research"
        assert by_id[ids["mission_b"]]["open"]["research"] == ""
        assert by_id[ids["mission_b"]]["open"]["approve"].endswith(
            ids["mission_b"])


def test_g_pending_approvals_visible(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_cockpit(client)
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        assert view["pending"]["total"] >= 3
        assert ids["mission_b"] in {
            item["mission_id"]
            for item in view["pending"]["mission_approvals"]}
        page = client.get(f"/workspaces/{WS}").text
        assert "PENDING HUMAN ACTIONS" in page
        assert "wacht op YES" in page
        client.post(f"/api/v1/missions/{ids['mission_b']}/approve",
                    json={"response": "YES", "decided_by": "human"})
        later = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        assert ids["mission_b"] not in {
            item["mission_id"] for item in
            later["pending"]["mission_approvals"]}


def test_h_events_visible(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_cockpit(client)
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        assert view["events"]
        assert view["bus_events"]
        assert ids["mission_a"] in {
            item["mission_id"] for item in view["bus_events"]}
        page = client.get(f"/workspaces/{WS}").text
        assert "ACTIVITY" in page
        assert "mission_created" in page


def test_i_workers_visible(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_cockpit(client)
        _ = ids
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        assert {NODE_1, NODE_2} <= {
            worker["node_id"] for worker in view["workers"]
            if worker["available"]}
        page = client.get(f"/workspaces/{WS}").text
        assert "SHARED RESOURCES" in page
        assert NODE_1 in page
        assert "/nodes" in page


def test_j_forge_link_works(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_cockpit(client)
        _ = ids
        assert client.get("/forge").status_code == 200
        page = client.get(f"/workspaces/{WS}").text
        assert "/forge" in page


def test_k_research_link_works(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        ids = build_cockpit(client)
        claimed = client.post(
            f"/api/v1/tasks/claim/{NODE_1}",
            params={"node_token": TOKEN_1}).json()
        assert claimed["id"] == ids["task_a"]
        mock_socket(monkeypatch)
        ok, result, error = node_main.execute_safe_task({
            "kind": "research.fetch_url",
            "payload": {"url": SEED, "max_chars": 65536}})
        assert ok is True, error
        client.post(f"/api/v1/tasks/{ids['task_a']}/complete",
                    params={"node_id": NODE_1}, json={
                        "success": True,
                        "result": {"url": result["url"],
                                   "text": result["text"]},
                        "error": None})
        executed = client.post(
            f"/api/v1/research/runs/{ids['run_a']}/execute",
            json={"provider": "test",
                  "test_pages": {"blad": ["Titel", "Hennep isoleert."]},
                  "max_sources": 6}).json()
        assert executed["status"] == "completed", executed
        reported = client.post(
            f"/api/v1/workspaces/{WS}/research/"
            f"{ids['run_a']}/report").json()
        assert reported["reported"] is True
        assert client.get("/research").status_code == 200
        assert client.get(
            f"/api/v1/research/dossiers/"
            f"{executed['dossier_id']}").status_code == 200
        page = client.get(f"/workspaces/{WS}").text
        assert executed["dossier_id"] in page


def test_l_attach_uses_existing_route(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        stray = chat(client, "verdwaald", project_ref="")[
            "conversation_id"]
        before = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        assert stray not in {item["conversation_id"]
                             for item in before["conversations"]}
        attached = client.post(
            f"/api/v1/workspaces/{WS}/conversations/"
            f"{stray}/attach")
        assert attached.status_code == 200, attached.text
        assert attached.json()["moved"] is True
        after = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        assert stray in {item["conversation_id"]
                         for item in after["conversations"]}
        assert stray in after["tree"]["roots"]
        page = client.get(f"/workspaces/{WS}").text
        assert "ATTACH" in page


def test_m_no_new_database_or_tables(tmp_path, monkeypatch):
    import pathlib
    import sqlite3
    for client in make_client(tmp_path, monkeypatch):
        ids = build_cockpit(client)
        _ = ids
        client.get(f"/api/v1/workspaces/{WS}/workstreams")
        client.get(f"/workspaces/{WS}")
        tables: set[str] = set()
        for name in ("queue.db", "chat-state.db"):
            path = tmp_path / name
            assert path.exists()
            db = sqlite3.connect(str(path))
            try:
                tables.update(
                    row[0] for row in db.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name NOT LIKE "
                        "'sqlite_%'"))
            finally:
                db.close()
        sources = list(pathlib.Path("coordinator/app").glob("*.py"))
        declared: dict[str, str] = {}
        for source in sources:
            text = source.read_text(encoding="utf-8")
            for line in text.splitlines():
                upper = line.upper()
                if "CREATE TABLE" in upper:
                    for table in tables:
                        if table.lower() in line.lower():
                            declared.setdefault(table,
                                                source.name)
        assert "CREATE TABLE" not in pathlib.Path(
            "coordinator/app/workspaces.py").read_text(
            encoding="utf-8")
        undeclared = tables - set(declared)
        assert not undeclared, undeclared


def test_n_no_new_queue_bus_or_scheduler(tmp_path, monkeypatch):
    import pathlib
    for client in make_client(tmp_path, monkeypatch):
        ids = build_cockpit(client)
        _ = ids
        from coordinator.app.database import (
            chat_connection as _chat_conn,
        )
        from coordinator.app.database import connection as _conn
        with _conn() as db:
            tasks_before = db.execute(
                "SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
        with _chat_conn() as db:
            bus_before = db.execute(
                "SELECT COUNT(*) AS n FROM interface_events"
            ).fetchone()["n"]
            stored_before = db.execute(
                "SELECT COUNT(*) AS n FROM conversation_events"
            ).fetchone()["n"]
        client.get(f"/api/v1/workspaces/{WS}/workstreams")
        client.get(f"/workspaces/{WS}")
        with _conn() as db:
            tasks_after = db.execute(
                "SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
        with _chat_conn() as db:
            bus_after = db.execute(
                "SELECT COUNT(*) AS n FROM interface_events"
            ).fetchone()["n"]
            stored_after = db.execute(
                "SELECT COUNT(*) AS n FROM conversation_events"
            ).fetchone()["n"]
        assert tasks_after == tasks_before
        assert bus_after == bus_before
        assert stored_after == stored_before
        text = pathlib.Path(
            "coordinator/app/workspaces.py").read_text(
            encoding="utf-8")
        for banned in ("threading", "BackgroundTasks",
                       "create_task", "asyncio", "sched",
                       "INSERT INTO tasks", "INSERT INTO missions"):
            assert banned not in text, banned
