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
        "architecture": platform.machine(),
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


def parse_xrandr_query(text: str) -> list[dict]:
    """Parse `xrandr --query` output into display reports. Pure.

    Only connected outputs become entries. Anything unparsable
    yields None fields (never guessed); outputs without an
    active mode keep width/height None. No I/O, no fallback
    data — used by collect_displays() and unit-tested with
    captured samples."""
    import re
    displays: list[dict] = []
    # e.g. "HDMI-1 connected primary 1920x1080+0+0 (normal ...) 477mm x 268mm"
    # e.g. "eDP-1 connected 1920x1080+1920+0 (normal ...) 344mm x 193mm"
    # e.g. "DP-1 disconnected (normal ...)"
    header = re.compile(
        r"^(?P<output>\S+)\s+(?P<state>connected|disconnected)\b"
        r"(?P<rest>.*)$")
    geometry = re.compile(
        r"(?P<width>\d+)x(?P<height>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+)")
    phys = re.compile(r"(?P<wmm>\d+)mm\s*x\s*(?P<hmm>\d+)mm")
    mode = re.compile(
        r"^\s+(?P<width>\d+)x(?P<height>\d+)\s+(?P<rates>[\d.\s*+]+)")
    current: dict | None = None
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        match = header.match(line)
        if match and not line.startswith((" ", "\t")):
            if match.group("state") != "connected":
                current = None
                continue
            rest = match.group("rest") or ""
            geo = geometry.search(rest)
            size = phys.search(rest)
            rotation = re.search(r"\(([^)]*)\)", rest)
            orientation = "unknown"
            if rotation:
                first = (rotation.group(1) or "").split()
                if first and first[0] in (
                        "normal", "left", "right", "inverted"):
                    orientation = first[0]
            output = match.group("output")
            current = {
                "id": output[:120],
                "name": output[:120],
                "width": int(geo.group("width"))
                if geo else None,
                "height": int(geo.group("height"))
                if geo else None,
                "refresh_rate": None,
                "physical_width_mm": int(size.group("wmm"))
                if size else None,
                "physical_height_mm": int(size.group("hmm"))
                if size else None,
                "x": int(geo.group("x")) if geo else None,
                "y": int(geo.group("y")) if geo else None,
                "scale": None,
                "orientation": orientation,
                "primary": "primary" in rest.split(),
            }
            displays.append(current)
            continue
        if current is not None:
            modeline = mode.match(line)
            if modeline and current["refresh_rate"] is None:
                try:
                    width = int(modeline.group("width"))
                    height = int(modeline.group("height"))
                except ValueError:
                    continue
                if ("*" in line and width == current.get("width")
                        and height == current.get("height")):
                    rates = re.findall(r"(\d+(?:\.\d+)?)\*",
                                       modeline.group("rates"))
                    if rates:
                        try:
                            current["refresh_rate"] = float(rates[0])
                        except ValueError:
                            current["refresh_rate"] = None
    return displays[:16]


def _collect_displays_xrandr() -> list[dict] | None:
    """Linux X11/XWayland discovery via xrandr. Returns None when
    xrandr is unavailable (Wayland-native, headless, missing) so
    the caller can report honestly empty. No shell, 5s timeout."""
    import shutil
    import subprocess
    if shutil.which("xrandr") is None:
        return None
    try:
        result = subprocess.run(
            ["xrandr", "--query"], capture_output=True, text=True,
            timeout=5)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    try:
        return parse_xrandr_query(result.stdout or "")
    except Exception:
        return None


