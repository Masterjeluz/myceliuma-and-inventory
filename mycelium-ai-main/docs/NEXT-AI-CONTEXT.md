# NEXT-AI-CONTEXT — continue Mycelium development here

Date: 2026-09-18. HEAD: `BIG #35 - build 3D workshop ecosystem`
(main, pushed to origin/main). Start with `git log --oneline -5`
and `git status` (a pre-existing `Mycelium/agent/agent_ui.py`
modification is NOT ours — leave it).

## Architecture in one paragraph

Local-first personal AI: coordinator (`:8000`, FastAPI + SQLite
WAL) is the authority (approvals, tasks, leases, missions);
INVENTory (`:8080`) is the world memory, read via GET-only
loopback bridge (`inventory_read.py`), written only via gated
proposals (`inventory_writes.py` + exact YES + verification);
Ollama/external models are advisors (never authority); desktop
agent is the only hands (pull-only, outbound). Provenance always;
health scoped; no shell/RCE; no background threads (jobs run on
explicit trigger). Tests: `pytest -v` per project with tmp DB
env vars (`MYCELIUM_DATABASE_PATH`, `MYCELIUM_CHAT_DATABASE_PATH`
before TestClient; `MYCELIUM_FABRICATION_DIR` for fab tests).
Full Mycelium suite: 1199 tests, batch-run (single run exceeds
10-min timeout); INVENTory: 179 + 1 pre-existing byte-size
failure (do not touch that test).

## What BIG #35 added (where)

- `coordinator/app/workshop3d.py` — `mdl_`/`mat_`/`fabjob_`
  registries (additive chat-DB tables), inbox-pattern model
  ingest (STL/OBJ scanned, 3MF/GLB/GLTF metadata-only,
  sha256 dedupe), closed link predicates → connection
  candidates, 13-stage fab-job machine deriving
  approval/execution from write records + PrintResult,
  camera two-half verification, presence checklists,
  continuation packet.
- `main.py` — 16 API routes (`/api/v1/workshop/*`) + 5 web
  routes; /3d workbench (Models/Materials/Presence/
  Fabrication/Machines/Connect/Workspace/Runs); mobile
  Workbench; honest printer badges.
- `ui.py` — `stage_progress()` (real bars, no XP);
  `living_bg()` reads living_state (density 8–48, amber on
  waiting approvals; ambient only, reduced-motion safe).
- `guide.py` — workshop items + `workshop` kind.
- `symbiosis.py` — `mdl_`/`mat_`/`fabjob_` prefixes.
- Tests: `tests/test_big35_workshop.py` (13).
- Scripts: `scripts/b35_smoke.py` (tmp-DB full chain).
- Lessons: WriteResult uses `outcome` (+
  `after.print_result.status`), NOT `result.status`;
  SlicerResult field is `sha256`; check_artifact_ref covers
  only STL/OBJ/G-code (models need their own gate);
  binary-STL header is 80 bytes; never insert helpers
  between a route decorator and its function.

## Docs to read first

`docs/ARCHITECTURE_STATUS.md` (truth), `docs/ROADMAP.md` +
`docs/ROADMAP-V2.md` (BIG #36–40), `docs/3d-workshop.md`,
`docs/3d-workflow.md`, `docs/camera-ecosystem.md`,
`docs/living-ecosystem.md`, `docs/knowledge-lifecycle.md`,
`docs/research-routing.md`, `docs/context-packets.md`,
`docs/mycelium-ui-personality.md`,
`docs/BIG35-final-report.md` (§2 = commit/push record).

## Next BIG (from BIG35 report §13 / ROADMAP-V2)

BIG #36: Mobile Mycelium — phone as primary input surface
(approval triage, packet handoff, per-node notification
deep-links, camera-inbox guidance, all on existing flows).
Constraints: no new stores, existing gates, honest labels,
tmp DBs, screenshots in `docs/r36-shots/`, one commit
`BIG #36 - ...`, push to `origin/main`.
