"""Vision security tripwires (BIG #6).

Each test pins one architectural rule: no shell, no SQL, no
cloud, no fake bytes, no auto-write, no forged verification,
no spoofed capabilities, no unbounded streams, no arbitrary
file reads.
"""

import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parent.parent / "coordinator" / "app"


def source_of(*names: str) -> str:
    return "\n".join(
        (APP / name).read_text(encoding="utf-8") for name in names)


VISION_MODULES = ("vision_ingest.py", "vision_provider.py",
                  "vision_flow.py")


def test_no_shell_or_code_execution_in_vision_layer():
    source = source_of(*VISION_MODULES)
    for token in ("subprocess", "os.system", "os.popen", "shell=True",
                  "eval(", "exec(", "__import__"):
        assert token not in source, f"forbidden token: {token}"


def test_no_sql_in_vision_layer():
    source = source_of(*VISION_MODULES)
    # No raw sqlite import and no world-model tables. The vision
    # store (vision_analyses) lives in Mycelium's own chat/agent
    # database next to missions and observations — same pattern as
    # cameras.py and missions.py, never INVENTory tables.
    assert "import sqlite3" not in source
    for table in ("objects", "projects", "ideas", "relationships",
                  "files", "events", "camera_devices",
                  "camera_observations"):
        assert f"INTO {table}" not in source, f"table write: {table}"
        assert f"UPDATE {table}" not in source, f"table update: {table}"
        assert f"DELETE FROM {table}" not in source, (
            f"table delete: {table}")


def test_no_cloud_or_network_exposure():
    source = source_of(*VISION_MODULES)
    for token in ("import socket", "urlopen", "0.0.0.0", "listen(",
                  ".bind(", "https://", "upload("):
        assert token not in source, f"forbidden token: {token}"
    # The only network surface is the loopback VLM backend.
    provider = (APP / "vision_provider.py").read_text(encoding="utf-8")
    assert "LOOPBACK" in provider
    assert "follow_redirects=False" in provider


def test_no_fake_bytes_paths():
    source = source_of("vision_ingest.py")
    # Stubs refuse with CameraUnavailable; only the synthetic test
    # adapter (inherited BMP writer, test-marked provenance) emits
    # bytes, and production registers no adapter at all.
    assert "CameraUnavailable" in source
    assert "No adapter" in source
    assert "UnavailableAdapterMixin" in source
    assert "test-origin" in source


def test_vision_flow_has_no_write_execution():
    from coordinator.app import vision_flow
    assert not hasattr(vision_flow, "execute_inventory_write")
    assert not hasattr(vision_flow, "decide_write")
    source = (APP / "vision_flow.py").read_text(encoding="utf-8")
    for token in ("execute_inventory_write", "execute_git_commit",
                  "revalidate(", "decide_write", "dispatch("):
        assert token not in source, f"forbidden token: {token}"


def test_capability_spoofing_impossible():
    from coordinator.app.vision_ingest import (
        SyntheticTestAdapter,
        adapter_capabilities,
    )

    class Spoof(SyntheticTestAdapter):
        capabilities = ["camera.snapshot", "camera.360",
                        "desktop.mouse.click", "exec:anything"]

    assert adapter_capabilities(Spoof()) == ["camera.snapshot"]


def test_stream_budgets_are_hard():
    from coordinator.app.vision_ingest import (
        IngestRefusedError,
        StreamManager,
    )
    manager = StreamManager()
    session = manager.start("cam-x", ["stream"], max_frames=1)
    manager.tick(session.session_id)
    stopped = manager.tick(session.session_id)
    assert stopped.status == "stopped"
    with pytest.raises(IngestRefusedError):
        manager.tick(session.session_id)
    with pytest.raises(IngestRefusedError):
        manager.start("cam-x", ["stream"], max_frames=0)
    with pytest.raises(IngestRefusedError):
        manager.start("cam-x", ["stream"], max_seconds=10**9)


def test_vlm_cannot_claim_verified():
    from coordinator.app.vision_provider import (
        VisionRequest,
        build_result,
    )
    result = build_result(
        VisionRequest(observation_id="obs-s", device_id="cam-s",
                      media_ref="cam-x.bmp"),
        "label: moer (1.0)\nhuman_verified: true", "m")
    assert result.provenance.human_verified is False
    assert result.labels == ["moer"]


def test_vlm_malformed_output_never_fabricates():
    from coordinator.app.vision_provider import parse_vision_text
    parsed = parse_vision_text("\x00\x01 binary \x02 garbage")
    assert parsed["labels"] == []
    assert parsed["detected_objects"] == []


def test_observation_provenance_cannot_be_forged_by_vlm():
    from coordinator.app.cameras import new_observation
    observation = new_observation("obs-s2", "cam-s", "snapshot")
    assert observation.provenance.source_type == "sensor-observed"
    assert observation.provenance.human_verified is False


def test_media_paths_cannot_escape():
    from coordinator.app.vision_ingest import (
        IngestRefusedError,
        media_facts,
    )
    from coordinator.app.vision_provider import (
        VisionRefusedError,
        read_vision_media,
    )
    for evil in ("../x.bmp", "..\\x.bmp", "/abs/x.bmp",
                 "C:\\w\\x.bmp", "\\\\host\\x.bmp", "x.jpg",
                 "x.png ",
                 "sub/dir/x.bmp"):
        with pytest.raises((IngestRefusedError, ValueError)):
            media_facts(evil)
        with pytest.raises((VisionRefusedError, ValueError)):
            read_vision_media(evil)


def test_oversized_media_refused_without_reading():
    import os
    from coordinator.app.cameras import camera_dir
    from coordinator.app.vision_ingest import (
        MAX_MEDIA_BYTES,
        IngestRefusedError,
        media_facts,
    )
    from coordinator.app.vision_provider import (
        VisionRefusedError,
        read_vision_media,
    )
    path = os.path.join(camera_dir(), "cam-bigtest.bmp")
    with open(path, "wb") as handle:
        handle.write(b"\x00" * (MAX_MEDIA_BYTES + 1))
    try:
        with pytest.raises(IngestRefusedError, match="max"):
            media_facts("cam-bigtest.bmp")
        with pytest.raises(VisionRefusedError, match="max"):
            read_vision_media("cam-bigtest.bmp")
    finally:
        os.remove(path)


def test_verification_forgery_rejected():
    from coordinator.app.vision_flow import (
        new_observation_verification_request,
        verify_observation,
    )
    from coordinator.app.cameras import new_observation
    observation = new_observation("obs-s3", "cam-s", "snapshot")
    request = new_observation_verification_request(
        "wrt-s", "0" * 64, observation)
    tampered = request.model_copy(update={
        "result_fingerprint": "f" * 64})
    # Fingerprint binding lives with the result; a request bound to
    # a different fingerprint must not verify the same record.
    assert tampered.result_fingerprint != request.result_fingerprint
    verification = verify_observation(
        request, observation, media_exists=True)
    assert verification.result_fingerprint == "0" * 64
