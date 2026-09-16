"""Deterministic task routing for distributed Mycelium (BIG #8).

Scheduling logic, not model-quality ranking: a task declares
closed requirements, the router compares them against what
nodes advertised, and selects deterministically with a full
explanation. No wildcards, no inheritance, no task-granted
capabilities, no "best/smartest model" claims anywhere.

Eligibility (all hard, any failure rejects the node):

1. node is live (fresh, status online/busy, not disabled)
2. node authenticated (when policy requires it)
3. required capabilities ⊆ advertised capabilities
4. required model types each present on the node
5. required executor advertised (when set)
6. locality label compatible (or requirement 'any')

Ordering among eligible nodes (preferences, never requirements):

- preferred model id present (+2 each, capped)
- energy policy compatible (+1): solar source when the policy
  prefers it, energy_level meeting the policy minimum
- resource minimums met (+1): min_memory_mb, needs_gpu
- deterministic tie-break: lowest node_id wins

Energy and resources never disqualify; they only order. A node
that fails a required capability is never selected regardless
of preferences. Every decision carries inspectable reasons;
credentials never appear in any output.
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .nodes import (
    VALID_LOCALITIES,
    VALID_MODEL_TYPES,
    check_capabilities,
    check_locality,
    check_model_id,
)

MAX_REQUIREMENTS = 30
MAX_MODEL_IDS = 10


class TaskRequirements(BaseModel):
    """Declarative task requirements. Closed fields only: no code,
    no commands, no paths, no executable references."""

    model_config = ConfigDict(extra="forbid")

    required_capabilities: list[str] = Field(default_factory=list,
                                             max_length=MAX_REQUIREMENTS)
    required_model_types: list[str] = Field(default_factory=list,
                                            max_length=MAX_MODEL_IDS)
    preferred_model_ids: list[str] = Field(default_factory=list,
                                           max_length=MAX_MODEL_IDS)
    required_executor: str = Field(default="", max_length=80)
    min_memory_mb: int = Field(default=0, ge=0, le=10**9)
    needs_gpu: bool = False
    locality: str = Field(default="any", max_length=20)
    physical_action: bool = False


class RoutingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefer_solar: bool = False
    min_energy_level: int | None = Field(default=None, ge=0, le=100)
    require_authenticated: bool = True


class RejectedNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = ""
    reasons: list[str] = Field(default_factory=list)


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_node_id: str | None = None
    eligible_nodes: list[str] = Field(default_factory=list)
    rejected: list[RejectedNode] = Field(default_factory=list)
    requirements: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    decided_at: str = ""


def check_requirements(raw) -> TaskRequirements:
    """Validate a requirements dict. Fail-closed on unknown
    fields, wildcards, paths and command-shaped strings."""
    if raw is None:
        return TaskRequirements()
    if not isinstance(raw, dict):
        raise ValueError("Task requirements must be an object")
    unknown = set(raw) - set(TaskRequirements.model_fields)
    if unknown:
        raise ValueError(
            f"requirements carry unknown fields: {sorted(unknown)}")
    try:
        requirements = TaskRequirements.model_validate(raw)
    except Exception as error:
        raise ValueError(f"Invalid requirements: {error}") from error
    requirements.required_capabilities = check_capabilities(
        requirements.required_capabilities)
    for model_type in requirements.required_model_types:
        if model_type not in VALID_MODEL_TYPES:
            raise ValueError(
                f"model_type '{model_type}' unknown; expected one of "
                f"{sorted(VALID_MODEL_TYPES)}")
    for model_id in requirements.preferred_model_ids:
        check_model_id(model_id)
    if requirements.required_executor:
        executor = requirements.required_executor.strip().lower()
        import re as _re
        if not _re.match(r"^exec:[a-z0-9._-]+$",
                         executor):
            raise ValueError(
                "required_executor must be an explicit "
                "'exec:<kind>' reference (no wildcards)")
        requirements.required_executor = executor
    if requirements.locality not in VALID_LOCALITIES:
        raise ValueError(
            f"locality '{requirements.locality}' unknown; expected "
            f"one of {sorted(VALID_LOCALITIES)}")
    check_locality(requirements.locality)
    return requirements


def check_policy(raw) -> RoutingPolicy:
    if raw is None:
        return RoutingPolicy()
    if not isinstance(raw, dict):
        raise ValueError("Routing policy must be an object")
    try:
        return RoutingPolicy.model_validate(raw)
    except Exception as error:
        raise ValueError(f"Invalid policy: {error}") from error


def _node_models(node: dict) -> list[dict]:
    models = node.get("models", [])
    return [entry for entry in models if isinstance(entry, dict)]


def _eligible(node: dict, requirements: TaskRequirements,
              policy: RoutingPolicy) -> tuple[bool, list[str], int]:
    """Returns (eligible, reasons, preference_score)."""
    node_id = str(node.get("node_id", "?"))
    reasons: list[str] = []
    if not node.get("fresh", False):
        return False, [f"{node_id}: node not fresh"], 0
    if str(node.get("status", "")) not in ("online", "busy"):
        return False, [f"{node_id}: status "
                       f"'{node.get('status', '?')}' not live"], 0
    if policy.require_authenticated and not node.get(
            "authenticated", False):
        return False, [f"{node_id}: not authenticated"], 0
    advertised = {str(cap).strip().lower()
                  for cap in node.get("capabilities", [])}
    missing = [cap for cap in requirements.required_capabilities
               if cap.strip().lower() not in advertised]
    if missing:
        return False, [f"{node_id}: missing "
                       f"{', '.join(sorted(missing))}"], 0
    node_types = {str(entry.get("model_type", ""))
                  for entry in _node_models(node)}
    missing_types = [kind for kind in
                     requirements.required_model_types
                     if kind not in node_types]
    if missing_types:
        return False, [f"{node_id}: missing model type "
                       f"{', '.join(sorted(missing_types))}"], 0
    if requirements.required_executor:
        executors = {str(item).strip().lower()
                     for item in node.get("executors", [])}
        if requirements.required_executor not in executors:
            return False, [f"{node_id}: missing executor "
                           f"{requirements.required_executor}"], 0
    want_locality = requirements.locality
    if want_locality != "any" and str(
            node.get("locality_zone", "local_network")) != want_locality:
        return False, [f"{node_id}: locality "
                       f"'{node.get('locality_zone', '?')}' does not "
                       f"satisfy '{want_locality}'"], 0
    # Eligible: collect positive reasons + preference score.
    score = 0
    node_model_ids = {str(entry.get("model_id", ""))
                      for entry in _node_models(node)}
    for model_id in requirements.preferred_model_ids:
        if model_id in node_model_ids:
            score += 2
            reasons.append(f"{node_id}: preferred model "
                           f"{model_id} present")
    resources = node.get("resources", {})
    if not isinstance(resources, dict):
        resources = {}
    if requirements.min_memory_mb:
        memory = resources.get("memory_mb", 0)
        if isinstance(memory, int) and \
                memory >= requirements.min_memory_mb:
            score += 1
            reasons.append(f"{node_id}: memory {memory}MB meets "
                           f"minimum {requirements.min_memory_mb}MB")
        else:
            reasons.append(f"{node_id}: memory below minimum "
                           f"{requirements.min_memory_mb}MB")
    if requirements.needs_gpu:
        if resources.get("gpu_available") is True:
            score += 1
            reasons.append(f"{node_id}: GPU available")
        else:
            reasons.append(f"{node_id}: no GPU advertised")
    if policy.prefer_solar:
        if resources.get("energy_source") == "solar":
            score += 1
            reasons.append(f"{node_id}: solar energy source "
                           "(policy-compatible hint)")
        else:
            reasons.append(f"{node_id}: energy source "
                           f"'{resources.get('energy_source', '?')}' "
                           "(hint only, still eligible)")
    if policy.min_energy_level is not None:
        level = resources.get("energy_level")
        if isinstance(level, int) and \
                level >= policy.min_energy_level:
            score += 1
            reasons.append(f"{node_id}: energy level {level} meets "
                           f"minimum {policy.min_energy_level}")
        else:
            reasons.append(f"{node_id}: energy level below policy "
                           "minimum (hint only, still eligible)")
    for cap in requirements.required_capabilities:
        reasons.append(f"{node_id}: required capability "
                       f"{cap.strip().lower()} present")
    return True, reasons, score


def route_task(requirements: TaskRequirements, nodes: list[dict],
               policy: RoutingPolicy | None = None,
               now_str: str | None = None) -> RouteDecision:
    """Deterministic routing over candidate nodes. Same inputs
    always yield the same decision (score desc, node_id asc)."""
    active = policy or RoutingPolicy()
    eligible: list[tuple[int, str, list[str]]] = []
    rejected: list[RejectedNode] = []
    for node in nodes or []:
        if not isinstance(node, dict) or not node.get("node_id"):
            continue
        ok, reasons, score = _eligible(node, requirements, active)
        if ok:
            eligible.append((score, str(node["node_id"]), reasons))
        else:
            rejected.append(RejectedNode(node_id=str(
                node["node_id"]), reasons=reasons))
    eligible.sort(key=lambda entry: (-entry[0], entry[1]))
    rejected.sort(key=lambda entry: entry.node_id)
    stamp = now_str or datetime.now(timezone.utc).isoformat()
    if not eligible:
        return RouteDecision(
            selected_node_id=None,
            eligible_nodes=[],
            rejected=rejected,
            requirements=requirements.model_dump(mode="json"),
            policy=active.model_dump(mode="json"),
            reasons=["no eligible node; task waits for a capable, "
                     "fresh, authenticated node"],
            decided_at=stamp)
    score, winner, why = eligible[0]
    return RouteDecision(
        selected_node_id=winner,
        eligible_nodes=[node_id for _, node_id, _ in eligible],
        rejected=rejected,
        requirements=requirements.model_dump(mode="json"),
        policy=active.model_dump(mode="json"),
        reasons=[f"selected {winner} (preference score {score}; "
                 "tie-break by node_id)"] + why,
        decided_at=stamp)


def requirements_from_payload(payload) -> TaskRequirements:
    """Read routing requirements from a task payload's reserved
    'routing' key. Task creation merges this with the explicit
    field (explicit wins) and stores the result; the payload
    never keeps a shadow copy afterwards."""
    if not isinstance(payload, dict):
        return TaskRequirements()
    return check_requirements(payload.get("routing"))
