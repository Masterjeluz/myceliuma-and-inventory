"""Staging bridge: approved CoordinatorTask as data in the coordinator queue.

Read the safety boundary carefully:

- This module REGISTERS task data. It never hands work to nodes, never
  marks anything assigned, never starts an executor and never completes
  anything.
- Staged rows use status ``staged``. The existing claim path selects only
  ``status='queued'`` and transitions atomically from ``queued`` to
  ``assigned``; the complete path only accepts ``assigned``. A staged row
  is therefore unreachable for node hand-off and completion under the
  current queue semantics. A regression test pins this property: if the
  claim path ever returns a staged row, the suite fails.
- Identity is deterministic (proposal_id + request_id + fingerprint);
  re-staging the same approved task returns the existing row.
- The single source of truth is the CoordinatorTask object produced by
  M6.4. Nothing is looked up again, re-decided or re-approved here.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from .database import connection, dump, load
from .proposal_tasks import CoordinatorTask

STAGED_STATUS = "staged"
STAGED_KIND = "staged-proposal"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def staging_key_for(task: CoordinatorTask) -> str:
    """Deterministic identity of a staging: proposal + request + fingerprint."""
    return (f"{task.proposal_id}:{task.request_id}:"
            f"{task.proposal_fingerprint}")


class StagedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue_id: int
    staging_key: str = Field(min_length=1, max_length=300)
    status: str = Field(default=STAGED_STATUS)
    task: CoordinatorTask


def _validate(task: CoordinatorTask) -> None:
    if not isinstance(task, CoordinatorTask):
        raise ValueError("Staging needs a CoordinatorTask")
    if task.status != "approved":
        raise ValueError("Only approved tasks can be staged")
    approval = task.approval_reference
    if approval.approved is not True:
        raise ValueError("Only approved proposals stage to tasks")
    if (approval.proposal_id != task.proposal_id
            or approval.request_id != task.request_id):
        raise ValueError("Approval does not belong to this task")
    fingerprint = task.proposal_fingerprint
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ValueError("Task carries no valid proposal fingerprint")
    provenance = task.provenance
    verified = (provenance.get("human_verified")
                if isinstance(provenance, dict)
                else getattr(provenance, "human_verified", False))
    if verified:
        raise ValueError("Verified-marked tasks never stage")


def _find_staged(db, staging_key: str):
    rows = db.execute(
        "SELECT id, payload FROM tasks WHERE status=?", (STAGED_STATUS,)).fetchall()
    for row in rows:
        try:
            payload = load(row["payload"])
        except Exception:
            continue
        if isinstance(payload, dict) and payload.get("staging_key") == staging_key:
            return row["id"], payload
    return None, None


def stage_task(task: CoordinatorTask, connection_factory=None) -> StagedTask:
    """Register an approved task as non-dispatchable staged data.

    Idempotent: staging the same approved task twice returns the same
    staged record without inserting a second row.
    """
    _validate(task)
    key = staging_key_for(task)
    connect = connection_factory or connection
    with connect() as db:
        existing_id, existing_payload = _find_staged(db, key)
        if existing_id is not None:
            stored = existing_payload.get("task") or {}
            return StagedTask(queue_id=existing_id, staging_key=key,
                              status=STAGED_STATUS,
                              task=CoordinatorTask.model_validate(stored))
        payload = {"staging_key": key, "kind": STAGED_KIND,
                   "task": task.model_dump(mode="json")}
        cursor = db.execute(
            """INSERT INTO tasks (kind,payload,required_capabilities,preferred_tier,priority,status,created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (STAGED_KIND, dump(payload), dump([]), None, 0,
             STAGED_STATUS, _utc_now()))
        return StagedTask(queue_id=cursor.lastrowid, staging_key=key,
                          status=STAGED_STATUS, task=task)
