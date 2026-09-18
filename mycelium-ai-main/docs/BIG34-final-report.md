# BIG #34 — Camera Ecosystem: final report

## 1. Wat gebouwd is

`coordinator/app/camera_ecosystem.py` (new, ~700 lines) plus
wiring in `main.py` (9 API + 5 web routes), `guide.py`
(camera items), `symbiosis.py` (camera ID prefixes),
camera detail + Camera Lab + mobile UI:

- **Multi-file ingest sessions**: `POST
  /api/v1/camera-sessions` + `.../{id}/run`, `cing_…` ids,
  ≤8 files, per-file states
  (queued/observed/duplicate/refused), sha256 dedupe across
  sessions, additive `camera_ingest_sessions` table.
- **VLM layer**: `POST /api/v1/observations/{id}/describe`
  — REAL Ollama analysis when the loopback backend answers,
  extractive fallback (`vlm_state: UNAVAILABLE`, empty
  labels, `model: ""`) otherwise. Stored distinguishably.
- **Candidates**: `POST
  /api/v1/observations/{id}/propose-candidates` — one
  idempotent candidate per REAL label; fallback yields none;
  no auto-promotion.
- **Matching + links**: `GET /api/v1/camera-match`
  (POSSIBLE MATCH evidence, bounded browse) and `POST
  /api/v1/camera-suggest-link` (closed predicates) → connection
  candidate → PROPOSED symbiosis; YES/NO/REVIEW via knowledge.
- **Timeline**: `GET /api/v1/camera-timeline` from the shared
  bus + notifications (no second event system).
- **UI**: Camera Lab (`/cameras` + 8-step Insta360 guide),
  detail page (session form, session list, per-observation
  Describe/Propose/Review buttons, suggest-link form,
  timeline), mobile camera flow panel.
- Tests: `tests/test_big34_camera_ecosystem.py` (13).
- Scripts: `scripts/b34_smoke.py` (full-chain smoke).
- Screenshots: `docs/r34-shots/` (4 PNGs).

## 2. Wat hergebruikt is

cameras.py (devices, observations, retention), vision_ingest
(FileIngestAdapter, media_facts, inbox, availability),
vision_provider (Ollama loopback, VisionUnavailable),
vision_flow (analysis store, inert proposals, verification),
knowledge (candidates, support/promote/reject, fencing),
symbiosis PROPOSED, craft overlays, guide, worldgraph,
events (`observation.created`, `candidate.observed`,
`relation.proposed` — no new types), notify_center IN_APP
types, mobile, morning/activity. No gate removed, no
provenance relaxed, no INVENTory change.

## 3. Camera flow

FILE → SESSION (`cing_…`) → OBSERVATION (`obs-…`) → VLM
REAL / fallback → CANDIDATE (`cand_…`, per label,
idempotent) → POSSIBLE MATCH → LINK PROPOSAL (YES) →
SYMBIOSIS → CRAFT → GUIDE → MEMORY (if allowed) →
MORNING / ACTIVITY / WORLD. Verified end-to-end by smoke.

## 4. Insta360 status

REAL: registratie, file ingest, metadata, sessions,
analyse van aangeleverde bestanden. UNAVAILABLE: directe
live transport, camera-control, proprietary protocol —
verified adapter vereist. REGISTERED ≠ CONNECTED, nooit
fake LIVE. Camera Guide op `/cameras` toont het 8-stappen
file-pad.

## 5. VLM status

REAL wanneer Ollama-loopback antwoordt (gestructureerde
labels + confidences + description + uncertainty, stored).
UNAVAILABLE fallback wanneer niet (geen labels, geen
confidences, expliciete uncertainty). Smoke bewees beide
(fallback live; REAL via MockTransport-test). VLM-output is
OBSERVATION, nooit FACT.

## 6. Candidates

Eén per REAL label, evidence aan observatie gebonden,
sensor/ai-provenance, `observation`-type, state
`observation`. Idempotent per (observation, label).
Mens beslist via support/promote/reject.

## 7. Symbiosis

Link-voorstellen zijn `connection`-candidates met
`entity_refs=[observation, entity]` → zichtbaar als
PROPOSED in `/symbiosis` (getest). Geen auto-merge.

## 8. Craft integration

Observaties stromen via bestaande overlays de wereldgrafiek
in; `/craft` toont ze (aanwezig ✓ / ontbrekend ? via gaps).
Geen parallel systeem.

## 9. Mobile

Camera-paneel: inbox-wacht → PROCESSING → RESULT
(kandidaten, YES/REVIEW) of lege-camera-uitleg. Bestaande
flow, contractstrings behouden.

