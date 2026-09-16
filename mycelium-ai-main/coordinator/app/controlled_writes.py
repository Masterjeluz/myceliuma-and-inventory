"""Controlled-write foundation for Mycelium (BIG #5).

Generic, domain-agnostic layer between PROPOSAL and ACTION:

    FACT / OBSERVATION -> ADVICE -> PROPOSAL -> APPROVAL
        -> CONTROLLED ACTION / WRITE -> RESULT -> VERIFICATION
        -> WORLD MODEL UPDATE

An LLM may only ever produce a proposal. A proposal never touches
anything: it becomes an action exclusively through an exact human
YES, bound to that exact proposal content (fingerprint), and every
executor must revalidate the binding immediately before acting.
Proposals expire (staleness) so an old YES can never authorize a
new world.

Rules (tested, all fail-closed):

- mutation_type comes from a closed allow-list; unknown types,
  free SQL, shell, code or arbitrary HTTP writes cannot be
  expressed here at all.
- a WriteProposal never claims human verification: its provenance
  must carry human_verified=False (approval is permission, not
  truth — see verification.py).
- approval binds (proposal_id + content fingerprint); any content
  change after approval is a fingerprint mismatch and refuses.
- approval requires an exact ``YES`` (same dialect as approval.py
  and agent_loop.py — no second dialect); anything else denies.
- proposals expire after WRITE_TTL_SECONDS; stale approvals refuse.
- executors call revalidate() immediately before acting; the
  generic layer itself performs no I/O of any kind.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import Provenance

APPROVE_TEXT = "YES"
REJECT_TEXT = "NO"

#: Closed set of mutation types. Domains add executors for these;
#: nothing outside this set can be proposed, approved or executed.
#: ``printer.execute`` (BIG #7) reuses the exact-YES/fingerprint/
#: staleness machinery for physical execution: it is a second,
#: explicit approval on top of any mission/plan approval — a plan
#: YES never means "start the machine". ``robot.execute`` and
#: ``drone.mission`` (BIG #16) reuse the same machinery for
#: physical-agent actions; like printing, approval authorizes
#: but execution itself stays HARDWARE_REQUIRED.
VALID_MUTATION_TYPES = frozenset({
    "inventory.create",
    "inventory.update",
    "inventory.create_relationship",
    "git.commit",
    "printer.execute",
    "robot.execute",
    "drone.mission",
})

MUTATION_CAPABILITIES = {
    "inventory.create": "inventory.write.create",
    "inventory.update": "inventory.write.update",
    "inventory.create_relationship": "inventory.write.relate",
    "git.commit": "git.write.commit",
    "printer.execute": "printer.execute",
    "robot.execute": "robot.execute",
    "drone.mission": "drone.mission",
}

#: A proposal authorizes execution for at most one hour afterwards.
WRITE_TTL_SECONDS = 3600

WriteOutcome = Literal["executed", "failed", "blocked"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


class WriteProposal(BaseModel):
    """A validated, inert description of one intended mutation."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=3, max_length=80)
    mutation_type: str = Field(min_length=1, max_length=40)
    target: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance = Field(default_factory=Provenance)
    actor: str = Field(min_length=1, max_length=80)
    created_at: str = ""
    expires_at: str = ""

    def capability(self) -> str:
        return MUTATION_CAPABILITIES[self.mutation_type]


class WriteApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=3, max_length=80)
    fingerprint: str = Field(min_length=64, max_length=64,
                             pattern=r"^[0-9a-f]{64}$")


class WriteApproval(BaseModel):
    """A recorded human decision. Permission only — never truth."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=3, max_length=80)
    fingerprint: str = Field(min_length=64, max_length=64,
                             pattern=r"^[0-9a-f]{64}$")
    approved: bool = False
    decision: Literal["approved", "rejected"] = "rejected"
    decided_by: str = Field(default="human", min_length=1, max_length=80)
    decided_at: str = ""
    note: str = Field(default="", max_length=500)


class WriteResult(BaseModel):
    """What execution actually did. Never automatically verified."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=3, max_length=80)
    fingerprint: str = Field(min_length=64, max_length=64,
                             pattern=r"^[0-9a-f]{64}$")
    outcome: WriteOutcome = "blocked"
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    actor: str = Field(min_length=1, max_length=80)
    executed_at: str = ""
    error: str = Field(default="", max_length=2000)
    provenance: Provenance = Field(default_factory=Provenance)


