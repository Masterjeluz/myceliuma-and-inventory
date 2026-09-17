"""Persistent mission recovery (BIG #25).

Missions already survive restarts (SQLite ``missions`` table);
this module makes recovery SAFE and EXPLICIT:

1. ``assess(mission, bindings)`` reconstructs one mission's
   state and classifies it — pure function, no mutation:
   - ``safe_to_resume``: only pending read-only steps
     (readout/analysis) remain; no desktop/write/physical
     steps touched, no stale approvals.
   - ``needs_reapproval``: a gated step (desktop/write/
     physical/proposal/...) is pending or waiting — a human
     YES is required again, stale approvals never reused.
   - ``waiting_agent``: a dispatched action is out with an
     agent; recovery only observes, never re-dispatches.
   - ``terminal``: already ended; recovery only records memory.
2. ``scan()`` runs the assessment over all non-terminal
   missions and returns a report (used by the startup scan
   and by POST /api/v1/missions/recover).
3. Resuming is always explicit: the recover endpoint only
   drives ``safe_to_resume`` missions through the existing
   bounded ``run_loop`` when ``resume_safe=True`` is passed;
   the default is report-only.

Never: blind execution, stale approval reuse, re-dispatch of
agent actions, auto-start of physical machinery.
"""

from dataclasses import dataclass, field

SAFE_RESUME_KINDS = frozenset({"readout", "analysis"})
GATED_KINDS = frozenset(
    {"desktop", "write", "proposal", "fabricate", "slice",
     "physical_print", "camera_observe"})
NON_TERMINAL = frozenset(
    {"draft", "pending_approval", "approved", "running", "paused"})
TERMINAL = frozenset({"completed", "failed", "cancelled", "blocked"})


@dataclass(frozen=True)
class RecoveryVerdict:
    """Assessment of one mission. Data only."""

    mission_id: str = ""
    goal: str = ""
    status: str = ""
    verdict: str = "terminal"
    reason: str = ""
    remaining: int = 0
    gated_pending: list = field(default_factory=list)


def assess(mission, bindings: dict | None = None) -> RecoveryVerdict:
    """Reconstruct + revalidate one mission. Pure, no mutation."""
    bindings = bindings or {}
    mission_id = str(getattr(mission, "mission_id", "") or "")
    goal = str(getattr(mission, "goal", "") or "")[:200]
    status = str(getattr(mission, "status", "") or "")
    steps = list(getattr(mission, "steps", []) or [])
    if not mission_id:
        raise ValueError("assess needs a mission with an id")
    if status in TERMINAL:
        return RecoveryVerdict(mission_id, goal, status, "terminal",
                               "Mission already ended; observing only.",
                               0, [])
    if status in ("draft", "pending_approval"):
        return RecoveryVerdict(
            mission_id, goal, status, "needs_reapproval",
            "Plan was never approved; a human YES is still required.",
            len(steps), [])
    remaining = [step for step in steps
                 if str(getattr(step, "status", "")) not in (
                     "completed", "skipped")]
    if not remaining:
        return RecoveryVerdict(
            mission_id, goal, status, "terminal",
            "All steps finished; mission can complete on next tick.",
            0, [])
    for step in remaining:
        step_status = str(getattr(step, "status", "") or "")
        action_id = str(
            getattr(step, "desktop_action_id", "") or "")
        if step_status == "dispatched" and action_id:
            bound = bindings.get(action_id)
            expected = (mission_id,
                        str(getattr(step, "step_id", "") or ""))
            if bound is None or bound != expected:
                return RecoveryVerdict(
                    mission_id, goal, status, "needs_reapproval",
                    f"Dispatched action {action_id[:24]} has no valid "
                    "binding after restart; never re-dispatch blindly.",
                    len(remaining), ["desktop"])
            return RecoveryVerdict(
                mission_id, goal, status, "waiting_agent",
                f"Action {action_id[:24]} is out with an agent; "
                "recovery observes, the agent report unblocks it.",
                len(remaining), [])
        if step_status == "waiting_approval":
            return RecoveryVerdict(
                mission_id, goal, status, "needs_reapproval",
                "A desktop input waited for YES across the restart; "
                "stale approvals are never reused.",
                len(remaining), ["desktop"])
    gated = sorted({str(getattr(step, "kind", "") or "unknown")
                    for step in remaining
                    if str(getattr(step, "kind", "")) in GATED_KINDS})
    if gated:
        return RecoveryVerdict(
            mission_id, goal, status, "needs_reapproval",
            f"Gated steps remain ({', '.join(gated)}); each needs "
            "its own fresh human YES.",
            len(remaining), gated)
    unknown = [str(getattr(step, "kind", "") or "?")
               for step in remaining
               if str(getattr(step, "kind", "")) not in
               SAFE_RESUME_KINDS]
    if unknown:
        return RecoveryVerdict(
            mission_id, goal, status, "needs_reapproval",
            f"Unknown step kinds remain ({', '.join(sorted(set(unknown)))}); "
            "refusing to guess.",
            len(remaining), sorted(set(unknown)))
    current = int(getattr(mission, "current_step", 0) or 0)
    if not 0 <= current <= len(steps):
        return RecoveryVerdict(
            mission_id, goal, status, "needs_reapproval",
            "Current-step pointer is out of range after restart; "
            "a human reviews before anything runs.",
            len(remaining), [])
    return RecoveryVerdict(
        mission_id, goal, status, "safe_to_resume",
        f"{len(remaining)} read-only step(s) remain; safe to tick "
        "through the bounded loop.",
        len(remaining), [])


def scan(missions, bindings_fn=None) -> dict:
    """Assess every non-terminal mission. Report only, no mutation."""
    verdicts: list[RecoveryVerdict] = []
    for mission in missions or []:
        bindings: dict = {}
        if bindings_fn is not None:
            try:
                bindings = dict(
                    bindings_fn(str(getattr(
                        mission, "mission_id", ""))) or {})
            except Exception:
                bindings = {}
        verdicts.append(assess(mission, bindings))
    by_verdict: dict[str, int] = {}
    for verdict in verdicts:
        by_verdict[verdict.verdict] = by_verdict.get(
            verdict.verdict, 0) + 1
    return {"verdicts": [dict(
        mission_id=item.mission_id, goal=item.goal,
        status=item.status, verdict=item.verdict,
        reason=item.reason, remaining=item.remaining,
        gated_pending=list(item.gated_pending))
        for item in verdicts],
        "counts": by_verdict,
        "total": len(verdicts)}
