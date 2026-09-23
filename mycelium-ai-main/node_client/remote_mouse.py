"""Node-side remote control execution (REMOTE INPUT SLICES 1+2).

Small allow-listed operations only: mouse move, click, button
down/up (drag parts), scroll (vertical), key press, hotkey,
unicode typing, text-only clipboard read/write.
No shell, no subprocess, no filesystem, no code execution.

Backends (native APIs, stdlib ctypes only):

- WindowsMouseAdapter: SetCursorPos/SendInput/clipboard APIs.
  Real on Windows, all six capabilities.
- X11MouseAdapter: XWarpPointer via libX11 plus XTest button/key
  events when libXtst loads (move always when a display is
  reachable; click/keyboard/scroll/drag only with XTest).
  Clipboard is unavailable on X11 (selection ownership needs
  an event loop — not faked, reported unavailable).
- UnavailableMouseAdapter: fail-closed everywhere else.

The node advertises each ``desktop.*`` capability only when its
probe passes AND the operator opted in per flag. No probe, no
capability. Ever.

Contracts mirror the coordinator (defense in depth): coordinates
0..16384, buttons left/right/middle, keys from the shared
allow-list, scroll deltas bounded, clipboard text-only bounded.
"""

from __future__ import annotations

import os

MAX_COORDINATE = 16384
MAX_SCROLL_DELTA = 10000
MAX_TEXT_CHARS = 500
MAX_CLIPBOARD_CHARS = 65536

MOUSE_CAPABILITY = "desktop.mouse.move"
CLICK_CAPABILITY = "desktop.mouse.click"
SCROLL_CAPABILITY = "desktop.mouse.scroll"
KEYBOARD_TYPE_CAPABILITY = "desktop.keyboard.type"
KEYBOARD_PRESS_CAPABILITY = "desktop.keyboard.press"
CLIPBOARD_WRITE_CAPABILITY = "desktop.clipboard.write"
CLIPBOARD_READ_CAPABILITY = "desktop.clipboard.read"

#: Shared key vocabulary (same table as the coordinator's
#: desktop_runtime backend: identical values, no second dialect).
KEY_ALLOW_LIST = frozenset({
    "enter", "tab", "escape", "esc", "space", "backspace", "delete",
    "up", "down", "left", "right", "home", "end", "pageup", "pagedown",
    "insert", "printscreen", "pause",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10",
    "f11", "f12",
    "ctrl", "alt", "shift", "win", "cmd",
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
})

MOUSE_BUTTONS = frozenset({"left", "right", "middle"})


class MouseUnavailableError(RuntimeError):
    """No mouse backend here. Fail-closed, never fake input."""


