"""3D workshop ecosystem (BIG #35): models become living citizens.

The workbench, reusing every existing safety layer:

    DISCOVER → IMPORT → INSPECT → UNDERSTAND → CONNECT →
    MODIFY → PREPARE → SLICE → FABRICATE → OBSERVE →
    VERIFY → LEARN → UPDATE WORLD

Rules (fail-closed, tested):

- No second world model. Models (`mdl_…`), materials
  (`mat_…`) and fab jobs (`fabjob_…`) are workshop metadata;
  relationships to INVENTory entities are connection
  candidates (PROPOSED symbiosis) until the knowledge flow
  supports/promotes them. No direct edges, no invented
  predicates outside the closed set below.
- Model files live in the existing fabrication dir (operator
  copies them there, like the camera inbox). REAL inspection
  for STL/OBJ via the existing mesh validator; 3MF/GLB/GLTF
  register metadata-only with inspection UNKNOWN. Nothing
  отлично is ever measured that was not parsed; manifold,
  units and volume stay UNKNOWN unless actually determined.
- Dedupe by sha256: same bytes never register twice.
- Fabrication honesty: preparation/validation/slicing use
  the existing TEST slicer (labeled) or refuse with an
  explicit UNAVAILABLE reason. Print proposals go through
  the existing writes flow (`printer.execute`, exact YES);
  fab-job stages DERIVE from the stored write record and
  PrintResult — the module never approves or executes.
  Simulated execution only ever reports SIMULATED telemetry.
- Camera verification: an observation plus the existing
  observation-verification halves; human YES stays required
  before any verified memory.
- No shell, no subprocess, no eval, no URLs, no credentials.
  Model bytes are parsed as data with struct, never run.
"""

from __future__ import annotations

import hashlib as _hashlib
import secrets as _secrets
import struct as _struct
import time as _time

from pydantic import BaseModel, ConfigDict, Field

#: Model filename suffixes. STL/OBJ get geometric inspection;
#: 3MF/GLB/GLTF register metadata-only (inspection UNKNOWN).
MODEL_SUFFIXES = (".stl", ".obj", ".3mf", ".glb", ".gltf")
INSPECTABLE_SUFFIXES = (".stl", ".obj")

MAX_MODELS_PER_PAGE = 50

#: Closed predicates for workshop → world links. Connection
#: candidates only (PROPOSED symbiosis); never direct edges.
WORKSHOP_PREDICATES = (
    "represents",
    "requires",
    "used_in",
    "generated_from",
    "fabricated_by",
    "replacement_for",
    "compatible_with",
    "verified_by",
    "part_of",
    "related_to",
)

MODEL_STATES = (
    "imported",
    "inspected",
    "connected",
    "in-fabrication",
    "observed",
    "verified",
)

MATERIAL_STATES = ("known", "candidate", "unknown")

FABJOB_STAGES = (
    "designed",
    "prepared",
    "sliced",
    "gcode-ready",
    "proposed",
    "approved",
    "printing-simulated",
    "printed-simulated",
    "observed",
    "verifying",
    "verified",
    "blocked",
    "cancelled",
)


class WorkshopRefusedError(ValueError):
    """Workshop validation refused; nothing was stored."""


class ModelInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    triangles: int = Field(default=-1, ge=-1)
    vertices: int = Field(default=-1, ge=-1)
    bbox_mm: list[float] = Field(default_factory=list,
                                 max_length=6)
    bbox_volume_mm3: float = Field(default=-1.0, ge=-1.0)
    manifold: str = Field(default="UNKNOWN", max_length=20)
    units: str = Field(default="UNKNOWN", max_length=20)
    volume: str = Field(default="UNKNOWN", max_length=20)
    mesh_verdict: str = Field(default="UNKNOWN", max_length=20)
    inspected: bool = False
    note: str = Field(default="", max_length=500)


class WorkshopModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=3, max_length=80)
    filename: str = Field(min_length=1, max_length=200)
    mime_type: str = Field(default="", max_length=200)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64,
                        pattern=r"^[0-9a-f]{64}$")
    source: str = Field(default="inbox", max_length=40)
    status: str = Field(default="imported", max_length=20)
    inspection: ModelInspection = Field(
        default_factory=ModelInspection)
    created_at: str = ""
    updated_at: str = ""


class WorkshopMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="filament", max_length=40)
    state: str = Field(default="unknown", max_length=20)
    notes: str = Field(default="", max_length=1000)
    sustainability_note: str = Field(default="", max_length=1000)
    linked_entity: str = Field(default="", max_length=100)
    created_at: str = ""
    updated_at: str = ""


class FabJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=3, max_length=80)
    model_id: str = Field(min_length=3, max_length=80)
    material_ref: str = Field(default="", max_length=120)
    printer_id: str = Field(default="", max_length=80)
    profile: str = Field(default="", max_length=40)
    stage: str = Field(default="designed", max_length=30)
    gcode_ref: str = Field(default="", max_length=200)
    gcode_sha256: str = Field(default="", max_length=64)
    proposal_id: str = Field(default="", max_length=80)
    print_job_id: str = Field(default="", max_length=80)
    observation_id: str = Field(default="", max_length=80)
    history: list[dict] = Field(default_factory=list,
                                max_length=60)
    created_at: str = ""
    updated_at: str = ""


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def generate_model_id() -> str:
    return f"mdl_{_secrets.token_hex(6)}"


def generate_material_id() -> str:
    return f"mat_{_secrets.token_hex(4)}"


def generate_fabjob_id() -> str:
    return f"fabjob_{int(_time.time() * 1000):x}" \
        f"{_secrets.token_hex(2)}"


def init_workshop_tables() -> None:
    """Additive workshop tables in the chat DB. Idempotent."""
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS workshop_models (
            model_id TEXT PRIMARY KEY,
            record TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workshop_materials (
            material_id TEXT PRIMARY KEY,
            record TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workshop_fabjobs (
            job_id TEXT PRIMARY KEY,
            record TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_workshop_models_created
            ON workshop_models(created_at);
        CREATE INDEX IF NOT EXISTS idx_workshop_fabjobs_created
            ON workshop_fabjobs(created_at);
        """)


def check_workshop_id(value: str, prefix: str) -> str:
    cleaned = str(value or "").strip()[:80]
    if not cleaned.startswith(prefix) or len(cleaned) < 6:
        raise WorkshopRefusedError(
            f"id must be a {prefix} workshop id")
    if any(char not in
           "abcdefghijklmnopqrstuvwxyz0123456789_-"
           for char in cleaned):
        raise WorkshopRefusedError("id has illegal characters")
    return cleaned


def _check_model_filename(value: str) -> str:
    """Model filename only: no paths, URLs or schemes, and a
    known model suffix. Mirrors the fab-dir discipline for the
    wider model set (3MF/GLB/GLTF are metadata-only)."""
    if not isinstance(value, str):
        raise WorkshopRefusedError("model filename must be text")
    text = value.strip()
    if not text:
        raise WorkshopRefusedError(
            "model filename must be non-empty text")
    if len(text) > 200:
        raise WorkshopRefusedError("model filename too long")
    lowered = text.lower()
    if ("://" in lowered or text.startswith("\\\\")
            or text.startswith("/") or ":" in text):
        raise WorkshopRefusedError(
            "model filename must be a plain local filename")
    if ".." in text or "/" in text or "\\" in text:
        raise WorkshopRefusedError(
            "model filename must not contain a path")
    if not lowered.endswith(MODEL_SUFFIXES):
        raise WorkshopRefusedError(
            f"unsupported model format; expected one of "
            f"{list(MODEL_SUFFIXES)}")
    return text


def _model_bytes(reference: str) -> bytes:
    """Read one validated model file inside the fabrication dir."""
    import os as _os
    from .mesh3d import fabrication_dir, read_artifact_bytes
    if reference.lower().endswith(INSPECTABLE_SUFFIXES):
        return read_artifact_bytes(reference)
    root = _os.path.abspath(fabrication_dir())
    path = _os.path.abspath(_os.path.join(root, reference))
    if path != root and not path.startswith(root + _os.sep):
        raise WorkshopRefusedError(
            "model escapes the fabrication directory")
    if not _os.path.isfile(path):
        raise WorkshopRefusedError(
            f"model '{reference}' is not in the fabrication dir; "
            f"copy the file there first")
    size = _os.path.getsize(path)
    if size <= 0:
        raise WorkshopRefusedError("model is empty; refusing")
    from .mesh3d import MAX_MESH_BYTES
    if size > MAX_MESH_BYTES:
        raise WorkshopRefusedError(
            f"model is {size} bytes (max {MAX_MESH_BYTES}); refusing")
    with open(path, "rb") as handle:
        return handle.read(MAX_MESH_BYTES + 1)


def _mime_for(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".stl"):
        return "model/stl"
    if lowered.endswith(".obj"):
        return "model/obj"
    if lowered.endswith(".3mf"):
        return "model/3mf"
    if lowered.endswith((".glb", ".gltf")):
        return "model/gltf-binary" if lowered.endswith(".glb") \
            else "model/gltf+json"
    return "application/octet-stream"


def _save(table: str, key: str, key_col: str,
          record: dict, created_at: str) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_workshop_tables()
    init_chat_database()
    with chat_connection() as db:
        db.execute(
            f"""INSERT INTO {table}
            ({key_col}, record, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT({key_col}) DO UPDATE SET
            record=excluded.record""",
            (key, dump(record), created_at or _now()))


def _load(table: str, key_col: str, key: str):
    from .database import chat_connection, init_chat_database, load
    init_workshop_tables()
    init_chat_database()
    with chat_connection() as db:
        row = db.execute(f"SELECT record FROM {table} "
                         f"WHERE {key_col}=?", (key,)).fetchone()
    if row is None:
        return None
    return load(row["record"])


def _list(table: str, limit: int) -> list[dict]:
    from .database import chat_connection, init_chat_database, load
    init_workshop_tables()
    init_chat_database()
    count = max(1, min(int(limit or 50), 100))
    with chat_connection() as db:
        rows = db.execute(f"SELECT record FROM {table} "
                          f"ORDER BY created_at DESC LIMIT ?",
                          (count,)).fetchall()
    return [load(row["record"]) for row in rows]


# -- model ingest + inspection ---------------------------------------------------

def known_model_shas() -> set[str]:
    return {str(item.get("sha256", "")) for item in
            _list("workshop_models", 100) if item.get("sha256")}


def register_model(filename: str, *, source: str = "inbox") -> dict:
    """Register one model file already present in the fabrication
    dir (operator copies it there, like the camera inbox).
    Metadata-only for 3MF/GLB/GLTF. Dedupe by sha256."""
    cleaned_source = str(source or "inbox").strip()[:40]
    if cleaned_source not in ("inbox", "generated", "test"):
        raise WorkshopRefusedError(
            "source must be inbox, generated or test")
    reference = _check_model_filename(filename)
    lowered = reference.lower()
    try:
        data = _model_bytes(reference)
    except WorkshopRefusedError:
        raise
    except ValueError as error:
        raise WorkshopRefusedError(str(error)) from error
    digest = _hashlib.sha256(data).hexdigest()
    if digest in known_model_shas():
        raise WorkshopRefusedError(
            "same model bytes already registered; replay refused")
    stamp = _now()
    model = WorkshopModel(
        model_id=generate_model_id(), filename=reference,
        mime_type=_mime_for(reference), size_bytes=len(data),
        sha256=digest, source=cleaned_source, status="imported",
        created_at=stamp, updated_at=stamp)
    _save("workshop_models", model.model_id, "model_id",
          model.model_dump(mode="json"), stamp)
    return model.model_dump(mode="json")


def get_model(model_id: str) -> dict | None:
    record = _load("workshop_models", "model_id",
                   check_workshop_id(model_id, "mdl_"))
    return record


def list_models(limit: int = 50) -> list[dict]:
    return _list("workshop_models", limit)


def _scan_stl(data: bytes) -> dict:
    """Lightweight geometric scan (stdlib only). Dimensions and
    counts only; manifold/volume stay UNKNOWN by design."""
    if len(data) >= 84 + 4:
        count = _struct.unpack("<I", data[80:84])[0]
        if count > 0 and len(data) == 80 + 4 + count * 50:
            points: list[tuple[float, float, float]] = []
            offset = 84
            for _ in range(min(count, 200000)):
                try:
                    (nx, ny, nz, x1, y1, z1, x2, y2, z2,
                     x3, y3, z3, _attr) = _struct.unpack(
                        "<12fH", data[offset:offset + 50])
                except _struct.error:
                    break
                points.extend([(x1, y1, z1), (x2, y2, z2),
                               (x3, y3, z3)])
                offset += 50
            if points:
                axes = list(zip(*points))
                lo = [min(axis) for axis in axes]
                hi = [max(axis) for axis in axes]
                size = [hi[i] - lo[i] for i in range(3)]
                return {"triangles": count,
                        "vertices": count * 3,
                        "bbox_mm": lo + hi,
                        "bbox_volume_mm3": size[0] * size[1] *
                        size[2]}
    text = None
    try:
        text = data[:200000].decode("ascii")
    except (UnicodeDecodeError, ValueError):
        text = None
    if text is not None and "facet normal" in text:
        facets = text.count("facet normal")
        numbers: list[float] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("vertex"):
                parts = stripped.split()
                if len(parts) == 4:
                    try:
                        numbers.extend(float(part) for part in
                                       parts[1:4])
                    except ValueError:
                        continue
        if facets and numbers:
            coords = [numbers[i:i + 3] for i in
                      range(0, len(numbers) - 2, 3)]
            axes = list(zip(*coords))
            lo = [min(axis) for axis in axes]
            hi = [max(axis) for axis in axes]
            size = [hi[i] - lo[i] for i in range(3)]
            return {"triangles": facets,
                    "vertices": facets * 3,
                    "bbox_mm": lo + hi,
                    "bbox_volume_mm3": size[0] * size[1] * size[2]}
    return {}


def _scan_obj(data: bytes) -> dict:
    try:
        text = data[:500000].decode("utf-8", "replace")
    except (UnicodeDecodeError, ValueError):
        return {}
    verts: list[tuple[float, float, float]] = []
    faces = 0
    for line in text.splitlines():
        if line.startswith("v "):
            parts = line.split()
            if len(parts) >= 4:
                try:
                    verts.append((float(parts[1]), float(parts[2]),
                                  float(parts[3])))
                except ValueError:
                    continue
        elif line.startswith("f "):
            faces += 1
    if not verts:
        return {}
    axes = list(zip(*verts))
    lo = [min(axis) for axis in axes]
    hi = [max(axis) for axis in axes]
    size = [hi[i] - lo[i] for i in range(3)]
    return {"triangles": faces, "vertices": len(verts),
            "bbox_mm": lo + hi,
            "bbox_volume_mm3": size[0] * size[1] * size[2]}


def inspect_model(model_id: str) -> dict:
    """Geometric scan + mesh-validator verdict. UNKNOWN wherever
    the bytes do not actually determine the answer."""
    from .mesh3d import read_artifact_bytes, validate_mesh
    record = get_model(model_id)
    if record is None:
        raise WorkshopRefusedError("model not found")
    filename = str(record.get("filename", ""))
    lowered = filename.lower()
    inspection = ModelInspection()
    if lowered.endswith(INSPECTABLE_SUFFIXES):
        try:
            data = _model_bytes(filename)
        except WorkshopRefusedError as error:
            raise error
        except ValueError as error:
            raise WorkshopRefusedError(str(error)) from error
        scanned = _scan_stl(data) if lowered.endswith(".stl") \
            else _scan_obj(data)
        if scanned:
            inspection.triangles = int(scanned["triangles"])
            inspection.vertices = int(scanned["vertices"])
            inspection.bbox_mm = [float(value) for value in
                                  scanned["bbox_mm"]]
            inspection.bbox_volume_mm3 = float(
                scanned["bbox_volume_mm3"])
            inspection.inspected = True
            inspection.note = ("workshop geometric scan (dimensions "
                               "and counts); manifold/volume/units "
                               "stay UNKNOWN")
        try:
            verdict = validate_mesh(filename)
            inspection.mesh_verdict = str(verdict.verdict)
        except ValueError:
            inspection.mesh_verdict = "inconclusive"
    else:
        inspection.note = ("format has no local inspector; "
                           "metadata only, everything UNKNOWN")
        inspection.mesh_verdict = "inconclusive"
    record["inspection"] = inspection.model_dump(mode="json")
    if record.get("status") == "imported":
        record["status"] = "inspected"
    record["updated_at"] = _now()
    _save("workshop_models", record["model_id"], "model_id",
          record, record.get("created_at", ""))
    return record


# -- materials ---------------------------------------------------------------------

def create_material(name: str, *, kind: str = "filament",
                    state: str = "unknown", notes: str = "",
                    sustainability_note: str = "",
                    linked_entity: str = "") -> dict:
    """Register one material. Sustainability text is an operator
    note, never a verified claim — no green claims by name."""
    cleaned_name = str(name or "").strip()[:120]
    if not cleaned_name:
        raise WorkshopRefusedError("material needs a name")
    cleaned_kind = str(kind or "filament").strip()[:40]
    if cleaned_kind not in ("filament", "resin", "powder",
                            "sheet", "fastener", "electronics",
                            "other"):
        raise WorkshopRefusedError(
            "material kind must be filament, resin, powder, sheet, "
            "fastener, electronics or other")
    cleaned_state = str(state or "unknown").strip()
    if cleaned_state not in MATERIAL_STATES:
        raise WorkshopRefusedError(
            f"material state must be one of {list(MATERIAL_STATES)}")
    entity = str(linked_entity or "").strip()[:100]
    if entity:
        from .symbiosis import clean_entity
        try:
            clean_entity(entity)
        except ValueError as error:
            raise WorkshopRefusedError(str(error)) from error
    stamp = _now()
    material = WorkshopMaterial(
        material_id=generate_material_id(), name=cleaned_name,
        kind=cleaned_kind, state=cleaned_state,
        notes=str(notes or "")[:1000],
        sustainability_note=str(sustainability_note or "")[:1000],
        linked_entity=entity, created_at=stamp, updated_at=stamp)
    _save("workshop_materials", material.material_id,
          "material_id", material.model_dump(mode="json"), stamp)
    return material.model_dump(mode="json")


def get_material(material_id: str) -> dict | None:
    return _load("workshop_materials", "material_id",
                 check_workshop_id(material_id, "mat_"))


def list_materials(limit: int = 50) -> list[dict]:
    return _list("workshop_materials", limit)


def suggest_materials(model_id: str, limit: int = 5) -> list[dict]:
    """Possible material matches: known materials first, then
    candidates. Suggestions, never assignments."""
    record = get_model(model_id)
    if record is None:
        raise WorkshopRefusedError("model not found")
    materials = list_materials(limit=50)
    known = [item for item in materials
             if item.get("state") == "known"]
    candidates = [item for item in materials
                  if item.get("state") == "candidate"]
    rest = [item for item in materials
            if item.get("state") not in ("known", "candidate")]
    ordered = known + candidates + rest
    return [{"material_id": item["material_id"],
             "name": item.get("name", ""),
             "state": item.get("state", ""),
             "why": "known stock; confirm before slicing"
             if item.get("state") == "known" else
             "candidate; needs review before use"}
            for item in ordered[:max(1, min(int(limit or 5), 10))]]


# -- workshop → world links (PROPOSED symbiosis) --------------------------------------

def propose_workshop_link(workshop_id: str, entity_id: str,
                          predicate: str) -> dict:
    """Link a model/material/fabjob to a world entity as a
    connection candidate. PROPOSED until the knowledge flow
    decides."""
    from .events import new_event as _bus_new
    from .events import save_event as _bus_save
    from .inventory_read import Provenance
    from .knowledge import (CandidateRefusedError, new_candidate,
                            save_candidate)
    from .symbiosis import clean_entity
    cleaned_workshop = str(workshop_id or "").strip()[:80]
    if not (cleaned_workshop.startswith(("mdl_", "mat_",
                                         "fabjob_"))):
        raise WorkshopRefusedError(
            "workshop id must be mdl_, mat_ or fabjob_")
    try:
        clean_entity(cleaned_workshop)
    except ValueError as error:
        raise WorkshopRefusedError(str(error)) from error
    try:
        target = clean_entity(entity_id)
    except ValueError as error:
        raise WorkshopRefusedError(str(error)) from error
    verb = str(predicate or "").strip()[:20]
    if verb not in WORKSHOP_PREDICATES:
        raise WorkshopRefusedError(
            f"predicate must be one of {list(WORKSHOP_PREDICATES)}")
    try:
        entry = new_candidate(
            f"workshop {cleaned_workshop[:24]} {verb} "
            f"{target[:40]}",
            "connection",
            summary=(f"Possible relation: workshop record "
                     f"{cleaned_workshop} {verb} {target}. "
                     f"PROPOSED — needs your YES before it means "
                     f"anything."),
            state="candidate",
            provenance=Provenance(
                source_type="user-created",
                creator_id="workshop-3d", human_verified=False,
                notes="workshop-suggested link; unconfirmed"),
            source_refs=[{"kind": "workshop-record",
                          "id": cleaned_workshop,
                          "label": f"workshop {cleaned_workshop}"}],
            entity_refs=[cleaned_workshop, target])
        save_candidate(entry)
    except CandidateRefusedError as error:
        raise WorkshopRefusedError(str(error)) from error
    try:
        _bus_save(_bus_new(
            "relation.proposed",
            f"Workshop link proposed: {cleaned_workshop} {verb} "
            f"{target}"))
    except Exception:
        pass
    return {"candidate_id": entry.candidate_id,
            "workshop_id": cleaned_workshop, "entity_id": target,
            "predicate": verb, "state": "PROPOSED"}


# -- fab jobs --------------------------------------------------------------------------

def _history(record: dict, stage: str, note: str) -> None:
    history = record.get("history") or []
    history.append({"stage": stage, "at": _now(),
                    "note": str(note or "")[:300]})
    record["history"] = history[-60:]
    record["stage"] = stage
    record["updated_at"] = _now()


def create_fabjob(model_id: str, *, material_ref: str = "",
                  printer_id: str = "", profile: str = "",
                  actor: str = "web") -> dict:
    record = get_model(model_id)
    if record is None:
        raise WorkshopRefusedError("model not found")
    cleaned_printer = str(printer_id or "").strip()[:80]
    if cleaned_printer:
        from .printer3d import load_printer
        if load_printer(cleaned_printer) is None:
            raise WorkshopRefusedError("printer not found")
    cleaned_profile = str(profile or "").strip()[:40]
    if cleaned_profile:
        from .slicer3d import SLICER_PROFILES
        if cleaned_profile not in SLICER_PROFILES:
            raise WorkshopRefusedError(
                "unknown slicer profile for a fab job")
    stamp = _now()
    job = FabJob(
        job_id=generate_fabjob_id(),
        model_id=record["model_id"],
        material_ref=str(material_ref or "")[:120],
        printer_id=cleaned_printer, profile=cleaned_profile,
        created_at=stamp, updated_at=stamp)
    data = job.model_dump(mode="json")
    _history(data, "designed",
             f"job for {record['model_id']} by {actor[:40]}")
    _save("workshop_fabjobs", data["job_id"], "job_id", data,
          stamp)
    return data


def get_fabjob(job_id: str) -> dict | None:
    return _load("workshop_fabjobs", "job_id",
                 check_workshop_id(job_id, "fabjob_"))


def list_fabjobs(limit: int = 50) -> list[dict]:
    return _list("workshop_fabjobs", limit)


def _store_job(data: dict) -> dict:
    _save("workshop_fabjobs", data["job_id"], "job_id", data,
          data.get("created_at", ""))
    return data


def prepare_job(job_id: str) -> dict:
    """Validate mesh + printability assessment. Read-only."""
    from .mesh3d import validate_mesh
    from .mesh3d import assess_printability
    data = get_fabjob(job_id)
    if data is None:
        raise WorkshopRefusedError("fab job not found")
    if data["stage"] != "designed":
        raise WorkshopRefusedError(
            f"job is {data['stage']}; prepare needs designed")
    model = get_model(data["model_id"])
    if model is None:
        raise WorkshopRefusedError("model for this job is gone")
    try:
        verdict = validate_mesh(model["filename"])
    except ValueError as error:
        raise WorkshopRefusedError(str(error)) from error
    if verdict.verdict != "valid":
        data["stage"] = "blocked"
        data["updated_at"] = _now()
        _history(data, "blocked",
                 f"mesh verdict {verdict.verdict}; refusing")
        return _store_job(data)
    assessment = assess_printability(verdict)
    _history(data, "prepared",
             f"mesh valid ({verdict.faces} faces); printability "
             f"{assessment.verdict}")
    data["printability"] = assessment.model_dump(mode="json")
    return _store_job(data)


def slice_job(job_id: str, *, slicer: str = "test-slicer") -> dict:
    """Slice with a named slicer. TEST slicer labels output;
    anything else unavailable refuses honestly."""
    from .slicer3d import (SlicerUnavailable, check_slicer_request,
                           get_slicer)
    data = get_fabjob(job_id)
    if data is None:
        raise WorkshopRefusedError("fab job not found")
    if data["stage"] != "prepared":
        raise WorkshopRefusedError(
            f"job is {data['stage']}; slice needs prepared")
    model = get_model(data["model_id"])
    if model is None:
        raise WorkshopRefusedError("model for this job is gone")
    if not data.get("printer_id"):
        raise WorkshopRefusedError(
            "job needs a printer before slicing")
    try:
        request = check_slicer_request(
            model["filename"],
            data.get("profile") or "draft-pla",
            data["printer_id"])
    except ValueError as error:
        raise WorkshopRefusedError(str(error)) from error
    try:
        provider = get_slicer(slicer)
        result = provider.slice(request)
    except (ValueError, SlicerUnavailable) as error:
        data["stage"] = "blocked"
        _history(data, "blocked", f"slicer refused: {error}")
        return _store_job(data)
    data["gcode_ref"] = result.gcode_ref
    data["gcode_sha256"] = result.sha256
    data["slicer"] = result.slicer
    _history(data, "sliced", f"{result.slicer}: {result.gcode_ref}")
    _history(data, "gcode-ready", "G-code artifact stored locally")
    return _store_job(data)


def propose_job_print(job_id: str, *, actor: str = "web") -> dict:
    """Create the INERT printer.execute proposal through the
    existing flow. Approval + execution stay in writes."""
    from . import main as _main
    from .fab_flow import propose_print
    from .printer3d import new_job
    data = get_fabjob(job_id)
    if data is None:
        raise WorkshopRefusedError("fab job not found")
    if data["stage"] != "gcode-ready":
        raise WorkshopRefusedError(
            f"job is {data['stage']}; propose needs gcode-ready")
    if not data.get("gcode_ref") or not data.get("gcode_sha256"):
        raise WorkshopRefusedError("job carries no G-code")
    import secrets as _secrets
    job = new_job(f"pjob-{_secrets.token_hex(4)}",
                  data["printer_id"], data["gcode_ref"],
                  data["gcode_sha256"],
                  data.get("profile") or "draft-pla", actor[:80],
                  proposal_id=f"wrt-{_secrets.token_hex(4)}")
    try:
        proposal = propose_print(
            job.proposal_id, job,
            safety_verdict="inconclusive", actor=actor[:80])
    except ValueError as error:
        raise WorkshopRefusedError(str(error)) from error
    _main._write_save(proposal, "proposed")
    data["proposal_id"] = proposal.proposal_id
    data["print_job_id"] = job.job_id
    _history(data, "proposed",
             f"printer.execute {proposal.proposal_id}; exact YES "
             f"required, execution only via writes")
    return _store_job(data)


def sync_job(job_id: str) -> dict:
    """Derive stage from the stored write record + PrintResult.
    Never sets approval/execution — only observes them."""
    from . import main as _main
    data = get_fabjob(job_id)
    if data is None:
        raise WorkshopRefusedError("fab job not found")
    if not data.get("proposal_id"):
        return data
    record = _main._write_load(data["proposal_id"])
    if record is None:
        return data
    status = str(record.get("status", ""))
    result = record.get("result") or {}
    if status == "approved" and data["stage"] == "proposed":
        _history(data, "approved",
                 f"{data['proposal_id']} approved; execution only "
                 f"via writes execute")
    elif status == "rejected":
        data["stage"] = "blocked"
        _history(data, "blocked",
                 f"{data['proposal_id']} rejected; refusing")
    elif status == "executed" or result:
        outcome = str(result.get("outcome",
                                 result.get("status", "")))
        telemetry = ((result.get("after") or {}).get("print_result")
                     or {}) if isinstance(result, dict) else {}
        telem_status = str(telemetry.get("status", ""))
        if outcome == "executed" and telem_status == "completed":
            _history(data, "printing-simulated",
                     "execution reported; SIMULATED telemetry only")
            _history(data, "printed-simulated",
                     f"job {data.get('print_job_id')}; camera "
                     f"observation still required")
        elif outcome in ("failed", "blocked"):
            data["stage"] = "blocked"
            _history(data, "blocked",
                     f"execution {outcome}: "
                     f"{str(result.get('error', ''))[:200]}")
    return _store_job(data)


def observe_job(job_id: str, observation_id: str) -> dict:
    """Attach a real camera observation to a printed job."""
    data = get_fabjob(job_id)
    if data is None:
        raise WorkshopRefusedError("fab job not found")
    if data["stage"] not in ("printed-simulated", "observed",
                             "verifying"):
        raise WorkshopRefusedError(
            f"job is {data['stage']}; observe needs a printed job")
    cleaned = str(observation_id or "").strip()[:80]
    found = None
    try:
        from . import main as _main
        found = _main._observation_load(cleaned)
    except Exception:
        found = None
    if found is None:
        raise WorkshopRefusedError("observation not found")
    data["observation_id"] = cleaned
    _history(data, "observed",
             f"camera observation {cleaned} attached; identity of "
             f"the printed object still unconfirmed")
    return _store_job(data)


def verify_job(job_id: str, *, verified_by: str) -> dict:
    """Two halves: PrintResult telemetry present + observation
    verification passed. Human verifier named, never assumed."""
    from . import main as _main
    from .vision_flow import (new_observation_verification_request,
                              verify_observation)
    data = get_fabjob(job_id)
    if data is None:
        raise WorkshopRefusedError("fab job not found")
    if data["stage"] not in ("observed", "verifying"):
        raise WorkshopRefusedError(
            f"job is {data['stage']}; verify needs an observed job")
    approver = str(verified_by or "").strip()[:80]
    if not approver:
        raise WorkshopRefusedError(
            "verification needs a named human verifier")
    record = _main._write_load(data["proposal_id"]) \
        if data.get("proposal_id") else None
    result = (record or {}).get("result") or {}
    telemetry = ((result.get("after") or {}).get("print_result")
                 or {}) if isinstance(result, dict) else {}
    if str(result.get("outcome", "")) != "executed" or \
            str(telemetry.get("status", "")) != "completed":
        raise WorkshopRefusedError(
            "no completed execution telemetry; refusing")
    observation = _main._observation_load(data["observation_id"])
    if observation is None:
        raise WorkshopRefusedError(
            "attached observation is gone; refusing")
    import os as _os
    from .cameras import camera_dir
    media_path = _os.path.join(
        camera_dir(), observation.media_ref) \
        if observation.media_ref else ""
    request = new_observation_verification_request(
        data["proposal_id"],
        str(telemetry.get("gcode_sha256", "")),
        observation)
    outcome = verify_observation(
        request, observation,
        media_exists=bool(media_path) and _os.path.isfile(
            media_path))
    if outcome.outcome != "passed":
        data["stage"] = "blocked"
        _history(data, "blocked",
                 f"camera half failed: {outcome.note[:200]}")
        return _store_job(data)
    _history(data, "verifying",
             f"telemetry completed + camera readback passed; "
             f"verifier {approver}")
    _history(data, "verified",
             f"verified by {approver}; observation confirms the "
             f"object, identity now human-confirmed")
    data["verified_by"] = approver
    return _store_job(data)


def cancel_job(job_id: str, *, reason: str = "") -> dict:
    data = get_fabjob(job_id)
    if data is None:
        raise WorkshopRefusedError("fab job not found")
    if data["stage"] in ("verified", "cancelled"):
        raise WorkshopRefusedError(
            f"job is {data['stage']}; cannot cancel")
    if data["stage"] in ("printed-simulated", "observed",
                         "verifying"):
        raise WorkshopRefusedError(
            "printed plastic cannot be un-printed; record the "
            "outcome instead of cancelling")
    _history(data, "cancelled", str(reason or "")[:300] or
             "cancelled by operator")
    return _store_job(data)


# -- presence, packet, progress data -----------------------------------------------------

def workshop_presence(entity_id: str) -> dict:
    """Checklist for one world entity: model / material /
    fabrication / observation / verification. All from real
    stores; missing pieces are actionable gaps."""
    from .symbiosis import clean_entity
    try:
        cleaned = clean_entity(entity_id)
    except ValueError as error:
        raise WorkshopRefusedError(str(error)) from error
    try:
        from .knowledge import list_candidates
        candidates = list_candidates(limit=300)
    except Exception:
        candidates = []
    linked_models: list[str] = []
    linked_materials: list[str] = []
    project_count = 0
    projects: set[str] = set()
    for entry in candidates:
        try:
            data = entry.model_dump(mode="json")
        except Exception:
            continue
        if data.get("candidate_type") != "connection":
            continue
        refs = data.get("entity_refs") or []
        if cleaned not in refs:
            continue
        for ref in refs:
            if str(ref).startswith("mdl_") and \
                    ref not in linked_models:
                linked_models.append(str(ref))
            if str(ref).startswith("mat_") and \
                    ref not in linked_materials:
                linked_materials.append(str(ref))
            if str(ref).startswith("proj_"):
                projects.add(str(ref))
    project_count = len(projects)
    jobs = [job for job in list_fabjobs(limit=100)
            if job.get("model_id") in linked_models]
    FabricationRecord = None
    try:
        from . import main as _main
        FabricationRecord = [
            {"fabrication_id": record.fabrication_id,
             "status": record.status}
            for record in _main.list_fabrications(50)]
    except Exception:
        FabricationRecord = []
    observed = [job for job in jobs if job.get("observation_id")]
    verified = [job for job in jobs if job.get("stage") == "verified"]
    checklist = [
        ("project", bool(cleaned.startswith("proj_")) or
         project_count > 0),
        ("3d model", bool(linked_models)),
        ("material", bool(linked_materials)),
        ("fabrication", bool(jobs or FabricationRecord)),
        ("physical verification", bool(verified)),
    ]
    gaps = []
    if not linked_models:
        gaps.append({"missing": "3d model",
                     "hint": "No model linked yet.",
                     "href": "/3d"})
    if linked_models and not linked_materials:
        gaps.append({"missing": "material",
                     "hint": "Model has no material.",
                     "href": "/3d"})
    if linked_models and not jobs:
        gaps.append({"missing": "fabrication",
                     "hint": "No fabrication route yet.",
                     "href": "/fabrication"})
    if jobs and not observed:
        gaps.append({"missing": "camera evidence",
                     "hint": "Printed, but no camera observation.",
                     "href": "/cameras"})
    if observed and not verified:
        gaps.append({"missing": "verification",
                     "hint": "Evidence exists, not reviewed.",
                     "href": "/3d"})
    done = sum(1 for _, present in checklist if present)
    return {"entity_id": cleaned, "checklist": checklist,
            "done": done, "total": len(checklist),
            "models": linked_models[:10],
            "materials": linked_materials[:10],
            "fabjobs": [job["job_id"] for job in jobs[:10]],
            "project_links": project_count, "gaps": gaps}


def workshop_packet(project_id: str = "") -> dict:
    """Continuation packet section for 3D work: model, stage,
    material, facts, observations, candidates, blockers, next
    actions, provenance, approvals. No secrets."""
    cleaned = str(project_id or "").strip()[:100]
    models = list_models(limit=20)
    jobs = list_fabjobs(limit=20)
    if cleaned:
        try:
            presence = workshop_presence(cleaned)
            models = [model for model in models
                      if model["model_id"] in
                      presence["models"]] or models[:5]
            jobs = [job for job in jobs
                    if job["job_id"] in
                    presence["fabjobs"]] or []
        except WorkshopRefusedError:
            presence = {"entity_id": cleaned, "checklist": [],
                        "gaps": []}
    else:
        presence = {"entity_id": "", "checklist": [],
                    "gaps": []}
    blockers = [f"{job['job_id']} is {job['stage']}"
                for job in jobs if job["stage"] == "blocked"][:10]
    waiting = [f"{job['job_id']} awaits "
               f"{'approval' if job['stage'] == 'proposed' else 'verification'}"
               for job in jobs if job["stage"] in
               ("proposed", "observed", "verifying")][:10]
    lines = ["# MYCELIUM 3D WORKSHOP SECTION",
             f"project: {cleaned or '(whole workshop)'}",
             f"models: {len(models)} tracked, "
             f"fab jobs: {len(jobs)} tracked"]
    for model in models[:8]:
        inspection = model.get("inspection", {})
        lines.append(
            f"- model {model['model_id']} ({model['filename']}, "
            f"{model['status']}, mesh: "
            f"{inspection.get('mesh_verdict', 'UNKNOWN')})")
    for job in jobs[:8]:
        lines.append(
            f"- fabjob {job['job_id']}: model {job['model_id']}, "
            f"stage {job['stage']}, printer "
            f"{job.get('printer_id') or 'none'}, material "
            f"{job.get('material_ref') or 'none'}")
    lines.append(f"blockers: {'; '.join(blockers) or 'none'}")
    lines.append(f"waiting: {'; '.join(waiting) or 'none'}")
    lines.append("provenance: workshop registry (local), mesh "
                 "validator, TEST slicer where labeled, human YES "
                 "for prints, camera readback for verification")
    return {"packet": "mycelium-3d-workshop/1",
            "project_id": cleaned, "models": models[:20],
            "fabjobs": jobs[:20], "presence": presence,
            "blockers": blockers, "waiting": waiting,
            "markdown": "\n".join(lines)[:6000]}
