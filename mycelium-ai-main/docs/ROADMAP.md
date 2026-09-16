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

## PHASE G — HUMAN INTERFACE (FUTURE)

- Spraak (lokaal model, expliciete activering) — FUTURE
- Telefoon als node/bediening — FUTURE
- Garmin/auto/camper-integraties — FUTURE
- Realtime scherm/warme observatie — FUTURE
- Toekomstige AR-weergave van wereldmodel — FUTURE

## PHASE H — LIVING WORKSHOP (FUTURE)

- Definitieve Mycelium-workspace (chat, missies, wereldgrafiek,
  projecten, ideeën, agents, apparaten in één beeld) — FUTURE
- Lange-termijn-geheugen en geschiedenis/provenance-blik — FUTURE
- Fysieke-wereld-koppeling (actuatoren pas na Fases C–E) — FUTURE

## Expliciet niet op de kaart

Autonome ongelimiteerde computerbediening, credential-automatisering,
cloud-verplichte kern, permanente achtergrond-autonomie, wapens- of
toezicht-toepassingen. Deze komen niet "later vanzelf"; ze vereisen
een apart, expliciet besluit.
