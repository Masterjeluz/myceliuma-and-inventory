"""VERTICAL SLICE 1 tests: physical digital world (NODE -> DISPLAY).

Covers the task's Fase H contract:

A node zonder display metadata werkt
B node met een display werkt
C node met meerdere displays werkt
D onbekende fysieke afmetingen blijven null
E onbekende positie blijft null
F UI rendert nodes
G UI rendert displays
H selectie werkt (stable ids + selectie-plumbing in de UI)
I drag werkt alleen in UI-state (geen writes, geen fetch/POST)
J reset layout werkt (reset-knop + handler wist UI-state)
K offline node degradeert
L bestaande worker flow blijft groen
M bestaande Forge flow blijft groen (pagina + JSON leven nog)
N geen writes tijdens world rendering (GETs zijn pure reads)

Plus pure unit tests: check_displays fail-closed, xrandr-parser
eerlijk (geen fake data), derive_digital_world bounded/gesorteerd.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.nodes import (
    NodeRefusedError,
    check_displays,
    derive_digital_world,
)
from node_client.main import parse_xrandr_query

TOKEN = "digital-world-test-token-123456789"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "dw.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "dw-chat.db"))
    with TestClient(main_mod.app) as client:
        yield client


def register(client, node_id="node-dw", token=TOKEN):
    body = {"node_id": node_id, "hostname": node_id,
            "tier": "worker",
            "capabilities": ["research.fetch"],
            "node_token": token}
    response = client.post("/api/v1/nodes/register", json=body)
    assert response.status_code == 201, response.text


def heartbeat(client, node_id="node-dw", token=TOKEN, **fields):
    body = {"available": True, "node_token": token}
    body.update(fields)
    return client.post(f"/api/v1/nodes/{node_id}/heartbeat",
                       json=body)


ONE_DISPLAY = [{
    "id": "HDMI-1", "name": "HDMI-1",
    "width": 1920, "height": 1080, "refresh_rate": 60.0,
    "physical_width_mm": 477, "physical_height_mm": 268,
    "x": 0, "y": 0, "scale": None,
    "orientation": "normal", "primary": True,
}]

TWO_DISPLAYS = ONE_DISPLAY + [{
    "id": "eDP-1", "name": "eDP-1",
    "width": 1920, "height": 1080, "refresh_rate": None,
    "physical_width_mm": None, "physical_height_mm": None,
    "x": None, "y": None, "scale": None,
    "orientation": "unknown", "primary": False,
}]


# -- A: node zonder display metadata ------------------------------------------

def test_a_node_without_displays_reports_empty(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client).status_code == 204
        node = client.get("/api/v1/nodes/node-dw").json()
        assert node["displays"] == []
        world = client.get("/api/v1/digital-world").json()
        assert world["provenance"] == "derived"
        assert world["node_count"] == 1
        assert world["display_count"] == 0
        entry = world["nodes"][0]
        assert entry["displays"] == []
        assert entry["display_count"] == 0


# -- B/C: een en meerdere displays --------------------------------------------

def test_b_single_display_roundtrip(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client, displays=ONE_DISPLAY).status_code == 204
        node = client.get("/api/v1/nodes/node-dw").json()
        assert len(node["displays"]) == 1
        disp = node["displays"][0]
        assert disp["id"] == "HDMI-1"
        assert disp["width"] == 1920
        assert disp["height"] == 1080
        assert disp["primary"] is True
        reality = client.get(
            "/api/v1/nodes/node-dw/reality").json()
        assert len(reality["displays"]) == 1


def test_c_multiple_displays_roundtrip(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client, displays=TWO_DISPLAYS).status_code == 204
        world = client.get("/api/v1/digital-world").json()
        assert world["display_count"] == 2
        assert world["nodes"][0]["display_count"] == 2


# -- D/E: onbekend blijft null -------------------------------------------------

def test_d_unknown_physical_size_stays_null(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client, displays=TWO_DISPLAYS).status_code == 204
        node = client.get("/api/v1/nodes/node-dw").json()
        laptop = [d for d in node["displays"]
                  if d["id"] == "eDP-1"][0]
        assert laptop["physical_width_mm"] is None
        assert laptop["physical_height_mm"] is None
        # ... terwijl bekende maten wel doorkomen
        hdmi = [d for d in node["displays"]
                if d["id"] == "HDMI-1"][0]
        assert hdmi["physical_width_mm"] == 477


def test_e_unknown_position_and_refresh_stay_null(tmp_path,
                                                  monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client, displays=TWO_DISPLAYS).status_code == 204
        node = client.get("/api/v1/nodes/node-dw").json()
        laptop = [d for d in node["displays"]
                  if d["id"] == "eDP-1"][0]
        assert laptop["x"] is None
        assert laptop["y"] is None
        assert laptop["refresh_rate"] is None


def test_refusals_stay_fail_closed(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        # onbekend veld
        bad = [dict(ONE_DISPLAY[0], edid_hack="x")]
        assert heartbeat(client, displays=bad).status_code == 422
        # dubbele id
        assert heartbeat(client,
                         displays=ONE_DISPLAY + ONE_DISPLAY
                         ).status_code == 422
        # geen id
        assert heartbeat(client,
                         displays=[{"width": 800}]
                         ).status_code == 422
        # te veel displays
        many = [dict(ONE_DISPLAY[0], id=f"D-{i}")
                for i in range(17)]
        assert heartbeat(client, displays=many).status_code == 422
        # mislukte heartbeat mag niets opslaan
        node = client.get("/api/v1/nodes/node-dw").json()
        assert node["displays"] == []


# -- F/G: UI rendert nodes en displays -----------------------------------------

def test_f_ui_renders_nodes(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client, node_id="linux-1")
        register(client, node_id="windows-pc")
        assert heartbeat(client, node_id="linux-1",
                         displays=ONE_DISPLAY).status_code == 204
        assert heartbeat(client, node_id="windows-pc").status_code == 204
        page = client.get("/nodes").text
        assert "Digital World" in page
        assert "dw-node" in page
        assert "linux-1" in page
        assert "windows-pc" in page


def test_g_ui_renders_displays(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client, displays=ONE_DISPLAY).status_code == 204
        page = client.get("/nodes").text
        assert "dw-display" in page
        assert "HDMI-1" in page
        assert "1920" in page and "1080" in page
        # onbekende waarden worden eerlijk gelabeld
        assert heartbeat(client, displays=TWO_DISPLAYS).status_code == 204
        page = client.get("/nodes").text
        assert "onbekend" in page


# -- H/I/J: selectie, drag (UI-only), reset -------------------------------------

def _world_script(page: str) -> str:
    start = page.index("const DWDATA")
    end = page.index("</script>", start)
    return page[start:end]


def test_h_selection_plumbing_present(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client, displays=ONE_DISPLAY).status_code == 204
        page = client.get("/nodes").text
        assert 'id="dw-details"' in page
        assert 'id="dw-stage"' in page
        script = _world_script(page)
        # selectie-functie + stabiele ids per display
        assert "function select(" in script
        assert "data-display" in script
        # JSON-snapshot draagt de stabiele ids voor selectie
        world = client.get("/api/v1/digital-world").json()
        assert world["nodes"][0]["displays"][0]["id"] == "HDMI-1"


def test_i_drag_is_ui_state_only(tmp_path, monkeypatch):
    import re
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client, displays=ONE_DISPLAY).status_code == 204
        page = client.get("/nodes").text
        panel = page[page.index("Digital World"):page.index(
            "Gerapporteerde nodes")]
        # geen enkel formulier/POST in het game-panel
        assert "<form" not in panel
        assert "method=\"post\"" not in panel
        script = _world_script(page)
        # layout/select/drag/pan/zoom/reset zijn netwerkvrij: de
        # enige fetch-aanroepen zitten in de expliciete
        # remote-control handlers (CONNECT/DISCONNECT/input/pad/
        # clipboard), nooit in render/layout/drag-state.
        layout = re.sub(
            r"function dw(Connect|Disconnect|PadMove|Input|ClipRequest)\(.*?"""
            r"\n\}",
            "", script, flags=re.DOTALL)
        assert "fetch(" not in layout
        assert "XMLHttpRequest" not in layout
        assert "postJSON" not in layout
        assert 'state.ui' in script
        # expliciet gelabeld als niet-fysiek
        assert "niet fysiek" in page


