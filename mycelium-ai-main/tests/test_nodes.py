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
    check_executors,
    check_locality,
    check_models,
    check_resources,
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
