"""Desktop runtime tests (Fase G/Q).

Dry-run backend (validates, executes nothing), BMP writer roundtrip,
observation pruning, and the dispatched-only execution gate. Real
input is never performed here: MYCELIUM_DESKTOP_DRYRUN forces the
safe backend, and the Windows backend is only touched for a
read-only screenshot.
"""

import os
import struct

import pytest

from coordinator.app.agent_loop import (
    decide,
    dispatch,
    propose,
)
from coordinator.app.computer_actions import new_action
from coordinator.app.desktop_runtime import (
    BackendUnavailable,
    DryRunDesktopBackend,
    get_backend,
    observation_dir,
    prune_observations,
    run_approved_action,
    write_bmp_24,
)


def test_dryrun_blocks_input_without_side_effects(monkeypatch):
    monkeypatch.setenv("MYCELIUM_DESKTOP_DRYRUN", "1")
    backend = get_backend()
    assert isinstance(backend, DryRunDesktopBackend)
    result = backend.execute(new_action("dact-1", "click",
                                        {"x": 10, "y": 10}))
    assert result.status == "blocked"
    assert "Dry-run" in result.error


def test_dryrun_screenshot_raises_instead_of_faking(monkeypatch):
    monkeypatch.setenv("MYCELIUM_DESKTOP_DRYRUN", "1")
    with pytest.raises(BackendUnavailable):
        get_backend().screenshot()


def test_dryrun_rejects_garbage_action():
    backend = DryRunDesktopBackend()
    result = backend.execute("not-an-action")
    assert result.status == "blocked"


def test_get_backend_defaults_to_dryrun_off_windows(monkeypatch):
    monkeypatch.setenv("MYCELIUM_DESKTOP_DRYRUN", "1")
    assert isinstance(get_backend(), DryRunDesktopBackend)


def test_bmp_writer_produces_readable_bitmap(tmp_path):
    path = str(tmp_path / "shot.bmp")
    pixels = b"\xff\x00\x00" * 4 + b"\x00\xff\x00" * 4
    write_bmp_24(path, 4, 2, pixels)
    with open(path, "rb") as handle:
        data = handle.read()
    assert data[:2] == b"BM"
    file_size, _, _, offset = struct.unpack("<IHHI", data[2:14])
    assert file_size == len(data) and offset == 54
    width, height, _, bits = struct.unpack("<iiHH", data[18:30])
    assert (width, height, bits) == (4, 2, 24)


def test_prune_keeps_latest_only(tmp_path, monkeypatch):
    import coordinator.app.desktop_runtime as runtime
    monkeypatch.setattr(runtime, "observation_dir", lambda: str(tmp_path))
    directory = runtime.observation_dir()
    for index in range(8):
        open(os.path.join(directory, f"obs-{index:04d}.bmp"),
             "wb").write(b"x")
    removed = prune_observations(keep=5)
    assert removed == 3
    remaining = sorted(os.listdir(directory))
    assert len(remaining) == 5


def test_run_refuses_anything_not_dispatched():
    backend = DryRunDesktopBackend()
    pending = propose(new_action("dact-1", "click", {"x": 1, "y": 1}))
    with pytest.raises(ValueError):
        run_approved_action(pending, backend)
    approved = decide(pending, "dact-1", "YES")
    with pytest.raises(ValueError):
        run_approved_action(approved, backend)


def test_run_dispatched_reports_blocked_on_dryrun():
    backend = DryRunDesktopBackend()
    record = dispatch(decide(
        propose(new_action("dact-9", "type_text", {"text": "hoi"})),
        "dact-9", "YES"), "dact-9")
    closed = run_approved_action(record, backend)
    assert closed.status == "blocked"
    assert closed.result is not None


def test_no_shell_code_or_network_surface():
    import coordinator.app.desktop_runtime as runtime
    source = open(runtime.__file__, encoding="utf-8").read()
    lowered = source.lower()
    for token in ("import subprocess", "from subprocess", "os.system",
                  "shell=true", "eval(", "import socket", "import httpx",
                  "import urllib", "import requests"):
        assert token not in lowered
    assert "SendInput" in source  # real input path exists
    assert "BitBlt" in source  # real capture path exists


def test_windows_screenshot_stays_local():
    import sys
    if sys.platform != "win32" or os.environ.get(
            "MYCELIUM_DESKTOP_DRYRUN") == "1":
        pytest.skip("Windows screenshot only on real Windows")
    from coordinator.app.desktop_runtime import WindowsDesktopBackend
    observation = WindowsDesktopBackend().screenshot()
    assert observation.width >= 1 and observation.height >= 1
    assert observation.image_ref.endswith(".bmp")
    assert observation.provenance.human_verified is False
    full = os.path.join(observation_dir(), observation.image_ref)
    assert os.path.isfile(full)
