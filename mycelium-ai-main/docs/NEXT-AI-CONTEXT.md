# NEXT-AI-CONTEXT — continue Mycelium development here

Date: 2026-09-19. HEAD: `BIG #39 - build hardware reality layer`
(main, pushed to origin/main). Start with `git log --oneline -5`
and `git status` (a pre-existing `Mycelium/agent/agent_ui.py`
modification is NOT ours — leave it; `scripts/b38_screenshots.py`
is an untracked BIG #38 leftover — leave it).

## Architecture in one paragraph

Local-first personal AI: coordinator (`:8000`, FastAPI + SQLite
WAL) is the authority (approvals, tasks, leases, missions);
INVENTory (`:8080`) is the world memory, read via GET-only
loopback bridge (`inventory_read.py`), written only via gated
proposals (`inventory_writes.py` + exact YES + verification);
Ollama/external models are advisors (never authority); desktop
agent is the only hands (pull-only, outbound). Nodes report
read-only telemetry/hardware/compute/energy on heartbeat
(BIG #39); the coordinator validates fail-closed, derives
ONLINE/DEGRADED/STALE/OFFLINE/UNKNOWN health, and routes by
it — never executes on nodes. Provenance always; health
scoped; no shell/RCE; no background threads (jobs run on
explicit trigger). Tests: `pytest -v` per project with tmp DB
env vars (`MYCELIUM_DATABASE_PATH`, `MYCELIUM_CHAT_DATABASE_PATH`
before TestClient; `MYCELIUM_FABRICATION_DIR` for fab tests).
Full Mycelium suite: 1325 tests, batch-run (single run exceeds
10-min timeout); INVENTory: 179 + 1 pre-existing byte-size
failure (do not touch that test).

## What BIG #39 added (where)

- `coordinator/app/nodes.py` — `check_telemetry/hardware/
  compute_capabilities/energy_state` (closed sets, bounded,
  fail-closed) + `compute_node_health`
- `coordinator/app/database.py` — additive migration (6
  nullable columns; existing rows keep working)
- `coordinator/app/schemas.py` — `Heartbeat` telemetry fields
  (hardware ≤ 50, compute ≤ 20)
- `main.py` — heartbeat stores telemetry (+timestamp) /
  hardware / compute / energy (dynamic COALESCE update);
  `health_status` on node JSON; routing candidates project
  hardware/compute/telemetry-age/health; world builder wired
  to `show=…,hardware,compute`; mobile nodes HTML shows
  health + telemetry + hardware + compute + energy
- `routing.py` — hard gates (`required_hardware`,
  `required_compute`, `max_telemetry_age_seconds`,
  `min_health`) + preferences (`prefer_fresh_telemetry`,
  `prefer_connected_hardware`, `prefer_compute_capabilities`)
- `worldgraph.py` — registry counts + `hw_*` (HAS) /
  `compute_*` (PROVIDES) overlays, `node-reported` +
  `human_verified=False`
- `mobile.py` — nodes panel (health, telemetry, hardware,
  compute, energy); `guide.py` — Ollama/GPU/camera/printer/
  offline/disconnected/research-waiting items → `/nodes`
- `events.py` — additive `node.*` bus types;
  `notify_center.py` — additive IN_APP kinds (WEB_PUSH stays
  UNAVAILABLE)
- `node_client/main.py` — read-only psutil collectors sent
  on every heartbeat (bounded, degrade-to-empty)
- Tests: `tests/test_big39_telemetry.py` (20) +
  `test_nodes.py` (+42) + `test_routing.py` (+12).
- Scripts: `scripts/b39_smoke.py` (25 checks, tmp DBs),
  `scripts/b39_shots.py` + `scripts/b39_screenshots.py`.
- Docs: `docs/hardware-reality-layer.md`,
  `docs/BIG39-final-report.md`.
- Lessons: two fail-closed wiring gaps found while testing
  (`_routing_candidates` projection, `_graph_data` overlay
  flags) — both fixed + tested; partial heartbeats keep
  prior good values via COALESCE; hardware claims are
  advertisements, not attestations.

## Docs to read first

`docs/ARCHITECTURE_STATUS.md` (truth), `docs/ROADMAP.md` +
`docs/ROADMAP-V2.md` (BIG #40),
`docs/hardware-reality-layer.md`, `docs/living-automation.md`,
`docs/automation-security.md`,
`docs/conversation-intelligence.md`, `docs/mobile-mycelium.md`,
`docs/3d-workshop.md`, `docs/camera-ecosystem.md`,
`docs/living-ecosystem.md`, `docs/knowledge-lifecycle.md`,
`docs/research-routing.md`, `docs/context-packets.md`,
`docs/mycelium-ui-personality.md`, `docs/BIG39-final-report.md`
(§2 = commit/push record).

## Next BIG (from BIG39 report §13 / ROADMAP-V2)

BIG #40: Presence — per-recipient in-app delivery (including
the nine BIG #39 `node_*/hardware_*/capability_* /
telemetry_stale / mission_blocked_hardware` kinds), morning
"why open Mycelium today" answer, overnight digest of queue +
discoveries + connections. Web push only with a real
transport; until then explicit UNAVAILABLE. Screenshots in
`docs/r40-shots/`, one commit `BIG #40 - ...`, push to
`origin/main`. Mycelium V2 moves to BIG #41.
