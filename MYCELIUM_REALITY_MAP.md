# MYCELIUM REALITY MAP — factual audit at HEAD

Date (UTC): 2026-09-25
> **Historical snapshot.** This audit describes repository state on 2026-09-25 and is not the current implementation status. The repository layout, coordinator scheduler, service state, and Obsidian setup have since changed. For current architecture and live checks, use `AGENTS.md`, `PROJECTATLAS.md`, `docs/CURRENT_STATE.md`, and `Mycelium-Knowledge-Vault/What works today.md`; executable code and tests remain authoritative. Detailed findings below are preserved as dated audit notes.
Method: static inspection of code + test files + docs. No test execution for this audit (per instruction). No code modifications, no commits.
Evidence tags used on every claim: **VERIFIED FROM CODE** / **VERIFIED FROM TESTS** (static test-file inspection only, not execution) / **DOCUMENTATION CLAIM** / **UNCERTAIN**.

## HEAD / scope

- `inventory/` is the only git repo here. HEAD: `6697e9a` **VERIFIED FROM CODE** (`git rev-parse --short HEAD` in `inventory/`). Branch `main...origin/main [ahead 10]`, untracked `../AI_HANDOFF/`, `../MYCELIUM_AI_HANDOFF.zip` **VERIFIED FROM CODE** (`git status --short`).
- Root is a plain folder, not a monorepo: no workspace config, no root git repo, no shared dependencies **VERIFIED FROM CODE** (`AGENTS.md`, directory listing).
- `mycelium-ai-main/` is not under git **VERIFIED FROM CODE** (no `.git` in listing; `AGENTS.md`). No HEAD SHA available for it.
- `Mycelium/agent/` is a local desktop agent, not under git **VERIFIED FROM CODE**.
- Trust rule applied: `app/main.py`, `app/database.py`, `app/schemas.py`, `tests/` over prose **DOCUMENTATION CLAIM** (`AGENTS.md` "Docs lag behind code") but confirmed by direct inspection below.

## Status labels

- 🟢 WORKING / USABLE — backend + route + some UI + tests exist; usable today by a technical local user.
- 🟡 BACKEND EXISTS, UI OR INTEGRATION MISSING — API + tests exist, user-facing or real-world side missing.
- 🟠 PARTIAL / STUB / UNCERTAIN — code present but simulated/mocked/gated, or contradicts docs, or deploy-broken.
- 🔴 BROKEN — import/dep or contract break verifiable statically.
- ⚪ NOT IMPLEMENTED — no code found.

## Global finding: frontend

There is no real frontend anywhere in the repository **VERIFIED FROM CODE**:
- Glob for `**/*.tsx`, `**/*.jsx`, `**/*.vue`, `**/*.html`, `**/static/**/*`, `**/templates/**/*` in source returns 0 hits (only `.venv/.git` excluded noise).
- `inventory/pyproject.toml` deps: `fastapi, uvicorn[standard], pydantic` only **VERIFIED FROM CODE**. `mycelium-ai-main/pyproject.toml` deps: `fastapi, uvicorn[standard], httpx, psutil` only **VERIFIED FROM CODE**. No `Jinja2`, no `StaticFiles`, no `package.json`/`vite`/`tsconfig`.
- All UI is server-rendered inline Python HTML via `HTMLResponse`/`RedirectResponse`/`render_template_string` **VERIFIED FROM CODE** (`inventory/app/main.py`, `mycelium-ai-main/coordinator/app/main.py` + `ui.py` 1089L, `Mycelium/agent/agent_ui.py` 87L Flask).
- Screenshots in `mycelium-ai-main/docs/r33-shots|v1-shots` prove pages render **DOCUMENTATION CLAIM** (not re-verified here). See `MYCELIUM_UI_GAP_MAP.md` for the full backend→UI gap table.

## Global finding: hard boundaries (hold)

- No cross-imports, no shared DB **VERIFIED FROM CODE** (separate `INVENTORY_DATABASE_PATH` default `data/inventory.db` and `MYCELIUM_DATABASE_PATH` default `data/mycelium.db`; separate `pyproject.toml`).
- Only coordinator→INVENTory direction via read-only bridge `mycelium-ai-main/coordinator/app/inventory_read.py`: HTTP GET only, loopback only, no redirects **VERIFIED FROM CODE** (module exists; header/contract) / **VERIFIED FROM TESTS** (`tests/test_inventory_read.py` exists — static only).
- `Mycelium/agent/` is read-only toward user projects; only writes own `discovery.json`/`project_index.json` **VERIFIED FROM CODE** (`agent.py`, `ARCHITECTURE_CONTRACT.md`).

---

## 1. Inventory — 🟢 WORKING / USABLE

| Dimension | Assessment |
|---|---|
| Backend | 🟢 WORKING — full CRUD for 11 entities + relationships + events + FTS + graph |
| Public/API routes | 🟢 WORKING — 61 REST + 71 HTML form routes |
| Frontend/UI | 🟢 usable minimal — inline HTML for all entities, not a SPA |
| Tests | 🟢 exists — 13 files, 183 `def test_*` (static count) |
| Real external integration | ⚪ NOT IMPLEMENTED by design (world-model records only) |
| Current usability | 🟢 usable via API + browser forms on `:8080` |

