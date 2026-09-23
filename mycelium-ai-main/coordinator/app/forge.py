"""Forge Studio backing helpers (vertical slice 1).

Thin, read-mostly layer over existing contracts — no second
database, no second queue, no second event bus, no second
model registry, no execution:

- primitives: facets straight from the existing procedural
  CAD builders (``cad.box_facets`` / ``cad.cylinder_facets``).
  The 20mm cube is the default editor primitive.
- slicer status: the existing ``TestSlicer`` (SIMULATED) plus
  the honest UNAVAILABLE state for production slicing.
- printers: the existing ``printer3d`` store + simulated badge
  logic (mirrors ``main._printer_is_simulated``, no import of
  ``main`` to avoid a cycle).
- ask: closed-rule intent parsing (existing
  ``meshops.parse_prompt_edit`` + keyword intents). Returns
  advice + an optional proposed op + an unsaved mission draft
  using existing step kinds. READ / ADVISE / PROPOSE only —
  this function never writes, never approves, never executes.
- fork: editor-local context clone. There is deliberately no
  dedicated fork record; canonical persistence of a fork runs
  through the existing gated write flow (``inventory.create``
  object/file + ``inventory.create_relationship`` with a
  ``generated_from``/``related_to`` provenance note) — see
  ``FORK_MISSING_RECORD``.

Pure except for read-only store listings (workshop registry,
printers, familiars, INVENTory browse); every failing source
degrades to an explicit empty/UNAVAILABLE, never invented data.
"""

from __future__ import annotations

#: Editor primitives backed by existing procedural builders.
FORGE_PRIMITIVES = ("cube", "cylinder")

#: Exact backend record that does NOT exist yet: a dedicated
#: fork record. Reported honestly by the UI until Save runs
#: through the existing gated write flow.
FORK_MISSING_RECORD = (
    "no dedicated fork record exists; a fork stays editor-local "
    "(ForgeSession.forked_from) until Save proposes "
    "inventory.create (object/file) + inventory.create_relationship "
    "through POST /api/v1/writes/inventory with exact YES approval"
)

#: Physical execution is never available from Forge Studio.
PHYSICAL_STATE = "HARDWARE_REQUIRED"


def default_session() -> dict:
    """Fresh editor-state shape. UI-only; never canonical."""
    return {
        "selected_model": "",
        "selected_part": "",
        "camera": {"rot_x": 0.5, "rot_y": 0.6, "scale": 1.0,
                   "ox": 0.0, "oy": 0.0},
        "parts": [],
        "parameters": {},
        "dirty": False,
        "project_id": "",
        "model_id": "",
        "forked_from": {},
        "saved": "",
    }


def primitive_facets(name: str, size_mm: float = 20.0) -> dict:
    """Facets for one named primitive via existing CAD builders.

    Cube: ``cad.box_facets`` (same math as the procedural test
    path). Cylinder: ``cad.cylinder_facets`` (r=10mm, h=20mm
    scaled by size). Returns JSON-safe tris + honesty note.
    """
    from . import cad as _cad
    key = str(name or "").strip().lower()
    if key not in FORGE_PRIMITIVES:
        raise ValueError(
            f"Unknown primitive '{name}'; expected one of "
            f"{list(FORGE_PRIMITIVES)}")
    try:
        size = float(size_mm)
    except (TypeError, ValueError):
        raise ValueError("size_mm must be a number")
    if not 0.1 <= size <= 1000.0:
        raise ValueError("size_mm must be 0.1..1000")
    if key == "cube":
        facets = _cad.box_facets(size, size, size)
        source = "cad.box_facets (procedural, local math)"
    else:
        facets = _cad.cylinder_facets(size / 2.0, size, 24)
        source = "cad.cylinder_facets (procedural, local math)"
    tris = [[[float(coord) for coord in point]
             for point in facet] for facet in facets]
    return {
        "name": key,
        "size_mm": size,
        "tris": tris,
        "total_tris": len(tris),
        "truncated": False,
        "source": source,
        "provenance": {"source_type": "derived",
                       "creator_id": "forge-studio",
                       "human_verified": False},
        "honesty": "procedural preview geometry; not a measured "
                   "mesh, not validated, not registered",
    }


def slicer_status() -> dict:
    """Honest slicer availability from existing providers."""
    from .slicer3d import SLICER_PROFILES, get_slicer
    try:
        test = get_slicer("test-slicer")
        simulated = {"name": test.name, "state": "SIMULATED",
                     "note": "deterministic synthetic G-code, "
                             "never for printers"}
    except Exception as error:  # pragma: no cover - defensive
        simulated = {"name": "test-slicer", "state": "UNAVAILABLE",
                     "note": str(error)[:160]}
    try:
        get_slicer("production")
        production = {"name": "production", "state": "AVAILABLE",
                      "note": "reviewed local runtime"}
    except Exception:
        production = {"name": "production", "state": "UNAVAILABLE",
                      "note": "no reviewed local slicer runtime; "
                              "see SlicerProvider.requirements()"}
    return {
        "simulated": simulated,
        "production": production,
        "profiles": sorted(SLICER_PROFILES),
        "honesty": "SIMULATED output is test-only; production "
                   "slicing refuses until a reviewed runtime exists",
    }


def printer_summary() -> list[dict]:
    """Stored printers with honest SIMULATED/UNAVAILABLE badges.

    Read-only; mirrors the ``main._printer_is_simulated`` badge
    without importing ``main``.
    """
    try:
        from .printer3d import adapter_for_printer
        from .printer3d import list_stored_printers
        devices = list_stored_printers()
    except Exception:
        return []
    out = []
    for device in devices[:12]:
        printer_id = str(getattr(device, "printer_id", ""))
        simulated = False
        available = False
        try:
            adapter = adapter_for_printer(printer_id)
            available = adapter is not None
            if adapter is not None:
                try:
                    status = adapter.status(None)
                    simulated = bool(
                        isinstance(status, dict)
                        and status.get("simulated"))
                except Exception:
                    simulated = (getattr(adapter, "name", "")
                                 == "simulated-test")
        except Exception:
            available = False
        state = ("SIMULATED" if simulated else
                 "REAL" if available else "UNAVAILABLE")
        out.append({
            "printer_id": printer_id,
            "name": str(getattr(device, "name", ""))[:80],
            "capabilities": list(
                getattr(device, "capabilities", []) or [])[:12],
            "state": state,
        })
    return out


def forge_identity() -> dict:
    """Forge familiar identity (existing capability record).

    Read-only: finds the canonical Forge familiar by name; when
    absent it says so instead of inventing one (creation stays
    with ``familiars.ensure_npc_familiars`` callers).
    """
    try:
        from .familiars import list_familiars
        for familiar in list_familiars() or []:
            if str(getattr(familiar, "name", "")).strip() \
                    .lower() == "forge":
                try:
                    return familiar.model_dump(mode="json")
                except Exception:
                    return {"name": "Forge",
                            "kind": getattr(familiar, "kind",
                                            "machine")}
    except Exception:
        pass
    return {"name": "Forge", "kind": "machine",
            "state": "UNREGISTERED",
            "note": "no Forge familiar record yet; the NPC "
                    "identity in /play stays canonical"}


def workshop_snapshot(limit: int = 8) -> dict:
    """Bounded read-only snapshot of the existing 3D registry."""
    count = max(1, min(int(limit or 8), 12))
    snapshot: dict = {"models": [], "materials": [],
                      "fabjobs": []}
    try:
        from .workshop3d import list_fabjobs, list_materials
        from .workshop3d import list_models
        snapshot["models"] = list_models(limit=count)
        snapshot["materials"] = list_materials(limit=count)
        snapshot["fabjobs"] = list_fabjobs(limit=count)
    except Exception:
        pass
    return snapshot


async def inventory_snapshot() -> dict:
    """Bounded INVENTory browse via the existing read bridge.

    Best-effort: unreachable INVENTory yields an explicit
    UNAVAILABLE instead of invented records.
    """
    try:
        from .inventory_read import InventoryReader
        reader = InventoryReader()
        response = await reader.browse()
        return {
            "state": "REAL",
            "results": [item.model_dump(mode="json")
                        for item in response.results],
            "total": response.total,
            "provenance": "inventory_read.browse "
                          "(read-only bridge)",
        }
    except Exception as error:
        return {"state": "UNAVAILABLE", "results": [],
                "total": 0,
                "note": f"INVENTory unreachable: {error}"[:200]}


def ask_forge(question: str) -> dict:
    """READ / ADVISE / PROPOSE over one question. Pure: no I/O,
    no writes, no approvals, no execution.

    Returns advice + optionally a proposed editor op (parsed by
    the existing ``meshops.parse_prompt_edit``) + an unsaved
    mission draft using existing step kinds (research/readout)
    that the UI may submit to the existing ``POST
    /api/v1/missions`` route. Physical work is always labelled
    HARDWARE_REQUIRED.
    """
    text = str(question or "").strip()
    if not text:
        raise ValueError("Ask Forge needs a question")
    if len(text) > 500:
        raise ValueError("question too long (max 500 chars)")
    lowered = text.lower()
    proposed_op: dict | None = None
    try:
        from .meshops import parse_prompt_edit
        parsed = parse_prompt_edit(text)
        proposed_op = {"op": parsed["op"],
                       "params": parsed["params"],
                       "interpretation": parsed.get(
                           "interpretation", "")[:160],
                       "note": "parsed, unconfirmed — preview only, "
                               "persistence via the gated save flow"}
    except Exception:
        proposed_op = None
    advice: list[str] = []
    routes: list[dict] = []
    if proposed_op is not None:
        advice.append(
            f"Parsed as {proposed_op['op']} "
            f"({proposed_op['interpretation']}). Preview it in "
            f"DESIGN; nothing is stored until Save proposes "
            f"through /writes with exact YES.")
        routes.append({"label": "3D workbench",
                       "href": "/3d"})
    if any(token in lowered for token in
           ("printbaar", "printable", "a1 mini", "a1mini",
            "printen", "print", "slic", "laag", "layer",
            "infill")):
        advice.append(
            "Printability: validate the mesh in the BUILD tab "
            "(existing mesh validator), slice only with the "
            "TEST slicer (SIMULATED output, never for printers), "
            "and print exclusively via the /writes exact-YES gate. "
            "Physical printing stays HARDWARE_REQUIRED.")
        routes.append({"label": "Slicer panel (SIMULATED)",
                       "href": "/forge#slicer"})
        routes.append({"label": "Writes gate", "href": "/writes"})
    if any(token in lowered for token in
           ("wandhouder", "houder", "holder", "bracket", "mount",
            "beugel")):
        advice.append(
            "Start from the cube primitive, extend it along one "
            "axis (DESIGN parameters), and fork before changing "
            "anything so the original stays untouched.")
    if any(token in lowered for token in
           ("materiaal", "material", "filament", "pla", "petg",
            "onderdelen", "nodig")):
        advice.append(
            "Materials come from the real registry only "
            "(/3d materials + suggest endpoint); suggestions "
            "never assign — confirm before slicing.")
        routes.append({"label": "Materials", "href": "/3d"})
    if any(token in lowered for token in
           ("alternatie", "onderzoek", "research", "lichter",
            "light", "sterker", "strong")):
        advice.append(
            "I can file this as a research mission draft below — "
            "read-only web research through the existing engine; "
            "results return as a dossier, never as execution.")
        routes.append({"label": "Research", "href": "/research"})
    if not advice:
        advice.append(
            "Describe what the part should become (e.g. 'maak "
            "deze bracket 5mm langer in x-richting'); I parse "
            "safe edits, advise on printability/materials, and "
            "draft research or proposal tasks — never execution.")
    mission_draft = {
        "goal": f"Forge: {text[:120]}",
        "steps": [{
            "kind": "research",
            "description": f"Research options for: {text[:120]}",
            "parameters": {"question": text[:500]},
        }],
        "note": "unsaved draft using the existing mission "
                "contract (research step: question only); submit "
                "via POST /api/v1/missions, approval stays with "
                "the existing mission gate",
    }
    return {
        "question": text[:500],
        "advice": advice,
        "proposed_op": proposed_op,
        "mission_draft": mission_draft,
        "routes": routes,
        "physical": PHYSICAL_STATE,
        "honesty": "READ / ADVISE / PROPOSE only: no writes, no "
                   "approvals, no execution from this panel",
    }


class ForgeGeometryError(ValueError):
    """Editor geometry refused; nothing was written, nothing
    proposed."""


#: Editor bounds mirror the existing contracts exactly: dims
#: 0.1..1000mm (cad box), translate -1000..1000 (mesh3d),
#: rotate -360..360 (mesh3d), scale 0.01..100 (mesh3d), at most
#: 20 parts (cad), merged mesh at most 5000 facets (meshops).
FORGE_MAX_PARTS = 20
FORGE_DIM_MIN = 0.1
FORGE_DIM_MAX = 1000.0
FORGE_POS_BOUND = 1000.0
FORGE_DEG_BOUND = 360.0
FORGE_SCALE_MIN = 0.01
FORGE_SCALE_MAX = 100.0


