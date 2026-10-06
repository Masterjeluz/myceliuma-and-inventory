"""M4.1 Bambu read-only MQTT: connect/subscribe/read/disconnect.

No network, no printer, no credentials: a strict fake MQTT client
(without any publish method, so any publish attempt explodes)
drives every case. Motion paths must not exist.
"""

import json

import pytest

from coordinator.app.printer3d import (
    BambuPrinterAdapter,
    PrinterRefusedError,
    PrinterUnavailable,
    bambu_config_from_env,
    read_bambu_once,
)

SERIAL = "01P00A000000000"
TOPIC = f"device/{SERIAL}/report"


def _dev(pid="prt-a1"):
    from coordinator.app.printer3d import new_printer
    return new_printer(pid, "Bambu Lab A1 Mini",
                       ["printer.status"])


class FakeMessage:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload


class FakeMQTTClient:
    """Strict fake: NO publish method exists. Any publish attempt
    raises AttributeError — that is the M4.1 proof."""

    def __init__(self):
        self.subscribed = []
        self.looped = False
        self.stopped = False
        self.disconnected = False
        self.auth = None
        self.tls = False
        self.insecure = False
        self.connected_to = None
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None
        self.fail_connect = False

    def username_pw_set(self, username, password=None):
        self.auth = (username, password)

    def tls_set(self, *args, **kwargs):
        self.tls = True

    def tls_insecure_set(self, value):
        self.insecure = bool(value)

    def subscribe(self, topic):
        self.subscribed.append(topic)

    def connect_async(self, host, port, keepalive=60):
        if self.fail_connect:
            raise OSError("network unreachable (fake)")
        self.connected_to = (host, port)

    def loop_start(self):
        self.looped = True

    def loop_stop(self):
        self.stopped = True

    def disconnect(self):
        self.disconnected = True

    # Test driver: fire CONNACK / inbound message.
    def fire_connack(self, rc=0):
        self.on_connect(self, None, None, rc)

    def fire_report(self, payload):
        raw = payload if isinstance(payload, bytes) else \
            json.dumps(payload).encode()
        self.on_message(self, None, FakeMessage(TOPIC, raw))

    def fire_topic(self, topic, payload):
        raw = payload if isinstance(payload, bytes) else \
            json.dumps(payload).encode()
        self.on_message(self, None, FakeMessage(topic, raw))


def make_adapter(**overrides):
    params = {"mqtt_host": "192.168.1.100", "mqtt_port": 8883,
              "mqtt_username": "bblp", "mqtt_password": "code1234",
              "printer_serial": SERIAL, "printer_token": ""}
    params.update(overrides)
    fakes = []

    def factory():
        fake = FakeMQTTClient()
        fakes.append(fake)
        return fake

    adapter = BambuPrinterAdapter(**params, client_factory=factory)
    return adapter, fakes


def good_print(**overrides):
    payload = {"gcode_state": "IDLE", "gcode_file": "kubus.gcode.3mf",
               "subtask_name": "kubus", "nozzle_temper": 24.5,
               "bed_temper": 23.0, "mc_percent": 0,
               "mc_remaining_time": 0,
               "ams": {"ams_exist_bits": "1",
                       "ams": [{"tray": [
                           {"id": 0,
                            "tag_uid": "A00B112233445566",
                            "ctype": 0, "remain": 80}]}]}}
    payload.update(overrides)
    return {"print": payload}


def test_config_missing_names_vars():
    config, missing = bambu_config_from_env({})
    assert config == {}
    assert missing == ["BAMBU_MQTT_HOST", "BAMBU_MQTT_ACCESS_CODE",
                       "BAMBU_PRINTER_SERIAL"]


def test_config_malformed_port():
    config, missing = bambu_config_from_env({
        "BAMBU_MQTT_HOST": "h", "BAMBU_MQTT_PORT": "nan",
        "BAMBU_MQTT_ACCESS_CODE": "c", "BAMBU_PRINTER_SERIAL": "s"})
    assert config == {}
    assert any("PORT" in item for item in missing)


def test_config_ok_defaults():
    config, missing = bambu_config_from_env({
        "BAMBU_MQTT_HOST": "192.168.1.50",
        "BAMBU_MQTT_ACCESS_CODE": "12345678",
        "BAMBU_PRINTER_SERIAL": SERIAL})
    assert missing == []
    assert config == {"host": "192.168.1.50", "port": 8883,
                      "username": "bblp", "access_code": "12345678",
                      "serial": SERIAL}


