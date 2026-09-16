"""Fabrication security tripwires (BIG #7).

No shell, no SQL on world tables, no cloud, no fake geometry/
G-code/telemetry, no auto-execution, no forged verification,
no safe_to_execute anywhere, no public exposure.
"""

import pathlib

import pytest


@pytest.fixture(autouse=True)
def isolated_fab_dir(tmp_path, monkeypatch):
    """Each test gets its own fabrication dir: no cross-test
    file bleed through the shared temp directory."""
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "fab"))


APP = pathlib.Path(__file__).resolve().parent.parent / "coordinator" / "app"


def source_of(*names: str) -> str:
    return "\n".join(
        (APP / name).read_text(encoding="utf-8") for name in names)


FAB_MODULES = ("mesh3d.py", "slicer3d.py", "printer3d.py",
               "fab_flow.py")


def test_no_shell_or_code_execution():
    source = source_of(*FAB_MODULES)
    for token in ("subprocess", "os.system", "os.popen", "shell=True",
                  "eval(", "exec(", "__import__"):
        assert token not in source, f"forbidden token: {token}"


def test_no_heavy_or_vendor_dependencies():
    source = source_of(*FAB_MODULES)
    for token in ("import numpy", "import trimesh", "import PIL",
                  "from PIL", "import serial", "from serial",
                  "import usb", "octoprint", "cura", "prusa",
                  "import requests", "import boto"):
        assert token not in source, f"forbidden token: {token}"


def test_no_sql_on_world_tables():
    source = source_of(*FAB_MODULES)
    assert "import sqlite3" not in source
    for table in ("objects", "projects", "ideas", "relationships",
                  "files", "events", "camera_devices",
                  "camera_observations"):
        assert f"INTO {table}" not in source, f"table write: {table}"
        assert f"UPDATE {table}" not in source, f"table update: {table}"
        assert f"DELETE FROM {table}" not in source, (
            f"table delete: {table}")


def test_no_cloud_or_network():
    source = source_of(*FAB_MODULES)
    for token in ("import socket", "urlopen", "0.0.0.0", "listen(",
                  ".bind(", "https://", "upload("):
        assert token not in source, f"forbidden token: {token}"


def test_no_safe_to_execute_anywhere():
    source = source_of(*FAB_MODULES)
    # Binding forms only: prose may name the forbidden concept,
    # but no field, flag or permission may ever carry it.
    for token in ("safe_to_execute=", "safe_to_execute :",
                  "'safe_to_execute'", '"safe_to_execute"'):
        assert token not in source, f"forbidden token: {token}"


def test_no_auto_execution_path():
    from coordinator.app import fab_flow
    assert not hasattr(fab_flow, "auto_print")
    assert not hasattr(fab_flow, "start_print")
    source = (APP / "fab_flow.py").read_text(encoding="utf-8")
    for token in ("auto_print", "direct-print", "start_print(",
                  "auto_start"):
        assert token not in source, f"forbidden token: {token}"


def test_existing_pipeline_still_refuses_physical():
    from coordinator.app.pipeline3d import new_generation_request
    for method in ("printer", "gcode", "auto", "cloud"):
        with pytest.raises(ValueError):
            new_generation_request("req-s", "obj_x", method)


def test_changed_artifact_fingerprint_rejected():
    import hashlib
    from coordinator.app.mesh3d import (
        artifact_path,
        read_artifact_bytes,
    )
    from coordinator.app.slicer3d import TestSlicer, check_slicer_request
    from coordinator.app.mesh3d import ProceduralTestGenerator
    mesh = ProceduralTestGenerator().generate("kubus", {}).artifact_ref
    request = check_slicer_request(mesh, "draft-pla", "prt-s")
    result = TestSlicer().slice(request)
    original = hashlib.sha256(
        read_artifact_bytes(result.gcode_ref)).hexdigest()
    assert original == result.sha256
    with open(artifact_path(result.gcode_ref), "a",
              encoding="utf-8") as handle:
        handle.write("; tampered\n")
    tampered = hashlib.sha256(
        read_artifact_bytes(result.gcode_ref)).hexdigest()
    assert tampered != result.sha256


def test_telemetry_cannot_forge_verification():
    from coordinator.app.fab_flow import (
        new_telemetry_request,
        verify_print_telemetry,
    )
    from coordinator.app.controlled_writes import WriteResult, now
    from coordinator.app.inventory_read import Provenance
    request = new_telemetry_request("wrt-s", "0" * 64, "ab" * 32)
    result = WriteResult(
        proposal_id="wrt-s", fingerprint="0" * 64,
        outcome="failed", actor="t", executed_at=now(),
        provenance=Provenance(source_type="sensor-observed",
                              creator_id="t",
                              human_verified=False))
    verification = verify_print_telemetry(request, result)
    assert verification.outcome == "failed"
    from coordinator.app.verification import is_verified
    assert is_verified(verification) is False


def test_ai_cannot_set_verified_or_safe():
    from coordinator.app.mesh3d import (
        ProceduralTestGenerator,
        validate_mesh,
    )
    report = validate_mesh(
        ProceduralTestGenerator().generate("x", {}).artifact_ref)
    assert not hasattr(report, "human_verified")
    assert report.verdict == "valid"
    from coordinator.app.slicer3d import (
        TestSlicer,
        check_slicer_request,
        validate_gcode,
    )
    from coordinator.app.mesh3d import ProceduralTestGenerator as Gen
    mesh = Gen().generate("x", {}).artifact_ref
    safety = validate_gcode(TestSlicer().slice(
        check_slicer_request(mesh, "draft-pla", "prt-s")).gcode_ref)
    assert not hasattr(safety, "human_verified")
    assert not hasattr(safety, "safe_to_execute")