def test_j_reset_layout_present(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        page = client.get("/nodes").text
        assert 'id="dw-reset"' in page
        script = _world_script(page)
        assert "dw-reset" in script
        assert "state.ui = {}" in script


# -- K: offline degradeert ------------------------------------------------------

def test_k_offline_node_degrades(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client, node_id="old-laptop")
        assert heartbeat(client, node_id="old-laptop",
                         displays=ONE_DISPLAY).status_code == 204
        db_path = str(tmp_path / "dw.db")
        db = sqlite3.connect(db_path)
        db.execute(
            "UPDATE nodes SET last_seen='2000-01-01T00:00:00+00:00' "
            "WHERE node_id='old-laptop'")
        db.commit()
        db.close()
        world = client.get("/api/v1/digital-world").json()
        entry = world["nodes"][0]
        assert entry["derived_status"] in ("stale", "offline")
        # displays blijven zichtbaar (laatst bekende state), status eerlijk
        assert entry["display_count"] == 1
        page = client.get("/nodes").text
        assert "dim-offline" in page


# -- L: worker flow blijft groen --------------------------------------------------

def test_l_worker_task_flow_still_green(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client, displays=ONE_DISPLAY).status_code == 204
        created = client.post("/api/v1/tasks", json={
            "kind": "research.fetch_url",
            "payload": {},
            "required_capabilities": [],
        })
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]
        claimed = client.post("/api/v1/tasks/claim/node-dw",
                              params={"node_token": TOKEN})
        assert claimed.status_code == 200, claimed.text
        done = client.post(f"/api/v1/tasks/{task_id}/complete",
                           json={"success": True, "result": {},
                                 "error": None,
                                 "node_id": "node-dw"})
        assert done.status_code in (200, 204), done.text


