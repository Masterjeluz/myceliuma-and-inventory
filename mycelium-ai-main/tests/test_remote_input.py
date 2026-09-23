"""REMOTE INPUT SLICE 1 tests: real remote mouse movement.

E2E over the real API on tmp DBs (Fase H):

A node zonder remote.mouse -> refused
B offline node -> refused
C supported node -> connect
D invalid coordinate -> refused
E valid movement -> node ontvangt input (poll)
F movement gebruikt alleen allow-listed input operation
G geen shell/subprocess/arbitrary command in de node-adapter
H disconnect stopt verdere input
I onbekende node -> refused
J bestaande node/worker flow blijft groen (regressie apart)
K Digital World blijft werken
L Forge/workspace/research blijven leven (regressie apart)

Plus pure unit tests (sessie/expiry/latest-wins/consume) en een
live Windows-adaptertest die de cursor niet verplaatst (leest de
positie en beweegt erheen terug: echte SetCursorPos, geen effect).
"""

import asyncio
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.remote_input import (
    REGISTRY,
    RemoteInputGoneError,
    RemoteInputRefusedError,
    check_move,
    close_session,
    open_session,
    require_live,
    take_pending,
)
from node_client import remote_mouse
from node_client.remote_mouse import (
    MouseUnavailableError,
    check_coordinates,
    execute_remote_move,
    mouse_backend_available,
)

TOKEN = "remote-input-test-token-123456789"
MOUSE_CAP = "desktop.mouse.move"


@pytest.fixture(autouse=True)
def clean_registry():
    REGISTRY.clear()
    yield
    REGISTRY.clear()


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "ri.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "ri-chat.db"))
    with TestClient(main_mod.app) as client:
        yield client


def register(client, node_id="node-ri", capabilities=None,
             token=TOKEN):
    body = {"node_id": node_id, "hostname": node_id,
            "tier": "worker",
            "capabilities": capabilities if capabilities is not None
            else [MOUSE_CAP, "research.fetch"],
            "node_token": token}
    response = client.post("/api/v1/nodes/register", json=body)
    assert response.status_code == 201, response.text


def heartbeat(client, node_id="node-ri", token=TOKEN):
    return client.post(f"/api/v1/nodes/{node_id}/heartbeat",
                       json={"available": True, "node_token": token})


def connect(client, node_id="node-ri"):
    return client.post("/api/v1/remote-input/sessions",
                       json={"node_id": node_id})


def move(client, session_id, x, y):
    return client.post(
        f"/api/v1/remote-input/sessions/{session_id}/move",
        json={"x": x, "y": y})


def poll(client, node_id="node-ri", token=TOKEN):
    return client.post("/api/v1/remote-input/poll",
                       json={"node_id": node_id,
                             "node_token": token})


def stale_node(tmp_path, node_id="node-ri"):
    db = sqlite3.connect(str(tmp_path / "ri.db"))
    db.execute(
        "UPDATE nodes SET last_seen='2000-01-01T00:00:00+00:00' "
        "WHERE node_id=?", (node_id,))
    db.commit()
    db.close()


# -- A: zonder capability refused ----------------------------------------------

def test_a_node_without_mouse_capability_refused(tmp_path,
                                                 monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client, capabilities=["research.fetch"])
        assert heartbeat(client).status_code == 204
        response = connect(client)
        assert response.status_code == 403
        assert "desktop.mouse.move" in response.text


# -- B: offline node refused -----------------------------------------------------

