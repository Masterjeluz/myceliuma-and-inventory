# ARCHITECTURE CONTRACT — Milestone 1F

Contract voor Mycelium AI + INVENTory + Desktop Agent. Vastgesteld op basis van
analyse van de bestaande implementatie (zie §H). Alleen analyserend en
vastleggend: geen codewijzigingen, geen API's, geen UI-wijzigingen.

Analysebronnen: `agent/agent.py` v0.2.0, `agent/agent_ui.py`, `agent/discovery.json`
(9 projecten), `agent/project_index.py` v1.0.0, `agent/project_index.json`
(9 projecten, 7 met relaties), `agent/README.md`, `agent/WORLD_MODEL.md`,
`agent/CANONICAL_PROJECTS.md`, `agent/tests/` (35 tests), INVENTory
(`inventory/app/main.py`, `schemas.py`, `README.md`, `tests/`, FastAPI :8080,
SQLite WAL), Mycelium (`mycelium-ai-main`: `coordinator/`, `node_client/`,
`docs/architecture.md`, `tests/`, :8000).

Reparatiestatus Milestone 1G (2026-09-11): §I.1 en §I.2 zijn hersteld
(INVENTory-README dekt Milestones 1A+1B; testaantal 35 geverifieerd).
Resterende §I-punten zijn gedocumenteerde openstaande interfaces, geen
contradicties meer.

## A. Rollen

- **Desktop Agent** (`agent/`): observeert het lokale filesystem (Desktop,
  Documents, Downloads), read-only. Produceert `discovery.json` (observaties)
  en `project_index.json` (identiteit + relaties). UI op :8787 toont alleen.
  Voert nooit mutaties uit aan gebruikersprojecten; enige schrijfactie is het
  (her)schrijven van de eigen twee JSON-bestanden.
- **INVENTory** (`inventory/`): wereldmodel-store voor fysiek én digitaal.
  SQLite (WAL), FastAPI-REST + server-rendered UI op :8080. Entiteiten met
  `obj_`/`proj_`/`idea_`/`rel_`/`evt_`-IDs en afgedwongen provenance
  (AI-gegenereerd = standaard ongeverifieerd). Bewaart staat en historie;
  beslist niets.
- **Mycelium Brain/Orchestrator** (`mycelium-ai-main/`, ambitie): reasoning,
  coördinatie en actie-aansturing. Huidige realiteit: `coordinator/` is een
  taakqueue met capability-matching (tiers seed/worker/core, nodes pollen),
  géén reasoning. De server verstuurt nooit uitvoerbare code; enige
  allow-list-taak is `system_inventory`. Elke AI-beslislaag is TOEKOMST en valt
  onder §D en §F.

## B. Wat INVENTory als wereldmodel moet representeren

| Concept | Status in INVENTory | Dekking |
|---|---|---|
| fysieke objecten | AANWEZIG | `Object` (naam, beschrijving, aantal) |
| hardware | ONTBREEKT | geen entiteit; hooguit als `Object`-tekst |
| sensoren | ONTBREEKT | alleen bronlabel `sensor-observed`, geen `Sensor`-entiteit |
| camera's | ONTBREEKT | geen entiteit, geen pipeline |
| software/projecten | AANWEZIG | `Project` + status (`idea…archived`) |
| bestanden/code | ONTBREEKT | gepland als Milestone 3 (Files + SHA-256) |
| materialen | ONTBREEKT | alleen als `Object`-beschrijving |
| locaties | ONTBREEKT | alleen predicaat `stored_in`, geen `Location`-entiteit |
| projecten | AANWEZIG | `Project` |
| ideeën | AANWEZIG | `Idea` + status (`raw…converted`) |
| modellen (AI) | ONTBREEKT | geen register; zie §D |
| events | AANWEZIG | `Event` (alle CRUD-overgangen) + `GET /api/v1/events` |
| relaties | AANWEZIG | `Relationship`, 10 predicaten, geen zelfreferentie |

## C. Kernrelaties → INVENTory-predicaat

| Relatie | Predicaat | Status |
|---|---|---|
| object → project | `used_in` / `part_of` | ONDERSTEUND |
| hardware → sensor | — | ONTBREEKT (geen entiteiten) |
| hardware → project | (`uses`) | ONTBREEKT (geen hardware-entiteit) |
| file → project | — | ONTBREEKT (wacht op Files, M3) |
| project → project | `depends_on` / `related_to` | ONDERSTEUND |
| object → location | `stored_in` | GEDEELTELIJK (geen Location-entiteit) |
| sensor → observation | — | ONTBREEKT (geen Sensor-entiteit, geen observatie-tabel) |
| idea → project | `became` / `led_to` | ONDERSTEUND |
| model → task | — | ONTBREEKT (geen modelregister; Mycelium-taken kennen alleen capability-strings) |
| event → entity | `Event.entity_id` | ONDERSTEUND |

