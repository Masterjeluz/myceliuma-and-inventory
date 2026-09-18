# Mycelium AI + INVENTory — Roadmap

Strategische roadmap na BIG #3 (september 2026). Geen microtask-lijst:
per fase staat wat af is, wat volgt, en wat bewust nog niet bestaat.
Principes uit `living-principles.md` blijven leidend: local-first,
kleinste bruikbare stap, geen cloud-afhankelijkheid voor de kern,
mens beslist.

Legenda: **DONE** werkt en is getest · **PARTIAL** werkt deels of
alleen als contract · **NEXT** eerstvolgende verticale slice ·
**FUTURE** later, nog geen ontwerpverplichting.

## PHASE A — BRAIN (DONE)

Kern van redeneren, coördineren en gecontroleerd uitvoeren.

- Core coordinator (nodes, queue, leases) — DONE (M7.4)
- INVENTory als wereldmodel (read-only bridge) — DONE (M5)
- Lokale AI via Ollama/Qwen — DONE (M8.1)
- Chat met conversaties, context en bronnen — DONE (BIG #1)
- Provider-abstractie (extern = fail-closed stub) — DONE (BIG #1)
- Approvals (exact YES, geen bypass) — DONE (M6.3/M8.4)
- CoordinatorTask / staging / promotion — DONE (M6.4/M7.1)
- Desktop-agent: contract, runtime, observe→act→observe — DONE (BIG #1)
- Standalone agent-proces met claim + revalidatie — DONE (BIG #2)
- Missies: plan, steps, executor, events, binding-bewijs — DONE (BIG #3)
- Testbasis: 515 Mycelium-tests, 178 INVENTory-tests — DONE

## PHASE B — UNDERSTANDING (DONE als BIG #4)

Zie `docs/semantic-world-model.md` en `docs/camera-architecture.md`.

- Semantische retrieval naast de substring-bridge (lokaal
  embedding-model via Ollama, lexicaal als fallback) — DONE
- Rijker wereldmodel-redeneren (hybride RRF + relatie-expansie
  als plan-context, provenance-bewust) — DONE
- Missie-sjablonen per projecttype (5 stuks, geen bypass) — DONE
- Uniforme wereldgrafiek-projectie (INVENTory + missie/agent
  overlay, geen tweede waarheid) — DONE
- Camera-foundation (abstractie, read-only detectie, observatie-
  contract, Insta360-fase 1) — DONE (start van PHASE D)
- Project-bewuste context (actief project als standaard-filter) —
  DONE (BIG #5: bounded pakketten + missie-context)
- `docs/first-node-blueprint.md` herstellen (README linkt erheen,
  bestand ontbreekt) — DONE (BIG #5)
- Testbasis: 629 Mycelium-tests — DONE

## PHASE C — CONTROLLED WRITES (DONE als BIG #5)

Zie `docs/controlled-writes-and-verification.md`.

- INVENTory-schrijfvoorstellen (operator-keurt-goed, provenance
  `ai-generated` → nooit automatisch `human_verified`) — DONE
  (object/project/idea + relaties; deletes en M3+-typen weigeren)
- Git-voorstellen en commits via expliciete capability (push/merge
  blijven verboden) — DONE (allow-list, geen push)
- Bestands-/projectwijzigingen via missie-stappen met diff-preview — PARTIAL
  (write-stap + git-voorstel; file-inhoud schrijven volgt later)
- Verificatie-stap als eersteklas burger (resultaat ≠ verified) — DONE
- Sterkere audit-trail (wie/wat/waarom per mutatie, exporteerbaar) — PARTIAL
  (before/after + write/result/verification-events; export volgt later)

## PHASE D — VISION (PARTIAL als BIG #6)

Zie `docs/vision-architecture.md` en `docs/camera-architecture.md`.

- Camera-ingestie (lokaal, tijdelijk, retentie-begrensd zoals screenshots) — DONE
  (snapshot-ingestie met hash/size-caps; webcam/stream als contract + stub)
- VLM-adapter (lokaal eerst; extern alleen via provider-beleid) — DONE
  (Ollama loopback, `VISION_MODEL`, geen downloads, geen cloud)
- Object-identificatie → voorstel → menselijke verificatie → INVENTory — DONE
  (generieke keten via BIG #5; onzekerheid behouden, 0.99 autoriseert niets)
- Beeld-provenance (bron, tijd, model, verificatiestatus) — DONE
- Echte Windows-capture-runtime — FUTURE (stub + vereisten gedocumenteerd)
- Echte Insta360-capture (webcam-driver of file-ingest) — FUTURE
  (foundation zonder gegokte SDK; expliciet unavailable)
- Live-stream-transport naar lokale consumer — FUTURE (alleen lifecycle)

## PHASE E — CREATION / 3D (PARTIAL als BIG #7)

Zie `docs/3d-architecture.md`. Contracten + test-pipeline bestaan;
echte hardware/transporten niet.

- Object → 3D-haalbaarheid → CAD/mesh (lokaal) — DONE
  (deterministische test-kubus, STL/OBJ-validatie, printability-
  advies; geen CAD-kernel, geen downloads)
- Slicer/G-code als preview-only, nooit directe printeraansturing — DONE
  (test-slicer met never-for-printers-markering, G-code-safety-
  assessment; productie-slicer vereist reviewed runtime)
- Fysieke executie via dubbele approval (plan-YES + fysieke YES),
  simulated/unavailable adapters, cancel-grens (geen e-stop-claim) — DONE
- Menselijke goedkeuring vóór elk fysiek artefact — DONE
  (printer.execute-voorstel + fingerprint + safety + revalidatie)
- Fysieke verificatie-terugkoppeling naar INVENTory — DONE
  (telemetrie + camera, beide vereist; INVENTory-update via BIG #5)
- Echte printertransport/vendorintegratie — FUTURE
- Echte slicer-runtime — FUTURE

## PHASE F — DISTRIBUTED MYCELIUM (PARTIAL als BIG #8)

Zie `docs/distributed-architecture.md` en
`docs/first-node-blueprint.md`. Protocol + veilige foundation
bestaan; echte multi-machine-praktijk volgt.

- Node-registratie, heartbeat, freshness (60s), leases (300s,
  max 3 pogingen) — DONE (bestaand, hergebruikt)
- Token-authenticatie (lokaal, bearer, legacy-compatibel) — DONE
- Capability/model/executor-advertenties + resource/energy-hints — DONE
- Deterministische routing met uitleg — DONE
- Queue-plaatsing (assign als constraint, pull blijft) — DONE
- Claim-revalidatie + fysieke no-reroute bij lease-verval — DONE
- Desktop-agent als token-bewuste node — DONE
- Meerdere nodes in de praktijk (huis, werkplaats, onderweg) — FUTURE
- Capability-discovery en model-routing — DONE als foundation
- Workload-verdeling en offline-weerbaarheid — PARTIAL
  (leases/retry/fysieke blokkering; echte verdeling volgt)
- Energie-bewuste scheduling (metingen eerst, handmatige override
  altijd, conform architectuur-v0.1) — PARTIAL (hints als
  voorkeur, geen metingen, geen sturing)
- API-tokens vóór nodes buiten het vertrouwde LAN — DONE
  (per-node tokens; geen PKI, LAN-vertrouwen gedocumenteerd)

## PHASE G — HUMAN INTERFACE (PARTIAL als BIG #9)

Zie `docs/human-interface-architecture.md`.

- Interface-abstractie (tekst echt, voice als architectuur,
  nooit een tweede coordinator) — DONE
- STT/TTS-abstracties (lokaal-first contract, unavailable +
  test-providers, geen cloud/downloads) — DONE
- Telefoon als node (bestaande BIG #8-auth, `phone.*`-
  capabilities, pull-only, camera/mic expliciet gated) — DONE
- Eventbus + notificaties (polling, cursor-replay, geen
  broker) — DONE
- Voice-approval met binding/eenmaligheid/verval (fysiek
  nooit via voice) — DONE
- Mobiele webinterface (server-rendered, geen framework) — DONE
- Spraak (lokaal model, expliciete activering) — PARTIAL
  (contract + capture-sessies; echte STT-engine FUTURE)
- Telefoon als node/bediening — PARTIAL (foundation; geen
  native app, geen push-infra)
- Realtime status — DONE (polling + `/status`; geen sockets)
- Garmin/auto/camper-integraties — FUTURE
- Toekomstige AR-weergave van wereldmodel — FUTURE

## PHASE H — LIVING WORKSHOP (PARTIAL als BIG #10)

Zie `docs/distributed-state.md`, `docs/coordinator-failover.md`,
`docs/living-workshop.md` en `docs/mycelium-live.md`.

- Distributed state als event/change-log (geen DB-kopie,
  idempotent, expliciete conflicten, geen last-write-wins) — DONE
- Coordinator-failover (lease/epoch/fencing, deterministische
  verkiezing, quorum/degraded, geen split-brain) — DONE
- INVENTory change-feed via additieve `since`-cursor op
  `/api/v1/events` (read-only HTTP, geen dumps) — DONE
- Uniforme wereldgrafiek met node/printer-overlays — DONE
- Interactieve workshop-UI (`/workshop`, `/workshop/graph`,
  `/workshop/3d`) — DONE
- 3D-transform als voorstel (preview + lokaal werkbestand,
  INVENTory-registratie via BIG #5-flow) — DONE
- Live-sessies (capability-scoped, bounded context,
  `git.commit ≠ git.push`) — DONE
- Watcher-findings, morning report, domein-extensiepunten
  (health/skills/ingestion als placeholders) — DONE
- Definitieve Mycelium-workspace (alles in één beeld) — PARTIAL
  (workshop-pagina's als foundation; samenvoeging volgt)
- Lange-termijn-geheugen en geschiedenis/provenance-blik — FUTURE
- Fysieke-wereld-koppeling (actuatoren pas na Fases C–E) — FUTURE

## PHASE I — LIVING MYCELIUM (PARTIAL als BIG #11-15)

Zie `docs/memory.md`, `docs/watcher.md`,
`docs/morning-reports.md`, `docs/health.md`,
`docs/nutrition.md`, `docs/garmin.md`,
`docs/research-ingestion.md`, `docs/skills.md`,
`docs/advanced-workshop.md`, `docs/cad.md`,
`docs/fabrication.md`, `docs/robots.md`,
`docs/drones.md`, `docs/digital-twin.md` en
`docs/mycelium-live.md`.

- Memory-laag (10 typen, truth-tiers, retrieval,
  consolidatie-voorstellen) — DONE
- Watcher bruikbaar (15 finding-kinds, explainable,
  findings-only) — DONE
- Morning reports (15 secties, deterministisch,
  mobile-first `/morning`) — DONE
- Health-tracking + transparante index (geen diagnose-
  engine) — DONE
- Nutrition (maaltijden, vegan-bewijs, coverage) — DONE
- Garmin-adapter (interface + mock + import; live
  UNAVAILABLE) — DONE als MOCK
- Research/ingestie (pipeline, claims-met-bron,
  Instagram manual-export-only) — DONE
- Skills (candidates, evidence-progressie, discovery) — DONE
- Advanced 3D (mirror/merge/extend/orient, prompt-edits
  als voorstel) + CAD-foundation (procedural bouwt;
  externe adapters UNAVAILABLE) — DONE/PARTIAL
- Fabrication-orkestratie (filament, selectie, plan;
  fysieke start blijft gated) — PARTIAL
- Robots/drones/familiars/digital twin (modellen +
  gates; executie HARDWARE_REQUIRED) — PARTIAL
- Live als universele interface (8 nieuwe secties,
  health apart gescoped) — PARTIAL
- Jobs-foundation (bounded, observable, idempotent,
  geen achtergrond-threads) — DONE
- Living-Workshop-UI (Home/Morning/Memory/Health/
  Skills/Research/Devices/Watcher-pagina's) — DONE
- SMOKE11_15: 41/41 — DONE
- Echte multi-machine-praktijk, echte STT/slicer/
  printertransports, live Garmin/Instagram, CAD-
  runtimes, fysieke robot/drone-executie — FUTURE

## PHASE J — STABILIZATION (DONE als BIG #16)

Zie `docs/stabilization.md`. Geen nieuwe productfeatures;
concurrency, fencing, approvals, auth en retentie
gehard als voorwaarde voor elke echte LIVE-integratie.

- SQLite WAL + busy_timeout, atomische claim/campaign-
  writes, concurrency-tests — DONE
- Globale fencing (sync/claim/complete/campaign) + atomaire
  campaign (één houder per epoch) — DONE
- Retentie (logs) + indexen (hot paths) — DONE
- Robot/drone via WriteProposal (exact YES, fingerprint,
  target-binding) + bewijs-verificatie — DONE
- Node-auth (token-plicht nieuw, legacy bevroren, rotatie,
  operator-gated enable/disable) — DONE
- Health-isolatie, provenance-defaults, save-invarianten,
  payload-unificatie, paginatie-conventie — DONE
- Mock-badges, voice-beleid (optie A), testhygiëne,
  perf-sanity — DONE
- Testbasis: 920 Mycelium-tests — DONE

## PHASE K — INTEGRATION PLANE (DONE als BIG #17,
e2e bewezen als BIG #18)

Zie `docs/n8n-integration.md`. n8n als externe
automation-laag rondom Mycelium — nooit de coordinator.

- Integration contract (envelop, validatie, provenance) — DONE
- Eigen integration-auth (bearer keys, hash-only,
  capabilities, operator-uitgifte) — DONE
- Idempotente ingestie (UNIQUE-ledger, duplicate/conflict,
  race-convergentie) — DONE
- Webhook-boundary (observation-only, bounded, getest) — DONE
- Outbox poll-model (allow-listed labels, geen callbacks,
  geen URL-forwarding) — DONE
- Scheduler-trigger (alleen bekende jobs) — DONE
- Secret boundary (credentials blijven in n8n) — DONE
- Garmin readiness (UNAVAILABLE + requirements, mock
  behouden) — DONE
- Testbasis: 935 Mycelium-tests — DONE
- Echte lokale e2e (23 checks over live HTTP: trigger,
  outbox, idempotency, provenance, mock-Garmin, auth,
  failure-leg) + committed workflow-artifacts — DONE
  als BIG #18
- Echte n8n-workflows, echte Garmin-OAuth, live externe
  integraties — FUTURE (pas met officiële toegang)

## PHASE L — LIVING WORKSHOP UI (DONE als BIG #19)

Zie `docs/living-workshop-ui.md`. Van technisch
dashboard naar levende digitale werkplaats — zelfde
API's, nieuwe ervaring.

- Design system (`ui.py`: tokens, shell, componenten) — DONE
- Living home (grafiek centraal, missies/taken/nodes/
  notificaties eromheen, chat eronder) — DONE
- World graph explorer (pan/zoom/select/focus/expand/
  filters, toetsenbord, touch) — DONE
- Organische graftaal + node-states + truth/state-chips — DONE
- Chat met entity-referenties naar de wereld — DONE
- Missies als procespad (approved ≠ executed) — DONE
- Project-ecosystemen, entity-details, activity stream — DONE
- Physical/fabrication met LIVE/SIMULATED/TEST-states — DONE
- Bewuste mobile-volgorde, reduced-motion, focus, landmarks — DONE
- Testbasis: 944 Mycelium-tests — DONE

## PHASE M — AUTONOMOUS MISSION LOOP (DONE als BIG #21)

Zie `docs/autonomous-mission-loop.md`. Eén veilige
continue runner over de bestaande executor: chat →
missie → tick → observeer → evalueer → vervolg →
verifieer → rond af. Stopt bij elke gate (plan-,
desktop-, proposal-, write- en physical-approvals),
vindt nooit stappen uit, voert nooit fysiek uit
zonder bestaande approvals. Terminale missies
schrijven één episodic memory (observed, nooit fact).
Testbasis: 951 Mycelium-tests + 12-checks live smoke.

## PHASE N — DESKTOP AGENT HANDS (DONE als BIG #22)

Zie `docs/desktop-hands.md`. De desktop-agent als
bruikbare handen: claim → revalidate → observe → act
→ observe → report met dispatch-leases (300s),
attempt-bounds (max 3) en lazy expiry; mission loop
gaat na desktop-resultaat automatisch verder. Echte
Windows-backend (ctypes, geen deps) bewezen over live
localhost HTTP met zero desktop disturbance
(screenshot-reads alleen). Fysiek onmogelijk via deze
keten; geen shell/RCE/cloud. Testbasis: 961
Mycelium-tests + 9-checks live hands-smoke.

## PHASE O — MYCELIUM V1 (DONE als BIG #23–#28)

Zie `docs/mycelium-v1.md`. Eerste dagelijks bruikbare Mycelium:
Command Center (/world) met deterministische NL-router
(`POST /api/v1/command`) naar status-antwoorden, veilige
template-missies en missie-besturing; expliciete
beslisstaten (`decisions.py`: CONTINUE/RETRY/REPLAN/
WAITING_FOR_HUMAN/WAITING_FOR_AGENT/BLOCKED/FAILED/
COMPLETED/CANCELLED, `POST /missions/{id}/decide` leest mee);
persistente recovery (boot-scan rapporteert, hervat alleen
expliciet read-only, nooit stale approvals); agenda-importer
(.ics preview → bevestig, UID-dedup, alleen-lezen context);
bootstrap-onderzoekscampagne (9 domeinen, idempotent,
wacht eerlijk op echte research-transport);
ochtendrapport met waiting + agenda; eerlijke
fysieke matrix (`GET /physical/status`, nooit fake LIVE);
Windows-startup via Task Scheduler zonder admin
(`docs/startup.md`, `scripts/`).

## PHASE P — RESEARCH ENGINE (DONE als BIG #29)

Zie `docs/research-engine.md`. Eerste echte zintuig:
vraag → queries → search → fetch → extract → claims →
tegenstrijdigheden → Ollama-synthesis → dossier → research
memory → morning/UI/chat. SSRF-geharde GET-only transport
(httpx, timeouts, caps, allowlists) met providers
wikipedia (REAL-poging) / test (TEST-fixtures) /
unavailable (eerlijk wachten) + expliciete `source_urls`
(REAL direct fetch). Deterministische claim-extractie en
contradictie-groepen (onopgelost, nooit arbitrage),
prompt-injectie als gelabelde data, health-isolatie,
`research`-missiestap + template, `/research`-werkplaats +
dossierpagina + graph-overlay, ochtend-Research-sectie.
Omgevingswaarheid: direct fetch REAL (live bewezen),
Wikipedia vanaf dit netwerk UNAVAILABLE (edge-403),
Ollama momenteel DOWN (extractive fallback actief).

## PHASE Q — LIVING ECOSYSTEM (DONE als BIG #30)

Zie `docs/living-ecosystem.md`, `docs/conversation-bridge.md`,
`docs/mobile-node-flow.md`, `docs/linux-node-setup.md`,
`docs/camera-workflow.md`, `docs/3d-workflow.md`. Van losse
pagina's naar een zichtbaar ecosysteem — zelfde stores, nieuwe
verbindingen, geen fake functionaliteit.

- Living Workshop cockpit (`/world`): ecosysteem-overzicht, echte
  graph + context rail, "do something with this" naar bestaande
  endpoints — DONE
- Conversation bridge: import (pasted/TXT/Markdown/JSON/safe HTML)
  als `conv_...` met OBSERVATION/CANDIDATE-analyse + "what did we
  miss?" (evidence-backed), universeel context packet + continuation
  (Markdown + JSON, entity-first, health-scoped) — DONE
- Mobile als input surface (`/mobile`: INPUT/PROCESSING/NODE/RESULT,
  quick actions op bestaande routes, help) + notification center
  (IN_APP real, WEB_PUSH expliciet UNAVAILABLE) — DONE
- Linux nodes praktisch (`/nodes`-machines, starter capabilities,
  10-stappen runbook, pull-only, geen shell) — DONE
- Insta360 foundation zichtbaar (REGISTERED/CONNECTED/UNAVAILABLE,
  how-to met WHAT EXISTS/MISSING/NEEDS) — DONE
- 3D-pipeline zichtbaar (`/3d`: stages met eerlijke chips,
  procedural/test REAL, reconstructie UNAVAILABLE) — DONE
- Activity met Mycelium voice + echte links — DONE

## PHASE R — ACTIVATION (BIG #31, in uitvoering)

Zie `docs/living-ecosystem.md`, `docs/context-packets.md`,
`docs/overnight-research.md`. Van gebouwd naar levend: dezelfde
stores, zichtbare verbindingen, geen fake functionaliteit.

- Context engine (`context_engine.py`) + globale `/search` +
  command traces met last-flow op `/world` — DONE
- Packet v2 handoff-schema + Markdown/download + Copy-context —
  DONE
- Living state in elke topbar (`/api/v1/state`) — DONE
- Archaeology depth (compare, INVENTory-relevantie, discoveries,
  markdown-export) — DONE
- Camera file-ingest (REAL) + detailpagina — DONE
- Writes-inbox (propose links/objecten, exact YES) — DONE
- Node-rollen + one-command bootstrap + systemd-unit — DONE
- Overnight-modus + research queue + GOOD MORNING — DONE
- Startup start/stop/status/restart (Windows + Linux-user-unit) —
  DONE

## Expliciet niet op de kaart

Autonome ongelimiteerde computerbediening, credential-automatisering,
cloud-verplichte kern, permanente achtergrond-autonomie, wapens- of
toezicht-toepassingen. Deze komen niet "later vanzelf"; ze vereisen
een apart, expliciet besluit.
