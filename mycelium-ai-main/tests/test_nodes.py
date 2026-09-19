"""Node registry tests (BIG #8).

Identity, advertisement validation, token auth, freshness
status, disable/enable. Pure nodes.py behavior plus HTTP
register/heartbeat flows.
"""

import pytest

from coordinator.app.nodes import (
    NodeAuthError,
    NodeRefusedError,
    authenticate,
    check_capabilities,
    check_compute_capabilities,
    check_energy_state,
    check_executors,
    check_hardware,
    check_locality,
    check_models,
    check_resources,
    check_telemetry,
    compute_node_health,
    derive_status,
    generate_token,
    hash_token,
    verify_token,
)


def test_token_lifecycle():
    token = generate_token()
    assert len(token) == 64
    stored = hash_token("node-1", token)
    assert stored != token
    assert len(stored) == 64
    assert verify_token("node-1", token, stored) is True
    assert verify_token("node-1", "wrong", stored) is False
    assert verify_token("node-2", token, stored) is False
    assert authenticate("node-1", None, None) == "legacy"
    assert authenticate("node-1", stored, token) == "token"
    with pytest.raises(NodeAuthError):
        authenticate("node-1", stored, "wrong")
    with pytest.raises(NodeAuthError):
        authenticate("node-1", stored, None)


def test_capabilities_closed():
    assert check_capabilities(["camera.snapshot"]) == [
        "camera.snapshot"]
    for bad in (["*"], ["camera.*"], ["rm -rf"], ["a b"],
                ["x" * 81], ["bad/slash"], ["semi;colon"]):
        with pytest.raises(NodeRefusedError):
            check_capabilities(bad)
    with pytest.raises(NodeRefusedError):
        check_capabilities("not-a-list")
    with pytest.raises(NodeRefusedError):
        check_capabilities(["ok"] * 51)


def test_executors_namespaced():
    assert check_executors(["exec:desktop"]) == ["exec:desktop"]
    for bad in (["desktop"], ["exec:Desktop X"], ["exec:*"],
                ["shell.exec"]):
        with pytest.raises(NodeRefusedError):
            check_executors(bad)


def test_models_validated():
    models = check_models([{
        "model_id": "mod_abc123", "display_name": "Qwen",
        "model_type": "llm", "capabilities": ["text.generate"],
        "provider": "ollama", "status": "available"}])
    assert models[0]["model_id"] == "mod_abc123"
    local = check_models([{"model_id": "model:sim-vlm",
                           "model_type": "vlm"}])
    assert local[0]["provider"] == "local"
    for bad in ([{"model_id": "qwen", "model_type": "llm"}],
                [{"model_id": "mod_x", "model_type": "agi"}],
                [{"model_id": "mod_x", "model_type": "llm",
                  "provider": "https://evil.example/model"}],
                [{"model_id": "mod_x", "model_type": "llm",
                  "api_key": "x"}],
                [{"model_id": "mod_x", "model_type": "llm",
                  "capabilities": ["*"]}],
                "not-a-list"):
        with pytest.raises(NodeRefusedError):
            check_models(bad)


def test_resources_bounded_hints():
    resources = check_resources({"cpu_cores": 4, "memory_mb": 8000,
                                 "gpu_available": True,
                                 "energy_source": "solar",
                                 "energy_level": 80,
                                 "energy_priority": "high"})
    assert resources["energy_level"] == 80
    assert check_resources(None) == {}
    for bad in ({"energy_source": "coal"},
                {"energy_level": 101},
                {"energy_level": -1},
                {"energy_priority": "urgent"},
                {"cpu_cores": -2},
                {"gpu_available": "yes"},
                {"backdoor": 1},
                "not-a-dict"):
        with pytest.raises(NodeRefusedError):
            check_resources(bad)


def test_locality_closed():
    assert check_locality("same_host") == "same_host"
    assert check_locality(None) == "local_network"
    with pytest.raises(NodeRefusedError):
        check_locality("internet")


def test_derive_status():
    assert derive_status("disabled", "2026-01-01T00:00:00+00:00",
                         "2026-06-01T00:00:00+00:00") == "disabled"
    assert derive_status("online", "2026-01-01T00:00:00+00:00",
                         "2026-01-01T00:00:30+00:00") == "online"
    assert derive_status("online", "2026-01-01T00:00:00+00:00",
                         "2026-01-01T00:05:00+00:00") == "stale"
    assert derive_status("offline", "2020-01-01T00:00:00+00:00",
                         "2026-01-01T00:00:00+00:00") == "offline"
    assert derive_status("busy", "2026-01-01T00:00:00+00:00",
                         "2026-01-01T00:00:10+00:00") == "busy"
    assert derive_status("weird", "2026-01-01T00:00:00+00:00",
                         "2026-01-01T00:00:10+00:00") == "unknown"
    assert derive_status("online", "not-a-time",
                         "2026-01-01T00:00:10+00:00") == "stale"


