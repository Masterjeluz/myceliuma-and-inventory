"""Mission tests (BIG #3, §17).

Creation, persistence, validation, approvals, bindings, executor
chain (mission -> dact -> agent -> observation -> next step),
scope violations, races, events, chat integration. Fail-closed
first; the desktop side is simulated through HTTP (no real input).
"""

import os

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.missions import (
    MissionConflictError,
    approve_mission,
    check_binding,
    load_mission,
    new_mission,
    save_mission,
)


def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH", str(tmp_path / "m-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def readonly_steps():
    return [
        {"kind": "readout", "description": "Lees project",
         "parameters": {"source": "project"}},
        {"kind": "analysis", "description": "Vat samen",
         "parameters": {"question": "Wat moet er gebeuren?"}},
    ]


def make_conversation(test_client):
    response = test_client.post("/api/v1/chat", json={
        "message": "hallo"})
    assert response.status_code == 200
    return response.json()["conversation_id"]


class FakeProvider:
    def __init__(self, advice="Doe X, dan Y.", fail=None):
        self._advice = advice
        self._fail = fail

    async def advise(self, question, records):
        if self._fail:
            raise self._fail
        from coordinator.app.ollama_advisor import AdviceResponse
        return AdviceResponse(question=question, advice=self._advice,
                              model="fake", records_used=len(records),
                              sources=[])


class FakeReader:
    async def search(self, q, type=None):
        from coordinator.app.inventory_read import SearchResponse
        return SearchResponse(query=q, results=[], total=0)

    async def browse(self, type=None):
        return await self.search("", type)


@pytest.fixture()
def fakes(monkeypatch):
    monkeypatch.setattr(main_mod, "_world_reader", lambda: FakeReader())
    monkeypatch.setattr(main_mod, "get_provider",
                        lambda name=None, **k: FakeProvider())
    return True


# -- creation & validation -----------------------------------------------

def test_mission_create_and_persist(tmp_path, monkeypatch, fakes):
    for test_client in client(tmp_path, monkeypatch):
        conversation = make_conversation(test_client)
        created = test_client.post("/api/v1/missions", json={
            "conversation_id": conversation,
            "goal": "Bekijk mijn project",
            "steps": readonly_steps()})
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["mission_id"].startswith("mission_")
        assert body["status"] == "pending_approval"
        assert [step["sequence"] for step in body["steps"]] == [0, 1]
        assert body["steps"][0]["step_id"].startswith("step_")

        fetched = test_client.get(
            f"/api/v1/missions/{body['mission_id']}")
        assert fetched.status_code == 200
        assert fetched.json()["goal"] == "Bekijk mijn project"
        assert test_client.get("/api/v1/missions/unknown").status_code == 404


def test_mission_create_rejects_garbage(tmp_path, monkeypatch, fakes):
    for test_client in client(tmp_path, monkeypatch):
        conversation = make_conversation(test_client)
        base = {"conversation_id": conversation, "goal": "x"}
        assert test_client.post("/api/v1/missions", json={
            **base, "goal": "  "}).status_code == 422
        assert test_client.post("/api/v1/missions", json={
            **base, "steps": []}).status_code == 422
        assert test_client.post("/api/v1/missions", json={
            **base, "steps": [{"kind": "teleport",
                               "description": "x"}]}).status_code == 422
        assert test_client.post("/api/v1/missions", json={
            **base, "steps": [{"kind": "desktop",
                               "description": "x",
                               "action_type": "run_shell",
                               "parameters": {}}]}).status_code == 422
        assert test_client.post("/api/v1/missions", json={
            **base, "steps": [{"kind": "readout", "description": "x",
                               "parameters": {"source": "cloud"}}]
        }).status_code == 422
        # input step claiming no approval is refused
        assert test_client.post("/api/v1/missions", json={
            **base, "steps": [{"kind": "desktop", "description": "x",
                               "action_type": "click",
                               "parameters": {"x": 1, "y": 1},
                               "requires_approval": False}]
        }).status_code == 422
        # non-desktop step claiming approval is refused
        assert test_client.post("/api/v1/missions", json={
            **base, "steps": [{"kind": "readout", "description": "x",
                               "parameters": {"source": "project"},
                               "requires_approval": True}]
        }).status_code == 422


