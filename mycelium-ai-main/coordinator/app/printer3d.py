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
  is M4.1 READ-ONLY telemetry (TLS connect + allow-listed report
  subscribe + real ``print``-payload parsing); it has NO publish
  path, and ``execute()``/``cancel()`` refuse unconditionally.
  Motion returns no earlier than M4.2. The adapter needs the
  optional ``paho-mqtt`` package plus real hardware, and raises
  ``PrinterUnavailable`` until a valid push arrives. No serial,
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
import threading # Bambu connack/push events (bounded waits only)
import json # Bambu report parsing (inbound only, never publish)
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
    model: str = Field(default="", max_length=80)
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
    spool_id: str = Field(default="", max_length=80)
    slot: str = Field(default="", max_length=12)
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
                notes: str = "", model: str = "") -> PrinterDevice:
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
    cleaned_model = str(model or "").strip()[:80]
    return PrinterDevice(
        printer_id=printer_id.strip(),
        name=name.strip()[:120],
        model=cleaned_model,
        capabilities=check_capabilities(capabilities or []),
        inventory_hardware_id=twin,
        notes=str(notes or "")[:500],
        created_at=now())


def new_job(job_id: str, printer_id: str, gcode_ref: str,
            gcode_sha256: str, profile: str, actor: str,
            proposal_id: str = "", spool_id: str = "",
            slot: str = "") -> PrintJob:
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
    import re as _slot_re
    cleaned_slot = str(slot or "").strip()[:12]
    if cleaned_slot and not _slot_re.match(
            r"^[A-Za-z0-9_-]{1,12}$", cleaned_slot):
        raise PrinterRefusedError(
            "slot must match [A-Za-z0-9_-]{1,12}")
    return PrintJob(
        job_id=job_id, printer_id=printer_id,
        gcode_ref=reference, gcode_sha256=gcode_sha256.lower(),
        profile=profile, actor=actor.strip(),
        proposal_id=proposal_id,
        spool_id=str(spool_id or "")[:80], slot=cleaned_slot,
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
    """Bambu Lab A1 Mini (AMS), M4.1 READ-ONLY telemetry.

    TLS connect + subscribe to the allow-listed report topic +
    parse of real Bambu ``print`` payloads + disconnect. There is
    NO publish path in this phase: the old command-sending helper
    was removed, ``execute()``/``cancel()`` refuse unconditionally,
    and motion returns no earlier than M4.2. Status is UNKNOWN
    until a valid push arrives and goes stale after 60s; READY is
    never inferred from connection alone.
    """

    name = "bambu-a1-mini-ams"
    capabilities = ["printer.status", "printer.telemetry",
                    "printer.upload", "printer.start",
                    "printer.pause", "printer.stop",
                    "printer.cancel"]

    #: Exact-match subscription allowlist (single entry, M4.1).
    #: Anything else inbound is counted and ignored.
    REPORT_TOPIC_TEMPLATE = "device/{serial}/report"

    #: Seconds without a valid push before telemetry counts stale.
    STALE_AFTER_SECONDS = 60.0

    def __init__(self, mqtt_host: str, mqtt_port: int, mqtt_username: Optional[str], mqtt_password: Optional[str], printer_serial: str, printer_token: str, *, client_factory=None, default_timeout: float = 10.0):
        if not str(mqtt_host or "").strip() or not str(printer_serial or "").strip():
            raise PrinterRefusedError(
                "Bambu adapter needs mqtt_host and printer_serial")
        self.mqtt_host = str(mqtt_host).strip()
        try:
            self.mqtt_port = int(mqtt_port or 8883)
        except (TypeError, ValueError):
            raise PrinterRefusedError(
                "mqtt_port must be numeric") from None
        self.mqtt_username = str(mqtt_username or "") or "bblp"
        self.mqtt_password = mqtt_password
        self.printer_serial = str(printer_serial).strip()
        self.printer_token = printer_token
        self._client_factory = client_factory
        try:
            self._default_timeout = max(1.0, float(default_timeout))
        except (TypeError, ValueError):
            self._default_timeout = 10.0

        self.client = None
        self.is_connected = False
        self._report: dict[str, Any] = {}
        self._pushes = 0
        self._unexpected_topics = 0
        self._payload_errors = 0
        self._last_read_at = ""
        self._connected_at = ""
        self._connack = threading.Event()
        self._pushed = threading.Event()


    def _report_topic(self) -> str:
        return self.REPORT_TOPIC_TEMPLATE.format(
            serial=self.printer_serial)

    def _make_client(self):
        """Build the MQTT client. The factory is injectable so
        tests use a fake without network; production uses paho
        with the module-global reference (keeps the existing
        ``paho.mqtt.client.Client`` patch point working).

        Proven against the real A1 mini broker: explicit v3.1.1,
        clean session, legacy TLS negotiation floor (the ESP32
        broker never answers the strict TLSv1.2+ default).
        """
        _require_mqtt()
        if self._client_factory is not None:
            return self._client_factory()
        import secrets as _secrets
        client_id = f"mycelium-{_secrets.token_hex(4)}"
        try:
            api = mqtt.CallbackAPIVersion.VERSION2
            return mqtt.Client(api, client_id=client_id,
                               protocol=mqtt.MQTTv311,
                               transport="tcp", clean_session=True)
        except AttributeError:
            return mqtt.Client(client_id=client_id)

    @staticmethod
    def _rc_to_int(rc) -> int:
        try:
            value = rc.value if hasattr(rc, "value") else rc
            return int(value)
        except (TypeError, ValueError):
            return -1

    def _on_connect(self, client, userdata, flags, rc,
                    properties=None):
        code = self._rc_to_int(rc)
        if code == 0:
            try:
                client.subscribe(self._report_topic())
            except Exception as error:
                logger.error(f"Bambu subscribe failed: {error}")
                self.is_connected = False
                return
            self.is_connected = True
            self._connected_at = now()
            self._connack.set()
            logger.info(
                f"Bambu MQTT connected (read-only): {self.mqtt_host} "
                f"(subscribed, never publishing)")
        else:
            logger.error(f"Bambu MQTT refused, return code {code}")
            self.is_connected = False
            self._connack.set()

    def _on_disconnect(self, client, userdata, flags, rc,
                       properties=None):
        self.is_connected = False
        logger.info(
            f"Bambu MQTT disconnected "
            f"(rc={self._rc_to_int(rc)})")

    def _on_message(self, client, userdata, msg):
        try:
            topic = str(getattr(msg, "topic", ""))
            raw = bytes(getattr(msg, "payload", b"") or b"")
        except Exception as error:
            logger.error(f"Bambu message read failed: {error}")
            return
        self._handle_mqtt_payload(topic, raw)

    def _connect_mqtt(self):
        """Open a read-only session. Fire-and-forget by design:
        connect_async never blocks; callers bound the wait via
        wait_for_push()/read_bambu_once(). No publish, ever."""
        _require_mqtt()
        if self.is_connected and self.client is not None:
            return
        self._connack.clear()
        client = self._make_client()
        try:
            if self.mqtt_username:
                client.username_pw_set(
                    self.mqtt_username, self.mqtt_password or "")
            try:
                import ssl as _ssl
                # Bewezen tegen de echte A1 mini: CERT_NONE direct
                # in tls_set. Alleen tls_insecure_set() achteraf
                # bouwt de context al met CERT_REQUIRED waardoor
                # de ESP32-handshake nooit een CONNACK oplevert
                # (bisectie A/B/C). Self-signed LAN-cert, nooit
                # plaintext.
                client.tls_set(tls_version=_ssl.PROTOCOL_TLS,
                               cert_reqs=_ssl.CERT_NONE)
            except Exception as error:
                raise PrinterUnavailable(
                    f"Bambu TLS setup failed ({error}); refusing "
                    f"plaintext to a printer") from error
            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message
            self.client = client
            client.connect_async(self.mqtt_host, self.mqtt_port,
                                 keepalive=60)
            client.loop_start()
        except PrinterUnavailable:
            raise
        except Exception as error:
            self.client = None
            raise PrinterUnavailable(
                f"Bambu MQTT unreachable ({error})") from error

    #: gcode_state -> honest adapter state. Unknown strings stay
    #: "unknown"; READY is never a state (never infer readiness).
    GCODE_STATE_MAP = {
        "IDLE": "idle",
        "RUNNING": "printing",
        "PAUSE": "paused",
        "PAUSED": "paused",
        "FINISH": "idle",
        "FAILED": "failed",
        "PREPARE": "preparing",
        "SLICING": "preparing",
    }

    def _handle_mqtt_payload(self, topic: str, raw: bytes) -> str:
        """Parse one inbound report against the real Bambu schema.

        Returns "stored" | "ignored-topic" | "ignored-payload".
        Only the exact allow-listed topic is accepted; payloads
        merge as deltas into ``_report`` (Bambu sends partial
        updates). Anything unexpected is counted, never trusted.
        """
        if topic != self._report_topic():
            self._unexpected_topics += 1
            return "ignored-topic"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._payload_errors += 1
            return "ignored-payload"
        if not isinstance(payload, dict):
            self._payload_errors += 1
            return "ignored-payload"
        node = payload.get("print")
        if not isinstance(node, dict):
            self._payload_errors += 1
            return "ignored-payload"
        merged = dict(self._report)
        for key in ("gcode_state", "gcode_file", "subtask_name",
                    "nozzle_temper", "bed_temper", "chamber_temper",
                    "nozzle_target_temper", "bed_target_temper",
                    "mc_percent", "mc_remaining_time",
                    "layer_num", "total_layer_num", "print_error",
                    "wifi_signal", "nozzle_diameter", "ams_status"):
            if key in node and node[key] is not None:
                merged[key] = node[key]
        ams = node.get("ams")
        if isinstance(ams, dict):
            trays = []
            for unit in ams.get("ams", []) or []:
                if isinstance(unit, dict):
                    for tray in unit.get("tray", []) or []:
                        if isinstance(tray, dict):
                            trays.append({
                                "id": tray.get("id"),
                                "tag_uid": tray.get("tag_uid", ""),
                                "ctype": tray.get("ctype", ""),
                                "remain": tray.get("remain", -1),
                            })
            merged["ams_trays"] = trays
            merged["ams_exists"] = ams.get("ams_exist_bits", "")
        self._report = merged
        self._pushes += 1
        self._last_read_at = now()
        self._pushed.set()
        return "stored"

    def _report_age_seconds(self, current: str = "") -> float | None:
        if not self._last_read_at:
            return None
        try:
            from datetime import datetime, timezone
            stamp = current or datetime.now(timezone.utc).isoformat()
            delta = (datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                     - datetime.fromisoformat(
                         self._last_read_at.replace("Z", "+00:00")))
            return max(0.0, delta.total_seconds())
        except (ValueError, TypeError):
            return None

    def _live_status(self) -> dict:
        """Build the status dict from the last good push. UNKNOWN
        wherever the printer has not actually said anything."""
        report = self._report
        gcode_state = str(report.get("gcode_state", "") or "")
        state = self.GCODE_STATE_MAP.get(gcode_state, "unknown")
        if gcode_state == "FINISH":
            state = "idle"

        def _num(key: str):
            try:
                value = report.get(key, None)
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        trays = report.get("ams_trays") or []
        has_trays = isinstance(report.get("ams_trays"), list)
        loaded_flags = [bool(
            isinstance(tray, dict)
            and str(tray.get("tag_uid", "") or "") not in
            ("", "0000000000000000")) for tray in trays]
        loaded = sum(1 for flag in loaded_flags if flag)
        job_name = str(report.get("subtask_name", "")
                       or report.get("gcode_file", "") or "")
        return {
            "state": state,
            "gcode_state": gcode_state or "UNKNOWN",
            "nozzle_c": _num("nozzle_temper"),
            "bed_c": _num("bed_temper"),
            "progress_pct": _num("mc_percent"),
            "remaining_min": _num("mc_remaining_time"),
            "layer": _num("layer_num"),
            "layers_total": _num("total_layer_num"),
            "job_name": job_name[:120],
            "ams_trays": len(trays),
            "ams_loaded": loaded,
            "trays_loaded": loaded_flags if has_trays else [],
            "print_error": report.get("print_error", 0),
            "pushes": self._pushes,
            "last_read_at": self._last_read_at,
        }

    def wait_for_push(self, timeout: float | None = None) -> bool:
        """Wait (bounded) for the next valid push. No polling of
        the printer — the broker delivers; we only wait."""
        try:
            budget = max(1.0, float(
                self._default_timeout if timeout is None
                else timeout))
        except (TypeError, ValueError):
            budget = self._default_timeout
        self._pushed.clear()
        return bool(self._pushed.wait(timeout=budget))

    def disconnect(self) -> None:
        """Close the read session. Best-effort, never raises."""
        self.is_connected = False
        client, self.client = self.client, None
        if client is None:
            return
        try:
            client.loop_stop()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass


    def status(self, device: PrinterDevice) -> dict:
        """Live read-only status from the last valid push.

        Refuses (fail-closed) when offline, without telemetry, or
        stale (>60s). Never invents READY: without a gcode_state
        the state is "unknown".
        """
        if not self.is_connected:
            raise PrinterUnavailable("Bambu printer is offline.")
        if not self._report or not self._last_read_at:
            raise PrinterUnavailable(
                "Bambu connected but no telemetry yet; UNKNOWN, "
                "never READY by connection alone.")
        age = self._report_age_seconds()
        if age is not None and age > self.STALE_AFTER_SECONDS:
            raise PrinterUnavailable(
                f"Bambu telemetry stale ({age:.0f}s without push); "
                f"not READY.")
        live = self._live_status()
        live["printer_id"] = device.printer_id
        return live

    def execute(self, device: PrinterDevice, job: PrintJob) -> PrintResult:
        """M4.2 physical execution (operator-gated upstream).

        Runs only after exact-YES + revalidation in fab_flow: live
        G-code re-hash, plate .3mf build, FTPS upload + SIZE
        verify, project_file publish, start-confirm via telemetry.
        Returns started (never completed — completion is observed
        separately). Offline/unconfigured refuses fail-closed.
        """
        if not self.is_connected:
            raise PrinterUnavailable("Bambu printer is offline.")
        from .bambu_exec import BambuExecError, BambuExecUnavailable
        from .bambu_exec import execute_bambu_job
        try:
            started = execute_bambu_job(self, device, job)
        except (BambuExecError, BambuExecUnavailable) as error:
            raise PrinterUnavailable(
                f"Bambu execution refused: {error}") from error
        return PrintResult(
            job_id=job.job_id,
            printer_id=device.printer_id,
            status="running",
            gcode_sha256=job.gcode_sha256,
            started_at=now(),
            ended_at="",
            error="",
            telemetry={
                "remote_name": started["remote_name"],
                "size_bytes": started["size_bytes"],
                "subtask_name": started["subtask_name"],
                "sequence_id": started["sequence_id"],
                "profile_files": started["profile_files"],
                "weight_g": started["weight_g"],
            },
            actor=job.actor,
            provenance=Provenance(
                source_type="operator-request",
                creator_id=job.actor, human_verified=False,
                notes="physical print started; completion is "
                      "observed separately, never implied"))

    def cancel(self, device: PrinterDevice, job: PrintJob) -> PrintJob:
        """M4.2 hardware stop (operator-gated upstream).

        Publishes stop and confirms IDLE; refuses (fail-closed)
        when offline or unconfirmed. Queue bookkeeping stays with
        the caller.
        """
        if not self.is_connected:
            raise PrinterUnavailable("Bambu printer is offline.")
        from .bambu_exec import BambuExecError, BambuExecUnavailable
        from .bambu_exec import stop_bambu_job
        try:
            stop_bambu_job(self)
        except (BambuExecError, BambuExecUnavailable) as error:
            raise PrinterUnavailable(
                f"Bambu stop refused: {error}") from error
        return job.model_copy(update={
            "status": "cancelled", "ended_at": now(),
            "error": "stopped by operator; verify on device (" +
                     ESTOP_NOTE + ")",
        })


    @classmethod
    def requirements(cls) -> str:
        return ("Bambu Lab printer (M4.1 read-only): LAN MQTT over "
                "TLS :8883 as user bblp with the printer access code, "
                "plus the printer serial for the report topic. "
                "Configure via BAMBU_MQTT_HOST/PORT/USERNAME/"
                "ACCESS_CODE env only (never stored); enable LAN mode "
                "on the printer. Motion paths do not exist in M4.1.")

    def __del__(self):
        """Best-effort disconnect on teardown. Never raises."""
        try:
            self.disconnect()
        except Exception:
            pass


#: Env-only Bambu credentials (M4.1). Never persisted, never
#: logged, never rendered. USERNAME defaults to the protocol-fixed
#: "bblp"; the serial is identity (not a secret) but also stays
#: out of source/DB for the same handling discipline.
BAMBU_ENV_VARS = ("BAMBU_MQTT_HOST", "BAMBU_MQTT_PORT",
                  "BAMBU_MQTT_USERNAME", "BAMBU_MQTT_ACCESS_CODE",
                  "BAMBU_PRINTER_SERIAL")


def bambu_config_from_env(env=None) -> tuple[dict, list[str]]:
    """Read Bambu LAN config from the environment only.

    Returns (config, missing). Missing names the exact vars to
    set; values never appear in messages, logs or errors.
    """
    import os as _os
    source = env if env is not None else _os.environ
    host = str(source.get("BAMBU_MQTT_HOST", "") or "").strip()
    raw_port = str(source.get("BAMBU_MQTT_PORT", "") or "").strip()
    username = str(source.get("BAMBU_MQTT_USERNAME", "")
                   or "").strip() or "bblp"
    access_code = str(source.get("BAMBU_MQTT_ACCESS_CODE", "")
                      or "").strip()
    serial = str(source.get("BAMBU_PRINTER_SERIAL", "")
                 or "").strip()
    missing = []
    if not host:
        missing.append("BAMBU_MQTT_HOST")
    if not access_code:
        missing.append("BAMBU_MQTT_ACCESS_CODE")
    if not serial:
        missing.append("BAMBU_PRINTER_SERIAL")
    try:
        port = int(raw_port) if raw_port else 8883
    except (TypeError, ValueError):
        return {}, ["BAMBU_MQTT_PORT (moet numeriek zijn)"]
    if not 1 <= port <= 65535:
        return {}, ["BAMBU_MQTT_PORT (moet 1..65535 zijn)"]
    if missing:
        return {}, missing
    return {"host": host, "port": port, "username": username,
            "access_code": access_code, "serial": serial}, []


def read_bambu_once(printer_id: str = "", timeout: float = 20.0,
                    client_factory=None, env=None) -> dict:
    """One bounded read-only session: connect, wait for a valid
    push, snapshot, disconnect (always, via finally).

    Raises PrinterUnavailable (missing config/unreachable/
    timeout/no telemetry) or PrinterRefusedError (bad config).
    Publishes nothing; the adapter has no publish path.
    """
    config, missing = bambu_config_from_env(env=env)
    if missing:
        raise PrinterUnavailable(
            "Bambu niet geconfigureerd; zet "
            + ", ".join(missing))
    adapter = BambuPrinterAdapter(
        config["host"], config["port"], config["username"],
        config["access_code"], config["serial"], "",
        client_factory=client_factory, default_timeout=timeout)
    try:
        adapter._connect_mqtt()
        if not adapter.wait_for_push(timeout=timeout):
            raise PrinterUnavailable(
                "Bambu verbonden maar geen geldige telemetrie "
                "binnen budget; UNKNOWN.")
        live = adapter._live_status()
        live["printer_id"] = printer_id or config["serial"]
        live["reachable"] = True
        return live
    finally:
        adapter.disconnect()


#: Last read-only snapshots per printer (process-local display
#: cache; never a source of truth, always timestamped).
_LAST_BAMBU_READS: dict[str, dict] = {}


def connect_printer(printer_id: str, *, timeout: float = 20.0,
                    client_factory=None) -> dict:
    """Attach a live Bambu adapter to a registered printer.

    Operator-triggered only (connect route). Exactly one bounded
    read-only telemetry check via ``read_bambu_once``; the adapter
    is registered in the in-memory registry only on valid
    telemetry. Every failure closes without registering and
    without partial state. This function never moves hardware:
    no publish, no upload, no job — motion stays behind the
    printer.execute YES-gate in fab_flow.
    """
    device = _PRINTERS.get(str(printer_id or ""))
    if device is None:
        device = load_printer(str(printer_id or ""))
    if device is None:
        raise PrinterRefusedError(
            f"Printer '{str(printer_id or '')[:40]}' unknown; "
            f"register it first")
    config, missing = bambu_config_from_env()
    if missing:
        raise PrinterRefusedError(
            "Bambu niet geconfigureerd; zet "
            + ", ".join(missing))
    _require_mqtt()
    try:
        budget = float(timeout)
    except (TypeError, ValueError):
        budget = 20.0
    budget = max(1.0, min(budget, 60.0))
    live = read_bambu_once(device.printer_id, timeout=budget,
                           client_factory=client_factory)
    adapter = BambuPrinterAdapter(
        config["host"], config["port"], config["username"],
        config["access_code"], config["serial"], "",
        client_factory=client_factory)
    register_printer(device, adapter)
    return {
        "printer_id": device.printer_id,
        "adapter": adapter.name,
        "reachable": True,
        "state": live.get("state", "unknown"),
        "gcode_state": live.get("gcode_state", "UNKNOWN"),
        "nozzle_c": live.get("nozzle_c"),
        "bed_c": live.get("bed_c"),
        "progress_pct": live.get("progress_pct"),
        "last_read_at": live.get("last_read_at", ""),
    }


def record_bambu_reading(printer_id: str, snapshot: dict) -> dict:
    entry = dict(snapshot or {})
    entry["read_at"] = now()
    _LAST_BAMBU_READS[str(printer_id or "")] = entry
    return entry


def last_bambu_reading(printer_id: str) -> dict | None:
    return _LAST_BAMBU_READS.get(str(printer_id or ""))


def adapter_capabilities(adapter: PrinterAdapter) -> list[str]:
    claimed = list(getattr(adapter, "capabilities", []) or [])
    return [cap for cap in claimed if cap in PRINTER_CAPABILITIES]


def ams_slot_loaded(live: dict | None,
                    slot_label: str) -> bool | None:
    """Is the tray for one AMS-N slot loaded? True/False, or None
    when the printer reported no tray data. Never guessed: an
    empty slot label or unknown tray state returns None."""
    import re as _re
    match = _re.match(r"(?i)^ams-([1-8])$",
                      str(slot_label or ""))
    if not match:
        return None
    flags = (live or {}).get("trays_loaded")
    if not isinstance(flags, list) or not flags:
        return None
    index = int(match.group(1)) - 1
    if index >= len(flags):
        return None
    return bool(flags[index])


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