# -- Telemetry validation (BIG #39 Hardware Reality Layer) --

def test_telemetry_valid():
    """Test valid telemetry payload."""
    telemetry = {
        "hostname": "test-node",
        "os": "Linux",
        "platform": "Linux-5.15.0",
        "cpu_percent": 45.5,
        "cpu_count": 8,
        "memory_percent": 60.0,
        "memory_total_mb": 16384,
        "memory_available_mb": 6554,
        "disk_percent": 40.0,
        "disk_total_gb": 500.0,
        "disk_free_gb": 300.0,
        "uptime_seconds": 3600,
        "temperature_celsius": 42.5,
        "load_average": [1.2, 1.5, 1.8],
        "network_interfaces": ["eth0", "wlan0"],
        "boot_time": 1700000000,
    }
    result = check_telemetry(telemetry)
    assert result["hostname"] == "test-node"
    assert result["cpu_percent"] == 45.5
    assert result["memory_percent"] == 60.0
    assert result["load_average"] == [1.2, 1.5, 1.8]
    assert result["network_interfaces"] == ["eth0", "wlan0"]


def test_telemetry_unknown_fields_refused():
    """Unknown telemetry fields are refused."""
    for bad in ({"unknown_field": 1}, {"cpu_percent": 10, "evil": "x"}):
        with pytest.raises(NodeRefusedError):
            check_telemetry(bad)


def test_telemetry_bounds_enforced():
    """Telemetry numeric bounds are enforced."""
    for field, bad_value in [
        ("cpu_percent", -1),
        ("cpu_percent", 101),
        ("memory_percent", -5),
        ("memory_percent", 150),
        ("disk_percent", 101),
        ("temperature_celsius", -51),
        ("temperature_celsius", 151),
        ("memory_total_mb", -1),
        ("memory_total_mb", 10**10),
        ("uptime_seconds", -1),
    ]:
        with pytest.raises(NodeRefusedError):
            check_telemetry({field: bad_value})


def test_telemetry_load_average_format():
    """Load average must be [1m, 5m, 15m] - exactly 3 elements."""
    assert check_telemetry({"load_average": [1.0, 2.0, 3.0]})["load_average"] == [1.0, 2.0, 3.0]
    # Length must be exactly 3
    for bad in ([1.0], [1.0, 2.0], [1.0, 2.0, 3.0, 4.0], "not-a-list"):
        with pytest.raises(NodeRefusedError):
            check_telemetry({"load_average": bad})
    # Non-numeric values are filtered out but original length must be 3
    result = check_telemetry({"load_average": [1.0, "bad", 3.0]})
    assert result["load_average"] == [1.0, 3.0]


def test_telemetry_network_interfaces():
    """Network interfaces must be a list, truncated to 20."""
    assert check_telemetry({"network_interfaces": ["eth0"]})["network_interfaces"] == ["eth0"]
    long_list = [f"if{i}" for i in range(25)]
    result = check_telemetry({"network_interfaces": long_list})
    assert len(result["network_interfaces"]) == 20  # truncated to 20 in validation
    with pytest.raises(NodeRefusedError):
        check_telemetry({"network_interfaces": "not-a-list"})


def test_telemetry_string_fields():
    """String fields are stripped and bounded."""
    result = check_telemetry({"hostname": "  test-node  ", "os": "Linux", "platform": "x"})
    assert result["hostname"] == "test-node"
    long_str = "x" * 150
    result = check_telemetry({"hostname": long_str})
    assert len(result["hostname"]) == 120
    with pytest.raises(NodeRefusedError):
        check_telemetry({"hostname": 123})


def test_telemetry_none_returns_empty():
    assert check_telemetry(None) == {}


def test_telemetry_not_dict_refused():
    with pytest.raises(NodeRefusedError):
        check_telemetry("not-a-dict")


def test_telemetry_too_many_fields():
    fields = {f"field{i}": i for i in range(35)}
    # Need to include at least one valid field
    fields["cpu_percent"] = 50
    with pytest.raises(NodeRefusedError):
        check_telemetry(fields)


# -- Hardware inventory validation (BIG #39) --

