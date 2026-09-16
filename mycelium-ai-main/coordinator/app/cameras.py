"""Generic camera abstraction (BIG #4).

One interface for every camera Mycelium may ever meet — snapshot
stills today, an Insta360 (photo, webcam, live, 360) tomorrow.
Kinds are explicit per device; nothing is assumed:

- snapshot: one still image -> observation (the only active mode)
- webcam: local video source for UI/vision consumers (registered,
  not opened, until a reviewed capture runtime exists)
- stream: local stream to an authorized consumer (same: registered)
- p360: 360° media for viewer/VLM (same: registered)

Rules (tested, all fail-closed):

- CameraDevice pins device_id (cam-*), name, kinds (closed
  literal, no wildcards), source (manual/usb/insta360/phone) and
  status. Unknown kinds/sources are refused at registration.
- Cameras are observation sources, never actuators: this module
  has no capture, network or shell surface. A snapshot only
  happens through an injected CameraAdapter; without one the
  endpoint refuses (409) instead of fabricating bytes.
- CameraObservation reuses the observation vocabulary
  (observation_id obs-*, timestamp, dimensions, local media
  reference, sensor-observed/unverified provenance) and binds
  device + capture kind + optional INVENTory file reference.
  No automatic AI interpretation as FACT, no cloud upload.
- Media lives under the local temp camera directory with the
  same retention discipline as screenshots (latest N kept).
- detect_local_imaging_devices() enumerates Windows image devices
  read-only (names only, ctypes/setupapi, no capture, no stream);
  elsewhere it returns [] with a reason. Discovery never activates
  anything and never leaves the machine.
- TestCameraAdapter exists for tests ONLY (clearly named, writes
  a minimal BMP via the shared writer); production registers no
  adapter until a reviewed runtime lands (Insta360 phases in
  docs/camera-architecture.md).
"""

import ctypes
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .database import chat_connection, init_chat_database
from .desktop_runtime import write_bmp_24
from .inventory_read import Provenance
from .observations import check_image_ref

CameraKind = Literal["snapshot", "webcam", "stream", "p360"]
VALID_KINDS = frozenset({"snapshot", "webcam", "stream", "p360"})

CameraSource = Literal["manual", "usb", "insta360", "phone"]
VALID_SOURCES = frozenset({"manual", "usb", "insta360", "phone"})

CAMERA_CAPABILITIES = {
    "snapshot": "camera.snapshot",
    "webcam": "camera.webcam",
    "stream": "camera.stream",
    "p360": "camera.360",
}

CAMERA_DIR_NAME = "mycelium-cam"
CAMERA_RETENTION = 5
MAX_NAME_CHARS = 120


class CameraUnavailable(RuntimeError):
    """No capture path for this device. Fail-closed, never fake bytes."""


