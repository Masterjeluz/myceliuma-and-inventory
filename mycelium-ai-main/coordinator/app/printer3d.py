"""Printer devices + physical execution for Mycelium (BIG #7).

A printer is a Mycelium-owned device record (``printer_devices``
table) with an optional link to an INVENTory hardware twin
(``hw_`` reference only — the twin is world memory, this table
is execution authority; no duplicate device database, the link
is documented, not synchronized).

Execution position in the chain:

    G-code artifact (validated + safety-assessed)
        -> print proposal (printer.execute, inert)
        -> human exact-YES (physical approval, distinct from
           mission/plan approval)
        -> revalidation (approval binding + fingerprint +
           G-code hash + safety + adapter)
        -> execution (adapter only)
        -> PrintResult (telemetry only, never verification)
        -> observation (BIG #6) -> verification (print_verify)

Rules (tested, all fail-closed):

- Capabilities are closed (printer.status/telemetry/upload/
  start/pause/stop/cancel) and claimed per adapter; spoofing is
  filtered like every other capability surface.
- Only ``SimulatedPrinterAdapter`` (deterministic in-memory
  state machine, explicitly simulated) and
  ``UnavailablePrinterAdapter`` exist. No real transport, no
  serial, no network, no vendor SDK.
- Execution needs ALL of: bound non-stale approval, unchanged
  G-code fingerprint, a safety assessment that is not unsafe,
  an allow-listed profile, a registered adapter. Anything else
  refuses — including high VLM confidence and mission approval
  alone (mission YES never means "start the machine").
- Cancel/stop are modeled (cancelled is terminal), but a
  software cancel is documented as NOT a physical emergency
  stop: without hardware there is only the contract boundary
  (``estop_note`` on every job, docs spell the difference).
- Results carry telemetry only. Telemetry != verification:
  ``printer reports completed`` and ``camera confirms object``
  are separate verifications that must both pass.
"""

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import Provenance

PRINTER_CAPABILITIES = frozenset({
    "printer.status",
    "printer.telemetry",
    "printer.upload",
    "printer.start",
    "printer.pause",
    "printer.stop",
    "printer.cancel",
})

VALID_JOB_STATUSES = frozenset({
    "proposed", "approved", "queued", "running", "paused",
    "completed", "failed", "cancelled",
})
TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled"})

ESTOP_NOTE = ("software cancel/stop is a state transition only; "
              "it is NOT a physical emergency stop. Real e-stop "
              "needs hardware that this layer does not touch.")


class PrinterRefusedError(ValueError):
    """Local validation refused; no printer was touched."""


class PrinterUnavailable(RuntimeError):
    """No execution path. Fail-closed, never fake telemetry."""


class PrinterDevice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    printer_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    capabilities: list[str] = Field(default_factory=list,
                                    max_length=10)
    inventory_hardware_id: str = Field(default="", max_length=100)
    status: str = Field(default="registered", max_length=20)
    notes: str = Field(default="", max_length=500)
    created_at: str = ""


class PrintJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=3, max_length=80)
    printer_id: str = Field(min_length=3, max_length=80)
    gcode_ref: str = Field(min_length=1, max_length=200)
    gcode_sha256: str = Field(min_length=64, max_length=64,
                              pattern=r"^[0-9a-f]{64}$")
    profile: str = Field(min_length=1, max_length=40)
    status: str = Field(default="proposed", max_length=20)
    actor: str = Field(min_length=1, max_length=80)
    proposal_id: str = Field(default="", max_length=80)
    started_at: str = ""
    ended_at: str = ""
    error: str = Field(default="", max_length=2000)
    estop_note: str = Field(default=ESTOP_NOTE, max_length=500)
    provenance: Provenance = Field(default_factory=Provenance)