def test_hardware_valid():
    """Test valid hardware inventory."""
    hardware = [
        {"kind": "camera", "identifier": "/dev/video0", "details": {"subsystem": "v4l2"}, "status": "connected", "connected_since": 1700000000},
        {"kind": "usb", "identifier": "1-1.2", "details": {"description": "Logitech Webcam"}, "status": "connected", "connected_since": 1700000000},
        {"kind": "gpu", "identifier": "NVIDIA RTX 3080", "details": {"memory_mb": "10240", "vendor": "nvidia"}, "status": "connected"},
    ]
    result = check_hardware(hardware)
    assert len(result) == 3
    assert result[0]["kind"] == "camera"
    assert result[0]["identifier"] == "/dev/video0"
    assert result[1]["kind"] == "usb"
    assert result[2]["details"]["vendor"] == "nvidia"


def test_hardware_unknown_kind_refused():
    with pytest.raises(NodeRefusedError):
        check_hardware([{"kind": "invalid_kind", "identifier": "test"}])


def test_hardware_missing_identifier_refused():
    with pytest.raises(NodeRefusedError):
        check_hardware([{"kind": "camera", "identifier": ""}])


def test_hardware_status_normalized():
    """Hardware status is normalized."""
    result = check_hardware([{"kind": "camera", "identifier": "cam1", "status": "CONNECTED"}])
    assert result[0]["status"] == "connected"
    result = check_hardware([{"kind": "camera", "identifier": "cam1", "status": "weird"}])
    assert result[0]["status"] == "unknown"


def test_hardware_details_optional():
    """Hardware details defaults to empty dict."""
    result = check_hardware([{"kind": "camera", "identifier": "cam1"}])
    assert result[0]["details"] == {}


def test_hardware_connected_since_bounded():
    """Connected since is bounded and stringified."""
    result = check_hardware([{"kind": "camera", "identifier": "cam1", "connected_since": 1700000000.123}])
    assert result[0]["connected_since"] == "1700000000.123"


def test_hardware_none_returns_empty():
    assert check_hardware(None) == []


def test_hardware_not_list_refused():
    with pytest.raises(NodeRefusedError):
        check_hardware("not-a-list")


def test_hardware_too_many_items():
    items = [{"kind": "camera", "identifier": f"cam{i}"} for i in range(55)]
    with pytest.raises(NodeRefusedError):
        check_hardware(items)


def test_hardware_unknown_fields_refused():
    with pytest.raises(NodeRefusedError):
        check_hardware([{"kind": "camera", "identifier": "cam1", "evil": "x"}])


# -- Compute capabilities validation (BIG #39) --

def test_compute_capabilities_valid():
    """Test valid compute capabilities."""
    compute = [
        {"capability": "ollama", "details": {"models": ["llama3", "qwen2"]}, "status": "available", "since": 1700000000},
        {"capability": "gpu_available", "details": {"vendor": "nvidia"}, "status": "available"},
        {"capability": "vram_mb", "details": {"vram_mb": 10240}, "status": "available"},
    ]
    result = check_compute_capabilities(compute)
    assert len(result) == 3
    assert result[0]["capability"] == "ollama"
    assert result[1]["capability"] == "gpu_available"
    assert result[2]["details"]["vram_mb"] == 10240


def test_compute_unknown_capability_refused():
    with pytest.raises(NodeRefusedError):
        check_compute_capabilities([{"capability": "quantum", "details": {}}])


def test_compute_status_normalized():
    """Compute status is normalized."""
    result = check_compute_capabilities([{"capability": "ollama", "status": "BUSY"}])
    assert result[0]["status"] == "busy"
    result = check_compute_capabilities([{"capability": "ollama", "status": "weird"}])
    assert result[0]["status"] == "unknown"


def test_compute_details_optional():
    result = check_compute_capabilities([{"capability": "ollama"}])
    assert result[0]["details"] == {}


def test_compute_since_bounded():
    result = check_compute_capabilities([{"capability": "ollama", "since": 1700000000.123}])
    assert result[0]["since"] == "1700000000.123"


def test_compute_none_returns_empty():
    assert check_compute_capabilities(None) == []


def test_compute_not_list_refused():
    with pytest.raises(NodeRefusedError):
        check_compute_capabilities("not-a-list")


def test_compute_too_many_items():
    items = [{"capability": "cpu_inference"} for _ in range(25)]
    with pytest.raises(NodeRefusedError):
        check_compute_capabilities(items)


def test_compute_unknown_fields_refused():
    with pytest.raises(NodeRefusedError):
        check_compute_capabilities([{"capability": "ollama", "evil": "x"}])


# -- Energy state validation (BIG #39) --

