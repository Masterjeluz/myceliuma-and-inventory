"""PASS 6: Forge multi-workstream readiness via the cockpit.

One workspace holds a Forge conversation (fabricate mission),
an artwork conversation, a research conversation and a
write-bound mission. The cockpit links, tracks and gates each
through existing routes only: fabricate tick, write
propose/approve/execute/verify, research report. No cross-write,
no merge, no Forge or engine changes — readiness proof.

INVENTory HTTP is faked with httpx.MockTransport (established
pattern for the write path).
"""

import httpx
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

WS = "forge-ws"


class FakeStore:
    def __init__(self):
        self.objects: dict = {}
        self.counter = 0

    def handler(self, request):
        import json
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/objects":
            body = json.loads(request.content.decode())
            self.counter += 1
            entity_id = f"obj_p6_{self.counter:03d}"
            record = {"id": entity_id, "name": body["name"],
                      "description": body.get("description", ""),
                      "quantity": body.get("quantity", 1),
                      "provenance": body.get("provenance", {}),
                      "created_at": "2026-01-01T00:00:00+00:00",
                      "updated_at": "2026-01-01T00:00:00+00:00"}
            self.objects[entity_id] = record
            return httpx.Response(201, json=record)
        if path.startswith("/api/v1/objects/"):
            record = self.objects.get(path.rsplit("/", 1)[-1])
            if record is None:
                return httpx.Response(404, json={"detail": "no"})
            return httpx.Response(200, json=record)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"detail": "no route"})


def make_client(tmp_path, monkeypatch):
    store = FakeStore()
    transport = httpx.MockTransport(store.handler)
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "queue.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "chat-state.db"))
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "fab"))
    from coordinator.app.inventory_read import InventoryReader
    from coordinator.app.inventory_writes import InventoryWriter
    monkeypatch.setattr(main_mod, "_world_reader",
                        lambda: InventoryReader(transport=transport))
    monkeypatch.setattr(main_mod, "InventoryWriter",
                        lambda *a, **k: InventoryWriter(
                            transport=transport))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def chat(client, message, conversation_id=None):
    body = {"message": message, "project_ref": WS}
    if conversation_id:
        body["conversation_id"] = conversation_id
    response = client.post("/api/v1/chat", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_forge_artwork_research_side_by_side(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        forge_conv = chat(client, "Maak deze bracket 5mm langer")[
            "conversation_id"]
        art_conv = chat(client, "Maak achtergrond voor workshop")[
            "conversation_id"]
        res_conv = chat(client, "Zoek geschikte stepper motors")[
            "conversation_id"]

        fabricate = client.post("/api/v1/missions", json={
            "conversation_id": forge_conv,
            "goal": "Forge bracket 5mm langer",
            "steps": [{"kind": "fabricate",
                       "description": "genereer bracket",
                       "parameters": {"description": "bracket 5mm",
                                      "method": "procedural-test"}}],
            "max_steps": 3})
        assert fabricate.status_code == 201, fabricate.text
        fabricate_id = fabricate.json()["mission_id"]
        assert client.post(
            f"/api/v1/missions/{fabricate_id}/approve",
            json={"response": "YES",
                  "decided_by": "human"}).status_code == 200
        assert client.post(
            f"/api/v1/missions/{fabricate_id}/tick").status_code \
            == 200

        artwork = client.post("/api/v1/missions", json={
            "conversation_id": art_conv,
            "goal": "Ontwerp NPC",
            "steps": [{"kind": "analysis",
                       "description": "schets NPC-concept",
                       "parameters": {}}],
            "max_steps": 3})
        assert artwork.status_code == 201, artwork.text

        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        assert len(view["workstreams"]) == 2
        assert len(view["forge"]["missions"]) == 1
        assert view["forge"]["missions"][0]["mission_id"] == \
            fabricate_id
        by_conv = {stream["conversation_id"]: stream
                   for stream in view["workstreams"]}
        assert by_conv[forge_conv]["open"]["forge"] == "/forge"
        assert by_conv[art_conv]["open"]["forge"] == ""
        # Research conversation stays usable beside Forge work.
        continued = chat(client, "nog een motor-optie",
                         conversation_id=res_conv)
        assert continued["conversation_id"] == res_conv
        page = client.get(f"/workspaces/{WS}").text
        assert "Forge bracket 5mm langer" in page
        assert "Ontwerp NPC" in page


def test_write_bound_mission_tracks_through_cockpit(
        tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        forge_conv = chat(client, "Bracket voorstel")[
            "conversation_id"]
        proposed = client.post("/api/v1/writes/inventory", json={
            "proposal_id": "wrt-p6", "mutation": "create",
            "entity_type": "object",
            "fields": {"name": "P6 bracket", "quantity": 1}})
        assert proposed.status_code == 201, proposed.text
        mission = client.post("/api/v1/missions", json={
            "conversation_id": forge_conv,
            "goal": "Bracket vastleggen",
            "steps": [{"kind": "write",
                       "description": "maak bracket-object aan",
                       "parameters": {"proposal_id": "wrt-p6"}}],
            "max_steps": 3})
        assert mission.status_code == 201, mission.text
        mission_id = mission.json()["mission_id"]

        # Pending write visible before any approval.
        pending = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()["pending"]
        assert "wrt-p6" in {item["label"]
                            for item in pending["writes"]}
        page = client.get(f"/workspaces/{WS}").text
        assert "PENDING HUMAN ACTIONS" in page
        assert "wrt-p6" in page

        # Existing gates only: write YES, then mission YES + tick.
        assert client.post("/api/v1/writes/wrt-p6/approve",
                           json={"response": "YES",
                                 "decided_by": "human"}
                           ).status_code == 200
        assert client.post(f"/api/v1/missions/{mission_id}/approve",
                           json={"response": "YES",
                                 "decided_by": "human"}
                           ).status_code == 200
        ticked = client.post(f"/api/v1/missions/{mission_id}/tick")
        assert ticked.status_code == 200, ticked.text
        finished = client.get(
            f"/api/v1/missions/{mission_id}").json()
        assert finished["steps"][0]["status"] == "completed"
        verified = client.post(
            "/api/v1/writes/wrt-p6/verify").json()
        assert verified["verification"]["outcome"] == "passed"
        view = client.get(
            f"/api/v1/workspaces/{WS}/workstreams").json()
        stream = {item["mission_id"]: item
                  for item in view["workstreams"]}[mission_id]
        assert stream["greenlight"] == "afgerond"