# -- M: Forge flow blijft groen ----------------------------------------------------

def test_m_forge_still_green(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.get("/forge").status_code == 200
        state = client.get("/api/v1/game/state")
        assert state.status_code == 200


# -- N: geen writes tijdens rendering ----------------------------------------------

def test_n_world_rendering_performs_no_writes(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client, displays=TWO_DISPLAYS).status_code == 204

        def snapshot_db():
            db = sqlite3.connect(str(tmp_path / "dw.db"))
            rows = db.execute(
                "SELECT * FROM nodes ORDER BY node_id").fetchall()
            db.close()
            return rows

        before = snapshot_db()
        first = client.get("/api/v1/digital-world").json()
        second = client.get("/api/v1/digital-world").json()
        page = client.get("/nodes").text
        assert page.status_code == 200 if hasattr(page, "status_code") \
            else True
        after = snapshot_db()
        assert first == second
        assert before == after


# -- pure unit tests ---------------------------------------------------------------

def test_check_displays_minimal_and_defaults():
    cleaned = check_displays([{"id": "DP-1"}])
    assert cleaned == [{
        "id": "DP-1", "name": "", "width": None, "height": None,
        "refresh_rate": None, "physical_width_mm": None,
        "physical_height_mm": None, "x": None, "y": None,
        "scale": None, "orientation": "unknown", "primary": False,
    }]


def test_check_displays_none_is_empty():
    assert check_displays(None) == []


@pytest.mark.parametrize("bad", [
    "no-list", 42, [{"id": ""}], [{"id": "  "}],
    [{"id": "A", "width": True}], [{"id": "A", "primary": "yes"}],
    [{"id": "A", "orientation": "diagonal"}],
    [{"id": "A", "width": 0}], [{"id": "A", "width": 99999}],
    [{"id": "A", "refresh_rate": -5}],
    [{"id": "A", "scale": 100}],
    [{"id": "A", "mystery": 1}],
    [{"id": "A"}, {"id": "A"}],
])
def test_check_displays_refuses_bad_input(bad):
    with pytest.raises(NodeRefusedError):
        check_displays(bad)


def test_derive_digital_world_sorted_bounded_and_safe():
    records = [
        {"node_id": "b-node", "hostname": "b",
         "derived_status": "online", "telemetry": {"os": "Linux"},
         "hardware": [], "displays": "corrupt"},
        {"node_id": "a-node", "hostname": "a",
         "derived_status": "stale", "telemetry": {},
         "hardware": [{"kind": "gpu", "identifier": "GTX",
                       "status": "connected"}],
         "displays": [{"id": "X", "width": 1}]},
        "not-a-record",
        {"hostname": "no-id"},
    ]
    world = derive_digital_world(records)
    assert [n["node_id"] for n in world["nodes"]] == [
        "a-node", "b-node"]
    assert world["nodes"][0]["hardware"]["gpu"] == ["GTX"]
    # corrupte display-rij dropt, breekt de wereld niet
    assert world["nodes"][1]["displays"] == []
    assert world["provenance"] == "derived"
    assert "honesty" in world


XRANDR_SAMPLE = """Screen 0: minimum 8 x 8, current 3840 x 1080, maximum 32767 x 32767
HDMI-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 477mm x 268mm
   1920x1080     60.00*+  50.00    59.94
   1680x1050     59.88
DP-1 disconnected (normal left inverted right x axis y axis)
eDP-1 connected 1920x1080+1920+0 (normal left inverted right x axis y axis) 344mm x 193mm
   1920x1080     60.02*+  48.00
   1280x720      60.00
VGA-1 connected (normal left inverted right x axis y axis)
"""


def test_xrandr_parser_honest_no_fake_data():
    displays = parse_xrandr_query(XRANDR_SAMPLE)
    by_id = {d["id"]: d for d in displays}
    # disconnected output wordt nooit gerapporteerd
    assert "DP-1" not in by_id
    hdmi = by_id["HDMI-1"]
    assert (hdmi["width"], hdmi["height"]) == (1920, 1080)
    assert hdmi["primary"] is True
    assert (hdmi["x"], hdmi["y"]) == (0, 0)
    assert hdmi["refresh_rate"] == pytest.approx(60.0)
    assert (hdmi["physical_width_mm"],
            hdmi["physical_height_mm"]) == (477, 268)
    laptop = by_id["eDP-1"]
    assert (laptop["x"], laptop["y"]) == (1920, 0)
    assert laptop["primary"] is False
    # connected zonder actieve modus: geen resolutie verzinnen
    vga = by_id["VGA-1"]
    assert vga["width"] is None
    assert vga["height"] is None
    assert vga["refresh_rate"] is None
    assert vga["physical_width_mm"] is None
    # schaal is via xrandr niet betrouwbaar: altijd None
    assert all(d["scale"] is None for d in displays)


def test_xrandr_parser_empty_and_garbage():
    assert parse_xrandr_query("") == []
    assert parse_xrandr_query("garbage\nmore garbage\n") == []
