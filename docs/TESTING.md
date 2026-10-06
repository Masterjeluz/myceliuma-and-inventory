# TESTING — snelle teststrategie (FAST / FEATURE / FULL)

Stand: 2026-10-05. Tooling: bestaande `pytest` per project, dunne
wrappers in `tools/`. Geen nieuwe infrastructuur, geen CI.

## Scopes

| Scope | Wanneer | Commando | Wat draait |
|---|---|---|---|
| **FAST** | na elke codewijziging (standaard) | `.\tools\test-fast.ps1 -Project <p> -TestPath <file> [-K naam]` | alleen direct geraakte testmodule + `-K`-filter voor één test |
| **FEATURE** | feature af / grenscontrole | `.\tools\test-feature.ps1 -Feature <naam>` | alle testfiles van die feature (mapping hieronder) |
| **FULL** | alleen expliciet of vóór milestone | `.\tools\test-full.ps1 -Project <p\|all>` | volledige per-project suite |

Directe pytest-mag ook (vanuit de projectsubdir):
`pytest tests/test_objects.py -v`, `pytest tests/test_x.py -k naam -v`.

## Feature-mapping (`test-feature.ps1`)

- `inventory-objects` → `test_objects.py`, `test_database.py`
- `inventory-search` → milestone-3x + `test_milestone_4.py`, `test_search_types_ui.py`
- `inventory-all` → `inventory/tests/`
- `missions` → `test_missions.py`, `test_big46_quest_mission.py`
- `research` → `test_research_*.py` (api/engine/extract/plan/security/transport)
- `knowledge` → `test_big32_knowledge.py`, `test_knowledge_lifecycle.py`
- `nodes-tasks` → `test_nodes.py`, `test_node_auth.py`, `test_node_client.py`, `test_dist_queue.py`, `test_desktop_agent.py`
- `vision` → `test_cameras.py`, `test_bambu_camera.py`, `test_vision_*.py`, `test_big34_camera_ecosystem.py`, `test_capture_probe.py`, `test_probe_grab.py`, `test_vision_capabilities.py`
- `fab` → `test_fab_*.py`, `test_printer3d.py`, `test_advanced_3d.py`, `test_bambu_readonly.py`
- `workshop` → `test_workshop.py`, `test_big35_workshop.py`, `test_big57_printfase.py` (incl. bibliotheek-importketen)
- `automation` → `test_big38_automation.py`, `test_controlled_writes.py`, `test_approvals_api.py`
- `game` → `test_big43/44/48` + `test_big46 t/m test_big57`, `test_canvas.py` (lezen mag; `/side` zelf is frozen)
- `solarpunk` → `test_solarpunk.py` (fase 1: read-only projectie; fase 2+ breidt uit)
- `insta360` → `test_insta360.py` (grab-runtime; alles gemockt, echte camera nooit in pytest)
- `homebase` → `test_homebase.py` (3D-pand pagina; render-only)
- `town` → `test_town.py` (fase 3+4; NPC zonder model → eerlijke noot, reflect → 409)
- `world` → `test_world_*.py` (`areas`, `observations`, `proxy`, `workspace`)
- `hermes` → `test_hermes_*.py` (`npc`, `bridge`, `all_npcs`)
- `agent` → `Mycelium/agent/tests/`

Mapping-aanpassing: voeg de nieuwe testfile toe aan de feature-lijst
in `tools/test-feature.ps1`; geen aparte lijsten elders.

## Regels

1. **Scope past bij wijziging**: FAST na elke edit, FEATURE bij
   feature-grens, FULL nooit standaard.
2. **Geen ongerelateerde suites** als verificatie van een kleine edit.
3. **Geen dubbele tests**: één testfile per gedrag; nieuwe edge →
   bestaande file uitbreiden i.p.v. nieuwe file.
4. **Geen `sleep`/willekeurige timeouts** in nieuwe tests (huidig:
   3x coordinator, 0x inventory — niet uitbreiden). Poll/wacht met
   deadline + expliciete timeout-constante.
5. **Geen externe services in unit tests**: netwerk gemockt of
   fail-closed (Ollama `:11434` down → 502/503; Wikipedia offline →
   `ran:false`). Echte calls alleen in handmatige checks.
6. **Geen echte hardware in pytest**: printer/camera-tests zijn
   gemockt en fail-closed (`PrinterUnavailable`, file-inbox +
   `UNAVAILABLE`). Echte Bambu/Insta360/Garmin-checks altijd apart
   en handmatig, nooit onderdeel van FAST/FEATURE/FULL.
7. **Duidelijke timeouts**: wrappers default 300s (FAST) / 600s
   (FEATURE); pytest-output kort (`-q --tb=short`).
8. **Tmp-DB discipline**: wrappers zetten `INVENTORY_DATABASE_PATH`,
   `MYCELIUM_DATABASE_PATH`, `MYCELIUM_CHAT_DATABASE_PATH` op tmp
   (`$env:TEMP`). Nooit echte `data/*.db` aanraken.
9. **Output kort en bruikbaar**: `-q --tb=short`; bij falen alleen
   de falende test + 5 regels context in het rapport.

## Voorbeelden

```powershell
# FAST: één module na een edit in inventory
.\tools\test-fast.ps1 -Project inventory -TestPath tests/test_objects.py

# FAST: één test binnen coordinator-missies
.\tools\test-feature.ps1 -Feature missions   # feature-grens
.\tools\test-fast.ps1 -Project coordinator -TestPath tests/test_missions.py -K test_approve

# FULL: alleen op verzoek / voor milestone
.\tools\test-full.ps1 -Project inventory
```

## Bekende quirks (niet "fixen" via infra)

- Inventory-tests zetten `INVENTORY_DATABASE_PATH` direct
  (`os.environ`, geen `monkeypatch`) → lekkage tussen tests in één
  proces; wrappers isoleren via tmp-pad per run.
- Coordinator-tests bouwen `TestClient(app)` met lifespan; zet DB-paden
  vóór client-constructie. Enkele tests skippen op non-Windows of
  eisen `git` op PATH.
