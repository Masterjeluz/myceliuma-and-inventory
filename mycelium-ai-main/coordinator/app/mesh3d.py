"""3D generation + mesh validation for Mycelium (BIG #7).

Sits beside the BIG #5 contracts in ``pipeline3d.py`` (untouched:
feasibility stays advice, physical methods stay refused there).
This module adds what that contract deliberately lacks: a real
(but strictly bounded) generation path and real mesh validation.

Pipeline position:

    INVENTory object/idea -> generation request (advice-shaped)
        -> provider generates bytes (local only)
        -> mesh validation (valid/invalid/inconclusive)
        -> File payload (inert, BIG #5 approval flow)

Rules (tested, all fail-closed):

- Providers: ``ThreeDProvider`` interface; only
  ``ProceduralTestGenerator`` (deterministic test cube, always
  test-marked) and ``UnavailableGenerator`` (explicit reason)
  exist. No network, no downloads, no cloud, no vendor SDK.
- A generated artifact is never valid/printable/safe/verified
  by itself: generation returns bytes + metadata, validation
  is a separate step with its own verdict.
- Validation is stdlib-only: ASCII/binary STL and minimal OBJ
  parsing with finite-float checks (NaN/Inf refuse), bounded
  vertex/face counts, bounded file size, allow-listed suffixes
  inside the fabrication dir. Anything unparseable is
  ``inconclusive`` — never ``valid``.
- Provenance is set by this module (ai-generated, unverified).
  Model/generator output never self-verifies.
"""

import hashlib
import math
import os
import struct
import tempfile
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import Provenance

FABRICATION_DIR_NAME = "mycelium-fab"
FABRICATION_RETENTION = 5

#: Closed set of mesh suffixes this layer reads or writes.
MESH_SUFFIXES = (".stl", ".obj")

#: Hard caps: files, geometry and text stay bounded.
MAX_MESH_BYTES = 20 * 1024 * 1024
MAX_VERTICES = 500_000
MAX_FACES = 1_000_000
MAX_LINE_CHARS = 4096

#: Default build volume (mm) for printability heuristics.
DEFAULT_BUILD_VOLUME_MM = (220.0, 220.0, 250.0)

TEST_ORIGIN_MARK = "test-origin: synthetic geometry, never a real design"


class MeshRefusedError(ValueError):
    """Local validation refused; nothing was generated or read."""


class MeshUnavailable(RuntimeError):
    """No generation path. Fail-closed, never fake geometry."""


