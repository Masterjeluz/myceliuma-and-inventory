"""Phase 5 tests (BIG #11-15): robots, drones, familiars, twin."""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "p5.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "p5-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_robot_capabilities_safety_approval(tmp_path,
                                            monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        # No wildcards, no custom capabilities.
        assert test_client.post("/api/v1/robots", json={
            "name": "X", "capabilities": ["robot.*"]}
        ).status_code == 422
        robot = test_client.post("/api/v1/robots", json={
            "name": "Arm-1", "robot_type": "robotic_arm",
            "capabilities": ["robot.move", "robot.observe",
                             "robot.status"],
            "location": "workshop"}).json()
        assert robot["robot_id"].startswith("rbt_")
        robot_id = robot["robot_id"]
        # Unowned capability refuses.
        assert test_client.post(
            f"/api/v1/robots/{robot_id}/propose",
            json={"action": "robot.grab"}).status_code == 422
        proposal = test_client.post(
            f"/api/v1/robots/{robot_id}/propose",
            json={"action": "robot.move",
                  "params": {"to": "shelf"},
                  "simulation_note": "path clear in model"}
        ).json()
        assert proposal["physical"] is True
        assert proposal["status"] == "proposed"
        # Approval without human refuses.
        assert test_client.post(
            f"/api/v1/robots/{robot_id}/approve",
            json={**proposal, "approved_by": ""}
        ).status_code == 422
        approved = test_client.post(
            f"/api/v1/robots/{robot_id}/approve",
            json={**proposal, "approved_by": "jelles"}).json()
        assert approved["status"] == "approved"
        # Lock the robot: physical approval now refuses.
        test_client.post(f"/api/v1/robots/{robot_id}/safety",
                         json={"safety_state": "locked"})
        assert test_client.post(
            f"/api/v1/robots/{robot_id}/approve",
            json={**proposal, "approved_by": "jelles"}
        ).status_code == 422
        # Telemetry without observation does not verify.
        pending = test_client.post(
            f"/api/v1/robots/{robot_id}/telemetry",
            json={"action_id": proposal["action_id"],
                  "robot_id": robot_id,
                  "status": "completed"}).json()
        assert pending["verification"] is None
        verified = test_client.post(
            f"/api/v1/robots/{robot_id}/telemetry",
            json={"action_id": proposal["action_id"],
                  "robot_id": robot_id,
                  "status": "completed",
                  "observation": "arm at shelf, camera frame 12"}
        ).json()
        assert verified["verification"]["verdict"] == "verified"


def test_drone_mission_gates(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        drone = test_client.post("/api/v1/drones", json={
            "name": "Scout", "capabilities": ["drone.observe",
                                              "drone.navigate"],
            "home_location": "garden"}).json()
        drone_id = drone["drone_id"]
        assert drone_id.startswith("drn_")
        # Autonomous without geofence/ceiling refuses.
        assert test_client.post(
            f"/api/v1/drones/{drone_id}/mission",
            json={"kind": "navigate", "autonomous": True}
        ).status_code == 422
        mission = test_client.post(
            f"/api/v1/drones/{drone_id}/mission",
            json={"kind": "navigate",
                  "params": {"to": "garden"},
                  "autonomous": True,
                  "geofence": "garden-only",
                  "max_altitude_m": 15,
                  "approved_by": "jelles"}).json()
        assert mission["status"] == "approved"
        assert mission["autonomous"] is True
        # Unknown kinds refuse.
        assert test_client.post(
            f"/api/v1/drones/{drone_id}/mission",
            json={"kind": "dogfight"}).status_code == 422


def test_familiars_one_capability_model(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        assert test_client.post("/api/v1/familiars", json={
            "name": "X", "kind": "toaster"}).status_code == 422
        phone = test_client.post("/api/v1/familiars", json={
            "name": "Jelles phone", "kind": "phone",
            "linked_id": "node-phone"}).json()
        assert phone["familiar_id"].startswith("fam_")
        assert "phone.camera" in phone["capabilities"]
        from coordinator.app.familiars import (
            familiar_can, get_familiar)
        stored = get_familiar(phone["familiar_id"])
        assert familiar_can(stored, "phone.camera") is True
        assert familiar_can(stored, "robot.move") is False
        assert familiar_can(stored, "*") is False
        listed = test_client.get("/api/v1/familiars").json()
        assert len(listed) == 1


def test_twin_links_and_staleness(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        assert test_client.post("/api/v1/twin/links", json={
            "physical_ref": "workshop printer",
            "digital_ref": "hw_1",
            "link_type": "teleports"}).status_code == 422
        link = test_client.post("/api/v1/twin/links", json={
            "physical_ref": "workshop printer Ender",
            "digital_ref": "hw_1", "link_type": "represents",
            "source": "manual", "confidence": 0.9,
            "last_observed_at": "2020-01-01T00:00:00+00:00"}
        ).json()
        assert link["link_id"].startswith("twn_")
        report = test_client.get("/api/v1/twin/staleness").json()
        assert len(report["stale"]) == 1
        assert "automatically current" in report["warning"]
        observed = test_client.post(
            f"/api/v1/twin/links/{link['link_id']}/observe").json()
        assert observed["status"] == "active"
        fresh = test_client.get(
            "/api/v1/twin/staleness").json()
        assert fresh["stale"] == []
        assert fresh["fresh"] == [link["link_id"]]