class CameraRefusedError(ValueError):
    """Local validation refused; nothing touched any device."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CameraDevice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    kinds: list[str] = Field(min_length=1, max_length=4)
    source: str = Field(min_length=1, max_length=20)
    status: str = Field(default="registered", max_length=20)
    notes: str = Field(default="", max_length=500)
    created_at: str = ""


class CameraObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(min_length=3, max_length=80)
    device_id: str = Field(min_length=3, max_length=80)
    kind: str = Field(min_length=1, max_length=20)
    media_ref: str = Field(default="", max_length=200)
    width: int = Field(default=0, ge=0, le=16384)
    height: int = Field(default=0, ge=0, le=16384)
    file_id: str = Field(default="", max_length=80)
    created_at: str = ""
    provenance: Provenance = Field(default_factory=Provenance)


def check_kinds(kinds) -> list[str]:
    if not isinstance(kinds, (list, tuple)) or not kinds:
        raise CameraRefusedError("Camera needs at least one kind")
    cleaned = []
    for kind in kinds:
        if not isinstance(kind, str) or kind.strip() not in VALID_KINDS:
            raise CameraRefusedError(
                f"Unknown camera kind '{kind}'; expected snapshot, "
                "webcam, stream or p360")
        if kind.strip() not in cleaned:
            cleaned.append(kind.strip())
    return cleaned


def new_device(device_id: str, name: str, kinds, source: str,
               notes: str = "") -> CameraDevice:
    if source not in VALID_SOURCES:
        raise CameraRefusedError(
            f"Unknown camera source '{source}'; expected manual, usb, "
            "insta360 or phone")
    if not isinstance(name, str) or not name.strip():
        raise CameraRefusedError("Camera name must be non-empty text")
    return CameraDevice(
        device_id=device_id, name=name.strip()[:MAX_NAME_CHARS],
        kinds=check_kinds(kinds), source=source,
        notes=str(notes or "")[:500], created_at=now())


def new_observation(observation_id: str, device_id: str, kind: str, *,
                    media_ref: str = "", width: int = 0,
                    height: int = 0,
                    file_id: str = "") -> CameraObservation:
    if kind not in VALID_KINDS:
        raise CameraRefusedError(f"Unknown camera kind '{kind}'")
    try:
        reference = check_image_ref(media_ref) if media_ref else ""
    except ValueError as error:
        raise CameraRefusedError(str(error)) from error
    if file_id and not file_id.startswith("file_"):
        raise CameraRefusedError("file_id must be an INVENTory file id")
    return CameraObservation(
        observation_id=observation_id, device_id=device_id, kind=kind,
        media_ref=reference, width=width, height=height,
        file_id=file_id, created_at=now(),
        provenance=Provenance(
            source_type="sensor-observed",
            creator_id=f"camera:{device_id}",
            human_verified=False,
            notes="camera capture metadata; pixels local only, "
                  "never auto-interpreted as fact",
        ),
    )


def camera_dir() -> str:
    path = os.path.join(tempfile.gettempdir(), CAMERA_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def prune_captures(keep: int = CAMERA_RETENTION) -> int:
    try:
        entries = os.listdir(camera_dir())
    except OSError:
        return 0
    shots = sorted(entry for entry in entries
                   if entry.startswith("cam-")
                   and entry.lower().endswith((".bmp", ".png")))
    removed = 0
    for entry in shots[:max(0, len(shots) - keep)]:
        try:
            os.remove(os.path.join(camera_dir(), entry))
            removed += 1
        except OSError:
            continue
    return removed


class CameraAdapter:
    """Capture contract. Production adapters arrive per reviewed
    runtime; the core ships none (fail-closed without one)."""

    name = "base"

    def snapshot(self, device: CameraDevice) -> CameraObservation:
        raise NotImplementedError


class TestCameraAdapter(CameraAdapter):
    """TESTS ONLY. Writes a minimal BMP, never touches hardware."""

    name = "test-only"

    def __init__(self, width: int = 64, height: int = 48):
        self.width = width
        self.height = height

    def snapshot(self, device: CameraDevice) -> CameraObservation:
        observation_id = f"obs-{int(time.time() * 1000):x}"
        filename = f"cam-{observation_id[4:]}.bmp"
        pixels = b"\x20\x40\x60" * (self.width * self.height)
        write_bmp_24(os.path.join(camera_dir(), filename),
                     self.width, self.height, pixels)
        prune_captures()
        return new_observation(observation_id, device.device_id,
                               "snapshot", media_ref=filename,
                               width=self.width, height=self.height)


def take_snapshot(device: CameraDevice,
                  adapter: CameraAdapter | None) -> CameraObservation:
    """Capture one still. No adapter, no bytes — ever."""
    if not isinstance(device, CameraDevice):
        raise CameraRefusedError("Snapshot needs a CameraDevice")
    if "snapshot" not in device.kinds:
        raise CameraRefusedError(
            f"Device '{device.device_id}' has no snapshot capability")
    if adapter is None:
        raise CameraUnavailable(
            f"No capture runtime for '{device.device_id}'; refusing "
            "instead of fabricating image data")
    if not isinstance(adapter, CameraAdapter):
        raise CameraRefusedError("Unknown adapter type")
    observation = adapter.snapshot(device)
    if (not isinstance(observation, CameraObservation)
            or observation.device_id != device.device_id):
        raise CameraUnavailable("Adapter returned an invalid observation")
    return observation


# -- registry (chat/agent database; world data stays in INVENTory) ------

def save_device(device: CameraDevice) -> None:
    from .database import dump
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO camera_devices
        (device_id, record, created_at) VALUES (?, ?, ?)
        ON CONFLICT(device_id) DO UPDATE SET record=excluded.record""",
                   (device.device_id,
                    dump(device.model_dump(mode="json")),
                    device.created_at or now()))


