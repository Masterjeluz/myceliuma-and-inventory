# BIG #39 — eindrapport

## 1. Status

DONE — built, tested, smoked, screenshotted, documented,
committed, pushed.

## 2. Commit SHA

`BIG #39 - build hardware reality layer` (SHA verified against
remote HEAD after push; see git log).

## 3. Files changed

New:
- `tests/test_big39_telemetry.py` — 20 tests (heartbeat API,
  routing dry-run, mobile page, guide, world-graph builder,
  bus events, notify center, node-client collectors, schema
  bounds)
- `scripts/b39_smoke.py` — full chain on tmp DBs (25 checks)
- `scripts/b39_shots.py` — seed data for screenshots
- `scripts/b39_screenshots.py` — server + Playwright capture
- `docs/r39-shots/` (6 PNGs)
- `docs/hardware-reality-layer.md`
- `docs/BIG39-final-report.md` (this file)

Extended:
- `coordinator/app/database.py` — additive migration: 6
  nullable columns (`telemetry`, `telemetry_timestamp`,
  `hardware`, `compute_capabilities`, `energy_state`,
  `health`); existing rows keep working
- `coordinator/app/schemas.py` — `Heartbeat` accepts the four
  optional fields (pydantic bounds: hardware ≤ 50,
  compute ≤ 20)
- `coordinator/app/nodes.py` — `check_telemetry`,
  `check_hardware`, `check_compute_capabilities`,
  `check_energy_state` (closed sets, bounded numbers,
  fail-closed) + `compute_node_health`
- `coordinator/app/main.py` — heartbeat stores telemetry (+
  timestamp) / hardware / compute / energy via dynamic
  COALESCE update; `_node_to_json` parses new fields and adds
  `health_status`; `_routing_candidates` projects hardware /
  compute / telemetry age / health into routing input;
  `_graph_data` wires `hardware` / `compute` show-flags into
  the world builder; `/world` layer help lists the new
  overlays; mobile nodes HTML renders health + telemetry +
  hardware + compute + energy per node
- `coordinator/app/routing.py` — hard gates
  (`required_hardware`, `required_compute`,
  `max_telemetry_age_seconds`, `min_health`) + preferences
  (`prefer_fresh_telemetry`, `prefer_connected_hardware`,
  `prefer_compute_capabilities`); energy/resources stay
  preferences, never disqualifiers
- `coordinator/app/worldgraph.py` — registry overlay carries
  health + telemetry/hardware/compute counts; `hw_<node>_<id>`
  nodes (HAS edges) for connected hardware;
  `compute_<node>_<cap>` nodes (PROVIDES edges) for available
  compute; `node-reported`, `human_verified=False`
  provenance throughout
- `coordinator/app/mobile.py` — nodes panel: health +
  cpu/mem/disk/temp/uptime + hardware counts/kinds +
  compute counts/capabilities + energy
- `coordinator/app/guide.py` — hardware-aware items:
  Ollama-online, GPU-available, camera-connected,
  printer-connected, offline-node, disconnected-hardware,
  research-waiting (all link to `/nodes`)
- `coordinator/app/events.py` — additive bus types
  `node.health_changed`, `node.hardware_changed`,
  `node.compute_changed`, `node.telemetry_received`
- `coordinator/app/notify_center.py` — additive IN_APP kinds
  `node_online/degraded/stale`, `hardware_connected/
  disconnected`, `capability_available/unavailable`,
  `telemetry_stale`, `mission_blocked_hardware`
- `node_client/main.py` — read-only collectors
  (`collect_telemetry/hardware/compute_capabilities/
  energy_state`, psutil best-effort, bounded subprocess,
  never fails the heartbeat) sent on every heartbeat
- `tests/test_nodes.py` (+42), `tests/test_routing.py` (+12)
- `docs/NEXT-AI-CONTEXT.md`
- `docs/ROADMAP-V2.md`
- `README.md` (docs list + test count touch-up)

NOT in this commit (left untouched on purpose):
- `Mycelium/agent/agent_ui.py` — pre-existing local
  modification, not ours
- `scripts/b38_screenshots.py` — untracked BIG #38 leftover,
  not staged
- `inventory/` — zero changes; its 1 pre-existing failure is
  unchanged (see §Tests)

## 4. Hardware Reality Layer

Nodes report what they really are; the coordinator validates,
stores, routes, guides, and shows — never executes, never
invents. Full contract in `docs/hardware-reality-layer.md`.

