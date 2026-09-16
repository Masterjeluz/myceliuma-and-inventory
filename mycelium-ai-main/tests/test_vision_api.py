"""Vision API tests (BIG #6).

Ingest, availability, recent observations, VLM analysis,
vision proposals into the BIG #5 write chain, streams, chat
observation context, graph overlay and camera_observe missions.
INVENTory HTTP is faked; media is synthetic and local.
"""

import json
import os

import httpx
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app import vision_ingest as ingest_mod
from coordinator.app.vision_ingest import SyntheticTestAdapter
from coordinator.app.vision_provider import TestVisionProvider


class FakeStore:
    def __init__(self):
        self.objects: dict = {}
        self.files: dict = {}
        self.counter = 0

    def _record(self, prefix, body, extra):
        self.counter += 1
        entity_id = f"{prefix}_api{self.counter:03d}"
        record = {"id": entity_id, **extra,
                  "provenance": body.get("provenance", {}),
                  "created_at": "2026-01-01T00:00:00+00:00",
                  "updated_at": "2026-01-01T00:00:00+00:00"}
        return entity_id, record

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/objects":
            body = json.loads(request.content.decode())
            entity_id, record = self._record(
                "obj", body, {"name": body["name"],
                              "description": body.get("description", ""),
                              "quantity": body.get("quantity", 1)})
            self.objects[entity_id] = record
            return httpx.Response(201, json=record)
        if request.method == "POST" and path == "/api/v1/files":
            body = json.loads(request.content.decode())
            entity_id, record = self._record(
                "file", body, {"name": body["name"],
                               "file_kind": body.get("file_kind",
                                                     "other"),
                               "mime_type": body.get("mime_type", ""),
                               "sha256": body.get("sha256", "0" * 64),
                               "size_bytes": body.get("size_bytes", 0),
                               "description": body.get("description", ""),
                               "status": body.get("status", "unknown"),
                               "metadata": body.get("metadata", {})})
            self.files[entity_id] = record
            return httpx.Response(201, json=record)
        if path.startswith("/api/v1/objects/"):
            entity_id = path.rsplit("/", 1)[-1]
            record = self.objects.get(entity_id)
            if record is None:
                return httpx.Response(404, json={})
            return httpx.Response(200, json=record)
        if path.startswith("/api/v1/files/"):
            entity_id = path.rsplit("/", 1)[-1]
            record = self.files.get(entity_id)
            if record is None:
                return httpx.Response(404, json={})
            return httpx.Response(200, json=record)
        if path == "/api/v1/graph":
            return httpx.Response(200, json={
                "entity_id": "obj_abc", "depth": 1,
                "nodes": [], "edges": []})
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={})


def make_client(tmp_path, monkeypatch):
    store = FakeStore()
    transport = httpx.MockTransport(store.handler)
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "v.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "v-chat.db"))
    from coordinator.app.inventory_read import InventoryReader
    from coordinator.app.inventory_writes import InventoryWriter
    monkeypatch.setattr(main_mod, "_world_reader",
                        lambda: InventoryReader(transport=transport))
    monkeypatch.setattr(main_mod, "InventoryWriter",
                        lambda *a, **k: InventoryWriter(
                            transport=transport))
    monkeypatch.setattr(main_mod, "get_vision_provider",
                        lambda name=None, **k: TestVisionProvider(
                            labels=["moer"]))
    ingest_mod.clear_adapters()
    with TestClient(main_mod.app) as test_client:
        yield test_client
    ingest_mod.clear_adapters()


def register_camera(test_client, device_id="cam-vis1",
                    kinds=("snapshot",), source="manual"):
    response = test_client.post("/api/v1/cameras/register", json={
        "device_id": device_id, "name": "Viscam",
        "kinds": list(kinds), "source": source})
    assert response.status_code == 201, response.text
    ingest_mod.register_adapter(device_id, SyntheticTestAdapter())
    return device_id


