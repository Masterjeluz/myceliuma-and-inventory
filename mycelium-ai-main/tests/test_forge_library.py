"""Forge Studio slice 3: model library + hybrid manual/AI editing.

A. zonder model · B. workshop-open · C. inventory-open (eerlijk
indien onbereikbaar) · D. provenance · E. manual dirty ·
F. selectie · G. prompt zonder selectie · H. selectie-context ·
I. voorstel · J. geen writes · K. APPLY · L. DISCARD ·
M. manual→AI→manual · N. AI→manual→AI · O. save-flow ·
P. approval · Q. execute-gate · R. verify · S. reload ·
T. geen secrets · U. unknown-op geweigerd · V. slice-1 groen ·
W. slice-2 groen.
"""

import json
import os

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.forge import build_scene_facets
from coordinator.app.forge import clean_scene_parts
from coordinator.app.printer3d import clear_printers

DEAD_INVENTORY = "http://127.0.0.1:9"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "forge3.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "forge3-chat.db"))
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "forge3-fab"))
    clear_printers()
    with TestClient(main_mod.app) as client:
        yield client
    clear_printers()


def cube_scene(size=20.0, dx=0.0, part_id="part_1_cube"):
    return [{
        "id": part_id,
        "kind": "cube",
        "size": {"w": size, "h": size, "d": size},
        "pos": {"x": dx, "y": 0.0, "z": 0.0},
        "rot": {"x": 0.0, "y": 0.0, "z": 0.0},
        "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        "material": "PLA",
    }]


def two_cube_scene():
    first = cube_scene(20.0, 0.0, "part_1_cube")
    second = cube_scene(20.0, 50.0, "part_2_cube")
    return first + second


def seed_workshop_model(client):
    from coordinator.app.mesh3d import ProceduralTestGenerator
    generated = ProceduralTestGenerator().generate("kubus", {})
    reg = client.post("/api/v1/workshop/models", json={
        "filename": generated.artifact_ref, "source": "generated"})
    assert reg.status_code == 201, reg.text
    return reg.json()


def fab_file_count(tmp_path):
    fab = tmp_path / "forge3-fab"
    if not fab.exists():
        return 0
    return len([entry for entry in os.listdir(fab)])


def test_no_model_session_and_save_refuse(tmp_path, monkeypatch):
    """A: Forge werkt zonder model; lege save weigert."""
    for client in make_client(tmp_path, monkeypatch):
        assert client.get("/forge").status_code == 200
        session = client.get("/api/v1/forge/session").json()
        assert session["session"]["dirty"] is False
        assert client.post("/api/v1/forge/save",
                           json={"design_name": "x",
                                 "parts": []}).status_code == 422
        library = client.get("/api/v1/forge/library").json()
        assert set(library) >= {"workshop", "inventory",
                                "local", "external"}
        assert library["external"]["state"] == "NOT_CONNECTED"


def test_workshop_model_opens(tmp_path, monkeypatch):
    """B: bestaand workshop-model opent als derived editor-part."""
    for client in make_client(tmp_path, monkeypatch):
        model = seed_workshop_model(client)
        opened = client.post(
            "/api/v1/forge/open",
            json={"source": "workshop",
                  "ref": model["model_id"]})
        assert opened.status_code == 200, opened.text
        body = opened.json()
        assert body["status"] == "OPENED"
        assert len(body["parts"]) == 1
        part = body["parts"][0]
        assert part["kind"] == "derived"
        assert len(part["tris"]) > 0
        assert body["provenance"]["source"] == "workshop"
        assert body["provenance"]["source_ref"] == \
            model["model_id"]
        assert client.post(
            "/api/v1/forge/open",
            json={"source": "workshop",
                  "ref": "mdl_nope_nope"}).status_code == 422