def test_new_mission_model_rules():
    with pytest.raises(ValueError):
        new_mission("mission_a", "conv-1", "  ", [{"kind": "readout",
                                                   "description": "x",
                                                   "parameters": {
                                                       "source": "project"}}])
    mission = new_mission("mission_b", "conv-1", "doel",
                          readonly_steps(), max_steps=5)
    assert mission.max_steps == 5
    with pytest.raises(ValueError):
        new_mission("mission_c", "conv-1", "doel", readonly_steps(),
                    max_steps=99)
    with pytest.raises(ValueError):
        approve_mission(mission, "ja graag")
    approved = approve_mission(mission, "YES", decided_by="jelles")
    assert approved.status == "approved"
    assert approved.approved_by == "jelles"
    with pytest.raises(ValueError):
        approve_mission(approved, "YES")


def test_save_conflict_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH", str(tmp_path / "c.db"))
    mission = new_mission("mission_race", "conv-1", "doel",
                          readonly_steps())
    save_mission(mission)
    with pytest.raises(MissionConflictError):
        save_mission(mission, expected=("running", 0))
    assert load_mission("mission_race").status == "pending_approval"


# -- control: approve/pause/resume/cancel ----------------------------------

def test_mission_control_lifecycle(tmp_path, monkeypatch, fakes):
    for test_client in client(tmp_path, monkeypatch):
        conversation = make_conversation(test_client)
        mission_id = test_client.post("/api/v1/missions", json={
            "conversation_id": conversation, "goal": "doel",
            "steps": [{"kind": "desktop", "description": "Klik",
                       "action_type": "click",
                       "parameters": {"x": 5, "y": 5},
                       "requires_approval": True}]}).json()["mission_id"]
        assert test_client.post(
            f"/api/v1/missions/{mission_id}/approve",
            json={"response": "misschien"}).status_code == 422
        assert test_client.post(
            f"/api/v1/missions/{mission_id}/approve",
            json={"response": "YES"}).json()["status"] == "approved"
        assert test_client.post(
            f"/api/v1/missions/{mission_id}/approve",
            json={"response": "YES"}).status_code == 422
        assert test_client.post(
            f"/api/v1/missions/{mission_id}/tick").status_code == 200
        paused = test_client.post(
            f"/api/v1/missions/{mission_id}/pause")
        assert paused.json()["status"] == "paused"
        assert test_client.post(
            f"/api/v1/missions/{mission_id}/tick").status_code == 422
        assert test_client.post(
            f"/api/v1/missions/{mission_id}/resume").json()["status"] \
            == "running"
        cancelled = test_client.post(
            f"/api/v1/missions/{mission_id}/cancel")
        assert cancelled.json()["status"] == "cancelled"
        assert test_client.post(
            f"/api/v1/missions/{mission_id}/tick").status_code == 422
        assert test_client.post(
            f"/api/v1/missions/{mission_id}/cancel").status_code == 422


# -- full chain: mission -> dact -> agent -> observation -> next -----------