def test_energy_state_valid():
    """Test valid energy state."""
    energy = {
        "source": "battery",
        "level_percent": 75,
        "charging": False,
        "details": {"health": "good"},
        "since": 1700000000,
    }
    result = check_energy_state(energy)
    assert result["source"] == "battery"
    assert result["level_percent"] == 75
    assert result["charging"] is False
    assert result["details"]["health"] == "good"
    assert result["since"] == "1700000000"


def test_energy_state_source_closed_set():
    """Energy source must be from closed set."""
    assert check_energy_state({"source": "solar"})["source"] == "solar"
    assert check_energy_state({"source": "grid"})["source"] == "grid"
    with pytest.raises(NodeRefusedError):
        check_energy_state({"source": "fusion"})


def test_energy_state_level_bounds():
    """Energy level must be 0-100."""
    assert check_energy_state({"source": "battery", "level_percent": 0})["level_percent"] == 0
    assert check_energy_state({"source": "battery", "level_percent": 100})["level_percent"] == 100
    for bad in (-1, 101, "not-a-number", True):
        with pytest.raises(NodeRefusedError):
            check_energy_state({"source": "battery", "level_percent": bad})


def test_energy_state_charging_boolean():
    """Charging must be boolean."""
    assert check_energy_state({"source": "grid", "charging": True})["charging"] is True
    assert check_energy_state({"source": "battery", "charging": False})["charging"] is False
    with pytest.raises(NodeRefusedError):
        check_energy_state({"source": "grid", "charging": "yes"})


def test_energy_state_none_returns_empty():
    assert check_energy_state(None) == {}


def test_energy_state_not_dict_refused():
    with pytest.raises(NodeRefusedError):
        check_energy_state("not-a-dict")


def test_energy_state_unknown_fields_refused():
    with pytest.raises(NodeRefusedError):
        check_energy_state({"source": "battery", "evil": "x"})


def test_energy_state_since_bounded():
    result = check_energy_state({"source": "battery", "since": 1700000000.123})
    assert result["since"] == "1700000000.123"


# -- compute_node_health (BIG #39) --

def test_compute_node_health_online():
    """Online node with fresh telemetry = ONLINE."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "derived_status": "online",
        "telemetry_timestamp": now,
        "telemetry": {"cpu_percent": 50},
        "hardware": [{"status": "connected"}],
        "compute_capabilities": [{"capability": "ollama", "status": "available"}],
        "energy_state": {"source": "grid", "level_percent": 100},
    }
    health = compute_node_health(record)
    assert health["health"] == "ONLINE"
    assert health["details"]["telemetry_age_seconds"] is not None
    assert health["details"]["telemetry_age_seconds"] < 60


def test_compute_node_health_degraded():
    """Online node with stale telemetry = DEGRADED."""
    from datetime import datetime, timezone, timedelta
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    record = {
        "derived_status": "online",
        "telemetry_timestamp": old_ts,
        "telemetry": {},
        "hardware": [],
        "compute_capabilities": [],
        "energy_state": {},
    }
    health = compute_node_health(record)
    assert health["health"] == "DEGRADED"


def test_compute_node_health_stale():
    """Stale derived status = STALE."""
    record = {
        "derived_status": "stale",
        "telemetry_timestamp": "2026-01-01T12:00:00+00:00",
        "telemetry": {},
        "hardware": [],
        "compute_capabilities": [],
        "energy_state": {},
    }
    health = compute_node_health(record)
    assert health["health"] == "STALE"


def test_compute_node_health_offline():
    """Disabled/offline = OFFLINE."""
    for status in ("disabled", "offline"):
        record = {
            "derived_status": status,
            "telemetry_timestamp": "2026-01-01T12:00:00+00:00",
            "telemetry": {},
            "hardware": [],
            "compute_capabilities": [],
            "energy_state": {},
        }
        health = compute_node_health(record)
        assert health["health"] == "OFFLINE"


def test_compute_node_health_unknown():
    """Unknown derived status = UNKNOWN."""
    record = {
        "derived_status": "weird",
        "telemetry_timestamp": "2026-01-01T12:00:00+00:00",
        "telemetry": {},
        "hardware": [],
        "compute_capabilities": [],
        "energy_state": {},
    }
    health = compute_node_health(record)
    assert health["health"] == "UNKNOWN"


def test_compute_node_health_no_telemetry():
    """Online node with no telemetry = DEGRADED."""
    record = {
        "derived_status": "online",
        "telemetry_timestamp": "",
        "telemetry": {},
        "hardware": [],
        "compute_capabilities": [],
        "energy_state": {},
    }
    health = compute_node_health(record)
    assert health["health"] == "DEGRADED"