- Relevant files **VERIFIED FROM CODE**: `inventory/app/main.py` (~3664L), `app/database.py` (561L), `app/schemas.py` (512L), `app/ids.py` (73L), `app/__init__.py` (2L). No `static/`, `templates/`, `*.html/*.tsx` **VERIFIED FROM CODE** (glob).
- Important API routes **VERIFIED FROM CODE**: `GET /api/v1/health`; per entity `GET/POST /api/v1/{objects,projects,ideas,hardware,sensors,cameras,locations,models,tasks,actuators,files}`, `GET/PATCH/DELETE /api/v1/{entity}/{id}`; `GET/POST/DELETE /api/v1/relationships`; `GET /api/v1/events(?entity_id,?limit=100,?since)`; `GET /api/v1/search(?q,?type)`; `GET /api/v1/graph(?entity_id,?depth=1)`; HTML `GET / (=objects index)`, `GET /{projects,ideas,hardware,sensors,cameras,locations,models,tasks,actuators,files}`, `GET /{entity}/{id}`, `GET /{entity}/{id}/edit`, `POST /web/{entity}`, `POST /web/{entity}/{id}/edit|/delete`, `POST /web/relationships`, `GET /search`, `GET /graph/{entity_id}`.
- Important classes/functions **VERIFIED FROM CODE**: `database_path()`, `connection()` (`PRAGMA busy_timeout=15000`), `init_database()` (`PRAGMA journal_mode=WAL`, 12 canonical tables + `_init_fts()` + `rebuild_fts()`), `sanitize_fts_query()`, `search_fts()` (`SEARCHABLE_TYPES` 12 entries, `SEARCH_MAX_RESULTS=50`, `SEARCH_MAX_QUERY_LENGTH=200`), `dump()/load()`; `Provenance` validator (`ai-generated` without `verified_by` forces `human_verified=False`); `XxxCreate/XxxUpdate/XxxResponse` triples; ID generators `obj_,proj_,idea_,rel_,evt_,hw_,sns_,cam_,loc_,mod_,task_,act_,file_`; `_append_event()` on every mutation; `_page()/_nav()/web_*_index/detail/edit_form/create/update/delete`.
- Existing tests **VERIFIED FROM TESTS** (static, not executed): `test_database.py` (2), `test_objects.py` (7), `test_milestone_1b.py` (26), `test_milestone_3_1..3_8.py` (13+13+13+14+14+14+15+19), `test_milestone_4.py` (30), `test_search_types_ui.py` (3). Total 183. `inventory/README.md` claim "35 tests, M3/M4 future" is **DOCUMENTATION CLAIM** and stale.
- What can actually be used today: full CRUD with prefixed IDs + validation + provenance defaults; relationships with predicate allowlist; append-only event log + `?since` cursor; FTS5 search with type filter; 1–2-hop graph with cycle termination; form UI for all entities + search/graph pages at `http://127.0.0.1:8080` **VERIFIED FROM CODE**.
- Missing UI: no SPA, no auth, no pagination beyond `limit=100`/50-result cap, no bulk import UI **VERIFIED FROM CODE**.
- Missing integrations: none required — M3+ entities are world-model records only: "no readout, no capture, no inference, no execution, no GPIO/network" **VERIFIED FROM CODE** (comments + `AGENTS.md`).
- Known risks: no auth on `:8080` **VERIFIED FROM CODE**; `INVENTORY_DATABASE_PATH` defaults to `data/inventory.db` (must use tmp path for experiments) **VERIFIED FROM CODE**; some tests set `os.environ` directly (leak risk) **DOCUMENTATION CLAIM** (`AGENTS.md`).
- Exact next implementation step: add a `/health`-style readiness line + auth-or-bind notice in `_nav()`; no backend change needed.

## 2. Projects / Ideas — 🟢 WORKING / USABLE

Same backend/UI/tests as Inventory (subset). Statuses `ProjectStatus: idea/planned/active/paused/completed/archived`, `IdeaStatus: raw/considered/planned/rejected/converted` **VERIFIED FROM CODE** (`app/schemas.py`). Relationships link any entity; hierarchy via relationships, no GIS/3D **VERIFIED FROM CODE**. `test_milestone_1b.py` covers CRUD + event stream + provenance **VERIFIED FROM TESTS**. Usable today via REST + `/projects`, `/ideas` pages. Missing: no Kanban/board view, no bulk convert idea→project button (must do via API/relationships). Risk: stale `inventory/README.md` says only M1B exists — ignore, M3+ exists **DOCUMENTATION CLAIM vs VERIFIED FROM CODE**. Next step: UI-only "Convert idea" link posting to existing `POST /api/v1/projects` + relationship.

## 3. World / Game — 🟠 PARTIAL / STUB / UNCERTAIN

| Backend | 🟠 derived read-only views, no second truth |
| Routes | 🟡 exists but read-only |
| UI | 🟡 server pages exist, no game canvas |
| Tests | 🟡 exists (static) |
| Integration | ⚪ none (by design) |
| Usability | 🟠 browse-only |

- Relevant files **VERIFIED FROM CODE**: `mycelium-ai-main/coordinator/app/world.py`, `worldgraph.py`, `game.py`, `quests.py`, `campaigns.py`, `connections.py`, `ecosystem.py`, `living_state.py`, `symbiosis.py`, `craft.py`, `familiars.py`. All headers describe derived views **VERIFIED FROM CODE**.
- Important API routes **VERIFIED FROM CODE** (from route sweep): `GET /api/v1/world/search`, `GET /api/v1/world/entity/{type}/{id}`, `GET /api/v1/world/graph`, `GET /game/state`, `POST/GET/DELETE /quests*`, `POST/GET/DELETE /campaigns*`, `POST/GET /connections*`, HTML `GET /world`, `/game`, `/play`, `/quests`, `/campaigns`, `/connections`, `/symbiosis`, `/craft`.
- Important classes/functions **VERIFIED FROM CODE** (headers): world = bridge shaping over INVENTory + local stores; game/quests/campaigns = state machines over existing stores, no execution.
- Existing tests **VERIFIED FROM TESTS** (static): `test_big43_game.py`, `test_big44_world.py`, `test_digital_world.py`, `test_big33_living_world.py`, `test_big30_living_ecosystem.py`, `test_big42_ecosystem.py`.
- Usable today: browse world search/entity/graph pages, view game state/quests/campaigns lists **VERIFIED FROM CODE** (routes + `ui.py` pages).
- Missing UI: no Terraria/Ori-like canvas, no tile map, no sprite layer — pages are lists/forms **VERIFIED FROM CODE**.
- Missing integrations: no game engine, no WebSocket multiplayer, SSE only at `/events/stream` **VERIFIED FROM CODE**.
- Known risks: docs (`ROADMAP.md` PHASE A–S, `vision-architecture.md`) imply a living world; code is read-only shaping — gap **DOCUMENTATION CLAIM vs VERIFIED FROM CODE**.
- Exact next step: UI-only world-tiles list rendering existing `/api/v1/world/search` + `/graph` results; no new backend.

