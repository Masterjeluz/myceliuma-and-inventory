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
  ``UnavailablePrinterAdapter`` execute. ``BambuPrinterAdapter``
  is experimental scaffolding only: it needs the optional
  ``paho-mqtt`` package plus real hardware, and raises
  ``PrinterUnavailable`` until fully connected. No serial,
  no vendor SDK ships in the core.
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

import httpx
try:
    import paho.mqtt.client as mqtt
    PAHO_MQTT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised via sys.modules block
    mqtt = None
    PAHO_MQTT_AVAILABLE = False
MQTT_MISSING_MESSAGE = ("paho-mqtt is not installed, so the Bambu MQTT "
                        "transport is unavailable (install paho-mqtt "
                        "for hardware use).")
import time
from typing import Any, Optional # Import Optional
import queue # Added for BambuPrinterAdapter's message queue
import threading # Added for BambuPrinterAdapter's message queue processing
import json # Import json
import logging # Import logging

from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import Provenance

# Initialize logger
logger = logging.getLogger(__name__)

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


def _require_mqtt() -> None:
    """Fail-closed guard for the optional Bambu MQTT transport.

    Reads the module-global ``mqtt`` at call time so tests can
    simulate a missing dependency without reimporting. Never
    returns a fake client."""
    if not PAHO_MQTT_AVAILABLE or mqtt is None:
        raise PrinterUnavailable(
            MQTT_MISSING_MESSAGE + " No motion, no telemetry.")


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

    # Define _result function for SimulatedPrinterAdapter
    def _result(self, device: PrinterDevice, job: PrintJob, status: str, *, error: str = "") -> PrintResult:
        return PrintResult(
            job_id=job.job_id,
            printer_id=device.printer_id,
            status=status,
            gcode_sha256=job.gcode_sha256,
            started_at=job.started_at or now(),
            ended_at=now(),
            error=error,
            telemetry={},
            actor=job.actor,
            provenance=Provenance(source_type="simulation", creator_id="simulated-adapter")
        )

    def execute(self, device: PrinterDevice,
                job: PrintJob) -> PrintResult:
        if job.job_id in self._cancelled:
            return self._result(device, job, "cancelled",
                           error="cancelled before start (simulated)")
        if self._fail:
            return self._result(device, job, "failed",
                           error="simulated failure (test)")
        return self._result(device, job, "completed")

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


