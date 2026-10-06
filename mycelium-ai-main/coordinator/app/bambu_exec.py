"""Bambu physical execution (M4.2): FTPS upload + project_file start.

Explicit operator-triggered only, through the existing writes
YES flow. No auto-execution, no background autonomy, no second
queue or database. Every step is bounded and fail-closed; the
first real print is a supervised experiment whose exact bytes,
commands (sans secrets) and telemetry land in the job dossier.

Not scanned by the fab-core tripwire tests (new module, reviewed
here instead): network I/O lives solely in this file, never in
mesh3d/slicer3d/printer3d/fab_flow. Secrets travel only inside
TLS sessions and never reach messages, logs, records or tests.
"""

from __future__ import annotations

import hashlib as _hashlib
import os as _os
import re as _re
import socket as _socket
import ssl as _ssl
import time as _time

BAMBU_FTPS_PORT = 990
BAMBU_FTPS_USER = "bblp"
CONNECT_TIMEOUT_SECONDS = 15.0
COMMAND_TIMEOUT_SECONDS = 30.0
START_CONFIRM_SECONDS = 180.0
STOP_CONFIRM_SECONDS = 120.0
MAX_3MF_BYTES = 200 * 1024 * 1024


class BambuExecError(ValueError):
    """Local validation refused; the printer was not touched."""


class BambuExecUnavailable(RuntimeError):
    """Printer/transport unavailable; fail-closed, never partial."""


def sanitize_3mf_name(name: str) -> str:
    """Bare .3mf filename: stem + single suffix, no paths, no
    spaces/URL-illegal characters (firmware parses ftp://{name})."""
    text = str(name or "").strip()
    if "\\" in text or "/" in text or ".." in text:
        raise BambuExecError(
            "3mf name must be a bare filename (no paths); refusing")
    text = text.replace(" ", "_")
    if not text.lower().endswith(".3mf") or len(text) > 80:
        raise BambuExecError(
            "3mf name must be a bare filename ending .3mf "
            "(<=80 chars)")
    if text.startswith("."):
        raise BambuExecError("3mf name invalid")
    if not _re.match(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*\.3mf$",
                     text, _re.IGNORECASE):
        raise BambuExecError(
            "3mf name carries illegal characters; refusing")
    return text


def footer_facts(text: str, density: float | None) -> dict:
    """Filament/estimate facts from a slicer footer. Honest
    fallbacks: cm3 x density preferred (the [g] line reads 0.00
    on real output and is never trusted)."""
    out: dict = {"cm3": None, "weight_g": None,
                 "prediction_s": 0, "support": False}
    for line in str(text or "").splitlines()[-600:]:
        match = _re.search(
            r";\s*filament used \[cm3\]\s*=\s*([0-9]+(?:\.[0-9]+)?)",
            line)
        if match:
            try:
                out["cm3"] = float(match.group(1))
            except ValueError:
                pass
        match = _re.search(
            r";\s*estimated printing time.*=\s*(?:(\d+)h\s*)?"
            r"(?:(\d+)m\s*)?(?:(\d+)s)?", line)
        if match and any(match.groups()):
            out["prediction_s"] = int(match.group(1) or 0) * 3600 \
                + int(match.group(2) or 0) * 60 \
                + int(match.group(3) or 0)
        if "support_material" in line \
                or "; support" in line.lower():
            out["support"] = True
    if out["cm3"] is not None and density:
        try:
            out["weight_g"] = round(
                out["cm3"] * float(density), 2)
        except (TypeError, ValueError):
            out["weight_g"] = None
    return out


class _Dial:
    """Injectable transport (real sockets by default, scripted
    fakes in tests). TLS wrapping is separate so tests cover the
    command sequence without certificates."""

    def __init__(self, factory=None, wrap=None):
        self._factory = factory
        self._wrap = wrap

    def connect(self, host: str, port: int, timeout: float):
        if self._factory is not None:
            return self._factory(host, port, timeout)
        return _socket.create_connection((host, port),
                                         timeout=timeout)

    def wrap_tls(self, sock):
        if self._wrap is not None:
            return self._wrap(sock)
        ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        return ctx.wrap_socket(sock)


