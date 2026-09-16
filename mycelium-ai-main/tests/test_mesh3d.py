"""Mesh generation + validation tests (BIG #7).

Deterministic test geometry, unavailable provider honesty,
format sanity (ASCII/binary STL, OBJ), NaN/Inf/excessive
geometry refusal, printability assessments.
"""

import hashlib
import os
import struct

import pytest


@pytest.fixture(autouse=True)
def isolated_fab_dir(tmp_path, monkeypatch):
    """Each test gets its own fabrication dir: no cross-test
    file bleed through the shared temp directory."""
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "fab"))
from coordinator.app.mesh3d import (
    MeshRefusedError,
    MeshUnavailable,
    ProceduralTestGenerator,
    UnavailableGenerator,
    artifact_path,
    assess_printability,
    check_artifact_ref,
    fabrication_dir,
    file_payload_for_mesh,
    get_generator,
    read_artifact_bytes,
    validate_mesh,
)


def test_generator_is_deterministic_and_marked():
    first = ProceduralTestGenerator().generate("kubus", {})
    second = ProceduralTestGenerator().generate("kubus", {})
    assert first.sha256 == second.sha256
    assert first.test_origin is True
    assert "test-origin" in first.provenance.notes
    assert first.provenance.human_verified is False
    assert first.format == "stl-ascii"


def test_unavailable_generator_refuses():
    with pytest.raises(MeshUnavailable, match="no fake STL"):
        get_generator("unavailable").generate("x", {})
    with pytest.raises(MeshRefusedError, match="Unknown 3D"):
        get_generator("cloud-magic")


def test_valid_cube_report():
    generated = ProceduralTestGenerator().generate("kubus", {})
    report = validate_mesh(generated.artifact_ref)
    assert report.verdict == "valid"
    assert report.faces == 12
    assert report.vertices == 36
    assert report.bounds_mm == [-10.0, -10.0, -10.0,
                                10.0, 10.0, 10.0]
    assessment = assess_printability(report)
    assert assessment.verdict == "printable"
    assert not hasattr(assessment, "safe_to_print")


def test_printability_rejects_oversize():
    generated = ProceduralTestGenerator().generate("kubus", {})
    report = validate_mesh(generated.artifact_ref)
    assessment = assess_printability(
        report, build_volume_mm=(5.0, 5.0, 5.0))
    assert assessment.verdict == "not_printable"
    assert any("exceeds build" in reason
               for reason in assessment.reasons)


def test_printability_needs_valid_mesh():
    report = validate_mesh(
        ProceduralTestGenerator().generate("x", {}).artifact_ref)
    broken = report.model_copy(update={"verdict": "invalid",
                                       "reasons": ["bad"]})
    assert assess_printability(broken).verdict == "not_printable"
    unknown = report.model_copy(update={"verdict": "inconclusive",
                                        "reasons": ["?"]})
    assert assess_printability(unknown).verdict == "inconclusive"


def _write(name: str, data: bytes) -> str:
    path = os.path.join(fabrication_dir(), name)
    with open(path, "wb") as handle:
        handle.write(data)
    return name


def test_malformed_meshes_invalid():
    ref = _write("fab-bad1.stl", b"geen mesh maar tekst\n")
    assert validate_mesh(ref).verdict in ("invalid", "inconclusive")
    ref = _write("fab-bad2.stl", b"solid\nvertex x y z\n")
    assert validate_mesh(ref).verdict == "invalid"
    ref = _write("fab-bad3.obj", b"v 0 0\nf 1 2\n")
    assert validate_mesh(ref).verdict == "invalid"


def test_nan_inf_refused():
    ref = _write("fab-nan.stl",
                 b"solid t\nfacet normal 0 0 0\nouter loop\n"
                 b"vertex nan 0 0\nvertex 0 0 0\nvertex 0 1 0\n"
                 b"endloop\nendfacet\nendsolid t\n")
    assert validate_mesh(ref).verdict == "invalid"
    ref = _write("fab-inf.obj", b"v inf 0 0\nv 0 0 0\nv 0 1 0\n"
                 b"f 1 2 3\n")
    assert validate_mesh(ref).verdict == "invalid"


def test_binary_stl_parses():
    header = b"\x00" * 80
    facet = struct.pack("<12fH", 0, 0, 1,
                        0, 0, 0, 1, 0, 0, 0, 1, 0, 0)
    data = header + struct.pack("<I", 1) + facet
    ref = _write("fab-bin.stl", data)
    report = validate_mesh(ref)
    assert report.verdict == "valid"
    assert report.format == "stl-binary"
    assert report.faces == 1


def test_truncated_binary_is_invalid():
    ref = _write("fab-trunc.stl", b"\x00" * 90)
    report = validate_mesh(ref)
    assert report.verdict in ("invalid", "inconclusive")


def test_artifact_boundaries():
    with pytest.raises(MeshRefusedError):
        check_artifact_ref("../buiten.stl")
    with pytest.raises(MeshRefusedError):
        check_artifact_ref("C:\\x\\y.stl")
    with pytest.raises(MeshRefusedError):
        check_artifact_ref("model.step")
    with pytest.raises(MeshRefusedError):
        read_artifact_bytes("fab-bestaat-niet.stl")
    assert artifact_path("fab-test-cube.stl").endswith(
        "fab-test-cube.stl")


def test_file_payload_for_mesh():
    report = validate_mesh(
        ProceduralTestGenerator().generate("x", {}).artifact_ref)
    payload = file_payload_for_mesh(
        report, "ab" * 32, 1823, "testkubus")
    assert payload["file_kind"] == "mesh"
    assert payload["sha256"] == "ab" * 32
    assert payload["metadata"]["validation"] == "valid"
    broken = report.model_copy(update={"verdict": "invalid"})
    with pytest.raises(MeshRefusedError, match="Invalid meshes"):
        file_payload_for_mesh(broken, "ab" * 32, 10, "x")
    assert hashlib.sha256(b"").hexdigest() != "ab" * 32
