# 3D Workshop Ecosystem (BIG #35)

The 3D system is no longer an isolated page. Models are
living citizens of the workshop:

    MODEL ↔ OBJECT ↔ MATERIAL ↔ PROJECT ↔ IDEA ↔ MACHINE ↔
    FABRICATION ↔ OBSERVATION ↔ VERIFICATION ↔ KNOWLEDGE ↔
    SYMBIOSIS ↔ CRAFT TREE

A model is not a file. It can be part of a project, derived
from an idea, made from materials, produced by a machine, a
replacement part, a prototype, evidence — all through the
existing world model. No second 3D universe was built.

## Model lifecycle (all states explicit)

DISCOVER → IMPORT → INSPECT → UNDERSTAND → CONNECT →
MODIFY → PREPARE → SLICE → FABRICATE → OBSERVE → VERIFY →
LEARN → UPDATE WORLD.

- **Import** (`POST /api/v1/workshop/models`): the operator
  copies STL/OBJ/3MF/GLB/GLTF into the fabrication dir (like
  the camera inbox); registration records `mdl_…` id,
  filename, MIME, size, sha256, provenance, timestamp,
  source. Same bytes never register twice (replay refused).
  Traversal, unsupported formats, oversize and missing files
  refuse. Model bytes are parsed as data, never executed.
- **Inspect** (`POST .../inspect`): STL/OBJ get a geometric
  scan (triangles, vertices, bounding box) plus the existing
  mesh-validator verdict. Manifold, units and volume stay
  UNKNOWN unless actually determined — never invented.
  3MF/GLB/GLTF register metadata-only (inspection UNKNOWN).
- **Connect**: links are connection candidates (PROPOSED
  symbiosis) with a closed predicate set (`represents`,
  `requires`, `used_in`, `generated_from`, `fabricated_by`,
  `replacement_for`, `compatible_with`, `verified_by`,
  `part_of`, `related_to`). YES/NO/REVIEW via knowledge.
- **Modify**: existing procedural/test transform + preview
  flows (`/workshop/3d`, fab endpoints) — untouched.
- **Prepare/Slice**: fab-job `prepare` (mesh must be valid +
  printability assessment) and `slice` (TEST slicer labeled,
  anything else UNAVAILABLE → blocked with reason).
- **Fabricate**: print proposals go through the existing
  writes flow (`printer.execute`, exact YES). Fab-job stages
  DERIVE from the stored write record and PrintResult —
  the workshop never approves or executes. Simulated
  execution reports SIMULATED telemetry, never REAL.
- **Observe/Verify**: attach a real camera observation,
  then verify with both halves (execution telemetry +
  observation readback) and a named human verifier.
- **Learn/Update**: candidates, symbiosis, craft gaps, guide
  items and morning carry results back into the world.

## Materials (known / candidate / unknown)

`POST /api/v1/workshop/materials`: name, kind (closed set),
state, notes, linked entity. Suggestions (`.../suggest`)
rank known stock first — suggestions, never assignments.
Sustainability text is an operator note, never a verified
claim: no green claims by name.

## Fabrication honesty

REAL: preparation metadata, validation, TEST slicing,
workflow state, relationships, provenance. SIMULATED:
printer execution where explicitly marked (simulated
adapter only). UNAVAILABLE: real printer transport. A
SIMULATED print never becomes REAL. Software cancel is a
state transition (and refused once plastic exists); it is
never an e-stop.

## Camera verification (BIG #34 integration)

`observe` needs a stored camera observation;
`verify` needs completed telemetry + passed camera readback
+ a named human. Observation confirms the object; identity
becomes human-confirmed only through YES.

## Craft, guide, mobile, notifications, nodes, packets

- `/craft` picks models up through graph overlays;
  `GET /api/v1/workshop/presence` gives a per-entity
  checklist (✓ present / ? missing) with actionable gaps.
- Guide gains workshop items (bare model, awaiting
  verification, blocked job, reusable model).
- Mobile gains a Workbench panel (input only; YES gates
  intact). WEB_PUSH stays UNAVAILABLE.
- Notifications reuse `fabrication_ready`,
  `candidate_waiting`, `new_connection`, `camera_ready`.
- `/3d` shows mesh-capable nodes (read-only); delegation
  uses the existing mesh validate + task claims.
- `GET /api/v1/workshop/packet` emits a continuation
  section (model, stage, material, facts, blockers, next
  actions, provenance, approvals — no secrets) another AI
  can continue from.

## Progress + living background

`stage_progress()` renders real bars (`[██████░░░░] 60%`)
with ✓/○/■ checklists from backend states — no XP, no
levels. The spore canvas now scales density (8–48) with
24h ecosystem activity and tints amber while approvals
wait; ambient only, reduced-motion safe, never implying
events that did not happen.
