"""Fabrication flow for Mycelium (BIG #7).

Owns the digital-to-physical chain as data, never as motion:

    source object/idea
        -> generation record (mesh bytes, local only)
        -> validation record (valid/invalid/inconclusive)
        -> File proposal (BIG #5, mesh registration)
        -> slice record (G-code bytes, local only)
        -> safety record (safe/unsafe/inconclusive)
        -> File proposal (BIG #5, G-code registration)
        -> print proposal (printer.execute, inert)
        -> human exact-YES (PHYSICAL approval)
        -> execution (adapter only, revalidated)
        -> PrintResult (telemetry only)
        -> observation (BIG #6) + verification (both halves)

Rules (tested, all fail-closed):

- This module proposes and verifies; motion happens only in
  ``execute_print`` and only after full revalidation. A plan or
  mission YES never authorizes motion — the printer.execute
  approval is a second, explicit, fingerprint-bound YES.
- Execution additionally requires: unchanged G-code (sha256
  match against the proposal), a recorded safety assessment
  that is not ``unsafe``, an allow-listed profile, a registered
  adapter with the ``printer.start`` capability.
- Results are telemetry. Verification needs two independent
  halves: telemetry readback (job completed + fingerprint) AND
  camera readback (observation confirms the object). Either
  half failing means NOT verified.
- Every step appends to the FabricationRecord links/history so
  the full chain stays traceable end to end.
"""

import secrets
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .controlled_writes import (
    WriteApproval,
    WriteProposal,
    WriteResult,
    now,
    propose_write,
    revalidate,
)
from .inventory_read import Provenance
from .printer3d import (
    PrinterAdapter,
    PrinterDevice,
    PrinterRefusedError,
    PrinterUnavailable,
    PrintJob,
    PrintResult,
    adapter_capabilities,
    ams_slot_loaded,
    new_job,
)
from .slicer3d import SlicerRefusedError
from .verification import (
    VerificationRequest,
    VerificationResult,
    generate_verification_id,
    new_verification_request,
)

PHYSICAL_CAPABILITY = "printer.execute"


class FabricationRecord(BaseModel):
    """Traceable chain for one digital-to-physical run. Data only."""

    model_config = ConfigDict(extra="forbid")

    fabrication_id: str = Field(min_length=3, max_length=80)
    source_object_id: str = Field(default="", max_length=100)
    source_idea_id: str = Field(default="", max_length=100)
    mesh_ref: str = Field(default="", max_length=200)
    mesh_sha256: str = Field(default="", max_length=64)
    mesh_validation: str = Field(default="", max_length=20)
    mesh_file_id: str = Field(default="", max_length=100)
    gcode_ref: str = Field(default="", max_length=200)
    gcode_sha256: str = Field(default="", max_length=64)
    gcode_safety: str = Field(default="", max_length=20)
    gcode_file_id: str = Field(default="", max_length=100)
    job_id: str = Field(default="", max_length=80)
    observation_id: str = Field(default="", max_length=80)
    status: str = Field(default="started", max_length=40)
    history: list[dict[str, Any]] = Field(default_factory=list,
                                          max_length=60)
    created_at: str = ""


class PrintRefusedError(ValueError):
    """Local validation refused; nothing moved."""


class PrintFailedError(RuntimeError):
    """Execution failed; nothing is verified."""


def generate_fabrication_id() -> str:
    return f"fab_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def new_fabrication(source_object_id: str = "",
                    source_idea_id: str = "") -> FabricationRecord:
    """Start one fabrication chain. Sources are optional at start
    (a bare description may precede the object link) but when
    given they must be proper INVENTory references."""
    for label, value, prefix in (
            ("source_object_id", source_object_id, "obj_"),
            ("source_idea_id", source_idea_id, "idea_")):
        if value and not value.startswith(prefix):
            raise PrintRefusedError(
                f"{label} must be a '{prefix}' reference")
    return FabricationRecord(
        fabrication_id=generate_fabrication_id(),
        source_object_id=source_object_id,
        source_idea_id=source_idea_id,
        created_at=now())


