"""Human approval gate for adapter proposals (M6.3).

Pure decision layer: a proposal is never approved automatically, and an
approval never starts anything. The outcome is a data record that a future
system may consult before treating a proposal as approved.

Policy (explicit, tested):

- Only an exact ``YES`` approves; only an exact ``NO`` is a deliberate
  rejection. Every other input denies. No normalization is applied.
- An approval binds to one specific proposal: both ``proposal_id`` and
  ``request_id`` must match, otherwise the call fails closed.
- ``requires_approval=False`` can never bypass this gate: proposals that
  lack it are refused outright.
- Approval records the decision; it never rewrites the proposal's
  provenance and never marks data as human-verified.
- No wall-clock values, no shared mutable state, no retries, no I/O.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .adapter_contracts import AdapterProposal
from .inventory_read import Provenance

ApprovalDecision = Literal["approved", "rejected"]
APPROVE_TEXT = "YES"
REJECT_TEXT = "NO"


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=3, max_length=80)
    request_id: str = Field(min_length=3, max_length=80)


class ApprovalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=3, max_length=80)
    request_id: str = Field(min_length=3, max_length=80)
    decision: ApprovalDecision
    approved: bool
    decided_by: str = Field(default="human", min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)
    proposal_provenance: Provenance = Field(default_factory=Provenance)


def request_approval(proposal: AdapterProposal) -> ApprovalRequest:
    """Open an approval request bound to one specific proposal."""
    if not isinstance(proposal, AdapterProposal):
        raise ValueError("Approval needs an AdapterProposal")
    if proposal.requires_approval is not True:
        raise ValueError("Proposals without requires_approval cannot enter the gate")
    return ApprovalRequest(proposal_id=proposal.proposal_id,
                           request_id=proposal.request_id)


def _bind(request: ApprovalRequest, proposal: AdapterProposal) -> None:
    if (request.proposal_id != proposal.proposal_id
            or request.request_id != proposal.request_id):
        raise ValueError("Approval request does not match this proposal")


def _result(request: ApprovalRequest, proposal: AdapterProposal,
            decision: ApprovalDecision, decided_by: str, note: str = "") -> ApprovalResult:
    return ApprovalResult(
        proposal_id=request.proposal_id,
        request_id=request.request_id,
        decision=decision,
        approved=(decision == "approved"),
        decided_by=decided_by,
        note=note,
        proposal_provenance=proposal.provenance,
    )


def decide(request: ApprovalRequest, proposal: AdapterProposal, response: str,
           decided_by: str = "human") -> ApprovalResult:
    """Resolve raw human input: exact YES approves, anything else denies."""
    _bind(request, proposal)
    if not isinstance(decided_by, str) or not decided_by.strip():
        raise ValueError("decided_by must be non-empty text")
    if response == APPROVE_TEXT:
        return _result(request, proposal, "approved", decided_by.strip())
    if response == REJECT_TEXT:
        return _result(request, proposal, "rejected", decided_by.strip(),
                       note="human answered NO")
    return _result(request, proposal, "rejected", decided_by.strip(),
                   note="unrecognized response; default deny")


def approve(request: ApprovalRequest, proposal: AdapterProposal,
            decided_by: str = "human") -> ApprovalResult:
    """Record an explicit human YES. Calling this IS the human decision."""
    _bind(request, proposal)
    if not isinstance(decided_by, str) or not decided_by.strip():
        raise ValueError("decided_by must be non-empty text")
    return _result(request, proposal, "approved", decided_by.strip())


def reject(request: ApprovalRequest, proposal: AdapterProposal,
           decided_by: str = "human", note: str = "") -> ApprovalResult:
    """Record an explicit human NO."""
    _bind(request, proposal)
    if not isinstance(decided_by, str) or not decided_by.strip():
        raise ValueError("decided_by must be non-empty text")
    if not isinstance(note, str):
        raise ValueError("note must be text")
    return _result(request, proposal, "rejected", decided_by.strip(),
                   note=note[:500])