def _forge_num(mapping: dict, key: str, default: float,
               lo: float, hi: float, label: str) -> float:
    try:
        value = float(mapping.get(key, default))
    except (TypeError, ValueError):
        raise ForgeGeometryError(
            f"{label} must be a number")
    import math as _math
    if not _math.isfinite(value) or not lo <= value <= hi:
        raise ForgeGeometryError(
            f"{label} must be {lo}..{hi}")
    return value


def check_editor_part(data: dict, index: int) -> dict:
    """Validate one editor part. Closed kinds, existing bounds,
    no side effects. Scale is baked into dimensions downstream
    (the existing single-factor scale op cannot express
    per-axis scale); cylinders need equal width/height."""
    if not isinstance(data, dict):
        raise ForgeGeometryError(
            f"part {index} must be an object")
    kind = str(data.get("kind", "")).strip().lower()
    if kind not in FORGE_PRIMITIVES:
        raise ForgeGeometryError(
            f"part {index}: unknown kind '{kind}'; expected one "
            f"of {list(FORGE_PRIMITIVES)}")
    if not isinstance(data.get("size", {}), dict):
        raise ForgeGeometryError(
            f"part {index}: size must be an object")
    size = {axis: _forge_num(data["size"], axis, 20.0,
                             FORGE_DIM_MIN, FORGE_DIM_MAX,
                             f"part {index} dim {axis}")
            for axis in ("w", "h", "d")}
    pos = data.get("pos", {}) if isinstance(
        data.get("pos", {}), dict) else {}
    rot = data.get("rot", {}) if isinstance(
        data.get("rot", {}), dict) else {}
    scale = data.get("scale", {}) if isinstance(
        data.get("scale", {}), dict) else {}
    cleaned = {
        "kind": kind,
        "size": size,
        "pos": {axis: _forge_num(pos, axis, 0.0,
                                 -FORGE_POS_BOUND,
                                 FORGE_POS_BOUND,
                                 f"part {index} pos {axis}")
                for axis in ("x", "y", "z")},
        "rot": {axis: _forge_num(rot, axis, 0.0,
                                 -FORGE_DEG_BOUND,
                                 FORGE_DEG_BOUND,
                                 f"part {index} rot {axis}")
                for axis in ("x", "y", "z")},
        "scale": {axis: _forge_num(scale, axis, 1.0,
                                   FORGE_SCALE_MIN,
                                   FORGE_SCALE_MAX,
                                   f"part {index} scale {axis}")
                  for axis in ("x", "y", "z")},
        "material": str(data.get("material", "PLA") or "PLA")
        [:80],
    }
    scaled = {"w": size["w"] * cleaned["scale"]["x"],
              "h": size["h"] * cleaned["scale"]["y"],
              "d": size["d"] * cleaned["scale"]["z"]}
    for axis, value in scaled.items():
        if not FORGE_DIM_MIN <= value <= FORGE_DIM_MAX:
            raise ForgeGeometryError(
                f"part {index}: scaled dimension {axis} "
                f"({value:.2f}mm) outside 0.1..1000mm")
    cleaned["scaled_size"] = scaled
    if kind == "cylinder":
        import math as _math
        if not _math.isclose(scaled["w"], scaled["h"],
                             rel_tol=1e-9):
            raise ForgeGeometryError(
                f"part {index}: cylinder needs equal width and "
                f"height ({scaled['w']:.3f} vs "
                f"{scaled['h']:.3f}mm); adjust params or use a "
                f"cube")
        radius = scaled["w"] / 2.0
        if not 0.1 <= radius <= 500.0:
            raise ForgeGeometryError(
                f"part {index}: cylinder radius outside "
                f"0.1..500mm")
    return cleaned


def build_editor_facets(parts: list) -> list:
    """Editor parts to one merged facet list, using existing
    geometry only: cad builders, mesh3d transforms (rotate x,
    then y, then z — the same order as the Forge viewport —
    then translate), meshops merge. Pure; input untouched."""
    from . import cad as _cad
    from .mesh3d import transform_facets as _move
    from .meshops import MAX_FACETS as _cap
    from .meshops import merge_facets as _merge
    if not isinstance(parts, list) or \
            not 1 <= len(parts) <= FORGE_MAX_PARTS:
        raise ForgeGeometryError(
            f"save needs 1..{FORGE_MAX_PARTS} parts")
    cleaned = [check_editor_part(item, index)
               for index, item in enumerate(parts)]
    groups = []
    for part in cleaned:
        size = part["scaled_size"]
        if part["kind"] == "cube":
            facets = _cad.box_facets(size["w"], size["h"],
                                     size["d"])
        else:
            facets = _cad.cylinder_facets(size["w"] / 2.0,
                                          size["d"], 24)
        for axis in ("x", "y", "z"):
            degrees = part["rot"][axis]
            if abs(degrees) > 1e-12:
                facets = _move(facets, "rotate",
                               {"axis": axis,
                                "degrees": degrees})
        pos = part["pos"]
        if any(abs(value) > 1e-12 for value in pos.values()):
            facets = _move(facets, "translate",
                           {"dx": pos["x"], "dy": pos["y"],
                            "dz": pos["z"]})
        groups.append(facets)
    merged = groups[0] if len(groups) == 1 else _merge(groups)
    if len(merged) > _cap:
        raise ForgeGeometryError(
            f"merged mesh is {len(merged)} facets "
            f"(max {_cap}); refusing")
    return merged


def save_editor_geometry(design_name: str, parts: list,
                          forked_from=None,
                          ai_edits=None) -> dict:
    """Persist editor geometry the existing way: merged facets
    (cad + mesh3d + meshops) → write_derived_mesh (local working
    file, deterministic name from bytes) → validate_mesh →
    file_payload_for_mesh (inert dict).

    Writes a working file only — like the existing fab/transform
    persist path. Creates no proposal, no approval, no
    execution, no registration. Editor params ride along in
    ``metadata.forge`` so a later reload restores the editor,
    not just triangles. ``parts`` may mix parametric
    cube/cylinder parts with ``derived`` reference parts (placed
    tris, same transform order as the viewport). ``ai_edits``
    is an optional list of applied AI assists
    ({op, targets, reason}) recorded under
    ``metadata.forge.ai_edits`` with existing ``ai-generated``
    provenance vocabulary.
    """
    from .mesh3d import file_payload_for_mesh, validate_mesh
    from .mesh3d import write_derived_mesh
    name = str(design_name or "").strip()
    if not name:
        raise ForgeGeometryError("save needs a design name")
    if len(name) > 200:
        raise ForgeGeometryError("design name too long")
    fork = dict(forked_from) if isinstance(forked_from,
                                           dict) else {}
    assists = _check_ai_edits(ai_edits)
    scene = clean_scene_parts(parts, need_ids=False)
    merged = build_scene_facets(scene)
    try:
        derived_ref, digest, size = write_derived_mesh(
            "forge", "forge-save", merged)
    except (ValueError, OSError) as error:
        raise ForgeGeometryError(str(error)) from error
    report = validate_mesh(derived_ref)
    if report.verdict == "invalid":
        raise ForgeGeometryError(
            "derived mesh invalid: "
            + "; ".join(report.reasons[:5]))
    try:
        payload = file_payload_for_mesh(report, digest, size,
                                        name)
    except ValueError as error:
        raise ForgeGeometryError(str(error)) from error
    cleaned = [check_editor_part(item, index)
               for index, item in enumerate(parts)
               if isinstance(item, dict)
               and str(item.get("kind", "")).strip().lower()
               != "derived"]
    params = [{key: part[key] for key in
               ("kind", "size", "pos", "rot", "scale",
                "material")} for part in cleaned]
    scene_summary = []
    for _part_id, kind, part in scene:
        if kind == "derived":
            scene_summary.append({
                "kind": "derived",
                "source": part["source"],
                "total_tris": len(part["tris"]),
                "material": part["material"],
            })
        else:
            scene_summary.append({
                key: part[key] for key in
                ("kind", "size", "pos", "rot", "scale",
                 "material")})
    payload["metadata"]["forge"] = {
        "editor": "forge-studio",
        "design": name[:200],
        "parts": scene_summary,
        "forked_from": {str(key)[:40]: str(value)[:200]
                        for key, value in fork.items()},
        "derived_ref": derived_ref,
        "honesty": "editor preview params; canonical truth is "
                   "the INVENTory file record + provenance",
    }
    if assists:
        payload["metadata"]["forge"]["ai_edits"] = assists
    source = str(fork.get("source", ""))[:120]
    payload["description"] = (
        f"Forge Studio design '{name[:120]}': "
        f"{len(scene)} part(s), {len(merged)} tris, "
        f"validation {report.verdict}"
        + (f"; forked from {source}" if source else "")
        + (f"; ai-assisted ({len(assists)} edit(s))"
           if assists else "")
        + " (editor mesh, unverified)")[:2000]
    return {
        "status": "SAVED",
        "design": name[:200],
        "derived_ref": derived_ref,
        "sha256": digest,
        "size_bytes": size,
        "total_tris": len(merged),
        "validation": report.model_dump(mode="json"),
        "file_payload": payload,
        "editor": {"parts": scene_summary,
                   "ai_edits": assists,
                   "forked_from": payload["metadata"]["forge"][
                       "forked_from"]},
        "next": {"method": "POST",
                 "href": "/api/v1/writes/inventory",
                 "body": {"mutation": "create",
                          "entity_type": "file",
                          "fields": "file_payload (as-is)",
                          "actor": "forge-studio"},
                 "note": "existing gated flow: proposal is inert "
                         "until exact YES, execution + verify "
                         "stay behind their gates"},
        "honesty": "local derived working file + inert payload "
                   "only; nothing proposed, approved, executed "
                   "or registered by this call",
    }


# =============================================================================
# FORGE SLICE 3 — model library + hybrid manual/AI editing.
#
# Thin adapter over existing contracts only: workshop registry +
# fabrication-dir files + INVENTory read bridge (sources), cad +
# mesh3d + meshops (geometry), parse_prompt_edit + a minimal
# intent fallback limited to existing safe ops (AI proposals),
# write_derived_mesh + file_payload_for_mesh + the existing
# writes gate (persistence). No new database, no new queue, no
# new bus, no new approval engine, no second geometry truth,
# no external downloader, no execution of any kind.
# =============================================================================

#: Sources the Forge library reads. Read-only views; the library
#: never stores, never registers, never downloads.
FORGE_SOURCES = ("inventory", "workshop", "local", "external")

#: External 3D libraries are not connected: no Printables/URL
#: adapter exists in the codebase (verified by search), so the
#: library labels this honestly instead of inventing results.
EXTERNAL_SOURCE_STATE = "NOT_CONNECTED"

#: Ops a Forge AI proposal may carry. extend/mirror validate via
#: the existing meshops checker; translate/rotate via the
#: existing mesh3d checker; remove is editor-local only (drops
#: parts from editor state, never touches canonical data).
FORGE_PROPOSE_OPS = ("extend", "mirror", "translate",
                     "rotate", "remove")

#: Display cap for proposal preview triangles; the APPLY patch
#: carries full (bounded) geometry, the preview stays small.
FORGE_PREVIEW_TRIS = 500


class ForgeUpstreamError(RuntimeError):
    """An existing upstream (INVENTory bridge) is unreachable.
    Routes map this to 502 without leaking internals."""


def _check_ai_edits(ai_edits) -> list:
    """Validate the optional applied-AI-assists list. Shape only:
    [{op, targets, reason}]; op must be a known proposal op so
    the provenance note stays inside the existing vocabulary."""
    if ai_edits is None:
        return []
    if not isinstance(ai_edits, list) or len(ai_edits) > 20:
        raise ForgeGeometryError("ai_edits must be a list of "
                                 "at most 20 entries")
    cleaned = []
    for entry in ai_edits:
        if not isinstance(entry, dict):
            raise ForgeGeometryError(
                "ai_edits entries must be objects")
        op = str(entry.get("op", "")).strip().lower()
        if op not in FORGE_PROPOSE_OPS:
            raise ForgeGeometryError(
                f"ai_edits op '{op}' is not a known proposal op")
        targets = entry.get("targets", [])
        if not isinstance(targets, list) or \
                not all(isinstance(item, str) for item in targets):
            raise ForgeGeometryError(
                "ai_edits targets must be a string list")
        cleaned.append({
            "op": op,
            "targets": [item[:80] for item in targets[:20]],
            "reason": str(entry.get("reason", ""))[:160],
            "origin": "ai-generated",
        })
    return cleaned


def external_source_status() -> dict:
    """Honest external-library boundary. No adapter exists, so
    this reports NOT_CONNECTED plus the interface a future
    reviewed adapter would implement. Pure."""
    return {
        "state": EXTERNAL_SOURCE_STATE,
        "results": [],
        "total": 0,
        "note": "no external 3D-library adapter exists "
                "(no Printables/URL importer in the codebase); "
                "INVENTory + workshop + local files only",
        "adapter": {
            "interface": "forge.open_model(source, ref) with "
                         "source provenance {source, source_type, "
                         "source_ref, imported_from}",
            "future": "a reviewed adapter may map external "
                      "metadata onto this contract; no scraper, "
                      "no downloader, no auto-import here",
        },
    }


