"""Slicer + G-code safety tests (BIG #7).

Closed profiles, deterministic test slicer, unavailable
slicer honesty, G-code validation (commands, temperatures,
bounds) and safety verdicts that never authorize execution.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def isolated_fab_dir(tmp_path, monkeypatch):
    """Each test gets its own fabrication dir: no cross-test
    file bleed through the shared temp directory."""
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "fab"))
from coordinator.app.mesh3d import (
    ProceduralTestGenerator,
    fabrication_dir,
    validate_mesh,
)
from coordinator.app.slicer3d import (
    SlicerRefusedError,
    SlicerUnavailable,
    TestSlicer,
    UnavailableSlicer,
    check_profile,
    check_slicer_request,
    file_payload_for_gcode,
    get_slicer,
    validate_gcode,
)


def make_mesh_ref() -> str:
    return ProceduralTestGenerator().generate("kubus", {}).artifact_ref


def make_slice() -> str:
    request = check_slicer_request(make_mesh_ref(), "draft-pla",
                                   "prt-test1")
    return TestSlicer().slice(request).gcode_ref


def test_profiles_are_closed():
    assert check_profile("draft-pla")["material"] == "PLA"
    with pytest.raises(SlicerRefusedError, match="Unknown slicer"):
        check_profile("turbo-abs")
    with pytest.raises(SlicerRefusedError, match="mesh artifact"):
        check_slicer_request("fab-x.gcode", "draft-pla", "prt-1")
    with pytest.raises(SlicerRefusedError, match="Unknown slicer"):
        get_slicer("cloud-slice")


def test_test_slicer_is_marked_and_deterministic():
    request = check_slicer_request(make_mesh_ref(), "fine-pla",
                                   "prt-test1")
    first = TestSlicer().slice(request)
    second = TestSlicer().slice(request)
    assert first.sha256 == second.sha256
    assert first.test_generated is True
    assert "test-origin" in first.provenance.notes
    assert first.provenance.human_verified is False
    assert first.line_count > 5


def test_unavailable_slicer_refuses():
    request = check_slicer_request(make_mesh_ref(), "draft-pla",
                                   "prt-test1")
    with pytest.raises(SlicerUnavailable, match="no fake G-code"):
        get_slicer("unavailable").slice(request)
    assert "reviewed" in UnavailableSlicer.requirements().lower() or \
        "reviewed" in UnavailableSlicer.requirements()


def test_test_gcode_is_safe_but_not_permission():
    assessment = validate_gcode(make_slice())
    assert assessment.verdict == "safe"
    assert not hasattr(assessment, "safe_to_execute")
    assert assessment.line_count > 5


def _write(name: str, text: str) -> str:
    path = os.path.join(fabrication_dir(), name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return name


def test_dangerous_gcode_is_unsafe():
    ref = _write("fab-evil.gcode",
                 "G28\nM104 S9999\nG1 X10 E1\n")
    assessment = validate_gcode(ref)
    assert assessment.verdict == "unsafe"
    assert any("exceeds" in finding
               for finding in assessment.findings)
    ref = _write("fab-evil2.gcode", "G28\nM112\nG1 X1\n")
    assert validate_gcode(ref).verdict == "unsafe"


def test_unknown_commands_are_inconclusive():
    ref = _write("fab-weird.gcode", "G28\nM9999 Z1\nG1 X1\n")
    assessment = validate_gcode(ref)
    assert assessment.verdict == "inconclusive"
    assert any("unknown command" in finding
               for finding in assessment.findings)


def test_gcode_boundaries():
    with pytest.raises(SlicerRefusedError):
        validate_gcode("../buiten.gcode")
    with pytest.raises(SlicerRefusedError):
        validate_gcode("fab-test-cube.stl")
    ref = _write("fab-empty.gcode", "M104 S200\n")
    assert validate_gcode(ref).verdict == "inconclusive"


def test_file_payload_for_gcode():
    assessment = validate_gcode(make_slice())
    payload = file_payload_for_gcode(
        assessment, "cd" * 32, 500, "testprint")
    assert payload["file_kind"] == "gcode"
    assert payload["metadata"]["safety"] == "safe"
    unsafe = assessment.model_copy(update={"verdict": "unsafe"})
    with pytest.raises(SlicerRefusedError, match="Unsafe G-code"):
        file_payload_for_gcode(unsafe, "cd" * 32, 500, "x")