def write_fingerprint(proposal: WriteProposal) -> str:
    """Deterministic content hash of a proposal (sha256, hex)."""
    canonical = json.dumps(proposal.model_dump(mode="json"),
                           sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _check_provenance(provenance: Provenance) -> None:
    verified = (provenance.get("human_verified")
                if isinstance(provenance, dict)
                else getattr(provenance, "human_verified", False))
    if verified:
        raise ValueError(
            "Write proposals never claim human verification; "
            "approval is permission, verification is a separate step")


def propose_write(proposal_id: str, mutation_type: str, target: str,
                  payload: dict, *, actor: str,
                  provenance: Provenance | None = None,
                  ttl_seconds: int = WRITE_TTL_SECONDS) -> WriteProposal:
    """Build a validated, inert write proposal. Performs nothing."""
    if mutation_type not in VALID_MUTATION_TYPES:
        raise ValueError(
            f"Unknown mutation type '{mutation_type}'; "
            f"expected one of {sorted(VALID_MUTATION_TYPES)}")
    if not isinstance(target, str) or not target.strip():
        raise ValueError("Write target must be non-empty text")
    if not isinstance(payload, dict):
        raise ValueError("Write payload must be an object")
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("actor must be non-empty text")
    provenance = provenance or Provenance(
        source_type="ai-generated", creator_id=actor.strip(),
        human_verified=False,
        notes="write proposal; inert until human approval")
    _check_provenance(provenance)
    try:
        ttl = int(ttl_seconds)
    except (TypeError, ValueError):
        raise ValueError("ttl_seconds must be an integer")
    if ttl <= 0 or ttl > 24 * 3600:
        raise ValueError("ttl_seconds must be 1..86400")
    created = datetime.now(timezone.utc)
    proposal = WriteProposal(
        proposal_id=proposal_id,
        mutation_type=mutation_type,
        target=target.strip(),
        payload=dict(payload),
        provenance=provenance,
        actor=actor.strip(),
        created_at=created.isoformat(),
        expires_at=(created + timedelta(seconds=ttl)).isoformat(),
    )
    return proposal


def request_write_approval(proposal: WriteProposal) -> WriteApprovalRequest:
    """Open an approval request bound to one exact proposal content."""
    if not isinstance(proposal, WriteProposal):
        raise ValueError("Approval needs a WriteProposal")
    return WriteApprovalRequest(proposal_id=proposal.proposal_id,
                                fingerprint=write_fingerprint(proposal))


def is_stale(proposal: WriteProposal, now_str: str | None = None) -> bool:
    """True when the proposal expired (or carries unreadable time)."""
    try:
        current = _parse_time(now_str) if now_str else datetime.now(timezone.utc)
        return current > _parse_time(proposal.expires_at)
    except (ValueError, TypeError):
        return True


def decide_write(request: WriteApprovalRequest, proposal: WriteProposal,
                 response: str, decided_by: str = "human",
                 now_str: str | None = None) -> WriteApproval:
    """Resolve raw human input: exact YES approves, else denies.

    Approving a stale proposal or a proposal whose content changed
    since the request refuses (fail-closed).
    """
    if not isinstance(request, WriteApprovalRequest):
        raise ValueError("Decision needs a WriteApprovalRequest")
    if not isinstance(proposal, WriteProposal):
        raise ValueError("Decision needs a WriteProposal")
    if request.proposal_id != proposal.proposal_id:
        raise ValueError("Approval request does not match this proposal")
    if not isinstance(decided_by, str) or not decided_by.strip():
        raise ValueError("decided_by must be non-empty text")
    current_fingerprint = write_fingerprint(proposal)
    if request.fingerprint != current_fingerprint:
        raise ValueError("Proposal content differs from the approved content")
    if is_stale(proposal, now_str):
        raise ValueError("Proposal is stale; re-propose instead")
    stamp = now_str or now()
    if response == APPROVE_TEXT:
        return WriteApproval(
            proposal_id=request.proposal_id,
            fingerprint=current_fingerprint,
            approved=True, decision="approved",
            decided_by=decided_by.strip(), decided_at=stamp)
    note = ("human answered NO" if response == REJECT_TEXT
            else "unrecognized response; default deny")
    return WriteApproval(
        proposal_id=request.proposal_id,
        fingerprint=current_fingerprint,
        approved=False, decision="rejected",
        decided_by=decided_by.strip(), decided_at=stamp, note=note)


def revalidate(proposal: WriteProposal, approval: WriteApproval,
               now_str: str | None = None) -> str:
    """Final gate immediately before execution. Returns fingerprint.

    Every executor must call this right before acting; any mismatch
    raises and the write must not happen.
    """
    if not isinstance(proposal, WriteProposal):
        raise ValueError("Execution needs a WriteProposal")
    if not isinstance(approval, WriteApproval):
        raise ValueError("Execution needs a WriteApproval")
    if approval.approved is not True or approval.decision != "approved":
        raise ValueError("Only an approved decision executes")
    if (approval.proposal_id != proposal.proposal_id
            or approval.fingerprint != write_fingerprint(proposal)):
        raise ValueError("Approval does not bind to this exact proposal")
    if is_stale(proposal, now_str):
        raise ValueError("Proposal is stale; re-propose instead")
    return approval.fingerprint
