"""Autonomous mission loop (BIG #21).

One safe continuous runner over the existing architecture:
chat intent → mission → tick → observe → evaluate →
continue → verify → complete. This module adds NO new
execution power: it calls the existing executor.tick(),
reads the existing gates, and STOPS at every one of them.

The loop NEVER:
- approves plans, actions, writes or prints (exact YES
  stays human, through the existing endpoints),
- invents steps outside the approved plan,
- retries failed/blocked steps blindly,
- executes physical actions (HARDWARE_REQUIRED + own
  approval live in the existing runners),
- promotes results to FACT (verification outcomes come
  from the existing verification flow).

What it DOES:
- drive approved work forward until the next gate,
- report exactly where it stopped and what unblocks it
  (actionable stop reasons with ids),
- store one episodic memory when the mission reaches a
  terminal state (observed truth, never fact),
- stay bounded (max rounds per call; concurrent runs
  lose the existing conditional-update race).

Continuation ("herplan → vervolg") happens across calls:
an external actor (human YES, desktop agent claim/act/
report, new observation) changes state, the next run
ticks further within the approved plan. Replanning
beyond approved steps needs a new approval, never the
loop.
"""

import time

MAX_LOOP_ROUNDS = 10

TERMINAL_STATES = ("completed", "failed", "cancelled",
                   "blocked")


class MissionLoopRefusedError(ValueError):
    """Loop validation refused; nothing was driven."""


def _stop(reason: str, detail: str = "", action: dict | None = None,
          rounds: int = 0, mission_id: str = "",
          status: str = "") -> dict:
    return {"mission_id": mission_id, "status": status,
            "outcome": "stopped", "stop_reason": reason,
            "detail": str(detail or "")[:500],
            "action": action or {}, "rounds": rounds}


async def run_loop(mission_id: str, *, max_rounds: int = 10,
                   actor: str = "mission-loop") -> dict:
    """Drive one mission until a gate, terminal state or the
    round budget. Returns a run report, never an approval."""
    from .mission_executor import ExecutorError
    from .missions import current_step_of, load_mission
    if not isinstance(mission_id, str) or not mission_id.strip():
        raise MissionLoopRefusedError("mission_id must be text")
    try:
        budget = max(1, min(int(max_rounds or 10),
                            MAX_LOOP_ROUNDS))
    except (TypeError, ValueError):
        raise MissionLoopRefusedError(
            "max_rounds must be an integer")
    mission = load_mission(mission_id.strip())
    if mission is None:
        raise MissionLoopRefusedError("mission not found")
    if mission.status == "pending_approval":
        return _stop("needs_plan_approval",
                      "The plan needs an exact YES before "
                      "anything runs. Approval authorizes "
                      "steps only, never execution.",
                      {"approve": f"/api/v1/missions/"
                                  f"{mission.mission_id}/approve"},
                      rounds=0, mission_id=mission.mission_id,
                      status=mission.status)
    if mission.status in TERMINAL_STATES:
        remembered = _remember_if_new(mission)
        return {"mission_id": mission.mission_id,
                "status": mission.status, "outcome": "stopped",
                "stop_reason": "already_terminal",
                "detail": "Mission already ended; loop only "
                          "observes terminal states.",
                "action": {}, "rounds": 0,
                "memory_id": remembered}
    if mission.status == "paused":
        return _stop("paused",
                      "Mission is paused. Resume explicitly "
                      "before the loop continues.",
                      {"resume": f"/api/v1/missions/"
                                 f"{mission.mission_id}/resume"},
                      rounds=0, mission_id=mission.mission_id,
                      status=mission.status)
    from .main import _executor
    rounds = 0
    last_tick: dict = {}
    while rounds < budget:
        rounds += 1
        try:
            last_tick = await _executor().tick(mission_id)
        except ExecutorError as error:
            return _stop("conflict_or_error", str(error),
                         rounds=rounds,
                         mission_id=mission.mission_id,
                         status=_safe_status(mission_id))
        outcome = str(last_tick.get("outcome", ""))
        status = str(last_tick.get("status", ""))
        if outcome == "completed" or status == "completed":
            remembered = _remember_if_new(
                _reload(mission_id, mission))
            return {"mission_id": mission_id,
                    "status": "completed",
                    "outcome": "completed", "rounds": rounds,
                    "tick": last_tick, "memory_id": remembered}
        if status in ("failed", "blocked", "cancelled",
                      "paused"):
            mission_now = _reload(mission_id, mission)
            remembered = _remember_if_new(mission_now)
            return {"mission_id": mission_id, "status": status,
                    "outcome": "stopped",
                    "stop_reason": f"mission_{status}",
                    "detail": "Terminal state reached; a human "
                              "reviews before anything else.",
                    "action": {}, "rounds": rounds,
                    "tick": last_tick, "memory_id": remembered}
        # Waiting: name the gate, do not push through it.
        return _describe_wait(mission_id, rounds, last_tick)
    return _stop("round_budget",
                 f"Used all {budget} rounds without reaching a "
                 "terminal state; re-run explicitly.",
                 rounds=budget, mission_id=mission_id,
                 status=_safe_status(mission_id))


