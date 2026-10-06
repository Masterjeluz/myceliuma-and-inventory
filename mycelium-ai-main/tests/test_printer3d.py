"""Printer device + execution tests (BIG #7).

Registration, capability filtering, unavailable honesty,
simulated execution, cancel semantics, and the physical
approval gate: mission YES never starts the machine.
"""

import pytest

from coordinator.app.controlled_writes import (
    decide_write,
    request_write_approval,
    revalidate,
)
from coordinator.app.fab_flow import (
    PrintRefusedError,
    execute_print,
    propose_print,
)
from coordinator.app.mesh3d import ProceduralTestGenerator
from coordinator.app.printer3d import (
    PrinterRefusedError,
    PrinterUnavailable,
    SimulatedPrinterAdapter,
    UnavailablePrinterAdapter,
    adapter_capabilities,
    adapter_for_printer,
    clear_printers,
    get_printer,
    list_printers,
    new_job as make_job,
    new_printer,
    register_printer,
    unregister_printer,
)
from coordinator.app.slicer3d import (
    TestSlicer,
    check_slicer_request,
    validate_gcode,
)


def make_gcode() -> tuple[str, str]:
    mesh = ProceduralTestGenerator().generate("kubus", {}).artifact_ref
    request = check_slicer_request(mesh, "draft-pla", "prt-test1")
    result = TestSlicer().slice(request)
    return result.gcode_ref, result.sha256


def make_device(printer_id="prt-test1"):
    return new_printer(printer_id, "Testprinter",
                       ["printer.status", "printer.start",
                        "printer.cancel"])


def approved(proposal):
    return decide_write(request_write_approval(proposal), proposal,
                        "YES", decided_by="jelles")


def test_registration_and_prefix():
    device = make_device()
    assert device.printer_id == "prt-test1"
    assert device.status == "registered"
    with pytest.raises(PrinterRefusedError, match="prt-"):
        new_printer("printer-1", "X", [])
    with pytest.raises(PrinterRefusedError, match="hw_"):
        new_printer("prt-2", "X", [],
                    inventory_hardware_id="obj_x")
    twin = new_printer("prt-3", "X", [], inventory_hardware_id="hw_x")
    assert twin.inventory_hardware_id == "hw_x"
    with pytest.raises(PrinterRefusedError, match="Unknown printer"):
        new_printer("prt-4", "X", ["printer.fly"])


def test_capability_spoofing_filtered():
    adapter = SimulatedPrinterAdapter()
    caps = adapter_capabilities(adapter)
    assert "printer.start" in caps
    assert "printer.upload" in caps

    class Spoof(SimulatedPrinterAdapter):
        capabilities = ["printer.start", "printer.launch-missiles",
                        "exec:anything"]

    assert adapter_capabilities(Spoof()) == ["printer.start"]


def test_unavailable_printer_refuses():
    device = make_device()
    adapter = UnavailablePrinterAdapter()
    with pytest.raises(PrinterUnavailable,
                       match="refusing instead of moving"):
        adapter.execute(device, make_job(
            "pjob-1", "prt-test1", "fab-x.gcode", "0" * 64,
            "draft-pla", "t"))
    assert "reviewed" in UnavailablePrinterAdapter.requirements()


def test_registry():
    clear_printers()
    device = make_device()
    adapter = SimulatedPrinterAdapter()
    register_printer(device, adapter)
    assert get_printer("prt-test1") is device
    assert adapter_for_printer("prt-test1") is adapter
    assert len(list_printers()) == 1
    unregister_printer("prt-test1")
    assert get_printer("prt-test1") is None
    with pytest.raises(PrinterRefusedError):
        register_printer(object())
    clear_printers()


def test_simulated_execution_completes():
    gcode_ref, sha = make_gcode()
    device = make_device()
    adapter = SimulatedPrinterAdapter()
    job = make_job("pjob-sim1", "prt-test1", gcode_ref, sha,
                   "draft-pla", "tester")
    proposal = propose_print("wrt-print1", job, safety_verdict="safe",
                             actor="tester")
    assert proposal.mutation_type == "printer.execute"
    assert proposal.capability() == "printer.execute"
    assert proposal.provenance.human_verified is False
    result = execute_print(proposal, approved(proposal),
                           device=device, adapter=adapter,
                           safety_verdict="safe")
    assert result.outcome == "executed"
    assert result.after["print_result"]["status"] == "completed"
    assert result.after["print_result"]["gcode_sha256"] == sha
    assert result.provenance.human_verified is False


