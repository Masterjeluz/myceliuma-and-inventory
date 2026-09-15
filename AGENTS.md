# AGENTS.md

Root is a plain folder, not a monorepo: no workspace config, no root git repo, no shared dependencies. Three independent areas:

- `inventory/` — world-model store. FastAPI (`app/main.py`) + SQLite WAL on port **8080**. This is the only git repo here.
- `mycelium-ai-main/` — coordinator task queue (`coordinator/`) + polling client (`node_client/`) on port **8000**. Not under git.
- `Mycelium/agent/` — local desktop agent (filesystem observer, UI on **8787**). Runtime data lives in `Mycelium/{memory,backups,workspace,projects}` — do not treat as source code.

## Commands (run from the project subdir, not root)

Both Python projects set `pythonpath = ["."]` in `pyproject.toml`, so `cd` into the subdir first.

```powershell
cd inventory
py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
pytest -v                                   # full suite
pytest tests/test_objects.py -v             # single file
pytest tests/test_objects.py -k some_name -v  # single test
```

```powershell
cd mycelium-ai-main
pip install -e .   # dev extra does not exist here; pytest only: pip install pytest httpx
python -m uvicorn coordinator.app.main:app --host 127.0.0.1 --port 8000
python -m node_client.main --coordinator http://127.0.0.1:8000 --node-id seed-01 --tier seed --capability system_inventory --poll-seconds 5
pytest -v
```

No lint/typecheck/formatter config exists. Verification is `pytest -v` per touched project.

## Hard boundaries (architecture contract)

- **No cross-imports, no shared DB, no cross-DB queries.** `inventory/` and `mycelium-ai-main/` communicate only over HTTP, and only in one direction: coordinator → INVENTory via the read-only bridge in `mycelium-ai-main/coordinator/app/inventory_read.py`.
- Bridge constraints (enforced + tested): HTTP GET only, loopback hosts only (`127.0.0.1`/`localhost`/`::1`, redirects never followed), query ≤ 200 chars, timeout ≤ 5s, entity IDs limited to known `xxx_` prefixes. Never extend it to writes or non-loopback hosts.
- `Mycelium/agent/` is read-only toward user projects; its only writes are its own `discovery.json` / `project_index.json`. Keep it that way.

## INVENTory gotchas

- DB path: `INVENTORY_DATABASE_PATH` (default `data/inventory.db`, gitignored). Always point it at a tmp file when experimenting so you never touch real data.
- SQLite WAL + `busy_timeout=15000` is load-bearing (`app/database.py`); keep both on any new connection path.
- Canonical tables are source of truth; `*_fts` tables are a derived, rebuildable index (`rebuild_fts()`). Never write to `*_fts` directly.
- FTS input must go through `sanitize_fts_query()` (plain-text phrases); table names only from `SEARCHABLE_TYPES`. Never interpolate user input into MATCH SQL.
- Provenance rule is enforced in `app/schemas.py`: `ai-generated` without `verified_by` forces `human_verified=False`. Never hand-set `human_verified=True` on AI/sensor content.
- IDs are prefixed per entity (`obj_`, `proj_`, `idea_`, `rel_`, `evt_`, `hw_`, `sns_`, `cam_`, `loc_`, `mod_`, `task_`, `act_`, `file_`, see `app/ids.py`). New entities need a matching generator + `xxx_`-prefixed response pattern.
- Every CRUD mutation must append an event via `_append_event()` — tests cover the event stream.
- M3+ entities (hardware/sensors/cameras/locations/models/tasks/actuators/files) are world-model records only: no hardware access, no inference, no execution.

## Mycelium coordinator gotchas

- DB path: `MYCELIUM_DATABASE_PATH` (default `data/mycelium.db`); Docker overrides to `/data/mycelium.db`. Same tmp-file discipline as above.
- Start coordinator before any node; node staleness is 60s, task lease 300s with max 3 attempts (`coordinator/app/main.py`). A re-registered `node_id` upserts — use a fresh `--node-id` if a stale registration confuses a manual test.
- Schema uses additive, idempotent migrations (`_ensure_task_columns`); follow that pattern, never a destructive migration.

## Test quirks

- Some tests set `os.environ["...DATABASE_PATH"]` directly instead of `monkeypatch`, leaking the value to later tests in the process. Prefer running the full per-project suite; if running a subset, export a tmp DB path env var first.
- Coordinator tests use `fastapi.testclient.TestClient(app)` with `lifespan` (DB init runs on client entry) — set the DB env var before constructing the client.
- Docs lag behind code: both READMEs and `Mycelium/agent/ARCHITECTURE_CONTRACT.md` describe older milestones (e.g. "hardware missing", "35 tests") that the code has since passed. Trust `app/main.py`, `app/database.py`, `app/schemas.py`, and the `tests/` directory over prose.
