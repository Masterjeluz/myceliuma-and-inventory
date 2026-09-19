"""Routing engine tests (BIG #8).

Deterministic selection, eligibility gates, explanations,
energy-as-preference, locality, model-type routing. Scheduling
logic only — never model-quality ranking.
"""

import pytest

from coordinator.app.routing import (
    RouteDecision,
    check_policy,
    check_requirements,
    requirements_from_payload,
    route_task,
)


def node(node_id, **overrides):
    record = {
        "node_id": node_id,
        "capabilities": [],
        "models": [],
        "executors": [],
        "resources": {},
        "locality_zone": "local_network",
        "status": "online",
        "fresh": True,
        "authenticated": True,
    }
    record.update(overrides)
    return record


def req(**overrides):
    base = {"required_capabilities": []}
    base.update(overrides)
    return check_requirements(base)


def test_selects_capable_node_with_reasons():
    nodes = [
        node("node_cpu", capabilities=["exec:system_inventory"]),
        node("node_vision",
             capabilities=["camera.snapshot", "vision.describe"]),
    ]
    decision = route_task(
        req(required_capabilities=["vision.describe"]), nodes)
    assert decision.selected_node_id == "node_vision"
    assert decision.eligible_nodes == ["node_vision"]
    assert decision.rejected[0].node_id == "node_cpu"
    assert any("missing vision.describe" in reason
               for reason in decision.rejected[0].reasons)
    assert any("node_vision" in reason
               for reason in decision.reasons)
    assert decision.decided_at != ""


def test_deterministic_tie_break_by_node_id():
    nodes = [node("node_b", capabilities=["x.y"]),
             node("node_a", capabilities=["x.y"])]
    first = route_task(req(required_capabilities=["x.y"]), nodes)
    second = route_task(req(required_capabilities=["x.y"]),
                        list(reversed(nodes)))
    assert first.selected_node_id == "node_a"
    assert second.selected_node_id == "node_a"


def test_no_eligible_node_explains():
    decision = route_task(req(required_capabilities=["nope"]),
                          [node("n1")])
    assert decision.selected_node_id is None
    assert decision.eligible_nodes == []
    assert len(decision.rejected) == 1


def test_hard_gates_reject():
    base = dict(capabilities=["camera.snapshot"],
                executors=["exec:camera"],
                models=[{"model_id": "model:v",
                         "model_type": "vlm"}],
                locality_zone="local_network")
    cases = [
        (dict(fresh=False), "not fresh"),
        (dict(status="disabled"), "not live"),
        (dict(status="stale"), "not live"),
        (dict(authenticated=False), "not authenticated"),
        (dict(capabilities=[]), "missing camera.snapshot"),
        (dict(models=[]), "missing model type vlm"),
        (dict(executors=[]), "missing executor exec:camera"),
        (dict(locality_zone="remote_lan"),
         "does not satisfy 'local_network'"),
    ]
    requirements = req(
        required_capabilities=["camera.snapshot"],
        required_model_types=["vlm"],
        required_executor="exec:camera",
        locality="local_network")
    for overrides, marker in cases:
        candidate = node("n1", **{**base, **overrides})
        decision = route_task(requirements, [candidate])
        assert decision.selected_node_id is None, overrides
        assert any(marker in reason
                   for entry in decision.rejected
                   for reason in entry.reasons), overrides
    # Intact base passes.
    assert route_task(requirements,
                      [node("n1", **base)]).selected_node_id == "n1"


def test_model_type_and_executor_gates():
    vision = node("node_vision",
                  capabilities=["camera.snapshot"],
                  executors=["exec:vision"],
                  models=[{"model_id": "model:sim-vlm",
                           "model_type": "vlm"}])
    cpu = node("node_cpu", capabilities=["camera.snapshot"],
               executors=["exec:system_inventory"])
    requirements = req(required_capabilities=["camera.snapshot"],
                       required_model_types=["vlm"],
                       required_executor="exec:vision")
    decision = route_task(requirements, [cpu, vision])
    assert decision.selected_node_id == "node_vision"


def test_preferred_models_order_but_never_require():
    low = node("node_a", capabilities=["x.y"],
               models=[{"model_id": "model:other",
                        "model_type": "llm"}])
    high = node("node_b", capabilities=["x.y"],
                models=[{"model_id": "mod_want",
                         "model_type": "llm"}])
    decision = route_task(
        req(required_capabilities=["x.y"],
            preferred_model_ids=["mod_want"]), [low, high])
    assert decision.selected_node_id == "node_b"
    # Without the preference both stay eligible (tie-break wins).
    plain = route_task(req(required_capabilities=["x.y"]),
                       [low, high])
    assert plain.selected_node_id == "node_a"


def test_energy_is_preference_never_disqualifier():
    grid = node("node_grid", capabilities=["x.y"],
                resources={"energy_source": "grid",
                           "energy_level": 10})
    solar = node("node_solar", capabilities=["x.y"],
                 resources={"energy_source": "solar",
                            "energy_level": 90})
    policy = check_policy({"prefer_solar": True,
                           "min_energy_level": 50})
    decision = route_task(req(required_capabilities=["x.y"]),
                          [grid, solar], policy)
    assert decision.selected_node_id == "node_solar"
    assert any("hint only" in reason or "policy-compatible" in reason
               for reason in decision.reasons)
    # Grid node alone stays eligible despite weak hints.
    alone = route_task(req(required_capabilities=["x.y"]), [grid],
                       policy)
    assert alone.selected_node_id == "node_grid"


