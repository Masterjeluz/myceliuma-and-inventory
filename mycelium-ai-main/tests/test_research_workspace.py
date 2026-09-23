"""Workspace research, vertical slice 1 (E2E over existing chain).

Workspace -> research mission (research_topic template, pending
approval) -> research.fetch_url task (mission_id-bound) -> worker
claim (pull-only, lease) -> real worker fetch (node_client path,
mocked socket) -> completion ingest (SourceRecord on the run) ->
engine execute (claims -> dossier -> research memory) -> explicit
report back into the workspace conversation.

World reads and providers are faked; the worker socket is mocked
at the httpx boundary only — every other step runs the shipped
code. Nothing reaches INVENTory, Wikipedia, Ollama or a real model.
"""

import httpx

import coordinator.app.main as main_mod
import node_client.main as node_main
from coordinator.app.ollama_advisor import AdviceResponse
from fastapi.testclient import TestClient

QUESTION = "Is hennepvezel geschikt als isolatie voor een camper?"
SEED = "https://example.com/hennep"
TOKEN = "research-token-abcdef-123456"
NODE = "linux-1"
FETCHED_TEXT = (
    "Hennepvezel isoleert goed en is dampopen. "
    "Het is een natuurlijk materiaal met een hoge warmtecapaciteit.")


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
    monkeypatch.setattr(main_mod, "_world_reader",
                        lambda: FakeReader())
    monkeypatch.setattr(main_mod, "get_provider",
                        lambda name=None, **k: FakeProvider())
    with TestClient(main_mod.app) as test_client:
        yield test_client


def register_worker(client, node_id=NODE):
    response = client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": node_id, "tier": "worker",
        "capabilities": ["research.fetch", "research.search"],
        "node_token": TOKEN})
    assert response.status_code == 201, response.text


def start(client, ws="mycelium-ai", route="node-first",
          seeds=None, question=QUESTION):
    response = client.post(
        f"/api/v1/workspaces/{ws}/research", json={
            "question": question, "route": route,
            "seed_urls": seeds if seeds is not None else [SEED],
            "max_sources": 6})
    assert response.status_code == 201, response.text
    return response.json()


