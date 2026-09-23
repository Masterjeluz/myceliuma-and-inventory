"""Forge Studio vertical slice 1: E2E over bestaande contracten.

A. /forge opent · B. primitive verschijnt · C. selectie-hook ·
D. parameter-hook · E. dirty-hook · F. fork · G. backend-read ·
H. gated save/proposal-flow · I. eerlijke slicer-status ·
J. geen fysieke actie zonder gate.
"""

import pathlib

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.forge import (ask_forge, default_session,
                                   primitive_facets)
from coordinator.app.missions import list_missions
from coordinator.app.printer3d import clear_printers


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "forge.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "forge-chat.db"))
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "forge-fab"))
    clear_printers()
    with TestClient(main_mod.app) as client:
        yield client
    clear_printers()


def test_forge_page_opens_with_workshop_shell(tmp_path,
                                              monkeypatch):
    """A: /forge bestaat, bruikbaar, in het design system."""
    for client in make_client(tmp_path, monkeypatch):
        response = client.get("/forge")
        assert response.status_code == 200
        text = response.text
        assert "<nav" in text and "<main" in text
        assert 'id="forge-view"' in text
        assert "ForgeSession" in text
        assert 'id="forge-save"' in text
        assert 'id="forge-fork"' in text
        assert "HARDWARE_REQUIRED" in text
        for tab in ("DESIGN", "SLICE", "BUILD", "HISTORY",
                    "MYCELIUM"):
            assert tab in text


def test_forge_session_primitive_and_honesty(tmp_path,
                                             monkeypatch):
    """B + I + G: echte primitive + eerlijke slicer + echte read."""
    for client in make_client(tmp_path, monkeypatch):
        data = client.get("/api/v1/forge/session").json()
        cube = data["primitives"]["cube"]
        assert cube["total_tris"] == 12
        assert "cad.box_facets" in cube["source"]
        assert len(cube["tris"][0]) == 3
        assert data["primitives"]["cylinder"]["total_tris"] > 12
        assert data["slicer"]["simulated"]["state"] == "SIMULATED"
        assert data["slicer"]["production"]["state"] == \
            "UNAVAILABLE"
        assert data["inventory"]["state"] in ("REAL",
                                              "UNAVAILABLE")
        assert "models" in data["workshop"]
        assert data["identity"]["name"] == "Forge"
        assert data["session"]["dirty"] is False
        assert data["session"]["forked_from"] == {}


def test_forge_editor_hooks_present(tmp_path, monkeypatch):
    """C + D + E + F: selectie/params/dirty/fork hooks in de UI."""
    for client in make_client(tmp_path, monkeypatch):
        text = client.get("/forge").text
        assert "selectPart" in text and 'id="forge-parts"' in text
        assert "applyProps" in text and "fp-" in text
        assert "dim.w" in text and "fp-material" in text
        assert "setDirty" in text and 'id="forge-dirty"' in text
        assert "forked_from" in text
        session = default_session()
        assert session["dirty"] is False
        assert set(session) >= {"selected_model", "selected_part",
                                "camera", "parts", "parameters",
                                "dirty", "project_id", "model_id",
                                "forked_from"}


def test_forge_ask_proposes_without_writing(tmp_path,
                                            monkeypatch):
    """Mycelium-paneel: adviseert + stelt voor, schrijft niets."""
    for client in make_client(tmp_path, monkeypatch):
        missions_before = len(list_missions(limit=100))
        answer = client.post(
            "/api/v1/forge/ask",
            json={"question": "maak deze bracket 5mm langer"}).json()
        assert answer["proposed_op"]["op"] == "extend"
        assert answer["physical"] == "HARDWARE_REQUIRED"
        assert answer["mission_draft"]["steps"][0]["kind"] == \
            "research"
        assert len(list_missions(limit=100)) == missions_before
        assert client.post("/api/v1/forge/ask",
                           json={"question": ""}).status_code == 422
        assert client.post(
            "/api/v1/forge/ask",
            json={"question": "x" * 501}).status_code == 422


def test_forge_save_uses_existing_gated_flow(tmp_path,
                                             monkeypatch):
    """H: Save = bestaande writes-flow (inert tot exact YES)."""
    for client in make_client(tmp_path, monkeypatch):
        assert "/api/v1/writes/inventory" in \
            client.get("/forge").text
        created = client.post(
            "/api/v1/writes/inventory",
            json={"mutation": "create", "entity_type": "object",
                  "fields": {"name": "Forge design",
                             "description": "cube 20x20x20mm"},
                  "actor": "forge-studio"})
        assert created.status_code == 201
        body = created.json()
        assert body["status"] == "proposed"
        proposal_id = body["proposal"]["proposal_id"]
        decided = client.post(
            f"/api/v1/writes/{proposal_id}/approve",
            json={"response": "YES", "decided_by": "jelles"})
        assert decided.json()["status"] == "approved"


def test_forge_no_physical_action_without_gate(tmp_path,
                                               monkeypatch):
    """J: geen uitvoering, geen printer/shell/subprocess-pad."""
    source = pathlib.Path(
        "coordinator/app/forge.py").read_text(encoding="utf-8")
    for banned in ("printer.execute", "robot.execute",
                   "execute_print", "subprocess", "os.system",
                   "ensure_npc_familiars("):
        assert banned not in source
    assert "HARDWARE_REQUIRED" in source
    for client in make_client(tmp_path, monkeypatch):
        text = client.get("/forge").text
        assert "start nooit zelf een printer" in text
        assert "/writes" in text


def test_primitive_helpers_fail_closed():
    assert primitive_facets("cube")["total_tris"] == 12
    try:
        primitive_facets("torus")
    except ValueError:
        pass
    else:  # pragma: no cover - must refuse
        raise AssertionError("unknown primitive accepted")
    try:
        ask_forge("")
    except ValueError:
        pass
    else:  # pragma: no cover - must refuse
        raise AssertionError("empty question accepted")
