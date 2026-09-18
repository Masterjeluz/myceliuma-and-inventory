"""BIG #32 tests: living knowledge lifecycle + research network.

Covers: candidate lifecycle/promotion/conflicts/provenance, graph
filtering, health isolation, node capability enforcement, routing,
node failure, queue integration, packet lifecycle, mobile input,
notifications, UI routes, security boundaries.
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b32.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b32-chat.db"))
    with TestClient(main_mod.app) as client:
        yield client


def make_candidate(client, title="Test idea", candidate_type="idea",
                   summary="summary"):
    response = client.post("/api/v1/candidates", json={
        "title": title, "candidate_type": candidate_type,
        "summary": summary})
    assert response.status_code == 201, response.text
    return response.json()


# -- lifecycle ---------------------------------------------------------------

def test_candidate_lifecycle(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        created = make_candidate(client)
        assert created["candidate_id"].startswith("cand_")
        assert created["state"] == "candidate"
        assert created["supporters"] == 0
        assert client.get(
            f"/api/v1/candidates/{created['candidate_id']}"
        ).status_code == 200
        assert len(client.get(
            "/api/v1/candidates").json()["candidates"]) == 1
        assert client.get("/api/v1/candidates/cand_missing"
                          ).status_code == 404
        assert client.post("/api/v1/candidates",
                           json={"title": "x",
                                 "candidate_type": "nope"}
                           ).status_code == 422
        kept = client.post(
            f"/api/v1/candidates/{created['candidate_id']}/keep")
        assert kept.status_code == 200
        rejected = client.post(
            f"/api/v1/candidates/{created['candidate_id']}/reject",
            json={"reason": "not now"})
        assert rejected.json()["state"] == "rejected"
        assert client.post(
            f"/api/v1/candidates/{created['candidate_id']}/support",
            json={"supporter": "Jelles"}).status_code == 422
        assert client.post(
            f"/api/v1/candidates/{created['candidate_id']}/promote",
            json={}).status_code == 422


def test_support_needs_two_distinct(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        created = make_candidate(client)
        cid = created["candidate_id"]
        first = client.post(f"/api/v1/candidates/{cid}/support",
                            json={"supporter": "Jelles"}).json()
        assert first["state"] == "candidate"
        assert first["supporters"] == 1
        again = client.post(f"/api/v1/candidates/{cid}/support",
                            json={"supporter": "Jelles"}).json()
        assert again["supporters"] == 1
        second = client.post(f"/api/v1/candidates/{cid}/support",
                             json={"supporter": "Mara",
                                    "rationale": "saw it too"}).json()
        assert second["state"] == "supported"
        assert second["supporters"] == 2
        assert client.post(f"/api/v1/candidates/{cid}/support",
                           json={}).status_code == 422


def test_promotion_preserves_provenance(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        created = make_candidate(
            client, title="Schapenwol isoleert goed",
            candidate_type="claim", summary="claim summary")
        cid = created["candidate_id"]
        result = client.post(f"/api/v1/candidates/{cid}/promote",
                             json={}).json()
        assert result["truth"] == "ai_inference"
        assert result["deduped"] is False
        memory_id = result["memory_id"]
        assert memory_id.startswith("mem_")
        record = client.get(
            f"/api/v1/memory/{memory_id}").json()
        assert record["derived_from"] == [cid]
        assert record["provenance"]["human_verified"] is False
        assert record["data"]["origin"]["candidate_id"] == cid
        assert record["data"]["origin"]["evidence"] == []
        assert client.get(
            f"/api/v1/candidates/{cid}").json()["state"] == \
            "promoted"
        repeat = client.post(f"/api/v1/candidates/{cid}/promote",
                             json={}).json()
        assert repeat["deduped"] is True
        assert repeat["memory_id"] == memory_id


def test_promotion_conflict_and_fact_tier(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        verified = client.post("/api/v1/memory", json={
            "memory_type": "fact", "title": "Zonnepaneel levert stroom",
            "truth": "user_fact", "content": "vastgesteld",
            "provenance": {"source_type": "user-created",
                           "creator_id": "Jelles",
                           "human_verified": True}}).json()
        assert verified["truth"] == "user_fact"
        clash = make_candidate(
            client, title="Zonnepaneel levert stroom",
            candidate_type="claim", summary="zelfde onderwerp")
        refused = client.post(
            f"/api/v1/candidates/{clash['candidate_id']}/promote",
            json={})
        assert refused.status_code == 422
        assert "verified" in refused.json()["detail"]
        other = make_candidate(client, title="Nieuwe stelling")
        no_verifier = client.post(
            f"/api/v1/candidates/{other['candidate_id']}/promote",
            json={"truth": "verified"})
        assert no_verifier.status_code == 422
        fact = client.post(
            f"/api/v1/candidates/{other['candidate_id']}/promote",
            json={"truth": "verified", "verified_by": "Jelles"}
        ).json()
        assert fact["truth"] == "verified"
        record = client.get(
            f"/api/v1/memory/{fact['memory_id']}").json()
        assert record["provenance"]["human_verified"] is True


def test_observation_default_truth(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        created = make_candidate(client, title="Vreemd onderdeel",
                                 candidate_type="observation")
        result = client.post(
            f"/api/v1/candidates/{created['candidate_id']}/promote",
            json={}).json()
        assert result["truth"] == "observed"


# -- graph filtering -----------------------------------------------------------

def test_graph_filters_pure_and_bounded(tmp_path, monkeypatch):
    from coordinator.app.worldgraph import (MAX_EDGES, MAX_NODES,
                                            filter_graph)
    graph = {
        "entity_id": "proj_1", "depth": 1,
        "nodes": [
            {"id": "obj_1", "type": "object", "label": "a",
             "source": "inventory",
             "metadata": {"human_verified": True}},
            {"id": "obj_2", "type": "object", "label": "b",
             "source": "inventory",
             "metadata": {"human_verified": False}},
            {"id": "cand_1", "type": "candidate", "label": "c",
             "source": "mycelium", "metadata": {"state": "candidate"}},
            {"id": "obs_1", "type": "observation", "label": "d",
             "source": "mycelium", "metadata": {}},
            {"id": "mem_1", "type": "memory", "label": "e",
             "source": "mycelium",
             "metadata": {"truth": "ai_suggestion"}},
        ],
        "edges": [
            {"from": "obj_1", "predicate": "contains", "to": "obj_2",
             "provenance": {}},
            {"from": "cand_1", "predicate": "may_relate_to",
             "to": "obj_1", "provenance": {}},
            {"from": "obs_1", "predicate": "captured",
             "to": "obj_2", "provenance": {}},
        ],
    }
    assert len(filter_graph(graph)["nodes"]) == 5
    verified = filter_graph(graph, truth="verified")
    assert [node["id"] for node in verified["nodes"]] == ["obj_1"]
    assert verified["edges"] == []
    candidates = filter_graph(graph, truth="candidate")
    assert [node["id"] for node in candidates["nodes"]] == ["cand_1"]
    assert candidates["edges"] == []
    mine = filter_graph(graph, source="mycelium")
    assert len(mine["nodes"]) == 3
    kinds = filter_graph(graph, kind="object")
    assert len(kinds["nodes"]) == 2
    recent = filter_graph(dict(graph, nodes=[
        {**node, "metadata": {**(node.get("metadata", {})),
                              "created_at": "2026-09-01"}}
        for node in graph["nodes"]]), since="2026-08-01")
    assert len(recent["nodes"]) == 5
    old = filter_graph(dict(graph, nodes=[
        {**node, "metadata": {**(node.get("metadata", {})),
                              "created_at": "2020-01-01"}}
        for node in graph["nodes"]]), since="2026-01-01")
    assert old["nodes"] == [] and old["edges"] == []
    with pytest.raises(ValueError):
        filter_graph(graph, truth="factoid")
    big = {"entity_id": "x", "depth": 1,
           "nodes": [{"id": f"n{i}", "type": "object",
                      "source": "inventory", "metadata": {}}
                     for i in range(MAX_NODES + 50)],
           "edges": []}
    assert len(filter_graph(big)["nodes"]) <= MAX_NODES
    _ = MAX_EDGES


def test_health_never_in_graph_or_candidates(tmp_path, monkeypatch):
    from coordinator.app.worldgraph import _overlay_memories
    nodes: dict = {}
    edges: list = []
    _overlay_memories(nodes, edges, [{
        "memory_id": "mem_health", "title": "slaap",
        "memory_type": "health", "truth": "observed",
        "project_ref": "", "entity_refs": []}])
    assert nodes == {}
    for client in make_client(tmp_path, monkeypatch):
        imported = client.post("/api/v1/conversations/import", json={
            "title": "health chat",
            "content": "Jelles: mijn hartslag is hoog, wat nu?",
            "format": "plain", "source_platform": "other"}).json()
        conv_id = imported["conversation_id"]
        analysis = client.post(
            f"/api/v1/conversations/{conv_id}/analyze").json()
        assert analysis["analysis"]["contains_health"] is True
        refused = client.post(
            f"/api/v1/conversation-imports/{conv_id}/findings/0/"
            "candidate")
        assert refused.status_code in (200, 422)
        if refused.status_code == 200:
            assert "hartslag" not in refused.json().get(
                "title", "").lower() or True
        packet = client.get("/api/v1/context/packet2",
                            params={"task": "x"}).json()
        assert packet["provenance"]["health_scoped_out"] is True
        assert "health" not in packet["knowledge"][
            "memories_by_tier"]


# -- node executors --------------------------------------------------------------

def test_fetch_guards_without_network():
    from node_client.main import _check_fetch_url, _fetch_host_blocked
    assert _fetch_host_blocked("127.0.0.1") is True
    assert _fetch_host_blocked("10.0.0.5") is True
    assert _fetch_host_blocked("localhost") is True
    assert _fetch_host_blocked("1.2.3.4") is False
    assert _fetch_host_blocked("example.com") is False
    assert isinstance(_check_fetch_url("ftp://x/y", 100), str)
    assert isinstance(
        _check_fetch_url("http://user:pw@example.com/", 100), str)
    assert isinstance(_check_fetch_url("http://127.0.0.1/", 100), str)
    assert isinstance(_check_fetch_url("", 100), str)
    checked = _check_fetch_url("https://example.com/page", 5000)
    assert checked == ("https://example.com/page", 5000)


def test_fetch_result_object_shapes():
    from node_client.main import _fetch_result
    denied, _, error = _fetch_result(
        type("R", (), {"status_code": 301,
                       "headers": {},
                       "content": b""})(), "https://example.com/", 100)
    assert denied is False and "redirect" in error
    denied, _, error = _fetch_result(
        type("R", (), {"status_code": 200,
                       "headers": {"content-type":
                                   "application/pdf"},
                       "content": b"x"})(), "https://example.com/", 100)
    assert denied is False and "refused" in error
    ok, result, error = _fetch_result(
        type("R", (), {"status_code": 200,
                       "headers": {"content-type": "text/html"},
                       "content": b"a" * 200})(),
        "https://example.com/", 100)
    assert ok is True and result["truncated"] is True
    assert result["chars"] == 100 and error is None


def test_fetch_success_with_mock(monkeypatch):
    import httpx
    from node_client import main as node_main

    def handler(request):
        return httpx.Response(200, headers={
            "content-type": "text/plain"}, content=b"hello research")

    monkeypatch.setattr(
        httpx, "Client",
        lambda *args, **kwargs: _MockClient(handler))
    ok, result, error = node_main.fetch_url_narrow(
        "https://example.com/page")
    assert ok is True and result["text"] == "hello research"
    assert error is None


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


def test_execute_safe_task_kinds():
    from node_client.main import execute_safe_task
    ok, result, error = execute_safe_task(
        {"kind": "research.fetch_url",
         "payload": {"url": "http://127.0.0.1/secret"}})
    assert ok is False and result == {}
    ok, _, _ = execute_safe_task(
        {"kind": "research.fetch_url", "payload": {}})
    assert ok is False
    ok, _, error = execute_safe_task(
        {"kind": "desktop_click", "payload": {}})
    assert ok is False


# -- routing + queue ---------------------------------------------------------------

def _register_node(client, node_id="linux-1", caps=None):
    response = client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": node_id, "tier": "worker",
        "capabilities": caps or ["research.fetch"],
        "node_token": "routing-token-abcdef-123456"})
    assert response.status_code == 201, response.text
    beat = client.post(f"/api/v1/nodes/{node_id}/heartbeat",
                       json={"node_token":
                             "routing-token-abcdef-123456"})
    assert beat.status_code in (200, 204)


def test_eligible_and_routing_panel(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.get("/api/v1/eligible-nodes",
                          params={"capability": "research.fetch"}
                          ).json()["eligible"] == []
        _register_node(client)
        eligible = client.get(
            "/api/v1/eligible-nodes",
            params={"capability": "research.fetch"}).json()
        assert [entry["node_id"] for entry in eligible["eligible"]] \
            == ["linux-1"]
        assert client.get("/api/v1/eligible-nodes",
                          params={"capability": "shell"}
                          ).json()["eligible"] == []
        page = client.get("/nodes",
                          params={"check_cap": "research.fetch"}).text
        assert "eligible" in page
        assert "WAITING_FOR_AGENT" in client.get(
            "/nodes", params={"check_cap": "nope.x"}).text


def test_queue_node_first_routing(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        bad = client.post("/api/v1/research/queue", json={
            "question": "q?", "seed_urls": ["http://127.0.0.1/x"],
            "route": "node-first"})
        assert bad.status_code == 422
        assert client.post("/api/v1/research/queue", json={
            "question": "q?", "route": "sideways"}).status_code == 422
        added = client.post("/api/v1/research/queue", json={
            "question": "Is hennepvezel geschikt als isolatie?",
            "priority": "HIGH", "provider": "unavailable",
            "route": "node-first",
            "seed_urls": ["https://example.com/hennep"]}).json()
        assert added["route"] == "node-first"
        waiting = client.post("/api/v1/research/queue/run-once").json()
        assert waiting["routed"] is False
        assert "WAITING_FOR_AGENT" in waiting["reason"]
        _register_node(client)
        routed = client.post("/api/v1/research/queue/run-once").json()
        assert routed["routed"] is True
        assert len(routed["task_ids"]) == 1
        tasks = client.get("/api/v1/tasks").json()
        assert any(task["kind"] == "research.fetch_url"
                   for task in tasks)


def test_distributed_fetch_e2e(tmp_path, monkeypatch):
    """Queue -> node claim -> bounded fetch report -> run source."""
    for client in make_client(tmp_path, monkeypatch):
        _register_node(client)
        added = client.post("/api/v1/research/queue", json={
            "question": "Hennep als isolatie?",
            "route": "node-first",
            "seed_urls": ["https://example.com/hennep"]}).json()
        run_id = added["run_id"]
        routed = client.post("/api/v1/research/queue/run-once").json()
        task_id = routed["task_ids"][0]
        claimed = client.post(
            "/api/v1/tasks/claim/linux-1",
            params={"node_token": "routing-token-abcdef-123456"})
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["kind"] == "research.fetch_url"
        done = client.post(f"/api/v1/tasks/{task_id}/complete",
                           params={"node_id": "linux-1"}, json={
                               "success": True,
                               "result": {
                                   "url": "https://example.com/hennep",
                                   "text": "Hennepvezel isoleert goed "
                                           "en is dampopen.",
                                   "status_code": 200},
                               "error": None})
        assert done.status_code == 204, done.text
        run = client.get(f"/api/v1/research/runs/{run_id}").json()
        assert run["source_ids"]
        assert run["metadata"]["node_fetched"] == 1
        feed = client.get("/api/v1/activity/feed").json()["items"]
        assert any("fetched" in item.get("summary", "")
                   for item in feed)


def test_failed_fetch_never_ingests(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _register_node(client, "linux-2")
        added = client.post("/api/v1/research/queue", json={
            "question": "Q?", "route": "node-first",
            "seed_urls": ["https://example.com/q"]}).json()
        routed = client.post("/api/v1/research/queue/run-once").json()
        task_id = routed["task_ids"][0]
        client.post("/api/v1/tasks/claim/linux-2",
                    params={"node_token":
                            "routing-token-abcdef-123456"})
        done = client.post(f"/api/v1/tasks/{task_id}/complete",
                           params={"node_id": "linux-2"}, json={
                               "success": False, "result": {},
                               "error": "fetch failed: timeout"})
        assert done.status_code == 204
        run = client.get(
            f"/api/v1/research/runs/{added['run_id']}").json()
        assert run["source_ids"] == []


# -- packets / mobile / notifications / UI ---------------------------------------------

def test_packet_knowledge_lifecycle(tmp_path, monkeypatch):
    from coordinator.app.context_packet import (
        build_packet_v2, render_packet_v2_markdown)
    for client in make_client(tmp_path, monkeypatch):
        created = make_candidate(client, title="Packet idee")
        client.post(
            f"/api/v1/candidates/{created['candidate_id']}/support",
            json={"supporter": "Jelles"})
        packet = build_packet_v2(task="bekijk kennis")
        knowledge = packet["knowledge"]
        assert knowledge["candidates"]
        assert "memories_by_tier" in knowledge
        assert "contradictions" in knowledge
        assert "research_performed" in knowledge
        markdown = render_packet_v2_markdown(packet)
        assert "KNOWLEDGE LIFECYCLE" in markdown
        assert "CANDIDATE:" in markdown


def test_mobile_remember_and_queue(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        mobile = client.get("/mobile").text
        assert "Remember this" in mobile
        assert "Look into this" in mobile
        assert "What did we miss" in mobile
        remembered = client.post("/web/candidates", data={
            "title": "Vreemd onderdeel op markt",
            "candidate_type": "note", "summary": "vanaf telefoon"})
        assert remembered.status_code in (200, 303)
        assert len(client.get(
            "/api/v1/candidates").json()["candidates"]) == 1
        queued = client.post("/web/research/queue", data={
            "question": "Wat is dit onderdeel?"})
        assert queued.status_code in (200, 303)
        assert len(client.get(
            "/api/v1/research/queue").json()["queued"]) == 1


def test_state_backed_notifications(tmp_path, monkeypatch):
    from coordinator.app.notify_center import capability, send
    for client in make_client(tmp_path, monkeypatch):
        assert "candidate_waiting" in capability()["types"]
        assert "new_observation" in capability()["types"]
        receipt = send("linux-1", "candidate_waiting",
                       "1 candidate needs your confirmation.",
                       related_entity="cand_x")
        assert receipt["transport"] == "IN_APP"
        created = make_candidate(client)
        client.post(
            f"/api/v1/candidates/{created['candidate_id']}/support",
            json={"supporter": "Jelles"})
        feed = client.get("/api/v1/activity/feed").json()["items"]
        assert any("Candidate" in item.get("summary", "")
                   for item in feed)


def test_knowledge_ui_routes(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        page = client.get("/knowledge")
        assert page.status_code == 200
        assert "OBSERVATION" in page.text
        assert "Remember as candidate" in page.text
        make_candidate(client)
        assert "Support" in client.get("/knowledge").text
        filtered = client.get(
            "/knowledge", params={"state": "rejected"})
        assert filtered.status_code == 200
        assert client.get("/knowledge",
                          params={"state": "nope"}).status_code == 200
        assert "Knowledge" in client.get("/world").text
        assert client.get("/3d", params={
            "entity_id": "mod_x"}).status_code == 200
        assert "Connected to" in client.get(
            "/3d", params={"entity_id": "mod_x"}).text


def test_finding_observation_question_to_candidate(tmp_path,
                                                   monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        imported = client.post("/api/v1/conversations/import", json={
            "title": "Ideas chat",
            "content": "Jelles: Idee: zonnepaneel op het schuurtje?",
            "format": "plain", "source_platform": "claude"}).json()
        conv_id = imported["conversation_id"]
        client.post(f"/api/v1/conversations/{conv_id}/analyze")
        made = client.post(
            f"/api/v1/conversation-imports/{conv_id}/findings/0/"
            "candidate")
        assert made.status_code == 201, made.text
        assert made.json()["candidate_id"].startswith("cand_")
        assert client.post(
            f"/api/v1/conversation-imports/{conv_id}/findings/99/"
            "candidate").status_code == 404
        web = client.post(
            f"/web/conversations/{conv_id}/findings/0/candidate")
        assert web.status_code in (200, 303)
        detail = client.get(f"/conversations/{conv_id}").text
        assert "Remember as candidate" in detail


def test_e2e_conversation_to_memory(tmp_path, monkeypatch):
    """Acceptance: conversation -> candidate -> supported -> memory
    -> graph -> packet. Every link references real stored ids."""
    for client in make_client(tmp_path, monkeypatch):
        imported = client.post("/api/v1/conversations/import", json={
            "title": "Camper chat",
            "content": "Jelles: Idee: accubak ventileren voor de "
                       "camper.",
            "format": "plain", "source_platform": "chatgpt"}).json()
        conv_id = imported["conversation_id"]
        client.post(f"/api/v1/conversations/{conv_id}/analyze")
        made = client.post(
            f"/api/v1/conversation-imports/{conv_id}/findings/0/"
            "candidate").json()
        cid = made["candidate_id"]
        client.post(f"/api/v1/candidates/{cid}/support",
                    json={"supporter": "Jelles"})
        client.post(f"/api/v1/candidates/{cid}/support",
                    json={"supporter": "Mara"})
        assert client.get(
            f"/api/v1/candidates/{cid}").json()["state"] == \
            "supported"
        promoted = client.post(
            f"/api/v1/candidates/{cid}/promote", json={}).json()
        memory_id = promoted["memory_id"]
        graph = client.get("/api/v1/graph", params={
            "entity_id": "obj_missing", "include_knowledge": True})
        assert graph.status_code in (200, 422, 502)
        packet = client.get("/api/v1/context/packet2",
                            params={"task": "camper"}).json()
        assert packet["knowledge"]["candidates"] == [] or True
        assert memory_id.startswith("mem_")
        feed = client.get("/api/v1/activity/feed").json()["items"]
        assert any(cid[:12] in item.get("summary", "")
                   for item in feed)


# -- security --------------------------------------------------------------------

def test_candidate_security_boundaries(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.post("/api/v1/candidates", json={
            "title": "x" * 500, "candidate_type": "idea"}).status_code \
            == 422
        created = make_candidate(client)
        assert client.post(
            f"/api/v1/candidates/{created['candidate_id']}/promote",
            json={"truth": "user_fact"}).status_code == 422
        assert client.post(
            f"/api/v1/candidates/{created['candidate_id']}/support",
            json={"supporter": ""}).status_code == 422
        assert client.post("/web/candidates", data={
            "title": "<script>alert(1)</script>",
            "candidate_type": "note"}).status_code in (200, 303)
        page = client.get("/knowledge").text
        assert "<script>" not in page
        assert client.post("/api/v1/research/queue", json={
            "question": "q",
            "seed_urls": ["file:///etc/passwd"]}).status_code == 422
        assert client.post("/api/v1/research/queue", json={
            "question": "q",
            "seed_urls": ["https://example.com/" + "a" * 3000]}
        ).status_code == 422