## 4. Missions — 🟡 BACKEND EXISTS, UI OR INTEGRATION MISSING

- Relevant files **VERIFIED FROM CODE**: `coordinator/app/missions.py`, `mission_loop.py`, `mission_executor.py`, `mission_templates.py`, `plans.py`.
- Important API routes **VERIFIED FROM CODE**: `POST/GET /missions*` incl. `approve|pause|resume|cancel|dispatch|tick|run|decide|recover|suggest|from-template`, `GET /mission-templates`, `POST /chat/{id}/missions`, `POST /command`, `POST /plans|/plans/to-proposal`, HTML `GET /missions*`.
- Important classes/functions **VERIFIED FROM CODE** (headers): server-owned goal + bounded steps; autonomy only inside approved steps; `tick/run/dispatch/decide/recover`.
- Existing tests **VERIFIED FROM TESTS** (static): `test_missions.py`, `test_mission_loop.py`, `test_mission_dispatch.py`, `test_mission_templates.py`, `test_mission_task_binding.py`, `test_mission_closeout.py`, `test_command.py`.
- Usable today: propose→approve→tick→dispatch flow via API + MPA pages; `from-template` usable **VERIFIED FROM CODE**. Root `README.md` live chain `Chat→context→advies→missie→approval→stap→taak` is **DOCUMENTATION CLAIM** — code paths exist but end-to-end liveness **UNCERTAIN** without running.
- Missing UI: no mission board/timeline view; 484-route nav buries missions **VERIFIED FROM CODE**.
- Missing integrations: no external executor — tasks route to nodes only **VERIFIED FROM CODE**.
- Known risks: 20,143L `main.py` hard to navigate **VERIFIED FROM CODE**; safety ceremony (exact YES) slows casual use **VERIFIED FROM CODE** (`approval.py`, `voice_approval.py`).
- Exact next step: UI-only mission detail page linking existing `tick/decide/recover` posts + approval fingerprint display.

## 5. Research — 🟡 BACKEND EXISTS, UI OR INTEGRATION MISSING

- Relevant files **VERIFIED FROM CODE**: `coordinator/app/research.py`, `research_engine.py`, `research_plan.py`, `research_extract.py`, `research_transport.py`.
- Important API routes **VERIFIED FROM CODE**: `GET /research/capability`, `POST/GET /research/sources|/records|/runs|/runs/{id}/execute|/dossiers*`, `POST /research/{id}/plan`, `POST/GET /research/queue*`, HTML `GET /research*`.
- Important classes/functions **VERIFIED FROM CODE** (headers): pipeline `SOURCE→FETCH→EXTRACT→NORMALIZE→UNDERSTAND→DEDUPE→RELATE→PROPOSE→APPROVE→STORE`; question→dossier, read-only until approval.
- Existing tests **VERIFIED FROM TESTS** (static): `test_research_api.py`, `test_research_engine.py`, `test_research_extract.py`, `test_research_plan.py`, `test_research_transport.py`, `test_research_security.py`, `test_research_perf.py`, `test_research_skills.py`, `test_research_workspace.py`.
- Usable today: create source/record/run/dossier via API + pages; `AUTOPILOT_ROADMAP` P0 "Research→Mission E2E" still listed as todo **DOCUMENTATION CLAIM** — so E2E **UNCERTAIN**.
- Missing UI: no dossier rich view, no queue operator view beyond forms **VERIFIED FROM CODE**.
- Missing integrations: fetch is loopback-fenced; no cloud search by default **VERIFIED FROM CODE** (transport header).
- Known risks: docs escalate test counts (515→1380) **DOCUMENTATION CLAIM** — static file count is 141 test files, per-test execution not done here.
- Exact next step: UI-only dossier page joining existing `runs/{id}/execute` + `dossiers` GETs.

## 6. Agents / Nodes — 🟡 BACKEND EXISTS, UI OR INTEGRATION MISSING

- Relevant files **VERIFIED FROM CODE**: `coordinator/app/nodes.py`, `nodemesh.py`, `linux_node.py`, `sim_nodes.py`, `capability_matching.py`, `executor_registry.py`, `routing.py`, `model_router.py`; `node_client/main.py` (975L), `bootstrap.py`, `install.py`, `remote_mouse.py`, `mycelium-node.service`; `desktop_agent/main.py` (105L), `agent.py`, `identity.py`; `code_worker/main.py` (573L); `scout/main.py` (305L).
- Important API routes **VERIFIED FROM CODE**: `POST /api/v1/nodes/register`, `POST /nodes/{id}/heartbeat|rotate-token|disable|enable`, `GET /nodes`, `POST /tasks|/tasks/route|/tasks/{id}/assign|/tasks/claim/{node}|/tasks/{id}/complete`, `GET /tasks|/tasks/by-id/{id}`, `GET /models/routes`, `GET /events/stream`, `GET /events`, `GET /status|/state`, HTML `GET /agents`, `/nodes`.
- Important classes/functions **VERIFIED FROM CODE** (headers): registry with token-bind-on-first-register; capability/model/executor advertisement; `analysis.ollama` routed to ollama-capable nodes; node staleness 60s, task lease 300s, max 3 attempts **DOCUMENTATION CLAIM** (`AGENTS.md` — not re-verified line-by-line here); `collect_telemetry()` = `psutil`+`socket/platform` read-only; `remote_mouse.py` = outbound poll for `remote-input`; `code_worker` allow-listed calls only, goals never shell; `scout` max 1 queued task/run, cannot approve/execute.
- Existing tests **VERIFIED FROM TESTS** (static): `test_nodes.py`, `test_node_auth.py`, `test_node_client.py`, `test_capability_matching.py`, `test_routing.py`, `test_model_router.py`, `test_executor_registry.py`, `test_dist_queue.py`, `test_dist_security.py`, `test_dist_sim.py`, `test_fencing.py`, `test_failover.py`, `test_failover_race.py`, `test_agent_loop.py`, `test_b10_security.py`.
- Usable today: `uvicorn coordinator.app.main:app --port 8000` + `python -m node_client.main --coordinator http://127.0.0.1:8000 --node-id seed-01 --tier seed --capability system_inventory` **DOCUMENTATION CLAIM** (`AGENTS.md`) matching code flags **VERIFIED FROM CODE** (headers). Re-registered `node_id` upserts — use fresh `--node-id` **DOCUMENTATION CLAIM**.
- Missing UI: node list page exists but no live presence grid, no capability matrix view **VERIFIED FROM CODE**.
- Missing integrations: Linux systemd install only (`install.py`, `.service`); no Windows service; no GPU/Ollama service in `docker-compose.yml` (single `coordinator` service) **VERIFIED FROM CODE**.
- Known risks: `source/` is a Python venv, not source — confusing **VERIFIED FROM CODE**.
- Exact next step: UI-only nodes dashboard joining existing `GET /nodes` + `GET /status` + staleness display.

