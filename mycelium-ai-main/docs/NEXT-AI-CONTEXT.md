# NEXT-AI-CONTEXT — continue Mycelium development here

Date: 2026-09-20. HEAD: `BIG #42 - ecosystem hardening + first V2 workflows`
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
agent is the only hands (pull-only, outbound). V2
(`docs/v2-ecosystem.md`, BIG #41) unifies BIG #1–40 systems;
BIG #42 hardens it: human hardware links unlock VERIFIED
(operator key only, revoke sticks, selfie-verification
impossible), finance/energy stores make money and power
first-class entities (UNKNOWN stays unknown, finance amounts
scoped to project packets), quest trails derive done/total
from live records with hardware-aware readiness, bounded mesh
workflows (max 6 pinned delegations) chain research/camera/
compute across nodes through the existing task queue. Provenance
always; health scoped; no shell/RCE; no background threads
(explicit triggers only). Tests: `pytest -v` per project with
tmp DB env vars (`MYCELIUM_DATABASE_PATH`,
`MYCELIUM_CHAT_DATABASE_PATH` before TestClient;
`MYCELIUM_FABRICATION_DIR` for fab tests; `MYCELIUM_OPERATOR_KEY`
for hardware verify tests). Testing discipline: targeted tests
during dev, module tests for changed areas, smoke for the BIG,
FULL Mycelium suite ONCE + FULL INVENTory suite ONCE near the
end, bounded batches (single run exceeds 10-min timeout;
camera device enumeration may log access-violation noise on
Windows — pre-existing, unrelated). Counts: 1354 passed across
4 bounded batches (107 files) + missions/loop/routing/templates
green in the touched-module run — every file green at least
once, 22 new in test_big42_ecosystem.py; INVENTory 179 + 1
pre-existing byte-size failure (do not touch that test).

## What BIG #42 added (where)

- `hardware_links.py` (new) — PROPOSED→VERIFIED→REVOKED store,
  operator-gated verify/revoke, audit events; `main.py` —
  `/api/v1/hardware/links*` + `/hardware` page + VERIFIED
  overlay in `/nodes/{id}/reality`
- `finance.py` (new) — income/expense/budget, DRAFT/CONFIRMED/
  ARCHIVED, NULL amounts; `main.py` — `/api/v1/finance/*` +
  `/finance` page + morning FINANCE (only when data exists)
- `energy.py` (new) — solar/battery/grid/machine/other ×
  production/consumption/storage/state, NULL values; `main.py`
  — `/api/v1/energy/*` + `/energy` page + morning ENERGY
- `quests.py` (new) — quest defs + live derivation + hardware
  readiness; `main.py` — `/api/v1/quests*` + `/quests` page +
  morning QUESTS
- `main.py` — `/api/v1/workflows/preview|dispatch` (bounded
  multi-node delegation, coordinator authoritative)
- `mission_templates.py` — `idea_to_verification` (9 steps),
  `project_finance_energy` (5 steps), existing kinds only
- `symbiosis.py` — `fin_/enr_/hv_/qst_` prefixes + funds/
  funded_by/powers/powered_by/allocated_to (closed)
- `guide.py` — hardware/finance/energy/quest kinds + WHAT/WHY/
  NEXT ecosystem items; `presence.py` — hardware_unverified/
  quest_blocked/finance_pending/energy_unknown types +
  `_collect_ecosystem`; `reports.py` — hardware/quests/energy/
  finance morning keys (additive)
- `mobile.py` — quests/hardware/finance/energy/mesh_receipts
  panels; `ecosystem.py` — hardware/finance/energy/quests
  overview sections + hardware_verified per node;
  `context_packet.py` — packet-v2 `ecosystem` block (finance
  amounts project-scoped); world strip quest/trust/money/
  energy line + nav links
- `events.py` — hardware.linked/verified/revoked,
  finance.recorded, energy.recorded, quest.created/updated,
  workflow.dispatched (audit only)
- Tests: `tests/test_big42_ecosystem.py` (22).
- Scripts: `scripts/b42_smoke.py` (49 checks, fresh tmp DBs),
  `scripts/b42_shots.py` + `scripts/b42_screenshots.py`.
- Docs: `docs/hardware-verification.md`,
  `docs/finance-ecosystem.md`, `docs/energy-ecosystem.md`,
  `docs/mission-templates.md`, `docs/quest-trails.md`,
  `docs/BIG42-final-report.md`.
- Lessons: inline `[{...} for ...]` + slice needs TWO closing
  brackets (`records[:n]]`); report_morning is sync — no async
  inventory reads there (derive projects from finance/energy
  refs); mobile dashboard SyntaxError surfaced only at request
  time (import mobile in tests!); template-count pins need
  updating when the BIG explicitly adds templates (safety
  iterator tests cover the new ones automatically).

## Docs to read first

`docs/ARCHITECTURE_STATUS.md` (truth),
`docs/v2-ecosystem.md` (V2 contracts), `docs/ROADMAP.md` +
`docs/ROADMAP-V2.md` (BIG #43), `docs/hardware-verification.md`,
`docs/finance-ecosystem.md`, `docs/energy-ecosystem.md`,
`docs/mission-templates.md`, `docs/quest-trails.md`,
`docs/presence-ecosystem.md`, `docs/hardware-reality-layer.md`,
`docs/context-packets.md`, `docs/mobile-mycelium.md`,
`docs/BIG42-final-report.md` (§21 = commit/push record).

## Next BIG (from BIG42 report §23 / ROADMAP-V2)

BIG #43: game layer on the hardened ecosystem — quests become
campaigns, symbiosis becomes progression, presence becomes
stakes. Keep every new power behind the existing gates.