def _collect_displays_windows() -> list[dict] | None:
    """Windows discovery via EnumDisplayDevices/EnumDisplaySettings
    (read-only, ctypes, no new dependency). Returns None when the
    API is unreachable. Physical size/scale stay None — this API
    does not reliably expose them, and we never guess."""
    import ctypes
    from ctypes import wintypes
    try:
        user32 = ctypes.windll.user32
    except Exception:
        return None
    try:
        class DISPLAY_DEVICEW(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128),
                ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128),
                ("DeviceKey", wintypes.WCHAR * 128),
            ]

        class _DevmodeDisplay(ctypes.Structure):
            _fields_ = [
                ("dmPositionX", ctypes.c_long),
                ("dmPositionY", ctypes.c_long),
                ("dmDisplayOrientation", wintypes.DWORD),
                ("dmDisplayFixedOutput", wintypes.DWORD),
            ]

        class _DevmodeUnion(ctypes.Union):
            _fields_ = [("display", _DevmodeDisplay),
                        ("raw", ctypes.c_byte * 16)]

        class DEVMODEW(ctypes.Structure):
            _fields_ = [
                ("dmDeviceName", wintypes.WCHAR * 32),
                ("dmSpecVersion", wintypes.WORD),
                ("dmDriverVersion", wintypes.WORD),
                ("dmSize", wintypes.WORD),
                ("dmDriverExtra", wintypes.WORD),
                ("dmFields", wintypes.DWORD),
                ("u", _DevmodeUnion),
                ("dmColor", ctypes.c_short),
                ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short),
                ("dmTTOption", ctypes.c_short),
                ("dmCollate", ctypes.c_short),
                ("dmFormName", wintypes.WCHAR * 32),
                ("dmLogPixels", wintypes.WORD),
                ("dmBitsPerPel", wintypes.DWORD),
                ("dmPelsWidth", wintypes.DWORD),
                ("dmPelsHeight", wintypes.DWORD),
                ("dmDisplayFlags", wintypes.DWORD),
                ("dmDisplayFrequency", wintypes.DWORD),
            ]

        user32.EnumDisplayDevicesW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.POINTER(DISPLAY_DEVICEW), wintypes.DWORD]
        user32.EnumDisplayDevicesW.restype = wintypes.BOOL
        user32.EnumDisplaySettingsW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.POINTER(DEVMODEW)]
        user32.EnumDisplaySettingsW.restype = wintypes.BOOL

        ENUM_CURRENT_SETTINGS = 0xFFFFFFFF
        DISPLAY_DEVICE_ATTACHED = 0x1
        DISPLAY_DEVICE_PRIMARY = 0x4
        displays: list[dict] = []
        index = 0
        while True:
            device = DISPLAY_DEVICEW()
            device.cb = ctypes.sizeof(device)
            if not user32.EnumDisplayDevicesW(
                    None, index, ctypes.byref(device), 0):
                break
            index += 1
            if not (device.StateFlags & DISPLAY_DEVICE_ATTACHED):
                continue
            settings = DEVMODEW()
            settings.dmSize = ctypes.sizeof(settings)
            if not user32.EnumDisplaySettingsW(
                    device.DeviceName, ENUM_CURRENT_SETTINGS,
                    ctypes.byref(settings)):
                continue
            width = int(settings.dmPelsWidth) or None
            height = int(settings.dmPelsHeight) or None
            frequency = int(settings.dmDisplayFrequency)
            ident = str(device.DeviceName or "").strip() or \
                f"DISPLAY{len(displays) + 1}"
            label = str(device.DeviceString or "").strip() or ident
            displays.append({
                "id": ident[:120],
                "name": label[:120],
                "width": width,
                "height": height,
                "refresh_rate": float(frequency)
                if frequency and frequency > 1 else None,
                "physical_width_mm": None,
                "physical_height_mm": None,
                "x": int(settings.u.display.dmPositionX),
                "y": int(settings.u.display.dmPositionY),
                "scale": None,
                "orientation": "unknown",
                "primary": bool(
                    device.StateFlags & DISPLAY_DEVICE_PRIMARY),
            })
            if len(displays) >= 16:
                break
        return displays
    except Exception:
        return None


def collect_displays() -> list[dict]:
    """Read-only display discovery for this node. Linux tries
    xrandr; Windows tries EnumDisplaySettings; anything else
    reports []. Unknown fields stay None (never guessed, never
    faked). Best-effort: any failure returns []."""
    try:
        if os.name == "nt":
            found = _collect_displays_windows()
            return found if found is not None else []
        found = _collect_displays_xrandr()
        return found if found is not None else []
    except Exception:
        return []


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
    parser.add_argument("--remote-mouse", action="store_true", default=False,
                        help="Advertise desktop.mouse.move and poll for remote mouse moves (explicit opt-in; needs a real OS mouse backend)")
    parser.add_argument("--remote-click", action="store_true", default=False,
                        help="Advertise desktop.mouse.click (explicit opt-in; probed)")
    parser.add_argument("--remote-keyboard", action="store_true", default=False,
                        help="Advertise desktop.keyboard.type/press (explicit opt-in; probed)")
    parser.add_argument("--remote-scroll", action="store_true", default=False,
                        help="Advertise desktop.mouse.scroll, vertical only (explicit opt-in; probed)")
    parser.add_argument("--remote-drag", action="store_true", default=False,
                        help="Allow button down/up for drag (needs move+click backends; probed)")
    parser.add_argument("--remote-clipboard", action="store_true", default=False,
                        help="Advertise desktop.clipboard.write/read, text only (explicit opt-in; probed)")
    parser.add_argument("--remote-mouse-poll-seconds", type=float, default=0.2,
                        help="Poll cadence for remote input while opted in")
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


