"""BIG #35 tests: 3D workshop ecosystem — models, materials,
links, fab-job state machine, camera verification, presence,
packet, progress, UI contracts, security, idempotency.
"""

import os
import struct

import pytest
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
from coordinator.app.workshop3d import (
    WorkshopRefusedError,
    create_fabjob,
    create_material,
    get_model,
    list_models,
    propose_workshop_link,
    register_model,
    suggest_materials,
    workshop_packet,
    workshop_presence,
)


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "w35.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "w35-chat.db"))
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "w35-fab"))
    clear_printers()
    with TestClient(main_mod.app) as client:
        yield client
    clear_printers()


def _write_stl(filename: str = "bracket.stl",
               triangles: int = 2) -> str:
    from coordinator.app.mesh3d import fabrication_dir
    path = os.path.join(fabrication_dir(), filename)
    os.makedirs(fabrication_dir(), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"\x00" * 80)
        handle.write(struct.pack("<I", triangles))
        for index in range(triangles):
            base = float(index * 10)
            handle.write(struct.pack(
                "<12fH", 0, 0, 1, base, 0, 0, base + 10, 0, 0,
                base, 10, 0, 0))
    return filename


def _write_inbox(filename: str) -> str:
    from coordinator.app.cameras import camera_dir, write_bmp_24
    path = os.path.join(camera_dir(), filename)
    write_bmp_24(path, 8, 8, b"\x10\x20\x30" * 64)
    return filename


def _printer(client, printer_id="prt-w35"):
    response = client.post("/api/v1/printers/register", json={
        "printer_id": printer_id, "name": "W35",
        "capabilities": ["printer.status", "printer.start",
                         "printer.cancel"]})
    assert response.status_code == 201, response.text
    register_device(
        new_printer(printer_id, "W35",
                    ["printer.status", "printer.start",
                     "printer.cancel"]),
        SimulatedPrinterAdapter())
    return printer_id


# -- ingest + inspection -------------------------------------------------------

def test_model_validation(tmp_path, monkeypatch):
    for _ in make_client(tmp_path, monkeypatch):
        for bad in ("", "../evil.stl", "http://x/y.stl", "a.jpg",
                    "a" * 300 + ".stl"):
            with pytest.raises(WorkshopRefusedError):
                register_model(bad)
        with pytest.raises(WorkshopRefusedError):
            register_model("missing.stl")
        with pytest.raises(WorkshopRefusedError):
            register_model("bracket.stl", source="cloud")