def check_coordinates(x, y) -> tuple[int, int]:
    """Node-side coordinate gate. Integers 0..16384, bools refused."""
    for name, value in (("x", x), ("y", y)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise MouseUnavailableError(
                f"remote input '{name}' must be an integer")
        if not 0 <= value <= MAX_COORDINATE:
            raise MouseUnavailableError(
                f"remote input '{name}' must be 0..{MAX_COORDINATE}")
    return int(x), int(y)


def check_button(value) -> str:
    if not isinstance(value, str) or value.lower() not in MOUSE_BUTTONS:
        raise MouseUnavailableError(
            "remote input button must be left/right/middle")
    return value.lower()


def check_key(value) -> str:
    if not isinstance(value, str) or value.lower() not in KEY_ALLOW_LIST:
        raise MouseUnavailableError(
            f"unknown key {str(value)[:20]!r}; refusing")
    return value.lower()


def check_keys(value) -> list[str]:
    if not isinstance(value, list) or not 2 <= len(value) <= 4:
        raise MouseUnavailableError("hotkey needs 2..4 keys")
    return [check_key(entry) for entry in value]


def check_delta(name, value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MouseUnavailableError(
            f"remote input '{name}' must be an integer")
    if not -MAX_SCROLL_DELTA <= value <= MAX_SCROLL_DELTA:
        raise MouseUnavailableError(
            f"remote input '{name}' out of range")
    return int(value)


def check_text(value, limit: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str) or not value:
        raise MouseUnavailableError("remote input text must be text")
    if len(value) > limit:
        raise MouseUnavailableError(
            f"remote input text exceeds {limit} chars")
    return value


def check_clipboard_text(value) -> str:
    """Text-only clipboard gate: bounded, no control chars except
    newline/CR/tab. Mirrors the coordinator contract."""
    text = check_text(value, MAX_CLIPBOARD_CHARS)
    for char in text:
        if ord(char) < 32 and char not in ("\n", "\r", "\t"):
            raise MouseUnavailableError(
                "clipboard text has control characters")
    return text


class MouseAdapter:
    """Allow-listed input operations. Anything not listed here
    cannot happen through this module."""

    name = "unavailable"
    #: Explicit opt-in per backend family.
    can_move = False
    can_click = False
    can_key = False
    can_scroll = False
    can_clipboard_write = False
    can_clipboard_read = False

    def move(self, x: int, y: int) -> None:
        raise MouseUnavailableError("no mouse backend; refusing")

    def click(self, x: int, y: int, button: str) -> None:
        raise MouseUnavailableError("no click backend; refusing")

    def button(self, down: bool, x: int, y: int,
               button: str) -> None:
        raise MouseUnavailableError("no button backend; refusing")

    def release(self, button: str) -> None:
        """Button-up WITHOUT moving (drag fail-safe)."""
        raise MouseUnavailableError("no button backend; refusing")

    def scroll(self, dy: int) -> None:
        raise MouseUnavailableError("no scroll backend; refusing")

    def key_press(self, key: str) -> None:
        raise MouseUnavailableError("no keyboard backend; refusing")

    def hotkey(self, keys: list) -> None:
        raise MouseUnavailableError("no keyboard backend; refusing")

    def type_text(self, text: str) -> None:
        raise MouseUnavailableError("no keyboard backend; refusing")

    def clipboard_write(self, text: str) -> None:
        raise MouseUnavailableError("no clipboard backend; refusing")

    def clipboard_read(self) -> str:
        raise MouseUnavailableError("no clipboard backend; refusing")


class UnavailableMouseAdapter(MouseAdapter):
    name = "unavailable"


def _windows_input_structs():
    """Shared SendInput shapes (module-level so tests can pin the
    real INPUT size: x64 INPUT is 40 bytes — a key-only 32-byte
    struct makes SendInput reject every keystroke)."""
    import ctypes
    from ctypes import wintypes

    class _Mi(ctypes.Structure):
        _fields_ = [("dx", ctypes.c_long),
                    ("dy", ctypes.c_long),
                    ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_void_p)]

    class _Ki(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD),
                    ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_void_p)]

    class _Union(ctypes.Union):
        _fields_ = [("mi", _Mi), ("ki", _Ki)]

    class _In(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD),
                    ("u", _Union)]

    return _Mi, _Ki, _In


def windows_input_size() -> tuple[int, int]:
    """(mouse INPUT bytes, keyboard INPUT bytes). Must be equal:
    both ride the same INPUT union."""
    import ctypes
    _Mi, _Ki, _In = _windows_input_structs()
    mouse = (_In * 1)()
    mouse[0].type = 0
    key = (_In * 1)()
    key[0].type = 1
    return ctypes.sizeof(mouse[0]), ctypes.sizeof(key[0])


#: Virtual-key table (identical values to the coordinator's
#: desktop_runtime backend; one shared vocabulary, no dialect).
_VK_CODES = {
    "enter": 0x0D, "tab": 0x09, "escape": 0x1B, "esc": 0x1B,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "insert": 0x2D, "printscreen": 0x2C, "pause": 0x13,
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
    "cmd": 0x5B,
}
_VK_CODES.update({f"f{n}": 0x6F + n for n in range(1, 13)})
_VK_CODES.update({chr(c): c - 32 for c in range(ord("a"),
                                                 ord("z") + 1)})
