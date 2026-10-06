"""BIG52: resterende weg als questlijn (F3-F5), F3-werkbank
read-only, TEST-provenance. Bestaande modellen/routes only: geen
tweede backlog, geen Quest/Mission-records, geen POST vanuit de
werkbank, geen verzonnen voltooiing."""

import re

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

PAGES = {
    "hydro": ["Hydroponics proef",
              "Vochtige grond naast een waterbron is geschikt "
              "voor hydroponics. Wortels nemen water op."],
}

FAB_STATES = {"REAL", "SIMULATED", "BLOCKED", "UNAVAILABLE"}


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b52.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b52-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", "b52-operator")
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://127.0.0.1:9")
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_journal_roadmap_lists_f3_f5(tmp_path, monkeypatch):
    """Resterende weg: F3/F4/F5 als questlijn-VIEW — geen records,
    wel bron, status en bestaande route per item; F3 met live
    ketentelling als bewijs."""
    for test_client in api(tmp_path, monkeypatch):
        body = test_client.get("/api/v1/play/journal").json()
        road = {item["id"]: item for item in body["roadmap"]}
        assert set(road) == {"gap-F3", "gap-F4", "gap-F5"}
        for item in road.values():
            assert item["kind"] == "roadmap"
            assert item["status"] in ("open", "in uitvoering")
            assert item["source"].startswith("GAPMATRIX")
            assert item["href"].startswith("/")
            assert item["action"]["method"] == "GET"
        assert "keten live:" in road["gap-F3"]["why"]
        assert body["counts"]["roadmap_open"] == 3


def test_knowledge_origin_test_is_explicit(tmp_path, monkeypatch):
    """TEST-dossier + memory blijven als proef herkenbaar in
    Journal (origin + telling); REAL wordt nooit geclaimd."""
    for test_client in api(tmp_path, monkeypatch):
        created = test_client.post("/api/v1/research/runs", json={
            "question": "Welke hydroponics-aanpak past bij "
                        "vochtige grond?",
            "provider": "test", "test_pages": PAGES})
        assert created.status_code == 201, created.text
        dossier_id = created.json()["dossier_id"]
        journal = test_client.get("/api/v1/play/journal").json()
        know = [k for k in journal["knowledge"]
                if k["id"] == dossier_id]
        assert len(know) == 1
        assert know[0]["origin"] != "REAL"
        assert "Proefherkomst" in know[0]["why"]
        assert "nooit feit" in know[0]["why"]
        assert journal["counts"]["memories_test"] >= 1
        assert journal["counts"]["memories_real"] == 0


def test_research_regression_still_holds(tmp_path, monkeypatch):
    """BIG50-regel behouden: draft zonder dossier -> 422."""
    for test_client in api(tmp_path, monkeypatch):
        run = test_client.post("/api/v1/research/queue", json={
            "question": "Onplanbare vraag zonder dossier?"}).json()
        plan = test_client.post(
            f"/api/v1/research/{run['run_id']}/plan", json={})
        assert plan.status_code == 422, plan.text
        assert "dossier" in plan.text.lower()


def test_play_status_fabrication_states(tmp_path, monkeypatch):
    """Keten gebruikt alleen echte toestanden; execution is
    nooit REAL-claim zonder printervoltooiing."""
    for test_client in api(tmp_path, monkeypatch):
        status = test_client.get("/api/v1/play/status").json()
        chain = status["fabrication"]
        assert len(chain) >= 10
        states = {step["state"] for step in chain}
        assert states <= FAB_STATES, states
        assert "REAL" in states  # bestaande stores werken echt
        assert "SIMULATED" in states  # slicer eerlijk gelabeld
        by_step = {step["step"]: step for step in chain}
        assert by_step["execution"]["state"] in ("UNAVAILABLE",
                                                 "BLOCKED")
        for step in chain:
            assert step["step"] and step["via"]


def test_workbench_starts_nothing(tmp_path, monkeypatch):
    """Werkbank-JS doet alleen GET-reads; geen propose/execute/
    inspect/dispatch-POST, wel keten, legenda en deeplinks."""
    for test_client in api(tmp_path, monkeypatch):
        html = test_client.get("/side").text
        for marker in ("renderBench", "FAB_NEXT",
                       "fabricageketen", "Legenda",
                       "SIMULATED", "geen knop",
                       "eerlijk leeg", "/workshop/3d",
                       "/fabrication"):
            assert marker in html, marker
        bench = html.split("async function renderBench()")[1].split(
            "async function doDiscover()")[0]
        assert bench.count("postJSON") == bench.count('"GET"')
        for forbidden in ("prints/propose", "/inspect",
                          "/execute", "/dispatch", "/drive",
                          "gcode_ref"):
            assert forbidden not in bench, forbidden


def test_workbench_links_resolve(tmp_path, monkeypatch):
    """Alle pagina's waar werkbank en roadmap heen linken
    bestaan (/, /play, /world, /side + bench-doelen)."""
    for test_client in api(tmp_path, monkeypatch):
        # /cameras bewust uitgesloten: echte Windows-detectie via
        # ctypes crasht native in dit testproces (pre-existing,
        # los van deze slice; linkdoel blijft bestaan).
        for path in ("/", "/play", "/world", "/side",
                     "/fabrication", "/workshop/3d", "/automation",
                     "/canvas", "/approvals", "/projects",
                     "/knowledge", "/writes",
                     "/activity", "/forge", "/workshop"):
            res = test_client.get(path)
            assert res.status_code == 200, path


def test_side_big52_markers(tmp_path, monkeypatch):
    """Roadmap-sectie, herkomst-chip en TEST-labels in /side
    (statische JS-markers; hoofdletter-Proefherkomst leeft in
    API-why, getest in test_knowledge_origin_test_is_explicit)."""
    for test_client in api(tmp_path, monkeypatch):
        html = test_client.get("/side").text
        for marker in ("Resterende weg", "herkomst: ",
                       "proefherkomst",
                       "TEST-proef", "FAB_MEANING",
                       "worldMemoryTest", "Onthouden als "):
            assert marker in html, marker