## 7. Conversations / Chat — 🟡 BACKEND EXISTS, UI OR INTEGRATION MISSING

- Relevant files **VERIFIED FROM CODE**: `coordinator/app/conversations.py`, `routes_conversations.py`, `conversation_bridge.py`, `conversation_intel.py`.
- Important API routes **VERIFIED FROM CODE**: `POST /api/v1/conversations/import`, `POST /chat`, `GET /conversations*`, `POST /chat/{id}/missions`, HTML `GET /chat`, `/conversations*`.
- Important classes/functions **VERIFIED FROM CODE** (headers): chat store (`conv_*`, provenance, capped); import TXT/MD/JSON/HTML; intel = timeline/graph/missed/materialize as OBSERVATION/CANDIDATE only.
- Existing tests **VERIFIED FROM TESTS** (static): `test_conversations.py`, `test_chat_api.py`, `test_big37_conversation_intel.py`.
- Usable today: chat post + import + intel materialize as candidates via API/pages **VERIFIED FROM CODE**.
- Missing UI: no streaming chat, no markdown-rich thread view beyond forms **VERIFIED FROM CODE** (SSE only at `/events/stream`).
- Missing integrations: Ollama advisor is the only model path (`POST {loopback}:11434/api/generate`, loopback-only, 120s max, question 500 chars) **VERIFIED FROM CODE** (`ollama_advisor.py` header); requires local Ollama + `ollama pull <model>` else honest `OllamaUnavailable`/`UNAVAILABLE` **VERIFIED FROM CODE**.
- Known risks: mixed NL/EN strings **VERIFIED FROM CODE**.
- Exact next step: UI-only chat thread page rendering existing conversation GETs + advise link.

## 8. Vision / Cameras — 🟠 PARTIAL / STUB / UNCERTAIN

- Relevant files **VERIFIED FROM CODE**: `coordinator/app/cameras.py`, `camera_ecosystem.py`, `vision_provider.py`, `vision_ingest.py`, `vision_flow.py`.
- Important API routes **VERIFIED FROM CODE**: `POST/GET /cameras*` (`register|detected|{id}|observations|snapshot|availability|ingest`), `GET /observations/recent`, `POST /vision/analyze|/vision/propose`, `POST /streams/start|/{id}/tick|/{id}/stop`, `POST/GET /camera-sessions*`, `POST /observations/{id}/describe|propose-candidates`, `GET /camera-match|/camera-timeline`, `POST /camera-suggest-link`, `GET /camera-inbox`, `POST /cameras/{id}/ingest-file|poll-inbox`, HTML `GET /cameras*`.
- Important classes/functions **VERIFIED FROM CODE** (headers): snapshot-only active mode; webcam/stream/p360 registered-not-opened; no adapter = 409, never fake bytes; `TestCameraAdapter` writes minimal BMP; `detect_local_imaging_devices()` Windows-only names via ctypes; VLM = advice/analysis, never FACT.
- Existing tests **VERIFIED FROM TESTS** (static): `test_cameras.py`, `test_big34_camera_ecosystem.py`, plus 6 `test_vision_*` files (per sweep).
- Usable today: register camera, ingest file, poll inbox, snapshot metadata, propose candidates **VERIFIED FROM CODE**.
- Missing UI: no live video element, no timeline view beyond list **VERIFIED FROM CODE**.
- Missing integrations: no production capture adapter; Insta360 live FUTURE **DOCUMENTATION CLAIM** (roadmap qualifiers).
- Known risks: 409 without injected adapter is by design but confusing in UI **VERIFIED FROM CODE**.
- Exact next step: UI-only inbox gallery rendering existing `ingest-file` + `observations/recent` results.

## 9. 3D / CAD / Workshop — 🟠 PARTIAL / STUB / UNCERTAIN