_VK_CODES.update({str(d): ord(str(d)) for d in range(10)})


class WindowsMouseAdapter(MouseAdapter):
    """Real input via user32 (SetCursorPos/SendInput) plus
    text-only clipboard via the clipboard APIs. Windows + stdlib."""

    name = "windows"
    can_move = True
    can_click = True
    can_key = True
    can_scroll = True
    can_clipboard_write = True
    can_clipboard_read = True

    def __init__(self) -> None:
        if os.name != "nt":
            raise MouseUnavailableError(
                "Windows mouse backend needs Windows")
        import ctypes
        try:
            self._user32 = ctypes.windll.user32
            self._user32.SetCursorPos.argtypes = [
                ctypes.c_int, ctypes.c_int]
            self._user32.SetCursorPos.restype = ctypes.c_bool
        except (AttributeError, OSError) as error:
            raise MouseUnavailableError(
                f"Desktop APIs unavailable: {error}") from error

    def move(self, x: int, y: int) -> None:
        if not self._user32.SetCursorPos(int(x), int(y)):
            try:
                import ctypes as _ctypes
                code = _ctypes.GetLastError()
            except Exception:
                code = -1
            raise MouseUnavailableError(
                f"Input was not accepted (last-error {code})")

    # -- SendInput plumbing (mouse + keyboard, stdlib only) ----------

    def _mouse_event(self, flags: int, data: int = 0,
                     dx: int = 0, dy: int = 0) -> None:
        import ctypes
        _Mi, _Ki, _In = _windows_input_structs()
        events = (_In * 1)()
        events[0].type = 0
        events[0].u.mi.dx = dx
        events[0].u.mi.dy = dy
        events[0].u.mi.mouseData = data
        events[0].u.mi.dwFlags = flags
        events[0].u.mi.time = 0
        events[0].u.mi.dwExtraInfo = None
        if self._user32.SendInput(1, events,
                                  ctypes.sizeof(events[0])) != 1:
            raise MouseUnavailableError("Input was not accepted")

    def _key_event(self, virtual_key: int, release: bool,
                   unicode_char: int = 0) -> None:
        import ctypes
        _Mi, _Ki, _In = _windows_input_structs()
        flags = 0x0002 if release else 0x0000
        if unicode_char:
            flags |= 0x0004
        events = (_In * 1)()
        events[0].type = 1
        events[0].u.ki.wVk = virtual_key
        events[0].u.ki.wScan = unicode_char
        events[0].u.ki.dwFlags = flags
        events[0].u.ki.time = 0
        events[0].u.ki.dwExtraInfo = None
        if self._user32.SendInput(1, events,
                                  ctypes.sizeof(events[0])) != 1:
            raise MouseUnavailableError("Input was not accepted")

    _CLICK_FLAGS = {"left": (0x0002, 0x0004),
                    "right": (0x0008, 0x0010),
                    "middle": (0x0020, 0x0040)}

    def _click_flags(self, button: str) -> tuple[int, int]:
        try:
            return self._CLICK_FLAGS[button]
        except KeyError:
            raise MouseUnavailableError(
                "button must be left/right/middle") from None

    def click(self, x: int, y: int, button: str) -> None:
        down, up = self._click_flags(button)
        self.move(x, y)
        self._mouse_event(down)
        self._mouse_event(up)

    def button(self, down: bool, x: int, y: int,
               button: str) -> None:
        first, second = self._click_flags(button)
        self.move(x, y)
        self._mouse_event(first if down else second)

    def release(self, button: str) -> None:
        _, up = self._click_flags(button)
        self._mouse_event(up)

    def scroll(self, dy: int) -> None:
        # Vertical wheel only (0x0800); data is wheel ticks.
        self._mouse_event(0x0800, data=dy)

    def key_press(self, key: str) -> None:
        code = _VK_CODES[key]
        self._key_event(code, False)
        self._key_event(code, True)

    def hotkey(self, keys: list) -> None:
        codes = [_VK_CODES[key] for key in keys]
        for code in codes:
            self._key_event(code, False)
        for code in reversed(codes):
            self._key_event(code, True)

    def type_text(self, text: str) -> None:
        for char in text:
            code = ord(char)
            self._key_event(0, False, unicode_char=code)
            self._key_event(0, True, unicode_char=code)

    # -- text-only clipboard (CF_UNICODETEXT, no files) --------------

    def _clipboard_apis(self):
        """user32/kernel32 clipboard functions with real 64-bit
        signatures (default c_int returns truncate handles)."""
        import ctypes
        from ctypes import wintypes
        user32 = self._user32
        kernel32 = ctypes.windll.kernel32
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT,
                                            wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE
        user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
        user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT,
                                         ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HANDLE
        kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
        kernel32.GlobalFree.restype = wintypes.HANDLE
        kernel32.GlobalSize.argtypes = [wintypes.HANDLE]
        kernel32.GlobalSize.restype = ctypes.c_size_t
        return user32, kernel32

    def clipboard_write(self, text: str) -> None:
        import ctypes
        user32, kernel32 = self._clipboard_apis()
        data = (text + "\0").encode("utf-16-le")
        if not user32.OpenClipboard(None):
            raise MouseUnavailableError("Clipboard busy; refusing")
        try:
            if not user32.EmptyClipboard():
                raise MouseUnavailableError(
                    "Clipboard busy; refusing")
            handle = kernel32.GlobalAlloc(0x0002, len(data))
            if not handle:
                raise MouseUnavailableError(
                    "Clipboard alloc failed")
            try:
                locked = kernel32.GlobalLock(handle)
                if not locked:
                    raise MouseUnavailableError(
                        "Clipboard lock failed")
                try:
                    ctypes.memmove(locked, data, len(data))
                finally:
                    kernel32.GlobalUnlock(handle)
                if not user32.SetClipboardData(13, handle):
                    raise MouseUnavailableError(
                        "Clipboard set failed")
                handle = None  # system owns it now
            finally:
                if handle:
                    kernel32.GlobalFree(handle)
        finally:
            user32.CloseClipboard()

    def clipboard_read(self) -> str:
        import ctypes
        user32, kernel32 = self._clipboard_apis()
        if not user32.OpenClipboard(None):
            raise MouseUnavailableError("Clipboard busy; refusing")
        try:
            if not user32.IsClipboardFormatAvailable(13):
                raise MouseUnavailableError(
                    "No text on clipboard")
            handle = user32.GetClipboardData(13)
            if not handle:
                raise MouseUnavailableError(
                    "Clipboard read failed")
            locked = kernel32.GlobalLock(handle)
            if not locked:
                raise MouseUnavailableError(
                    "Clipboard lock failed")
            try:
                # Bounded by the real allocation size first:
                # never read past it, never silently truncate.
                size_bytes = kernel32.GlobalSize(handle)
                if size_bytes > (MAX_CLIPBOARD_CHARS + 1) * 2:
                    raise MouseUnavailableError(
                        "Clipboard text too large")
                text = ctypes.wstring_at(locked)
                if len(text) > MAX_CLIPBOARD_CHARS:
                    raise MouseUnavailableError(
                        "Clipboard text too large")
            finally:
                kernel32.GlobalUnlock(handle)
            return text or ""
        finally:
            user32.CloseClipboard()