def test_inventory_open_honest_when_unreachable(tmp_path,
                                                monkeypatch):
    """C: zonder INVENTory geen fake geometry — eerlijke weigering."""
    for client in make_client(tmp_path, monkeypatch):
        monkeypatch.setenv("INVENTORY_BASE_URL", DEAD_INVENTORY)
        response = client.post(
            "/api/v1/forge/open",
            json={"source": "inventory", "entity_type": "file",
                  "ref": "file_deadbeef"})
        assert response.status_code in (422, 502)
        library = client.get("/api/v1/forge/library").json()
        assert library["inventory"]["state"] == "UNAVAILABLE"
        assert library["external"]["state"] == "NOT_CONNECTED"
        assert library["external"]["results"] == []


def test_import_keeps_provenance(tmp_path, monkeypatch):
    """D: import behoudt bron; save neemt source mee."""
    for client in make_client(tmp_path, monkeypatch):
        model = seed_workshop_model(client)
        opened = client.post(
            "/api/v1/forge/open",
            json={"source": "workshop",
                  "ref": model["model_id"]}).json()
        provenance = opened["provenance"]
        assert provenance["source"] == "workshop"
        assert provenance["source_ref"] == model["model_id"]
        assert provenance["imported_from"] == \
            model["filename"]
        scene = [{"id": "part_9_derived",
                  **opened["parts"][0]}]
        saved = client.post(
            "/api/v1/forge/save",
            json={"design_name": "import-bracket",
                  "parts": scene}).json()
        assert saved["status"] == "SAVED"
        stored = saved["file_payload"]["metadata"]["forge"]
        assert stored["parts"][0]["kind"] == "derived"
        assert stored["parts"][0]["source"]["source"] == \
            "workshop"


def test_manual_transform_yields_new_artifact(tmp_path,
                                              monkeypatch):
    """E: handmatige transform = ander derived artifact."""
    for client in make_client(tmp_path, monkeypatch):
        first = client.post(
            "/api/v1/forge/save",
            json={"design_name": "m",
                  "parts": cube_scene()}).json()
        moved = cube_scene()
        moved[0]["pos"]["x"] = 10.0
        second = client.post(
            "/api/v1/forge/save",
            json={"design_name": "m",
                  "parts": moved}).json()
        assert first["sha256"] != second["sha256"]
        assert first["derived_ref"] != second["derived_ref"]


def test_selection_tracked(tmp_path, monkeypatch):
    """F: multi-selectie komt exact terug in het voorstel."""
    for client in make_client(tmp_path, monkeypatch):
        proposal = client.post(
            "/api/v1/forge/propose",
            json={"selection": ["part_1_cube", "part_2_cube"],
                  "prompt": "maak deze 5mm langer",
                  "parts": two_cube_scene()}).json()
        assert proposal["proposal"]["target_selection"] == \
            ["part_1_cube", "part_2_cube"]
        assert client.post(
            "/api/v1/forge/propose",
            json={"selection": ["part_9_ghost"],
                  "prompt": "maak deze 5mm langer",
                  "parts": two_cube_scene()}).status_code \
            == 422


def test_prompt_without_selection_refused(tmp_path, monkeypatch):
    """G: prompt zonder selectie wordt veilig afgehandeld."""
    for client in make_client(tmp_path, monkeypatch):
        assert client.post(
            "/api/v1/forge/propose",
            json={"selection": [],
                  "prompt": "maak deze 5mm langer",
                  "parts": cube_scene()}).status_code == 422


def test_prompt_sees_only_selection(tmp_path, monkeypatch):
    """H: alleen geselecteerde geometry zit in de preview."""
    for client in make_client(tmp_path, monkeypatch):
        proposal = client.post(
            "/api/v1/forge/propose",
            json={"selection": ["part_2_cube"],
                  "prompt": "maak deze 5mm langer",
                  "parts": two_cube_scene()}).json()
        assert proposal["proposal"]["target_selection"] == \
            ["part_2_cube"]
        assert proposal["proposal"]["preview"]["total_tris"] \
            == 12


def test_ai_proposal_shape(tmp_path, monkeypatch):
    """I: gestructureerd voorstel met preview + APPLY-patch."""
    for client in make_client(tmp_path, monkeypatch):
        proposal = client.post(
            "/api/v1/forge/propose",
            json={"selection": ["part_1_cube"],
                  "prompt": "maak deze 5mm langer",
                  "parts": cube_scene()}).json()["proposal"]
        assert set(proposal) >= {"target_selection", "operation",
                                 "parameters", "reason",
                                 "preview"}
        assert proposal["operation"] == "extend"
        assert proposal["parameters"] == {"axis": "x",
                                          "delta_mm": 5.0}
        assert proposal["preview"]["patch"]["update"][
            "part_1_cube"]["size"]["w"] == 25.0