def test_full_step_chain_with_agent(tmp_path, monkeypatch, fakes):
    for test_client in client(tmp_path, monkeypatch):
        conversation = make_conversation(test_client)
        mission_id = test_client.post("/api/v1/missions", json={
            "conversation_id": conversation,
            "goal": "Open mijn project en kijk wat er nog moet gebeuren",
            "steps": [
                {"kind": "readout", "description": "Lees projectcontext",
                 "parameters": {"source": "project"}},
                {"kind": "desktop", "description": "Bekijk desktop",
                 "action_type": "screenshot", "parameters": {},
                 "required_capabilities": ["desktop.screen.read"]},
                {"kind": "analysis", "description": "Vat samen",
                 "parameters": {}},
            ]}).json()["mission_id"]
        test_client.post(f"/api/v1/missions/{mission_id}/approve",
                         json={"response": "YES"})
        first = test_client.post(f"/api/v1/missions/{mission_id}/tick")
        assert first.status_code == 200, first.text
        # readout done, screenshot proposed (auto-approved by policy)
        state = test_client.get(f"/api/v1/missions/{mission_id}").json()
        assert state["steps"][0]["status"] == "completed"
        action_id = state["steps"][1]["desktop_action_id"]
        assert action_id.startswith("dact-")

        # binding proof travels with the action
        fetched = test_client.get(
            f"/api/v1/desktop/actions/{action_id}").json()
        assert fetched["mission_id"] == mission_id
        assert fetched["step_id"] == state["steps"][1]["step_id"]

        # standalone agent claims and "executes" (simulated via HTTP)
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "desktop-chain-01", "hostname": "pc",
            "capabilities": ["agent:desktop", "desktop.screen.read"],
            "node_token": "chain-token-123456"})
        claimed = test_client.post("/api/v1/desktop/actions/next",
                                   json={"node_id": "desktop-chain-01",
                                         "node_token":
                                         "chain-token-123456"})
        assert claimed.json()["action_id"] == action_id
        assert claimed.json()["mission_id"] == mission_id
        test_client.post(f"/api/v1/desktop/actions/{action_id}/result",
                         json={"status": "completed",
                               "observation_reference": "obs-chain-1"})

        second = test_client.post(f"/api/v1/missions/{mission_id}/tick")
        assert second.status_code == 200, second.text
        done = test_client.get(f"/api/v1/missions/{mission_id}").json()
        assert done["status"] == "completed"
        assert done["steps"][1]["observation_reference"] == "obs-chain-1"
        assert done["steps"][1]["status"] == "completed"

        events = test_client.get(
            f"/api/v1/missions/{mission_id}/events").json()
        types = [event["event_type"] for event in events]
        assert "mission_created" in types
        assert "mission_approved" in types
        assert "step_completed" in types
        assert "observation" in types
        assert "mission_completed" in types

        thread = test_client.get(
            f"/api/v1/conversations/{conversation}").json()
        texts = [msg["content"] for msg in thread["messages"]
                 if msg["role"] == "assistant"]
        assert any("Missie voltooid" in text for text in texts)
        assert any(action_id in text for text in texts)


def test_desktop_step_waits_for_human_yes(tmp_path, monkeypatch, fakes):
    for test_client in client(tmp_path, monkeypatch):
        conversation = make_conversation(test_client)
        mission_id = test_client.post("/api/v1/missions", json={
            "conversation_id": conversation, "goal": "klik iets",
            "steps": [{"kind": "desktop", "description": "Klik",
                       "action_type": "click",
                       "parameters": {"x": 10, "y": 10},
                       "requires_approval": True}]}).json()["mission_id"]
        test_client.post(f"/api/v1/missions/{mission_id}/approve",
                         json={"response": "YES"})
        ticked = test_client.post(f"/api/v1/missions/{mission_id}/tick")
        assert ticked.json()["outcome"] == "waiting"
        state = test_client.get(f"/api/v1/missions/{mission_id}").json()
        assert state["status"] == "running"  # plan approved, step gated
        assert state["steps"][0]["status"] == "waiting_approval"
        action_id = state["steps"][0]["desktop_action_id"]
        # agent cannot claim before approval
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "desktop-wait-01", "hostname": "pc",
            "capabilities": ["agent:desktop", "desktop.mouse.click"],
            "node_token": "wait-token-123456"})
        assert test_client.post("/api/v1/desktop/actions/next", json={
            "node_id": "desktop-wait-01",
            "node_token": "wait-token-123456"}).json() is None
        # human YES unblocks; agent claims; failure stops mission safely
        test_client.post(f"/api/v1/desktop/actions/{action_id}/decision",
                         json={"response": "YES"})
        assert test_client.post("/api/v1/desktop/actions/next", json={
            "node_id": "desktop-wait-01",
            "node_token": "wait-token-123456"}).json()[
                "action_id"] == action_id
        test_client.post(f"/api/v1/desktop/actions/{action_id}/result",
                         json={"status": "failed",
                               "error": "knop niet gevonden"})
        test_client.post(f"/api/v1/missions/{mission_id}/tick")
        failed = test_client.get(f"/api/v1/missions/{mission_id}").json()
        assert failed["status"] == "failed"
        assert failed["steps"][0]["status"] == "failed"


