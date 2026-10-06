"""BIG50 game integration: Journal, honest research affordance,
in-world knowledge support. All through existing models/routes."""

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b50.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b50-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", "b50-operator")
    with TestClient(main_mod.app) as test_client:
        yield test_client


def make_mission(test_client, goal="Journal missie"):
    chat = test_client.post("/api/v1/chat",
                            json={"message": "hi"}).json()
    res = test_client.post("/api/v1/missions", json={
        "conversation_id": chat["conversation_id"], "goal": goal,
        "steps": [{"kind": "readout", "description": "Lees",
                   "parameters": {"source": "project"}}]})
    assert res.status_code == 201, res.text
    return res.json()


def test_journal_empty_shape(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        res = test_client.get("/api/v1/play/journal")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["active"] is None
        assert body["waiting"] == []
        assert body["quests"] == []
        assert body["research"] == []
        assert body["candidates"] == []


def test_journal_ranks_active_and_waiting(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        pending = make_mission(test_client, goal="Wachtende missie")
        active = make_mission(test_client, goal="Actieve missie")
        yes = test_client.post(
            f"/api/v1/missions/{active['mission_id']}/approve",
            json={"response": "YES", "decided_by": "jelles"})
        assert yes.status_code == 200, yes.text

        body = test_client.get("/api/v1/play/journal").json()
        assert body["active"]["id"] == active["mission_id"]
        assert body["active"]["action"]["path"].endswith("/tick")
        assert body["active"]["progress"] == "0/1"
        assert body["active"]["step"]["kind"] == "readout"
        waiting = [w for w in body["waiting"]
                   if w["id"] == pending["mission_id"]]
        assert len(waiting) == 1
        assert waiting[0]["action"]["path"].endswith("/approve")
        assert body["counts"]["missions_active"] == 1
        assert body["counts"]["missions_waiting"] == 1


def test_journal_shows_quests_candidates_research(tmp_path,
                                                 monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        quest = test_client.post("/api/v1/quests", json={
            "title": "Journal quest",
            "steps": [{"key": "s", "label": "Notitie",
                       "kind": "note", "ref": ""}]})
        assert quest.status_code == 201, quest.text
        cand = test_client.post("/api/v1/candidates", json={
            "title": "Journal vondst", "candidate_type": "observation",
            "state": "observation", "summary": "x"})
        assert cand.status_code == 201, cand.text
        run = test_client.post("/api/v1/research/queue", json={
            "question": "Journal vraag?"})
        assert run.status_code == 201, run.text

        body = test_client.get("/api/v1/play/journal").json()
        assert [q for q in body["quests"]
                if q["id"] == quest.json()["quest_id"]]
        assert [c for c in body["candidates"]
                if c["id"] == cand.json()["candidate_id"]]
        assert [r for r in body["research"]
                if r["id"] == run.json()["run_id"]]
        assert body["counts"]["quests_open"] == 1
        assert body["counts"]["candidates_open"] == 1
        assert body["counts"]["research_open"] == 1


def test_plan_refuses_draft_run_without_dossier(tmp_path, monkeypatch):
    """Backend contract the game now respects: 422, no dossier
    invented, no Plan offered for unplannable runs."""
    for test_client in api(tmp_path, monkeypatch):
        run = test_client.post("/api/v1/research/queue", json={
            "question": "Onplanbare vraag?"}).json()
        plan = test_client.post(
            f"/api/v1/research/{run['run_id']}/plan", json={})
        assert plan.status_code == 422, plan.text
        assert "dossier" in plan.text.lower()


def test_inworld_support_counts(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        cand = test_client.post("/api/v1/candidates", json={
            "title": "Steun deze vondst",
            "candidate_type": "observation", "state": "observation",
            "summary": "x"}).json()
        cid = cand["candidate_id"]
        first = test_client.post(
            f"/api/v1/candidates/{cid}/support",
            json={"supporter": "speler", "rationale": ""})
        assert first.status_code == 200, first.text
        assert first.json()["supporters"] == 1
        # Same supporter is a no-op, never double counts.
        again = test_client.post(
            f"/api/v1/candidates/{cid}/support",
            json={"supporter": "speler", "rationale": ""})
        assert again.json()["supporters"] == 1
        second = test_client.post(
            f"/api/v1/candidates/{cid}/support",
            json={"supporter": "luma", "rationale": ""})
        assert second.json()["state"] == "supported"


def test_side_journal_and_support_hooks(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        html = test_client.get("/side").text
        for marker in ("journal-open", "renderJournal",
                       "/api/v1/play/journal",
                       "data-act=\"jyes\"", "data-act=\"jtick\"",
                       "data-act=\"ksup\"",
                       "Voltooide dossiers", "niet planbaar",
                       "zonder bruikbaar dossier",
                       "Terug naar station"):
            assert marker in html, marker
