# Vision Architecture (BIG #6)

Van camera tot geverifieerde wereldwijziging — zonder dat AI
ooit rechtstreeks de wereld aanraakt:

```
camera
  ↓ capture (adapter, allow-listed capability only)
local media (camera dir, hash + size, retention-bounded)
  ↓ ingest (observation + media facts + inert File payload)
OBSERVATION (sensor-observed, unverified — never FACT)
  ↓ local VLM (loopback Ollama, allow-listed media only)
ANALYSIS / ADVICE (labels + confidences + description)
  ↓ inert proposal (BIG #5, uncertainty preserved)
PROPOSAL
  ↓ human exact-YES (existing dialect, no new framework)
APPROVAL (permission — still not truth)
  ↓ controlled write (BIG #5, fingerprint-bound)
RESULT (executed/failed/blocked — never verified)
  ↓ independent readback (BIG #5)
VERIFICATION (passed/failed/inconclusive)
  ↓ only passed promotes
WORLD MODEL (INVENTory authority)
```

Drie zinnen die nooit vermengd worden:

- **observation ≠ fact** — een capture bewijst het record,
  nooit de identiteit van wat erop staat.
- **AI analysis ≠ fact** — VLM-output is advies met
  onzekerheid, ook bij confidence 0.99.
- **approval ≠ verification** — YES staat de actie toe;
  alleen readback bewijst het resultaat.

## Ingestie (`vision_ingest.py`)

Bovenop de BIG #4-abstractie (`cameras.py`, onaangeroerd).
Staten zijn expliciet: registered → detected → connected →
capturable, anders unavailable — nooit geïmpliceerd. `probe`
activeert niets. `ingest_snapshot` levert observatie +
media-feiten (sha256, grootte, mime) + een INERT File-payload
voor de BIG #5-approvalflow; zonder werkende adapter weigert
alles (409). Testmedia draagt altijd `test-origin` in de
provenance. Media limiet 10 MiB per bestand, retentie laatste
5 — cleanup raakt nooit world-model-entities.

## Adapters

- `SyntheticTestAdapter` — deterministische testbeelden,
  altijd als test gemarkeerd. Enige bron van bytes in tests.
- `WindowsWebcamAdapter` — stub met complete interface maar
  zonder capture: een veilige MediaFoundation/DirectShow-
  runtime ontbreekt nog (vereisten gedocumenteerd in code).
- `Insta360Adapter` — foundation zonder gegokte SDK: identiteit
  (source=insta360, kinds per geïmplementeerde capability),
  staten, heuristische detectie-kandidaten (substring-match,
  expliciet kandidaat, nooit verbinding), en gedocumenteerde
  eisen voor echte integratie (webcam-modus via vendor-driver
  of reviewed file-ingest). Echte capture vandaag:
  unavailable — nooit fake bytes.
- Registry is leeg in productie (fail-closed); capabilities
  worden per adapter gefilterd tegen de gesloten set
  (`camera.snapshot/webcam/stream/360`) — spoofing is
  onmogelijk.

## Streams

`StreamSession`/`StreamManager`: lokale lifecycle-foundation
zonder transport — expliciete start/stop, frame- en
tijdbudgetten (max 10000 frames, max 3600 s), auto-expiry.
Gestopte of verlopen sessies hervatten nooit. Geen binding,
geen inbound ports, geen relay, geen permanente streams.

## VLM (`vision_provider.py`)

`VisionProvider`-interface (`analyze(VisionRequest) ->
VisionResult`). `OllamaVisionProvider` praat met lokaal Ollama
(`/api/chat` + base64-image), loopback-only, timeout ≤ 120s,
model via `VISION_MODEL` (default `qwen3-vl:4b`). Ontbrekend
model weigert met een `ollama pull`-hint — Mycelium downloadt
nooit zelf. Input: exact één bestand uit de camera-dir
(bestaande `check_image_ref`, bekende suffix, 10 MiB-cap,
boundary-check). Output: labels, detected objects met
model-confidence, beschrijving, onzekerheid — plus ruwe tekst
voor audit. Provenance altijd ai-generated/unverified, door
de module gezet; model-claims worden genegeerd. Malformed
output weigert; structuur wordt nooit verzonnen.
`UnavailableVisionProvider` (fail-closed stub) en
`TestVisionProvider` (deterministisch) completeren het beeld.

## Flow (`vision_flow.py`)

Alleen voorstellen en verifiëren — de module bevat geen enkel
uitvoeringspad (getest per broncode-inspectie). `vision_to_`
`object_proposal` (top-kandidaat als naam, alle kandidaten +
confidences in de beschrijving) en `vision_to_file_proposal`
(mediaregistratie) bouwen inerte BIG #5-voorstellen; lege
analyses weigeren. `verify_observation` controleert record +
lokale media; een pass bevestigt het record, nooit de
afgebeelde identiteit. Menselijke verificatie hergebruikt het
bestaande exact-YES op het write-voorstel — geen nieuw
approval-framework.

## Integratie

- Missie-stap `camera_observe` (device-binding, metadata-
  resultaat, geen pixels in state, nooit automatische write;
  zonder capability BLOCK).
- Chat: opt-in `observation_ids` (max 3, metadata-samenvat-
  tingen); standaardgedrag ongewijzigd.
- World Graph: optionele observatie-overlay (captured-edges,
  describes-edges alleen bij expliciete link).
- Project-pakketten: ≤ 5 observaties met VLM-labels.
- API: ingest, availability, observations/recent,
  vision/analyze, vision/propose, streams, plus `/cameras`-
  pagina met beschikbaarheid en laatste observatie.
- File-create/update als controlled mutation (schema
  geverifieerd tegen `inventory/app/schemas.py`), zodat
  media-registratie dezelfde keten volgt.

## Retentie & files

Media: camera-dir, 10 MiB-cap, laatste 5, hash-verplicht voor
File-registratie (`file_kind=image`, `human_verified=False`).
File-lifecycle (media) en entity-lifecycle (INVENTory-rij)
blijven gescheiden: cleanup verwijdert bestanden, nooit
entities. Geen file-inhoud in chat/context/databases —
alleen referenties en metadata.
