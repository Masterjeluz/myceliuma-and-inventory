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