De Desktop Agent levert verwante paren (`same_remote_ids`, `shared_name_ids`,
`possible_copy_ids`, `nested_children_ids`); het contract schrijft voor deze bij
import te vertalen naar bovenstaande predicaten (bv. `possible_copy_ids` →
`related_to` + metadata `{basis: same_remote|shared_name}`, nooit automatisch
samenvoegen).

## D. Model-agnostische AI (bindend)

- Alle AI-capabilities lopen via adapters/interfaces. Directe koppeling van
  core/database aan één model is verboden.
- Adapter-contract (te implementeren): input = index + plan-context, output =
  plan-voorstel (data, geen actie). Adapter vermeldt model + versie in provenance.
- Bestaande fundamenten: INVENTory-bron `ai-generated` + validator
  (`human_verified=False` tenzij `verified_by`); Mycelium allow-list
  (`system_inventory`) als precedent voor kleinste veilige capability.
- Wat ontbreekt: de interface zelf — nergens code voor; eerste adapter krijgt
  géén executierechten (alleen voorstellen).

## E. Physical-world architecture (normatieve lus)

`observe → understand → plan → permission → act → verify → record`

- observe: Desktop Agent (digitaal), INVENTory-objecten/sensoren (fysiek).
- understand/plan: Mycelium (TOEKOMST als runtime; nu alleen core loop op papier).
- permission: gate vóór elke mutatie (§F; code ONTBREEKT).
- act: skills met gedeclareerde output-grenzen; fysieke actuatie altijd achter een gate.
- verify: testsuites na wijzigingen; fysieke verificatie via nieuwe observatie.
- record: INVENTory-events + Git-checkpoints + provenance.

## F. Safety (bindend, per item met status)

1. Read-only discovery by default — GEÏMPLEMENTEERD (`SCANNER_MODE=local-readonly`).
2. Inspect before modify — BELEID (`README.md`), geen afdwinging in code.
3. Explicit permission voor destructieve wijzigingen — BELEID, geen gate-code.
4. Git-checkpoint vóór wijziging van getrackte projecten — ONTBREEKT (voorgesteld: `checkpoint.py`).
5. Test na wijzigingen — GEÏMPLEMENTEERD als suites (35 agent-tests; INVENTory-suite, zie §I.2), maar geen automatische koppeling aan acties.
6. Provenance voor AI-gegenereerde informatie — GEÏMPLEMENTEERD in INVENTory
   (`enforce_ai_unverified_rule`); Desktop Agent/index hebben nog géén
   `ai-generated`-bron (ze produceren ook geen AI-output — consistent).
7. Fysieke acties vereisen expliciete toestemming tot een toekomstige veilige
   automatiseringslaag bestaat — VACUÜM WAAR (er bestaan geen actuatoren), als
   norm vastgelegd zodat de eerste actuator er nooit omheen kan.

## G. Dataflow (normatief)

`Desktop Agent → Project Index → INVENTory → Mycelium → controlled workspace → tests/checkpoint → INVENTory/event history`

- Elke pijl is een expliciete, lokale overdracht met provenance; geen laag
  schrijft direct in een andere laag.
- `controlled workspace` bestaat nog niet: gedefinieerd als de enige plek waar
  goedgekeurde plannen worden uitgevoerd (werk-kopieën, nooit live projectmappen).
- Terugkoppeling (`event history`) is het enige toegestane pad van uitvoering
  terug naar het wereldmodel.

## H. Grenzen tussen de drie componenten

| Grens | Mechanisme | Contract |
|---|---|---|
| Desktop Agent → Project Index | bestand | `discovery.json` in, `project_index.json` uit; index bindt via `discovery_timestamp` |
| Project Index → INVENTory | REST (TOEKOMST) | `POST /api/v1/projects` + `POST /api/v1/relationships`; mappingtabel desktop-ID ↔ `proj_`-ID (ONTBREEKT, vereist) |
| Mycelium → INVENTory | REST (TOEKOMST, gepland M5) | alleen lezen + voorstellen; coordinator ziet vandaag geen bestanden/sensordata (bewust, `docs/architecture.md`) |
| INVENTory → Mycelium | REST/events (TOEKOMST) | wereldstaat + historie als context, nooit als opdracht |
| Mens → alles | UI's + gates | :8787 (lezen), :8080 (CRUD + webformulieren), :8000 (dashboard); destructief/fysiek alleen na expliciete toestemming |
| Mycelium → workspace | bestand/proces (TOEKOMST) | `controlled workspace` = werk-kopieën, nooit live projectmappen; enige plek waar goedgekeurde plannen draaien |
| ID-ruimten | gescheiden | agent: `sha1(computer\|pad)[:16]` zonder prefix; INVENTory: `obj_/proj_/idea_/rel_/evt_`; koppeling alleen via mappingtabel |

Binnen `agent/` geldt bovendien: `agent_ui.py` leest `discovery.json` direct en
slaat de indexlaag over (§I.5).

## I. Contradicties en ontbrekende interfaces (gevonden bij analyse)

