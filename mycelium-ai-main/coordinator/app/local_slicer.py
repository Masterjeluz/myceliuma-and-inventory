"""Local subprocess slicer (M2/BIG57): real G-code, no mocks.

Runs a pinned local slicer binary headlessly (fixed argv
allow-list, shell=False, timeout, output caps, no network) and
returns the real bytes + sha256. Bambu Studio CLI is supported in
design but UNPROVEN on this build (all headless slice attempts
fail); prusa-slicer-console is the proven default.

NOTE on test_fab_security.py: the no-shell tripwire scans
mesh3d/slicer3d/printer3d/fab_flow only. Subprocess use lives
solely here (reviewed local runtime, exactly what
SlicerProvider.requirements() demands); the fab core stays
shell-free. This module never prints, never uploads, never
auto-executes.
"""

from __future__ import annotations

import hashlib as _hashlib
import os as _os
import shutil as _shutil
import subprocess as _subprocess

BAMBU_BIN_ENV_VAR = "BAMBU_STUDIO_BIN"
DEFAULT_BAMBU_BIN = (
    "C:/Program Files/Bambu Studio/bambu-studio.exe")
PRUSA_CONSOLE_ENV_VAR = "PRUSASLICER_CONSOLE_BIN"
DEFAULT_PRUSA_CONSOLE_BIN = (
    "E:/Mycelium/tools/prusa/PrusaSlicer-2.9.6/"
    "prusa-slicer-console.exe")

SLICE_TIMEOUT_SECONDS = 600.0
SMOKE_TIMEOUT_SECONDS = 20.0
MAX_STDOUT_BYTES = 1 << 20

#: Closed override allow-list for prusa-console (CLI keys only).
PRUSA_OVERRIDE_KEYS = frozenset({
    "layer-height", "fill-density", "support-material",
    "support-material-threshold", "temperature",
    "first-layer-temperature", "bed-temperature",
    "first-layer-bed-temperature", "nozzle-diameter",
    "filament-diameter", "perimeters", "top-layers",
    "bottom-layers", "brim", "bed-shape",
})

ENGINES = ("prusa", "bambu")


class LocalSlicerError(ValueError):
    """Local slicing refused or failed; nothing was produced."""


class LocalSlicerUnavailable(RuntimeError):
    """No working local slicer runtime."""


def resolve_console_binary(engine: str) -> str:
    """Pinned binary path for one engine. No PATH guessing beyond
    an explicit env override or the reviewed default."""
    cleaned = str(engine or "").strip().lower()
    if cleaned == "prusa":
        override = str(_os.environ.get(
            PRUSA_CONSOLE_ENV_VAR, "") or "").strip()
        binary = override or DEFAULT_PRUSA_CONSOLE_BIN
    elif cleaned == "bambu":
        override = str(_os.environ.get(
            BAMBU_BIN_ENV_VAR, "") or "").strip()
        binary = override or DEFAULT_BAMBU_BIN
    else:
        raise LocalSlicerError(
            f"unknown slicer engine '{engine}'; "
            f"expected one of {list(ENGINES)}")
    if not binary or not _os.path.isfile(binary):
        raise LocalSlicerUnavailable(
            f"{cleaned} binary not found at {binary[:120]}; "
            f"set the matching env var or install the slicer")
    return binary


def _check_overrides(overrides: dict) -> dict:
    if not isinstance(overrides, dict):
        raise LocalSlicerError("overrides must be an object")
    cleaned: dict[str, str] = {}
    for key, value in overrides.items():
        name = str(key or "").strip()
        if name not in PRUSA_OVERRIDE_KEYS:
            raise LocalSlicerError(
                f"override '{name[:40]}' not in the allow-list; "
                f"expected one of {sorted(PRUSA_OVERRIDE_KEYS)}")
        text = str(value if value is not None else "").strip()
        if not text or len(text) > 40:
            raise LocalSlicerError(
                f"override '{name}' must be 1..40 characters")
        if any(char in text for char in ";|&$`()<>\\\"'"):
            raise LocalSlicerError(
                f"override '{name}' carries shell characters; "
                f"refusing")
        cleaned[name] = text
    if len(cleaned) > 12:
        raise LocalSlicerError("at most 12 overrides")
    return cleaned


