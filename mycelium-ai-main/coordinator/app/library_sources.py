"""External 3D model libraries: search, gated download, import.

One vertical slice on top of existing flows:

    library source -> metadata -> ModelLicense/provenance
    -> explicit download/import -> existing proposal/write flow
    -> INVENTory file_ + workshop mdl_

Rules (fail-closed, tested):

- No second database, no second file registry, no new
  approval flow: models land in the existing library folder,
  records in workshop_models, proposals via
  ``propose_inventory_write`` + the existing YES/write gate.
- Search and download only run on explicit operator action
  (POST routes); nothing polls, syncs or auto-imports.
- "open"/"free"/"open source" never implies sellable or
  remixable: vague names and license-less external origins are
  refused by ``clean_library_license``; unknown terms block
  import until a human reads the actual license.
- Network posture mirrors the research transport: fixed
  per-source host allowlists, timeout <= 5s, byte caps,
  3D content-types only, no credentials, no cookies.
"""

from __future__ import annotations

FETCH_TIMEOUT_SECONDS = 5.0
MAX_API_BYTES = 2 * 1024 * 1024

COMMONS_API_HOST = frozenset({"commons.wikimedia.org"})
COMMONS_FILE_HOSTS = frozenset({"upload.wikimedia.org"})
NIH_FILE_HOSTS = frozenset({"3d.nih.gov"})
NASA_FILE_HOSTS = frozenset({"science.nasa.gov"})

#: Hosts a downloaded model file may come from, per source.
SOURCE_FILE_HOSTS: dict[str, frozenset] = {
    "wikimedia-commons": COMMONS_FILE_HOSTS,
    "nih-3d": NIH_FILE_HOSTS,
    "nasa-3d": NASA_FILE_HOSTS,
}

#: Content-types accepted for model downloads. Generic
#: octet-stream stays allowed (many hosts serve STL that way);
#: HTML/text/JSON are refused so an error page never becomes
#: a "model".
MODEL_CONTENT_TYPES = frozenset({
    "model/stl",
    "model/obj",
    "model/mesh",
    "application/octet-stream",
    "application/sla",
})

INTENDED_USES = ("private", "commercial", "remix")


class LibraryRefusedError(ValueError):
    """Library search/download/import refused; nothing stored."""


LIBRARY_SOURCES: dict[str, dict] = {
    "wikimedia-commons": {
        "source_library": "wikimedia-commons",
        "name": "Wikimedia Commons",
        "portal_url": "https://commons.wikimedia.org/",
        "search": "commons-api",
        "formats": [".stl", ".obj"],
        "license_policy": ("per bestand via API "
                           "(LicenseShortName/UsageTerms)"),
        "automation": "supported",
        "limitations": ("multi-licenties handmatig controleren; "
                        "Artist is HTML; 20 MB-bestandscap"),
    },
    "nih-3d": {
        "source_library": "nih-3d",
        "name": "NIH 3D",
        "portal_url": "https://3d.nih.gov/discover",
        "search": "manual",
        "formats": [".stl", ".glb", ".x3d", ".wrl"],
        "license_policy": ("per entry op de modelpagina lezen; "
                           "varieert van public domain tot "
                           "restrictief"),
        "automation": "manual-only",
        "limitations": ("geen stabiele publieke zoek-API; "
                        "operator neemt licentie over"),
    },
    "nasa-3d": {
        "source_library": "nasa-3d",
        "name": "NASA 3D Resources",
        "portal_url": "https://science.nasa.gov/3d-resources/",
        "search": "manual",
        "formats": [".stl", ".glb", ".usdz"],
        "license_policy": ("uniform: free and without copyright "
                           "(US-overheidswerk); guidelines lezen"),
        "automation": "partial",
        "limitations": ("geen API; GitHub-mirror alleen handmatig"),
    },
}


def library_catalog() -> list[dict]:
    """Registered library sources. Read-only."""
    return [dict({"source_library": key}, **info)
            for key, info in LIBRARY_SOURCES.items()]


