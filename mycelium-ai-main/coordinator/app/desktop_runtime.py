"""Desktop-agent runtime: local hands for approved actions (Fase G/H).

The coordinator never moves a mouse: this module runs inside a local
agent process (same machine, logged-in session) and executes only
ComputerActions that the operator already approved. The interface is
swappable; the Windows implementation uses nothing but the standard
library (ctypes -> user32/gdi32) plus a hand-written BMP writer, so
no new dependency was needed.

Backends:

- WindowsDesktopBackend: real screenshot (BMP, bottom-up 24-bit),
  SetCursorPos/SendInput mouse, SendInput keyboard, active-window
  title. Only constructs on Windows; otherwise BackendUnavailable.
- DryRunDesktopBackend: safe default everywhere else (and whenever
  MYCELIUM_DESKTOP_DRYRUN=1). It validates every action but executes
  nothing: input actions report blocked, screenshots raise
  BackendUnavailable. Tests always use this backend.

Safety (tested where side-effect-free):

- execute() re-validates parameters (defense in depth) and refuses
  unknown types without touching the desktop.
- run_approved_action() only runs records with status dispatched;
  anything else raises before any input happens.
- execute() never raises for input actions: failures become failed
  results with a bounded error string.
- screenshots land in the local temp observation directory only;
  prune_observations() keeps the latest OBSERVATION_RETENTION files.
- no shell, no subprocess, no code execution anywhere in this module.
"""

import ctypes
import os
import struct
import tempfile
import time
from datetime import datetime, timezone

from .agent_loop import DesktopActionRecord, record_result
from .agent_results import AgentActionResult, new_result
from .computer_actions import (
    KEYBOARD_PRESS,
    KEYBOARD_TYPE,
    MOUSE_CLICK,
    MOUSE_MOVE,
    MOUSE_SCROLL,
    SCREEN_READ,
    validate_parameters,
)
from .observations import (
    OBSERVATION_RETENTION,
    ScreenObservation,
    new_observation,
)

OBS_DIR_NAME = "mycelium-obs"
DRYRUN_ENV_VAR = "MYCELIUM_DESKTOP_DRYRUN"


