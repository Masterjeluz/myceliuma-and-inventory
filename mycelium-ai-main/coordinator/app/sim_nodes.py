"""Deterministic multi-node simulator (BIG #8, tests/orchestration).

Three fake node advertisements with disjoint capabilities for
routing and queue tests. TEST-ONLY: these dicts exercise the
coordinator's scheduling decisions, never real execution and
never real-world results.

- node_desktop: desktop input + screen reading
- node_vision: camera + VLM-flavoured vision
- node_cpu: plain system inventory executor
"""

SIM_NODES = {
    "node_desktop": {
        "node_id": "node_desktop",
        "hostname": "sim-desktop",
        "tier": "worker",
        "display_name": "Simulated desktop",
        "capabilities": [
            "agent:desktop",
            "desktop.screen.read",
            "desktop.mouse.click",
            "desktop.keyboard.type",
        ],
        "executors": ["exec:desktop"],
        "models": [],
        "resources": {"cpu_cores": 4, "memory_mb": 8000,
                      "energy_source": "grid",
                      "energy_priority": "normal"},
        "locality_zone": "local_network",
        "cpu_cores": 4,
        "memory_mb": 8000,
        "energy_source": "grid",
    },
    "node_vision": {
        "node_id": "node_vision",
        "hostname": "sim-vision",
        "tier": "worker",
        "display_name": "Simulated vision",
        "capabilities": [
            "camera.read",
            "camera.snapshot",
            "vision.detect",
            "vision.describe",
        ],
        "executors": ["exec:vision", "exec:camera"],
        "models": [{
            "model_id": "model:sim-vlm",
            "display_name": "Simulated VLM",
            "model_type": "vlm",
            "capabilities": ["vision.describe"],
            "provider": "test-only",
            "status": "available",
        }],
        "resources": {"cpu_cores": 8, "memory_mb": 16000,
                      "gpu_available": True, "gpu_memory_mb": 8000,
                      "energy_source": "solar", "energy_level": 80,
                      "energy_priority": "normal"},
        "locality_zone": "local_network",
        "cpu_cores": 8,
        "memory_mb": 16000,
        "energy_source": "solar",
    },
    "node_cpu": {
        "node_id": "node_cpu",
        "hostname": "sim-cpu",
        "tier": "seed",
        "display_name": "Simulated CPU",
        "capabilities": ["exec:system_inventory"],
        "executors": ["exec:system_inventory"],
        "models": [],
        "resources": {"cpu_cores": 2, "memory_mb": 2000,
                      "energy_source": "grid",
                      "energy_priority": "low"},
        "locality_zone": "local_network",
        "cpu_cores": 2,
        "memory_mb": 2000,
        "energy_source": "grid",
    },
}


def sim_registration(node_id: str) -> dict:
    """Registration JSON for one simulated node (test-only)."""
    if node_id not in SIM_NODES:
        raise ValueError(f"Unknown simulated node '{node_id}'")
    node = SIM_NODES[node_id]
    return {
        "node_id": node["node_id"],
        "hostname": node["hostname"],
        "tier": node["tier"],
        "display_name": node["display_name"],
        "capabilities": list(node["capabilities"]),
        "executors": list(node["executors"]),
        "models": [dict(entry) for entry in node["models"]],
        "resources": dict(node["resources"]),
        "locality_zone": node["locality_zone"],
        "cpu_cores": node["cpu_cores"],
        "memory_mb": node["memory_mb"],
        "energy_source": node["energy_source"],
    }