class GenerationResult(BaseModel):
    """Bytes plus metadata. Advice-shaped output, never a release."""

    model_config = ConfigDict(extra="forbid")

    artifact_ref: str = Field(min_length=1, max_length=200)
    sha256: str = Field(min_length=64, max_length=64,
                        pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    format: str = Field(min_length=1, max_length=20)
    generator: str = Field(min_length=1, max_length=80)
    test_origin: bool = False
    provenance: Provenance = Field(default_factory=Provenance)


class MeshReport(BaseModel):
    """Validation verdict over one mesh file."""

    model_config = ConfigDict(extra="forbid")

    artifact_ref: str = Field(min_length=1, max_length=200)
    format: str = Field(min_length=1, max_length=20)
    verdict: str = Field(default="inconclusive", max_length=20)
    vertices: int = Field(default=0, ge=0)
    faces: int = Field(default=0, ge=0)
    degenerate_faces: int = Field(default=0, ge=0)
    bounds_mm: list[float] = Field(default_factory=list,
                                   max_length=6)
    checks: list[str] = Field(default_factory=list, max_length=30)
    reasons: list[str] = Field(default_factory=list, max_length=30)


class PrintabilityAssessment(BaseModel):
    """Heuristic assessment. An assessment is never permission:
    there is deliberately no ``safe_to_print`` field anywhere."""

    model_config = ConfigDict(extra="forbid")

    artifact_ref: str = Field(min_length=1, max_length=200)
    verdict: str = Field(default="inconclusive", max_length=20)
    reasons: list[str] = Field(default_factory=list, max_length=30)
    checks: list[str] = Field(default_factory=list, max_length=30)


def fabrication_dir() -> str:
    path = os.path.join(tempfile.gettempdir(), FABRICATION_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def prune_fabrication(keep: int = FABRICATION_RETENTION) -> int:
    try:
        entries = os.listdir(fabrication_dir())
    except OSError:
        return 0
    artifacts = sorted(entry for entry in entries
                       if entry.startswith("fab-")
                       and entry.lower().endswith(
                           MESH_SUFFIXES + (".gcode",)))
    removed = 0
    for entry in artifacts[:max(0, len(artifacts) - keep)]:
        try:
            os.remove(os.path.join(fabrication_dir(), entry))
            removed += 1
        except OSError:
            continue
    return removed


def check_artifact_ref(value: str) -> str:
    """Fabrication filename only: no paths, URLs or schemes, and a
    known artifact suffix (.stl/.obj/.gcode). Fail-closed."""
    if not isinstance(value, str):
        raise MeshRefusedError("artifact_ref must be text")
    text = value.strip()
    if not text:
        raise MeshRefusedError("artifact_ref must be non-empty text")
    if len(text) > 200:
        raise MeshRefusedError("artifact_ref too long")
    lowered = text.lower()
    if ("://" in lowered or text.startswith("\\\\")
            or text.startswith("/") or ":" in text):
        raise MeshRefusedError(
            "artifact_ref must be a plain local filename")
    if ".." in text or "/" in text or "\\" in text:
        raise MeshRefusedError("artifact_ref must not contain a path")
    if not lowered.endswith(MESH_SUFFIXES + (".gcode",)):
        raise MeshRefusedError(
            "artifact_ref must be a .stl, .obj or .gcode file")
    return text


def artifact_path(artifact_ref: str) -> str:
    """Resolve one validated ref inside the fabrication dir."""
    reference = check_artifact_ref(artifact_ref)
    root = os.path.abspath(fabrication_dir())
    path = os.path.abspath(os.path.join(root, reference))
    if path != root and not path.startswith(root + os.sep):
        raise MeshRefusedError(
            "Artifact escapes the fabrication directory")
    return path


def read_artifact_bytes(artifact_ref: str) -> bytes:
    """Read one allow-listed artifact file, capped. Everything else
    refuses before any byte is read."""
    path = artifact_path(artifact_ref)
    if not os.path.isfile(path):
        raise MeshRefusedError(
            f"Artifact '{artifact_ref}' does not exist; refusing")
    size = os.path.getsize(path)
    if size <= 0:
        raise MeshRefusedError("Artifact is empty; refusing")
    if size > MAX_MESH_BYTES:
        raise MeshRefusedError(
            f"Artifact is {size} bytes (max {MAX_MESH_BYTES}); refusing")
    with open(path, "rb") as handle:
        return handle.read(MAX_MESH_BYTES + 1)


def _store_artifact(filename: str, data: bytes) -> str:
    reference = check_artifact_ref(filename)
    if len(data) > MAX_MESH_BYTES:
        raise MeshRefusedError("Artifact exceeds the size cap")
    prune_fabrication()
    path = os.path.abspath(
        os.path.join(os.path.abspath(fabrication_dir()), reference))
    with open(path, "wb") as handle:
        handle.write(data)
    return reference


# -- providers ------------------------------------------------------------

class ThreeDProvider:
    """Interface for 3D sources. Subclasses implement generate()."""

    name = "base"

    def generate(self, description: str, params: dict
                 ) -> GenerationResult:
        raise NotImplementedError


def _test_cube_stl(size_mm: float = 20.0) -> bytes:
    """Deterministic ASCII STL of a cube. Fixed vertices, fixed
    text — the same input always yields the same bytes."""
    half = size_mm / 2.0
    corners = [(-half, -half, -half), (half, -half, -half),
               (half, half, -half), (-half, half, -half),
               (-half, -half, half), (half, -half, half),
               (half, half, half), (-half, half, half)]
    faces = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
             (0, 4, 5), (0, 5, 1), (2, 6, 7), (2, 7, 3),
             (0, 3, 7), (0, 7, 4), (1, 5, 6), (1, 6, 2)]
    lines = ["solid mycelium_test_cube"]
    for face in faces:
        lines.append("  facet normal 0 0 0")
        lines.append("    outer loop")
        for index in face:
            x, y, z = corners[index]
            lines.append(f"      vertex {x:.1f} {y:.1f} {z:.1f}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append("endsolid mycelium_test_cube")
    return ("\n".join(lines) + "\n").encode("ascii")


class ProceduralTestGenerator(ThreeDProvider):
    """Deterministic TEST generator. A fixed 20mm cube as ASCII STL;
    no parameters influence geometry, no network, no CAD kernel."""

    name = "procedural-test"

    def generate(self, description: str, params: dict
                 ) -> GenerationResult:
        from datetime import datetime, timezone
        _ = (description, params)
        data = _test_cube_stl()
        reference = _store_artifact("fab-test-cube.stl", data)
        return GenerationResult(
            artifact_ref=reference,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data), format="stl-ascii",
            generator=self.name, test_origin=True,
            provenance=Provenance(
                source_type="ai-generated",
                creator_id="fabrication:test-generator",
                human_verified=False,
                notes=TEST_ORIGIN_MARK))


class UnavailableGenerator(ThreeDProvider):
    """Explicit unavailable generator. Complete interface, zero bytes."""

    name = "unavailable"

    def __init__(self, reason: str = "no 3D generator available"):
        self.reason = reason

    def generate(self, description: str, params: dict
                 ) -> GenerationResult:
        raise MeshUnavailable(
            f"{self.reason}; no fake STL, no cloud generation, "
            "no runtime download")


def get_generator(name: str | None = None, **kwargs) -> ThreeDProvider:
    """Resolve a generator by name. Unknown names fail closed."""
    resolved = (name or "unavailable").strip().lower()
    if resolved == "procedural-test":
        return ProceduralTestGenerator()
    if resolved == "unavailable":
        return UnavailableGenerator(**kwargs)
    raise MeshRefusedError(f"Unknown 3D generator '{name}'")


# -- mesh validation (stdlib only) -----------------------------------------

def _parse_stl_ascii(text: str):
    """Returns (facets, degenerate, notes, checks). Errors arrive as
    notes with empty facets; the caller decides the verdict."""
    checks = ["ascii-st-header"]
    lines = text.splitlines()
    if not lines or not lines[0].strip().lower().startswith("solid"):
        return [], 0, ["missing solid header"], checks
    facets: list = []
    degenerate = 0
    current: list = []
    for line in lines[1:]:
        if len(line) > MAX_LINE_CHARS:
            return [], 0, ["line exceeds cap"], checks
        stripped = line.strip()
        if stripped.lower().startswith("vertex"):
            parts = stripped.split()
            if len(parts) != 4:
                return [], 0, ["malformed vertex line"], checks
            try:
                point = (float(parts[1]), float(parts[2]),
                         float(parts[3]))
            except ValueError:
                return [], 0, ["non-numeric vertex"], checks
            if any(not math.isfinite(value) for value in point):
                return [], 0, ["non-finite vertex (NaN/Inf)"], checks
            current.append(point)
            if len(current) == 3:
                if current[0] == current[1] or current[1] == current[2] \
                        or current[0] == current[2]:
                    degenerate += 1
                facets.append(tuple(current))
                current = []
                if len(facets) > MAX_FACES:
                    return [], 0, ["face count exceeds cap"], checks
    checks.append(f"facets={len(facets)}")
    if current:
        return [], 0, ["truncated facet"], checks
    notes = (["degenerate=%d" % degenerate] if degenerate else [])
    return facets, degenerate, notes, checks


def _parse_stl_binary(data: bytes):
    checks = ["binary-st-header"]
    if len(data) < 84:
        return [], 0, ["file too small for binary STL"], checks
    try:
        (count,) = struct.unpack("<I", data[80:84])
    except struct.error:
        return [], 0, ["unreadable facet count"], checks
    if count <= 0:
        return [], 0, ["no facets"], checks
    if count > MAX_FACES:
        return [], 0, ["face count exceeds cap"], checks
    if len(data) < 84 + count * 50:
        return [], 0, ["truncated binary STL"], checks
    facets: list = []
    degenerate = 0
    offset = 84
    for _ in range(count):
        try:
            values = struct.unpack("<12fH", data[offset:offset + 50])
        except struct.error:
            return [], 0, ["unreadable facet"], checks
        points = [values[3:6], values[6:9], values[9:12]]
        if any(not math.isfinite(v) for point in points
               for v in point):
            return [], 0, ["non-finite vertex (NaN/Inf)"], checks
        if points[0] == points[1] or points[1] == points[2] \
                or points[0] == points[2]:
            degenerate += 1
        facets.append(tuple(points))
        offset += 50
    checks.append(f"facets={len(facets)}")
    notes = (["degenerate=%d" % degenerate] if degenerate else [])
    return facets, degenerate, notes, checks


def _parse_obj(text: str):
    checks = ["obj-vertex-face"]
    points: list = []
    facets: list = []
    degenerate = 0
    for line in text.splitlines():
        if len(line) > MAX_LINE_CHARS:
            return [], [], 0, ["line exceeds cap"], checks
        stripped = line.strip()
        if stripped.startswith("v "):
            parts = stripped.split()
            if len(parts) < 4:
                return [], [], 0, ["malformed vertex line"], checks
            try:
                point = (float(parts[1]), float(parts[2]),
                         float(parts[3]))
            except ValueError:
                return [], [], 0, ["non-numeric vertex"], checks
            if any(not math.isfinite(value) for value in point):
                return [], [], 0, ["non-finite vertex (NaN/Inf)"], checks
            points.append(point)
            if len(points) > MAX_VERTICES:
                return [], [], 0, ["vertex count exceeds cap"], checks
        elif stripped.startswith("f "):
            parts = stripped.split()[1:]
            if len(parts) < 3:
                return [], [], 0, ["degenerate face line"], checks
            try:
                indices = [int(part.split("/")[0]) for part in parts]
            except ValueError:
                return [], [], 0, ["non-numeric face index"], checks
            if any(index < 1 or index > len(points)
                   for index in indices):
                return [], [], 0, ["face index out of range"], checks
            if len(set(indices)) != len(indices):
                degenerate += 1
            # Fan triangulation keeps bounds exact for convex n-gons
            # and bounded for anything else.
            for index in range(1, len(indices) - 1):
                facets.append((points[indices[0] - 1],
                               points[indices[index] - 1],
                               points[indices[index + 1] - 1]))
            if len(facets) > MAX_FACES:
                return [], [], 0, ["face count exceeds cap"], checks
    checks.append(f"vertices={len(points)}")
    checks.append(f"faces={len(facets)}")
    notes = (["degenerate=%d" % degenerate] if degenerate else [])
    return points, facets, degenerate, notes, checks


def validate_mesh(artifact_ref: str) -> MeshReport:
    """Validate one mesh artifact. Verdicts: valid (parsed fully,
    finite, non-empty, within caps), invalid (concrete defect), or
    inconclusive (unparseable as a known mesh — never valid)."""
    data = read_artifact_bytes(artifact_ref)
    lowered = artifact_ref.lower()
    if lowered.endswith(".stl"):
        text = None
        try:
            text = data.decode("ascii")
        except UnicodeDecodeError:
            text = None
        if text is not None and text.lstrip().lower().startswith(
                "solid"):
            facets, degenerate, notes, checks = _parse_stl_ascii(text)
            format_name = "stl-ascii"
            point_count = len(facets) * 3
        else:
            facets, degenerate, notes, checks = _parse_stl_binary(
                data)
            format_name = "stl-binary"
            point_count = len(facets) * 3
    elif lowered.endswith(".obj"):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return _report(artifact_ref, "obj", "inconclusive", 0, 0,
                           ["not decodable as UTF-8 text"], [])
        points, facets, degenerate, notes, checks = _parse_obj(text)
        format_name = "obj"
        point_count = len(points)
    else:  # pragma: no cover - guarded by check_artifact_ref
        raise MeshRefusedError("Unsupported mesh suffix")
    if any("exceeds cap" in note or "malformed" in note
           or "non-numeric" in note or "non-finite" in note
           or "truncated" in note or "missing" in note
           or "out of range" in note or "no facets" in note
           or "too small" in note or "not decodable" in note
           for note in notes):
        return _report(artifact_ref, format_name, "invalid",
                       point_count, len(facets), degenerate, notes,
                       checks)
    if not facets:
        return _report(artifact_ref, format_name, "inconclusive",
                       point_count, 0, degenerate,
                       ["empty geometry"], checks)
    return _report(artifact_ref, format_name, "valid", point_count,
                   len(facets), degenerate, notes, checks)


def _report(artifact_ref: str, format_name: str, verdict: str,
            point_count: int, face_count: int, degenerate: int,
            reasons, checks) -> MeshReport:
    return MeshReport(
        artifact_ref=artifact_ref, format=format_name,
        verdict=verdict,
        vertices=point_count,
        faces=face_count,
        degenerate_faces=degenerate if verdict == "valid" else 0,
        bounds_mm=_bounds_of(artifact_ref, format_name),
        checks=list(checks or []),
        reasons=[str(reason)[:200] for reason in (reasons or [])])


def _bounds_of(artifact_ref: str, format_name: str) -> list[float]:
    """Re-read coordinates for bounds. Small helper kept separate
    so the verdict path never depends on float aggregation."""
    try:
        data = read_artifact_bytes(artifact_ref)
    except MeshRefusedError:
        return []
    coords: list[float] = []
    try:
        if format_name == "stl-ascii":
            text = data.decode("ascii")
            facets, _, _, _ = _parse_stl_ascii(text)
            coords = [c for facet in facets for point in facet
                      for c in point]
        elif format_name == "stl-binary":
            facets, _, _, _ = _parse_stl_binary(data)
            coords = [c for facet in facets for point in facet
                      for c in point]
        elif format_name == "obj":
            text = data.decode("utf-8")
            _, facets, _, _, _ = _parse_obj(text)
            coords = [c for facet in facets for point in facet
                      for c in point]
    except (UnicodeDecodeError, struct.error, ValueError):
        return []
    if not coords or len(coords) % 3:
        return []
    xs = coords[0::3]
    ys = coords[1::3]
    zs = coords[2::3]
    return [round(min(xs), 3), round(min(ys), 3),
            round(min(zs), 3), round(max(xs), 3),
            round(max(ys), 3), round(max(zs), 3)]


def assess_printability(report: MeshReport, *,
                        build_volume_mm=None) -> PrintabilityAssessment:
    """Heuristic printability assessment over a mesh report.

    printable / not_printable / inconclusive with reasons. This is
    an assessment for planning — it never authorizes a print and
    carries no safe_to_print field by design.
    """
    volume = tuple(build_volume_mm or DEFAULT_BUILD_VOLUME_MM)
    checks = [f"volume={volume[0]}x{volume[1]}x{volume[2]}mm"]
    if report.verdict == "invalid":
        return PrintabilityAssessment(
            artifact_ref=report.artifact_ref, verdict="not_printable",
            reasons=["mesh invalid: "
                     + "; ".join(report.reasons[:5])],
            checks=checks + ["mesh-valid=no"])
    if report.verdict != "valid":
        return PrintabilityAssessment(
            artifact_ref=report.artifact_ref,
            verdict="inconclusive",
            reasons=["mesh inconclusive: "
                     + "; ".join(report.reasons[:5])],
            checks=checks + ["mesh-valid=unknown"])
    checks.append("mesh-valid=yes")
    reasons: list[str] = []
    if report.bounds_mm and len(report.bounds_mm) == 6:
        sizes = [report.bounds_mm[3] - report.bounds_mm[0],
                 report.bounds_mm[4] - report.bounds_mm[1],
                 report.bounds_mm[5] - report.bounds_mm[2]]
        checks.append(f"size={'x'.join(f'{v:.1f}' for v in sizes)}mm")
        for size, limit, axis in zip(sizes, volume, "xyz"):
            if size > limit:
                reasons.append(
                    f"{axis}-size {size:.1f}mm exceeds build "
                    f"volume {limit:.1f}mm")
    else:
        reasons.append("no measurable bounds")
    if report.faces <= 0:
        reasons.append("no faces")
    if reasons:
        return PrintabilityAssessment(
            artifact_ref=report.artifact_ref,
            verdict="not_printable", reasons=reasons, checks=checks)
    return PrintabilityAssessment(
        artifact_ref=report.artifact_ref, verdict="printable",
        reasons=["within caps, finite, fits build volume; "
                 "still needs human review and physical approval"],
        checks=checks)


def file_payload_for_mesh(report: MeshReport, data_sha256: str,
                          size_bytes: int, name: str) -> dict:
    """Inert INVENTory File-create payload for a validated mesh.
    Returned, never sent: registration runs through BIG #5 approval."""
    if report.verdict == "invalid":
        raise MeshRefusedError(
            "Invalid meshes never become File proposals")
    if not isinstance(name, str) or not name.strip():
        raise MeshRefusedError("File name must be non-empty text")
    return {
        "name": name.strip()[:200],
        "file_kind": "mesh",
        "mime_type": ("model/stl" if report.format.startswith("stl")
                      else "model/obj"),
        "sha256": data_sha256,
        "size_bytes": size_bytes,
        "description": (f"3D mesh {report.artifact_ref}: "
                        f"{report.verdict}, {report.faces} faces"),
        "status": "available",
        "metadata": {"artifact_ref": report.artifact_ref,
                     "format": report.format,
                     "validation": report.verdict,
                     "faces": report.faces,
                     "bounds_mm": report.bounds_mm},
    }


#: Preview/transform bounds: never a full-mesh dump by default.
PREVIEW_MAX_TRIS = 5000

VALID_TRANSFORM_OPS = frozenset({"rotate", "translate", "scale"})


def mesh_facets(artifact_ref: str, max_tris: int = PREVIEW_MAX_TRIS
                ) -> tuple[list, str, int, bool]:
    """Bounded facet read for preview/transform. Returns
    (facets, format, total, truncated). Validation state does
    not matter here — preview shows bytes, verdicts stay with
    validate_mesh."""
    try:
        count = max(1, min(int(max_tris or PREVIEW_MAX_TRIS),
                           PREVIEW_MAX_TRIS))
    except (TypeError, ValueError):
        raise MeshRefusedError("max_tris must be an integer")
    data = read_artifact_bytes(artifact_ref)
    lowered = artifact_ref.lower()
    if lowered.endswith(".stl"):
        text = None
        try:
            text = data.decode("ascii")
        except UnicodeDecodeError:
            text = None
        if text is not None and text.lstrip().lower().startswith(
                "solid"):
            facets, _, _, _ = _parse_stl_ascii(text)
            format_name = "stl-ascii"
        else:
            facets, _, _, _ = _parse_stl_binary(data)
            format_name = "stl-binary"
    elif lowered.endswith(".obj"):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise MeshRefusedError(
                "OBJ preview needs UTF-8 text")
        _, facets, _, _, _ = _parse_obj(text)
        format_name = "obj"
    else:  # pragma: no cover - guarded by check_artifact_ref
        raise MeshRefusedError("Unsupported mesh suffix")
    total = len(facets)
    return facets[:count], format_name, total, total > count


def check_transform(op: str, params) -> dict:
    """Validate one mesh transform. Pure math only: rotate
    (axis + degrees), translate (dx/dy/dz), scale (factor).
    No scripting, no code, no file access."""
    if op not in VALID_TRANSFORM_OPS:
        raise MeshRefusedError(
            f"Unknown transform '{op}'; expected one of "
            f"{sorted(VALID_TRANSFORM_OPS)}")
    if not isinstance(params, dict):
        raise MeshRefusedError("transform params must be an object")
    if op == "rotate":
        axis = str(params.get("axis", ""))
        if axis not in ("x", "y", "z"):
            raise MeshRefusedError(
                "rotate needs axis x, y or z")
        try:
            degrees = float(params.get("degrees", 0.0))
        except (TypeError, ValueError):
            raise MeshRefusedError("degrees must be a number")
        if not math.isfinite(degrees) or abs(degrees) > 360.0:
            raise MeshRefusedError("degrees must be -360..360")
        unknown = set(params) - {"axis", "degrees"}
        if unknown:
            raise MeshRefusedError(
                f"rotate carries unexpected params: "
                f"{sorted(unknown)}")
        return {"axis": axis, "degrees": degrees}
    if op == "translate":
        deltas = {}
        for key in ("dx", "dy", "dz"):
            try:
                value = float(params.get(key, 0.0))
            except (TypeError, ValueError):
                raise MeshRefusedError(f"{key} must be a number")
            if not math.isfinite(value) or abs(value) > 1000.0:
                raise MeshRefusedError(
                    f"{key} must be -1000..1000")
            deltas[key] = value
        unknown = set(params) - {"dx", "dy", "dz"}
        if unknown:
            raise MeshRefusedError(
                f"translate carries unexpected params: "
                f"{sorted(unknown)}")
        return deltas
    try:
        factor = float(params.get("factor", 1.0))
    except (TypeError, ValueError):
        raise MeshRefusedError("factor must be a number")
    if not math.isfinite(factor) or not 0.01 <= factor <= 100.0:
        raise MeshRefusedError("factor must be 0.01..100")
    unknown = set(params) - {"factor"}
    if unknown:
        raise MeshRefusedError(
            f"scale carries unexpected params: {sorted(unknown)}")
    return {"factor": factor}


def transform_facets(facets: list, op: str, params: dict) -> list:
    """Apply one validated transform to facet triples. Returns
    new triples; input untouched."""
    import math as _math
    out = []
    if op == "rotate":
        axis, degrees = params["axis"], params["degrees"]
        radians = _math.radians(degrees)
        cos_a, sin_a = _math.cos(radians), _math.sin(radians)

        def turn(point):
            x, y, z = (float(point[0]), float(point[1]),
                       float(point[2]))
            if axis == "x":
                return (x, y * cos_a - z * sin_a,
                        y * sin_a + z * cos_a)
            if axis == "y":
                return (x * cos_a + z * sin_a, y,
                        -x * sin_a + z * cos_a)
            return (x * cos_a - y * sin_a,
                    x * sin_a + y * cos_a, z)
    elif op == "translate":
        dx, dy, dz = (params["dx"], params["dy"], params["dz"])

        def turn(point):
            return (float(point[0]) + dx, float(point[1]) + dy,
                    float(point[2]) + dz)
    else:
        factor = params["factor"]

        def turn(point):
            return (float(point[0]) * factor,
                    float(point[1]) * factor,
                    float(point[2]) * factor)
    for facet in facets or []:
        out.append(tuple(turn(point) for point in facet))
    return out


def write_derived_mesh(source_ref: str, op: str,
                       facets: list) -> tuple[str, str, int]:
    """Persist transformed facets as a local derived STL file.
    Returns (artifact_ref, sha256, size). The file is a working
    artifact: INVENTory registration still needs the BIG #5
    proposal flow (file_payload_for_mesh)."""
    import hashlib as _hashlib
    lines = [f"solid mycelium_derived_{op}"]
    for facet in facets:
        lines.append("  facet normal 0 0 0")
        lines.append("    outer loop")
        for point in facet:
            lines.append(
                f"      vertex {float(point[0]):.3f} "
                f"{float(point[1]):.3f} {float(point[2]):.3f}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append(f"endsolid mycelium_derived_{op}")
    data = ("\n".join(lines) + "\n").encode("ascii")
    digest = _hashlib.sha256(data).hexdigest()
    reference = check_artifact_ref(f"fab-derived-{digest[:12]}.stl")
    prune_fabrication()
    path = os.path.abspath(os.path.join(
        os.path.abspath(fabrication_dir()), reference))
    with open(path, "wb") as handle:
        handle.write(data)
    return reference, digest, len(data)
