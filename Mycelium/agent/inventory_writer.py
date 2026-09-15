"""Approval-gated writer: desktop mapping -> INVENTory project (M2B).

This module is the ONLY place that may create INVENTory projects, and it does
so only when every gate passes, in this order:

1. identifiers present, desktop path exists and is a directory;
2. idempotency: a ``mapped`` row in the store short-circuits with 0 writes;
3. eligibility: only ``proposed`` / ``nested`` bridge mappings are writable.
   ``copy`` / ``conflict`` / ``unmapped`` / ``rejected`` / ``mapped`` are
   refused — a human must reclassify them first, never the code;
4. canonical workspace: the desktop path must sit inside an explicitly passed
   ``allowed_roots`` list. Empty or missing ``allowed_roots`` refuses everything;
5. payload validation against the existing ``ProjectCreate`` contract
   (``POST /api/v1/projects``): create-only shape, no ``id`` field,
   ``provenance.source_type == "imported"``, ``human_verified is False``;
6. explicit approval: a decision dict with ``approved is True`` whose
   ``action``/``target`` match this exact import. Anything else refuses.
   Interactive callers obtain it via :func:`request_approval_and_write`,
   which uses ``permissions.request_permission`` (exact-YES gate);
7. git checkpoint: for git projects ``checkpoint.create_checkpoint`` must
   succeed BEFORE any write, with its own matching checkpoint approval;
8. exactly one ``create_project`` call on the injected inventory client;
9. the returned ``proj_`` ID is validated and stored via ``mark_mapped``.

Any violation raises :class:`WriteRefusedError` and performs zero writes.
Only CREATE operations exist here: no update, no delete, no overwrite path.
Relationship writes are NOT implemented (no safe contract yet — M2B scope).
"""

import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from checkpoint import CHECKPOINT_ACTION, create_checkpoint
from permissions import request_permission

IMPORT_ACTION = "import_project_to_inventory"
IMPORT_COMPONENT = "inventory_writer"
IMPORT_SOURCE = "mycelium-desktop-agent:inventory-writer"
IMPORT_VERSION = "1.0.0"

# Writable bridge statuses: clean proposal or distinguishable nested project.
WRITABLE_STATUSES = {"proposed", "nested"}

# Mirrors INVENTory ProjectCreate: name 1..200, description <=5000,
# status one of the ProjectStatus literals. Verified against
# inventory/app/schemas.py (M1B contract); nothing invented.
PROJECT_STATUSES = {"idea", "planned", "active", "paused", "completed", "archived"}
INVENTORY_PROJECTS_PATH = "/api/v1/projects"


class WriteRefusedError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _approval_matches(approval, action, target) -> bool:
    return (
        isinstance(approval, dict)
        and approval.get("approved") is True
        and approval.get("action") == action
        and str(approval.get("target") or "").strip() == str(target).strip()
    )


def _within_roots(desktop_path: Path, allowed_roots) -> bool:
    if not allowed_roots:
        return False
    candidate = os.path.normcase(str(desktop_path))
    for root in allowed_roots:
        try:
            resolved = Path(root).resolve()
        except (OSError, ValueError):
            continue
        if not resolved.exists():
            continue
        prefix = os.path.normcase(str(resolved))
        if candidate == prefix or candidate.startswith(prefix + os.sep):
            return True
    return False


def validate_project_payload(payload) -> dict:
    """Validate a create-only payload against the ProjectCreate contract."""
    if not isinstance(payload, dict):
        raise WriteRefusedError("Project payload must be an object")
    if "id" in payload:
        raise WriteRefusedError("Payload must not carry an ID; proj_ IDs are server-assigned")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise WriteRefusedError("Payload name must be 1..200 characters")
    description = payload.get("description", "")
    if not isinstance(description, str) or len(description) > 5000:
        raise WriteRefusedError("Payload description must be at most 5000 characters")
    if payload.get("status") not in PROJECT_STATUSES:
        raise WriteRefusedError("Payload status is not a known INVENTory project status")
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        raise WriteRefusedError("Payload requires a provenance object")
    if provenance.get("source_type") != "imported":
        raise WriteRefusedError("Payload provenance.source_type must be 'imported'")
    if provenance.get("human_verified") is not False:
        raise WriteRefusedError("Payload provenance.human_verified must be false")
    return payload


class HttpInventoryClient:
    """Thin adapter over the existing INVENTory REST API (create-only)."""

    def __init__(self, base_url, timeout=15):
        self.base_url = str(base_url).rstrip("/")
        self.timeout = timeout

    def create_project(self, payload) -> dict:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + INVENTORY_PROJECTS_PATH,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            raise WriteRefusedError(f"INVENTory create failed: {error}") from error
        if not isinstance(data, dict) or not str(data.get("id") or "").startswith("proj_"):
            raise WriteRefusedError("INVENTory did not return a proj_ ID")
        return data


def _writer_provenance(desktop_id, stamp) -> dict:
    return {
        "source": IMPORT_SOURCE,
        "component": IMPORT_COMPONENT,
        "version": IMPORT_VERSION,
        "mode": "approval-gated-create",
        "desktop_project_id": desktop_id,
        "created_at": stamp,
    }


