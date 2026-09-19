# Mycelium V2 Roadmap — BIG #37 → BIG #40 (directional)

Status after BIG #38: living automation — observe → research →
propose → wait-for-YES → act inside approved plan → observe →
verify → record. Mission templates chain research queue +
candidates + writes with human gates at every consequential
step. No new autonomy levels, no gate removal. 1251 Mycelium
tests green; INVENTory untouched (179 + 1 pre-existing). See
`docs/BIG38-final-report.md`.

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

## BIG #39 — Presence

Per-recipient in-app notification delivery, morning "why open
Mycelium today" answer, overnight digest of queue +
discoveries + connections. Web push only with a real transport;
until then explicit UNAVAILABLE.

## BIG #40 — Mycelium V2

The coherent autonomous local-first ecosystem: everything above
working together — conversation → idea → research → node →
observation → candidate → memory → relation → project →
fabrication → verification → morning — with provenance at every
link and Jelles approving everything consequential.