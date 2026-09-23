"""Forge Studio slice 2: persistente editor-geometry via bestaande infra.

A. session zonder saved geometry · B. wijziging = ander artifact ·
C. save muteert niets direct · D. file/derived-mesh proposal-contract ·
E. geen secrets · F. approval verplicht · G. execute via gate ·
H. verify-path · I. reload na persistence · J. reload == geometry ·
K. fork zonder save = lokaal · L. fork na save behoudt provenance ·
M. failed proposal muteert niets canoniek · N. slice-1 groen (apart).
"""

import json

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.forge import build_editor_facets
from coordinator.app.printer3d import clear_printers

DEAD_INVENTORY = "http://127.0.0.1:9"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "forge2.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "forge2-chat.db"))
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "forge2-fab"))
    clear_printers()
    with TestClient(main_mod.app) as client:
        yield client
    clear_printers()


def cube_parts(size=20.0, dx=0.0):
    return [{
        "kind": "cube",
        "size": {"w": size, "h": size, "d": size},
        "pos": {"x": dx, "y": 0.0, "z": 0.0},
        "rot": {"x": 0.0, "y": 0.0, "z": 0.0},
        "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        "material": "PLA",
    }]


def save(client, parts, name="bracket", forked=None):
    return client.post("/api/v1/forge/save", json={
        "design_name": name, "parts": parts,
        "forked_from": forked or {}})


def test_save_needs_geometry_and_name(tmp_path, monkeypatch):
    """A: session werkt zonder saved geometry; lege save weigert."""
    for client in make_client(tmp_path, monkeypatch):
        assert client.get("/api/v1/forge/session").status_code \
            == 200
        assert save(client, []).status_code == 422
        assert save(client, cube_parts(),
                    name="").status_code == 422
        assert save(client, [{"kind": "torus"}]).status_code \
            == 422


def test_geometry_change_yields_new_artifact(tmp_path,
                                             monkeypatch):
    """B: gewijzigde geometry is dirty in de zin die ertoe doet:
    een ander derived artifact (andere sha, andere ref)."""
    for client in make_client(tmp_path, monkeypatch):
        first = save(client, cube_parts(20.0)).json()
        second = save(client, cube_parts(30.0)).json()
        assert first["sha256"] != second["sha256"]
        assert first["derived_ref"] != second["derived_ref"]
        assert first["total_tris"] == second["total_tris"] == 12


def test_save_mutates_nothing(tmp_path, monkeypatch):
    """C: save schrijft alleen een lokale working file; geen
    proposal, geen approval, geen registratie."""
    for client in make_client(tmp_path, monkeypatch):
        body = save(client, cube_parts()).json()
        assert body["status"] == "SAVED"
        assert body["validation"]["verdict"] == "valid"
        assert not (set(body) & {"proposal", "approval",
                                 "result", "proposal_id",
                                 "verification"})
        assert "file_payload" in body


def test_file_payload_contract(tmp_path, monkeypatch):
    """D: payload volgt exact het bestaande file-contract."""
    for client in make_client(tmp_path, monkeypatch):
        body = save(client, cube_parts(), forked={
            "source": "mdl_demo"}).json()
        payload = body["file_payload"]
        assert set(payload) == {"name", "file_kind",
                                "mime_type", "sha256",
                                "size_bytes", "description",
                                "status", "metadata"}
        assert payload["file_kind"] == "mesh"
        assert payload["status"] == "available"
        assert len(payload["sha256"]) == 64
        assert payload["size_bytes"] > 0
        assert payload["metadata"]["artifact_ref"] == \
            body["derived_ref"]
        assert len(payload["metadata"]["forge"]["parts"]) == 1


def test_payload_carries_no_secrets(tmp_path, monkeypatch):
    """E: geen secrets, geen paden, geen ongewenste data."""
    for client in make_client(tmp_path, monkeypatch):
        payload = save(client, cube_parts()).json()[
            "file_payload"]
        dumped = json.dumps(payload).lower()
        for banned in ("token", "password", "secret", "passwd",
                       "credential", "begin ", "c:\\", "/tmp"):
            assert banned not in dumped
        assert "/" not in payload["metadata"]["artifact_ref"]
        assert "\\" not in payload["metadata"]["artifact_ref"]


def _approved_failed_flow(client, monkeypatch):
    """Save → proposal → YES → execute tegen dode INVENTory
    (deterministisch failed, raakt nooit echte data)."""
    monkeypatch.setenv("INVENTORY_BASE_URL", DEAD_INVENTORY)
    payload = save(client, cube_parts()).json()["file_payload"]
    created = client.post(
        "/api/v1/writes/inventory",
        json={"mutation": "create", "entity_type": "file",
              "fields": payload, "actor": "forge-studio"})
    assert created.status_code == 201
    proposal_id = created.json()["proposal"]["proposal_id"]
    return proposal_id


