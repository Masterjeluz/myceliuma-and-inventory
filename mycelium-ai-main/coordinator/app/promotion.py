"""Staged to queued promotion gate (M7.1). New safety boundary.

A staged CoordinatorTask becomes queued only through an explicit human
promotion decision. Promotion verifies, atomically flips one row from
``staged`` to ``queued``, and records an audit. Nothing here hands work
to nodes, marks anything assigned, or starts any executor: after this
module, existing queue semantics apply unchanged.

Promotion verifies, in order (any failure denies):

1. the staged row exists with status ``staged`` and the staging kind;
2. the row payload carries the request's staging_key;
3. the embedded task is approved, bound to the given approval, carries a
   valid fingerprint, and never claims human verification;
4. the embedded task fingerprint equals the request's proposal fingerprint;
5. a fresh fingerprint over the embedded task equals the request's staged
   fingerprint, proving the staged content is unchanged;
6. the selected node exists and its live capabilities equal the approved
   snapshot (normalized);
7. a fresh M6.2 match on live data yields a compatible verdict for the
   recorded model and adapter;
8. one atomic UPDATE flips ``staged`` to ``queued`` (plus the validated
   requirements) and touches nothing else.

The queued row keeps the staging kind and payload. Nodes may later claim
queued rows through the existing, unchanged claim path.
"""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .approval import ApprovalResult
from .capability_matching import (
    ModelInfo,
    NodeInfo,
    TaskIntent,
    default_registry,
    match_task,
)
from .database import connection, dump, load
from .inventory_read import Provenance
from .proposal_tasks import CoordinatorTask
from .task_queue_bridge import STAGED_KIND, STAGED_STATUS

QUEUED_STATUS = "queued"
SAFE_ID_PATTERN = r"^[a-zA-Z0-9._-]+$"


class PromotionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    promotion_request_id: str = Field(min_length=3, max_length=80,
                                     pattern=SAFE_ID_PATTERN)
    staging_key: str = Field(min_length=1, max_length=300)
    queue_id: int = Field(ge=1)
    proposal_fingerprint: str = Field(min_length=64, max_length=64,
                                      pattern=r"^[0-9a-f]{64}$")
    staged_fingerprint: str = Field(min_length=64, max_length=64,
                                    pattern=r"^[0-9a-f]{64}$")
    selected_node_id: str = Field(min_length=3, max_length=80,
                                  pattern=SAFE_ID_PATTERN)
    required_capabilities: list[str] = Field(default_factory=list, max_length=50)
    model: dict[str, Any]
    adapter_id: str = Field(min_length=1, max_length=80, pattern=SAFE_ID_PATTERN)
    capability_snapshot: list[str] = Field(default_factory=list, max_length=30)
    note: str = Field(default="", max_length=500)


class PromotionAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    promotion_request_id: str = Field(min_length=3, max_length=80)
    staging_key: str = Field(min_length=1, max_length=300)
    queue_id: int = Field(ge=1)
    original_fingerprint: str = Field(min_length=64, max_length=64)
    current_fingerprint: str = Field(min_length=64, max_length=64)
    selected_node_id: str = Field(min_length=3, max_length=80)
    capability_snapshot: list[str] = Field(default_factory=list)
    approval: ApprovalResult
    result: Literal["queued"] = "queued"
    provenance: Provenance = Field(default_factory=Provenance)


def _normalize(values) -> list[str]:
    seen: list[str] = []
    for value in values or []:
        text = str(value).strip().lower()
        if text and text not in seen:
            seen.append(text)
    return sorted(seen)


