# Living Workshop (BIG #10)

Eén werkplaats-beeld: uniforme wereldgrafiek + interactieve
workshop-UI + 3D-foundation met transform-voorstellen.
INVENTory blijft de bron van de waarheid; alles anders is
een projectie (overlay), nooit een tweede waarheid.

## Uniforme wereldgrafiek

`build_world_graph` legt overlays over de INVENTory-grafiek:

- missies en agent-nodes (bestaand, BIG #4)
- camera-observaties en fabrications (bestaand)
- **registry-nodes** (`type: node`) en **printers**
  (`type: printer`) — nieuw in BIG #10, alleen tellen en
  korte labels, geen dumps

Elke overlay is begrensd (MAX_NODES/EDGES) en faalt
afzonderlijk zonder de basisgrafiek te breken.
`GET /api/v1/world/graph` serveert het geheel; de
interactieve pagina staat op `/workshop/graph`.

## Workshop-pagina's (server-rendered, geen framework)

- `/workshop` — overzicht: taken, fabrications, grafiek-
  ingang, 3D-ingang
- `/workshop/graph` — entity/depth-formulier + node/edge-
  tellingen met overlay-herkomst
- `/workshop/3d` — mesh-preview, transform-voorstel
  (scale/translate/rotate/mirror, factor-begrensd),
  optioneel lokaal persisteren als werkbestand

## 3D-transform als voorstel

`POST /api/v1/fab/transform` geeft altijd eerst een
preview (driehoeken afgekapt, geen verrassingen). Met
`persist: true` ontstaat een lokaal afgeleid STL-werkbestand
(`fab-derived-*`), direct gevalideerd. Registratie in
INVENTory loopt daarna nog steeds via de BIG #5
file-proposal-flow — een werkbestand is geen bewijs, geen
printopdracht, geen waarheid.

## Toekomst-domeinen (alleen extensiepunten)

`GET /api/v1/domains` somt `health`, `skills`, `ingestion`
op als gecontracteerde placeholders: naam, status,
capabilities, expliciete `requirements`-tekst. Geen
Garmin/Instagram/native apps, geen CAD-kernel, geen
printer-SDK — alleen de plek waar zo'n domein later mag
landen zonder de kern te breken.
