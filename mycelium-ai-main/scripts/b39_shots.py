"""Seed a tmp demo world for BIG #39 screenshots (real records only)."""

import os
import sys

# Default paths if not set
tmp = os.environ.get("B39_SHOT_TMP", r"C:\Users\Jelles\AppData\Local\Temp\b39_shots")
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(tmp, "shots.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    tmp, "shots-chat.db")

# Import after setting env vars
from fastapi.testclient import TestClient
import coordinator.app.main as main_mod


def main():
    with TestClient(main_mod.app) as client:
        # Worker laptop: Ollama + GPU + camera + printer, grid power.
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
                     "connected_since": 1700000000},
                    {"kind": "printer_3d",
                     "identifier": "/dev/ttyUSB0",
                     "details": {"subsystem": "serial"},
                     "status": "connected",
                     "connected_since": 1700000000}],
                "compute_capabilities": [
                    {"capability": "ollama",
                     "details": {"models": ["llama3", "qwen2"]},
                     "status": "available", "since": 1700000000},
                    {"capability": "gpu_available",
                     "details": {"vendor": "nvidia"},
                     "status": "available", "since": 1700000000},
                    {"capability": "cpu_inference",
                     "details": {}, "status": "available",
                     "since": 1700000000}],
                "energy_state": {"source": "grid",
                                 "level_percent": 100,
                                 "charging": True, "details": {}}})
        print("heartbeat laptop:", beat.status_code)

        # Sensor Pi: camera + sensor, battery power.
        pi = client.post("/api/v1/nodes/register", json={
            "node_id": "pi-sensor", "hostname": "pi-sensor",
            "tier": "seed",
            "capabilities": ["camera.snapshot"],
            "node_token": "screenshot-token-pisensor-789012"})
        print("node pi:", pi.status_code)
        pi_beat = client.post(
            "/api/v1/nodes/pi-sensor/heartbeat", json={
                "available": True,
                "node_token": "screenshot-token-pisensor-789012",
                "telemetry": {
                    "hostname": "pi-sensor", "os": "Linux",
                    "platform": "Linux-6.6.0",
                    "cpu_percent": 18.0, "cpu_count": 4,
                    "memory_percent": 44.0,
                    "memory_total_mb": 4096,
                    "memory_available_mb": 2294,
                    "disk_percent": 62.0, "disk_total_gb": 64.0,
                    "disk_free_gb": 24.3, "uptime_seconds": 172800,
                    "temperature_celsius": 52.0,
                    "load_average": [0.8, 0.9, 1.0],
                    "network_interfaces": ["wlan0"],
                    "boot_time": 1700000000},
                "hardware": [
                    {"kind": "camera",
                     "identifier": "/dev/video0",
                     "details": {"subsystem": "v4l2"},
                     "status": "connected",
                     "connected_since": 1700000000},
                    {"kind": "sensor",
                     "identifier": "bme280-i2c",
                     "details": {"bus": "i2c"},
                     "status": "connected",
                     "connected_since": 1700000000},
                    {"kind": "usb",
                     "identifier": "1-1.3",
                     "details": {"description": "Spare webcam"},
                     "status": "disconnected"}],
                "compute_capabilities": [
                    {"capability": "cpu_inference",
                     "details": {}, "status": "available",
                     "since": 1700000000}],
                "energy_state": {"source": "battery",
                                 "level_percent": 62,
                                 "charging": False,
                                 "details": {}}})
        print("heartbeat pi:", pi_beat.status_code)

        # A queued research task so routing/activity have content.
        task = client.post("/api/v1/tasks", json={
            "kind": "research.fetch_url",
            "payload": {},
            "required_capabilities": ["research.fetch"],
            "requirements": {"required_hardware": ["camera"]}})
        print("task:", task.status_code)

        print("seed done")
        return 0


if __name__ == "__main__":
    sys.exit(main())
