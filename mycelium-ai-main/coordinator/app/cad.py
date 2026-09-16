"""CAD foundation (BIG #11-15, Phase 4).

CadDocument → parts → parametric operations → derived mesh.
External CAD executors (OpenSCAD/FreeCAD/Blender) exist as
adapters with explicit requirements — UNAVAILABLE until a
reviewed local runtime exists. The only executing adapter is
the procedural box builder (pure math → facets → the
existing derived-mesh path).

External executor boundary (when one ever lands):
allow-list → proposal → approval → sandbox → result →
verification. This module spawns no external processes.
"""

import secrets
import time

from pydantic import BaseModel, Field

from .inventory_read import Provenance

CAD_OPS = (
    "box",
    "cylinder",
    "transform",
    "advanced",
)

CAD_ADAPTERS = {
    "procedural": "IMPLEMENTED",
    "openscad": "UNAVAILABLE",
    "freecad": "UNAVAILABLE",
    "blender": "UNAVAILABLE",
}

CAD_ADAPTER_REQUIREMENTS = {
    "procedural": "built in; pure-math box/cylinder facets, "
                   "no external binary",
    "openscad": "reviewed local runtime required: pinned "
                 "binary, fixed argv allow-list, bounded stdout "
                 "capture, no network. Not present.",
    "freecad": "reviewed local runtime required (see openscad). "
                "Not present.",
    "blender": "reviewed local runtime required (see openscad). "
                "Not present.",
}


class CadRefusedError(ValueError):
    """Fail-closed CAD validation."""


def now() -> str:
    import datetime
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def generate_document_id() -> str:
    return f"cad_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


