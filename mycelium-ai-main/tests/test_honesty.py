"""FASE 13/14 tests (BIG #16): mock honesty + voice policy.

Mocks stay visibly mock (Garmin origin, Instagram refs,
simulated-printer and test-camera badges); voice resolves
interface approvals (desktop) but never physical execution
(printer/robot/drone writes).
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "hon.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "hon-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_garmin_import_marks_origin(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        imported = client.post(
            "/api/v1/integrations/garmin/import",
            json={"provider": "mock", "limit": 3}).json()
        assert imported["provider_state"] == "MOCK"
        rows = client.get(
            "/api/v1/health/measurements",
            params={"metric": "steps",
                    "source": "wearable"}).json()
        assert rows
        assert all(row["origin"] == "garmin:mock"
                   for row in rows)
        assert "MOCK" in client.get("/health").text


def test_simulated_printer_badged(tmp_path, monkeypatch):
    from coordinator.app.printer3d import (
        SimulatedPrinterAdapter,
        adapter_for_printer,
        register_printer,
        unregister_printer,
    )
    for client in make_client(tmp_path, monkeypatch):
        client.post("/api/v1/printers/register", json={
            "printer_id": "prt-sim", "name": "Sim",
            "capabilities": ["printer.status"]})
        from coordinator.app.printer3d import list_stored_printers
        device = next(item for item in list_stored_printers()
                      if item.printer_id == "prt-sim")
        register_printer(device, SimulatedPrinterAdapter())
        try:
            assert adapter_for_printer("prt-sim") is not None
            assert "[SIMULATED]" in client.get(
                "/fabrication").text
        finally:
            unregister_printer("prt-sim")
        assert "[SIMULATED]" not in client.get(
            "/fabrication").text


def test_voice_refuses_physical_writes(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        robot = client.post("/api/v1/robots", json={
            "name": "R", "robot_type": "robotic_arm",
            "capabilities": ["robot.move"]}).json()
        proposed = client.post(
            f"/api/v1/robots/{robot['robot_id']}/propose",
            json={"action": "robot.move",
                  "actor": "jelles"}).json()
        proposal_id = proposed["proposal"]["proposal_id"]
        # Physical mutations never resolve by voice.
        assert client.post("/api/v1/voice/approval-requests",
                           json={"kind": "write",
                                 "target_id": proposal_id}
                           ).status_code == 422
        # Unknown kinds never resolve either.
        assert client.post("/api/v1/voice/approval-requests",
                           json={"kind": "physical",
                                 "target_id": "x"}
                           ).status_code == 422


def test_voice_allows_desktop_interface(tmp_path, monkeypatch):
    from coordinator.app.voice_approval import (
        VoiceApprovalRefusedError,
        VoiceApprovalRequest,
        now,
        resolve_voice_approval,
    )
    request = VoiceApprovalRequest(
        approval_id="vapr-test", kind="desktop",
        target_id="act_1", fingerprint="",
        created_at=now(),
        expires_at="2999-01-01T00:00:00+00:00")
    outcome = resolve_voice_approval(
        [request], "ja", kind="desktop", target_ok=True)
    assert outcome == {"approved": True, "response": "YES",
                       "approval_id": "vapr-test",
                       "reason": "exactly one active request, "
                                 "unexpired, binding intact, "
                                 "explicit YES word"}
    with pytest.raises(VoiceApprovalRefusedError):
        resolve_voice_approval([request], "ja", kind="physical",
                               target_ok=True)


def test_test_camera_marks_observations(tmp_path, monkeypatch):
    from coordinator.app.cameras import (
        TestCameraAdapter,
        new_device,
        save_device,
        take_snapshot,
    )
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "cam.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "cam-chat.db"))
    device = new_device("cam-test-1", "Test cam",
                        ["snapshot"], "manual")
    save_device(device)
    observation = take_snapshot(device, TestCameraAdapter())
    assert "test-only" in str(
        observation.provenance.notes or "")


def test_robot_approval_binds_target(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        first = client.post("/api/v1/robots", json={
            "name": "R1", "robot_type": "robotic_arm",
            "capabilities": ["robot.move"]}).json()
        second = client.post("/api/v1/robots", json={
            "name": "R2", "robot_type": "robotic_arm",
            "capabilities": ["robot.move"]}).json()
        proposed = client.post(
            f"/api/v1/robots/{first['robot_id']}/propose",
            json={"action": "robot.move",
                  "actor": "jelles"}).json()
        proposal_id = proposed["proposal"]["proposal_id"]
        # Same proposal cannot approve a different robot:
        # target binding is checked against live state.
        assert client.post(
            f"/api/v1/robots/{second['robot_id']}/approve",
            json={"proposal_id": proposal_id, "response": "YES",
                  "decided_by": "jelles"}).status_code == 422


def test_new_modules_have_no_shell_network_or_cloud():
    import pathlib
    app = pathlib.Path(__file__).resolve().parent.parent / \
        "coordinator" / "app"
    for name in ("payloads.py", "retention.py", "robots.py",
                 "drones.py", "familiars.py", "twin.py",
                 "jobs.py", "cad.py", "fabrication.py",
                 "meshops.py", "memory.py", "health.py",
                 "nutrition.py", "garmin.py", "research.py",
                 "skills.py", "failover.py", "sync.py",
                 "diststate.py", "events.py", "live.py",
                 "watcher.py", "reports.py", "nodes.py"):
        source = (app / name).read_text(encoding="utf-8")
        for token in ("subprocess", "os.system", "eval(",
                      "import sqlite3", "https://", "boto",
                      "kubernetes", "celery", "redis",
                      "0.0.0.0"):
            assert token not in source, f"{name}: {token}"
