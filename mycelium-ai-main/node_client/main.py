import argparse
import asyncio
import logging
import os
import platform
import socket
import time
import uuid

import httpx
import psutil

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("mycelium.node")

BOOT_TIME = time.time()


def detected_memory_mb() -> int:
    """Return local physical memory without adding a dependency to small nodes."""
    try:
        return psutil.virtual_memory().total // (1024 * 1024)
    except Exception:
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


def collect_telemetry() -> dict:
    """Collect system telemetry. Only safe, read-only metrics."""
    telemetry = {
        "hostname": socket.gethostname(),
        "os": platform.system(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count() or 1,
        "boot_time": BOOT_TIME,
    }
    try:
        telemetry["cpu_percent"] = psutil.cpu_percent(interval=0.1)
    except Exception:
        telemetry["cpu_percent"] = 0.0
    try:
        mem = psutil.virtual_memory()
        telemetry["memory_total_mb"] = mem.total // (1024 * 1024)
        telemetry["memory_available_mb"] = mem.available // (1024 * 1024)
        telemetry["memory_percent"] = mem.percent
    except Exception:
        telemetry["memory_total_mb"] = detected_memory_mb()
        telemetry["memory_available_mb"] = 0
        telemetry["memory_percent"] = 0.0
    try:
        disk = psutil.disk_usage("/")
        telemetry["disk_total_gb"] = round(disk.total / (1024**3), 1)
        telemetry["disk_free_gb"] = round(disk.free / (1024**3), 1)
        telemetry["disk_percent"] = round((disk.used / disk.total) * 100, 1)
    except Exception:
        telemetry["disk_total_gb"] = 0.0
        telemetry["disk_free_gb"] = 0.0
        telemetry["disk_percent"] = 0.0
    try:
        telemetry["uptime_seconds"] = int(time.time() - BOOT_TIME)
    except Exception:
        telemetry["uptime_seconds"] = 0
    # Temperature (Linux only, best effort)
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            # Get first CPU temperature
            for name, entries in temps.items():
                for entry in entries:
                    if entry.current:
                        telemetry["temperature_celsius"] = entry.current
                        break
                if "temperature_celsius" in telemetry:
                    break
    except Exception:
        pass
    # Load average (Unix only)
    try:
        if hasattr(os, "getloadavg"):
            telemetry["load_average"] = list(os.getloadavg())
    except Exception:
        pass
    # Network interfaces (names only)
    try:
        net_if = psutil.net_if_addrs()
        telemetry["network_interfaces"] = list(net_if.keys())[:10]
    except Exception:
        telemetry["network_interfaces"] = []
    return telemetry


def collect_hardware() -> list[dict]:
    """Collect hardware inventory. Only safe, read-only detection."""
    hardware = []
    # Cameras (Linux video4linux)
    try:
        import glob
        for video_dev in glob.glob("/dev/video*"):
            hardware.append({
                "kind": "camera",
                "identifier": video_dev,
                "details": {"subsystem": "v4l2"},
                "status": "connected",
                "connected_since": time.time(),
            })
    except Exception:
        pass
    # USB devices
    try:
        import subprocess
        result = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n")[:20]:
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 6:
                        bus_dev = f"{parts[1]}:{parts[3].rstrip(':')}"
                        desc = " ".join(parts[6:])
                        hardware.append({
                            "kind": "usb",
                            "identifier": bus_dev,
                            "details": {"description": desc[:120]},
                            "status": "connected",
                            "connected_since": time.time(),
                        })
    except Exception:
        pass
    # 3D printers (serial devices commonly used)
    try:
        import glob
        for serial_dev in glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"):
            hardware.append({
                "kind": "printer_3d",
                "identifier": serial_dev,
                "details": {"subsystem": "serial"},
                "status": "connected",
                "connected_since": time.time(),
            })
    except Exception:
        pass
    # GPU detection
    try:
        import subprocess
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 2:
                        hardware.append({
                            "kind": "gpu",
                            "identifier": parts[0],
                            "details": {"memory_mb": parts[1], "vendor": "nvidia"},
                            "status": "connected",
                            "connected_since": time.time(),
                        })
    except Exception:
        pass
    return hardware


def collect_compute_capabilities() -> list[dict]:
    """Detect compute/AI capabilities. Only safe checks."""
    compute = []
    # Ollama availability
    try:
        import subprocess
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            models = []
            for line in result.stdout.strip().split("\n")[1:]:  # skip header
                if line.strip():
                    parts = line.split()
                    if parts:
                        models.append(parts[0])
            compute.append({
                "capability": "ollama",
                "details": {"models": models[:20]},
                "status": "available",
                "since": time.time(),
            })
            for model in models[:10]:
                compute.append({
                    "capability": "local_models",
                    "details": {"model": model},
                    "status": "available",
                    "since": time.time(),
                })
    except Exception:
        pass
    # CPU inference always available
    compute.append({
        "capability": "cpu_inference",
        "details": {},
        "status": "available",
        "since": time.time(),
    })
    # GPU availability
    try:
        import subprocess
        result = subprocess.run(["nvidia-smi"], capture_output=True, timeout=3)
        if result.returncode == 0:
            compute.append({
                "capability": "gpu_available",
                "details": {"vendor": "nvidia"},
                "status": "available",
                "since": time.time(),
            })
            # Try to get VRAM
            try:
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=3)
                if result.returncode == 0:
                    vram_mb = sum(int(x.strip()) for x in result.stdout.strip().split("\n") if x.strip().isdigit())
                    if vram_mb > 0:
                        compute.append({
                            "capability": "vram_mb",
                            "details": {"vram_mb": vram_mb},
                            "status": "available",
                            "since": time.time(),
                        })
            except Exception:
                pass
    except Exception:
        pass
    # Capability flags based on what's available
    if any(c["capability"] == "ollama" for c in compute):
        compute.append({"capability": "research", "details": {}, "status": "available", "since": time.time()})
        compute.append({"capability": "analysis", "details": {}, "status": "available", "since": time.time()})
    if any(c["capability"] == "gpu_available" for c in compute):
        compute.append({"capability": "vision", "details": {}, "status": "available", "since": time.time()})
    compute.append({"capability": "inventory", "details": {}, "status": "available", "since": time.time()})
    return compute