def record_event(record: FabricationRecord, stage: str,
                 detail: str) -> FabricationRecord:
    history = list(record.history) + [{
        "stage": stage, "detail": str(detail)[:500],
        "at": now()}]
    return record.model_copy(update={"history": history[-60:]})


def propose_print(proposal_id: str, job: PrintJob, *,
                  safety_verdict: str,
                  actor: str) -> WriteProposal:
    """One inert printer.execute proposal = the PHYSICAL approval.

    Refuses unless a safety assessment exists and is not unsafe.
    A safety ``safe`` still authorizes nothing by itself — only
    the human YES on this proposal does, and only for the exact
    G-code fingerprint bound here.
    """
    if safety_verdict not in ("safe", "inconclusive"):
        raise PrintRefusedError(
            f"Safety verdict '{safety_verdict}' never becomes a "
            "print proposal")
    if not isinstance(actor, str) or not actor.strip():
        raise PrintRefusedError("actor must be non-empty text")
    payload = {
        "job_id": job.job_id,
        "printer_id": job.printer_id,
        "gcode_ref": job.gcode_ref,
        "gcode_sha256": job.gcode_sha256,
        "profile": job.profile,
        "safety_verdict": safety_verdict,
        "spool_id": str(getattr(job, "spool_id", "") or "")[:80],
        "slot": str(getattr(job, "slot", "") or "")[:12],
    }
    return propose_write(
        proposal_id, "printer.execute",
        f"printer:{job.printer_id}:{job.job_id}", payload,
        actor=actor.strip())


