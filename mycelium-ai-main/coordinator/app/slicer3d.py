"""Slicer abstraction + G-code safety for Mycelium (BIG #7).

A slicer turns a validated mesh into a G-code artifact. G-code is
potentially physically dangerous, so it is a separate artifact
with its own validation and safety assessment — and a safety
assessment is never permission to execute.

Rules (tested, all fail-closed):

- ``SlicerProvider`` interface; only ``TestSlicer``
  (deterministic synthetic G-code, always ``test_generated``)
  and ``UnavailableSlicer`` (explicit reason) exist. No real
  slicer ships: producing production G-code needs a reviewed
  local slicer runtime (documented in requirements). No
  arbitrary slicer command execution exists anywhere.
- Slicer profiles come from a closed allow-list
  (``SLICER_PROFILES``); unknown profiles, printers and
  materials refuse before anything runs.
- G-code validation: allow-listed suffix, capped size/lines/
  line length, command allow-list per line, temperature bounds,
  no includes/references, no path traversal. Unknown commands
  make the file ``inconclusive`` at best, dangerous content
  makes it ``unsafe``.
- ``GCodeSafetyAssessment`` verdicts: safe / unsafe /
  inconclusive. There is deliberately no ``safe_to_execute``
  field: safety assessment != permission to execute.
"""

import hashlib
import math
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import Provenance
from .mesh3d import (
    MeshRefusedError,
    artifact_path,
    check_artifact_ref,
    read_artifact_bytes,
)

#: Closed slicer profiles. Identity only — no slicer runs here.
SLICER_PROFILES = {
    "draft-pla": {"layer_mm": 0.28, "infill": 15,
                  "material": "PLA", "nozzle_c": 210,
                  "bed_c": 60},
    "fine-pla": {"layer_mm": 0.12, "infill": 20,
                 "material": "PLA", "nozzle_c": 210,
                 "bed_c": 60},
    "draft-petg": {"layer_mm": 0.28, "infill": 15,
                   "material": "PETG", "nozzle_c": 240,
                   "bed_c": 80},
}

#: G-code dialects this layer emits/reads. Nothing else parses.
GCODE_SUFFIXES = (".gcode",)

MAX_GCODE_BYTES = 50 * 1024 * 1024
MAX_GCODE_LINES = 2_000_000
MAX_LINE_CHARS = 1024

#: Motion/extrusion/heat commands a reviewed profile may emit.
#: Anything else is a finding (unsafe set below, else inconclusive).
ALLOWED_COMMANDS = frozenset({
    "G0", "G1", "G2", "G3", "G4", "G20", "G21", "G28", "G90", "G91",
    "G92", "M82", "M83", "M84", "M104", "M106", "M107", "M109",
    "M140", "M190", "M73", "M117", "M201", "M203", "M204", "M205",
    "M900", "T0",
})

#: Commands that are never acceptable in a Mycelium artifact.
UNSAFE_COMMANDS = frozenset({
    "M112",  # emergency stop inside a file hides intent
    "M226",  # filament-change pause hides operator intent
    "M530", "M531",  # filament handling outside profile control
})

MAX_NOZZLE_C = 300.0
MAX_BED_C = 120.0

TEST_ORIGIN_MARK = "test-origin: synthetic G-code, never for printers"


class SlicerRefusedError(ValueError):
    """Local validation refused; nothing was sliced or read."""


class SlicerUnavailable(RuntimeError):
    """No slicing path. Fail-closed, never fake G-code."""


class SlicerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mesh_ref: str = Field(min_length=1, max_length=200)
    profile: str = Field(min_length=1, max_length=40)
    printer_id: str = Field(min_length=3, max_length=80)
    material: str = Field(default="", max_length=40)


