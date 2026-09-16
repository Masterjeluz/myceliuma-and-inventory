"""Advanced mesh operations (BIG #11-15, Phase 4).

Pure, bounded geometry over facet lists from mesh3d — no
scripting, no code execution, no file access here. Every op
validates first (fail-closed) and returns new facets; the
caller previews, and only an explicit persist writes a
derived working file (existing write_derived_mesh path).

Ops: mirror, merge, extend (dimension +=, geometrically
guarded), orient (flattest side down), volume estimate,
repair proposal (data only, never mutation), prompt parsing
("maak deze bracket 5mm langer" → explicit op or refusal).
"""

import math

ADVANCED_OPS = frozenset({
    "mirror",
    "merge",
    "extend",
    "orient",
})

MAX_FACETS = 5000
MAX_DELTA_MM = 100.0


class MeshOpRefusedError(ValueError):
    """Fail-closed geometry validation."""


def _check_facets(facets) -> list:
    if not isinstance(facets, list) or not facets:
        raise MeshOpRefusedError("facets must be a non-empty list")
    if len(facets) > MAX_FACETS:
        raise MeshOpRefusedError(
            f"at most {MAX_FACETS} facets per op")
    cleaned = []
    for facet in facets:
        try:
            points = [(float(point[0]), float(point[1]),
                       float(point[2])) for point in facet]
        except (TypeError, ValueError, IndexError):
            raise MeshOpRefusedError(
                "facets must hold (x, y, z) numbers")
        if len(points) != 3 or any(
                not math.isfinite(coord) for point in points
                for coord in point):
            raise MeshOpRefusedError(
                "facets must be finite triangles")
        cleaned.append(tuple(points))
    return cleaned


def check_advanced_op(op: str, params) -> dict:
    """Validate one advanced op. No side effects."""
    if op not in ADVANCED_OPS:
        raise MeshOpRefusedError(
            f"Unknown advanced op '{op}'; expected one of "
            f"{sorted(ADVANCED_OPS)}")
    if not isinstance(params, dict):
        raise MeshOpRefusedError("params must be an object")
    if op == "mirror":
        plane = str(params.get("plane", ""))
        if plane not in ("x", "y", "z"):
            raise MeshOpRefusedError(
                "mirror needs plane x, y or z")
        if set(params) - {"plane"}:
            raise MeshOpRefusedError(
                "mirror carries unexpected params")
        return {"plane": plane}
    if op == "extend":
        axis = str(params.get("axis", ""))
        if axis not in ("x", "y", "z"):
            raise MeshOpRefusedError(
                "extend needs axis x, y or z")
        try:
            delta = float(params.get("delta_mm", 0.0))
        except (TypeError, ValueError):
            raise MeshOpRefusedError("delta_mm must be a number")
        if not math.isfinite(delta) or delta == 0.0 or \
                abs(delta) > MAX_DELTA_MM:
            raise MeshOpRefusedError(
                f"delta_mm must be nonzero within "
                f"+/-{MAX_DELTA_MM}")
        if set(params) - {"axis", "delta_mm"}:
            raise MeshOpRefusedError(
                "extend carries unexpected params")
        return {"axis": axis, "delta_mm": delta}
    if set(params):
        raise MeshOpRefusedError(
            f"{op} takes no params")
    return {}


def mirror_facets(facets, plane: str) -> list:
    """Mirror across the origin plane. Winding flips — the
    derived file re-validates downstream, never assumed."""
    cleaned = _check_facets(facets)
    index = {"x": 0, "y": 1, "z": 2}[plane]
    out = []
    for facet in cleaned:
        mirrored = tuple(
            tuple(-coord if axis == index else coord
                  for axis, coord in enumerate(point))
            for point in facet)
        out.append(mirrored)
    return out


def merge_facets(groups: list) -> list:
    """Concatenate facet groups (duplicate = place twice).
    Bounded total; each group validated."""
    if not isinstance(groups, list) or not groups or \
            len(groups) > 10:
        raise MeshOpRefusedError("merge needs 1..10 groups")
    merged: list = []
    for group in groups:
        merged.extend(_check_facets(group))
        if len(merged) > MAX_FACETS:
            raise MeshOpRefusedError(
                f"merged mesh exceeds {MAX_FACETS} facets")
    return merged


def bounds_of(facets) -> tuple:
    cleaned = _check_facets(facets)
    axes = [[point[axis] for facet in cleaned
             for point in facet] for axis in range(3)]
    return tuple((min(values), max(values)) for values in axes)


