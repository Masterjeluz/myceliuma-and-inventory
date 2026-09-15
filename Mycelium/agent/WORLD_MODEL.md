# WORLD MODEL — Mycelium + INVENTory symbiose

Architectuurspecificatie. Gebaseerd uitsluitend op bestaande code, documentatie
en de huidige project-index. Normatief voor toekomstige milestones; geen code,
geen API's, geen UI-wijzigingen in dit document.

Bronnen (stand 2026-09-11): `agent.py` v0.2.0, `project_index.py` v1.0.0,
`agent_ui.py` (Flask, read-only, :8787), `discovery.json`, `project_index.json`
(9 projecten: 6 git, 5 met remote, 1 backup, 4 nested, 7 met relaties),
`README.md` (core loop + safety principles), 35/35 agent-tests groen.

## 1. Lagen en verantwoordelijkheden

| Laag | Rol | Eigenaar van waarheid |
|---|---|---|
| Mycelium | Reasoning, coördinatie, acties aansturen | Plannen, beslissingen, toestemmingen |
| INVENTory | Fysieke wereld: objecten, hardware, sensoren | Fysieke staat en metingen |
| Desktop Agent | Computer-laag: filesystem, projecten, Git | `discovery.json` (observaties) |
| Project Index | Digitale projectwereld-index | `project_index.json` (identiteit + relaties) |
| World Model | Verbindende laag (dit document) | Koppelingen tussen alle lagen |

Regel: elke laag spreekt alleen via vastgelegde, lokale datastructuren
(JSON-bestanden). Geen laag schrijft direct in een andere laag.

## 2. Mycelium — reasoning/coördinatie/action-laag

- Interpreteert index + sensordata, maakt plannen, coördineert uitvoering.
- Voert zelf nooit mutaties uit; delegeert aan capabilities (skills) via permission gates (§8).
- Volgt strikt de core loop uit `README.md`: DISCOVER → UNDERSTAND → PLAN → ASK PERMISSION → BUILD → TEST → CHECKPOINT.
- Vandaag bestaat Mycelium als principe + core loop; reasoning-runtime is TOEKOMST (§12-status).

## 3. INVENTory — fysieke wereld/object/hardware/sensor-laag

- Aparte codebase (niet in deze repo). Rapporteert objecten, hardware en sensormetingen.
- Koppeling met Mycelium verloopt later via stabiele IDs en provenance, nooit via direct filesystem-schrijven.
- Statusopgave: eigen testsuite, geverifieerd 35/35 groen op 2026-09-11 (3 testbestanden);
  eerdere "73/73"-claims zijn niet reproduceerbaar en worden nergens meer gesteld.
  Geldt hier als externe context, niet als geverifieerd feit in deze repo.

## 4. Desktop Agent — computer/project/filesystem-laag (NU)

- `agent.py` v0.2.0, scanner `mycelium-desktop-agent`, modus `local-readonly`.
- Scant Desktop, Documents, Downloads; slaat `node_modules`, `.venv`, `__pycache__` e.d. over.
- Detecteert: git, python, node, documented, backup/kopie, nested, duplicaten.
- Leest Git-remotes uitsluitend uit `.git/config` (geen subprocess, geen netwerk).
- Schrijft alleen `discovery.json` naast zichzelf. Verwijdert, verplaatst of wijzigt nooit gebruikersprojecten.
- `agent_ui.py`: read-only Flask-UI met scan-knop; toont metadata, muteert niets.

## 5. Project Index — digitale projectwereld-index (NU)

- `project_index.py` v1.0.0 (`mycelium-project-index`), input `discovery.json`, output `project_index.json`.
- Stabiele project-ID: `sha1(computer|pad)[:16]`, case-insensitief. Zelfde computer + zelfde pad = zelfde ID, altijd. ID-schema is gedeeld met de scanner (`inventory.stable_id`); `agent.stable_id` is single source of truth.
- Per project: path, name, types, git-status, git remote, last_modified, file_count, recognized_files, backup/nested-status, `parent_id`, `relations` (`nested_children_ids`, `same_remote_ids`, `shared_name_ids`, `possible_copy_ids` = unie van remote + naam).
- Relaties zijn ID-verwijzingen (geen padafhankelijkheid), deterministisch gesorteerd.
- `possible_copy_ids` is een heuristiek (zelfde remote óf gedeelde naam), geen bewijs van identiteit.

## 6. World Model — verbindende laag (dit document + index)

- Het World Model is geen database maar een contract: lagen verwijzen naar elkaar via stabiele IDs + provenance.
- Digitale identiteit: project-ID uit de index. Fysieke identiteit (later): INVENTory-object-ID. Koppeltabel tussen die twee is TOEKOMST; het index-veld `inventory: {entity_type, stable_id, sync_ready}` is de gereserveerde haak.
- Alles wat het model beweert, is herleidbaar tot een observatie (§7).

## 7. Model-agnostische AI-adapters (TOEKOMST)

- Er is vandaag géén AI-model in de agent (bewust). Toekomstige modellen worden adapters achter een interface: input = index + plan-context, output = plan-voorstel, nooit directe actie.
- Adapters zijn vervangbaar zonder de lagen te wijzigen; provenance vermeldt altijd welk model/welke versie een voorstel deed.

## 8. Skills als herbruikbare capabilities (IN ONTWIKKELING)

