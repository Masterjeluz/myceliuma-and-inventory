"""Tests for M6.4 approved-proposal to task translation (data only).

No network, no subprocess, no filesystem writes, no database, no hardware.
Translation is pure: identical inputs always yield identical tasks.
"""
from pathlib import Path

import pytest

from coordinator.app.adapters import ReferenceNoopAdapter
from coordinator.app.adapter_contracts import AdapterRequest
from coordinator.app.approval import approve, decide, reject, request_approval
from coordinator.app.proposal_tasks import (
    CoordinatorTask,
    proposal_fingerprint,
    proposal_to_task,
)

PROV = {"source_type": "user-created", "creator_id": "tester",
        "human_verified": True}


def make_proposal(request_id="req-9"):
    adapter = ReferenceNoopAdapter()
    request = AdapterRequest(request_id=request_id, adapter_id="reference-noop",
                             model_id="mod_cam", node_id="node-1",
                             task_id="task_3",
                             input={"object_id": "obj_1"},
                             provenance=dict(PROV))
    return adapter.propose(request)


def make_approved(proposal=None):
    proposal = proposal if proposal is not None else make_proposal()
    approval_request = request_approval(proposal)
    approval = approve(approval_request, proposal, decided_by="jelles")
    return proposal, approval, proposal_fingerprint(proposal)


def translate(proposal=None, approval=None, fingerprint=None, **kwargs):
    proposal = proposal if proposal is not None else make_proposal()
    if approval is None or fingerprint is None:
        _, auto_approval, auto_fp = make_approved(proposal)
        approval = approval if approval is not None else auto_approval
        fingerprint = fingerprint if fingerprint is not None else auto_fp
    return proposal_to_task(proposal, approval, approved_fingerprint=fingerprint,
                            **kwargs)


# --- happy path --------------------------------------------------------------------------

def test_valid_approved_proposal_translates():
    proposal, approval, fingerprint = make_approved()
    task = translate(proposal, approval, fingerprint,
                     task_type="inspect", input={"object_id": "obj_1"})
    assert isinstance(task, CoordinatorTask)
    assert task.status == "approved"
    assert task.proposal_id == proposal.proposal_id
    assert task.request_id == proposal.request_id
    assert task.model_id == "mod_cam"
    assert task.adapter_id == "reference-noop"
    assert task.node_id == "node-1"
    assert task.task_type == "inspect"
    assert task.input == {"object_id": "obj_1"}
    assert task.expected_output == proposal.expected_output
    assert task.approval_reference == approval
    assert task.proposal_fingerprint == fingerprint
    assert task.provenance.human_verified is False
    assert task.provenance.source_type == "ai-generated"


def test_default_task_id_derived_deterministically():
    proposal, approval, fingerprint = make_approved()
    first = translate(proposal, approval, fingerprint)
    second = translate(proposal, approval, fingerprint)
    assert first == second
    assert first.task_id == f"ctask-{proposal.proposal_id}"


# --- refusals ---------------------------------------------------------------------------------

def test_unapproved_proposal_refused():
    proposal = make_proposal()
    with pytest.raises(ValueError):
        translate(proposal, None, "x" * 64)


def test_rejected_approval_refused():
    proposal = make_proposal()
    approval_request = request_approval(proposal)
    denied = reject(approval_request, proposal)
    with pytest.raises(ValueError):
        translate(proposal, denied, proposal_fingerprint(proposal))


def test_decide_no_refused():
    proposal = make_proposal()
    approval_request = request_approval(proposal)
    denied = decide(approval_request, proposal, "NO")
    with pytest.raises(ValueError):
        translate(proposal, denied, proposal_fingerprint(proposal))


def test_proposal_id_mismatch_refused():
    proposal, approval, fingerprint = make_approved()
    other = make_proposal(request_id="req-other")
    with pytest.raises(ValueError):
        translate(other, approval, fingerprint)


def test_request_id_mismatch_refused():
    proposal, approval, fingerprint = make_approved()
    tampered = approval.model_copy(update={"request_id": "req-other"})
    with pytest.raises(ValueError):
        translate(proposal, tampered, fingerprint)


def test_requires_approval_false_refused():
    proposal, approval, fingerprint = make_approved()
    stripped = proposal.model_copy(update={"requires_approval": False})
    with pytest.raises(ValueError):
        translate(stripped, approval, proposal_fingerprint(stripped))


def test_verified_bypass_refused():
    proposal, approval, fingerprint = make_approved()
    faked = proposal.model_copy(update={"provenance": {
        "source_type": "ai-generated", "creator_id": "adapter:x",
        "human_verified": True}})
    with pytest.raises(ValueError):
        translate(faked, approval, proposal_fingerprint(faked))


def test_modified_proposal_after_approval_refused():
    proposal, approval, fingerprint = make_approved()
    altered = proposal.model_copy(
        update={"proposed_action": "Do something entirely different"})
    assert proposal_fingerprint(altered) != fingerprint
    with pytest.raises(ValueError):
        translate(altered, approval, fingerprint)


def test_wrong_fingerprint_refused():
    proposal, approval, _ = make_approved()
    with pytest.raises(ValueError):
        translate(proposal, approval, "0" * 64)


# --- preservation ----------------------------------------------------------------------------------

def test_fields_preserved():
    proposal, approval, fingerprint = make_approved()
    task = translate(proposal, approval, fingerprint, input={"k": "v"})
    assert task.model_id == proposal.model_id
    assert task.adapter_id == proposal.adapter_id
    assert task.node_id == proposal.node_id
    assert task.input == {"k": "v"}
    assert task.expected_output == proposal.expected_output
    assert task.approval_reference.proposal_id == proposal.proposal_id
    assert task.approval_reference.decided_by == "jelles"


def test_translation_marks_nothing_verified_or_done():
    proposal, approval, fingerprint = make_approved()
    task = translate(proposal, approval, fingerprint)
    assert task.status == "approved"
    assert task.provenance.human_verified is False
    dump = task.model_dump()
    assert dump["status"] == "approved"
    for forbidden in ("completed", "executed", "success"):
        assert forbidden not in str(dump.get("status"))


# --- purity ----------------------------------------------------------------------------------------------

def test_no_global_state_and_no_clock():
    proposal, approval, fingerprint = make_approved()
    results = [translate(proposal, approval, fingerprint).model_dump()
               for _ in range(3)]
    assert results[0] == results[1] == results[2]


def test_coordinator_db_untouched(tmp_path, monkeypatch):
    import os
    os.environ["MYCELIUM_DATABASE_PATH"] = str(tmp_path / "m64.db")
    proposal, approval, fingerprint = make_approved()
    translate(proposal, approval, fingerprint)
    from coordinator.app.database import connection
    with connection() as db:
        tables = sorted(r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall())
    assert tables == []


def test_no_execution_attributes():
    import coordinator.app.proposal_tasks as module
    for name in dir(module):
        if name.startswith("__"):
            continue
        lowered = name.lower()
        for token in ("execute", "run", "infer", "fetch", "download", "shell"):
            assert token not in lowered, f"translation layer must not offer {name}"


def test_implementation_has_no_io_tokens():
    source = (Path(__file__).resolve().parent.parent
              / "coordinator" / "app" / "proposal_tasks.py").read_text(
                  encoding="utf-8")
    for token in ("subprocess", "os.system", "socket", "httpx", "requests",
                  "torch", "transformers", "ollama", "serial", "GPIO",
                  "threading", "asyncio", "pathlib", "shutil", "open(",
                  "execute", "inference", "download", "filesystem-write",
                  "datetime", "time.time", "random"):
        assert token not in source, f"translation layer must not use {token}"