def local_model_files(limit: int = 12) -> list[dict]:
    """Read-only listing of local mesh files (.stl/.obj) in the
    existing fabrication dir that are NOT registered workshop
    models. No reads of file contents, no writes, no registration."""
    import os as _os
    from .mesh3d import check_artifact_ref, fabrication_dir
    count = max(1, min(int(limit or 12), 50))
    try:
        entries = sorted(_os.listdir(fabrication_dir()))
    except OSError:
        return []
    registered: set = set()
    try:
        from .workshop3d import list_models
        registered = {str(item.get("filename", ""))
                      for item in list_models(limit=100)}
    except Exception:
        registered = set()
    out = []
    for entry in entries:
        if not entry.lower().endswith((".stl", ".obj")):
            continue
        try:
            reference = check_artifact_ref(entry)
        except ValueError:
            continue
        if reference in registered:
            continue
        size = 0
        try:
            size = _os.path.getsize(_os.path.join(
                _os.path.abspath(fabrication_dir()), reference))
        except OSError:
            continue
        out.append({
            "id": reference,
            "name": reference,
            "source": "LOCAL",
            "type": "mesh-stl" if reference.lower().endswith(
                ".stl") else "mesh-obj",
            "file": reference,
            "status": "unregistered",
            "size_bytes": size,
            "provenance": {"source_type": "local-file",
                           "source_ref": reference,
                           "human_verified": False},
            "open": {"method": "POST",
                     "href": "/api/v1/forge/open",
                     "body": {"source": "local",
                              "ref": reference}},
        })
        if len(out) >= count:
            break
    return out


async def forge_library(limit: int = 8) -> dict:
    """Read-only model library over existing sources: workshop
    registry, INVENTory browse (best-effort UNAVAILABLE),
    unregistered local mesh files, and the honest external
    NOT_CONNECTED stub. Never stores, never registers."""
    count = max(1, min(int(limit or 8), 12))
    workshop: list = []
    try:
        from .workshop3d import list_models
        for item in list_models(limit=count):
            model_id = str(item.get("model_id", ""))
            filename = str(item.get("filename", ""))
            inspection = item.get("inspection", {}) \
                if isinstance(item.get("inspection", {}), dict) \
                else {}
            workshop.append({
                "id": model_id,
                "name": filename,
                "source": "WORKSHOP",
                "type": str(item.get("mime_type",
                                     "model"))[:40],
                "file": filename,
                "status": str(item.get("status",
                                       "unknown"))[:40],
                "triangles": inspection.get("triangles"),
                "mesh_verdict": inspection.get("mesh_verdict"),
                "provenance": {
                    "source_type": str(item.get(
                        "source", "inbox"))[:40],
                    "source_ref": model_id,
                    "human_verified": False},
                "open": {"method": "POST",
                         "href": "/api/v1/forge/open",
                         "body": {"source": "workshop",
                                  "ref": model_id}},
            })
    except Exception:
        workshop = []
    inventory_entries: list = []
    inventory_state = "UNAVAILABLE"
    inventory_note = ""
    try:
        snapshot = await inventory_snapshot()
        inventory_state = str(snapshot.get("state", "UNAVAILABLE"))
        inventory_note = str(snapshot.get("note", ""))[:200]
        for item in snapshot.get("results", []) or []:
            if not isinstance(item, dict):
                continue
            entity_id = str(item.get("entity_id", ""))
            entity_type = str(item.get("entity_type", ""))
            provenance = item.get("provenance", {}) \
                if isinstance(item.get("provenance", {}), dict) \
                else {}
            inventory_entries.append({
                "id": entity_id,
                "name": str(item.get("title", ""))[:120],
                "source": "INVENTORY",
                "type": entity_type[:40],
                "file": "",
                "status": inventory_state,
                "provenance": {
                    "source_type": str(provenance.get(
                        "source_type", "unknown"))[:40],
                    "source_ref": entity_id,
                    "human_verified": bool(provenance.get(
                        "human_verified", False))},
                "open": {"method": "POST",
                         "href": "/api/v1/forge/open",
                         "body": {"source": "inventory",
                                  "entity_type": entity_type,
                                  "ref": entity_id}},
            })
    except Exception as error:
        inventory_state = "UNAVAILABLE"
        inventory_note = f"INVENTory unreachable: {error}"[:200]
    return {
        "workshop": workshop[:count],
        "inventory": {"state": inventory_state,
                      "results": inventory_entries[:count],
                      "note": inventory_note},
        "local": local_model_files(limit=count),
        "external": external_source_status(),
        "honesty": "read-only views over existing stores; "
                   "INVENTory/LOCAL entries open geometry only "
                   "when local mesh bytes exist, EXTERNAL is "
                   "NOT_CONNECTED (no adapter in the codebase)",
    }


def _forge_part_id(value, label: str) -> str:
    """Editor part ids are client handles, never paths: strict
    allow-list so proposals echo nothing filesystem-shaped."""
    import re as _re
    text = str(value or "")
    if not _re.fullmatch(r"[A-Za-z0-9_-]{1,80}", text):
        raise ForgeGeometryError(
            f"{label} must be 1..80 chars [A-Za-z0-9_-]")
    return text


def check_derived_part(data: dict, index: int) -> dict:
    """Validate one imported (triangle-soup) editor part. Inline
    tris bounded like every existing mesh op (at most 5000),
    finite numbers only; transform bounds mirror the existing
    mesh3d contracts; source stays a small string map."""
    if not isinstance(data, dict):
        raise ForgeGeometryError(
            f"part {index} must be an object")
    kind = str(data.get("kind", "")).strip().lower()
    if kind != "derived":
        raise ForgeGeometryError(
            f"part {index}: expected kind 'derived'")
    tris = data.get("tris", [])
    if not isinstance(tris, list) or \
            not 1 <= len(tris) <= 5000:
        raise ForgeGeometryError(
            f"part {index}: derived tris must be 1..5000")
    import math as _math
    cleaned_tris = []
    for facet in tris:
        if not isinstance(facet, (list, tuple)) or \
                len(facet) != 3:
            raise ForgeGeometryError(
                f"part {index}: derived facets must be triangles")
        points = []
        for point in facet:
            if not isinstance(point, (list, tuple)) or \
                    len(point) != 3:
                raise ForgeGeometryError(
                    f"part {index}: derived points must be "
                    f"(x, y, z)")
            try:
                coords = (float(point[0]), float(point[1]),
                          float(point[2]))
            except (TypeError, ValueError):
                raise ForgeGeometryError(
                    f"part {index}: derived coords must be numbers")
            if any(not _math.isfinite(coord)
                   for coord in coords):
                raise ForgeGeometryError(
                    f"part {index}: derived coords must be finite")
            points.append(coords)
        cleaned_tris.append(tuple(points))
    pos = data.get("pos", {}) if isinstance(
        data.get("pos", {}), dict) else {}
    rot = data.get("rot", {}) if isinstance(
        data.get("rot", {}), dict) else {}
    scale = data.get("scale", {}) if isinstance(
        data.get("scale", {}), dict) else {}
    source = data.get("source", {}) if isinstance(
        data.get("source", {}), dict) else {}
    return {
        "kind": "derived",
        "tris": cleaned_tris,
        "pos": {axis: _forge_num(pos, axis, 0.0,
                                 -FORGE_POS_BOUND,
                                 FORGE_POS_BOUND,
                                 f"part {index} pos {axis}")
                for axis in ("x", "y", "z")},
        "rot": {axis: _forge_num(rot, axis, 0.0,
                                 -FORGE_DEG_BOUND,
                                 FORGE_DEG_BOUND,
                                 f"part {index} rot {axis}")
                for axis in ("x", "y", "z")},
        "scale": {axis: _forge_num(scale, axis, 1.0,
                                   FORGE_SCALE_MIN,
                                   FORGE_SCALE_MAX,
                                   f"part {index} scale {axis}")
                  for axis in ("x", "y", "z")},
        "material": str(data.get("material", "—") or "—")[:80],
        "source": {str(key)[:40]: str(value)[:200]
                   for key, value in source.items()},
    }


def clean_scene_parts(parts: list,
                      need_ids: bool = False) -> list:
    """Validate a mixed editor scene: parametric cube/cylinder
    parts (existing checker) plus derived reference parts. Pure;
    input untouched. Returns [(id, kind, cleaned)]."""
    if not isinstance(parts, list) or \
            not 1 <= len(parts) <= FORGE_MAX_PARTS:
        raise ForgeGeometryError(
            f"scene needs 1..{FORGE_MAX_PARTS} parts")
    seen: set = set()
    out = []
    for index, item in enumerate(parts):
        if not isinstance(item, dict):
            raise ForgeGeometryError(
                f"part {index} must be an object")
        kind = str(item.get("kind", "")).strip().lower()
        if kind in FORGE_PRIMITIVES:
            cleaned = check_editor_part(item, index)
        elif kind == "derived":
            cleaned = check_derived_part(item, index)
        else:
            raise ForgeGeometryError(
                f"part {index}: unknown kind '{kind}'; expected "
                f"cube, cylinder or derived")
        part_id = str(item.get("id", "") or "")
        if need_ids:
            part_id = _forge_part_id(
                part_id, f"part {index} id")
            if part_id in seen:
                raise ForgeGeometryError(
                    f"duplicate part id '{part_id}'")
            seen.add(part_id)
        out.append((part_id, kind, cleaned))
    return out


def _parametric_part_facets(part: dict) -> list:
    """Facets for one cleaned parametric part. Same builders and
    same transform order (rotate x, y, z, then translate) as the
    existing save path."""
    from . import cad as _cad
    from .mesh3d import transform_facets as _move
    size = part["scaled_size"]
    if part["kind"] == "cube":
        facets = _cad.box_facets(size["w"], size["h"],
                                 size["d"])
    else:
        facets = _cad.cylinder_facets(size["w"] / 2.0,
                                      size["d"], 24)
    for axis in ("x", "y", "z"):
        degrees = part["rot"][axis]
        if abs(degrees) > 1e-12:
            facets = _move(facets, "rotate",
                           {"axis": axis, "degrees": degrees})
    pos = part["pos"]
    if any(abs(value) > 1e-12 for value in pos.values()):
        facets = _move(facets, "translate",
                       {"dx": pos["x"], "dy": pos["y"],
                        "dz": pos["z"]})
    return facets


def _place_derived_tris(part: dict) -> list:
    """Place cleaned derived tris in the scene: per-axis scale,
    then rotate x, y, z, then translate — the same order as the
    Forge viewport. Pure math, no I/O."""
    from .mesh3d import transform_facets as _move
    scale = part["scale"]
    moved = [tuple((point[0] * scale["x"],
                    point[1] * scale["y"],
                    point[2] * scale["z"])
                   for point in facet)
             for facet in part["tris"]]
    for axis in ("x", "y", "z"):
        degrees = part["rot"][axis]
        if abs(degrees) > 1e-12:
            moved = _move(moved, "rotate",
                          {"axis": axis, "degrees": degrees})
    pos = part["pos"]
    if any(abs(value) > 1e-12 for value in pos.values()):
        moved = _move(moved, "translate",
                      {"dx": pos["x"], "dy": pos["y"],
                       "dz": pos["z"]})
    return moved


def build_scene_facets(scene: list) -> list:
    """Cleaned scene (from ``clean_scene_parts``) to one merged
    facet list. Parametric parts use the existing builders;
    derived parts contribute their placed tris. Bounded by the
    existing meshops cap. Pure; input untouched."""
    from .meshops import MAX_FACETS as _cap
    from .meshops import merge_facets as _merge
    if not isinstance(scene, list) or not scene:
        raise ForgeGeometryError("scene is empty")
    groups = []
    for _part_id, kind, part in scene:
        if kind == "derived":
            groups.append(_place_derived_tris(part))
        else:
            groups.append(_parametric_part_facets(part))
    merged = groups[0] if len(groups) == 1 else _merge(groups)
    if len(merged) > _cap:
        raise ForgeGeometryError(
            f"merged mesh is {len(merged)} facets "
            f"(max {_cap}); refusing")
    return merged


def _import_part(tris: list, source: dict, validation: str,
                 total: int, artifact_ref: str) -> dict:
    """One editor-local derived part from placed mesh facets.
    JSON-safe; transform identity; provenance rides along."""
    return {
        "kind": "derived",
        "tris": [[[float(coord) for coord in point]
                  for point in facet] for facet in tris],
        "pos": {"x": 0.0, "y": 0.0, "z": 0.0},
        "rot": {"x": 0.0, "y": 0.0, "z": 0.0},
        "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        "material": "—",
        "source": {str(key)[:40]: str(value)[:200]
                   for key, value in source.items()},
        "derived": {"artifact_ref": artifact_ref,
                    "validation": validation,
                    "total_tris": total},
    }