class _Ftps:
    """Minimal implicit-TLS FTPS speaking exactly the Bambu
    dialect: TLS on connect, TYPE I -> PBSZ 0 -> PROT P order,
    PASV-only with bogus-IP discard, data-TLS only after 150,
    SIZE-verify, no resume. Bounded everywhere. Only command
    VERBS are recorded (never arguments — the password never
    leaves the TLS session into any log)."""

    def __init__(self, sock, host: str, dial: _Dial,
                 timeout: float = COMMAND_TIMEOUT_SECONDS):
        self._sock = sock
        self._host = host
        self._dial = dial
        self._timeout = timeout
        self._file = sock.makefile("rb")
        #: Audit trail: command VERBS only, never arguments (the
        #: password travels inside TLS and never lands here).
        self.verbs: list[str] = []

    def _read(self) -> str:
        line = self._file.readline().decode("utf-8", "replace")
        if not line:
            raise BambuExecUnavailable("FTPS closed the connection")
        return line.strip()

    def _cmd(self, verb: str, argument: str,
             expect: tuple[str, ...]) -> str:
        self.verbs.append(verb)
        self._sock.sendall(f"{verb} {argument}\r\n".encode())
        reply = self._read()
        if reply[:3] not in expect:
            raise BambuExecUnavailable(
                f"FTPS {verb} refused ({reply[:60]})")
        return reply

    def login(self, username: str, password: str) -> None:
        banner = self._read()
        if not banner.startswith("220"):
            raise BambuExecUnavailable(
                f"FTPS no banner ({banner[:60]})")
        reply = self._cmd("USER", username, ("230", "331"))
        if reply.startswith("230"):
            return
        final = self._cmd("PASS", password, ("230",))
        _ = final

    def prepare(self) -> None:
        self._cmd("TYPE", "I", ("200",))
        self._cmd("PBSZ", "0", ("200",))
        self._cmd("PROT", "P", ("200",))

    def _pasv_port(self) -> int:
        reply = self._cmd("PASV", "", ("227",))
        match = _re.search(
            r"\((\d+),(\d+),(\d+),(\d+),(\d+),(\d+)\)", reply)
        if not match:
            raise BambuExecUnavailable(
                f"FTPS PASV unparseable ({reply[:60]})")
        nums = [int(part) for part in match.groups()]
        return nums[4] * 256 + nums[5]

    def upload(self, remote_name: str, data: bytes,
               transfer_timeout: float) -> None:
        try:
            self._cmd("DELE", remote_name, ("250", "450", "550"))
        except BambuExecUnavailable:
            pass
        port = self._pasv_port()
        data_sock = self._dial.connect(self._host, port,
                                       self._timeout)
        try:
            self._cmd("STOR", remote_name, ("150", "125"))
            tls_data = self._dial.wrap_tls(data_sock)
            try:
                tls_data.sendall(data)
            finally:
                try:
                    tls_data.shutdown(_socket.SHUT_RDWR)
                except Exception:
                    pass
                tls_data.close()
            self._sock.settimeout(transfer_timeout)
            try:
                reply = self._read()
            finally:
                self._sock.settimeout(self._timeout)
            if not reply.startswith("226"):
                raise BambuExecUnavailable(
                    f"FTPS stored without 226 ({reply[:60]})")
        finally:
            try:
                data_sock.close()
            except Exception:
                pass

    def size(self, remote_name: str) -> int:
        reply = self._cmd("SIZE", remote_name, ("213",))
        try:
            return int(reply[4:].strip().split(" ")[0])
        except (ValueError, IndexError):
            raise BambuExecUnavailable(
                f"FTPS SIZE unparseable ({reply[:60]})") from None

    def quit(self) -> None:
        try:
            self._cmd("QUIT", "", ("221", "226"))
        except BambuExecUnavailable:
            pass
        try:
            self._file.close()
            self._sock.close()
        except Exception:
            pass


def verify_remote_size(local_size: int, remote_size: int) -> None:
    """Refuse partial uploads: SIZE must equal local bytes."""
    if int(remote_size) != int(local_size):
        raise BambuExecUnavailable(
            f"FTPS SIZE mismatch ({remote_size} != {local_size}); "
            f"refusing partial file")


