"""Phase 4 tests (BIG #11-15): advanced 3D, CAD, fabrication."""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "p4.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "p4-chat.db"))
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "p4-fab"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def make_cube(test_client):
    generated = test_client.post("/api/v1/fab/generate", json={
        "generator": "procedural-test",
        "description": "phase4 cube", "params": {}}).json()
    return generated["fabrication"]["mesh_ref"]


def test_advanced_ops_preview_and_persist(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        ref = make_cube(test_client)
        assert test_client.post("/api/v1/fab/advanced", json={
            "artifact_ref": ref, "op": "nope"}).status_code == 422
        mirrored = test_client.post("/api/v1/fab/advanced",
                                    json={
                                        "artifact_ref": ref,
                                        "op": "mirror",
                                        "params": {"plane": "x"}}).json()
        assert mirrored["executed"] is False
        assert mirrored["result_tris"] == mirrored["total_tris"]
        assert mirrored["preview_tris"]
        extended = test_client.post("/api/v1/fab/advanced",
                                    json={
                                        "artifact_ref": ref,
                                        "op": "extend",
                                        "params": {"axis": "x",
                                                   "delta_mm": 5.0},
                                        "persist": True}).json()
        assert extended["executed"] is True
        assert extended["validation"]["verdict"] == "valid"
        # Shrink past zero refuses.
        assert test_client.post("/api/v1/fab/advanced", json={
            "artifact_ref": ref, "op": "extend",
            "params": {"axis": "x", "delta_mm": -100.0},
            "persist": True}).status_code == 422
        oriented = test_client.post("/api/v1/fab/advanced",
                                    json={
                                        "artifact_ref": ref,
                                        "op": "orient",
                                        "params": {}}).json()
        assert oriented["detail"]["rotation"] in (
            "identity", "rot_x90", "rot_y90")
        merged = test_client.post("/api/v1/fab/advanced", json={
            "artifact_ref": ref, "op": "merge",
            "params": {}, "extra_refs": [ref]}).json()
        assert merged["result_tris"] == 2 * merged["total_tris"]
        volume = test_client.get(
            "/api/v1/fab/volume",
            params={"artifact_ref": ref}).json()
        assert volume["volume_cm3"] == pytest.approx(8.0)


def test_prompt_edit_parses_or_refuses(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        ref = make_cube(test_client)
        assert test_client.post("/api/v1/fab/prompt-edit",
                                json={
                                    "artifact_ref": ref,
                                    "text": "doe iets vaags"}).status_code == 422
        proposal = test_client.post("/api/v1/fab/prompt-edit",
                                    json={
                                        "artifact_ref": ref,
                                        "text": "maak deze bracket "
                                                "5mm langer"}).json()
        assert proposal["op"] == "extend"
        assert proposal["executed"] is False
        assert "5.0" in proposal["interpretation"]
        # Persist without approver refuses.
        assert test_client.post("/api/v1/fab/prompt-edit",
                                json={
                                    "artifact_ref": ref,
                                    "text": "maak hem 5mm langer",
                                    "persist": True}).status_code == 422
        done = test_client.post("/api/v1/fab/prompt-edit", json={
            "artifact_ref": ref,
            "text": "maak hem 5mm langer in z-richting",
            "persist": True,
            "approved_by": "jelles"}).json()
        assert done["executed"] is True
        assert done["validation"]["verdict"] == "valid"


def test_cad_document_build_and_adapter_states(tmp_path,
                                               monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        adapters = test_client.get(
            "/api/v1/cad/adapters").json()
        states = {item["adapter"]: item["state"]
                  for item in adapters}
        assert states["procedural"] == "IMPLEMENTED"
        assert states["openscad"] == "UNAVAILABLE"
        assert states["freecad"] == "UNAVAILABLE"
        assert states["blender"] == "UNAVAILABLE"
        document = test_client.post("/api/v1/cad/documents",
                                    json={
                                        "name": "Bracket"}).json()
        doc_id = document["document_id"]
        assert doc_id.startswith("cad_")
        part = test_client.post(
            f"/api/v1/cad/documents/{doc_id}/parts",
            json={"name": "base"}).json()
        part_id = part["parts"][0]["part_id"]
        # External adapter refuses with requirements.
        refused = test_client.post(
            f"/api/v1/cad/documents/{doc_id}/operate",
            json={"part_id": part_id, "op": "box",
                  "params": {"w": 30, "h": 10, "d": 20},
                  "adapter": "openscad"})
        assert refused.status_code == 422
        assert "UNAVAILABLE" in refused.json()["detail"]
        # Procedural box builds a derived mesh.
        test_client.post(
            f"/api/v1/cad/documents/{doc_id}/operate",
            json={"part_id": part_id, "op": "box",
                  "params": {"w": 30, "h": 10, "d": 20}})
        built = test_client.post(
            f"/api/v1/cad/documents/{doc_id}/build").json()
        assert built["status"] == "built"
        assert built["parts"][0]["derived_ref"].endswith(".stl")
        volume = test_client.get(
            "/api/v1/fab/volume", params={
                "artifact_ref": built["parts"][0][
                    "derived_ref"]}).json()
        assert volume["volume_cm3"] == pytest.approx(6.0)
        # Bad params refuse.
        assert test_client.post(
            f"/api/v1/cad/documents/{doc_id}/operate",
            json={"part_id": part_id, "op": "box",
                  "params": {"w": -5, "h": 10, "d": 20}}
        ).status_code == 422


def test_filament_printer_selection_pipeline(tmp_path,
                                             monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        assert test_client.post("/api/v1/filament/spools",
                                json={"material": "Unobtainium",
                                      "weight_g": 100}).status_code == 422
        spool = test_client.post("/api/v1/filament/spools",
                                 json={
                                     "material": "PLA",
                                     "weight_g": 750,
                                     "color": "green",
                                     "location": "workshop shelf"}
                                 ).json()
        assert spool["spool_id"].startswith("spl_")
        check = test_client.get("/api/v1/filament/check", params={
            "spool_id": spool["spool_id"],
            "grams": 100}).json()
        assert check["enough"] is True
        short = test_client.get("/api/v1/filament/check", params={
            "spool_id": spool["spool_id"],
            "grams": 5000}).json()
        assert short["enough"] is False
        # No printers yet: selection refuses honestly.
        assert test_client.post("/api/v1/fab/select-printer",
                                json={}).status_code == 422
        test_client.post("/api/v1/printers/register", json={
            "printer_id": "prt-a", "name": "A",
            "capabilities": ["printer.status"]})
        test_client.post("/api/v1/printers/register", json={
            "printer_id": "prt-b", "name": "B",
            "capabilities": ["printer.status", "printer.start"]})
        pick = test_client.post("/api/v1/fab/select-printer",
                                json={
                                    "capabilities": ["printer.start"]}
                                ).json()
        assert pick["printer_id"] == "prt-b"
        assert "gated" in pick["physical_start"]
        plan = test_client.post("/api/v1/fab/plan", json={
            "source_object_id": "obj_1", "profile": "draft-pla",
            "material": "PLA"}).json()
        assert len(plan["stages"]) == 14
        assert any("GATED" in stage["action"]
                   for stage in plan["stages"])
        assert "print proposal approval" in plan["gates"]


def test_repair_proposal_is_data_only():
    from coordinator.app.meshops import repair_proposal
    from coordinator.app.mesh3d import MeshReport
    report = MeshReport(artifact_ref="fab-x.stl", format="stl-ascii",
                        verdict="invalid", vertices=3, faces=1,
                        degenerate_faces=1,
                        bounds_mm=[0, 0, 0, 1, 1, 1],
                        checks=[], reasons=["zero-area facet"])
    proposal = repair_proposal(report)
    assert proposal["verdict"] == "invalid"
    assert proposal["suggestions"]
    assert "untouched" in proposal["note"]
