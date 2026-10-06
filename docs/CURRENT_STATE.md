# CURRENT_STATE — Mycelium AI + INVENTory (actueel)

Stand: 2026-10-05. Bron: code + tests (code is truth).
Vervangt geen `AGENTS.md` of `PROJECTATLAS.md`; dit is de korte
iteratie-kaart voor dagelijks werk. `/side` is frozen (geen wijzigingen
zonder expliciete opdracht).

## 1. Backend services (3 runtimegebieden, geen gedeelde code/DB)

| Gebied | Locatie | Run | Poort | Status |
|---|---|---|---|---|
| INVENTory wereldmodel-store | `inventory/app/` (`main.py` ~3700 regels, 4 modules) | `cd inventory; python -m uvicorn app.main:app --host 127.0.0.1 --port 8080` | 8080 | Werkend, FastAPI + SQLite WAL |
| Mycelium coordinator | `mycelium-ai-main/coordinator/app/` (`main.py` ~24200 regels, 126 modules) | `cd mycelium-ai-main; python -m uvicorn coordinator.app.main:app --host 127.0.0.1 --port 8000` | 8000 | Werkend, 530 routes |
| node_client worker | `mycelium-ai-main/node_client/` | `python -m node_client.main --coordinator http://127.0.0.1:8000 --node-id seed-01 --tier seed --capability system_inventory --poll-seconds 5` | — (pull-only naar :8000) | Werkend |
| code_worker | `mycelium-ai-main/code_worker/main.py` | via coordinator `code.*`-taken, lokale `opencode`-binary | — | Werkend (BIG47/48 bewezen) |
| scout | `mycelium-ai-main/scout/` | via coordinator, max 1 taak | — | Bestaat, begrensd |
| desktop_agent + agent | `mycelium-ai-main/desktop_agent/` + `Mycelium/agent/agent.py` (Flask-UI `:8787`) | `pytest -v` vanuit `Mycelium/agent/` | 8787 | Werkend, read-only |

Regel: coordinator → INVENTory alleen via HTTP loopback
(`inventory_read.py` GET-only, `inventory_writes.py` gated
voorstel → exact-`YES` → execute → verify). Nooit cross-imports,
nooit gedeelde DB.

## 2. Frontend / UI routes (server-rendered, geen bundler)

