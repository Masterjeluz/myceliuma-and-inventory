"""Planning contract for Mycelium (Fase D).

AI advice is not execution. A Plan sits between them: a goal, a list
of steps, and the capabilities each step needs. Plans never execute
anything and never approve anything. When a plan is good enough to
act on, it converts into exactly one AdapterProposal, which re-enters
the existing M6.3 approval gate — there is deliberately no second
approval mechanism.

Rules (tested):

- a plan has a goal (1..500 chars) and 1..20 steps; empty plans and
  step-less goals are refused.
- every step describes its action (1..500 chars); required
  capabilities are explicit strings, at most 10 per step.
- requires_approval is derived: True when any step needs it (default
  True; only all-manual-read steps may relax it, never silently).
- provenance is always ai-generated/unverified here; human verification
  can only arrive later through the approval gate.
- plan_to_proposal() preserves goal, steps, capabilities and risks in
  the proposal text so the operator decides on the full content.
"""

from pydantic import BaseModel, ConfigDict, Field

from .adapter_contracts import AdapterProposal
from .inventory_read import Provenance

MAX_STEPS = 20
MAX_GOAL_CHARS = 500
MAX_STEP_CHARS = 500
MAX_STEP_CAPABILITIES = 10
MAX_RISK_ITEMS = 20
MAX_RISK_CHARS = 200


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=MAX_STEP_CHARS)
    required_capabilities: list[str] = Field(default_factory=list,
                                             max_length=MAX_STEP_CAPABILITIES)
    requires_approval: bool = True


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=3, max_length=80)
    goal: str = Field(min_length=1, max_length=MAX_GOAL_CHARS)
    summary: str = Field(default="", max_length=2000)
    steps: list[PlanStep] = Field(min_length=1, max_length=MAX_STEPS)
    risks: list[str] = Field(default_factory=list, max_length=MAX_RISK_ITEMS)
    provenance: Provenance = Field(default_factory=Provenance)
    requires_approval: bool = True


def validate_plan(plan: Plan) -> Plan:
    """Fail-closed plan check: structure, approval flag, provenance."""
    if not isinstance(plan, Plan):
        raise ValueError("Planning needs a Plan")
    if plan.requires_approval is not True and any(
            step.requires_approval for step in plan.steps):
        raise ValueError(
            "Plan steps need approval but the plan claims otherwise")
    if plan.provenance.human_verified:
        raise ValueError("Plans are AI output and must not claim "
                         "human verification")
    seen = set()
    for step in plan.steps:
        if step.step_id in seen:
            raise ValueError(f"Duplicate step_id '{step.step_id}'")
        seen.add(step.step_id)
        for capability in step.required_capabilities:
            if not isinstance(capability, str) or not capability.strip():
                raise ValueError("Step capabilities must be non-empty text")
    return plan


def plan_capabilities(plan: Plan) -> list[str]:
    """Union of step capabilities, sorted and deduplicated."""
    capabilities: set[str] = set()
    for step in plan.steps:
        capabilities.update(capability.strip() for capability
                            in step.required_capabilities
                            if capability.strip())
    return sorted(capabilities)


def plan_to_proposal(plan: Plan, *, adapter_id: str,
                     request_id: str) -> AdapterProposal:
    """Convert a validated plan into one AdapterProposal for approval.

    IDs come from the caller; the plan supplies goal/steps/risks as the
    proposed action text. Provenance is set locally (ai-generated,
    unverified); plan-supplied provenance never transfers trust.
    """
    validate_plan(plan)
    if not isinstance(adapter_id, str) or not adapter_id.strip():
        raise ValueError("adapter_id must be non-empty text")
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request_id must be non-empty text")
    lines = [f"Doel: {plan.goal.strip()}"]
    if plan.summary.strip():
        lines.append(f"Samenvatting: {plan.summary.strip()[:500]}")
    lines.append("Stappen:")
    for position, step in enumerate(plan.steps, start=1):
        capabilities = ", ".join(step.required_capabilities) or "geen"
        lines.append(f"{position}. {step.description.strip()} "
                     f"[capabilities: {capabilities}]")
    action = "\n".join(lines)
    if len(action) > 2000:
        action = action[:1999] + "…"
    risks = [risk for risk in plan.risks
             if isinstance(risk, str) and risk.strip()][:MAX_RISK_ITEMS]
    return AdapterProposal(
        proposal_id=f"prop-{request_id.strip()}"[:80],
        request_id=request_id.strip(),
        adapter_id=adapter_id.strip(),
        proposed_action=action,
        expected_output=f"Plan '{plan.plan_id}' uitgevoerd stap voor stap",
        risks=[risk.strip()[:MAX_RISK_CHARS] for risk in risks],
        provenance=Provenance(
            source_type="ai-generated",
            creator_id=f"planner:{adapter_id.strip()}",
            human_verified=False,
            notes=f"converted from plan {plan.plan_id}; "
                  "approval still required",
        ),
        requires_approval=True,
    )