def test_locality_matching():
    here = node("node_here", capabilities=["x.y"],
                locality_zone="same_host")
    away = node("node_away", capabilities=["x.y"],
                locality_zone="remote_lan")
    decision = route_task(req(required_capabilities=["x.y"],
                              locality="same_host"), [away, here])
    assert decision.selected_node_id == "node_here"
    open_decision = route_task(req(required_capabilities=["x.y"]),
                               [away, here])
    assert open_decision.selected_node_id in ("node_away",
                                              "node_here")


def test_requirements_validation_tripwires():
    assert check_requirements(None).required_capabilities == []
    assert requirements_from_payload({}).required_capabilities == []
    assert requirements_from_payload(None).required_capabilities == []
    assert requirements_from_payload(
        {"routing": {"required_capabilities": ["a.b"]}}
    ).required_capabilities == ["a.b"]
    for bad in ({"required_capabilities": ["*"]},
                {"required_capabilities": ["rm -rf"]},
                {"required_capabilities": ["a/b"]},
                {"required_capabilities": "not-a-list"},
                {"required_model_types": ["agi"]},
                {"preferred_model_ids": ["qwen"]},
                {"required_executor": "desktop"},
                {"required_executor": "exec:*"},
                {"locality": "internet"},
                {"min_memory_mb": -1},
                {"arbitrary_code": "x"},
                "not-a-dict"):
        with pytest.raises(ValueError):
            check_requirements(bad)
    with pytest.raises(ValueError):
        check_policy("nope")
    assert isinstance(route_task(req(), []), RouteDecision)


# -- BIG #39: Hardware Reality Layer routing tests --

from datetime import datetime, timezone, timedelta


def node_with_telemetry(node_id, **overrides):
    """Create a node with telemetry and hardware reality layer fields."""
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "node_id": node_id,
        "capabilities": ["x.y"],  # Default capability for tests
        "models": [],
        "executors": [],
        "resources": {},
        "locality_zone": "local_network",
        "status": "online",
        "fresh": True,
        "authenticated": True,
        "telemetry": {"cpu_percent": 10},
        "telemetry_timestamp": now,
        "hardware": [{"kind": "camera", "identifier": "cam1", "status": "connected"}],
        "compute_capabilities": [{"capability": "ollama", "status": "available"}],
        "energy_state": {"source": "grid", "level_percent": 100},
        "health_status": "ONLINE",
    }
    record.update(overrides)
    return record


def test_required_hardware_gate():
    """Required hardware is a hard gate - missing connected hardware rejects."""
    cam_node = node_with_telemetry("node_cam",
        hardware=[{"kind": "camera", "identifier": "cam1", "status": "connected"}])
    no_cam_node = node_with_telemetry("node_no_cam",
        hardware=[{"kind": "usb", "identifier": "usb1", "status": "connected"}])
    req = check_requirements({
        "required_capabilities": ["x.y"],
        "required_hardware": ["camera"],
    })
    # Node with camera passes
    decision = route_task(req, [cam_node, no_cam_node])
    assert decision.selected_node_id == "node_cam"
    # Node without camera is rejected
    assert any("missing connected hardware camera" in r
               for r in decision.rejected[0].reasons)
    # Disconnected hardware doesn't count
    disconnected = node_with_telemetry("node_disc",
        hardware=[{"kind": "camera", "identifier": "cam1", "status": "disconnected"}])
    decision = route_task(req, [disconnected])
    assert decision.selected_node_id is None


def test_required_compute_gate():
    """Required compute capability is a hard gate."""
    gpu_node = node_with_telemetry("node_gpu",
        compute_capabilities=[{"capability": "gpu_available", "status": "available"}])
    cpu_node = node_with_telemetry("node_cpu",
        compute_capabilities=[{"capability": "cpu_inference", "status": "available"}])
    req = check_requirements({
        "required_capabilities": ["x.y"],
        "required_compute": ["gpu_available"],
    })
    decision = route_task(req, [gpu_node, cpu_node])
    assert decision.selected_node_id == "node_gpu"
    assert any("missing available compute gpu_available" in r
               for r in decision.rejected[0].reasons)
    # Busy compute doesn't count
    busy = node_with_telemetry("node_busy",
        compute_capabilities=[{"capability": "gpu_available", "status": "busy"}])
    decision = route_task(req, [busy])
    assert decision.selected_node_id is None


