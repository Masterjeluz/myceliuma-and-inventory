"""BIG48 living-runtime tests: the full game -> worker -> world chain.

Proves the acceptance chain without fakes: play session -> play
mission (quest + pending_approval mission + analysis step) ->
approve -> step-bound code task -> worker claim -> real complete ->
existing closeout closes the step -> tick completes the mission ->
quest COMPLETE -> fungi shows the completed result -> refreshed
play snapshot (no reload).

Also: session lifecycle/throttle, dispatch of analysis steps,
quest fabrication states, and every refusal gate (wrong mission,
wrong kind, pending mission, terminal step).
"""

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN = "b48-test-token-12345678"
OPERATOR = "b48-operator-key"


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b48.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b48-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", OPERATOR)
    with TestClient(main_mod.app) as test_client:
        yield test_client


def register_code_node(test_client, node_id="b48-code-01"):
    res = test_client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": "b48host", "tier": "worker",
        "capabilities": ["code.review"], "executors": ["exec:code"],
        "node_token": TOKEN})
    assert res.status_code == 201, res.text
    beat = test_client.post(f"/api/v1/nodes/{node_id}/heartbeat",
                            json={"available": True,
                                  "node_token": TOKEN})
    assert beat.status_code == 204, beat.text


def claim(test_client, node_id="b48-code-01"):
    res = test_client.post(
        f"/api/v1/tasks/claim/{node_id}?node_token={TOKEN}", json={})
    return res


def complete(test_client, task_id, node_id="b48-code-01",
             summary="review done"):
    return test_client.post(f"/api/v1/tasks/{task_id}/complete", json={
        "node_id": node_id, "success": True,
        "result": {"summary": summary, "files_changed": []}})


