"""Deterministic step decisions (BIG #24).

Upgrades the BIG #21 loop ``plan -> step -> result -> next`` to
``plan -> execute -> observe -> evaluate -> decide`` where the
decision passes deterministic policy validation.

Decision states (closed): CONTINUE, RETRY, REPLAN,
WAITING_FOR_HUMAN, WAITING_FOR_AGENT, BLOCKED, FAILED,
COMPLETED, CANCELLED.

Rules (fail-closed, all tested):

- This module NEVER mutates mission state. It reads a step
  outcome and returns a decision; the caller (loop/executor)
  applies it through the existing validated transitions.
- The LLM never decides: provider advice is input evidence at
  most, never a state transition.
- A failed step never fails the whole mission by itself: retry
  while attempts remain, then REPLAN (human approves the new
  plan), then BLOCKED.
- RETRY is bounded (MAX_ATTEMPTS) with backoff seconds; when
  the budget is exhausted the decision becomes REPLAN for
  safe kinds and BLOCKED for gated kinds.
- Anything requiring human authority (approvals, writes,
  physical, publish, credentials) decides WAITING_FOR_HUMAN
  and names the exact gate — never a vague "approval required".
- Dispatched-but-unclaimed agent work decides WAITING_FOR_AGENT.
- COMPLETED/CANCELLED only mirror terminal states the
  executor already reached; this module never declares them
  from a non-terminal step.
"""

from dataclasses import dataclass, field

DECISIONS = (
    "CONTINUE",
    "RETRY",
    "REPLAN",
    "WAITING_FOR_HUMAN",
    "WAITING_FOR_AGENT",
    "BLOCKED",
    "FAILED",
    "COMPLETED",
    "CANCELLED",
)

#: Step kinds the loop may retry or continue on its own. Anything
#: gated (desktop input, writes, physical) always waits for a human.
SAFE_KINDS = frozenset({"readout", "analysis", "camera_observe"})

#: Kinds that always need an explicit human YES somewhere.
GATED_KINDS = frozenset(
    {"desktop", "write", "proposal", "fabricate", "slice",
     "physical_print"})

MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (5, 30, 120)


@dataclass(frozen=True)
class StepOutcome:
    """What the executor observed for one step. Plain data."""

    kind: str = "readout"
    step_status: str = "pending"
    ok: bool = False
    error: str = ""
    attempts: int = 0
    waiting_detail: str = ""
    mission_status: str = "running"


@dataclass(frozen=True)
class Decision:
    """The validated next move. Data only — never an approval."""

    state: str = "BLOCKED"
    reason: str = ""
    retry_in_seconds: int = 0
    needs: dict = field(default_factory=dict)


def decide(outcome: StepOutcome) -> Decision:
    """Evaluate one step outcome into a decision. Pure function."""
    if not isinstance(outcome, StepOutcome):
        raise ValueError("decide needs a StepOutcome")
    kind = str(outcome.kind or "")
    step_status = str(outcome.step_status or "")
    mission_status = str(outcome.mission_status or "")

    if mission_status == "cancelled":
        return Decision("CANCELLED", "Mission was cancelled; loop stops.")
    if mission_status == "completed":
        return Decision("COMPLETED", "Mission already completed.")
    if mission_status in ("failed", "blocked"):
        state = "FAILED" if mission_status == "failed" else "BLOCKED"
        return Decision(
            state, f"Mission is {mission_status}; a human reviews.")

    if step_status == "completed" and outcome.ok:
        return Decision(
            "CONTINUE",
            f"Step ({kind or 'unknown'}) succeeded; next step is safe "
            "to evaluate.")

    if step_status == "waiting_approval":
        return Decision(
            "WAITING_FOR_HUMAN",
            "Desktop input waits for an exact human YES. The loop "
            "never approves input.",
            needs={"gate": "desktop_action_decision",
                   "detail": outcome.waiting_detail[:200]})
    if step_status == "dispatched":
        return Decision(
            "WAITING_FOR_AGENT",
            "Action is dispatched to a desktop agent; the loop waits "
            "for its report, then continues.",
            needs={"gate": "agent_report",
                   "detail": outcome.waiting_detail[:200]})
    if step_status == "skipped":
        return Decision(
            "CONTINUE", "Step was skipped by policy; evaluate the next.")

    if step_status in ("failed", "blocked"):
        return _on_failure(kind, outcome)

    if step_status == "pending":
        if kind in GATED_KINDS:
            return Decision(
                "WAITING_FOR_HUMAN",
                f"A {kind} step needs its own explicit approval "
                "before it runs.",
                needs={"gate": kind,
                       "detail": outcome.waiting_detail[:200]})
        return Decision(
            "CONTINUE",
            f"Step ({kind or 'unknown'}) is pending and read-only; "
            "safe to tick.")

    return Decision(
        "BLOCKED",
        f"Unknown step status '{step_status[:40]}'; refusing to guess.")


def _on_failure(kind: str, outcome: StepOutcome) -> Decision:
    attempts = outcome.attempts
    try:
        attempts = int(attempts)
    except (TypeError, ValueError):
        attempts = MAX_ATTEMPTS
    if attempts < 0:
        attempts = 0
    if kind in SAFE_KINDS and attempts < MAX_ATTEMPTS:
        wait = RETRY_BACKOFF_SECONDS[
            min(attempts, len(RETRY_BACKOFF_SECONDS) - 1)]
        return Decision(
            "RETRY",
            f"Read-only step failed (attempt {attempts + 1}/"
            f"{MAX_ATTEMPTS}); retry with backoff, mission continues.",
            retry_in_seconds=wait)
    if kind in SAFE_KINDS:
        return Decision(
            "REPLAN",
            "Read-only step exhausted its retries; the mission needs "
            "a revised plan (new human approval), it does not fail "
            "silently.",
            needs={"gate": "plan_approval"})
    return Decision(
        "WAITING_FOR_HUMAN" if kind in GATED_KINDS else "BLOCKED",
        f"Step ({kind or 'unknown'}) {outcome.step_status}; "
        f"{outcome.error[:200] or 'no detail'}. A human decides "
        "whether to replan or stop.",
        needs={"gate": kind or "review",
               "detail": outcome.error[:200]})
