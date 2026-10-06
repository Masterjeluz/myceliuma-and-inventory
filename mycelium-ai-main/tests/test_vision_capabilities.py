"""Vision capabilities + Hermes status: honest states only.
Nothing is activated, nothing is probed beyond a bounded
loopback socket check. Unknown stays UNKNOWN."""

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "vcap.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "vcap-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", "vcap-operator")
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://127.0.0.1:9")
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_vision_capabilities_shape(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        body = test_client.get(
            "/api/v1/vision/capabilities").json()
        for section in ("capture", "vision", "usb_enumeration",
                        "insta360"):
            assert section in body, section
            assert body[section]["state"] in (
                "REAL", "TEST", "UNAVAILABLE", "UNKNOWN"), section
            assert body[section]["reason"], section
        assert isinstance(body["capture"].get("adapters"), list)
        assert body["vision"].get("model")
        # default test env: nothing registered, nothing reachable
        assert body["insta360"]["state"] == "UNAVAILABLE"
        assert body["usb_enumeration"]["state"] == "UNKNOWN"


def test_vision_capabilities_sees_test_adapter(tmp_path,
                                               monkeypatch):
    from coordinator.app import vision_ingest as _ingest
    from coordinator.app.cameras import TestCameraAdapter
    for test_client in api(tmp_path, monkeypatch):
        _ingest.register_adapter("cam-test-1", TestCameraAdapter())
        try:
            body = test_client.get(
                "/api/v1/vision/capabilities").json()
            assert body["capture"]["state"] == "TEST"
        finally:
            _ingest.clear_adapters()


def test_hermes_status_unconfigured(tmp_path, monkeypatch):
    monkeypatch.delenv("HERMES_API_KEY", raising=False)
    for test_client in api(tmp_path, monkeypatch):
        body = test_client.get("/api/v1/hermes/status").json()
        assert body["state"] == "UNAVAILABLE"
        assert "reason" in body
        assert "base_url" in body
        # naming the env var is fine; leaking a secret is not
        assert "HERMES_API_KEY" in body["reason"]
        assert len(body["reason"]) < 120


def test_hermes_status_unreachable(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "test-key-long-enough")
    monkeypatch.setenv("HERMES_API_URL", "http://127.0.0.1:9")
    for test_client in api(tmp_path, monkeypatch):
        body = test_client.get("/api/v1/hermes/status").json()
        assert body["state"] == "UNAVAILABLE"
        assert body["base_url"] == "http://127.0.0.1:9"