def test_max_telemetry_age_gate():
    """Max telemetry age is a hard gate."""
    now = datetime.now(timezone.utc).isoformat()
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    fresh_node = node_with_telemetry("node_fresh", telemetry_timestamp=now)
    stale_node = node_with_telemetry("node_stale", telemetry_timestamp=old_ts)
    req = check_requirements({
        "required_capabilities": ["x.y"],
        "max_telemetry_age_seconds": 300,  # 5 minutes
    })
    decision = route_task(req, [fresh_node, stale_node])
    assert decision.selected_node_id == "node_fresh"
    assert any("telemetry too old" in r for r in decision.rejected[0].reasons)
    # No telemetry timestamp fails
    no_ts = node_with_telemetry("node_no_ts", telemetry_timestamp="")
    decision = route_task(req, [no_ts])
    assert decision.selected_node_id is None
    assert any("no telemetry timestamp" in r for r in decision.rejected[0].reasons)


def test_min_health_gate():
    """Minimum health is a hard gate."""
    online = node_with_telemetry("node_online", health_status="ONLINE")
    degraded = node_with_telemetry("node_degraded", health_status="DEGRADED")
    stale = node_with_telemetry("node_stale", health_status="STALE")
    req = check_requirements({
        "required_capabilities": ["x.y"],
        "min_health": "ONLINE",
    })
    decision = route_task(req, [online, degraded, stale])
    assert decision.selected_node_id == "node_online"
    assert len(decision.rejected) == 2
    # DEGRADED is below ONLINE
    assert any("health DEGRADED below minimum ONLINE" in r
               for r in decision.rejected[0].reasons)
    # Lower min_health allows more - both ONLINE and DEGRADED eligible
    # Tie-break by node_id: node_degraded < node_online alphabetically
    req2 = check_requirements({
        "required_capabilities": ["x.y"],
        "min_health": "DEGRADED",
    })
    decision2 = route_task(req2, [online, degraded, stale])
    assert decision2.selected_node_id == "node_degraded"
    assert len(decision2.rejected) == 1  # only STALE rejected


def test_telemetry_freshness_preference():
    """Fresh telemetry gives preference bonus."""
    now = datetime.now(timezone.utc).isoformat()
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    fresh = node_with_telemetry("node_fresh", telemetry_timestamp=now)
    stale = node_with_telemetry("node_stale", telemetry_timestamp=old_ts)
    policy = check_policy({"prefer_fresh_telemetry": True})
    req = check_requirements({"required_capabilities": ["x.y"]})
    decision = route_task(req, [stale, fresh], policy)
    assert decision.selected_node_id == "node_fresh"
    assert any("fresh telemetry" in r for r in decision.reasons)


def test_connected_hardware_preference():
    """Connected hardware count gives preference bonus."""
    hw_node = node_with_telemetry("node_hw",
        hardware=[{"kind": "camera", "identifier": "cam1", "status": "connected"},
                  {"kind": "printer_3d", "identifier": "printer1", "status": "connected"}])
    no_hw = node_with_telemetry("node_no_hw", hardware=[])
    policy = check_policy({"prefer_connected_hardware": True})
    req = check_requirements({"required_capabilities": ["x.y"]})
    decision = route_task(req, [no_hw, hw_node], policy)
    assert decision.selected_node_id == "node_hw"
    assert any("2 connected hardware item" in r for r in decision.reasons)


def test_compute_capabilities_preference():
    """Available compute capabilities give preference bonus."""
    compute_node = node_with_telemetry("node_compute",
        compute_capabilities=[{"capability": "ollama", "status": "available"},
                              {"capability": "gpu_available", "status": "available"}])
    no_compute = node_with_telemetry("node_no_compute",
        compute_capabilities=[{"capability": "cpu_inference", "status": "unavailable"}])
    policy = check_policy({"prefer_compute_capabilities": True})
    req = check_requirements({"required_capabilities": ["x.y"]})
    decision = route_task(req, [no_compute, compute_node], policy)
    assert decision.selected_node_id == "node_compute"
    assert any("available compute capability" in r for r in decision.reasons)


def test_required_hardware_positive_reason():
    """Required hardware present shows as positive reason."""
    cam_node = node_with_telemetry("node_cam",
        hardware=[{"kind": "camera", "identifier": "cam1", "status": "connected"}])
    req = check_requirements({
        "required_capabilities": ["x.y"],
        "required_hardware": ["camera"],
    })
    decision = route_task(req, [cam_node])
    assert any("required hardware camera connected" in r for r in decision.reasons)


def test_required_compute_positive_reason():
    """Required compute present shows as positive reason."""
    gpu_node = node_with_telemetry("node_gpu",
        compute_capabilities=[{"capability": "gpu_available", "status": "available"}])
    req = check_requirements({
        "required_capabilities": ["x.y"],
        "required_compute": ["gpu_available"],
    })
    decision = route_task(req, [gpu_node])
    assert any("required compute gpu_available available" in r for r in decision.reasons)


def test_invalid_required_hardware_refused():
    """Invalid required_hardware values are refused at validation."""
    with pytest.raises(ValueError):
        check_requirements({"required_hardware": ["invalid_kind"]})


def test_invalid_required_compute_refused():
    """Invalid required_compute values are refused at validation."""
    with pytest.raises(ValueError):
        check_requirements({"required_compute": ["quantum"]})


def test_invalid_min_health_refused():
    """Invalid min_health values are refused at validation."""
    with pytest.raises(ValueError):
        check_requirements({"min_health": "SUPER_HEALTHY"})
