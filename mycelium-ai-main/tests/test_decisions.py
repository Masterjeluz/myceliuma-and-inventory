"""BIG #24 tests: deterministic step decisions.

decide() is pure: same outcome, same decision, never a
mutation, never an approval. Failed read-only steps retry
bounded, then replan; gated steps wait for a human.
"""

from coordinator.app.decisions import (
    DECISIONS,
    MAX_ATTEMPTS,
    StepOutcome,
    decide,
)


def test_states_closed():
    assert set(DECISIONS) == {
        "CONTINUE", "RETRY", "REPLAN", "WAITING_FOR_HUMAN",
        "WAITING_FOR_AGENT", "BLOCKED", "FAILED", "COMPLETED",
        "CANCELLED"}


def test_success_continues():
    decision = decide(StepOutcome(
        kind="readout", step_status="completed", ok=True))
    assert decision.state == "CONTINUE"


def test_pending_readonly_continues():
    decision = decide(StepOutcome(
        kind="analysis", step_status="pending"))
    assert decision.state == "CONTINUE"


def test_pending_gated_waits_for_human():
    for kind in ("desktop", "write", "physical_print", "proposal"):
        decision = decide(StepOutcome(
            kind=kind, step_status="pending"))
        assert decision.state == "WAITING_FOR_HUMAN", kind
        assert decision.needs.get("gate") == kind


def test_waiting_approval_names_gate():
    decision = decide(StepOutcome(
        kind="desktop", step_status="waiting_approval",
        waiting_detail="dact-123"))
    assert decision.state == "WAITING_FOR_HUMAN"
    assert "dact-123" in decision.reason or \
        decision.needs.get("detail") == "dact-123"


def test_dispatched_waits_for_agent():
    decision = decide(StepOutcome(
        kind="desktop", step_status="dispatched",
        waiting_detail="dact-9"))
    assert decision.state == "WAITING_FOR_AGENT"


def test_failed_readonly_retries_bounded():
    first = decide(StepOutcome(
        kind="readout", step_status="failed", error="timeout",
        attempts=0))
    assert first.state == "RETRY"
    assert first.retry_in_seconds > 0
    last = decide(StepOutcome(
        kind="readout", step_status="failed", error="timeout",
        attempts=MAX_ATTEMPTS))
    assert last.state == "REPLAN"
    assert last.needs.get("gate") == "plan_approval"


def test_failed_gated_never_retries():
    decision = decide(StepOutcome(
        kind="write", step_status="failed", error="no YES",
        attempts=0))
    assert decision.state == "WAITING_FOR_HUMAN"


def test_failure_never_fails_mission_directly():
    decision = decide(StepOutcome(
        kind="analysis", step_status="failed", error="boom",
        attempts=0))
    assert decision.state in ("RETRY", "REPLAN")
    assert decision.state not in ("FAILED", "COMPLETED")


def test_terminal_mirrors_only():
    assert decide(StepOutcome(
        mission_status="cancelled").__class__(
            kind="readout", step_status="completed", ok=True,
            mission_status="cancelled")).state == "CANCELLED"
    assert decide(StepOutcome(
        kind="readout", step_status="pending",
        mission_status="completed")).state == "COMPLETED"
    assert decide(StepOutcome(
        kind="readout", step_status="pending",
        mission_status="failed")).state == "FAILED"
    assert decide(StepOutcome(
        kind="readout", step_status="pending",
        mission_status="blocked")).state == "BLOCKED"


def test_unknown_status_blocks():
    decision = decide(StepOutcome(
        kind="readout", step_status="teleporting"))
    assert decision.state == "BLOCKED"


def test_pure_no_mutation():
    outcome = StepOutcome(
        kind="readout", step_status="failed", attempts=1)
    first = decide(outcome)
    second = decide(outcome)
    assert first == second
    assert outcome.attempts == 1