**Health** is derived live, never stored:
`disabled → OFFLINE`; `offline → OFFLINE`; `stale → STALE`;
online/busy with telemetry older than 5 min → DEGRADED;
otherwise ONLINE.

**Two wiring gaps found and fixed while testing** (both
fail-closed, both covered by new tests):
1. `_routing_candidates` never projected hardware/compute/
   telemetry-age/health into routing input, so every
   telemetry-aware requirement missed honestly but always.
   Now projected (validated store data, never credentials).
2. `_graph_data` never passed `include_hardware` /
   `include_compute` to the world builder despite the builder
   supporting them. Now wired to `show=…,hardware,compute`.

**Mobile nodes HTML** now renders the telemetry the JSON
panel already carried (health + cpu/mem + uptime + hardware
kinds + compute capabilities + energy per node).

## 5. API Surface

```
POST /api/v1/nodes/{node_id}/heartbeat   (extended: telemetry,
    hardware, compute_capabilities, energy_state)
GET  /api/v1/nodes  /  /api/v1/nodes/{node_id}
    (extended: telemetry, telemetry_timestamp, hardware,
     compute_capabilities, energy_state, health_status)
POST /api/v1/tasks/route  (extended: required_hardware,
    required_compute, max_telemetry_age_seconds, min_health)
GET  /world?show=missions,nodes,hardware,compute
```

Web: `/nodes` (cards + capability check + mesh),
`/mobile` (nodes panel with hardware detail), `/guide`
(hardware-aware items), `/world` (hardware/compute layers).

## 6. Security

- Unknown telemetry fields / hardware kinds / compute
  capabilities / energy sources → 422, nothing stored.
  Partial heartbeats keep prior good values (COALESCE);
  never partial-bad writes.
- Credential gates untouched: bad tokens 403, unknown nodes
  404, disabled refused, legacy freeze preserved. Wildcard
  and shell-shaped capabilities still refused (tripwires
  green, smoked).
- No new execution surface: telemetry is read-only state;
  no shell/RCE surface (static assert in tests); node
  subprocess calls bounded (3–5 s timeouts, truncated
  output, degrade-to-empty).
- Node-reported data never enters INVENTory, never becomes
  memory/candidate truth, never approves anything. World
  overlays carry `node-reported` + `human_verified=False`.
- Health is freshness-based, not diagnostic; hardware claims
  are advertisements (like capabilities), not attestations —
  documented, not hidden.

## 7. Tests

New/changed: 74 tests, all green.

- `tests/test_nodes.py` (+42): telemetry bounds (percents,
  temperature, counters, load-average shape, interface
  truncation, string bounds, field-count cap), hardware
  (closed kinds, identifier required, status normalization,
  item cap, unknown-field refusal), compute (closed
  capabilities, status normalization, item cap), energy
  (closed sources, 0–100 level, boolean charging), health
  matrix (ONLINE/DEGRADED/STALE/OFFLINE/UNKNOWN/no-telemetry).
- `tests/test_routing.py` (+12): hardware/compute hard
  gates (connected/available only), telemetry-age gate,
  min_health ordering, freshness/hardware/compute
  preferences, positive reasons, invalid requirement
  refusals.
- `tests/test_big39_telemetry.py` (20): register →
  heartbeat → ONLINE over the real API; all four refusal
  classes (422 + nothing stored); gates intact (403/404/
  wildcard/shell); partial-update keeps prior fields;
  route-preview match/miss/min_health; mobile panel data;
  mobile page hardware detail; guide hardware awareness;
  world-graph overlays + builder flags on/off; bus event
  types + unknown-type refusal; notify-center types,
  severities, IN_APP receipt, WEB_PUSH UNAVAILABLE;
  node-client collectors validate; schema bounds.

Full Mycelium suite: **1325 passed, 0 failed** across all
108 test files in 25 bounded batches (single run exceeds the
10-min tool timeout; per-batch evidence in the run log).

INVENTory suite: **179 passed + 1 pre-existing failure**
(`test_milestone_3_8.py::test_real_inventory_db_untouched`
asserts the real `data/inventory.db` is exactly 73728 bytes;
on disk it is 573440 bytes through real use). `inventory/`
is untouched by this BIG; failure is environmental and
unchanged. Do not touch that test.

## 8. Smoke

`scripts/b39_smoke.py` on tmp DBs: 25/25 OK.