def execute_print(proposal: WriteProposal, approval: WriteApproval, *,
                  device: PrinterDevice,
                  adapter: PrinterAdapter | None,
                  safety_verdict: str,
                  now_str: str | None = None) -> WriteResult:
    """Execute one approved print proposal. Revalidates everything
    first: approval binding, staleness, G-code fingerprint is not
    re-checkable here (bytes live in the fabrication dir — the
    caller passes the recorded hash, and execution re-hashes the
    file before motion), safety, profile, adapter capability."""
    from .mesh3d import read_artifact_bytes
    from .slicer3d import check_profile
    fingerprint = revalidate(proposal, approval,
                             now_str or now())
    if proposal.mutation_type != "printer.execute":
        raise PrintRefusedError(
            f"Mutation '{proposal.mutation_type}' is not a print")
    if adapter is None:
        return _blocked(proposal, fingerprint,
                        "no printer adapter registered; refusing")
    if not isinstance(adapter, PrinterAdapter):
        return _blocked(proposal, fingerprint,
                        "unknown adapter type; refusing")
    if "printer.start" not in adapter_capabilities(adapter):
        return _blocked(proposal, fingerprint,
                        "adapter lacks printer.start; refusing")
    if not getattr(adapter, "is_connected", True):
        connector = getattr(adapter, "_connect_mqtt", None)
        waiter = getattr(adapter, "wait_for_push", None)
        if not callable(connector) or not callable(waiter):
            return _blocked(proposal, fingerprint,
                            "adapter is offline with no session "
                            "path; refusing")
        try:
            connector()
            alive = waiter(timeout=20.0)
        except PrinterUnavailable as error:
            return _failed(proposal, fingerprint,
                           f"printer offline ({error}); refusing")
        if not alive:
            try:
                adapter.disconnect()
            except Exception:
                pass
            return _failed(proposal, fingerprint,
                           "printer silent within budget; refusing")
    try:
        check_profile(proposal.payload.get("profile", ""))
    except (SlicerRefusedError, ValueError) as error:
        return _blocked(proposal, fingerprint, str(error))
    if safety_verdict not in ("safe", "inconclusive"):
        return _blocked(proposal, fingerprint,
                        f"safety verdict '{safety_verdict}' blocks "
                        "execution")
    payload = proposal.payload
    try:
        current = read_artifact_bytes(payload.get("gcode_ref", ""))
    except ValueError as error:
        return _blocked(proposal, fingerprint,
                        f"G-code unreadable: {error}")
    import hashlib
    if hashlib.sha256(current).hexdigest() != payload.get(
            "gcode_sha256", ""):
        return _blocked(proposal, fingerprint,
                        "G-code changed since approval "
                        "(fingerprint mismatch); refusing")
    slot_label = str(payload.get("slot", "") or "")
    if slot_label:
        reader = getattr(adapter, "_live_status", None)
        if not callable(reader):
            return _failed(proposal, fingerprint,
                           "adapter reports no tray state; "
                           "refusing")
        tray = None
        try:
            # The first push after connect is often partial (no
            # AMS node yet); wait boundedly for tray data instead
            # of judging one possibly incomplete push.
            waiter = getattr(adapter, "wait_for_push", None)
            for _ in range(6):
                live_now = reader()
                tray = ams_slot_loaded(live_now, slot_label)
                if tray is not None:
                    break
                if not callable(waiter) or not waiter(timeout=5.0):
                    break
        except Exception as error:
            return _failed(proposal, fingerprint,
                           f"telemetry unreadable ({error}); "
                           f"refusing")
        if tray is not True:
            reason = (f"slot '{slot_label[:12]}' is not loaded; "
                      f"load filament first"
                      if tray is False else
                      "tray state unknown; verify physically "
                      "and retry")
            return _failed(proposal, fingerprint, reason)
    job = new_job(
        payload.get("job_id", ""), payload.get("printer_id", ""),
        payload.get("gcode_ref", ""),
        payload.get("gcode_sha256", ""),
        payload.get("profile", ""), proposal.actor,
        proposal_id=proposal.proposal_id,
        spool_id=str(payload.get("spool_id", "") or ""),
        slot=str(payload.get("slot", "") or ""))
    running = job.model_copy(update={"status": "running",
                                     "started_at": now()})
    try:
        result = adapter.execute(device, running)
    except PrinterUnavailable as error:
        return _failed(proposal, fingerprint, str(error))
    if result.status == "completed":
        outcome: str = "executed"
        started_note = ""
    elif result.status == "cancelled":
        outcome = "blocked"
        started_note = ""
    elif result.status == "running":
        outcome = "executed"
        started_note = ("print STARTED (not completed); completion "
                        "is observed separately via telemetry, "
                        "never implied")
    else:
        return _failed(proposal, fingerprint,
                       result.error or "printer reported "
                       f"{result.status}")
    return WriteResult(
        proposal_id=proposal.proposal_id, fingerprint=fingerprint,
        outcome=outcome,  # type: ignore[arg-type]
        before={"job": running.model_dump(mode="json")},
        after={"print_result": result.model_dump(mode="json"),
               "started_note": started_note},
        actor=proposal.actor, executed_at=now(),
        provenance=Provenance(
            source_type="sensor-observed",
            creator_id=f"printer:{device.printer_id}",
            human_verified=False,
            notes="printer telemetry only; not physical "
                  "verification"))


def _blocked(proposal: WriteProposal, fingerprint: str,
             error: str) -> WriteResult:
    return WriteResult(
        proposal_id=proposal.proposal_id, fingerprint=fingerprint,
        outcome="blocked", before={}, after={},
        actor=proposal.actor, executed_at=now(),
        error=error[:2000],
        provenance=Provenance(
            source_type="ai-generated", creator_id=proposal.actor,
            human_verified=False,
            notes="print blocked before motion; nothing is verified"))


def _failed(proposal: WriteProposal, fingerprint: str,
            error: str) -> WriteResult:
    return WriteResult(
        proposal_id=proposal.proposal_id, fingerprint=fingerprint,
        outcome="failed", before={}, after={},
        actor=proposal.actor, executed_at=now(),
        error=error[:2000],
        provenance=Provenance(
            source_type="sensor-observed",
            creator_id=proposal.actor, human_verified=False,
            notes="print failed; nothing is verified"))


