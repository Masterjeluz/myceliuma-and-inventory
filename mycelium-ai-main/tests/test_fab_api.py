"""Fabrication API tests (BIG #7).

End-to-end over coordinator routes with faked INVENTory:
generate -> validate -> slice -> safety -> propose -> approve ->
execute (simulated) -> telemetry verify -> camera verify.
Plus missions, printers, assess, fabrication page and graph.
"""

import json
import os

import httpx
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.printer3d import (
    SimulatedPrinterAdapter,
    clear_printers,
    new_printer,
)
from coordinator.app.printer3d import (
    register_printer as register_device,
)


class FakeStore:
    def __init__(self):
        self.entities: dict = {}
        self.counter = 0

    def _record(self, prefix, body, extra):
        self.counter += 1
        entity_id = f"{prefix}_fab{self.counter:03d}"
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
            self.entities[entity_id] = record
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
            self.entities[entity_id] = record
            return httpx.Response(201, json=record)
        if path.startswith("/api/v1/objects/") or path.startswith(
                "/api/v1/files/"):
            entity_id = path.rsplit("/", 1)[-1]
            record = self.entities.get(entity_id)
            if record is None:
                return httpx.Response(404, json={})
            return httpx.Response(200, json=record)
        if path == "/api/v1/graph":
            return httpx.Response(200, json={
                "entity_id": "obj_x", "depth": 1,
                "nodes": [], "edges": []})
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={})


def make_client(tmp_path, monkeypatch):
    store = FakeStore()
    transport = httpx.MockTransport(store.handler)
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "f.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "f-chat.db"))
    from coordinator.app.inventory_read import InventoryReader
    from coordinator.app.inventory_writes import InventoryWriter
    monkeypatch.setattr(main_mod, "_world_reader",
                        lambda: InventoryReader(transport=transport))
    monkeypatch.setattr(main_mod, "InventoryWriter",
                        lambda *a, **k: InventoryWriter(
                            transport=transport))
    clear_printers()
    with TestClient(main_mod.app) as test_client:
        yield test_client
    clear_printers()


def register_test_printer(test_client, printer_id="prt-fab1"):
    response = test_client.post("/api/v1/printers/register", json={
        "printer_id": printer_id, "name": "Fabprinter",
        "capabilities": ["printer.status", "printer.start",
                         "printer.cancel"]})
    assert response.status_code == 201, response.text
    register_device(
        new_printer(printer_id, "Fabprinter",
                    ["printer.status", "printer.start",
                     "printer.cancel"]),
        SimulatedPrinterAdapter())
    return printer_id


