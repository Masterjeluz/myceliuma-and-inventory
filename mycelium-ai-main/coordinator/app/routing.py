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
7. telemetry freshness (when required) - BIG #39
8. required hardware present (when specified) - BIG #39
9. required compute capabilities present (when specified) - BIG #39

Every rejection carries a verdict (BIG #41, Routing 2.0):

- "waiting": transient — the node could become eligible
  (not fresh, stale/offline status, not authenticated,
  missing/stale/invalid telemetry, health below minimum).
- "blocked": administrative — a disabled node never routes
  until an operator re-enables it.
- "unavailable": structural for this task — missing
  capabilities, models, executor, locality, hardware or
  compute. Nothing about the node is wrong; the task simply
  does not fit.

Ordering among eligible nodes (preferences, never requirements):

- preferred model id present (+2 each, capped)
- energy policy compatible (+1): solar source when the policy
  prefers it, energy_level meeting the policy minimum
- resource minimums met (+1): min_memory_mb, needs_gpu
- telemetry freshness bonus (+1): recent telemetry (< 60s)
- hardware availability bonus (+1): required hardware connected
- idle node bonus (+1): no running tasks when the policy
  prefers idle nodes (BIG #41)
- deterministic tie-break: lowest node_id wins

Energy, resources and workload never disqualify; they only
order. A node that fails a required capability is never
selected regardless of preferences. Every decision carries
inspectable reasons; credentials never appear in any output.
"""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .nodes import (
    VALID_LOCALITIES,
    VALID_MODEL_TYPES,
    check_capabilities,
    check_locality,
    check_model_id,
    VALID_HARDWARE_KINDS,
    VALID_COMPUTE_CAPABILITIES,
)

MAX_REQUIREMENTS = 30
MAX_MODEL_IDS = 10
MAX_HARDWARE_REQUIREMENTS = 10
MAX_COMPUTE_REQUIREMENTS = 10


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
    # BIG #39: Hardware Reality Layer requirements
    required_hardware: list[str] = Field(default_factory=list,
                                          max_length=MAX_HARDWARE_REQUIREMENTS)
    required_compute: list[str] = Field(default_factory=list,
                                         max_length=MAX_COMPUTE_REQUIREMENTS)
    max_telemetry_age_seconds: int = Field(default=0, ge=0, le=3600)
    min_health: str = Field(default="", max_length=20)  # ONLINE, DEGRADED, etc.


class RoutingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefer_solar: bool = False
    min_energy_level: int | None = Field(default=None, ge=0, le=100)
    require_authenticated: bool = True
    # BIG #39: Hardware Reality Layer preferences
    prefer_fresh_telemetry: bool = False
    prefer_connected_hardware: bool = False
    prefer_compute_capabilities: bool = False
    # BIG #41: Routing 2.0 — prefer nodes with no running
    # tasks. Ordering only, never eligibility.
    prefer_idle: bool = False


#: Rejection verdicts (BIG #41). "waiting" is transient,
#: "blocked" is administrative, "unavailable" means the task
#: does not fit this node.
NodeVerdict = Literal["waiting", "blocked", "unavailable"]


class RejectedNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = ""
    reasons: list[str] = Field(default_factory=list)
    verdict: NodeVerdict = "unavailable"


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
    # BIG #39: Hardware Reality Layer - validate hardware and compute requirements
    for hw in requirements.required_hardware:
        hw_clean = str(hw).strip().lower()
        if hw_clean not in VALID_HARDWARE_KINDS:
            raise ValueError(
                f"required_hardware '{hw}' unknown; expected one of "
                f"{sorted(VALID_HARDWARE_KINDS)}")
    for comp in requirements.required_compute:
        comp_clean = str(comp).strip().lower()
        if comp_clean not in VALID_COMPUTE_CAPABILITIES:
            raise ValueError(
                f"required_compute '{comp}' unknown; expected one of "
                f"{sorted(VALID_COMPUTE_CAPABILITIES)}")
    if requirements.min_health:
        health_clean = str(requirements.min_health).strip().upper()
        if health_clean not in ("ONLINE", "DEGRADED", "STALE", "OFFLINE", "UNKNOWN"):
            raise ValueError(
                f"min_health '{requirements.min_health}' unknown; expected one of "
                "ONLINE, DEGRADED, STALE, OFFLINE, UNKNOWN")
        requirements.min_health = health_clean
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
              policy: RoutingPolicy
              ) -> tuple[bool, list[str], int, str]:
    """Returns (eligible, reasons, preference_score, verdict).

    Verdict is "" when eligible, else one of "waiting" /
    "blocked" / "unavailable" (BIG #41 Routing 2.0)."""
    node_id = str(node.get("node_id", "?"))
    reasons: list[str] = []
    if not node.get("fresh", False):
        return False, [f"{node_id}: node not fresh"], 0, "waiting"
    status = str(node.get("status", ""))
    if status == "disabled":
        return False, [f"{node_id}: status 'disabled' not live "
                       f"(operator re-enable required)"], 0, "blocked"
    if status not in ("online", "busy"):
        return False, [f"{node_id}: status "
                       f"'{node.get('status', '?')}' not live"], 0, \
            "waiting"
    if policy.require_authenticated and not node.get(
            "authenticated", False):
        return False, [f"{node_id}: not authenticated"], 0, \
            "waiting"
    advertised = {str(cap).strip().lower()
                  for cap in node.get("capabilities", [])}
    missing = [cap for cap in requirements.required_capabilities
               if cap.strip().lower() not in advertised]
    if missing:
        return False, [f"{node_id}: missing "
                       f"{', '.join(sorted(missing))}"], 0, \
            "unavailable"
    node_types = {str(entry.get("model_type", ""))
                  for entry in _node_models(node)}
    missing_types = [kind for kind in
                     requirements.required_model_types
                     if kind not in node_types]
    if missing_types:
        return False, [f"{node_id}: missing model type "
                       f"{', '.join(sorted(missing_types))}"], 0, \
            "unavailable"
    if requirements.required_executor:
        executors = {str(item).strip().lower()
                     for item in node.get("executors", [])}
        if requirements.required_executor not in executors:
            return False, [f"{node_id}: missing executor "
                           f"{requirements.required_executor}"], 0, \
                "unavailable"
    want_locality = requirements.locality
    if want_locality != "any" and str(
            node.get("locality_zone", "local_network")) != want_locality:
        return False, [f"{node_id}: locality "
                       f"'{node.get('locality_zone', '?')}' does not "
                       f"satisfy '{want_locality}'"], 0, "unavailable"
    # BIG #39: Hardware Reality Layer - hard gates for hardware and compute
    if requirements.required_hardware:
        node_hardware = node.get("hardware", [])
        if not isinstance(node_hardware, list):
            node_hardware = []
        connected_hardware = {str(item.get("kind", "")).strip().lower()
                              for item in node_hardware
                              if isinstance(item, dict)
                              and str(item.get("status", "")).lower() == "connected"}
        missing_hw = [hw for hw in requirements.required_hardware
                      if hw.strip().lower() not in connected_hardware]
        if missing_hw:
            return False, [f"{node_id}: missing connected hardware "
                           f"{', '.join(sorted(missing_hw))}"], 0, \
                "unavailable"
    if requirements.required_compute:
        node_compute = node.get("compute_capabilities", [])
        if not isinstance(node_compute, list):
            node_compute = []
        available_compute = {str(item.get("capability", "")).strip().lower()
                             for item in node_compute
                             if isinstance(item, dict)
                             and str(item.get("status", "")).lower() == "available"}
        missing_comp = [comp for comp in requirements.required_compute
                        if comp.strip().lower() not in available_compute]
        if missing_comp:
            return False, [f"{node_id}: missing available compute "
                           f"{', '.join(sorted(missing_comp))}"], 0, \
                "unavailable"
    # BIG #39: Telemetry freshness hard gate
    if requirements.max_telemetry_age_seconds > 0:
        telemetry_ts = node.get("telemetry_timestamp", "")
        if not telemetry_ts:
            return False, [f"{node_id}: no telemetry timestamp"], 0, \
                "waiting"
        try:
            from datetime import datetime, timezone
            ts = datetime.fromisoformat(telemetry_ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = int((datetime.now(timezone.utc) - ts).total_seconds())
            if age > requirements.max_telemetry_age_seconds:
                return False, [f"{node_id}: telemetry too old ({age}s > "
                                f"{requirements.max_telemetry_age_seconds}s)"], 0, \
                    "waiting"
        except (ValueError, TypeError):
            return False, [f"{node_id}: invalid telemetry timestamp"], 0, \
                "waiting"
    # BIG #39: Minimum health requirement
    if requirements.min_health:
        node_health = node.get("health_status", "UNKNOWN")
        health_order = {"ONLINE": 4, "DEGRADED": 3, "STALE": 2, "OFFLINE": 1, "UNKNOWN": 0}
        if health_order.get(node_health, 0) < health_order.get(requirements.min_health, 0):
            return False, [f"{node_id}: health {node_health} below minimum "
                           f"{requirements.min_health}"], 0, "waiting"
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
    # BIG #39: Telemetry freshness preference
    if policy.prefer_fresh_telemetry:
        telemetry_ts = node.get("telemetry_timestamp", "")
        if telemetry_ts:
            try:
                from datetime import datetime, timezone
                ts = datetime.fromisoformat(telemetry_ts)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age = int((datetime.now(timezone.utc) - ts).total_seconds())
                if age < 60:
                    score += 1
                    reasons.append(f"{node_id}: fresh telemetry ({age}s)")
                else:
                    reasons.append(f"{node_id}: telemetry age {age}s (hint only)")
            except (ValueError, TypeError):
                reasons.append(f"{node_id}: invalid telemetry timestamp (hint only)")
        else:
            reasons.append(f"{node_id}: no telemetry (hint only)")
    # BIG #39: Connected hardware preference
    if policy.prefer_connected_hardware:
        node_hardware = node.get("hardware", [])
        if isinstance(node_hardware, list):
            connected_count = sum(1 for item in node_hardware
                                  if isinstance(item, dict)
                                  and str(item.get("status", "")).lower() == "connected")
            if connected_count > 0:
                score += 1
                reasons.append(f"{node_id}: {connected_count} connected hardware item(s)")
            else:
                reasons.append(f"{node_id}: no connected hardware (hint only)")
    # BIG #39: Compute capabilities preference
    if policy.prefer_compute_capabilities:
        node_compute = node.get("compute_capabilities", [])
        if isinstance(node_compute, list):
            available_count = sum(1 for item in node_compute
                                  if isinstance(item, dict)
                                  and str(item.get("status", "")).lower() == "available")
            if available_count > 0:
                score += 1
                reasons.append(f"{node_id}: {available_count} available compute capability(s)")
            else:
                reasons.append(f"{node_id}: no available compute (hint only)")
    for cap in requirements.required_capabilities:
        reasons.append(f"{node_id}: required capability "
                       f"{cap.strip().lower()} present")
    # BIG #39: Required hardware and compute as positive reasons
    for hw in requirements.required_hardware:
        reasons.append(f"{node_id}: required hardware {hw} connected")
    for comp in requirements.required_compute:
        reasons.append(f"{node_id}: required compute {comp} available")
    # BIG #41: Routing 2.0 — current workload as ordering hint.
    # running_tasks comes from the coordinator projection (tasks
    # assigned right now); unknown stays unclaimed (no bonus).
    if policy.prefer_idle:
        running = node.get("running_tasks")
        if isinstance(running, bool) or not isinstance(
                running, int) or running < 0:
            reasons.append(f"{node_id}: workload unknown "
                           f"(hint only, still eligible)")
        elif running == 0:
            score += 1
            reasons.append(f"{node_id}: idle, no running tasks "
                           f"(+1)")
        else:
            reasons.append(f"{node_id}: {running} running "
                           f"task(s) (hint only, still eligible)")
    return True, reasons, score, ""


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
        ok, reasons, score, verdict = _eligible(
            node, requirements, active)
        if ok:
            eligible.append((score, str(node["node_id"]), reasons))
        else:
            rejected.append(RejectedNode(
                node_id=str(node["node_id"]), reasons=reasons,
                verdict=verdict or "unavailable"))
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


def explain_decision(decision: RouteDecision,
                     nodes: list[dict] | None = None) -> dict:
    """Transparent routing explanation (BIG #41 Routing 2.0).

    Groups every candidate into WHY ELIGIBLE / WHY WAITING /
    WHY BLOCKED / WHY NOT AVAILABLE with the router's own
    reasons. Pure function over a decision (+ optional node
    rows for workload context); deterministic, no ranking
    beyond what route_task already decided.
    """
    groups: dict[str, list[dict]] = {
        "eligible": [], "waiting": [], "blocked": [],
        "unavailable": []}
    for entry in decision.rejected or []:
        verdict = str(getattr(entry, "verdict", "unavailable"))
        if verdict not in groups:
            verdict = "unavailable"
        groups[verdict].append({
            "node_id": entry.node_id,
            "why": list(entry.reasons)[:6]})
    workload: dict[str, int] = {}
    for node in nodes or []:
        if not isinstance(node, dict) or not node.get("node_id"):
            continue
        running = node.get("running_tasks")
        if isinstance(running, int) and not isinstance(
                running, bool) and running >= 0:
            workload[str(node["node_id"])] = running
    for node_id in decision.eligible_nodes or []:
        why = [f"{node_id} meets every hard requirement"]
        if node_id == decision.selected_node_id:
            why = list(decision.reasons)[:8]
        if node_id in workload:
            why = why + [f"{workload[node_id]} running task(s)"]
        groups["eligible"].append({"node_id": node_id, "why": why})
    lines = {
        "eligible": [f"{entry['node_id']}: "
                     f"{entry['why'][0] if entry['why'] else '?'}"
                     for entry in groups["eligible"]][:10],
        "waiting": [f"{entry['node_id']}: "
                    f"{entry['why'][0] if entry['why'] else '?'}"
                    for entry in groups["waiting"]][:10],
        "blocked": [f"{entry['node_id']}: "
                    f"{entry['why'][0] if entry['why'] else '?'}"
                    for entry in groups["blocked"]][:10],
        "unavailable": [f"{entry['node_id']}: "
                        f"{entry['why'][0] if entry['why'] else '?'}"
                        for entry in groups["unavailable"]][:10],
    }
    summary = ("no eligible node; task waits for a capable, "
               "fresh, authenticated node"
               if not groups["eligible"] else
               f"{decision.selected_node_id} selected from "
               f"{len(groups['eligible'])} eligible; "
               f"{len(groups['waiting'])} waiting, "
               f"{len(groups['blocked'])} blocked, "
               f"{len(groups['unavailable'])} unavailable")
    return {"eligible": groups["eligible"],
            "waiting": groups["waiting"],
            "blocked": groups["blocked"],
            "unavailable": groups["unavailable"],
            "lines": lines, "summary": summary}


def requirements_from_payload(payload) -> TaskRequirements:
    """Read routing requirements from a task payload's reserved
    'routing' key. Task creation merges this with the explicit
    field (explicit wins) and stores the result; the payload
    never keeps a shadow copy afterwards."""
    if not isinstance(payload, dict):
        return TaskRequirements()
    return check_requirements(payload.get("routing"))