def _safe_status(mission_id: str) -> str:
    from .missions import load_mission
    try:
        mission = load_mission(mission_id)
        return mission.status if mission else "unknown"
    except ValueError:
        return "unknown"


def _reload(mission_id: str, fallback):
    from .missions import load_mission
    try:
        mission = load_mission(mission_id)
        return mission if mission is not None else fallback
    except ValueError:
        return fallback


def _describe_wait(mission_id: str, rounds: int,
                   tick: dict) -> dict:
    """Name the exact gate a waiting tick stopped at, with
    the ids a human or agent needs to unblock it."""
    from .missions import current_step_of, load_mission
    try:
        mission = load_mission(mission_id)
    except ValueError:
        return _stop("conflict_or_error",
                      "Mission vanished mid-run.", rounds=rounds,
                      mission_id=mission_id)
    if mission is None:
        return _stop("conflict_or_error",
                      "Mission vanished mid-run.", rounds=rounds,
                      mission_id=mission_id)
    step = current_step_of(mission)
    if step is None:
        return _stop("waiting",
                      "No current step; re-run after state "
                      "changes.", rounds=rounds,
                      mission_id=mission_id,
                      status=mission.status)
    kind = str(step.kind)
    if step.status == "waiting_approval":
        return _stop(
            "needs_desktop_approval",
            f"Desktop action {step.desktop_action_id or '?'} "
            f"({step.action_type or step.description}) waits "
            f"for an exact YES. The loop never approves input.",
            {"action_id": step.desktop_action_id or "",
             "decide": "/api/v1/desktop/actions/"
                       f"{step.desktop_action_id or ''}/decision"
                       if step.desktop_action_id else ""},
            rounds=rounds, mission_id=mission_id,
            status=mission.status)
    if step.status == "dispatched":
        return _stop(
            "waiting_agent",
            f"Action {step.desktop_action_id or '?'} is "
            f"dispatched to an agent. The loop waits; the "
            f"desktop agent claims, acts and reports, then a "
            f"new run continues.",
            {"action_id": step.desktop_action_id or ""},
            rounds=rounds, mission_id=mission_id,
            status=mission.status)
    if kind == "proposal":
        return _stop(
            "needs_proposal_approval",
            "A proposal step finished as data. It needs the "
            "separate /approvals flow; proposals never "
            "auto-execute.",
            {"approvals": "/api/v1/approvals"},
            rounds=rounds, mission_id=mission_id,
            status=mission.status)
    if kind in ("write", "fabricate", "slice",
                "physical_print"):
        return _stop(
            "needs_write_or_physical_approval",
            f"A {kind} step needs its own exact YES plus "
            f"fingerprint revalidation (physical_print: plus "
            f"its own physical approval — a mission YES never "
            f"starts a machine).",
            {"writes": "/api/v1/writes"},
            rounds=rounds, mission_id=mission_id,
            status=mission.status)
    return _stop("waiting",
                 f"Step '{step.description[:80]}' ({kind}) is "
                 f"{step.status}. Re-run after the world "
                 f"changes.",
                 rounds=rounds, mission_id=mission_id,
                 status=mission.status,
                 action={"tick": f"/api/v1/missions/"
                                 f"{mission_id}/tick"})


def _remember_if_new(mission) -> str:
    """Store one episodic memory for a terminal mission.
    Observed truth, sensor-observed provenance, mission +
    observation links. Never a fact tier, never verified.
    Skips when a memory already references the mission."""
    from .memory import list_memories, new_memory, save_memory
    mission_id = mission.mission_id
    try:
        existing = list_memories(limit=200)
    except ValueError:
        existing = []
    for entry in existing:
        if mission_id in (entry.entity_refs or []):
            return entry.memory_id
    observations = []
    for step in (mission.steps or []):
        ref = getattr(step, "observation_reference", "") or ""
        if ref:
            observations.append(
                f"{step.kind}:{step.status}:{ref}")
    content = (f"Mission '{mission.goal[:200]}' ended as "
               f"{mission.status}. Steps: "
               + "; ".join(
                   f"{step.kind}={step.status}"
                   for step in (mission.steps or []))[:1500]
               + (". Observations: " + "; ".join(
                   observations[:10]) if observations else ""))
    from .inventory_read import Provenance
    entry = new_memory(
        "episodic", f"Mission ended: {mission.goal[:120]}",
        truth="observed", content=content,
        source=f"mission:{mission_id}",
        provenance=Provenance(
            source_type="sensor-observed",
            creator_id="mission-loop", human_verified=False,
            notes="loop terminal-state record; observed "
                  "system outcome, never a fact"),
        project_ref="",
        entity_refs=[mission_id],
        event_refs=[])
    save_memory(entry)
    return entry.memory_id
