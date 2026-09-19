"""Seed a tmp demo world for BIG #40 screenshots (real records only)."""

import os
import sys

# Default paths if not set
tmp = os.environ.get("B40_SHOT_TMP", r"C:\Users\Jelles\AppData\Local\Temp\b40_shots")
os.makedirs(tmp, exist_ok=True)
for name in ("shots.db", "shots-chat.db"):
    path = os.path.join(tmp, name)
    if os.path.exists(path):
        os.remove(path)
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(tmp, "shots.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    tmp, "shots-chat.db")

# Import after setting env vars
from fastapi.testclient import TestClient
import coordinator.app.main as main_mod


def main():
    with TestClient(main_mod.app) as client:
        # Capable worker node with full telemetry.
        node = client.post("/api/v1/nodes/register", json={
            "node_id": "workshop-laptop", "hostname": "workshop-laptop",
            "tier": "worker",
            "capabilities": ["research.fetch", "research.fetch_url",
                             "analysis.ollama", "inventory.read",
                             "camera.snapshot"],
            "node_token": "screenshot-token-abcdef-123456"})
        print("node laptop:", node.status_code)
        beat = client.post(
            "/api/v1/nodes/workshop-laptop/heartbeat", json={
                "available": True,
                "node_token": "screenshot-token-abcdef-123456",
                "telemetry": {
                    "hostname": "workshop-laptop", "os": "Linux",
                    "platform": "Linux-6.8.0",
                    "cpu_percent": 32.5, "cpu_count": 8,
                    "memory_percent": 58.0,
                    "memory_total_mb": 16384,
                    "memory_available_mb": 6881,
                    "disk_percent": 41.0, "disk_total_gb": 512.0,
                    "disk_free_gb": 302.0, "uptime_seconds": 86400,
                    "temperature_celsius": 46.0,
                    "load_average": [1.4, 1.6, 1.9],
                    "network_interfaces": ["eth0", "wlan0"],
                    "boot_time": 1700000000},
                "hardware": [
                    {"kind": "camera",
                     "identifier": "/dev/video0",
                     "details": {"subsystem": "v4l2"},
                     "status": "connected",
                     "connected_since": 1700000000},
                    {"kind": "gpu",
                     "identifier": "NVIDIA RTX 3060",
                     "details": {"vendor": "nvidia"},
                     "status": "connected",
                     "connected_since": 1700000000}],
                "compute_capabilities": [
                    {"capability": "ollama",
                     "details": {"models": ["llama3"]},
                     "status": "available", "since": 1700000000},
                    {"capability": "cpu_inference",
                     "details": {}, "status": "available",
                     "since": 1700000000}],
                "energy_state": {"source": "grid",
                                 "level_percent": 100,
                                 "charging": True,
                                 "details": {}}})
        print("heartbeat laptop:", beat.status_code)

        # Offline node (stored offline, honestly derived).
        from coordinator.app.database import connection
        with connection() as db:
            db.execute(
                "INSERT INTO nodes (node_id, hostname, tier, "
                "capabilities, cpu_cores, memory_mb, "
                "energy_source, last_seen, status) VALUES (?, "
                "?, ?, ?, ?, ?, ?, ?, ?)",
                ("pi-sensor", "pi-sensor", "seed",
                 '["camera.snapshot"]', 4, 4096, "battery",
                 "2020-01-01T00:00:00+00:00", "offline"))
        print("node pi offline: seeded")

        # Mission waiting for YES.
        chat = client.post(
            "/api/v1/chat",
            json={"message": "maak de zolderkamer af"}).json()
        mission = client.post("/api/v1/missions", json={
            "conversation_id": chat["conversation_id"],
            "goal": "Zolderkamer afmaken",
            "steps": [{"kind": "readout",
                       "description": "Read status",
                       "parameters": {"source": "project"}}]})
        print("mission:", mission.status_code)

        # Desktop approval waiting.
        action = client.post("/api/v1/desktop/actions", json={
            "action_id": "dact-shot-1", "action_type": "click",
            "parameters": {"x": 100, "y": 200}})
        print("desktop action:", action.status_code)

        # Automation waiting for human.
        run = client.post("/api/v1/automation/runs", json={
            "goal": "Zolderklus keten",
            "steps": [
                {"kind": "mission_propose",
                 "params": {"goal": "Zoldermissie",
                            "conversation_id": chat[
                                "conversation_id"]}},
                {"kind": "wait",
                 "params": {"reason": "plan YES first"}}]}).json()
        driven = client.post(
            f"/api/v1/automation/runs/{run['run_id']}/drive",
            json={"budget_steps": 10}).json()
        print("automation:", driven.get("state"))

        # Candidate + failed task for discovered/needs variety.
        candidate = client.post("/api/v1/candidates", json={
            "title": "Zolder isoleren met schapenwol",
            "candidate_type": "idea",
            "summary": "natuurlijke isolatie overwegen"})
        print("candidate:", candidate.status_code)
        from coordinator.app.events import new_event, save_event
        save_event(new_event("task.failed", "shot task failed",
                             task_id="41"))
        print("task.failed event: saved")

        # Fan out presence notifications (deduplicated IN_APP).
        from coordinator.app.presence import (
            sync_presence_notifications)
        receipts = sync_presence_notifications(limit=10)
        print("notifications sent:", len(receipts["sent"]),
              "skipped:", receipts["skipped"])

        print("seed done")
        return 0


if __name__ == "__main__":
    sys.exit(main())
