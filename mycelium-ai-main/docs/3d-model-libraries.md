# 3D-modelbibliotheken — bronnen voor import

Stand: 2026-10-05. Praktijkgeverifieerd: Wikimedia Commons API is live
bevraagd (zoek + licentievelden); NIH 3D en NASA via portal/ToS.
Regel: **"open", "free" of "open source" betekent nooit automatisch
verkoopbaar/remixbaar** — alleen de daadwerkelijke licentievoorwaarden
per model tellen (`workshop3d.ModelLicense`, `license_terms()`).

Importketen: bibliotheekmap (operator downloadt) of expliciete
download-actie → `register_library_model()` / download-import →
`ModelLicense` + sha256 → `library_file_fields()` →
`propose_inventory_write()` → bestaande YES/write-gate (`/writes`) →
INVENTory `file_` + workshop `mdl_`. Geen tweede database, geen
tweede registry, geen nieuwe approval-flow.

## 1. Wikimedia Commons

- **API/download-methode**: open MediaWiki API, geen key, geen login.
  Zoeken: `GET https://commons.wikimedia.org/w/api.php`
  `?action=query&format=json&list=search&srsearch=<trefwoord>`
  `&srnamespace=6&srlimit=<n>`.
  Details per bestand: `?action=query&format=json`
  `&titles=File:<naam>&prop=imageinfo`
  `&iiprop=url|size|extmetadata`
  `&iiextmetadatafilter=Artist|LicenseShortName|LicenseUrl|`
  `UsageTerms|AttributionRequired`.
  Download: `imageinfo[0].url` (host `upload.wikimedia.org`).
- **3D-formaten (voorbeeld)**: `.stl` volop aanwezig
  (bv. `File:Moon elevation.stl`, `File:Apollo 11 landing site 3D.stl`);
  `.obj`/`.3mf` incidenteel. `size` in bytes via API.
- **Licentie-informatie**: `LicenseShortName` (bv. `CC BY-SA 4.0`),
  `LicenseUrl`, `UsageTerms`, `Artist` (HTML), `AttributionRequired`
  (`true`/`false`). Let op: multi-licenties zijn onbetrouwbaar
  per API-docs — bij twijfel de bestandspagina lezen.
- **commercial_use**: per licentie. Voorbeeld Moon elevation.stl:
  CC BY-SA 4.0 → JA (met share-alike bij remix).
- **remix_allowed**: per licentie (BY-SA: JA mits share-alike;
  BY-NC-ND: NEE).
- **attribution_required**: per `AttributionRequired` (meestal JA).
- **Bron-URL**: `https://commons.wikimedia.org/`
- **Originele model-URL**: `imageinfo[0].descriptionurl`
  (bv. `https://commons.wikimedia.org/wiki/File:Moon_elevation.stl`).
- **Beperkingen**: 26 MB-voorbeeld past niet onder de
  `MAX_MESH_BYTES`-cap (20 MB) → zulke bestanden weigeren met reden;
  `Artist` is HTML (alleen tonen, nooit uitvoeren); multi-licenties
  handmatig controleren.
- **Automatisering verantwoord?**: JA voor zoeken + metadata +
  download van `upload.wikimedia.org` (vaste host-allowlist, timeout
  ≤ 5 s, byte-cap, 3D-content-types). Alleen via expliciete
  operatoractie (POST); nooit op de achtergrond.

## 2. NIH 3D (3d.nih.gov)

- **API/download-methode**: portal, geen stabiele publieke JSON-API
  zonder account. Zoeken + download handmatig via
  `https://3d.nih.gov/discover`; operator plakt model-URL en
  licentie in het importvoorstel.
- **3D-formaten (voorbeeld)**: `.stl`, `.glb`, `.x3d`, `.wrl`
  (meeste modellen downloadbaar in meerdere formaten).
- **Licentie-informatie**: per entry op de modelpagina; varieert
  (public domain, CC-BY, maar ook restrictievere voorwaarden).
  ToS: bezoeker moet de licentie per bestand lezen en naleven;
  NIH handhaaft niet namens uploaders.
- **commercial_use**: ONBEKEND tot de entry gelezen is — nooit
  aannemen (ook niet bij "open repository").
- **remix_allowed**: idem ONBEKEND tot gelezen.
- **attribution_required**: idem (CC-BY-entries: JA).
- **Bron-URL**: `https://3d.nih.gov/`
- **Originele model-URL**: de modelpagina op `3d.nih.gov` (operator
  plakt hem; hij wordt als `original_model_url` vastgelegd).
- **Beperkingen**: geen machineleesbare licentie-API; account nodig
  voor uploaden/geavanceerd (niet nodig voor downloaden).
- **Automatisering verantwoord?**: NEE voor zoeken/metadata
  (geen stabiele publieke API). Download van `3d.nih.gov` is
  technisch mogelijk met dezelfde hardening, maar zonder
  machineleesbare licentie blijft de operator verantwoordelijk
  voor het overnemen van de voorwaarden → voorlopig handmatig.

## 3. NASA 3D Resources

- **API/download-methode**: geen API; directe downloads via
  `https://science.nasa.gov/3d-resources/` (bv. Moon near/far side
  `.stl`) en GitHub-mirror `nasa/NASA-3D-Resources` (`.glb`,
  `.usdz`, textures). Operator downloadt, importeert via map of
  expliciete download-actie.
- **3D-formaten (voorbeeld)**: `.stl` (printbaar), `.glb`,
  `.usdz`, textures/images.
- **Licentie-informatie**: "free and without copyright"
  (US-overheidswerk); lees de Usage Guidelines op de site.
- **commercial_use**: JA (zonder copyright; guidelines blijven
  van toepassing).
- **remix_allowed**: JA.
- **attribution_required**: NEE (naamsvermelding gewaardeerd,
  niet wettelijk vereist).
- **Bron-URL**: `https://science.nasa.gov/3d-resources/`
- **Originele model-URL**: de modelpagina op science.nasa.gov
  (operator plakt hem).
- **Beperkingen**: geen API, geen per-model licentieveld
  (uniform beleid i.p.v. per-model metadata); GitHub-mirror is
  handig maar geen canonieke bron.
- **Automatisering verantwoord?**: DEELS — download van
  `science.nasa.gov` met dezelfde hardening is verantwoord;
  licentie blijft uniform beleid (`NASA` in `license_terms()`).
  GitHub-raw-hosts worden NIET automatisch toegelaten
  (allowlist blijft klein); mirror via handmatige download.

## Veldmapping (alle bronnen → ModelLicense)

| Veld | Commons | NIH 3D | NASA |
|---|---|---|---|
| source_library | `wikimedia-commons` | `nih-3d` | `nasa-3d` |
| source_url | API-aanvraag-URL of `commons.wikimedia.org` | modelpagina (operator) | modelpagina (operator) |
| author | `Artist` (tekst, HTML strippen) | entry-auteur (operator) | `NASA` |
| license | `LicenseShortName` | entry-licentie (operator) | `NASA` / `public domain` |
| commercial_use | via `license_terms()` | via `license_terms()` of ONBEKEND | JA |
| remix_allowed | via `license_terms()` | via `license_terms()` of ONBEKEND | JA |
| attribution_required | `AttributionRequired` + `license_terms()` | per entry | NEE |
| original_model_url | `descriptionurl` | modelpagina | modelpagina |
| imported_at | importtijdstip (server) | idem | idem |
| provenance | `file_`-metadata + description (executie-provenance via writes-flow) | idem | idem |
