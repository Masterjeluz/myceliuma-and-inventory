"""Solar Punk City (/solarpunk): levende stad voor agents.

Render tests over tmp databases: pagina-vorm, eerlijk offline-paneel,
movement-loop (WASD/pijltjes, fetch + localStorage zoals de /side
game loop), town-chat + bureau (formulieren alleen daar, nooit onder
/solarpunk zelf: geen mutatie-routes op het pad). Deterministische
layout wordt op unit-niveau bewezen.
"""
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import coordinator.app.main as main_mod
from coordinator.app import solarpunk as solarpunk_mod


@contextmanager
def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "queue.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "chat.db"))
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "fab"))
    # Dode poort: wereld-store eerlijk offline, nooit echte traffic.
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://127.0.0.1:9")
    with TestClient(main_mod.app) as client:
        yield client


def _districts():
    return solarpunk_mod.district_payload([
        SimpleNamespace(entity_id="loc_garden", title="Garden",
                        snippet="green"),
        SimpleNamespace(entity_id="loc_market", title="Market",
                        snippet="trade"),
        SimpleNamespace(entity_id="loc_workshop", title="Workshop",
                        snippet="build"),
    ])


def test_solarpunk_offline_is_honest(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        res = client.get("/solarpunk")
        assert res.status_code == 200
        assert "Solar Punk City" in res.text
        assert "World store offline" in res.text
        assert "Traceback" not in res.text


def test_solarpunk_nav_present(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        res = client.get("/solarpunk")
        assert "/solarpunk" in res.text  # nav entry present
        world = client.get("/world")
        assert world.status_code == 200  # /world unchanged


def test_solarpunk_walk_view(tmp_path, monkeypatch):
    """Fase 2: first-person canvas + bird's eye + werelddata aanwezig.
    Fetch/localStorage zijn toegestaan voor de movement-loop (zelfde
    categorie als de /side game loop); formulieren blijven verboden."""
    with _client(tmp_path, monkeypatch) as client:
        res = client.get("/solarpunk")
        assert 'id="spc-view"' in res.text
        assert 'id="spc-map"' in res.text
        assert 'id="spc-world"' in res.text
        assert "requestAnimationFrame" in res.text
        assert "<form" not in res.text
        # Homebase staat ín de stad: zelfde 3D-pand embedded.
        assert 'id="hb-3d"' in res.text
        assert "importmap" in res.text and "three@0.160.0" in res.text
        assert "gableRoof" in res.text
        # Fase 5: solar-spawn met vrij uitzicht + muis-look +
        # proximiteitsbalk + NPC-sprites in de raycaster.
        assert "SOLAR_SPAWN" in res.text
        assert "pointerdown" in res.text
        assert 'id="spc-near"' in res.text
        assert "spcDrawActors" in res.text
        # In-game praat-HUD: bij de bewoner praten zonder te
        # scrollen (zelfde town-gesprek via spcSay).
        assert 'id="spc-hud"' in res.text
        assert 'id="spc-hud-send"' in res.text
        assert 'id="spc-hud-reply"' in res.text
        assert "spcSay" in res.text


def test_inline_js_has_no_escaped_quotes():
    """Regressie: \\" in een *_JS-bron wordt na Python-parsing
    een kale quote in de geserveerde JS en breekt het hele
    blok (zo stierf ACTORS_JS: geen NPC's, geen dots, geen
    balk — onzichtbaar voor node --check op de bron)."""
    import pathlib as _pathlib
    import re as _re
    src = _pathlib.Path(
        "coordinator/app/solarpunk.py").read_text(
        encoding="utf-8")
    blocks = _re.findall(
        r"^(?:SOLARPUNK_JS|SCAN_JS|TOWN_JS|ACTORS_JS|"
        r"BUREAU_JS) = \"\"\"(.*?)\"\"\"",
        src, _re.S | _re.M)
    assert len(blocks) == 5, len(blocks)
    for block in blocks:
        assert '\\"' not in block
        assert "\\'" not in block


def test_solarpunk_no_mutation_routes():
    """Er bestaat geen POST/PUT/PATCH/DELETE onder /solarpunk."""
    for route in main_mod.app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/solarpunk"):
            methods = getattr(route, "methods", set()) or set()
            assert methods <= {"GET", "HEAD", "OPTIONS"}, methods


def test_solarpunk_no_backend_writes(tmp_path, monkeypatch):
    """Hitting /solarpunk bewaart niets van zichzelf: geen eigen
    tabellen/kolommen (lazy shared-shell-inits tellen niet mee) en
    geen recordgroei in bestaande tabellen."""
    with _client(tmp_path, monkeypatch) as client:
        before = {}
        import glob as _glob
        for db_file in _glob.glob(str(tmp_path / "*.db")):
            con = sqlite3.connect(db_file)
            try:
                tables = [row[0] for row in con.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table'")]
                before[db_file] = {
                    name: con.execute(
                        f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                    for name in tables
                }
            finally:
                con.close()
        client.get("/solarpunk")
        client.get("/solarpunk")
        import glob as _glob2
        for db_file in _glob2.glob(str(tmp_path / "*.db")):
            con = sqlite3.connect(db_file)
            try:
                tables = [row[0] for row in con.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table'")]
                assert not any(
                    key in name.lower()
                    for name in tables
                    for key in ("solarpunk", "city", "district")), tables
                for table in tables:
                    cols = [row[1] for row in con.execute(
                        f"PRAGMA table_info({table})")]
                    assert not any(
                        key in col.lower()
                        for col in cols
                        for key in ("solarpunk", "district")), (table, cols)
                    if table in before.get(db_file, {}):
                        now = con.execute(
                            f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                        assert now == before[db_file][table], (table, now)
            finally:
                con.close()


def test_render_districts_deterministic():
    """Zelfde input -> zelfde SVG-posities; titels escaped."""
    first = solarpunk_mod.render(_districts())
    second = solarpunk_mod.render(_districts())
    assert first == second
    assert "Garden" in first and "loc_market" in first
    assert "<svg" in first and 'class="district"' in first
    evil = solarpunk_mod.render(solarpunk_mod.district_payload(
        [SimpleNamespace(entity_id="loc_x", title="<script>",
                         snippet="")]))
    assert "&lt;script&gt;" in evil  # titel ge-escaped in HTML
    payload = evil.split('id="spc-world">')[1].split("</script>")[0]
    assert "</script" not in payload  # geen JSON-breakout mogelijk


def test_world_payload_scaled_and_bounded():
    """Wereld-rects: deterministisch, binnen 3840x1400, titels mee."""
    first = solarpunk_mod.world_payload(_districts())
    assert first == solarpunk_mod.world_payload(_districts())
    assert len(first) == 3
    for rect in first:
        assert 0 <= rect["x"] <= 3840 and 0 <= rect["y"] <= 1400
        assert rect["w"] > 0 and rect["h"] > 0
        assert rect["x"] + rect["w"] <= 3840
        assert rect["y"] + rect["h"] <= 1400
    assert [r["title"] for r in first] == ["Garden", "Market", "Workshop"]


def test_solarpunk_position_roundtrip(tmp_path, monkeypatch):
    """Hergebruik bestaande play-sessie: openen, zone solarpunk
    bewaren, clampen op wereldranden, throttle, onbekende sessie 404.
    Kijkrichting (a) gaat mee, wrapt naar [0, 2pi) en blijft staan
    als de caller geen angle stuurt (/side stuurt er geen)."""
    with _client(tmp_path, monkeypatch) as client:
        opened = client.post("/api/v1/play/session", json={})
        assert opened.status_code == 200
        session = opened.json()["session_id"]
        assert opened.json()["a"] == 0.0
        moved = client.post("/api/v1/play/position", json={
            "session_id": session, "x": 1200, "y": 700,
            "a": 1.5, "zone": "solarpunk"})
        assert moved.status_code == 200
        body = moved.json()
        assert body["saved"] is True
        assert body["x"] == 1200 and body["zone"] == "solarpunk"
        assert body["a"] == 1.5
        resumed = client.post(
            "/api/v1/play/session",
            json={"session_id": session}).json()
        assert resumed["a"] == 1.5
        wrapped = client.post("/api/v1/play/session", json={})
        wrap_session = wrapped.json()["session_id"]
        over = client.post("/api/v1/play/position", json={
            "session_id": wrap_session, "x": 1200, "y": 700,
            "a": 7.0, "zone": "solarpunk"})
        assert over.status_code == 200
        import math as _math
        assert over.json()["a"] == (
            7.0 % (2.0 * _math.pi))
        bad = client.post("/api/v1/play/position", json={
            "session_id": wrap_session, "x": 1200, "y": 700,
            "a": "oost", "zone": "solarpunk"})
        assert bad.status_code == 422
        kept = client.post("/api/v1/play/position", json={
            "session_id": wrap_session, "x": 1300, "y": 700,
            "zone": "solarpunk"})
        assert kept.status_code == 200
        assert kept.json()["saved"] is False  # <2s: bewaard, niet geschreven
        assert kept.json()["x"] == 1200
        assert kept.json()["a"] == over.json()["a"]
        fresh = client.post("/api/v1/play/session", json={}).json()
        clamped = client.post("/api/v1/play/position", json={
            "session_id": fresh["session_id"], "x": 99999, "y": -5,
            "zone": "solarpunk"})
        assert clamped.status_code == 200
        assert clamped.json()["x"] == 3840
        assert clamped.json()["y"] == 0
        unknown = client.post("/api/v1/play/position", json={
            "session_id": "no-such-session", "x": 1, "y": 1})
        assert unknown.status_code == 404


def test_home_landmark_near_spawn_and_bounded():
    """SP Home Base: binnen de wereld, naast de spawn (800,500)."""
    home = solarpunk_mod.home_landmark()
    assert home["title"] == "SP Home Base"
    assert home["home"] is True
    assert 0 <= home["x"] and home["x"] + home["w"] <= 3840
    assert 0 <= home["y"] and home["y"] + home["h"] <= 1400
    assert abs((home["x"] + home["w"] / 2) - 800) < 400
    assert abs((home["y"] + home["h"] / 2) - 500) < 400
    assert solarpunk_mod.HOME_BASE["wall"] == "#8a4030"


def test_home_visible_in_all_views(tmp_path, monkeypatch):
    """Home in SVG-kaart, wereld-JSON en als botser voor de 3D-view."""
    with _client(tmp_path, monkeypatch) as client:
        res = client.get("/solarpunk")
        assert "SP Home Base" in res.text
        assert "#8a4030" in res.text  # baksteen in SVG
        payload = res.text.split('id="spc-world">')[1].split(
            "</script>")[0]
        assert '"home": true' in payload


def test_residents_panel_lists_npcs_honestly(tmp_path, monkeypatch):
    """Zes bewoners met rol + eerlijke slaap-status (geen key)."""
    monkeypatch.delenv("HERMES_API_KEY", raising=False)
    with _client(tmp_path, monkeypatch) as client:
        res = client.get("/solarpunk")
        assert res.status_code == 200
        assert "Residents" in res.text
        for name in ("Mos", "Orakel", "Smid", "Archivaris",
                     "Voorman", "Seinwachter"):
            assert name in res.text, name
        assert "slaapt" in res.text