def verify_print_telemetry(request: VerificationRequest,
                           result: WriteResult) -> VerificationResult:
    """Half 1: the recorded telemetry says completed for the exact
    bound G-code. Telemetry alone never verifies the object."""
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).isoformat()
    base = _verify_base(request, "print.telemetry_readback", stamp)
    if result.outcome != "executed":
        return VerificationResult(
            **base, outcome="failed",
            observed={"execution_outcome": result.outcome},
            source="write-result", verified_at=stamp,
            note="execution did not succeed; nothing to verify")
    if request.result_fingerprint != result.fingerprint:
        raise ValueError("Verification binds to a different result")
    telemetry = result.after.get("print_result", {})
    expected_sha = str(request.expected.get("gcode_sha256", ""))
    if expected_sha and telemetry.get("gcode_sha256") != expected_sha:
        return VerificationResult(
            **base, outcome="failed", observed=telemetry,
            source="print-telemetry", verified_at=stamp,
            note="telemetry G-code hash differs; NOT verified")
    if telemetry.get("status") != "completed":
        return VerificationResult(
            **base, outcome="failed", observed=telemetry,
            source="print-telemetry", verified_at=stamp,
            note="telemetry does not report completion; NOT verified")
    return VerificationResult(
        **base, outcome="passed", observed=telemetry,
        source="print-telemetry", verified_at=stamp,
        note="telemetry reports completion for the bound G-code; "
             "physical object still needs camera confirmation")


def verify_print_camera(request: VerificationRequest,
                        observation) -> VerificationResult:
    """Half 2: a camera observation confirms the printed object.
    Reuses the BIG #6 observation check; pictured identity stays
    unconfirmed beyond presence."""
    from .vision_flow import verify_observation
    expected = dict(request.expected)
    adapted = VerificationRequest(
        verification_id=request.verification_id,
        proposal_id=request.proposal_id,
        result_fingerprint=request.result_fingerprint,
        method="camera.readback",
        expected={"kind": "observation",
                  "observation_id": expected.get("observation_id",
                                                 ""),
                  "device_id": expected.get("device_id", ""),
                  "media_ref": expected.get("media_ref", "")})
    verification = verify_observation(
        adapted, observation,
        media_exists=bool(expected.get("media_exists", True)))
    return verification.model_copy(update={
        "method": "print.camera_readback"})


def print_verdict(telemetry, camera) -> str:
    """Final print verdict: verified only if BOTH halves passed."""
    from .verification import is_verified
    if is_verified(telemetry) and is_verified(camera):
        return "verified"
    return "not_verified"


def new_telemetry_request(proposal_id: str,
                          result_fingerprint: str,
                          gcode_sha256: str) -> VerificationRequest:
    return new_verification_request(
        proposal_id, result_fingerprint, "print.telemetry_readback",
        {"kind": "print", "gcode_sha256": gcode_sha256})


def _verify_base(request: VerificationRequest, method: str,
                 stamp: str) -> dict:
    return {
        "verification_id": request.verification_id,
        "proposal_id": request.proposal_id,
        "result_fingerprint": request.result_fingerprint,
        "method": method,
        "expected": dict(request.expected),
        "observer": "mycelium-verifier",
        "provenance": Provenance(
            source_type="sensor-observed",
            creator_id="mycelium-verifier", human_verified=False,
            notes="independent print verification read"),
    }


# -- store (chat/agent database; world data stays in INVENTory) -----------

def save_fabrication(record: FabricationRecord) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO fabrications
        (fabrication_id, record, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(fabrication_id) DO UPDATE SET
        record=excluded.record, status=excluded.status,
        updated_at=excluded.updated_at""",
                    (record.fabrication_id,
                     dump(record.model_dump(mode="json")),
                     record.status, record.created_at, now()))


def load_fabrication(fabrication_id: str) -> FabricationRecord | None:
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT record FROM fabrications "
                         "WHERE fabrication_id=?",
                         (fabrication_id,)).fetchone()
    if row is None:
        return None
    return FabricationRecord.model_validate(load(row["record"]))


def list_fabrications(limit: int = 20) -> list[FabricationRecord]:
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute(
            """SELECT record FROM fabrications ORDER BY created_at
            DESC LIMIT ?""",
            (max(1, min(limit, 50)),)).fetchall()
    return [FabricationRecord.model_validate(load(row["record"]))
            for row in rows]
