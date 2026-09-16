"""Controlled-write foundation tests (BIG #5).

The generic proposal/approval/result layer: allow-listed mutations,
exact-YES binding, fingerprint revalidation, staleness, and the
approval-is-not-verification rule.
"""

import pytest

from coordinator.app.controlled_writes import (
    decide_write,
    is_stale,
    propose_write,
    request_write_approval,
    revalidate,
    write_fingerprint,
)
from coordinator.app.inventory_read import Provenance


def ai_provenance() -> Provenance:
    return Provenance(source_type="ai-generated", creator_id="qwen",
                      human_verified=False)


def make_proposal(proposal_id="wrt-test1"):
    return propose_write(
        proposal_id, "inventory.create", "inventory:object",
        {"entity_type": "object",
         "fields": {"name": "Testonderdeel"}},
        actor="mycelium-test", provenance=ai_provenance())


def test_valid_proposal_is_inert_and_fingerprinted():
    proposal = make_proposal()
    assert proposal.mutation_type == "inventory.create"
    assert proposal.provenance.human_verified is False
    fingerprint = write_fingerprint(proposal)
    assert len(fingerprint) == 64
    # Deterministic for identical content (round-trip stable) ...
    assert write_fingerprint(proposal.model_copy()) == fingerprint
    assert write_fingerprint(
        proposal.model_validate(proposal.model_dump())) == fingerprint
    # ... and unique per proposal instance (created_at binds it).
    assert write_fingerprint(make_proposal()) != fingerprint


def test_unknown_mutation_type_refused():
    with pytest.raises(ValueError, match="Unknown mutation type"):
        propose_write("wrt-x", "database.drop_table", "inventory:object",
                      {}, actor="mycelium-test",
                      provenance=ai_provenance())


def test_free_form_mutations_not_expressible():
    for bad in ("shell.exec", "python.eval", "sql.raw", "http.post",
                "inventory.delete", "git.push", "git.force_push"):
        with pytest.raises(ValueError, match="Unknown mutation type"):
            propose_write("wrt-x", bad, "target", {},
                          actor="mycelium-test",
                          provenance=ai_provenance())


def test_proposal_never_claims_human_verification():
    bad = Provenance(source_type="ai-generated", creator_id="qwen",
                     human_verified=True)
    with pytest.raises(ValueError, match="never claim human verification"):
        propose_write("wrt-x", "inventory.create", "inventory:object",
                      {}, actor="mycelium-test", provenance=bad)


def test_exact_yes_approves_anything_else_denies():
    proposal = make_proposal()
    request = request_write_approval(proposal)
    approved = decide_write(request, proposal, "YES",
                            decided_by="jelles")
    assert approved.approved is True
    assert approved.decision == "approved"
    assert approved.fingerprint == write_fingerprint(proposal)
    for response in ("yes", "Yes", "NO", "OK", "", "JA"):
        denied = decide_write(request, proposal, response)
        assert denied.approved is False
        assert denied.decision == "rejected"


def test_approval_binds_exact_content():
    proposal = make_proposal()
    request = request_write_approval(proposal)
    tampered = proposal.model_copy(
        update={"payload": {"entity_type": "object",
                            "fields": {"name": "Ander onderdeel"}}})
    with pytest.raises(ValueError, match="differs from the approved"):
        decide_write(request, tampered, "YES")


def test_approval_binds_proposal_id():
    proposal = make_proposal("wrt-a")
    other = make_proposal("wrt-b")
    request = request_write_approval(proposal)
    with pytest.raises(ValueError, match="does not match"):
        decide_write(request, other, "YES")


def test_stale_proposal_refuses():
    proposal = make_proposal()
    request = request_write_approval(proposal)
    # Far future: expired long ago.
    with pytest.raises(ValueError, match="stale"):
        decide_write(request, proposal, "YES",
                     now_str="2999-01-01T00:00:00+00:00")
    assert is_stale(proposal, "2999-01-01T00:00:00+00:00") is True
    assert is_stale(proposal) is False


def test_revalidate_is_the_pre_execution_gate():
    proposal = make_proposal()
    request = request_write_approval(proposal)
    approval = decide_write(request, proposal, "YES")
    assert revalidate(proposal, approval) == approval.fingerprint
    # Rejected approval never executes.
    rejected = decide_write(request, proposal, "NO")
    with pytest.raises(ValueError, match="Only an approved"):
        revalidate(proposal, rejected)
    # Stale at execution time refuses even with a fresh approval.
    with pytest.raises(ValueError, match="stale"):
        revalidate(proposal, approval,
                   now_str="2999-01-01T00:00:00+00:00")


def test_capability_names_are_dotted():
    proposal = make_proposal()
    assert proposal.capability() == "inventory.write.create"
    git = propose_write("wrt-git", "git.commit", "git:/repo",
                        {"repository": "/repo"}, actor="mycelium-test",
                        provenance=ai_provenance())
    assert git.capability() == "git.write.commit"