def _open_mesh_facets(reference: str) -> tuple:
    """Read + validate local mesh bytes for editor import.
    Full geometry up to the existing cap; truncated or invalid
    meshes refuse instead of importing partial data."""
    from .mesh3d import mesh_facets, validate_mesh
    try:
        facets, _format, total, truncated = mesh_facets(
            reference, 5000)
    except ValueError as error:
        raise ForgeGeometryError(str(error)) from error
    if truncated:
        raise ForgeGeometryError(
            f"'{reference}' exceeds the 5000-facet editor cap; "
            f"import refused")
    try:
        report = validate_mesh(reference)
    except ValueError as error:
        raise ForgeGeometryError(str(error)) from error
    if report.verdict == "invalid":
        raise ForgeGeometryError(
            f"'{reference}' is an invalid mesh "
            f"({'; '.join(report.reasons[:3])}); import refused")
    return facets, report, total


def open_workshop_model(model_id: str) -> dict:
    """Import a registered workshop model into editor state.
    Read-only source: validates the record, reads the existing
    local mesh bytes, returns one derived editor part with
    provenance. Writes nothing, registers nothing."""
    from .workshop3d import WorkshopRefusedError, get_model
    reference = str(model_id or "").strip()
    try:
        record = get_model(reference)
    except (ValueError, WorkshopRefusedError) as error:
        raise ForgeGeometryError(str(error)[:200]) from error
    if record is None:
        raise ForgeGeometryError(
            f"workshop model '{reference[:80]}' not found")
    filename = str(record.get("filename", ""))
    if not filename.lower().endswith((".stl", ".obj")):
        raise ForgeGeometryError(
            f"model '{filename[:80]}' is metadata-only "
            f"(no local STL/OBJ geometry to import)")
    facets, report, total = _open_mesh_facets(filename)
    provenance = {
        "source": "workshop",
        "source_type": str(record.get("source", "inbox"))[:40],
        "source_ref": str(record.get("model_id",
                                     reference))[:80],
        "imported_from": filename,
        "human_verified": False,
    }
    return {
        "status": "OPENED",
        "source": "workshop",
        "ref": provenance["source_ref"],
        "parts": [_import_part(facets, provenance,
                               report.verdict, total, filename)],
        "provenance": provenance,
        "validation": report.model_dump(mode="json"),
        "honesty": "editor-local import; nothing written, "
                   "nothing proposed, nothing registered",
    }


def open_local_model(reference: str) -> dict:
    """Import an unregistered local mesh file into editor state.
    Same read-only discipline as the workshop path; provenance
    says local-file. Writes nothing."""
    from .mesh3d import check_artifact_ref
    try:
        cleaned = check_artifact_ref(str(reference or ""))
    except ValueError as error:
        raise ForgeGeometryError(str(error)) from error
    if not cleaned.lower().endswith((".stl", ".obj")):
        raise ForgeGeometryError(
            "local import needs a .stl or .obj file")
    facets, report, total = _open_mesh_facets(cleaned)
    provenance = {
        "source": "local",
        "source_type": "local-file",
        "source_ref": cleaned,
        "imported_from": cleaned,
        "human_verified": False,
    }
    return {
        "status": "OPENED",
        "source": "local",
        "ref": cleaned,
        "parts": [_import_part(facets, provenance,
                               report.verdict, total, cleaned)],
        "provenance": provenance,
        "validation": report.model_dump(mode="json"),
        "honesty": "editor-local import; registration state "
                   "unchanged, nothing proposed",
    }


async def open_inventory_model(entity_type: str,
                               entity_id: str) -> dict:
    """Open an INVENTory record into editor state. Metadata and
    provenance come from the existing read bridge; geometry only
    when the record names a local artifact whose bytes exist —
    otherwise an honest UNAVAILABLE with no invented triangles.
    Raises ForgeUpstreamError (route maps to 502) when the
    bridge is unreachable."""
    from .inventory_read import (InventoryReader,
                                 InventoryRefusedError,
                                 InventoryUnavailable)
    kind = str(entity_type or "").strip()
    reference = str(entity_id or "").strip()
    try:
        record = await InventoryReader().get(kind, reference)
    except InventoryRefusedError as error:
        raise ForgeGeometryError(str(error)) from error
    except InventoryUnavailable as error:
        raise ForgeUpstreamError(str(error)) from error
    if record is None:
        raise ForgeGeometryError(
            f"INVENTory entity '{reference[:80]}' not found")
    try:
        provenance = record.provenance.model_dump(mode="json")
    except Exception:
        provenance = {"source_type": "unknown"}
    details = dict(record.details or {})
    candidate = ""
    for key in ("artifact_ref", "filename"):
        value = details.get(key, "")
        if isinstance(value, str) and value.strip():
            candidate = value.strip()
            break
    metadata = details.get("metadata", {})
    if not candidate and isinstance(metadata, dict):
        for key in ("artifact_ref", "filename"):
            value = metadata.get(key, "")
            if isinstance(value, str) and value.strip():
                candidate = value.strip()
                break
    geometry: dict = {"state": "UNAVAILABLE",
                      "note": "record carries no local mesh "
                              "reference; metadata/provenance "
                              "only, no invented geometry"}
    parts: list = []
    if candidate:
        try:
            facets, report, total = _open_mesh_facets(candidate)
        except ForgeGeometryError as error:
            geometry = {"state": "UNAVAILABLE",
                        "artifact_ref": candidate[:200],
                        "note": str(error)[:200]}
        else:
            source = {
                "source": "inventory",
                "source_type": str(provenance.get(
                    "source_type", "unknown"))[:40],
                "source_ref": record.entity_id[:80],
                "imported_from": candidate,
                "human_verified": bool(provenance.get(
                    "human_verified", False)),
            }
            geometry = {"state": "AVAILABLE",
                        "artifact_ref": candidate,
                        "validation": report.verdict,
                        "total_tris": total}
            parts = [_import_part(facets, source,
                                  report.verdict, total,
                                  candidate)]
    return {
        "status": "OPENED",
        "source": "inventory",
        "entity_type": record.entity_type,
        "ref": record.entity_id,
        "title": record.title[:200],
        "parts": parts,
        "geometry": geometry,
        "provenance": {
            "source": "inventory",
            "source_type": str(provenance.get(
                "source_type", "unknown"))[:40],
            "source_ref": record.entity_id[:80],
            "human_verified": bool(provenance.get(
                "human_verified", False)),
        },
        "honesty": "metadata/provenance is canonical "
                   "INVENTory data; editor geometry only when "
                   "local mesh bytes exist",
    }


def open_model(source: str, ref: str) -> dict:
    """Synchronous open dispatcher for workshop/local sources.
    Inventory needs the async bridge (``open_inventory_model``);
    external has no adapter and refuses honestly."""
    key = str(source or "").strip().lower()
    if key == "workshop":
        return open_workshop_model(ref)
    if key == "local":
        return open_local_model(ref)
    if key == "inventory":
        raise ForgeGeometryError(
            "inventory open needs entity_type; the async "
            "INVENTory bridge resolves it")
    if key == "external":
        raise ForgeGeometryError(
            "EXTERNAL source NOT_CONNECTED: no external "
            "3D-library adapter exists; nothing imported")
    raise ForgeGeometryError(
        f"unknown source '{key}'; expected workshop, local, "
        f"inventory or external")


def _translate_intent(text: str):
    """Minimal move-intent fallback: 'verplaats 10mm naar links'
    style prompts to the existing translate op. Closed patterns
    only; returns None when not a move intent."""
    import re as _re
    move_keys = ("verplaats", "verschuif", "schuif", "beweeg",
                 "move", "shift", "translate")
    if not any(key in text for key in move_keys):
        return None
    match = _re.search(r"(\d+(?:[.,]\d+)?)\s*mm", text)
    if not match:
        return None
    try:
        amount = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    delta = {"x": 0.0, "y": 0.0, "z": 0.0}
    axis = ""
    for word, target, sign in (
            ("links", "x", -1.0), ("left", "x", -1.0),
            ("rechts", "x", 1.0), ("right", "x", 1.0),
            ("omhoog", "z", 1.0), ("up", "z", 1.0),
            ("omlaag", "z", -1.0), ("down", "z", -1.0),
            ("vooruit", "y", 1.0), ("naar voren", "y", 1.0),
            ("forward", "y", 1.0),
            ("achter", "y", -1.0), ("back", "y", -1.0)):
        if _re.search(r"\b" + _re.escape(word) + r"\b", text):
            axis, delta[target] = target, sign * amount
            break
    if not axis:
        for word, target in (("x-richting", "x"),
                             ("x-as", "x"), ("y-richting", "y"),
                             ("y-as", "y"), ("z-richting", "z"),
                             ("z-as", "z"), ("lengte", "x"),
                             ("breedte", "y"), ("hoogte", "z")):
            if word in text:
                axis, delta[target] = target, amount
                break
    if not axis:
        return None
    return {"op": "translate",
            "params": {"dx": delta["x"], "dy": delta["y"],
                       "dz": delta["z"]},
            "interpretation": f"translate {axis} by "
                              f"{delta[axis]:g}mm "
                              f"(parsed, unconfirmed)"}


def _rotate_intent(text: str):
    """Minimal rotate-intent fallback: 'draai 90 graden om z'
    style prompts to the existing rotate op. Closed patterns
    only; returns None when not a rotate intent."""
    import re as _re
    if not any(key in text for key in
               ("draai", "rotatie", "roteer", "rotate",
                "rotation")):
        return None
    match = _re.search(r"(-?\d+(?:[.,]\d+)?)\s*(graden|°|"
                       r"degrees?)\b", text)
    if not match:
        return None
    try:
        degrees = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    axis = ""
    for word, target in (("om x", "x"), ("rond x", "x"),
                         ("x-as", "x"), ("om y", "y"),
                         ("rond y", "y"), ("y-as", "y"),
                         ("om z", "z"), ("rond z", "z"),
                         ("z-as", "z")):
        if word in text:
            axis = target
            break
    if not axis:
        isolated = _re.search(r"\b([xyz])\b", text)
        if isolated:
            axis = isolated.group(1)
    if not axis:
        return None
    return {"op": "rotate",
            "params": {"axis": axis, "degrees": degrees},
            "interpretation": f"rotate {axis} by "
                              f"{degrees:g} degrees "
                              f"(parsed, unconfirmed)"}


def _remove_intent(text: str):
    """Minimal remove-intent fallback: 'maak een versie zonder
    dit onderdeel' style prompts to the editor-local remove op.
    Closed keywords only; returns None otherwise."""
    import re as _re
    if not any(key in text for key in
               ("verwijder", "verwijderen", "remove", "delete",
                "zonder dit onderdeel", "zonder deze",
                "weg met")):
        return None
    if _re.search(r"\b(gaten?|holes?)\b", text):
        return None
    return {"op": "remove", "params": {},
            "interpretation": "remove selected part(s) from "
                              "the editor scene (editor-local, "
                              "unconfirmed)"}


def parse_selection_intent(text: str) -> dict:
    """Selection-aware intent parsing. First the existing
    ``meshops.parse_prompt_edit`` (extend/mirror); then a minimal
    fallback limited to translate/rotate/remove phrasings that
    map onto existing safe ops. Anything else refuses with a
    hint; nothing is applied, nothing is written."""
    lowered = str(text or "").strip().lower()
    if not lowered:
        raise ForgeGeometryError(
            "propose needs a prompt or an explicit op")
    if len(lowered) > 500:
        raise ForgeGeometryError(
            "prompt too long (max 500 chars)")
    try:
        from .meshops import parse_prompt_edit
        parsed = parse_prompt_edit(text)
        return {"op": parsed["op"], "params": parsed["params"],
                "interpretation": parsed.get(
                    "interpretation", "")[:160]}
    except ValueError:
        pass
    for attempt in (_translate_intent, _rotate_intent,
                    _remove_intent):
        try:
            found = attempt(lowered)
        except ValueError:
            continue
        if found is not None:
            return found
    raise ForgeGeometryError(
        "could not parse a safe edit (try '5mm langer', "
        "'verplaats 10mm naar links', 'draai 90 graden om z', "
        "'spiegel x', or 'verwijder dit onderdeel'); nothing "
        "was changed")


def _check_selection(selection: list, by_id: dict) -> list:
    """Validate the target selection against scene ids. Closed
    allow-list; unknown or empty selections refuse."""
    if not isinstance(selection, list) or not selection:
        raise ForgeGeometryError(
            "propose needs a non-empty selection: selecteer "
            "eerst een onderdeel in de viewport")
    if len(selection) > 20:
        raise ForgeGeometryError(
            "selection holds at most 20 parts")
    targets = []
    for item in selection:
        part_id = _forge_part_id(item, "selection entry")
        if part_id not in by_id:
            raise ForgeGeometryError(
                f"selection '{part_id}' is not in this scene; "
                f"nothing was changed")
        if part_id not in targets:
            targets.append(part_id)
    return targets


