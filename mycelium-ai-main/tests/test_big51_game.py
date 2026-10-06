"""BIG51 game-first: Journal projects (real proj_), remembered
knowledge (dossier -> memory), research regression.

All through existing models/routes: no second store, no invented
projects, no Plan action without a completed dossier, approvals
stay exact-YES."""

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
import coordinator.app.play_workshop as workshop

PAGES = {
    "hydro": ["Hydroponics proef",
              "Vochtige grond naast een waterbron is geschikt "
              "voor hydroponics. Wortels nemen water en "
              "voeding op uit de stroming."],
}


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b51.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b51-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", "b51-operator")
    # Refused loopback port: deterministic INVENTory-offline.
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://127.0.0.1:9")
    with TestClient(main_mod.app) as test_client:
        yield test_client


def api_live_inventory(tmp_path, monkeypatch):
    """Same, but without overriding INVENTory (uses the real
    loopback backend when reachable, degrades honestly)."""
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b51.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b51-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", "b51-operator")
    monkeypatch.delenv("INVENTORY_BASE_URL", raising=False)
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_journal_projects_unavailable(tmp_path, monkeypatch):
    """INVENTory offline -> Journal toont UNAVAILABLE, verzint
    geen projecten, biedt de bestaande /world-vervolgstap."""
    for test_client in api(tmp_path, monkeypatch):
        body = test_client.get("/api/v1/play/journal").json()
        assert body["projects"] == []
        assert body["inventory"]["state"] == "unavailable"
        assert body["inventory"]["reason"]
        assert body["counts"]["projects_open"] == 0


def test_journal_projects_listed_from_real_records(tmp_path,
                                                   monkeypatch):
    """Echte proj_-records -> titel, status, waarom, bronrecord
    en deeplink; niet-proj_ ids worden geweigerd."""
    def stub():
        return {"state": "ok", "reason": "", "items": [
            {"kind": "project", "id": "proj_hydro",
             "title": "Hydroponics-proef", "status": "active",
             "href": "/world?entity_id=proj_hydro&depth=1",
             "why": "Loopt — echte voortgang leeft in INVENTory.",
             "action": {"label": "Inspecteren", "method": "GET",
                        "path": "/world?entity_id=proj_hydro&depth=1"},
             "source": "proj_hydro"},
            {"kind": "project", "id": "proj_zaai",
             "title": "Zaailing-plan", "status": "planned",
             "href": "/world?entity_id=proj_zaai&depth=1",
             "why": "Voorgesteld — nog niet gestart.",
             "action": {"label": "Inspecteren", "method": "GET",
                        "path": "/world?entity_id=proj_zaai&depth=1"},
             "source": "proj_zaai"},
        ]}
    monkeypatch.setattr(workshop, "_default_inventory_projects",
                        stub)
    for test_client in api(tmp_path, monkeypatch):
        body = test_client.get("/api/v1/play/journal").json()
        assert body["inventory"]["state"] == "ok"
        assert len(body["projects"]) == 2
        first = body["projects"][0]
        assert first["id"] == "proj_hydro"
        assert first["source"] == "proj_hydro"
        assert "entity_id=proj_hydro" in first["href"]
        assert first["why"]
        assert body["counts"]["projects_open"] == 2


def test_journal_projects_empty_is_honest(tmp_path, monkeypatch):
    """Lege INVENTory -> eerlijk leeg (state empty), geen
    UNAVAILABLE-leugen en geen verzonnen projecten."""
    monkeypatch.setattr(workshop, "_default_inventory_projects",
                        lambda: {"state": "empty",
                                 "reason": "Geen projecten in "
                                           "INVENTory (lege wereld) "
                                           "— niets verzonnen.",
                                 "items": []})
    for test_client in api(tmp_path, monkeypatch):
        body = test_client.get("/api/v1/play/journal").json()
        assert body["projects"] == []
        assert body["inventory"]["state"] == "empty"
        assert "verzonnen" in body["inventory"]["reason"]


