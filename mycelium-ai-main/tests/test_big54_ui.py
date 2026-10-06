"""BIG54 game UI cleanup: world-first presentation over the
unchanged BIG53 game. No backend changes: same routes, same
flows, same gates — only layout, HUD, verbs and visuals."""

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b54.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b54-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", "b54-operator")
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://127.0.0.1:9")
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_side_world_first_layout(tmp_path, monkeypatch):
    """Canvas dominant, HUD als overlay, dashboardlinks ingeklapt
    — alle bestaande ids en hooks behouden."""
    for test_client in api(tmp_path, monkeypatch):
        html = test_client.get("/side").text
        for marker in ("side-area", "side-hud-top",
                       "side-hud-bottom", "side-web",
                       "Mycelium-web", "<details",
                       "levende wereld", "dayTint"):
            assert marker in html, marker
        for anchor in ("sidestage", "side-objective",
                       "side-xp", "side-inv", "side-goals",
                       "side-prompt", "journal-open", "touch",
                       "sidedialog", "side-result",
                       "mycelium_side_xp",
                       "mycelium_side_session"):
            assert anchor in html, anchor
        # canvas komt voor de dialoog: wereld eerst.
        assert html.index("sidestage") < html.index("sidedialog")
        # dashboardlinks bestaan maar niet als permanente lijst.
        for href in ('href="/play"', 'href="/knowledge"',
                     'href="/research"', 'href="/quests"'):
            assert href in html, href


def test_side_interaction_verbs(tmp_path, monkeypatch):
    """Werkwoorden in prompts, labels en HUD — geen nieuwe flows."""
    for test_client in api(tmp_path, monkeypatch):
        html = test_client.get("/side").text
        for marker in ("Verzamel", "Gebruik werkbank",
                       "Open codex", "E · Werkbank",
                       "E · Codex", "E · TALK",
                       "E · Verzamel", "[✓]", '" × "',
                       "Houtstronk", "Vezelplant"):
            assert marker in html, marker


def test_side_observations_and_hermes_presence(tmp_path,
                                               monkeypatch):
    """Waarnemingen-dialoog en Hermes-statushaak bestaan in /side;
    data komt uitsluitend uit bestaande routes."""
    for test_client in api(tmp_path, monkeypatch):
        html = test_client.get("/side").text
        for marker in ("Waarnemingen", "renderObservations",
                       "/api/v1/world/observations",
                       "geen eigendom",
                       "/api/v1/hermes/status",
                       "Hermes-agent",
                       "/world?entity_id="):
            assert marker in html, marker


def test_side_vertical_slice_markers(tmp_path, monkeypatch):
    """Infinity-lus, Mos live-card, Missie-0, ruimtekaart en
    multi-node-convergentie bestaan als hooks; data blijft uit
    bestaande read-only routes komen."""
    for test_client in api(tmp_path, monkeypatch):
        html = test_client.get("/side").text
        for marker in ("renderMosLive", "moslive", "Missie 0",
                       "Mycelium-lus", "gomos",
                       "Ruimtekaart", "convergeOf",
                       "Waargenomen door",
                       "/api/v1/vision/capabilities"):
            assert marker in html, marker


def test_side_no_new_backend_routes():
    """Cleanup voegt geen routes toe: alleen /side + play_*."""
    paths = {getattr(route, "path", "")
             for route in main_mod.app.routes}
    assert "/side" in paths
    assert not any("side" in path.lower() and path != "/side"
                   for path in paths)
    for path in ("/api/v1/play/inventory",
                 "/api/v1/play/gather",
                 "/api/v1/play/craft",
                 "/api/v1/play/place"):
        assert path in paths, path


def test_game_loop_still_works(tmp_path, monkeypatch):
    """Backend ongemoeid: gather → craft → place via API."""
    for test_client in api(tmp_path, monkeypatch):
        sid = test_client.post(
            "/api/v1/play/session", json={}).json()["session_id"]
        for node in ("stump-1", "fiber-1", "rock-1"):
            res = test_client.post("/api/v1/play/gather", json={
                "session_id": sid, "node_id": node})
            assert res.status_code == 200, res.text
        for node in ("stump-2", "stump-3"):
            test_client.post("/api/v1/play/gather", json={
                "session_id": sid, "node_id": node})
        made = test_client.post("/api/v1/play/craft", json={
            "session_id": sid, "recipe": "torch"})
        # torch needs stick+vezel: alleen hout+vezel+steen hier
        assert made.status_code == 422
        plank = test_client.post("/api/v1/play/craft", json={
            "session_id": sid, "recipe": "plank"}).json()
        assert plank["crafted"] is True
        placed = test_client.post("/api/v1/play/place", json={
            "session_id": sid, "kind": "plank", "x": 1160,
            "y": 472}).json()
        assert placed["placed"] is True
        body = test_client.get(
            "/api/v1/play/inventory",
            params={"session_id": sid}).json()
        assert len(body["builds"]) == 1


def test_side_routes_intact(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        for path in ("/", "/play", "/world", "/side"):
            assert test_client.get(path).status_code == 200, path
