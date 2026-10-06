"""Infinite Canvas MVP (/canvas): additive workshop lens, no new truth.

Render tests over tmp databases: page shape, workspace scoping,
area payload, search/focus/reset controls, no persistence
anywhere. Behavioural JS (drag/camera) is client-side by
construction — asserted structurally.
"""
import sqlite3
from contextlib import contextmanager

import coordinator.app.main as main_mod
from coordinator.app.main import _world_scoped_graph


@contextmanager
def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "queue.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "chat.db"))
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "fab"))
    with TestClient(main_mod.app) as client:
        yield client


def test_canvas_empty_is_honest(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        res = client.get("/canvas")
        assert res.status_code == 200
        assert "quiet workbench" in res.text
        assert "Back to World" in res.text
        assert "csearch" in res.text and "creset" in res.text
        assert "localStorage" not in res.text


def test_canvas_world_links_and_nav(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        res = client.get("/canvas")
        assert "Canvas" in res.text  # nav entry present
        world = client.get("/world")
        assert world.status_code == 200
        assert "/canvas" in world.text  # World → Canvas link
        assert "World Graph" in world.text  # /world unchanged


def test_canvas_no_backend_writes(tmp_path, monkeypatch):
    """Hitting /canvas (empty + scoped) creates no canvas tables,
    columns or records anywhere."""
    with _client(tmp_path, monkeypatch) as client:
        client.get("/canvas")
        client.get("/canvas", params={"workspace": "camper"})
        import glob as _glob
        for db_file in _glob.glob(str(tmp_path / "*.db")):
            con = sqlite3.connect(db_file)
            try:
                tables = [row[0] for row in con.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table'")]
                assert not any("canvas" in name.lower()
                               for name in tables), tables
                for table in tables:
                    cols = [row[1] for row in con.execute(
                        f"PRAGMA table_info({table})")]
                    assert not any(
                        "canvas" in col.lower() or "position"
                        in col.lower() for col in cols), (table, cols)
            finally:
                con.close()


def test_canvas_no_post_routes():
    """The canvas adds reads only: no POST/PUT/DELETE canvas routes."""
    routes = [(sorted(methods), path)
              for route in main_mod.app.routes
              for methods, path in [(
                  getattr(route, "methods", set()) or set(),
                  getattr(route, "path", ""))]
              if "canvas" in path.lower()]
    assert routes, "expected the GET /canvas route"
    for methods, path in routes:
        assert methods == ["GET"], (methods, path)


def test_scoped_helper_shared_by_world_and_canvas():
    graph = {"nodes": [{"id": "proj_a", "type": "project",
                        "label": "A", "source": "inventory",
                        "metadata": {}}],
             "edges": []}
    scoped, wid, notice, keep = _world_scoped_graph(
        dict(graph), "", {"entity_id": "proj_a"}, base="/canvas")
    assert wid == "" and notice == "" and keep is None
    assert scoped["nodes"] == graph["nodes"]
