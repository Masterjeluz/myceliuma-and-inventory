"""Camera abstraction tests (BIG #4, §21).

Device/capability contracts, observation + provenance, snapshot
fail-closed without an adapter, test-adapter capture, registry,
read-only discovery shape, HTTP endpoints, and the no-network /
no-shell surface of the module.
"""

import os

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.cameras import (
    CameraRefusedError,
    CameraUnavailable,
    TestCameraAdapter,
    check_kinds,
    detect_local_imaging_devices,
    get_device,
    list_devices,
    list_observations,
    new_device,
    new_observation,
    save_device,
    save_observation,
    take_snapshot,
)


def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH", str(tmp_path / "c.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH", str(tmp_path / "c-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_device_contract():
    device = new_device("cam-1", "Insta360 X4", ["snapshot", "p360"],
                        "insta360")
    assert device.kinds == ["snapshot", "p360"]
    with pytest.raises(CameraRefusedError):
        new_device("cam-2", "X", ["teleport"], "usb")
    with pytest.raises(CameraRefusedError):
        new_device("cam-3", "X", ["snapshot"], "wifi-cloud")
    with pytest.raises(CameraRefusedError):
        new_device("cam-4", "  ", ["snapshot"], "manual")
    with pytest.raises(CameraRefusedError):
        check_kinds([])


def test_observation_contract_and_provenance():
    observation = new_observation("obs-1", "cam-1", "snapshot",
                                  media_ref="cam-1.bmp", width=64,
                                  height=48)
    assert observation.provenance.source_type == "sensor-observed"
    assert observation.provenance.human_verified is False
    assert "camera:cam-1" in observation.provenance.creator_id
    with pytest.raises(CameraRefusedError):
        new_observation("obs-2", "cam-1", "livestream")
    with pytest.raises(CameraRefusedError):
        new_observation("obs-3", "cam-1", "snapshot",
                        media_ref="http://x/y.png")
    with pytest.raises(CameraRefusedError):
        new_observation("obs-4", "cam-1", "snapshot",
                        file_id="not-a-file")


def test_snapshot_without_adapter_fails_closed():
    device = new_device("cam-9", "Lege camera", ["snapshot"], "manual")
    with pytest.raises(CameraUnavailable) as caught:
        take_snapshot(device, None)
    assert "refusing" in str(caught.value)
    webcam_only = new_device("cam-8", "Webcam", ["webcam"], "usb")
    with pytest.raises(CameraRefusedError):
        take_snapshot(webcam_only, TestCameraAdapter())


def test_test_adapter_captures_locally(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "cam.db"))
    import coordinator.app.cameras as module
    monkeypatch.setattr(module, "camera_dir", lambda: str(tmp_path))
    device = new_device("cam-t", "Test", ["snapshot"], "manual")
    observation = take_snapshot(device, TestCameraAdapter())
    assert observation.media_ref.endswith(".bmp")
    assert observation.width == 64
    full = str(tmp_path / observation.media_ref)
    assert os.path.isfile(full)
    save_device(device)
    save_observation(observation)
    assert get_device("cam-t").name == "Test"
    assert [dev.device_id for dev in list_devices()] == ["cam-t"]
    assert list_observations("cam-t")[0].observation_id == \
        observation.observation_id


def test_discovery_is_read_only_and_safe():
    result = detect_local_imaging_devices()
    assert set(result) == {"supported", "devices", "reason"}
    assert isinstance(result["devices"], list)
    for entry in result["devices"]:
        assert "path" in entry


def test_no_network_or_shell_surface():
    import coordinator.app.cameras as module
    source = open(module.__file__, encoding="utf-8").read().lower()
    for token in ("import httpx", "import socket", "import subprocess",
                  "os.system", "shell=true", "urllib", "requests"):
        assert token not in source


def test_camera_endpoints(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        assert test_client.post("/api/v1/cameras/register", json={
            "name": "X", "kinds": ["teleport"],
            "source": "usb"}).status_code == 422
        registered = test_client.post("/api/v1/cameras/register", json={
            "device_id": "cam endpoint",
            "name": "Insta360 (handmatig)",
            "kinds": ["snapshot", "webcam", "stream", "p360"],
            "source": "insta360"})
        assert registered.status_code == 201, registered.text
        device_id = registered.json()["device_id"]
        assert device_id == "cam endpoint"
        assert test_client.get(
            f"/api/v1/cameras/{device_id}").status_code == 200
        assert test_client.get("/api/v1/cameras/missing").status_code == 404
        assert len(test_client.get("/api/v1/cameras").json()) == 1
        detected = test_client.get("/api/v1/cameras/detected")
        assert detected.status_code == 200
        assert "devices" in detected.json()
        # no capture runtime ships: snapshot refuses, never fakes
        snapshot = test_client.post(
            f"/api/v1/cameras/{device_id}/snapshot")
        assert snapshot.status_code == 409
        assert test_client.get(
            f"/api/v1/cameras/{device_id}/observations").json() == []
        assert test_client.post(
            "/api/v1/cameras/missing/snapshot").status_code == 404
