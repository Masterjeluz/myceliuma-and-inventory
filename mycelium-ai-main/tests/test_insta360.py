"""Insta360 grab runtime: label-validatie, child-snippet guards,
parent-verificatie met gemockte subprocess (echte ffmpeg/camera
draait nooit in pytest), route-mapping voor source=insta360.
"""
import hashlib
import json
import os
from contextlib import contextmanager
from types import SimpleNamespace

import coordinator.app.capture_probe as probe_mod
import coordinator.app.main as main_mod
from coordinator.app.capture_probe import (
    _GRAB_SNIPPET,
    insta360_label,
    run_grab,
)


@contextmanager
def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "queue.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "chat.db"))
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "fab"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", "grab-operator")
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://127.0.0.1:9")
    with TestClient(main_mod.app) as client:
        yield client


def _register(client, device_id="cam-insta1", kinds=None, source="insta360"):
    response = client.post("/api/v1/cameras/register", json={
        "device_id": device_id, "name": "Insta360 X3",
        "kinds": kinds or ["snapshot"], "source": source})
    assert response.status_code == 201, response.text
    return response.json()


def test_insta360_label_defaults_and_validation(monkeypatch):
    monkeypatch.delenv("INSTA360_DSHOW_NAME", raising=False)
    assert insta360_label() == "Insta360 X3"
    monkeypatch.setenv("INSTA360_DSHOW_NAME", "Cam (front)")
    assert insta360_label() == "Cam (front)"
    for bad in ["a;b", "x|y", "../../e", "a" * 81, "", "cam$dollar"]:
        monkeypatch.setenv("INSTA360_DSHOW_NAME", bad)
        assert insta360_label() == "Insta360 X3", bad


def test_insta360_snippet_guards():
    """Child-code: dshow-tak aanwezig, nooit shell, vaste argv."""
    assert "insta360" in _GRAB_SNIPPET
    assert "shell=True" not in _GRAB_SNIPPET
    assert "shell =" not in _GRAB_SNIPPET
    assert "'-f', 'dshow'" in _GRAB_SNIPPET
    assert "'-frames:v', '1'" in _GRAB_SNIPPET
    assert "windows-webcam" in _GRAB_SNIPPET  # blijft geweigerd


def test_run_grab_unknown_grabber_needs_no_subprocess():
    result = run_grab({"grabber": "nope"})
    assert result["state"] == "error"


def test_run_grab_insta360_unavailable(tmp_path, monkeypatch):
    """ffmpeg-mislukking in child -> benoemde verdict, geen bytes."""
    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=0, stderr="",
            stdout=json.dumps({"state": "unavailable",
                               "reason": "ffmpeg not on PATH"}))
    monkeypatch.setattr(probe_mod.subprocess, "run", fake_run)
    result = run_grab({"grabber": "insta360"}, timeout=5)
    assert result["state"] == "unavailable"
    assert "ffmpeg" in result["reason"]


def test_run_grab_insta360_frame_verifies_parent_side(tmp_path, monkeypatch):
    """Ouder verifieert bestand + sha zelf; child-woord is niet genoeg."""
    from coordinator.app.cameras import camera_dir
    payload = b"\xff\xd8fake-jpeg-bytes\xff\xd9" * 100
    digest = hashlib.sha256(payload).hexdigest()
    name = "cam-insta360-pytest.jpg"
    path = os.path.join(camera_dir(), name)
    with open(path, "wb") as handle:
        handle.write(payload)
    try:
        def fake_run(*args, **kwargs):
            return SimpleNamespace(
                returncode=0, stderr="",
                stdout=json.dumps({"state": "frame_acquired",
                                   "media_ref": name, "sha256": digest,
                                   "size_bytes": len(payload),
                                   "width": 1920, "height": 1080,
                                   "reason": "fake child"}))
        monkeypatch.setattr(probe_mod.subprocess, "run", fake_run)
        result = run_grab({"grabber": "insta360"}, timeout=5)
        assert result["state"] == "frame_acquired"
        assert result["media_ref"] == name
        assert result["width"] == 1920 and result["height"] == 1080
        # Geknoei met de hash -> ouder weigert.
        def fake_tampered(*args, **kwargs):
            return SimpleNamespace(
                returncode=0, stderr="",
                stdout=json.dumps({"state": "frame_acquired",
                                   "media_ref": name, "sha256": "0" * 64,
                                   "size_bytes": len(payload),
                                   "width": 1, "height": 1,
                                   "reason": "fake child"}))
        monkeypatch.setattr(probe_mod.subprocess, "run", fake_tampered)
        tampered = run_grab({"grabber": "insta360"}, timeout=5)
        assert tampered["state"] == "error"
        assert "hash" in tampered["reason"]
    finally:
        if os.path.isfile(path):
            os.remove(path)