class CadParameter(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    value: float
    unit: str = Field(default="mm", max_length=10)


class CadOperation(BaseModel):
    op_id: str = Field(min_length=1, max_length=80)
    op: str = Field(min_length=1, max_length=20)
    params: dict = Field(default_factory=dict)
    adapter: str = Field(default="procedural", max_length=20)
    created_at: str = Field(default="", max_length=80)


class CadPart(BaseModel):
    part_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    operations: list[CadOperation] = Field(
        default_factory=list, max_length=50)
    derived_ref: str = Field(default="", max_length=200)
    derived_sha256: str = Field(default="", max_length=80)


class CadDocument(BaseModel):
    document_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    parts: list[CadPart] = Field(default_factory=list,
                                 max_length=20)
    parameters: dict[str, float] = Field(default_factory=dict)
    status: str = Field(default="draft", max_length=20)
    provenance: Provenance
    created_at: str = Field(default="", max_length=80)
    updated_at: str = Field(default="", max_length=80)


def new_document(name: str, *,
                 provenance: Provenance | None = None
                 ) -> CadDocument:
    if not isinstance(name, str) or not name.strip():
        raise CadRefusedError("document needs a name")
    stamp = now()
    return CadDocument(
        document_id=generate_document_id(),
        name=name.strip()[:200], parts=[], parameters={},
        status="draft",
        provenance=provenance or Provenance(
            source_type="user-created", creator_id="cad",
            human_verified=False),
        created_at=stamp, updated_at=stamp)


def _check_box_params(params: dict) -> tuple[float, float, float]:
    try:
        dims = tuple(float(params.get(key, 0.0))
                     for key in ("w", "h", "d"))
    except (TypeError, ValueError):
        raise CadRefusedError(
            "box needs numeric w/h/d in mm")
    if any(not 0.1 <= dim <= 1000.0 for dim in dims):
        raise CadRefusedError("box dims must be 0.1..1000mm")
    if set(params) - {"w", "h", "d"}:
        raise CadRefusedError("box carries unexpected params")
    return dims


def _check_cylinder_params(params: dict) -> tuple[float, float]:
    try:
        radius = float(params.get("r", 0.0))
        height = float(params.get("h", 0.0))
    except (TypeError, ValueError):
        raise CadRefusedError(
            "cylinder needs numeric r/h in mm")
    if not 0.1 <= radius <= 500.0 or not 0.1 <= height <= 1000.0:
        raise CadRefusedError(
            "cylinder r must be 0.1..500mm, h 0.1..1000mm")
    if set(params) - {"r", "h", "segments"}:
        raise CadRefusedError(
            "cylinder carries unexpected params")
    try:
        segments = int(params.get("segments", 24))
    except (TypeError, ValueError):
        raise CadRefusedError("segments must be an integer")
    if not 6 <= segments <= 96:
        raise CadRefusedError("segments must be 6..96")
    return radius, height, segments


def add_part(document: CadDocument, name: str) -> CadDocument:
    if len(document.parts) >= 20:
        raise CadRefusedError("at most 20 parts per document")
    if not isinstance(name, str) or not name.strip():
        raise CadRefusedError("part needs a name")
    part = CadPart(
        part_id=f"part_{len(document.parts) + 1}_{secrets.token_hex(3)}",
        name=name.strip()[:200], operations=[])
    return document.model_copy(update={
        "parts": [*document.parts, part], "updated_at": now()})


def add_operation(document: CadDocument, part_id: str, op: str,
                  params: dict, *,
                  adapter: str = "procedural") -> CadDocument:
    """Append one validated operation. External adapters
    refuse (UNAVAILABLE); procedural box/cylinder validate
    params now and build facets on execute."""
    if op not in CAD_OPS:
        raise CadRefusedError(f"Unknown CAD op '{op}'")
    if adapter not in CAD_ADAPTERS:
        raise CadRefusedError(
            f"Unknown CAD adapter '{adapter}'")
    if adapter != "procedural":
        raise CadRefusedError(
            f"adapter '{adapter}' is "
            f"{CAD_ADAPTERS[adapter]}: "
            f"{CAD_ADAPTER_REQUIREMENTS[adapter]}")
    if op == "box":
        _check_box_params(params or {})
    elif op == "cylinder":
        _check_cylinder_params(params or {})
    elif op in ("transform", "advanced"):
        from .meshops import check_advanced_op
        from .mesh3d import check_transform
        raw = dict(params or {})
        sub = str(raw.pop("sub_op", ""))
        if op == "transform":
            try:
                check_transform(sub, raw)
            except Exception as error:
                raise CadRefusedError(f"bad transform: {error}")
        else:
            try:
                check_advanced_op(sub, raw)
            except Exception as error:
                raise CadRefusedError(
                    f"bad advanced op: {error}")
        params = {"sub_op": sub, **raw}
    parts = []
    found = False
    for part in document.parts:
        if part.part_id == part_id:
            if len(part.operations) >= 50:
                raise CadRefusedError(
                    "at most 50 operations per part")
            found = True
            part = part.model_copy(update={
                "operations": [*part.operations, CadOperation(
                    op_id=f"op_{len(part.operations) + 1}_"
                          f"{secrets.token_hex(3)}",
                    op=op, params=dict(params or {}),
                    adapter=adapter, created_at=now())]})
        parts.append(part)
    if not found:
        raise CadRefusedError("part not found")
    return document.model_copy(update={
        "parts": parts, "updated_at": now()})


def box_facets(width: float, height: float,
               depth: float) -> list:
    """Twelve facets of an origin-centred box. Pure math."""
    hx, hy, hz = width / 2.0, height / 2.0, depth / 2.0
    corners = [(-hx, -hy, -hz), (hx, -hy, -hz),
               (hx, hy, -hz), (-hx, hy, -hz),
               (-hx, -hy, hz), (hx, -hy, hz),
               (hx, hy, hz), (-hx, hy, hz)]
    # Outward-wound quads (right-hand rule): consistent
    # orientation keeps the signed-volume math exact.
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (2, 3, 7, 6), (0, 4, 7, 3), (1, 2, 6, 5)]
    facets = []
    for quad in quads:
        points = [corners[index] for index in quad]
        facets.append((points[0], points[1], points[2]))
        facets.append((points[0], points[2], points[3]))
    return facets