def _json_tris(facets: list) -> list:
    return [[[float(coord) for coord in point]
             for point in facet] for facet in facets]


def propose_edit(selection: list, prompt: str = "",
                 parts: list | None = None, op: str = "",
                 params=None) -> dict:
    """Selection-aware AI edit proposal. Pure: validates the
    scene, the selection and the intent through the existing
    checkers (meshops/mesh3d/editor bounds), computes a preview
    plus an APPLY patch, and returns a structured proposal.

    APPLY/DISCARD stay client-side editor operations; this call
    writes nothing, proposes nothing canonical, approves
    nothing. Secrets never enter: only selection ids, the op
    and bounded geometry leave this function."""
    from .mesh3d import check_transform
    from .meshops import MAX_FACETS as _cap
    from .meshops import check_advanced_op, extend_facets
    from .meshops import merge_facets as _merge
    from .meshops import mirror_facets
    scene = clean_scene_parts(parts or [], need_ids=True)
    by_id = {part_id: (kind, cleaned)
             for part_id, kind, cleaned in scene}
    targets = _check_selection(selection, by_id)
    explicit = str(op or "").strip().lower()
    if explicit:
        if explicit not in FORGE_PROPOSE_OPS:
            raise ForgeGeometryError(
                f"unknown op '{explicit}'; expected one of "
                f"{list(FORGE_PROPOSE_OPS)}")
        given = dict(params) if isinstance(params, dict) \
            else {}
        if explicit in ("extend", "mirror"):
            try:
                cleaned_params = check_advanced_op(explicit,
                                                   given)
            except ValueError as error:
                raise ForgeGeometryError(
                    str(error)) from error
        elif explicit in ("translate", "rotate"):
            try:
                cleaned_params = check_transform(explicit,
                                                 given)
            except ValueError as error:
                raise ForgeGeometryError(
                    str(error)) from error
        else:
            if given:
                raise ForgeGeometryError(
                    "remove takes no params")
            cleaned_params = {}
        intent = {"op": explicit, "params": cleaned_params,
                  "interpretation": "explicit op (unconfirmed)"}
    else:
        intent = parse_selection_intent(prompt)
        name, values = intent["op"], intent["params"]
        try:
            if name in ("extend", "mirror"):
                intent["params"] = check_advanced_op(name,
                                                     values)
            elif name in ("translate", "rotate"):
                intent["params"] = check_transform(name,
                                                   values)
            elif name == "remove":
                if values:
                    raise ForgeGeometryError(
                        "remove takes no params")
        except ValueError as error:
            raise ForgeGeometryError(
                str(error)) from error
    name, values = intent["op"], intent["params"]
    if name == "remove" and \
            len(targets) >= len(scene):
        raise ForgeGeometryError(
            "remove would empty the scene; keep at least one "
            "part")
    patch: dict = {"update": {}, "remove": []}
    groups = []
    removed = 0
    for target in targets:
        kind, cleaned = by_id[target]
        if name == "remove":
            patch["remove"].append(target)
            removed += 1
            continue
        if kind == "derived":
            placed = _place_derived_tris(cleaned)
            if name == "extend":
                try:
                    placed = extend_facets(
                        placed, values["axis"],
                        values["delta_mm"])
                except ValueError as error:
                    raise ForgeGeometryError(
                        str(error)) from error
            elif name == "mirror":
                try:
                    placed = mirror_facets(
                        placed, values["plane"])
                except ValueError as error:
                    raise ForgeGeometryError(
                        str(error)) from error
            elif name == "translate":
                moved = dict(cleaned["pos"])
                for key, delta in (("x", values["dx"]),
                                   ("y", values["dy"]),
                                   ("z", values["dz"])):
                    moved[key] = _forge_num(
                        {"v": moved[key] + delta}, "v",
                        -FORGE_POS_BOUND, FORGE_POS_BOUND,
                        f"part {target} pos {key}")
                patch["update"][target] = {"pos": moved}
                placed = _place_derived_tris(
                    {**cleaned, "pos": moved})
            else:
                moved = {axis: _wrap_degrees(
                    cleaned["rot"][axis] + values["degrees"])
                    if axis == values["axis"]
                    else cleaned["rot"][axis]
                    for axis in ("x", "y", "z")}
                patch["update"][target] = {"rot": moved}
                placed = _place_derived_tris(
                    {**cleaned, "rot": moved})
            if name in ("extend", "mirror"):
                patch["update"][target] = {"tris": _json_tris(
                    placed)}
            groups.append(placed)
            continue
        raw = {"kind": kind, "size": dict(cleaned["size"]),
               "pos": dict(cleaned["pos"]),
               "rot": dict(cleaned["rot"]),
               "scale": dict(cleaned["scale"]),
               "material": cleaned["material"]}
        if name == "extend":
            dim = {"x": "w", "y": "h", "z": "d"}[values["axis"]]
            raw["size"][dim] = raw["size"][dim] + \
                values["delta_mm"]
            field = "size"
        elif name == "mirror":
            plane = values["plane"]
            raw["pos"][plane] = -raw["pos"][plane]
            field = "pos"
        elif name == "translate":
            raw["pos"]["x"] += values["dx"]
            raw["pos"]["y"] += values["dy"]
            raw["pos"]["z"] += values["dz"]
            field = "pos"
        else:
            raw["rot"][values["axis"]] = _wrap_degrees(
                raw["rot"][values["axis"]] + values["degrees"])
            field = "rot"
        try:
            rechecked = check_editor_part(raw, 0)
        except ForgeGeometryError as error:
            raise ForgeGeometryError(
                f"target {target}: {error}") from error
        patch["update"][target] = {field: rechecked[field]}
        groups.append(_parametric_part_facets(rechecked))
    if name == "remove":
        remaining = [part_id for part_id, _kind, _part
                     in scene if part_id not in patch["remove"]]
        preview: dict = {"total_tris": 0, "tris": [],
                         "truncated": False,
                         "removed": removed,
                         "remaining": len(remaining),
                         "remaining_ids": remaining[:20]}
    else:
        merged = groups[0] if len(groups) == 1 else _merge(
            groups)
        if len(merged) > _cap:
            raise ForgeGeometryError(
                f"proposal preview is {len(merged)} facets "
                f"(max {_cap}); refusing")
        preview = {"total_tris": len(merged),
                   "tris": _json_tris(
                       merged[:FORGE_PREVIEW_TRIS]),
                   "truncated": len(merged) >
                   FORGE_PREVIEW_TRIS}
    reason = (f"{intent['interpretation']}; targets "
              f"{', '.join(targets)[:200]}; preview only")
    return {
        "proposal": {
            "target_selection": targets,
            "operation": name,
            "parameters": values,
            "reason": reason[:500],
            "interpretation": intent["interpretation"][:160],
            "preview": {**preview, "patch": patch},
        },
        "validation": {
            "selection": f"{len(targets)}/{len(scene)} "
                         f"part(s)",
            "bounds": "existing meshops/mesh3d/editor bounds "
                      "(extend ±100mm, translate ±1000mm, "
                      "rotate ±360°, dims 0.1..1000mm)",
            "writes": "none — proposal only",
        },
        "honesty": "parsed, unconfirmed proposal over the "
                   "selected geometry only; APPLY is "
                   "editor-local, DISCARD changes nothing, "
                   "persistence only via Save → /writes with "
                   "exact YES",
        "next": {
            "apply": "client applies proposal.preview.patch "
                     "to editor state (dirty=true)",
            "discard": "client drops the proposal; nothing "
                       "canonical changes",
            "save": {"method": "POST",
                     "href": "/api/v1/forge/save",
                     "note": "existing derived-mesh + gated "
                             "file-proposal flow"},
        },
    }


def _wrap_degrees(value: float) -> float:
    """Wrap rotation into (-180, 180] so repeated AI rotates stay
    inside the existing ±360° editor bound. Pure."""
    import math as _math
    if not _math.isfinite(value):
        raise ForgeGeometryError("rotation must be finite")
    wrapped = ((float(value) + 180.0) % 360.0) - 180.0
    if wrapped <= -180.0:
        wrapped += 360.0
    return wrapped


