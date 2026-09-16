# Mycelium Chat + Desktop Agent — architectuur (verticale slice)

Doel: praat met Mycelium zoals met ChatGPT, met INVENTory als
wereldmodel, lokaal AI-advies, plannen met approval, en een
desktop-agent die scherm/muis/toetsenbord bedient na expliciete
toestemming.

## Rol-verdeling (AI DENKT, AGENT HANDELT, MENS BESLIST)

- **Mycelium (coordinator, `:8000`)** = redeneren/coördineren.
  Chat, context, providers, plannen, proposals, approvals, taken.
- **INVENTory (`:8080`)** = persistent wereldmodel. Alleen gelezen
  via de bestaande read-only bridge (`inventory_read.py`, GET-only,
  loopback-only). Geen tweede database voor INVENTory-data.
- **Desktop-agent (lokaal proces)** = computer-interactie/uitvoering.
  Voert alleen uit; redeneert niet; praat nooit direct met externe AI.
- **AI-providers** = redeneerbronnen. Lokaal Ollama/Qwen default;
  extern later, nooit verplicht.

```
Jelles → Mycelium Chat → Coordinator
                           ├── INVENTory-context (read-only bridge)
                           ├── AI-provider (Ollama default, extern = stub)
                           └── Plan → Proposal → Approval → Task
                                                  ↓
                                           Desktop-agent (lokaal)
                                                  ↓
                                    observe/screenshot → approval →
                                    muis/toetsenbord → resultaat
                                                  ↓
                                               Mycelium → Jelles
```

## Wat echt werkt

- **Chat** (`POST /api/v1/chat`, pagina `/chat`): gesprekken en
  berichten persistent (`conv-`/`msg-`), INVENTory-context per beurt,
  bronnen (`sources`) zichtbaar, best-effort proposal-extractie.
  Zonder model: eerlijke fallback (geen verzonnen advies).
- **Providers** (`providers.py`): `AIProvider`-interface,
  `OllamaProvider` om bestaande `OllamaAdvisor`, `ExternalProvider`
  als veilige stub (altijd unavailable, weigert credentials).
- **Planning** (`plans.py`): `Plan`/`PlanStep` met capabilities,
  `plan_to_proposal()` hergebruikt de M6.3-approval — geen tweede
  approval-mechanisme.
- **Desktop-contract** (`computer_actions.py`): 9 gesloten
  actie-types, strikt gevalideerde parameters, expliciete
  capabilities (`desktop.screen.read`, `desktop.mouse.*`,
  `desktop.keyboard.*`). Onbekend = fail-closed. Geen shell, geen code.
- **Runtime** (`desktop_runtime.py`): echte Windows-implementatie
  met alléén stdlib (`ctypes` → user32/gdi32, eigen BMP-writer).
  Screenshot, muis bewegen/klikken/scrollen, typen, toetsen,
  hotkeys, wachten. Droogloop-backend elders/zonder toestemming.
  **Bewezen op deze machine**: echte screenshot-test slaagt.
- **Agent-loop** (`agent_loop.py` + `desktop_actions` in
  `mycelium-chat.db`): pending → approved → dispatched →
  completed/failed/blocked, exact `YES`/`NO`, cancel uit elke
  wachtstaat (stop-grens). De coordinator voert nooit zelf input uit;
  dispatch is alleen een status-overgang.
- **Agent-UI** (`/agents`, `GET /api/v1/agent/status`): online-status,
  huidige actie, Approve/Reject/Stop-knoppen, activiteit met
  ✓/⏳/○. INVENTory/Projects/Files/Models-secties linken naar de
  INVENTory-UI + tonen coordinator-taken/nodes (geen data-duplicaat).
- **Project- (`project_context.py`) en Git-context
  (`git_context.py`)**: actief project via `MYCELIUM_PROJECT_ROOT`,
  alleen-lezen `status`/`branch`/`diff`. Geen push/merge/commit.
- **Node-client**: claim-loop blijft read-only
  (`system_inventory`, `desktop_screenshot`); desktop-input wordt
  geweigerd met "needs explicit human approval".
