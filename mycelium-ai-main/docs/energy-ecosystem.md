# Energy ecosystem (BIG #42)

Minimal energy domain: sources, production, consumption,
storage and current state, linked to projects/devices.

## Model

- Sources (closed): `solar` | `battery` | `grid` | `machine` |
  `other`.
- Kinds (closed): `production` | `consumption` | `storage` |
  `state`.
- **Unknown values stay NULL and render as UNKNOWN.**
  Measurements are never invented.
- Current state (`GET /api/v1/energy/state`) derives from the
  latest `state`-kind rows — never stored twice, explicit
  empty when nothing is recorded.

## Rules

- One observation per POST; `recorded_by` + observed_at +
  provenance on every row.
- Unknown energy honestly blocks energy-aware decisions
  (presence `energy_unknown`, guide items) instead of
  pretending availability.

## Symbiosis

Prefixes `enr_` + closed predicates `powers` / `powered_by`
(project↔energy, energy↔machine/node). Never merges entities.

## Future influence (not yet wired)

Routing, node availability, projects, machines, symbiosis,
guide and the morning report can read this store; BIG #42
exposes the data honestly but changes no routing weights.

## Surfaces

`/energy` page + API, presence `energy_unknown` (waiting),
guide energy items ("finance but no energy source"), morning
ENERGY section (only when records exist), overview `energy`,
packet-v2 energy block, mobile energy panel.