class PrintResult(BaseModel):
    """Telemetry-shaped outcome. Never verification."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=3, max_length=80)
    printer_id: str = Field(min_length=3, max_length=80)
    status: str = Field(min_length=1, max_length=20)
    gcode_sha256: str = Field(min_length=64, max_length=64,
                              pattern=r"^[0-9a-f]{64}$")
    started_at: str = ""
    ended_at: str = ""
    error: str = Field(default="", max_length=2000)
    telemetry: dict[str, Any] = Field(default_factory=dict)
    actor: str = Field(min_length=1, max_length=80)
    provenance: Provenance = Field(default_factory=Provenance)


def now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def check_capabilities(capabilities) -> list[str]:
    if not isinstance(capabilities, (list, tuple)):
        raise PrinterRefusedError("Capabilities must be a list")
    cleaned = []
    for capability in capabilities:
        if capability not in PRINTER_CAPABILITIES:
            raise PrinterRefusedError(
                f"Unknown printer capability '{capability}'; "
                f"expected one of {sorted(PRINTER_CAPABILITIES)}")
        if capability not in cleaned:
            cleaned.append(capability)
    return cleaned


def new_printer(printer_id: str, name: str, capabilities,
                inventory_hardware_id: str = "",
                notes: str = "") -> PrinterDevice:
    if not isinstance(printer_id, str) or not printer_id.strip():
        raise PrinterRefusedError("printer_id must be non-empty text")
    if not printer_id.startswith("prt-"):
        raise PrinterRefusedError(
            "printer_id must use the 'prt-' prefix")
    if not isinstance(name, str) or not name.strip():
        raise PrinterRefusedError("Printer name must be non-empty text")
    twin = str(inventory_hardware_id or "").strip()
    if twin and not twin.startswith("hw_"):
        raise PrinterRefusedError(
            "inventory_hardware_id must be an 'hw_' reference")
    return PrinterDevice(
        printer_id=printer_id.strip(),
        name=name.strip()[:120],
        capabilities=check_capabilities(capabilities or []),
        inventory_hardware_id=twin,
        notes=str(notes or "")[:500],
        created_at=now())


def new_job(job_id: str, printer_id: str, gcode_ref: str,
            gcode_sha256: str, profile: str, actor: str,
            proposal_id: str = "") -> PrintJob:
    from .mesh3d import check_artifact_ref
    try:
        reference = check_artifact_ref(gcode_ref)
    except ValueError as error:
        raise PrinterRefusedError(str(error)) from error
    if not reference.lower().endswith(".gcode"):
        raise PrinterRefusedError("Print jobs need a .gcode artifact")
    if (not isinstance(gcode_sha256, str) or len(gcode_sha256) != 64
            or any(c not in "0123456789abcdef"
                   for c in gcode_sha256.lower())):
        raise PrinterRefusedError("gcode_sha256 must be sha256 hex")
    if not isinstance(actor, str) or not actor.strip():
        raise PrinterRefusedError("actor must be non-empty text")
    return PrintJob(
        job_id=job_id, printer_id=printer_id,
        gcode_ref=reference, gcode_sha256=gcode_sha256.lower(),
        profile=profile, actor=actor.strip(),
        proposal_id=proposal_id,
        provenance=Provenance(
            source_type="ai-generated",
            creator_id=actor.strip(), human_verified=False,
            notes="print job; telemetry only until observation "
                  "and independent verification"))


# -- adapters ---------------------------------------------------------------

class PrinterAdapter:
    """Execution contract. Production transports arrive per
    reviewed runtime; the core ships none."""

    name = "base"
    capabilities: list[str] = []

    def status(self, device: PrinterDevice) -> dict:
        raise NotImplementedError

    def execute(self, device: PrinterDevice,
                job: PrintJob) -> PrintResult:
        raise NotImplementedError

    def cancel(self, device: PrinterDevice,
               job: PrintJob) -> PrintJob:
        raise NotImplementedError


class UnavailablePrinterAdapter(PrinterAdapter):
    """Explicit unavailable printer. Complete interface, zero motion."""

    name = "unavailable"

    def __init__(self, reason: str = "no printer transport available"):
        self.reason = reason
        self.capabilities = []

    def status(self, device: PrinterDevice) -> dict:
        raise PrinterUnavailable(
            f"{self.reason}; no fake telemetry, no motion")

    def execute(self, device: PrinterDevice,
                job: PrintJob) -> PrintResult:
        raise PrinterUnavailable(
            f"{self.reason}; refusing instead of moving hardware")

    def cancel(self, device: PrinterDevice,
               job: PrintJob) -> PrintJob:
        raise PrinterUnavailable(self.reason)

    @classmethod
    def requirements(cls) -> str:
        return ("A production printer needs a reviewed local "
                "transport (USB/serial or LAN with pinned host, "
                "fixed command allow-list, bounded timeouts, "
                "telemetry polling, explicit e-stop wiring). None of "
                "this ships in BIG #7.")


class SimulatedPrinterAdapter(PrinterAdapter):
    """Deterministic TEST execution. In-memory state machine only:
    queued -> running -> completed, cancellable before/during.
    Explicitly simulated — telemetry is scripted, never sensed."""

    name = "simulated-test"
    capabilities = ["printer.status", "printer.telemetry",
                    "printer.upload", "printer.start",
                    "printer.stop", "printer.cancel"]

    def __init__(self, fail: bool = False):
        self._fail = fail
        self._cancelled: set[str] = set()

    def status(self, device: PrinterDevice) -> dict:
        return {"printer_id": device.printer_id,
                "state": "idle", "simulated": True,
                "nozzle_c": 24.0, "bed_c": 22.0}

    def request_cancel(self, job_id: str) -> None:
        self._cancelled.add(job_id)

    def execute(self, device: PrinterDevice,
                job: PrintJob) -> PrintResult:
        if job.job_id in self._cancelled:
            return _result(device, job, "cancelled",
                           error="cancelled before start (simulated)")
        if self._fail:
            return _result(device, job, "failed",
                           error="simulated failure (test)")
        return _result(device, job, "completed")

    def cancel(self, device: PrinterDevice,
               job: PrintJob) -> PrintJob:
        self._cancelled.add(job.job_id)
        if job.status in TERMINAL_JOB_STATUSES:
            return job
        return job.model_copy(update={"status": "cancelled",
                                      "ended_at": now(),
                                      "error": "cancelled by operator "
                                               "(simulated; " + ESTOP_NOTE
                                               + ")"})


def _result(device: PrinterDevice, job: PrintJob, status: str,
            error: str = "") -> PrintResult:
    return PrintResult(
        job_id=job.job_id, printer_id=device.printer_id,
        status=status, gcode_sha256=job.gcode_sha256,
        started_at=job.started_at or now(), ended_at=now(),
        error=error[:2000],
        telemetry={"simulated": True, "state": status,
                   "progress": 1.0 if status == "completed" else 0.0,
                   "nozzle_c": 24.0, "bed_c": 22.0},
        actor=job.actor,
        provenance=Provenance(
            source_type="sensor-observed",
            creator_id=f"printer:{device.printer_id}",
            human_verified=False,
            notes="simulated telemetry; not physical verification"))


def adapter_capabilities(adapter: PrinterAdapter) -> list[str]:
    claimed = list(getattr(adapter, "capabilities", []) or [])
    return [cap for cap in claimed if cap in PRINTER_CAPABILITIES]


# -- registry (empty in production: fail-closed) ------------------------------

_PRINTERS: dict[str, PrinterDevice] = {}
_PRINTER_ADAPTERS: dict[str, PrinterAdapter] = {}


def register_printer(device: PrinterDevice,
                     adapter: PrinterAdapter | None = None) -> None:
    if not isinstance(device, PrinterDevice):
        raise PrinterRefusedError("Only PrinterDevice entries register")
    if adapter is not None and not isinstance(adapter,
                                              PrinterAdapter):
        raise PrinterRefusedError("Unknown adapter type")
    _PRINTERS[device.printer_id] = device
    if adapter is not None:
        _PRINTER_ADAPTERS[device.printer_id] = adapter


def unregister_printer(printer_id: str) -> None:
    _PRINTERS.pop(printer_id, None)
    _PRINTER_ADAPTERS.pop(printer_id, None)


def get_printer(printer_id: str) -> PrinterDevice | None:
    return _PRINTERS.get(printer_id)


def adapter_for_printer(printer_id: str) -> PrinterAdapter | None:
    return _PRINTER_ADAPTERS.get(printer_id)


def list_printers() -> list[PrinterDevice]:
    return list(_PRINTERS.values())


def clear_printers() -> None:
    _PRINTERS.clear()
    _PRINTER_ADAPTERS.clear()


# -- persistent device twin (chat/agent database) ------------------------------

def save_printer(device: PrinterDevice) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO printer_devices
        (printer_id, record, created_at) VALUES (?, ?, ?)
        ON CONFLICT(printer_id) DO UPDATE SET record=excluded.record""",
                    (device.printer_id,
                     dump(device.model_dump(mode="json")),
                     device.created_at or now()))


def load_printer(printer_id: str) -> PrinterDevice | None:
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT record FROM printer_devices "
                         "WHERE printer_id=?", (printer_id,)).fetchone()
    if row is None:
        return None
    return PrinterDevice.model_validate(load(row["record"]))


def list_stored_printers() -> list[PrinterDevice]:
    from .database import chat_connection, init_chat_database, load
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute(
            "SELECT record FROM printer_devices ORDER BY created_at"
        ).fetchall()
    return [PrinterDevice.model_validate(load(row["record"]))
            for row in rows]
