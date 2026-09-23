"""Forge vertical-slice tests: tweede volledige slice IN /play.

Volgt hetzelfde patroon als Luma, maar met de echte testconditie
dat de fysieke A1 Mini NIET verbonden is:

- rendering: volledige flow zichtbaar zonder redirects
- data: abilities/tools/missions uit echte backend-state
- model -> inspect -> assess -> slice -> proposal-preview
- approval: exact YES, fingerprint, bestaande route, geen shortcut
- hardware gate stopt eerlijk (blocked, nooit fake success)
- quest-evidence uitsluitend uit bestaande derivatie
- fungi/guide: afgeleid, read-only, geen fake progressie
- node --check op gerenderde JS
"""

import json
import os
import re

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "forge.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "forge-chat.db"))
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "forge-fab"))
    with TestClient(main_mod.app) as client:
        yield client


def _page(client) -> str:
    response = client.get("/play")
    assert response.status_code == 200, response.text
    return response.text


def _playdata(html: str) -> dict:
    match = re.search(r"const PLAYDATA = (\{.*?\});", html,
                      re.DOTALL)
    assert match, "PLAYDATA niet gevonden"
    return json.loads(match.group(1))


def test_forge_flow_markers_in_game(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        html = _page(client)
        for marker in (
                "Help mij iets te printen",
                "Missie-evidence",
                "Printability controleren",
                "Test-slice uitvoeren",
                "Printvoorstel bekijken",
                "Printvoorstel",
                "MODEL", "PRINTABILITY", "SLICER", "PRINTER",
                "RISICO / REQUIREMENTS", "PROPOSAL",
                "YES", "Annuleren",
                "Sessie:", "Model", "Analyse", "Voorstel",
                "Approval", "Hardware", "Uitvoering",
                "Verificatie",
                "Missie-evidence", "Fabrication-records",
                "Ververs wereld",
                "bestaande records tellen"):
            assert marker in html, marker


def test_forge_hardware_honesty_markers(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        html = _page(client)
        assert "A1 Mini" in html
        assert "NIET VERBONDEN" in html
        assert "HARDWARE_REQUIRED" in html
        assert "Meer informatie" in html
        assert "print nooit automatisch" in html
        # Geen fake succesclaims in de game-shell.
        assert "Print voltooid" not in html
        assert "printer connected" not in html
        assert "Print geslaagd" not in html


def test_forge_data_matches_backend(tmp_path, monkeypatch):
    from coordinator.app.campaigns import (
        ensure_fabrication_seeds,
    )
    for client in make_client(tmp_path, monkeypatch):
        ensure_fabrication_seeds()
        data = _playdata(_page(client))
        forge = data["forge"]
        assert {"models", "printers", "missions", "profiles",
                "quests", "fabrecords"} <= set(forge)
        assert isinstance(forge["profiles"], list)
        assert "draft-pla" in forge["profiles"]
        goals = [m["goal"] for m in forge["missions"]]
        assert "Maak je eerste digitale prototype" in goals
        titles = [q["title"] for q in forge["quests"]]
        assert ("Missie: Maak je eerste digitale prototype"
                in titles)
        npcs = {n["id"]: n for n in data["npcs"]}
        panel = npcs["forge"]["panel"]
        for ability in panel["abilities"]:
            assert ability["type"] in ("DIGITAL", "PHYSICAL",
                                       "HYBRID")
            assert ability["available"]
            assert ability["via"]
        for tool in panel["tools"]:
            assert tool["state"]
            assert tool["detail"]
        names = [t["name"] for t in panel["tools"]]
        assert {"3D-modellen", "Slicer/workbench", "Printers",
                "INVENTory hardware"} <= set(names)
        names = [a["name"] for a in panel["abilities"]]
        assert "Print uitvoeren (fysiek)" in names
        phys = next(a for a in panel["abilities"]
                    if a["name"] == "Print uitvoeren (fysiek)")
        assert phys["type"] == "PHYSICAL"
        # Zonder printer: eerlijk onbeschikbaar, nooit AVAILABLE.
        assert phys["available"] in ("NOT_CONNECTED",
                                     "HARDWARE_REQUIRED")
        assert npcs["forge"]["familiar"]["id"].startswith("fam_")


def _seed_model_and_slice(client):
    from coordinator.app.mesh3d import ProceduralTestGenerator
    generated = ProceduralTestGenerator().generate("kubus", {})
    reg = client.post("/api/v1/workshop/models", json={
        "filename": generated.artifact_ref, "source": "generated"})
    assert reg.status_code == 201, reg.text
    model = reg.json()
    insp = client.post(
        f"/api/v1/workshop/models/{model['model_id']}/inspect")
    assert insp.status_code == 200, insp.text
    assess = client.post("/api/v1/fab/assess",
                         params={"mesh_ref":
                                 generated.artifact_ref})
    assert assess.status_code == 200, assess.text
    sliced = client.post("/api/v1/fab/slice", json={
        "artifact_ref": generated.artifact_ref,
        "profile": "draft-pla", "printer_id": "prt-forge1"})
    assert sliced.status_code == 201, sliced.text
    return model, insp.json(), assess.json(), sliced.json()


def test_forge_model_inspect_assess_slice(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _model, insp, assess, sliced = \
            _seed_model_and_slice(client)
        verdict = insp["inspection"]["mesh_verdict"]
        assert verdict in ("valid", "invalid", "inconclusive",
                           "UNKNOWN")
        assert assess["assessment"]["verdict"] in (
            "printable", "not_printable", "inconclusive")
        assert "safe_to_print" not in json.dumps(assess)
        assert sliced["slice"]["gcode_ref"].endswith(".gcode")
        assert len(sliced["slice"]["sha256"]) == 64
        assert sliced["safety"]["verdict"] in ("safe",
                                               "inconclusive")


def test_forge_proposal_approval_hardware_gate(tmp_path,
                                               monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        # Zonder printer-record: voorstel geweigerd (eerste gate).
        missing = client.post("/api/v1/prints/propose", json={
            "printer_id": "prt-spook", "gcode_ref": "fab-x.gcode",
            "gcode_sha256": "0" * 64, "profile": "draft-pla",
            "actor": "game-jelles"})
        assert missing.status_code == 404
        _model, _insp, _assess, sliced = \
            _seed_model_and_slice(client)
        reg = client.post("/api/v1/printers/register", json={
            "printer_id": "prt-forge1", "name": "A1 Mini (test)",
            "capabilities": ["printer.status",
                             "printer.start"]})
        assert reg.status_code == 201, reg.text
        prop = client.post("/api/v1/prints/propose", json={
            "printer_id": "prt-forge1",
            "gcode_ref": sliced["slice"]["gcode_ref"],
            "gcode_sha256": sliced["slice"]["sha256"],
            "profile": "draft-pla", "actor": "game-jelles"})
        assert prop.status_code == 201, prop.text
        pid = (prop.json().get("proposal_id")
               or prop.json()["proposal"]["proposal_id"])
        # Geen shortcut: alles behalve exact YES wordt geweigerd
        # (bestaande semantiek: denied approval, status rejected).
        for wrong in ("yes", "Yes", "NO", "Y"):
            trial = client.post("/api/v1/prints/propose", json={
                "printer_id": "prt-forge1",
                "gcode_ref": sliced["slice"]["gcode_ref"],
                "gcode_sha256": sliced["slice"]["sha256"],
                "profile": "draft-pla", "actor": "game-jelles"})
            assert trial.status_code == 201, trial.text
            tid = (trial.json().get("proposal_id")
                   or trial.json()["proposal"]["proposal_id"])
            denied = client.post(f"/api/v1/writes/{tid}/approve",
                                 json={"response": wrong,
                                       "decided_by": "jelles"})
            assert denied.status_code == 200, wrong
            assert denied.json()["status"] == "rejected", wrong
            assert denied.json()["status"] != "approved", wrong
            blocked = client.post(f"/api/v1/writes/{tid}/execute")
            assert blocked.status_code == 409, wrong
        ok = client.post(f"/api/v1/writes/{pid}/approve",
                         json={"response": "YES",
                               "decided_by": "jelles"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "approved"
        # Printer-record zonder adapter: execution stopt eerlijk.
        ex = client.post(f"/api/v1/writes/{pid}/execute")
        assert ex.status_code == 200, ex.text
        body = ex.json()
        assert body["status"] == "blocked"
        assert body["status"] != "executed"
        assert "adapter" in (body["result"].get("error")
                             or "").lower()
        # Verificatie kan nooit slagen zonder uitvoering.
        ver = client.post(f"/api/v1/writes/{pid}/verify")
        assert ver.status_code == 200, ver.text
        assert ver.json()["verification"]["outcome"] != "passed"


def test_forge_quest_evidence_stays_honest(tmp_path, monkeypatch):
    from coordinator.app.campaigns import (
        ensure_fabrication_seeds,
    )
    for client in make_client(tmp_path, monkeypatch):
        ensure_fabrication_seeds()
        quests = client.get("/api/v1/quests").json()["quests"]
        fab = [q for q in quests
               if q["title"] == ("Missie: Maak je eerste "
                                 "digitale prototype")]
        assert len(fab) == 1
        assert fab[0]["state"] != "COMPLETED"
        assert fab[0]["progress"] == "0/1"
        # Voorstel aanmaken voedt geen quest-completion.
        _model, _insp, _assess, sliced = \
            _seed_model_and_slice(client)
        client.post("/api/v1/printers/register", json={
            "printer_id": "prt-forge1", "name": "A1 Mini (test)",
            "capabilities": ["printer.status"]})
        prop = client.post("/api/v1/prints/propose", json={
            "printer_id": "prt-forge1",
            "gcode_ref": sliced["slice"]["gcode_ref"],
            "gcode_sha256": sliced["slice"]["sha256"],
            "profile": "draft-pla", "actor": "game-jelles"})
        assert prop.status_code == 201, prop.text
        again = client.get("/api/v1/quests").json()["quests"]
        fab2 = [q for q in again
                if q["title"] == ("Missie: Maak je eerste "
                                  "digitale prototype")]
        assert fab2[0]["state"] != "COMPLETED"
        data = _playdata(_page(client))
        shown = [q for q in data["forge"]["quests"]
                 if q["title"] == ("Missie: Maak je eerste "
                                   "digitale prototype")]
        assert len(shown) == 1
        assert shown[0]["state"] != "COMPLETED"
        assert shown[0]["steps"]


def test_forge_fungi_guide_readonly(tmp_path, monkeypatch):
    from coordinator.app.quests import list_quests
    from coordinator.app.world import derive_fungi_network
    for client in make_client(tmp_path, monkeypatch):
        before = len(list_quests(limit=100))
        first = derive_fungi_network(limit=120)
        html = _page(client)
        assert _page(client)
        assert len(list_quests(limit=100)) == before
        assert first == derive_fungi_network(limit=120)
        assert first["total"] >= 1
        data = _playdata(html)
        assert data["fungi"]["total"] >= 1
        assert "Guide" in html
        assert data["guide"].get("what") is not None


def test_forge_node_syntax(tmp_path, monkeypatch):
    import shutil
    import subprocess
    import tempfile
    node = shutil.which("node")
    if node is None:
        pytest.skip("node niet beschikbaar")
    for client in make_client(tmp_path, monkeypatch):
        html = _page(client)
        scripts = re.findall(r"<script>(.*?)</script>", html,
                             re.DOTALL)
        game = [s for s in scripts if "PLAYDATA" in s]
        assert len(game) == 1
        with tempfile.NamedTemporaryFile(
                "w", suffix=".js", delete=False,
                encoding="utf-8") as handle:
            handle.write(game[0])
            path = handle.name
        try:
            result = subprocess.run(
                [node, "--check", path], capture_output=True,
                timeout=60)
            assert result.returncode == 0, result.stderr.decode(
                "utf-8", "replace")[:500]
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
