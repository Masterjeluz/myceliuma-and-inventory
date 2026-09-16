"""Mission write-step tests (BIG #5).

Write steps bind to exactly one stored write proposal. The
executor never writes itself: without a wired capability the
step BLOCKs; unapproved writes BLOCK; executed-but-unverified
writes complete the step WITHOUT verification; verified writes
complete WITH it.
"""

import asyncio

import pytest

from coordinator.app.mission_executor import ExecutorDeps, MissionExecutor
from coordinator.app.missions import (
    new_event,
    new_mission,
    save_mission,
)


def run(coro):
    return asyncio.run(coro)


def ai_provenance() -> Provenance:
    return Provenance(source_type="ai-generated", creator_id="t",
                      human_verified=False)


def make_deps(run_write=None):
    async def _advise(question, records):
        raise AssertionError("no advisor in write tests")

    async def _search(query):
        return []

    return ExecutorDeps(
        propose_desktop=lambda *a: (_ for _ in ()).throw(
            AssertionError("no desktop in write tests")),
        load_desktop=lambda action_id: None,
        post_message=lambda *a: "msg-1",
        advise=_advise,
        inventory_search=_search,
        git_read=lambda source: {},
        project_read=lambda: {},
        run_write=run_write,
    )


def make_mission(tmp_path, monkeypatch, proposal_id="wrt-m1"):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "missions.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "missions-chat.db"))
    mission = new_mission(
        "mission_write1", "conv-1", "Leg een bout vast",
        [{"kind": "write", "description": "Maak object aan",
          "parameters": {"proposal_id": proposal_id}}])
    # Approve the plan so tick() may run.
    from coordinator.app.missions import approve_mission
    mission = approve_mission(mission, "YES")
    mission = mission.model_copy(update={"status": "running"})
    save_mission(mission)
    return mission


def test_write_step_kind_validates_proposal_binding():
    mission = new_mission(
        "mission_x", "conv-1", "doel",
        [{"kind": "write", "description": "x",
          "parameters": {"proposal_id": "wrt-1"}}])
    assert mission.steps[0].kind == "write"
    with pytest.raises(ValueError, match="proposal_id"):
        new_mission("mission_y", "conv-1", "doel",
                    [{"kind": "write", "description": "x",
                      "parameters": {}}])
    with pytest.raises(ValueError, match="only proposal_id"):
        new_mission("mission_z", "conv-1", "doel",
                    [{"kind": "write", "description": "x",
                      "parameters": {"proposal_id": "wrt-1",
                                     "sql": "DROP"}}])
    with pytest.raises(ValueError, match="step-level approval"):
        new_mission("mission_w", "conv-1", "doel",
                    [{"kind": "write", "description": "x",
                      "parameters": {"proposal_id": "wrt-1"},
                      "requires_approval": True}])


def test_write_step_without_capability_blocks(tmp_path, monkeypatch):
    mission = make_mission(tmp_path, monkeypatch)
    executor = MissionExecutor(make_deps(run_write=None))
    summary = run(executor.tick(mission.mission_id))
    assert summary["status"] == "blocked"


def test_write_step_verified_completion(tmp_path, monkeypatch):
    mission = make_mission(tmp_path, monkeypatch)

    async def fake_run_write(mission_arg, step):
        assert step.parameters["proposal_id"] == "wrt-m1"
        return {"status": "completed",
                "result_text": "Write 'wrt-m1' executed.",
                "verification": "passed: readback matches",
                "verified": True}

    executor = MissionExecutor(make_deps(run_write=fake_run_write))
    summary = run(executor.tick(mission.mission_id))
    assert summary["status"] == "completed"
    from coordinator.app.missions import load_mission
    reloaded = load_mission(mission.mission_id)
    assert reloaded.steps[0].status == "completed"
    assert "passed" in reloaded.steps[0].result_text


def test_write_step_unverified_completion_marks_it(tmp_path, monkeypatch):
    mission = make_mission(tmp_path, monkeypatch)

    async def fake_run_write(mission_arg, step):
        return {"status": "completed",
                "result_text": "Write 'wrt-m1' executed.",
                "verification": "failed: readback differs",
                "verified": False}

    executor = MissionExecutor(make_deps(run_write=fake_run_write))
    summary = run(executor.tick(mission.mission_id))
    assert summary["status"] == "completed"
    from coordinator.app.missions import load_mission
    reloaded = load_mission(mission.mission_id)
    assert "NIET geslaagd" in reloaded.steps[0].result_text


def test_write_step_failure_fails_mission(tmp_path, monkeypatch):
    mission = make_mission(tmp_path, monkeypatch)

    async def fake_run_write(mission_arg, step):
        return {"status": "failed",
                "result_text": "target missing",
                "verification": "no execution; no verification",
                "verified": False}

    executor = MissionExecutor(make_deps(run_write=fake_run_write))
    summary = run(executor.tick(mission.mission_id))
    assert summary["status"] == "failed"


def test_write_events_exist_in_audit_chain():
    for event_type in ("write_proposed", "write_approved",
                       "write_executed", "write_result",
                       "verification_started", "verification_passed",
                       "verification_failed"):
        event = new_event("conv-1", event_type, "audit",
                          mission_id="mission_1", step_id="step_1")
        assert event.event_type == event_type
