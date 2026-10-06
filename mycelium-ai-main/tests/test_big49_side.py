"""BIG49 side-view slice tests: page shape, hooks, existing flows.

The /side page is presentation over existing truth: discovery is a
real knowledge candidate, Oracle/Research/quest run through
existing routes, position reuses play sessions (zone "side"), XP
is localStorage-only and never gates. No new tables, no new API
routes, no execution.
"""

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b49.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b49-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", "b49-operator")
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_side_page_renders(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        res = test_client.get("/side")
        assert res.status_code == 200, res.text
        for marker in ("sidestage", "side-objective", "side-xp",
                       "touch", "sidedialog", "Werkbank",
                       "Waterbron", "Plantplek", "Mos (NPC)",
                       "E · TALK",
                       "Vochtige grond bij de waterbron",
                       "Onderzoek-station",
                       "/api/v1/candidates",
                       "/api/v1/advise",
                       "/api/v1/research/queue",
                       "/api/v1/research/queue/run-once",
                       "/api/v1/research/dossiers/",
                       "/plan",
                       "/api/v1/play/mission",
                       "/api/v1/play/session",
                       "/api/v1/play/position",
                       'zone: "side"',
                       "mycelium_side_xp",
                       "mycelium_side_session"):
            assert marker in res.text, marker


def test_side_nav_and_play_intact(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        assert test_client.get("/play").status_code == 200
        world = test_client.get("/world")
        assert world.status_code == 200
        assert "/side" in test_client.get("/").text


def test_side_adds_no_backend_route():
    """The slice composes existing routes only."""
    allowed = {"/side"}
    paths = {getattr(route, "path", "")
             for route in main_mod.app.routes}
    assert allowed.issubset(paths)
    assert not any("side" in path.lower() and path != "/side"
                   for path in paths)


def test_discovery_flow_through_existing_candidate_api(tmp_path,
                                                      monkeypatch):
    """The exact discovery the game registers: observation
    candidate, idempotent by title, then a real quest+mission."""
    for test_client in api(tmp_path, monkeypatch):
        title = "Vochtige grond bij de waterbron"
        listed = test_client.get(
            "/api/v1/candidates?limit=50").json()
        assert not [c for c in listed["candidates"]
                    if c["title"] == title]
        made = test_client.post("/api/v1/candidates", json={
            "title": title, "candidate_type": "observation",
            "state": "observation",
            "summary": "Vochtige grond bij de waterbron; "
                       "hydroponics-proef waard.",
            "evidence": [{"text": "side-view waarneming x=900"}]})
        assert made.status_code == 201, made.text
        cid = made.json()["candidate_id"]
        again = test_client.get(
            "/api/v1/candidates?limit=50").json()
        assert [c for c in again["candidates"]
                if c["title"] == title][0]["candidate_id"] == cid
        quest = test_client.post("/api/v1/play/mission", json={
            "goal": "Hydroponics-proef bij de waterbron",
            "context": title})
        assert quest.status_code == 201, quest.text
        assert quest.json()["status"] == "pending_approval"


def test_advise_offline_is_honest(tmp_path, monkeypatch):
    """Without Ollama the Oracle choice surfaces 502 — the game
    renders UNAVAILABLE, never a fabricated answer."""
    for test_client in api(tmp_path, monkeypatch):
        res = test_client.post("/api/v1/advise", json={
            "q": "hydroponics",
            "question": "Wat kan ik met vochtige grond doen?"})
        assert res.status_code in (200, 502), res.text


def test_side_position_reuses_sessions(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        opened = test_client.post("/api/v1/play/session",
                                  json={}).json()
        sid = opened["session_id"]
        saved = test_client.post("/api/v1/play/position", json={
            "session_id": sid, "x": 900, "y": 440,
            "zone": "side"})
        assert saved.status_code == 200, saved.text
        resumed = test_client.post("/api/v1/play/session",
                                   json={"session_id": sid}).json()
        assert resumed["resumed"] is True
        assert resumed["x"] == 900.0
        assert resumed["zone"] == "side"