def test_proposal_writes_nothing(tmp_path, monkeypatch):
    """J: voorstel muteert niets canoniek en geen working file."""
    for client in make_client(tmp_path, monkeypatch):
        before_models = client.get(
            "/api/v1/workshop/models").json()["models"]
        before_files = fab_file_count(tmp_path)
        body = client.post(
            "/api/v1/forge/propose",
            json={"selection": ["part_1_cube"],
                  "prompt": "maak deze 5mm langer",
                  "parts": cube_scene()}).json()
        assert not (set(body) & {"proposal_id", "approval",
                                 "file_payload", "derived_ref",
                                 "verification", "result"})
        assert "proposal" in body
        assert client.get(
            "/api/v1/workshop/models").json()["models"] == \
            before_models
        assert fab_file_count(tmp_path) == before_files


def _apply_patch(parts, patch):
    for part_id, update in (patch.get("update") or {}).items():
        part = next(item for item in parts
                    if item.get("id") == part_id)
        for key in ("size", "pos", "rot"):
            if key in update:
                part[key] = update[key]
        if "tris" in update:
            part["tris"] = update["tris"]
    doomed = set(patch.get("remove") or [])
    parts[:] = [item for item in parts
                if item.get("id") not in doomed]
    return parts


def test_preview_applies_to_editor(tmp_path, monkeypatch):
    """K: APPLY-patch op editor state == backend-preview."""
    for client in make_client(tmp_path, monkeypatch):
        parts = cube_scene()
        proposal = client.post(
            "/api/v1/forge/propose",
            json={"selection": ["part_1_cube"],
                  "prompt": "maak deze 5mm langer",
                  "parts": parts}).json()["proposal"]
        applied = _apply_patch([dict(item) for item in parts],
                               proposal["preview"]["patch"])
        rebuilt = build_scene_facets(clean_scene_parts(
            applied, need_ids=True))
        preview = proposal["preview"]["tris"]
        assert len(rebuilt) == len(preview) == \
            proposal["preview"]["total_tris"]
        worst = max(abs(got - want)
                    for got_tri, want_tri in zip(
                        [[[float(v) for v in pt]
                           for pt in facet]
                          for facet in rebuilt], preview)
                    for got_pt, want_pt in zip(got_tri,
                                               want_tri)
                    for got, want in zip(got_pt, want_pt))
        assert worst < 1e-9


def test_discard_changes_nothing(tmp_path, monkeypatch):
    """L: DISCARD (voorstel verwerpen) muteert niets."""
    for client in make_client(tmp_path, monkeypatch):
        before_models = client.get(
            "/api/v1/workshop/models").json()["models"]
        before_files = fab_file_count(tmp_path)
        client.post("/api/v1/forge/propose", json={
            "selection": ["part_1_cube"],
            "prompt": "verwijder dit onderdeel",
            "parts": two_cube_scene()})
        assert client.get(
            "/api/v1/workshop/models").json()["models"] == \
            before_models
        assert fab_file_count(tmp_path) == before_files


def test_manual_ai_manual_flow(tmp_path, monkeypatch):
    """M: manual → AI → manual, alles editor-local tot Save."""
    for client in make_client(tmp_path, monkeypatch):
        parts = cube_scene()
        first = client.post(
            "/api/v1/forge/save",
            json={"design_name": "m",
                  "parts": parts}).json()
        proposal = client.post(
            "/api/v1/forge/propose",
            json={"selection": ["part_1_cube"],
                  "prompt": "maak deze 5mm langer",
                  "parts": parts}).json()["proposal"]
        _apply_patch(parts, proposal["preview"]["patch"])
        parts[0]["pos"]["x"] = 7.0
        second = client.post(
            "/api/v1/forge/save",
            json={"design_name": "m", "parts": parts,
                  "ai_edits": [{
                      "op": proposal["operation"],
                      "targets":
                          proposal["target_selection"],
                      "reason": proposal["reason"]}]}).json()
        assert first["sha256"] != second["sha256"]
        stored = second["file_payload"]["metadata"]["forge"]
        assert stored["ai_edits"][0]["origin"] == "ai-generated"
        assert stored["ai_edits"][0]["op"] == "extend"
        assert "ai-assisted" in second["file_payload"][
            "description"]