def collect_energy_state() -> dict:
    """Collect energy/power state. Best effort."""
    energy = {"source": "unknown"}
    try:
        battery = psutil.sensors_battery()
        if battery:
            energy["source"] = "battery"
            energy["level_percent"] = int(battery.percent)
            energy["charging"] = battery.power_plugged
        else:
            # No battery = likely grid
            energy["source"] = "grid"
            energy["level_percent"] = 100
            energy["charging"] = True
    except Exception:
        energy["source"] = "unknown"
    return energy


FETCH_MAX_CHARS = 65536
FETCH_TIMEOUT_SECONDS = 20.0
FETCH_ALLOWED_CONTENT = ("text/", "application/json",
                         "application/xml")


def _fetch_host_blocked(host: str) -> bool:
    """Local numeric/host check on the node. The coordinator
    validates every URL fully first (research_transport); this is
    defense in depth for the bytes this host actually opens."""
    import ipaddress as _ip
    cleaned = (host or "").lower().rstrip(".")
    if not cleaned:
        return True
    try:
        parsed = _ip.ip_address(cleaned)
        return (parsed.is_private or parsed.is_loopback
                or parsed.is_link_local or parsed.is_multicast
                or parsed.is_reserved or parsed.is_unspecified)
    except ValueError:
        pass
    if cleaned in ("localhost",):
        return True
    if all(part.isdigit() and 0 <= int(part) <= 255
           for part in cleaned.split(".") if part) and \
            "." in cleaned:
        return True
    return False


async def fetch_url_narrow_async(
        url: str, max_chars: int = FETCH_MAX_CHARS
        ) -> tuple[bool, dict, str | None]:
    """Async variant for tests. Same guards as the sync path."""
    checked = _check_fetch_url(url, max_chars)
    if isinstance(checked, str):
        return False, {}, checked
    text, cap = checked
    try:
        async with httpx.AsyncClient(
                timeout=FETCH_TIMEOUT_SECONDS,
                follow_redirects=False) as client:
            response = await client.get(
                text, headers={"User-Agent": "MyceliumNode/1 "
                                            "(research fetch)"})
    except Exception as error:
        return False, {}, f"fetch failed: {error}"
    return _fetch_result(response, text, cap)


def _check_fetch_url(url: str, max_chars: int
                     ) -> tuple[str, int] | str:
    """Shared URL guards. Returns (url, cap) or an error string."""
    from urllib.parse import urlparse as _urlparse
    if not isinstance(url, str) or not url.strip():
        return "fetch needs a URL"
    text = url.strip()
    if len(text) > 2000:
        return "URL too long; refusing"
    try:
        parsed = _urlparse(text)
    except ValueError as error:
        return f"URL unparsable: {error}"
    if parsed.scheme.lower() not in ("https", "http"):
        return "https/http URLs only; refusing"
    if not parsed.hostname or _fetch_host_blocked(
            parsed.hostname):
        return "host refused (local/numeric/empty)"
    if "@" in text.split("://", 1)[1].split("/", 1)[0]:
        return "credentials in URLs are refused"
    try:
        cap = max(1024, min(int(max_chars or FETCH_MAX_CHARS),
                            FETCH_MAX_CHARS))
    except (TypeError, ValueError):
        return "max_chars must be an integer"
    return text, cap