def extend_facets(facets, axis: str,
                  delta_mm: float) -> list:
    """Dimension extension: vertices on the maximum plane
    along axis move by delta_mm (positive grows, negative
    shrinks but never past the minimum plane). Only planar
    end-caps move; interior geometry is untouched."""
    cleaned = _check_facets(facets)
    index = {"x": 0, "y": 1, "z": 2}[axis]
    coords = [point[index] for facet in cleaned
              for point in facet]
    lowest, highest = min(coords), max(coords)
    size = highest - lowest
    if size <= 0:
        raise MeshOpRefusedError("mesh is flat on this axis")
    if delta_mm < 0 and size + delta_mm <= 0:
        raise MeshOpRefusedError(
            "shrink would invert the dimension; refusing")
    epsilon = max(size * 1e-6, 1e-6)
    return [tuple(tuple(
        coord + delta_mm if axis_index == index
        and coord >= highest - epsilon else coord
        for axis_index, coord in enumerate(point))
        for point in facet) for facet in cleaned]


def orient_facets(facets) -> tuple[list, dict]:
    """Rotate so the smallest extent is Z (flattest side
    down): tries identity, X-90 and Y-90, picks the rotation
    with minimal Z size. Deterministic."""
    cleaned = _check_facets(facets)
    import math as _math
    variants = []
    for name, transform in (
            ("identity", lambda p: p),
            ("rot_x90", lambda p: (p[0], -p[2], p[1])),
            ("rot_y90", lambda p: (p[2], p[1], -p[0]))):
        moved = [tuple(transform(point) for point in facet)
                 for facet in cleaned]
        zed = [point[2] for facet in moved for point in facet]
        variants.append((max(zed) - min(zed), name, moved))
    variants.sort(key=lambda item: item[0])
    _, name, moved = variants[0]
    return moved, {"rotation": name,
                   "method": "minimal Z extent over "
                             "identity/X-90/Y-90"}


def mesh_volume_cm3(facets) -> float:
    """Absolute summed tetra volume vs origin, in cm³.
    Estimate input for filament math, never a guarantee."""
    cleaned = _check_facets(facets)
    total = 0.0

    def dot(point, other):
        return sum(a * b for a, b in zip(point, other))

    def cross(point, other):
        return (point[1] * other[2] - point[2] * other[1],
                point[2] * other[0] - point[0] * other[2],
                point[0] * other[1] - point[1] * other[0])
    for facet in cleaned:
        total += dot(facet[0], cross(facet[1], facet[2])) / 6.0
    return round(abs(total) / 1000.0, 4)


def repair_proposal(report) -> dict:
    """Data-only repair suggestion from a validation report.
    Proposes, never mutates."""
    verdict = getattr(report, "verdict", "inconclusive")
    reasons = list(getattr(report, "reasons", []) or [])
    faces = int(getattr(report, "faces", 0) or 0)
    suggestions = []
    for reason in reasons:
        lowered = str(reason).lower()
        if "degenerate" in lowered or "zero-area" in lowered:
            suggestions.append(
                "drop zero-area facets, then re-validate")
        elif "non-manifold" in lowered or "edge" in lowered:
            suggestions.append(
                "run a mesh-repair pass in CAD, then re-import; "
                "no automatic stitching here")
        elif "normal" in lowered:
            suggestions.append(
                "recompute facet normals in CAD, then re-import")
        else:
            suggestions.append(
                f"inspect '{reason}' in CAD; no auto-fix offered")
    if verdict == "valid":
        suggestions = ["mesh already valid; nothing to repair"]
    return {"verdict": verdict, "faces": faces,
            "issues": reasons[:10],
            "suggestions": suggestions[:10],
            "note": "proposal only; the source file is untouched"}


def parse_prompt_edit(text: str) -> dict:
    """Parse 'maak deze bracket 5mm langer' style intents.
    Returns {op, params} or refuses on ambiguity. Closed
    patterns only — no LLM, no guessing."""
    import re
    if not isinstance(text, str) or not text.strip():
        raise MeshOpRefusedError("prompt edit needs text")
    lowered = text.strip().lower()
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*mm\s*(langer|korter|groter|kleiner)",
        lowered)
    if match:
        delta = float(match.group(1).replace(",", "."))
        if "kort" in match.group(2) or "klein" in match.group(2):
            delta = -delta
        axis = "x"
        for token, name in (("x-richting", "x"),
                            ("y-richting", "y"),
                            ("z-richting", "z"),
                            ("lengte", "x"), ("breedte", "y"),
                            ("hoogte", "z"), ("dik", "z")):
            if token in lowered:
                axis = name
                break
        return {"op": "extend",
                "params": {"axis": axis, "delta_mm": delta},
                "interpretation": f"extend {axis} by {delta}mm "
                                  "(parsed, unconfirmed)"}
    if "spiegel" in lowered or "mirror" in lowered:
        plane = "x"
        for token in ("x", "y", "z"):
            if f" {token}" in lowered or f"{token}-" in lowered:
                plane = token
                break
        return {"op": "mirror", "params": {"plane": plane},
                "interpretation": f"mirror across {plane} "
                                  "(parsed, unconfirmed)"}
    raise MeshOpRefusedError(
        "could not parse a safe edit (try '5mm langer', "
        "'10mm korter in z-richting', or 'spiegel x'); "
        "nothing was changed")