- Coordinator (`:8000`, ~55 HTML-pagina's in `main.py` via `ui.py` shell):
  `/`, `/chat`, `/missions`, `/research`, `/knowledge`, `/nodes`,
  `/tasks`, `/approvals`, `/automation`, `/game`, `/campaigns`,
  `/quests`, `/world`, `/canvas`, `/workshop/graph`, `/mobile`,
   `/play` (top-down runtime), `/side` (side-view, **FROZEN**),
   `/solarpunk` (Solar Punk City fase 2: first-person raycaster +
   bird's-eye minimap, positie via bestaande play-sessie),
   `/homebase` (SP Home Base 3D: procedureel hoekpand naar foto,
   Three.js gepinde CDN, render-only; zelfde pand embedded op
   `/solarpunk`),
   `/forge`, `/3d`, `/conversations`, `/system`.
   Canvas2D/SVG inline; `fetch` alleen op `/canvas` search,
   `/play` dialogs, `/side` game loop, `/solarpunk` movement/scan loops
   + town chat, `/homebase` Three.js scene, `/forge` preview.
- INVENTory (`:8080`, 132 routes in `app/main.py`):
  `/`, `/objects/{id}`, `/projects`, `/projects/{id}`,
  `/ideas`, `/ideas/{id}`, `/docs` (OpenAPI).
- Agent (`:8787`, `Mycelium/agent/agent_ui.py`): lokale scan-UI.

## 3. Databases (SQLite WAL, tmp-discipline bij experimenten)

| DB | Env-var | Default | Opmerking |
|---|---|---|---|
| INVENTory | `INVENTORY_DATABASE_PATH` | `inventory/data/inventory.db` (gitignored) | `busy_timeout=15000` load-bearing; `*_fts` = afgeleide index (`rebuild_fts()`), nooit direct schrijven |
| Coordinator | `MYCELIUM_DATABASE_PATH` | `mycelium-ai-main/data/mycelium.db` | additieve idempotente migraties (`_ensure_*_columns`) |
| Chat | `MYCELIUM_CHAT_DATABASE_PATH` | `mycelium-ai-main/data/chat.db` | apart van hoofd-DB |
| Agent | — (JSON) | `Mycelium/agent/{discovery.json,project_index.json}` | data, geen source; bridge dry-run only |

Strays (nooit openen): root `data/mycelium*.db`,
`data/inventory.db`, `mycelium-ai-main/data/inventory.db`.
Let op: quests/campaigns/research-runs/dossiers/queue/workspaces/
candidates/automation-runs hebben routes+logica+tests maar deels
**geen `CREATE TABLE`** — geen restart-duurzaamheid aannemen.

## 4. API's (canoniek)

- INVENTory (`:8080`, prefix-IDs `obj_/proj_/idea_/rel_/evt_/hw_/sns_/cam_/loc_/mod_/task_/act_/file_`):
  CRUD objects/projects/ideas, relationships (geen PATCH/single-GET
  by design), read-only `GET /api/v1/events?entity_id&limit&since`,
  search (`sanitize_fts_query()`, alleen `SEARCHABLE_TYPES`),
  graph. Elke mutatie appendt een event (`_append_event()`).
  `mod_` = AI-model (géén 3D-model; 3D = `mdl_` in coordinator,
  `files/file_` met `file_kind=cad|mesh|gcode` is het 3D-register).
- Coordinator (`:8000`, 530 routes): missions
  (`POST /api/v1/missions`, `/approve` exact-YES, `/tick`, `/dispatch`),
  queue-taken (`POST /api/v1/tasks`, `/claim`, `/complete`;
  lease 300s, 3 attempts, staleness 60s), research queue/run-once/
  dossiers/plan, candidates (`/support`, `/promote`), controlled
  writes (`/api/v1/writes/*`), nodes/routing, vision, fab/prints,
  project-package, context-packets, automation-runs, game-state
  (`GET /api/v1/play/journal`, `play/session`, `play/position`).
- Agent: geen API richting coordinator (bewust niet verbonden).

## 5. Tests (pytest, per project; telling 2026-10-05 via `def test_`)

| Project | Files | Tests | Run |
|---|---|---|---|
| `inventory/` | 13 | 183 | `cd inventory; pytest -v` |
| `mycelium-ai-main/` | 165 | 1860 | `cd mycelium-ai-main; pytest -v` |
| `Mycelium/agent/` | 7 | 100 | `cd Mycelium/agent; pytest -v` |

Teststrategie: zie `docs/TESTING.md` (FAST / FEATURE / FULL).
Quirks: inventory-tests zetten `INVENTORY_DATABASE_PATH` direct
(lekkage tussen tests); coordinator-tests bouwen `TestClient(app)`
met lifespan (zet `MYCELIUM_DATABASE_PATH` + chat-path op tmp vóór
constructie). Enkele tests skippen op non-Windows of eisen `git`.
Hardware is fail-closed en gemockt in unit tests
(`paho-mqtt` afwezig → `PrinterUnavailable`; geen capture-adapter →
file-inbox + `UNAVAILABLE`; Ollama `:11434`/Hermes `:8642` down →
502/503). Echte printer/camera-tests nooit in normale runs.

## 6. Scripts / tools (niet als suite draaien)

- `mycelium-ai-main/scripts/` (31 files, waarvan 29 `b*`): `b*_smoke.py`, `b*_shots.py`,
  `b*_screenshots.py` zijn eenmalige handmatige harnesses, vervangen
  door `tests/test_big*.py` + `test_smoke11_15.py`. Niet toevoegen.
- `mycelium-ai-main/n8n/`: localhost test-fixtures only.
- `then/`, `source/`: committed venvs (`pyvenv.cfg`), géén source.
- Nieuw: `tools/test-fast.ps1`, `tools/test-feature.ps1`,
  `tools/test-full.ps1` (dunne pytest-wrappers, zie `docs/TESTING.md`).

## 7. Docs / README's (vertrouwensvolgorde)

`AGENTS.md` > `PROJECTATLAS.md` > `MYCELIUM_REALITY_MAP.md` /
`MYCELIUM_UI_GAP_MAP.md` > code + tests >
`AI_HANDOFF/PROJECT_STATE.md` (labjournaal) >
roadmaps/READMEs (snapshots, deels achterhaald).
`mycelium-ai-main/docs/` = 94 md-files (architectuur + BIG31–45
rapporten als archief). `inventory/README.md` en root `README.md`
zijn minimaal bijgewerkt (counts + commando's); grote rewrite
bewust niet gedaan.

## 8. 3D / workshop

Coordinator `coordinator/app/` `cad.py`, `fabrication.py`,
`fab_flow.py`, `workshop*.py`, `forge*`, routes `/api/v1/fab/*`,
`/api/v1/prints/*`, `/3d`, `/forge`. Keten: object → test-mesh →
validatie → File → test-slice → G-code-safety → File → fysieke
YES → gesimuleerde uitvoering → telemetrie + camera-verificatie.
Slicer gesimuleerd, geen echte printertransporten, geen
`safe_to_execute` nergens. Register: `files/file_`
(`cad|mesh|gcode`), coordinator-IDs `mdl_`.
Externe bibliotheekmodellen: operator downloadt handmatig naar de
bibliotheekmap (geen auto-download, geen credentials), scant via
`scan_library()` en legt herkomst + licentie vast met
`attach_library_license()` (`workshop3d.ModelLicense`: source_library,
source_url, author, license, commercial_use, remix_allowed,
attribution_required, original_model_url, imported_at). Vage namen
("open source", "free") en licentieloze externe herkomst worden
geweigerd; onbekende licenties houden alle flags op onbekend
(nooit aannemen). `library_file_fields()` propageert het blok naar
`file_`-metadata + description; INVENTory-schema ongewijzigd.
Importketen (operator-expliciet): `coordinator/app/library_sources.py`
(catalogus + Commons-zoekopdracht + `gate_import()` + begrensde
download) → `mdl_`-record → `file_`-voorstel via bestaande
`propose_inventory_write()` + YES-gate (`/writes`).
Routes: `GET /api/v1/workshop/libraries`, `POST .../libraries/search`,
`POST .../libraries/import`, `POST /web/workshop/libraries/import`;
`/3d` heeft een **Modelbibliotheken**-sectie (bronkaarten, zoeken,
licentie-chips JA/NEE/ONBEKEND, Importvoorstel-knop).
Geschikte bronnen zonder API-key: Wikimedia Commons API
(extmetadata-licenties), NIH 3D (licentie per entry lezen),
NASA 3D Resources/GitHub-mirror (zonder copyright). Details:
`mycelium-ai-main/docs/3d-model-libraries.md`.

## 9. Camera / vision

`cameras.py`, `camera_ecosystem.py`, `capture_probe.py`,
`world_observations.py` (`wobs_`), `observations.py` (screen),
vision-routes `/api/v1/cameras/*/ingest`, `/api/v1/vision/*`.
Reviewde capture-runtime: `insta360`-grabber (`capture_probe.py`,
ffmpeg-dshow single frame, argv-only, parent verifieert SHA256;
device `source=insta360` via bestaande register-route, geen adapter
nodig). Room-scan via `/solarpunk`-paneel (UI-loop over bestaande
probe-grab, max 30 frames, geen threads). VLM-fallback eerlijk,
observatie ≠ feit. Uitzondering: Bambu-kameracamera via
`coordinator/app/bambu_camera.py` (TLS TCP :6000, 80-byte auth met
bestaande LAN-credential, één frame per aanroep, read-only,
live bewezen tegen A1 Mini). Drie complementaire modellen (camera-,
wereld-, schermobservaties) bewust niet unificeren.

## 10. INVENTory (samenvatting)

11 entiteiten + relaties + events + FTS + graaf; M3+
(hardware/sensors/cameras/locations/models/tasks/actuators/files)
zijn wereldmodel-records only (geen hardwaretoegang/inferentie/
executie). Provenance-regel (`app/schemas.py`): `ai-generated`
zonder `verified_by` forceert `human_verified=False`.

## 11. Mycelium coordinator (samenvatting)

Missies (uitvoerbaar) vs Plan (inert) vs AutomationRun vs
research-run (`res_`) vs queue-`tasks` (int, queued/assigned) vs
`ctask-` (goedgekeurd voorstel, nooit queued) vs inventory-`task_`
(wereldrecord, executeert nooit) — bewust gescheiden tabellen,
niet unificeren. Geen background threads/scheduler/auto-approval
(`jobs.py:12`); watcher/overnight/sweep alleen via expliciete POST
of externe cron. Ontbrekende providers degraderen eerlijk.
Town (Solar Punk City): `town_chat.py` (gesprekken op bestaande
chat-tabellen, town-rol in sources, round-robin of targeted
`npc_id`, max 1 NPC-beurt) + `town_memory.py` (tabel
`town_memories`, recall belang+recency, reflect 409 zonder
model) + `ollama_chat.py` (lokale fallback: Hermes → Ollama
→ eerlijke noot; model via `OLLAMA_CHAT_MODEL`, default
phi4-mini) + `town_actors.py` (NPC-aanwezigheid: tabellen
`town_actors`/`town_activity`; status verandert alleen op
echte signalen — queue-taken aan `town:{npc}` gebonden,
anders idle; walk-up chat binnen 100 eenheden) +
`town_proposals.py` (delegatie: voorstel met actie/
rechtvaardiging/blast-radius/confidence, exact-YES →
queue-taak met provenance `town:{npc}`; dial via
`TOWN_AUTONOMY`, default leeg, hardware/desktop nooit).
Residents-, activiteiten- en Bureaupaneel op `/solarpunk`.
Kijkrichting `a` persisteert mee (additieve `angle`-kolom op
play_sessions; callers zonder `a` laten hem staan). Forge heeft
een 3D-snapshot-preview-toggle (zelfde pinned three@0.160.0 +
fallback; 2D-editor blijft leidend) en BUILD-queuet mee
(prepare/slice/propose/preflight/enqueue als fetch-knoppen;
server blijft gaten). Insta360-frames 1-klik zichtbaar via
`GET /api/v1/cameras/observations/{id}/image`
(allow-listed read; "Bekijk beeld" in het scan-paneel).
Remote muis/toetsenbord loopt via `/nodes` (Digital-World-pad,
expliciete YES-sessie); vensters zijn titels-only, er is geen
file-transfer — dat is backend-werk, geen UI-werk.

## 12. Logische werkstructuur (grenzen, geen verhuizing)

- **CORE**: `inventory/app/` (wereldmodel+DB), `mycelium-ai-main/
  coordinator/app/database.py` + `coordinator/app/main.py` +
  queue/missions/research/knowledge/automation, DB's onder §3,
  API's onder §4.
- **UI**: coordinator HTML-routes + `/3d`+`/forge` (workshop),
  `/world`+`/canvas`+`/workshop/graph` (views), camera-views,
  `Mycelium/agent/agent_ui.py`; game-views (`/side` frozen,
  `/play`, `/world`, `/canvas`, `/forge`) zijn projecties.
- **HARDWARE**: Bambu (`bambu_exec.py`, MQTT `:8883` read-only),
  Insta360 (file-inbox), Garmin (docs/v2-ecosystem, geen live),
  robots/drones (docs only). Altijd fail-closed, expliciet,
  apart van unit tests.
- **INTEGRATIONS**: model-libraries/Ollama (`:11434`), web/imports
  (`research.fetch_url`, conversation-bridge `conv_`), externe
  services (n8n-fixtures, web-push unavailable). Cloud additief,
  nooit verplicht.