def _fetch_result(response, text: str, cap: int
                  ) -> tuple[bool, dict, str | None]:
    """Shared bounded response handling. No redirects, text only."""
    if response.status_code in (301, 302, 303, 307, 308):
        return False, {}, "redirects are never followed; refusing"
    if not 200 <= response.status_code < 300:
        return False, {}, f"HTTP {response.status_code}; refusing"
    content_type = response.headers.get("content-type", "").lower()
    if content_type and not content_type.startswith(
            FETCH_ALLOWED_CONTENT):
        return False, {}, (f"content-type '{content_type}' refused; "
                            "text only")
    body = response.content[:cap + 1]
    truncated = len(body) > cap
    decoded = body[:cap].decode("utf-8", errors="replace")
    return True, {"url": text, "status_code": response.status_code,
                  "content_type": content_type[:120],
                  "text": decoded, "truncated": truncated,
                  "chars": len(decoded)}, None


def fetch_url_narrow(url: str, max_chars: int = FETCH_MAX_CHARS
                     ) -> tuple[bool, dict, str | None]:
    """Fetch one coordinator-approved URL as bounded text (sync,
    for the claim loop). No redirects, no credentials, no
    binaries, no shell — bytes in, text out."""
    checked = _check_fetch_url(url, max_chars)
    if isinstance(checked, str):
        return False, {}, checked
    text, cap = checked
    try:
        with httpx.Client(timeout=FETCH_TIMEOUT_SECONDS,
                          follow_redirects=False) as client:
            response = client.get(
                text, headers={"User-Agent": "MyceliumNode/1 "
                                            "(research fetch)"})
    except Exception as error:
        return False, {}, f"fetch failed: {error}"
    return _fetch_result(response, text, cap)


def execute_safe_task(task: dict[str, object]) -> tuple[bool, dict[str, object], str | None]:
    """Execute only allow-listed, non-invasive local tasks.

    This function is intentionally small: task payloads never become commands,
    paths or Python code. New executors need their own explicit review.

    The claim loop auto-executes, so it may only serve read-only kinds:
    system_inventory, desktop_screenshot and research.fetch_url.
    Desktop INPUT (click, type, key presses, ...) is never
    auto-executed here: those actions run exclusively in the local
    desktop runtime after explicit human approval (see
    coordinator/app/agent_loop.py). A node that claims input tasks
    receives a refusal, never silent execution.
    """
    if task["kind"] == "research.fetch_url":
        payload = task.get("payload", {})
        if not isinstance(payload, dict):
            return False, {}, "fetch payload must be an object"
        return fetch_url_narrow(
            str(payload.get("url", "")),
            int(payload.get("max_chars", FETCH_MAX_CHARS))
            if str(payload.get("max_chars", "")).strip().isdigit()
            else FETCH_MAX_CHARS)
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
    parser.add_argument("--node-token", default=None,
                        help="Node credential (or MYCELIUM_NODE_TOKEN); bound on first register, required afterwards")
    parser.add_argument("--executor", action="append", default=[], help="Executor to advertise, exec:<kind>; can be supplied more than once")
    parser.add_argument("--model", action="append", default=[], help="Model to advertise as model_id:type, e.g. model:sim-vlm:vlm; can be supplied more than once")
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    return parser.parse_args()


def node_token_from(config: argparse.Namespace) -> str | None:
    token = config.node_token or os.environ.get("MYCELIUM_NODE_TOKEN", "")
    return token.strip() or None


def advertised_models(specs: list[str]) -> list[dict]:
    """Parse --model model_id:type entries. Fail fast on bad input."""
    models = []
    for spec in specs or []:
        if ":" not in spec:
            raise ValueError(f"Model spec '{spec}' must be model_id:type")
        model_id, _, model_type = spec.rpartition(":")
        models.append({"model_id": model_id.strip(),
                       "display_name": model_id.strip(),
                       "model_type": model_type.strip() or "other",
                       "capabilities": [],
                       "provider": "local",
                       "status": "available"})
    return models


async def run(config: argparse.Namespace) -> None:
    base_url = config.coordinator.rstrip("/") + "/api/v1"
    token = node_token_from(config)
    registration = {"node_id": config.node_id, "hostname": socket.gethostname(), "tier": config.tier,
                    "capabilities": config.capability, "cpu_cores": os.cpu_count() or 1,
                    "memory_mb": detected_memory_mb(), "energy_source": config.energy_source,
                    "executors": config.executor, "models": advertised_models(config.model)}
    if token:
        registration["node_token"] = token
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(f"{base_url}/nodes/register", json=registration)
        response.raise_for_status()
        logger.info("registered %s on %s (%s)", config.node_id, platform.system(), config.tier)
        while True:
            try:
                heartbeat = {"available": True}
                if token:
                    heartbeat["node_token"] = token
                # BIG #39: Include telemetry, hardware, compute capabilities, energy state
                heartbeat["telemetry"] = collect_telemetry()
                heartbeat["hardware"] = collect_hardware()
                heartbeat["compute_capabilities"] = collect_compute_capabilities()
                heartbeat["energy_state"] = collect_energy_state()
                await client.post(f"{base_url}/nodes/{config.node_id}/heartbeat", json=heartbeat)
                claim_url = f"{base_url}/tasks/claim/{config.node_id}"
                if token:
                    from urllib.parse import quote
                    claim_url += f"?node_token={quote(token, safe='')}"
                response = await client.post(claim_url)
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
