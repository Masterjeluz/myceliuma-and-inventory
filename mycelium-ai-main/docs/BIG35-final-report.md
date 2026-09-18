# BIG #35 — 3D Workshop Ecosystem: final report

## 1. Status

DONE — built, tested, smoked, screenshotted, documented,
committed, pushed.

## 2. Commit SHA

`BIG #35 - build 3D workshop ecosystem` (see §3; SHA in git
log — verified against remote HEAD after push).

## 3. Files changed

New: `coordinator/app/workshop3d.py`,
`tests/test_big35_workshop.py`, `scripts/b35_smoke.py`,
`docs/r35-shots/` (7 PNGs), `docs/3d-workshop.md`,
`docs/BIG35-final-report.md` (this file). Extended:
`coordinator/app/main.py` (16 API + 5 web routes, /3d
workbench, mobile workbench, printer badges),
`coordinator/app/ui.py` (`stage_progress`,
activity-aware `living_bg`), `coordinator/app/guide.py`
(workshop items + kind), `coordinator/app/symbiosis.py`
(`mdl_`/`mat_`/`fabjob_` prefixes), `docs/3d-workflow.md`,
`docs/NEXT-AI-CONTEXT.md`, `docs/ROADMAP-V2.md`.

## 4. Features built

- Model registry (`mdl_…`): inbox-pattern ingest for
  STL/OBJ/3MF/GLB/GLTF, sha256 dedupe, stdlib geometric scan
  (STL binary+ascii, OBJ) with honest UNKNOWNs, mesh-validator
  verdicts.
- Materials (`mat_…`): known/candidate/unknown, suggestions,
  no green claims.
- Workshop→world links: closed 10-predicate set as PROPOSED
  symbiosis via connection candidates.
- Fab jobs (`fabjob_…`): 13-stage state machine deriving
  approval/execution from the stored write record +
  PrintResult; TEST slicing labeled; unavailable slicer
  blocks honestly; cancel rules (never after print).
- Camera verification: observation attach + two-half verify
  (telemetry completed + camera readback passed) + named
  human → verified.
- Presence checklists with actionable gaps; continuation
  packet (`mycelium-3d-workshop/1`, Markdown+JSON, no
  secrets); real progress bars; activity-reactive ambient
  background; /3d workbench (Models/Materials/Presence/
  Fabrication/Machines/Connect/Workspace/Runs); mobile
  Workbench; guide workshop items; mesh-node panel.

## 5. Integrations reused

mesh3d/slicer3d/printer3d/fab_flow/verification/vision_flow
(cameras, observations), missions steps, worldgraph
overlays, knowledge, symbiosis, craft, guide, living_state,
events/notifications (no new types), mobile, context-packet
conventions, nodemesh validate, writes approve/execute. No
gate removed, no provenance relaxed, no INVENTory change.

## 6. REAL / TEST / SIMULATED / UNAVAILABLE

REAL: registry, inspection of parsed geometry, links,
presence, packet, progress, guide, machines list, file
payloads, preparation metadata. TEST: test-slicer G-code
(labeled never-for-printers), procedural meshes,
SimulatedPrinterAdapter telemetry. SIMULATED: print
execution (explicitly marked, never REAL). UNAVAILABLE:
real slicer/printer transports, photo→mesh reconstruction,
native mobile upload, web push, STT.

## 7. Tests before/after

Before: 1186 collected. After: **1199 collected (1186 + 13
new), all green** — full suite verified file-by-file
across all 104 test files in 9 bounded batches (1191) plus
the missed-file follow-up (8), 0 failures. New: 13
(`test_big35_workshop.py`). INVENTory: 179 passed + the
same 1 pre-existing failure (code untouched).

## 8. Smoke results

`scripts/b35_smoke.py` on tmp DBs, real HTTP: register →
inspect (1 triangle, UNKNOWNs honest) → material → fabjob →
prepare → TEST slice → inert propose → execute-before-YES
409 → YES → SIMULATED execute → printed-simulated →
observe → human verify → presence 4/5 → packet → 7 pages
200. All OK.

## 9. Screenshots

`docs/r35-shots/`: 3d-1440 (workbench with real models,
material, honest badges), 3d-390, craft, guide, symbiosis,
world, mobile-390. Edge headless, tmp DBs, real seed data.
Reviewed: stages honest (IMPORTED pre-inspection,
UNAVAILABLE printer without adapter), contracts intact.

## 10. Security results

Tested: traversal, unsupported formats, missing/oversize
files, malformed STL bytes, fake workshop/entity IDs, bad
predicates/kinds/states/profiles/printers, illegal
transitions, replay/dedupe, approval-bypass (execute before
YES 409), cancel-after-print refuse, hostile metadata
stored-as-data + escaped on render, prompt-injection text
in names/notes. No shell/eval/subprocess/URLs/credentials;
model bytes parsed with struct only.

## 11. Known limitations

Ollama/VLM REAL path needs a local backend (fallback
proven); no native mobile upload (inbox pattern);
no video/360-still extraction; reviewed extract executor
still future; seed chips show raw IDs without INVENTory
names (pre-existing); full suite needs batching (>10 min
single run); camera-ctypes Windows noise pre-existing.

## 12. What Jelles can actually do tomorrow

Copy an STL into the fab dir → register+inspect on /3d →
add PLA as known → link model to the solar project →
start fab job → prepare → TEST slice → propose print →
YES in Writes → SIMULATED execute → sync → photograph the
result → attach observation → verify as Jelles → watch
presence go 5/5 and the guide go quiet. Copy the workshop
packet to another AI to continue elsewhere.

## 13. Next BIG recommendation

BIG #36 — Mobile Mycelium (phone as primary input surface:
approval triage, packet handoff, per-node notification
deep-links, camera-inbox guidance — all on existing flows).