def test_session_lifecycle(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        created = test_client.post("/api/v1/play/session", json={})
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["session_id"].startswith("play_")
        assert body["resumed"] is False
        assert (body["x"], body["y"]) == (800.0, 500.0)
        sid = body["session_id"]

        saved = test_client.post("/api/v1/play/position", json={
            "session_id": sid, "x": 900, "y": 600,
            "zone": "Homebase"})
        assert saved.status_code == 200, saved.text
        assert saved.json()["saved"] is True

        # Immediate re-save throttles honestly (no failure).
        throttled = test_client.post("/api/v1/play/position", json={
            "session_id": sid, "x": 901, "y": 601})
        assert throttled.status_code == 200, throttled.text
        assert throttled.json()["saved"] is False
        assert throttled.json()["x"] == 900.0

        # Resume restores the stored position (refresh-safe).
        resumed = test_client.post("/api/v1/play/session",
                                   json={"session_id": sid})
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["resumed"] is True
        assert (resumed.json()["x"],
                resumed.json()["y"]) == (900.0, 600.0)

        # Unknown session 404s; bad shapes 422; coords clamp.
        missing = test_client.post("/api/v1/play/position", json={
            "session_id": "play_nope", "x": 1, "y": 1})
        assert missing.status_code == 404, missing.text
        bad = test_client.post("/api/v1/play/session",
                               json={"session_id": "!!"})
        assert bad.status_code == 422, bad.text
        no_id = test_client.post("/api/v1/play/position",
                                 json={"x": 1, "y": 1})
        assert no_id.status_code == 422, no_id.text


def test_play_mission_creates_quest_and_step(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        res = test_client.post("/api/v1/play/mission", json={
            "goal": "B48 review the loop"})
        assert res.status_code == 201, res.text
        made = res.json()
        assert made["status"] == "pending_approval"
        assert made["step_id"]
        assert made["quest_id"].startswith("qst_")

        mission = test_client.get(
            f"/api/v1/missions/{made['mission_id']}").json()
        assert mission["steps"][0]["kind"] == "analysis"
        assert mission["steps"][0]["parameters"]["goal"] == \
            "B48 review the loop"

        quests = test_client.get("/api/v1/quests?limit=20").json()
        mine = [quest for quest in quests["quests"]
                if quest["quest_id"] == made["quest_id"]]
        assert len(mine) == 1
        assert mine[0]["steps"][0]["ref"] == made["mission_id"]

        empty = test_client.post("/api/v1/play/mission",
                                 json={"goal": "   "})
        assert empty.status_code == 422, empty.text


def test_full_chain_to_fungi(tmp_path, monkeypatch):
    """session -> mission -> YES -> step task -> claim -> complete
    -> step COMPLETE -> tick -> mission completed -> quest
    COMPLETE -> fungi shows the result -> snapshot reflects it."""
    for test_client in api(tmp_path, monkeypatch):
        register_code_node(test_client)

        made = test_client.post("/api/v1/play/mission", json={
            "goal": "B48 full chain review"}).json()
        mid, sid, qid = (made["mission_id"], made["step_id"],
                         made["quest_id"])

        # Approval gate unchanged: exact YES required.
        yes = test_client.post(f"/api/v1/missions/{mid}/approve",
                               json={"response": "YES",
                                     "decided_by": "jelles"})
        assert yes.status_code == 200, yes.text
        assert yes.json()["status"] == "approved"

        # Bound task queues and marks the step dispatched.
        queued = test_client.post("/api/v1/play/code-task", json={
            "kind": "code.review",
            "goal": "B48 review the chain",
            "mission_id": mid, "step_id": sid})
        assert queued.status_code == 201, queued.text
        task_id = queued.json()["id"]
        steps = test_client.get(
            f"/api/v1/missions/{mid}/steps").json()
        assert steps[0]["status"] == "dispatched"

        # Idempotent re-queue returns the live task.
        again = test_client.post("/api/v1/play/code-task", json={
            "kind": "code.review", "goal": "B48 review again",
            "mission_id": mid, "step_id": sid})
        assert again.status_code == 201, again.text
        assert again.json()["existing"] is True
        assert again.json()["id"] == task_id

        # Existing worker claims + completes through the real path.
        claimed = claim(test_client)
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["id"] == task_id
        done = complete(test_client, task_id,
                        summary="B48 chain review done")
        assert done.status_code == 204, done.text

        # Existing closeout closed the step (no new logic).
        steps = test_client.get(
            f"/api/v1/missions/{mid}/steps").json()
        assert steps[0]["status"] == "completed"

        # Tick finishes the approved mission (existing executor).
        ticked = test_client.post(f"/api/v1/missions/{mid}/tick",
                                  json={})
        assert ticked.status_code == 200, ticked.text
        mission = test_client.get(
            f"/api/v1/missions/{mid}").json()
        assert mission["status"] == "completed"

        # Quest progress changed to COMPLETE.
        quests = test_client.get("/api/v1/quests?limit=20").json()
        mine = [quest for quest in quests["quests"]
                if quest["quest_id"] == qid][0]
        assert mine["state"] == "COMPLETED"
        assert mine["progress"] == "1/1"

        # Fungi/world shows the completed result (representation
        # only — nothing re-executable).
        from coordinator.app.world import derive_fungi_network
        net = derive_fungi_network(limit=120)
        labels = [node["label"] for node in net["nodes"]]
        assert any(str(label).startswith("✓ ")
                   and mid in str(node.get("href", ""))
                   for node, label in
                   zip(net["nodes"], labels))

        # Refreshed play snapshot reflects everything, no reload.
        snap = test_client.get("/api/v1/play/status").json()
        assert snap["tasks"]["counts"]["completed"] == 1
        assert snap["world"]["fungi_completed"] >= 1
        assert snap["world"]["fungi_total"] >= 2
        mine2 = [item for item in snap["missions"]["items"]
                 if item["id"] == mid]
        assert mine2 and mine2[0]["status"] == "completed"


def test_step_binding_refusals(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        made = test_client.post("/api/v1/play/mission", json={
            "goal": "B48 refusal checks"}).json()
        mid, sid = made["mission_id"], made["step_id"]

        # Pending mission: binding needs approval first (409).
        pending = test_client.post("/api/v1/play/code-task", json={
            "kind": "code.review", "goal": "too early",
            "mission_id": mid, "step_id": sid})
        assert pending.status_code == 409, pending.text

        test_client.post(f"/api/v1/missions/{mid}/approve",
                         json={"response": "YES",
                               "decided_by": "jelles"})

        # Only code.review binds.
        patch = test_client.post("/api/v1/play/code-task", json={
            "kind": "code.patch", "goal": "wrong kind",
            "mission_id": mid, "step_id": sid})
        assert patch.status_code == 422, patch.text

        # Unknown step refuses.
        ghost = test_client.post("/api/v1/play/code-task", json={
            "kind": "code.review", "goal": "ghost",
            "mission_id": mid, "step_id": "step_nope"})
        assert ghost.status_code == 422, ghost.text

        # Step without its mission refuses (no cross-binding).
        lonely = test_client.post("/api/v1/play/code-task", json={
            "kind": "code.review", "goal": "lonely",
            "step_id": sid})
        assert lonely.status_code == 422, lonely.text

        # Research steps never take play tasks: build one directly.
        chat = test_client.post("/api/v1/chat",
                                json={"message": "hi"}).json()
        res_mission = test_client.post("/api/v1/missions", json={
            "conversation_id": chat["conversation_id"],
            "goal": "research only",
            "steps": [{"kind": "research",
                       "description": "Zoek",
                       "parameters": {
                           "question": "wat?",
                           "source_urls": [
                               "http://127.0.0.1/x"]}}]}).json()
        res_step = res_mission["steps"][0]["step_id"]
        test_client.post(
            f"/api/v1/missions/{res_mission['mission_id']}/approve",
            json={"response": "YES", "decided_by": "jelles"})
        wrong_kind = test_client.post("/api/v1/play/code-task", json={
            "kind": "code.review", "goal": "wrong step kind",
            "mission_id": res_mission["mission_id"],
            "step_id": res_step})
        assert wrong_kind.status_code == 422, wrong_kind.text


def test_analysis_dispatch_queues_code_review(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        chat = test_client.post("/api/v1/chat",
                                json={"message": "hi"}).json()
        res = test_client.post("/api/v1/missions", json={
            "conversation_id": chat["conversation_id"],
            "goal": "dispatch analysis",
            "steps": [{"kind": "analysis",
                       "description": "Review X",
                       "parameters": {"goal": "Review X"}}]})
        assert res.status_code == 201, res.text
        mid = res.json()["mission_id"]
        step_id = res.json()["steps"][0]["step_id"]
        test_client.post(f"/api/v1/missions/{mid}/approve",
                         json={"response": "YES",
                               "decided_by": "jelles"})
        dispatched = test_client.post(
            f"/api/v1/missions/{mid}/dispatch",
            json={"step_id": step_id})
        assert dispatched.status_code == 200, dispatched.text
        assert dispatched.json()["task_ids"]
        tasks = test_client.get("/api/v1/tasks").json()
        mine = [task for task in tasks
                if task["id"] in dispatched.json()["task_ids"]]
        assert len(mine) == 1
        assert mine[0]["kind"] == "code.review"
        assert mine[0]["payload"]["mission_step_id"] == step_id

        # Idempotent second dispatch returns the same task.
        again = test_client.post(
            f"/api/v1/missions/{mid}/dispatch",
            json={"step_id": step_id})
        assert again.json()["task_ids"] == \
            dispatched.json()["task_ids"]

        # Analysis without goal never dispatches.
        res2 = test_client.post("/api/v1/missions", json={
            "conversation_id": chat["conversation_id"],
            "goal": "goalless",
            "steps": [{"kind": "analysis",
                       "description": "Review Y",
                       "parameters": {}}]})
        mid2 = res2.json()["mission_id"]
        test_client.post(f"/api/v1/missions/{mid2}/approve",
                         json={"response": "YES",
                               "decided_by": "jelles"})
        refused = test_client.post(
            f"/api/v1/missions/{mid2}/dispatch",
            json={"step_id": res2.json()["steps"][0]["step_id"]})
        assert refused.status_code == 422, refused.text


def test_quest_fabrication_states(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        plain = test_client.post("/api/v1/quests", json={
            "title": "plain quest",
            "steps": [{"key": "s", "label": "Record",
                       "kind": "note", "ref": ""}]})
        assert plain.status_code == 201, plain.text
        assert test_client.get(
            f"/api/v1/quests/{plain.json()['quest_id']}").json()[
                "fabrication"] == []

        fab = test_client.post("/api/v1/quests", json={
            "title": "print a bracket",
            "steps": [{"key": "s", "label": "Print bracket",
                       "kind": "note", "ref": ""}]})
        assert fab.status_code == 201, fab.text
        chain = test_client.get(
            f"/api/v1/quests/{fab.json()['quest_id']}").json()[
                "fabrication"]
        states = {row["step"]: row["state"] for row in chain}
        assert states["slicing"] == "SIMULATED"
        assert states["approval"] == "BLOCKED"
        assert states["verification"] == "REAL"


def test_play_page_has_session_and_actions(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        page = test_client.get("/play")
        assert page.status_code == 200, page.text
        for marker in ("mycelium_play_session",
                       "/api/v1/play/session",
                       "/api/v1/play/position",
                       "/api/v1/play/mission",
                       "refreshAfterAction",
                       "refreshJourneyData",
                       "fungi-total"):
            assert marker in page.text, marker
