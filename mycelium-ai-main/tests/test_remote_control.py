"""REMOTE CONTROL SLICE 2 tests: click/keyboard/scroll/drag/clipboard.

Matrix (taak A–R):

A capability discovery (derive markeert per capability)
B unsupported capability weigert
C session required (input zonder sessie / move-route analogue)
D stale node weigert
E disconnect weigert
F invalid payload weigert
G extra payload fields weigeren
H session expiry
I click execution (fake adapter + contract)
J keyboard execution (fake adapter + allow-list)
K scroll execution (fake adapter, verticaal-only)
L drag lifecycle (down/move/up + fifo-volgorde)
M clipboard (set + request/read, text-only)
N disconnect tijdens actieve actie (410 + emergency release)
O bestaande mouse blijft werken
P Digital World blijft werken (per-capability UI)
Q Forge blijft werken
R workspaces blijven werken

Plus pure unit tests en node-adapter tests (fake backend).
Echte OS-executie gebeurt in FASE F (live Windows).
"""

import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.remote_input import (
    REGISTRY,
    RemoteInputGoneError,
    RemoteInputRefusedError,
    capability_for_kind,
    check_clipboard_text,
    check_input_action,
    open_session,
    queue_action,
)
from node_client import remote_mouse
from node_client.remote_mouse import (
    ButtonTracker,
    MouseUnavailableError,
    execute_remote_action,
    probe_capabilities,
)

TOKEN = "remote-control-test-token-123456789"
ALL_CAPS = ["desktop.mouse.move", "desktop.mouse.click",
            "desktop.keyboard.type", "desktop.keyboard.press",
            "desktop.mouse.scroll", "desktop.clipboard.write",
            "desktop.clipboard.read"]


@pytest.fixture(autouse=True)
def clean_registry():
    REGISTRY.clear()
    yield
    REGISTRY.clear()


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "rc.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "rc-chat.db"))
    with TestClient(main_mod.app) as client:
        yield client


def register(client, node_id="node-rc", capabilities=None,
             token=TOKEN):
    body = {"node_id": node_id, "hostname": node_id,
            "tier": "worker",
            "capabilities": capabilities if capabilities is not None
            else list(ALL_CAPS),
            "node_token": token}
    response = client.post("/api/v1/nodes/register", json=body)
    assert response.status_code == 201, response.text


def heartbeat(client, node_id="node-rc", token=TOKEN):
    return client.post(f"/api/v1/nodes/{node_id}/heartbeat",
                       json={"available": True, "node_token": token})


def connect(client, node_id="node-rc"):
    return client.post("/api/v1/remote-input/sessions",
                       json={"node_id": node_id})


def send_input(client, session_id, kind, params):
    return client.post(
        f"/api/v1/remote-input/sessions/{session_id}/input",
        json={"kind": kind, "params": params})


def poll(client, node_id="node-rc", token=TOKEN, extra=None):
    body = {"node_id": node_id, "node_token": token}
    if extra:
        body.update(extra)
    return client.post("/api/v1/remote-input/poll", json=body)


def stale_node(tmp_path, node_id="node-rc"):
    db = sqlite3.connect(str(tmp_path / "rc.db"))
    db.execute(
        "UPDATE nodes SET last_seen='2000-01-01T00:00:00+00:00' "
        "WHERE node_id=?", (node_id,))
    db.commit()
    db.close()


# -- A: capability discovery ------------------------------------------------------

def test_a_capability_discovery(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client, capabilities=["desktop.mouse.move"])
        assert heartbeat(client).status_code == 204
        world = client.get("/api/v1/digital-world").json()
        entry = world["nodes"][0]
        assert entry["remote_mouse"] == "supported"
        assert "desktop.mouse.move" in entry["capabilities"]
        page = client.get("/nodes").text
        for cap in ("Mouse", "Click", "Keyboard", "Scroll",
                    "Drag", "Clipboard"):
            assert cap in page


# -- B: unsupported capability weigert -----------------------------------------------

