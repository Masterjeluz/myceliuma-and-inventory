"""Controlled camera ingestion for Mycelium (BIG #6).

Sits on top of the BIG #4 camera abstraction (``cameras.py``) and
feeds the BIG #5 write/verification chain. Pipeline:

    camera -> capture -> local media -> observation (+ File payload)

States are explicit and never implied:

- registered: operator created the device entry;
- detected: local enumeration saw a matching imaging device
  (candidate only — an Insta360 in webcam mode shows up here);
- connected: an adapter session proved the device reachable
  (only adapters that actually open the device may claim this);
- capturable: a probe capture succeeded through the adapter;
- unavailable: anything else — and unavailable never yields bytes.

Rules (tested, all fail-closed):

- No adapter claims a capability it does not implement: the
  registry records per-adapter capabilities, and ingest checks
  device kinds against them before touching anything.
- No fake media: without a working adapter every capture path
  raises CameraUnavailable. The synthetic test adapter marks
  its provenance notes ``test-origin`` explicitly.
- Media stays local under the camera dir; only references and
  metadata travel further. Size-capped (MAX_MEDIA_BYTES);
  oversized files refuse. Retention follows the existing
  prune discipline (latest CAMERA_RETENTION kept).
- File registration is a payload, not an action: ingest returns
  an INVENTory File-create payload for the BIG #5 approval flow.
  Nothing here writes to INVENTory.
- Streams are local-only lifecycle objects (explicit start/stop,
  bounded frames/seconds, auto-expiry). No binding, no inbound
  ports, no relay, no permanent running.
"""

import hashlib
import os
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .cameras import (
    CAMERA_CAPABILITIES,
    CameraAdapter,
    CameraDevice,
    CameraObservation,
    CameraRefusedError,
    CameraUnavailable,
    TestCameraAdapter,
    camera_dir,
    new_observation,
    prune_captures,
    take_snapshot,
)
from .inventory_read import Provenance
from .observations import check_image_ref

#: States a camera can be in. Never implied, always probed or stated.
VALID_CAMERA_STATES = frozenset({
    "registered", "detected", "connected", "capturable", "unavailable",
})

#: Hard cap per media file (10 MiB). Bigger files refuse, never load.
MAX_MEDIA_BYTES = 10 * 1024 * 1024

#: Allowed local media suffixes (mirrors check_image_ref).
MEDIA_SUFFIXES = (".bmp", ".png", ".jpg", ".jpeg")

TEST_ORIGIN_MARK = "test-origin: synthetic media, never a real capture"


class IngestRefusedError(ValueError):
    """Local validation refused; no device was touched."""


