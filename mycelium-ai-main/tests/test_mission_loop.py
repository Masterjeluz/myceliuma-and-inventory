"""BIG #21 tests: autonomous mission loop.

The loop drives approved work to the next gate and stops
with an actionable reason. It never approves, never
invents steps, never executes beyond the executor.
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "loop.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "loop-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def make_conversation(client):
    response = client.post("/api/v1/chat",
                           json={"message": "hi"})
    assert response.status_code == 200, response.text
    return response.json()["conversation_id"]


def make_mission(client, conversation, goal, steps):
    response = client.post("/api/v1/missions", json={
        "conversation_id": conversation, "goal": goal,
        "steps": steps})
    assert response.status_code == 201, response.text
    return response.json()["mission_id"]


def approve_plan(client, mission_id):
    response = client.post(
        f"/api/v1/missions/{mission_id}/approve",
        json={"response": "YES", "decided_by": "tester"})
    assert response.status_code == 200, response.text


def run(client, mission_id, max_rounds=10):
    response = client.post(
        f"/api/v1/missions/{mission_id}/run",
        json={"max_rounds": max_rounds})
    assert response.status_code == 200, response.text
    return response.json()


def readout_steps():
    return [{"kind": "readout", "description": "Read project",
             "parameters": {"source": "project"}}]


def test_loop_runs_readout_mission_to_completion(tmp_path,
                                                 monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        conversation = make_conversation(client)
        mission_id = make_mission(
            client, conversation, "survey the project",
            readout_steps())
        approve_plan(client, mission_id)
        report = run(client, mission_id)
        assert report["outcome"] == "completed"
        assert report["status"] == "completed"
        assert report["rounds"] >= 1
        memory_id = report.get("memory_id", "")
        assert memory_id.startswith("mem_")
        stored = client.get(
            f"/api/v1/memory/{memory_id}").json()
        assert stored["memory_type"] == "episodic"
        assert stored["truth"] == "observed"
        assert stored["provenance"]["human_verified"] is False
        assert mission_id in stored["entity_refs"]
        # Re-running a terminal mission only observes it.
        again = run(client, mission_id)
        assert again["stop_reason"] == "already_terminal"
        assert again.get("memory_id", "") == memory_id


def test_loop_stops_for_plan_approval(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        conversation = make_conversation(client)
        mission_id = make_mission(
            client, conversation, "unapproved plan",
            readout_steps())
        report = run(client, mission_id)
        assert report["outcome"] == "stopped"
        assert report["stop_reason"] == "needs_plan_approval"
        assert "approve" in report["action"]
        state = client.get(
            f"/api/v1/missions/{mission_id}").json()
        assert state["status"] == "pending_approval"


def test_loop_stops_for_desktop_approval_then_continues(
        tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        conversation = make_conversation(client)
        mission_id = make_mission(
            client, conversation, "click something",
            [{"kind": "desktop", "description": "Click",
              "action_type": "click",
              "parameters": {"x": 10, "y": 10},
              "requires_approval": True}])
        approve_plan(client, mission_id)
        stopped = run(client, mission_id)
        assert stopped["outcome"] == "stopped"
        assert stopped["stop_reason"] == \
            "needs_desktop_approval"
        action_id = stopped["action"]["action_id"]
        assert action_id
        # Human approves through the existing endpoint.
        assert client.post(
            f"/api/v1/desktop/actions/{action_id}/decision",
            json={"response": "YES",
                  "decided_by": "tester"}).status_code == 200
        # A node acts through the existing claim/act/report
        # chain (simulated here over HTTP).
        assert client.post("/api/v1/nodes/register", json={
            "node_id": "loop-agent-01", "hostname": "pc",
            "capabilities": ["agent:desktop",
                             "desktop.mouse.click"],
            "node_token": "loop-token-1234567890"}
        ).status_code == 201
        claimed = client.post("/api/v1/desktop/actions/next",
                              json={
                                  "node_id": "loop-agent-01",
                                  "node_token":
                                  "loop-token-1234567890"}).json()
        assert claimed is not None
        assert client.post(
            f"/api/v1/desktop/actions/{action_id}/result",
            json={"status": "completed",
                  "observation_reference": "obs-loop-1"}
        ).status_code in (200, 201, 204)
        done = run(client, mission_id)
        assert done["outcome"] == "completed", done
        assert done.get("memory_id", "").startswith("mem_")


def test_loop_drafts_proposal_without_executing(tmp_path,
                                                monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        conversation = make_conversation(client)
        mission_id = make_mission(
            client, conversation, "propose something",
            [{"kind": "proposal",
              "description": "Draft a change"}])
        approve_plan(client, mission_id)
        report = run(client, mission_id)
        # Drafting is data, not execution: the mission may
        # complete while the proposal itself still needs the
        # separate /approvals flow. Nothing auto-executes.
        assert report["outcome"] == "completed", report
        state = client.get(
            f"/api/v1/missions/{mission_id}").json()
        assert state["status"] == "completed"
        assert state["steps"][0]["status"] == "completed"


def test_loop_never_starts_physical_print(tmp_path,
                                          monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        conversation = make_conversation(client)
        mission_id = make_mission(
            client, conversation, "print the bracket",
            [{"kind": "physical_print",
              "description": "Print it",
              "parameters": {"proposal_id": "wrt-loop-1"}}])
        approve_plan(client, mission_id)
        report = run(client, mission_id)
        assert report["outcome"] == "stopped"
        assert report["stop_reason"] in (
            "needs_write_or_physical_approval", "waiting",
            "mission_blocked", "mission_failed")
        state = client.get(
            f"/api/v1/missions/{mission_id}").json()
        assert state["status"] != "completed"


def test_loop_bounds_and_validation(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.post("/api/v1/missions/nope/run",
                           json={"max_rounds": 10}
                           ).status_code == 422
        conversation = make_conversation(client)
        mission_id = make_mission(
            client, conversation, "bounded",
            readout_steps())
        approve_plan(client, mission_id)
        assert client.post(
            f"/api/v1/missions/{mission_id}/run",
            json={"max_rounds": 99}).status_code == 422
        assert client.post(
            f"/api/v1/missions/{mission_id}/run",
            json={"max_rounds": 0}).status_code == 422
        report = run(client, mission_id, max_rounds=1)
        assert report["rounds"] <= 1


def test_loop_has_no_shell_or_network_surface():
    import pathlib
    source = (pathlib.Path(__file__).resolve().parent.parent /
              "coordinator" / "app" / "mission_loop.py"
              ).read_text(encoding="utf-8")
    for token in ("subprocess", "os.system", "eval(",
                  "import sqlite3", "https://", "httpx",
                  "requests", "0.0.0.0"):
        assert token not in source, f"mission_loop.py: {token}"
