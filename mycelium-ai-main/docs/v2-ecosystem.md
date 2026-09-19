# Mycelium V2 Ecosystem (BIG #41)

One coherent living local-first ecosystem built from the
BIG #1–40 systems — no rebuilds, no new authority, no
weakened gates. V2 connects what exists: the coordinator
routes, nodes report, presence attends, the world shows.

## Unified model

`GET /api/v1/ecosystem/overview` composes existing stores
into eight answers, each naming its source; any failing
source degrades to explicit empty, never invented data:

- WHAT EXISTS — inventory counts + layer counts
  (`ecosystem_summary`)
- WHAT IS CONNECTED — symbiosis proposals + mesh edges
- WHAT IS HAPPENING — living state + last 5 bus events
- WHAT NEEDS ATTENTION — presence counts + top NEEDS YOU
- WHAT CAN I DO NEXT — presence suggested actions
- WHAT CAN MY NODES DO — online nodes: capabilities,
  connected hardware, current task
- WHAT IS BLOCKED — presence blocking types with links
- WHAT IS GROWING — progression counts (no XP, real stores)

`/world` carries a compact state strip (state line +
waiting/discoveries/offline + top attention + overview
link). The full overview stays out of the async page path:
inventory reads live behind the sync JSON endpoint.

## Remote node mesh (foundation)

`Node A → coordinator → Node B`, controlled end to end:

- Closed task kinds (`ALLOWED_TASK_KINDS`), closed
  capability prefixes, JSON-serializable payloads ≤4KB,
  secret-name scan, no wildcards, no shell-shaped anything.
- Pinned targets must be registered, enabled, and advertise
  the exact capability themselves — reachability grants
  nothing, and a node never gains capabilities through
  another node.
- `POST /api/v1/mesh/preview`: dry run — validate +
  routing explanation, creates nothing.
- `POST /api/v1/mesh/delegate`: authenticate requester →
  validate → eligibility precheck → create queued task →
  assign to target. Assign failure rolls the row back, so a
  task meant for one node can never drift to another.
- The target must still pull/claim (liveness + credential
  re-checked); lease 300s, max 3 attempts — the existing
  task machine, unchanged.
- Timeout (5–300s) is validated, recorded in the receipt and
  audit, enforced by the lease. Priority −10..10.
- Observability: `task.delegated` bus event names
  requester → target + reason; receipt carries WHAT / WHY /
  WHERE / CAPABILITY / RISK / RESULT (`/api/v1/tasks/by-id`)
  — the same vocabulary mobile uses before any approval.

## Live hardware reality

On top of BIG #39 telemetry:

- Every node listing carries `current_task` (assigned task
  id + kind, one indexed query, best-effort) — visible in
  the API, mobile nodes panel, and mobile hardware detail
  ("busy: task #N").
- `GET /api/v1/nodes/{id}/reality`: derived state, health,
  heartbeat age, telemetry summary, per-hardware trust,
  compute, energy, roles, current task. Read-only.
- Trust levels: ADVERTISED (said so — default, never a
  fact), OBSERVED (connected + fresh <300s report),
  VERIFIED (reserved for an explicit human link, like
  printer twins — no automated path may ever derive it,
  asserted in tests).

## Routing 2.0

From "which node can perform this" toward "which available
node should receive this bounded task" — without any
black-box ranking:

- Every rejection carries a verdict: `waiting` (transient:
  stale, unauthenticated, old telemetry, low health),
  `blocked` (disabled — operator re-enable required),
  `unavailable` (the task does not fit: caps, models,
  executor, locality, hardware, compute).
- `prefer_idle` policy (+1 for zero running tasks) as
  ordering-only preference; workload always visible in
  reasons when enabled, absent by default.
- `explain_decision()` groups candidates into WHY ELIGIBLE
  / WHY WAITING / WHY BLOCKED / WHY NOT AVAILABLE with the
  router's own reasons; `POST /api/v1/tasks/route` returns
  it as `why`. Deterministic, inspectable, no new ranking.

## World state

Presence + living state + nodes, derived now, rendered as
the cockpit strip and the JSON overview. The world graph
registry overlay carries per-node `attention_needs` /
`attention_offline` (boundary-matched ids, best-effort).
Graph nodes still never merge with INVENTory truth; health
still never enters the graph as fact.

## Craft (first-class navigation)

Chain stages keep their 12 real-data buckets; each stage
now carries a state with evidence: ✓ COMPLETE (linked
evidence present — never "work finished"), ● ACTIVE
(linked mission/fab running or waiting), ! BLOCKED
(linked record failed/blocked), ○ MISSING (empty + gap
with href). Surfaced in `/api/v1/craft` (`states`) and the
`/craft` page headers. The chain already spans idea →
research → materials → machines → model → fabrication →
observation → new knowledge on real links.

## Symbiosis 2.0 (foundation)

Same PROPOSED/SUPPORTED/VERIFIED engine, wider world: new
prefixes `node_`/`node-` (machine↔node, device↔node),
`res_`/`dos_` (research↔project), `auto_` (run↔project),
`food_`/`meal_` (health↔food, food↔project). Finance/energy
entity stores do not exist — no prefixes invented for them.
Closed `SYMBIOSIS_PREDICATES` (union of the INVENTory
relationship verbs and camera link verbs): proposal input
is refused on unknown verbs; stored edge verbs render
through `display_predicate` (unknown → "related" — edges
are never hidden, meanings never invented). Never merges
entities.

## Guide 2.0

Adds WHAT IS BLOCKING ME (failed/blocked automation runs
and missions with the exact unlock path) and WHAT WOULD
UNLOCK IT (research readiness naming the eligible node, or
the honest wait reason). Built on the same readiness check
as presence — which also fixed a wolf-crying bug: the old
inline check passed raw registry rows without fresh/auth
flags, so it reported "no eligible node" on healthy meshes.

## Game layer (foundation only)

No XP, no fake accomplishments — real state is the
progression system: quests (open missions + automation runs
with done/total, linked), discoveries/observations/growth/
activity counts, capabilities unlocked, ecosystem health
(online/offline/blocked). Surfaced on `/presence`
(activity panel), the JSON overview, and the world strip.
Terminology (QUEST, DISCOVERY, CRAFT, SYMBIOSIS, GROWTH,
UNLOCK) names existing concepts; nothing new is invented.

## Living background

Drifting-spore canvas (original pixel-organic language,
SolarPunk-tinted): density follows 24h activity, amber
flicker while approvals wait, drift tempo rises slightly
with online nodes (capped). Decorative only, `aria-hidden`,
killed entirely by `prefers-reduced-motion`. Motion never
claims specific events happened.

## Labels

Mesh delegation: REAL queue mechanics, TEST-safe dry runs,
no SIMULATED execution claims; printer transport stays
UNAVAILABLE; fab execution stays SIMULATED; WEB_PUSH stays
UNAVAILABLE; hardware claims stay node-reported until a
human links them. Background motion is ambient, not data.

## Limits (honest)

- Delegation queues; it cannot make a stale/offline node
  claim (409, nothing queued, nothing drifts).
- VERIFIED hardware needs a human link store that does not
  exist yet (printer twins are the pattern to follow).
- No finance/energy entity stores → no symbiosis pairs for
  them yet.
- Untargeted dispatch remains `POST /api/v1/tasks`
  (`/mesh/delegate` requires an explicit target).