def write_approved_mapping(*, desktop_id, desktop_path, is_git, payload,
                           mapping_status, approval, checkpoint_approval=None,
                           inventory_client, store=None, allowed_roots=(),
                           checkpoint_func=None, now=None) -> dict:
    """Create exactly one INVENTory project after all gates pass.

    Returns a result record with ``writes == 1``. Raises
    :class:`WriteRefusedError` (0 writes) on any violation, including an
    already-``mapped`` row, which short-circuits as ``already_mapped``.
    """
    stamp = (now or _utc_now)()
    desktop_id = str(desktop_id or "").strip()
    if not desktop_id:
        raise WriteRefusedError("Missing desktop stable_id")
    try:
        resolved_path = Path(desktop_path).resolve()
    except (OSError, ValueError, TypeError) as error:
        raise WriteRefusedError(f"Unresolvable desktop path: {error}") from error
    if not resolved_path.exists() or not resolved_path.is_dir():
        raise WriteRefusedError(f"Desktop path is not an existing directory: {resolved_path}")

    if store is not None:
        existing = store.get(desktop_id)
        if isinstance(existing, dict) and existing.get("mapping_status") == "mapped":
            return {
                "desktop_project_id": desktop_id,
                "inventory_project_id": existing.get("inventory_project_id"),
                "mapping_status": "already_mapped",
                "checkpoint_id": None,
                "writes": 0,
                "provenance": _writer_provenance(desktop_id, stamp),
                "created_at": stamp,
            }

    if mapping_status not in WRITABLE_STATUSES:
        raise WriteRefusedError(
            f"Mapping status {mapping_status!r} is not writable; "
            "a human must reclassify it to proposed/nested first"
        )
    if not _within_roots(resolved_path, allowed_roots):
        raise WriteRefusedError(
            f"Desktop path {resolved_path} is outside the canonical workspace"
        )
    validate_project_payload(payload)
    if not _approval_matches(approval, IMPORT_ACTION, str(desktop_path).strip()):
        raise WriteRefusedError("Missing or denied import approval: no write")

    checkpoint_id = None
    if is_git:
        target = str(resolved_path)
        if not _approval_matches(checkpoint_approval, CHECKPOINT_ACTION, target):
            raise WriteRefusedError("Git project requires a matching checkpoint approval")
        run_checkpoint = checkpoint_func or create_checkpoint
        try:
            checkpoint_result = run_checkpoint(
                resolved_path, checkpoint_approval,
                message=f"Mycelium pre-import checkpoint for {desktop_id}",
            )
        except Exception as error:
            raise WriteRefusedError(f"Checkpoint failed, refusing write: {error}") from error
        checkpoint_id = checkpoint_result.get("checkpoint_id")
        if not checkpoint_id:
            raise WriteRefusedError("Checkpoint did not return a checkpoint ID")

    if inventory_client is None:
        raise WriteRefusedError("No inventory client supplied")
    created = inventory_client.create_project(payload)
    inventory_id = created.get("id") if isinstance(created, dict) else None
    if not isinstance(inventory_id, str) or not inventory_id.startswith("proj_"):
        raise WriteRefusedError("INVENTory did not return a proj_ ID; mapping not stored")

    if store is not None:
        store.mark_mapped(desktop_id, str(desktop_path), inventory_id, approval,
                          provenance=_writer_provenance(desktop_id, stamp))
    return {
        "desktop_project_id": desktop_id,
        "inventory_project_id": inventory_id,
        "mapping_status": "mapped",
        "checkpoint_id": checkpoint_id,
        "writes": 1,
        "provenance": _writer_provenance(desktop_id, stamp),
        "created_at": stamp,
    }


def request_approval_and_write(*, desktop_id, desktop_path, is_git, payload,
                               mapping_status, inventory_client, store=None,
                               allowed_roots=(), checkpoint_func=None,
                               permission_func=None, input_func=None,
                               log_path=None, now=None) -> dict:
    """Obtain explicit human approvals, then delegate to :func:`write_approved_mapping`.

    Uses ``permissions.request_permission`` unless another ``permission_func``
    is injected (tests). Without an ``input_func`` the gate default-denies,
    so unattended calls always refuse with 0 writes.
    """
    ask = permission_func or request_permission
    checkpoint_approval = None
    if is_git:
        try:
            target = str(Path(desktop_path).resolve())
        except (OSError, ValueError, TypeError):
            target = str(desktop_path)
        checkpoint_approval = ask(
            CHECKPOINT_ACTION,
            target,
            {"reason": f"Create a local Git checkpoint before importing {desktop_id}."},
            input_func=input_func,
            log_path=log_path,
        )
    approval = ask(
        IMPORT_ACTION,
        desktop_path,
        {"reason": f"Create INVENTory project for desktop {desktop_id} ({desktop_path}).",
         "payload": {"name": payload.get("name") if isinstance(payload, dict) else None}},
        input_func=input_func,
        log_path=log_path,
    )
    return write_approved_mapping(
        desktop_id=desktop_id,
        desktop_path=desktop_path,
        is_git=is_git,
        payload=payload,
        mapping_status=mapping_status,
        approval=approval,
        checkpoint_approval=checkpoint_approval,
        inventory_client=inventory_client,
        store=store,
        allowed_roots=allowed_roots,
        checkpoint_func=checkpoint_func,
        now=now,
    )