## 10. Guide

Twee camera-items: inbox-bestanden en onbeschreven
observaties (met diepe link naar de camera). Read-only,
bounded.

## 11. Activity/world

Session-observaties als `observation.created` events,
candidates als `candidate.observed`, links als
`relation.proposed` — zichtbaar in `/activity`, timeline en
morning. Geen tweede eventsysteem.

## 12. Notifications

IN_APP (`new_observation`, `camera_ready`,
`candidate_waiting`, `new_connection`) naar geregistreerde
nodes (bounded, best-effort). WEB_PUSH UNAVAILABLE.

## 13. Security

Getest: hostile filenames, traversal (`../`, absoluut,
URL, backslash), lege/oversized-aanvragen (>8, dupes),
unsupported MIME (`.jpg` refuse), fake entity IDs, foute
predicates, onbekende devices/sessions/observations,
replay-idempotentie. Geen shell/eval/subprocess/URLs/
credentials; file bytes nooit geïnterpreteerd; VLM leest
alleen benoemde inbox-bestanden; model-provenance genegeerd.

## 14. Tests

Nieuw: 13 (`test_big34_camera_ecosystem.py`), alle groen.
Regressie begrensd: big30/big31/big32/big33, cameras,
vision_*, workshop_ui, missions, research_api — 179 +
87 + 92 + 13 voor/na-vergelijking zonder nieuwe failures
(volledige suite: 1173 + 13 = 1186 verzameld; batch-runs
alle groen). INVENTory: 179 + 1 pre-existing (onaangeraakt).

## 15. Smoke

`scripts/b34_smoke.py` op tmp DBs, echte HTTP: register →
session → 2 observations → fallback UNAVAILABLE → mock
REAL → 1 candidate → match → link PROPOSED → symbiosis
zichtbaar → timeline → guide → activity/world 200 →
transport UNAVAILABLE. Alles OK.

## 16. Screenshots

`docs/r34-shots/`: Camera Lab, camera-detail (sessie,
observaties, link-formulier, timeline), mobile-390,
guide — Edge headless, tmp DBs, echte records. Beoordeeld:
workflows zichtbaar, states eerlijk (REGISTERED,
UNAVAILABLE transport).

## 17. REAL/TEST/SIMULATED/UNAVAILABLE

REAL: sessies, observaties, file-ingest, fallback-labeling,
kandidaten, matches, link-voorstellen, timeline, guide,
notificaties, camera-registratie. TEST: SyntheticTestAdapter
+ MockTransport-VLM (gelabeld). SIMULATED: printers
(ongewijzigd). UNAVAILABLE: Insta360 live transport,
printer-transporten, web push, STT, VLM zonder Ollama.

## 18. Resterende gaten

Ollama niet gedetecteerd op dit netwerk (fallback bewezen;
REAL-pad via mock + bestaande provider-tests); geen native
mobile upload (inbox is het eerlijke pad); geen video/
360-still extractie (operator levert stills); reviewed
extract-executor blijft BIG35+; seed-chips tonen ruwe IDs
zonder INVENTory-namen (pre-existing).

## 19. Git commit

`BIG #34 - build camera ecosystem` (zie §21). INVENTory
onaangeraakt. Pre-existing
`Mycelium/agent/agent_ui.py`-wijziging ongemoeid, niet
meegecommit.

## 20. Wat Jelles morgen daadwerkelijk kan gebruiken

X4 registreren → still exporteren → inbox in kopiëren →
sessie draaien → VLM-beschrijving → kandidaten → YES →
link aan solar-project → terugzien in symbiose, craft,
guide, morning. Alles via `/cameras` + Camera Guide, geen
nieuwe tools nodig.

## 21. Volgende BIG

BIG #35 — 3D Workshop (modellen ↔ projecten ↔ materialen ↔
fabricatie als zichtbare relaties; verify-loop met
camera-observaties; geen printer-transportclaims).

## 22. Files changed

New: `coordinator/app/camera_ecosystem.py`,
`tests/test_big34_camera_ecosystem.py`,
`scripts/b34_smoke.py`, `docs/r34-shots/` (4 PNGs),
`docs/camera-ecosystem.md`, `docs/BIG34-final-report.md`
(this file). Extended: `coordinator/app/main.py` (9 API +
5 web routes, Camera Lab, detail, mobile),
`coordinator/app/guide.py` (camera items),
`coordinator/app/symbiosis.py` (obs_/cam_/cing_ prefixes),
`docs/camera-workflow.md`, `docs/NEXT-AI-CONTEXT.md`,
`docs/ROADMAP-V2.md`.
