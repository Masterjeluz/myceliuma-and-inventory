# Hardware Reality Layer (BIG #39)

The coordinator knows what its nodes really are: live telemetry,
connected hardware, compute capabilities, and energy state —
reported by the nodes themselves, validated fail-closed, and
used for routing, guidance, and display. Nothing is executed,
nothing is inferred, nothing is promised.

## Philosophy

```
Node reports → coordinator validates → stores → routes,
guides, and shows. Never executes, never invents.
```

- **No new execution power**: telemetry is read-only state.
  The coordinator never drives hardware, runs inference, or
  starts work on a node. Tasks still route by advertised
  capabilities; telemetry only adds honest gates and ordering.
- **Fail-closed validation**: unknown telemetry fields, hardware
  kinds, compute capabilities, and energy sources are refused
  with 422. Nothing unknown is ever stored.
- **No wildcards, no shell**: capability rules from BIG #8 are
  untouched. Telemetry adds no executable surface (static
  assert in tests).
- **Node-reported, never verified**: hardware and compute are
  what the node claims. They appear as `node-reported`,
  `human_verified=False` provenance in the world graph — never
  as INVENTory world truth.
- **Provenance always**: overlays carry `source_type:
  node-reported` with the reporting node as creator.

## Data model

Six additive nullable columns on `nodes` (migration in
`_ensure_node_columns`, existing rows keep working):

| Column | Type | Meaning |
|--------|------|---------|
| `telemetry` | JSON object | CPU/memory/disk percents, counts, uptime, temperature, load average, interfaces, boot time |
| `telemetry_timestamp` | ISO text | When the last telemetry heartbeat arrived |
| `hardware` | JSON list | `{kind, identifier, details, status, connected_since}` |
| `compute_capabilities` | JSON list | `{capability, details, status, since}` |
| `energy_state` | JSON object | `{source, level_percent, charging, details, since}` |
| `health` | text | Reserved; health is derived live, not stored |

`Heartbeat` schema accepts the four new optional fields with
pydantic bounds (hardware ≤ 50, compute ≤ 20). Validation lives
in `nodes.py`: `check_telemetry`, `check_hardware`,
`check_compute_capabilities`, `check_energy_state`.

### Closed sets

- Telemetry: 16 known fields, bounded numbers (percents
  0–100, temperature −50–150 °C, non-negative counters).
- Hardware kinds: `camera`, `usb`, `printer_3d`, `sensor`,
  `storage`, `gpu`, `display`, `audio`, `network`, `other`.
- Compute capabilities: `ollama`, `local_models`,
  `cpu_inference`, `gpu_available`, `vram_mb`, `research`,
  `vision`, `inventory`, `analysis`.
- Energy sources: `grid`, `solar`, `battery`, `unknown`.
- Hardware status: `connected` / `disconnected` / `error` /
  `unknown` (normalized, never refused).
- Compute status: `available` / `busy` / `unavailable` /
  `unknown` (normalized, never refused).

## Health: ONLINE / DEGRADED / STALE / OFFLINE / UNKNOWN

Derived live in `_compute_health_status` (and
`compute_node_health` for pure use) from stored status +
telemetry freshness:

- `disabled` → OFFLINE (sticky, wins over everything)
- `offline` → OFFLINE, `stale` → STALE
- online/busy with telemetry older than 5 minutes → DEGRADED
- online/busy otherwise → ONLINE

Health never disqualifies silently: routing treats it as an
explicit `min_health` requirement with inspectable reasons.

## Telemetry-aware routing

`routing.py` gains hard gates (any failure rejects with an
exact reason) and preferences (score only, never requirements):

Hard gates:
- `required_hardware`: every kind must be `connected` on the
  node right now. Disconnected hardware does not count.
- `required_compute`: every capability must be `available`.
  Busy does not count.
- `max_telemetry_age_seconds`: telemetry timestamp must be
  fresh enough; missing/invalid timestamps reject.
- `min_health`: `ONLINE(4) > DEGRADED(3) > STALE(2) >
  OFFLINE(1) > UNKNOWN(0)`.