def ftps_upload(host: str, port: int, username: str, password: str,
                remote_name: str, data: bytes, *,
                timeout: float = COMMAND_TIMEOUT_SECONDS,
                dial: _Dial | None = None) -> dict:
    """Upload bytes to the printer SD root over implicit FTPS.

    SIZE-verified; partial uploads never proceed. Raises
    BambuExecError (local refusal) or BambuExecUnavailable
    (transport) with the failing stage named.
    """
    name = sanitize_3mf_name(remote_name)
    if not data:
        raise BambuExecError("no bytes to upload; refusing")
    if len(data) > MAX_3MF_BYTES:
        raise BambuExecError("3mf exceeds 200MB; refusing")
    if not str(host or "").strip():
        raise BambuExecError("printer host is required")
    transport = dial or _Dial()
    try:
        raw = transport.connect(host, port, timeout)
    except (OSError, ValueError) as error:
        raise BambuExecUnavailable(
            f"FTPS unreachable ({error})") from error
    try:
        session = transport.wrap_tls(raw)
    except (OSError, ValueError, _ssl.SSLError) as error:
        try:
            raw.close()
        except Exception:
            pass
        raise BambuExecUnavailable(
            f"FTPS TLS failed ({error})") from error
    ftp = _Ftps(session, host, transport, timeout)
    try:
        ftp.login(username, password)
        ftp.prepare()
        transfer_timeout = max(60.0, len(data) / 65536.0)
        ftp.upload(name, data, transfer_timeout)
        remote_size = ftp.size(name)
        verify_remote_size(len(data), remote_size)
        return {"remote_name": name, "size_bytes": len(data)}
    finally:
        ftp.quit()


def project_file_payload(*, filename: str, task_id: str,
                         subtask_name: str = "",
                         ams_mapping: list | None = None,
                         ams_mapping2: list | None = None,
                         use_ams: bool = False,
                         bed_type: str = "auto",
                         bed_leveling: bool = True,
                         flow_cali: bool = False,
                         vibration_cali: bool = False,
                         timelapse: bool = False,
                         sequence_id: int | None = None) -> dict:
    """Pure project_file command builder (no I/O).

    Follows the hardware-validated field contract: param carries
    the 1-indexed plate, url/file the bare name, md5 empty (skip
    validation), JSON booleans for flags, string IDs int32-capped.
    Raises BambuExecError on anything out of contract.
    """
    name = sanitize_3mf_name(filename)
    clean_task = str(task_id or "").strip()
    if not clean_task or len(clean_task) > 40:
        raise BambuExecError("task_id 1..40 chars required")
    mapping = [int(item) for item in (ams_mapping or [])]
    if any(not -1 <= item <= 255 for item in mapping):
        raise BambuExecError("ams_mapping out of range")
    mapping2 = []
    for entry in (ams_mapping2 or []):
        if not isinstance(entry, dict):
            raise BambuExecError("ams_mapping2 entries must map")
        try:
            mapping2.append({
                "ams_id": int(entry.get("ams_id", 0)),
                "slot_id": int(entry.get("slot_id", 0))})
        except (TypeError, ValueError):
            raise BambuExecError(
                "ams_mapping2 ids must be integers") from None
    try:
        sequence = int(sequence_id) if sequence_id is not None \
            else int(_time.time()) % 2**31
    except (TypeError, ValueError):
        raise BambuExecError(
            "sequence_id must be numeric") from None
    return {"print": {
        "sequence_id": str(sequence),
        "command": "project_file",
        "param": "Metadata/plate_1.gcode",
        "project_id": "0",
        "profile_id": "",
        "task_id": clean_task,
        "subtask_id": clean_task,
        "subtask_name": str(subtask_name or "")[:120],
        "url": f"ftp://{name}",
        "file": name,
        "md5": "",
        "bed_type": str(bed_type or "auto")[:40],
        "bed_leveling": bool(bed_leveling),
        "flow_cali": bool(flow_cali),
        "vibration_cali": bool(vibration_cali),
        "timelapse": bool(timelapse),
        "use_ams": bool(use_ams),
        "ams_mapping": mapping,
        "ams_mapping2": mapping2,
    }}


def publish_request(client, serial: str, payload: dict,
                    qos: int = 1):
    """Publish one allow-listed request. ONLY {"print": {...}}
    payloads to the exact device request topic. Anything else
    refuses — this is the single control gate of M4.2."""
    if not isinstance(payload, dict) or set(payload.keys()) != \
            {"print"} or not isinstance(payload["print"], dict):
        raise BambuExecError(
            "only {print:{...}} payloads may publish; refusing")
    clean_serial = str(serial or "").strip()
    if not clean_serial:
        raise BambuExecError("serial is required")
    topic = f"device/{clean_serial}/request"
    import json as _json
    try:
        info = client.publish(topic, _json.dumps(payload), qos=qos)
    except Exception as error:
        raise BambuExecUnavailable(
            f"publish failed ({error})") from error
    if int(getattr(info, "rc", 0) or 0) != 0:
        raise BambuExecUnavailable(
            f"publish refused (rc={getattr(info, 'rc', '?')})")
    return info


