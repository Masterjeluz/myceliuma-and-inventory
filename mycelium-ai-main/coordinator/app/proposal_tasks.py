"""Approved-proposal to coordinator-task translation (M6.4).

Pure translation layer: an approved AdapterProposal becomes a
CoordinatorTask representation. Nothing is queued anywhere, nothing is
started, and no state of any kind is touched.

Binding rules (every mismatch fails closed):

- the ApprovalResult must carry approved=True;
- approval.proposal_id and approval.request_id must equal the proposal's;
- the proposal must carry requires_approval=True;
- the proposal's provenance must not claim human verification;
- the caller presents the fingerprint recorded when approval was granted;
  the proposal given here must reproduce it exactly, which proves the
  approved content was not altered afterwards.

Status ``approved`` means only that an approved proposal was translated
into a task representation. It never means queued, started, completed,
or verified.
"""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .adapter_contracts import AdapterProposal
from .approval import ApprovalResult
from .inventory_read import Provenance


class CoordinatorTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=3, max_length=80)
    proposal_id: str = Field(min_length=3, max_length=80)
    request_id: str = Field(min_length=3, max_length=80)
    model_id: str | None = Field(default=None, max_length=120)
    adapter_id: str = Field(min_length=1, max_length=80)
    node_id: str | None = Field(default=None, min_length=3, max_length=80)
    task_type: str = Field(default="other", min_length=1, max_length=40)
    input: dict[str, Any] = Field(default_factory=dict)
    expected_output: str = Field(default="", max_length=2000)
    status: Literal["approved"] = "approved"
    provenance: Provenance = Field(default_factory=Provenance)
    approval_reference: ApprovalResult
    proposal_fingerprint: str = Field(min_length=64, max_length=64)


def proposal_fingerprint(proposal: AdapterProposal) -> str:
    """Deterministic content hash of a proposal (sha256, hex)."""
    canonical = json.dumps(proposal.model_dump(mode="json"),
                           sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def proposal_to_task(proposal: AdapterProposal, approval: ApprovalResult, *,
                     task_id: str | None = None,
                     task_type: str = "other",
                     input: dict | None = None,
                     approved_fingerprint: str) -> CoordinatorTask:
    """Translate an approved proposal into a task representation.

    ``approved_fingerprint`` is the hash recorded when approval was
    granted; it must match the proposal given here.
    """
    if not isinstance(proposal, AdapterProposal):
        raise ValueError("Translation needs an AdapterProposal")
    if not isinstance(approval, ApprovalResult):
        raise ValueError("Translation needs an ApprovalResult")
    if approval.approved is not True or approval.decision != "approved":
        raise ValueError("Only approved proposals translate to tasks")
    if (approval.proposal_id != proposal.proposal_id
            or approval.request_id != proposal.request_id):
        raise ValueError("Approval does not belong to this proposal")
    if proposal.requires_approval is not True:
        raise ValueError("Proposals without requires_approval never translate")
    provenance = proposal.provenance
    if isinstance(provenance, dict):
        verified = provenance.get("human_verified")
    else:
        verified = getattr(provenance, "human_verified", False)
    if verified:
        raise ValueError("Verified-marked proposals never translate")
    if proposal_fingerprint(proposal) != approved_fingerprint:
        raise ValueError("Proposal content differs from the approved content")
    resolved_id = task_id if task_id is not None else f"ctask-{proposal.proposal_id}"
    if (not isinstance(resolved_id, str) or not (3 <= len(resolved_id) <= 80)):
        raise ValueError("task_id must be 3..80 characters")
    if not isinstance(task_type, str) or not task_type.strip() or len(task_type) > 40:
        raise ValueError("task_type must be 1..40 characters")
    if input is not None and not isinstance(input, dict):
        raise ValueError("input must be an object")
    return CoordinatorTask(
        task_id=resolved_id,
        proposal_id=proposal.proposal_id,
        request_id=proposal.request_id,
        model_id=proposal.model_id,
        adapter_id=proposal.adapter_id,
        node_id=proposal.node_id,
        task_type=task_type.strip(),
        input=dict(input) if input is not None else {},
        expected_output=proposal.expected_output,
        status="approved",
        provenance=proposal.provenance,
        approval_reference=approval,
        proposal_fingerprint=approved_fingerprint,
    )