def cylinder_facets(radius: float, height: float,
                    segments: int = 24) -> list:
    """Side + caps of a Z-centred cylinder. Pure math."""
    import math
    half = height / 2.0
    ring = [(radius * math.cos(2 * math.pi * index / segments),
             radius * math.sin(2 * math.pi * index / segments))
            for index in range(segments)]
    facets = []
    for index in range(segments):
        first, second = ring[index], ring[(index + 1) % segments]
        facets.append(((first[0], first[1], -half),
                       (second[0], second[1], -half),
                       (first[0], first[1], half)))
        facets.append(((second[0], second[1], -half),
                       (second[0], second[1], half),
                       (first[0], first[1], half)))
        facets.append(((0.0, 0.0, half), first + (half,),
                       second + (half,)))
        facets.append(((0.0, 0.0, -half), second + (-half,),
                       first + (-half,)))
    return facets


def execute_document(document: CadDocument) -> CadDocument:
    """Build every part's facets through its operation stack
    (procedural only) and persist each part as a derived mesh
    working file. Returns the document with derived refs."""
    from .mesh3d import transform_facets, write_derived_mesh
    from .meshops import (extend_facets, mirror_facets,
                          orient_facets)
    parts = []
    for part in document.parts:
        facets: list | None = None
        for operation in part.operations:
            if operation.op == "box":
                width, height, depth = _check_box_params(
                    operation.params)
                facets = box_facets(width, height, depth)
            elif operation.op == "cylinder":
                radius, height, segments = \
                    _check_cylinder_params(operation.params)
                facets = cylinder_facets(radius, height,
                                         segments)
            elif operation.op == "transform":
                if facets is None:
                    raise CadRefusedError(
                        "transform needs a base shape first")
                from .mesh3d import check_transform
                sub = operation.params["sub_op"]
                cleaned = check_transform(
                    sub, {key: value for key, value in
                          operation.params.items()
                          if key != "sub_op"})
                facets = transform_facets(facets, sub, cleaned)
            else:
                if facets is None:
                    raise CadRefusedError(
                        "advanced op needs a base shape first")
                from .meshops import check_advanced_op
                sub = operation.params["sub_op"]
                cleaned = check_advanced_op(
                    sub, {key: value for key, value in
                          operation.params.items()
                          if key != "sub_op"})
                if sub == "mirror":
                    facets = mirror_facets(
                        facets, cleaned["plane"])
                elif sub == "extend":
                    facets = extend_facets(
                        facets, cleaned["axis"],
                        cleaned["delta_mm"])
                else:
                    facets, _ = orient_facets(facets)
        if facets is None:
            parts.append(part)
            continue
        ref, digest, _ = write_derived_mesh(
            document.document_id, "cad", facets)
        parts.append(part.model_copy(update={
            "derived_ref": ref, "derived_sha256": digest}))
    return document.model_copy(update={
        "parts": parts, "status": "built", "updated_at": now()})


def save_document(document: CadDocument) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO cad_documents
        (document_id, name, parts, parameters, operations,
         status, provenance, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(document_id) DO UPDATE SET
         parts=excluded.parts,
         parameters=excluded.parameters,
         operations=excluded.operations,
         status=excluded.status, updated_at=excluded.updated_at""",
                     (document.document_id, document.name,
                      dump([part.model_dump(mode="json")
                            for part in document.parts]),
                      dump(document.parameters),
                      dump([]),
                      document.status,
                      dump(document.provenance.model_dump(
                          mode="json")),
                      document.created_at, document.updated_at))


def _row_to_document(row) -> CadDocument:
    from .database import load
    return CadDocument(
        document_id=row["document_id"], name=row["name"],
        parts=[CadPart(**item) for item in load(row["parts"])],
        parameters=load(row["parameters"]),
        status=row["status"],
        provenance=Provenance(**load(row["provenance"])),
        created_at=row["created_at"],
        updated_at=row["updated_at"])


def get_document(document_id: str) -> CadDocument | None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM cad_documents WHERE "
                         "document_id=?", (document_id,)).fetchone()
    return _row_to_document(row) if row is not None else None


def adapter_status() -> list[dict]:
    return [{"adapter": name, "state": state,
             "requirements": CAD_ADAPTER_REQUIREMENTS[name]}
            for name, state in CAD_ADAPTERS.items()]