def _http_get(url: str, *, max_bytes: int) -> tuple:
    """GET one validated URL. Returns (status, headers, body).
    Separated for tests (monkeypatch this, not httpx)."""
    import httpx
    from .research_transport import validate_url
    canonical = validate_url(url)
    try:
        with httpx.Client(
                timeout=FETCH_TIMEOUT_SECONDS,
                follow_redirects=False,
                headers={"User-Agent": "MyceliumLibrary/1.0 "
                                      "(local-first; contact: "
                                      "operator)"}) as client:
            response = client.get(canonical,
                                  timeout=FETCH_TIMEOUT_SECONDS)
    except Exception as error:
        raise LibraryRefusedError(
            f"ophalen mislukt ({type(error).__name__}; "
            f"offline is eerlijk UNAVAILABLE)") from error
    if response.status_code in (301, 302, 303, 307, 308):
        raise LibraryRefusedError(
            "redirects worden niet gevolgd bij bibliotheek-zoeken")
    if response.status_code != 200:
        raise LibraryRefusedError(
            f"HTTP {response.status_code} bij bibliotheek-aanvraag")
    body = response.content[:max_bytes + 1]
    if len(body) > max_bytes:
        raise LibraryRefusedError(
            f"antwoord groter dan {max_bytes} bytes; geweigerd")
    return (response.status_code, dict(response.headers), body)


def _strip_html(text: str) -> str:
    import re as _re
    return _re.sub(r"<[^>]+>", "", str(text or "")).strip()[:200]


def parse_commons_hits(payload: dict) -> list[dict]:
    """Parse Commons search JSON into candidate pointers. Pure."""
    items = ((payload.get("query", {}) or {}).get("search", [])
             or [])
    out: list[dict] = []
    for item in items:
        title = str(item.get("title", "") or "")
        if not title.startswith("File:"):
            continue
        out.append({
            "title": title,
            "page_url": ("https://commons.wikimedia.org/wiki/"
                         + title.replace(" ", "_")),
        })
    return out[:25]


def parse_commons_detail(title: str, payload: dict) -> dict:
    """Parse imageinfo+extmetadata into a license candidate. Pure.

    Raises LibraryRefusedError when the file has no usable
    license statement (never default to permissive).
    """
    from .workshop3d import clean_library_license, license_terms
    pages = (payload.get("query", {}) or {}).get("pages", {}) or {}
    info: dict = {}
    for page in pages.values():
        entries = page.get("imageinfo", []) or []
        if entries:
            info = entries[0]
            break
    if not info:
        raise LibraryRefusedError(
            f"geen bestandsinfo voor '{title[:80]}'")
    meta = info.get("extmetadata", {}) or {}

    def _field(name: str) -> str:
        return str((meta.get(name, {}) or {}).get("value", "")
                   or "").strip()

    license_name = _field("LicenseShortName") or _field("UsageTerms")
    if not license_name:
        raise LibraryRefusedError(
            f"'{title[:80]}' heeft geen machineleesbare licentie; "
            f"lees de bestandspagina en neem de voorwaarden over")
    author = _strip_html(_field("Artist"))
    candidate = {
        "source_library": "wikimedia-commons",
        "source_url": "https://commons.wikimedia.org/",
        "author": author,
        "license": license_name,
        "original_model_url": str(info.get("descriptionurl", "")
                                  or "")[:500],
        "commercial_use": None,
        "remix_allowed": None,
        "attribution_required": None,
    }
    required = str(_field("AttributionRequired")).lower()
    if required == "true":
        candidate["attribution_required"] = True
    cleaned = clean_library_license(candidate)
    terms = license_terms(cleaned.license)
    return {
        "title": title,
        "file_url": str(info.get("url", "") or "")[:500],
        "size_bytes": int(info.get("size", 0) or 0),
        "page_url": str(info.get("descriptionurl", "") or "")[:500],
        "preview_url": str(info.get("thumburl", "") or "")[:500],
        "author": cleaned.author,
        "license": cleaned.license,
        "license_url": _field("LicenseUrl")[:500],
        "commercial_use": cleaned.commercial_use,
        "remix_allowed": cleaned.remix_allowed,
        "attribution_required": cleaned.attribution_required,
        "terms_note": terms.get("note", ""),
        "original_model_url": cleaned.original_model_url,
    }


