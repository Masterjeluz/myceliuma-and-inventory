"""Desktop-agent task loop: observe -> propose -> approve -> act (Fase I).

The loop is deliberately slow and explicit. A ComputerAction starts as
pending_approval (or approved-by-policy for read-only actions),
waits for an exact human YES, may then be dispatched exactly once,
and closes with exactly one AgentActionResult. The operator can stop
the loop at any moment: cancel works from pending_approval and from
approved, and a dispatched action that never reports back stays
visible as dispatched — never silently completed.

This module is pure: transitions validate and return new records,
they never touch the database, the clock beyond an injected stamp,
or any desktop. Storage lives in the coordinator ``desktop_actions``
table (see database.py); HTTP mapping lives in main.py.

States: pending_approval -> approved -> dispatched ->
         completed | failed | blocked
         pending_approval -> rejected | cancelled
         approved -> cancelled

Rules (all tested, all fail-closed):

- only exact "YES" approves and only exact "NO" deliberately rejects
  (same words as the M6.3 gate, reused constants, no second dialect).
- decisions bind to one action_id; mismatches are refused.
- dispatch requires status approved; results require dispatched.
- exactly one terminal state; terminal records never transition.
- results reuse agent_results validation, so completed/false-error
  and error-less failure combinations are impossible.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .agent_results import AgentActionResult, new_result
from .approval import APPROVE_TEXT, REJECT_TEXT
from .computer_actions import ComputerAction
from .inventory_read import Provenance

ActionStatus = Literal[
    "pending_approval", "approved", "rejected", "cancelled",
    "dispatched", "completed", "failed", "blocked",
]
TERMINAL_STATUSES = frozenset(
    {"rejected", "cancelled", "completed", "failed", "blocked"})

#: Desktop dispatch lease, mirroring the task queue: a
#: dispatched action must report back inside this window or
#: lose the lease (expiry returns it to approved while
#: attempts remain, blocks it when exhausted).
DESKTOP_LEASE_SECONDS = 300
DESKTOP_MAX_ATTEMPTS = 3


class DesktopActionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ComputerAction
    status: str = "pending_approval"
    decided_by: str = ""
    note: str = Field(default="", max_length=500)
    result: AgentActionResult | None = None
    dispatched_by: str = Field(default="", max_length=80)
    dispatched_at: str = ""
    lease_until: str = ""
    attempt_count: int = Field(default=0, ge=0)
    provenance: Provenance = Field(default_factory=Provenance)


def propose(action: ComputerAction) -> DesktopActionRecord:
    """Open the loop for one validated action.

    Read-only actions (screenshot/wait) arrive pre-approved by policy;
    every input action waits for a human YES.
    """
    if not isinstance(action, ComputerAction):
        raise ValueError("Agent loop needs a ComputerAction")
    if action.requires_approval:
        status = "pending_approval"
        decided = ""
    else:
        status = "approved"
        decided = "policy:read-only-local"
    return DesktopActionRecord(
        action=action,
        status=status,
        decided_by=decided,
        provenance=Provenance(
            source_type="ai-generated" if action.requires_approval
            else "user-created",
            creator_id="desktop-agent-loop",
            human_verified=False,
        ),
    )


def _bind(record: DesktopActionRecord, action_id: str) -> None:
    if record.action.action_id != action_id:
        raise ValueError("Decision does not belong to this action")


def decide(record: DesktopActionRecord, action_id: str, response: str,
           decided_by: str = "human") -> DesktopActionRecord:
    """Resolve raw human input: exact YES approves, anything else denies."""
    _bind(record, action_id)
    if record.status != "pending_approval":
        raise ValueError(
            f"Action is {record.status}; only pending actions decide")
    if not isinstance(decided_by, str) or not decided_by.strip():
        raise ValueError("decided_by must be non-empty text")
    if response == APPROVE_TEXT:
        return record.model_copy(update={
            "status": "approved", "decided_by": decided_by.strip(),
            "note": ""})
    if response == REJECT_TEXT:
        return record.model_copy(update={
            "status": "rejected", "decided_by": decided_by.strip(),
            "note": "human answered NO"})
    return record.model_copy(update={
        "status": "rejected", "decided_by": decided_by.strip(),
        "note": "unrecognized response; default deny"})


def cancel(record: DesktopActionRecord, action_id: str,
           decided_by: str = "human") -> DesktopActionRecord:
    """Stop boundary: works from pending_approval, approved AND
    dispatched (lease revocation). Terminal records never cancel.

    Cancelling a dispatched action revokes the lease: the agent's
    pre-execution revalidation sees it and BLOCKS, and a late result
    is refused by the conditional update. An already-performed input
    cannot be un-done — cancellation prevents the NEXT input.
    """
    _bind(record, action_id)
    if record.status not in ("pending_approval", "approved", "dispatched"):
        raise ValueError(
            f"Action is {record.status}; only waiting or dispatched "
            "actions cancel")
    if not isinstance(decided_by, str) or not decided_by.strip():
        raise ValueError("decided_by must be non-empty text")
    return record.model_copy(update={
        "status": "cancelled", "decided_by": decided_by.strip(),
        "note": "stopped by operator"})


def dispatch(record: DesktopActionRecord, action_id: str,
             by: str = "", at: str = "") -> DesktopActionRecord:
    """Release one approved action to one local runtime. Exactly once.

    ``by`` pins the lease holder (node/agent id). An empty holder
    means a manual local dispatch with no remote owner; the standalone
    agent only executes actions dispatched to itself. Dispatch stamps
    a lease deadline (DESKTOP_LEASE_SECONDS past ``at``) and counts
    the attempt; exhausted records refuse re-dispatch and must be
    blocked by expiry instead.
    """
    from datetime import datetime, timedelta, timezone
    _bind(record, action_id)
    if record.status != "approved":
        raise ValueError(
            f"Action is {record.status}; only approved actions dispatch")
    if by and (not isinstance(by, str) or len(by) > 80):
        raise ValueError("dispatch owner must be 0..80 characters")
    if record.attempt_count >= DESKTOP_MAX_ATTEMPTS:
        raise ValueError(
            f"Action used all {DESKTOP_MAX_ATTEMPTS} attempts; "
            "it stays blocked, never silently retried")
    try:
        moment = datetime.fromisoformat(at) if at else \
            datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        raise ValueError("dispatch needs a readable timestamp")
    lease_until = (moment + timedelta(
        seconds=DESKTOP_LEASE_SECONDS)).isoformat()
    return record.model_copy(update={"status": "dispatched",
                                     "dispatched_by": by or "",
                                     "dispatched_at": moment.isoformat(),
                                     "lease_until": lease_until,
                                     "attempt_count":
                                     record.attempt_count + 1})


def record_result(record: DesktopActionRecord, action_id: str,
                  status: str, *,
                  error: str = "",
                  observation_reference: str = "") -> DesktopActionRecord:
    """Close a dispatched action with exactly one validated result."""
    _bind(record, action_id)
    if record.status != "dispatched":
        raise ValueError(
            f"Action is {record.status}; only dispatched actions close")
    result = new_result(action_id, status, error=error,
                        observation_reference=observation_reference)
    terminal = {"completed": "completed", "failed": "failed",
                "blocked": "blocked", "cancelled": "cancelled"}[status]
    return record.model_copy(update={"status": terminal, "result": result})


def describe(record: DesktopActionRecord) -> dict[str, Any]:
    """Operator-facing summary: what the agent wants / does / did."""
    return {
        "action_id": record.action.action_id,
        "action_type": record.action.action_type,
        "parameters": record.action.parameters,
        "status": record.status,
        "decided_by": record.decided_by,
        "note": record.note,
        "dispatched_by": record.dispatched_by,
        "dispatched_at": record.dispatched_at,
        "lease_until": record.lease_until,
        "attempt_count": record.attempt_count,
        "result": (record.result.model_dump(mode="json")
                   if record.result else None),
    }