class MediaRecord(BaseModel):
    """Local media facts: reference + hash + size. No pixels."""

    model_config = ConfigDict(extra="forbid")

    media_ref: str = Field(min_length=1, max_length=200)
    sha256: str = Field(min_length=64, max_length=64,
                        pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    mime_type: str = Field(default="", max_length=200)
    width: int = Field(default=0, ge=0, le=16384)
    height: int = Field(default=0, ge=0, le=16384)
    captured_at: str = ""


class IngestResult(BaseModel):
    """One ingested capture: observation + media facts + an inert
    File-create payload for the BIG #5 approval flow."""

    model_config = ConfigDict(extra="forbid")

    observation: CameraObservation
    media: MediaRecord
    file_payload: dict[str, Any] = Field(default_factory=dict)
    test_origin: bool = False


def _mime_for(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".bmp"):
        return "image/bmp"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    return "application/octet-stream"


def media_facts(media_ref: str, *, width: int = 0,
                height: int = 0) -> MediaRecord:
    """Hash and measure one local media file. Fail-closed on every
    boundary: plain filename only, inside the camera dir, capped
    size, known suffix."""
    try:
        reference = check_image_ref(media_ref)
    except ValueError as error:
        raise IngestRefusedError(str(error)) from error
    if not reference:
        raise IngestRefusedError("Ingest needs a media reference")
    root = os.path.abspath(camera_dir())
    path = os.path.abspath(os.path.join(root, reference))
    if path != root and not path.startswith(root + os.sep):
        raise IngestRefusedError("Media escapes the camera directory")
    if not os.path.isfile(path):
        raise IngestRefusedError(
            f"Media '{reference}' does not exist; refusing")
    size = os.path.getsize(path)
    if size <= 0:
        raise IngestRefusedError("Media is empty; refusing")
    if size > MAX_MEDIA_BYTES:
        raise IngestRefusedError(
            f"Media is {size} bytes (max {MAX_MEDIA_BYTES}); refusing")
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    from datetime import datetime, timezone
    return MediaRecord(
        media_ref=reference, sha256=digest.hexdigest(),
        size_bytes=size, mime_type=_mime_for(reference),
        width=width, height=height,
        captured_at=datetime.now(timezone.utc).isoformat())


def file_payload_for(media: MediaRecord, name: str,
                     device_id: str) -> dict:
    """Inert INVENTory File-create payload for one captured media.
    Returned, never sent: registration runs through BIG #5 approval."""
    if not isinstance(name, str) or not name.strip():
        raise IngestRefusedError("File name must be non-empty text")
    return {
        "name": name.strip()[:200],
        "file_kind": "image",
        "mime_type": media.mime_type,
        "sha256": media.sha256,
        "size_bytes": media.size_bytes,
        "description": (f"Camera capture {media.media_ref} "
                        f"({media.width}x{media.height})"),
        "status": "available",
        "metadata": {"media_ref": media.media_ref,
                     "device_id": device_id,
                     "width": media.width,
                     "height": media.height},
    }


def ingest_snapshot(device: CameraDevice,
                    adapter: CameraAdapter | None, *,
                    test_origin: bool = False) -> IngestResult:
    """Capture one still and ingest it: observation + media facts +
    inert File payload. No adapter (or a failing one) refuses."""
    if not isinstance(device, CameraDevice):
        raise IngestRefusedError("Ingest needs a CameraDevice")
    observation = take_snapshot(device, adapter)
    if test_origin:
        observation = observation.model_copy(update={
            "provenance": Provenance(
                source_type="sensor-observed",
                creator_id=f"camera:{device.device_id}",
                human_verified=False,
                notes="camera capture metadata; " + TEST_ORIGIN_MARK,
            )})
    media = media_facts(observation.media_ref,
                        width=observation.width,
                        height=observation.height)
    prune_captures()
    payload = file_payload_for(
        media, f"{device.device_id}-{observation.observation_id}",
        device.device_id)
    return IngestResult(observation=observation, media=media,
                        file_payload=payload,
                        test_origin=test_origin)


def probe_availability(device: CameraDevice,
                       adapter: CameraAdapter | None,
                       detected: bool = False) -> dict:
    """Report the honest state of one camera. Never claims
    capturable without proof; never activates anything."""
    if not isinstance(device, CameraDevice):
        raise IngestRefusedError("Probe needs a CameraDevice")
    if adapter is None:
        return {"device_id": device.device_id,
                "state": "registered" if not detected else "detected",
                "capturable": False,
                "reason": "no capture adapter registered"}
    if not isinstance(adapter, CameraAdapter):
        raise IngestRefusedError("Unknown adapter type")
    if isinstance(adapter, UnavailableAdapterMixin):
        return {"device_id": device.device_id,
                "state": "detected" if detected else "registered",
                "capturable": False,
                "reason": adapter.unavailable_reason()}
    if "snapshot" not in device.kinds:
        return {"device_id": device.device_id,
                "state": "connected",
                "capturable": False,
                "reason": "device has no snapshot capability"}
    return {"device_id": device.device_id,
            "state": "connected",
            "capturable": CAMERA_CAPABILITIES["snapshot"] in
            adapter_capabilities(adapter),
            "reason": ""}


def adapter_capabilities(adapter: CameraAdapter) -> list[str]:
    """Capabilities one adapter actually implements (closed set)."""
    claimed = list(getattr(adapter, "capabilities", []) or [])
    return [cap for cap in claimed if cap in CAMERA_CAPABILITIES.values()]


# -- adapters ------------------------------------------------------------

class UnavailableAdapterMixin:
    """Explicit unavailable stub. Complete interface, zero capture."""

    def unavailable_reason(self) -> str:
        raise NotImplementedError


class WindowsWebcamAdapter(CameraAdapter, UnavailableAdapterMixin):
    """Windows webcam stub: interface complete, capture unavailable.

    A safe first capture path needs a reviewed MediaFoundation /
    DirectShow runtime (device open, frame grab, format negotiation,
    timeout handling) — none of which exists here. Until that
    runtime lands reviewed, this adapter refuses with an explicit
    reason instead of guessing at ctypes capture calls.
    """

    name = "windows-webcam-stub"
    capabilities = ["camera.webcam"]

    def unavailable_reason(self) -> str:
        return ("no reviewed Windows capture runtime; snapshot "
                "needs a MediaFoundation/DirectShow implementation "
                "with device open, frame grab and timeout handling")

    def snapshot(self, device: CameraDevice) -> CameraObservation:
        raise CameraUnavailable(self.unavailable_reason())

    @classmethod
    def requirements(cls) -> str:
        return (
            "Windows capture needs: 1) IMFSourceReader-based device "
            "open over the imaging-device path, 2) first-frame grab "
            "with a hard timeout, 3) BMP/PNG encode via the existing "
            "writer, 4) no device activation outside an approved "
            "capture call. None of this ships in BIG #6.")


class Insta360Adapter(CameraAdapter, UnavailableAdapterMixin):
    """Insta360 foundation: identity + states, no guessed capture.

    Models source=insta360 with kinds snapshot/webcam/stream/p360
    claimed ONLY per implemented flags (default: none implemented,
    so every capture refuses). Connection states:

    - registered: operator created the device entry;
    - detected: local enumeration saw a candidate path (heuristic
      substring match, documented below — a candidate, never proof);
    - connected: a real session proved reachability (no path to
      this state exists yet — needs a reviewed transport);
    - capturable: a probe capture succeeded (same: not reachable).

    No SDK/API is assumed. What real integration needs is listed
    in requirements(): typically the Insta360 webcam-mode driver
    (then it appears as a USB imaging device and the Windows
    runtime above applies) or a reviewed file-ingest path for
    camera-stored photo/360 media.
    """

    name = "insta360-foundation"

    def __init__(self, implemented: list[str] | None = None):
        self.capabilities = [cap for cap in (implemented or [])
                             if cap in CAMERA_CAPABILITIES.values()]

    def unavailable_reason(self) -> str:
        return ("no reviewed Insta360 transport; webcam-mode needs "
                "the vendor driver plus the Windows capture runtime, "
                "file-mode needs a reviewed media-ingest path")

    def snapshot(self, device: CameraDevice) -> CameraObservation:
        raise CameraUnavailable(self.unavailable_reason())

    @staticmethod
    def match_detected(devices: list[dict]) -> list[dict]:
        """Heuristic candidate match over enumerated imaging devices.

        Substring 'insta360' in path or name. Returns CANDIDATES
        for the operator to confirm — never a connection, never
        proof of capturability.
        """
        candidates = []
        for entry in devices or []:
            if not isinstance(entry, dict):
                continue
            haystack = (f"{entry.get('path', '')} "
                        f"{entry.get('name', '')}").lower()
            if "insta360" in haystack:
                candidates.append({**entry, "candidate": "insta360",
                                   "state": "detected"})
        return candidates

    @classmethod
    def requirements(cls) -> str:
        return (
            "Real Insta360 capture needs one reviewed path: (a) "
            "webcam-mode via the vendor driver -> the camera appears "
            "as a USB imaging device -> Windows capture runtime "
            "applies; or (b) file-mode -> operator connects storage "
            "-> reviewed media-ingest copies named files into the "
            "camera dir with hash verification. BIG #6 ships neither; "
            "both need explicit review before bytes flow.")


class SyntheticTestAdapter(TestCameraAdapter):
    """Deterministic test adapter. Test-origin is always marked."""

    name = "synthetic-test"

    def __init__(self, width: int = 64, height: int = 48,
                 fail: bool = False):
        super().__init__(width=width, height=height)
        self.capabilities = ["camera.snapshot"]
        self._fail = fail

    def snapshot(self, device: CameraDevice) -> CameraObservation:
        if self._fail:
            from .cameras import CameraUnavailable as Unavail
            raise Unavail("synthetic failure (test)")
        return super().snapshot(device)


class FileIngestAdapter(CameraAdapter):
    """Reviewed file-ingest path (BIG #31): the operator copies
    camera files (Insta360 storage, phone, USB) into the camera
    dir; this adapter turns one NAMED file into an observation.

    REAL for file-mode; direct hardware transport stays
    UNAVAILABLE. Fail-closed: plain filename only (check_image_ref),
    inside the camera dir, capped size, known suffix. Provenance
    says file-ingest explicitly — never a live capture.
    """

    name = "file-ingest"

    def __init__(self, filename: str):
        from .observations import check_image_ref as _check
        try:
            reference = _check(filename)
        except ValueError as error:
            raise IngestRefusedError(str(error)) from error
        if not reference:
            raise IngestRefusedError(
                "File ingest needs a media filename")
        import os as _os
        root = _os.path.abspath(camera_dir())
        path = _os.path.abspath(_os.path.join(root, reference))
        if path != root and not path.startswith(root + _os.sep):
            raise IngestRefusedError(
                "Media escapes the camera directory")
        if not _os.path.isfile(path):
            raise IngestRefusedError(
                f"Media '{reference}' is not in the camera inbox; "
                "copy the file there first")
        size = _os.path.getsize(path)
        if size <= 0:
            raise IngestRefusedError("Media is empty; refusing")
        if size > MAX_MEDIA_BYTES:
            raise IngestRefusedError(
                f"Media is {size} bytes (max {MAX_MEDIA_BYTES}); "
                "refusing")
        self.filename = reference
        self.capabilities = ["camera.snapshot"]

    def snapshot(self, device: CameraDevice) -> CameraObservation:
        import time as _time
        if "snapshot" not in device.kinds:
            raise IngestRefusedError(
                f"Device '{device.device_id}' has no snapshot kind")
        observation_id = f"obs-{int(_time.time() * 1000):x}"
        from .cameras import new_observation as _new_obs
        observation = _new_obs(
            observation_id, device.device_id, "snapshot",
            media_ref=self.filename)
        notes = str(observation.provenance.notes or "")
        return observation.model_copy(update={
            "provenance": observation.provenance.model_copy(update={
                "notes": (notes + " | file-ingest: operator-provided "
                          f"file '{self.filename}'; not a live "
                          "capture").strip(" |")})})


def list_inbox_files(limit: int = 100) -> list[dict]:
    """Operator-visible media inbox: files in the camera dir with
    known suffixes. Names only + size; never pixels."""
    import os as _os
    count = max(1, min(int(limit or 100), 200))
    try:
        entries = _os.listdir(camera_dir())
    except OSError:
        return []
    out = []
    for entry in sorted(entries):
        lowered = entry.lower()
        if not lowered.endswith(MEDIA_SUFFIXES):
            continue
        try:
            size = _os.path.getsize(
                _os.path.join(camera_dir(), entry))
        except OSError:
            continue
        out.append({"filename": entry, "size_bytes": size,
                    "origin": "capture" if entry.startswith("cam-")
                    else "inbox"})
        if len(out) >= count:
            break
    return out


# -- adapter registry (empty in production: fail-closed) ------------------

_ADAPTERS: dict[str, CameraAdapter] = {}


def register_adapter(device_id: str, adapter: CameraAdapter) -> None:
    if not isinstance(adapter, CameraAdapter):
        raise IngestRefusedError("Only CameraAdapter entries register")
    _ADAPTERS[device_id] = adapter


def unregister_adapter(device_id: str) -> None:
    _ADAPTERS.pop(device_id, None)


def adapter_for(device_id: str) -> CameraAdapter | None:
    return _ADAPTERS.get(device_id)


def clear_adapters() -> None:
    _ADAPTERS.clear()


# -- local-only stream sessions (lifecycle foundation, no transport) -----

class StreamSession(BaseModel):
    """One bounded local stream. Metadata lifecycle only: explicit
    start/stop, frame budget, time budget, auto-expiry. No socket,
    no binding, no relay — frames flow only to a future local
    consumer through a reviewed adapter."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=3, max_length=80)
    device_id: str = Field(min_length=3, max_length=80)
    status: str = Field(default="open", max_length=20)
    max_frames: int = Field(default=100, ge=1, le=10000)
    max_seconds: int = Field(default=300, ge=1, le=3600)
    frames_captured: int = Field(default=0, ge=0)
    started_at: float = 0.0
    stopped_at: float = 0.0
    stop_reason: str = Field(default="", max_length=200)


class StreamManager:
    """Owns stream sessions. Expired or over-budget sessions can
    never tick again; a session that is not explicitly stopped
    expires instead of running forever."""

    def __init__(self, now_fn=None):
        self._sessions: dict[str, StreamSession] = {}
        self._counter = 0
        self._now = now_fn or time.monotonic

    def start(self, device_id: str, kinds: list[str], *,
              max_frames: int = 100,
              max_seconds: int = 300) -> StreamSession:
        if "stream" not in (kinds or []):
            raise IngestRefusedError(
                f"Device '{device_id}' has no stream capability")
        try:
            frames = int(max_frames)
            seconds = int(max_seconds)
        except (TypeError, ValueError):
            raise IngestRefusedError("Stream budgets must be integers")
        if not 1 <= frames <= 10000 or not 1 <= seconds <= 3600:
            raise IngestRefusedError(
                "Stream budgets out of range (frames 1..10000, "
                "seconds 1..3600)")
        self._counter += 1
        session = StreamSession(
            session_id=f"stream-{self._counter:04d}",
            device_id=device_id, status="open",
            max_frames=frames, max_seconds=seconds,
            started_at=self._now())
        self._sessions[session.session_id] = session
        return session

    def tick(self, session_id: str) -> StreamSession:
        """Record one captured frame interval. Expired sessions
        refuse instead of running on."""
        session = self._sessions.get(session_id)
        if session is None:
            raise IngestRefusedError(
                f"Stream '{session_id}' unknown")
        if session.status != "open":
            raise IngestRefusedError(
                f"Stream '{session_id}' is {session.status}; "
                "stopped streams never resume")
        elapsed = self._now() - session.started_at
        if elapsed > session.max_seconds:
            return self.stop(session_id, reason="time budget exceeded")
        if session.frames_captured + 1 > session.max_frames:
            return self.stop(session_id, reason="frame budget exceeded")
        updated = session.model_copy(update={
            "frames_captured": session.frames_captured + 1})
        self._sessions[session_id] = updated
        return updated

    def stop(self, session_id: str, reason: str = "operator stop"
             ) -> StreamSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise IngestRefusedError(
                f"Stream '{session_id}' unknown")
        if session.status != "open":
            return session
        updated = session.model_copy(update={
            "status": "stopped", "stopped_at": self._now(),
            "stop_reason": str(reason or "")[:200]})
        self._sessions[session_id] = updated
        return updated

    def get(self, session_id: str) -> StreamSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if (session.status == "open"
                and self._now() - session.started_at
                > session.max_seconds):
            return self.stop(session_id,
                              reason="time budget exceeded")
        return self._sessions[session_id]

    def list(self) -> list[StreamSession]:
        return [self.get(session.session_id)
                for session in self._sessions.values()]