def staged_fingerprint(task_data: dict) -> str:
    """Deterministic content hash of a staged task snapshot (sha256, hex)."""
    canonical = json.dumps(task_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _provenance_unverified(task: CoordinatorTask) -> None:
    provenance = task.provenance
    if isinstance(provenance, dict):
        verified = provenance.get("human_verified")
    else:
        verified = getattr(provenance, "human_verified", False)
    if verified:
        raise ValueError("Verified-marked tasks never promote")


def promote(request: PromotionRequest, approval: ApprovalResult,
            connection_factory=None, registry=None) -> PromotionAudit:
    """Promote one staged row to queued after full revalidation."""
    if not isinstance(request, PromotionRequest):
        raise ValueError("Promotion needs a PromotionRequest")
    if not isinstance(approval, ApprovalResult):
        raise ValueError("Promotion needs an ApprovalResult")
    if approval.approved is not True or approval.decision != "approved":
        raise ValueError("Only an approved decision promotes")
    connect = connection_factory or connection
    with connect() as db:
        row = db.execute("SELECT * FROM tasks WHERE id=?",
                         (request.queue_id,)).fetchone()
        if row is None:
            raise ValueError("Staged task not found")
        if row["status"] != STAGED_STATUS or row["kind"] != STAGED_KIND:
            raise ValueError("Only staged rows promote, exactly once")
        try:
            payload = load(row["payload"])
        except Exception as error:
            raise ValueError("Staged payload unreadable") from error
        if not isinstance(payload, dict) or payload.get("staging_key") != request.staging_key:
            raise ValueError("Staging key does not match this row")
        try:
            task = CoordinatorTask.model_validate(payload.get("task"))
        except Exception as error:
            raise ValueError("Staged task unreadable") from error
        if task.status != "approved":
            raise ValueError("Only approved tasks promote")
        if (task.approval_reference.approved is not True
                or task.approval_reference.proposal_id != task.proposal_id
                or task.approval_reference.request_id != task.request_id):
            raise ValueError("Embedded task approval invalid")
        _provenance_unverified(task)
        if task.proposal_fingerprint != request.proposal_fingerprint:
            raise ValueError("Proposal fingerprint does not match")
        if (approval.proposal_id != task.proposal_id
                or approval.request_id != task.request_id):
            raise ValueError("Approval does not belong to this task")
        current = staged_fingerprint(payload.get("task"))
        if current != request.staged_fingerprint:
            raise ValueError("Staged content changed since approval")
        node_row = db.execute("SELECT node_id, capabilities FROM nodes WHERE node_id=?",
                              (request.selected_node_id,)).fetchone()
        if node_row is None:
            raise ValueError("Selected node unknown")
        try:
            live_caps = _normalize(load(node_row["capabilities"]))
        except Exception as error:
            raise ValueError("Node capabilities unreadable") from error
        if live_caps != _normalize(request.capability_snapshot):
            raise ValueError("Node capabilities changed since approval")
        try:
            model = ModelInfo.model_validate(request.model)
        except Exception as error:
            raise ValueError("Promotion model invalid") from error
        active_registry = registry if registry is not None else default_registry()
        intent = TaskIntent(task_id=None,
                            requirements=list(request.required_capabilities))
        node = NodeInfo(node_id=request.selected_node_id,
                        capabilities=list(live_caps))
        verdicts = match_task(intent, [model], active_registry,
                              adapter_id=request.adapter_id, node=node)
        if not any(item.compatible and item.model_id == model.model_id
                   and item.adapter_id == request.adapter_id
                   for item in verdicts):
            raise ValueError("No compatible verdict for node and model")
        required = _normalize(request.required_capabilities)
        changed = db.execute(
            "UPDATE tasks SET status=?, required_capabilities=? WHERE id=? AND status=? AND kind=?",
            (QUEUED_STATUS, dump(required), request.queue_id,
             STAGED_STATUS, STAGED_KIND)).rowcount
        if changed != 1:
            raise ValueError("Atomic promotion failed")
    return PromotionAudit(
        promotion_request_id=request.promotion_request_id,
        staging_key=request.staging_key,
        queue_id=request.queue_id,
        original_fingerprint=request.proposal_fingerprint,
        current_fingerprint=current,
        selected_node_id=request.selected_node_id,
        capability_snapshot=live_caps,
        approval=approval,
        result="queued",
        provenance=task.provenance,
    )
