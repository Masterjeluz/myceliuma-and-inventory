# Mycelium V2 Roadmap — BIG #32 → BIG #40 (directional)

Status after BIG #32: knowledge lifecycle (candidates → memory),
Linux `research.fetch_url` executor, capability routing, graph
truth/source/kind/recency filters + memory/candidate/
conversation overlays, packet knowledge sections, mobile
remember/queue/missed, writes inbox, file ingest, overnight queue.

Principles for every step: reuse stores, explicit promotion,
provenance always, honest REAL/TEST/SIMULATED/UNAVAILABLE/FUTURE,
no background threads, no shell/RCE, health isolated. Never
implement a future stage prematurely because it is listed here.

## BIG #33 — Research Network

Multiple Linux nodes without architecture changes: reviewed
`research.extract` executor (deterministic, coordinator-owned
rules), per-node capability matrix UI, queue fan-out across
nodes, dossier synthesis over mixed local + node sources.
Needs: on-node extraction review + completion-hook extension.

## BIG #34 — Camera Ecosystem

Richer file/media workflows on the proven ingest path:
multi-file ingest sessions, observation → VLM advice → candidate
in one guided flow, camera detail timelines. Insta360 direct
transport only when a verified adapter exists (requirements are
documented on the adapter); until then UNAVAILABLE stays.

## BIG #35 — 3D Workshop

Models ↔ projects ↔ materials ↔ fabrication as visible
relations: file/model entity pages, material notes via
candidates, fabrication proposal from a linked model, verify
loop with camera observations. No printer transport claims.

## BIG #36 — Mobile Mycelium

Phone as primary input surface: remember/queue/missed (done in
#32) plus approval triage, packet handoff copy, notification
deep-links per node recipient, camera-inbox guidance from the
phone. No native app, no fake push.

## BIG #37 — Conversation Intelligence

External-AI refinery: repeated-theme detection across imports
(compare exists), decision/promise tracking with reminders,
contradiction surfacing into candidates, import → research
question proposals. Analysis stays OBSERVATION/CANDIDATE.

## BIG #38 — Living Automation

Observe → research → propose → act → observe loops inside
approved plans only: mission templates that chain research
queue + candidates + writes with human gates at every
consequential step. No new autonomy levels, no gate removal.

## BIG #39 — Presence

Notifications, mornings, overnight: per-recipient in-app
delivery, morning "why open Mycelium today" answer, overnight
digest of queue + discoveries + connections. Web push only with
a real transport; until then explicit UNAVAILABLE.

## BIG #40 — Mycelium V2

The coherent autonomous local-first ecosystem: everything above
working together — conversation → idea → research → node →
observation → candidate → memory → relation → project →
fabrication → verification → morning — with provenance at every
link and Jelles approving everything consequential.
