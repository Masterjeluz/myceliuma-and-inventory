# Architecture Status (september 2026, na BIG #18)

Momentopname van wat het systeem IS. Voor flows, zie
`chat-agent-architecture.md`; voor richting, zie `ROADMAP.md`.

## Current system

- **Mycelium = brain/orchestrator.** Begrijpt, plant, vraagt
  toestemming, orkestreert. Redeneert nooit direct met hardware.
- **Coordinator = authority.** Enige partij die approvals, taken,
  leases en missies mag uitgeven of sluiten. Fail-closed bij twijfel.
- **INVENTory = world memory.** Persistent wereldmodel (SQLite WAL,
  13 tabellen). Alleen-lezen voor Mycelium via een GET-only
  loopback-bridge; geen gedeelde database, geen cross-imports.
- **Ollama / external models = advisors.** Geven tekstadvies op
  aangeleverde records. Advies is geen waarheid en start niets.
- **Desktop Agent = hands.** Enige partij die scherm/muis/toetsenbord
  aanraakt. Pull-based, outbound-only, voert uitsluitend goedgekeurde
  acties uit binnen een goedgekeurd plan.

## Begrippen (in volgorde van vertrouwen)

1. **FACT** — rij in INVENTory of lokale status (git, project).
   Bron van waarheid binnen zijn domein.
2. **OBSERVATION** — wat de agent zag (screenshot-metadata, status-
   output). Gebeurd, maar interpretatie is nog open.
3. **ADVICE** — AI-tekst op basis van context. Altijd
   `ai-generated`, nooit `human_verified`, start niets.
4. **PROPOSAL** — concreet voorstel (AdapterProposal, missie-stap,
   3D-artefact). Wacht op een mens.
5. **APPROVAL** — exact `YES` van een mens op een specifiek voorstel.
   Niet overdraagbaar, niet herbruikbaar, geen bypass.
6. **TASK** — goedgekeurde werkeenheid (CoordinatorTask, desktop-
   actie, missie-stap). Mag uitgevoerd worden zoals beschreven —
   en alleen zoals beschreven (binding-bewijs vereist).
7. **RESULT** — completed/failed/cancelled/blocked met timing, error
   en observatie-referentie. Nooit automatisch verified.
8. **VERIFICATION** — aparte, eersteklas stap (`verification.py`):
   onafhankelijke readback (inventory/graph/git) met
   passed/failed/inconclusive. Alleen passed telt als
   geverifieerd; approval is toestemming, verificatie is waarheid.
9. **WORLD MODEL UPDATE** — alleen na passed verificatie; anders
   geen FACT-promotie.

## Componentkaart (code als bron)