def list_devices() -> list[CameraDevice]:
    from .database import load
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute(
            "SELECT record FROM camera_devices ORDER BY created_at").fetchall()
    return [CameraDevice.model_validate(load(row["record"]))
            for row in rows]


def get_device(device_id: str) -> CameraDevice | None:
    from .database import load
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT record FROM camera_devices "
                         "WHERE device_id=?", (device_id,)).fetchone()
    if row is None:
        return None
    return CameraDevice.model_validate(load(row["record"]))


def save_observation(observation: CameraObservation) -> None:
    from .database import dump
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO camera_observations
        (observation_id, device_id, record, created_at)
        VALUES (?, ?, ?, ?)""",
                   (observation.observation_id, observation.device_id,
                    dump(observation.model_dump(mode="json")),
                    observation.created_at or now()))


def list_observations(device_id: str,
                      limit: int = 20) -> list[CameraObservation]:
    from .database import load
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute(
            """SELECT record FROM camera_observations WHERE device_id=?
            ORDER BY created_at DESC LIMIT ?""",
            (device_id, max(1, min(limit, 50)))).fetchall()
    return [CameraObservation.model_validate(load(row["record"]))
            for row in rows]


# -- read-only local discovery (names only, never activation) -----------

def detect_local_imaging_devices() -> dict:
    """Enumerate local imaging devices by name. Read-only discovery:
    no capture, no stream, no activation, nothing leaves the machine.
    Non-Windows platforms honestly report unsupported.
    """
    if os.name != "nt":
        return {"supported": False, "devices": [],
                "reason": "local discovery needs Windows"}
    try:
        found = _windows_image_devices()
    except (AttributeError, OSError) as error:
        return {"supported": False, "devices": [],
                "reason": f"enumeration failed: {error}"}
    return {"supported": True, "devices": found, "reason": ""}


def _windows_image_devices() -> list[dict[str, Any]]:
    """SetupDi enumeration of GUID_DEVINTERFACE_IMAGE, names only."""
    setupapi = ctypes.windll.setupapi
    # GUID_DEVINTERFACE_IMAGE {6BDD1FC6-810F-11D0-BEC7-08002BE2092F},
    # little-endian byte order for the memmove below.
    guid_bytes = bytes([
        0xC6, 0x1F, 0xDD, 0x6B, 0x0F, 0x81, 0xD0, 0x11,
        0xBE, 0xC7, 0x08, 0x00, 0x2B, 0xE2, 0x09, 0x2F])

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong),
                    ("Data2", ctypes.c_ushort),
                    ("Data3", ctypes.c_ushort),
                    ("Data4", ctypes.c_ubyte * 8)]

    class DeviceInterfaceData(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong),
                    ("InterfaceClassGuid", GUID),
                    ("Flags", ctypes.c_ulong),
                    ("Reserved", ctypes.c_void_p)]

    guid = GUID()
    ctypes.memmove(ctypes.byref(guid), guid_bytes, 16)
    DIGCF_PRESENT = 0x00000002
    DIGCF_DEVICEINTERFACE = 0x00000010
    handle = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None,
        DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if handle in (None, 0, -1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
        raise OSError("SetupDiGetClassDevs failed")
    devices: list[dict[str, Any]] = []
    try:
        index = 0
        while True:
            data = DeviceInterfaceData()
            data.cbSize = ctypes.sizeof(DeviceInterfaceData)
            ok = setupapi.SetupDiEnumDeviceInterfaces(
                handle, None, ctypes.byref(guid), index,
                ctypes.byref(data))
            if not ok:
                break
            index += 1
            needed = ctypes.c_ulong(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                handle, ctypes.byref(data), None, 0,
                ctypes.byref(needed), None)
            size = needed.value
            if size < 8 or size > 8192:
                continue
            buffer = ctypes.create_string_buffer(size)
            buffer[0:4] = (8).to_bytes(4, "little")
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                    handle, ctypes.byref(data), buffer, size,
                    None, None):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buffer) + 4)
            devices.append({"path": path[:260], "source": "usb"})
            if len(devices) >= 16:
                break
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(handle)
    return devices
