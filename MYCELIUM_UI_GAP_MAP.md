# MYCELIUM UI GAP MAP — backend capability → user-facing UI

Date (UTC): 2026-09-25
> **Historical snapshot.** This map records UI gaps found on 2026-09-25 and is not the current implementation status. The product and repository have changed since then. For current architecture and live checks, use `AGENTS.md`, `PROJECTATLAS.md`, `docs/CURRENT_STATE.md`, and `Mycelium-Knowledge-Vault/What works today.md`; verify each capability against executable code and tests. Detailed rows below are preserved as dated audit notes.
Companion to `MYCELIUM_REALITY_MAP.md` (primary factual audit). Same method: static inspection only, no test execution, no code changes, no commits.
Language: English. Dutch UI labels/quotes preserved verbatim where they exist.
Evidence tags: **VERIFIED FROM CODE** / **VERIFIED FROM TESTS** (static file inspection only) / **DOCUMENTATION CLAIM** / **UNCERTAIN**.
No architecture invented or redesigned. Only records what exists and names the UI gap + exact UI work required (UI-only, reusing existing `POST /web/*` gates + `ui.py` tokens).

## 0. No real frontend anywhere — VERIFIED FROM CODE

- 0 hits for `**/*.tsx,*.jsx,*.vue,*.html`, `**/static`, `**/templates` in source (excluding `.venv/.git`) **VERIFIED FROM CODE** (glob).
- Deps prove it: `inventory/pyproject.toml` = `fastapi,uvicorn[standard],pydantic`; `mycelium-ai-main/pyproject.toml` = `fastapi,uvicorn[standard],httpx,psutil` **VERIFIED FROM CODE** (both files read). No JS framework, no bundler, no `Jinja2`/`StaticFiles`.
- What exists instead **VERIFIED FROM CODE**:
  - INVENTory: ~71 inline-HTML routes (`HTMLResponse`/`RedirectResponse`, f-string `_page()/_nav()`, forms to `POST /web/*`, Dutch labels e.g. `"bijv. 3D-Printer build"`).
  - Coordinator: `coordinator/app/ui.py` (1089L SolarPunk tokens, 3-col shell nav/main/aside + cmdbar, chips `REAL/TEST/SIMULATED/UNAVAILABLE`) + ~55 `HTMLResponse` pages in `main.py` (20,143L, 484 decorators) + tiny inline `<script>` (forge estimate).
  - Desktop scanner: `Mycelium/agent/agent_ui.py` (87L Flask, fully read) — `GET /` + `POST /scan` on `127.0.0.1:8787`, dark `#101410`, Dutch labels (see §16).
- Screenshots `docs/r33-shots|v1-shots` + `scripts/bXX_screenshots.py` show pages render **DOCUMENTATION CLAIM** (not executed here).

## 1. Capability → UI gap matrix

Columns: capability | backend implementation | API/route | existing UI | UI missing | integration missing | current usability | exact UI work required (UI-only).

### Inventory / Projects / Ideas

| Capability | Backend | API/route | Existing UI | UI missing | Integration missing | Usability | Exact UI work required |
|---|---|---|---|---|---|---|---|
| Objects CRUD | `app/database.py` canonical `objects` + `ids.generate_object_id(obj_)` **VERIFIED FROM CODE** | `GET/POST /api/v1/objects`, `GET/PATCH/DELETE /api/v1/objects/{id}` **VERIFIED FROM CODE** | `GET /`, `/objects/{id}`, `/objects/{id}/edit`, `POST /web/objects*` **VERIFIED FROM CODE** | Bulk create, pagination beyond `limit=100` | None (by design) | Usable via forms | Add paged table reusing existing `GET /api/v1/objects` |
| Projects CRUD | `projects` + `ProjectStatus` **VERIFIED FROM CODE** | `/api/v1/projects*` | `GET /projects`, `/projects/{id}`, `/edit`, `POST /web/projects*` | Board/Kanban, status filter UI | None | Usable | Add status-filter chips calling existing `GET /projects` |
| Ideas CRUD + convert | `ideas` + `IdeaStatus` **VERIFIED FROM CODE** | `/api/v1/ideas*` | `GET /ideas*`, `POST /web/ideas*` | "Convert idea→project" button | None | Manual via 2 POSTs | Add convert link posting existing project-create + relationship-create |
| Relationships | `relationships(rel_)`, predicate allowlist, self-ref reject **VERIFIED FROM CODE** | `GET/POST /api/v1/relationships`, `DELETE /{rel_id}` | `POST /web/relationships`, `POST /web/relationships/{id}/delete`, `_render_relationships` | Graph canvas, only `GET /graph/{id}` list | None | Usable as list | Render existing `GET /api/v1/graph` as SVG tiles (read-only) |
| Events/audit | `_append_event()` every mutation **VERIFIED FROM CODE** | `GET /api/v1/events(?entity_id,?limit,?since)` | `_render_events` per detail page | Global timeline view | None | Per-entity only | Add global feed page over existing `GET /api/v1/events?since=` |
| Search + graph | `search_fts()` + `sanitize_fts_query()`, `SEARCHABLE_TYPES` 12, FTS triggers + `rebuild_fts()` **VERIFIED FROM CODE** | `GET /api/v1/search`, `GET /api/v1/graph` | `GET /search`, `GET /graph/{id}` | Type-ahead, highlighting | None | Usable | Add type-filter chips (already in `test_search_types_ui.py` **VERIFIED FROM TESTS**) to nav |
| M3+ records (hw/sns/cam/loc/mod/task/act/file) | 8 canonical tables, allowlists, `normalize_sha256()` **VERIFIED FROM CODE** | `/api/v1/{hardware,sensors,cameras,locations,models,tasks,actuators,files}*` | `GET /{hardware,sensors,cameras,locations,models,tasks,actuators,files}` + detail/edit + `POST /web/*` | Unified browser, no device views (by design) | None required | Usable as registers | Add unified index linking existing 8 list pages |