| Onderdeel | Locatie | Status |
|---|---|---|
| Coordinator API + workspace-UI | `coordinator/app/main.py` | DONE |
| Nodes / queue / leases | `main.py`, `database.py` | DONE |
| Capability-matching | `capability_matching.py` | DONE |
| INVENTory read-bridge | `inventory_read.py` | DONE |
| Ollama-adviseur | `ollama_advisor.py` | DONE |
| Provider-abstractie | `providers.py` | DONE (extern = stub) |
| Adaptervoorstellen | `adapters.py`, `advisor_proposals.py` | DONE |
| Approval-poort | `approval.py` | DONE |
| Proposal→task | `proposal_tasks.py` | DONE |
| Staging/promotion | `task_queue_bridge.py`, `promotion.py` | DONE |
| Executor-register | `executor_registry.py` | DONE |
| Conversaties/berichten | `conversations.py` | DONE |
| Chat + plannen (stateless) | `main.py`, `plans.py` | DONE |
| Computer-acties | `computer_actions.py` | DONE (9 typen) |
| Observaties/resultaten | `observations.py`, `agent_results.py` | DONE |
| Agent-lus (state machine) | `agent_loop.py` | DONE |
| Desktop-runtime (ctypes) | `desktop_runtime.py` | DONE |
| Missies + executor | `missions.py`, `mission_executor.py` | DONE |
| Semantische retrieval | `embeddings.py`, `semantic_store.py`, `retrieval.py` | DONE (lexicaal fallback) |
| Missie-sjablonen | `mission_templates.py` | DONE (5 stuks) |
| Camera-abstractie | `cameras.py` | DONE (contract + detectie) |
| Camera-ingestie | `vision_ingest.py` | DONE (states, snapshot, streams-lifecycle, insta360-foundation, webcam-stub) |
| Local VLM | `vision_provider.py` | DONE (Ollama loopback, test/unavailable providers) |
| Vision→proposal→verificatie | `vision_flow.py` | DONE (geen uitvoeringspad) |
| File controlled writes | `inventory_writes.py` | DONE (file create/update; object/project/idea/relatie intact) |
| Camera-missiestap | `missions.py`, `mission_executor.py` | DONE (`camera_observe`) |
| 3D-generatie + mesh-validatie | `mesh3d.py` | DONE (test-kubus, STL/OBJ, geen CAD-deps) |
| Slicer + G-code-safety | `slicer3d.py` | DONE (test-slicer, geen safe_to_execute) |
| Printer-devices + executie | `printer3d.py`, `fab_flow.py` | DONE (simulated/unavailable, fysieke YES) |
| Print-verificatie (twee helften) | `fab_flow.py`, `verification.py` | DONE (telemetrie + camera) |
| Fabricage-missiestappen | `missions.py`, `mission_executor.py` | DONE (fabricate/slice/physical_print) |
| Node-register/auth/advertenties | `nodes.py`, `database.py` | DONE (tokens, modellen, executors, resources) |
| Deterministische routing | `routing.py` | DONE (uitlegbaar, geen kwaliteitsranking) |
| Queue-plaatsing + claim-revalidatie | `main.py` (assign/route/claim/expire) | DONE (fysieke no-reroute) |
| Multi-node-simulator | `sim_nodes.py` | DONE (test-only) |
| Human-interface-adapters | `interface.py` | DONE (tekst echt, voice-architectuur) |
| STT/TTS + audio-security | `voice.py` | DONE (loopback/test/unavailable) |
| Voice-approval-safety | `voice_approval.py` | DONE (binding, geen fysiek) |
| Eventbus + notificaties | `events.py` | DONE (polling, geen broker) |
| Mobiele interface | `main.py` (`/mobile`) | DONE (server-rendered) |
| Wereldgrafiek | `worldgraph.py` | DONE (projectie) |
| Project-/git-context (read-only) | `project_context.py`, `git_context.py` | DONE |
| Controlled writes (generiek) | `controlled_writes.py` | DONE |
| INVENTory write-capability | `inventory_writes.py` | DONE (object/project/idea + relaties) |
| Verification (eersteklas) | `verification.py` | DONE (readback, geen model-mening) |
| Git-commit-capability | `git_commit.py` | DONE (allow-list, geen push) |
| Project-pakketten | `project_package.py` | DONE (bounded, geen secrets) |
| Write-stap in missies | `missions.py`, `mission_executor.py` | DONE |
| Write/verify-API | `main.py` (`/writes`, `/project/package`) | DONE |
| 3D-pijplijn | `pipeline3d.py` | PARTIAL (contracten) |
| Standalone agent | `desktop_agent/` | DONE |
| Node-client (read-only loop) | `node_client/` | DONE |
| INVENTory wereldmodel | `inventory/app/` | DONE (alleen additieve `since`-cursor op `/events`) |
| Distributed state | `diststate.py`, `sync.py` | DONE (event-log, idempotent, expliciete conflicten) |
| Failover | `failover.py` | DONE (lease/epoch/fencing, quorum/degraded) |
| Live-sessies | `live.py` | DONE (capability-scoped, bounded context) |
| Watcher + reports | `watcher.py`, `reports.py` | DONE (findings-only, deterministisch) |
| Domein-extensiepunten | `domains.py` | DONE (placeholders met requirements) |
| Workshop-UI + 3D-voorstel | `main.py` (`/workshop*`, `/fab/transform`) | DONE |
| Memory-laag | `memory.py` | DONE (10 typen, truth-tiers, tombstones) |
| Watcher | `watcher.py` | DONE (15 kinds, findings-only) |
| Reports | `reports.py` | DONE (15 secties, deterministisch) |
| Health/nutrition | `health.py`, `nutrition.py` | DONE (tracking; geen diagnose-engine) |
| Garmin | `garmin.py` | MOCK (live UNAVAILABLE, import-pipeline echt) |
| Research/ingestie | `research.py` | DONE (claims-met-bron; Instagram manual-export) |
| Skills | `skills.py` | DONE (evidence-progressie, discovery) |
| Advanced 3D/CAD | `meshops.py`, `cad.py` | DONE/PARTIAL (procedural bouwt; extern UNAVAILABLE) |
| Fabricatie-orkestratie | `fabrication.py` | PARTIAL (plant/selecteert; start blijft gated) |
| Robots/drones/familiars/twin | `robots.py`, `drones.py`, `familiars.py`, `twin.py` | PARTIAL (modellen + gates; executie HARDWARE_REQUIRED) |
| Jobs | `jobs.py` | DONE (bounded, observable, idempotent) |
| Stabilization | `retention.py`, `payloads.py`, node-auth, fencing | DONE (BIG #16; zie `stabilization.md`) |
| Integration plane | `n8n.py` + routes | DONE (BIG #17; zie `n8n-integration.md`) |
| Live-universiteit | `live.py` + secties | PARTIAL (8 nieuwe secties, health apart gescoped) |
| Lokale desktop-scanner | `Mycelium/agent/` | Bestaand, read-only |

## Teststatus (gemeten, niet geschat)

- Mycelium: **935 passed** (`pytest -v` in `mycelium-ai-main/`)
  (931 voor BIG #18 + 4 nieuwe workflow-artifact-tests;
  camera-ctypes geeft dezelfde pre-existing
  access-violation-meldingen als altijd)
- INVENTory: **179 passed, 1 failed** (ongewijzigd schema) — de faal is pre-existing:
  `test_real_inventory_db_untouched` pint de exacte byte-grootte van
  de gitignored lokale `data/inventory.db`; inhoud groeit bij normaal
  gebruik, dus de assertie is broos per ontwerp van die test.

## Harde grenzen (blijven gelden)

Geen shell/RCE via acties · geen credentials-opslag · geen
auto-approval/bypass · geen permanente autonomie · geen fysieke
acties · geen cloud-verplichting · screenshots lokaal ·
coordinator raakt nooit input aan · agent handelt nooit buiten
goedgekeurd plan · INVENTory-mutaties nooit automatisch.
