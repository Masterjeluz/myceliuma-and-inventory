"""Capture probe tests: isolated enumeration verdicts, all via
mocked subprocess — the real SetupDi walk never runs in tests."""

import json
import subprocess

from fastapi.testclient import TestClient

import coordinator.app.capture_probe as probe_mod
import coordinator.app.main as main_mod


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "probe.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "probe-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", "probe-operator")
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://127.0.0.1:9")
    with TestClient(main_mod.app) as test_client:
        yield test_client


class _Done:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _payload(devices):
    return json.dumps({"supported": True, "devices": devices,
                       "reason": ""})


def test_probe_found_and_none(tmp_path, monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(kwargs)
        return _Done(0, _payload([{"name": "Insta360 Link",
                                   "path": "usb\\vid_1234"}]))
    monkeypatch.setattr(probe_mod.subprocess, "run", fake_run)
    out = probe_mod.run_probe(timeout=10)
    assert out["state"] == "found"
    assert out["devices"][0]["name"] == "Insta360 Link"
    assert out["elapsed_ms"] >= 0

    monkeypatch.setattr(
        probe_mod.subprocess, "run",
        lambda *a, **k: _Done(0, _payload([])))
    out = probe_mod.run_probe()
    assert out["state"] == "none_found"
    assert out["devices"] == []


def test_probe_timeout_crash_error(tmp_path, monkeypatch):
    def fake_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)
    monkeypatch.setattr(probe_mod.subprocess, "run", fake_timeout)
    out = probe_mod.run_probe(timeout=5)
    assert out["state"] == "timeout"

    monkeypatch.setattr(
        probe_mod.subprocess, "run",
        lambda *a, **k: _Done(-1073741819, "", "boom"))
    out = probe_mod.run_probe()
    assert out["state"] == "crashed"

    monkeypatch.setattr(
        probe_mod.subprocess, "run",
        lambda *a, **k: _Done(0, "not-json{{{"))
    out = probe_mod.run_probe()
    assert out["state"] == "error"

    def fake_oserror(*args, **kwargs):
        raise OSError("noexec")
    monkeypatch.setattr(probe_mod.subprocess, "run", fake_oserror)
    out = probe_mod.run_probe()
    assert out["state"] == "error"

    out = probe_mod.run_probe(timeout="veel")
    assert out["state"] == "error"


def test_probe_never_claims_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(
        probe_mod.subprocess, "run",
        lambda *a, **k: _Done(0, _payload([{"name": "Cam"}])))
    out = probe_mod.run_probe()
    assert "captur" not in str(out).lower()
    assert out["state"] == "found"


def test_probe_route_and_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        probe_mod.subprocess, "run",
        lambda *a, **k: _Done(0, _payload([])))
    for test_client in api(tmp_path, monkeypatch):
        ok = test_client.post("/api/v1/cameras/probe", json={})
        assert ok.status_code == 200, ok.text
        assert ok.json()["state"] == "none_found"
        ok2 = test_client.post("/api/v1/cameras/probe",
                               json={"timeout": 5})
        assert ok2.status_code == 200
        bad = test_client.post("/api/v1/cameras/probe",
                               json={"timeout": 9999})
        assert bad.status_code == 422
        bad2 = test_client.post("/api/v1/cameras/probe",
                                json={"timeout": "lang"})
        assert bad2.status_code == 422