def test_b_offline_node_refused(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        stale_node(tmp_path)
        assert connect(client).status_code == 403


# -- C: connect -------------------------------------------------------------------

def test_c_supported_node_connects(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        response = connect(client)
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["status"] == "open"
        assert data["node_id"] == "node-ri"
        assert len(data["session_id"]) >= 16
        # idempotent CONNECT: zelfde open sessie terug
        again = connect(client)
        assert again.status_code == 201
        assert again.json()["session_id"] == data["session_id"]
        # status-route leest mee
        status = client.get(
            f"/api/v1/remote-input/sessions/{data['session_id']}")
        assert status.status_code == 200
        assert status.json()["status"] == "open"


# -- D: invalid coordinates refused -------------------------------------------------

@pytest.mark.parametrize("x,y", [
    (-1, 100), (100, -1), (16385, 100), (100, 99999),
    (1.5, 100), (100, 2.5), ("100", 100), (100, None),
    (True, 100), (None, None),
])
def test_d_invalid_coordinates_refused(tmp_path, monkeypatch,
                                       x, y):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        response = move(client, session_id, x, y)
        assert response.status_code == 422, (x, y, response.text)


def test_d_malformed_and_oversized_refused(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        # extra velden zijn verboden (gesloten contract)
        response = client.post(
            f"/api/v1/remote-input/sessions/{session_id}/move",
            json={"x": 100, "y": 100, "click": True})
        assert response.status_code in (403, 422)
        # oversized input
        response = client.post(
            f"/api/v1/remote-input/sessions/{session_id}/move",
            json={"x": "9" * 5000, "y": 100})
        assert response.status_code == 422
        # onbekende sessie
        assert move(client, "nope" * 8, 100, 100).status_code == 404


# -- E: valid movement -> node poll ontvangt -----------------------------------------

def test_e_valid_move_reaches_node_poll(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        assert move(client, session_id, 800, 450).status_code == 204
        got = poll(client)
        assert got.status_code == 200
        data = got.json()
        assert data["move"]["x"] == 800 and data["move"]["y"] == 450
        assert data["session_id"] == session_id
        # consume-on-read: tweede poll is leeg (geen replay)
        assert poll(client).json() is None


def test_e_latest_wins_no_backlog(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        for point in [(10, 10), (20, 20), (30, 30)]:
            assert move(client, session_id, *point).status_code == 204
        data = poll(client).json()
        assert (data["move"]["x"], data["move"]["y"]) == (30, 30)
        assert data["move"]["seq"] == 3


def test_e_poll_requires_node_token(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        assert move(client, session_id, 1, 1).status_code == 204
        bad = client.post("/api/v1/remote-input/poll",
                          json={"node_id": "node-ri",
                                "node_token": "wrong-token-123456789"})
        assert bad.status_code == 403


# -- F/G: allow-listed operatie, geen shell ----------------------------------------------

class FakeMouse:
    name = "fake"
    # Expliciete test-double opt-in: alleen move, niets anders.
    can_move = True

    def __init__(self):
        self.moves = []

    def move(self, x, y):
        self.moves.append((x, y))


def test_f_only_allow_listed_move_operation():
    fake = FakeMouse()
    receipt = execute_remote_move(123, 456, adapter=fake)
    assert receipt == {"ok": True, "x": 123, "y": 456,
                       "backend": "fake"}
    assert fake.moves == [(123, 456)]
    # slice-2: de allow-list is bewust uitgebreid met
    # click/keyboard/scroll/drag/clipboard-methoden; verboden
    # blijven shell/exec/command-achtige operaties.
    for name in ("click", "button", "release", "scroll",
                 "key_press", "hotkey", "type_text",
                 "clipboard_write", "clipboard_read"):
        assert hasattr(remote_mouse.WindowsMouseAdapter, name), name
    for name in ("shell", "exec", "command", "run", "open_url",
                 "download", "upload", "key", "press"):
        assert not hasattr(remote_mouse.WindowsMouseAdapter, name), name
        assert not hasattr(remote_mouse.X11MouseAdapter, name), name


def test_g_no_shell_or_arbitrary_execution_in_adapter():
    import pathlib
    src = pathlib.Path(remote_mouse.__file__).read_text(
        encoding="utf-8")
    assert "import subprocess" not in src
    assert "shell=True" not in src
    assert "os.system" not in src
    assert "eval(" not in src
    assert "exec(" not in src
    assert "compile(" not in src


def test_node_side_coordinate_gate():
    assert check_coordinates(0, 0) == (0, 0)
    assert check_coordinates(16384, 16384) == (16384, 16384)
    for bad in [(-1, 0), (0, 16385), (1.5, 0), ("1", 0),
                (True, 0), (None, 0)]:
        with pytest.raises(MouseUnavailableError):
            check_coordinates(*bad)
    assert mouse_backend_available(
        adapter=remote_mouse.UnavailableMouseAdapter()) is False
    with pytest.raises(MouseUnavailableError):
        execute_remote_move(
            10, 10,
            adapter=remote_mouse.UnavailableMouseAdapter())


class _StubResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.content = b"{}" if payload is not None else b""
        self._payload = payload

    def json(self):
        return self._payload


class _StubClient:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self._status = status_code

    async def post(self, url, json=None):
        assert url.endswith("/remote-input/poll")
        return _StubResp(self._status, self._payload)


def run_coro(coro):
    """Drive one coroutine on a fresh loop in its own thread.

    (asyncio.run() collides with the TestClient portal loop in
    this thread; a helper thread keeps it deterministic.)
    """
    import threading
    outcome: dict = {}

    def _run():
        outcome["result"] = asyncio.new_event_loop(
            ).run_until_complete(coro)

    worker = threading.Thread(target=_run)
    worker.start()
    worker.join(timeout=30)
    assert not worker.is_alive()
    return outcome["result"]


def test_e_node_loop_executes_polled_move(monkeypatch):
    import node_client.main as node_main
    fake = FakeMouse()

    def _fake_execute(x, y):
        fake.move(x, y)
        return {"ok": True, "x": x, "y": y, "backend": "fake"}

    monkeypatch.setattr(
        "node_client.remote_mouse.execute_remote_move", _fake_execute)
    receipt = run_coro(node_main.poll_remote_input_once(
        _StubClient({"move": {"x": 321, "y": 654, "seq": 1},
                     "actions": [], "clipboard_request": False}),
        "http://x/api/v1", "node-ri", None))
    assert receipt["move"] == {"ok": True, "x": 321, "y": 654,
                               "backend": "fake"}
    assert receipt["actions"] == []
    assert fake.moves == [(321, 654)]
    # lege poll: geen executie
    assert run_coro(node_main.poll_remote_input_once(
        _StubClient(None), "http://x/api/v1",
        "node-ri", None)) is None
    assert fake.moves == [(321, 654)]
    # gesloten sessie: 410-summary met release-check, geen executie
    gone = run_coro(node_main.poll_remote_input_once(
        _StubClient(None, 410), "http://x/api/v1",
        "node-ri", None))
    assert gone["move"] is None
    assert gone["actions"] == []
    assert gone["released"] is None
    assert fake.moves == [(321, 654)]


@pytest.mark.skipif(os.name != "nt",
                    reason="live Windows adapter only")
def test_live_windows_adapter_moves_to_current_position():
    """Echte SetCursorPos zonder zichtbaar effect: lees de cursor,
    beweeg erheen terug. Bewijst dat het echte OS-pad werkt.

    De machine wordt live gebruikt: een menselijke
    muisactie (drag/menu) kan SetCursorPos tijdelijk weigeren.
    Daarom bounded retries; persistente weigering faalt de test.
    """
    import ctypes
    import time as _time
    assert remote_mouse.mouse_backend_available() is True

    class _Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    last_error: Exception | None = None
    for _ in range(8):
        point = _Point()
        assert ctypes.windll.user32.GetCursorPos(
            ctypes.byref(point))
        try:
            receipt = execute_remote_move(point.x, point.y)
            break
        except Exception as error:
            last_error = error
            _time.sleep(0.25)
    else:
        raise AssertionError(
            f"live SetCursorPos persistently refused: {last_error}")
    assert receipt["ok"] is True
    assert receipt["backend"] == "windows"
    assert (receipt["x"], receipt["y"]) == (point.x, point.y)


# -- H: disconnect stopt input -----------------------------------------------------------

def test_h_disconnect_stops_input(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        assert move(client, session_id, 5, 5).status_code == 204
        closed = client.post(
            f"/api/v1/remote-input/sessions/{session_id}/close")
        assert closed.status_code == 200
        assert closed.json()["status"] == "closed"
        # verdere moves geweigerd
        after = move(client, session_id, 6, 6)
        assert after.status_code in (403, 410)
        # poll na close: 410 Gone (release-signaal voor drag;
        # slice-2 compat: nooit meer stil null na close)
        assert poll(client).status_code == 410
        # status-route toont gesloten
        status = client.get(
            f"/api/v1/remote-input/sessions/{session_id}")
        assert status.json()["status"] == "closed"


def test_h_stale_node_auto_closes_session(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        stale_node(tmp_path)
        # move op dode node: sessie sluit, input geweigerd
        assert move(client, session_id, 7, 7).status_code == 403
        assert poll(client).status_code == 410


# -- I: onbekende node ----------------------------------------------------------------------

def test_i_unknown_node_refused(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert connect(client, node_id="ghost-node").status_code == 404
        bad = client.post("/api/v1/remote-input/poll",
                          json={"node_id": "ghost-node",
                                "node_token": TOKEN})
        assert bad.status_code == 404


# -- K: Digital World blijft werken --------------------------------------------------------------

def test_k_digital_world_still_works(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        world = client.get("/api/v1/digital-world").json()
        assert world["node_count"] == 1
        entry = world["nodes"][0]
        assert entry["remote_mouse"] == "supported"
        assert MOUSE_CAP in entry["capabilities"]
        page = client.get("/nodes").text
        assert "Digital World" in page
        assert "REMOTE CONTROL" in page
        assert "dw-connect" in page
        assert "dw-pad" in page
        assert "dw-disconnect" in page
        assert "remote mouse: supported" in page


def test_k_unsupported_node_ui_marks(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client, node_id="plain",
                 capabilities=["research.fetch"])
        world = client.get("/api/v1/digital-world").json()
        assert world["nodes"][0]["remote_mouse"] == "unsupported"
        page = client.get("/nodes").text
        assert "remote mouse: unsupported" in page


# -- L: Forge/workspace/research leven nog ------------------------------------------------------------

def test_l_flows_alive(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.get("/forge").status_code == 200
        assert client.get("/api/v1/game/state").status_code == 200
        assert client.get(
            "/api/v1/workspaces").status_code == 200


# -- pure unit tests -------------------------------------------------------------------------

def test_session_lifecycle_pure():
    session = open_session("node-ri", now=1000.0)
    assert session.status == "open"
    first = check_move(session, 10, 20, now=1001.0)
    assert (first["x"], first["y"], first["seq"]) == (10, 20, 1)
    second = check_move(session, 30, 40, now=1002.0)
    assert second["seq"] == 2
    taken = take_pending(session, now=1003.0)
    assert (taken["x"], taken["y"]) == (30, 40)
    assert take_pending(session, now=1004.0) is None
    close_session(session)
    with pytest.raises(RemoteInputGoneError):
        require_live(session, now=1005.0)


def test_expiry_absolute_and_idle():
    session = open_session("node-ri", now=0.0)
    with pytest.raises(RemoteInputGoneError):
        require_live(session, now=601.0)
    session = open_session("node-ri", now=0.0)
    with pytest.raises(RemoteInputGoneError):
        require_live(session, now=121.0)
    fresh = open_session("node-ri", now=0.0)
    with pytest.raises(RemoteInputRefusedError):
        check_move(fresh, "x", 0, now=0.0)


def test_session_id_unpredictable():
    ids = {open_session("n", now=0.0).session_id for _ in range(5)}
    assert len(ids) == 5
    assert all(len(item) >= 16 for item in ids)
