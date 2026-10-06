# AGENTS.md

## Development contract (nieuwe start, leidend voor iteratief werk)

1. **Code is truth.** Bij conflict tussen docs en code/tests wint de uitvoerbare bron. Docs (`docs/CURRENT_STATE.md`, `docs/TESTING.md`) worden bijgewerkt als ze achterlopen; code wordt niet aangepast om bij docs te passen.
2. **Eerst bestaande code lezen.** Voor elke wijziging: relevante module + tests + dit bestand lezen. Niets vervangen wat niet begrepen is.
3. **Kleine wijzigingen boven grote refactors.** Geen blind refactoren, geen grote delen verwijderen.
4. **Geen functionaliteit verwijderen zonder opdracht.** Werkende functionaliteit blijft behouden.
5. **`/side` is momenteel frozen.** Geen `/side`-wijzigingen zonder expliciete opdracht. Lezen/testen mag; editen niet.
6. **Geen tweede database/queue wanneer een bestaande canonical variant bestaat.** Game-views zijn projecties (sessie-positie is het enige game-eigendom); geen nieuwe stores voor missies/taken/kennis/projecten.
7. **Geen credentials in code/docs/tests/logs.** Geen shell/RCE, geen secrets-opslag, geen bypass van exact-YES.
8. **Hardware-acties altijd expliciet en apart van normale tests.** Bambu/Insta360/Garmin: fail-closed, gemockt in pytest; echte hardware nooit in FAST/FEATURE/FULL, alleen handmatig en expliciet.
9. **Tests passend bij wijzigingsscope.** FAST na elke edit (geraakte module + directe dependencies), FEATURE bij feature-grens, FULL alleen expliciet/voor milestone. Zie `docs/TESTING.md` + `tools/test-*.ps1`.
10. **Na iedere wijziging:** (a) wijziging controleren (diff/lezen), (b) relevante snelle tests draaien (FAST), (c) pas daarna eventueel breder (FEATURE, zelden FULL).
11. **Geen commits/pushes zonder expliciete opdracht.**

