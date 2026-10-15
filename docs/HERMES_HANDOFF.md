# HERMES Handoff — continue the shared agent workspace here

Date: 2026-10-06. Audience: an AI agent (or human) picking up where the
Solar Punk City game UI stopped. Everything below is verified against
the code; docs that disagree with code/tests lose (code is truth).

> **Superseding status check, 2026-10-15:** Local checks found coordinator, Hermes, Ollama, INVENTory, and the scheduler reachable. CouchDB `/_up` answered; the active Obsidian LiveSync vault is `Solarlab` on database `solarlab`. The prepared Mycelium vault is not yet open/configured, and Android has no NetBird HTTPS route. Docker container state could not be read from this shell. For current state, use `docs/CURRENT_STATE.md` and `Mycelium-Knowledge-Vault/What works today.md`.

> **Overdracht 2026-10-15:** Eerst Mycelium-Knowledge-Vault als aparte vault laten syncen en daarna via NetBird Private BYOP + DNS-01 de Android-notitie-roundtrip afronden; NetBird-peer is verbonden via relay, maar CouchDB blijft localhost-only en heeft nog geen HTTPS-proxypad.

## Operational update — 2026-10-14

- `tools/start-local.ps1` now checks loopback HTTP before launching each
  service and starts missing INVENTory (:8080), coordinator (:8000),
  Ollama (:11434), and Hermes gateway (:8642). It opens Docker Desktop and
  starts the loopback-only LiveSync CouchDB Compose service when the Docker
  engine is ready. A failed service no longer prevents startup attempts for
  the rest. This is a startup action, not a continuous watchdog.
  `install-autostart.ps1` installs a per-user Windows Startup shortcut
  (no administrator task registration). The shortcut is installed on this
  machine at sign-in.
- Coordinator `lifespan` now starts a fixed scheduler for four bounded,
  read-only jobs (watcher, device health, queue reconciliation, research
  source counts). It does not dispatch tasks or execute research. Status is
  visible at `/system` and `GET /api/v1/jobs/scheduler`; set
  `MYCELIUM_BACKGROUND_SCHEDULER=0` before restarting to disable it.
- Local Ollama/Hermes HTTP clients now ignore system proxy variables
  (`trust_env=False`) because their validated endpoints are loopback-only.
  Vision requests also disable Qwen thinking and cap generation at 160
  tokens. `qwen3.5:4b` is now the default vision model because it is
  installed locally; the previous default `qwen3-vl:4b` was absent. Manual
  synthetic-image check: Qwen returned a REAL screen summary through
  `_hermes_screen_summary`. A follow-up live call exposed a parser issue:
  Qwen combined a label and description on one line, which the old parser
  dropped. The prompt/parser now preserve inline descriptions; an end-to-end
  synthetic screen observation returned a label and readable summary.
  Keep the output cap because longer unconstrained Qwen calls previously
  timed out on this GTX 1050 Ti.
- Current host check: Ryzen 5 5600X, 16 GiB RAM, GTX 1050 Ti 4 GiB VRAM.
  Local health endpoints for all four services responded. Ollama has five
  installed models; inference is idle unless a request is made.
- Docker Desktop's engine is still blocked by firmware virtualization on
  this PC. Its startup launch is configured; CouchDB will be created and
  started automatically on a later sign-in once Docker reports a ready
  engine. No remote HTTPS route is configured.

## 1. What this repo is

Single root git repo, three runtime areas, no shared code or DB:

- `inventory/` — world-model store. FastAPI (`app/main.py`) + SQLite
  WAL on port **8080**.
- `mycelium-ai-main/` — coordinator (`coordinator/app/main.py`,
  ~26k lines / ~546 routes) + pull-only worker (`node_client/`) on
  port **8000**.
- `Mycelium/agent/` — local desktop scanner (Flask UI on **8787**),
  read-only toward user projects.

Trust order: `AGENTS.md` > `PROJECTATLAS.md` > code + tests >
lab journal (`AI_HANDOFF/PROJECT_STATE.md`) > roadmaps/READMEs
(snapshots, often stale).

## 2. What was built (Oct 2026) — reuse it, don't rebuild it

A town layer for NPC agents. All state lives in existing DBs
(additive tables in the chat DB, queue rows in the mycelium DB).
No second database, no scheduler, no background threads.

| Piece | Module | Routes |
|---|---|---|
| Town chat (round-robin or targeted `npc_id`, max 1 NPC turn, honest note without model) | `coordinator/app/town_chat.py` | `POST /api/v1/town/conversations`, `.../{id}/messages` |
| Town memory (`town_memories`, importance+recency, reflect 409 without model) | `town_memory.py` | `POST /api/v1/town/reflect` |
| NPC presence (`town_actors`/`town_activity`; status changes on real signals only — queued `town:{npc}` tasks — else honest `idle`) | `town_actors.py` | `GET /api/v1/town/actors` |
| Delegation (NPC drafts JSON spec → stored proposal with action/justification/blast-radius/confidence → literal `YES` queues one task; anything else rejects; second decision 409) | `town_proposals.py` | `POST /api/v1/town/npc/{id}/delegate`, `GET /api/v1/town/proposals`, `POST .../{pid}/decide`, `GET /api/v1/town/autonomy` |
| Autonomy dial (`TOWN_AUTONOMY="npc:kind"`, default empty; only `research.fetch_url`/`system_inventory`/`desktop_screenshot` may ever be listed; hardware/desktop-input never; auto-decisions logged as `standing-rule:TOWN_AUTONOMY`) | `town_proposals.py` | (same as above) |
| NPC chat chain (Hermes → Ollama → honest note; `OLLAMA_CHAT_MODEL`, default `phi4-mini`) | `hermes_npc.py`, `ollama_chat.py`, `hermes_bridge.py` | `POST /api/v1/hermes/chat`, `GET /api/v1/hermes/history`, `GET /api/v1/hermes/status` |
| Insta360 one-frame grab + 1-click view | `capture_probe.py`, `cameras.py` | `POST /api/v1/cameras/{id}/probe-grab`, `GET /api/v1/cameras/observations/{id}/image` |
| Forge 3D snapshot preview + BUILD queue buttons | `forge.py` | page `/forge`, actions via `/web/workshop/fabjobs/{id}/{action}` |
| Remote mouse/keyboard (opt-in node caps, explicit YES sessions) | `remote_input.py`, `node_client/` | UI on `/nodes`, API `/api/v1/remote-input/*` |

