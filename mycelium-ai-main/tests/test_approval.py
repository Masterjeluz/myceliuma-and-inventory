"""Tests for the M6.3 human approval gate (decision records only).

No network, no subprocess, no filesystem writes, no hardware. Approval is a
pure function of (request, proposal, response): no clocks, no shared state.
"""
from pathlib import Path

import pytest
from pydantic import ValidationError

from coordinator.app.adapters import ReferenceNoopAdapter
from coordinator.app.adapter_contracts import AdapterProposal, AdapterRequest
from coordinator.app.approval import (
    ApprovalRequest,
    ApprovalResult,
    approve,
    decide,
    reject,
    request_approval,
)

PROV = {"source_type": "user-created", "creator_id": "tester",
        "human_verified": True}


def make_proposal(proposal_id="prop-req-1", request_id="req-1"):
    adapter = ReferenceNoopAdapter()
    request = AdapterRequest(request_id=request_id,
                             adapter_id="reference-noop",
                             input={"object_id": "obj_1"},
                             provenance=dict(PROV))
    proposal = adapter.propose(request)
    return proposal.model_copy(update={"proposal_id": proposal_id,
                                       "request_id": request_id})


def make_pair(**overrides):
    proposal = make_proposal(**overrides)
    return request_approval(proposal), proposal


# --- default deny --------------------------------------------------------------------

def test_default_deny_without_decision():
    request, proposal = make_pair()
    assert isinstance(request, ApprovalRequest)
    assert isinstance(request_approval(proposal), ApprovalRequest)
    # Opening a request approves nothing by itself.
    assert not hasattr(request, "approved")


def test_exact_yes_approves():
    request, proposal = make_pair()
    result = decide(request, proposal, "YES")
    assert isinstance(result, ApprovalResult)
    assert result.approved is True
    assert result.decision == "approved"
    assert result.proposal_id == proposal.proposal_id


def test_exact_no_rejects():
    request, proposal = make_pair()
    result = decide(request, proposal, "NO")
    assert result.approved is False
    assert result.decision == "rejected"


@pytest.mark.parametrize("response", [
    "yes", "Yes", "YES ", " YES", " Y", "N", "no", "", "   ",
    "YESS", "OK", "approve", "1", "True", "JA", "oui", "\nYES\n",
])
def test_anything_else_rejects(response):
    request, proposal = make_pair()
    result = decide(request, proposal, response)
    assert result.approved is False
    assert result.decision == "rejected"


# --- binding ----------------------------------------------------------------------------

def test_wrong_proposal_id_rejects():
    request, proposal = make_pair()
    other = make_proposal(proposal_id="prop-other", request_id="req-1")
    with pytest.raises(ValueError):
        decide(request, other, "YES")
    with pytest.raises(ValueError):
        approve(request, other)
    with pytest.raises(ValueError):
        reject(request, other)


def test_approval_of_a_cannot_apply_to_b():
    request_a, proposal_a = make_pair(proposal_id="prop-a", request_id="req-a")
    _, proposal_b = make_pair(proposal_id="prop-b", request_id="req-b")
    with pytest.raises(ValueError):
        approve(request_a, proposal_b)
    result = approve(request_a, proposal_a)
    assert result.proposal_id == "prop-a"
    assert result.request_id == "req-a"


def test_approval_without_proposal_fails_closed():
    with pytest.raises((ValueError, ValidationError, AttributeError, TypeError)):
        decide(ApprovalRequest(proposal_id="prop-x", request_id="req-x"),
               None, "YES")
    with pytest.raises((ValueError, ValidationError, AttributeError, TypeError)):
        approve(ApprovalRequest(proposal_id="prop-x", request_id="req-x"), None)


def test_request_approval_needs_real_proposal():
    with pytest.raises(ValueError):
        request_approval({"proposal_id": "prop-x"})
    with pytest.raises(ValueError):
        request_approval(None)


# --- explicit actions ----------------------------------------------------------------------

def test_approve_and_reject_actions():
    request, proposal = make_pair()
    approved = approve(request, proposal, decided_by="jelles")
    assert approved.approved is True
    assert approved.decided_by == "jelles"
    rejected = reject(request, proposal, decided_by="jelles", note="not now")
    assert rejected.approved is False
    assert rejected.note == "not now"


def test_double_approval_has_no_hidden_state():
    request, proposal = make_pair()
    assert approve(request, proposal) == approve(request, proposal)
    assert decide(request, proposal, "YES") == approve(request, proposal)
    assert decide(request, proposal, "maybe").approved is False
    assert reject(request, proposal).approved is False


def test_deterministic_results():
    request, proposal = make_pair()
    assert (decide(request, proposal, "YES").model_dump()
            == decide(request, proposal, "YES").model_dump())


# --- proposal guarantees survive the gate ------------------------------------------------------

def test_gate_preserves_proposal_guarantees():
    request, proposal = make_pair()
    assert proposal.requires_approval is True
    result = approve(request, proposal)
    assert proposal.requires_approval is True
    assert proposal.provenance.human_verified is False
    assert result.proposal_provenance.human_verified is False
    assert result.proposal_provenance.source_type == "ai-generated"


def test_gate_never_marks_data_verified():
    request, proposal = make_pair()
    for result in (decide(request, proposal, "YES"),
                   approve(request, proposal),
                   reject(request, proposal)):
        assert result.proposal_provenance.human_verified is False


# --- absence of execution -------------------------------------------------------------------------

def test_no_execution_attributes():
    import coordinator.app.approval as approval_mod
    for name in dir(approval_mod):
        if name.startswith("__"):
            continue
        lowered = name.lower()
        for token in ("execute", "run", "infer", "fetch", "download", "shell"):
            assert token not in lowered, f"approval module must not offer {name}"


def test_implementation_has_no_io_tokens():
    source = (Path(__file__).resolve().parent.parent
              / "coordinator" / "app" / "approval.py").read_text(encoding="utf-8")
    for token in ("subprocess", "os.system", "socket", "httpx", "requests",
                  "torch", "transformers", "ollama", "serial", "GPIO",
                  "threading", "asyncio", "pathlib", "shutil", "open(",
                  "execute", "inference", "download", "filesystem-write"):
        assert token not in source, f"approval layer must not use {token}"
