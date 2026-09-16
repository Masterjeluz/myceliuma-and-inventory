"""Vision ingestion tests (BIG #6).

Camera states, probe honesty, snapshot ingest with media facts,
File payloads, failure modes, adapter registry, stream lifecycle,
Insta360 foundation and the Windows webcam stub.
"""

import os

import pytest

from coordinator.app.cameras import (
    CameraUnavailable,
    camera_dir,
    new_device,
)
from coordinator.app.vision_ingest import (
    IngestRefusedError,
    Insta360Adapter,
    StreamManager,
    SyntheticTestAdapter,
    WindowsWebcamAdapter,
    adapter_capabilities,
    adapter_for,
    clear_adapters,
    file_payload_for,
    ingest_snapshot,
    media_facts,
    probe_availability,
    register_adapter,
    unregister_adapter,
)


def make_device(device_id="cam-test1", kinds=None, source="manual"):
    return new_device(device_id, "Testcam", kinds or ["snapshot"],
                      source)


def test_probe_without_adapter_is_honest():
    device = make_device()
    state = probe_availability(device, None)
    assert state["state"] == "registered"
    assert state["capturable"] is False
    detected = probe_availability(device, None, detected=True)
    assert detected["state"] == "detected"
    assert detected["capturable"] is False


def test_probe_with_test_adapter_connected():
    device = make_device()
    state = probe_availability(device, SyntheticTestAdapter())
    assert state["state"] == "connected"
    assert state["capturable"] is True


def test_probe_device_without_snapshot_capability():
    device = make_device(kinds=["webcam"])
    state = probe_availability(device, SyntheticTestAdapter())
    assert state["capturable"] is False
    assert "snapshot" in state["reason"]


def test_ingest_snapshot_marks_test_origin():
    device = make_device()
    result = ingest_snapshot(device, SyntheticTestAdapter(),
                             test_origin=True)
    assert result.test_origin is True
    assert "test-origin" in result.observation.provenance.notes
    assert result.observation.provenance.human_verified is False
    assert result.observation.device_id == "cam-test1"
    assert result.media.size_bytes > 0
    assert len(result.media.sha256) == 64
    assert result.file_payload["file_kind"] == "image"
    assert result.file_payload["sha256"] == result.media.sha256
    assert os.path.isfile(os.path.join(
        camera_dir(), result.media.media_ref))


def test_ingest_without_adapter_refuses():
    device = make_device()
    with pytest.raises(CameraUnavailable):
        ingest_snapshot(device, None)


def test_ingest_failing_adapter_refuses():
    device = make_device()
    with pytest.raises(CameraUnavailable):
        ingest_snapshot(device, SyntheticTestAdapter(fail=True))


def test_media_facts_boundaries():
    with pytest.raises(IngestRefusedError):
        media_facts("../buiten.bmp")
    with pytest.raises(IngestRefusedError):
        media_facts("http://x/y.png")
    with pytest.raises(IngestRefusedError):
        media_facts("foto.jpg")
    with pytest.raises(IngestRefusedError):
        media_facts("bestaat-niet.bmp")


def test_file_payload_needs_name():
    device = make_device()
    result = ingest_snapshot(device, SyntheticTestAdapter(),
                             test_origin=True)
    with pytest.raises(IngestRefusedError):
        file_payload_for(result.media, "  ", "cam-test1")


def test_adapter_registry():
    clear_adapters()
    assert adapter_for("cam-test1") is None
    adapter = SyntheticTestAdapter()
    register_adapter("cam-test1", adapter)
    assert adapter_for("cam-test1") is adapter
    unregister_adapter("cam-test1")
    assert adapter_for("cam-test1") is None
    with pytest.raises(IngestRefusedError):
        register_adapter("cam-x", object())
    clear_adapters()