- Relevant files **VERIFIED FROM CODE**: `coordinator/app/cad.py`, `mesh3d.py`, `meshops.py`, `pipeline3d.py`, `slicer3d.py`, `workshop3d.py`, `forge.py` (read-mostly studio over `cad.*`).
- Important API routes **VERIFIED FROM CODE**: `POST/GET /cad/documents*`, `POST/GET /mesh/validate|preview|delegate|topology`, `GET /fab/mesh/preview`, `POST /fab/transform`, `POST/GET /workshop/models|materials|links|fabjobs*`, HTML `GET /workshop|/workshop/3d|/workshop/graph`, `/3d`, `/forge`.
- Important classes/functions **VERIFIED FROM CODE** (headers): `CadDocument→parts→ops→mesh`; only executing adapter = procedural box/cylinder math; OpenSCAD/FreeCAD/Blender = `UNAVAILABLE`; slicer badge `SIMULATED`.
- Existing tests **VERIFIED FROM TESTS** (static): `test_mesh3d.py`, `test_advanced_3d.py`, `test_big35_workshop.py`, `test_forge*.py` (4 files), `test_pass6_forge_readiness.py`.
- Usable today: procedural CAD save/open/library/propose + mesh validate/preview numbers + tiny inline `<script>` estimate calc **VERIFIED FROM CODE**.
- Missing UI: no real 3D viewport (no Three.js/Babylon), only numeric preview **VERIFIED FROM CODE**.
- Missing integrations: no CAD runtime, no real slicer — `TestSlicer SIMULATED`, never G-code for printers **VERIFIED FROM CODE** (headers + `slicer3d.py` `safe_to_execute` deliberately absent per sweep).
- Known risks: forge Dutch string `"Alleen DESIGN is vrij…"` + `SIMULATED` chips need flag-hiding for usability **VERIFIED FROM CODE** (header quote).
- Exact next step: UI-only mesh-preview table + `SIMULATED` badge legend; no runtime addition.

## 10. Fabrication — 🟠 PARTIAL / STUB / UNCERTAIN

- Relevant files **VERIFIED FROM CODE**: `coordinator/app/fabrication.py`, `fab_flow.py`.
- Important API routes **VERIFIED FROM CODE**: `POST /fab/generate|validate|assess|slice|advanced|prompt-edit|select-printer|plan`, `GET /fab/volume|/fab/mesh/preview`, `GET /fabrication/records`, `POST /writes/{id}/verify-print`, `POST/GET /slicer`, HTML `GET /fabrication`.
- Important classes/functions **VERIFIED FROM CODE** (headers): `IDEA→CAD→MESH→VALIDATE→SLICE→GCODE→PRINT→CAMERA→TELEMETRY→VERIFY`; physical start needs exact-YES + fingerprint + safety + adapter.
- Existing tests **VERIFIED FROM TESTS** (static): `test_fab_api.py`, `test_fab_security.py`.
- Usable today: generate/validate/assess/slice/plan as data + records list **VERIFIED FROM CODE**.
- Missing UI: no fab-job tracker beyond list **VERIFIED FROM CODE**.
- Missing integrations: no real G-code execution path by default **VERIFIED FROM CODE**.
- Known risks: safety ceremony correct but heavy **VERIFIED FROM CODE**.
- Exact next step: UI-only fab-job detail joining existing `fab/*` + `fabrication/records` GETs.

## 11. Bambu printer — 🟠 PARTIAL / STUB / UNCERTAIN (🔴 BROKEN stock install)

- Relevant files **VERIFIED FROM CODE**: `coordinator/app/printer3d.py` (732L per sweep), `tests/test_printer3d.py`, `tests/test_bambu_adapter.py`.
- Important API routes **VERIFIED FROM CODE**: `POST/GET /printers*`, `POST /prints/propose|cancel`, `POST /filament/spools`, `GET /filament/check`.
- Important classes/functions **VERIFIED FROM CODE**: `PrinterAdapter`, `SimulatedPrinterAdapter` (line 261), `BambuPrinterAdapter` (line 320), `import paho.mqtt.client as mqtt` (line 45) — grep-verified for this audit.
- Existing tests **VERIFIED FROM TESTS** (static): `test_printer3d.py`, `test_bambu_adapter.py` exist; execution not run.
- Usable today: simulated propose/cancel + filament records **VERIFIED FROM CODE** (headers). Real MQTT path **UNCERTAIN** without creds/hardware.
- Missing UI: printer status page exists but defaults to SIMULATED **VERIFIED FROM CODE**.
- Missing integrations: `paho-mqtt` not in `pyproject.toml` dependencies **VERIFIED FROM CODE** (read `pyproject.toml`) → stock `pip install .` + import = crash → 🔴 BROKEN for real path until dep added + creds configured. No serial/vendor SDK path **VERIFIED FROM CODE**. Module docstring says "Only Simulated/Unavailable exist" contradicting MQTT class — stale doc **VERIFIED FROM CODE** (sweep).
- Known risks: committing printer creds; physical execution needs double-YES + fingerprint **VERIFIED FROM CODE** (headers).
- Exact next step: add `paho-mqtt` to deps OR lazy-import with honest `UNAVAILABLE` + document creds setup; UI-only printer readiness chip first.

## 12. Automation — 🟡 BACKEND EXISTS, UI OR INTEGRATION MISSING

- Relevant files **VERIFIED FROM CODE**: `coordinator/app/automation.py` (BIG38).
- Important API routes **VERIFIED FROM CODE** (sweep): `POST/GET /jobs*`, `POST /workflows/dispatch|preview`, `GET /watcher/scan`, HTML `GET /automation*`.
- Important classes/functions **VERIFIED FROM CODE** (header): observe→research→propose→wait-YES→act-inside-plan→verify; explicitly no new execution power.
- Existing tests **VERIFIED FROM TESTS** (static): `test_big38_automation.py`.
- Usable today: dispatch/preview + watcher scan via API/pages **VERIFIED FROM CODE**.
- Missing UI: no workflow visual editor, no run timeline **VERIFIED FROM CODE**.
- Missing integrations: n8n workflows are test-only localhost (`workflow-a-schedule-morning-report.json`, `workflow-b-outbox-notify.json`, `N8N_HOST=127.0.0.1:5678`) **VERIFIED FROM CODE** (`n8n/` listing).
- Known risks: docs (`living-automation.md`, `automation-security.md`) promise more than code executes — by design gated **DOCUMENTATION CLAIM**.
- Exact next step: UI-only job run list joining existing `/jobs` + `/watcher/scan` GETs.

## 13. Presence — 🟡 BACKEND EXISTS, UI OR INTEGRATION MISSING

