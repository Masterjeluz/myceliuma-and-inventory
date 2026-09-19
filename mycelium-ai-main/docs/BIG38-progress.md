# BIG #38 — Living Automation: progress

_Goal: observe → research → propose → wait-for-YES → act-inside-approved-plan → observe → verify → record. Reuse everything; no second engines._

- [x] Repository + architecture audit (missions/executor/loop/decisions/recovery/knowledge/research/camera/3d/conversations/nodes/notify/packet/worldgraph/guide/mobile/morning)
- [x] Implementation plan (this file): `automation.py` runs/steps/bounds/resume + step executors on existing functions + API/UI/surface wiring
- [x] `automation.py`: run/step records, closed safe-step allow-list, drive loop, approval-resume with revalidation, bounds, templates, overnight eligibility
- [x] `events.py`: additive `automation.*` bus types
- [x] `main.py`: automation API + web routes, /automation pages, mission-detail link, morning section, packet section
- [x] `living_state.py`: automation counts (reasons only, no priority change)
- [x] `guide.py`: waiting/blocked/failed automation items
- [x] `mobile.py`: automation quests in progress panel
- [x] `ui.py`: subtle symbiosis/craft automation styling (reduced-motion safe)
- [x] `reports.py`: automation morning section (allow-listed)
- [x] `context_packet.py`: automation sections (v1 + v2 + markdown)
- [x] notifier: existing START/PROGRESS/WAITING/DONE/FAILED used for the BIG run
- [x] `tests/test_big38_automation.py`: engine, bounds, resume, gates, security (20 tests green)
- [x] `scripts/b38_smoke.py`: full chain on tmp DBs (17/17 OK)
- [ ] screenshots `docs/r38-shots/` + visual review
- [ ] docs: `living-automation.md`, `automation-security.md`, BIG38 report, NEXT-AI-CONTEXT, ROADMAP-V2, README touch-up
- [ ] full regression + INVENTory suite
- [ ] ONE commit `BIG #38 - build living automation`, push, verify remote HEAD

## Safety invariants (must hold at every step)

- Closed step-kind allow-list; default-deny anything else.
- No approval fabrication: resume re-reads live store state.
- No stale approvals: fingerprint/content recheck where the underlying flow has one; otherwise status re-read.
- No background threads: drive/resume are explicit calls only.
- Bounds on every run; fail-closed with exact reasons.
- Health content never enters candidates (reuse candidate_from_finding).
- Secrets never in payloads/packets (reuse redaction + nodemesh hints).