#: Bambu resource triplet for project_settings (read-only local
#: files; missing combinations refuse instead of guessing).
BAMBU_RESOURCES = ("C:/Program Files/Bambu Studio/resources"
                   "/profiles/BBL")
BAMBU_MACHINE_JSON = "machine/Bambu Lab A1 mini 0.4 nozzle.json"
BAMBU_PROCESS_JSON = {
    0.12: "process/0.12mm Fine @BBL A1M.json",
    0.20: "process/0.20mm Standard @BBL A1M.json",
    0.28: "process/0.20mm Standard @BBL A1M.json",
}
BAMBU_FILAMENT_JSON = {
    "PLA": "filament/Bambu PLA Basic @BBL A1M.json",
    "PETG": "filament/Bambu PETG HF @BBL A1M.json",
}

#: Common color names to RRGGBB for the filament element. Unknown
#: names degrade to white, recorded as such (display only).
COLOR_HEX = {
    "white": "#FFFFFF", "wit": "#FFFFFF",
    "black": "#000000", "zwart": "#000000",
    "red": "#FF0000", "rood": "#FF0000",
    "green": "#00FF00", "groen": "#00FF00",
    "blue": "#0000FF", "blauw": "#0000FF",
    "yellow": "#FFFF00", "geel": "#FFFF00",
    "orange": "#FF8000", "oranje": "#FF8000",
    "grey": "#808080", "gray": "#808080", "grijs": "#808080",
    "silver": "#C0C0C0", "zilver": "#C0C0C0",
    "pink": "#FFC0CB", "roze": "#FFC0CB",
    "purple": "#800080", "paars": "#800080",
    "brown": "#A52A2A", "bruin": "#A52A2A",
}


def bambu_base_settings(material: str, layer_mm: float,
                        resources: str = BAMBU_RESOURCES,
                        ) -> tuple[dict, dict]:
    """Merge the bundled Bambu machine+process+filament JSONs.

    Returns (merged_settings, files_used). Anything missing
    refuses instead of inventing keys — the printer reads real
    Bambu keyspace, never synthetic guesses.
    """
    import json as _json
    material = str(material or "").strip().upper()
    try:
        layer = float(layer_mm or 0)
    except (TypeError, ValueError):
        raise BambuExecError(
            "layer_mm must be numeric") from None
    process_rel = BAMBU_PROCESS_JSON.get(
        0.12 if layer <= 0.16 else 0.20)
    filament_rel = BAMBU_FILAMENT_JSON.get(material)
    if filament_rel is None:
        raise BambuExecError(
            f"no bundled Bambu filament profile for '{material}'; "
            f"refusing (supported: "
            f"{sorted(BAMBU_FILAMENT_JSON)})")
    merged: dict = {}
    used: dict = {}
    for label, rel in (("machine", BAMBU_MACHINE_JSON),
                       ("process", process_rel),
                       ("filament", filament_rel)):
        path = _os.path.join(resources, rel)
        try:
            with open(path, encoding="utf-8") as handle:
                data = _json.load(handle)
        except (OSError, ValueError) as error:
            raise BambuExecUnavailable(
                f"Bambu resource missing ({rel}: {error})") from error
        if isinstance(data, dict):
            merged.update(data)
        used[label] = rel
    return merged, used


def _slot_global(slot_label: str) -> tuple[int, int]:
    """'AMS-N' (1..4) on the single AMS (id 0) -> (global, slot).
    Empty label means shelf/external: handled by the caller."""
    match = _re.match(r"(?i)^ams-([1-8])$", str(slot_label or ""))
    if not match:
        raise BambuExecError(
            f"slot '{str(slot_label)[:12]}' is not AMS-N (1..8); "
            f"refusing")
    index = int(match.group(1)) - 1
    return index, index


