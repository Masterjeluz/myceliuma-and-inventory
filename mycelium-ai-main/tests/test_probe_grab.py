"""Probe-grab tests: out-of-process frame grab to CameraObservation
+ WorldObservation. The child process is ALWAYS mocked — no USB
enumeration, no hardware, no spawning in unit tests."""

import hashlib
import json
import os
import subprocess

from fastapi.testclient import TestClient

import coordinator.app.capture_probe as probe_mod
import coordinator.app.main as main_mod


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "grab.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "grab-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", "grab-operator")
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://127.0.0.1:9")
    with TestClient(main_mod.app) as test_client:
        yield test_client


class _Done:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _register(test_client, device_id="cam-grab1", kinds=None,
              source="manual"):
    response = test_client.post("/api/v1/cameras/register", json={
        "device_id": device_id, "name": f"Grab {device_id}",
        "kinds": kinds or ["snapshot"], "source": source})
    assert response.status_code == 201, response.text
    return device_id


def _real_frame(filename="cam-grabframe.bmp"):
    """A real BMP in the real camera dir (test-written, hashed)."""
    from coordinator.app.cameras import camera_dir
    from coordinator.app.desktop_runtime import write_bmp_24
    path = os.path.join(camera_dir(), filename)
    write_bmp_24(path, 16, 12, b"\x10\x20\x30" * (16 * 12))
    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    return filename, digest, os.path.getsize(path)


def _frame_stdout(filename, digest, size, width=16, height=12):
    return json.dumps({"state": "frame_acquired",
                       "media_ref": filename, "sha256": digest,
                       "size_bytes": size, "width": width,
                       "height": height, "reason": "mocked child"})


# -- A. successful grab ------------------------------------------------

def test_probe_grab_success_creates_both_observations(
        tmp_path, monkeypatch):
    from coordinator.app import vision_ingest as _ingest
    from coordinator.app.vision_ingest import SyntheticTestAdapter
    filename, digest, size = _real_frame()
    monkeypatch.setattr(
        probe_mod.subprocess, "run",
        lambda *a, **k: _Done(0, _frame_stdout(filename, digest,
                                               size)))
    for test_client in api(tmp_path, monkeypatch):
        _register(test_client)
        _ingest.register_adapter("cam-grab1",
                                 SyntheticTestAdapter())
        try:
            response = test_client.post(
                "/api/v1/cameras/cam-grab1/probe-grab", json={})
            assert response.status_code == 201, response.text
            body = response.json()
            # G. CameraObservation stored + hash verified
            cam = body["camera_observation"]
            assert cam["device_id"] == "cam-grab1"
            assert cam["media_ref"] == filename
            assert cam["observation_id"].startswith("obs-")
            assert "probe-grab" in cam["provenance"]["notes"]
            assert "test-origin" in cam["provenance"]["notes"]
            assert body["grab"]["sha256"] == digest
            stored = test_client.get(
                "/api/v1/cameras/cam-grab1/observations").json()
            assert any(entry["observation_id"] ==
                       cam["observation_id"] for entry in stored)
            # H+I. WorldObservation stored, no entity without vision
            listed = test_client.get(
                "/api/v1/world/observations",
                params={"node_id": "cam-grab1"}).json()
            assert listed["total"] >= 1
            wobs = body["world_observation"]
            assert wobs["entity_ref"] == ""
            assert wobs["confidence"] == 0.0
            assert wobs["x"] is None and wobs["z"] is None
            assert wobs["media_ref"] == filename
            assert wobs["provenance"]["sha256"] == digest
            assert wobs["provenance"]["camera_observation_id"] == \
                cam["observation_id"]
        finally:
            _ingest.clear_adapters()


# -- B..F. failure verdicts, nothing stored ----------------------------

def _grab_with_child(tmp_path, monkeypatch, fake_run,
                     device_id="cam-grab1"):
    from coordinator.app import vision_ingest as _ingest
    from coordinator.app.vision_ingest import SyntheticTestAdapter
    monkeypatch.setattr(probe_mod.subprocess, "run", fake_run)
    for test_client in api(tmp_path, monkeypatch):
        _register(test_client, device_id=device_id)
        _ingest.register_adapter(device_id, SyntheticTestAdapter())
        try:
            before = test_client.get(
                f"/api/v1/cameras/{device_id}/observations").json()
            response = test_client.post(
                f"/api/v1/cameras/{device_id}/probe-grab", json={})
            after = test_client.get(
                f"/api/v1/cameras/{device_id}/observations").json()
            # K. parent survives: endpoint answers after the failure
            assert test_client.get("/api/v1/health").status_code \
                == 200
            yield response, before, after, test_client
        finally:
            _ingest.clear_adapters()


