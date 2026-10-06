"""BIG53 core loop backend: session-owned inventory, gather
(cooldown), craft (consume), place (consume + bounds). Game state
only — never backend records, nothing invented."""

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b53.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b53-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", "b53-operator")
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://127.0.0.1:9")
    with TestClient(main_mod.app) as test_client:
        yield test_client


def _session(test_client):
    return test_client.post("/api/v1/play/session", json={}).json()


def test_inventory_empty_shape(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        session = _session(test_client)
        body = test_client.get(
            "/api/v1/play/inventory",
            params={"session_id": session["session_id"]}).json()
        assert body["items"] == {}
        assert body["builds"] == []


def test_inventory_unknown_session_404(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        res = test_client.get("/api/v1/play/inventory",
                              params={"session_id": "play_nope"})
        assert res.status_code == 404
        for path, payload in (
                ("/api/v1/play/gather",
                 {"session_id": "play_nope", "node_id": "stump-1"}),
                ("/api/v1/play/craft",
                 {"session_id": "play_nope", "recipe": "stick"}),
                ("/api/v1/play/place",
                 {"session_id": "play_nope", "kind": "plank",
                  "x": 100, "y": 100})):
            assert test_client.post(path, json=payload).status_code == 404


def test_gather_yields_and_cools_down(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        session = _session(test_client)
        sid = session["session_id"]
        first = test_client.post("/api/v1/play/gather", json={
            "session_id": sid, "node_id": "stump-1"}).json()
        assert first["item"] == "wood" and first["qty"] == 1
        again = test_client.post("/api/v1/play/gather", json={
            "session_id": sid, "node_id": "stump-1"})
        assert again.status_code == 422
        assert "rust" in again.text
        other = test_client.post("/api/v1/play/gather", json={
            "session_id": sid, "node_id": "fiber-2"}).json()
        assert other["item"] == "fiber"
        bad = test_client.post("/api/v1/play/gather", json={
            "session_id": sid, "node_id": "dragon-9"})
        assert bad.status_code == 422


def test_craft_consumes_and_adds(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        session = _session(test_client)
        sid = session["session_id"]
        poor = test_client.post("/api/v1/play/craft", json={
            "session_id": sid, "recipe": "stick"})
        assert poor.status_code == 422
        assert "Not enough" in poor.text
        for node in ("stump-1", "stump-2"):
            test_client.post("/api/v1/play/gather", json={
                "session_id": sid, "node_id": node})
        made = test_client.post("/api/v1/play/craft", json={
            "session_id": sid, "recipe": "stick"}).json()
        assert made["crafted"] is True and made["qty"] == 1
        items = test_client.get(
            "/api/v1/play/inventory",
            params={"session_id": sid}).json()["items"]
        assert items.get("stick") == 1
        assert "wood" not in items
        unknown = test_client.post("/api/v1/play/craft", json={
            "session_id": sid, "recipe": "sword"})
        assert unknown.status_code == 422


def test_place_consumes_bounds_and_lists(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        session = _session(test_client)
        sid = session["session_id"]
        empty = test_client.post("/api/v1/play/place", json={
            "session_id": sid, "kind": "plank", "x": 100,
            "y": 100})
        assert empty.status_code == 422
        for node in ("stump-1", "stump-2", "stump-3"):
            test_client.post("/api/v1/play/gather", json={
                "session_id": sid, "node_id": node})
        test_client.post("/api/v1/play/craft", json={
            "session_id": sid, "recipe": "plank"})
        placed = test_client.post("/api/v1/play/place", json={
            "session_id": sid, "kind": "plank", "x": 5000,
            "y": -5}).json()
        assert placed["placed"] is True
        assert placed["x"] == 3840.0 and placed["y"] == 0.0
        assert placed["build_id"].startswith("bld_")
        body = test_client.get(
            "/api/v1/play/inventory",
            params={"session_id": sid}).json()
        assert "plank" not in body["items"]
        assert len(body["builds"]) == 1
        assert body["builds"][0]["kind"] == "plank"
        bad_kind = test_client.post("/api/v1/play/place", json={
            "session_id": sid, "kind": "house", "x": 1, "y": 1})
        assert bad_kind.status_code == 422


def test_side_big53_markers(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        html = test_client.get("/side").text
        for marker in ("play/inventory", "play/gather",
                       "play/craft", "play/place", "NODES",
                       "RECIPES", "renderInv", "puffer",
                       "doelen", "codex", "ghostClick",
                       "stage.onclick", "side-result"):
            assert marker in html, marker