def test_full_physical_chain(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        printer_id = register_test_printer(test_client)
        # 1. Generate + validate + printability.
        generated = test_client.post("/api/v1/fab/generate", json={
            "description": "testkubus voor smoke",
            "generator": "procedural-test"})
        assert generated.status_code == 201, generated.text
        body = generated.json()
        assert body["validation"]["verdict"] == "valid"
        assert body["printability"]["verdict"] == "printable"
        fabrication_id = body["fabrication"]["fabrication_id"]
        # 2. Slice + safety.
        sliced = test_client.post("/api/v1/fab/slice", json={
            "artifact_ref": body["generation"]["artifact_ref"],
            "profile": "draft-pla", "printer_id": printer_id})
        assert sliced.status_code == 201, sliced.text
        assert sliced.json()["safety"]["verdict"] == "safe"
        gcode = sliced.json()["slice"]
        # 3. Physical proposal (inert).
        proposed = test_client.post("/api/v1/prints/propose", json={
            "proposal_id": "wrt-fab1", "printer_id": printer_id,
            "gcode_ref": gcode["gcode_ref"],
            "gcode_sha256": gcode["sha256"],
            "profile": "draft-pla"})
        assert proposed.status_code == 201, proposed.text
        assert proposed.json()["status"] == "proposed"
        assert proposed.json()["safety"]["verdict"] == "safe"
        # 4. Execute before approval refuses.
        assert test_client.post(
            "/api/v1/writes/wrt-fab1/execute").status_code == 409
        # 5. Physical YES -> execute (simulated).
        assert test_client.post(
            "/api/v1/writes/wrt-fab1/approve",
            json={"response": "YES"}).status_code == 200
        executed = test_client.post(
            "/api/v1/writes/wrt-fab1/execute")
        assert executed.status_code == 200, executed.text
        assert executed.json()["status"] == "executed"
        # 6. Telemetry half.
        verified = test_client.post(
            "/api/v1/writes/wrt-fab1/verify")
        assert verified.json()["verification"]["outcome"] == "passed"
        # 7. Camera half needs an observation; unknown refuses.
        combined = test_client.post(
            "/api/v1/writes/wrt-fab1/verify-print",
            params={"observation_id": "obs-missing"})
        assert combined.status_code == 404
        # 8. Fabrication records + graph overlay ride along.
        records = test_client.get(
            "/api/v1/fabrication/records").json()
        assert any(record["fabrication_id"] == fabrication_id
                   for record in records)
        graph = test_client.get("/api/v1/graph", params={
            "entity_id": "obj_x", "include_fabrication": True,
            "fabrication_id": fabrication_id})
        assert graph.status_code == 200, graph.text


def test_verify_print_full_both_halves(tmp_path, monkeypatch):
    import coordinator.app.main as main_module
    for test_client in make_client(tmp_path, monkeypatch):
        printer_id = register_test_printer(test_client)
        mesh = test_client.post("/api/v1/fab/generate", json={
            "description": "x"}).json()
        gcode = test_client.post("/api/v1/fab/slice", json={
            "artifact_ref": mesh["generation"]["artifact_ref"],
            "profile": "draft-pla",
            "printer_id": printer_id}).json()["slice"]
        test_client.post("/api/v1/prints/propose", json={
            "proposal_id": "wrt-fab2", "printer_id": printer_id,
            "gcode_ref": gcode["gcode_ref"],
            "gcode_sha256": gcode["sha256"],
            "profile": "draft-pla"})
        test_client.post("/api/v1/writes/wrt-fab2/approve",
                         json={"response": "YES"})
        test_client.post("/api/v1/writes/wrt-fab2/execute")
        # Fake a stored observation for the camera half.
        from coordinator.app.cameras import new_observation
        observation = new_observation(
            "obs-fab1", "cam-fab1", "snapshot",
            media_ref="", width=64, height=48)
        from coordinator.app.cameras import save_observation
        save_observation(observation)
        combined = test_client.post(
            "/api/v1/writes/wrt-fab2/verify-print",
            params={"observation_id": "obs-fab1"})
        assert combined.status_code == 200, combined.text
        verification = combined.json()["verification"]
        # No local media file -> camera half fails -> not verified.
        assert verification["outcome"] == "failed"
        assert verification["observed"]["verdict"] == "not_verified"
        assert "media file missing" in verification["note"] or \
            "camera=failed" in verification["note"]
        _ = main_module


def test_propose_needs_matching_hash(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        printer_id = register_test_printer(test_client)
        mesh = test_client.post("/api/v1/fab/generate", json={
            "description": "x"}).json()
        gcode = test_client.post("/api/v1/fab/slice", json={
            "artifact_ref": mesh["generation"]["artifact_ref"],
            "profile": "draft-pla",
            "printer_id": printer_id}).json()["slice"]
        refused = test_client.post("/api/v1/prints/propose", json={
            "printer_id": printer_id,
            "gcode_ref": gcode["gcode_ref"],
            "gcode_sha256": "f" * 64, "profile": "draft-pla"})
        assert refused.status_code == 422


def test_unknown_printer_and_profile_refused(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        mesh = test_client.post("/api/v1/fab/generate", json={
            "description": "x"}).json()
        refused = test_client.post("/api/v1/fab/slice", json={
            "artifact_ref": mesh["generation"]["artifact_ref"],
            "profile": "turbo-abs", "printer_id": "prt-fab1"})
        assert refused.status_code == 422
        missing = test_client.post("/api/v1/prints/propose", json={
            "printer_id": "prt-missing",
            "gcode_ref": "fab-test-print.gcode",
            "gcode_sha256": "0" * 64, "profile": "draft-pla"})
        assert missing.status_code == 404


def test_assess_endpoint_advises(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        mesh = test_client.post("/api/v1/fab/generate", json={
            "description": "x"}).json()
        assessed = test_client.post(
            "/api/v1/fab/assess",
            params={"mesh_ref": mesh["generation"]["artifact_ref"]})
        assert assessed.status_code == 200
        assert assessed.json()["assessment"]["verdict"] == "printable"
        assert "slice" in assessed.json()["next_step"]
        empty = test_client.post("/api/v1/fab/assess", params={})
        assert empty.status_code == 422
        guided = test_client.post(
            "/api/v1/fab/assess",
            params={"description": "een dobbelsteen"})
        assert "generate" in guided.json()["next_step"]


def test_printer_routes_and_cancel(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        printer_id = register_test_printer(test_client)
        listed = test_client.get("/api/v1/printers").json()
        assert any(entry["printer_id"] == printer_id
                   for entry in listed)
        single = test_client.get(
            f"/api/v1/printers/{printer_id}").json()
        assert single["adapter"] == "simulated-test"
        assert "printer.start" in single["adapter_capabilities"]
        assert "emergency stop" in single["estop_note"]
        assert test_client.get(
            "/api/v1/printers/prt-missing").status_code == 404
        cancelled = test_client.post("/api/v1/prints/cancel", json={
            "job_id": "pjob-zzz"}).json()
        assert cancelled["job_id"] == "pjob-zzz"
        assert "emergency stop" in cancelled["estop_note"]


def test_fabrication_mission_steps(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        printer_id = register_test_printer(test_client)
        mesh = test_client.post("/api/v1/fab/generate", json={
            "description": "x"}).json()
        gcode = test_client.post("/api/v1/fab/slice", json={
            "artifact_ref": mesh["generation"]["artifact_ref"],
            "profile": "draft-pla",
            "printer_id": printer_id}).json()["slice"]
        test_client.post("/api/v1/prints/propose", json={
            "proposal_id": "wrt-fabm", "printer_id": printer_id,
            "gcode_ref": gcode["gcode_ref"],
            "gcode_sha256": gcode["sha256"],
            "profile": "draft-pla"})
        test_client.post("/api/v1/writes/wrt-fabm/approve",
                         json={"response": "YES"})
        created = test_client.post("/api/v1/missions", json={
            "conversation_id": "conv-fab1",
            "goal": "Print de testkubus",
            "steps": [
                {"kind": "fabricate",
                 "description": "Genereer testkubus",
                 "parameters": {"description": "testkubus"}},
                {"kind": "slice",
                 "description": "Slice de kubus",
                 "parameters": {
                     "artifact_ref": mesh["generation"][
                         "artifact_ref"],
                     "profile": "draft-pla",
                     "printer_id": printer_id}},
                {"kind": "physical_print",
                 "description": "Print na fysieke approval",
                 "parameters": {"proposal_id": "wrt-fabm"}}]})
        assert created.status_code == 201, created.text
        mission_id = created.json()["mission_id"]
        test_client.post(f"/api/v1/missions/{mission_id}/approve",
                         json={"response": "YES"})
        ticked = test_client.post(
            f"/api/v1/missions/{mission_id}/tick")
        assert ticked.status_code == 200, ticked.text
        mission = test_client.get(
            f"/api/v1/missions/{mission_id}").json()
        assert mission["status"] == "completed"
        kinds = [step["kind"] for step in mission["steps"]]
        assert kinds == ["fabricate", "slice", "physical_print"]
        assert all(step["status"] == "completed"
                   for step in mission["steps"])
        # Physical step completed but never auto-verified.
        assert "NIET" in mission["steps"][2]["result_text"]


def test_fabrication_mission_without_runners_blocks(tmp_path,
                                                    monkeypatch):
    from coordinator.app.mission_executor import (
        ExecutorDeps,
        MissionExecutor,
    )
    import asyncio

    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "fm.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "fm-chat.db"))
    from coordinator.app.missions import (
        approve_mission,
        new_mission,
        save_mission,
    )
    mission = new_mission(
        "mission_fabblock", "conv-x", "Print iets",
        [{"kind": "physical_print",
          "description": "Print",
          "parameters": {"proposal_id": "wrt-x"}}])
    mission = approve_mission(mission, "YES")
    mission = mission.model_copy(update={"status": "running"})
    save_mission(mission)

    async def _advise(question, records):
        raise AssertionError("no advisor")

    async def _search(query):
        return []

    executor = MissionExecutor(ExecutorDeps(
        propose_desktop=lambda *a: (_ for _ in ()).throw(
            AssertionError("no desktop")),
        load_desktop=lambda action_id: None,
        post_message=lambda *a: "msg-1",
        advise=_advise, inventory_search=_search,
        git_read=lambda source: {}, project_read=lambda: {}))
    summary = asyncio.run(executor.tick(mission.mission_id))
    assert summary["status"] == "blocked"


def test_fabrication_page(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        register_test_printer(test_client)
        test_client.post("/api/v1/fab/generate", json={
            "description": "x"})
        page = test_client.get("/fabrication")
        assert page.status_code == 200
        assert "Fabrication" in page.text
        assert "fysieke approval" in page.text