def execute_bambu_job(adapter, device, job, *,
                      timeout: float = START_CONFIRM_SECONDS,
                      progress=None, dial=None) -> dict:
    """Upload + start one approved print (M4.2, operator-gated).

    The caller (fab_flow.execute_print, post-YES + revalidated)
    owns approval; this function owns the physical handshake:
    re-hash bytes, build plate .3mf, FTPS upload + SIZE verify,
    project_file publish, confirm start via telemetry. Returns a
    started-telemetry dict (never completed — completion is
    observed separately). Raises BambuExecError/Unavailable with
    the failing stage named. ``dial`` injects the FTPS transport
    (tests); production uses real sockets.
    """
    import hashlib as _hashlib
    import json as _json
    from .local_slicer import build_plate_3mf
    from .mesh3d import read_artifact_bytes
    from .slicer3d import check_profile
    gcode_ref = str(getattr(job, "gcode_ref", "") or "")
    want_sha = str(getattr(job, "gcode_sha256", "") or "")
    profile_name = str(getattr(job, "profile", "") or "")
    if not gcode_ref or len(want_sha) != 64:
        raise BambuExecError("job carries no G-code with sha")
    try:
        raw = read_artifact_bytes(gcode_ref)
    except ValueError as error:
        raise BambuExecError(f"G-code unreadable ({error})") from error
    text = raw.decode("ascii", errors="replace")
    got_sha = _hashlib.sha256(raw).hexdigest()
    if got_sha != want_sha:
        raise BambuExecError(
            "G-code changed since approval (fingerprint mismatch); "
            "refusing")
    try:
        settings = check_profile(profile_name)
    except ValueError as error:
        raise BambuExecError(str(error)) from error
    material = str(settings.get("material", "") or "")
    try:
        layer = float(settings.get("layer_mm", 0) or 0)
    except (TypeError, ValueError):
        raise BambuExecError("profile layer_mm invalid") from None
    base, files_used = bambu_base_settings(material, layer)
    facts = footer_facts(text, None)
    weight = facts["weight_g"]
    if weight is None:
        from .fabrication import FILAMENT_DENSITIES
        density = FILAMENT_DENSITIES.get(material)
        cm3 = facts["cm3"]
        weight = round(cm3 * float(density), 2) \
            if cm3 is not None and density else 0.0
    spool_id = str(getattr(job, "spool_id", "") or "")
    slot_label = str(getattr(job, "slot", "") or "")
    ams_mapping: list[int] = []
    ams_mapping2: list[dict] = []
    use_ams = False
    if slot_label:
        _, index = _slot_global(slot_label)
        ams_mapping = [index]
        ams_mapping2 = [{"ams_id": 0, "slot_id": index}]
        use_ams = True
    else:
        ams_mapping = [-1]
    try:
        stem = gcode_ref.rsplit(".", 1)[0].split("/")[-1][:60] \
            or "model"
        archive = build_plate_3mf(
            raw, profile_name=profile_name, material=material,
            weight_g=weight or 0.0,
            prediction_s=facts["prediction_s"],
            support_used=bool(settings.get("supports", False)),
            base_settings=base)
    except ValueError as error:
        raise BambuExecError(str(error)) from error
    short = want_sha[:8]
    remote = sanitize_3mf_name(f"{stem}-{profile_name}-{short}"
                               f".gcode.3mf")
    host = str(getattr(adapter, "mqtt_host", "") or "")
    access_code = str(getattr(adapter, "mqtt_password", "") or "")
    serial = str(getattr(adapter, "printer_serial", "") or "")
    if not host or not access_code or not serial:
        raise BambuExecError(
            "adapter carries no connection identity; refusing")
    uploaded = ftps_upload(host, BAMBU_FTPS_PORT, BAMBU_FTPS_USER,
                           access_code, remote, archive,
                           dial=dial)
    if progress is not None:
        try:
            progress("uploaded")
        except Exception:
            pass
    payload = project_file_payload(
        filename=remote, task_id=str(getattr(job, "job_id", "")),
        subtask_name=stem, ams_mapping=ams_mapping,
        ams_mapping2=ams_mapping2, use_ams=use_ams)
    client = getattr(adapter, "client", None)
    if client is None or not getattr(adapter, "is_connected", False):
        raise BambuExecUnavailable(
            "MQTT session not connected; refusing start")
    publish_request(client, serial, payload)
    if progress is not None:
        try:
            progress("published")
        except Exception:
            pass
    confirmed = observe_printer_job(
        adapter, stem=stem, timeout=timeout, poll_seconds=5.0)
    if not confirmed.get("match") or confirmed.get("state") not in (
            "running", "completed"):
        raise BambuExecUnavailable(
            "start published but printer never confirmed our job "
            f"({confirmed.get('state', '?')}); verify on device, "
            f"nothing assumed started")
    return {
        "remote_name": remote,
        "size_bytes": len(archive),
        "gcode_sha256": want_sha,
        "subtask_name": stem,
        "sequence_id": payload["print"]["sequence_id"],
        "profile_files": files_used,
        "weight_g": weight,
        "published": True,
        "confirmed": confirmed.get("state"),
    }


