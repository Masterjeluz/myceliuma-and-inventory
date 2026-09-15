"""Planning contract tests (Fase D/Q).

Plan validation, capability union, conversion into AdapterProposal
for the existing approval gate, and the no-second-mechanism rule.
"""

import pytest

from coordinator.app.adapter_contracts import AdapterProposal
from coordinator.app.plans import (
    Plan,
    PlanStep,
    plan_capabilities,
    plan_to_proposal,
    validate_plan,
)


def make_plan(**overrides):
    data = {
        "plan_id": "plan-1",
        "goal": "Verbeter de Mycelium UI",
        "summary": "kleine stappen",
        "steps": [
            {"step_id": "s1", "description": "Open projectdirectory",
             "required_capabilities": ["desktop.screen.read"],
             "requires_approval": False},
            {"step_id": "s2", "description": "Klik op Chat",
             "required_capabilities": ["desktop.mouse.click"],
             "requires_approval": True},
        ],
        "risks": ["verkeerde knop"],
    }
    data.update(overrides)
    steps = [step if isinstance(step, PlanStep) else PlanStep(**step)
             for step in data["steps"]]
    data["steps"] = steps
    return Plan(**data)


def test_valid_plan_passes():
    assert validate_plan(make_plan()).plan_id == "plan-1"


def test_empty_steps_refused():
    with pytest.raises(ValueError):
        make_plan(steps=[])


def test_too_many_steps_refused():
    steps = [{"step_id": f"s{i}", "description": "x"} for i in range(21)]
    with pytest.raises(ValueError):
        make_plan(steps=steps)


def test_duplicate_step_ids_refused():
    with pytest.raises(ValueError):
        validate_plan(make_plan(steps=[
            {"step_id": "s1", "description": "een"},
            {"step_id": "s1", "description": "twee"},
        ]))


def test_plan_claiming_no_approval_with_needy_steps_refused():
    with pytest.raises(ValueError):
        validate_plan(make_plan(requires_approval=False))


def test_plan_claiming_human_verified_refused():
    from coordinator.app.inventory_read import Provenance
    plan = make_plan()
    plan.provenance = Provenance(source_type="ai-generated",
                                 creator_id="p", human_verified=True)
    with pytest.raises(ValueError):
        validate_plan(plan)


def test_capability_union_sorted_unique():
    assert plan_capabilities(make_plan()) == [
        "desktop.mouse.click", "desktop.screen.read"]


def test_plan_to_proposal_reuses_approval_gate():
    proposal = plan_to_proposal(make_plan(), adapter_id="mycelium-plan",
                                request_id="req-plan-1")
    assert isinstance(proposal, AdapterProposal)
    assert proposal.requires_approval is True
    assert proposal.provenance.human_verified is False
    assert proposal.request_id == "req-plan-1"
    assert "Verbeter de Mycelium UI" in proposal.proposed_action
    assert "Klik op Chat" in proposal.proposed_action


def test_plan_to_proposal_needs_caller_ids():
    with pytest.raises(ValueError):
        plan_to_proposal(make_plan(), adapter_id=" ", request_id="r")
    with pytest.raises(ValueError):
        plan_to_proposal(make_plan(), adapter_id="a", request_id=" ")


def test_proposal_from_plan_passes_existing_approval_gate():
    from coordinator.app.approval import decide, request_approval
    proposal = plan_to_proposal(make_plan(), adapter_id="mycelium-plan",
                                request_id="req-plan-2")
    request = request_approval(proposal)
    assert decide(request, proposal, "YES").approved is True
    assert decide(request, proposal, "maybe").approved is False