### World / Game

| Capability | Backend | API/route | Existing UI | UI missing | Integration missing | Usability | Exact UI work required |
|---|---|---|---|---|---|---|---|
| World search/entity/graph | `world.py`, `worldgraph.py` derived views **VERIFIED FROM CODE** | `GET /api/v1/world/search`, `/entity/{type}/{id}`, `/graph` | `GET /world` | Tile map, sprites | Game engine (not present, not required now) | Browse lists | Render search+graph JSON as tile cards (read-only) |
| Game/quests/campaigns | `game.py`, `quests.py`, `campaigns.py` state over stores **VERIFIED FROM CODE** | `GET /game/state`, `/quests*`, `/campaigns*` | `GET /game`, `/play`, `/quests`, `/campaigns` | Canvas, progression visuals | None | Lists only | Add quest detail joining existing GETs + progress bar from existing fields |

### Missions

| Capability | Backend | API/route | Existing UI | UI missing | Integration missing | Usability | Exact UI work required |
|---|---|---|---|---|---|---|---|
| Mission lifecycle | `missions.py`, `mission_loop.py`, `mission_executor.py`, `mission_templates.py` **VERIFIED FROM CODE** | `/missions*` (`approve|pause|resume|cancel|dispatch|tick|run|decide|recover|suggest|from-template`), `/mission-templates`, `/command`, `/plans` | `GET /missions*` | Board/timeline, fingerprint display | External executor (nodes only) | API-usable, UI-buried | Add mission detail page with existing `tick/decide/recover` buttons + approval fingerprint text |

### Research

| Capability | Backend | API/route | Existing UI | UI missing | Integration missing | Usability | Exact UI work required |
|---|---|---|---|---|---|---|---|
| Dossier pipeline | `research*.py` 5 files, `SOURCE→…→STORE` **VERIFIED FROM CODE** | `/research/sources|/records|/runs|/runs/{id}/execute|/dossiers*`, `/research/{id}/plan`, `/research/queue*` | `GET /research*` | Dossier rich view, queue operator view | Cloud search (loopback-fenced) | API-usable | Add dossier page joining existing `runs/{id}/execute` + `dossiers` GETs |

### Agents / Nodes

| Capability | Backend | API/route | Existing UI | UI missing | Integration missing | Usability | Exact UI work required |
|---|---|---|---|---|---|---|---|
| Registry + queue | `nodes.py`, `nodemesh.py`, `routing.py`, `model_router.py`, `capability_matching.py` **VERIFIED FROM CODE**; `node_client/main.py` 975L; staleness 60s/lease 300s/3 attempts **DOCUMENTATION CLAIM** (`AGENTS.md`) | `/nodes/register|/heartbeat|/rotate-token|/disable|/enable`, `/nodes`, `/tasks|/route|/assign|/claim|/complete`, `/models/routes`, `/events/stream`, `/status`, `/state` | `GET /agents`, `/nodes` | Live presence grid, capability matrix | Windows service, GPU/Ollama in compose | CLI-usable (`node_client --node-id seed-01 --tier seed --capability system_inventory` **DOCUMENTATION CLAIM** matching flags **VERIFIED FROM CODE**) | Add nodes table with staleness + capability chips from existing `GET /nodes` + `GET /status` |