class BackendUnavailable(RuntimeError):
    """No desktop backend can run here. Fail-closed, never fake input."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def observation_dir() -> str:
    path = os.path.join(tempfile.gettempdir(), OBS_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def prune_observations(keep: int = OBSERVATION_RETENTION) -> int:
    """Delete oldest observation files beyond retention. Returns removed."""
    try:
        entries = os.listdir(observation_dir())
    except OSError:
        return 0
    shots = sorted(entry for entry in entries
                   if entry.startswith("obs-")
                   and entry.lower().endswith((".bmp", ".png")))
    removed = 0
    for entry in shots[:max(0, len(shots) - keep)]:
        try:
            os.remove(os.path.join(observation_dir(), entry))
            removed += 1
        except OSError:
            continue
    return removed


def _safe_filename(observation_id: str) -> str:
    cleaned = "".join(char for char in observation_id
                      if char.isalnum() or char in ("-", "_"))[:60]
    return f"{cleaned or 'obs'}.bmp"


def write_bmp_24(path: str, width: int, height: int,
                 bgr_rows_top_down: bytes) -> None:
    """Write 24-bit bottom-up BMP with stdlib only. No imaging dependency."""
    row_stride = (width * 3 + 3) // 4 * 4
    padding = row_stride - width * 3
    body = bytearray()
    for row in range(height - 1, -1, -1):
        start = row * width * 3
        body += bgr_rows_top_down[start:start + width * 3]
        body += b"\x00" * padding
    file_size = 14 + 40 + len(body)
    header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, 14 + 40)
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0,
                       len(body), 0, 0, 0, 0)
    with open(path, "wb") as handle:
        handle.write(header)
        handle.write(info)
        handle.write(body)


class DesktopBackend:
    """Interface for local computer interaction."""

    def capabilities(self) -> list[str]:
        raise NotImplementedError

    def screenshot(self) -> ScreenObservation:
        raise NotImplementedError

    def execute(self, action) -> AgentActionResult:
        raise NotImplementedError


class DryRunDesktopBackend(DesktopBackend):
    """Validates everything, executes nothing. Default outside Windows."""

    def capabilities(self) -> list[str]:
        return [SCREEN_READ]

    def screenshot(self) -> ScreenObservation:
        raise BackendUnavailable(
            "Dry-run backend takes no screenshots; refusing")

    def execute(self, action) -> AgentActionResult:
        from .computer_actions import ComputerAction
        if not isinstance(action, ComputerAction):
            return new_result("unknown", "blocked",
                              error="Not a ComputerAction; refusing")
        try:
            validate_parameters(action.action_type, action.parameters)
        except ValueError as error:
            return new_result(action.action_id, "blocked", error=str(error))
        if action.action_type in ("screenshot", "wait"):
            return new_result(action.action_id, "blocked",
                              error="Dry-run backend executes nothing; "
                                    "screenshot/wait need a real backend")
        return new_result(action.action_id, "blocked",
                          error="Dry-run backend performs no input; "
                                "action stays blocked")


_VK_CODES = {
    "enter": 0x0D, "tab": 0x09, "escape": 0x1B, "esc": 0x1B,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "insert": 0x2D, "printscreen": 0x2C, "pause": 0x13,
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "cmd": 0x5B,
}
_VK_CODES.update({f"f{n}": 0x6F + n for n in range(1, 13)})
_VK_CODES.update({chr(c): c - 32 for c in range(ord("a"), ord("z") + 1)})
_VK_CODES.update({str(d): ord(str(d)) for d in range(10)})


class WindowsDesktopBackend(DesktopBackend):
    """Real local input via user32/gdi32. Windows + stdlib only."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise BackendUnavailable("Windows backend needs Windows")
        try:
            self._user32 = ctypes.windll.user32
            self._gdi32 = ctypes.windll.gdi32
        except (AttributeError, OSError) as error:
            raise BackendUnavailable(
                f"Desktop APIs unavailable: {error}") from error
        self._user32.SetProcessDPIAware()

    def capabilities(self) -> list[str]:
        return [SCREEN_READ, MOUSE_MOVE, MOUSE_CLICK, MOUSE_SCROLL,
                KEYBOARD_TYPE, KEYBOARD_PRESS]

    # -- observation ----------------------------------------------------

    def _screen_size(self) -> tuple[int, int]:
        width = self._user32.GetSystemMetrics(0)
        height = self._user32.GetSystemMetrics(1)
        if width < 1 or height < 1:
            raise BackendUnavailable("Could not read screen size")
        return int(width), int(height)

    def _active_window(self) -> str:
        try:
            handle = self._user32.GetForegroundWindow()
            if not handle:
                return ""
            length = self._user32.GetWindowTextLengthW(handle)
            if length < 1 or length > 200:
                return ""
            buffer = ctypes.create_unicode_buffer(length + 1)
            self._user32.GetWindowTextW(handle, buffer, length + 1)
            return buffer.value or ""
        except (AttributeError, OSError):
            return ""

    def screenshot(self) -> ScreenObservation:
        width, height = self._screen_size()
        user32, gdi32 = self._user32, self._gdi32
        observation_id = (f"obs-{int(time.time() * 1000):x}")
        filename = _safe_filename(observation_id)
        path = os.path.join(observation_dir(), filename)
        try:
            screen_dc = user32.GetDC(None)
            memory_dc = gdi32.CreateCompatibleDC(screen_dc)
            bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
            gdi32.SelectObject(memory_dc, bitmap)
            ok = gdi32.BitBlt(memory_dc, 0, 0, width, height, screen_dc,
                              0, 0, 0x00CC0020)
            info = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 24,
                               0, 0, 0, 0, 0, 0)
            buffer_size = width * height * 3
            pixels = ctypes.create_string_buffer(buffer_size)
            lines = gdi32.GetDIBits(memory_dc, bitmap, 0, height,
                                    pixels, info, 0)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(None, screen_dc)
            if not ok or lines != height:
                raise BackendUnavailable("Screen capture failed")
            write_bmp_24(path, width, height, pixels.raw)
        except BackendUnavailable:
            raise
        except (AttributeError, OSError, struct.error) as error:
            raise BackendUnavailable(
                f"Screen capture failed: {error}") from error
        prune_observations()
        return new_observation(f"{observation_id}", width, height,
                               image_ref=filename,
                               active_window=self._active_window())

    # -- input ----------------------------------------------------------

    def _send_input(self, inputs) -> None:
        count = self._user32.SendInput(len(inputs), inputs,
                                       ctypes.sizeof(inputs[0]))
        if count != len(inputs):
            raise BackendUnavailable("Input was not accepted")

    def _mouse_input(self, flags: int, data: int = 0,
                     dx: int = 0, dy: int = 0):
        class MouseInput(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                        ("mouseData", ctypes.c_ulong),
                        ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.c_void_p)]

        class Input(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong),
                        ("mi", MouseInput)]
        return (Input * 1)(Input(type=0, mi=MouseInput(
            dx=dx, dy=dy, mouseData=data, dwFlags=flags, time=0,
            dwExtraInfo=None)))

    def _key_inputs(self, virtual_key: int, press: bool):
        class KeyInput(ctypes.Structure):
            _fields_ = [("wVk", ctypes.c_ushort),
                        ("wScan", ctypes.c_ushort),
                        ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.c_void_p)]

        class Input(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong),
                        ("ki", KeyInput)]
        flags = 0x0002 if not press else 0x0000
        return (Input * 1)(Input(type=1, ki=KeyInput(
            wVk=virtual_key, wScan=0, dwFlags=flags, time=0,
            dwExtraInfo=None)))

    def _unicode_inputs(self, text: str):
        class KeyInput(ctypes.Structure):
            _fields_ = [("wVk", ctypes.c_ushort),
                        ("wScan", ctypes.c_ushort),
                        ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.c_void_p)]

        class Input(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong),
                        ("ki", KeyInput)]
        events = (Input * (len(text) * 2))()
        for position, char in enumerate(text):
            code = ord(char)
            events[position * 2] = Input(type=1, ki=KeyInput(
                wVk=0, wScan=code, dwFlags=0x0004, time=0,
                dwExtraInfo=None))
            events[position * 2 + 1] = Input(type=1, ki=KeyInput(
                wVk=0, wScan=code, dwFlags=0x0004 | 0x0002, time=0,
                dwExtraInfo=None))
        return events

    def _click_flags(self, button: str) -> tuple[int, int]:
        return {"left": (0x0002, 0x0004),
                "right": (0x0008, 0x0010),
                "middle": (0x0020, 0x0040)}[button]

    def _do_execute(self, action_type: str, params: dict) -> str:
        if action_type == "screenshot":
            observation = self.screenshot()
            return observation.observation_id
        if action_type == "wait":
            time.sleep(min(params.get("ms", 0), 30000) / 1000.0)
            return ""
        if action_type == "move_mouse":
            self._user32.SetCursorPos(params["x"], params["y"])
            return ""
        if action_type in ("click", "double_click"):
            self._user32.SetCursorPos(params["x"], params["y"])
            down, up = self._click_flags(params.get("button", "left"))
            self._send_input(self._mouse_input(down))
            self._send_input(self._mouse_input(up))
            if action_type == "double_click":
                time.sleep(0.05)
                self._send_input(self._mouse_input(down))
                self._send_input(self._mouse_input(up))
            return ""
        if action_type == "scroll":
            self._send_input(self._mouse_input(0x0800,
                                               data=params.get("dy", 0)))
            return ""
        if action_type == "type_text":
            text = params["text"]
            for offset in range(0, len(text), 64):
                self._send_input(
                    self._unicode_inputs(text[offset:offset + 64]))
            return ""
        if action_type == "key_press":
            code = _VK_CODES[params["key"]]
            self._send_input(self._key_inputs(code, True))
            self._send_input(self._key_inputs(code, False))
            return ""
        if action_type == "hotkey":
            codes = [_VK_CODES[key] for key in params["keys"]]
            for code in codes:
                self._send_input(self._key_inputs(code, True))
            for code in reversed(codes):
                self._send_input(self._key_inputs(code, False))
            return ""
        raise BackendUnavailable(f"Unknown action '{action_type}'")

    def execute(self, action) -> AgentActionResult:
        from .computer_actions import ComputerAction
        if not isinstance(action, ComputerAction):
            return new_result("unknown", "blocked",
                              error="Not a ComputerAction; refusing")
        try:
            params = validate_parameters(action.action_type,
                                         action.parameters)
        except ValueError as error:
            return new_result(action.action_id, "blocked", error=str(error))
        started = now()
        try:
            observation_ref = self._do_execute(action.action_type, params)
        except BackendUnavailable as error:
            result = new_result(action.action_id, "failed",
                                error=str(error)[:2000])
        except (AttributeError, OSError) as error:
            result = new_result(action.action_id, "failed",
                                error=f"Desktop call failed: {error}"[:2000])
        else:
            result = new_result(action.action_id, "completed",
                                observation_reference=observation_ref)
        return result.model_copy(update={"started_at": started,
                                         "completed_at": now()})


def get_backend() -> DesktopBackend:
    """Local backend selection. Never fakes: no Windows means dry-run."""
    if os.environ.get(DRYRUN_ENV_VAR, "").strip() == "1":
        return DryRunDesktopBackend()
    if os.name == "nt":
        try:
            return WindowsDesktopBackend()
        except BackendUnavailable:
            return DryRunDesktopBackend()
    return DryRunDesktopBackend()


def run_approved_action(record: DesktopActionRecord,
                        backend: DesktopBackend) -> DesktopActionRecord:
    """Execute one dispatched record. Refuses anything not dispatched."""
    if not isinstance(record, DesktopActionRecord):
        raise ValueError("Agent loop needs a DesktopActionRecord")
    if record.status != "dispatched":
        raise ValueError(
            f"Action is {record.status}; only dispatched actions run")
    from .computer_actions import ComputerAction
    if not isinstance(record.action, ComputerAction):
        raise ValueError("Record carries no valid ComputerAction")
    outcome = backend.execute(record.action)
    return record_result(record, record.action.action_id, outcome.status,
                         error=outcome.error,
                         observation_reference=outcome.observation_reference)