def search_commons(query: str, *, limit: int = 10) -> dict:
    """Search Wikimedia Commons for 3D files. Read-only metadata.

    Runs only on explicit operator action (POST route). Offline
    or API change -> honest refusal, never invented results.
    """
    import json as _json
    import urllib.parse as _urlparse
    from .research_transport import validate_url
    text = str(query or "").strip()
    if not text:
        raise LibraryRefusedError(
            "zoekopdracht is leeg; geweigerd")
    if len(text) > 120:
        raise LibraryRefusedError("zoekopdracht te lang")
    count = max(1, min(int(limit or 10), 25))
    params = _urlparse.urlencode({
        "action": "query", "format": "json", "list": "search",
        "srsearch": text, "srnamespace": 6, "srlimit": count,
    })
    api_url = ("https://commons.wikimedia.org/w/api.php?"
               + params)
    validate_url(api_url, allow_hosts=COMMONS_API_HOST)
    _, _, body = _http_get(api_url, max_bytes=MAX_API_BYTES)
    try:
        payload = _json.loads(body.decode("utf-8", "replace"))
    except ValueError as error:
        raise LibraryRefusedError(
            f"Commons-antwoord onleesbaar ({error})") from error
    hits = parse_commons_hits(payload)
    results: list[dict] = []
    for hit in hits:
        detail_params = _urlparse.urlencode({
            "action": "query", "format": "json",
            "titles": hit["title"], "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "iiextmetadatafilter": ("Artist|LicenseShortName|"
                                    "LicenseUrl|UsageTerms|"
                                    "AttributionRequired"),
        })
        detail_url = ("https://commons.wikimedia.org/w/api.php?"
                      + detail_params)
        validate_url(detail_url, allow_hosts=COMMONS_API_HOST)
        try:
            _, _, detail_body = _http_get(
                detail_url, max_bytes=MAX_API_BYTES)
            detail = _json.loads(
                detail_body.decode("utf-8", "replace"))
            results.append(parse_commons_detail(
                hit["title"], detail))
        except (LibraryRefusedError, ValueError):
            continue
    return {"source": "wikimedia-commons", "query": text,
            "results": results}


def gate_import(license_value, *, intended_use: str) -> dict:
    """Decide whether an import proposal may be built.

    ``intended_use`` is private (print for self), commercial
    (sell) or remix (derive/share). Unknown terms block every
    use; NC blocks commercial; ND blocks remix. Vague or
    missing licenses never reach a proposal.
    """
    from .workshop3d import clean_library_license
    use = str(intended_use or "").strip().lower()
    if use not in INTENDED_USES:
        raise LibraryRefusedError(
            f"intended_use '{use}' onbekend; kies uit "
            f"{list(INTENDED_USES)}")
    cleaned = clean_library_license(license_value)
    if cleaned is None:
        raise LibraryRefusedError(
            "import zonder licentiegegevens is geweigerd")
    terms = {"commercial_use": cleaned.commercial_use,
             "remix_allowed": cleaned.remix_allowed,
             "attribution_required": cleaned.attribution_required}
    if any(value is None for value in terms.values()):
        raise LibraryRefusedError(
            f"licentie '{cleaned.license}' is onbekend voor de "
            f"importketen: lees de voorwaarden en leg commercial_"
            f"use/remix/attributie expliciet vast")
    if use == "commercial" and cleaned.commercial_use is not True:
        raise LibraryRefusedError(
            f"commercieel gebruik geblokkeerd: licentie "
            f"'{cleaned.license}' staat verkoop niet toe")
    if use == "remix" and cleaned.remix_allowed is not True:
        raise LibraryRefusedError(
            f"remix geblokkeerd: licentie '{cleaned.license}' "
            f"staat afgeleiden niet toe")
    note = ""
    if cleaned.attribution_required:
        maker = cleaned.author or cleaned.source_library
        note = f"naamsvermelding verplicht ({maker})"
    return {"allowed": True, "intended_use": use,
            "license": cleaned.model_dump(mode="json"),
            "note": note}