- Relevant files **VERIFIED FROM CODE**: `coordinator/app/presence.py` (BIG40).
- Important API routes **VERIFIED FROM CODE** (sweep): presence under life layers + HTML `GET /presence`.
- Important classes/functions **VERIFIED FROM CODE** (header): derived attention view (approvals/missions/nodes/research/candidates/cameras/craft/automation/fab); only stores SEEN/DEFERRED triage.
- Existing tests **VERIFIED FROM TESTS** (static): `test_big40_presence.py`.
- Usable today: attention triage page via API **VERIFIED FROM CODE**.
- Missing UI: no ambient/presence indicator, no push — page only **VERIFIED FROM CODE**.
- Missing integrations: `WEB_PUSH UNAVAILABLE` **VERIFIED FROM CODE** (header/sweep).
- Known risks: overlaps with `/mobile/dashboard` shaping — confusing **VERIFIED FROM CODE**.
- Exact next step: UI-only presence hub linking existing approval/mission/node/research counts.

## 14. Mobile — 🟠 PARTIAL / STUB / UNCERTAIN

- Relevant files **VERIFIED FROM CODE**: `coordinator/app/mobile.py`, `docs/mobile-node-flow.md`, `docs/mobile-mycelium.md` (existence per sweep).
- Important API routes **VERIFIED FROM CODE**: `GET /mobile`, `GET /api/v1/mobile/dashboard`, `POST /phone/{node}/camera`.
- Important classes/functions **VERIFIED FROM CODE** (header): read-only dashboard shaping; all YES/NO posts to existing `/web/*` gates.
- Existing tests **VERIFIED FROM TESTS** (static): `test_big36_mobile.py`.
- Usable today: responsive server page `/mobile` readable on phone; INPUT→NODE→RESULT flow **VERIFIED FROM CODE**.
- Missing UI: no native app, no PWA manifest/service worker, no offline-first **VERIFIED FROM CODE** (no `manifest`, no JS bundle).
- Missing integrations: `WEB_PUSH UNAVAILABLE` **VERIFIED FROM CODE**.
- Known risks: docs imply mobile node; code is server page + phone-camera trigger only **DOCUMENTATION CLAIM vs VERIFIED FROM CODE**.
- Exact next step: UI-only responsive pass over existing `/mobile` + dashboard shaping; add manifest later (no backend change).

## 15. Voice — 🟠 PARTIAL / STUB / UNCERTAIN

- Relevant files **VERIFIED FROM CODE**: `coordinator/app/voice.py`, `voice_approval.py`.
- Important API routes **VERIFIED FROM CODE**: `POST /voice/transcribe|synthesize|chat|capture/open|capture/close`, `DELETE /voice/audio/{ref}`, `POST /voice/approval-requests`, `POST /voice/approve`, `POST /interface/sessions*`, `POST /interface/chat`.
- Important classes/functions **VERIFIED FROM CODE** (headers): STT/TTS abstractions; local loopback STT when `STT_BACKEND_URL` set else `Unavailable`; `Test*` canned; audio under `mycelium-audio/`, 25 MiB cap, retain 5; voice never authorizes.
- Existing tests **VERIFIED FROM TESTS** (static): `test_voice.py` (implied), `test_voice_approval.py`, `test_interface.py`, `test_interface_api.py`.
- Usable today: contract + test providers + approval-request shaping **VERIFIED FROM CODE**; real use only if `STT_BACKEND_URL`/loopback VLM configured **VERIFIED FROM CODE**.
- Missing UI: no microphone button/waveform, no audio playback beyond refs **VERIFIED FROM CODE**.
- Missing integrations: real STT/TTS engine FUTURE; physical never via voice (by design) **VERIFIED FROM CODE**.
- Known risks: audio retention + approval confusion (voice approve ≠ authorization) **VERIFIED FROM CODE** (header: "voice never authorizes").
- Exact next step: UI-only voice panel calling existing `transcribe/chat` + explicit "voice cannot approve physical" notice.

## 16. Desktop agent — 🟡 BACKEND EXISTS, UI OR INTEGRATION MISSING

- Relevant files **VERIFIED FROM CODE**: `Mycelium/agent/agent.py` (410L v0.2.0), `agent_ui.py` (87L Flask — fully read for this audit), `project_index.py`, `mapping_store.py`, `inventory_bridge.py` (495L dry-run-proposal), `inventory_writer.py` (gated future), `permissions.py`, `checkpoint.py`, `permission_log.jsonl`, `agent.json` (`mycelium-desktop-agent 0.2.0 foundation`), `discovery.json` + `project_index.json` (runtime data), `tests/` 7 files.
- Important API routes **VERIFIED FROM CODE**: `GET /` (renders inline HTML, Dutch dark `#101410`, stats `computer/project-count/git-count`, cards with `types/git/backup/nested/duplicate/remote/last_modified/file_count/recognized_files`), `POST /scan` (re-runs scanner, redirect). Binds `127.0.0.1:8787`, `debug=False`. No auth, no templates, no static JS.
- Important classes/functions **VERIFIED FROM CODE** (headers + UI read): scanner skips `.git/.venv/node_modules/__pycache__/.pytest_cache`, detects `git/python/node/documented`, reads `git remote` from `.git/config` only, cap 5000 files; `stable ID sha1(computer|path)[:16]`; relations `nested_children/same_remote/shared_name/possible_copy`; `request_permission(action,target)` default-DENY exact YES; checkpoint clean-tree + HEAD check + one local empty commit (`-c commit.gpgsign=false --no-verify`), never `push/reset/clean/rm/stash/fetch`; bridge `build_plan/dry_run` only, no HTTP/SQLite.
- Existing tests **VERIFIED FROM TESTS** (static): `test_discovery`, `test_project_index`, `test_permissions`, `test_checkpoint`, `test_mapping_store`, `test_inventory_bridge`, `test_inventory_writer`.
- Usable today: `GET /` project cards with Dutch labels — "🧠 Mycelium Desktop Agent", "Lokale computer-agent • read-only discovery", "💻 Computer", "📁 Projectlocaties", "🟢 Git-projecten", "🔄 Computer opnieuw scannen", "Projecten", "🟢 Git repository" / "⚪ Geen Git", "💾 Mogelijke backup/kopie", "📦 Nested repository", "👯 Dubbele locatie", "Laatste scan:" + `timestamp`/`"nooit"`/`"onbekend"` fallbacks **VERIFIED FROM CODE** (full `agent_ui.py` read).
- Missing UI: `project_index.json` relations/IDs invisible in UI (contract §I.5 gap) **DOCUMENTATION CLAIM** (contract) consistent with `agent_ui.py` reading only `discovery.json` **VERIFIED FROM CODE**.
- Missing integrations: no coordinator link (bridge dry-run only), no `screen/muis/toetsenbord` control in this folder — root `README.md` claim "desktop-agent bedient scherm/muis/toetsenbord pas na expliciete menselijke goedkeuring" is **DOCUMENTATION CLAIM** pointing at `mycelium-ai-main/desktop_agent/` + `remote-input` sessions, not `Mycelium/agent/` **UNCERTAIN** end-to-end without running.
- Known risks: `agent_ui.py.backup`, `__pycache__/`, `.pytest_cache/` noise; no auth on `:8787` **VERIFIED FROM CODE**.
- Exact next step: UI-only `project_index.json` relations rendering in existing `GET /` cards; no scanner change.