Werkstructuur (logische grenzen, structuur blijft): CORE (Mycelium/coordinator/INVENTory/databases/API's) · UI (webinterface, 3D-workshop, camera, dashboards) · HARDWARE (Bambu, Insta360, Garmin, overig) · INTEGRATIONS (model-libraries, web/imports, externe services). Details: `docs/CURRENT_STATE.md` §12.

---

Single root git repo (`./.git`; `ahead 11` with untracked BIG46–57 + world/hermes/bambu/canvas tests at last check). `inventory/` has no own `.git` — it is just a subdirectory. Three independent runtime areas, no shared code or DB:

- `inventory/` — world-model store. FastAPI (`app/main.py`) + SQLite WAL on port **8080**.
- `mycelium-ai-main/` — coordinator (`coordinator/app/main.py`, ~24k lines / 530 routes in `main.py`, 126 app-modules, gemeten 2026-10-05) + pull-only worker (`node_client/`) on port **8000**.
- `Mycelium/agent/` — local desktop scanner (filesystem observer, Flask UI on **8787**). Runtime data in `Mycelium/{memory,backups,workspace,projects}` and `agent/{discovery.json,project_index.json,permission_log.jsonl}` is data, not source.

## Commands (run from the project subdir, not root)

Both Python projects set `pythonpath = ["."]` in `pyproject.toml`, so `cd` into the subdir first. No lint/typecheck/formatter config; verification is `pytest -v` per touched project. No CI workflows, no `opencode.json`.

```powershell
cd inventory
py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
pytest -v                                     # full suite (preferred)
pytest tests/test_objects.py -v               # single file
pytest tests/test_objects.py -k some_name -v  # single test
```

```powershell
cd mycelium-ai-main
pip install -e .   # no dev extra; pytest only needs: pip install pytest httpx
python -m uvicorn coordinator.app.main:app --host 127.0.0.1 --port 8000
python -m node_client.main --coordinator http://127.0.0.1:8000 --node-id seed-01 --tier seed --capability system_inventory --poll-seconds 5
pytest -v
```

`Mycelium/agent/` has its own tests (`agent/tests/`, ~100 tests) but no `pyproject.toml`; run `pytest -v` from `Mycelium/agent/`.

## Hard boundaries (architecture contract)

- **No cross-imports, no shared DB, no cross-DB queries.** `inventory/` and `mycelium-ai-main/` communicate only over HTTP, one direction: coordinator → INVENTory via `coordinator/app/inventory_read.py` (GET-only) and `coordinator/app/inventory_writes.py` (gated POST/PATCH, proposal → exact-`YES` → execute → verify).
- Bridge constraints (enforced + tested): loopback hosts only (`127.0.0.1`/`localhost`/`::1`, redirects never followed), query ≤ 200 chars, timeout ≤ 5s, entity IDs limited to known `xxx_` prefixes. Never extend to non-loopback hosts.
- `Mycelium/agent/` is read-only toward user projects; its only writes are its own `discovery.json` / `project_index.json`. Its bridge (`inventory_bridge.py`) is dry-run only — never wire it to HTTP or SQLite.
- Game views (`/side`, `/play`, `/world`, `/canvas`, `/forge`) are projections, never second databases. Session position is the only game-owned state. Per `PROJECTATLAS.md` §6, **`/side` is the primary runtime**; this overrules older roadmaps (`AUTOPILOT` P3 "game last", `ROADMAP-V2`, "BIG48 `/play` = runtime", `CANVAS_DIRECTION` FUTURE stays archive).

## INVENTory gotchas

- DB path: `INVENTORY_DATABASE_PATH` (default `data/inventory.db`, gitignored). Always point it at a tmp file when experimenting; never touch real data. Orphan copies at `data/inventory.db` and `mycelium-ai-main/data/inventory.db` are strays — coordinator never opens them.
- SQLite WAL + `busy_timeout=15000` is load-bearing (`app/database.py`); keep both on any new connection path.
- Canonical tables are source of truth; `*_fts` tables are a derived, rebuildable index (`rebuild_fts()`). Never write to `*_fts` directly.
- FTS input must go through `sanitize_fts_query()`; table names only from `SEARCHABLE_TYPES`. Never interpolate user input into MATCH SQL.
- Provenance rule in `app/schemas.py`: `ai-generated` without `verified_by` forces `human_verified=False`. Never hand-set `human_verified=True` on AI/sensor content.
- IDs are prefixed per entity (`obj_`, `proj_`, `idea_`, `rel_`, `evt_`, `hw_`, `sns_`, `cam_`, `loc_`, `mod_`, `task_`, `act_`, `file_`, see `app/ids.py`). New entities need a matching generator + `xxx_`-prefixed response pattern. Note: inventory `mod_` = AI model, **not** 3D model (coordinator 3D uses `mdl_`; `files/file_` with `file_kind=cad|mesh|gcode` is the sole 3D registry).
- Every CRUD mutation must append an event via `_append_event()` — tests cover the event stream. Relationships have no PATCH/single-GET by design; events are read-only (`GET /api/v1/events?entity_id&limit&since`).
- M3+ entities (hardware/sensors/cameras/locations/models/tasks/actuators/files) are world-model records only: no hardware access, no inference, no execution. There is no conversations table (only negative 422 tests).

## Coordinator gotchas

- DBs: `MYCELIUM_DATABASE_PATH` (default `data/mycelium.db`) + `MYCELIUM_CHAT_DATABASE_PATH` (chat DB); Docker overrides to `/data/*.db`. Same tmp-file discipline. Root `data/mycelium*.db` copies are strays.
- **No background threads, no scheduler, no auto-approval** (`jobs.py:12`, `main.py:3316`). Watcher/overnight/research-`run-once`/sweep only run via explicit POST (`/api/v1/jobs/run`, `/research/queue/run-once`, `/maintenance/sweep-leases`) or external cron. Startup `lifespan` only scans and reports (`recovery.scan`), executes nothing.
- Node semantics: staleness 60s, task lease 300s with max 3 attempts; re-registered `node_id` upserts — use a fresh `--node-id` if a stale registration confuses a manual test. Claim loop is pull-only; `system_inventory`/`desktop_screenshot`/`research.fetch_url` are the only auto-executable kinds; desktop input always requires exact-`YES`.
- Schema uses additive, idempotent migrations (`_ensure_*_columns`); follow that pattern, never a destructive migration. But note: quests/campaigns/research-runs/dossiers/queue/workspaces/candidates/automation-runs have routes + logic + tests yet **no `CREATE TABLE` in `database.py`** — do not assume restart durability; check before building on them.
- Name collisions (do not unify, do not guess): `task_` (inventory record, never executes) vs queue `tasks` (integer id, actually executes) vs `ctask-` (approved proposal, never queued) — quest `task` steps take queue ints only. `plans.py` Plan (inert) vs `missions.py` Mission (executable) vs `automation_runs` vs `res_` runs are separate tables by design. Camera observations (`cameras.py`), world observations (`world_observations.py` `wobs_`), and screen observations (`observations.py`) are three complementary models.
- Missing hardware is fail-closed, not broken: `paho-mqtt` absent → `PrinterUnavailable` (tested); no capture adapter → file-inbox only + honest `UNAVAILABLE` chips; Ollama (`:11434`) / Hermes (`:8642`) down → 502/503 with degrade. Do not "fix" by faking a provider or silently installing transports.
- `main.py` is ~24k lines / 530 routes (gemeten 2026-10-05), mixed NL/EN. New UI is server-rendered inline HTML (`ui.py` shell + `GRAPH_JS`/`CANVAS_JS` SVG, Canvas2D for `/play`/`/side`/forge 2D wireframe). No bundler, no Three.js, no `fetch` except: `/canvas` search, `/play` dialogs, `/side` game loop, `/solarpunk` movement/scan loops + town chat, `/homebase` Three.js scene (pinned CDN + honest fallback), `/forge` 3D-snapshot-preview (zelfde pinned CDN + fallback; 2D-editor blijft leidend). Three.js dus alleen `/homebase` + `/forge`-preview. Check existing `POST /web/*` handlers before adding routes.

## Do not touch

- `mycelium-ai-main/then/` and `mycelium-ai-main/source/` are committed venvs (`pyvenv.cfg`), not source. Likewise `__pycache__/`, `.pytest_cache/`, `agent_ui.py.backup`.
- `mycelium-ai-main/scripts/b*_smoke.py`, `b*_shots.py`, `b*_screenshots.py` (~29 b*-harnesses, 31 scripts totaal, gemeten 2026-10-05) and `docs/r*-shots/` PNG dirs are superseded by `tests/test_big*.py` + `test_smoke11_15.py`. Do not run them as suites; do not add more per-milestone scripts.
- `mycelium-ai-main/n8n/` workflows are localhost test fixtures only.

## Test quirks

- All 13 inventory test files set `os.environ["INVENTORY_DATABASE_PATH"]` directly (no `monkeypatch`), leaking to later tests in-process. Prefer the full per-project suite; for subsets, export a tmp DB path env var first.
- Coordinator tests use `TestClient(app)` with `lifespan` (DB init runs on client entry) — set `MYCELIUM_DATABASE_PATH` (+ chat path) to tmp files before constructing the client. ~6 test files also use raw `os.environ`; same leak risk. Some tests skip on non-Windows (`os.name != "nt"`) or need `git` on PATH.
- Test-count sentences in READMEs/roadmaps are all stale (actual: ~183 inventory + ~1860 coordinator `def test_` + ~100 agent). Recount with `Select-String ^\s*def test_` instead of trusting prose.

## Docs trust order

`AGENTS.md` > `PROJECTATLAS.md` > `MYCELIUM_REALITY_MAP.md` / `MYCELIUM_UI_GAP_MAP.md` > code + tests > `AI_HANDOFF/PROJECT_STATE.md` (lab journal, uncommitted BIG46–57) > roadmaps/READMEs (`AUTOPILOT_ROADMAP`, `ROADMAP.md`, `ROADMAP-V2.md`, `ARCHITECTURE_STATUS.md`, `Mycelium/agent/ARCHITECTURE_CONTRACT.md` are snapshots with obsolete status claims). If docs conflict with config, scripts, or tests, trust the executable source.