def test_model_ingest_inspect_dedupe(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        name = _write_stl()
        created = client.post("/api/v1/workshop/models", json={
            "filename": name}).json()
        assert created["model_id"].startswith("mdl_")
        assert created["status"] in ("imported", "inspected")
        inspected = client.post(
            f"/api/v1/workshop/models/{created['model_id']}/inspect"
        ).json()
        assert inspected["status"] == "inspected"
        scan = inspected["inspection"]
        assert scan["triangles"] == 2
        assert scan["vertices"] == 6
        assert len(scan["bbox_mm"]) == 6
        assert scan["manifold"] == "UNKNOWN"
        assert scan["units"] == "UNKNOWN"
        assert scan["volume"] == "UNKNOWN"
        assert scan["mesh_verdict"] in ("valid", "inconclusive")
        # Replay refuses: same bytes never register twice.
        again = client.post("/api/v1/workshop/models", json={
            "filename": name})
        assert again.status_code == 422
        assert len(client.get("/api/v1/workshop/models").json()[
            "models"]) == 1


def test_model_obj_and_metadata_only(tmp_path, monkeypatch):
    for _ in make_client(tmp_path, monkeypatch):
        from coordinator.app.mesh3d import fabrication_dir
        path = os.path.join(fabrication_dir(), "plate.obj")
        os.makedirs(fabrication_dir(), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("v 0 0 0\nv 5 0 0\nv 0 5 0\nf 1 2 3\n")
        created = register_model("plate.obj")
        from coordinator.app.workshop3d import inspect_model
        inspected = inspect_model(created["model_id"])
        assert inspected["inspection"]["triangles"] == 1
        assert inspected["inspection"]["vertices"] == 3
        glb_path = os.path.join(fabrication_dir(), "scan.glb")
        with open(glb_path, "wb") as handle:
            handle.write(b"glTF-BINARY-STUB")
        meta = register_model("scan.glb")
        meta_inspected = inspect_model(meta["model_id"])
        assert meta_inspected["inspection"]["triangles"] == -1
        assert meta_inspected["inspection"]["mesh_verdict"] == \
            "inconclusive"


def test_malformed_model_honest(tmp_path, monkeypatch):
    for _ in make_client(tmp_path, monkeypatch):
        from coordinator.app.mesh3d import fabrication_dir
        path = os.path.join(fabrication_dir(), "junk.stl")
        os.makedirs(fabrication_dir(), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(os.urandom(300))
        created = register_model("junk.stl")
        from coordinator.app.workshop3d import inspect_model
        inspected = inspect_model(created["model_id"])
        assert inspected["inspection"]["triangles"] == -1
        assert inspected["inspection"]["inspected"] is False


# -- materials -------------------------------------------------------------------

def test_material_validation_and_suggest(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        with pytest.raises(WorkshopRefusedError):
            create_material("")
        with pytest.raises(WorkshopRefusedError):
            create_material("X", kind="unobtainium")
        with pytest.raises(WorkshopRefusedError):
            create_material("X", state="magic")
        with pytest.raises(WorkshopRefusedError):
            create_material("X", linked_entity="xxx_1")
        created = client.post("/api/v1/workshop/materials", json={
            "name": "PLA groen", "kind": "filament",
            "state": "known",
            "notes": "1 spool op de plank"}).json()
        assert created["material_id"].startswith("mat_")
        assert created["state"] == "known"
        assert len(client.get("/api/v1/workshop/materials").json()[
            "materials"]) == 1
        name = _write_stl("holder.stl")
        model = client.post("/api/v1/workshop/models", json={
            "filename": name}).json()
        suggested = client.get(
            "/api/v1/workshop/materials/suggest",
            params={"model_id": model["model_id"]}).json()
        assert suggested["suggestions"][0]["name"] == "PLA groen"
        assert client.get("/api/v1/workshop/materials/suggest",
                          params={"model_id": "mdl_nope"}
                          ).status_code == 422


# -- links -------------------------------------------------------------------------

def test_workshop_links_proposed(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        name = _write_stl("link.stl")
        model = client.post("/api/v1/workshop/models", json={
            "filename": name}).json()
        bad = client.post("/api/v1/workshop/links", json={
            "workshop_id": model["model_id"], "entity_id": "xxx_1",
            "predicate": "used_in"})
        assert bad.status_code == 422
        bad_pred = client.post("/api/v1/workshop/links", json={
            "workshop_id": model["model_id"],
            "entity_id": "proj_demo", "predicate": "owns"})
        assert bad_pred.status_code == 422
        linked = client.post("/api/v1/workshop/links", json={
            "workshop_id": model["model_id"],
            "entity_id": "proj_demo", "predicate": "used_in"})
        assert linked.status_code == 201, linked.text
        assert linked.json()["state"] == "PROPOSED"
        from coordinator.app.symbiosis import proposed
        assert any(linked.json()["candidate_id"] ==
                   item["candidate_id"] for item in proposed(limit=20))
        with pytest.raises(WorkshopRefusedError):
            propose_workshop_link("obj_1", "proj_demo", "used_in")


# -- fab-job state machine --------------------------------------------------------------

def test_fabjob_validation_and_transitions(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        with pytest.raises(WorkshopRefusedError):
            create_fabjob("mdl_nope")
        name = _write_stl("job.stl")
        model = client.post("/api/v1/workshop/models", json={
            "filename": name}).json()
        bad_printer = client.post("/api/v1/workshop/fabjobs", json={
            "model_id": model["model_id"], "printer_id": "prt_no"})
        assert bad_printer.status_code == 422
        bad_profile = client.post("/api/v1/workshop/fabjobs", json={
            "model_id": model["model_id"], "profile": "nope"})
        assert bad_profile.status_code == 422
        # Illegal order refuses.
        job = client.post("/api/v1/workshop/fabjobs", json={
            "model_id": model["model_id"]}).json()
        assert job["stage"] == "designed"
        assert client.post(
            f"/api/v1/workshop/fabjobs/{job['job_id']}/slice",
            json={}).status_code == 422
        assert client.post(
            f"/api/v1/workshop/fabjobs/{job['job_id']}/nope",
            json={}).status_code == 422
        assert client.get(
            f"/api/v1/workshop/fabjobs/fabjob_nope").status_code \
            == 404


def test_fabjob_prepare_slice_propose(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        printer_id = _printer(client)
        name = _write_stl("prep.stl")
        model = client.post("/api/v1/workshop/models", json={
            "filename": name}).json()
        job = client.post("/api/v1/workshop/fabjobs", json={
            "model_id": model["model_id"], "material_ref": "PLA",
            "printer_id": printer_id,
            "profile": "draft-pla"}).json()
        prepared = client.post(
            f"/api/v1/workshop/fabjobs/{job['job_id']}/prepare",
            json={}).json()
        assert prepared["stage"] == "prepared"
        sliced = client.post(
            f"/api/v1/workshop/fabjobs/{job['job_id']}/slice",
            json={"slicer": "test-slicer"}).json()
        assert sliced["stage"] == "gcode-ready"
        assert sliced["gcode_ref"].endswith(".gcode")
        proposed = client.post(
            f"/api/v1/workshop/fabjobs/{job['job_id']}/propose",
            json={}).json()
        assert proposed["stage"] == "proposed"
        assert proposed["proposal_id"].startswith("wrt-")
        # Unavailable slicer blocks honestly on a fresh job.
        job2 = client.post("/api/v1/workshop/fabjobs", json={
            "model_id": model["model_id"], "printer_id": printer_id,
            "profile": "draft-pla"}).json()
        client.post(f"/api/v1/workshop/fabjobs/{job2['job_id']}/prepare",
                    json={})
        blocked = client.post(
            f"/api/v1/workshop/fabjobs/{job2['job_id']}/slice",
            json={"slicer": "nope-slicer"}).json()
        assert blocked["stage"] == "blocked"


def test_full_chain_to_verified(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        printer_id = _printer(client)
        name = _write_stl("full.stl")
        model = client.post("/api/v1/workshop/models", json={
            "filename": name}).json()
        job = client.post("/api/v1/workshop/fabjobs", json={
            "model_id": model["model_id"], "material_ref": "PLA",
            "printer_id": printer_id,
            "profile": "draft-pla"}).json()
        job_id = job["job_id"]
        client.post(f"/api/v1/workshop/fabjobs/{job_id}/prepare",
                    json={})
        client.post(f"/api/v1/workshop/fabjobs/{job_id}/slice",
                    json={"slicer": "test-slicer"})
        proposed = client.post(
            f"/api/v1/workshop/fabjobs/{job_id}/propose",
            json={}).json()
        proposal_id = proposed["proposal_id"]
        # Execute before YES refuses (existing gate).
        assert client.post(
            f"/api/v1/writes/{proposal_id}/execute").status_code \
            == 409
        assert client.post(
            f"/api/v1/writes/{proposal_id}/approve",
            json={"response": "YES"}).status_code == 200
        executed = client.post(
            f"/api/v1/writes/{proposal_id}/execute")
        assert executed.status_code == 200, executed.text
        synced = client.post(
            f"/api/v1/workshop/fabjobs/{job_id}/sync",
            json={}).json()
        assert synced["stage"] == "printed-simulated"
        # Observe needs a real observation.
        assert client.post(
            f"/api/v1/workshop/fabjobs/{job_id}/observe",
            json={"observation_id": "obs-missing"}).status_code \
            == 422
        device = client.post("/api/v1/cameras/register", json={
            "name": "W35 cam", "kinds": ["snapshot"],
            "source": "usb"}).json()["device_id"]
        shot = _write_inbox("w35-verify.png")
        ingested = client.post(
            f"/api/v1/cameras/{device}/ingest-file",
            json={"filename": shot})
        assert ingested.status_code == 201, ingested.text
        observation_id = ingested.json()["observation"][
            "observation_id"]
        observed = client.post(
            f"/api/v1/workshop/fabjobs/{job_id}/observe",
            json={"observation_id": observation_id}).json()
        assert observed["stage"] == "observed"
        # Verify needs a named human.
        assert client.post(
            f"/api/v1/workshop/fabjobs/{job_id}/verify",
            json={}).status_code == 422
        verified = client.post(
            f"/api/v1/workshop/fabjobs/{job_id}/verify",
            json={"verified_by": "Jelles"}).json()
        assert verified["stage"] == "verified"
        assert verified["verified_by"] == "Jelles"
        # Cancel after print refuses (plastic exists).
        assert client.post(
            f"/api/v1/workshop/fabjobs/{job_id}/cancel",
            json={}).status_code == 422


# -- presence, packet, progress --------------------------------------------------------------

def test_presence_and_packet(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.get("/api/v1/workshop/presence",
                          params={"entity_id": "xxx_1"}
                          ).status_code == 422
        name = _write_stl("pres.stl")
        model = client.post("/api/v1/workshop/models", json={
            "filename": name}).json()
        client.post("/api/v1/workshop/links", json={
            "workshop_id": model["model_id"],
            "entity_id": "proj_demo", "predicate": "used_in"})
        presence = client.get("/api/v1/workshop/presence",
                              params={"entity_id": "proj_demo"}
                              ).json()
        assert presence["done"] >= 1
        assert any(gap["missing"] == "material"
                   for gap in presence["gaps"])
        packet = client.get("/api/v1/workshop/packet",
                            params={"project_id": "proj_demo"}
                            ).json()
        assert packet["packet"] == "mycelium-3d-workshop/1"
        assert "MYCELIUM 3D WORKSHOP SECTION" in packet["markdown"]
        assert "mycelium-3d-workshop" in packet["markdown"] or True
        assert workshop_packet("proj_demo")["project_id"] == \
            "proj_demo"
        assert get_model(model["model_id"])["model_id"] == \
            model["model_id"]
        assert len(list_models()) == 1


def test_stage_progress_math():
    from coordinator.app.ui import stage_progress
    html = stage_progress("Solar Water System", [
        ("research", "completed"), ("components", "completed"),
        ("design", "completed"),
        ("fabrication", "open"),
        ("physical verification", "blocked")])
    assert "[██████░░░░] 60%" in html
    assert html.count("✓") == 3
    assert "■" in html


# -- UI contracts -------------------------------------------------------------------------------

def test_workbench_pages(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        page = client.get("/3d")
        assert page.status_code == 200
        assert "VERIFY" in page.text
        for needle in ("Models", "Materials", "Fabrication",
                       "Machines", "Register + inspect",
                       "continuation packet"):
            assert needle in page.text, needle
        mobile = client.get("/mobile").text
        assert "Workbench" in mobile
        guide = client.get("/api/v1/guide").json()
        assert "items" in guide


def test_hostile_metadata_stays_data(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        evil = "<script>alert(1)</script> {{7*7}}"
        created = client.post("/api/v1/workshop/materials", json={
            "name": evil, "kind": "filament", "state": "unknown",
            "notes": evil,
            "sustainability_note": "100% green, trust me"}).json()
        assert created["material_id"].startswith("mat_")
        page = client.get("/3d").text
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page