def test_unsafe_safety_never_proposes_nor_executes():
    gcode_ref, sha = make_gcode()
    job = make_job("pjob-unsafe", "prt-test1", gcode_ref, sha,
                   "draft-pla", "tester")
    with pytest.raises(PrintRefusedError, match="never becomes"):
        propose_print("wrt-unsafe", job, safety_verdict="unsafe",
                      actor="tester")
    proposal = propose_print("wrt-unsafe2", job,
                             safety_verdict="safe", actor="tester")
    device = make_device()
    blocked = execute_print(proposal, approved(proposal),
                            device=device,
                            adapter=SimulatedPrinterAdapter(),
                            safety_verdict="unsafe")
    assert blocked.outcome == "blocked"


def test_changed_gcode_blocked():
    gcode_ref, sha = make_gcode()
    job = make_job("pjob-change", "prt-test1", gcode_ref, sha,
                   "draft-pla", "tester")
    proposal = propose_print("wrt-change", job,
                             safety_verdict="safe", actor="tester")
    approval = approved(proposal)
    # Tamper with the stored artifact after approval.
    import os
    from coordinator.app.mesh3d import artifact_path
    with open(artifact_path(gcode_ref), "a",
              encoding="utf-8") as handle:
        handle.write("G1 X999\n")
    device = make_device()
    blocked = execute_print(proposal, approval, device=device,
                            adapter=SimulatedPrinterAdapter(),
                            safety_verdict="safe")
    assert blocked.outcome == "blocked"
    assert "fingerprint mismatch" in blocked.error


def test_no_adapter_blocked_not_failed():
    gcode_ref, sha = make_gcode()
    job = make_job("pjob-noad", "prt-test1", gcode_ref, sha,
                   "draft-pla", "tester")
    proposal = propose_print("wrt-noad", job, safety_verdict="safe",
                             actor="tester")
    blocked = execute_print(proposal, approved(proposal),
                            device=make_device(), adapter=None,
                            safety_verdict="safe")
    assert blocked.outcome == "blocked"
    assert "no printer adapter" in blocked.error


def test_mission_yes_never_starts_machine():
    """A rejected (non-approved) proposal refuses at revalidation:
    plan-level approval lives elsewhere and cannot substitute."""
    gcode_ref, sha = make_gcode()
    job = make_job("pjob-noperm", "prt-test1", gcode_ref, sha,
                   "draft-pla", "tester")
    proposal = propose_print("wrt-noperm", job,
                             safety_verdict="safe", actor="tester")
    request = request_write_approval(proposal)
    rejected = decide_write(request, proposal, "NO")
    with pytest.raises(ValueError, match="Only an approved"):
        revalidate(proposal, rejected)


def test_cancel_semantics():
    device = make_device()
    adapter = SimulatedPrinterAdapter()
    adapter.request_cancel("pjob-cancel1")
    job = make_job("pjob-cancel1", "prt-test1", "fab-x.gcode",
                   "0" * 64, "draft-pla", "tester")
    cancelled = adapter.cancel(device, job)
    assert cancelled.status == "cancelled"
    assert "NOT a physical emergency stop" in (
        cancelled.error + cancelled.estop_note)


def test_simulated_failure_is_failed():
    gcode_ref, sha = make_gcode()
    job = make_job("pjob-fail", "prt-test1", gcode_ref, sha,
                   "draft-pla", "tester")
    proposal = propose_print("wrt-fail", job, safety_verdict="safe",
                             actor="tester")
    result = execute_print(proposal, approved(proposal),
                           device=make_device(),
                           adapter=SimulatedPrinterAdapter(fail=True),
                           safety_verdict="safe")
    assert result.outcome == "failed"
    assert "simulated" in result.error


# -- runtime connect (operator-triggered adapter attach) -------------------