### Conversations / Chat

| Capability | Backend | API/route | Existing UI | UI missing | Integration missing | Usability | Exact UI work required |
|---|---|---|---|---|---|---|---|
| Chat + import + intel | `conversations.py`, `routes_conversations.py`, `conversation_bridge.py`, `conversation_intel.py` **VERIFIED FROM CODE**; Ollama `POST {loopback}:11434/api/generate` 120s/500-char cap **VERIFIED FROM CODE** | `POST /chat`, `/conversations/import`, `/chat/{id}/missions`, `GET /conversations*` | `GET /chat`, `/conversations*` | Streaming, markdown thread | Local Ollama + `ollama pull qwen3.5:4b` (`.env.example` **VERIFIED FROM CODE**) | Forms only | Add thread view over existing conversation GETs + advise button calling existing `POST /api/v1/advise` |

### Vision / Cameras

| Capability | Backend | API/route | Existing UI | UI missing | Integration missing | Usability | Exact UI work required |
|---|---|---|---|---|---|---|---|
| Registry + file ingest | `cameras.py`, `camera_ecosystem.py`, `vision_*.py` 3 files; snapshot-only, 409 without adapter, `TestCameraAdapter` BMP **VERIFIED FROM CODE** | `/cameras*` (`register|detected|observations|snapshot|availability|ingest`), `/observations/recent`, `/vision/analyze|/propose`, `/streams/*`, `/camera-sessions*`, `/camera-inbox`, `/ingest-file|poll-inbox` | `GET /cameras*` | Video element, timeline gallery | Production capture adapter; 360 live FUTURE **DOCUMENTATION CLAIM** | File-ingest usable | Add inbox gallery over existing `observations/recent` + `ingest-file` results |

### 3D / CAD / Workshop / Fabrication / Forge / Bambu

| Capability | Backend | API/route | Existing UI | UI missing | Integration missing | Usability | Exact UI work required |
|---|---|---|---|---|---|---|---|
| Procedural CAD + mesh | `cad.py`, `mesh3d.py`, `meshops.py`, `pipeline3d.py`, box/cylinder only; OpenSCAD/FreeCAD/Blender `UNAVAILABLE` **VERIFIED FROM CODE** | `/cad/documents*`, `/mesh/validate|preview|delegate|topology`, `/fab/mesh/preview`, `/fab/transform`, `/workshop/*` | `GET /workshop|/workshop/3d|/graph`, `/3d`, `/forge` + inline estimate `<script>` | 3D viewport (no Three.js) | CAD runtimes | Numbers only | Add preview table + `SIMULATED` legend from existing validate/preview JSON |
| Fab jobs | `fabrication.py`, `fab_flow.py`, `IDEA→…→VERIFY`, exact-YES+fingerprint **VERIFIED FROM CODE** | `/fab/generate|validate|assess|slice|advanced|prompt-edit|select-printer|plan`, `/fab/volume`, `/fabrication/records`, `/writes/{id}/verify-print`, `/slicer` | `GET /fabrication` | Job tracker | Real G-code exec (SIMULATED by design) | Plan-as-data | Add job detail joining existing `fab/*` + `records` GETs |
| Forge studio | `forge.py` read-mostly over `cad.*`, slicer `SIMULATED`, `"Alleen DESIGN is vrij…"` **VERIFIED FROM CODE** | Forge under fab group | `GET /forge` | Diff viewer, viewport | Same as CAD | Save/open/propose usable | Expose existing save/open/library/propose in one detail page |
| Printers + Bambu | `printer3d.py` 732L; `SimulatedPrinterAdapter` L261 + `BambuPrinterAdapter` L320 + `import paho.mqtt.client` L45 **VERIFIED FROM CODE** (grep); `paho-mqtt` NOT in `pyproject.toml` **VERIFIED FROM CODE** (file read) | `/printers*`, `/prints/propose|cancel`, `/filament/spools`, `/filament/check` | Printer status page (SIMULATED default) | Real-status widget | `paho-mqtt` dep + broker creds + serial SDK (absent) | Simulated usable; real path 🔴 stock-broken / 🟠 with creds **UNCERTAIN** | Add readiness chip (`SIMULATED` vs `UNAVAILABLE` vs error) + lazy-import fix (only code-adjacent UI task: display existing adapter label) |

### Automation / Presence

