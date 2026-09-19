# Mycelium V2 Roadmap — BIG #37 → BIG #44 (directional)

Status after BIG #41: Mycelium V2 foundation — the BIG #1–40
systems working as one ecosystem: targeted mesh delegation
through the task queue (pull-only claims, rollback on
failure), routing verdicts + workload explanations, live
hardware reality with trust levels, ecosystem overview (8
answers), craft chain states, wider symbiosis, guide
unlocks, node-tempo background. No rebuilds, no new
authority, no gate removal. 1380 Mycelium tests green;
INVENTory untouched (179 + 1 pre-existing). See
`docs/BIG41-final-report.md`.

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

## BIG #40 — Presence Ecosystem (DONE 2026-09-19)

Shipped: attention engine (`presence.py`) with 12 live
collectors, deterministic priority + reasons, 5 bands,
SEEN/DEFERRED triage store, RESOLVED/EXPIRED memory,
progression foundation, read-only overnight digest,
deduplicated IN_APP fan-out. Surfaces: `/presence` page +
API, mobile bands + greeting, topbar counts, offline card
dimming, guide AFTERWARDS, 7 morning sections. 31 tests +
49 smoke checks green.

## BIG #41 — Mycelium V2 Foundation (DONE 2026-09-19)

Shipped: mesh preview/delegate (closed contracts, pinned
targets, pull-only claims, rollback, audit event), Routing
2.0 (verdicts, idle preference, explainer), live hardware
reality (`current_task`, `/reality`, trust levels),
ecosystem overview + world strip, craft states, symbiosis
prefixes + closed predicates, guide unlocks, node-tempo
background, notifier blocked/checklist/waiting guidance.
24 tests + 54 smoke checks green.

## BIG #42 — Ecosystem Hardening + First V2 Workflows (DONE 2026-09-20)

Shipped: human hardware-link store (PROPOSED→VERIFIED operator-
only, revoke sticks, reality overlay, no self-verify),
finance/energy stores (explicit records, UNKNOWN stays unknown,
finance amounts project-scoped), symbiosis map completed
(fin_/enr_/hv_/qst_ + funds/funded_by/powers/powered_by/
allocated_to, still closed), two V2 mission templates chaining
mesh delegation into craft chains, quest trails with live
done/total + hardware-aware readiness, bounded mesh workflows
(max 6 pinned steps, preview dry-runs), guide/world/mobile/
morning/packet integration (morning HARDWARE/QUESTS/ENERGY/
PROJECTS/FINANCE only when real data exists; no packet-v3).
22 tests + 49 smoke checks green. See
`docs/BIG42-final-report.md`.

## BIG #43 — Game Layer on Hardened Ground (DONE 2026-09-20)

Shipped: quest campaigns (defs + live counts/current/next/
evidence, fake quests refuse, deleted quests mark MISSING),
read-only game-state view (`GET /api/v1/game/state`, 10
sections, POST 405) + `/game` page, symbiosis progression
display (strong/growing/seedling, no silent promotion),
craft game framing, living background with 5 real-state
signals (research/discovery/verified/fab/offline, still
reduced-motion safe), solarpunk-workshop accents, guide
companion cards (BLOCKED BY/UNLOCKS/EVIDENCE), mobile
campaign panel, morning CURRENT CAMPAIGN + game headers,
worldgraph verified-hardware glow. 15 tests + 47 smoke
checks green. See `docs/BIG43-final-report.md`.

## BIG #44 — Living Solarpunk World (DONE 2026-09-20)

Shipped: /world as primary experience (HUD, world objects,
campaign progression, symbiosis network, craft world,
energy, attention panels — all best-effort, empty means
absent), original solarpunk visual language (pixel-step
HUD, kind-accented objects, network/energy styling),
background gains solar + needs signals (still one loop,
reduced-motion safe), graph verified-hardware glow,
guide node-dimm evidence (heartbeat/task/restore path),
mobile world panel sharing desktop vocabulary. 13 tests +
41 smoke checks green. See `docs/BIG44-final-report.md`.

## BIG #45 — (NEXT, not started)

Nothing designed yet — BIG #44 stops here.