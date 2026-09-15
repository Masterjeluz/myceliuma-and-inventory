"""Agent-loop lifecycle tests (Fase I/Q).

Propose -> approve -> dispatch -> result, plus rejection,
cancellation, binding checks and terminal-state finality. Pure
transitions; no database, no desktop, no clock.
"""

import pytest

from coordinator.app.agent_loop import (
    cancel,
    decide,
    describe,
    dispatch,
    propose,
    record_result,
)
from coordinator.app.computer_actions import new_action


def click_action(action_id="dact-1"):
    return new_action(action_id, "click", {"x": 100, "y": 200})


def test_input_action_waits_for_approval():
    record = propose(click_action())
    assert record.status == "pending_approval"


def test_readonly_action_preapproved_by_policy():
    from coordinator.app.computer_actions import new_action as make
    record = propose(make("dact-s", "screenshot", {}))
    assert record.status == "approved"
    assert record.decided_by == "policy:read-only-local"


def test_exact_yes_approves_anything_else_rejects():
    assert decide(propose(click_action("dact-a1")), "dact-a1", "YES").status == "approved"
    assert decide(propose(click_action("dact-a2")), "dact-a2", "NO").status == "rejected"
    denied = decide(propose(click_action("dact-a3")), "dact-a3", "ja graag")
    assert denied.status == "rejected"
    assert "default deny" in denied.note


def test_decision_binds_to_action_id():
    with pytest.raises(ValueError):
        decide(propose(click_action("dact-a1")), "other", "YES")


def test_decision_only_from_pending():
    record = decide(propose(click_action("dact-a1")), "dact-a1", "YES")
    with pytest.raises(ValueError):
        decide(record, "dact-a1", "YES")


def test_cancel_from_waiting_states_always():
    assert cancel(propose(click_action("dact-a1")), "dact-a1").status == "cancelled"
    approved = decide(propose(click_action("dact-a2")), "dact-a2", "YES")
    assert cancel(approved, "dact-a2").status == "cancelled"


def test_cancel_from_terminal_refused():
    record = decide(propose(click_action("dact-a1")), "dact-a1", "NO")
    with pytest.raises(ValueError):
        cancel(record, "dact-a1")


def test_dispatch_exactly_once_from_approved():
    approved = decide(propose(click_action("dact-a1")), "dact-a1", "YES")
    assert dispatch(approved, "dact-a1").status == "dispatched"
    with pytest.raises(ValueError):
        dispatch(propose(click_action("dact-a2")), "dact-a2")


def test_full_success_cycle():
    record = dispatch(decide(propose(click_action("dact-a1")), "dact-a1", "YES"),
                      "dact-a1")
    closed = record_result(record, "dact-a1", "completed")
    assert closed.status == "completed"
    assert closed.result is not None
    assert closed.result.status == "completed"


def test_failed_action_keeps_error():
    record = dispatch(decide(propose(click_action("dact-a1")), "dact-a1", "YES"),
                      "dact-a1")
    closed = record_result(record, "dact-a1", "failed",
                           error="knop niet gevonden",
                           observation_reference="obs-9")
    assert closed.status == "failed"
    assert closed.result.error == "knop niet gevonden"
    assert closed.result.observation_reference == "obs-9"


def test_result_only_from_dispatched():
    with pytest.raises(ValueError):
        record_result(propose(click_action("dact-a1")), "dact-a1", "completed")
    with pytest.raises(ValueError):
        record_result(decide(propose(click_action("dact-a2")), "dact-a2", "YES"),
                      "dact-a2", "completed")


def test_terminal_states_never_transition():
    record = dispatch(decide(propose(click_action("dact-a1")), "dact-a1", "YES"),
                      "dact-a1")
    closed = record_result(record, "dact-a1", "completed")
    with pytest.raises(ValueError):
        cancel(closed, "dact-a1")
    with pytest.raises(ValueError):
        dispatch(closed, "dact-a1")
    with pytest.raises(ValueError):
        decide(closed, "dact-a1", "YES")


def test_describe_for_operator_ui():
    record = propose(click_action("dact-a1"))
    summary = describe(record)
    assert summary["action_id"] == "dact-a1"
    assert summary["action_type"] == "click"
    assert summary["status"] == "pending_approval"
    assert summary["result"] is None