- **Standalone desktop-agent** (`desktop_agent/`, BIG #2): eigen
  proces, outbound-only (register/heartbeat/claim/result via
  bestaande node-routes + `POST /desktop/actions/next`), stabiele
  `desktop_<sha1(host|user)>`-identity, claim = atomair
  approved→dispatched (exactly-once lease, `dispatched_by/at`),
  hercontrole van approval direct vóór iedere input-actie,
  observe→act→observe met pre/post-screenshots,
  `MAX_AGENT_STEPS` default 20 (hard cap 100), stop-vlag,
  cancel óók vanuit dispatched (lease-herroeping). **Live bewezen**:
  echte agent claimde screenshot, voerde uit, rapporteerde
  completed; niet-goedgekeurde click bleef onaangeroerd.

## Nog stub/interface (expliciet, geen nepfunctionaliteit)

- `ExternalProvider`: interface + fail-closed stub; echte
  OpenAI/Gemini-koppeling vereist apart review (credentials,
  dataminimalisatie, toestemming).
- `pipeline3d.py`: alleen contracten/stadia/validatie voor de
  foto→3D-keten; **geen generator**, geen printer, geen G-code.
- `node_client` voert desktop-input nooit automatisch uit; de
  zelfstandige desktop-agent (`desktop_agent/`) claimt, hercontroleert
  en voert uit — de coordinator zelf raakt nooit een muis aan.
- Screenshots blijven lokaal (`%TEMP%/mycelium-obs`, retentie 5);
  nooit naar cloud/extern model zonder expliciete capability.

## Veiligheidsgrenzen (actief, getest)

Geen arbitraire code/shell via actions · geen remote inbound control
· geen credentials-opslag (provider-config weigert secrets) · geen
browser-logins/financiële acties · geen destructieve FS-acties ·
geen permanente autonomie · geen auto-approval/bypass (exact YES) ·
geen fysieke hardware · geen externe AI-call zonder configuratie ·
screenshots lokaal · fail-closed bij onbekende capability/actie ·
agent altijd stopbaar (cancel + rejected-default).

## Keten (voorbeeld, BIG #3 + #4 — live bewezen)

1. `POST /api/v1/chat` {message, mode: hybrid} → hybrid retrieval
   (semantisch + lexicaal + relaties) → reply + sources met
   `match_type`/`score` + `retrieval_mode`
2. `POST /api/v1/chat/{id}/missions` of `/missions/from-template`
   → missie met wereldcontext → plan-bericht in gesprek
3. `POST /api/v1/missions/{id}/approve` YES → plan goedgekeurd
4. `POST .../tick` → readout-stappen direct; desktop-stap maakt
   één dact via bestaande gate + binding (mission, step, action)
5. Desktop-agent claimt via `/next` (alleen approved + matching
   capability), hervalideert, pre-screenshot → input →
   post-screenshot, rapporteert resultaat
6. `POST .../tick` → observatie in stap, volgende stap, analyse
   via Ollama, eind-samenvatting (bronnen + acties) in conversatie
7. Events (`.../events`) + voortgang (`/missions/{id}`, `/agents`,
   `/chat`) tonen elke overgang; pause/resume/cancel altijd;
   voorstel-stappen produceren alleen artifacten (aparte approval).
8. Wereldgrafiek (`/api/v1/graph`) projecteert INVENTory +
   missie/agent-overlay voor navigatie en toekomstige UI.
9. Camera's (`/cameras`): registratie + read-only detectie;
   snapshots weigeren zonder capture-runtime (409).
10. Controlled writes (BIG #5): chat/missies dragen project-
    identiteit als context; writes lopen via
    `/api/v1/writes/*` (voorstel → exact YES → uitvoering →
    onafhankelijke verificatie). Missie-`write`-stappen binden
    aan exact één goedgekeurd voorstel; zonder gekoppelde
    capability BLOCKt de stap. Project-pakketten via
    `/api/v1/project/package` (bounded, geen secrets).

Autonomie geldt uitsluitend binnen de goedgekeurde stappen; een
actie zonder geldige binding wordt genegeerd (fail-closed).

## Volgende grootste verticale stap (BIG #4-voorstel)

Stap-voor-stap autonomie mét tussen-goedkeuring per desktop-input
bestaat al; wat ontbreekt is selectieve aandacht: semantische
INVENTory-retrieval naast de huidige substring-bridge (zodat "wat
kan ik maken met mijn onderdelen" echt redeneert over voorraad),
   plus missie-sjablonen per projecttype. Daarna: gecontroleerde
   schrijf-paden — DONE in BIG #5
   (`docs/controlled-writes-and-verification.md`): INVENTory-
   voorstellen via bestaande provenance-regel, git-commits via
   expliciete capability, verificatie als eersteklas stap.