## 17. Forge — 🟠 PARTIAL / STUB / UNCERTAIN

- Relevant files **VERIFIED FROM CODE**: `coordinator/app/forge.py`.
- Important API routes **VERIFIED FROM CODE** (sweep): forge under 3D/fab group + HTML `GET /forge`.
- Important classes/functions **VERIFIED FROM CODE** (header): read-mostly 3D studio over `cad.*` procedural facets; save/open/library/propose; slicer badge `SIMULATED`.
- Existing tests **VERIFIED FROM TESTS** (static): `test_forge.py`, `test_forge_library.py`, `test_forge_persistence.py`, `test_forge_slice.py`, `test_pass6_forge_readiness.py`.
- Usable today: Issue→Plan→Code→Test→Diff→Commit controlled flow (allow-listed) + 3D save/open **VERIFIED FROM CODE** (header: "controlled Issue→Plan→Code→Test→Diff→Commit, allow-listed").
- Missing UI: no code diff viewer beyond text, no 3D viewport **VERIFIED FROM CODE**.
- Missing integrations: no CAD runtime, slicer simulated **VERIFIED FROM CODE**.
- Known risks: name collision with generic "forge" expectations (this is not a git forge) **UNCERTAIN** (naming only).
- Exact next step: UI-only forge detail joining existing save/open/library/propose GETs + estimate calc already inline.

## 18. Workspaces — 🟡 BACKEND EXISTS, UI OR INTEGRATION MISSING

- Relevant files **VERIFIED FROM CODE**: `coordinator/app/workspaces.py`.
- Important API routes **VERIFIED FROM CODE**: `GET/POST /workspaces*`, HTML `GET /workspaces*`.
- Important classes/functions **VERIFIED FROM CODE** (header): workspace = `project_ref` col on `conversations`; no new tables.
- Existing tests **VERIFIED FROM TESTS** (static): `test_workspaces.py`, `test_research_workspace.py`.
- Usable today: workspace scoping for conversations via API/pages **VERIFIED FROM CODE**.
- Missing UI: no workspace switcher beyond list, no per-workspace dashboard **VERIFIED FROM CODE**.
- Missing integrations: none required (column-level scoping) **VERIFIED FROM CODE**.
- Known risks: confused with `Mycelium/{workspace,projects}` runtime dirs (not source) **VERIFIED FROM CODE** (`AGENTS.md` warning).
- Exact next step: UI-only workspace switcher linking existing `/workspaces*` + conversation filter.

## 19. Memory / Knowledge — 🟡 BACKEND EXISTS, UI OR INTEGRATION MISSING

- Relevant files **VERIFIED FROM CODE**: `coordinator/app/memory.py`, `knowledge.py`, `semantic_store.py`, `embeddings.py`, `retrieval.py`.
- Important API routes **VERIFIED FROM CODE**: `POST/GET/DELETE /memory*` (`verify|retrieve|consolidate`), `POST/GET /candidates*` (`support|promote|reject|keep`), `POST /conversation-imports*/findings*/candidate`, `POST /observations*/candidate`, `POST /research/dossiers*/candidate`, HTML `GET /memory`, `/knowledge`.
- Important classes/functions **VERIFIED FROM CODE** (headers): 10 memory types; truth tiers `user_fact>verified>observed>external>ai_inference>ai_suggestion`; `OBSERVATION→CANDIDATE→SUPPORTED→PROMOTED`; embeddings via loopback `POST {base}/api/embed` (Ollama), missing model = explicit `ollama pull` hint.
- Existing tests **VERIFIED FROM TESTS** (static): `test_memory.py`, `test_big32_knowledge.py` (plus retention/promotion tests per sweep).
- Usable today: verify/retrieve/consolidate + candidate promotion chain via API/pages **VERIFIED FROM CODE**.
- Missing UI: no knowledge graph view beyond `/graph` lists, no timeline **VERIFIED FROM CODE**.
- Missing integrations: embeddings require local Ollama + pulled model; else hint only **VERIFIED FROM CODE**.
- Known risks: `Mycelium/{memory,backups}` runtime data must not be treated as source **VERIFIED FROM CODE** (`AGENTS.md`).
- Exact next step: UI-only candidate triage queue joining existing `candidates/*` + `memory/retrieve` GETs.

## 20. Other life-layer modules (for completeness, not in required 19)