def test_scope_violation_blocks_step(tmp_path, monkeypatch, fakes):
    import sqlite3
    for test_client in client(tmp_path, monkeypatch):
        conversation = make_conversation(test_client)
        mission_id = test_client.post("/api/v1/missions", json={
            "conversation_id": conversation, "goal": "kijk",
            "steps": [{"kind": "desktop", "description": "Kijk",
                       "action_type": "screenshot", "parameters": {}}]
        }).json()["mission_id"]
        test_client.post(f"/api/v1/missions/{mission_id}/approve",
                         json={"response": "YES"})
        test_client.post(f"/api/v1/missions/{mission_id}/tick")
        state = test_client.get(f"/api/v1/missions/{mission_id}").json()
        action_id = state["steps"][0]["desktop_action_id"]
        # attacker removes the binding: executor must block, never adopt
        db_path = os.environ["MYCELIUM_CHAT_DATABASE_PATH"]
        db = sqlite3.connect(db_path)
        db.execute("DELETE FROM action_bindings WHERE action_id=?",
                   (action_id,))
        db.commit()
        db.close()
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "desktop-scope-01", "hostname": "pc",
            "capabilities": ["agent:desktop", "desktop.screen.read"],
            "node_token": "scope-token-123456"})
        test_client.post("/api/v1/desktop/actions/next",
                         json={"node_id": "desktop-scope-01",
                               "node_token": "scope-token-123456"})
        test_client.post(f"/api/v1/desktop/actions/{action_id}/result",
                         json={"status": "completed",
                               "observation_reference": "obs-x"})
        test_client.post(f"/api/v1/missions/{mission_id}/tick")
        blocked = test_client.get(f"/api/v1/missions/{mission_id}").json()
        assert blocked["status"] == "blocked"
        assert blocked["steps"][0]["status"] == "blocked"


def test_binding_model_rejects_foreign_action():
    from coordinator.app.missions import Mission
    mission = new_mission("mission_x", "conv-1", "doel",
                          readonly_steps())
    with pytest.raises(ValueError):
        check_binding(mission, mission.steps[0].step_id, "dact-vreemd",
                      {})
    with pytest.raises(ValueError):
        check_binding(mission, "step_vreemd", "dact-x",
                      {"dact-x": ("mission_x", "step_vreemd")})


def test_max_steps_budget_blocks(tmp_path, monkeypatch, fakes):
    for test_client in client(tmp_path, monkeypatch):
        conversation = make_conversation(test_client)
        mission_id = test_client.post("/api/v1/missions", json={
            "conversation_id": conversation, "goal": "veel",
            "max_steps": 1,
            "steps": readonly_steps()}).json()["mission_id"]
        test_client.post(f"/api/v1/missions/{mission_id}/approve",
                         json={"response": "YES"})
        ticked = test_client.post(f"/api/v1/missions/{mission_id}/tick")
        assert ticked.json()["status"] == "blocked"


def test_analysis_without_model_pauses(tmp_path, monkeypatch):
    from coordinator.app.providers import ProviderUnavailable
    monkeypatch.setattr(main_mod, "_world_reader", lambda: FakeReader())
    monkeypatch.setattr(main_mod, "get_provider", lambda name=None, **k:
                        FakeProvider(fail=ProviderUnavailable("down")))
    for test_client in client(tmp_path, monkeypatch):
        conversation = make_conversation(test_client)
        mission_id = test_client.post("/api/v1/missions", json={
            "conversation_id": conversation, "goal": "analyseer",
            "steps": [{"kind": "analysis", "description": "Denk na",
                       "parameters": {}}]}).json()["mission_id"]
        test_client.post(f"/api/v1/missions/{mission_id}/approve",
                         json={"response": "YES"})
        test_client.post(f"/api/v1/missions/{mission_id}/tick")
        paused = test_client.get(f"/api/v1/missions/{mission_id}").json()
        assert paused["status"] == "paused"
        assert paused["steps"][0]["status"] == "blocked"


