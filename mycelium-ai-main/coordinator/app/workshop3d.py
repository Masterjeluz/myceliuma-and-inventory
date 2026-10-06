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
    "queued",
    "approved",
    "printing",
    "printed",
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


#: License names that carry no enforceable terms. They describe
#: availability, not rights — accepting them as a license would
#: silently turn "open source" into "sellable", which is exactly
#: what must never happen.
VAGUE_LICENSE_NAMES = frozenset({
    "open source", "open-source", "opensource", "open",
    "free", "free for use", "free to use", "freeware",
    "public", "public domain-ish", "creative commons",
    "cc", "all rights reserved",
})


class ModelLicense(BaseModel):
    """License + remix/sale terms of one library model.

    All use-flags are explicit tri-state: True/False from the
    actual license text, None = unknown (never assumed).
    """

    model_config = ConfigDict(extra="forbid")

    source_library: str = Field(default="", max_length=80)
    source_url: str = Field(default="", max_length=500)
    author: str = Field(default="", max_length=200)
    license: str = Field(default="", max_length=120)
    commercial_use: bool | None = None
    remix_allowed: bool | None = None
    attribution_required: bool | None = None
    original_model_url: str = Field(default="", max_length=500)
    imported_at: str = Field(default="", max_length=64)


def license_terms(name: str) -> dict:
    """Map a known license name to use-flags. Unknown names map
    to all-None: rights are never guessed from a name."""
    text = str(name or "").strip().lower().replace("  ", " ")
    text = text.replace(" ", "-")
    known = True
    note = ""
    if text in ("cc0-1.0", "cc0", "cc0 1.0 universal",
                "public domain", "pdm", "us government work",
                "nasa", "nasa usage guidelines"):
        commercial, remix, attribution = True, True, False
        note = ("public-domain dedication; attribution appreciated, "
                "not legally required")
    elif text.startswith("cc-by-nc-nd"):
        commercial, remix, attribution = False, False, True
        note = "non-commercial, no derivatives"
    elif text.startswith("cc-by-nc-sa"):
        commercial, remix, attribution = False, True, True
        note = "non-commercial, share-alike on remix"
    elif text.startswith("cc-by-nc"):
        commercial, remix, attribution = False, True, True
        note = "non-commercial"
    elif text.startswith("cc-by-nd"):
        commercial, remix, attribution = True, False, True
        note = "no derivatives"
    elif text.startswith("cc-by-sa"):
        commercial, remix, attribution = True, True, True
        note = "share-alike on remix"
    elif text.startswith("cc-by"):
        commercial, remix, attribution = True, True, True
        note = ""
    elif text in ("mit", "apache-2.0"):
        commercial, remix, attribution = True, True, True
        note = "software license applied to model files"
    else:
        known = False
        commercial, remix, attribution = None, None, None
        note = ("unknown license: commercial use, remix and "
                "attribution stay undecided until checked")
    return {"commercial_use": commercial, "remix_allowed": remix,
            "attribution_required": attribution, "known": known,
            "note": note}


def clean_library_license(
        value: dict | ModelLicense | None) -> ModelLicense | None:
    """Validate operator-supplied license info. Fail-closed:

    - vague names ("open source", "free", ...) are refused: they
      express no terms and must never imply sellability;
    - external origin (library/URL/author set) without an actual
      license name is refused: license is always part of the
      record, never optional for imports;
    - unknown license names keep all flags None (never assumed);
    - known names only fill flags the operator left undecided —
      explicit operator flags always win.
    """
    if value is None:
        return None
    if isinstance(value, ModelLicense):
        lic = value
    elif isinstance(value, dict):
        try:
            lic = ModelLicense(**{str(key): val for key, val in
                                   value.items()})
        except ValueError as error:
            raise WorkshopRefusedError(
                f"license info invalid ({error})") from error
    else:
        raise WorkshopRefusedError(
            "license info must be an object")
    cleaned_name = str(lic.license or "").strip()
    if cleaned_name.lower() in VAGUE_LICENSE_NAMES:
        raise WorkshopRefusedError(
            f"'{cleaned_name}' is geen licentie: leg de daadwerkelijke "
            f"licentievoorwaarden per model vast (bv. CC-BY-NC-4.0); "
            f"'open source' betekent niet verkoopbaar")
    external = any(str(part or "").strip() for part in
                   (lic.source_library, lic.source_url,
                    lic.original_model_url, lic.author))
    if external and not cleaned_name:
        raise WorkshopRefusedError(
            "externe herkomst zonder licentie geweigerd: licentie "
            "is altijd onderdeel van het modelrecord")
    terms = license_terms(cleaned_name) if cleaned_name else None
    data = lic.model_dump(mode="json")
    if terms is not None:
        for flag in ("commercial_use", "remix_allowed",
                     "attribution_required"):
            if data.get(flag) is None:
                data[flag] = terms[flag]
    data["license"] = cleaned_name
    data["imported_at"] = str(
        lic.imported_at or "").strip() or _now()
    return ModelLicense(**data)


class WorkshopModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=3, max_length=80)
    filename: str = Field(min_length=1, max_length=200)
    library_ref: str = Field(default="", max_length=200)
    mime_type: str = Field(default="", max_length=200)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64,
                        pattern=r"^[0-9a-f]{64}$")
    source: str = Field(default="inbox", max_length=40)
    status: str = Field(default="imported", max_length=20)
    inspection: ModelInspection = Field(
        default_factory=ModelInspection)
    license: ModelLicense | None = None
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
    model_id: str = Field(default="", max_length=80)
    material_ref: str = Field(default="", max_length=120)
    printer_id: str = Field(default="", max_length=80)
    profile: str = Field(default="", max_length=40)
    stage: str = Field(default="designed", max_length=30)
    gcode_ref: str = Field(default="", max_length=200)
    gcode_sha256: str = Field(default="", max_length=64)
    slicer_engine: str = Field(default="", max_length=40)
    gcode_canonical_ref: str = Field(default="", max_length=200)
    gcode_verdict: str = Field(default="", max_length=20)
    spool_id: str = Field(default="", max_length=80)
    queue_task_id: int = Field(default=0, ge=0)
    preflight: dict = Field(default_factory=dict)
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