| Capability | Backend | API/route | Existing UI | UI missing | Integration missing | Usability | Exact UI work required |
|---|---|---|---|---|---|---|---|
| Jobs/workflows/watcher | `automation.py` BIG38, no new exec power; n8n JSON localhost-only **VERIFIED FROM CODE** | `/jobs*`, `/workflows/dispatch|preview`, `/watcher/scan` | `GET /automation*` | Visual editor, run timeline | n8n tunnel/cloud | Dispatch/preview usable | Add run list over existing `/jobs` + `/watcher/scan` |
| Attention triage | `presence.py` BIG40, SEEN/DEFERRED only **VERIFIED FROM CODE** | Presence routes + `/presence` | `GET /presence` | Ambient indicator, push (`WEB_PUSH UNAVAILABLE` **VERIFIED FROM CODE**) | Push service | Page only | Add hub linking existing approval/mission/node/research counts |

### Mobile / Voice / Interface

| Capability | Backend | API/route | Existing UI | UI missing | Integration missing | Usability | Exact UI work required |
|---|---|---|---|---|---|---|---|
| Mobile dashboard | `mobile.py` read-only shaping; YES/NO via `/web/*` **VERIFIED FROM CODE** | `GET /mobile`, `/api/v1/mobile/dashboard`, `POST /phone/{node}/camera` | `GET /mobile` (responsive server page, no native app) **VERIFIED FROM CODE** | PWA manifest/SW, offline | `WEB_PUSH UNAVAILABLE` | Readable on phone | Responsive pass + manifest over existing `/mobile` GETs |
| Voice | `voice.py`, `voice_approval.py`; `Unavailable` default, `Test*` canned, `STT_BACKEND_URL` loopback; `mycelium-audio/` 25MiB/retain-5; voice never authorizes **VERIFIED FROM CODE** | `/voice/transcribe|synthesize|chat|capture/open|close`, `/voice/audio/{ref}`, `/voice/approval-requests`, `/voice/approve`, `/interface/sessions*`, `/interface/chat` | None (contract only) | Mic button, waveform, playback | Real STT/TTS engine | Test-provider only | Add voice panel calling existing `transcribe/chat` + "voice cannot approve physical" notice from existing header |

### Desktop agent (`Mycelium/agent/` + `mycelium-ai-main/desktop_agent/`)

| Capability | Backend | API/route | Existing UI | UI missing | Integration missing | Usability | Exact UI work required |
|---|---|---|---|---|---|---|---|
| Discovery + permissions | `agent.py` 410L scan (cap 5000, skips `.git/.venv/node_modules/__pycache__/.pytest_cache`), `project_index.py` (`sha1(computer\|path)[:16]`), `inventory_bridge.py` 495L dry-run only, `permissions.py` default-DENY exact-YES, `checkpoint.py` local commit only **VERIFIED FROM CODE** | `GET /` + `POST /scan` on `127.0.0.1:8787` **VERIFIED FROM CODE** (full 87L read) | Cards with `"🧠 Mycelium Desktop Agent"`, `"Lokale computer-agent • read-only discovery"`, `"💻 Computer"`, `"📁 Projectlocaties"`, `"🟢 Git-projecten"`, `"🔄 Computer opnieuw scannen"`, `"Projecten"`, `"🟢 Git repository"`/`"⚪ Geen Git"`, `"💾 Mogelijke backup/kopie"`, `"📦 Nested repository"`, `"👯 Dubbele locatie"`, `"Laatste scan:"`/`"nooit"`/`"onbekend"` **VERIFIED FROM CODE** | `project_index.json` relations invisible (contract §I.5 **DOCUMENTATION CLAIM**, consistent with UI reading only `discovery.json` **VERIFIED FROM CODE**) | Coordinator link (bridge has no HTTP/SQLite **VERIFIED FROM CODE**); `screen/muis/toetsenbord` claim lives in root `README.md` **DOCUMENTATION CLAIM** → `desktop_agent/` + `remote-input` sessions, liveness **UNCERTAIN** | Discovery usable | Render `project_index.json` relations/IDs in existing cards (UI-only) |
| Outbound executor | `mycelium-ai-main/desktop_agent/*.py`, `coordinator/app/desktop_runtime.py`, `remote_input.py` **VERIFIED FROM CODE** (file presence + headers) | `/desktop/actions*` (8: `decision|cancel|dispatch|result|next`), `/remote-input/sessions*` (8), `/agent/status` | `GET /agent/status` (assumed page; full route content **UNCERTAIN** without line read) | Approval-gated control console | OS input backend per platform | Gate flow exists | Add action queue view over existing `desktop/actions/next` + `result` GETs |