async def poll_remote_input_once(client, base_url: str,
                                   node_id: str,
                                   token: str | None,
                                   tracker=None,
                                   clipboard_text: str | None = None
                                   ) -> dict | None:
    """One pull for pending remote input. Returns a summary dict
    ({move, actions, clipboard_request, released}) or None when
    idle/unknown.

    Only the allow-listed execute_remote_move/execute_remote_action
    can run here; refusals are logged and swallowed (next poll
    retries). A 410 means the session died: any held drag button
    is released via the tracker. A 404 means no session: quiet.
    """

    def _tracker():
        nonlocal tracker
        if tracker is None:
            try:
                from .remote_mouse import ButtonTracker
                tracker = ButtonTracker()
            except ImportError:
                tracker = None
        return tracker

    try:
        from .remote_mouse import (
            execute_remote_action, execute_remote_move,
        )
    except ImportError:
        return None
    payload: dict = {"node_id": node_id}
    if token:
        payload["node_token"] = token
    if clipboard_text is not None:
        payload["clipboard_text"] = clipboard_text
    try:
        response = await client.post(
            f"{base_url}/remote-input/poll", json=payload)
    except Exception as error:
        logger.debug("remote input poll failed: %s", error)
        return None
    if response.status_code == 404:
        return None
    if response.status_code == 410:
        # Session died (close/expiry/stale): release a held drag
        # button so it never sticks. Never raises.
        released = None
        active = _tracker()
        if active is not None:
            try:
                released = active.emergency_release()
            except Exception as error:
                logger.debug("button release failed: %s", error)
        return {"move": None, "actions": [],
                "clipboard_request": False, "released": released}
    if response.status_code == 204 or not response.content:
        return None
    try:
        data = response.json()
    except Exception:
        return None
    if not data:
        return None
    summary: dict = {"move": None, "actions": [],
                     "clipboard_request": bool(
                         data.get("clipboard_request", False)),
                     "released": None}
    active = _tracker()
    move = data.get("move")
    if isinstance(move, dict):
        try:
            summary["move"] = execute_remote_move(
                move.get("x"), move.get("y"))
        except Exception as error:
            logger.warning("remote move refused: %s", error)
    for action in data.get("actions") or []:
        if not isinstance(action, dict):
            continue
        params = {key: value for key, value in action.items()
                  if key not in ("kind", "seq")}
        try:
            summary["actions"].append(execute_remote_action(
                action.get("kind"), params, tracker=active))
        except Exception as error:
            logger.warning("remote action refused: %s", error)
    return summary


async def remote_input_loop(base_url: str, config: argparse.Namespace,
                            token: str | None) -> None:
    """Fast pull loop for remote input (existing HTTP pull,
    higher cadence). Runs only with remote flags on a capable
    node; every iteration is fail-closed and independent. Holds
    the drag ButtonTracker and one pending clipboard text."""
    try:
        cadence = max(0.05, float(
            getattr(config, "remote_mouse_poll_seconds", 0.2) or 0.2))
    except (TypeError, ValueError):
        cadence = 0.2
    try:
        from .remote_mouse import ButtonTracker
        tracker = ButtonTracker()
    except ImportError:
        tracker = None
    pending_clipboard: str | None = None
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                summary = await poll_remote_input_once(
                    client, base_url, config.node_id, token,
                    tracker=tracker,
                    clipboard_text=pending_clipboard)
                # Clipboard text is one-shot: sent once, then
                # dropped (the browser re-requests when needed).
                pending_clipboard = None
                if isinstance(summary, dict) and summary.get(
                        "clipboard_request"):
                    try:
                        from .remote_mouse import default_adapter
                        adapter = default_adapter()
                        if getattr(adapter,
                                   "can_clipboard_read", False):
                            try:
                                pending_clipboard = \
                                    adapter.clipboard_read()
                            except Exception as error:
                                logger.debug(
                                    "clipboard read refused: %s",
                                    error)
                    except Exception as error:
                        logger.debug("clipboard probe failed: %s",
                                     error)
            except Exception as error:
                logger.debug("remote input loop error: %s", error)
            await asyncio.sleep(cadence)