def studio_page() -> str:
    """Forge Studio HTML. Uses the shared workshop shell; all
    data arrives via ``GET /api/v1/forge/session`` (existing
    stores only) and all writes go through existing gated
    routes. No inline secrets, no auto-execution."""
    from . import ui as _ui
    main = """<h1>Forge Studio</h1>
    <p class="muted">Zelfstandige 3D-werkplek: bekijken, aanpassen, forken en
    beheren als Forge-project — op de bestaande backend. Voorstel &rarr; approval
    &rarr; execute &rarr; verify blijft de enige weg naar canoniek.
    De NPC-presentatie blijft in <a href="/play">/play</a>.</p>
    <div class="panel"><div class="flowline">
    <span id="forge-dirty" class="chip">CLEAN</span>
    <span class="chip state-SIMULATED">SLICER: SIMULATED</span>
    <span class="chip state-UNAVAILABLE">PRINT: HARDWARE_REQUIRED</span>
    <label>Design <input type="text" id="forge-design-name" value="Forge design"
    style="width:12rem" aria-label="Design name"></label>
    <button id="forge-save" type="button">Save (proposal)</button>
    <button id="forge-fork" type="button">Fork</button>
    <span id="forge-status" class="muted" role="status">Loading session…</span>
    </div>
    <div id="forge-persist" class="muted">MODEL: editor only · GEOMETRY: preview · PERSISTENCE: unsaved · HISTORY: no fork.</div></div>
    <div class="panel"><div class="forge-grid">
    <section aria-label="Parts"><h2>Parts</h2>
    <p><button id="forge-add-cube" type="button">+ Primitive (cube)</button>
    <button id="forge-add-cylinder" type="button">+ Primitive (cylinder)</button>
    <button id="forge-add-component" type="button">+ Component (registry)</button></p>
    <ul id="forge-parts" class="quest"></ul>
    <div id="forge-library"><h3>Model library</h3>
    <p><label>Search <input type="text" id="forge-lib-search" placeholder="filter name/source…"
    style="width:10rem" aria-label="Filter library"></label></p>
    <ul id="forge-lib-list" class="quest"><li>○ Loading…</li></ul>
    <p id="forge-lib-honesty" class="muted">Sources: WORKSHOP · INVENTORY · LOCAL · EXTERNAL.</p></div>
    <div id="forge-inventory"><p class="muted">Inventory: loading…</p></div>
    </section>
    <section aria-label="3D viewport"><h2>3D viewport</h2>
    <canvas id="forge-view" width="640" height="420"
    style="width:100%;height:420px;background:var(--soil-2);border:1px solid var(--line);border-radius:var(--r)"
    role="img" aria-label="Forge 3D viewport: drag to rotate, wheel to zoom, shift-drag to pan"></canvas>
    <p class="muted">Drag = rotate · wheel = zoom · shift-drag = pan ·
    click a part to select (amber = selected). Procedural preview only.</p>
    </section>
    <section aria-label="Properties"><h2>Properties</h2>
    <div id="forge-props"><p class="muted">Select a part.</p></div>
    </section>
    </div></div>
    <div class="panel"><h2>AI editor</h2>
    <p class="muted">Selection-aware proposals over bestaande veilige geometry-ops
    (extend · mirror · translate · rotate · remove). Voorstel &rarr; preview &rarr;
    APPLY = editor-local (dirty) · DISCARD = niets. Canoniek pas via Save &rarr; /writes (exact YES).</p>
    <p>Selection: <code id="forge-selection">none</code>
    <span class="muted">click = select · ctrl/cmd-click = multi-select</span></p>
    <form id="forge-propose-form"><input type="text" id="forge-prompt" style="width:60%"
    placeholder="maak deze 5mm langer / verplaats 10mm naar links / verwijder dit onderdeel…"
    aria-label="AI edit prompt">
    <button type="submit">Propose</button>
    <button type="button" id="forge-discard">DISCARD</button>
    <button type="button" id="forge-apply" disabled>APPLY</button></form>
    <div id="forge-proposal"><p class="muted">No proposal — select parts, describe the edit, Propose.</p></div></div>
    <div class="panel"><div class="flowline" role="tablist" aria-label="Forge tabs">
    <button type="button" data-forge-tab="design" aria-label="Tab Design">DESIGN</button>
    <button type="button" data-forge-tab="slice" aria-label="Tab Slice">SLICE</button>
    <button type="button" data-forge-tab="build" aria-label="Tab Build">BUILD</button>
    <button type="button" data-forge-tab="history" aria-label="Tab History">HISTORY</button>
    <button type="button" data-forge-tab="mycelium" aria-label="Tab Mycelium">MYCELIUM</button>
    </div>
    <div id="forge-tab-design"><h3>Design</h3>
    <p class="muted">Parameters van het geselecteerde part. Elke wijziging zet
    <code>dirty</code>; canoniek wordt het pas via Save &rarr; /writes (exact YES).</p>
    <div id="forge-design-hint"><p class="muted">No part selected.</p></div>
    <p><label>Open saved geometry <input type="text" id="forge-open-ref" placeholder="fab-derived-….stl" style="width:16rem" aria-label="Derived reference"></label>
    <button id="forge-open" type="button">Open derived (preview, read-only)</button></p></div>
    <div id="forge-tab-slice" hidden><h3>Slicer</h3>
    <p><label>Printer <select id="sl-printer" aria-label="Printer"></select></label>
    <label>Material <select id="sl-material" aria-label="Material"></select></label>
    <label>Profile <select id="sl-profile" aria-label="Profile"></select></label>
    <label>Layer height <select id="sl-layer" aria-label="Layer height">
    <option value="0.28">0.28mm draft</option><option value="0.2">0.2mm</option>
    <option value="0.12">0.12mm fine</option></select></label>
    <label>Infill <select id="sl-infill" aria-label="Infill">
    <option value="15">15%</option><option value="20">20%</option>
    <option value="50">50%</option><option value="100">100%</option></select></label>
    <label>Supports <select id="sl-supports" aria-label="Supports">
    <option value="none">none</option><option value="touching">touching buildplate</option>
    </select></label></p>
    <div id="sl-estimate"><p class="muted">Select a part for an estimate.</p></div></div>
    <div id="forge-tab-build" hidden><h3>Build pipeline</h3>
    <div id="forge-pipeline" class="path" aria-label="Build pipeline"></div>
    <div id="forge-fabjobs"><p class="muted">Fab jobs: loading…</p></div>
    <div class="panel"><b>PRINT</b> — HARDWARE_REQUIRED. Fysieke uitvoering alleen via
    de bestaande approval-gate in <a href="/writes">/writes</a> (exact YES + execute +
    verify). Forge Studio start nooit zelf een printer.</div></div>
    <div id="forge-tab-history" hidden><h3>History</h3>
    <ul id="forge-log" class="timeline"></ul>
    <h3>Events (bestaande bus)</h3><ul id="forge-events" class="timeline"></ul></div>
    <div id="forge-tab-mycelium" hidden><h3>Mycelium — Ask Forge</h3>
    <p class="muted">READ / ADVISE / PROPOSE only. Geen uitvoering.</p>
    <form id="forge-ask-form"><input type="text" id="forge-ask-input" style="width:60%"
    placeholder="Maak hiervan een wandhouder…" aria-label="Ask Forge">
    <button type="submit">Ask</button></form>
    <div id="forge-advice"></div></div>
    </div>
    <style>.forge-grid{display:grid;grid-template-columns:220px minmax(0,1fr) 250px;gap:var(--space-2)}
    @media (max-width:1080px){.forge-grid{grid-template-columns:minmax(0,1fr)}}</style>
    <script>
    const ForgeSession = {selected_model:"",selected_part:"",selection:[],ai_edits:[],camera:{rot_x:0.5,rot_y:0.6,scale:1.0,ox:0.0,oy:0.0},parts:[],parameters:{},dirty:false,project_id:"",model_id:"",forked_from:{}};
    let FORGE_PRIMS = {}, FORGE_DATA = {}, FORGE_SEQ = 0, FORGE_PROPOSAL = null;
    const $ = id => document.getElementById(id);
    function forgeLog(msg){ const li=document.createElement("li"); li.textContent=new Date().toISOString().slice(11,19)+" "+msg; $("forge-log").prepend(li); }
    function setDirty(d, why){ ForgeSession.dirty=d; const c=$("forge-dirty"); c.textContent=d?"DIRTY":"CLEAN"; if(d&&why) forgeLog(why); try{ persistLine(); }catch(e){} }
    function boxTris(w,h,d){ const hx=w/2,hy=h/2,hz=d/2;
      const c=[[-hx,-hy,-hz],[hx,-hy,-hz],[hx,hy,-hz],[-hx,hy,-hz],[-hx,-hy,hz],[hx,-hy,hz],[hx,hy,hz],[-hx,hy,hz]];
      const q=[[0,3,2,1],[4,5,6,7],[0,1,5,4],[2,3,7,6],[0,4,7,3],[1,2,6,5]]; const t=[];
      q.forEach(f=>{ const p=f.map(i=>c[i]); t.push([p[0],p[1],p[2]]); t.push([p[0],p[2],p[3]]); }); return t; }
    function partTris(p){ if(p.kind==="derived") return (p.tris||[]);
      if(p.kind==="cube") return boxTris(p.size.w,p.size.h,p.size.d);
      const base = (FORGE_PRIMS.cylinder && FORGE_PRIMS.cylinder.tris) || [];
      const sx=p.size.w/20, sy=p.size.h/20, sz=p.size.d/20;
      return base.map(t=>t.map(pt=>[pt[0]*sx,pt[1]*sy,pt[2]*sz])); }
    function xform(p, pt){ let [x,y,z]=pt;
      const r=p.rot||{x:0,y:0,z:0}, s=p.scale||{x:1,y:1,z:1};
      x*=s.x; y*=s.y; z*=s.z;
      const rad=d=>d*Math.PI/180; let a=rad(r.x),b=rad(r.y),g=rad(r.z);
      let y1=y*Math.cos(a)-z*Math.sin(a), z1=y*Math.sin(a)+z*Math.cos(a); y=y1; z=z1;
      let x1=x*Math.cos(b)+z*Math.sin(b); z1=-x*Math.sin(b)+z*Math.cos(b); x=x1; z=z1;
      x1=x*Math.cos(g)-y*Math.sin(g); y1=x*Math.sin(g)+y*Math.cos(g); x=x1; y=y1;
      const q=p.pos||{x:0,y:0,z:0}; return [x+q.x,y+q.y,z+q.z]; }
    function draw(){ const cv=$("forge-view"), ctx=cv.getContext("2d");
      ctx.clearRect(0,0,640,420); const cam=ForgeSession.camera;
      const proj=p=>{ const cx=Math.cos(cam.rot_y),sx=Math.sin(cam.rot_y),cy=Math.cos(cam.rot_x),sy=Math.sin(cam.rot_x);
        const x1=p[0]*cx-p[2]*sx, z1=p[0]*sx+p[2]*cx, y1=p[1]*cy-z1*sy;
        return [320+x1*cam.scale+cam.ox, 210-y1*cam.scale+cam.oy]; };
      ForgeSession.parts.forEach(p=>{ const sel=ForgeSession.selection.includes(p.id);
        ctx.strokeStyle=sel?"#d9a441":"#a5c48a"; ctx.lineWidth=sel?2:1; ctx.beginPath();
        partTris(p).forEach(t=>{ const a=t.map(q=>proj(xform(p,q)));
          ctx.moveTo(a[0][0],a[0][1]); ctx.lineTo(a[1][0],a[1][1]); ctx.lineTo(a[2][0],a[2][1]); ctx.closePath(); });
        ctx.stroke(); }); }
    function renderParts(){ const ul=$("forge-parts"); ul.innerHTML="";
      ForgeSession.parts.forEach(p=>{ const li=document.createElement("li");
        const sel=ForgeSession.selection.includes(p.id);
        li.innerHTML="<span class='"+(sel?"q-now":"q-todo")+"'>"+(sel?"●":"○")+"</span> ";
        const a=document.createElement("a"); a.href="#"; a.textContent=p.name+" ("+p.kind+")";
        a.onclick=e=>{e.preventDefault(); selectPart(p.id, e.ctrlKey||e.metaKey);}; li.appendChild(a); ul.appendChild(li); });
      if(!ForgeSession.parts.length) ul.innerHTML="<li>○ No parts — add a primitive.</li>"; }
    function selectPart(id, toggle){ const at=ForgeSession.selection.indexOf(id);
      if(toggle){ if(at>=0) ForgeSession.selection.splice(at,1); else ForgeSession.selection.push(id); }
      else ForgeSession.selection=[id];
      ForgeSession.selected_part=ForgeSession.selection[0]||"";
      const p=ForgeSession.parts.find(q=>q.id===id); renderParts(); renderProps(); draw(); selLine();
      if(p){ forgeLog((toggle?"part toggled: ":"part selected: ")+p.name); } }
    function selLine(){ const el=$("forge-selection");
      if(el) el.textContent=ForgeSession.selection.length?ForgeSession.selection.join(", "):"none"; }
    function renderProps(){ const p=ForgeSession.parts.find(q=>q.id===ForgeSession.selected_part);
      const box=$("forge-props"), hint=$("forge-design-hint");
      if(!p){ box.innerHTML="<p class='muted'>Select a part.</p>"; hint.innerHTML="<p class='muted'>No part selected.</p>"; return; }
      if(p.kind==="derived"){ const num=(id,val)=>"<label>"+id+" <input type='number' step='0.5' id='fp-"+id+"' value='"+val+"' style='width:4.2rem' aria-label='"+id+"'></label>";
        box.innerHTML="<b>"+p.name+"</b> <span class='muted'>imported geometry ("+(p.tris||[]).length+" tris, "+(p.validation||"?")+"), transform editable — dimensions read-only (source: "+String((p.source||{}).source||"?")+").</span><br>"
        +num("pos.x",p.pos.x)+num("pos.y",p.pos.y)+num("pos.z",p.pos.z)+"<br>"
        +num("rot.x",p.rot.x)+num("rot.y",p.rot.y)+num("rot.z",p.rot.z)+"<br>"
        +num("scale.x",p.scale.x)+num("scale.y",p.scale.y)+num("scale.z",p.scale.z);
        hint.innerHTML="<p>Imported part <b>"+p.name+"</b> — transform stays in ForgeSession until Save.</p>";
        box.querySelectorAll("input").forEach(inp=>{ inp.onchange=()=>{ applyProps(); }; }); return; }
      const num=(id,val)=>"<label>"+id+" <input type='number' step='0.5' id='fp-"+id+"' value='"+val+"' style='width:4.2rem' aria-label='"+id+"'></label>";
      box.innerHTML="<b>"+p.name+"</b> <span class='muted'>"+p.kind+"</span><br>"
        +num("pos.x",p.pos.x)+num("pos.y",p.pos.y)+num("pos.z",p.pos.z)+"<br>"
        +num("rot.x",p.rot.x)+num("rot.y",p.rot.y)+num("rot.z",p.rot.z)+"<br>"
        +num("scale.x",p.scale.x)+num("scale.y",p.scale.y)+num("scale.z",p.scale.z)+"<br>"
        +num("dim.w",p.size.w)+num("dim.h",p.size.h)+num("dim.d",p.size.d)+"<br>"
        +"<label>material <input type='text' id='fp-material' value='"+p.material+"' style='width:8rem' aria-label='Material'></label>";
      hint.innerHTML="<p>Editing <b>"+p.name+"</b> — changes stay in ForgeSession until Save.</p>";
      box.querySelectorAll("input").forEach(inp=>{ inp.onchange=()=>{ applyProps(); }; }); }
    function applyProps(){ const p=ForgeSession.parts.find(q=>q.id===ForgeSession.selected_part); if(!p) return;
      const g=id=>parseFloat($("fp-"+id).value)||0;
      p.pos={x:g("pos.x"),y:g("pos.y"),z:g("pos.z")}; p.rot={x:g("rot.x"),y:g("rot.y"),z:g("rot.z")};
      p.scale={x:g("scale.x")||1,y:g("scale.y")||1,z:g("scale.z")||1};
      if(p.kind!=="derived"){ p.size={w:Math.max(0.1,g("dim.w")||20),h:Math.max(0.1,g("dim.h")||20),d:Math.max(0.1,g("dim.d")||20)};
        p.material=$("fp-material").value.slice(0,80); }
      ForgeSession.parameters[p.id]={pos:p.pos,rot:p.rot,scale:p.scale,size:p.size,material:p.material};
      setDirty(true,"part changed: "+p.name); draw(); slicerEstimate(); }
    function addPart(kind, fromRegistry){ FORGE_SEQ+=1;
      const base=(FORGE_PRIMS[kind]&&FORGE_PRIMS[kind].tris)||[];
      const p={id:"part_"+FORGE_SEQ+"_"+kind,name:(fromRegistry||kind)+" #"+FORGE_SEQ,kind:kind,
        size:{w:20,h:20,d:20},pos:{x:0,y:0,z:0},rot:{x:0,y:0,z:0},scale:{x:1,y:1,z:1},material:"PLA",registry:fromRegistry||""};
      if(!base.length&&kind!=="cube"){ $("forge-status").textContent="Primitive '"+kind+"' unavailable."; return; }
      ForgeSession.parts.push(p); selectPart(p.id); setDirty(true,"part added: "+p.name); }
    function slicerEstimate(){ const p=ForgeSession.parts.find(q=>q.id===ForgeSession.selected_part);
      const box=$("sl-estimate"); if(!p){ box.innerHTML="<p class='muted'>Select a part for an estimate.</p>"; return; }
      const layer=parseFloat($("sl-layer").value)||0.28, infill=parseFloat($("sl-infill").value)||15;
      const vol=p.size.w*p.size.h*p.size.d/1000, layers=Math.max(1,Math.ceil(p.size.d/layer));
      const grams=(vol*1.24*(0.2+0.8*infill/100)).toFixed(1), mins=Math.round(layers*0.8);
      const warn=p.size.w>220||p.size.h>220||p.size.d>250?"<br><b>WARNING: exceeds 220x220x250mm build volume.</b><br>No overhang analysis — validator only.":"<br>No overhang analysis — validator only.";
      box.innerHTML="<p><b>SIMULATED estimate</b> (TEST slicer heuristics, never G-code): layers ~"+layers
        +", volume ~"+vol.toFixed(1)+"cm3, filament ~"+grams+"g PLA, time ~"+mins+"min."+warn+"</p>"; }
    async function loadSession(){ try{
        const r=await fetch("/api/v1/forge/session"); if(!r.ok) throw new Error("HTTP "+r.status);
        FORGE_DATA=await r.json(); FORGE_PRIMS=FORGE_DATA.primitives||{};
        if(!ForgeSession.parts.length&&FORGE_PRIMS.cube){ addPart("cube"); setDirty(false); }
        renderInventory(); renderSlicer(); renderFabjobs(); renderPipeline(); loadEvents(); loadLibrary(); selLine();
        const id=(FORGE_DATA.identity||{}).name||"Forge";
        $("forge-status").textContent="Session live — "+ForgeSession.parts.length+" part(s), identity: "+id+".";
        try{ persistLine(); }catch(e){}
        forgeLog("model opened: default cube primitive (procedural)");
      }catch(e){ $("forge-status").textContent="Session failed: "+e+". Backend required."; } }
    function renderInventory(){ const inv=FORGE_DATA.inventory||{state:"UNAVAILABLE",results:[]};
      let html="<h3>Inventory</h3>";
      if(inv.state!=="REAL"||!inv.results.length){ html+="<p class='muted'>INVENTory: "+inv.state+" — editor model until Save. "+((inv.note||""))+"</p>"; }
      else{ html+="<ul>"; inv.results.slice(0,6).forEach(it=>{
          html+="<li><code>"+it.entity_id+"</code> <b>"+String(it.title||"").slice(0,50)+"</b><br><span class='muted'>"+it.entity_type+" · provenance "+String((it.provenance||{}).source_type||"?")+(it.provenance&&it.provenance.human_verified?" · VERIFIED":"")+"</span></li>"; });
        html+="</ul><p class='muted'>Provenance + status shown; Save wordt pas canoniek via /writes.</p>"; }
      const mods=(FORGE_DATA.workshop&&FORGE_DATA.workshop.models)||[];
      if(mods.length){ html+="<h3>Workshop models</h3><ul>"+mods.slice(0,5).map(m=>"<li><code>"+m.model_id+"</code> "+String(m.filename||"").slice(0,40)+" ["+m.status+"]</li>").join("")+"</ul>"; }
      $("forge-inventory").innerHTML=html; }
    function renderSlicer(){ const sl=FORGE_DATA.slicer||{};
      const pr=$("sl-printer"); pr.innerHTML="";
      (FORGE_DATA.printers||[]).forEach(p=>{ const o=document.createElement("option"); o.value=p.printer_id; o.textContent=p.name+" ["+p.state+"]"; pr.appendChild(o); });
      const sim=document.createElement("option"); sim.value=""; sim.textContent="Simulated (TEST slicer)"; pr.appendChild(sim);
      const prod=document.createElement("option"); prod.value="production"; prod.disabled=true;
      prod.textContent="Production [UNAVAILABLE]"; pr.appendChild(prod);
      const mat=$("sl-material"); mat.innerHTML="";
      ((FORGE_DATA.workshop&&FORGE_DATA.workshop.materials)||[{name:"PLA"},{name:"PETG"}]).slice(0,8).forEach(m=>{ const o=document.createElement("option"); o.textContent=m.name; mat.appendChild(o); });
      const prof=$("sl-profile"); prof.innerHTML="";
      (sl.profiles||["draft-pla"]).forEach(p=>{ const o=document.createElement("option"); o.textContent=p; prof.appendChild(o); });
      ["sl-printer","sl-material","sl-profile","sl-layer","sl-infill","sl-supports"].forEach(id=>{ $(id).onchange=slicerEstimate; });
      slicerEstimate(); }
    function renderFabjobs(){ const jobs=((FORGE_DATA.workshop||{}).fabjobs)||[];
      $("forge-fabjobs").innerHTML=jobs.length?("<ul>"+jobs.slice(0,6).map(j=>"<li><code>"+j.job_id+"</code> ["+j.stage+"] model "+String(j.model_id||"").slice(0,16)
        +" <form method='post' action='/web/workshop/fabjobs/"+j.job_id+"/sync' style='display:inline'><button type='submit'>Sync</button></form></li>").join("")+"</ul>"):"<p class='muted'>No fab jobs — start one in <a href='/3d'>/3d</a>.</p>"; }
    function renderPipeline(){ const stages=[["DESIGN",ForgeSession.parts.length?"done":"now"],["VALIDATE",""],["SLICE",""],["APPROVAL",ForgeSession.dirty?"now":""],["PRINT","blocked"]];
      $("forge-pipeline").innerHTML=stages.map(s=>"<span class='step "+s[1]+"'>"+s[0]+"</span>").join("<span class='arrow'>→</span>")
        +"<p class='muted'>Alleen DESIGN is vrij editeerbaar. SLICE = TEST (SIMULATED). PRINT = HARDWARE_REQUIRED via /writes.</p>"; }
    async function loadEvents(){ try{ const r=await fetch("/api/v1/events?limit=20"); const ev=await r.json();
        $("forge-events").innerHTML=ev.slice(-12).reverse().map(e=>"<li><small>"+String(e.created_at||"").slice(0,19)+"</small> <b>"+String(e.event_type||"")+"</b> — "+String(e.summary||"").slice(0,120)+"</li>").join("")||"<li>No events.</li>";
      }catch(e){ $("forge-events").innerHTML="<li>Events unavailable.</li>"; } }
    document.querySelectorAll("[data-forge-tab]").forEach(b=>{ b.onclick=()=>{ ["design","slice","build","history","mycelium"].forEach(t=>{ $("forge-tab-"+t).hidden=(t!==b.dataset.forgeTab); }); }; });
    $("forge-add-cube").onclick=()=>addPart("cube");
    $("forge-add-cylinder").onclick=()=>addPart("cylinder");
    $("forge-add-component").onclick=()=>{ const mods=((FORGE_DATA.workshop||{}).models)||[];
      if(!mods.length){ $("forge-status").textContent="No registry models — register one in /3d first."; return; }
      ForgeSession.selected_model=mods[0].model_id; addPart("cube",mods[0].model_id); forgeLog("component linked: "+mods[0].model_id+" (reference only)"); };
    (function(){ const cv=$("forge-view"); let drag=null,pan=false;
      cv.addEventListener("pointerdown",e=>{ drag=[e.clientX,e.clientY]; pan=e.shiftKey; cv.setPointerCapture(e.pointerId); });
      cv.addEventListener("pointerup",()=>drag=null);
      cv.addEventListener("pointermove",e=>{ if(!drag) return; const dx=e.clientX-drag[0],dy=e.clientY-drag[1];
        if(pan){ ForgeSession.camera.ox+=dx; ForgeSession.camera.oy+=dy; } else { ForgeSession.camera.rot_y+=dx*0.01; ForgeSession.camera.rot_x+=dy*0.01; }
        drag=[e.clientX,e.clientY]; draw(); });
      cv.addEventListener("wheel",e=>{ e.preventDefault(); ForgeSession.camera.scale*=e.deltaY<0?1.1:0.9; draw(); },{passive:false}); })();
    $("forge-fork").onclick=async ()=>{ if(!ForgeSession.parts.length){ $("forge-status").textContent="Nothing to fork."; return; }
      const src=ForgeSession.selected_model||ForgeSession.model_id||"editor";
      ForgeSession.forked_from={source:src,at:new Date().toISOString()};
      setDirty(true,"model forked from "+src);
      $("forge-status").textContent="Forked from "+src+" — editor-local until Save.";
      if(ForgeSession.selected_model&&ForgeSession.project_id){ try{
          const r=await fetch("/api/v1/workshop/links",{method:"POST",headers:{"Content-Type":"application/json"},
            body:JSON.stringify({workshop_id:ForgeSession.selected_model,entity_id:ForgeSession.project_id,predicate:"generated_from"})});
          forgeLog(r.ok?"fork link proposed (PROPOSED symbiosis)":"fork link refused: HTTP "+r.status); }catch(e){ forgeLog("fork link failed: "+e); } }
      else forgeLog("fork is editor-local: no mdl_/proj_ pair selected (no dedicated fork record — see Save)"); };
    function persistLine(){ const f=ForgeSession.forked_from||{};
      $("forge-persist").textContent="MODEL: "+($("forge-design-name").value||"Forge design")
        +" · GEOMETRY: "+ForgeSession.parts.length+" part(s)"+(ForgeSession.dirty?" (dirty)":" (clean)")
        +" · PERSISTENCE: "+(ForgeSession.saved||"unsaved")
        +" · HISTORY: "+(f.source?("forked from "+f.source):"no fork")
        +(ForgeSession.ai_edits.length?(" · AI: "+ForgeSession.ai_edits.length+" edit(s) (ai-generated, unverified)"):""); }
    function editorParts(){ return ForgeSession.parts.filter(p=>p.kind==="cube"||p.kind==="cylinder")
      .map(p=>({kind:p.kind,size:p.size,pos:p.pos,rot:p.rot,scale:p.scale,material:p.material})); }
    function sceneParts(){ return ForgeSession.parts.map(p=>{
      if(p.kind==="derived") return {id:p.id,kind:"derived",tris:p.tris||[],pos:p.pos,rot:p.rot,scale:p.scale,material:p.material||"—",source:p.source||{}};
      return {id:p.id,kind:p.kind,size:p.size,pos:p.pos,rot:p.rot,scale:p.scale,material:p.material}; }); }
    let FORGE_LIB = {workshop:[],inventory:{results:[]},local:[],external:{}};
    async function loadLibrary(){ try{
        const r=await fetch("/api/v1/forge/library"); if(!r.ok) throw new Error("HTTP "+r.status);
        FORGE_LIB=await r.json(); renderLibrary();
      }catch(e){ $("forge-lib-list").innerHTML="<li>○ Library unavailable.</li>";
        $("forge-lib-honesty").textContent="Library failed: "+e; } }
    function libEntries(){ const q=($("forge-lib-search").value||"").toLowerCase();
      const all=[];
      (FORGE_LIB.workshop||[]).forEach(m=>all.push({group:"WORKSHOP",id:m.id,name:m.name,sub:(m.triangles||"?")+" tris · "+(m.mesh_verdict||"?"),open:{source:"workshop",ref:m.id}}));
      ((FORGE_LIB.inventory||{}).results||[]).forEach(m=>all.push({group:"INVENTORY",id:m.id,name:m.name||m.id,sub:m.type+" · provenance "+((m.provenance||{}).source_type||"?"),open:{source:"inventory",entity_type:m.type,ref:m.id}}));
      (FORGE_LIB.local||[]).forEach(m=>all.push({group:"LOCAL",id:m.id,name:m.name,sub:(m.type||"mesh")+" · unregistered",open:{source:"local",ref:m.id}}));
      const ext=FORGE_LIB.external||{};
      $("forge-lib-honesty").textContent="Sources: WORKSHOP ("+(FORGE_LIB.workshop||[]).length+") · INVENTORY ("+(((FORGE_LIB.inventory||{}).results||[]).length)+", "+((FORGE_LIB.inventory||{}).state||"?")+") · LOCAL ("+(FORGE_LIB.local||[]).length+") · EXTERNAL ("+(ext.state||"NOT_CONNECTED")+").";
      return all.filter(e=>!q||(e.name+e.group+e.id).toLowerCase().includes(q)); }
    function renderLibrary(){ const ul=$("forge-lib-list"); const items=libEntries().slice(0,20);
      ul.innerHTML=items.length?"":"<li>○ No models — register one in <a href='/3d'>/3d</a>.</li>";
      items.forEach(e=>{ const li=document.createElement("li");
        li.innerHTML="<span class='q-todo'>○</span> ";
        const b=document.createElement("button"); b.type="button"; b.textContent="Open";
        b.onclick=()=>openLibraryModel(e.open, e.name);
        li.appendChild(b); li.appendChild(document.createTextNode(" ["+e.group+"] "+e.name+" "));
        const s=document.createElement("span"); s.className="muted"; s.textContent=e.sub; li.appendChild(s);
        ul.appendChild(li); }); }
    async function openLibraryModel(open, name){ $("forge-status").textContent="Opening "+name+"… (read-only import, nothing stored)";
      try{ const r=await fetch("/api/v1/forge/open",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(open)});
        const j=await r.json();
        if(!r.ok){ $("forge-status").textContent="Import refused: "+JSON.stringify(j).slice(0,300); return; }
        if(!(j.parts||[]).length){ $("forge-status").textContent="Opened metadata ("+(j.title||j.ref||"?")+"): "+((j.geometry||{}).note||"no geometry — nothing imported."); forgeLog("inventory record opened (metadata only): "+(j.ref||"?")); return; }
        j.parts.forEach(p=>{ FORGE_SEQ+=1;
          ForgeSession.parts.push({id:"part_"+FORGE_SEQ+"_derived",name:(name||"imported").slice(0,60)+" #"+FORGE_SEQ,kind:"derived",
            size:{w:0,h:0,d:0},pos:p.pos,rot:p.rot,scale:p.scale,material:"—",source:p.source||{},
            tris:p.tris||[],validation:((p.derived||{}).validation||"?")}); });
        const last=ForgeSession.parts[ForgeSession.parts.length-1];
        selectPart(last.id,false); setDirty(true,"model imported: "+name+" ("+(j.provenance||{}).source+")");
        ForgeSession.model_id=(j.provenance||{}).source_ref||""; persistLine();
        $("forge-status").textContent="Imported "+name+" — editor-local until Save.";
        forgeLog("model opened: "+name+" ("+((j.parts[0].derived||{}).total_tris||"?")+" tris, "+j.source+")");
      }catch(e){ $("forge-status").textContent="Import failed: "+e; } }
    $("forge-lib-search").oninput=renderLibrary;
    $("forge-propose-form").onsubmit=async e=>{ e.preventDefault();
      const prompt=$("forge-prompt").value||"";
      if(!ForgeSession.selection.length){ $("forge-proposal").innerHTML="<p>Selecteer eerst een onderdeel (click / ctrl-click).</p>"; return; }
      $("forge-proposal").innerHTML="<p class='muted'>Proposing (read-only, no writes)…</p>";
      try{ const r=await fetch("/api/v1/forge/propose",{method:"POST",headers:{"Content-Type":"application/json"},
          body:JSON.stringify({selection:ForgeSession.selection,prompt:prompt,parts:sceneParts()})});
        const j=await r.json();
        if(!r.ok){ $("forge-proposal").innerHTML="<p>Proposal refused: "+JSON.stringify(j).slice(0,400)+"</p>"; FORGE_PROPOSAL=null; $("forge-apply").disabled=true; return; }
        FORGE_PROPOSAL=j.proposal;
        $("forge-proposal").innerHTML="<p>Proposal: <code>"+j.proposal.operation+" "+JSON.stringify(j.proposal.parameters)+"</code><br>targets: <code>"+j.proposal.target_selection.join(", ")+"</code><br>"+String(j.proposal.reason).slice(0,300)+"<br><span class='muted'>preview: "+j.proposal.preview.total_tris+" tris"+(j.proposal.preview.truncated?" (capped)":"")+(j.proposal.preview.removed!=null?(" · remove "+j.proposal.preview.removed+", "+j.proposal.preview.remaining+" remain"):"")+" · APPLY = editor-local · DISCARD = nothing.</span></p>";
        $("forge-apply").disabled=false;
        forgeLog("AI proposal: "+j.proposal.operation+" on "+j.proposal.target_selection.join(","));
      }catch(err){ $("forge-proposal").innerHTML="<p>Propose failed: "+err+"</p>"; } };
    $("forge-apply").onclick=()=>{ if(!FORGE_PROPOSAL) return;
      const patch=FORGE_PROPOSAL.preview.patch||{update:{},remove:[]};
      Object.keys(patch.update||{}).forEach(id=>{ const p=ForgeSession.parts.find(q=>q.id===id); if(!p) return;
        const u=patch.update[id];
        if(u.size) p.size=u.size; if(u.pos) p.pos=u.pos; if(u.rot) p.rot=u.rot; if(u.tris) p.tris=u.tris;
        ForgeSession.parameters[id]={pos:p.pos,rot:p.rot,scale:p.scale,size:p.size,material:p.material}; });
      (patch.remove||[]).forEach(id=>{ const i=ForgeSession.parts.findIndex(q=>q.id===id); if(i>=0) ForgeSession.parts.splice(i,1); });
      ForgeSession.selection=ForgeSession.selection.filter(id=>!(patch.remove||[]).includes(id));
      ForgeSession.selected_part=ForgeSession.selection[0]||"";
      ForgeSession.ai_edits.push({op:FORGE_PROPOSAL.operation,targets:FORGE_PROPOSAL.target_selection.slice(0,20),reason:String(FORGE_PROPOSAL.reason||"").slice(0,160)});
      FORGE_PROPOSAL=null; $("forge-apply").disabled=true;
      $("forge-proposal").innerHTML="<p class='muted'>Applied to editor state (dirty). DISCARD no longer possible for this one — Save stays gated.</p>";
      setDirty(true,"AI proposal applied: "+ForgeSession.ai_edits[ForgeSession.ai_edits.length-1].op);
      renderParts(); renderProps(); draw(); selLine(); slicerEstimate(); persistLine(); };
    $("forge-discard").onclick=()=>{ if(!FORGE_PROPOSAL){ $("forge-proposal").innerHTML="<p class='muted'>No proposal — select parts, describe the edit, Propose.</p>"; return; }
      forgeLog("AI proposal discarded: "+FORGE_PROPOSAL.operation); FORGE_PROPOSAL=null; $("forge-apply").disabled=true;
      $("forge-proposal").innerHTML="<p class='muted'>Discarded — nothing changed, nothing stored.</p>"; };
    $("forge-save").onclick=async ()=>{ const scene=sceneParts();
      if(!scene.length){ $("forge-status").textContent="Nothing to save."; return; }
      const name=($("forge-design-name").value||"Forge design").slice(0,200);
      $("forge-status").textContent="Saving geometry… (working file, no mutation)";
      try{ const r=await fetch("/api/v1/forge/save",{method:"POST",headers:{"Content-Type":"application/json"},
          body:JSON.stringify({design_name:name,parts:scene,forked_from:ForgeSession.forked_from,ai_edits:ForgeSession.ai_edits})});
        const j=await r.json();
        if(!r.ok){ $("forge-status").textContent="Save refused: "+JSON.stringify(j).slice(0,300); return; }
        ForgeSession.saved="SAVED "+j.derived_ref+" ["+j.validation.verdict+"]";
        setDirty(false); persistLine();
        forgeLog("geometry saved: "+j.derived_ref+" ("+j.total_tris+" tris, "+j.validation.verdict+")");
        $("forge-status").textContent="SAVED working file "+j.derived_ref+" — proposing via existing writes gate…";
        const w=await fetch("/api/v1/writes/inventory",{method:"POST",headers:{"Content-Type":"application/json"},
          body:JSON.stringify({mutation:"create",entity_type:"file",fields:j.file_payload,actor:"forge-studio"})});
        const wj=await w.json();
        if(!w.ok){ $("forge-status").textContent="Proposal refused: "+JSON.stringify(wj).slice(0,300);
          ForgeSession.saved+=" · PROPOSAL_FAILED"; persistLine(); return; }
        const pid=(wj.proposal&&wj.proposal.proposal_id)||"?";
        ForgeSession.saved+=" · PROPOSAL_PENDING "+pid; persistLine();
        $("forge-status").innerHTML="Proposal <code>"+pid+"</code> inert — APPROVAL_REQUIRED: exact YES in <a href='/writes'>/writes</a>. <button type='button' id='forge-check'>Check status</button>";
        forgeLog("file proposal "+pid+" pending (needs exact YES)"); renderPipeline();
        $("forge-check").onclick=async ()=>{ try{
            const s=await (await fetch("/api/v1/writes/"+encodeURIComponent(pid))).json();
            const map={proposed:"PROPOSAL_PENDING — APPROVAL_REQUIRED",approved:"APPROVED — execution via /writes",executed:"EXECUTED — verify via /writes",failed:"FAILED",rejected:"FAILED (rejected)"};
            let label=map[s.status]||s.status;
            if(s.verification&&s.verification.outcome==="passed") label="VERIFIED";
            else if(s.verification) label+=" · verification "+s.verification.outcome;
            ForgeSession.saved="SAVED "+j.derived_ref+" · "+label; persistLine();
            $("forge-status").textContent="Proposal "+pid+": "+label; forgeLog("proposal "+pid+" → "+label);
          }catch(e){ $("forge-status").textContent="Status check failed: "+e; } };
      }catch(e){ $("forge-status").textContent="Save failed: "+e; } };
    $("forge-open").onclick=async ()=>{ const ref=($("forge-open-ref").value||"").trim();
      if(!ref){ $("forge-status").textContent="Enter a derived reference first."; return; }
      try{ const r=await fetch("/api/v1/fab/mesh/preview?artifact_ref="+encodeURIComponent(ref)+"&max_tris=5000");
        const j=await r.json();
        if(!r.ok){ $("forge-status").textContent="Reload refused: "+JSON.stringify(j).slice(0,200); return; }
        FORGE_SEQ+=1;
        const p={id:"part_"+FORGE_SEQ+"_derived",name:"derived #"+FORGE_SEQ,kind:"derived",
          size:{w:0,h:0,d:0},pos:{x:0,y:0,z:0},rot:{x:0,y:0,z:0},scale:{x:1,y:1,z:1},
          material:"—",tris:j.tris||[],validation:j.format};
        ForgeSession.parts.push(p); selectPart(p.id);
        ForgeSession.model_id=ref; persistLine();
        $("forge-status").textContent="Reloaded "+j.total_tris+" tris from "+j.artifact_ref+(j.truncated?" (capped)":"")+" — reference, params read-only.";
        forgeLog("model opened: "+j.artifact_ref+" ("+j.total_tris+" tris)");
      }catch(e){ $("forge-status").textContent="Reload failed: "+e; } };
    $("forge-ask-form").onsubmit=async e=>{ e.preventDefault(); const q=$("forge-ask-input").value;
      $("forge-advice").innerHTML="<p class='muted'>Thinking (read-only)…</p>";
      try{ const r=await fetch("/api/v1/forge/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:q})});
        const j=await r.json(); if(!r.ok){ $("forge-advice").innerHTML="<p>Refused: "+JSON.stringify(j).slice(0,300)+"</p>"; return; }
        let html="<ul>"+j.advice.map(a=>"<li>"+String(a).slice(0,400)+"</li>").join("")+"</ul>";
        (j.routes||[]).forEach(rt=>{ html+="<a class='chip' href='"+rt.href+"'>"+rt.label+"</a> "; });
        if(j.proposed_op){ html+="<p>Proposed op: <code>"+j.proposed_op.op+" "+JSON.stringify(j.proposed_op.params)+"</code> ("+j.proposed_op.interpretation+") "
          +"<button type='button' id='forge-apply-op'>Preview</button></p>";
          $("forge-advice").innerHTML=html;
          $("forge-apply-op").onclick=()=>{ const p=ForgeSession.parts.find(x=>x.id===ForgeSession.selected_part)||ForgeSession.parts[0]; if(!p){ return; }
            if(j.proposed_op.op==="extend"){ const ax=j.proposed_op.params.axis||"x", d=j.proposed_op.params.delta_mm||0;
              const key=ax==="x"?"w":ax==="y"?"h":"d"; p.size[key]=Math.max(0.1,p.size[key]+d); }
            renderProps(); setDirty(true,"mycelium proposal previewed: "+j.proposed_op.op); draw(); slicerEstimate(); }; }
        else $("forge-advice").innerHTML=html;
        $("forge-advice").innerHTML+="<details><summary>Mission draft (unsaved)</summary><code>"+JSON.stringify(j.mission_draft).slice(0,800)+"</code><br><a href='/missions'>Submit via Missions →</a></details>"
          +"<p class='muted'>"+j.honesty+" · physical: "+j.physical+"</p>";
      }catch(e){ $("forge-advice").innerHTML="<p>Ask failed: "+e+"</p>"; } };
    draw(); loadSession();
    </script>"""
    context = (
        _ui.context_block(
            "Forge",
            "<p>Forge NPC (capability: machine) + Forge Studio "
            "(werkplek). NPC blijft in "
            "<a href=\"/play\">/play</a>; werken doe je hier.</p>")
        + _ui.context_block(
            "Flow",
            "<p>DESIGN &rarr; VALIDATE &rarr; SLICE (TEST) &rarr; "
            "APPROVAL (exact YES) &rarr; PRINT "
            "(HARDWARE_REQUIRED).</p>")
        + _ui.context_block(
            "Bestaande routes",
            "<p><a href=\"/3d\">3D workbench</a> · "
            "<a href=\"/workshop/3d\">3D viewer</a> · "
            "<a href=\"/writes\">Writes</a> · "
            "<a href=\"/missions\">Missions</a> · "
            "<a href=\"/research\">Research</a> · "
            "<a href=\"/fabrication\">Fabrication</a></p>"))
    return _ui.shell("Forge Studio", "/forge", main, context,
                     _ui.command_bar())