def _check_output_path(path: str, out_dir: str) -> str:
    name = str(path or "").strip().replace("\\", "/").split("/")[-1]
    if not name.lower().endswith(".gcode") or len(name) > 120:
        raise LocalSlicerError(
            "output must be a .gcode filename (<=120 chars)")
    if not name or name.startswith("."):
        raise LocalSlicerError("output filename invalid")
    root = _os.path.abspath(out_dir)
    full = _os.path.abspath(_os.path.join(root, name))
    if full != root and not full.startswith(root + _os.sep):
        raise LocalSlicerError("output escapes the output dir")
    return full


def slice_with_prusa(*, stl_path: str, output_path: str,
                     profile: dict, overrides: dict | None = None,
                     timeout: float = SLICE_TIMEOUT_SECONDS,
                     extra_printer_keys: dict | None = None) -> dict:
    """Slice one STL with prusa-slicer-console. Real bytes out.

    ``profile`` is the coordinator profile dict (material, temps,
    layer, infill + M2 supports/speed keys); unknown keys are
    ignored, never passed. Returns paths + sha + argv for the
    record. Raises LocalSlicerError/Unavailable; writes nothing
    on failure except the (possibly partial) output file, which
    the caller owns.
    """
    from .slicer3d import MAX_GCODE_BYTES
    binary = resolve_console_binary("prusa")
    if not _os.path.isfile(stl_path):
        raise LocalSlicerError("model file not found; refusing")
    out_dir = _os.path.dirname(
        _os.path.abspath(output_path)) or _os.getcwd()
    _os.makedirs(out_dir, exist_ok=True)
    out_file = _check_output_path(output_path, out_dir)
    clean_over = _check_overrides(overrides or {})
    settings = dict(profile or {})
    argv = [binary, "--export-gcode", "--output", out_file]
    material = str(settings.get("material", "") or "").strip()
    layer = str(settings.get("layer_mm", "") or "").strip()
    infill = str(settings.get("infill", "") or "").strip()
    nozzle_c = str(settings.get("nozzle_c", "") or "").strip()
    bed_c = str(settings.get("bed_c", "") or "").strip()
    if layer:
        argv += ["--layer-height", layer]
    if infill:
        dense = str(infill).strip()
        if not dense.endswith("%"):
            dense += "%"
        argv += ["--fill-density", dense]
    if nozzle_c:
        argv += ["--temperature", nozzle_c,
                 "--first-layer-temperature", nozzle_c]
    if bed_c:
        argv += ["--bed-temperature", bed_c,
                 "--first-layer-bed-temperature", bed_c]
    supports = settings.get("supports", False)
    if supports in (True, "true", "1", 1):
        argv += ["--support-material"]
        threshold = str(settings.get(
            "support_threshold_deg", "") or "").strip()
        if threshold:
            argv += ["--support-material-threshold", threshold]
    for key in sorted(clean_over):
        argv += [f"--{key}", clean_over[key]]
    for key, value in dict(extra_printer_keys or {}).items():
        name = str(key or "").strip()
        if name not in PRUSA_OVERRIDE_KEYS:
            raise LocalSlicerError(
                f"printer key '{name[:40]}' not in the allow-list")
        argv += [f"--{name}", str(value)[:40]]
    argv.append(stl_path)
    try:
        budget = min(float(timeout or SLICE_TIMEOUT_SECONDS),
                     SLICE_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        budget = SLICE_TIMEOUT_SECONDS
    if budget <= 0:
        budget = SLICE_TIMEOUT_SECONDS
    try:
        proc = _subprocess.run(
            argv, shell=False, capture_output=True, timeout=budget,
            cwd=out_dir)
    except _subprocess.TimeoutExpired as error:
        raise LocalSlicerError(
            f"slicer timed out after {budget:g}s; killed") from error
    except OSError as error:
        raise LocalSlicerUnavailable(
            f"slicer could not start ({error})") from error
    if proc.returncode != 0:
        tail = ((proc.stderr or b"")[-500:] +
                (proc.stdout or b"")[-500:]).decode(
                    "utf-8", "replace")
        raise LocalSlicerError(
            f"slicer refused (exit {proc.returncode}): "
            f"{tail[:300]}")
    if not _os.path.isfile(out_file):
        raise LocalSlicerError(
            "slicer exited 0 but wrote no G-code; refusing")
    size = _os.path.getsize(out_file)
    if size <= 0 or size > MAX_GCODE_BYTES:
        raise LocalSlicerError(
            f"G-code size {size} out of bounds; refusing")
    digest = _hashlib.sha256()
    lines = 0
    with open(out_file, "rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
            lines += chunk.count(b"\n")
    return {"gcode_path": out_file, "sha256": digest.hexdigest(),
            "size_bytes": size, "line_count": lines,
            "engine": "prusa",
            "argv": [argv[0]] + argv[1:-1] + ["<model>"]}


def canonical_gcode_name(mesh_filename: str, profile: str,
                         sha8: str) -> str:
    """Deterministic canonical G-code filename. Single source of
    truth used by both the slicer and the job record."""
    stem = "".join(
        char if char.isalnum() or char in ("-", "_") else "_"
        for char in str(mesh_filename or "").rsplit(".", 1)[0]
    )[:60] or "model"
    clean_profile = "".join(
        char if char.isalnum() or char in ("-", "_") else "_"
        for char in str(profile or ""))[:40] or "profile"
    clean_sha = "".join(
        char for char in str(sha8 or "").lower()
        if char in "0123456789abcdef")[:8] or "00000000"
    return f"{stem}-{clean_profile}-{clean_sha}.gcode"


def canonical_gcode_dir() -> str:
    """E:\\Mycelium\\gcode (created on use, never on probe)."""
    from .forge import library_root
    path = _os.path.join(library_root(), "gcode")
    _os.makedirs(path, exist_ok=True)
    return path


def run_help_smoke(binary: str, timeout: float = 20.0,
                  ) -> tuple[int | None, str]:
    """Run `<binary> --help` with a timeout; return (code, output).

    shell=False, fixed argv, capped output. None code means the
    process never answered (timeout/spawn failure). Shared by the
    forge readiness probes so console handling lives in exactly
    one reviewed place.
    """
    try:
        proc = _subprocess.run(
            [binary, "--help"], shell=False, capture_output=True,
            timeout=timeout)
    except Exception:
        return None, ""
    try:
        text = (proc.stdout or b"").decode("utf-8", "replace")
        text += (proc.stderr or b"").decode("utf-8", "replace")
    except Exception:
        text = ""
    return proc.returncode, text[:2000]


def canonical_gcode_dir() -> str:
    """E:\\Mycelium\\gcode (created on use, never on probe)."""
    from .forge import library_root
    path = _os.path.join(library_root(), "gcode")
    _os.makedirs(path, exist_ok=True)
    return path


#: 1x1 transparent PNG placeholder (68 bytes). Headless slicing
#: renders no thumbnails; references are required, pixels are not.
PLACEHOLDER_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000"
    "001f15c4890000000d49444154789c626001000000ffff030000060005"
    "1b5f090000000049454e44ae426082")

#: A1 mini model code (Bambu machine profiles). Never hard-fail on
#: unknown codes elsewhere; here it labels OUR printer honestly.
A1MINI_MODEL_ID = "N1"
A1MINI_NOZZLE_MM = "0.4"


def _slot_count_for(trays: int) -> int:
    try:
        count = max(1, min(int(trays or 0), 8))
    except (TypeError, ValueError):
        count = 1
    return count + 1 if count < 8 else count


def _pad_slots(values: list, count: int, fallback: str = "1") -> list:
    items = [str(value) for value in (values or [])]
    while len(items) < count:
        items.append(items[-1] if items else fallback)
    return items[:count]


def build_plate_3mf(gcode: bytes, *, profile_name: str,
                    material: str, color_hex: str = "#FFFFFF",
                    weight_g: float = 0.0, prediction_s: int = 0,
                    support_used: bool = False,
                    filament_type: str = "",
                    nozzle_diameter: str = A1MINI_NOZZLE_MM,
                    printer_model_id: str = A1MINI_MODEL_ID,
                    bed_type: str = "textured_plate",
                    plate_index: int = 1,
                    slot_count: int = 5,
                    base_settings: dict | None = None,
                    ) -> bytes:
    """Build a plate-sliced .gcode.3mf from real G-code (M4.2).

    Pure function: no I/O, no network. Layout follows the
    hardware-validated plate-sliced contract (empty 3dmodel,
    Metadata/plate_N.gcode + uppercase .md5, ordered
    model_settings/slice_info XML, full project_settings JSON).
    Values come from the caller (slicer footer + profile + spool);
    unknown filament preset degrades to generic honestly.
    Raises LocalSlicerError on empty G-code.
    """
    import hashlib as _hashlib
    import io as _io
    import json as _json
    import zipfile as _zip
    if not gcode:
        raise LocalSlicerError("no G-code bytes; refusing")
    slots = _slot_count_for(slot_count)
    gcode_name = f"Metadata/plate_{plate_index}.gcode"
    digest = _hashlib.md5(gcode).hexdigest().upper()
    filament_label = str(filament_type or material or "PLA")[:40]
    try:
        weight = round(float(weight_g or 0.0), 2)
    except (TypeError, ValueError):
        weight = 0.0
    try:
        prediction = max(0, int(prediction_s or 0))
    except (TypeError, ValueError):
        prediction = 0
    maps = " ".join(["1"] * slots)
    zeros = " ".join(["0"] * slots)
    model_settings = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n'
        '  <plate>\n'
        '    <metadata key="plater_id" value="1"/>\n'
        '    <metadata key="plater_name" value=""/>\n'
        '    <metadata key="locked" value="false"/>\n'
        '    <metadata key="filament_map_mode" value="Auto For Flush"/>\n'
        f'    <metadata key="filament_maps" value="{maps}"/>\n'
        f'    <metadata key="filament_volume_maps" value="{zeros}"/>\n'
        f'    <metadata key="gcode_file" value="{gcode_name}"/>\n'
        '    <metadata key="thumbnail_file" '
        'value="Metadata/plate_1.png"/>\n'
        '    <metadata key="thumbnail_no_light_file" '
        'value="Metadata/plate_no_light_1.png"/>\n'
        '    <metadata key="top_file" value="Metadata/top_1.png"/>\n'
        '    <metadata key="pick_file" value="Metadata/pick_1.png"/>\n'
        '    <metadata key="pattern_bbox_file" '
        'value="Metadata/plate_1.json"/>\n'
        '  </plate>\n</config>\n')
    color = str(color_hex or "#FFFFFF")[:7]
    if not color.startswith("#"):
        color = "#FFFFFF"
    slice_info = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n'
        '  <header>\n'
        '    <header_item key="X-BBL-Client-Type" value="slicer"/>\n'
        '    <header_item key="X-BBL-Client-Version" '
        'value="02.05.00.66"/>\n'
        '  </header>\n'
        '  <plate>\n'
        '    <metadata key="index" value="1"/>\n'
        '    <metadata key="extruder_type" value="0"/>\n'
        '    <metadata key="nozzle_volume_type" value="0"/>\n'
        f'    <metadata key="printer_model_id" '
        f'value="{printer_model_id}"/>\n'
        f'    <metadata key="nozzle_diameters" value="{nozzle_diameter}"/>\n'
        '    <metadata key="timelapse_type" value="0"/>\n'
        f'    <metadata key="prediction" value="{prediction}"/>\n'
        f'    <metadata key="weight" value="{weight}"/>\n'
        '    <metadata key="outside" value="false"/>\n'
        f'    <metadata key="support_used" '
        f'value="{str(bool(support_used)).lower()}"/>\n'
        '    <metadata key="label_object_enabled" value="true"/>\n'
        f'    <metadata key="filament_maps" value="{maps}"/>\n'
        f'    <metadata key="limit_filament_maps" value="{zeros}"/>\n'
        f'    <filament id="1" tray_info_idx="GFL99" '
        f'type="{filament_label}" color="{color}" '
        f'used_m="0" used_g="{weight}" used_for_object="true" '
        f'used_for_support="false" group_id="0" '
        f'nozzle_diameter="{nozzle_diameter}" volume_type="Standard"/>\n'
        '  </plate>\n</config>\n')
    project_settings = dict(base_settings or {})
    project_settings.setdefault("printer_model_id",
                                printer_model_id)
    project_settings.setdefault("nozzle_diameter", nozzle_diameter)
    project_settings.setdefault("bed_type", bed_type)
    project_settings.setdefault(
        "slicer", "mycelium-prusa-console-plate")
    project_settings.setdefault("profile", profile_name)
    project_settings.setdefault("material", material)
    plate_json = _json.dumps({"bed_type": bed_type},
                             separators=(",", ":"))
    model_3d = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/'
        '2015/02"><resources/><build/></model>')
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/'
        '2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.'
        'openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.'
        'ms-package.3dmanufacturing-3dmodel+xml"/>'
        '<Default Extension="config" ContentType="text/xml"/>'
        '<Default Extension="gcode" ContentType="text/plain"/>'
        '<Default Extension="md5" ContentType="text/plain"/>'
        '<Default Extension="json" ContentType="application/json"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '</Types>')
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/'
        'package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/'
        '01/3dmodel"/></Relationships>')
    model_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/'
        'package/2006/relationships">'
        '<Relationship Target="plate_1.gcode" Id="rel-gcode" '
        'Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/oleObject"/></Relationships>')
    buf = _io.BytesIO()
    with _zip.ZipFile(buf, "w", _zip.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("3D/3dmodel.model", model_3d)
        archive.writestr(gcode_name, gcode)
        archive.writestr(gcode_name + ".md5", digest)
        archive.writestr("Metadata/model_settings.config",
                         model_settings)
        archive.writestr("Metadata/_rels/model_settings.config.rels",
                         model_rels)
        archive.writestr("Metadata/slice_info.config", slice_info)
        archive.writestr("Metadata/project_settings.config",
                         _json.dumps(project_settings, indent=1,
                                     sort_keys=True))
        archive.writestr("Metadata/plate_1.json", plate_json)
        for thumb in ("Metadata/plate_1.png",
                      "Metadata/plate_1_small.png",
                      "Metadata/plate_no_light_1.png",
                      "Metadata/top_1.png",
                      "Metadata/pick_1.png"):
            archive.writestr(thumb, PLACEHOLDER_PNG)
    return buf.getvalue()


def smoke_console(engine: str = "prusa") -> dict:
    """Fast --help proof that a console CLI answers. Read-only."""
    cleaned = str(engine or "").strip().lower()
    if cleaned not in ENGINES:
        return {"engine": cleaned, "state": "UNKNOWN",
                "reason": f"expected one of {list(ENGINES)}"}
    try:
        binary = resolve_console_binary(cleaned)
    except (LocalSlicerError, LocalSlicerUnavailable) as error:
        return {"engine": cleaned, "state": "ABSENT",
                "reason": str(error)[:160]}
    code, text = run_help_smoke(binary,
                                timeout=SMOKE_TIMEOUT_SECONDS)
    lowered = text.lower()
    if code == 0 and ("export-gcode" in lowered
                      or "--slice" in lowered):
        return {"engine": cleaned, "state": "CLI_OK",
                "reason": "console answers with slice flags"}
    if code == 0:
        return {"engine": cleaned, "state": "PRESENT_CLI_UNPROVEN",
                "reason": "--help shows no slice flags"}
    if code is None:
        return {"engine": cleaned, "state": "CLI_FAILED",
                "reason": "no answer (timeout/spawn failure)"}
    return {"engine": cleaned, "state": "CLI_FAILED",
            "reason": f"exit {code}"}


#: Default bed geometry for the Bambu Lab A1 Mini (mm). Used only
#: when no explicit bed-shape override is given; recorded in the
#: result so the provenance never hides it.
A1MINI_BED_SHAPE = "0x0,180x0,180x180,0x180"

#: Bambu Studio CLI is UNPROVEN on this build (8 headless attempts:
#: input files never accepted, silent exit -2, segfault without
#: settings). The argv mapping below is pure and tested, but
#: execution stays refused until a manual proof flips
#: BAMBU_CLI_PROVEN=1. Evidence over optimism.
BAMBU_PROOF_ENV_VAR = "BAMBU_CLI_PROVEN"


def bambu_slice_argv(*, binary: str, stl_path: str,
                     machine_json: str, process_json: str,
                     filament_json: str, output_3mf: str,
                     overrides: dict | None = None) -> list[str]:
    """Pure argv builder for Bambu Studio headless slicing.

    No execution here — mapping only, so the design survives the
    day the CLI proves itself. Tested without running anything.
    """
    for label, value in (("model", stl_path),
                         ("machine profile", machine_json),
                         ("process profile", process_json),
                         ("filament profile", filament_json)):
        text = str(value or "").strip()
        if not text:
            raise LocalSlicerError(f"{label} is required")
        if not _os.path.isfile(text):
            raise LocalSlicerError(f"{label} not found; refusing")
    settings = f"{machine_json};{process_json}"
    argv = [binary, "--orient", "--arrange", "1",
            "--load-settings", settings,
            "--load-filaments", str(filament_json),
            "--slice", "0", "--export-3mf", output_3mf]
    for key, value in dict(overrides or {}).items():
        name = str(key or "").strip()
        if not name or len(name) > 60 or not name.startswith("--"):
            raise LocalSlicerError(
                "bambu overrides must look like --key=value")
        if any(char in name for char in " \t|&;$`()<>\"'"):
            raise LocalSlicerError(
                "bambu override carries shell characters; refusing")
        argv.append(f"{name}={str(value)[:80]}")
    argv.append(stl_path)
    return argv


def resolve_model_artifact(mesh_ref: str) -> tuple[str, str, bytes]:
    """Find model bytes for a slice request.

    Returns (source, path, data) where source is "library" or
    "fabdir". Library models (E:\\Mycelium) are read in place;
    inbox models come from the fabrication dir. Ambiguity and
    absence refuse honestly.
    """
    from .mesh3d import MAX_MESH_BYTES
    from .workshop3d import _library_model_bytes, _model_bytes
    from .workshop3d import list_models
    wanted = str(mesh_ref or "").strip()
    if not wanted:
        raise LocalSlicerError("mesh_ref is required")
    matches = [item for item in list_models(limit=200) or []
               if str(item.get("filename", "")) == wanted]
    library_hits = [item for item in matches
                    if str(item.get("library_ref", "") or "")]
    if len(library_hits) > 1:
        raise LocalSlicerError(
            f"several library models named '{wanted[:60]}'; "
            f"refusing ambiguous slice")
    if library_hits:
        rel = str(library_hits[0].get("library_ref", ""))
        name = rel.split("/")[-1]
        try:
            data = _library_model_bytes(name)
        except ValueError as error:
            raise LocalSlicerError(str(error)) from error
        from .forge import library_root
        path = _os.path.join(library_root(), "bibliotheek", name)
        return "library", path, data
    try:
        data = _model_bytes(wanted)
    except ValueError as error:
        raise LocalSlicerError(str(error)) from error
    if len(matches) > 1:
        raise LocalSlicerError(
            f"several fab models named '{wanted[:60]}'; refusing")
    from .mesh3d import artifact_path
    return "fabdir", artifact_path(wanted), data


class ConsoleSlicer:
    """Real local slicing through a proven console binary.

    Implements the SlicerProvider shape (slice(request)) without
    importing it, so slicer3d.py never gains subprocess/mqtt
    tokens. Engine "prusa" executes; "bambu" refuses as UNPROVEN
    until BAMBU_CLI_PROVEN=1 documents a manual proof.
    """

    name = "prusa-console"

    def __init__(self, engine: str = "prusa"):
        cleaned = str(engine or "").strip().lower()
        if cleaned == "bambu":
            import os as _env
            if _env.environ.get(BAMBU_PROOF_ENV_VAR,
                                "") != "1":
                from .slicer3d import SlicerUnavailable
                raise SlicerUnavailable(
                    "Bambu Studio CLI headless slicing is UNPROVEN "
                    "on this build (input files never accepted in "
                    "8 attempts); refusing instead of faking output")
        if cleaned not in ("prusa",):
            from .slicer3d import SlicerRefusedError
            raise SlicerRefusedError(
                f"console engine '{engine}' is not executable; "
                f"expected 'prusa'")
        self.engine = cleaned

    def slice(self, request) -> object:
        from .slicer3d import MAX_GCODE_BYTES as _MAXG
        from .slicer3d import (SlicerRefusedError, SlicerResult,
                               check_profile)
        from .slicer3d import _store_gcode
        from .inventory_read import Provenance
        profile_name = str(getattr(request, "profile", ""))
        settings = check_profile(profile_name)
        if str(getattr(request, "mesh_ref", "") or "") == "":
            raise SlicerRefusedError("mesh_ref is required")
        source, model_path, data = resolve_model_artifact(
            str(request.mesh_ref))
        if len(data) <= 0:
            raise SlicerRefusedError("model is empty; refusing")
        short = _hashlib.sha256(data).hexdigest()[:8]
        out_name = canonical_gcode_name(
            str(request.mesh_ref), profile_name, short)
        gcode_dir = canonical_gcode_dir()
        canonical = _os.path.join(gcode_dir, out_name)
        if not _os.path.isfile(canonical):
            with open(model_path, "rb") as _src:
                model_bytes = _src.read()
            import tempfile as _tf
            tmp_in = _os.path.join(
                gcode_dir, f".slice-{short}.stl")
            try:
                with open(tmp_in, "wb") as handle:
                    handle.write(model_bytes)
                result = slice_with_prusa(
                    stl_path=tmp_in, output_path=canonical,
                    profile=settings,
                    extra_printer_keys={
                        "bed-shape": A1MINI_BED_SHAPE})
            finally:
                try:
                    _os.remove(tmp_in)
                except OSError:
                    pass
        else:
            with open(canonical, "rb") as handle:
                blob = handle.read()
            if len(blob) <= 0 or len(blob) > _MAXG:
                raise SlicerRefusedError(
                    "canonical G-code out of bounds; refusing")
            result = {"gcode_path": canonical,
                      "sha256": _hashlib.sha256(blob).hexdigest(),
                      "size_bytes": len(blob),
                      "line_count": blob.count(b"\n"),
                      "engine": "prusa", "argv": ["<cached>"]}
        try:
            text = open(result["gcode_path"], "rb").read().decode(
                "ascii")
        except (OSError, UnicodeDecodeError) as error:
            raise SlicerRefusedError(
                f"G-code unreadable as ASCII ({error}); refusing")
        work_ref, work_data = _store_gcode(
            f"fab-{short}-{profile_name}.gcode", text)
        if _hashlib.sha256(work_data).hexdigest() != \
                result["sha256"]:
            raise SlicerRefusedError(
                "working copy differs from canonical; refusing")
        return SlicerResult(
            gcode_ref=work_ref, sha256=result["sha256"],
            size_bytes=result["size_bytes"],
            line_count=result["line_count"], profile=profile_name,
            printer_id=str(getattr(request, "printer_id", "")),
            slicer=self.name, test_generated=False,
            provenance=Provenance(
                source_type="derived",
                creator_id=f"fabrication:local-slicer:{self.engine}",
                human_verified=False,
                notes=("local subprocess slice "
                       f"({result['engine']}); canonical "
                       f"{canonical[-80:]}")))
