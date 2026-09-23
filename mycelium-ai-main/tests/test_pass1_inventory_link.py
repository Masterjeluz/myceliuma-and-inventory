"""PASS 1: workspace <-> INVENTory project linking (read-only).

Linkage comes from existing rows only: the workspace id itself
when it IS a proj_ id, proj_ ids in mission context_records, and
proj_ ids in research run linked_entities. Resolution uses the
existing single-GET bridge with provenance intact. No writes,
no new tables, no name-similarity guessing.

INVENTory HTTP is faked with httpx.MockTransport (established
pattern); no real INVENTory server, no real model.
"""

import httpx

import coordinator.app.main as main_mod
from coordinator.app.inventory_read import InventoryReader
from coordinator.app.ollama_advisor import AdviceResponse
from fastapi.testclient import TestClient

PROJECTS = {
    "proj_cafe01": {
        "id": "proj_cafe01", "name": "Camper verbouwen",
        "description": "camper ombouwen", "status": "active",
        "provenance": {"source_type": "user-created",
                       "creator_id": "jelles",
                       "human_verified": True},
    },
    "proj_tuin": {
        "id": "proj_tuin", "name": "Moestuin",
        "description": "voedsel verbouwen", "status": "planned",
        "provenance": {"source_type": "user-created",
                       "creator_id": "jelles",
                       "human_verified": False},
    },
}


def inventory_handler(request):
    path = request.url.path
    if path == "/api/v1/projects":
        return httpx.Response(200, json=list(PROJECTS.values()))
    for pid, payload in PROJECTS.items():
        if path == f"/api/v1/projects/{pid}":
            return httpx.Response(200, json=payload)
    if path.startswith("/api/v1/projects/"):
        return httpx.Response(404, json={"detail": "not found"})
    if path.startswith("/api/v1/"):
        return httpx.Response(200, json=[])
    return httpx.Response(404, json={"detail": "not found"})


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
    reader = InventoryReader(
        transport=httpx.MockTransport(inventory_handler))
    monkeypatch.setattr(main_mod, "_world_reader", lambda: reader)
    monkeypatch.setattr(main_mod, "get_provider",
                        lambda name=None, **k: FakeProvider())
    with TestClient(main_mod.app) as test_client:
        yield test_client


def chat(client, message, project_ref):
    response = client.post("/api/v1/chat", json={
        "message": message, "project_ref": project_ref})
    assert response.status_code == 200, response.text
    return response.json()


def test_a_workspace_without_project_links_nothing(tmp_path,
                                                   monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        chat(client, "hallo daar", "plain-ws")
        body = client.get(
            "/api/v1/workspaces/plain-ws/inventory-projects").json()
        assert body["projects"] == []
        assert body["candidate_refs"] == 0
        assert body["unresolved"] == 0
        page = client.get("/workspaces/plain-ws").text
        assert "Geen aantoonbaar gekoppeld" in page


def test_b_workspace_id_matching_proj_resolves(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        chat(client, "camper draad", "proj_cafe01")
        body = client.get(
            "/api/v1/workspaces/proj_cafe01/inventory-projects"
        ).json()
        assert body["candidate_refs"] == 1
        assert len(body["projects"]) == 1
        project = body["projects"][0]
        assert project["entity_id"] == "proj_cafe01"
        assert project["title"] == "Camper verbouwen"
        assert project["via"] == "workspace-id"
        page = client.get("/workspaces/proj_cafe01").text
        assert "Camper verbouwen" in page


def test_c_multiple_projects_via_rows(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        conv = chat(client, "tuin draad", "garden-ws")[
            "conversation_id"]
        mission = client.post("/api/v1/missions", json={
            "conversation_id": conv, "goal": "Tuin plannen",
            "steps": [{"kind": "readout",
                       "description": "lees status",
                       "parameters": {"source": "git-status"}}],
            "max_steps": 3})
        assert mission.status_code == 201, mission.text
        mission_id = mission.json()["mission_id"]
        # Existing store, arranged directly: mission context
        # references a proj_ id (as chat/research context does).
        from coordinator.app.missions import load_mission, save_mission
        stored = load_mission(mission_id)
        save_mission(stored.model_copy(update={
            "context_records": [{
                "entity_type": "project",
                "entity_id": "proj_tuin",
                "title": "Moestuin"}]}))
        # Research run whose question names a proj_ id: the real
        # engine links it on execute (link_entities).
        run = client.post("/api/v1/research/runs", json={
            "question": "Wat heeft proj_cafe01 nodig?",
            "project_ref": "garden-ws",
            "provider": "test",
            "test_pages": {"camper-nodig": [
                "Camper isolatie",
                "De camper heeft isolatie nodig voor de winter."]},
            "max_sources": 3,
            "execute": True}).json()
        assert run["status"] == "completed", run
        body = client.get(
            "/api/v1/workspaces/garden-ws/inventory-projects").json()
        by_id = {item["entity_id"]: item
                 for item in body["projects"]}
        assert by_id["proj_tuin"]["via"] == "mission-context"
        assert by_id["proj_cafe01"]["via"] == "research-link"
        assert body["unresolved"] == 0


def test_d_provenance_stays_intact(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        chat(client, "camper", "proj_cafe01")
        chat(client, "tuin linker", "proj_tuin")
        camper = client.get(
            "/api/v1/workspaces/proj_cafe01/inventory-projects"
        ).json()["projects"][0]
        assert camper["provenance"] == {
            "source_type": "user-created", "human_verified": True,
            "creator_id": "jelles"}
        tuin = client.get(
            "/api/v1/workspaces/proj_tuin/inventory-projects"
        ).json()["projects"][0]
        assert tuin["provenance"]["human_verified"] is False
        assert tuin["provenance"]["source_type"] == "user-created"


def test_e_cockpit_keeps_working(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        chat(client, "draad", "plain-ws")
        assert client.get("/workspaces/plain-ws").status_code == 200
        view = client.get(
            "/api/v1/workspaces/plain-ws/workstreams").json()
        assert view["workspace_id"] == "plain-ws"
        page = client.get("/workspaces/plain-ws").text
        for marker in ("ACTIVE WORKSTREAMS", "CONVERSATIONS",
                       "PENDING HUMAN ACTIONS", "ACTIVITY",
                       "SHARED RESOURCES"):
            assert marker in page


def test_f_resolution_writes_nothing(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        chat(client, "camper", "proj_cafe01")
        from coordinator.app.database import (
            chat_connection as _chat_conn,
        )
        from coordinator.app.database import connection as _conn
        with _conn() as db:
            tasks_before = db.execute(
                "SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
        with _chat_conn() as db:
            counts_before = {
                table: db.execute(
                    f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
                for table in ("conversations", "messages", "missions",
                              "conversation_events",
                              "interface_events", "write_proposals")}
        client.get("/api/v1/workspaces/proj_cafe01/inventory-projects")
        client.get("/workspaces/proj_cafe01")
        client.get("/api/v1/workspaces/proj_cafe01/workstreams")
        with _conn() as db:
            tasks_after = db.execute(
                "SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
        with _chat_conn() as db:
            counts_after = {
                table: db.execute(
                    f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
                for table in counts_before}
        assert tasks_after == tasks_before
        assert counts_after == counts_before