async def run(config: argparse.Namespace) -> None:
    base_url = config.coordinator.rstrip("/") + "/api/v1"
    token = node_token_from(config)
    capabilities = list(config.capability or [])
    # REMOTE INPUT SLICES 1+2: explicit opt-in per family + probe.
    # No probe means no capability advertisement (fail-closed):
    # the coordinator and the UI then refuse that input family.
    want_remote = {
        "move": bool(getattr(config, "remote_mouse", False)),
        "click": bool(getattr(config, "remote_click", False)),
        "keyboard": bool(getattr(config, "remote_keyboard", False)),
        "scroll": bool(getattr(config, "remote_scroll", False)),
        "drag": bool(getattr(config, "remote_drag", False)),
        "clipboard": bool(getattr(config, "remote_clipboard", False)),
    }
    remote_caps = {
        "move": "desktop.mouse.move",
        "click": "desktop.mouse.click",
        "keyboard_type": "desktop.keyboard.type",
        "keyboard_press": "desktop.keyboard.press",
        "scroll": "desktop.mouse.scroll",
        "clipboard_write": "desktop.clipboard.write",
        "clipboard_read": "desktop.clipboard.read",
    }
    remote_active = False
    if any(want_remote.values()):
        try:
            from .remote_mouse import probe_capabilities
            probed = probe_capabilities()
        except ImportError:
            probed = {}
        grants: list[str] = []
        if want_remote["move"] and probed.get("move"):
            grants.append(remote_caps["move"])
        if want_remote["click"] and probed.get("click"):
            grants.append(remote_caps["click"])
        if want_remote["keyboard"] and probed.get("keyboard"):
            grants.extend([remote_caps["keyboard_type"],
                           remote_caps["keyboard_press"]])
        if want_remote["scroll"] and probed.get("scroll"):
            grants.append(remote_caps["scroll"])
        if want_remote["drag"] and probed.get("drag"):
            # Drag rides on move+click backends; the down/up
            # markers are gated server-side on both. Advertise
            # both so the gate can pass (no new capability).
            grants.extend([remote_caps["move"],
                           remote_caps["click"]])
        if want_remote["clipboard"]:
            if probed.get("clipboard_write"):
                grants.append(remote_caps["clipboard_write"])
            if probed.get("clipboard_read"):
                grants.append(remote_caps["clipboard_read"])
        for granted in grants:
            if granted not in capabilities:
                capabilities.append(granted)
        remote_active = bool(grants)
        if remote_active:
            logger.info("remote input enabled (%s)",
                        ", ".join(sorted(set(grants))))
        else:
            logger.warning(
                "remote input requested but no OS backend "
                "is available here; capabilities NOT advertised")
    registration = {"node_id": config.node_id, "hostname": socket.gethostname(), "tier": config.tier,
                    "capabilities": capabilities, "cpu_cores": os.cpu_count() or 1,
                    "memory_mb": detected_memory_mb(), "energy_source": config.energy_source,
                    "executors": config.executor, "models": advertised_models(config.model)}
    if token:
        registration["node_token"] = token
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(f"{base_url}/nodes/register", json=registration)
        response.raise_for_status()
        logger.info("registered %s on %s (%s)", config.node_id, platform.system(), config.tier)
        remote_task = None
        if remote_active:
            remote_task = asyncio.create_task(
                remote_input_loop(base_url, config, token))
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
                # VERTICAL SLICE 1: read-only display report (never faked)
                heartbeat["displays"] = collect_displays()
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
                        "node_id": config.node_id,
                    })
                    completion.raise_for_status()
            except httpx.HTTPError as error:
                logger.warning("coordinator unavailable: %s", error)
            await asyncio.sleep(config.poll_seconds)


if __name__ == "__main__":
    asyncio.run(run(arguments()))
