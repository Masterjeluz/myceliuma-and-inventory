"""BIG 46 slices 1+2: quest -> mission -> action -> result from /play.

The game composes existing backend truth: quest step refs resolve
to existing mission ids with live status; approval/tick reuse the
existing gates; results come from existing mission/task/event
readers. Slice 2 adds live claiming-node visibility per task:
claimed tasks show node id + live state, unclaimed tasks show an
honest waiting hint. No new model, no bypass, no fake progress.
"""
import json
import re
from contextlib import contextmanager

import coordinator.app.main as main_mod


@contextmanager
def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "queue.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "chat.db"))
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "fab"))
    with TestClient(main_mod.app) as client:
        yield client


def _seed(tmp_path, monkeypatch):
    from coordinator.app.quests import new_quest, save_quest

    mission = main_mod._executor().create(
        "conv-big46-1", "Isoleer de camper",
        [{"kind": "research", "description": "zoek isolatie"}],
        max_steps=5, context_records=[])
    save_quest(new_quest("Camper quest", [
        {"key": "s1", "label": "Start isolatie-missie",
         "kind": "mission", "ref": mission.mission_id}]))
    save_quest(new_quest("Losse quest", [
        {"key": "s1", "label": "Algemene notitie",
         "kind": "note", "ref": ""}]))
    return mission


def _playdata(client):
    html = client.get("/play").text
    return json.loads(
        re.search(r"const PLAYDATA = (\{.*?\});\n",
                  html, re.DOTALL).group(1))


