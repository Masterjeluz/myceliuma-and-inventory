# PROJECTATLAS — Mycelium AI + INVENTory (BIG50)

Stand: 2026-09-25, werkboom bovenop `81db8aa`, uncommitted BIG46–55.
Bronregel: code + tests bewijzen werking; documenten bewijzen intentie.
Afwijkingen intentie↔implementatie zijn gelabeld.

## 1. Apps / services / projecten

| # | App/service | Locatie | Doel | Status | Eigenaar | Capability | Afhankelijkheden |
|---|---|---|---|---|---|---|---|
| A1 | INVENTory wereldmodel-store | `inventory/` (enige git-repo: `app/main.py`, `app/database.py`, `app/schemas.py`, `app/ids.py`) | Bron van waarheid "wat bestaat": 11 entiteiten + relaties + events + FTS + graaf | Werkend, `:8080`, SQLite WAL, geen auth | — | CRUD `obj_/proj_/idea_/rel_/evt_/hw_/sns_/cam_/loc_/mod_/task_/act_/file_`, search, graph | geen |
| A2 | Mycelium coordinator | `mycelium-ai-main/coordinator/app/` (`main.py` ~22k regels, ~120 modules) | "Wat kan/moet gebeuren": missions, tasks, research, knowledge, nodes, automation, game-views | Werkend, `:8000`, `MYCELIUM_DATABASE_PATH` + chat-DB | — | 480+ routes (55 HTML-pagina's), queue, gates | A1 (alleen lezend via loopback bridge), lokale Ollama |
| A3 | node_client worker | `mycelium-ai-main/node_client/` | Generieke node: heartbeat, claim, `research.fetch_url`/`system_inventory` uitvoeren | Werkend | — | pull-only claim/complete | A2 |
| A4 | code_worker | `mycelium-ai-main/code_worker/main.py` | Bounded code.*-worker via lokale OpenCode-run | Werkend, live bewezen (BIG47/48) | — | `code.review/patch/test`, allowlist-calls | A2, lokale `opencode`-binary |
| A5 | scout | `mycelium-ai-main/scout/` | Verkenner, max 1 taak, mag niet approven/executen | Bestaat | — | begrensde observatie | A2 |
| A6 | desktop_agent | `mycelium-ai-main/desktop_agent/` + `Mycelium/agent/` (`agent.py`, Flask-UI `:8787`) | Read-only discovery van computer/projecten | Werkend, read-only | — | scan, `discovery.json`/`project_index.json` | geen (bewust geen coordinator-link) |
| A7 | Top-down game `/play` | `coordinator/app/main.py` `play_page` + Luma/Forge-dialog | Primaire runtime (BIG48): Oracle/research/knowledge/missions/workshop/forge als NPC-views | Werkend, canvas+JS inline | — | alle A2-reads + gated writes | A2 |
| A8 | Side-view game `/side` | `coordinator/app/main.py` `side_page` (BIG49/49-X) | Terraria-geïnspireerde wereld (BIG53–55): 6 regio's, nodes/recepten, kisten, NPC-housing, klok/events, encounters/boss | Speelbaar, browser-bewezen | — | candidates/advise/research/quests/missions/sessies/flags/npc/notes | A2 |
| A9 | World/canvas/graph | `/world`, `/canvas`, `/workshop/graph`, `world.py`, `worldgraph.py` | Afgeleide wereldviews over A1+A2 | Werkend, read-only | — | search/entity/graph-projecties | A1, A2 |

## 2. Welke game-data al gebruikt wordt

- `/play`: `game_state()`, missions, candidates, observations, inbox, notifications, bus-events, fungi-netwerk, forge-stores, INVENTory-tellingen, `play/status`-snapshot, `play/code-task`, `play/mission`, sessies.
- `/side`: candidates (discovery), advise, research queue/run-once/dossiers/plan, `play/mission`, quests, sessies (zone `side`), XP localStorage-only.
- Beide: geen tweede truth; sessie-positie is het enige game-eigendom (server-side rij, geen entiteit).

## 3. Overlapclusters (mogelijk dubbel — bewijs vastgelegd, niets hernoemd)

| Cluster | Leden | Canonieke bron | Bewijs van grens |
|---|---|---|---|
| C1 plannen vs missies vs runs | `plans.py` Plan (inert) / `missions.py` Mission (uitvoerbaar) / `automation.py` AutomationRun ("NO second mission engine" :8) / `jobs.py` job_runs / research runs `res_` | Per doel: uitvoerbaar werk = **Mission**; research = **run**; automatisering = **AutomationRun** | Verschillende tabellen; `task_queue_bridge.py:12` markeert staged-grens expliciet |
| C2 taken (3 systemen) | queue-`tasks` (int-id, queued/assigned) / `CoordinatorTask` (data, approved, nooit queued) / INVENTory-`task_` (remote world-model) / quest-`task`-steps (alleen refs) | Uitvoerbare taken = **queue-`tasks`**; `CoordinatorTask` = vertaalvoorstel | `proposal_tasks.py:17-19`, `task_queue_bridge.py:12` |
| C3 projecten (3) | remote `proj_` (A1) / lokaal `ProjectContext prj-` / `project_package`-projectie (geen store) | Wereldwaarheid = **INVENTory `proj_`**; lokaal alleen context | `project_package.py:14` (geen store) |
| C4 kennisgeheugen (3 paden) | candidates `cand_` / memories `mem_` / research records+dossiers | Feit = **memory**; kandidaat/dossier = voorfase | `promote_candidate`, `remember_dossier`, `mirror_record` met fingerprint-dedup |
| C5 gamepagina's | `/play` (top-down runtime) / `/side` (side-view slice) / `/game` (hub) / `/canvas` (workbench-lens) | Primaire runtime = **`/side`** (BIG51-gebruikerskeuze, zie §6); `/play` behouden; `/game` = hub | Verschillende presentatie, zelfde stores; géén derde game-ervaring gebouwd |

## 4. Aantoonbaar missend / gesimuleerd / offline / niet-aangesloten

- Printer/fabricage: SIMULATED slicer, geen printer/adapter → UNAVAILABLE; `paho-mqtt` ontbreekt stock (`REALITY_MAP §C`, code-bewijs). Fysiek printen = BLOCKED achter exact-YES + hardware.
- CAD-runtimes (OpenSCAD/FreeCAD/Blender): UNAVAILABLE; alleen `procedural-test`.
- Camera live/VLM/GPU: geen capture-adapter → file-ingest only, VLM-fallback eerlijk.
- Research providers: `wikipedia` vereist internet (offline → eerlijke `ran:false`); `test` vereist fixtures; Instagram UNAVAILABLE (alleen manual/mock).
- Embeddings/STT/TTS/WEB_PUSH/Garmin-live/robots/drones: UNAVAILABLE/MOCK by design.
- INVENTory-bridge: GET-only loopback; `:8080` offline → alle world-data UNAVAILABLE (advise degradeert eerlijk).
- Game: geen XP-economie, geen multiplayer, geen SSE/polling, touch niet op hardware getest.

## 5. Statusmodellen (canoniek, voor game-weergave)

- Mission: `draft → pending_approval → approved → running → completed`, plus `paused/failed/cancelled/blocked`. Exact-YES enige approve-weg. Steps: `pending → dispatched → completed` (queue-pad) of inline runners.
- Quest: alleen def opgeslagen; state live afgeleid (`COMPLETE/ACTIVE/WAITING/BLOCKED/FAILED/MISSING`), `done/total` echt.
- Campaign: afgeleid over quests; seeds zijn draft-missies + koppelquests.
- Task: `queued → assigned → completed/failed` (lease/fencing/capability-gated); `staged` nooit claimbaar.
- Research run: `draft/collecting/…/completed/blocked/failed/cancelled/unavailable` + `execution_state REAL/SIMULATED/TEST/UNAVAILABLE`; alleen `draft/blocked/failed` herstartbaar. Plan vereist **completed dossier met inhoud**, anders 422.
- Candidate: `observation → candidate → supported (2 supporters) → promoted`; fact-tier eist `verified_by`.
- Approvals: mission-YES, write-YES (+fingerprint/TTL/revalidate), voice (nooit fysiek), promotion human `staged→queued`. Niets omzeild.

## 6. BIG51 — game-first productrichting (gebruikerskeuze, leidend)

De side-view game (`/side`) is de primaire Mycelium-ervaring: een
Terraria-geïnspireerde eigen gamewereld waarin echte projecten,
backend-mogelijkheden en voortgang begrijpelijk en bruikbaar zijn.
Deze keuze heeft voorrang op verouderde roadmaptekst (AUTOPILOT
P0–P3 "game last", ROADMAP-V2, BIG48 "`/play` = runtime",
CANVAS_DIRECTION "FUTURE"): die documenten blijven archief
(intentie op schrijfmoment), geen sturing.

Behouden architectuurregels (ongewijzigd, getest):

- Bestaande backend is leidend; de game is VIEW, geen tweede
  missie-/project-/task-/kennisdatabase (`play_journal()` is
  read-only rangschikking; sessie-positie blijft het enige
  game-eigendom).
- INVENTory blijft bron van waarheid via de read-only loopback
  bridge (GET-only, timeout ≤ 5s); offline → UNAVAILABLE, leeg →
  eerlijk leeg, nooit verzonnen.
- Approvals blijven intact: operationele missies met echte
  effecten alleen achter de bestaande exacte YES; XP is optionele
  beloning (localStorage), geen toegangspoort, geen bewijs van
  voortgang.
- Bestaande `/play-`, `/world-`, `/side-` en dashboardroutes
  blijven werken zolang nuttig; geen derde game-ervaring.
  Journal/Command Center (`GET /api/v1/play/journal` + in-game
  Journal-view) toont missions/quests/research/vondsten én echte
  `proj_`-records en onthouden `mem_`-records met bronrecord +
  deeplink.

## 7. Bronverwijzingen (routes/tests per model)

Zie subatlas: modellen+routes+tests zijn volledig geïnventariseerd in de BIG50-werknotities (missions/quests/campaigns/tasks/projects/research/knowledge/approvals met module-, regel- en testverwijzingen). Kernroutes: `POST /api/v1/missions`, `/approve`, `/tick`, `/dispatch`; `POST /api/v1/quests`; `POST /api/v1/campaigns`; `POST /api/v1/tasks`, `/claim`, `/complete`; `POST /api/v1/research/queue`, `/queue/run-once`, `/runs/{id}/execute`, `/dossiers/{id}`, `/{id}/plan`; `POST /api/v1/candidates`, `/support`, `/promote`, `/reject`; `POST /api/v1/play/mission`, `/play/code-task`, `/play/session`, `/play/position`. Game: `/play` (L18608), `/side` (L21275), `/game`, `/quests`, `/world`. Paginagroen: 55 HTML-routes in `coordinator/app/main.py`, 33 in `inventory/app/main.py`, `Mycelium/agent/agent_ui.py` (`:8787`).
