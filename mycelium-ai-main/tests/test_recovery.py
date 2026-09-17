"""BIG #25 tests: persistent mission recovery.

assess() reconstructs state without mutating; scan() reports
counts. Stale approvals are never reused, agent actions never
re-dispatched, gated steps always need a fresh human YES.
"""

from coordinator.app.missions import new_mission
from coordinator.app.recovery import assess, scan


def _mission(status, kinds, step_statuses=None):
    steps = []
    for kind in kinds:
        data = {"kind": kind, "description": f"step {kind}",
                "parameters": _params(kind)}
        if kind == "desktop":
            data.update({
                "action_type": "screenshot",
                "requires_approval": False,
                "required_capabilities": ["desktop.screen.read"]})
        steps.append(data)
    mission = new_mission(
        "mission_test1", "conv-1", "test goal", steps,
        status="pending_approval")
    statuses = step_statuses or ["pending"] * len(kinds)
    steps_done = []
    for step, wanted in zip(mission.steps, statuses):
        steps_done.append(step.model_copy(update={
            "status": wanted,
            "desktop_action_id": ("dact-1" if step.kind == "desktop"
                                  and wanted in ("dispatched",
                                                 "waiting_approval")
                                  else "")}))
    mission = mission.model_copy(update={
        "status": status, "steps": steps_done})
    return mission


def _params(kind):
    if kind == "desktop":
        return {}
    if kind == "write":
        return {"proposal_id": "prop-123"}
    if kind == "camera_observe":
        return {"device_id": "cam-1"}
    if kind == "fabricate":
        return {"description": "test box"}
    if kind == "slice":
        return {"artifact_ref": "a", "profile": "p",
                "printer_id": "printer-1"}
    if kind == "physical_print":
        return {"proposal_id": "print-1"}
    if kind == "readout":
        return {"source": "project"}
    return {}


def test_terminal_observed_only():
    mission = _mission("completed", ["readout"], ["completed"])
    verdict = assess(mission)
    assert verdict.verdict == "terminal"


def test_unapproved_needs_reapproval():
    mission = _mission("pending_approval", ["readout"])
    verdict = assess(mission)
    assert verdict.verdict == "needs_reapproval"


def test_readonly_safe_to_resume():
    mission = _mission("approved", ["readout", "analysis"])
    verdict = assess(mission)
    assert verdict.verdict == "safe_to_resume"
    assert verdict.remaining == 2


def test_desktop_pending_needs_fresh_yes():
    mission = _mission(
        "approved", ["readout", "desktop"],
        ["completed", "pending"])
    # desktop pending without action id: still gated
    mission = mission.model_copy(update={
        "steps": [mission.steps[0],
                  mission.steps[1].model_copy(update={
                      "action_type": "screenshot"})]})
    verdict = assess(mission)
    assert verdict.verdict == "needs_reapproval"
    assert "desktop" in verdict.gated_pending


def test_waiting_approval_never_reused():
    mission = _mission("running", ["desktop"], ["waiting_approval"])
    verdict = assess(mission, {"dact-1": ("mission_test1",
                                          mission.steps[0].step_id)})
    assert verdict.verdict == "needs_reapproval"


def test_dispatched_with_binding_waits_for_agent():
    mission = _mission("running", ["desktop"], ["dispatched"])
    step_id = mission.steps[0].step_id
    verdict = assess(mission,
                     {"dact-1": ("mission_test1", step_id)})
    assert verdict.verdict == "waiting_agent"


def test_dispatched_without_binding_needs_review():
    mission = _mission("running", ["desktop"], ["dispatched"])
    verdict = assess(mission, {})
    assert verdict.verdict == "needs_reapproval"


def test_write_step_needs_fresh_yes():
    mission = _mission("approved", ["write"])
    verdict = assess(mission)
    assert verdict.verdict == "needs_reapproval"


def test_bad_pointer_needs_review():
    mission = _mission("approved", ["readout"])
    mission = mission.model_copy(update={"current_step": 99})
    verdict = assess(mission)
    assert verdict.verdict == "needs_reapproval"


def test_scan_counts():
    missions = [
        _mission("approved", ["readout"]),
        _mission("pending_approval", ["readout"]),
        _mission("completed", ["readout"], ["completed"]),
    ]
    report = scan(missions)
    assert report["total"] == 3
    assert report["counts"]["safe_to_resume"] == 1
    assert report["counts"]["needs_reapproval"] == 1
    assert report["counts"]["terminal"] == 1