class X11MouseAdapter(MouseAdapter):
    """Best-effort movement via XWarpPointer (libX11, ctypes only).

    X11 only: no Wayland, no shell, no subprocess. The display
    must be reachable (DISPLAY set); otherwise unavailable.
    """

class X11MouseAdapter(MouseAdapter):
    """Best-effort input via libX11 + libXtst (ctypes only).

    X11 only: no Wayland, no shell, no subprocess. Move works
    whenever a display is reachable; click/keyboard/scroll/drag
    additionally need libXtst (probed, flags set accordingly).
    Clipboard stays unavailable (selection ownership needs an
    event loop — not faked, reported unavailable).
    """

    name = "x11"
    can_move = True
    can_click = False
    can_key = False
    can_scroll = False
    can_clipboard_write = False
    can_clipboard_read = False

    def __init__(self) -> None:
        if os.name == "nt":
            raise MouseUnavailableError(
                "X11 mouse backend is not for Windows")
        import ctypes
        try:
            self._x11 = ctypes.CDLL("libX11.so.6")
        except OSError as error:
            raise MouseUnavailableError(
                f"libX11 unavailable: {error}") from error
        try:
            self._x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            self._x11.XOpenDisplay.restype = ctypes.c_void_p
            self._x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            self._x11.XDefaultRootWindow.restype = ctypes.c_ulong
            self._x11.XWarpPointer.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                ctypes.c_uint, ctypes.c_int, ctypes.c_int]
            self._x11.XWarpPointer.restype = ctypes.c_int
            self._x11.XFlush.argtypes = [ctypes.c_void_p]
            self._x11.XFlush.restype = ctypes.c_int
            self._x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        except (AttributeError, OSError) as error:
            raise MouseUnavailableError(
                f"X11 bindings failed: {error}") from error
        display = self._x11.XOpenDisplay(None)
        if not display:
            raise MouseUnavailableError(
                "No X display reachable; refusing")
        self._x11.XCloseDisplay(display)
        self._xtest = self._probe_xtest()

    def _probe_xtest(self):
        """libXtst for button/key events. None when missing: the
        adapter still moves, but click/key refuse (flags stay off)."""
        import ctypes
        try:
            xtest = ctypes.CDLL("libXtst.so.6")
            xtest.XTestFakeButtonEvent.argtypes = [
                ctypes.c_void_p, ctypes.c_uint, ctypes.c_int,
                ctypes.c_ulong]
            xtest.XTestFakeButtonEvent.restype = ctypes.c_int
            xtest.XTestFakeKeyEvent.argtypes = [
                ctypes.c_void_p, ctypes.c_uint, ctypes.c_int,
                ctypes.c_ulong]
            xtest.XTestFakeKeyEvent.restype = ctypes.c_int
            xtest.XTestQueryExtension = xtest.XTestQueryExtension
        except (OSError, AttributeError):
            return None
        self.can_click = True
        self.can_key = True
        self.can_scroll = True
        return xtest

    def _open(self):
        display = self._x11.XOpenDisplay(None)
        if not display:
            raise MouseUnavailableError(
                "No X display reachable; refusing")
        return display

    def _require_xtest(self):
        if self._xtest is None:
            raise MouseUnavailableError(
                "libXtst unavailable: button/key input refused")
        return self._xtest

    def _flush_close(self, display) -> None:
        try:
            self._x11.XFlush(display)
        finally:
            self._x11.XCloseDisplay(display)

    _X11_BUTTONS = {"left": 1, "middle": 2, "right": 3}

    def click(self, x: int, y: int, button: str) -> None:
        try:
            number = self._X11_BUTTONS[button]
        except KeyError:
            raise MouseUnavailableError(
                "button must be left/right/middle") from None
        self.move(x, y)
        self.button(True, x, y, button)
        self.button(False, x, y, button)

    def button(self, down: bool, x: int, y: int,
               button: str) -> None:
        xtest = self._require_xtest()
        try:
            number = self._X11_BUTTONS[button]
        except KeyError:
            raise MouseUnavailableError(
                "button must be left/right/middle") from None
        self.move(x, y)
        display = self._open()
        try:
            xtest.XTestFakeButtonEvent(display, number,
                                       1 if down else 0, 0)
            self._flush_close(display)
        except Exception:
            try:
                self._x11.XCloseDisplay(display)
            except Exception:
                pass
            raise MouseUnavailableError(
                "XTest button event failed")

    def release(self, button: str) -> None:
        xtest = self._require_xtest()
        try:
            number = self._X11_BUTTONS[button]
        except KeyError:
            raise MouseUnavailableError(
                "button must be left/right/middle") from None
        display = self._open()
        try:
            xtest.XTestFakeButtonEvent(display, number, 0, 0)
            self._flush_close(display)
        except Exception:
            try:
                self._x11.XCloseDisplay(display)
            except Exception:
                pass
            raise MouseUnavailableError(
                "XTest button release failed")

    def scroll(self, dy: int) -> None:
        xtest = self._require_xtest()
        display = self._open()
        try:
            # X11 wheel: button 4 = up, 5 = down.
            steps = max(1, min(33, (abs(int(dy)) + 119) // 120))
            number = 4 if int(dy) > 0 else 5
            for _ in range(steps):
                xtest.XTestFakeButtonEvent(display, number, 1, 0)
                xtest.XTestFakeButtonEvent(display, number, 0, 0)
            self._flush_close(display)
        except MouseUnavailableError:
            raise
        except Exception:
            try:
                self._x11.XCloseDisplay(display)
            except Exception:
                pass
            raise MouseUnavailableError("XTest scroll failed")

    def _keysym(self, key: str) -> int:
        table = {
            "enter": 0xFF0D, "tab": 0xFF09, "escape": 0xFF1B,
            "esc": 0xFF1B, "space": 0x0020, "backspace": 0xFF08,
            "delete": 0xFFFF, "up": 0xFF52, "down": 0xFF54,
            "left": 0xFF51, "right": 0xFF53, "home": 0xFF50,
            "end": 0xFF57, "pageup": 0xFF55, "pagedown": 0xFF56,
            "insert": 0xFF63, "printscreen": 0xFF61,
            "pause": 0xFF13, "ctrl": 0xFFE3, "alt": 0xFFE9,
            "shift": 0xFFE1, "win": 0xFFEB, "cmd": 0xFFEB,
        }
        if key in table:
            return table[key]
        if key.startswith("f") and key[1:].isdigit():
            number = int(key[1:])
            if 1 <= number <= 12:
                return 0xFFBE + number - 1
        if len(key) == 1:
            code = ord(key)
            if 0x20 <= code <= 0x7E:
                return code
        raise MouseUnavailableError(
            f"no X keysym for {key!r}; refusing")

    def _fake_key(self, key: str, down: bool) -> None:
        import ctypes
        xtest = self._require_xtest()
        keysym = self._keysym(key)
        display = self._open()
        try:
            xtest.XKeysymToKeycode.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong]
            xtest.XKeysymToKeycode.restype = ctypes.c_uint
        except AttributeError:
            try:
                self._x11.XKeysymToKeycode.argtypes = [
                    ctypes.c_void_p, ctypes.c_ulong]
                self._x11.XKeysymToKeycode.restype = ctypes.c_uint
                to_code = self._x11.XKeysymToKeycode
            except AttributeError:
                self._x11.XCloseDisplay(display)
                raise MouseUnavailableError(
                    "XKeysymToKeycode missing; refusing")
        else:
            to_code = xtest.XKeysymToKeycode
        try:
            code = to_code(display, keysym)
            if not code:
                raise MouseUnavailableError(
                    f"no X keycode for {key!r}; refusing")
            xtest.XTestFakeKeyEvent(display, code,
                                    1 if down else 0, 0)
            self._flush_close(display)
        except MouseUnavailableError:
            raise
        except Exception:
            try:
                self._x11.XCloseDisplay(display)
            except Exception:
                pass
            raise MouseUnavailableError("XTest key event failed")

    def key_press(self, key: str) -> None:
        self._fake_key(key, True)
        self._fake_key(key, False)

    def hotkey(self, keys: list) -> None:
        for key in keys:
            self._fake_key(key, True)
        for key in reversed(keys):
            self._fake_key(key, False)

    def type_text(self, text: str) -> None:
        for char in text:
            if char == "\n":
                self.key_press("enter")
            elif char == "\t":
                self.key_press("tab")
            elif char == " ":
                self.key_press("space")
            elif len(char) == 1 and char.isalpha() and \
                    char.isascii():
                if char.isupper():
                    self._fake_key("shift", True)
                    self._fake_key(char.lower(), True)
                    self._fake_key(char.lower(), False)
                    self._fake_key("shift", False)
                else:
                    self.key_press(char.lower())
            elif len(char) == 1 and char.isascii() and \
                    0x20 <= ord(char) <= 0x7E:
                self._fake_key(char, True)
                self._fake_key(char, False)
            else:
                raise MouseUnavailableError(
                    "X11 typing supports ascii only; refusing")

    def move(self, x: int, y: int) -> None:
        display = self._x11.XOpenDisplay(None)
        if not display:
            raise MouseUnavailableError(
                "No X display reachable; refusing")
        try:
            root = self._x11.XDefaultRootWindow(display)
            self._x11.XWarpPointer(display, 0, root, 0, 0, 0, 0,
                                   int(x), int(y))
            self._x11.XFlush(display)
        finally:
            self._x11.XCloseDisplay(display)


def default_adapter() -> MouseAdapter:
    """Probe order: Windows, then X11, else unavailable. Never fakes."""
    if os.name == "nt":
        try:
            return WindowsMouseAdapter()
        except MouseUnavailableError:
            return UnavailableMouseAdapter()
    try:
        return X11MouseAdapter()
    except MouseUnavailableError:
        return UnavailableMouseAdapter()


def mouse_backend_available(adapter: MouseAdapter | None = None) -> bool:
    """True only when a real backend constructed successfully."""
    try:
        backend = adapter if adapter is not None else default_adapter()
    except MouseUnavailableError:
        return False
    return backend.name in ("windows", "x11")


def execute_remote_move(x, y,
                        adapter: MouseAdapter | None = None) -> dict:
    """Execute exactly one validated mouse move. Returns a small receipt.

    Raises MouseUnavailableError when refused.
    """
    point = check_coordinates(x, y)
    backend = adapter if adapter is not None else default_adapter()
    if not getattr(backend, "can_move", False):
        raise MouseUnavailableError("no mouse backend; refusing")
    backend.move(*point)
    return {"ok": True, "x": point[0], "y": point[1],
            "backend": backend.name}


def probe_capabilities(adapter: MouseAdapter | None = None) -> dict:
    """Per-family availability. Never raises, never fakes."""
    try:
        backend = adapter if adapter is not None \
            else default_adapter()
    except MouseUnavailableError:
        return {"move": False, "click": False, "keyboard": False,
                "scroll": False, "drag": False,
                "clipboard_write": False, "clipboard_read": False}
    move = bool(getattr(backend, "can_move", False))
    click = bool(getattr(backend, "can_click", False))
    key = bool(getattr(backend, "can_key", False))
    scroll = bool(getattr(backend, "can_scroll", False))
    return {
        "move": move,
        "click": click,
        "keyboard": key,
        "scroll": scroll,
        "drag": bool(move and click),
        "clipboard_write": bool(
            getattr(backend, "can_clipboard_write", False)),
        "clipboard_read": bool(
            getattr(backend, "can_clipboard_read", False)),
    }


def execute_remote_action(kind, params,
                          adapter: MouseAdapter | None = None,
                          tracker=None) -> dict:
    """Execute exactly one validated discrete input action.

    Closed kind vocabulary; every kind re-validates here
    (defense in depth) and maps to exactly one adapter method.
    mouse_down/up update the tracker so a lost session can
    release a held button. Raises MouseUnavailableError.
    """
    if not isinstance(kind, str):
        raise MouseUnavailableError("input kind must be text")
    if not isinstance(params, dict):
        raise MouseUnavailableError("input params must be an object")
    backend = adapter if adapter is not None else default_adapter()
    if kind == "click":
        if not backend.can_click:
            raise MouseUnavailableError("no click backend; refusing")
        point = check_coordinates(params.get("x"), params.get("y"))
        button = check_button(params.get("button", "left"))
        backend.click(point[0], point[1], button)
        return {"ok": True, "kind": kind, "x": point[0],
                "y": point[1], "button": button,
                "backend": backend.name}
    if kind in ("mouse_down", "mouse_up"):
        if not (backend.can_move and backend.can_click):
            raise MouseUnavailableError("no drag backend; refusing")
        point = check_coordinates(params.get("x"), params.get("y"))
        button = check_button(params.get("button", "left"))
        backend.button(kind == "mouse_down", point[0], point[1],
                       button)
        if tracker is not None:
            if kind == "mouse_down":
                tracker.press(button)
            else:
                tracker.release(button)
        return {"ok": True, "kind": kind, "x": point[0],
                "y": point[1], "button": button,
                "backend": backend.name}
    if kind == "scroll":
        if not backend.can_scroll:
            raise MouseUnavailableError("no scroll backend; refusing")
        if int(params.get("dx", 0)) != 0:
            raise MouseUnavailableError(
                "only vertical scroll in this slice")
        delta = check_delta("dy", params.get("dy"))
        if delta == 0:
            raise MouseUnavailableError(
                "scroll needs a non-zero delta")
        backend.scroll(delta)
        return {"ok": True, "kind": kind, "dy": delta,
                "backend": backend.name}
    if kind == "key_press":
        if not backend.can_key:
            raise MouseUnavailableError(
                "no keyboard backend; refusing")
        key = check_key(params.get("key"))
        backend.key_press(key)
        return {"ok": True, "kind": kind, "key": key,
                "backend": backend.name}
    if kind == "hotkey":
        if not backend.can_key:
            raise MouseUnavailableError(
                "no keyboard backend; refusing")
        keys = check_keys(params.get("keys"))
        backend.hotkey(keys)
        return {"ok": True, "kind": kind, "keys": keys,
                "backend": backend.name}
    if kind == "type_text":
        if not backend.can_key:
            raise MouseUnavailableError(
                "no keyboard backend; refusing")
        text = check_text(params.get("text"))
        backend.type_text(text)
        return {"ok": True, "kind": kind, "chars": len(text),
                "backend": backend.name}
    if kind == "clipboard_set":
        if not backend.can_clipboard_write:
            raise MouseUnavailableError(
                "no clipboard backend; refusing")
        text = check_clipboard_text(params.get("text"))
        backend.clipboard_write(text)
        return {"ok": True, "kind": kind, "chars": len(text),
                "backend": backend.name}
    raise MouseUnavailableError(
        f"unknown input kind '{str(kind)[:40]}'")


class ButtonTracker:
    """Node-side drag fail-safe: remembers a held button so a
    dead session (410/close/expiry) releases it. One button at
    a time; a second press replaces the first (no chord state)."""

    def __init__(self) -> None:
        self.held: str | None = None

    def press(self, button: str) -> None:
        self.held = button

    def release(self, button: str | None = None) -> str | None:
        if button is not None and self.held != button:
            return self.held
        was = self.held
        self.held = None
        return was

    def emergency_release(self,
                          adapter: MouseAdapter | None = None
                          ) -> dict | None:
        """Release a stuck button after session death. Returns a
        receipt when a release happened, else None. Never raises:
        a dead session must never wedge the node loop."""
        if self.held is None:
            return None
        button = self.held
        self.held = None
        try:
            backend = adapter if adapter is not None \
                else default_adapter()
            if not (getattr(backend, "can_move", False)
                    and getattr(backend, "can_click", False)):
                return None
            backend.release(button)
        except Exception:
            return None
        return {"ok": True, "kind": "mouse_up",
                "button": button, "emergency": True,
                "backend": getattr(backend, "name", "?")}