Preferences (`RoutingPolicy`):
- `prefer_fresh_telemetry` (+1 for telemetry < 60 s)
- `prefer_connected_hardware` (+1 when any connected)
- `prefer_compute_capabilities` (+1 when any available)

Energy and resources stay preferences, never disqualifiers —
unchanged from BIG #8.

## Surfaces

| Surface | Hardware Reality integration |
|---------|------------------------------|
| Nodes API (`/api/v1/nodes`, `/api/v1/nodes/{id}`) | Telemetry, hardware, compute, energy, `health_status`, `telemetry_timestamp` |
| `/nodes` page + capability check | Existing cards; routing dry-run answers capability questions |
| Route dry-run (`POST /api/v1/tasks/route`) | Hardware/compute/health/telemetry-age requirements honored |
| Mobile (`/api/v1/mobile/dashboard`, `/mobile`) | Nodes panel: health + cpu/mem/disk/temp/uptime + hardware counts/kinds + compute counts/capabilities + energy |
| Guide (`/api/v1/guide`, `/guide`) | Ollama-online, GPU-available, camera-connected, printer-connected, offline-node, disconnected-hardware, research-waiting items (all link to `/nodes`) |
| World graph (`/world?show=…,hardware,compute`) | Node overlay carries health/telemetry/hardware/compute counts; `hw_<node>_<id>` nodes (HAS edges) for connected hardware; `compute_<node>_<cap>` nodes (PROVIDES edges) for available compute |
| Notifications | Additive bus types `node.health_changed`, `node.hardware_changed`, `node.compute_changed`, `node.telemetry_received`; additive IN_APP kinds `node_online/degraded/stale`, `hardware_connected/disconnected`, `capability_available/unavailable`, `telemetry_stale`, `mission_blocked_hardware`. WEB_PUSH stays UNAVAILABLE |

## Node client

`node_client/main.py` collects read-only state with psutil
(best-effort, every call guarded) and sends it on every
heartbeat:

- `collect_telemetry()` — hostname, OS, CPU/memory/disk,
  uptime, temperature (Linux), load average (Unix), interface
  names only. No process lists, no credentials, no paths.
- `collect_hardware()` — v4l2 cameras, `lsusb` devices,
  serial 3D-printer ports, NVIDIA GPUs. Detection only.
- `collect_compute_capabilities()` — `ollama list` models,
  always-on `cpu_inference`, `nvidia-smi` GPU/VRAM, derived
  `research`/`analysis`/`vision`/`inventory` flags.
- `collect_energy_state()` — battery level/charging or
  grid assumption; `unknown` on failure.

Subprocess calls are bounded (`timeout=3–5 s`), output
truncated, and failures degrade to empty — a node never
fails to heartbeat because detection failed.

## Security

- Unknown fields/kinds/capabilities/sources → 422, nothing
  stored (partial updates keep prior good values via
  `COALESCE`, never partial-bad writes).
- Credential gates untouched: bad tokens 403, unknown nodes
  404, disabled nodes refused, legacy freeze preserved.
- No wildcard capabilities, no shell metacharacters, no
  URLs/credentials in providers — existing tripwires all
  still green.
- Node-reported data never enters INVENTory, never becomes
  memory/candidate truth, never approves anything.
- Labels: node-reported state is REAL (measured locally);
  disconnected/stale data is shown as such, never hidden;
  printer transport stays UNAVAILABLE; fab execution stays
  SIMULATED. See the final report §REAL/TEST/SIMULATED.

## Limitations

- Health is freshness-based, not diagnostic: DEGRADED means
  "telemetry older than 5 minutes", nothing more.
- Hardware/compute are self-reported claims; a lying node
  can claim a GPU. Routing treats them as advertisements
  (like capabilities), not attestations.
- No push: the coordinator never polls nodes; state is only
  as fresh as the last heartbeat.
- Bus event types exist additively; heartbeat does not emit
  per-beat events (no spam). Surfaces read live store state.