def mock_socket(monkeypatch, text=FETCHED_TEXT,
                content_type="text/plain; charset=utf-8"):
    def handler(request):
        return _FakeResponse(200, {"content-type": content_type},
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


def claim(client, node_id=NODE):
    response = client.post(
        f"/api/v1/tasks/claim/{node_id}",
        params={"node_token": TOKEN})
    assert response.status_code == 200, response.text
    return response.json()


def test_start_links_workspace_mission_task(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        record = start(client)
        assert record["workspace_id"] == "mycelium-ai"
        assert record["mission_status"] == "pending_approval"
        assert record["run_status"] == "draft"
        assert record["routed"] is False  # no worker yet: honest wait
        assert "WAITING_FOR_AGENT" in record["status_note"]

        mission = client.get(
            f"/api/v1/missions/{record['mission_id']}").json()
        assert mission["conversation_id"] == record["conversation_id"]
        assert mission["status"] == "pending_approval"
        assert mission["steps"][0]["kind"] == "research"

        run = client.get(
            f"/api/v1/research/runs/{record['run_id']}").json()
        assert run["mission_id"] == record["mission_id"]
        assert run["question"] == QUESTION

        register_worker(client)
        # Second start now routes: mission -> task exists.
        second = start(client, seeds=["https://example.com/hennep-b"])
        assert second["routed"] is True
        assert len(second["task_ids"]) == 1
        tasks = {task["id"]: task
                 for task in client.get("/api/v1/tasks").json()}
        task = tasks[second["task_ids"][0]]
        assert task["kind"] == "research.fetch_url"
        assert task["mission_id"] == second["mission_id"]
        context = task["payload"]["research_context"]
        assert context["question"] == QUESTION
        assert context["run_id"] == second["run_id"]
        assert context["mission_id"] == second["mission_id"]
        assert context["conversation_id"] == \
            second["conversation_id"]

        detail = client.get("/api/v1/workspaces/mycelium-ai").json()
        assert record["conversation_id"] in {
            item["conversation_id"]
            for item in detail["conversations"]}
        events = client.get("/api/v1/events",
                            params={"limit": 50}).json()
        assert any("research" in item.get("event_type", "")
                   for item in events)


def test_worker_claim_fetch_complete_and_provenance(
        tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register_worker(client)
        record = start(client)
        assert record["routed"] is True
        task_id = record["task_ids"][0]

        claimed = claim(client)
        assert claimed["kind"] == "research.fetch_url"
        context = claimed["payload"]["research_context"]
        assert context["question"] == QUESTION
        assert context["project_ref"] == "mycelium-ai"
        assert context["run_id"] == record["run_id"]
        assert context["conversation_id"] == \
            record["conversation_id"]

        # Worker executes through the real node path (socket mocked).
        mock_socket(monkeypatch)
        ok, result, error = node_main.execute_safe_task({
            "kind": "research.fetch_url",
            "payload": {"url": SEED, "max_chars": 65536}})
        assert ok is True, error
        assert "Hennepvezel" in result["text"]

        done = client.post(
            f"/api/v1/tasks/{task_id}/complete",
            params={"node_id": NODE}, json={
                "success": True,
                "result": {"url": result["url"],
                           "text": result["text"]},
                "error": None})
        assert done.status_code == 204, done.text

        run = client.get(
            f"/api/v1/research/runs/{record['run_id']}").json()
        assert run["source_ids"]
        assert run["metadata"]["node_fetched"] == 1
        meta = run["sources_meta"][0]
        assert meta["url"].startswith("https://example.com/")
        assert meta["provider"] == f"node:{NODE}"

        sources = client.get("/api/v1/research/sources").json()
        node_sources = [
            entry for entry in sources
            if entry["source_id"] in run["source_ids"]]
        assert node_sources
        provenance = node_sources[0]["provenance"]
        assert provenance["human_verified"] is False
        assert provenance["source_type"] in (
            "external-source", "web")
        assert NODE in str(provenance.get("creator_id", "")) \
            or "node" in str(provenance.get("notes", "")).lower()


def test_execute_dossier_report_and_idempotency(
        tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register_worker(client)
        record = start(client)
        task_id = record["task_ids"][0]
        claimed = claim(client)
        assert claimed["id"] == task_id
        mock_socket(monkeypatch)
        ok, result, error = node_main.execute_safe_task({
            "kind": "research.fetch_url",
            "payload": {"url": SEED, "max_chars": 65536}})
        assert ok is True, error
        done = client.post(
            f"/api/v1/tasks/{task_id}/complete",
            params={"node_id": NODE}, json={
                "success": True,
                "result": {"url": result["url"],
                           "text": result["text"]},
                "error": None})
        assert done.status_code == 204, done.text

        # Real engine path (deterministic TEST fixtures): claims ->
        # dossier -> research memory. Honest TEST label.
        executed = client.post(
            f"/api/v1/research/runs/{record['run_id']}/execute",
            json={"provider": "test",
                  "test_pages": {"camper-isolatie": [
                      "Hennepdossier",
                      "Hennepvezel isoleert goed en is dampopen. "
                      "De warmtecapaciteit is hoog."]},
                  "max_sources": 6}).json()
        assert executed["status"] == "completed", executed
        assert executed["dossier_id"]
        run = client.get(
            f"/api/v1/research/runs/{record['run_id']}").json()
        assert run["claim_count"] >= 1
        stored = set(run["source_ids"])
        for claim_row in run["claims"]:
            assert claim_row["source_id"] in stored
        assert run["memory_id"]

        dossier = client.get(
            f"/api/v1/research/dossiers/{executed['dossier_id']}"
        ).json()
        assert dossier["provenance"]["human_verified"] is False
        assert dossier["provenance"]["source_type"] == \
            "external-source"
        assert dossier["execution_state"] in ("TEST", "REAL")

        memories = client.get(
            "/api/v1/memory",
            params={"memory_type": "research"}).json()
        remembered = [entry for entry in memories
                      if entry["memory_id"] == run["memory_id"]]
        assert remembered
        assert remembered[0]["truth"] == "external_source"

        before = client.get(
            f"/api/v1/conversations/{record['conversation_id']}"
        ).json()
        reported = client.post(
            f"/api/v1/workspaces/mycelium-ai/research/"
            f"{record['run_id']}/report").json()
        assert reported["reported"] is True
        assert reported["dossier_id"] == executed["dossier_id"]
        assert reported["mission_status"] == "pending_approval"

        after = client.get(
            f"/api/v1/conversations/{record['conversation_id']}"
        ).json()
        assert len(after["messages"]) == len(before["messages"]) + 1
        last = after["messages"][-1]
        assert last["role"] == "assistant"
        assert "UNVERIFIED" in last["content"]
        assert executed["dossier_id"] in last["content"]
        assert last["provenance"]["human_verified"] is False

        again = client.post(
            f"/api/v1/workspaces/mycelium-ai/research/"
            f"{record['run_id']}/report").json()
        assert again["reported"] is False
        assert again["reason"] == "already-reported"
        final = client.get(
            f"/api/v1/conversations/{record['conversation_id']}"
        ).json()
        assert len(final["messages"]) == len(after["messages"])

        detail = client.get("/api/v1/workspaces/mycelium-ai").json()
        assert any("Dossier" in item.get("message", "")
                   for item in detail["events"])


def test_outage_leaves_mission_state_intact(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        # Unavailable provider: honest terminal run, mission untouched.
        record = start(client, route="local", seeds=[])
        executed = client.post(
            f"/api/v1/research/runs/{record['run_id']}/execute",
            json={"provider": "unavailable"}).json()
        assert executed["status"] == "unavailable", executed
        mission = client.get(
            f"/api/v1/missions/{record['mission_id']}").json()
        assert mission["status"] == "pending_approval"
        assert mission["steps"][0]["status"] == "pending"
        waiting = client.post(
            f"/api/v1/workspaces/mycelium-ai/research/"
            f"{record['run_id']}/report").json()
        assert waiting["reported"] is False
        assert waiting["status"] == "unavailable"

        # Failed worker result: task fails, run/mission unchanged.
        register_worker(client)
        routed = start(client, seeds=["https://example.com/kapot"])
        assert routed["routed"] is True
        task_id = routed["task_ids"][0]
        claimed = claim(client)
        assert claimed["id"] == task_id
        failed = client.post(
            f"/api/v1/tasks/{task_id}/complete",
            params={"node_id": NODE}, json={
                "success": False, "result": {}, "error": "fetch stuk"})
        assert failed.status_code == 204, failed.text
        run = client.get(
            f"/api/v1/research/runs/{routed['run_id']}").json()
        assert run["source_ids"] == []
        mission = client.get(
            f"/api/v1/missions/{routed['mission_id']}").json()
        assert mission["status"] == "pending_approval"

        # Expired lease requeues instead of corrupting.
        third = start(client, seeds=["https://example.com/opnieuw"])
        assert third["routed"] is True
        task_id = third["task_ids"][0]
        claimed = claim(client)
        assert claimed["id"] == task_id
        foreign = client.post(
            f"/api/v1/tasks/{task_id}/complete",
            params={"node_id": "someone-else"}, json={
                "success": True,
                "result": {"url": SEED, "text": "x"},
                "error": None})
        assert foreign.status_code == 404
        from datetime import datetime, timedelta, timezone
        future = (datetime.now(timezone.utc)
                  + timedelta(seconds=3600)).isoformat()
        recovered = main_mod.expire_leases(future)
        assert recovered["requeued"] >= 1
        tasks = {task["id"]: task
                 for task in client.get("/api/v1/tasks").json()}
        assert tasks[task_id]["status"] == "queued"


def test_no_auto_approval_or_canonical_mutation(
        tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register_worker(client)
        record = start(client)
        claimed = claim(client)
        mock_socket(monkeypatch)
        ok, result, error = node_main.execute_safe_task({
            "kind": "research.fetch_url",
            "payload": {"url": SEED, "max_chars": 65536}})
        assert ok is True, error
        client.post(f"/api/v1/tasks/{claimed['id']}/complete",
                    params={"node_id": NODE}, json={
                        "success": True,
                        "result": {"url": result["url"],
                                   "text": result["text"]},
                        "error": None})
        client.post(
            f"/api/v1/research/runs/{record['run_id']}/execute",
            json={"provider": "test",
                  "test_pages": {"stuk": ["Titel", "Hennep isoleert."]},
                  "max_sources": 6})
        client.post(f"/api/v1/workspaces/mycelium-ai/research/"
                    f"{record['run_id']}/report")

        mission = client.get(
            f"/api/v1/missions/{record['mission_id']}").json()
        assert mission["status"] == "pending_approval"
        refused = client.post(
            f"/api/v1/missions/{record['mission_id']}/approve",
            json={"response": "NO", "decided_by": "human"})
        assert refused.status_code == 422, refused.text

        from coordinator.app.database import (
            chat_connection as _chat_conn,
        )
        with _chat_conn() as db:
            proposals = db.execute(
                "SELECT COUNT(*) AS n FROM write_proposals").fetchone()
        assert proposals["n"] == 0

        memories = client.get("/api/v1/memory").json()
        assert all(entry["truth"] != "user_fact"
                   for entry in memories)
        assert all(entry["truth"] != "verified"
                   for entry in memories)


def test_research_npc_panel_visible(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register_worker(client)
        record = start(client)
        page = client.get("/workspaces/mycelium-ai").text
        assert response_ok(client, "/workspaces/mycelium-ai")
        assert "Research NPC" in page
        assert "Start research" in page
        assert NODE in page
        assert record["run_id"] in page
        assert f"/web/workspaces/mycelium-ai/research" in page
        # Run listed without dossier yet; report button present.
        assert "nog geen dossier" in page
        assert f"/web/workspaces/mycelium-ai/research/" \
            f"{record['run_id']}/report" in page


def response_ok(client, path):
    return client.get(path).status_code == 200