BAMBU_ENV_KEYS = ("BAMBU_MQTT_HOST", "BAMBU_MQTT_PORT",
                  "BAMBU_MQTT_USERNAME", "BAMBU_MQTT_ACCESS_CODE",
                  "BAMBU_PRINTER_SERIAL")

FAKE_REPORT = {"print": {"gcode_state": "IDLE",
                         "gcode_file": "moon.gcode.3mf",
                         "subtask_name": "moon",
                         "nozzle_temper": 24.0,
                         "bed_temper": 22.0,
                         "mc_percent": 0,
                         "mc_remaining_time": 0,
                         "layer_num": 0,
                         "total_layer_num": 100,
                         "print_error": 0}}


class FakeBambuClient:
    """Fake paho client: connects, then delivers one canned
    report through the real adapter callbacks. ``publish`` explodes:
    the connect path must never move hardware."""

    def __init__(self, serial="TESTSERIAL", silent=False):
        import threading as _threading
        self.serial = serial
        self.silent = silent
        self.calls: list = []
        self.published: list = []
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None
        self._threading = _threading

    def username_pw_set(self, username, password):
        self.calls.append(("auth", username))

    def tls_set(self, **kwargs):
        self.calls.append(("tls", sorted(kwargs)))

    def subscribe(self, topic):
        self.calls.append(("subscribe", topic))
        return (0, 0)

    def connect_async(self, host, port, keepalive=60):
        self.calls.append(("connect", host, port))

    def loop_start(self):
        def _fire():
            import time as _time
            _time.sleep(0.05)
            if self.on_connect is not None:
                self.on_connect(self, None, None, 0)
            if not self.silent and self.on_message is not None:
                import json as _json
                msg = type("Msg", (), {
                    "topic": f"device/{self.serial}/report",
                    "payload": _json.dumps(
                        FAKE_REPORT).encode()})()
                self.on_message(self, None, msg)
        self._threading.Thread(target=_fire, daemon=True).start()

    def loop_stop(self):
        self.calls.append(("loop_stop",))

    def disconnect(self):
        self.calls.append(("disconnect",))

    def publish(self, *args, **kwargs):
        self.published.append((args, kwargs))
        raise AssertionError("motion publish during connect")


def _set_bambu_env(monkeypatch, **overrides):
    for key in BAMBU_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    base = {"BAMBU_MQTT_HOST": "192.168.1.50",
            "BAMBU_MQTT_PORT": "8883",
            "BAMBU_MQTT_ACCESS_CODE": "fake-code-123",
            "BAMBU_PRINTER_SERIAL": "TESTSERIAL"}
    base.update(overrides)
    for key, value in base.items():
        if value is not None:
            monkeypatch.setenv(key, value)


def _conn_device(printer_id="prt-conn1"):
    from coordinator.app.printer3d import new_printer
    return new_printer(printer_id, "Connprinter",
                       ["printer.status", "printer.telemetry",
                        "printer.start"])


def test_connect_attaches_adapter_on_valid_telemetry(monkeypatch):
    from coordinator.app.printer3d import (
        BambuPrinterAdapter,
        adapter_for_printer,
        connect_printer,
        register_printer,
        unregister_printer,
    )
    _set_bambu_env(monkeypatch)
    device = _conn_device()
    register_printer(device)
    try:
        result = connect_printer(
            "prt-conn1", timeout=5,
            client_factory=lambda: FakeBambuClient())
        assert result["reachable"] is True
        assert result["adapter"] == "bambu-a1-mini-ams"
        assert result["state"] == "idle"
        adapter = adapter_for_printer("prt-conn1")
        assert isinstance(adapter, BambuPrinterAdapter)
        # Fresh adapter, never connected: the check used its own
        # short-lived session (disconnected in finally).
        assert adapter.is_connected is False
    finally:
        unregister_printer("prt-conn1")