def test_adapter_capabilities_are_filtered():
    adapter = SyntheticTestAdapter()
    assert adapter_capabilities(adapter) == ["camera.snapshot"]

    class Spoof(SyntheticTestAdapter):
        capabilities = ["camera.snapshot", "camera.nuke",
                        "shell.exec"]

    assert adapter_capabilities(Spoof()) == ["camera.snapshot"]


# -- streams -------------------------------------------------------------

def test_stream_lifecycle():
    clock = [1000.0]
    manager = StreamManager(now_fn=lambda: clock[0])
    session = manager.start("cam-test1", ["snapshot", "stream"],
                            max_frames=3, max_seconds=60)
    assert session.status == "open"
    manager.tick(session.session_id)
    manager.tick(session.session_id)
    session = manager.tick(session.session_id)
    assert session.frames_captured == 3
    # Budget exhausted -> auto-stopped, never resumes.
    stopped = manager.tick(session.session_id)
    assert stopped.status == "stopped"
    assert "budget" in stopped.stop_reason
    with pytest.raises(IngestRefusedError, match="never resume"):
        manager.tick(session.session_id)


def test_stream_time_expiry():
    clock = [0.0]
    manager = StreamManager(now_fn=lambda: clock[0])
    session = manager.start("cam-test1", ["stream"], max_seconds=10)
    clock[0] = 999.0
    expired = manager.get(session.session_id)
    assert expired.status == "stopped"
    assert "time budget" in expired.stop_reason


def test_stream_needs_capability_and_budgets():
    manager = StreamManager()
    with pytest.raises(IngestRefusedError, match="no stream"):
        manager.start("cam-test1", ["snapshot"])
    with pytest.raises(IngestRefusedError, match="out of range"):
        manager.start("cam-test1", ["stream"], max_frames=10**9)
    with pytest.raises(IngestRefusedError, match="unknown"):
        manager.tick("stream-9999")
    with pytest.raises(IngestRefusedError, match="unknown"):
        manager.stop("stream-9999")


def test_stream_explicit_stop():
    manager = StreamManager()
    session = manager.start("cam-test1", ["stream"])
    stopped = manager.stop(session.session_id)
    assert stopped.status == "stopped"
    assert stopped.stop_reason == "operator stop"
    # Stopping twice is idempotent.
    assert manager.stop(session.session_id).status == "stopped"


# -- insta360 + windows ---------------------------------------------------

def test_insta360_never_captures():
    device = new_device("cam-360", "Insta360 X4",
                        ["snapshot", "webcam", "stream", "p360"],
                        "insta360")
    adapter = Insta360Adapter()
    assert adapter_capabilities(adapter) == []
    with pytest.raises(CameraUnavailable):
        adapter.snapshot(device)
    state = probe_availability(device, adapter)
    assert state["capturable"] is False


def test_insta360_claims_only_implemented():
    adapter = Insta360Adapter(
        implemented=["camera.snapshot", "camera.nuke"])
    assert adapter_capabilities(adapter) == ["camera.snapshot"]
    assert "reviewed" in adapter.unavailable_reason()
    assert "webcam-mode" in Insta360Adapter.requirements()


def test_insta360_candidate_match_is_labeled():
    devices = [{"path": "\\\\?\\usb#vid_2e1a&insta360_x4",
                "source": "usb"},
               {"path": "\\\\?\\usb#vid_046d&logitech", "source": "usb"},
               "not-a-dict"]
    candidates = Insta360Adapter.match_detected(devices)
    assert len(candidates) == 1
    assert candidates[0]["candidate"] == "insta360"
    assert candidates[0]["state"] == "detected"


def test_windows_webcam_stub_refuses():
    device = make_device(kinds=["webcam"], source="usb")
    adapter = WindowsWebcamAdapter()
    with pytest.raises(CameraUnavailable, match="reviewed"):
        adapter.snapshot(device)
    state = probe_availability(device, adapter, detected=True)
    assert state["state"] == "detected"
    assert state["capturable"] is False
    assert "IMFSourceReader" in WindowsWebcamAdapter.requirements()
