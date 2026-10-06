"""Out-of-process camera discovery probe.

``cameras.detect_local_imaging_devices`` walks Windows SetupDi via
ctypes. On some machines that call dies with an access violation
that Python cannot catch — taking the whole coordinator (or test
runner) down with it. This module therefore runs enumeration in
a short-lived child process with a hard timeout and parses a
JSON verdict from stdout:

- ``found``      — enumeration ok, ≥1 device (names only)
- ``none_found`` — enumeration ok, zero devices
- ``timeout``    — child exceeded the budget (killed)
- ``crashed``    — child died (nonzero exit / access violation)
- ``error``      — anything else (bad payload, spawn failure)

The probe NEVER claims capture capability: at most it reports
``detected`` in the existing camera-state vocabulary
(registered/detected/connected/capturable/unavailable). Claiming
``capturable`` still requires a reviewed adapter + probe frame.
No adapter is registered, no device is opened, no bytes move.

``run_grab`` extends the same isolation to one frame: the child
opens the named grabber (closed literal set, never arbitrary
code), writes or verifies exactly one local BMP, hashes it and
prints a ``frame_acquired`` verdict. The parent re-validates
everything — filename, directory containment, size bounds and
the SHA256 it recomputes itself. Verdicts:

- ``frame_acquired`` — a real frame file verified by the parent
- ``unavailable``    — grabber refuses (stub runtime, no bytes)
- ``timeout``        — child exceeded the budget (killed)
- ``crashed``        — child died (nonzero exit / access violation)
- ``error``          — anything else (bad payload, hash mismatch,
  missing frame, spawn failure)

``frame_acquired`` is never returned without a verified frame.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PROBE_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 60.0
MAX_DEVICES = 32
MAX_NAME_CHARS = 260

#: Insta360 webcam label for the dshow grabber. Overridable per
#: machine via INSTA360_DSHOW_NAME; strict charset so the value
#: can never become a command line. Default matches the X3 in
#: webcam mode ("Insta360 X3").
INSTA360_DEFAULT_LABEL = "Insta360 X3"
INSTA360_LABEL_RE = re.compile(r"^[A-Za-z0-9 _()+-]{1,80}$")


def insta360_label() -> str:
    """Validated dshow device label. Invalid env -> safe default."""
    raw = str(os.environ.get("INSTA360_DSHOW_NAME",
                             INSTA360_DEFAULT_LABEL) or "").strip()
    if not raw or len(raw) > 80 or not INSTA360_LABEL_RE.match(raw):
        return INSTA360_DEFAULT_LABEL
    return raw

#: Closed grabber set. ``test`` writes a synthetic BMP (test-origin
#: only, never sensed); ``file`` hashes one operator-provided file
#: already inside the camera dir; ``insta360`` grabs one dshow frame
#: via ffmpeg argv (no shell) into the camera dir; ``windows-webcam``
#: still refuses until its runtime is reviewed.
VALID_GRABBERS = frozenset({"test", "file", "windows-webcam",
                            "insta360"})
GRAB_STATES = frozenset({"frame_acquired", "unavailable", "timeout",
                         "crashed", "error"})
MAX_FRAME_BYTES = 10 * 1024 * 1024
MAX_FRAME_DIMENSION = 16384

#: Child grab script. Takes one argv JSON ``{"grabber": ...,
#: "filename": ...}``. Prints exactly one JSON verdict line.
#: Hardware grabbers refuse without touching anything.
_GRAB_SNIPPET = "\n".join([
    "import hashlib, json, os, sys, time",
    "def _out(o): print(json.dumps(o))",
    "try: spec = json.loads(sys.argv[1])",
    "except Exception: _out({'state': 'error',",
    " 'reason': 'bad grab spec'}); raise SystemExit(0)",
    "grabber = spec.get('grabber', '')",
    "if grabber == 'windows-webcam':",
    "    _out({'state': 'unavailable', 'reason': 'no reviewed '",
    "     'capture runtime for windows-webcam'});",
    "    raise SystemExit(0)",
    "if grabber not in ('test', 'file', 'insta360'):",
    "    _out({'state': 'error', 'reason': 'unknown grabber'});",
    "    raise SystemExit(0)",
    "from coordinator.app.cameras import camera_dir",
    "root = os.path.abspath(camera_dir())",
    "if grabber == 'test':",
    "    from coordinator.app.desktop_runtime import write_bmp_24",
    "    w, h = 64, 48",
    "    fn = 'cam-grab-%x.bmp' % int(time.time() * 1000)",
    "    path = os.path.join(root, fn)",
    "    write_bmp_24(path, w, h, b'\\x20\\x40\\x60' * (w * h))",
    "    why = 'test grabber; synthetic pixels'",
    "elif grabber == 'file':",
    "    fn = os.path.basename(str(spec.get('filename', '')))",
    "    if not fn.lower().endswith(('.bmp', '.png', '.jpg',",
    "     '.jpeg')) or '/' in fn or '\\\\' in fn or '..' in fn:",
    "        _out({'state': 'error',",
    "         'reason': 'grab filename refused'}); raise SystemExit(0)",
    "    path = os.path.abspath(os.path.join(root, fn))",
    "    if path != root and not path.startswith(root + os.sep):",
    "        _out({'state': 'error',",
    "         'reason': 'grab escapes camera dir'}); raise SystemExit(0)",
    "    if not os.path.isfile(path):",
    "        _out({'state': 'error',",
    "         'reason': 'grab file missing: ' + fn[:80]});",
    "        raise SystemExit(0)",
    "    w, h = 0, 0",
    "    why = 'file grabber; operator-provided file'",
    "else:",
    "    import re as _re, shutil as _sh, subprocess as _sp",
    "    from coordinator.app.capture_probe import insta360_label",
    "    label = insta360_label()",
    "    ffmpeg = _sh.which('ffmpeg')",
    "    if not ffmpeg:",
    "        _out({'state': 'unavailable',",
    "         'reason': 'ffmpeg not on PATH; install ffmpeg'});",
    "        raise SystemExit(0)",
    "    fn = 'cam-insta360-%x.jpg' % int(time.time() * 1000)",
    "    path = os.path.join(root, fn)",
    "    try:",
    "        proc = _sp.run([ffmpeg, '-hide_banner', '-loglevel',",
    "         'info', '-f', 'dshow', '-i', 'video=' + label,",
    "         '-frames:v', '1', '-y', path], capture_output=True,",
    "         text=True, timeout=25)",
    "    except Exception as e:",
    "        _out({'state': 'error',",
    "         'reason': 'insta360 grab failed: ' + str(e)[:120]});",
    "        raise SystemExit(0)",
    "    if proc.returncode != 0 or not os.path.isfile(path):",
    "        tail = (proc.stderr or '').strip().splitlines()",
    "        tail = tail[-1][:160] if tail else 'ffmpeg problem'",
    "        _out({'state': 'error', 'reason': 'insta360: ' + tail});",
    "        raise SystemExit(0)",
    "    m = _re.search(r' (\\d{3,5})x(\\d{3,5})[ ,\\]]',",
    "     proc.stderr or '')",
    "    w, h = (int(m.group(1)), int(m.group(2))) if m else (0, 0)",
    "    why = 'insta360 grabber; dshow single frame'",
    "size = os.path.getsize(path)",
    "if size <= 0 or size > 10485760:",
    "    _out({'state': 'error',",
    "     'reason': 'grab size out of bounds'}); raise SystemExit(0)",
    "d = hashlib.sha256()",
    "f = open(path, 'rb')",
    "d.update(f.read()); f.close()",
    "_out({'state': 'frame_acquired', 'media_ref': os.path.basename(",
    " path), 'sha256': d.hexdigest(), 'size_bytes': size,",
    " 'width': w, 'height': h, 'reason': why})",
])

_PROBE_SNIPPET = (
    "import json;"
    "from coordinator.app.cameras import detect_local_imaging_devices as f;"
    "r = f();"
    "ds = r.get('devices', []) if isinstance(r, dict) else [];"
    "print(json.dumps({"
    "'supported': bool(r.get('supported', False)) if isinstance(r, dict) else False,"
    "'devices': ["
    "{'name': str(d.get('name', ''))[:260], 'path': str(d.get('path', ''))[:260]} "
    "for d in ds[:32] if isinstance(d, dict)],"
    "'reason': str(r.get('reason', ''))[:300] if isinstance(r, dict) else '',"
    "}))"
)


def _project_root() -> Path:
    # coordinator/app/capture_probe.py -> mycelium-ai-main/
    return Path(__file__).resolve().parent.parent.parent


def _check_timeout(timeout) -> tuple[float, dict | None]:
    try:
        budget = float(timeout)
    except (TypeError, ValueError):
        return 0.0, {"state": "error",
                     "reason": "timeout must be a number",
                     "elapsed_ms": 0}
    return max(1.0, min(budget, MAX_TIMEOUT_SECONDS)), None


def _spawn_child(args, budget: float, started: float) -> tuple:
    """Run the child, mapping spawn/timeout/crash to verdicts.
    Returns (completed | None, verdict | None). Never raises."""
    try:
        completed = subprocess.run(
            args, cwd=str(_project_root()),
            capture_output=True, text=True, timeout=budget,
            stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - started) * 1000)
        return None, {"state": "timeout",
                      "reason": f"grab exceeded {budget:g}s; killed",
                      "elapsed_ms": elapsed}
    except (OSError, ValueError) as error:
        elapsed = int((time.monotonic() - started) * 1000)
        return None, {"state": "error",
                      "reason": f"grab spawn failed: {type(error).__name__}",
                      "elapsed_ms": elapsed}
    elapsed = int((time.monotonic() - started) * 1000)
    if completed.returncode != 0:
        tail = (completed.stderr or "").strip()[-300:]
        return None, {"state": "crashed",
                      "reason": ("child died "
                                 f"(exit {completed.returncode})"
                                 + (f": {tail}" if tail else "")),
                      "elapsed_ms": elapsed}
    return completed, None


def run_grab(spec, timeout: float = PROBE_TIMEOUT_SECONDS) -> dict:
    """Grab one frame out-of-process. Never raises.

    ``spec`` is ``{"grabber": <closed literal>, "filename": ...}``
    (filename only for the ``file`` grabber). Only ``frame_acquired``
    with a parent-verified file (name, directory, size, SHA256)
    counts as a frame — everything else is a named non-frame
    verdict, and the coordinator is never at risk.
    """
    budget, bad = _check_timeout(timeout)
    if bad is not None:
        return bad
    if not isinstance(spec, dict):
        return {"state": "error", "reason": "grab spec must be an object",
                "elapsed_ms": 0}
    grabber = spec.get("grabber", "")
    if grabber not in VALID_GRABBERS:
        return {"state": "error",
                "reason": f"unknown grabber '{grabber}'",
                "elapsed_ms": 0}
    child_spec: dict = {"grabber": grabber}
    if grabber == "file":
        from .observations import check_image_ref
        try:
            reference = check_image_ref(spec.get("filename", ""))
        except ValueError as error:
            return {"state": "error",
                    "reason": f"grab filename refused: {error}",
                    "elapsed_ms": 0}
        if not reference:
            return {"state": "error",
                    "reason": "file grab needs a media filename",
                    "elapsed_ms": 0}
        child_spec["filename"] = reference
    started = time.monotonic()
    completed, verdict = _spawn_child(
        [sys.executable, "-c", _GRAB_SNIPPET, json.dumps(child_spec)],
        budget, started)
    if verdict is not None:
        return verdict
    elapsed = int((time.monotonic() - started) * 1000)
    try:
        payload = json.loads((completed.stdout or "").strip().split(
            "\n")[-1] or "{}")
    except ValueError:
        return {"state": "error",
                "reason": "child returned invalid JSON",
                "elapsed_ms": elapsed}
    if not isinstance(payload, dict):
        return {"state": "error",
                "reason": "child returned non-object JSON",
                "elapsed_ms": elapsed}
    state = payload.get("state", "")
    if state == "unavailable":
        return {"state": "unavailable",
                "reason": str(payload.get("reason", "unavailable")
                              or "unavailable")[:300],
                "elapsed_ms": elapsed}
    if state != "frame_acquired":
        return {"state": "error",
                "reason": str(payload.get("reason", "child refused")
                              or "child refused")[:300],
                "elapsed_ms": elapsed}
    return _verify_frame(payload, elapsed)


def _verify_frame(payload: dict, elapsed: int) -> dict:
    """Parent-side frame verification: the child's word is never
    enough. Filename, directory containment, size bounds and a
    freshly recomputed SHA256 must all check out."""
    import hashlib
    from .observations import check_image_ref
    try:
        reference = check_image_ref(payload.get("media_ref", ""))
    except ValueError:
        return {"state": "error",
                "reason": "child returned an invalid media_ref",
                "elapsed_ms": elapsed}
    if not reference:
        return {"state": "error",
                "reason": "child returned no media_ref",
                "elapsed_ms": elapsed}
    from .cameras import camera_dir
    import os as _os
    root = _os.path.abspath(camera_dir())
    path = _os.path.abspath(_os.path.join(root, reference))
    if path != root and not path.startswith(root + _os.sep):
        return {"state": "error",
                "reason": "frame escapes the camera directory",
                "elapsed_ms": elapsed}
    if not _os.path.isfile(path):
        return {"state": "error",
                "reason": f"frame file missing: {reference}",
                "elapsed_ms": elapsed}
    try:
        size = _os.path.getsize(path)
    except OSError:
        return {"state": "error",
                "reason": "frame file unreadable",
                "elapsed_ms": elapsed}
    if size <= 0 or size > MAX_FRAME_BYTES:
        return {"state": "error",
                "reason": "frame size out of bounds",
                "elapsed_ms": elapsed}
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return {"state": "error",
                "reason": "frame file unreadable",
                "elapsed_ms": elapsed}
    claimed = str(payload.get("sha256", ""))
    if digest.hexdigest() != claimed:
        return {"state": "error",
                "reason": "frame hash mismatch; refusing",
                "elapsed_ms": elapsed}
    try:
        width = int(payload.get("width", 0))
        height = int(payload.get("height", 0))
    except (TypeError, ValueError):
        return {"state": "error",
                "reason": "frame dimensions invalid",
                "elapsed_ms": elapsed}
    if not 0 <= width <= MAX_FRAME_DIMENSION or \
            not 0 <= height <= MAX_FRAME_DIMENSION:
        return {"state": "error",
                "reason": "frame dimensions out of bounds",
                "elapsed_ms": elapsed}
    return {"state": "frame_acquired", "media_ref": reference,
            "sha256": claimed, "size_bytes": size,
            "width": width, "height": height,
            "reason": str(payload.get("reason", ""))[:300],
            "elapsed_ms": elapsed}


def run_probe(timeout: float = PROBE_TIMEOUT_SECONDS) -> dict:
    """Run USB imaging enumeration isolated. Never raises."""
    try:
        budget = float(timeout)
    except (TypeError, ValueError):
        return {"state": "error",
                "reason": "timeout must be a number",
                "devices": [], "elapsed_ms": 0}
    budget = max(1.0, min(budget, MAX_TIMEOUT_SECONDS))
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [sys.executable, "-c", _PROBE_SNIPPET],
            cwd=str(_project_root()),
            capture_output=True, text=True, timeout=budget,
            stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - started) * 1000)
        return {"state": "timeout",
                "reason": f"enumeration exceeded {budget:g}s; killed",
                "devices": [], "elapsed_ms": elapsed}
    except (OSError, ValueError) as error:
        elapsed = int((time.monotonic() - started) * 1000)
        return {"state": "error",
                "reason": f"probe spawn failed: {type(error).__name__}",
                "devices": [], "elapsed_ms": elapsed}
    elapsed = int((time.monotonic() - started) * 1000)
    if completed.returncode != 0:
        tail = (completed.stderr or "").strip()[-300:]
        return {"state": "crashed",
                "reason": ("child died "
                           f"(exit {completed.returncode})"
                           + (f": {tail}" if tail else "")),
                "devices": [], "elapsed_ms": elapsed}
    try:
        payload = json.loads(completed.stdout or "{}")
    except ValueError:
        return {"state": "error",
                "reason": "child returned invalid JSON",
                "devices": [], "elapsed_ms": elapsed}
    if not isinstance(payload, dict):
        return {"state": "error",
                "reason": "child returned non-object JSON",
                "devices": [], "elapsed_ms": elapsed}
    if not payload.get("supported", False):
        return {"state": "error",
                "reason": str(payload.get("reason", "unsupported") or
                              "unsupported")[:300],
                "devices": [], "elapsed_ms": elapsed}
    devices = payload.get("devices", [])
    if not isinstance(devices, list):
        devices = []
    clean = []
    for entry in devices[:MAX_DEVICES]:
        if not isinstance(entry, dict):
            continue
        clean.append({
            "name": str(entry.get("name", ""))[:MAX_NAME_CHARS],
            "path": str(entry.get("path", ""))[:MAX_NAME_CHARS],
        })
    if not clean:
        return {"state": "none_found",
                "reason": "enumeration ok, zero imaging devices",
                "devices": [], "elapsed_ms": elapsed}
    return {"state": "found",
            "reason": f"{len(clean)} imaging device(s) by name only",
            "devices": clean, "elapsed_ms": elapsed}
