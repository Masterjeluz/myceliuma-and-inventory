"""SP Home Base 3D (/homebase): procedureel Three.js-pand.

Render tests over tmp databases: pagina-vorm, importmap +
gebouw-markers, eerlijke fallback, geen formulieren, geen
backend-writes, geen mutatie-routes.
"""
import sqlite3
from contextlib import contextmanager

import coordinator.app.main as main_mod
from coordinator.app import homebase as homebase_mod


@contextmanager
def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "queue.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "chat.db"))
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "fab"))
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://127.0.0.1:9")
    with TestClient(main_mod.app) as client:
        yield client


def test_homebase_page_shape(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        res = client.get("/homebase")
        assert res.status_code == 200
        assert "SP Home Base" in res.text
        assert 'id="hb-3d"' in res.text
        assert "importmap" in res.text and "three@0.160.0" in res.text
        assert "OrbitControls" in res.text
        assert "/solarpunk" in res.text  # terug naar de stad
        assert "3D unavailable" in res.text  # eerlijke fallback
        assert "<form" not in res.text


def test_homebase_building_markers():
    """Foto-kenmerken zitten in de code: dubbele tuitgevel, ramen,
    baksteen, dakpannen, hoekopzet met regenpijp en zijdeur."""
    js = homebase_mod.HOMEBASE_JS
    for marker in ("gableRoof", "brickTexture", "roofTexture",
                   "windowUnit", "ridge", "pipe", "sdoor",
                   "attic", "cobbleTexture"):
        assert marker in js, marker
    assert "shell=True" not in js  # geen schelp, geen netwerk in JS


def test_homebase_no_mutation_routes():
    for route in main_mod.app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/homebase"):
            methods = getattr(route, "methods", set()) or set()
            assert methods <= {"GET", "HEAD", "OPTIONS"}, methods


def test_homebase_no_backend_writes(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        before = {}
        import glob as _glob
        for db_file in _glob.glob(str(tmp_path / "*.db")):
            con = sqlite3.connect(db_file)
            try:
                before[db_file] = {
                    row[0]: con.execute(
                        f'SELECT COUNT(*) FROM "{row[0]}"').fetchone()[0]
                    for row in con.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table'")}
            finally:
                con.close()
        client.get("/homebase")
        import glob as _glob2
        for db_file in _glob2.glob(str(tmp_path / "*.db")):
            con = sqlite3.connect(db_file)
            try:
                tables = [row[0] for row in con.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table'")]
                assert not any(
                    key in name.lower() for name in tables
                    for key in ("homebase", "house", "building")), tables
                for table in tables:
                    if table in before.get(db_file, {}):
                        now = con.execute(
                            f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                        assert now == before[db_file][table], (table, now)
            finally:
                con.close()