def _apply_inspection(record: dict, data: bytes,
                      lowered: str) -> dict:
    """Shared scan + validate + save over caller-supplied bytes.

    Extracted from inspect_model so library files (E:\\Mycelium,
    never copied to the fabrication dir) get the identical
    verdicts. Behavior for fabrication-dir models is unchanged:
    the same bytes flow through the same checks.
    """
    from .mesh3d import validate_mesh
    inspection = ModelInspection()
    if lowered.endswith(INSPECTABLE_SUFFIXES):
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
            verdict = validate_mesh(str(record.get("filename", "")),
                                    data=data)
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


def inspect_model(model_id: str) -> dict:
    """Geometric scan + mesh-validator verdict. UNKNOWN wherever
    the bytes do not actually determine the answer."""
    record = get_model(model_id)
    if record is None:
        raise WorkshopRefusedError("model not found")
    filename = str(record.get("filename", ""))
    lowered = filename.lower()
    try:
        data = _model_bytes(filename)
    except WorkshopRefusedError as error:
        raise error
    except ValueError as error:
        raise WorkshopRefusedError(str(error)) from error
    return _apply_inspection(record, data, lowered)


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
                  spool_id: str = "", actor: str = "web") -> dict:
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
    cleaned_spool = str(spool_id or "").strip()[:80]
    stamp = _now()
    job = FabJob(
        job_id=generate_fabjob_id(),
        model_id=record["model_id"],
        material_ref=str(material_ref or "")[:120],
        printer_id=cleaned_printer, profile=cleaned_profile,
        spool_id=cleaned_spool,
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
        if str(model.get("library_ref", "") or ""):
            data_blob = _library_model_bytes(
                str(model.get("library_ref", "")).split("/")[-1])
            verdict = validate_mesh(model["filename"],
                                    data=data_blob)
        else:
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
    prusa-console slices really through the local console;
    bambu-studio refuses as UNPROVEN; anything else refuses.
    Stores the G-code verdict alongside the artifact."""
    from .slicer3d import (SlicerUnavailable, check_slicer_request,
                           get_slicer, validate_gcode)
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
    cleaned_slicer = str(slicer or "test-slicer").strip().lower()
    try:
        if cleaned_slicer in ("prusa-console", "prusa"):
            from .local_slicer import ConsoleSlicer
            provider = ConsoleSlicer(engine="prusa")
            result = provider.slice(request)
            data["slicer_engine"] = "prusa"
        elif cleaned_slicer in ("bambu-studio", "bambu"):
            from .local_slicer import ConsoleSlicer
            provider = ConsoleSlicer(engine="bambu")
            result = provider.slice(request)
            data["slicer_engine"] = "bambu"
        else:
            provider = get_slicer(cleaned_slicer)
            result = provider.slice(request)
            data["slicer_engine"] = str(cleaned_slicer)[:40]
    except (ValueError, SlicerUnavailable,
            RuntimeError) as error:
        data["stage"] = "blocked"
        _history(data, "blocked", f"slicer refused: {error}")
        return _store_job(data)
    data["gcode_ref"] = result.gcode_ref
    data["gcode_sha256"] = result.sha256
    data["slicer"] = result.slicer
    try:
        from .local_slicer import canonical_gcode_name
        canonical = canonical_gcode_name(
            model["filename"],
            data.get("profile") or "draft-pla",
            str(model.get("sha256", ""))[:8])
        data["gcode_canonical_ref"] = f"gcode/{canonical}"
    except Exception:
        data["gcode_canonical_ref"] = ""
    try:
        verdict = validate_gcode(result.gcode_ref)
        data["gcode_verdict"] = str(verdict.verdict)
    except ValueError:
        data["gcode_verdict"] = "inconclusive"
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
    spool_id = str(data.get("spool_id", "") or "")
    slot = ""
    if spool_id:
        from .fabrication import list_spools
        try:
            spools = {spool.spool_id: spool
                      for spool in list_spools() or []}
        except Exception:
            spools = {}
        spool = spools.get(spool_id)
        if spool is not None:
            location = str(getattr(spool, "location", "") or "")
            slot = location.split("/")[-1][:12] if location else ""
    job = new_job(f"pjob-{_secrets.token_hex(4)}",
                  data["printer_id"], data["gcode_ref"],
                  data["gcode_sha256"],
                  data.get("profile") or "draft-pla", actor[:80],
                  proposal_id=f"wrt-{_secrets.token_hex(4)}",
                  spool_id=spool_id, slot=slot)
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


def _cancel_printing_job(data: dict, reason: str = "") -> dict:
    """Stop hardware for a printing job, then close its task.

    Step 1 (physical): bounded stop + IDLE confirm via a fresh
    session. Unreachable/unconfirmed refuses — never pretend.
    Step 2 (books): close the linked print.execute task as
    cancelled (queued/assigned only). Returns the updated data.
    """
    from .bambu_exec import (BambuExecError, BambuExecUnavailable,
                             stop_bambu_job)
    job_id = str(data.get("job_id", ""))
    with _bambu_session(timeout=60.0) as adapter:
        try:
            stopped = stop_bambu_job(adapter)
        except (BambuExecError, BambuExecUnavailable) as error:
            raise WorkshopRefusedError(
                f"printer-stop mislukt ({error}); job blijft "
                f"printing tot hardware-bevestiging") from error
    data["updated_at"] = _now()
    _history(data, "cancelling",
             f"printer gestopt ({stopped.get('sequence_id', '?')})")
    linked = int(data.get("queue_task_id", 0) or 0)
    if linked:
        close_print_task(linked, "cancelled",
                         f"fab job {job_id} cancelled"
                         + (f": {reason[:120]}" if reason else ""))
    return data


def cancel_job(job_id: str, *, reason: str = "") -> dict:
    """Cancel one fab job + its live queue task (M3.5/BIG57).

    Idempotent: cancelling a cancelled job returns it (and still
    syncs a possibly live task). Verified/printed outcomes refuse.
    M4.2: a job in stage printing stops the hardware first
    (bounded, confirmed IDLE) and closes the linked queue task;
    unreachable printers refuse instead of pretending.
    """
    data = get_fabjob(job_id)
    if data is None:
        raise WorkshopRefusedError("fab job not found")
    if data["stage"] == "verified":
        raise WorkshopRefusedError(
            "job is verified; record the outcome instead")
    if data["stage"] in ("printed-simulated", "observed",
                         "verifying"):
        raise WorkshopRefusedError(
            "printed plastic cannot be un-printed; record the "
            "outcome instead of cancelling")
    if data["stage"] == "printing":
        _cancel_printing_job(data, reason=reason)
    linked = int(data.get("queue_task_id", 0) or 0)
    linked = int(data.get("queue_task_id", 0) or 0)
    if linked:
        from fastapi import HTTPException as _HTTPException
        from . import main as _main
        try:
            _main._cancel_task(
                linked,
                reason=f"fab job {job_id} cancelled"
                       + (f": {reason[:120]}" if reason else ""),
                actor="fabjob-cancel")
        except _HTTPException as error:
            if error.status_code == 404:
                pass
            else:
                detail = str(getattr(error, "detail", ""))[:160]
                raise WorkshopRefusedError(
                    f"queue-taak #{linked} houdt de job vast "
                    f"({detail}); annuleren onmogelijk tot "
                    f"afronding of lease-afloop") from error
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


# -- library scan (M1/BIG57) ----------------------------------------------
# Local model library on E:\Mycelium\bibliotheek. Large files stay
# put exactly once; only hashes + metadata enter the registry.
# INVENTory file_ records are proposed (never auto-created):
# approval happens in /writes through the existing gates.

LIBRARY_SUBDIR = "bibliotheek"
LIBRARY_SCAN_MAX_FILES = 50
LIBRARY_SUBDIRS = ("bibliotheek", "profielen", "gcode", "archief")


def library_scan_dir() -> str:
    """Library folder. No creation here (probe/setup own that)."""
    import os as _os
    from .forge import library_root
    return _os.path.join(library_root(), LIBRARY_SUBDIR)


def setup_library() -> dict:
    """Ensure the library folder layout. Explicit action only:
    called from the setup route/button, never from a probe."""
    import os as _os
    from .forge import library_root
    root = library_root()
    made = []
    here = []
    for sub in LIBRARY_SUBDIRS:
        path = _os.path.join(root, sub)
        if _os.path.isdir(path):
            here.append(sub)
            continue
        _os.makedirs(path, exist_ok=True)
        made.append(sub)
    return {"root": root, "created": made, "existing": here}


def _check_library_relname(value: str) -> str:
    """Flat library filename: no paths, URLs or schemes, known
    model suffix. Mirrors the fab-dir filename discipline."""
    if not isinstance(value, str):
        raise WorkshopRefusedError(
            "library name must be text")
    text = value.strip().replace("\\", "/")
    if not text or len(text) > 200:
        raise WorkshopRefusedError(
            "library name must be 1..200 characters")
    lowered = text.lower()
    if "://" in lowered or text.startswith("/"):
        raise WorkshopRefusedError(
            "library name must be a plain filename")
    if ".." in text or "/" in text:
        raise WorkshopRefusedError(
            "library subfolders are not scanned; flat names only")
    if not lowered.endswith(MODEL_SUFFIXES):
        raise WorkshopRefusedError(
            f"unsupported model format; expected one of "
            f"{list(MODEL_SUFFIXES)}")
    if text.startswith("."):
        raise WorkshopRefusedError(
            "hidden files are never scanned")
    return text


def _library_model_bytes(relname: str) -> bytes:
    """Read one validated library file, capped. The file stays in
    the library; nothing is copied to the fabrication dir."""
    import os as _os
    from .mesh3d import MAX_MESH_BYTES
    cleaned = _check_library_relname(relname)
    root = _os.path.abspath(library_scan_dir())
    path = _os.path.abspath(_os.path.join(root, cleaned))
    if path != root and not path.startswith(root + _os.sep):
        raise WorkshopRefusedError(
            "library file escapes the library folder")
    if not _os.path.isfile(path):
        raise WorkshopRefusedError(
            f"library file '{cleaned}' not found; refusing")
    size = _os.path.getsize(path)
    if size <= 0:
        raise WorkshopRefusedError("library file is empty; refusing")
    if size > MAX_MESH_BYTES:
        raise WorkshopRefusedError(
            f"library file is {size} bytes (max {MAX_MESH_BYTES}); "
            f"refusing")
    with open(path, "rb") as handle:
        return handle.read(MAX_MESH_BYTES + 1)


def register_library_model(relname: str, *,
                           actor: str = "scan",
                           license: dict | ModelLicense | None = None,
                           ) -> dict:
    """Register one library file by reference. Hashes + inspects
    the bytes in place; dedupes by sha256 like inbox registration.
    The large file is never copied.

    Optional ``license`` (operator-supplied dict): external origin
    always requires actual license terms — vague names and
    license-less imports are refused, never assumed.
    """
    import hashlib as _hashlib
    cleaned_actor = str(actor or "scan").strip()[:40]
    cleaned = _check_library_relname(relname)
    cleaned_license = clean_library_license(license)
    data = _library_model_bytes(cleaned)
    digest = _hashlib.sha256(data).hexdigest()
    if digest in known_model_shas():
        raise WorkshopRefusedError(
            "same model bytes already registered; replay refused")
    stamp = _now()
    model = WorkshopModel(
        model_id=generate_model_id(), filename=cleaned,
        library_ref=f"{LIBRARY_SUBDIR}/{cleaned}",
        mime_type=_mime_for(cleaned), size_bytes=len(data),
        sha256=digest, source="library", status="imported",
        license=cleaned_license,
        created_at=stamp, updated_at=stamp)
    record = model.model_dump(mode="json")
    record["_actor"] = cleaned_actor
    _save("workshop_models", model.model_id, "model_id",
          record, stamp)
    return _apply_inspection(record, data, cleaned.lower())


def attach_library_license(model_id: str,
                           license: dict | ModelLicense, *,
                           actor: str = "operator") -> dict:
    """Attach (or correct) license info on an existing model
    record. Operator flow: scan first, copy the actual terms from
    the source page, then attach. Empty license names are refused
    here: attaching means declaring real terms."""
    cleaned_actor = str(actor or "operator").strip()[:40]
    if isinstance(license, dict) and not str(
            license.get("license", "") or "").strip():
        raise WorkshopRefusedError(
            "licentie vastleggen vereist een daadwerkelijke "
            "licentienaam (geen 'open source')")
    cleaned_license = clean_library_license(license)
    if cleaned_license is None:  # pragma: no cover - guarded above
        raise WorkshopRefusedError(
            "licentie vastleggen vereist licentiegegevens")
    record = get_model(model_id)
    if record is None:
        raise WorkshopRefusedError(
            f"model '{model_id}' unknown; refusing")
    record["license"] = cleaned_license.model_dump(mode="json")
    record["updated_at"] = _now()
    record["_actor"] = cleaned_actor
    _save("workshop_models", str(record.get("model_id", model_id)),
          "model_id", record, str(record.get("created_at", "")))
    return record


def library_models(limit: int = 50) -> list[dict]:
    """Registered models with source library. Read-only."""
    return [item for item in _list("workshop_models", limit)
            if str(item.get("source", "")) == "library"]


def scan_library(*, actor: str = "scan") -> dict:
    """Scan the library folder once. Bounded, flat, explicit.

    Returns counts + per-file outcomes. Missing folder refuses
    with a setup hint; per-file problems are collected, never
    raised. Never writes to INVENTory (proposals are separate).
    """
    import os as _os
    cleaned_actor = str(actor or "scan").strip()[:40]
    root = library_scan_dir()
    if not _os.path.isdir(root):
        raise WorkshopRefusedError(
            "bibliotheekmap ontbreekt; richt eerst in via setup")
    try:
        entries = sorted(_os.listdir(root))
    except OSError as error:
        raise WorkshopRefusedError(
            f"bibliotheekmap onleesbaar ({error})")
    candidates = [name for name in entries
                  if _os.path.isfile(_os.path.join(root, name))]
    out: dict = {"scanned": 0, "registered": [], "duplicates": [],
                 "refused": [], "skipped": []}
    for name in candidates:
        if out["scanned"] >= LIBRARY_SCAN_MAX_FILES:
            out["skipped"].append(name[:120])
            continue
        out["scanned"] += 1
        try:
            model = register_library_model(
                name, actor=cleaned_actor)
        except WorkshopRefusedError as error:
            text = str(error)
            if "already registered" in text:
                out["duplicates"].append(name[:120])
            else:
                out["refused"].append(
                    {"file": name[:120], "reason": text[:160]})
            continue
        out["registered"].append({
            "model_id": model["model_id"],
            "filename": model["filename"],
            "sha256": model["sha256"],
            "verdict": str(model.get("inspection", {}).get(
                "mesh_verdict", "UNKNOWN")),
        })
    return out


def _file_kind_for(filename: str) -> str:
    lowered = str(filename or "").lower()
    if lowered.endswith((".stl", ".obj", ".3mf")):
        return "mesh"
    return "other"


def library_file_fields(model: dict) -> dict:
    """INVENTory file_ create fields for one library model.

    Used to build write proposals (approval in /writes); creates
    nothing by itself. License info on the model record travels
    along: structured under metadata["license"] (all nine fields)
    plus one human-readable provenance line in the description.
    (Execution provenance itself is set by the writes flow.)
    """
    filename = str(model.get("filename", ""))[:200]
    sha256 = str(model.get("sha256", ""))
    if len(sha256) != 64:
        raise WorkshopRefusedError(
            "model has no sha256; cannot propose file record")
    inspection = model.get("inspection", {}) or {}
    description = (
        f"Bibliotheekmodel {filename} "
        f"(mesh: {inspection.get('mesh_verdict', 'UNKNOWN')})"
    )
    metadata = {
        "artifact_ref": str(model.get("library_ref", ""))[:200],
        "workshop_model_id": str(model.get("model_id", ""))[:80],
        "mesh_verdict": str(inspection.get(
            "mesh_verdict", "UNKNOWN"))[:20],
    }
    raw_license = model.get("license") or {}
    if isinstance(raw_license, dict) and str(
            raw_license.get("license", "") or "").strip():
        block = {key: raw_license.get(key) for key in
                 ("source_library", "source_url", "author",
                  "license", "commercial_use", "remix_allowed",
                  "attribution_required", "original_model_url",
                  "imported_at")}
        metadata["license"] = block
        origin = str(block.get("source_library") or "").strip()
        maker = str(block.get("author") or "").strip()
        terms = str(block.get("license") or "").strip()
        sale = block.get("commercial_use")
        sale_text = ("verkoop: toegestaan" if sale is True
                     else "verkoop: NIET toegestaan" if sale is False
                     else "verkoop: onbekend — eerst licentie lezen")
        description += (f" | Herkomst: {origin or 'onbekend'}"
                        + (f" ({maker})" if maker else "")
                        + f" · Licentie: {terms} · {sale_text}")
    return {
        "name": filename,
        "sha256": sha256,
        "description": description[:5000],
        "file_kind": _file_kind_for(filename),
        "mime_type": str(model.get("mime_type", ""))[:200],
        "size_bytes": int(model.get("size_bytes", 0) or 0),
        "status": "available",
        "metadata": metadata,
    }


def verdict_oordeel(mesh_verdict: str) -> str:
    """One plain-language inspection sentence. Never permission:
    a valid verdict is not a print approval."""
    verdict = str(mesh_verdict or "UNKNOWN").strip().lower()
    if verdict == "valid":
        return ("Geometrie in orde bevonden (geen printgarantie).")
    if verdict == "invalid":
        return ("Geometrie afgekeurd — niet slicen in deze staat.")
    if verdict == "inconclusive":
        return ("Geen oordeel mogelijk — niet inspecteerbaar "
                "formaat of lege geometrie.")
    return ("Nog niet geïnspecteerd.")


# -- print queue (M3/BIG57) -------------------------------------------------
# Persistent ordered queue on the EXISTING tasks table (no second
# queue): print.execute tasks with printer.start capability, gated
# by exact YES (route-verified) + live pre-flight. Execution
# itself arrives in M4; here tasks wait honestly for hardware.

PRINT_TASK_KIND = "print.execute"
PRINT_TASK_CAPABILITY = "printer.start"


def _filament_grams_from_gcode(text: str, material: str,
                               ) -> tuple[float | None, str]:
    """Real filament estimate from slicer footer lines.

    Prefers `; filament used [cm3]` x density (the `[g]` footer
    line reads 0.00 on real output and is never trusted).
    Returns (grams|None, basis).
    """
    import re as _re
    from .fabrication import FILAMENT_DENSITIES
    density = FILAMENT_DENSITIES.get(str(material or ""))
    cm3 = None
    for line in str(text or "").splitlines()[-400:]:
        match = _re.search(
            r";\s*filament used \[cm3\]\s*=\s*([0-9]+(?:\.[0-9]+)?)",
            line)
        if match:
            try:
                cm3 = float(match.group(1))
            except ValueError:
                cm3 = None
    if cm3 is not None and density:
        return round(cm3 * float(density), 2), "slicer-cm3-x-dichtheid"
    return None, "onbekend (geen cm3-regel of dichtheid)"


def set_job_spool(job_id: str, spool_id: str) -> dict:
    """Pin a filament spool to a fab job. Spool must exist;
    compatibility is enforced at pre-flight, not here."""
    from .fabrication import FabricationRefusedError, list_spools
    data = get_fabjob(job_id)
    if data is None:
        raise WorkshopRefusedError("fab job not found")
    if data.get("stage") in ("queued", "approved", "cancelled",
                             "verified"):
        raise WorkshopRefusedError(
            f"job is {data.get('stage')}; spool staat vast")
    cleaned = str(spool_id or "").strip()[:80]
    if cleaned:
        try:
            known = {spool.spool_id for spool in list_spools() or []}
        except FabricationRefusedError as error:
            raise WorkshopRefusedError(str(error)) from error
        if cleaned not in known:
            raise WorkshopRefusedError("spool not found; refusing")
    data["spool_id"] = cleaned
    data["updated_at"] = _now()
    _history(data, str(data.get("stage") or "designed"),
             f"spool {cleaned or '—'} gekozen")
    return _store_job(data)


def preflight_print_job(job_id: str) -> dict:
    """Live pre-flight gate for one fab job. Read-only except for
    storing the outcome on the job record for UI display.

    Returns {"ok", "blockers", "warnings", "estimate_g",
    "estimate_basis"}. Blockers refuse enqueue; warnings inform.
    Every check re-reads live state (bytes re-hashed, verdict
    re-checked, spool re-read) — never cached trust.
    """
    import hashlib as _hashlib
    from .fabrication import (FILAMENT_DENSITIES, FabricationRefusedError,
                              list_spools)
    from .mesh3d import read_artifact_bytes
    from .printer3d import list_stored_printers
    from .slicer3d import check_profile, validate_gcode
    data = get_fabjob(job_id)
    if data is None:
        raise WorkshopRefusedError("fab job not found")
    blockers: list[str] = []
    warnings: list[str] = []
    estimate: float | None = None
    basis = "onbekend"
    profile_name = str(data.get("profile") or "draft-pla")
    try:
        settings = check_profile(profile_name)
    except ValueError:
        settings = {}
        blockers.append(f"onbekend profiel '{profile_name[:40]}'")
    material = str(settings.get("material", "")) if settings else ""
    if data.get("slicer_engine") == "test-slicer":
        blockers.append("TEST-G-code — nooit naar een printer")
    gcode_ref = str(data.get("gcode_ref", "") or "")
    want_sha = str(data.get("gcode_sha256", "") or "")
    text = ""
    if not gcode_ref or len(want_sha) != 64:
        blockers.append("job heeft geen G-code met sha")
    else:
        try:
            raw = read_artifact_bytes(gcode_ref)
        except ValueError as error:
            raw = b""
            blockers.append(f"G-code onleesbaar ({error})")
        if raw:
            got = _hashlib.sha256(raw).hexdigest()
            if got != want_sha:
                blockers.append(
                    "G-code gewijzigd sinds slice (sha mismatch); "
                    "opnieuw slicen")
            else:
                try:
                    text = raw.decode("ascii")
                except UnicodeDecodeError:
                    blockers.append(
                        "G-code niet als ASCII leesbaar")
    verdict = str(data.get("gcode_verdict", "") or "")
    if verdict and verdict not in ("safe", "inconclusive"):
        blockers.append(f"G-code-verdict '{verdict}' blokkeert")
    elif not verdict and text:
        try:
            live = validate_gcode(gcode_ref)
            verdict = str(live.verdict)
            data["gcode_verdict"] = verdict
        except ValueError:
            verdict = "inconclusive"
        if verdict not in ("safe", "inconclusive"):
            blockers.append(
                f"live G-code-verdict '{verdict}' blokkeert")
    printer_id = str(data.get("printer_id", "") or "")
    printer_model = ""
    printer_simulated = False
    if not printer_id:
        blockers.append("geen printer gekozen")
    else:
        from .printer3d import adapter_for_printer
        from .printer3d import list_stored_printers
        try:
            devices = {str(printer.printer_id or ""): printer
                       for printer in list_stored_printers() or []}
        except ValueError:
            devices = {}
        if printer_id not in devices:
            blockers.append(
                f"printer '{printer_id[:40]}' niet geregistreerd")
        else:
            device = devices[printer_id]
            printer_model = str(getattr(device, "model", "") or "")
            try:
                adapter = adapter_for_printer(printer_id)
                printer_simulated = bool(
                    adapter is not None and getattr(
                        adapter, "name", "") == "simulated-test")
            except (ValueError, AttributeError):
                printer_simulated = False
            if printer_simulated:
                warnings.append(
                    "printer is SIMULATED — uitvoering wordt een "
                    "droogloop, geen echte print")
            allowed = list(settings.get("printers", []) or []) \
                if settings else []
            if allowed and printer_model and \
                    printer_model not in allowed:
                blockers.append(
                    f"profiel '{profile_name[:40]}' ondersteunt "
                    f"'{printer_model[:40]}' niet "
                    f"(toegestaan: {', '.join(allowed[:6])})")
            elif allowed and not printer_model:
                warnings.append(
                    "printer heeft geen model; "
                    "profiel-compat niet controleerbaar")
            elif not allowed:
                warnings.append(
                    "profiel doet geen printer-uitspraak "
                    "(universeel)")
    spool_id = str(data.get("spool_id", "") or "")
    spool = None
    if not spool_id:
        blockers.append("geen spoel gekozen")
    else:
        try:
            spools = {spool.spool_id: spool
                      for spool in list_spools() or []}
        except FabricationRefusedError:
            spools = {}
        spool = spools.get(spool_id)
        if spool is None:
            blockers.append("gekozen spoel bestaat niet meer")
        else:
            if spool.material != material and material:
                blockers.append(
                    f"spoel is {spool.material}, profiel wil "
                    f"{material}")
            compat = list(getattr(spool, "compatible_profiles",
                                  None) or [])
            if compat and profile_name not in compat:
                blockers.append(
                    f"profiel '{profile_name[:40]}' staat niet in "
                    f"compatibele profielen van de spoel")
            location = str(getattr(spool, "location", "") or "")
            if "/" in location:
                pinned_printer = location.split("/")[0]
                if pinned_printer != printer_id:
                    blockers.append(
                        f"spoel hangt aan '{pinned_printer[:40]}', "
                        f"job wil '{printer_id[:40]}'")
            elif location:
                warnings.append(
                    f"spoel staat als '{location[:40]}' (niet aan "
                    f"deze printer toegewezen)")
            else:
                warnings.append("spoel heeft geen locatie")
            if text and spool is not None:
                estimate, basis = _filament_grams_from_gcode(
                    text, spool.material)
                if estimate is not None:
                    remaining = float(
                        spool.weight_remaining_g or 0.0)
                    if remaining < estimate:
                        blockers.append(
                            f"spoel te licht ({remaining:g}g < "
                            f"{estimate:g}g nodig)")
                else:
                    warnings.append(
                        "filamentschatting onbekend; controleer "
                        "spoel handmatig")
    outcome = {"ok": not blockers, "blockers": blockers,
               "warnings": warnings, "estimate_g": estimate,
               "estimate_basis": basis}
    try:
        data["preflight"] = outcome
        data["updated_at"] = _now()
        _store_job(data)
    except Exception:
        pass
    return outcome


def enqueue_print_job(job_id: str, *, actor: str,
                      approved_proposal: dict) -> dict:
    """Queue one approved print as a print.execute task (M3).

    The route verifies the YES (approved status, printer.execute
    mutation, sha binding) and passes the loaded proposal in;
    this function re-checks everything from the dict (defense in
    depth), runs live pre-flight, refuses duplicates, and queues
    through the EXISTING tasks table. No execution here.
    """
    from . import main as _main
    from .database import connection
    from .database import load as _load
    from .schemas import TaskCreate
    data = get_fabjob(job_id)
    if data is None:
        raise WorkshopRefusedError("fab job not found")
    with connection() as db:
        rows = db.execute(
            "SELECT id, payload FROM tasks WHERE kind=? AND "
            "status IN ('queued','assigned')",
            (PRINT_TASK_KIND,)).fetchall()
    for row in rows:
        try:
            existing_payload = _load(row["payload"] or "{}")
        except ValueError:
            continue
        if isinstance(existing_payload, dict) and \
                existing_payload.get("print_job_id") == job_id:
            if not data.get("queue_task_id"):
                data["queue_task_id"] = int(row["id"])
                data["updated_at"] = _now()
                _store_job(data)
            return {"task_id": int(row["id"]), "existing": True,
                    "job_id": job_id}
    if data.get("stage") != "proposed":
        raise WorkshopRefusedError(
            f"job is {data.get('stage')}; enqueue needs proposed "
            f"(voorstel + YES eerst)")
    proposal = dict(approved_proposal or {})
    if str(proposal.get("status", "")) != "approved":
        raise WorkshopRefusedError(
            "voorstel is niet approved; exact YES eerst")
    record = proposal.get("record", {}) or {}
    if isinstance(record, str):
        try:
            record = _load(record)
        except ValueError:
            record = {}
    if str(record.get("mutation_type", "")) != "printer.execute":
        raise WorkshopRefusedError(
            "voorstel is geen printer.execute; refusing")
    payload = record.get("payload", {}) or {}
    if str(payload.get("gcode_sha256", "")) != \
            str(data.get("gcode_sha256", "")):
        raise WorkshopRefusedError(
            "voorstel-sha komt niet overeen met job-G-code; "
            "opnieuw voorstellen")
    gate = preflight_print_job(job_id)
    if not gate.get("ok"):
        raise WorkshopRefusedError(
            "pre-flight blokkeert: "
            + "; ".join(gate.get("blockers", [])[:4])[:300])
    spool_id = str(data.get("spool_id", "") or "")
    slot = ""
    spool_material = ""
    spool_weight = 0.0
    if spool_id:
        from .fabrication import FabricationRefusedError
        from .fabrication import list_spools
        try:
            spools = {spool.spool_id: spool
                      for spool in list_spools() or []}
        except FabricationRefusedError:
            spools = {}
        spool = spools.get(spool_id)
        if spool is not None:
            location = str(getattr(spool, "location", "") or "")
            slot = location.split("/")[-1][:12] if location else ""
            spool_material = str(getattr(spool, "material", "")
                                 or "")[:20]
            try:
                spool_weight = float(
                    getattr(spool, "weight_remaining_g", 0.0)
                    or 0.0)
            except (TypeError, ValueError):
                spool_weight = 0.0
    created = _main.create_task(TaskCreate(
        kind=PRINT_TASK_KIND,
        payload={"print_job_id": job_id,
                 "gcode_ref": str(data.get("gcode_ref", "")),
                 "gcode_sha256": str(data.get("gcode_sha256", "")),
                 "profile": str(data.get("profile", "")),
                 "printer_id": str(data.get("printer_id", "")),
                 "spool_id": spool_id,
                 "slot": slot,
                 "spool_material": spool_material,
                 "spool_weight_g": spool_weight,
                 "proposal_id": str(data.get("proposal_id", ""))},
        required_capabilities=[PRINT_TASK_CAPABILITY]))
    task_id = int(created.get("id", 0))
    data["queue_task_id"] = task_id
    data["stage"] = "queued"
    data["updated_at"] = _now()
    _history(data, "queued",
             f"print.execute-taak #{task_id} "
             f"({str(actor or 'web')[:40]})")
    _store_job(data)
    return {"task_id": task_id, "existing": False,
            "job_id": job_id}

def _bambu_session(timeout: float = 45.0):
    """Fresh bounded printer session as a context manager.

    Connects, waits for one valid push, yields the adapter,
    disconnects on exit. No publish except through explicit
    stop/execute flows (never here).
    """
    import contextlib as _contextlib

    @_contextlib.contextmanager
    def _session():
        from .printer3d import (BambuPrinterAdapter,
                                PrinterUnavailable,
                                bambu_config_from_env)
        config, missing = bambu_config_from_env()
        if missing:
            raise WorkshopRefusedError(
                "printer niet geconfigureerd (" + ", ".join(missing)
                + "); zet env-vars, geen harde waarden")
        adapter = BambuPrinterAdapter(
            config["host"], config["port"], config["username"],
            config["access_code"], config["serial"], "")
        try:
            adapter._connect_mqtt()
            if not adapter.wait_for_push(timeout=timeout):
                raise WorkshopRefusedError(
                    "printer zwijgt binnen budget; status onbekend")
            yield adapter
        except PrinterUnavailable as error:
            raise WorkshopRefusedError(str(error)) from error
        finally:
            adapter.disconnect()

    return _session()


def observe_print_job(job_id: str, *, timeout: float = 45.0,
                      actor: str = "web") -> dict:
    """One bounded observation round for a printing job (M4.2).

    Reads live telemetry, matches OUR file stem, maps state.
    Mutates the job only on positive match (stage/history);
    completion itself stays behind finalize (explicit).
    """
    data = get_fabjob(job_id)
    if data is None:
        raise WorkshopRefusedError("fab job not found")
    if str(data.get("stage", "")) not in ("printing", "proposed",
                                          "queued", "approved"):
        raise WorkshopRefusedError(
            f"job is {data.get('stage')}; observeren heeft alleen "
            f"zin rond uitvoering")
    stem = str(data.get("gcode_ref", "") or "")
    stem = stem.rsplit(".", 1)[0].split("/")[-1][:60]
    if not stem:
        raise WorkshopRefusedError("job heeft geen G-code")
    with _bambu_session(timeout=timeout) as adapter:
        live = adapter._live_status()
    job_name = str(live.get("job_name", "") or "")
    gcode_state = str(live.get("gcode_state", "") or "")
    mine = bool(job_name) and stem.lower() in job_name.lower()
    outcome = {"match": bool(mine), "gcode_state": gcode_state,
               "job_name": job_name[:120],
               "telemetry": live}
    if not mine:
        outcome["state"] = "not-ours"
        return outcome
    if gcode_state in ("PREPARE", "RUNNING", "PAUSE", "SLICING"):
        data["stage"] = "printing"
        data["updated_at"] = _now()
        _history(data, "printing",
                 f"printer actief ({gcode_state}, "
                 f"{live.get('progress_pct', '?')}%)")
        _store_job(data)
        outcome["state"] = "running"
    elif gcode_state == "FINISH":
        outcome["state"] = "finished-pending"
    elif gcode_state == "FAILED":
        data["stage"] = "blocked"
        data["updated_at"] = _now()
        _history(data, "blocked",
                 f"printer meldt FAILED (fout "
                 f"{live.get('print_error', '?')})")
        _store_job(data)
        outcome["state"] = "failed"
    else:
        outcome["state"] = "unknown"
    return outcome


def close_print_task(task_id: int, to_status: str,
                     note: str = "") -> dict:
    """Close one print.execute task directly (M4.2 cancel path).

    Only queued/assigned print.execute tasks; conditional update
    so races resolve honestly. Terminal tasks refuse.
    """
    from . import main as _main
    from .database import connection
    if to_status not in ("cancelled", "failed"):
        raise WorkshopRefusedError(
            "close target must be cancelled/failed")
    try:
        task_id = int(task_id)
    except (TypeError, ValueError):
        raise WorkshopRefusedError("task_id invalid") from None
    with connection() as db:
        row = db.execute("SELECT kind, status FROM tasks WHERE "
                         "id=?", (task_id,)).fetchone()
        if row is None:
            raise WorkshopRefusedError("task not found")
        if str(row["kind"] or "") != PRINT_TASK_KIND:
            raise WorkshopRefusedError(
                "only print.execute tasks close this way")
        if str(row["status"] or "") not in ("queued", "assigned"):
            raise WorkshopRefusedError(
                f"task is {row['status']}; terminal/bekend "
                f"blijft staan")
        changed = db.execute(
            "UPDATE tasks SET status=?, completed_at=? WHERE id=? "
            "AND status IN ('queued','assigned')",
            (to_status, _now(), task_id)).rowcount
    if not changed:
        raise WorkshopRefusedError("task already moved on")
    _main.emit_event(f"task.{to_status}",
                     f"Print task {task_id} {to_status}"
                     f"{(': ' + note[:160]) if note else ''}",
                     task_id=str(task_id))
    return {"id": task_id, "status": to_status}


def finalize_print_task(task_id: int, *, actor: str = "web") -> dict:
    """Complete one print task on FRESH FINISH evidence (M4.2).

    Verifies right now (bounded observe): FINISH for OUR file,
    else refuses — no stale completion. Then completes the queue
    task as its assigned node, deducts the spool exactly once
    (key print:{task_id}), and marks the job printed. Camera
    verification continues separately (existing verify path).
    """
    from . import main as _main
    from .database import connection
    from .database import load as _load
    from .fabrication import deduct_spool
    from .schemas import TaskResult
    try:
        task_id = int(task_id)
    except (TypeError, ValueError):
        raise WorkshopRefusedError("task_id invalid") from None
    with connection() as db:
        row = db.execute("SELECT * FROM tasks WHERE id=?",
                         (task_id,)).fetchone()
    if row is None:
        raise WorkshopRefusedError("task not found")
    if str(row["kind"] or "") != PRINT_TASK_KIND:
        raise WorkshopRefusedError("only print.execute finalizes")
    if str(row["status"] or "") != "assigned":
        raise WorkshopRefusedError(
            f"task is {row['status']}; finalize needs an assigned "
            f"(claimed) task")
    try:
        payload = _load(row["payload"] or "{}")
    except ValueError:
        raise WorkshopRefusedError(
            "task payload unreadable") from None
    job_id = str((payload or {}).get("print_job_id", "") or "")
    data = get_fabjob(job_id)
    if data is None:
        raise WorkshopRefusedError("fab job for task not found")
    observed = observe_print_job(job_id, actor=actor or "finalize")
    if not observed.get("match") or \
            observed.get("state") != "finished-pending":
        raise WorkshopRefusedError(
            "geen verse FINISH voor deze print "
            f"({observed.get('gcode_state', '?')}); "
            f"alleen echte completion rondt af")
    telemetry = dict(observed.get("telemetry", {}) or {})
    assigned = str(row["assigned_node_id"] or "")
    _main._complete_task(
        task_id,
        TaskResult(success=True, result={
            "summary": "print FINISH observed on device",
            "telemetry": telemetry,
            "proposal_id": str(data.get("proposal_id", "")),
            "gcode_sha256": str(data.get("gcode_sha256", ""))}),
        completing_node_id=assigned)
    estimate = (data.get("preflight", {}) or {}).get("estimate_g")
    try:
        grams = float(estimate) if estimate is not None else 0.0
    except (TypeError, ValueError):
        grams = 0.0
    if grams <= 0:
        raise WorkshopRefusedError(
            "geen filamentschatting opgeslagen; deductie "
            "onmogelijk zonder hoeveelheid")
    deducted = deduct_spool(
        str(data.get("spool_id", "") or ""), grams,
        reason=f"print:{task_id}", usage_key=f"print:{task_id}")
    data["stage"] = "printed"
    data["updated_at"] = _now()
    _history(data, "printed",
             f"FINISH bevestigd; taak #{task_id} completed; "
             f"{grams:g}g afgeschreven")
    _store_job(data)
    return {"task_id": task_id, "status": "completed",
            "deducted": deducted, "telemetry": telemetry}