@pytest.mark.parametrize("kind,params,caps", [
    ("click", {"x": 10, "y": 10},
     ["desktop.mouse.move"]),
    ("key_press", {"key": "enter"},
     ["desktop.mouse.move", "desktop.mouse.click"]),
    ("hotkey", {"keys": ["ctrl", "c"]},
     ["desktop.mouse.move"]),
    ("type_text", {"text": "hi"},
     ["desktop.mouse.move"]),
    ("scroll", {"dx": 0, "dy": 120},
     ["desktop.mouse.move"]),
    ("mouse_down", {"x": 1, "y": 1},
     ["desktop.mouse.move"]),
    ("clipboard_set", {"text": "hi"},
     ["desktop.mouse.move", "desktop.mouse.click"]),
])
def test_b_unsupported_capability_refused(tmp_path, monkeypatch,
                                          kind, params, caps):
    for client in make_client(tmp_path, monkeypatch):
        register(client, capabilities=caps)
        assert heartbeat(client).status_code == 204
        # CONNECT slaagt (move-cap aanwezig), de input-gate
        # weigert per kind (ontbrekende capability).
        session_id = connect(client).json()["session_id"]
        response = send_input(client, session_id, kind, params)
        assert response.status_code == 403, (kind, response.text)


def test_b_click_needs_click_cap(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client, capabilities=["desktop.mouse.move",
                                       "desktop.mouse.click"])
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        # click-cap aanwezig: click mag door
        assert send_input(client, session_id, "click",
                          {"x": 5, "y": 5}).status_code == 204
        # keyboard-cap ontbreekt: key weigert
        assert send_input(client, session_id, "key_press",
                          {"key": "enter"}).status_code == 403


# -- C: session required ---------------------------------------------------------------

