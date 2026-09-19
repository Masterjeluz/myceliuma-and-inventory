# Mycelium V2 Roadmap — BIG #37 → BIG #41 (directional)

Status after BIG #39: hardware reality layer — nodes report
read-only telemetry/hardware/compute/energy on heartbeat; the
coordinator validates fail-closed, derives
ONLINE/DEGRADED/STALE/OFFLINE/UNKNOWN health, routes by
connected hardware / available compute / telemetry freshness,
guides by what is really online, and shows per-node hardware
detail on mobile and in the world graph. No new execution
power, no gate removal. 1325 Mycelium tests green; INVENTory
untouched (179 + 1 pre-existing). See
`docs/BIG39-final-report.md`.

Principles for every step: reuse stores, explicit promotion,
provenance always, honest REAL/TEST/SIMULATED/UNAVAILABLE/FUTURE,
no background threads, no shell/RCE, health isolated. Never
implement a future stage prematurely because it is listed here.

## BIG #33 — Living World (DONE 2026-09-18)

Shipped: symbiosis (PROPOSED/SUPPORTED/VERIFIED), craft
tree (12 real-data stages + gaps), guide (WHAT/WHY/NEXT),
quest presentation (same gates), living shell
(reduced-motion safe), mobile input surface, node-mesh
delegation contracts, dev notify utility. Research-network
items (reviewed `research.extract` executor) remain future
work (see BIG33 report §12).

## BIG #34 — Camera Ecosystem (DONE 2026-09-18)

Shipped: sessions, VLM honesty, candidates, matches, link
proposals, timeline, Camera Lab + guide, mobile flow,
notifications. Insta360 live transport stays UNAVAILABLE
until a verified adapter exists (file ingest is REAL).

## BIG #35 — 3D Workshop (DONE 2026-09-18)

Shipped: registries, inspection, materials, links, fab-job
machine, camera verification, presence, packet, progress,
workbench. Real printer transport stays UNAVAILABLE;
SIMULATED execution never becomes REAL.

## BIG #36 — Mobile Mycelium (DONE 2026-09-18)

Shipped: command-surface home, triage cards, deeplinks,
camera/packet/guide/craft/symbiosis/nodes/progress panels,
notifier lifecycle. WEB_PUSH stays UNAVAILABLE; DEFER is an
honest non-action.

## BIG #37 — Conversation Intelligence (DONE 2026-09-19)

Shipped: deterministic themes/decisions/promises/
contradictions/missed/research/links/symbiosis, fingerprint
dedupe, REVISIT, timeline, packet section, graph overlay,
archive UI, guide/mobile/notifications. No LLM involved;
analysis stays OBSERVATION/CANDIDATE.

## BIG #38 — Living Automation (DONE 2026-09-19)

Shipped: automation engine (`automation.py`) with runs,
bounded steps, closed safe-step allow-list, gates, resume
with live re-check, bounds, templates, overnight eligibility.
API + web routes (`/automation`, `/automation/{run_id}`).
Surfaces: guide, mobile, morning report, context packet,
living state. Notifications reuse existing kinds. Security:
default-deny, live gate re-check, secret scan, health
isolation, capability allow-list, no shell surface, prompt
injection contained. 20 tests + 17 smoke checks green.

## BIG #39 — Hardware Reality Layer (DONE 2026-09-19)

Shipped: telemetry/hardware/compute/energy heartbeat fields
with closed-set fail-closed validation, derived node health,
telemetry-aware routing gates + preferences, world-graph
hardware/compute overlays (`node-reported`,
`human_verified=False`), mobile hardware view, hardware-aware
guide, additive node bus/notification types, read-only
node-client collectors. 74 tests + 25 smoke checks green.

## BIG #40 — Presence (NEXT)

Per-recipient in-app notification delivery, morning "why open
Mycelium today" answer, overnight digest of queue +
discoveries + connections — now feasible on real node state
(BIG #39 health/hardware/compute). Web push only with a real
transport; until then explicit UNAVAILABLE.

## BIG #41 — Mycelium V2 (directional)

The coherent autonomous local-first ecosystem: everything above
working together — conversation → idea → research → node →
observation → candidate → memory → relation → project →
fabrication → verification → morning — with provenance at every
link and Jelles approving everything consequential.