Chain verified:
1. Node registered with token (201)
2. Heartbeat with full telemetry/hardware/compute/energy
   accepted (204)
3. Node health ONLINE + telemetry + timestamp + hardware +
   compute + energy readable
4. Telemetry-aware routing matches (camera + ollama +
   ONLINE) and misses honestly (printer_3d → none)
5. Mobile dashboard JSON carries telemetry/hardware/compute
6. Guide API is hardware-aware (Ollama + GPU)
7. Notification capability lists node kinds; WEB_PUSH
   UNAVAILABLE
8. Pages render: `/nodes`, `/mobile`, `/guide`, `/world`
9. Refusals: unknown telemetry field 422, unknown hardware
   kind 422, bad credential 403, wildcard capability 422

## 9. Screenshots

`docs/r39-shots/` (Edge headless, real seed data, reviewed):

1. `nodes-1440.png` — `/nodes` with onboarding, routing
   check, mesh, both node cards
2. `routing-1440.png` — `/nodes?check_cap=camera.snapshot`
   capability routing answer
3. `world-1440.png` — `/world` Layers panel with
   `missions,nodes,hardware,compute` overlays documented
   (graph honestly empty: no INVENTory entity open)
4. `mobile-1440.png` — `/mobile` full dashboard
5. `hardware-1440.png` — mobile `#nodes` panel: per-node
   health, cpu/mem, uptime, hardware kinds, compute
   capabilities, energy
6. `guide-1440.png` — `/guide` with Ollama/GPU/camera/
   printer/disconnected-hardware/research-waiting items

## 10. REAL / TEST / SIMULATED / UNAVAILABLE

| Aspect | Label |
|--------|-------|
| Node telemetry (psutil, local measure) | REAL |
| Hardware/compute inventory (node-reported claims) | REAL claims, explicitly unverified (`node-reported`, `human_verified=False`) |
| Health derivation (freshness only) | REAL (documented as freshness, not diagnosis) |
| Disconnected/stale/offline display | REAL (shown as such, never hidden) |
| IN_APP notifications | REAL (polling store) |
| WEB_PUSH | UNAVAILABLE (explicit, capability endpoint) |
| Camera live capture (Insta360) | UNAVAILABLE (unchanged) |
| Printer transport | UNAVAILABLE (unchanged) |
| Fab execution | SIMULATED (unchanged, never REAL) |
| Background threads / coordinator push | NEVER |

## 11. Limitations

- Health is freshness-based, not diagnostic.
- Hardware/compute are self-reported advertisements, not
  attestations; a lying node can claim a GPU.
- State is only as fresh as the last heartbeat (pull-only;
  coordinator never polls).
- Heartbeat emits no per-beat bus events (no spam); the four
  additive `node.*` bus types exist for consumers. Surfaces
  read live store state.
- World-graph hardware/compute overlay nodes covered by
  builder tests; the `/world` screenshot shows the layer UI
  with an honestly empty graph (no live INVENTory entity in
  the shot DB).

## 12. What Jelles can do tomorrow

1. Open `/nodes` — see both machines with WHAT IT CAN DO
2. Type a capability in "Which node can do this?" — dry-run
   answer names the eligible node
3. Open `/mobile` — per-node cpu/mem, hardware, compute,
   battery/grid at a glance
4. Open `/guide` — Ollama/GPU/camera/printer items point at
   `/nodes`; disconnected hardware is named, not hidden
5. Open `/world?show=missions,nodes,hardware,compute` —
   hardware/compute overlays documented as layers
6. Queue a task with `required_hardware: ["camera"]` — it
   routes to the node with a connected camera, waits
   honestly otherwise
7. Run `python scripts/b39_smoke.py` with `B39_SMOKE_TMP`
   set — 25 checks re-prove the chain any time

## 13. Recommended BIG #40

Presence (the deferred BIG #38 §21 plan, now feasible on
real node state): per-recipient in-app notification delivery
— including the nine new `node_*/hardware_*/capability_* /
telemetry_stale / mission_blocked_hardware` kinds, which today
exist as types without a per-recipient fan-out — plus the
morning "why open Mycelium today" answer and an overnight
digest of queue + discoveries + connections. The hardware
reality layer gives Presence honest machine state to deliver:
route by what nodes really have, notify about what really
changed, show what is really connected. Web push only with a
real transport; until then explicit UNAVAILABLE. Mycelium V2
(the full autonomous local-first ecosystem) moves to
BIG #41 (see ROADMAP-V2).