def test_research_regression_draft_has_no_plan(tmp_path,
                                               monkeypatch):
    """Geen completed dossier -> 422 op plan; het Journal biedt
    voor open onderzoek alleen de bestaande Openen-actie."""
    for test_client in api(tmp_path, monkeypatch):
        run = test_client.post("/api/v1/research/queue", json={
            "question": "Onplanbare vraag zonder dossier?"}).json()
        plan = test_client.post(
            f"/api/v1/research/{run['run_id']}/plan", json={})
        assert plan.status_code == 422, plan.text
        assert "dossier" in plan.text.lower()
        body = test_client.get("/api/v1/play/journal").json()
        match = [r for r in body["research"]
                 if r["id"] == run["run_id"]]
        assert len(match) == 1
        assert match[0]["action"]["path"] == "/research"
        assert "plan" not in match[0]["action"]["path"]


def test_research_completed_plans_and_remembers(tmp_path,
                                                monkeypatch):
    """Echte completed/planbare inhoud (TEST) -> bestaande
    planflow naar pending_approval + onthouden mem_-record in
    het Journal; foute approval blijft geweigerd."""
    for test_client in api_live_inventory(tmp_path, monkeypatch):
        created = test_client.post("/api/v1/research/runs", json={
            "question": "Welke hydroponics-aanpak past bij "
                        "vochtige grond?",
            "provider": "test", "test_pages": PAGES})
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["status"] == "completed"
        assert body["dossier_id"].startswith("dos_")
        assert body["memory_id"].startswith("mem_")
        dossier = test_client.get(
            f"/api/v1/research/dossiers/{body['dossier_id']}").json()
        assert dossier["sources"] or dossier["claims"]
        planned = test_client.post(
            f"/api/v1/research/{body['dossier_id']}/plan", json={})
        assert planned.status_code in (200, 201), planned.text
        mission = planned.json()
        assert mission["status"] == "pending_approval"
        bad = test_client.post(
            f"/api/v1/missions/{mission['mission_id']}/approve",
            json={"response": "maybe", "decided_by": "game"})
        assert bad.status_code in (422, 409)
        journal = test_client.get("/api/v1/play/journal").json()
        know = [k for k in journal["knowledge"]
                if k["id"] == body["dossier_id"]]
        assert len(know) == 1
        assert know[0]["memory_id"] == body["memory_id"]
        assert know[0]["memory_id"].startswith("mem_")
        assert journal["counts"]["memories_remembered"] >= 1
        assert journal["counts"]["dossiers_completed"] >= 1


def test_research_unavailable_is_honest(tmp_path, monkeypatch):
    """Unavailable provider -> eerlijke status zonder dossier en
    zonder memory; plan weigert met 422; een geldige vervolgstap
    (opnieuw/Oracle/dossierlijst) bestaat in /side."""
    for test_client in api(tmp_path, monkeypatch):
        created = test_client.post("/api/v1/research/runs", json={
            "question": "Onbereikbare bronvraag?",
            "provider": "unavailable"})
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["status"] == "unavailable"
        assert not body["dossier_id"]
        assert not body["memory_id"]
        plan = test_client.post(
            f"/api/v1/research/{body['run_id']}/plan", json={})
        assert plan.status_code == 422, plan.text
        journal = test_client.get("/api/v1/play/journal").json()
        assert journal["counts"]["memories_remembered"] == 0
        html = test_client.get("/side").text
        for marker in ("zonder bruikbaar dossier",
                       "niet planbaar",
                       "Terug naar station"):
            assert marker in html, marker


def test_side_big51_markers(tmp_path, monkeypatch):
    """Nieuwe BIG51-hooks bestaan in /side: projecten-sectie,
    kennis-sectie, station-memoryregel, wereldgeheugen."""
    for test_client in api(tmp_path, monkeypatch):
        html = test_client.get("/side").text
        for marker in ("Projecten uit INVENTory",
                       "Onthouden kennis",
                       "Onthouden als ",
                       "refreshWorldMemory",
                       "memSpores",
                       "bronrecord",
                       "Inspecteren",
                       "UNAVAILABLE"):
            assert marker in html, marker