def test_probe_grab_timeout(tmp_path, monkeypatch):
    def fake_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)
    for response, before, after, _ in _grab_with_child(
            tmp_path, monkeypatch, fake_timeout):
        assert response.status_code == 504, response.text
        assert after == before


def test_probe_grab_crash(tmp_path, monkeypatch):
    for response, before, after, _ in _grab_with_child(
            tmp_path, monkeypatch,
            lambda *a, **k: _Done(-1073741819, "", "access boom")):
        assert response.status_code == 502, response.text
        assert after == before


def test_probe_grab_malformed_json(tmp_path, monkeypatch):
    for response, before, after, _ in _grab_with_child(
            tmp_path, monkeypatch,
            lambda *a, **k: _Done(0, "not-json{{{")):
        assert response.status_code == 502, response.text
        assert after == before


def test_probe_grab_missing_frame(tmp_path, monkeypatch):
    for response, before, after, _ in _grab_with_child(
            tmp_path, monkeypatch,
            lambda *a, **k: _Done(
                0, _frame_stdout("cam-does-not-exist.bmp",
                                 "0" * 64, 10))):
        assert response.status_code == 502, response.text
        assert "missing" in response.json()["detail"]
        assert after == before


def test_probe_grab_hash_mismatch(tmp_path, monkeypatch):
    filename, _digest, size = _real_frame("cam-grabtamper.bmp")
    for response, before, after, _ in _grab_with_child(
            tmp_path, monkeypatch,
            lambda *a, **k: _Done(
                0, _frame_stdout(filename, "f" * 64, size))):
        assert response.status_code == 502, response.text
        assert "hash mismatch" in response.json()["detail"]
        assert after == before


# -- validation: 404/409/422, no writes --------------------------------

def test_probe_grab_validation(tmp_path, monkeypatch):
    from coordinator.app import vision_ingest as _ingest
    from coordinator.app.vision_ingest import (
        Insta360Adapter,
        SyntheticTestAdapter,
    )
    monkeypatch.setattr(
        probe_mod.subprocess, "run",
        lambda *a, **k: _Done(0, "unused"))
    for test_client in api(tmp_path, monkeypatch):
        missing = test_client.post(
            "/api/v1/cameras/cam-nope/probe-grab", json={})
        assert missing.status_code == 404
        _register(test_client, device_id="cam-bare1")
        bare = test_client.post(
            "/api/v1/cameras/cam-bare1/probe-grab", json={})
        assert bare.status_code == 409  # no adapter, no fake bytes
        _register(test_client, device_id="cam-360-1",
                  kinds=["snapshot", "p360"], source="insta360")
        _ingest.register_adapter("cam-360-1", Insta360Adapter())
        try:
            refused = test_client.post(
                "/api/v1/cameras/cam-360-1/probe-grab", json={})
            assert refused.status_code == 409
            assert "nsta360" in refused.json()["detail"]
        finally:
            _ingest.clear_adapters()
        _register(test_client, device_id="cam-ok1")
        _ingest.register_adapter("cam-ok1", SyntheticTestAdapter())
        try:
            bad_timeout = test_client.post(
                "/api/v1/cameras/cam-ok1/probe-grab",
                json={"timeout": 9999})
            assert bad_timeout.status_code == 422
            bad_kind = test_client.post(
                "/api/v1/cameras/cam-ok1/probe-grab",
                json={"timeout": "lang"})
            assert bad_kind.status_code == 422
        finally:
            _ingest.clear_adapters()


# -- run_grab unit: no spawn unless valid --------------------------------

