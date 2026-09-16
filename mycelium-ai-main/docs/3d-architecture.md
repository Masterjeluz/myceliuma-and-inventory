# 3D & Physical Pipeline Architecture (BIG #7)

Van digitaal object naar fysiek object — door dezelfde poorten
als alles else in Mycelium:

```
INVENTory object / idea
  ↓ generate (deterministic test geometry, local only)
3D mesh bytes (never valid/printable/safe by themselves)
  ↓ validate (stdlib STL/OBJ parsing, finite, bounded)
MeshReport: valid / invalid / inconclusive
  ↓ printability assessment (heuristic, never permission)
  ↓ File proposal → exact YES → controlled write (BIG #5)
mesh File (file_, sha256 identity)
  ↓ slice (test slicer or explicit unavailable)
G-code bytes (never production unless reviewed runtime made it)
  ↓ safety assessment (safe / unsafe / inconclusive)
  ↓ File proposal → exact YES → controlled write (BIG #5)
G-code File (file_, sha256 identity)
  ↓ print proposal (printer.execute — SECOND, explicit YES)
PHYSICAL APPROVAL (mission YES never starts the machine)
  ↓ revalidation (binding + fingerprint + G-code hash + safety)
execution (adapter only)
  ↓ telemetry result (telemetry only, never verification)
observation (BIG #6 camera) + two-half verification
  ↓ only both halves passed promotes
WORLD MODEL (INVENTory update via BIG #5)
```

Grenzen die nooit vermengen:

- **digital artifact ≠ physical artifact** — bytes zijn geen object.
- **validation ≠ human approval** — `valid` is een parse-oordeel.
- **assessment ≠ permission** — er bestaat nergens een
  `safe_to_execute`-veld; `safe` + `printable` autoriseren niets.
- **approval ≠ verification** — YES staat beweging toe; alleen
  readback bewijst resultaat.
- **printer telemetry ≠ physical verification** — "printer
  meldt voltooid" en "camera bevestigt object" zijn aparte
  verificatiehelften; beide moeten passen.
- **software cancel ≠ physical emergency stop** — cancel is een
  statustransitie; echte e-stop vereist hardware die deze laag
  niet aanraakt (contractgrens + `estop_note` op elke job).

## Generatie (`mesh3d.py`)

Naast de BIG #5-contracten in `pipeline3d.py` (onaangeroerd:
feasibility blijft advies, fysieke methoden blijven geweigerd).
`ThreeDProvider`-interface met exact twee implementaties:
`ProceduralTestGenerator` (deterministische 20mm-kubus als
ASCII STL, altijd test-gemarkeerd) en `UnavailableGenerator`
(expliciete reden). Geen netwerk, geen downloads, geen CAD-kernel.

## Validatie (`mesh3d.py`, stdlib-only)

ASCII/binaire STL en minimale OBJ: suffix-allow-list,
fabrication-dir-boundary, 20 MiB-cap, vertex/face-caps,
finite-float-checks (NaN/Inf weigert), non-empty geometrie.
Verdict `valid` / `invalid` (concreet defect) /
`inconclusive` (onparseerbaar — nooit `valid`).
`assess_printability` toetst bounds tegen build-volume
(default 220×220×250mm); output is planning-advies.

## Slicing (`slicer3d.py`)

`SlicerProvider`-interface; `TestSlicer` (deterministische
synthetische G-code met never-for-printers-header) en
`UnavailableSlicer` (met integratie-eisen voor een reviewed
lokale runtime: gepinde binary, vaste argv-allow-list,
bounded profiles). Profielen uit een gesloten set
(draft/fine-PLA, draft-PETG). Geen arbitraire slicer-
commando's — het executie-oppervlak bestaat niet.

## G-code safety (`slicer3d.py`)

Commando-allow-list per regel, temperatuurgrenzen (nozzle
≤ 300°C, bed ≤ 120°C), size/line-caps, geen includes, geen
traversal. Onbekende commando's → `inconclusive`; M112 en
andere verborgen intentie → `unsafe`. Unsafe G-code wordt
nooit een File-voorstel. Vingerafdruk (sha256) bindt het
artefact aan het voorstel; gewijzigde bytes na approval
blokkeren bij uitvoering.

## Printers (`printer3d.py`)

Mycelium-eigen device-tabel (`printer_devices`, id's `prt-*`)
met optionele `hw_`-link naar een INVENTory-hardware-twin
(wereldgeheugen vs. uitvoeringsautoriteit — gedocumenteerd,
niet gesynchroniseerd, geen dubbele device-database).
Gesloten capabilities (`printer.status/telemetry/upload/
start/pause/stop/cancel`), per adapter gefilterd. Alleen
`SimulatedPrinterAdapter` (deterministische in-memory state
machine, expliciet gesimuleerd) en `UnavailablePrinterAdapter`
bestaan. Geen serieel, geen netwerk, geen vendor-SDK.

## Uitvoering (`fab_flow.py`)

`propose_print` bouwt het inerte `printer.execute`-voorstel
(weiteit bij safety `unsafe`). `execute_print` eist alles:
binding, geen staleness, G-code-hash, safety ≠ unsafe,
allow-list-profile, adapter met `printer.start`. Resultaat is
telemetrie. `FabricationRecord` traceert elke stap
(source → mesh → validatie → file → slice → safety → file →
job → observatie) met history.

## Verificatie

`verify_print_telemetry` (job completed + hash) en
`verify_print_camera` (BIG #6-observatiecheck) — verified
alleen als beide passen (`print_verdict`). Bestaande
`/writes/{id}/verify` dekt de telemetriehelft;
`/writes/{id}/verify-print` combineert met camera.

## Missies, chat, graph, UI

Stap-soorten `fabricate`/`slice`/`physical_print` via
geïnjecteerde runners (zonder wiring BLOCKt de stap);
`physical_print` voltooit nooit geverifieerd vanzelf.
`POST /api/v1/fab/assess` beantwoordt "kunnen we dit
printen?" met advies + volgende stap — print nooit.
World-graph-overlay met gesloten predicaten (derived_from,
sliced_to, executed_as, produced, observed_by). Minimale
`/fabrication`-pagina in bestaande stijl (runs, printers,
validatie-, safety- en verificatiestaten).

## Retentie & files

Fabrication-dir, 20 MiB mesh-cap / 50 MiB G-code-cap,
laatste 5 artefacten, sha256-verplicht voor File-registratie
(`file_kind` mesh/gcode, `human_verified=False`). Alleen
referenties en metadata reizen verder — nooit bytes in
chat/context/databases.