1. ~~Stale INVENTory-README~~ **HERSTELD in 1G**: README dekt nu Milestones 1A+1B
   (Project/Idea/Relationship/Event-CRUD + event-stream + UI-pagina's) en noemt
   expliciet wat ontbreekt. Resterende plan-items: M3 (Conversations/Files),
   M4 (FTS5/graaf), M5 (Mycelium↔INVENTory REST).
2. ~~Testaantal INVENTory~~ **GEVERIFIEERD in 1G**: canonieke suite = 35 tests
   in 3 bestanden, 35/35 groen op 2026-09-11. Oudere "73/73"-claims zijn niet
   reproduceerbaar en worden nergens meer gesteld (INVENTory-README,
   `WORLD_MODEL.md` en dit contract).
3. **ID-kloof — VOLGENDE KERNINTERFACE (M2B)**: geen mapping tussen
   desktop-project-ID (`stable_id`) en INVENTory-`proj_`-ID; het index-haakveld
   `inventory: {stable_id, sync_ready}` wordt door geen enkele schrijver gevuld
   of gelezen. Canoniek-vs-kopie-beleid staat in `agent/CANONICAL_PROJECTS.md`:
   kopie-ID's worden als `copy_of` gemarkeerd, nooit als zelfstandige projecten
   geïmporteerd.
4. **Entiteitsgaten** (§B): hardware, sensor, camera, file, material, location,
   model, task ontbreken als entiteit; C-relaties hardware→sensor,
   sensor→observation, file→project, model→task zijn daardoor niet uitdrukbaar.
   Fysieke entiteiten (hardware, sensor, camera, materiaal, locatie, model, taak,
   observatie/event) mogen later via hetzelfde wereldmodel worden toegevoegd —
   nu alleen gedocumenteerd, GEEN entiteit toegevoegd in 1G.
5. **UI slaat index over**: `agent_ui.py` leest `discovery.json`, niet
   `project_index.json` — relaties/ID's zijn onzichtbaar in de UI.
6. **Geen gate-/checkpoint-code**: §F items 2–4 zijn beleid zonder afdwinging;
   enige schrijfactie in `agent/` is ongegatede lokale herschrijf van eigen JSON
   (acceptabel, maar precedent voor discipline).
7. **Geen import-/dedup-beleid**: index kent 7/9 gerelateerde (kopie/nested)
   projecten; INVENTory heeft geen regel wat er gebeurt als die geïmporteerd
   worden. Gedeeltelijk afgedekt in 1G: `agent/CANONICAL_PROJECTS.md` legt vast
   welke checkout canoniek is en verbiedt automatisch samenvoegen; volledige
   mappingtabel + `copy_of`-markering is M2B-werk.
8. **Zwakke index-binding**: index bewaart `discovery_timestamp` maar geen hash
   van de discovery-inhoud; staleness is detecteerbaar op tijd, niet op inhoud.
9. **Mycelium↔INVENTory-spanning**: coordinator mag bewust geen
   bestanden/sensordata zien (privacy-ontwerp), terwijl M5 juist
   hardware-inventarisatie-koppeling wil — vereist expliciete, minimale
   interface (alleen vrijwillige profielen + provenance), geen algemene lezing.
10. **Auth ontbreekt overal** (:8787/:8080/:8000 zonder tokens; Mycelium-docs
    noemen API-tokens als toekomstige stap) — acceptabel lokaal, moet expliciet
    blijven tot besloten wordt anders.

## J. Volgende 5 milestones (geprioriteerd)

1. **M1G — Contract-reparatie zonder code-risico**: INVENTory-README
   gelijkzetten met realiteit (M1B-geïmplementeerd markeren), testaantal
   ophelderen, `stored_in`-conventie documenteren. Klein, deblokkeert alles.
2. **M2A — Permission gates + `checkpoint.py`**: gate-functie +
   Git-checkpoint-skill met tests op tmp-repos; §F items 2–4 worden afdwingbaar.
   Vereist vóór elke mutatie- of import-mijlpaal.
3. **M2B — Index→INVENTory import (read-only eerst)**: mappingtabel
   desktop-ID ↔ `proj_`-ID, dry-run-modus, dedup-beleid (§I.7), provenance-bron
   voor index-import, C-vertaling `possible_copy_ids → related_to`. Pas daarna
   echt schrijven.
4. **M3 — Wereldmodel-entiteiten fase 1**: `Location`, `File` (+SHA-256, reeds
   gepland), minimale `Hardware`/`Sensor`-schema's; daarmee worden C-relaties
   hardware→sensor, sensor→observation, file→project, object→location
   uitdrukbaar.
5. **M5′ — Mycelium↔INVENTory leesbrug**: vrijwillige node-capability-profielen
   als `sensor-observed`/`ai-generated`-objecten met `human_verified=false`;
   expliciete minimale interface die het privacy-ontwerp (§I.9) respecteert.
   Adapter-interface (§D) en `controlled workspace` (§G) schuiven door naar M6.