def test_ai_manual_ai_flow(tmp_path, monkeypatch):
    """N: AI → manual → AI, tweede voorstel ziet nieuwe state."""
    for client in make_client(tmp_path, monkeypatch):
        parts = cube_scene()
        first = client.post(
            "/api/v1/forge/propose",
            json={"selection": ["part_1_cube"],
                  "prompt": "maak deze 5mm langer",
                  "parts": parts}).json()["proposal"]
        _apply_patch(parts, first["preview"]["patch"])
        assert parts[0]["size"]["w"] == 25.0
        parts[0]["rot"]["z"] = 15.0
        second = client.post(
            "/api/v1/forge/propose",
            json={"selection": ["part_1_cube"],
                  "prompt": "verplaats 10mm naar links",
                  "parts": parts}).json()["proposal"]
        assert second["operation"] == "translate"
        assert second["parameters"]["dx"] == -10.0
        assert second["preview"]["total_tris"] == 12


def _save_proposal_flow(client, monkeypatch, parts):
    monkeypatch.setenv("INVENTORY_BASE_URL", DEAD_INVENTORY)
    payload = client.post(
        "/api/v1/forge/save",
        json={"design_name": "hybrid", "parts": parts}).json()[
            "file_payload"]
    created = client.post(
        "/api/v1/writes/inventory",
        json={"mutation": "create", "entity_type": "file",
              "fields": payload, "actor": "forge-studio"})
    assert created.status_code == 201
    return created.json()["proposal"]["proposal_id"]


def test_save_uses_derived_mesh_flow(tmp_path, monkeypatch):
    """O: Save = bestaande derived-mesh + inert file-payload."""
    for client in make_client(tmp_path, monkeypatch):
        body = client.post(
            "/api/v1/forge/save",
            json={"design_name": "hybrid",
                  "parts": cube_scene()}).json()
        assert body["status"] == "SAVED"
        assert body["file_payload"]["file_kind"] == "mesh"
        assert body["validation"]["verdict"] == "valid"


def test_approval_required(tmp_path, monkeypatch):
    """P: approval blijft verplicht (409 zonder YES)."""
    for client in make_client(tmp_path, monkeypatch):
        proposal_id = _save_proposal_flow(client, monkeypatch,
                                          cube_scene())
        assert client.post(
            f"/api/v1/writes/{proposal_id}/execute"
        ).status_code == 409
        assert client.post(
            f"/api/v1/writes/{proposal_id}/approve",
            json={"response": "YES",
                  "decided_by": "jelles"}).json()[
                "status"] == "approved"


def test_execute_uses_gate(tmp_path, monkeypatch):
    """Q: execute gaat door de echte gate (failed zonder INVENTory)."""
    for client in make_client(tmp_path, monkeypatch):
        proposal_id = _save_proposal_flow(client, monkeypatch,
                                          cube_scene())
        client.post(f"/api/v1/writes/{proposal_id}/approve",
                    json={"response": "YES",
                          "decided_by": "jelles"})
        done = client.post(
            f"/api/v1/writes/{proposal_id}/execute").json()
        assert done["status"] == "failed"
        assert done["result"]["outcome"] == "failed"


def test_verify_path(tmp_path, monkeypatch):
    """R: verify gebruikt het bestaande verify-pad."""
    for client in make_client(tmp_path, monkeypatch):
        proposal_id = _save_proposal_flow(client, monkeypatch,
                                          cube_scene())
        client.post(f"/api/v1/writes/{proposal_id}/approve",
                    json={"response": "YES",
                          "decided_by": "jelles"})
        client.post(f"/api/v1/writes/{proposal_id}/execute")
        verified = client.post(
            f"/api/v1/writes/{proposal_id}/verify").json()
        assert verified["verification"]["outcome"] == "failed"