def test_execute_needs_approval(tmp_path, monkeypatch):
    """F: approval blijft verplicht (409 zonder YES)."""
    for client in make_client(tmp_path, monkeypatch):
        proposal_id = _approved_failed_flow(client, monkeypatch)
        assert client.post(
            f"/api/v1/writes/{proposal_id}/execute"
        ).status_code == 409
        decided = client.post(
            f"/api/v1/writes/{proposal_id}/approve",
            json={"response": "YES", "decided_by": "jelles"})
        assert decided.json()["status"] == "approved"


def test_execute_uses_existing_gate(tmp_path, monkeypatch):
    """G: approved execute gaat door de echte writer — zonder
    INVENTory eerlijk failed, nooit fake succes."""
    for client in make_client(tmp_path, monkeypatch):
        proposal_id = _approved_failed_flow(client, monkeypatch)
        client.post(f"/api/v1/writes/{proposal_id}/approve",
                    json={"response": "YES",
                          "decided_by": "jelles"})
        done = client.post(
            f"/api/v1/writes/{proposal_id}/execute")
        body = done.json()
        assert body["status"] == "failed"
        assert body["result"]["outcome"] == "failed"
        assert body["result"]["error"]


def test_verify_path_on_failed_result(tmp_path, monkeypatch):
    """H: verify gebruikt het bestaande verify-pad (failed,
    want execution slaagde niet — nooit een valse pass)."""
    for client in make_client(tmp_path, monkeypatch):
        proposal_id = _approved_failed_flow(client, monkeypatch)
        client.post(f"/api/v1/writes/{proposal_id}/approve",
                    json={"response": "YES",
                          "decided_by": "jelles"})
        client.post(f"/api/v1/writes/{proposal_id}/execute")
        verified = client.post(
            f"/api/v1/writes/{proposal_id}/verify")
        body = verified.json()
        assert body["verification"]["outcome"] == "failed"


def test_reload_after_save(tmp_path, monkeypatch):
    """I + J: reload via de bestaande preview levert dezelfde
    geometry terug (tolerantie voor .3f-afronding)."""
    for client in make_client(tmp_path, monkeypatch):
        parts = cube_parts(20.0)
        saved = save(client, parts).json()
        preview = client.get(
            "/api/v1/fab/mesh/preview",
            params={"artifact_ref": saved["derived_ref"],
                    "max_tris": 5000}).json()
        assert preview["total_tris"] == saved["total_tris"]
        assert preview["format"] == "stl-ascii"
        expected = build_editor_facets(parts)
        assert len(preview["tris"]) == len(expected)
        worst = 0.0
        for got_tri, want_tri in zip(preview["tris"],
                                     expected):
            for got_pt, want_pt in zip(got_tri, want_tri):
                for got, want in zip(got_pt, want_pt):
                    worst = max(worst, abs(got - want))
        assert worst < 0.002


def test_fork_without_save_stays_local(tmp_path, monkeypatch):
    """K: fork zonder save legt niets canoniek vast."""
    for client in make_client(tmp_path, monkeypatch):
        before = client.get(
            "/api/v1/workshop/models").json()["models"]
        body = save(client, cube_parts()).json()
        assert body["editor"]["forked_from"] == {}
        assert body["file_payload"]["metadata"]["forge"][
            "forked_from"] == {}
        after = client.get(
            "/api/v1/workshop/models").json()["models"]
        assert before == after
        assert "forked from" not in body["file_payload"][
            "description"]


def test_fork_after_save_keeps_provenance(tmp_path, monkeypatch):
    """L: fork-referentie reist mee in payload-metadata."""
    for client in make_client(tmp_path, monkeypatch):
        body = save(client, cube_parts(), forked={
            "source": "mdl_demo",
            "at": "2026-01-01T00:00:00+00:00"}).json()
        forged = body["file_payload"]["metadata"]["forge"]
        assert forged["forked_from"]["source"] == "mdl_demo"
        assert "forked from mdl_demo" in body["file_payload"][
            "description"]


def test_failed_proposal_changes_nothing(tmp_path, monkeypatch):
    """M: failed proposal muteert de canonieke state niet;
    herhaalde execute is idempotent."""
    for client in make_client(tmp_path, monkeypatch):
        proposal_id = _approved_failed_flow(client, monkeypatch)
        client.post(f"/api/v1/writes/{proposal_id}/approve",
                    json={"response": "YES",
                          "decided_by": "jelles"})
        first = client.post(
            f"/api/v1/writes/{proposal_id}/execute").json()
        second = client.post(
            f"/api/v1/writes/{proposal_id}/execute").json()
        assert first["status"] == second["status"] == "failed"
        assert first["result"]["outcome"] == "failed"
        assert second["verification"] is None