`health.py`, `nutrition.py`, `garmin.py` (MOCK + 60 rate-limit), `n8n.py` (MOCK|LIVE label), `skills.py`, `robots.py`, `drones.py`, `twin.py`, `finance.py`, `energy.py`, `hardware_links.py`, `diststate.py`, `sync.py`, `failover.py`, `controlled_writes.py`, `inventory_writes.py`, `approval.py`, `verification.py`, `jobs.py`, `reports.py`, `guide.py`, `live.py`, `interface.py` — all CRUD/state-machine/data-record level, no GPIO/serial/flight code **VERIFIED FROM CODE** (headers/sweep). Tests exist per module **VERIFIED FROM TESTS** (static names). All 🟡/🟠 backend-only by design.

---

## A. What is actually usable today

- INVENTory on `:8080`: full CRUD + search + graph + inline form UI for all 11 entities **VERIFIED FROM CODE**.
- Coordinator MPA console on `:8000`: one-command run (`uvicorn coordinator.app.main:app --host 127.0.0.1 --port 8000`), coherent nav (`/` hub → chat/missions/research/memory/cameras/3D/fabrication), honest `REAL/TEST/SIMULATED/UNAVAILABLE` chips, mobile-readable pages **VERIFIED FROM CODE** (`ui.py`, route sweep).
- Desktop scanner UI on `:8787`: `GET /` cards + `POST /scan` with Dutch labels quoted above **VERIFIED FROM CODE** (full file read).
- Loopback chains that exist as code (liveness **UNCERTAIN** without running): Ollama advise/embed, INVENTory GET bridge, node register→heartbeat→claim→complete, mission propose→YES→execute→verify, camera file-inbox ingest, procedural CAD→mesh→validate→slice(SIMULATED) **VERIFIED FROM CODE** (routes + headers).

## B. What is backend-only

Missions tick/recover/dispatch, research dossier pipeline, memory promotion tiers, workspaces scoping, presence triage, automation dispatch/preview, fab/validate/plan, voice contract/test providers, mobile dashboard shaping, robots/drones/hardware-links/finance/energy records, quests/campaigns/connections state — all have API + tests **VERIFIED FROM TESTS** (static) but only form-list UI, no purpose-built views **VERIFIED FROM CODE**.

## C. What is broken / uncertain

- 🔴 Stock-install broken: `printer3d.py:45 import paho.mqtt.client as mqtt` **VERIFIED FROM CODE** (grep) but `paho-mqtt` absent from `pyproject.toml` dependencies **VERIFIED FROM CODE** (file read) → real-printer import fails unless manually installed. Simulated path unaffected.
- 🟠 Stale docs: `inventory/README.md` (M1B-only/35 tests), `mycelium-ai-main/README.md` + `ROADMAP.md`/`ROADMAP-V2.md` + `AUTOPILOT_ROADMAP.md.txt` escalating DONE/test counts (822/178+1/515→1380) are **DOCUMENTATION CLAIM**; static counts here are 13/183 (inventory) and 141 test files (coordinator). No execution done per instruction, so pass/fail **UNCERTAIN**.
- 🟠 `main.py` 20,143L single-file app, 484 decorators, mixed NL/EN, 55 pages — navigability/operator overload **VERIFIED FROM CODE** (size + sweep).
- 🟠 `source/` is a venv, not source; `docker-compose.yml` single-service (no Ollama/printer/camera); `.env.example` loopback-only **VERIFIED FROM CODE**.
- 🟠 Live camera capture/stream/360, real STT/TTS/VLM, Garmin/Instagram live, CAD runtimes, robot/drone execution, WEB_PUSH — all `UNAVAILABLE`/`MOCK`/`SIMULATED`/`FUTURE` by design **VERIFIED FROM CODE** (headers).
- 🟠 Root `README.md` live chain + "desktop-agent bedient scherm/muis/toetsenbord" + `ARCHITECTURE_CONTRACT.md` milestones — **DOCUMENTATION CLAIM**, end-to-end liveness **UNCERTAIN** without running.

## D. Smallest vertical slice to a genuinely usable application (no architecture change)

1. Start INVENTory `:8080` + coordinator `:8000` (existing commands).
2. Coordinator `/world/search` (existing, loopback bridge) → verify INVENTory link.
3. `/chat` post + `POST /api/v1/advise` (existing, Ollama loopback; needs `OLLAMA_BASE_URL=http://127.0.0.1:11434`, `OLLAMA_MODEL=qwen3.5:4b` from `.env.example`).
4. One mission `from-template` (existing) → approval exact-YES (existing) → one `system_inventory` node task via `node_client` with fresh `--node-id` (existing).
5. Poll `GET /events/stream` + `GET /status` (existing) → observe completion.
6. UI-only addition: readiness line on `/` showing Ollama/printer/camera actual state using existing health/status routes (no backend change).
This slice uses only existing routes + one UI line; it proves Chat→advise→mission→approval→node→observe without touching hardware.

## E. Dependency-ordered roadmap toward the Terraria/Ori-like Mycelium interface (UI-first, no backend redesign)

1. Split `coordinator/app/main.py` for navigability + fix `paho-mqtt` lazy import + add readiness endpoint display (unblocks all below; code health only).
2. Hide `SIMULATED/UNAVAILABLE` actions behind a flag + declutter nav to Chat/Missions/World/Memory first (usability; uses existing `ui.py` chips).
3. PWA shell over existing `POST /web/*` MPA (Chat/Missions/World first; `/mobile` responsive page as base; add manifest + cached GETs only).
4. World-tiles view rendering existing `world/search` + `graph` results (read-only tiles; no engine).
5. Camera-inbox thumbnails on tiles (existing `ingest-file` + `observations/recent`; still no live stream).
6. Forge mesh-preview tiles (existing numeric preview; still no Three.js until later).
7. Voice/mobile as input-only (existing `transcribe/chat` + `mobile/dashboard`; voice never authorizes physical).
8. Printer/fab physical last (existing double-YES + fingerprint + adapter; add dep + creds docs only when hardware present).
Each step depends on the previous only for UI coherence, never for new execution power — fail-closed provenance preserved.