def test_c_input_needs_session(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        assert send_input(client, "dead" * 8, "click",
                          {"x": 1, "y": 1}).status_code == 404
        assert client.post(
            "/api/v1/remote-input/sessions/deadbeef/input",
            json={"kind": "click",
                  "params": {"x": 1}}).status_code == 404


# -- D/E: stale + disconnect ------------------------------------------------------------

def test_d_stale_node_refuses_input(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        stale_node(tmp_path)
        assert send_input(client, session_id, "click",
                          {"x": 1, "y": 1}).status_code == 403
        assert send_input(client, session_id, "key_press",
                          {"key": "a"}).status_code == 403


def test_e_disconnect_refuses_input(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        assert client.post(
            f"/api/v1/remote-input/sessions/{session_id}/close"
            ).status_code == 200
        assert send_input(client, session_id, "click",
                          {"x": 1, "y": 1}).status_code in (403, 410)
        assert poll(client).status_code == 410


# -- F/G: invalid + extra fields ------------------------------------------------------------

@pytest.mark.parametrize("kind,params", [
    ("click", {"x": -1, "y": 5}),
    ("click", {"x": 5}),
    ("click", {"x": 5, "y": 5, "button": "side"}),
    ("key_press", {"key": "rm -rf"}),
    ("key_press", {"key": "F13"}),
    ("hotkey", {"keys": ["ctrl"]}),
    ("hotkey", {"keys": ["ctrl", "alt", "shift", "x", "y"]}),
    ("hotkey", {"keys": ["ctrl", "shell"]}),
    ("type_text", {"text": ""}),
    ("type_text", {"text": "x" * 501}),
    ("type_text", {"text": "bad\x07bell"}),
    ("scroll", {"dx": 0, "dy": 0}),
    ("scroll", {"dx": 5, "dy": 120}),
    ("scroll", {"dx": 0, "dy": 20000}),
    ("mouse_down", {"x": 1}),
    ("mouse_up", {"x": 1, "y": 2, "button": "nope"}),
    ("clipboard_set", {"text": ""}),
    ("clipboard_set", {"text": "x" * 65537}),
    ("clipboard_set", {"text": "bad\x00null"}),
    ("frobnicate", {}),
    ("click", "not-a-dict"),
])
def test_f_invalid_payload_refused(tmp_path, monkeypatch, kind,
                                   params):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        assert send_input(client, session_id, kind,
                          params).status_code == 422, (kind, params)


def test_g_extra_fields_refused(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        assert send_input(
            client, session_id, "click",
            {"x": 1, "y": 1, "double": True}).status_code == 422
        response = client.post(
            f"/api/v1/remote-input/sessions/{session_id}/input",
            json={"kind": "click",
                  "params": {"x": 1, "y": 1}, "extra": 1})
        assert response.status_code == 422


# -- H: expiry -------------------------------------------------------------------------------

def test_h_session_expiry(tmp_path, monkeypatch):
    session = open_session("node-rc", now=0.0)
    with pytest.raises(RemoteInputGoneError):
        queue_action(session, "click", {"x": 1, "y": 1},
                     now=601.0)
    assert session.status == "closed"


def test_h_buffer_full_refuses(tmp_path, monkeypatch):
    session = open_session("node-rc", now=0.0)
    for _ in range(64):
        queue_action(session, "key_press", {"key": "a"}, now=1.0)
    with pytest.raises(RemoteInputRefusedError):
        queue_action(session, "key_press", {"key": "a"}, now=1.0)


# -- I/J/K: execution via fake adapter ------------------------------------------------------------

class FakeInput:
    name = "fake"
    can_move = True
    can_click = True
    can_key = True
    can_scroll = True
    can_clipboard_write = True
    can_clipboard_read = True

    def __init__(self):
        self.calls = []
        self.clipboard = ""

    def move(self, x, y):
        self.calls.append(("move", x, y))

    def click(self, x, y, button):
        self.calls.append(("click", x, y, button))

    def button(self, down, x, y, button):
        self.calls.append(("button", down, x, y, button))

    def release(self, button):
        self.calls.append(("release", button))

    def scroll(self, dy):
        self.calls.append(("scroll", dy))

    def key_press(self, key):
        self.calls.append(("key_press", key))

    def hotkey(self, keys):
        self.calls.append(("hotkey", tuple(keys)))

    def type_text(self, text):
        self.calls.append(("type_text", text))

    def clipboard_write(self, text):
        self.calls.append(("clipboard_write", text))
        self.clipboard = text

    def clipboard_read(self):
        self.calls.append(("clipboard_read",))
        return self.clipboard or "node-text"


def test_i_click_execution():
    fake = FakeInput()
    receipt = execute_remote_action(
        "click", {"x": 11, "y": 22, "button": "right"},
        adapter=fake)
    assert receipt["button"] == "right"
    assert fake.calls == [("click", 11, 22, "right")]
    with pytest.raises(MouseUnavailableError):
        execute_remote_action(
            "click", {"x": 1, "y": 1},
            adapter=remote_mouse.UnavailableMouseAdapter())


def test_j_keyboard_execution():
    fake = FakeInput()
    assert execute_remote_action(
        "key_press", {"key": "Enter"},
        adapter=fake)["key"] == "enter"
    assert execute_remote_action(
        "hotkey", {"keys": ["CTRL", "c"]},
        adapter=fake)["keys"] == ["ctrl", "c"]
    assert execute_remote_action(
        "type_text", {"text": "hello"},
        adapter=fake)["chars"] == 5
    assert fake.calls == [("key_press", "enter"),
                          ("hotkey", ("ctrl", "c")),
                          ("type_text", "hello")]
    with pytest.raises(MouseUnavailableError):
        execute_remote_action("key_press", {"key": "rm"},
                              adapter=fake)
    with pytest.raises(MouseUnavailableError):
        execute_remote_action("unknown_kind", {},
                              adapter=fake)


def test_k_scroll_execution_vertical_only():
    fake = FakeInput()
    assert execute_remote_action(
        "scroll", {"dx": 0, "dy": -240},
        adapter=fake)["dy"] == -240
    assert fake.calls == [("scroll", -240)]
    with pytest.raises(MouseUnavailableError):
        execute_remote_action("scroll", {"dx": 3, "dy": 120},
                              adapter=fake)
    with pytest.raises(MouseUnavailableError):
        execute_remote_action("scroll", {"dx": 0, "dy": 0},
                              adapter=fake)


def test_no_shell_in_extended_adapter():
    import pathlib
    src = pathlib.Path(remote_mouse.__file__).read_text(
        encoding="utf-8")
    assert "import subprocess" not in src
    assert "shell=True" not in src
    assert "os.system" not in src
    assert "eval(" not in src
    # allow-listed methoden bestaan, niets daarbuiten
    for name in ("click", "button", "release", "scroll",
                 "key_press", "hotkey", "type_text",
                 "clipboard_write", "clipboard_read"):
        assert hasattr(remote_mouse.WindowsMouseAdapter, name)
    for name in ("shell", "exec", "command", "run", "open_url",
                 "download", "upload"):
        assert not hasattr(remote_mouse.WindowsMouseAdapter, name)
    assert probe_capabilities(
        adapter=remote_mouse.UnavailableMouseAdapter()) == {
            "move": False, "click": False, "keyboard": False,
            "scroll": False, "drag": False,
            "clipboard_write": False, "clipboard_read": False}


@pytest.mark.skipif(os.name != "nt",
                    reason="Windows INPUT layout only")
def test_windows_input_struct_union_size():
    """Regressie: keyboard-INPUT moet even groot zijn als
    mouse-INPUT (echte 40-byte union op x64) — een key-only
    32-byte struct laat SendInput elke toets weigeren."""
    mouse_size, key_size = remote_mouse.windows_input_size()
    assert mouse_size == key_size == 40


# -- L: drag lifecycle -------------------------------------------------------------------------------

def test_l_drag_lifecycle_order(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        assert send_input(client, session_id, "mouse_down",
                          {"x": 100, "y": 100}).status_code == 204
        assert send_input(client, session_id, "mouse_up",
                          {"x": 150, "y": 160}).status_code == 204
        data = poll(client).json()
        kinds = [a["kind"] for a in data.get("actions", [])]
        assert kinds == ["mouse_down", "mouse_up"]
        # consume-on-read: tweede poll leeg
        assert poll(client).json() is None


def test_l_drag_executes_in_order_with_tracker():
    fake = FakeInput()
    tracker = ButtonTracker()
    execute_remote_action("mouse_down", {"x": 1, "y": 2},
                          adapter=fake, tracker=tracker)
    assert tracker.held == "left"
    execute_remote_action("mouse_up", {"x": 3, "y": 4},
                          adapter=fake, tracker=tracker)
    assert tracker.held is None
    assert fake.calls == [("button", True, 1, 2, "left"),
                          ("button", False, 3, 4, "left")]


def test_tracker_emergency_release_without_moving():
    fake = FakeInput()
    tracker = ButtonTracker()
    assert tracker.emergency_release(adapter=fake) is None
    tracker.press("right")
    receipt = tracker.emergency_release(adapter=fake)
    assert receipt["emergency"] is True
    assert receipt["button"] == "right"
    # release beweegt de cursor NIET (alleen button-up)
    assert fake.calls == [("release", "right")]
    assert tracker.held is None


# -- M: clipboard ---------------------------------------------------------------------------------------

def test_m_clipboard_set_roundtrip(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        assert send_input(client, session_id, "clipboard_set",
                          {"text": "hello node"}).status_code == 204
        data = poll(client).json()
        assert data["actions"][0]["kind"] == "clipboard_set"
        assert data["actions"][0]["text"] == "hello node"


def test_m_clipboard_request_read_flow(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        # lezen zonder tekst: null (geen fake)
        empty = client.get(
            f"/api/v1/remote-input/sessions/{session_id}/clipboard")
        assert empty.status_code == 200
        assert empty.json() == {"text": None}
        # request zetten
        assert client.post(
            f"/api/v1/remote-input/sessions/{session_id}"
            f"/clipboard/request").status_code == 204
        # node ziet de vlag in de poll
        data = poll(client).json()
        assert data is not None
        assert data.get("clipboard_request") is True
        # node levert tekst bij de volgende poll
        delivered = poll(client, extra={"clipboard_text": "from-node"})
        assert delivered.status_code == 200
        # browser leest eenmalig
        got = client.get(
            f"/api/v1/remote-input/sessions/{session_id}/clipboard")
        assert got.json() == {"text": "from-node"}
        again = client.get(
            f"/api/v1/remote-input/sessions/{session_id}/clipboard")
        assert again.json() == {"text": None}


def test_m_unsolicited_clipboard_refused(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        connect(client)
        response = poll(client, extra={"clipboard_text": "sneaky"})
        assert response.status_code == 422


def test_check_clipboard_text_gate():
    assert check_clipboard_text("a\nb\rc\td") == "a\nb\rc\td"
    for bad in ["", "x" * 65537, "bad\x00", "bad\x07", 42, None]:
        try:
            check_clipboard_text(bad)
        except RemoteInputRefusedError:
            continue
        raise AssertionError(f"accepted {bad!r}"[:60])


def test_capability_for_kind_closed():
    from coordinator.app.remote_input import (
        CLIPBOARD_READ_CAPABILITY, CLIPBOARD_WRITE_CAPABILITY,
        CLICK_CAPABILITY, KEYBOARD_PRESS_CAPABILITY,
        KEYBOARD_TYPE_CAPABILITY, MOUSE_CAPABILITY,
        SCROLL_CAPABILITY,
    )
    assert capability_for_kind("click") == {CLICK_CAPABILITY}
    assert capability_for_kind("scroll") == {SCROLL_CAPABILITY}
    assert capability_for_kind("type_text") == {
        KEYBOARD_TYPE_CAPABILITY}
    assert capability_for_kind("key_press") == {
        KEYBOARD_PRESS_CAPABILITY}
    assert capability_for_kind("mouse_down") == {
        MOUSE_CAPABILITY, CLICK_CAPABILITY}
    assert capability_for_kind("clipboard_set") == {
        CLIPBOARD_WRITE_CAPABILITY}
    assert CLIPBOARD_READ_CAPABILITY.startswith("desktop.")
    try:
        capability_for_kind("rm -rf")
    except RemoteInputRefusedError:
        pass
    else:
        raise AssertionError("open kind accepted")


def test_check_input_action_uses_existing_contracts():
    assert check_input_action(
        "click", {"x": 1, "y": 2})["button"] == "left"
    assert check_input_action(
        "key_press", {"key": "F5"}) == {"kind": "key_press",
                                        "key": "f5"}
    assert check_input_action(
        "scroll", {"dx": 0, "dy": 120})["dy"] == 120
    assert check_input_action(
        "mouse_down",
        {"x": 3, "y": 4}) == {"kind": "mouse_down", "x": 3,
                              "y": 4, "button": "left"}
    for bad_kind, bad_params in [
            ("click", {"x": 1, "y": 2, "button": "side"}),
            ("scroll", {"dx": 1, "dy": 1}),
            ("mouse_down", {"x": 1}),
            ("mouse_up", {"x": 1, "y": 1, "button": "x"}),
            ("clipboard_set", {"text": ""}),
            ("clipboard_set", {"x": 1}),
            ("nope", {}), ("click", []),
    ]:
        try:
            check_input_action(bad_kind, bad_params)
        except RemoteInputRefusedError:
            continue
        raise AssertionError(f"accepted {bad_kind}")


# -- N: disconnect tijdens actieve actie --------------------------------------------------------------------

def test_n_disconnect_during_drag_releases(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        assert send_input(client, session_id, "mouse_down",
                          {"x": 50, "y": 50}).status_code == 204
        assert client.post(
            f"/api/v1/remote-input/sessions/{session_id}/close"
            ).status_code == 200
        # node die nog pollt krijgt 410 (release-signaal),
        # nooit de oude down-actie opnieuw
        gone = poll(client)
        assert gone.status_code == 410


def test_n_410_triggers_emergency_release(monkeypatch):
    import node_client.main as node_main
    import node_client.remote_mouse as rm

    fake = FakeInput()

    class _Gone:
        status_code = 410
        content = b"{}"

        def json(self):
            raise AssertionError("no body on 410")

    class _StubClient:
        async def post(self, url, json=None):
            return _Gone()

    tracker = ButtonTracker()
    tracker.press("left")
    monkeypatch.setattr(rm, "default_adapter", lambda: fake)

    def run_coro(coro):
        import asyncio
        import threading
        outcome: dict = {}

        def _run():
            outcome["result"] = asyncio.new_event_loop(
                ).run_until_complete(coro)

        worker = threading.Thread(target=_run)
        worker.start()
        worker.join(timeout=30)
        return outcome["result"]

    summary = run_coro(node_main.poll_remote_input_once(
        _StubClient(), "http://x/api/v1", "node-rc", None,
        tracker=tracker))
    assert summary["released"]["emergency"] is True
    assert tracker.held is None
    assert ("release", "left") in fake.calls


# -- O/P/Q/R: bestaande flows ----------------------------------------------------------------------------------

def test_o_mouse_still_works(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        session_id = connect(client).json()["session_id"]
        assert client.post(
            f"/api/v1/remote-input/sessions/{session_id}/move",
            json={"x": 800, "y": 450}).status_code == 204
        data = poll(client).json()
        assert data["move"] == {"x": 800, "y": 450, "seq": 1}
        assert data["actions"] == [] if "actions" in data else True
        assert poll(client).json() is None


def test_p_digital_world_per_capability_ui(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        page = client.get("/nodes").text
        assert "REMOTE CONTROL" in page
        for cap in ("Mouse", "Click", "Keyboard", "Scroll",
                    "Drag", "Clipboard"):
            assert cap in page
        assert "dw-kbd" in page
        assert "dw-clip" in page
        assert "dw-click-left" in page
        assert "dw-pad" in page


def test_q_forge_alive(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.get("/forge").status_code == 200
        assert client.get("/api/v1/game/state").status_code == 200


def test_r_workspaces_alive(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.get("/api/v1/workspaces").status_code == 200
        assert client.get("/workspaces").status_code == 200