def test_run_grab_rejects_without_spawning(tmp_path, monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        return _Done(0, "{}")
    monkeypatch.setattr(probe_mod.subprocess, "run", fake_run)
    assert probe_mod.run_grab(
        {"grabber": "nuke"})["state"] == "error"
    assert probe_mod.run_grab("nonsense")["state"] == "error"
    assert probe_mod.run_grab(
        {"grabber": "file",
         "filename": "../buiten.bmp"})["state"] == "error"
    assert probe_mod.run_grab(
        {"grabber": "test"}, timeout="veel")["state"] == "error"
    assert calls == []


def test_run_grab_unavailable_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(
        probe_mod.subprocess, "run",
        lambda *a, **k: _Done(
            0, json.dumps({"state": "unavailable",
                           "reason": "no reviewed runtime"})))
    out = probe_mod.run_grab({"grabber": "insta360"})
    assert out["state"] == "unavailable"
    assert out["reason"] == "no reviewed runtime"


# -- grab-analyze: frame -> VLM -> WorldObservation ----------------------

def _mock_provider(monkeypatch, labels=("soldeerbout", "werkbank")):
    from coordinator.app.vision_provider import TestVisionProvider
    monkeypatch.setattr(
        main_mod, "get_vision_provider",
        lambda name=None, **kwargs: TestVisionProvider(
            labels=list(labels)))


def test_grab_analyze_full_chain(tmp_path, monkeypatch):
    from coordinator.app import vision_ingest as _ingest
    from coordinator.app.vision_ingest import SyntheticTestAdapter
    filename, digest, size = _real_frame("cam-grabanalyse.bmp")
    monkeypatch.setattr(
        probe_mod.subprocess, "run",
        lambda *a, **k: _Done(0, _frame_stdout(filename, digest,
                                               size)))
    _mock_provider(monkeypatch)
    for test_client in api(tmp_path, monkeypatch):
        _register(test_client)
        _ingest.register_adapter("cam-grab1",
                                 SyntheticTestAdapter())
        try:
            response = test_client.post(
                "/api/v1/vision/grab-analyze",
                json={"device_id": "cam-grab1",
                      "provider": "test-only"})
            assert response.status_code == 201, response.text
            body = response.json()
            assert body["grab"]["state"] == "frame_acquired"
            assert body["camera_observation"]["media_ref"] \
                == filename
            labels = [entry["label"]
                      for entry in body["candidates"]]
            assert labels == ["soldeerbout", "werkbank"]
            # WorldObservation: VLM advice, never an entity/object
            wobs = body["world_observation"]
            assert wobs["entity_ref"] == ""
            assert wobs["confidence"] == 0.5
            assert "soldeerbout" in wobs["note"]
            assert "geen feit" in wobs["note"]
            assert wobs["provenance"]["analysis_id"] == \
                body["analysis"]["analysis_id"]
            listed = test_client.get(
                "/api/v1/world/observations",
                params={"node_id": "cam-grab1"}).json()
            assert listed["total"] >= 2  # frame presence + VLM
            # no INVENTory object was created from the detection
            assert "proposal" not in body
        finally:
            _ingest.clear_adapters()


def test_grab_analyze_vlm_down_is_502(tmp_path, monkeypatch):
    from coordinator.app import vision_ingest as _ingest
    from coordinator.app.vision_ingest import SyntheticTestAdapter
    from coordinator.app.vision_provider import TestVisionProvider
    filename, digest, size = _real_frame("cam-grabdown.bmp")
    monkeypatch.setattr(
        probe_mod.subprocess, "run",
        lambda *a, **k: _Done(0, _frame_stdout(filename, digest,
                                               size)))
    monkeypatch.setattr(
        main_mod, "get_vision_provider",
        lambda name=None, **kwargs: TestVisionProvider(fail=True))
    for test_client in api(tmp_path, monkeypatch):
        _register(test_client)
        _ingest.register_adapter("cam-grab1",
                                 SyntheticTestAdapter())
        try:
            response = test_client.post(
                "/api/v1/vision/grab-analyze",
                json={"device_id": "cam-grab1",
                      "provider": "test-only"})
            assert response.status_code == 502, response.text
        finally:
            _ingest.clear_adapters()


def test_grab_analyze_validation(tmp_path, monkeypatch):
    _mock_provider(monkeypatch)
    for test_client in api(tmp_path, monkeypatch):
        missing = test_client.post("/api/v1/vision/grab-analyze",
                                   json={})
        assert missing.status_code == 422
        unknown = test_client.post("/api/v1/vision/grab-analyze",
                                   json={"device_id": "cam-nope"})
        assert unknown.status_code == 404
