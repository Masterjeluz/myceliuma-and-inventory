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

## PHASE B — UNDERSTANDING (NEXT)

Mycelium begrijpt de wereld beter vóórdat het handelt.

- Semantische retrieval naast de substring-bridge (lokaal embedding-model, FTS blijft fallback) — NEXT (BIG #4-kandidaat)
- Rijker wereldmodel-redeneren (relaties/grafiek als plan-context) — NEXT
- Missie-sjablonen per projecttype (verken, diagnose, bouw-voorstel) — NEXT
- Project-bewuste context (actief project als standaard-filter) — NEXT
- `docs/first-node-blueprint.md` herstellen (README linkt erheen, bestand ontbreekt) — NEXT (klein)

## PHASE C — CONTROLLED WRITES (FUTURE)

Schrijven mag, maar alleen via dezelfde poorten als lezen: voorstel,
goedkeuring, uitvoering, verificatie.

- INVENTory-schrijfvoorstellen (operator-keurt-goed, provenance
  `ai-generated` → nooit automatisch `human_verified`) — FUTURE
- Git-voorstellen en commits via expliciete capability (push/merge
  blijven verboden tot apart review) — FUTURE
- Bestands-/projectwijzigingen via missie-stappen met diff-preview — FUTURE
- Verificatie-stap als eersteklas burger (resultaat ≠ verified) — FUTURE
- Sterkere audit-trail (wie/wat/waarom per mutatie, exporteerbaar) — FUTURE

## PHASE D — VISION (FUTURE)

Van registreren naar waarnemen — altijd met menselijke verificatie.

- Camera-ingestie (lokaal, tijdelijk, retentie-begrensd zoals screenshots) — FUTURE
- VLM-adapter (lokaal eerst; extern alleen via provider-beleid) — FUTURE
- Object-identificatie → voorstel → menselijke verificatie → INVENTory — FUTURE
- Beeld-provenance (bron, tijd, model, verificatiestatus) — FUTURE

## PHASE E — CREATION / 3D (FUTURE)

Alleen contracten bestaan (`pipeline3d.py`); uitvoering komt pas met
een menselijke hand aan elke fysieke grens.

- Object → 3D-haalbaarheid → CAD/mesh (lokaal) — FUTURE
- Slicer/G-code als preview-only, nooit directe printeraansturing — FUTURE
- Menselijke goedkeuring vóór elk fysiek artefact — FUTURE
- Fysieke verificatie-terugkoppeling naar INVENTory — FUTURE

## PHASE F — DISTRIBUTED MYCELIUM (FUTURE)

Het protocol is er (register/heartbeat/claim/leaset); schaal volgt.

- Meerdere nodes in de praktijk (huis, werkplaats, onderweg) — FUTURE
- Capability-discovery en model-routing — FUTURE
- Workload-verdeling en offline-weerbaarheid — FUTURE
- Energie-bewuste scheduling (metingen eerst, handmatige override
  altijd, conform architectuur-v0.1) — FUTURE
- API-tokens vóór nodes buiten het vertrouwde LAN — FUTURE

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