def test_unreachable_printer():
    adapter, fakes = make_adapter()
    fakes_holder = {}

    def failing_factory():
        fake = FakeMQTTClient()
        fake.fail_connect = True
        fakes_holder["fake"] = fake
        return fake

    adapter._client_factory = failing_factory
    with pytest.raises(PrinterUnavailable):
        adapter._connect_mqtt()
    assert adapter.is_connected is False


def test_identity_mismatch_ignored():
    adapter, fakes = make_adapter()
    adapter._connect_mqtt()
    fake = fakes[0]
    fake.fire_connack(0)
    assert adapter.is_connected is True
    fake.fire_topic("device/OTHER/report", good_print())
    assert adapter._unexpected_topics == 1
    assert adapter._pushes == 0
    with pytest.raises(PrinterUnavailable, match="no telemetry"):
        adapter.status(_dev("prt-x"))


def test_unexpected_topic_ignored():
    adapter, fakes = make_adapter()
    adapter._connect_mqtt()
    fakes[0].fire_connack(0)
    fake_topic = f"device/{SERIAL}/command"
    fakes[0].fire_topic(fake_topic, {"print": {"gcode_state": "IDLE"}})
    assert adapter._unexpected_topics == 1
    assert adapter._pushes == 0


def test_malformed_payload_unknown():
    adapter, fakes = make_adapter()
    adapter._connect_mqtt()
    fakes[0].fire_connack(0)
    fakes[0].fire_report(b"\xff\xfe-not-json")
    fakes[0].fire_report([1, 2, 3])
    fakes[0].fire_report({"pushing": {"command": "pushall"}})
    assert adapter._payload_errors == 3
    assert adapter._pushes == 0
    with pytest.raises(PrinterUnavailable, match="no telemetry"):
        adapter.status(_dev("prt-x"))


def test_stale_status_refuses():
    adapter, fakes = make_adapter()
    adapter._connect_mqtt()
    fakes[0].fire_connack(0)
    fakes[0].fire_report(good_print(gcode_state="RUNNING"))
    assert adapter._pushes == 1
    adapter._last_read_at = "2000-01-01T00:00:00+00:00"
    with pytest.raises(PrinterUnavailable, match="stale"):
        adapter.status(_dev("prt-x"))


def test_valid_status_mapping():
    adapter, fakes = make_adapter()
    adapter._connect_mqtt()
    fakes[0].fire_connack(0)
    fakes[0].fire_report(good_print(
        gcode_state="RUNNING", mc_percent=42,
        mc_remaining_time=17, nozzle_temper=210.0,
        bed_temper=60.0))
    body = adapter.status(_dev("prt-a1"))
    assert body["printer_id"] == "prt-a1"
    assert body["state"] == "printing"
    assert body["gcode_state"] == "RUNNING"
    assert body["nozzle_c"] == 210.0
    assert body["bed_c"] == 60.0
    assert body["progress_pct"] == 42
    assert body["remaining_min"] == 17
    assert body["job_name"] == "kubus"
    assert body["ams_trays"] == 1
    assert body["ams_loaded"] == 1
    assert body["last_read_at"] != ""


def test_state_map_covers_protocol():
    adapter, fakes = make_adapter()
    adapter._connect_mqtt()
    fakes[0].fire_connack(0)
    for raw, expected in (("IDLE", "idle"), ("PAUSE", "paused"),
                          ("FINISH", "idle"), ("FAILED", "failed"),
                          ("PREPARE", "preparing"),
                          ("WEIRD", "unknown")):
        fakes[0].fire_report(good_print(gcode_state=raw))
        body = adapter.status(_dev("prt-a1"))
        assert body["state"] == expected, raw
        assert "ready" not in body["state"].lower()


def test_delta_merge():
    adapter, fakes = make_adapter()
    adapter._connect_mqtt()
    fakes[0].fire_connack(0)
    fakes[0].fire_report({"print": {"gcode_state": "RUNNING"}})
    fakes[0].fire_report({"print": {"nozzle_temper": 215.5}})
    body = adapter.status(_dev("prt-a1"))
    assert body["state"] == "printing"
    assert body["nozzle_c"] == 215.5
    assert adapter._pushes == 2


