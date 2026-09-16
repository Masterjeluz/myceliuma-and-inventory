# CAD (BIG #11-15, Phase 4) — PARTIAL

CadDocument → parts → parametric operations
(box/cylinder/transform/advanced) → derived mesh.
Documents persist locally with provenance; building
executes only the procedural adapter (pure-math
facets through the existing derived-mesh path).

External adapters (OpenSCAD, FreeCAD, Blender) exist
with explicit requirements and report UNAVAILABLE:
a future executor needs allow-list → proposal →
approval → sandbox → result → verification, with a
pinned binary, fixed argv allow-list, bounded
capture and no network. No subprocess exists in
this module; adding a runtime must document why,
license, offline behaviour, security impact and
fallback (none is added here — the procedural
builder covers local needs).
