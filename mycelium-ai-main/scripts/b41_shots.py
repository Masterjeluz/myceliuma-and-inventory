"""Seed a tmp demo world for BIG #41 screenshots (real records only)."""

import os
import sys

# Default paths if not set
tmp = os.environ.get("B41_SHOT_TMP", r"C:\Users\Jelles\AppData\Local\Temp\b41_shots")
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
        # Worker node with full reality: telemetry + hardware + compute.
        node = client.post("/api/v1/nodes/register", json={
            "node_id": "atelier-laptop", "hostname": "atelier-laptop",
            "tier": "worker",
            "capabilities": ["research.fetch", "research.fetch_url",
                             "analysis.ollama", "inventory.read",
                             "camera.snapshot"],
            "node_token": "screenshot-token-abcdef-123456"})
        print("node laptop:", node.status_code)
        beat = client.post(
            "/api/v1/nodes/atelier-laptop/heartbeat", json={
                "available": True,
                "node_token": "screenshot-token-abcdef-123456",
                "telemetry": {
                    "hostname": "atelier-laptop", "os": "Linux",
                    "platform": "Linux-6.8.0",
                    "cpu_percent": 28.0, "cpu_count": 8,
                    "memory_percent": 52.0,
                    "memory_total_mb": 16384,
                    "memory_available_mb": 7864,
                    "disk_percent": 38.0, "disk_total_gb": 512.0,
                    "disk_free_gb": 317.0, "uptime_seconds": 90000,
                    "temperature_celsius": 44.0,
                    "load_average": [1.2, 1.4, 1.6],
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

        # Second node, offline (stored offline, honestly derived).
        from coordinator.app.database import connection
        with connection() as db:
            db.execute(
                "INSERT INTO nodes (node_id, hostname, tier, "
                "capabilities, cpu_cores, memory_mb, "
                "energy_source, last_seen, status) VALUES (?, "
                "?, ?, ?, ?, ?, ?, ?, ?)",
                ("zolder-pi", "zolder-pi", "seed",
                 '["camera.snapshot"]', 4, 4096, "battery",
                 "2020-01-01T00:00:00+00:00", "offline"))
        print("node pi offline: seeded")

        # Mission + desktop approval waiting.
        chat = client.post(
            "/api/v1/chat",
            json={"message": "richt de zolderwerkplaats in"}).json()
        mission = client.post("/api/v1/missions", json={
            "conversation_id": chat["conversation_id"],
            "goal": "Zolderwerkplaats inrichten",
            "steps": [{"kind": "readout",
                       "description": "Read status",
                       "parameters": {"source": "project"}}]})
        print("mission:", mission.status_code)
        action = client.post("/api/v1/desktop/actions", json={
            "action_id": "dact-shot-41", "action_type": "click",
            "parameters": {"x": 120, "y": 240}})
        print("desktop action:", action.status_code)

        # Delegated mesh task (audit trail in activity).
        delegation = client.post("/api/v1/mesh/delegate", json={
            "requesting_node": "atelier-laptop",
            "node_token": "screenshot-token-abcdef-123456",
            "target_node": "atelier-laptop",
            "task_kind": "research.fetch_url",
            "capability": "research.fetch",
            "payload": {"url": "https://example.com/werkplaats",
                        "max_chars": 500},
            "reason": "shot delegation"})
        print("delegation:", delegation.status_code)

        # Symbiosis proposal + note candidate.
        proposal = client.post("/api/v1/candidates", json={
            "title": "Werkbank hoort bij zolderproject",
            "candidate_type": "connection",
            "summary": "fysieke plek voor het project",
            "entity_refs": ["proj_zolder", "obj_werkbank"]})
        print("symbiosis candidate:", proposal.status_code)
        note = client.post("/api/v1/candidates", json={
            "title": "Schapenwol als isolatie overwegen",
            "candidate_type": "idea",
            "summary": "natuurlijk materiaal"})
        print("note candidate:", note.status_code)

        # Presence notifications for the recent rail.
        from coordinator.app.presence import (
            sync_presence_notifications)
        receipts = sync_presence_notifications(limit=10)
        print("notifications sent:", len(receipts["sent"]),
              "skipped:", receipts["skipped"])

        print("seed done")
        return 0


if __name__ == "__main__":
    sys.exit(main())