def test_reconnect_and_disconnect():
    adapter, fakes = make_adapter()
    adapter._connect_mqtt()
    first = fakes[0]
    first.fire_connack(0)
    assert adapter.is_connected is True
    adapter.disconnect()
    assert adapter.is_connected is False
    assert first.disconnected is True
    assert first.stopped is True
    adapter._connect_mqtt()
    assert len(fakes) == 2
    fakes[1].fire_connack(0)
    assert adapter.is_connected is True


def test_no_publish_path_in_read_phase():
    import pathlib
    source = (pathlib.Path(__file__).resolve().parent.parent /
              "coordinator" / "app" / "printer3d.py").read_text(
                  encoding="utf-8")
    assert ".publish(" not in source
    assert "_send_command" not in source
    assert not hasattr(BambuPrinterAdapter, "_send_command")
    adapter, fakes = make_adapter()
    adapter._connect_mqtt()
    fakes[0].fire_connack(0)
    fakes[0].fire_report(good_print(gcode_state="IDLE"))
    from coordinator.app.printer3d import new_job
    job = new_job("pjob-b575x1", "prt-a1", "kubus.gcode", "b" * 64,
                  "fine-pla", "b575-test", proposal_id="wrt-x")
    with pytest.raises(PrinterUnavailable):
        adapter.execute(_dev("prt-a1"), job)
    with pytest.raises(PrinterUnavailable):
        adapter.cancel(_dev("prt-a1"), job)


def test_on_connect_never_publishes():
    adapter, fakes = make_adapter()
    adapter._connect_mqtt()
    fake = fakes[0]
    fake.fire_connack(0)
    assert fake.subscribed == [TOPIC]
    assert adapter.is_connected is True
    fake.fire_connack(0)
    assert adapter.is_connected is True


def test_read_once_happy_and_disconnects():
    import threading
    import time
    env = {"BAMBU_MQTT_HOST": "192.168.1.50",
           "BAMBU_MQTT_ACCESS_CODE": "12345678",
           "BAMBU_PRINTER_SERIAL": SERIAL}
    fakes = []

    def factory():
        fake = FakeMQTTClient()
        fakes.append(fake)
        return fake

    def delayed_push():
        time.sleep(0.2)
        if fakes:
            fakes[0].fire_connack(0)
            fakes[0].fire_report(good_print(gcode_state="IDLE"))

    thread = threading.Thread(target=delayed_push, daemon=True)
    thread.start()
    snapshot = read_bambu_once("prt-a1", timeout=5.0,
                               client_factory=factory, env=env)
    assert snapshot["reachable"] is True
    assert snapshot["state"] == "idle"
    assert snapshot["printer_id"] == "prt-a1"
    assert fakes and fakes[0].disconnected is True


def test_read_once_missing_config_refuses():
    with pytest.raises(PrinterUnavailable, match="BAMBU_MQTT_HOST"):
        read_bambu_once("prt-a1", timeout=2.0, env={})


def _ui_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import coordinator.app.main as main_mod
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "m41.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "m41-chat.db"))
    for name in ("BAMBU_MQTT_HOST", "BAMBU_MQTT_PORT",
                 "BAMBU_MQTT_USERNAME", "BAMBU_MQTT_ACCESS_CODE",
                 "BAMBU_PRINTER_SERIAL"):
        monkeypatch.delenv(name, raising=False)
    with TestClient(main_mod.app) as client:
        yield client


def test_3d_read_button_unconfigured(tmp_path, monkeypatch):
    for client in _ui_client(tmp_path, monkeypatch):
        made = client.post("/web/printers/register",
                           data={"name": "Bambu Lab A1 Mini",
                                 "model": "A1 mini"})
        assert made.status_code in (200, 303), made.text
        html = client.get("/3d").text
        assert "Lezen" in html
        assert "A1 mini" in html
        printers = client.get("/api/v1/printers").json()
        assert len(printers) == 1
        pid = printers[0]["printer_id"]
        assert printers[0]["model"] == "A1 mini"
        done = client.post(f"/web/printers/{pid}/read-status")
        assert done.status_code in (200, 303), done.text
        html = client.get("/3d").text
        assert "UNAVAILABLE" in html
        assert "BAMBU_MQTT_HOST" in html
