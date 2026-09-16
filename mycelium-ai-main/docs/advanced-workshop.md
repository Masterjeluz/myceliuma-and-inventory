# Advanced Workshop (BIG #11-15, Phase 4) — IMPLEMENTED

On top of the BIG #7/#10 pipeline: scene-level
interaction over objects, meshes, printers and tools
with select/inspect/group semantics in the UI, and
safe geometry ops behind preview-first endpoints.

## Mesh ops (pure, bounded, no code execution)

mirror, merge, translate/rotate/scale (existing),
extend (dimension ±, guarded against inversion),
orient (flattest side down, deterministic), volume
estimate, repair proposal (data only — the source
file is untouched).

## Prompt editing

"maak deze bracket 5mm langer" parses through closed
patterns to an explicit op (or refuses on ambiguity):
selected object → parsed intent → geometry proposal →
preview → before/after → derived artifact + hash +
provenance → human approval → persist. Persisting
always needs a named approver.

## Fabrication pipeline

IDEA → CAD → MESH → VALIDATION → SLICING → G-code →
PRINTER → PRINT → CAMERA → TELEMETRY → VERIFICATION
→ INVENTory, planned by `plan_pipeline` as data.
Preparation is actionable; the physical start stays
behind the existing proposal + exact-YES gates, and
verification still needs telemetry AND camera.
Filament spools are local resource records with
estimate-vs-remaining checks (estimates labelled,
never sensor-certain).