def test_reload_keeps_geometry(tmp_path, monkeypatch):
    """S: reload levert de opgeslagen geometry terug."""
    for client in make_client(tmp_path, monkeypatch):
        saved = client.post(
            "/api/v1/forge/save",
            json={"design_name": "hybrid",
                  "parts": cube_scene()}).json()
        preview = client.get(
            "/api/v1/fab/mesh/preview",
            params={"artifact_ref": saved["derived_ref"],
                    "max_tris": 5000}).json()
        assert preview["total_tris"] == saved["total_tris"]


def test_no_secrets_in_ai_context(tmp_path, monkeypatch):
    """T: geen secrets/filesystem-data in AI-context of echo."""
    for client in make_client(tmp_path, monkeypatch):
        proposal = client.post(
            "/api/v1/forge/propose",
            json={"selection": ["part_1_cube"],
                  "prompt": "maak deze 5mm langer",
                  "parts": cube_scene()}).json()
        dumped = json.dumps(proposal).lower()
        for banned in ("token", "password", "secret", "passwd",
                       "credential", "begin ", "c:\\", "/tmp"):
            assert banned not in dumped
        assert client.post(
            "/api/v1/forge/propose",
            json={"selection": ["../evil"],
                  "prompt": "maak deze 5mm langer",
                  "parts": cube_scene()}).status_code == 422


def test_unknown_op_refused(tmp_path, monkeypatch):
    """U: onbekende/arbitrary operaties worden geweigerd."""
    for client in make_client(tmp_path, monkeypatch):
        assert client.post(
            "/api/v1/forge/propose",
            json={"selection": ["part_1_cube"],
                  "prompt": "maak er een draak van",
                  "parts": cube_scene()}).status_code == 422
        assert client.post(
            "/api/v1/forge/propose",
            json={"selection": ["part_1_cube"],
                  "op": "teleport",
                  "parts": cube_scene()}).status_code == 422
        assert client.post(
            "/api/v1/forge/propose",
            json={"selection": ["part_1_cube"],
                  "prompt": "maak deze twee gaten groter",
                  "parts": cube_scene()}).status_code == 422
        assert client.post(
            "/api/v1/forge/propose",
            json={"selection": ["part_1_cube"],
                  "prompt": "verwijder dit onderdeel",
                  "parts": cube_scene()}).status_code == 422


def test_slice1_still_green(tmp_path, monkeypatch):
    """V: Slice-1-gedrag intact (primitives + ask zonder writes)."""
    for client in make_client(tmp_path, monkeypatch):
        data = client.get("/api/v1/forge/session").json()
        assert data["primitives"]["cube"]["total_tris"] == 12
        assert data["session"]["dirty"] is False
        assert 'id="forge-save"' in client.get("/forge").text
        answer = client.post(
            "/api/v1/forge/ask",
            json={"question":
                  "maak deze bracket 5mm langer"}).json()
        assert answer["proposed_op"]["op"] == "extend"
        assert answer["physical"] == "HARDWARE_REQUIRED"


def test_slice2_still_green(tmp_path, monkeypatch):
    """W: Slice-2-contract intact (SAVED + file-payload)."""
    for client in make_client(tmp_path, monkeypatch):
        body = client.post(
            "/api/v1/forge/save",
            json={"design_name": "bracket",
                  "parts": [{
                      "kind": "cube",
                      "size": {"w": 20.0, "h": 20.0,
                               "d": 20.0},
                      "pos": {"x": 0.0, "y": 0.0, "z": 0.0},
                      "rot": {"x": 0.0, "y": 0.0, "z": 0.0},
                      "scale": {"x": 1.0, "y": 1.0,
                                "z": 1.0},
                      "material": "PLA"}]}).json()
        assert body["status"] == "SAVED"
        assert set(body["file_payload"]) == {
            "name", "file_kind", "mime_type", "sha256",
            "size_bytes", "description", "status", "metadata"}
