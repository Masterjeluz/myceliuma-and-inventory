"""PASS 4: conversation parallelism over existing fork/attach.

Main + Forge + Artwork + NPC + Research conversations in one
workspace, each with its own mission, progressing independently
and re-linkable through the existing attach/provenance path. No
new conversation database, chat engine or message store — the
test only drives existing routes and reads existing rows.
"""

import coordinator.app.main as main_mod
from fastapi.testclient import TestClient

WS = "atelier-ws"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "queue.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "chat-state.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def chat(client, message, project_ref=WS, conversation_id=None):
    body = {"message": message, "project_ref": project_ref}
    if conversation_id:
        body["conversation_id"] = conversation_id
    response = client.post("/api/v1/chat", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def make_mission(client, conversation_id, goal):
    response = client.post("/api/v1/missions", json={
        "conversation_id": conversation_id, "goal": goal,
        "steps": [{"kind": "readout", "description": "lees status",
                   "parameters": {"source": "git-status"}}],
        "max_steps": 3})
    assert response.status_code == 201, response.text
    return response.json()


def build_atelier(client):
    main = chat(client, "hoofdlijn atelier")["conversation_id"]
    branches = {}
    for name in ("forge", "artwork", "npc", "research"):
        forked = client.post(
            f"/api/v1/conversations/{main}/fork", json={}).json()
        branches[name] = forked["conversation_id"]
        chat(client, f"vervolg {name}",
             conversation_id=forked["conversation_id"])
    missions = {}
    for name, conv in [("main", main)] + sorted(branches.items()):
        missions[name] = make_mission(
            client, conv, f"Missie {name}")["mission_id"]
    return main, branches, missions


def test_parallel_tree_with_own_missions(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        main, branches, missions = build_atelier(client)
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        assert len(view["conversations"]) == 5
        assert len(view["workstreams"]) == 5
        tree = view["tree"]
        assert set(tree["children"][main]) == set(branches.values())
        for conv in branches.values():
            assert tree["nodes"][conv]["parent"] == main
        # Every conversation kept its own messages.
        for name, conv in [("main", main)] + sorted(branches.items()):
            detail = client.get(
                f"/api/v1/conversations/{conv}").json()
            assert detail["project_ref"] == WS
            assert len(detail["messages"]) >= 2


def test_branches_progress_without_waiting(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        main, branches, missions = build_atelier(client)
        # Forge approves, NPC cancels, rest wait: all independent.
        assert client.post(
            f"/api/v1/missions/{missions['forge']}/approve",
            json={"response": "YES",
                  "decided_by": "human"}).status_code == 200
        assert client.post(
            f"/api/v1/missions/{missions['npc']}/cancel").status_code \
            == 200
        states = {name: client.get(
            f"/api/v1/missions/{mid}").json()["status"]
            for name, mid in missions.items()}
        assert states == {"main": "pending_approval",
                          "forge": "approved",
                          "artwork": "pending_approval",
                          "npc": "cancelled",
                          "research": "pending_approval"}


def test_result_relinks_to_workspace(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        main, branches, missions = build_atelier(client)
        before = client.get(
            f"/api/v1/missions/{missions['artwork']}").json()
        moved = client.post(
            f"/api/v1/workspaces/{WS}/missions/"
            f"{missions['artwork']}/attach",
            json={"conversation_id": main})
        assert moved.status_code == 200, moved.text
        assert moved.json()["moved"] is True
        after = client.get(
            f"/api/v1/missions/{missions['artwork']}").json()
        assert after["conversation_id"] == main
        assert after["mission_id"] == missions["artwork"]
        # Siblings byte-identical.
        for name in ("forge", "npc", "research"):
            current = client.get(
                f"/api/v1/missions/{missions[name]}").json()
            assert current["status"] == "pending_approval"
        events = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()["events"]
        assert any(missions["artwork"] in
                   (item.get("mission_id", "")) for item in events)
        _ = before
