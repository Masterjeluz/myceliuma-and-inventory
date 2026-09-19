"""BIG #39 live smoke: hardware reality layer on tmp DBs.

Proves with real localhost HTTP (TestClient, no mocks):
register → heartbeat with telemetry/hardware/compute/energy →
node shows ONLINE with telemetry → telemetry-aware routing
matches/misses honestly → mobile nodes panel → hardware-aware
guide → notifications capability lists node types → pages
render → refusals stay fail-closed (unknown fields, bad
credentials, wildcards).
"""

import os
import sys

tmp = os.environ.get("B39_SMOKE_TMP", "")
assert tmp, "B39_SMOKE_TMP required"
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(tmp, "smoke.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    tmp, "smoke-chat.db")

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN = "b39-smoke-token-123456"

TELEMETRY = {
    "hostname": "smoke-node",
    "os": "Linux",
    "platform": "Linux-5.15.0",
    "cpu_percent": 35.0,
    "cpu_count": 8,
    "memory_percent": 55.0,
    "memory_total_mb": 16384,
    "memory_available_mb": 7372,
    "disk_percent": 40.0,
    "disk_total_gb": 500.0,
    "disk_free_gb": 300.0,
    "uptime_seconds": 7200,
    "temperature_celsius": 44.0,
    "load_average": [1.1, 1.3, 1.6],
    "network_interfaces": ["eth0", "wlan0"],
    "boot_time": 1700000000,
}

HARDWARE = [
    {"kind": "camera", "identifier": "/dev/video0",
     "details": {"subsystem": "v4l2"}, "status": "connected",
     "connected_since": 1700000000},
    {"kind": "gpu", "identifier": "NVIDIA RTX 3080",
     "details": {"vendor": "nvidia"}, "status": "connected"},
]

COMPUTE = [
    {"capability": "ollama",
     "details": {"models": ["llama3"]},
     "status": "available", "since": 1700000000},
    {"capability": "gpu_available",
     "details": {"vendor": "nvidia"}, "status": "available"},
    {"capability": "cpu_inference", "details": {},
     "status": "available"},
]

ENERGY = {"source": "grid", "level_percent": 100,
          "charging": True, "details": {}}


def check(name, ok, detail=""):
    line = f"{'OK  ' if ok else 'FAIL'} {name} {detail}"
    print(line, flush=True)
    if not ok:
        sys.exit(1)


with TestClient(main_mod.app) as client:
    reg = client.post("/api/v1/nodes/register", json={
        "node_id": "smoke-node", "hostname": "smoke-node",
        "tier": "worker",
        "capabilities": ["research.fetch", "analysis.ollama"],
        "node_token": TOKEN})
    check("node registered", reg.status_code == 201,
          str(reg.status_code))

    beat = client.post("/api/v1/nodes/smoke-node/heartbeat",
                       json={"available": True,
                             "node_token": TOKEN,
                             "telemetry": TELEMETRY,
                             "hardware": HARDWARE,
                             "compute_capabilities": COMPUTE,
                             "energy_state": ENERGY})
    check("heartbeat with telemetry accepted",
          beat.status_code == 204, str(beat.status_code))

    node = client.get("/api/v1/nodes/smoke-node").json()
    check("node health ONLINE",
          node.get("health_status") == "ONLINE",
          node.get("health_status", "?"))
    check("telemetry stored",
          node.get("telemetry", {}).get("cpu_percent") == 35.0)
    check("telemetry timestamped",
          bool(node.get("telemetry_timestamp")))
    check("hardware stored",
          len(node.get("hardware", [])) == 2)
    check("compute stored",
          len(node.get("compute_capabilities", [])) == 3)
    check("energy stored",
          node.get("energy_state", {}).get("source") == "grid")

    matched = client.post("/api/v1/tasks/route", json={
        "requirements": {
            "required_capabilities": ["research.fetch"],
            "required_hardware": ["camera"],
            "required_compute": ["ollama"],
            "min_health": "ONLINE"},
        "policy": {}}).json()
    check("telemetry-aware routing matches",
          matched.get("selected_node_id") == "smoke-node")

    missed = client.post("/api/v1/tasks/route", json={
        "requirements": {
            "required_capabilities": ["research.fetch"],
            "required_hardware": ["printer_3d"]},
        "policy": {}}).json()
    check("routing misses honestly",
          missed.get("selected_node_id") is None)

    mobile = client.get("/api/v1/mobile/dashboard").json()
    panel = mobile.get("nodes", {}).get("nodes", [])
    entry = next((item for item in panel
                  if item.get("node_id") == "smoke-node"), {})
    check("mobile nodes panel carries telemetry",
          entry.get("health") == "ONLINE"
          and entry.get("telemetry", {}).get(
              "cpu_percent") == 35.0)
    check("mobile nodes panel carries hardware",
          "camera" in entry.get("hardware", {}).get("kinds", []))
    check("mobile nodes panel carries compute",
          "ollama" in entry.get("compute", {}).get(
              "capabilities", []))

    guide = client.get("/api/v1/guide").json()
    guide_text = " | ".join(
        item.get("what", "") for item in guide.get("items", []))
    check("guide is hardware-aware",
          "Ollama" in guide_text and "GPU" in guide_text)

    cap = client.get("/api/v1/notifications/capability").json()
    check("notification types list node kinds",
          "node_degraded" in cap.get("types", [])
          and "hardware_connected" in cap.get("types", []))
    check("web push stays UNAVAILABLE",
          cap.get("transports", {}).get("WEB_PUSH", {}).get(
              "state") == "UNAVAILABLE")

    for path in ("/nodes", "/mobile", "/guide", "/world"):
        page = client.get(path)
        check(f"page {path} renders",
              page.status_code == 200
              and "Mycelium" in page.text,
              str(page.status_code))

    bad_field = dict(TELEMETRY)
    bad_field["evil_metric"] = 1
    refused = client.post(
        "/api/v1/nodes/smoke-node/heartbeat",
        json={"available": True, "node_token": TOKEN,
              "telemetry": bad_field})
    check("unknown telemetry field refused",
          refused.status_code == 422, str(refused.status_code))

    refused_hw = client.post(
        "/api/v1/nodes/smoke-node/heartbeat",
        json={"available": True, "node_token": TOKEN,
              "hardware": [{"kind": "quantum",
                            "identifier": "q1"}]})
    check("unknown hardware kind refused",
          refused_hw.status_code == 422,
          str(refused_hw.status_code))

    bad_auth = client.post(
        "/api/v1/nodes/smoke-node/heartbeat",
        json={"available": True,
              "node_token": "wrong-token-123456",
              "telemetry": TELEMETRY})
    check("bad credential still refused",
          bad_auth.status_code == 403, str(bad_auth.status_code))

    wild = client.post(
        "/api/v1/nodes/smoke-node/heartbeat",
        json={"available": True, "node_token": TOKEN,
              "capabilities": ["*"]})
    check("wildcard capability still refused",
          wild.status_code == 422, str(wild.status_code))

    print("smoke done", flush=True)