def test_quest_renders_linked_mission(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        mission = _seed(tmp_path, monkeypatch)
        lines = {q["title"]: q
                 for q in _playdata(client)["questlines"]}
        linked = lines["Camper quest"]["missions"]
        assert linked and linked[0]["id"] == mission.mission_id
        assert linked[0]["status"] == "pending_approval"


def test_quest_without_mission_start_path(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        _seed(tmp_path, monkeypatch)
        lines = {q["title"]: q
                 for q in _playdata(client)["questlines"]}
        assert lines["Losse quest"]["missions"] == []
        # existing start path: goal prefill on /missions
        res = client.get("/missions", params={"goal": "Losse quest"})
        assert res.status_code == 200
        assert 'value="Losse quest"' in res.text


def test_game_approval_cannot_be_bypassed(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        mission = _seed(tmp_path, monkeypatch)
        bad = client.post(
            f"/api/v1/missions/{mission.mission_id}/approve",
            json={"response": "maybe", "decided_by": "game"})
        assert bad.status_code in (422, 409)
        still = client.get(
            f"/api/v1/missions/{mission.mission_id}").json()
        assert still["status"] == "pending_approval"


def test_tick_result_visible_via_existing_readers(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        mission = _seed(tmp_path, monkeypatch)
        ok = client.post(
            f"/api/v1/missions/{mission.mission_id}/approve",
            json={"response": "YES", "decided_by": "game"})
        assert ok.json()["status"] == "approved"
        tick = client.post(
            f"/api/v1/missions/{mission.mission_id}/tick", json={})
        assert tick.status_code == 200
        events = client.get(
            f"/api/v1/missions/{mission.mission_id}/events").json()
        assert len(events) >= 1
        detail = client.get(
            f"/api/v1/missions/{mission.mission_id}").json()
        assert detail["status"] in ("approved", "running",
                                    "completed", "blocked", "failed",
                                    "paused")
        tasks = client.get("/api/v1/tasks").json()
        assert isinstance(tasks, list)
        nodes = client.get("/api/v1/nodes").json()
        assert isinstance(nodes, list)


def test_honest_simulated_states_on_play(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        html = client.get("/play").text
        assert "SIMULATED" in html


def _register_worker(client, node_id="worker-s2"):
    res = client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": node_id, "tier": "worker",
        "capabilities": ["research.fetch"],
        "node_token": "slice2-token-abcdef-123456"})
    assert res.status_code == 201, res.text


def test_claimed_task_shows_node_and_live_state(tmp_path, monkeypatch):
    """Slice 2: the exact fields the game result block composes —
    task.assigned_node_id plus node derived_status/current_task."""
    with _client(tmp_path, monkeypatch) as client:
        _register_worker(client)
        created = client.post("/api/v1/tasks", json={
            "kind": "system_inventory"}).json()
        task_id = created["id"]
        assigned = client.post(
            f"/api/v1/tasks/{task_id}/assign",
            json={"node_id": "worker-s2", "policy": {}})
        assert assigned.status_code == 200, assigned.text
        claimed = client.post(
            "/api/v1/tasks/claim/worker-s2",
            params={"node_token": "slice2-token-abcdef-123456"})
        assert claimed.status_code == 200, claimed.text
        task = client.get(f"/api/v1/tasks/by-id/{task_id}").json()
        assert task["assigned_node_id"] == "worker-s2"
        nodes = {row["node_id"]: row
                 for row in client.get("/api/v1/nodes").json()}
        node = nodes["worker-s2"]
        assert node["derived_status"] in ("online", "busy")
        current = node["current_task"] or {}
        assert str(current.get("task_id")) == str(task_id)
        # game composition hooks render these exact fields
        html = client.get("/play").text
        for hook in ("assigned_node_id", "derived_status",
                     "werkt hieraan", "Taken verversen", "mrefresh"):
            assert hook in html, hook


def test_unclaimed_task_shows_waiting_hint(tmp_path, monkeypatch):
    """Slice 2: a task nobody claimed keeps no node and the game
    keeps its honest waiting hint instead of implying work."""
    with _client(tmp_path, monkeypatch) as client:
        created = client.post("/api/v1/tasks", json={
            "kind": "system_inventory"}).json()
        task = client.get(
            f"/api/v1/tasks/by-id/{created['id']}").json()
        assert not task.get("assigned_node_id")
        html = client.get("/play").text
        assert "wacht op worker" in html


class _OracleReader:
    async def search(self, q, type=None):
        from coordinator.app.inventory_read import SearchResponse
        return SearchResponse(query=q or "", total=1, results=[{
            "entity_type": "object", "entity_id": "obj_moer",
            "title": "Moer M8", "snippet": "rvs",
            "provenance": {"source_type": "user-created",
                           "creator_id": "oracle-test",
                           "human_verified": False}}])

    async def browse(self, type=None):
        return await self.search("", type)


class _OracleAdvisor:
    async def advise(self, question, records):
        from coordinator.app.ollama_advisor import AdviceResponse
        return AdviceResponse(
            question=question, advice="Gebruik de Moer M8.",
            model="oracle-test-model", records_used=len(records),
            sources=[{"entity_id": "obj_moer",
                      "source_type": "user-created",
                      "human_verified": False}])


def test_oracle_ui_exists_in_play(tmp_path, monkeypatch):
    """S1 Oracle: Ask Oracle action, form, endpoint call and mission
    handoff are composed inside the /play dialog."""
    with _client(tmp_path, monkeypatch) as client:
        html = client.get("/play").text
        for hook in ("Ask Oracle", "renderOracle", "oracleask",
                     "oracle-q", "oracle-result", "oracleSourceLink",
                     "/api/v1/advise",
                     "Start mission from this advice",
                     "/missions?goal="):
            assert hook in html, hook


def test_oracle_uses_existing_advise_contract(tmp_path, monkeypatch):
    """S1 Oracle: the exact JS payload shape resolves through the
    unchanged advise backend, sources included."""
    with _client(tmp_path, monkeypatch) as client:
        monkeypatch.setattr(main_mod, "_world_reader",
                            lambda: _OracleReader())
        monkeypatch.setattr(main_mod, "_advisor",
                            lambda: _OracleAdvisor())
        res = client.post("/api/v1/advise", json={
            "q": "Wat kan ik maken?", "question": "Wat kan ik maken?"})
        assert res.status_code == 200
        body = res.json()
        assert body["advice"] == "Gebruik de Moer M8."
        assert body["model"] == "oracle-test-model"
        assert body["records_used"] == 1
        assert body["sources"][0]["entity_id"] == "obj_moer"
        assert body["retrieval_mode"] in ("lexical", "semantic",
                                          "hybrid")


def test_oracle_unavailable_is_honest(tmp_path, monkeypatch):
    """S1 Oracle: Ollama down surfaces as 502, which the dialog
    renders as UNAVAILABLE — never a fabricated answer."""
    with _client(tmp_path, monkeypatch) as client:
        class _DownAdvisor:
            async def advise(self, question, records):
                from coordinator.app.ollama_advisor import (
                    OllamaUnavailable)
                raise OllamaUnavailable("down")

        monkeypatch.setattr(main_mod, "_world_reader",
                            lambda: _OracleReader())
        monkeypatch.setattr(main_mod, "_advisor",
                            lambda: _DownAdvisor())
        res = client.post("/api/v1/advise", json={
            "q": "x", "question": "Wat kan ik maken?"})
        assert res.status_code == 502
        html = client.get("/play").text
        assert "UNAVAILABLE" in html


def test_oracle_adds_no_backend_route():
    """S1 Oracle: composition only — no new backend route exists."""
    paths = [getattr(route, "path", "")
             for route in main_mod.app.routes]
    assert not any("oracle" in path.lower() for path in paths)
    assert any(path == "/api/v1/advise" for path in paths)


PAGES = {
    "camper": ["Camper isolatie",
               "Hennepvezel isoleert goed en is dampopen. "
               "De camper heeft een zonnepaneel van 200 watt."],
}


def test_research_action_exists_in_luma(tmp_path, monkeypatch):
    """S4 Research: Luma offers Research; the view composes only
    existing research endpoints (queue, runs, dossier, plan)."""
    with _client(tmp_path, monkeypatch) as client:
        html = client.get("/play").text
        for hook in ("Research", "renderResearch", "resqueue",
                     "resrun", "resdossier", "resplan", "resrefresh",
                     "/api/v1/research/queue",
                     "/api/v1/research/queue/run-once"):
            assert hook in html, hook


def test_research_queue_and_states(tmp_path, monkeypatch):
    """S4 Research: question queues via the existing endpoint and
    the run state reads back honestly through existing readers."""
    with _client(tmp_path, monkeypatch) as client:
        empty = client.post("/api/v1/research/queue",
                            json={"question": "   "})
        assert empty.status_code == 422
        created = client.post("/api/v1/research/queue", json={
            "question": "Isoleert hennepvezel een camper?"})
        assert created.status_code == 201, created.text
        run_id = created.json()["run_id"]
        assert run_id.startswith("res_")
        runs = client.get("/api/v1/research/runs").json()
        match = [run for run in runs if run["run_id"] == run_id]
        assert len(match) == 1
        assert match[0]["status"] in ("draft", "collecting",
                                      "extracting", "synthesizing",
                                      "completed", "blocked", "failed",
                                      "cancelled", "unavailable")
        assert "execution_state" in match[0]
        assert "dossier_id" in match[0]


def test_research_dossier_and_plan_flow(tmp_path, monkeypatch):
    """S4 Research: deterministic test-provider run completes to a
    dossier, and planning yields a pending-approval mission —
    never auto-approved."""
    with _client(tmp_path, monkeypatch) as client:
        created = client.post("/api/v1/research/runs", json={
            "question": "Isoleert hennepvezel een camper?",
            "provider": "test", "test_pages": PAGES})
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["status"] == "completed"
        dossier_id = body["dossier_id"]
        assert dossier_id.startswith("dos_")
        dossier = client.get(
            f"/api/v1/research/dossiers/{dossier_id}").json()
        assert dossier["dossier_id"] == dossier_id
        assert dossier["question"]
        planned = client.post(
            f"/api/v1/research/{dossier_id}/plan", json={})
        assert planned.status_code in (200, 201), planned.text
        mission = planned.json()
        assert mission["status"] == "pending_approval"
        mission_id = mission["mission_id"]
        again = client.post(
            f"/api/v1/research/{dossier_id}/plan", json={})
        assert again.status_code == 200
        assert again.json()["is_new"] is False
        # approval still required: wrong response stays denied
        bad = client.post(
            f"/api/v1/missions/{mission_id}/approve",
            json={"response": "maybe", "decided_by": "game"})
        assert bad.status_code in (422, 409)
        detail = client.get(
            f"/api/v1/missions/{mission_id}").json()
        assert detail["status"] == "pending_approval"


def _make_candidate(client, title="Koperdraad isoleren",
                    candidate_type="observation"):
    res = client.post("/api/v1/candidates", json={
        "title": title, "candidate_type": candidate_type,
        "summary": "mogelijke isolatie-aanpak"})
    assert res.status_code == 201, res.text
    return res.json()


def test_knowledge_action_reachable_from_luma(tmp_path, monkeypatch):
    """S5 Knowledge: Luma offers Knowledge; the view composes only
    existing candidate endpoints plus support/promote/reject."""
    with _client(tmp_path, monkeypatch) as client:
        html = client.get("/play").text
        for hook in ("Knowledge", "renderKnowledge", "knowdetail",
                     "knowsupport", "knowreject", "knowpromote",
                     "knowrefresh", "/api/v1/candidates",
                     "verified_by"):
            assert hook in html, hook


def test_knowledge_support_flow(tmp_path, monkeypatch):
    """S5 Knowledge: existing candidate data renders and support
    calls the existing endpoint with visible state change."""
    with _client(tmp_path, monkeypatch) as client:
        entry = _make_candidate(client)
        cid = entry["candidate_id"]
        detail = client.get(
            f"/api/v1/candidates/{cid}").json()
        assert detail["state"] in ("observation", "candidate",
                                   "supported")
        first = client.post(
            f"/api/v1/candidates/{cid}/support",
            json={"supporter": "jelles", "rationale": ""})
        assert first.status_code == 200, first.text
        assert first.json()["supporters"] >= 1
        second = client.post(
            f"/api/v1/candidates/{cid}/support",
            json={"supporter": "luma", "rationale": ""})
        assert second.json()["supporters"] >= 2
        assert second.json()["state"] == "supported"


def test_knowledge_reject_flow(tmp_path, monkeypatch):
    """S5 Knowledge: reject calls the existing endpoint and the
    terminal state stays visible as audit trail."""
    with _client(tmp_path, monkeypatch) as client:
        entry = _make_candidate(client, title="Slechte aanpak")
        cid = entry["candidate_id"]
        done = client.post(
            f"/api/v1/candidates/{cid}/reject",
            json={"reason": "", "decided_by": "jelles"})
        assert done.status_code == 200, done.text
        assert done.json()["state"] == "rejected"


def test_knowledge_promote_gates_intact(tmp_path, monkeypatch):
    """S5 Knowledge: promote reuses exact requirements — AI tiers
    promote openly, fact tiers refuse without verified_by, and the
    resulting memory id is returned visibly."""
    with _client(tmp_path, monkeypatch) as client:
        entry = _make_candidate(client)
        cid = entry["candidate_id"]
        done = client.post(
            f"/api/v1/candidates/{cid}/promote",
            json={"truth": "", "verified_by": "", "importance": 0.6})
        assert done.status_code == 200, done.text
        assert done.json()["memory_id"].startswith("mem_")
        fact = _make_candidate(client, title="Feit kandidaat")
        refused = client.post(
            f"/api/v1/candidates/{fact['candidate_id']}/promote",
            json={"truth": "verified", "verified_by": "",
                  "importance": 0.6})
        assert refused.status_code == 422
        allowed = client.post(
            f"/api/v1/candidates/{fact['candidate_id']}/promote",
            json={"truth": "verified", "verified_by": "jelles",
                  "importance": 0.6})
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["truth"] == "verified"


def test_research_adds_no_backend_route():
    """S4 Research: the game posts only to pre-existing research
    endpoints — no game-specific research route exists."""
    allowed = {"/api/v1/research/queue",
               "/api/v1/research/queue/run-once",
               "/api/v1/research/runs",
               "/api/v1/research/runs/{run_id}",
               "/api/v1/research/runs/{run_id}/execute",
               "/api/v1/research/dossiers",
               "/api/v1/research/dossiers/{dossier_id}",
               "/api/v1/research/{research_id}/plan"}
    paths = {getattr(route, "path", "")
             for route in main_mod.app.routes}
    for path in paths:
        assert "game-research" not in path
        assert "luma-research" not in path
    assert allowed.issubset(paths)
