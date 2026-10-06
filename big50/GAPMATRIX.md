# GAPMATRIX — capability × game-integratie (BIG50)

Prioriteit uit AUTOPILOT_ROADMAP (P0 E2E > P1 UI > P3 presentatie) en
CANVAS_DIRECTION (additief, skin over data). Status = code-bewijs.

| # | Capability | Backend | Bestaande route/service | In game | Kleinste interactie | Gap / eerlijk pad |
|---|---|---|---|---|---|---|
| G1 | Research→dossier→missie | ✅ getest | `/research/queue|run-once|dossiers|/{id}/plan` | /side station (queue/run/dossier/plan) | dossier→Plan-knop | wikipedia offline → `ran:false`; geen dossier → géén Plan-knop (Fase 4-fix) |
| G2 | Oracle-advies | ✅ live bewezen | `POST /api/v1/advise` | /play + /side knop | ongewijzigd | Ollama offline → 502/UNAVAILABLE |
| G3 | Knowledge-lifecycle | ✅ getest | `/candidates`, `/support`, `/promote`, `/reject` | discovery (create) | **gekozen Fase 5: in-world Support op eigen vondst** | fact-tier eist `verified_by` |
| G4 | Quest/missie-volgen | ✅ getest | `/quests`, `/missions`, `/play/mission` | links + journey | **gekozen Fase 3: Journal (lezen + YES/tick)** | geen nieuwe backlog-tabel |
| G5 | Worker-taken | ✅ live bewezen | `/play/code-task`, claim/complete | workshop-view | ongewijzigd | worker offline → wacht-stand |
| G6 | INVENTory-lezen | ✅ (bridge nodig) | `/world/search|entity|graph` | tellingen only | later: projectdoelen uit echte `proj_`-records | `:8080` offline → UNAVAILABLE |
| G7 | Automation-drive | ✅ getest | `/automation/runs/{id}/drive` | /play workshop | ongewijzigd | geen scheduler (contract) |
| G8 | Fabricage-status | 🟠 SIMULATED | `/fab/*`, `fabrication_chain()` | chain-states bij quests | geen executie-knop | printer UNAVAILABLE; paho-mqtt ontbreekt stock |
| G9 | Camera/VLM | 🟠 file-ingest only | `/cameras/*`, inbox | geen in game | buiten scope | geen adapter → geen live |
| G10 | Herinneringen/memory | ✅ getest | `/memory`, retrieve/verify | geen in game | later: dossier→geheugen-link | embeddings vereisen Ollama-model |

## Fasering (rest, na BIG50)

- F1: G6 projectdoelen in Journal uit echte `proj_`-records (alleen lezen; :8080-vereiste eerlijk).
- F2: G10 dossierkennis → memory-promote zichtbaar in game (bestaande gates).
- F3: G8 werkbank toont live `fabrication_chain()` per model (read-only).
- F4: G7 automation-drive vanuit Journal-missie (bestaande drive-route).
- F5 (P3): Terraria-skin verdiepen (tiles/sprites) over ongewijzigde data.
- Nooit: tweede backlog/missie/task/project-database; fysieke executie
  buiten bestaande YES/fingerprint/TTL/hardware-gates.