def test_ingest_and_availability(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        device_id = register_camera(test_client)
        availability = test_client.get(
            f"/api/v1/cameras/{device_id}/availability")
        assert availability.status_code == 200, availability.text
        assert availability.json()["capturable"] is True
        ingested = test_client.post(
            f"/api/v1/cameras/{device_id}/ingest")
        assert ingested.status_code == 201, ingested.text
        body = ingested.json()
        assert body["test_origin"] is True
        assert body["observation"]["provenance"][
            "human_verified"] is False
        assert body["media"]["size_bytes"] > 0
        assert body["file_payload"]["file_kind"] == "image"
        recent = test_client.get("/api/v1/observations/recent")
        assert recent.status_code == 200
        assert any(item["entity_id"] == body["observation"][
            "observation_id"] for item in recent.json())


def test_ingest_without_adapter_is_409(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        response = test_client.post("/api/v1/cameras/register", json={
            "device_id": "cam-bare", "name": "Bare",
            "kinds": ["snapshot"], "source": "manual"})
        assert response.status_code == 201
        ingested = test_client.post("/api/v1/cameras/cam-bare/ingest")
        assert ingested.status_code == 409
        availability = test_client.get(
            "/api/v1/cameras/cam-bare/availability")
        assert availability.json()["capturable"] is False


def test_vision_analyze_and_propose_chain(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        device_id = register_camera(test_client)
        obs_id = test_client.post(
            f"/api/v1/cameras/{device_id}/ingest").json()[
                "observation"]["observation_id"]
        analyzed = test_client.post("/api/v1/vision/analyze", json={
            "observation_id": obs_id, "question": "Wat zie je?"})
        assert analyzed.status_code == 201, analyzed.text
        analysis_id = analyzed.json()["analysis"]["analysis_id"]
        assert analyzed.json()["candidates"][0]["label"] == "moer"
        # Propose object: inert until approval.
        proposed = test_client.post("/api/v1/vision/propose", json={
            "analysis_id": analysis_id, "kind": "object",
            "proposal_id": "wrt-visapi1"})
        assert proposed.status_code == 201, proposed.text
        assert proposed.json()["status"] == "proposed"
        assert proposed.json()["proposal"]["payload"]["fields"][
            "name"] == "moer"
        # Full BIG #5 chain: approve -> execute -> verify.
        assert test_client.post(
            "/api/v1/writes/wrt-visapi1/approve",
            json={"response": "YES"}).status_code == 200
        executed = test_client.post(
            "/api/v1/writes/wrt-visapi1/execute")
        assert executed.status_code == 200, executed.text
        assert executed.json()["status"] == "executed"
        verified = test_client.post(
            "/api/v1/writes/wrt-visapi1/verify")
        assert verified.json()["verification"]["outcome"] == "passed"
        # Propose file: inert media registration.
        file_proposed = test_client.post(
            "/api/v1/vision/propose", json={
                "analysis_id": analysis_id, "kind": "file",
                "proposal_id": "wrt-visapi2"})
        assert file_proposed.status_code == 201, file_proposed.text
        assert file_proposed.json()["proposal"]["payload"][
            "entity_type"] == "file"


def test_vision_propose_empty_analysis_refused(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        device_id = register_camera(test_client)
        obs_id = test_client.post(
            f"/api/v1/cameras/{device_id}/ingest").json()[
                "observation"]["observation_id"]
        monkeypatch.setattr(
            main_mod, "get_vision_provider",
            lambda name=None, **k: TestVisionProvider(labels=[]))
        analyzed = test_client.post("/api/v1/vision/analyze", json={
            "observation_id": obs_id})
        assert analyzed.status_code == 201
        refused = test_client.post("/api/v1/vision/propose", json={
            "analysis_id": analyzed.json()["analysis"]["analysis_id"],
            "kind": "object"})
        assert refused.status_code == 422


def test_streams_are_bounded_and_explicit(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        register_camera(test_client, device_id="cam-stream1",
                        kinds=("snapshot", "stream"))
        started = test_client.post("/api/v1/streams/start", json={
            "device_id": "cam-stream1", "max_frames": 2,
            "max_seconds": 60})
        assert started.status_code == 201, started.text
        session_id = started.json()["session_id"]
        assert test_client.post(
            f"/api/v1/streams/{session_id}/tick").status_code == 200
        assert test_client.post(
            f"/api/v1/streams/{session_id}/tick").status_code == 200
        over = test_client.post(
            f"/api/v1/streams/{session_id}/tick").json()
        assert over["status"] == "stopped"
        stopped = test_client.post(
            f"/api/v1/streams/{session_id}/stop")
        assert stopped.json()["status"] == "stopped"
        listed = test_client.get("/api/v1/streams")
        assert any(entry["session_id"] == session_id
                   for entry in listed.json())
        # No stream capability -> refused.
        register_camera(test_client, device_id="cam-nostream")
        refused = test_client.post("/api/v1/streams/start", json={
            "device_id": "cam-nostream"})
        assert refused.status_code == 422


def test_chat_observation_context_opt_in(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        device_id = register_camera(test_client)
        obs_id = test_client.post(
            f"/api/v1/cameras/{device_id}/ingest").json()[
                "observation"]["observation_id"]

        from coordinator.app.ollama_advisor import AdviceResponse

        class FakeProvider:
            async def advise(self, question, records):
                return AdviceResponse(
                    question=question, advice="advies", model="fake",
                    records_used=len(records), sources=[])

        monkeypatch.setattr(main_mod, "get_provider",
                            lambda name=None, **k: FakeProvider())
        eye = [item for item in
               test_client.post("/api/v1/chat", json={
                   "message": "Wat heb je gezien?",
                   "observation_ids": [obs_id]}).json()["sources"]
               if item["entity_id"] == obs_id]
        assert len(eye) == 1
        unknown = test_client.post("/api/v1/chat", json={
            "message": "x", "observation_ids": ["obs-bestaat-niet"]})
        assert unknown.status_code == 422


def test_graph_observation_overlay(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        device_id = register_camera(test_client)
        obs_id = test_client.post(
            f"/api/v1/cameras/{device_id}/ingest").json()[
                "observation"]["observation_id"]
        graph = test_client.get("/api/v1/graph", params={
            "entity_id": "obj_abc", "include_observations": True})
        # INVENTory graph is faked; the observation overlay must ride
        # along without crashing the projection.
        assert graph.status_code == 200, graph.text
        node_ids = [node["id"] for node in graph.json()["nodes"]]
        assert obs_id in node_ids
        edge = [edge for edge in graph.json()["edges"]
                if edge["to"] == obs_id]
        assert edge and edge[0]["predicate"] == "captured"


def test_camera_observe_mission_step(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        device_id = register_camera(test_client)
        created = test_client.post("/api/v1/missions", json={
            "conversation_id": "conv-vis1",
            "goal": "Kijk met de camera",
            "steps": [{"kind": "camera_observe",
                       "description": "Neem een foto",
                       "parameters": {"device_id": device_id}}]})
        assert created.status_code == 201, created.text
        mission_id = created.json()["mission_id"]
        assert test_client.post(
            f"/api/v1/missions/{mission_id}/approve",
            json={"response": "YES"}).status_code == 200
        ticked = test_client.post(
            f"/api/v1/missions/{mission_id}/tick")
        assert ticked.status_code == 200, ticked.text
        assert ticked.json()["status"] == "completed"
        mission = test_client.get(
            f"/api/v1/missions/{mission_id}").json()
        assert mission["steps"][0]["status"] == "completed"
        assert mission["steps"][0]["observation_reference"] != ""


def test_camera_observe_without_adapter_blocks(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        response = test_client.post("/api/v1/cameras/register", json={
            "device_id": "cam-blocked", "name": "Blocked",
            "kinds": ["snapshot"], "source": "manual"})
        assert response.status_code == 201
        created = test_client.post("/api/v1/missions", json={
            "conversation_id": "conv-vis2",
            "goal": "Kijk",
            "steps": [{"kind": "camera_observe",
                       "description": "Neem een foto",
                       "parameters": {"device_id": "cam-blocked"}}]})
        mission_id = created.json()["mission_id"]
        test_client.post(f"/api/v1/missions/{mission_id}/approve",
                         json={"response": "YES"})
        ticked = test_client.post(
            f"/api/v1/missions/{mission_id}/tick")
        assert ticked.json()["status"] == "blocked"


def test_cameras_page_shows_availability(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        register_camera(test_client)
        page = test_client.get("/cameras")
        assert page.status_code == 200
        assert "availability" in page.text
        assert "latest:" in page.text


def test_project_package_carries_observations(tmp_path, monkeypatch):
    from coordinator.app.project_context import ProjectContext
    from coordinator.app.project_package import (
        build_project_package,
        summarize_for_chat,
    )
    from coordinator.app.inventory_read import Provenance
    project = ProjectContext(
        project_id="prj-v", name="Visproject",
        repository=str(tmp_path), working_directory=str(tmp_path),
        provenance=Provenance(source_type="user-created",
                              creator_id="human",
                              human_verified=True))
    package = build_project_package(
        project,
        observations=[{
            "observation_id": "obs-p1", "device_id": "cam-vis1",
            "media_ref": "cam-abc.bmp",
            "created_at": "2026-01-01T00:00:00+00:00",
            "analyses": [{"labels": ["moer"]}],
            "provenance": {"source_type": "sensor-observed",
                           "human_verified": False}}])
    assert len(package["observations"]) == 1
    assert package["observations"][0]["vision_labels"] == ["moer"]
    assert "obs-p1" in summarize_for_chat(package)


def test_worldgraph_overlay_unit():
    import asyncio
    from coordinator.app.inventory_read import GraphResponse
    from coordinator.app.worldgraph import build_world_graph

    class Reader:
        async def graph(self, entity_id, depth=1):
            return GraphResponse(entity_id=entity_id, depth=depth,
                                 nodes=[], edges=[])

    graph = asyncio.run(build_world_graph(
        Reader(), "obj_abc", 1,
        observations=[{"observation_id": "obs-g1",
                       "device_id": "cam-g1",
                       "media_ref": "cam-g.bmp",
                       "created_at": "2026-01-01",
                       "provenance": {
                           "source_type": "sensor-observed",
                           "human_verified": False}}]))
    node_ids = [node["id"] for node in graph["nodes"]]
    assert "obs-g1" in node_ids
    assert any(edge["predicate"] == "captured"
               for edge in graph["edges"])