def fetch_model_bytes(file_url: str, *, source: str) -> bytes:
    """Download one model file from its source host. Bounded."""
    from .research_transport import validate_url
    from .workshop3d import MODEL_SUFFIXES
    from .mesh3d import MAX_MESH_BYTES
    hosts = SOURCE_FILE_HOSTS.get(str(source or ""))
    if hosts is None:
        raise LibraryRefusedError(
            f"bron '{source}' onbekend; kies een geregistreerde "
            f"bibliotheek")
    canonical = validate_url(file_url, allow_hosts=hosts)
    lowered = canonical.lower()
    if not lowered.endswith(MODEL_SUFFIXES):
        raise LibraryRefusedError(
            "alleen 3D-modelformaten (.stl/.obj/.3mf/.glb/.gltf); "
            "geen uitvoerbare of andere bestanden")
    _, headers, body = _http_get(canonical,
                                 max_bytes=MAX_MESH_BYTES + 1)
    if len(body) > MAX_MESH_BYTES:
        raise LibraryRefusedError(
            f"model is {len(body)} bytes (max {MAX_MESH_BYTES}); "
            f"geweigerd")
    content_type = str(headers.get("content-type", "")
                       or "").split(";")[0].strip().lower()
    if content_type and content_type not in MODEL_CONTENT_TYPES:
        raise LibraryRefusedError(
            f"content-type '{content_type[:80]}' geweigerd; geen "
            f"modelbytes ontvangen")
    if not body:
        raise LibraryRefusedError("leeg bestand; geweigerd")
    return body


def import_downloaded(*, source: str, file_url: str,
                      filename: str = "",
                      license: dict | None = None,
                      intended_use: str = "private",
                      actor: str = "operator") -> dict:
    """Gated import: license gate -> download -> dedupe ->
    library folder -> mdl_ record -> file_ proposal fields.

    Creates the workshop record but no proposal and no
    INVENTory write: the route builds the proposal through the
    existing write flow (YES-gate untouched).
    """
    import os as _os
    from .workshop3d import (
        _check_library_relname,
        clean_library_license,
        known_model_shas,
        library_file_fields,
        library_scan_dir,
        register_library_model,
    )
    from .mesh3d import MAX_MESH_BYTES
    gated = gate_import(license, intended_use=intended_use)
    data = fetch_model_bytes(file_url, source=source)
    import hashlib as _hashlib
    digest = _hashlib.sha256(data).hexdigest()
    if digest in known_model_shas():
        raise LibraryRefusedError(
            "deze modelbytes zijn al geregistreerd; dubbele "
            "file wordt geweigerd")
    if filename:
        relname = _check_library_relname(filename)
    else:
        tail = file_url.split("?", 1)[0].rstrip("/").rsplit(
            "/", 1)[-1][:200]
        relname = _check_library_relname(tail)
    root = _os.path.abspath(library_scan_dir())
    if not _os.path.isdir(root):
        raise LibraryRefusedError(
            "bibliotheekmap ontbreekt; richt eerst in via setup")
    target = _os.path.abspath(_os.path.join(root, relname))
    if target != root and not target.startswith(root + _os.sep):
        raise LibraryRefusedError(
            "bestandsnaam ontsnapt aan de bibliotheekmap")
    if _os.path.exists(target):
        raise LibraryRefusedError(
            f"'{relname}' bestaat al in de bibliotheekmap; "
            f"hernoem of gebruik het bestaande model")
    if len(data) > MAX_MESH_BYTES:  # pragma: no cover - guarded
        raise LibraryRefusedError("model te groot; geweigerd")
    with open(target, "wb") as handle:
        handle.write(data)
    try:
        record = register_library_model(
            relname, actor=str(actor or "operator")[:40],
            license=gated["license"])
    except Exception:
        try:
            _os.remove(target)
        except OSError:
            pass
        raise
    return {"model": record,
            "fields": library_file_fields(record),
            "gate_note": gated.get("note", "")}