### Workspaces / Memory / Knowledge

| Capability | Backend | API/route | Existing UI | UI missing | Integration missing | Usability | Exact UI work required |
|---|---|---|---|---|---|---|---|
| Workspaces | `workspaces.py`: `project_ref` col on `conversations`, no new tables **VERIFIED FROM CODE** | `GET/POST /workspaces*` | `GET /workspaces*` | Switcher, per-workspace dashboard | None | Scoping usable | Add switcher linking existing workspaces + conversation filter |
| Memory/knowledge | `memory.py`, `knowledge.py`, `semantic_store.py`, `embeddings.py` (loopback `/api/embed`, `ollama pull` hint), `retrieval.py`; tiers `user_fact>verified>observed>external>ai_inference>ai_suggestion`; `OBSERVATION→CANDIDATE→SUPPORTED→PROMOTED` **VERIFIED FROM CODE** | `/memory*` (`verify|retrieve|consolidate`), `/candidates*` (`support|promote|reject|keep`), `…/candidate` x4 | `GET /memory`, `/knowledge` | Graph/timeline views | Ollama embed model | Triage via API | Add candidate queue over existing `candidates/*` + `memory/retrieve` |

## 2. Cross-cutting UI gaps (all VERIFIED FROM CODE unless noted)

1. No nav coherence: 484 routes / ~55 pages overwhelm; Chat/Missions/World/Memory buried. Fix: UI-only nav reorder + hide `SIMULATED` behind flag (uses existing chips).
2. No readiness signal: Ollama/printer/camera state only discoverable via errors (`OllamaUnavailable`, 409, `UNAVAILABLE`). Fix: UI-only readiness line on `/` from existing health/status routes.
3. No streaming/realtime: SSE only at `/events/stream`; chat forms full-post. Fix: UI-only poll of existing stream endpoint (no backend change).
4. No auth messaging: `:8080`/`:8000`/`:8787` loopback-only with no login. Fix: UI banner + bind notice (docs already warn; no auth added here).
5. Language split: NL labels (`"Computer opnieuw scannen"`, `"Projectlocaties"`, `"Geen projecten gevonden."`, `"Alleen DESIGN is vrij…"`) inside EN flows. Fix: preserve quotes, add EN subtitles (UI-only).

## 3. Smallest practical UI-first vertical slice (final section, no backend changes)

Goal: turn existing backend into something genuinely usable in one UI pass.

1. **Readiness header (UI-only, 1 include in `ui.py` + inventory `_nav()`):** show `Ollama: REAL|UNAVAILABLE` (existing `GET /status` + advise error), `Printer: SIMULATED` (existing adapter label), `Camera: N configured` (existing `GET /cameras`), `INVENTory: OK` (existing `GET /api/v1/health` loopback). Reuses only existing GETs.
2. **World-first home (UI-only reorder):** make `/` link Chat → Advise → Mission → Approval → Task → Observe in that order using existing pages (`/chat`, `/missions`, `/world/search`, `/events/stream`). No new routes.
3. **One mission template end-to-end (UI-only wiring):** expose existing `POST /missions/from-template` + `POST /approvals` (exact YES + fingerprint display from existing response) + `GET /tasks/by-id/{id}` + `GET /events` poll on a single mission detail page. Backend already supports it; UI just joins the calls.
4. **Node join card (UI-only text):** copy-paste command from `AGENTS.md` (`node_client --coordinator http://127.0.0.1:8000 --node-id <fresh> --tier seed --capability system_inventory`) **DOCUMENTATION CLAIM** with fresh-ID warning + staleness note from existing `GET /nodes`. No backend change.
5. **Candidate + inbox triage (UI-only lists):** one page embedding existing `GET /candidates`, `GET /camera-inbox`, `GET /observations/recent`, `GET /research/queue` with approve/support links posting to existing `/web/*` gates. Voice/Mobile reuse the same gates (`voice never authorizes` notice preserved).
6. **Desktop discovery link (UI-only):** embed `:8787` cards next to coordinator `/agents` via iframe/link + render `project_index.json` relations in `agent_ui.py` `GET /` (the single biggest discoverability win; still read-only).

Done state: a non-developer can open `/`, see green/red readiness, run chat→mission→approval→node→observe, triage memory/camera/research queues, and browse desktop projects — all through existing APIs. Physical printer/fab, live camera streams, voice auth, and any 3D canvas stay explicitly `SIMULATED/UNAVAILABLE` behind the flag until hardware exists.
