"""BIG #39 tests: hardware reality layer integration.

Heartbeat telemetry/hardware/compute/energy end-to-end over the
real API on tmp DBs: register → heartbeat → node shows ONLINE +
telemetry + hardware + compute + energy. Refusals stay fail-closed
(unknown fields/kinds, bad credentials). Routing dry-run honors
telemetry-aware requirements. Mobile nodes panel, hardware-aware
guide, world-graph overlays, node bus events, notify-center types
and node-client collectors are covered against the real code.

No hardware is touched: collectors run read-only against psutil
best-effort data; validation is pure.
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN = "big39-test-token-123456"

TELEMETRY = {
    "hostname": "test-node",
    "os": "Linux",
    "platform": "Linux-5.15.0",
    "cpu_percent": 42.5,
    "cpu_count": 8,
    "memory_percent": 60.0,
    "memory_total_mb": 16384,
    "memory_available_mb": 6554,
    "disk_percent": 40.0,
    "disk_total_gb": 500.0,
    "disk_free_gb": 300.0,
    "uptime_seconds": 3600,
    "temperature_celsius": 45.0,
    "load_average": [1.2, 1.5, 1.8],
    "network_interfaces": ["eth0", "wlan0"],
    "boot_time": 1700000000,
}

HARDWARE = [
    {"kind": "camera", "identifier": "/dev/video0",
     "details": {"subsystem": "v4l2"}, "status": "connected",
     "connected_since": 1700000000},
    {"kind": "gpu", "identifier": "NVIDIA RTX 3080",
     "details": {"vendor": "nvidia"}, "status": "connected"},
    {"kind": "usb", "identifier": "1-1.2",
     "details": {"description": "Old webcam"},
     "status": "disconnected"},
]

COMPUTE = [
    {"capability": "ollama",
     "details": {"models": ["llama3"]},
     "status": "available", "since": 1700000000},
    {"capability": "gpu_available",
     "details": {"vendor": "nvidia"}, "status": "available"},
    {"capability": "cpu_inference", "details": {},
     "status": "available"},
]

ENERGY = {"source": "battery", "level_percent": 75,
          "charging": False, "details": {},
          "since": 1700000000}


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b39.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b39-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def register(client, node_id="node-b39", capabilities=None,
             token=TOKEN):
    body = {"node_id": node_id, "hostname": node_id,
            "tier": "worker",
            "capabilities": capabilities or [
                "research.fetch", "analysis.ollama"],
            "node_token": token}
    response = client.post("/api/v1/nodes/register", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def heartbeat(client, node_id="node-b39", token=TOKEN, **fields):
    body = {"available": True, "node_token": token}
    body.update(fields)
    return client.post(f"/api/v1/nodes/{node_id}/heartbeat",
                       json=body)


# -- heartbeat telemetry integration ----------------------------------------

def test_heartbeat_accepts_full_telemetry_payload(tmp_path,
                                                  monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        response = heartbeat(client, telemetry=TELEMETRY,
                             hardware=HARDWARE,
                             compute_capabilities=COMPUTE,
                             energy_state=ENERGY)
        assert response.status_code == 204, response.text
        node = client.get("/api/v1/nodes/node-b39").json()
        assert node["health_status"] == "ONLINE"
        assert node["telemetry"]["cpu_percent"] == 42.5
        assert node["telemetry"]["memory_percent"] == 60.0
        assert node["telemetry_timestamp"] != ""
        kinds = [item["kind"] for item in node["hardware"]]
        assert "camera" in kinds
        assert "gpu" in kinds
        caps = [item["capability"]
                for item in node["compute_capabilities"]]
        assert "ollama" in caps
        assert "gpu_available" in caps
        assert node["energy_state"]["source"] == "battery"
        assert node["energy_state"]["level_percent"] == 75


def test_heartbeat_telemetry_unknown_field_refused(tmp_path,
                                                   monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        bad = dict(TELEMETRY)
        bad["evil_metric"] = 1
        response = heartbeat(client, telemetry=bad)
        assert response.status_code == 422
        node = client.get("/api/v1/nodes/node-b39").json()
        assert node["telemetry"] == {}
        assert node["telemetry_timestamp"] == ""


def test_heartbeat_hardware_unknown_kind_refused(tmp_path,
                                                 monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        response = heartbeat(
            client, hardware=[{"kind": "quantum_reactor",
                               "identifier": "q1"}])
        assert response.status_code == 422
        node = client.get("/api/v1/nodes/node-b39").json()
        assert node["hardware"] == []


def test_heartbeat_compute_unknown_capability_refused(tmp_path,
                                                      monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        response = heartbeat(
            client, compute_capabilities=[
                {"capability": "teleportation"}])
        assert response.status_code == 422


def test_heartbeat_energy_bad_source_refused(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        response = heartbeat(client, energy_state={
            "source": "fusion", "level_percent": 90})
        assert response.status_code == 422


def test_heartbeat_gates_intact(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        # Bad credential still refused.
        assert heartbeat(client, token="wrong-token-123456",
                         telemetry=TELEMETRY).status_code == 403
        # Unknown node still 404.
        assert heartbeat(client, node_id="node-nope",
                         telemetry=TELEMETRY).status_code == 404
        # Wildcard capability still refused (no weakening).
        assert heartbeat(
            client, capabilities=["*"]).status_code == 422
        # Shell-shaped capability still refused.
        assert heartbeat(
            client, capabilities=["rm -rf"]).status_code == 422


def test_heartbeat_partial_update_keeps_prior_fields(tmp_path,
                                                     monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client, telemetry=TELEMETRY,
                         hardware=HARDWARE).status_code == 204
        # Second heartbeat with only compute keeps telemetry.
        assert heartbeat(
            client,
            compute_capabilities=COMPUTE).status_code == 204
        node = client.get("/api/v1/nodes/node-b39").json()
        assert node["telemetry"]["cpu_percent"] == 42.5
        assert len(node["hardware"]) == 3
        assert len(node["compute_capabilities"]) == 3


# -- telemetry-aware routing over the real API -------------------------------

def test_route_preview_honors_hardware_and_compute(tmp_path,
                                                   monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client, telemetry=TELEMETRY,
                         hardware=HARDWARE,
                         compute_capabilities=COMPUTE,
                         energy_state=ENERGY).status_code == 204
        matched = client.post("/api/v1/tasks/route", json={
            "requirements": {
                "required_capabilities": ["research.fetch"],
                "required_hardware": ["camera"],
                "required_compute": ["ollama"],
            },
            "policy": {}}).json()
        assert matched["selected_node_id"] == "node-b39"
        missing = client.post("/api/v1/tasks/route", json={
            "requirements": {
                "required_capabilities": ["research.fetch"],
                "required_hardware": ["printer_3d"],
            },
            "policy": {}}).json()
        assert missing["selected_node_id"] is None
        assert any("printer_3d" in reason
                   for entry in missing["rejected"]
                   for reason in entry["reasons"])


def test_route_preview_honors_min_health(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client, telemetry=TELEMETRY,
                         hardware=HARDWARE).status_code == 204
        decision = client.post("/api/v1/tasks/route", json={
            "requirements": {
                "required_capabilities": ["research.fetch"],
                "min_health": "ONLINE",
            },
            "policy": {}}).json()
        assert decision["selected_node_id"] == "node-b39"
        # Unknown hardware kind refused at validation (422).
        refused = client.post("/api/v1/tasks/route", json={
            "requirements": {"required_hardware": ["nope"]},
            "policy": {}})
        assert refused.status_code == 422


# -- mobile hardware view -----------------------------------------------------

def test_mobile_nodes_panel_shows_telemetry(tmp_path, monkeypatch):
    from coordinator.app.mobile import nodes_panel
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client, telemetry=TELEMETRY,
                         hardware=HARDWARE,
                         compute_capabilities=COMPUTE,
                         energy_state=ENERGY).status_code == 204
        panel = nodes_panel()
        entry = next(item for item in panel["nodes"]
                     if item["node_id"] == "node-b39")
        assert entry["health"] == "ONLINE"
        assert entry["telemetry"]["cpu_percent"] == 42.5
        assert entry["telemetry"]["memory_percent"] == 60.0
        assert entry["telemetry"]["timestamp"] != ""
        assert entry["hardware"]["connected"] == 2
        assert "camera" in entry["hardware"]["kinds"]
        assert "gpu" in entry["hardware"]["kinds"]
        assert entry["compute"]["available"] == 3
        assert "ollama" in entry["compute"]["capabilities"]
        assert entry["energy"]["source"] == "battery"


def test_mobile_page_shows_hardware_detail(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client, telemetry=TELEMETRY,
                         hardware=HARDWARE,
                         compute_capabilities=COMPUTE,
                         energy_state=ENERGY).status_code == 204
        html = client.get("/mobile").text
        assert "health ONLINE" in html
        assert "camera" in html
        assert "ollama" in html
        assert "battery" in html


# -- hardware-aware guide ------------------------------------------------------

def test_guide_shows_hardware_awareness(tmp_path, monkeypatch):
    from coordinator.app.guide import guide_items
    for client in make_client(tmp_path, monkeypatch):
        register(client)
        assert heartbeat(client, telemetry=TELEMETRY,
                         hardware=HARDWARE,
                         compute_capabilities=COMPUTE,
                         energy_state=ENERGY).status_code == 204
        items = guide_items(limit=20)
        texts = " | ".join(item["what"] for item in items)
        assert "Ollama" in texts
        assert "GPU" in texts
        assert "camera(s) connected" in texts
        # Disconnected USB device is surfaced honestly.
        assert "disconnected" in texts
        assert all(item["next"]["href"] == "/nodes"
                   for item in items
                   if item["kind"] == "node"
                   and "Ollama" in item["what"]
                   or "GPU" in item["what"])


# -- world-graph telemetry overlays --------------------------------------------

def test_worldgraph_hardware_overlay():
    from coordinator.app.worldgraph import _overlay_hardware
    registry = [{
        "node_id": "node-b39",
        "hardware": [
            {"kind": "camera", "identifier": "/dev/video0",
             "details": {}, "status": "connected",
             "connected_since": "t"},
            {"kind": "usb", "identifier": "1-1.2",
             "details": {}, "status": "disconnected",
             "connected_since": "t"},
        ],
    }]
    nodes: dict = {"node-b39": {"id": "node-b39"}}
    edges: list = []
    _overlay_hardware(nodes, edges, registry)
    assert "hw_node-b39_/dev/video0" in nodes
    assert "hw_node-b39_1-1.2" not in nodes
    assert edges[0]["predicate"] == "HAS"
    assert edges[0]["provenance"]["human_verified"] is False


def test_worldgraph_compute_overlay():
    from coordinator.app.worldgraph import _overlay_compute
    registry = [{
        "node_id": "node-b39",
        "compute_capabilities": [
            {"capability": "ollama", "details": {},
             "status": "available", "since": "t"},
            {"capability": "gpu_available", "details": {},
             "status": "busy", "since": "t"},
        ],
    }]
    nodes: dict = {"node-b39": {"id": "node-b39"}}
    edges: list = []
    _overlay_compute(nodes, edges, registry)
    assert "compute_node-b39_ollama" in nodes
    assert "compute_node-b39_gpu_available" not in nodes
    assert edges[0]["predicate"] == "PROVIDES"
    assert edges[0]["provenance"]["human_verified"] is False


def test_worldgraph_registry_nodes_carry_telemetry_counts():
    from coordinator.app.worldgraph import _overlay_registry_nodes
    registry = [{
        "node_id": "node-b39", "display_name": "Test",
        "hostname": "h", "derived_status": "online",
        "health_status": "ONLINE", "tier": "worker",
        "capabilities": ["a.b"], "models": [],
        "last_seen": "2026-09-19T00:00:00+00:00",
        "telemetry": {"cpu_percent": 10.0},
        "telemetry_timestamp": "2026-09-19T00:00:00+00:00",
        "hardware": [{"kind": "camera", "status": "connected"}],
        "compute_capabilities": [
            {"capability": "ollama", "status": "available"}],
        "energy_state": {"source": "grid"},
    }]
    nodes: dict = {}
    edges: list = []
    _overlay_registry_nodes(nodes, edges, registry)
    meta = nodes["node-b39"]["metadata"]
    assert meta["health"] == "ONLINE"
    assert meta["telemetry_fields"] == 1
    assert meta["hardware_connected"] == 1
    assert meta["compute_available"] == 1
    assert meta["energy_source"] == "grid"


def test_worldgraph_builder_hardware_compute_flags():
    import anyio
    from coordinator.app.inventory_read import GraphResponse
    from coordinator.app.worldgraph import build_world_graph

    class FakeReader:
        async def graph(self, entity_id, depth=1):
            return GraphResponse(entity_id=entity_id,
                                 depth=depth, nodes=[], edges=[])

    registry = [{
        "node_id": "node-b39", "display_name": "Test",
        "hostname": "h", "derived_status": "online",
        "health_status": "ONLINE", "tier": "worker",
        "capabilities": ["a.b"], "models": [],
        "last_seen": "2026-09-19T00:00:00+00:00",
        "telemetry": {"cpu_percent": 10.0},
        "telemetry_timestamp": "2026-09-19T00:00:00+00:00",
        "hardware": [{"kind": "camera",
                      "identifier": "/dev/video0",
                      "details": {}, "status": "connected",
                      "connected_since": "t"}],
        "compute_capabilities": [
            {"capability": "ollama", "details": {},
             "status": "available", "since": "t"}],
        "energy_state": {"source": "grid"},
    }]
    async def _build_full():
        return await build_world_graph(
            FakeReader(), "obj_x", 1, registry_nodes=registry,
            include_hardware=True, include_compute=True)

    graph = anyio.run(_build_full)
    ids = {node["id"] for node in graph["nodes"]}
    assert "node-b39" in ids
    assert "hw_node-b39_/dev/video0" in ids
    assert "compute_node-b39_ollama" in ids
    predicates = {edge["predicate"] for edge in graph["edges"]}
    assert "HAS" in predicates
    assert "PROVIDES" in predicates
    # Flags off: no hardware/compute overlay nodes.
    async def _build_plain():
        return await build_world_graph(
            FakeReader(), "obj_x", 1, registry_nodes=registry)

    plain = anyio.run(_build_plain)
    plain_ids = {node["id"] for node in plain["nodes"]}
    assert "node-b39" in plain_ids
    assert "hw_node-b39_/dev/video0" not in plain_ids
    assert "compute_node-b39_ollama" not in plain_ids


# -- node state bus events + notifications --------------------------------------

def test_node_bus_event_types_accepted():
    from coordinator.app.events import (
        EventRefusedError, new_event)
    for event_type in ("node.health_changed",
                       "node.hardware_changed",
                       "node.compute_changed",
                       "node.telemetry_received"):
        event = new_event(event_type, "telemetry check",
                          node_id="node-b39")
        assert event.event_type == event_type
        assert event.node_id == "node-b39"
    with pytest.raises(EventRefusedError):
        new_event("node.self_destruct", "nope")


def test_notify_center_big39_types(tmp_path, monkeypatch):
    from coordinator.app.notify_center import (
        NotifyRefusedError, capability, check_type, send)
    for client in make_client(tmp_path, monkeypatch):
        assert "node_degraded" in capability()["types"]
        assert capability()["transports"]["WEB_PUSH"][
            "state"] == "UNAVAILABLE"
        for kind in ("node_online", "node_degraded",
                     "node_stale", "hardware_connected",
                     "hardware_disconnected",
                     "capability_available",
                     "capability_unavailable", "telemetry_stale",
                     "mission_blocked_hardware"):
            assert check_type(kind) == kind
        receipt = send("node-b39", "node_degraded",
                       "Node degraded",
                       "telemetry older than 5 minutes")
        assert receipt["transport"] == "IN_APP"
        assert receipt["state"] == "DELIVERED_IN_APP"
        assert receipt["web_push"] == "UNAVAILABLE"
        with pytest.raises(NotifyRefusedError):
            check_type("node_self_destruct")


# -- node-client collectors validate ---------------------------------------------

def test_node_client_collectors_validate():
    from node_client.main import (
        collect_compute_capabilities, collect_energy_state,
        collect_hardware, collect_telemetry)
    from coordinator.app.nodes import (
        check_compute_capabilities, check_energy_state,
        check_hardware, check_telemetry)
    telemetry = collect_telemetry()
    assert check_telemetry(telemetry)["hostname"] != ""
    assert isinstance(check_hardware(collect_hardware()), list)
    assert isinstance(
        check_compute_capabilities(
            collect_compute_capabilities()), list)
    energy = collect_energy_state()
    assert check_energy_state(energy)["source"] in (
        "grid", "solar", "battery", "unknown")


# -- heartbeat schema bounds -----------------------------------------------------

def test_heartbeat_schema_bounds():
    from pydantic import ValidationError
    from coordinator.app.schemas import Heartbeat
    valid = Heartbeat(telemetry={"cpu_percent": 10.0},
                      hardware=[{"kind": "camera"}],
                      compute_capabilities=[
                          {"capability": "ollama"}],
                      energy_state={"source": "grid"})
    assert valid.telemetry == {"cpu_percent": 10.0}
    with pytest.raises(ValidationError):
        Heartbeat(hardware=[{"kind": "camera"}] * 51)
    with pytest.raises(ValidationError):
        Heartbeat(compute_capabilities=[
            {"capability": "ollama"}] * 21)
