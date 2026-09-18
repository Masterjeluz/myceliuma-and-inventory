# 3D Workflow (BIG #35: workbench)

PHOTO / OBJECT → OBSERVATION → 3D MODEL CANDIDATE → MODEL → EDIT →
PREPARE → SLICE → G-CODE → PRINTER → VERIFY.

Full ecosystem in `docs/3d-workshop.md`.

## What exists (REAL)

- Procedural/test mesh generation + STL/OBJ validation + printability
  assessment (`mesh3d.py`, `meshops.py`, `cad.py` procedural only)
- Wireframe preview + validated transform proposals (rotate/translate/
  scale) in `/workshop/3d`; persisting makes a derived file + payload
  for the proposal/approval path — never auto-registered
- Test slicer + G-code safety assessment (`slicer3d.py`; preview-only,
  never-for-printers, no `safe_to_execute` anywhere)
- Fabrication orchestration (`fabrication.py`, `fab_flow.py`,
  `printer3d.py`): proposal → physical exact-YES → simulated
  execution → telemetry + camera verification; software cancel ≠
  e-stop
- `/3d` pipeline view with stage chips: READY / WAITING / SIMULATED /
  TEST / HARDWARE_REQUIRED / UNAVAILABLE

## What is missing (UNAVAILABLE / HARDWARE_REQUIRED)

True photo→mesh reconstruction transport and real printer
transports. OBJECT → CREATE 3D MODEL says so openly and offers the
procedural/test workflow instead. No fake generated mesh, ever.

## Linking a model

A model links visibly to project / file / object / research / mission
/ fabrication plan through existing relations where they exist, or
explicit candidate relations (dashed overlays in `/world`) where the
source is a Mycelium domain. Chain inspection: `/workshop`, per-run
`/workshop?fabrication_id=...`, `/fabrication`.

New in BIG #31: the **Connect a model** panel on `/3d` (and the
propose forms on `/writes`) create `create_relationship` write
proposals with closed predicates (`used_in`, `part_of`,
`produced_by`, `related_to`, …). The proposal waits in the
`/writes` inbox for an exact YES — nothing links itself. Object
creation from mobile follows the same inbox (`/web/objects/propose`
→ YES → execute → verify).

## Related relations (BIG #32)

`/3d?entity_id=mod_…` shows the entity's CONNECTED TO panel
(stored relations via the ecosystem context) with a link into
the world graph — model ↔ project ↔ file ↔ object ↔ research
becomes navigable instead of implied. Links themselves are still
proposed through `/writes` and need YES.

## Workbench (BIG #35)

`/3d` is now one workbench: Models (`mdl_…` registry, STL/OBJ
inspection, 3MF/GLB/GLTF metadata-only), Materials (known /
candidate / unknown), per-entity presence checklists with gaps,
fab jobs (designed → … → verified state machine around the
existing YES flow), Machines (printer badges SIMULATED /
UNAVAILABLE + mesh-capable nodes), link proposals (PROPOSED
symbiosis), continuation packet (`/api/v1/workshop/packet`),
real progress bars. Details in `docs/3d-workshop.md`.