def test_proposal_step_never_auto_executes(tmp_path, monkeypatch, fakes):
    for test_client in client(tmp_path, monkeypatch):
        conversation = make_conversation(test_client)
        mission_id = test_client.post("/api/v1/missions", json={
            "conversation_id": conversation, "goal": "stel iets voor",
            "steps": [{"kind": "proposal",
                       "description": "Stel codewijziging voor",
                       "parameters": {}}]}).json()["mission_id"]
        test_client.post(f"/api/v1/missions/{mission_id}/approve",
                         json={"response": "YES"})
        test_client.post(f"/api/v1/missions/{mission_id}/tick")
        done = test_client.get(f"/api/v1/missions/{mission_id}").json()
        assert done["status"] == "completed"
        assert done["steps"][0]["proposal_id"].startswith("prop-")
        # no task, no action, no dispatch exists for the proposal
        assert done["steps"][0]["desktop_action_id"] == ""
        actions = test_client.get("/api/v1/desktop/actions").json()
        assert actions == []


# -- chat integration ------------------------------------------------------

def test_chat_to_mission(tmp_path, monkeypatch, fakes):
    for test_client in client(tmp_path, monkeypatch):
        conversation = make_conversation(test_client)
        assert test_client.post("/api/v1/chat/conv-bestaat-niet/missions",
                                json={"goal": "x"}).status_code == 404
        created = test_client.post(
            f"/api/v1/chat/{conversation}/missions",
            json={"goal": "Open mijn project en kijk wat er nog moet "
                          "gebeuren"})
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["conversation_id"] == conversation
        assert len(body["steps"]) == 3  # safe default template
        assert all(step["kind"] in ("readout", "analysis")
                   for step in body["steps"])
        thread = test_client.get(
            f"/api/v1/conversations/{conversation}").json()
        assert any("plan gemaakt" in msg["content"]
                   for msg in thread["messages"]
                   if msg["role"] == "assistant")


def test_suggest_is_advice_only(tmp_path, monkeypatch):
    monkeypatch.setattr(main_mod, "_world_reader", lambda: FakeReader())

    class SuggestProvider(FakeProvider):
        async def advise(self, question, records):
            from coordinator.app.ollama_advisor import AdviceResponse
            return AdviceResponse(
                question=question,
                advice="- Open het project\n- Lees de README\nruis",
                model="fake", records_used=0, sources=[])

    monkeypatch.setattr(main_mod, "get_provider",
                        lambda name=None, **k: SuggestProvider())
    for test_client in client(tmp_path, monkeypatch):
        response = test_client.post("/api/v1/missions/suggest", json={
            "goal": "bekijk project"})
        assert response.status_code == 200
        body = response.json()
        assert body["suggestions"] == [
            {"description": "Open het project"},
            {"description": "Lees de README"}]
        assert "Advies alleen" in body["note"]


# -- UI ---------------------------------------------------------------------

def test_mission_pages(tmp_path, monkeypatch, fakes):
    for test_client in client(tmp_path, monkeypatch):
        assert test_client.get("/missions").status_code == 200
        conversation = make_conversation(test_client)
        mission_id = test_client.post(
            f"/api/v1/chat/{conversation}/missions",
            json={"goal": "bekijk"}).json()["mission_id"]
        page = test_client.get(f"/missions/{mission_id}")
        assert page.status_code == 200
        assert "MISSION" in page.text and "0%" in page.text
        home = test_client.get("/")
        assert "/missions" in home.text
        chat_page = test_client.get("/chat")
        assert "Start mission" in chat_page.text
        agents = test_client.get("/agents")
        assert "/missions" in agents.text or "Agents" in agents.text


def test_web_mission_buttons(tmp_path, monkeypatch, fakes):
    for test_client in client(tmp_path, monkeypatch):
        conversation = make_conversation(test_client)
        created = test_client.post(
            "/web/missions",
            content=f"conversation_id={conversation}&goal=testmissie",
            headers={"Content-Type":
                     "application/x-www-form-urlencoded"})
        assert created.history[0].status_code == 303
        mission_id = created.history[0].headers["location"].split(
            "/")[-1]
        ticked = test_client.post(f"/web/missions/{mission_id}/tick",
                                  content="",
                                  headers={"Content-Type":
                                           "application/x-www-form-urlencoded"})
        assert ticked.history[0].status_code == 303