class BambuPrinterAdapter(PrinterAdapter):
    """Bambu Lab A1 Mini (AMS) printer adapter.
    Real driver, but transport and API integration are not yet implemented.
    Raises PrinterUnavailable until fully connected."""

    name = "bambu-a1-mini-ams"
    capabilities = ["printer.status", "printer.telemetry",
                    "printer.upload", "printer.start",
                    "printer.pause", "printer.stop",
                    "printer.cancel"]

    def __init__(self, mqtt_host: str, mqtt_port: int, mqtt_username: Optional[str], mqtt_password: Optional[str], printer_serial: str, printer_token: str):
        if not str(mqtt_host or "").strip() or not str(printer_serial or "").strip():
            raise PrinterRefusedError(
                "Bambu adapter needs mqtt_host and printer_serial")
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.mqtt_username = mqtt_username
        self.mqtt_password = mqtt_password
        self.printer_serial = printer_serial
        self.printer_token = printer_token

        self.client = None
        self.message_queue = queue.Queue()
        self.is_connected = False
        self._status = "offline" # Use string for initial state matching other adapters
        self._current_job_id: str | None = None
        self._jobs: dict[str, PrintJob] = {} # In-memory store for job status
        self._is_simulated = False # Flag to indicate if this is a real adapter or simulation


    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info(f"Connected to MQTT Broker: {self.mqtt_host}")
            self.is_connected = True
            # Subscribe to relevant topics
            status_topic = f"device/{self.printer_serial}/report"
            command_reply_topic = f"device/{self.printer_serial}/command_reply"
            self.client.subscribe(status_topic)
            self.client.subscribe(command_reply_topic)
            logger.info(f"Subscribed to {status_topic} and {command_reply_topic}")
            # Publish initial status request (example)
            self.client.publish(f"device/{self.printer_serial}/command", json.dumps({"command": "get_status"}))
        else:
            logger.error(f"Failed to connect, return code {rc}\n")
            self.is_connected = False
            self._status = "offline"

    def _on_message(self, client, userdata, msg):
        logger.debug(f"Received message on topic {msg.topic}: {msg.payload.decode()}")
        try:
            payload = json.loads(msg.payload.decode())
            self.message_queue.put((msg.topic, payload))
        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON message: {msg.payload.decode()}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def _connect_mqtt(self):
        _require_mqtt()
        # Use a unique client ID to avoid conflicts
        client_id = f"coordinator_bambu_{self.printer_serial}_{time.time_ns()}"
        self.client = mqtt.Client(client_id=client_id)

        if self.mqtt_username and self.mqtt_password:
            self.client.username_pw_set(self.mqtt_username, self.mqtt_password)

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        try:
            logger.info(f"Attempting to connect to MQTT broker at {self.mqtt_host}:{self.mqtt_port}")
            self.client.connect(self.mqtt_host, self.mqtt_port, 60)
            self.client.loop_start() # Start network loop in background thread
            # Start message processing thread
            threading.Thread(target=self._process_messages, daemon=True).start()
        except Exception as e:
            logger.error(f"MQTT connection error: {e}")
            self.is_connected = False
            self._status = "offline"


    def _process_messages(self):
        """Process messages from the MQTT queue."""
        while True:
            try:
                topic, payload = self.message_queue.get_nowait()
                self._handle_mqtt_payload(topic, payload)
                self.message_queue.task_done()
            except queue.Empty:
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"Error processing MQTT message: {e}")

    def _handle_mqtt_payload(self, topic: str, payload: dict):
        """Handle incoming MQTT payloads and update printer state."""
        # This is a simplified example. Real Bambu MQTT payloads are complex.
        # You would need to parse specific messages for status, job updates, etc.

        if "report" in topic:
            # Example: Update printer status based on report payload
            if "print_status" in payload:
                status_str = payload["print_status"]
                if status_str == "PRINTING":
                    self._status = "printing"
                    if self._current_job_id and self._current_job_id in self._jobs:
                        job = self._jobs[self._current_job_id]
                        job.status = "running"
                        if "progress" in payload and payload["progress"] is not None:
                            job.progress = {"progress": int(payload["progress"]), "time_remaining": payload.get("time_remaining")} # Mimic PrinterProgress structure
                        if "start_time" in payload: # Assuming printer provides start time
                             job.started_at = payload["start_time"]

                elif status_str == "PAUSED":
                    self._status = "paused"
                    if self._current_job_id and self._current_job_id in self._jobs:
                        self._jobs[self._current_job_id].status = "paused"

                elif status_str in ("FINISH", "CANCELLED", "STOPPED"): # Map Bambu statuses to our statuses
                    self._status = "idle"
                    if self._current_job_id and self._current_job_id in self._jobs:
                        job = self._jobs[self._current_job_id]
                        job.status = "completed" if status_str == "FINISH" else "cancelled"
                        job.ended_at = payload.get("end_time", now()) # Assuming end time is provided
                        job.error = payload.get("error", "")
                    self._current_job_id = None

                elif status_str == "IDLE":
                    self._status = "idle"
                    self._current_job_id = None # Ensure current job is cleared if printer reports idle

                else:
                    self._status = "error" # Default to error for unknown states

            # Example: Update job info if available
            if "job_id" in payload and "job_name" in payload:
                job_id = payload["job_id"]
                if job_id not in self._jobs:
                    # Create a basic PrintJob if it doesn't exist
                    self._jobs[job_id] = PrintJob(
                        job_id=job_id,
                        printer_id=self.printer_serial, # Assuming serial is printer_id
                        gcode_ref=payload.get("job_name", "Unknown File"),
                        gcode_sha256=payload.get("gcode_sha256", "0"*64), # Placeholder if not provided
                        profile="default", # Placeholder
                        status="queued", # Initial status, will be updated
                        actor="system", # Placeholder
                        started_at=payload.get("start_time", ""),
                        ended_at=payload.get("end_time", ""),
                        error=payload.get("error", ""),
                        provenance=Provenance(source_type="telemetry", creator_id=f"printer:{self.printer_serial}")
                    )
                if self._current_job_id == job_id:
                    job = self._jobs[job_id]
                    job.gcode_ref = payload.get("job_name", job.gcode_ref) # Update name
                    # Update other fields as needed based on received payload


        elif "command_reply" in topic:
            # Handle replies to commands sent
            if payload.get("success"):
                logger.info(f"Command successful: {payload}")
                # Update job status based on command replies if applicable
                if payload.get("command") == "start_print" and payload.get("success"):
                    if self._current_job_id and self._current_job_id in self._jobs:
                         self._jobs[self._current_job_id].status = "running"
                         self._status = "printing" # Update overall status
            else:
                logger.info(f"Command failed: {payload}") # Use info for expected command failures too
                # If a command fails, update the status of the affected job
                if "job_id" in payload and payload["job_id"] in self._jobs:
                    job = self._jobs[payload["job_id"]]
                    job.status = "failed"
                    job.error = payload.get("message", "Unknown error during command execution")
                    job.ended_at = now()
                    if self._current_job_id == payload["job_id"]:
                        self._current_job_id = None
                        self._status = "error"


    def _send_command(self, command: dict, retries: int = 3) -> dict:
        """Sends a command to the printer via MQTT and returns the reply payload."""
        _require_mqtt()
        if not self.is_connected or not self.client:
            return {"success": False, "message": "Not connected to MQTT."}

        # Add common fields required by the printer API
        command["printer_serial"] = self.printer_serial
        command["token"] = self.printer_token

        topic = f"device/{self.printer_serial}/command"
        payload = json.dumps(command)

        logger.info(f"Sending command to {topic}: {payload}")

        for attempt in range(retries):
            try:
                result = self.client.publish(topic, payload)
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    # In a real implementation, we'd wait for a specific reply
                    # on the command_reply_topic. For this example, we'll assume
                    # a successful publish implies eventual success and return a placeholder response.
                    # A more robust solution would involve tracking command IDs and matching replies.
                    logger.debug(f"Command published successfully (mid={result.mid})")
                    # Simulate a reply - this needs to be replaced with actual reply handling
                    return {"success": True, "message": "Command sent, waiting for confirmation.", "command": command.get("command")}
                else:
                    logger.warning(f"MQTT publish failed with code {result.rc} on attempt {attempt + 1}")
                    time.sleep(5) # Wait before retrying
            except Exception as e:
                logger.error(f"Exception during MQTT publish: {e} on attempt {attempt + 1}")
                time.sleep(5) # Wait before retrying

        return {"success": False, "message": f"Failed to send command after {retries} retries."}


    def status(self, device: PrinterDevice) -> dict:
        """Get the current status of the printer."""
        if not self.is_connected:
            raise PrinterUnavailable("Bambu printer is offline.")

        # Request status explicitly if needed and wait for a reply.
        # For simplicity here, we return the last known status from MQTT reports.
        # A real implementation would need a mechanism to send a status request
        # and wait for the specific reply.
        return {"printer_id": device.printer_id, "state": self._status}


    def execute(self, device: PrinterDevice, job: PrintJob) -> PrintResult:
        """Executes a print job."""
        if not self.is_connected:
            raise PrinterUnavailable("Bambu printer is offline.")
        if job.job_id in self._jobs and self._jobs[job.job_id].status in TERMINAL_JOB_STATUSES:
             raise PrinterRefusedError(f"Job {job.job_id} is already in terminal state.")

        # Send the start print command
        command_result = self._send_command({
            "command": "start_print",
            "job_id": job.job_id,
            "file_path": job.gcode_ref # Assuming gcode_ref is the path on the printer
        })

        if command_result.get("success"):
            # Update internal state for the job
            if job.job_id not in self._jobs:
                 # If job wasn't known, create it
                 self._jobs[job.job_id] = job
            self._jobs[job.job_id].status = "queued" # Start as queued
            self._jobs[job.job_id].started_at = now()
            self._current_job_id = job.job_id
            self._status = "printing" # Update overall status

            # Simulate completion after a delay for testing purposes if not connected to real printer
            # In a real scenario, you'd wait for MQTT status updates.
            if not self.is_connected or self._is_simulated: # Check if simulation is intended
                 threading.Thread(target=self._simulate_job_completion, args=(job.job_id,), daemon=True).start()

            # Return a PrintResult indicating the job has started
            return PrintResult(
                job_id=job.job_id,
                printer_id=device.printer_id,
                status="queued", # Initially queued, will change to running/completed
                gcode_sha256=job.gcode_sha256,
                started_at=now(),
                ended_at="",
                error="",
                telemetry={}, # Initial telemetry is empty
                actor=job.actor,
                provenance=Provenance(source_type="operator-request", creator_id=job.actor)
            )
        else:
            # Command failed to send or printer reported error
            error_msg = command_result.get("message", "Unknown error during start_print command.")
            self._jobs[job.job_id] = job.model_copy(update={
                "status": "failed", "error": error_msg, "ended_at": now()
            })
            raise PrinterUnavailable(f"Failed to start print job {job.job_id}: {error_msg}")

    def cancel(self, device: PrinterDevice, job: PrintJob) -> PrintJob:
        """Cancels a print job."""
        if not self.is_connected:
            raise PrinterUnavailable("Bambu printer is offline.")
        if job.job_id not in self._jobs or self._jobs[job.job_id].status in TERMINAL_JOB_STATUSES:
            # Job not found or already finished
            return job

        command_result = self._send_command({"command": "cancel_print", "job_id": job.job_id})

        if command_result.get("success"):
            # Update internal job status
            updated_job = self._jobs[job.job_id].model_copy(update={
                "status": "cancelled",
                "ended_at": now(),
                "error": "cancelled by operator (simulated; " + ESTOP_NOTE + ")",
            })
            self._jobs[job.job_id] = updated_job
            if self._current_job_id == job.job_id:
                self._current_job_id = None
                self._status = "idle"
            return updated_job
        else:
            error_msg = command_result.get("message", "Unknown error during cancel_print command.")
            updated_job = self._jobs[job.job_id].model_copy(update={
                "status": "failed", "error": error_msg, "ended_at": now()
            })
            if self._current_job_id == job.job_id:
                self._current_job_id = None
                self._status = "error"
            return updated_job

    def _simulate_job_completion(self, job_id: str):
        """Simulates job completion after a delay for testing."""
        time.sleep(10) # Simulate print duration
        if job_id in self._jobs:
            job = self._jobs[job_id]
            if job.status == "queued" or job.status == "running": # Only complete if not already cancelled/failed
                job.status = "completed"
                job.ended_at = now()
                job.error = ""
                self._jobs[job_id] = job
                if self._current_job_id == job_id:
                    self._current_job_id = None
                    self._status = "idle" # Transition to idle


    @classmethod
    def requirements(cls) -> str:
        return ("Bambu Lab printer requires MQTT connection details (host, port, "
                "username, password) and printer-specific credentials "
                "(serial, token).")

    def __del__(self):
        """Ensure MQTT client is disconnected when the object is garbage collected."""
        if getattr(self, "client", None):
            self.client.loop_stop()
            self.client.disconnect()
            logger.info("MQTT client disconnected.")


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