def test_connect_offline_registers_nothing(monkeypatch):
    from coordinator.app.printer3d import (
        PrinterUnavailable,
        adapter_for_printer,
        connect_printer,
        register_printer,
        unregister_printer,
    )
    _set_bambu_env(monkeypatch)
    register_printer(_conn_device("prt-conn2"))
    try:
        with pytest.raises(PrinterUnavailable):
            connect_printer(
                "prt-conn2", timeout=1,
                client_factory=lambda: FakeBambuClient(
                    silent=True))
        assert adapter_for_printer("prt-conn2") is None
    finally:
        unregister_printer("prt-conn2")


def test_connect_unknown_printer_refuses(monkeypatch):
    from coordinator.app.printer3d import (
        PrinterRefusedError,
        connect_printer,
    )
    _set_bambu_env(monkeypatch)
    with pytest.raises(PrinterRefusedError, match="unknown"):
        connect_printer("prt-nope", timeout=1,
                        client_factory=lambda: FakeBambuClient())


def test_connect_missing_env_names_vars_not_values(monkeypatch):
    from coordinator.app.printer3d import (
        PrinterRefusedError,
        adapter_for_printer,
        connect_printer,
        register_printer,
        unregister_printer,
    )
    _set_bambu_env(monkeypatch)
    monkeypatch.delenv("BAMBU_MQTT_HOST", raising=False)
    register_printer(_conn_device("prt-conn3"))
    try:
        with pytest.raises(PrinterRefusedError) as caught:
            connect_printer("prt-conn3", timeout=1,
                            client_factory=lambda: FakeBambuClient())
        text = str(caught.value)
        assert "BAMBU_MQTT_HOST" in text
        assert "BAMBU_PRINTER_SERIAL" not in text
        assert "fake-code-123" not in text
        assert "192.168.1.50" not in text
        assert adapter_for_printer("prt-conn3") is None
    finally:
        unregister_printer("prt-conn3")


def test_connect_causes_no_motion(monkeypatch):
    from coordinator.app import bambu_exec as exec_mod
    from coordinator.app.printer3d import (
        BambuPrinterAdapter,
        adapter_for_printer,
        connect_printer,
        register_printer,
        unregister_printer,
    )
    _set_bambu_env(monkeypatch)
    calls: list = []

    def _boom(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("motion path reached during connect")

    monkeypatch.setattr(exec_mod, "execute_bambu_job", _boom)
    monkeypatch.setattr(exec_mod, "ftps_upload", _boom)
    monkeypatch.setattr(exec_mod, "publish_request", _boom)
    monkeypatch.setattr(BambuPrinterAdapter, "execute", _boom)
    register_printer(_conn_device("prt-conn4"))
    try:
        result = connect_printer(
            "prt-conn4", timeout=5,
            client_factory=lambda: FakeBambuClient())
        assert result["reachable"] is True
        assert calls == []
        assert isinstance(adapter_for_printer("prt-conn4"),
                          BambuPrinterAdapter)
    finally:
        unregister_printer("prt-conn4")


def test_connect_registry_empty_after_restart(tmp_path, monkeypatch):
    from coordinator.app.printer3d import (
        adapter_for_printer,
        clear_printers,
        connect_printer,
        get_printer,
        load_printer,
        register_printer,
        save_printer,
    )
    _set_bambu_env(monkeypatch)
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "conn-chat.db"))
    clear_printers()
    assert adapter_for_printer("prt-conn5") is None
    device = _conn_device("prt-conn5")
    save_printer(device)
    # Stored twin carries the device, never an adapter.
    assert load_printer("prt-conn5") is not None
    assert adapter_for_printer("prt-conn5") is None
    result = connect_printer(
        "prt-conn5", timeout=5,
        client_factory=lambda: FakeBambuClient())
    assert result["reachable"] is True
    # "Restart": in-memory registry is empty again.
    clear_printers()
    assert get_printer("prt-conn5") is None
    assert adapter_for_printer("prt-conn5") is None


# -- AMS tray-loaded gate (print only what is loaded) ----------------------


def test_ams_slot_loaded_helper():
    from coordinator.app.printer3d import ams_slot_loaded
    live = {"trays_loaded": [True, False, False, False]}
    assert ams_slot_loaded(live, "AMS-1") is True
    assert ams_slot_loaded(live, "AMS-2") is False
    assert ams_slot_loaded(live, "AMS-9") is None
    assert ams_slot_loaded({}, "AMS-1") is None
    assert ams_slot_loaded({"trays_loaded": []}, "AMS-1") is None
    assert ams_slot_loaded(None, "AMS-1") is None
    assert ams_slot_loaded(live, "") is None
    assert ams_slot_loaded(live, "plank") is None