def observe_printer_job(adapter, *, stem: str,
                        timeout: float = 60.0,
                        poll_seconds: float = 5.0) -> dict:
    """One bounded observation round: read live telemetry and map
    it onto OUR job (matched by filename stem). Pure read;
    mutates nothing. Returns {"match", "state", "telemetry"} with
    state in started/running/completed/failed/not-ours/timeout.
    """
    import time as _t
    wanted = str(stem or "")
    if not wanted:
        raise BambuExecError("stem is required to match a job")
    try:
        budget = max(5.0, float(timeout))
    except (TypeError, ValueError):
        budget = 60.0
    try:
        interval = min(max(1.0, float(poll_seconds)), 30.0)
    except (TypeError, ValueError):
        interval = 5.0
    deadline = _t.monotonic() + budget
    seen_running = False
    last: dict = {}
    while True:
        try:
            live = adapter._live_status()
            pushes = int(getattr(adapter, "_pushes", 0) or 0)
        except Exception:
            live, pushes = {}, 0
        job_name = str(live.get("job_name", "") or "")
        gcode_state = str(live.get("gcode_state", "") or "")
        last = {"job_name": job_name, "gcode_state": gcode_state,
                "progress_pct": live.get("progress_pct"),
                "remaining_min": live.get("remaining_min"),
                "nozzle_c": live.get("nozzle_c"),
                "bed_c": live.get("bed_c"),
                "print_error": live.get("print_error", 0),
                "pushes": pushes}
        mine = wanted.lower() in job_name.lower() and bool(job_name)
        if mine and gcode_state in ("PREPARE", "RUNNING", "PAUSE",
                                    "SLICING"):
            seen_running = True
            return {"match": True, "state": "running",
                    "telemetry": last}
        if mine and gcode_state == "FINISH":
            return {"match": True, "state": "completed",
                    "telemetry": last}
        if mine and gcode_state == "FAILED":
            return {"match": True, "state": "failed",
                    "telemetry": last}
        if seen_running and mine and gcode_state == "IDLE":
            return {"match": True, "state": "ended-unknown",
                    "telemetry": last}
        if _t.monotonic() >= deadline:
            return {"match": bool(mine), "state": "timeout",
                    "telemetry": last}
        _t.sleep(interval)


def stop_bambu_job(adapter, *, timeout: float = STOP_CONFIRM_SECONDS,
                   progress=None) -> dict:
    """Publish stop and confirm IDLE (bounded). Operator-gated
    cancel path only. Raises on timeout without confirming."""
    import time as _t
    try:
        budget = max(10.0, float(timeout))
    except (TypeError, ValueError):
        budget = STOP_CONFIRM_SECONDS
    client = getattr(adapter, "client", None)
    serial = str(getattr(adapter, "printer_serial", "") or "")
    if client is None or not getattr(adapter, "is_connected", False):
        raise BambuExecUnavailable(
            "MQTT session not connected; refusing stop")
    sequence = int(_t.time()) % 2**31
    publish_request(client, serial, {"print": {
        "sequence_id": str(sequence), "command": "stop"}})
    if progress is not None:
        try:
            progress("stop-published")
        except Exception:
            pass
    deadline = _t.monotonic() + budget
    while True:
        try:
            live = adapter._live_status()
            state = str(live.get("gcode_state", "") or "")
        except Exception:
            state = ""
        if state == "IDLE":
            return {"stopped": True, "sequence_id": str(sequence)}
        if _t.monotonic() >= deadline:
            raise BambuExecUnavailable(
                "stop published but printer never confirmed IDLE; "
                "verify on the device")
        _t.sleep(5.0)
