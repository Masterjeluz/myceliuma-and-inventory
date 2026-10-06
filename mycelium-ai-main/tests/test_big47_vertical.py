"""BIG47 living-workshop vertical tests: game -> queue -> worker -> event.

Covers the largest honest digital loop: a /play-originated bounded
code.* task queues through the EXISTING task system, an EXISTING
code-capable worker claims it, completes it with a REAL result, and
the completion lands in the task record + bus events + play snapshot.

No mocks of the queue, no fake completions: register/heartbeat/
claim/complete all run against the real routes. The worker side is
the real claim+complete contract (the OpenCode subprocess itself is
not spawned here; execute_code_task is covered by code_worker tests).
"""

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN = "b47-test-token-12345678"
OPERATOR = "b47-operator-key"


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b47.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b47-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", OPERATOR)
    with TestClient(main_mod.app) as test_client:
        yield test_client


def register_code_node(test_client, node_id="b47-code-01"):
    res = test_client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": "b47host", "tier": "worker",
        "capabilities": ["code.review", "code.patch", "code.test"],
        "executors": ["exec:code"],
        "node_token": TOKEN})
    assert res.status_code == 201, res.text
    beat = test_client.post(f"/api/v1/nodes/{node_id}/heartbeat",
                            json={"available": True,
                                  "node_token": TOKEN})
    assert beat.status_code == 204, beat.text


def make_mission(test_client, goal="Review the workshop loop"):
    chat = test_client.post("/api/v1/chat", json={"message": "hi"})
    assert chat.status_code == 200, chat.text
    res = test_client.post("/api/v1/missions", json={
        "conversation_id": chat.json()["conversation_id"],
        "goal": goal,
        "steps": [{"kind": "readout", "description": "Lees",
                   "parameters": {"source": "project"}}]})
    assert res.status_code == 201, res.text
    return res.json()["mission_id"]


def test_play_status_snapshot_empty(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        res = test_client.get("/api/v1/play/status")
        assert res.status_code == 200, res.text
        snap = res.json()
        for key in ("tasks", "nodes", "automation", "missions",
                    "events", "liveness", "fabrication"):
            assert key in snap, key
        assert snap["tasks"]["counts"]["queued"] == 0
        assert snap["nodes"]["nodes"] == []
        assert snap["nodes"]["code_capable"] == 0
        assert "ollama" in snap["liveness"]
        assert "inventory" in snap["liveness"]
        steps = {row["step"]: row["state"]
                 for row in snap["fabrication"]}
        assert steps["slicing"] == "SIMULATED"
        assert steps["approval"] == "BLOCKED"
        assert steps["execution"] == "UNAVAILABLE"
        assert steps["verification"] == "REAL"
        assert steps["event"] == "REAL"


def test_play_code_task_validation(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        before = test_client.get("/api/v1/play/status").json()
        # Non-code kinds never queue from the game.
        bad = test_client.post("/api/v1/play/code-task", json={
            "kind": "shell.exec", "goal": "do anything"})
        assert bad.status_code == 422, bad.text
        # code.exec is code.* but not a bounded play kind.
        bad2 = test_client.post("/api/v1/play/code-task", json={
            "kind": "code.exec", "goal": "do anything"})
        assert bad2.status_code == 422, bad2.text
        # Empty goal refuses.
        bad3 = test_client.post("/api/v1/play/code-task", json={
            "kind": "code.review", "goal": "   "})
        assert bad3.status_code == 422, bad3.text
        # Unknown mission refuses (traceability must be real).
        bad4 = test_client.post("/api/v1/play/code-task", json={
            "kind": "code.review", "goal": "review",
            "mission_id": "mission_nope"})
        assert bad4.status_code == 422, bad4.text
        after = test_client.get("/api/v1/play/status").json()
        assert (after["tasks"]["counts"]["queued"]
                == before["tasks"]["counts"]["queued"])


def test_play_code_task_end_to_end(tmp_path, monkeypatch):
    """game intent -> queued -> claimed -> completed -> event -> snapshot."""
    for test_client in api(tmp_path, monkeypatch):
        register_code_node(test_client)
        mission_id = make_mission(test_client)

        # 1. Game queues bounded work (no execution here).
        created = test_client.post("/api/v1/play/code-task", json={
            "kind": "code.review",
            "goal": "Review the quest-mission link in world quests",
            "mission_id": mission_id})
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]
        assert created.json()["status"] == "queued"

        # Snapshot shows QUEUED + a code-capable worker waiting.
        snap = test_client.get("/api/v1/play/status").json()
        assert snap["tasks"]["counts"]["queued"] == 1
        assert snap["nodes"]["code_capable"] == 1
        queued = [row for row in snap["tasks"]["open"]
                  if row["id"] == task_id]
        assert queued and queued[0]["stage"] == "QUEUED"

        # 2. Existing worker claims through the existing gate.
        claimed = test_client.post(
            f"/api/v1/tasks/claim/b47-code-01?node_token={TOKEN}")
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["id"] == task_id
        assert claimed.json()["mission_id"] == mission_id

        # 3. Worker reports a REAL result (bounded review output).
        done = test_client.post(
            f"/api/v1/tasks/{task_id}/complete", json={
                "node_id": "b47-code-01", "success": True,
                "result": {"summary": "quest link reads mission "
                                     "status honestly",
                           "files_changed": [],
                           "opencode_output": "review only"}})
        assert done.status_code == 204, done.text

        # 4. Read back: completed record + event + snapshot.
        rows = test_client.get("/api/v1/tasks").json()
        mine = [row for row in rows if row["id"] == task_id]
        assert len(mine) == 1
        assert mine[0]["status"] == "completed"
        assert mine[0]["result"]["result"]["summary"].startswith(
            "quest link")

        events = test_client.get("/api/v1/events?limit=50").json()
        kinds = [event.get("event_type", "") for event in events]
        assert "task.queued" in kinds
        assert "task.completed" in kinds

        snap2 = test_client.get("/api/v1/play/status").json()
        assert snap2["tasks"]["counts"]["completed"] == 1
        mine2 = [row for row in snap2["tasks"]["open"]
                 if row["id"] == task_id]
        assert mine2
        assert mine2[0]["stage"].startswith("RESULT")


def test_play_code_task_without_mission(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        register_code_node(test_client, node_id="b47-code-02")
        created = test_client.post("/api/v1/play/code-task", json={
            "kind": "code.test", "goal": "Run the focused suite"})
        assert created.status_code == 201, created.text
        assert created.json()["mission_id"] is None
        claimed = test_client.post(
            "/api/v1/tasks/claim/b47-code-02?node_token={}".format(
                TOKEN))
        assert claimed.status_code == 200, claimed.text


def test_play_page_serves_workshop_view(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        page = test_client.get("/play")
        assert page.status_code == 200, page.text
        assert "Workshop" in page.text
        assert "/api/v1/play/status" in page.text
        assert "/api/v1/play/code-task" in page.text
