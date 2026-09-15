# Camera Architecture (BIG #4)

Generieke camera-abstractie voor Mycelium, ontworpen zodat een
Insta360 later als device kan worden geregistreerd zonder de core
opnieuw te ontwerpen. Camera's zijn **observatiebronnen, geen
actuatoren**: vastleggen is lezen, nooit handelen.

## Model

- `CameraDevice`: `cam_*`-id, naam, kinds (gesloten: snapshot,
  webcam, stream, p360), source (manual, usb, insta360), status,
  notities. Registratie is expliciet door de operator.
- Capabilities: `camera.snapshot`, `camera.webcam`,
  `camera.stream`, `camera.360`. Geen wildcards; onbekend = deny.
- `CameraAdapter`: capture-contract (`snapshot(device) ->
  CameraObservation`). De core levert GEEN productie-adapter:
  zonder adapter weigert een snapshot (409) in plaats van beeld
  te verzinnen. `TestCameraAdapter` bestaat alleen voor tests.
- `CameraObservation`: `obs_*`-id, device, kind, lokale
  media-referentie, afmetingen, optionele INVENTory-`file_`-binding,
  `sensor-observed`/ongeverifieerde provenance. Geen automatische
  AI-interpretatie als FACT.
- Media: `%TEMP%/mycelium-cam`, retentie laatste 5, nooit cloud.

## Modi (vandaag vs. later)

| Modus | Vandaag | Later |
|---|---|---|
| snapshot | contract + fail-closed endpoint | echte adapter per runtime |
| webcam | geregistreerd, niet geopend | lokale consumer (UI/visie) |
| stream | geregistreerd, niet gestart | lokale geautoriseerde consumer |
| p360 | geregistreerd | viewer/VLM |

## Read-only discovery

`detect_local_imaging_devices()` somt Windows imaging-devices op
via ctypes/setupapi (namen/paden alleen — geen capture, geen
stream, geen activatie). Een Insta360 in webcam-modus verschijnt
als imaging-device, dus deze detectie is direct herbruikbaar.
Andere platformen melden eerlijk `supported: false`.

## Insta360-roadmap

- **Phase 1** (DONE): device-abstractie, capability-model, adapter-
  contract, source-metadata (`source=insta360`), observatie-contract.
- **Phase 2**: photo/snapshot-ingestie via beoordeelde runtime.
- **Phase 3**: webcam-modus (detectie bestaat al).
- **Phase 4**: lokale live stream naar geautoriseerde consumer.
- **Phase 5**: 360-viewer.
- **Phase 6**: vision/VLM over observaties (mens verifieert).
- **Phase 7**: camera-bewuste missies ("bekijk mijn werkbank via
  de Insta360 en vertel wat je ziet" → observatie → VLM →
  context → advies → missie).

## Security

Geen verborgen activatie · geen remote activatie zonder expliciet
permission-beleid · geen cloud-upload/streaming · geen publieke
exposure · geen open inbound ports · AI verandert nooit zelfstandig
privacy-grenzen · captures blijven lokaal tot een expliciete
toekomstige provider-interface anders toestaat.

## Binding (voorbereid, niet automatisch)

camera → capture → file (`file_`-id, optioneel) → observation →
AI-analyse. Schrijven naar INVENTory gebeurt niet automatisch;
daarvoor geldt ROADMAP-fase C (voorstel → approval → uitvoering).