Tests: ~1950 coordinator (`pytest -v` in `mycelium-ai-main/`, tmp DBs
via env vars — never touch `data/*.db`), ~183 inventory, ~100 agent.
FAST after every edit (touched module only), FEATURE at feature
boundary, FULL only for milestones. See `docs/TESTING.md`.

## 3. Contract (non-negotiable unless the human says otherwise)

- No auto-approval, no scheduler, no background threads. Execution =
  proposal → exact-`YES` → execute → verify. Desktop input always
  exact-YES. Hardware fail-closed + mocked in pytest, never live in
  tests.
- Loopback only (`127.0.0.1`/`localhost`/`::1`); coordinator →
  INVENTory is GET-mostly over HTTP, never shared DB/imports.
- No credentials in code/docs/tests/logs. No shell/RCE.
- `/side` is frozen (read/test ok, never edit).
- Never commit/push/reset without an explicit order.
- Three.js only on `/homebase` + `/forge` preview (pinned
  `three@0.160.0` via unpkg + honest fallback); Canvas2D elsewhere.
- Living Principles (`mycelium-ai-main/docs/living-principles.md`):
  old laptops stay usable, energy visible, local-first, human
  overrides automation.

## 4. Why the game UI didn't land (honest retrospective)

The `/solarpunk` first-person raycaster works (movement, mouse-look,
NPC billboards, walk-up talk HUD, in-game chat — all proven with
headless-Chrome screenshots, zero JS errors) but never looked like
what the human wanted (GalaxyHQ/my-virtual-office polish). Causes:

1. **Fidelity gap**: flat-shaded Canvas2D + billboard sprites read as
   programmer art next to real 3D/pixel-art offices. More paint
   layers didn't close a taste gap.
2. **Label clutter**: 6 NPCs on one ray = overlapping name chips
   (later fixed with near→far declutter, but trust was gone).
3. **Stale pages**: inline-JS pages were browser-cached, so fixes
   didn't appear until hard refresh (later fixed with
   `Cache-Control: no-store` on `/solarpunk`).
4. **Model latency**: Hermes replies take ~30s+; the city feels
   asleep next to instant local UI.
5. **Empty world**: 0 districts until INVENTory has locations; NPCs
   700+ units from the old spawn (later fixed with a plaza spawn).
6. **Gateway limits**: the Hermes gateway offers chat only
   (`POST /v1/chat/completions` + `GET /health`, Bearer key,
   `X-Hermes-Session-Key` identity). No tools/tasks/presence — all
   "agentic" behavior (proposals, queue, dial, audit) is coordinator
   logic in §2. Don't expect it from the gateway.

## 5. Recommended ways forward with Hermes

- **A. Existing Hermes offices**: VirtOffice (3D, built for Hermes
  AgentOS subagents) or eliautobot/my-virtual-office (2D pixel,
  Hermes-supported). Point one at the gateway for presence, keep
  this coordinator beside it for memory/tasks/camera (§2 endpoints).
- **B. Keep the §2 backend, replace the frontend**: the endpoints
  are frontend-agnostic; any client can drive town life from them.
- **C. Extend the gateway first**: if agents must act (not just
  chat), the gateway needs tool/task/presence endpoints before any
  UI work matters.

## 6. Run it

```powershell
cd inventory
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
# other terminal:
cd mycelium-ai-main
python -m uvicorn coordinator.app.main:app --host 127.0.0.1 --port 8000
python -m node_client.main --coordinator http://127.0.0.1:8000 --node-id <fresh> --capability desktop.screen --remote-mouse --remote-click --remote-keyboard
```

Env: `HERMES_API_KEY` (Hermes, required for NPC voices),
`HERMES_API_URL` (default `http://127.0.0.1:8642`),
`OLLAMA_CHAT_MODEL` (default `phi4-mini`),
`TOWN_AUTONOMY` (default empty = nothing autonomous),
`INSTA360_DSHOW_NAME`, `INVENTORY_BASE_URL`,
`MYCELIUM_DATABASE_PATH`, `MYCELIUM_CHAT_DATABASE_PATH`
(point at tmp files when experimenting — never touch real data).
Windows startup scripts: `tools/start-local.ps1`,
`tools/install-autostart.ps1` (per-user Startup shortcut),
`tools/update.ps1` (ff-only, never force).

State of the tree at handoff: everything committed, nothing pushed.
`git status` + sync report first, then work.