class SlicerResult(BaseModel):
    """Slicing output. An artifact with metadata — never a release."""

    model_config = ConfigDict(extra="forbid")

    gcode_ref: str = Field(min_length=1, max_length=200)
    sha256: str = Field(min_length=64, max_length=64,
                        pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    line_count: int = Field(ge=0)
    profile: str = Field(min_length=1, max_length=40)
    printer_id: str = Field(min_length=3, max_length=80)
    slicer: str = Field(min_length=1, max_length=80)
    test_generated: bool = False
    provenance: Provenance = Field(default_factory=Provenance)


class GCodeSafetyAssessment(BaseModel):
    """Safety verdict over one G-code artifact. safe / unsafe /
    inconclusive with findings. No safe_to_execute field by design."""

    model_config = ConfigDict(extra="forbid")

    gcode_ref: str = Field(min_length=1, max_length=200)
    verdict: str = Field(default="inconclusive", max_length=20)
    findings: list[str] = Field(default_factory=list, max_length=50)
    checks: list[str] = Field(default_factory=list, max_length=30)
    line_count: int = Field(default=0, ge=0)


def check_profile(profile: str) -> dict:
    if profile not in SLICER_PROFILES:
        raise SlicerRefusedError(
            f"Unknown slicer profile '{profile}'; expected one of "
            f"{sorted(SLICER_PROFILES)}")
    return dict(SLICER_PROFILES[profile])


def check_slicer_request(mesh_ref: str, profile: str,
                         printer_id: str) -> SlicerRequest:
    reference = check_artifact_ref(mesh_ref)
    if not reference.lower().endswith((".stl", ".obj")):
        raise SlicerRefusedError(
            "Slicing needs a mesh artifact (.stl/.obj)")
    settings = check_profile(profile)
    if not isinstance(printer_id, str) or not printer_id.strip():
        raise SlicerRefusedError("printer_id must be non-empty text")
    return SlicerRequest(
        mesh_ref=reference, profile=profile,
        printer_id=printer_id.strip()[:80],
        material=settings["material"])


class SlicerProvider:
    """Interface for slicers. Subclasses implement slice()."""

    name = "base"

    def slice(self, request: SlicerRequest) -> SlicerResult:
        raise NotImplementedError

    @classmethod
    def requirements(cls) -> str:
        return ("A production slicer needs a reviewed local runtime: "
                "pinned slicer binary, fixed argv allow-list, bounded "
                "profile set, stdout/file capture with caps, no network. "
                "None of this ships in BIG #7.")


def _store_gcode(filename: str, text: str) -> tuple[str, bytes]:
    reference = check_artifact_ref(filename)
    if not reference.lower().endswith(GCODE_SUFFIXES):
        raise SlicerRefusedError("G-code must be a .gcode file")
    data = text.encode("utf-8")
    if len(data) > MAX_GCODE_BYTES:
        raise SlicerRefusedError("G-code exceeds the size cap")
    path = artifact_path(reference)
    from .mesh3d import prune_fabrication
    prune_fabrication()
    with open(path, "wb") as handle:
        handle.write(data)
    return reference, data


class TestSlicer(SlicerProvider):
    """Deterministic TEST slicer. Emits a small synthetic G-code
    with an explicit never-for-printers header (test-only)."""

    name = "test-slicer"

    def slice(self, request: SlicerRequest) -> SlicerResult:
        from datetime import datetime, timezone
        if not isinstance(request, SlicerRequest):
            raise SlicerRefusedError("Slicing needs a SlicerRequest")
        settings = check_profile(request.profile)
        lines = [
            "; TEST GENERATED G-CODE - NEVER SEND TO A PRINTER",
            f"; profile {request.profile} material "
            f"{settings['material']}",
            f"; source {request.mesh_ref}",
            "G21 ; millimeter",
            "G90 ; absolute",
            "G28 ; home",
            f"M104 S{settings['nozzle_c']} ; nozzle",
            f"M140 S{settings['bed_c']} ; bed",
            "G1 Z0.28 F600 ; first layer",
            "G1 X10 Y10 E0.5 F1200 ; test extrusion",
            "G1 X30 Y10 E1.0 ; test line",
            "M104 S0 ; nozzle off",
            "M140 S0 ; bed off",
            "M84 ; motors off",
        ]
        text = "\n".join(lines) + "\n"
        reference, data = _store_gcode("fab-test-print.gcode", text)
        return SlicerResult(
            gcode_ref=reference,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            line_count=len(lines), profile=request.profile,
            printer_id=request.printer_id, slicer=self.name,
            test_generated=True,
            provenance=Provenance(
                source_type="ai-generated",
                creator_id="fabrication:test-slicer",
                human_verified=False,
                notes=TEST_ORIGIN_MARK))


class UnavailableSlicer(SlicerProvider):
    """Explicit unavailable slicer. Complete interface, zero output."""

    name = "unavailable"

    def __init__(self, reason: str = "no slicer runtime available"):
        self.reason = reason

    def slice(self, request: SlicerRequest) -> SlicerResult:
        raise SlicerUnavailable(
            f"{self.reason}; no fake G-code, no cloud slicing, "
            "no runtime download")


def get_slicer(name: str | None = None, **kwargs) -> SlicerProvider:
    """Resolve a slicer by name. Unknown names fail closed."""
    resolved = (name or "unavailable").strip().lower()
    if resolved == "test-slicer":
        return TestSlicer()
    if resolved == "unavailable":
        return UnavailableSlicer(**kwargs)
    raise SlicerRefusedError(f"Unknown slicer '{name}'")


# -- G-code validation + safety --------------------------------------------

def _command_of(line: str) -> str:
    head = line.split(";")[0].strip().split()
    if not head:
        return ""
    return head[0].strip().upper()


def _temperatures(line: str) -> list[tuple[str, float]]:
    found: list[tuple[str, float]] = []
    import re
    for key in ("S",):
        for match in re.finditer(r"S(-?\d+(?:\.\d+)?)", line):
            try:
                found.append((key, float(match.group(1))))
            except ValueError:
                continue
    return found


def validate_gcode(gcode_ref: str) -> GCodeSafetyAssessment:
    """Validate one G-code artifact. safe requires: allow-listed
    commands only, temperatures within bounds, bounded size/lines,
    no includes, no traversal. Unknown commands ->
    inconclusive; dangerous content -> unsafe."""
    try:
        reference = check_artifact_ref(gcode_ref)
    except MeshRefusedError as error:
        raise SlicerRefusedError(str(error)) from error
    if not reference.lower().endswith(GCODE_SUFFIXES):
        raise SlicerRefusedError("G-code validation needs .gcode")
    try:
        data = read_artifact_bytes(reference)
    except MeshRefusedError as error:
        raise SlicerRefusedError(str(error)) from error
    if len(data) > MAX_GCODE_BYTES:
        return _assessment(reference, "unsafe",
                           ["exceeds size cap"], ["size"])
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return _assessment(reference, "inconclusive",
                           ["not decodable as UTF-8 text"],
                           ["decoding"])
    lines = text.splitlines()
    checks = [f"lines={len(lines)}"]
    if len(lines) > MAX_GCODE_LINES:
        return _assessment(reference, "unsafe",
                           ["line count exceeds cap"], checks)
    findings: list[str] = []
    inconclusive: list[str] = []
    for number, line in enumerate(lines, start=1):
        if len(line) > MAX_LINE_CHARS:
            return _assessment(reference, "unsafe",
                               [f"line {number} exceeds cap"], checks)
        command = _command_of(line)
        if not command:
            continue
        if command in UNSAFE_COMMANDS:
            findings.append(f"line {number}: forbidden {command}")
            continue
        if command not in ALLOWED_COMMANDS:
            inconclusive.append(
                f"line {number}: unknown command {command}")
            continue
        if command in ("M104", "M109"):
            for _, temp in _temperatures(line):
                if not math.isfinite(temp):
                    findings.append(
                        f"line {number}: non-finite temperature")
                elif temp > MAX_NOZZLE_C:
                    findings.append(
                        f"line {number}: nozzle {temp}C exceeds "
                        f"{MAX_NOZZLE_C}C")
        if command in ("M140", "M190"):
            for _, temp in _temperatures(line):
                if not math.isfinite(temp):
                    findings.append(
                        f"line {number}: non-finite temperature")
                elif temp > MAX_BED_C:
                    findings.append(
                        f"line {number}: bed {temp}C exceeds "
                        f"{MAX_BED_C}C")
        if "M98" in line.upper() or "M23" in line.upper():
            findings.append(
                f"line {number}: file/subroutine reference refused")
    if findings:
        return _assessment(reference, "unsafe", findings[:50],
                           checks + ["commands", "temperatures"])
    if inconclusive:
        return _assessment(reference, "inconclusive",
                           inconclusive[:50],
                           checks + ["commands"])
    if not any(_command_of(line) in ("G0", "G1")
               for line in lines):
        return _assessment(reference, "inconclusive",
                           ["no motion commands"], checks)
    return _assessment(reference, "safe",
                       ["allow-listed commands only; temperatures "
                        "within bounds; still needs human review "
                        "and physical approval"],
                       checks + ["commands", "temperatures"])


def _assessment(gcode_ref: str, verdict: str, findings,
                checks) -> GCodeSafetyAssessment:
    try:
        data = read_artifact_bytes(gcode_ref)
        count = len(data.decode("utf-8", errors="ignore").splitlines())
    except SlicerRefusedError:
        count = 0
    return GCodeSafetyAssessment(
        gcode_ref=gcode_ref, verdict=verdict,
        findings=[str(item)[:200] for item in findings],
        checks=list(checks),
        line_count=count)


def file_payload_for_gcode(assessment: GCodeSafetyAssessment,
                           data_sha256: str, size_bytes: int,
                           name: str) -> dict:
    """Inert INVENTory File-create payload for a G-code artifact.
    Unsafe G-code never becomes a File proposal."""
    if assessment.verdict == "unsafe":
        raise SlicerRefusedError(
            "Unsafe G-code never becomes a File proposal")
    if not isinstance(name, str) or not name.strip():
        raise SlicerRefusedError("File name must be non-empty text")
    return {
        "name": name.strip()[:200],
        "file_kind": "gcode",
        "mime_type": "text/x-gcode",
        "sha256": data_sha256,
        "size_bytes": size_bytes,
        "description": (f"G-code {assessment.gcode_ref}: "
                        f"{assessment.verdict}, "
                        f"{assessment.line_count} lines"),
        "status": "available",
        "metadata": {"artifact_ref": assessment.gcode_ref,
                     "safety": assessment.verdict,
                     "lines": assessment.line_count},
    }
