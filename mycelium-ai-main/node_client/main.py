import argparse
import asyncio
import logging
import os
import platform
import socket
import uuid

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("mycelium.node")


def detected_memory_mb() -> int:
    """Return local physical memory without adding a dependency to small nodes."""
    if os.name == "nt":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
                            ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                            ("total_page_file", ctypes.c_ulonglong), ("avail_page_file", ctypes.c_ulonglong),
                            ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                            ("avail_extended_virtual", ctypes.c_ulonglong)]
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.total_phys // (1024 * 1024)
        except (AttributeError, OSError):
            return 0
    try:
        return (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) // (1024 * 1024)
    except (AttributeError, OSError, ValueError):
        return 0


def execute_safe_task(task: dict[str, object]) -> tuple[bool, dict[str, object], str | None]:
    """Execute only allow-listed, non-invasive local tasks.

    This function is intentionally small: task payloads never become commands,
    paths or Python code. New executors need their own explicit review.

    The claim loop auto-executes, so it may only serve read-only kinds:
    system_inventory and desktop_screenshot. Desktop INPUT (click, type,
    key presses, ...) is never auto-executed here: those actions run
    exclusively in the local desktop runtime after explicit human
    approval (see coordinator/app/agent_loop.py). A node that claims
    input tasks receives a refusal, never silent execution.
    """
    if task["kind"] == "system_inventory":
        return True, {
            "operating_system": platform.system(),
            "machine": platform.machine(),
            "cpu_cores": os.cpu_count() or 1,
            "memory_mb": detected_memory_mb(),
        }, None
    if task["kind"] == "desktop_screenshot":
        try:
            from coordinator.app.desktop_runtime import get_backend
        except ImportError as error:
            return False, {}, f"Screenshot backend unavailable: {error}"
        try:
            observation = get_backend().screenshot()
        except Exception as error:
            return False, {}, f"Screenshot refused: {error}"
        return True, observation.model_dump(mode="json"), None
    if str(task["kind"]).startswith("desktop_"):
        return False, {}, (
            f"Desktop input '{task['kind']}' needs explicit human approval "
            "and never auto-executes in the claim loop; refusing")
    return False, {}, f"No safe executor installed for task kind: {task['kind']}"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lightweight Mycelium AI node")
    parser.add_argument("--coordinator", default="http://localhost:8000")
    parser.add_argument("--node-id", default=f"node-{uuid.getnode():x}")
    parser.add_argument("--tier", choices=["seed", "worker", "core"], default="seed")
    parser.add_argument("--capability", action="append", default=[], help="Can be supplied more than once")
    parser.add_argument("--energy-source", default="unknown", help="For example solar, grid or battery")
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    return parser.parse_args()


async def run(config: argparse.Namespace) -> None:
    base_url = config.coordinator.rstrip("/") + "/api/v1"
    registration = {"node_id": config.node_id, "hostname": socket.gethostname(), "tier": config.tier,
                    "capabilities": config.capability, "cpu_cores": os.cpu_count() or 1,
                    "memory_mb": detected_memory_mb(), "energy_source": config.energy_source}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(f"{base_url}/nodes/register", json=registration)
        response.raise_for_status()
        logger.info("registered %s on %s (%s)", config.node_id, platform.system(), config.tier)
        while True:
            try:
                await client.post(f"{base_url}/nodes/{config.node_id}/heartbeat", json={"available": True})
                response = await client.post(f"{base_url}/tasks/claim/{config.node_id}")
                response.raise_for_status()
                task = response.json()
                if task:
                    logger.info("received task %s (%s)", task["id"], task["kind"])
                    success, result, error = execute_safe_task(task)
                    completion = await client.post(f"{base_url}/tasks/{task['id']}/complete", json={
                        "success": success, "result": result, "error": error,
                    })
                    completion.raise_for_status()
            except httpx.HTTPError as error:
                logger.warning("coordinator unavailable: %s", error)
            await asyncio.sleep(config.poll_seconds)


if __name__ == "__main__":
    asyncio.run(run(arguments()))