def test_probe_grab_insta360_route_maps_source(tmp_path, monkeypatch):
    """source=insta360 -> grabber insta360; frame wordt observatie."""
    from coordinator.app.cameras import camera_dir
    payload = b"\xff\xd8route-bytes\xff\xd9" * 100
    digest = hashlib.sha256(payload).hexdigest()
    name = "cam-insta360-route.jpg"
    path = os.path.join(camera_dir(), name)
    with open(path, "wb") as handle:
        handle.write(payload)
    try:
        def fake_grab(spec, timeout=30.0):
            assert spec == {"grabber": "insta360"}
            return {"state": "frame_acquired", "media_ref": name,
                    "sha256": digest, "size_bytes": len(payload),
                    "width": 1280, "height": 720,
                    "reason": "fake grab", "elapsed_ms": 3}
        monkeypatch.setattr(probe_mod, "run_grab", fake_grab)
        with _client(tmp_path, monkeypatch) as client:
            _register(client)
            res = client.post("/api/v1/cameras/cam-insta1/probe-grab",
                              json={"timeout": 5})
            assert res.status_code == 201, res.text
            body = res.json()
            assert body["camera_observation"]["media_ref"] == name
            assert body["camera_observation"]["width"] == 1280
            notes = body["camera_observation"]["provenance"]["notes"]
            assert "grabber=insta360" in notes
    finally:
        if os.path.isfile(path):
            os.remove(path)


def test_probe_grab_refusals_need_no_hardware(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        missing = client.post("/api/v1/cameras/no-such-cam/probe-grab",
                              json={})
        assert missing.status_code == 404
        _register(client, device_id="cam-no-snap", kinds=["webcam"],
                  source="manual")
        refused = client.post(
            "/api/v1/cameras/cam-no-snap/probe-grab", json={})
        assert refused.status_code in (404, 422)


def test_solarpunk_scan_panel_present(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        res = client.get("/solarpunk")
        assert res.status_code == 200
        assert 'id="spc-scan"' in res.text
        assert "probe-grab" in res.text
        assert "<form" not in res.text
        # 1-klik beeld: knop + shot-div + image-route in de JS.
        assert 'id="spc-scan-snap"' in res.text
        assert 'id="spc-scan-shot"' in res.text
        assert "observations/" in res.text and "/image" in res.text


def test_observation_image_serves_stored_frame(tmp_path,
                                              monkeypatch):
    """1-klik beeld: opgeslagen frame als bytes; onbekend 404,
    ongeldig id 422, zonder media 409. Echte JPEG leest via
    de allow-listed camera-dir (OS-temp, geen echte camera)."""
    from coordinator.app.cameras import (
        camera_dir, new_observation, save_observation)
    with _client(tmp_path, monkeypatch) as client:
        missing = client.get(
            "/api/v1/cameras/observations/obs-nope/image")
        assert missing.status_code == 404
        bad = client.get(
            "/api/v1/cameras/observations/../x/image")
        assert bad.status_code in (404, 422)
        empty = new_observation(
            "obs-empty1", "cam-insta1", "snapshot")
        save_observation(empty)
        nomedia = client.get(
            "/api/v1/cameras/observations/obs-empty1/image")
        assert nomedia.status_code == 409
        name = "cam-testframe1.jpg"
        with open(os.path.join(camera_dir(), name),
                  "wb") as handle:
            handle.write(b"\xff\xd8\xff\xd9")
        framed = new_observation(
            "obs-framed1", "cam-insta1", "snapshot",
            media_ref=name, width=64, height=64)
        save_observation(framed)
        res = client.get(
            "/api/v1/cameras/observations/obs-framed1/image")
        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith(
            "image/")
        assert res.content == b"\xff\xd8\xff\xd9"
        os.remove(os.path.join(camera_dir(), name))