- Een skill = één herbruikbare, geteste capability met vaste input/output (bv. `scan`, `index`, `checkpoint`, later `sense`, `detect`).
- Bestaande skills in de geest van dit model: discovery-scan (`agent.py`), indexbouw (`project_index.py`).
- Elke nieuwe skill krijgt: eigen module, eigen tests, eigen provenance-vermelding. Geen skill muteert buiten zijn gedeclareerde output.

## 9. Provenance (NU, verplicht voor alles nieuw)

- Elke observatie draagt: `source` (waar vandaan), `found_at`/`indexed_at` (wanneer), `scanner` + `scanner_version` / `indexer` + `indexer_version` (wie).
- Scanner-bron: `local-filesystem-scan`. Index-bron: `mycelium-desktop-agent:discovery.json`.
- Regel: informatie zonder provenance wordt niet vertrouwd en niet gekoppeld.

## 10. Permission gates (beleid NU, afdwinging IN ONTWIKKELING)

- Beleid staat in `README.md`: nooit verwijderen/verplaatsen zonder expliciete toestemming, nooit destructieve commando's zonder toestemming, eerst inspecteren, Git-checkpoint vóór wijzigingen, tests na wijzigingen.
- Gates als code bestaan nog niet; elke muterende skill moet straks een gate aanroepen vóór uitvoering (voorstel volgende milestone: `checkpoint.py`).
- Read-only paden (scan, index, UI-weergave) hebben geen gate nodig en krijgen er geen.

## 11. Plan → approve → execute → test → checkpoint → learn (norm)

- PLAN: Mycelium stelt een plan op uit index + context; plan is data, geen actie.
- APPROVE: mens (of gedelegeerde policy) keurt goed via permission gate.
- EXECUTE: skills voeren uit binnen hun gedeclareerde output-grenzen.
- TEST: bestaande testsuites draaien; falen = stoppen en herstellen.
- CHECKPOINT: Git-checkpoint van geraakte projecten + index-momentopname.
- LEARN: uitkomsten terugvoeren als provenance-gelabelde observaties (TOEKOMST, gesloten lus).

## 12. Toekomstige camera/VLM/detectie pipeline (TOEKOMST)

- Camera → VLM/detector → objectobservaties met provenance → INVENTory-laag → optionele koppeling aan project-ID (bv. "welk project hoort bij dit werkstuk").
- Pipeline is read-only ten opzichte van de fysieke wereld; stuurt nooit hardware aan zonder gate (§10).
- Vereist eerst: adapter-interface (§7) + koppelveld project-ID ↔ object-ID (§6).

## 13. Toekomstige sensoren en fysieke hardware (TOEKOMST)

- Sensoren publiceren metingen met provenance (sensor-ID, timestamp, eenheid) naar INVENTory.
- Hardware-actuatie valt altijd onder permission gates; geen autonome fysieke acties zonder goedkeuring.
- Desktop Agent raakt hardware nooit direct aan; communicatie loopt via INVENTory-structuren.

## 14. Toekomstige digitale twin (TOEKOMST)

- Twin = World Model + live observaties (index + INVENTory-metingen) + plannen.
- Geen aparte database in fase 1: de twin is een samengestelde view over `project_index.json` en INVENTory-output, met provenance per feit.
- Doel: "waar staat alles, wat verandert, wat is van plan" — alleen lezen tot gates + checkpoint bestaan.

## 15. Statusoverzicht

| Onderdeel | Status | Bewijs / opmerking |
|---|---|---|
| Discovery-scan v0.2.0 | NU | `agent.py`, 16 tests |
| `discovery.json` + provenance | NU | 9 projecten, scanner-veld |
| Project Index v1.0.0 | NU | `project_index.py`, 19 tests |
| `project_index.json` + relaties | NU | 9 projecten, 7 met relaties |
| Read-only UI | NU | `agent_ui.py`, scan-knop, muteert niets |
| Provenance-velden | NU | scanner- + indexer-provenance |
| Permission-beleid | NU (beleid) | `README.md` safety principles |
| INVENTory-koppeling via `stable_id` | IN ONTWIKKELING | haakveld `inventory` bestaat, koppeling nog niet |
| Permission gates als code | IN ONTWIKKELING | voorgesteld: `checkpoint.py` |
| Checkpoint-skill | IN ONTWIKKELING | voorgestelde volgende milestone |
| Mycelium reasoning-runtime | TOEKOMST | alleen core loop + principes |
| Model-agnostische AI-adapters | TOEKOMST | expliciet nog géén model |
| Skills-framework (formeel) | TOEKOMST | nu: conventie, geen framework |
| Camera/VLM/detectie | TOEKOMST | vereist §6 + §7 |
| Sensoren/hardware-aansturing | TOEKOMST | altijd achter gates |
| Digitale twin | TOEKOMST | view over index + INVENTory |
| Learn-lus (gesloten) | TOEKOMST | vereist checkpoint + provenance |

## 16. Harde grenzen (blijvend)

- Lokaal-first: geen externe API's zonder expliciet architectuurbesluit.
- Read-only als default; mutaties alleen via plan → approve → checkpoint.
- Niets buiten `agent/` schrijven; nooit gebruikersbestanden verwijderen, verplaatsen of wijzigen zonder toestemming.
- Geen UI-redesign zonder apart besluit; UI blijft observatie-instrument, geen actieconsole.
