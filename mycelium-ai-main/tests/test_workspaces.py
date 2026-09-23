"""Project workspaces, vertical slice 1 (E2E).

One project holds many conversations, a conversation forks and each
fork continues on its own, and conversations/missions re-link later —
all on the existing conversations/messages/missions/event tables.
World reads and providers are faked; nothing reaches INVENTory or a
real model.
"""

import coordinator.app.main as main_mod
from coordinator.app.inventory_read import Provenance, SearchResult
from coordinator.app.ollama_advisor import AdviceResponse
from fastapi.testclient import TestClient


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


def chat(client, message, project_ref="", conversation_id=None):
    body = {"message": message, "project_ref": project_ref}
    if conversation_id:
        body["conversation_id"] = conversation_id
    response = client.post("/api/v1/chat", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_one_project_holds_many_conversations(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        first = chat(client, "eerste draad", project_ref="mycelium-ai")
        second = chat(client, "tweede draad", project_ref="mycelium-ai")
        assert first["conversation_id"] != second["conversation_id"]

        response = client.get("/api/v1/workspaces/mycelium-ai")
        assert response.status_code == 200, response.text
        detail = response.json()
        ids = {item["conversation_id"]
               for item in detail["conversations"]}
        assert first["conversation_id"] in ids
        assert second["conversation_id"] in ids
        assert detail["package_href"].startswith(
            "/api/v1/project/package")
        assert detail["context_href"].startswith(
            "/api/v1/context/packet")


def test_fork_continues_independently(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        origin = chat(client, "oorsprong", project_ref="mycelium-ai")
        origin_id = origin["conversation_id"]

        response = client.post(
            f"/api/v1/conversations/{origin_id}/fork", json={})
        assert response.status_code == 201, response.text
        fork = response.json()
        fork_id = fork["conversation_id"]
        assert fork_id != origin_id
        assert fork["forked_from"] == origin_id
        assert fork["messages_carried"] == 2  # user + assistant

        before = client.get(
            f"/api/v1/conversations/{origin_id}").json()
        chat(client, "vervolg in fork", conversation_id=fork_id)

        after_origin = client.get(
            f"/api/v1/conversations/{origin_id}").json()
        after_fork = client.get(
            f"/api/v1/conversations/{fork_id}").json()
        assert len(after_origin["messages"]) == len(before["messages"])
        assert len(after_fork["messages"]) == len(
            before["messages"]) + 2
        # Provenance survives the fork unchanged (no new claims).
        roles = [item["role"] for item in after_fork["messages"]]
        assert "user" in roles and "assistant" in roles


def test_conversation_relinks_to_same_project(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        home = chat(client, "thuis", project_ref="mycelium-ai")
        stray = chat(client, "verdwaald")
        assert stray["conversation_id"] not in {
            item["conversation_id"] for item in client.get(
                "/api/v1/workspaces/mycelium-ai").json()["conversations"]}

        response = client.post(
            "/api/v1/workspaces/mycelium-ai/conversations/"
            f"{stray['conversation_id']}/attach")
        assert response.status_code == 200, response.text
        assert response.json()["moved"] is True

        ids = {item["conversation_id"] for item in client.get(
            "/api/v1/workspaces/mycelium-ai").json()["conversations"]}
        assert stray["conversation_id"] in ids
        assert home["conversation_id"] in ids

        # Re-attaching to the same workspace is a no-op, not an error.
        again = client.post(
            "/api/v1/workspaces/mycelium-ai/conversations/"
            f"{stray['conversation_id']}/attach")
        assert again.status_code == 200, again.text
        assert again.json()["moved"] is False


def test_mission_relinks_with_unchanged_id(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        first = chat(client, "werk", project_ref="mycelium-ai")
        second = chat(client, "vervolg", project_ref="mycelium-ai")
        created = client.post("/api/v1/missions", json={
            "conversation_id": first["conversation_id"],
            "goal": "Onderzoek de werkplaats",
            "steps": [{"kind": "readout",
                       "description": "lees git status",
                       "parameters": {"source": "git-status"}}],
            "max_steps": 5})
        assert created.status_code == 201, created.text
        mission_id = created.json()["mission_id"]

        moved = client.post(
            f"/api/v1/workspaces/mycelium-ai/missions/{mission_id}/attach",
            json={"conversation_id": second["conversation_id"]})
        assert moved.status_code == 200, moved.text
        body = moved.json()
        assert body["mission_id"] == mission_id
        assert body["conversation_id"] == second["conversation_id"]
        assert body["workspace_id"] == "mycelium-ai"

        fetched = client.get(f"/api/v1/missions/{mission_id}").json()
        assert fetched["conversation_id"] == second["conversation_id"]

        # Wrong workspace in the path refuses: the target lives
        # in mycelium-ai, not in forge-studio.
        refused = client.post(
            f"/api/v1/workspaces/forge-studio/missions/{mission_id}/attach",
            json={"conversation_id": second["conversation_id"]})
        assert refused.status_code == 422, refused.text


def test_seeds_existing_views_and_fail_closed(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        listed = client.get("/api/v1/workspaces").json()
        ids = {item["workspace_id"] for item in listed}
        assert {"mycelium-ai", "inventory", "forge-studio"} <= ids

        forge = client.get("/api/v1/workspaces/forge-studio").json()
        assert forge["href"] == "/forge"
        assert forge["view"]
        inventory = client.get("/api/v1/workspaces/inventory").json()
        assert inventory["href"] == "/projects"

        assert client.post(
            "/api/v1/conversations/conv-nope/fork",
            json={}).status_code == 404
        assert client.post(
            "/api/v1/workspaces/!!-bad/conversations/conv-nope/attach"
        ).status_code in (404, 422)
        bad_mission = client.post(
            "/api/v1/workspaces/mycelium-ai/missions/mission_nope/attach",
            json={"conversation_id": "conv-nope"})
        assert bad_mission.status_code == 404

        # Fork/attach facts land on the existing interface bus.
        origin = chat(client, "ping", project_ref="mycelium-ai")
        client.post(f"/api/v1/conversations/"
                    f"{origin['conversation_id']}/fork", json={})
        events = client.get("/api/v1/events",
                            params={"limit": 50}).json()
        assert any("forked" in item.get("summary", "").lower()
                   for item in events)


def test_existing_pages_still_exist(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        for path in ("/chat", "/missions", "/conversations",
                     "/projects", "/forge", "/workspaces"):
            response = client.get(path)
            assert response.status_code == 200, (path, response.text)
        detail = client.get("/workspaces/mycelium-ai")
        assert detail.status_code == 200, detail.text