class FakeSessionAdapter(SimulatedPrinterAdapter):
    """Session adapter with canned telemetry. Records motion."""

    capabilities = ["printer.status", "printer.telemetry",
                    "printer.upload", "printer.start",
                    "printer.stop", "printer.cancel"]

    def __init__(self, live):
        super().__init__()
        self._live = dict(live or {})
        self.is_connected = True
        self.executions: list = []

    def _live_status(self):
        return dict(self._live)

    def execute(self, device, job):
        self.executions.append(job.job_id)
        return self._result(device, job, "completed")


def _slotted_job(slot="AMS-1"):
    from coordinator.app.printer3d import new_job
    gcode_ref, sha = make_gcode()
    return new_job("pjob-slot", "prt-test1", gcode_ref, sha,
                   "draft-pla", "tester", spool_id="spl-x",
                   slot=slot)


def test_execute_refuses_unloaded_slot():
    live = {"trays_loaded": [False, False, False, False]}
    adapter = FakeSessionAdapter(live)
    job = _slotted_job()
    proposal = propose_print("wrt-slot1", job,
                             safety_verdict="safe", actor="tester")
    result = execute_print(proposal, approved(proposal),
                           device=make_device(),
                           adapter=adapter, safety_verdict="safe")
    assert result.outcome == "failed"
    assert "not loaded" in result.error
    assert adapter.executions == []


def test_execute_refuses_unknown_tray_state():
    adapter = FakeSessionAdapter({})
    job = _slotted_job()
    proposal = propose_print("wrt-slot2", job,
                             safety_verdict="safe", actor="tester")
    result = execute_print(proposal, approved(proposal),
                           device=make_device(),
                           adapter=adapter, safety_verdict="safe")
    assert result.outcome == "failed"
    assert adapter.executions == []


def test_execute_proceeds_loaded_slot():
    live = {"trays_loaded": [True, False, False, False]}
    adapter = FakeSessionAdapter(live)
    job = _slotted_job()
    proposal = propose_print("wrt-slot3", job,
                             safety_verdict="safe", actor="tester")
    result = execute_print(proposal, approved(proposal),
                           device=make_device(),
                           adapter=adapter, safety_verdict="safe")
    assert result.outcome == "executed"
    assert adapter.executions == ["pjob-slot"]


def test_execute_without_slot_unchanged():
    adapter = FakeSessionAdapter({})
    gcode_ref, sha = make_gcode()
    from coordinator.app.printer3d import new_job
    job = new_job("pjob-noslot", "prt-test1", gcode_ref, sha,
                  "draft-pla", "tester")
    proposal = propose_print("wrt-slot4", job,
                             safety_verdict="safe", actor="tester")
    result = execute_print(proposal, approved(proposal),
                           device=make_device(),
                           adapter=adapter, safety_verdict="safe")
    assert result.outcome == "executed"


def test_execute_waits_for_partial_push_trays():
    """First pushes may lack the AMS node; the gate waits
    boundedly instead of judging one partial push."""

    class _Scripted(FakeSessionAdapter):
        def __init__(self):
            super().__init__({})
            self._reads = [{}, {},
                           {"trays_loaded": [True, False]}]
            self.waits = 0

        def _live_status(self):
            if len(self._reads) > 1:
                return self._reads.pop(0)
            return dict(self._reads[0])

        def wait_for_push(self, timeout=None):
            self.waits += 1
            return True

    adapter = _Scripted()
    job = _slotted_job()
    proposal = propose_print("wrt-slot5", job,
                             safety_verdict="safe", actor="tester")
    result = execute_print(proposal, approved(proposal),
                           device=make_device(),
                           adapter=adapter, safety_verdict="safe")
    assert result.outcome == "executed"
    assert adapter.waits >= 1
    assert adapter.executions == ["pjob-slot"]
