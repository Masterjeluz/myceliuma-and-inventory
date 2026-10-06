"""Workshop, Live, watcher and reports tests (BIG #10).

Graph overlays (nodes/printers), interactive pages, mesh
preview, transform proposals, Live sessions/capabilities/
context, git separation, watcher findings, deterministic
reports, domain extension points.
"""

import os

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "w.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "w-chat.db"))
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "w-fab"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_graph_nodes_printers_overlay(tmp_path, monkeypatch):
    import asyncio
    from coordinator.app.inventory_read import GraphResponse
    from coordinator.app.worldgraph import build_world_graph

    class Reader:
        async def graph(self, entity_id, depth=1):
            return GraphResponse(entity_id=entity_id, depth=depth,
                                 nodes=[], edges=[])

    async def run():
        return await build_world_graph(
            Reader(), "obj_x", 1,
            registry_nodes=[{"node_id": "node-1", "hostname": "h",
                    "tier": "worker", "derived_status": "online",
                    "capabilities": ["a", "b"],
                    "models": [{"model_id": "model:x"}],
                    "last_seen": "2026-01-01T00:00:00+00:00"}],
            printers=[{"printer_id": "prt-1", "name": "P",
                        "status": "registered",
                        "capabilities": ["printer.start"],
                        "inventory_hardware_id": ""}])

    graph = asyncio.run(run())
    node_ids = [node["id"] for node in graph["nodes"]]
    assert "node-1" in node_ids
    assert "prt-1" in node_ids
    node = next(entry for entry in graph["nodes"]
                if entry["id"] == "node-1")
    assert node["source"] == "mycelium"
    assert node["metadata"]["revision"] != ""


def test_graph_page_renders(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        page = test_client.get("/workshop/graph")
        assert page.status_code == 200
        assert "Living Workshop" in page.text
        assert "WORLD (INVENTory)" in page.text
        assert "<svg" in page.text


def test_workshop_pages(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        page = test_client.get("/workshop")
        assert page.status_code == 200
        assert "Keten" in page.text
        page3d = test_client.get("/workshop/3d")
        assert page3d.status_code == 200
        assert "Transformatie-voorstel" in page3d.text
        assert "canvas" in page3d.text


def test_mesh_preview_and_transform(tmp_path, monkeypatch):
    from coordinator.app.mesh3d import ProceduralTestGenerator
    for test_client in make_client(tmp_path, monkeypatch):
        generated = ProceduralTestGenerator().generate("kubus",
                                                       {})
        preview = test_client.get("/api/v1/fab/mesh/preview",
                                  params={
                                      "artifact_ref":
                                      generated.artifact_ref,
                                      "max_tris": 100}).json()
        assert preview["total_tris"] == 12
        assert len(preview["tris"]) == 12
        assert len(preview["tris"][0]) == 3
        refused = test_client.get("/api/v1/fab/mesh/preview",
                                  params={"artifact_ref":
                                          "../x.stl"})
        assert refused.status_code == 422
        # Preview-only transform: nothing persisted.
        moved = test_client.post("/api/v1/fab/transform", json={
            "artifact_ref": generated.artifact_ref,
            "op": "rotate",
            "params": {"axis": "z", "degrees": 90}}).json()
        assert moved["executed"] is False
        assert len(moved["preview_tris"]) == 12
        assert moved["preview_tris"] != preview["tris"]
        bad = test_client.post("/api/v1/fab/transform", json={
            "artifact_ref": generated.artifact_ref,
            "op": "melt", "params": {}})
        assert bad.status_code == 422
        bad2 = test_client.post("/api/v1/fab/transform", json={
            "artifact_ref": generated.artifact_ref,
            "op": "scale", "params": {"factor": 0}})
        assert bad2.status_code == 422
        # Persisted transform: local derived file + payload for
        # the proposal flow, nothing registered automatically.
        kept = test_client.post("/api/v1/fab/transform", json={
            "artifact_ref": generated.artifact_ref,
            "op": "translate",
            "params": {"dx": 5, "dy": 0, "dz": 0},
            "persist": True}).json()
        assert kept["executed"] is True
        assert kept["derived_ref"].startswith("fab-derived-")
        assert kept["file_payload"]["file_kind"] == "mesh"
        assert kept["validation"]["verdict"] == "valid"


def test_live_sessions_and_caps(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        opened = test_client.post("/api/v1/live/sessions", json={
            "interface": "web", "actor": "jelles",
            "capabilities": ["inventory.read", "git.diff"]}).json()
        session_id = opened["session_id"]
        assert session_id.startswith("live-")
        fetched = test_client.get(
            f"/api/v1/live/sessions/{session_id}").json()
        assert fetched["active"] is True
        assert test_client.post(
            "/api/v1/live/sessions/live-missing/revoke"
        ).status_code == 404
        revoked = test_client.post(
            f"/api/v1/live/sessions/{session_id}/revoke").json()
        assert revoked["active"] is False
        assert test_client.get(
            f"/api/v1/live/sessions/{session_id}").status_code == 403
        # git.push is never granted, unknown caps refuse.
        assert test_client.post("/api/v1/live/sessions", json={
            "interface": "web", "actor": "jelles",
            "capabilities": ["git.push"]}).status_code == 422
        assert test_client.post("/api/v1/live/sessions", json={
            "interface": "web", "actor": "jelles",
            "capabilities": ["nope.everything"]}).status_code == 422
        assert test_client.get(
            "/api/v1/live/sessions/live-missing").status_code == 404


def test_live_context_bounded(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-ctx", "hostname": "h",
            "capabilities": []})
        session_id = test_client.post("/api/v1/live/sessions",
                                      json={
                                          "interface": "web",
                                          "actor": "jelles",
                                          "capabilities": [
                                              "node.read",
                                              "task.read"]}).json()[
                                                  "session_id"]
        package = test_client.post("/api/v1/live/context", json={
            "session_id": session_id, "query": "wat draait er?",
            "budget": 2000}).json()
        assert "nodes" in package["sections"]
        assert "tasks" in package["sections"]
        assert "git" not in package["sections"]
        assert package["used"] <= 2000
        assert test_client.post("/api/v1/live/context", json={
            "session_id": "live-missing"}).status_code == 404


def test_live_git_separation(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        session_id = test_client.post("/api/v1/live/sessions",
                                      json={
                                          "interface": "web",
                                          "actor": "jelles",
                                          "capabilities": [
                                              "git.read",
                                              "git.diff",
                                              "git.commit"],
                                          "context_scope": {
                                              "include_git": True}}).json()[
                                                  "session_id"]
        package = test_client.post("/api/v1/live/context", json={
            "session_id": session_id}).json()
        assert "git" in package["sections"]
        # Proposing a commit is allowed; push is not a thing.
        proposed = test_client.post("/api/v1/live/propose", json={
            "session_id": session_id, "kind": "push",
            "target": "main", "payload": {}}).status_code
        assert proposed == 422
        denied = test_client.post("/api/v1/live/propose", json={
            "session_id": session_id, "kind": "inventory_write",
            "target": "inventory:object", "payload": {}})
        assert denied.status_code == 403


def test_live_inventory_propose(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        session_id = test_client.post("/api/v1/live/sessions",
                                      json={
                                          "interface": "web",
                                          "actor": "jelles",
                                          "capabilities": [
                                              "inventory.propose_write"]
                                      }).json()["session_id"]
        proposed = test_client.post("/api/v1/live/propose", json={
            "session_id": session_id, "kind": "inventory_write",
            "target": "inventory:object",
            "payload": {"entity_type": "object",
                        "fields": {"name": "Livebout"}},
            "actor": "jelles"}).json()
        assert proposed["status"] == "proposed"
        assert proposed["proposal"]["provenance"][
            "human_verified"] is False
        assert test_client.post("/api/v1/live/propose", json={
            "session_id": session_id, "kind": "nope",
            "target": "x", "payload": {}}).status_code == 422


def test_watcher_and_reports(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        scanned = test_client.get(
            "/api/v1/watcher/scan").json()
        assert "findings" in scanned
        report = test_client.get(
            "/api/v1/reports/morning").json()
        assert report["sections"]
        titles = [section["title"] for section in
                  report["sections"]]
        assert "Missions" in titles
        assert "Tasks" in titles
        domains = test_client.get("/api/v1/domains").json()
        assert {entry["domain"] for entry in domains} == {
            "health", "skills", "ingestion"}
        assert all(entry["status"] == "planned"
                   for entry in domains)
        assert test_client.get(
            "/api/v1/domains/health").json()["status"] == "planned"
        assert test_client.get(
            "/api/v1/domains/garmin").status_code == 404


def test_library_license_terms_mapping():
    from coordinator.app.workshop3d import license_terms

    nc = license_terms("CC-BY-NC-4.0")
    assert nc["commercial_use"] is False
    assert nc["attribution_required"] is True
    assert nc["known"] is True

    cc0 = license_terms("CC0-1.0")
    assert cc0["commercial_use"] is True
    assert cc0["attribution_required"] is False

    # Unknown license: everything stays undecided, never assumed.
    unknown = license_terms("some-custom-portal-terms-v2")
    assert unknown["known"] is False
    assert unknown["commercial_use"] is None
    assert unknown["remix_allowed"] is None
    assert unknown["attribution_required"] is None


def test_library_license_vague_names_refused():
    from coordinator.app.workshop3d import (
        WorkshopRefusedError,
        clean_library_license,
    )

    for vague in ("open source", "Open-Source", "free",
                  "free for use"):
        try:
            clean_library_license({
                "source_library": "wikimedia-commons",
                "license": vague})
        except WorkshopRefusedError:
            continue
        raise AssertionError(
            f"vague license '{vague}' was accepted")


def test_library_license_required_for_external_origin():
    from coordinator.app.workshop3d import (
        WorkshopRefusedError,
        clean_library_license,
    )

    # External origin without actual license terms is refused.
    try:
        clean_library_license({
            "source_library": "nih-3d",
            "source_url": "https://3d.nih.gov/entries/123",
            "author": "NIH"})
    except WorkshopRefusedError:
        pass
    else:
        raise AssertionError("licenseless import was accepted")

    # Known terms fill only undecided flags; explicit flags win.
    lic = clean_library_license({
        "source_library": "nasa-3d",
        "source_url": "https://science.nasa.gov/3d-resources/moon/",
        "author": "NASA",
        "license": "NASA",
        "original_model_url": "https://science.nasa.gov/x"})
    assert lic.commercial_use is True
    assert lic.attribution_required is False
    assert lic.imported_at != ""

    strict = clean_library_license({
        "source_library": "wikimedia-commons",
        "license": "CC-BY-4.0",
        "commercial_use": False})
    assert strict.commercial_use is False
    assert strict.remix_allowed is True


def test_library_license_attach_and_file_fields(tmp_path,
                                                monkeypatch):
    import coordinator.app.workshop3d as workshop

    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "lic.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "lic-chat.db"))
    record = {
        "model_id": "mdl_lictest01",
        "filename": "moon-far-side.stl",
        "library_ref": "bibliotheek/moon-far-side.stl",
        "mime_type": "model/stl",
        "size_bytes": 84,
        "sha256": "a" * 64,
        "source": "library",
        "status": "imported",
        "inspection": {"mesh_verdict": "UNKNOWN"},
        "license": None,
        "created_at": "2026-10-05T00:00:00+00:00",
        "updated_at": "2026-10-05T00:00:00+00:00",
    }
    workshop._save("workshop_models", "mdl_lictest01",
                   "model_id", record,
                   "2026-10-05T00:00:00+00:00")
    updated = workshop.attach_library_license(
        "mdl_lictest01", {
            "source_library": "nasa-3d",
            "source_url": "https://science.nasa.gov/3d-resources/",
            "author": "NASA",
            "license": "CC-BY-NC-4.0",
            "original_model_url": "https://science.nasa.gov/x"},
        actor="operator")
    assert updated["license"]["license"] == "CC-BY-NC-4.0"
    assert updated["license"]["commercial_use"] is False
    assert updated["license"]["source_library"] == "nasa-3d"

    fields = workshop.library_file_fields(updated)
    block = fields["metadata"]["license"]
    for key in ("source_library", "source_url", "author",
                "license", "commercial_use", "remix_allowed",
                "attribution_required", "original_model_url",
                "imported_at"):
        assert key in block
    assert "NIET toegestaan" in fields["description"]
    assert "CC-BY-NC-4.0" in fields["description"]

    # Model without license keeps the old proposal shape.
    plain = workshop.library_file_fields(record)
    assert "license" not in plain["metadata"]


# -- library import chain (sources -> license -> proposal) ---------------


def _mini_stl() -> bytes:
    """One-triangle binary STL (134 bytes, validator-verdict)."""
    import struct
    return b"\0" * 80 + struct.pack("<I", 1) + b"\0" * 50


def _lib_env(tmp_path, monkeypatch):
    from coordinator.app import forge as forge_mod
    from coordinator.app.workshop3d import setup_library
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "libimp.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "libimp-chat.db"))
    monkeypatch.setenv(forge_mod.LIBRARY_DIR_ENV_VAR,
                       str(tmp_path / "libimp-dir"))
    setup_library()


def _commons_search_json() -> bytes:
    import json
    return json.dumps({"query": {"search": [
        {"ns": 6, "title": "File:Moon test.stl"}]}}).encode()


def _commons_detail_json(license_name="CC BY-SA 4.0") -> bytes:
    import json
    meta = {"Artist": {"value": "Test Maker"},
            "LicenseUrl": {"value": "https://creativecommons.org/x"},
            "UsageTerms": {"value": "Creative Commons"},
            "AttributionRequired": {"value": "true"}}
    if license_name:
        meta["LicenseShortName"] = {"value": license_name}
    return json.dumps({"query": {"pages": {"123": {
        "pageid": 123, "ns": 6, "title": "File:Moon test.stl",
        "imageinfo": [{
            "size": 134,
            "url": ("https://upload.wikimedia.org/wikipedia/"
                    "commons/m/Moon_test.stl"),
            "descriptionurl": ("https://commons.wikimedia.org/"
                               "wiki/File:Moon_test.stl"),
            "extmetadata": meta}]}}}}).encode()


def _fake_http_get_factory(monkeypatch, download_bytes=None,
                           license_name="CC BY-SA 4.0"):
    import coordinator.app.library_sources as libmod

    def _fake(url, *, max_bytes):
        if "list=search" in url:
            return (200, {"content-type": "application/json"},
                    _commons_search_json())
        if "prop=imageinfo" in url:
            return (200, {"content-type": "application/json"},
                    _commons_detail_json(license_name))
        assert download_bytes is not None, url
        if len(download_bytes) > max_bytes:
            raise AssertionError("byte cap bypassed")
        return (200, {"content-type": "model/stl"},
                download_bytes)

    monkeypatch.setattr(libmod, "_http_get", _fake)


def test_library_search_happy_path(tmp_path, monkeypatch):
    import coordinator.app.library_sources as libmod
    _lib_env(tmp_path, monkeypatch)
    _fake_http_get_factory(monkeypatch)
    found = libmod.search_commons("moon")
    assert found["source"] == "wikimedia-commons"
    assert len(found["results"]) == 1
    hit = found["results"][0]
    assert hit["license"] == "CC BY-SA 4.0"
    assert hit["commercial_use"] is True
    assert hit["remix_allowed"] is True
    assert hit["attribution_required"] is True
    assert hit["page_url"].startswith(
        "https://commons.wikimedia.org/wiki/File:")


def test_library_search_marks_unknown_import_blocked(tmp_path,
                                                      monkeypatch):
    import coordinator.app.library_sources as libmod
    _lib_env(tmp_path, monkeypatch)
    # No machine-readable terms at all -> skipped, never listed
    # as permission.
    _fake_http_get_factory(monkeypatch, license_name="")
    found = libmod.search_commons("moon")
    assert found["results"] == []
    # A specific but unknown license is shown honestly (all
    # flags undecided) ...
    _fake_http_get_factory(monkeypatch,
                           license_name="Custom Portal Terms v3")
    found = libmod.search_commons("moon")
    assert len(found["results"]) == 1
    hit = found["results"][0]
    assert hit["commercial_use"] is None
    # ... and the import gate blocks every use until checked.
    try:
        libmod.gate_import(
            {"source_library": "wikimedia-commons",
             "license": hit["license"]},
            intended_use="private")
    except libmod.LibraryRefusedError:
        pass
    else:
        raise AssertionError("unknown license imported")


def test_library_unknown_license_blocks_import(tmp_path,
                                              monkeypatch):
    import coordinator.app.library_sources as libmod
    _lib_env(tmp_path, monkeypatch)
    try:
        libmod.gate_import(
            {"source_library": "nih-3d", "license": "Custom v3"},
            intended_use="private")
    except libmod.LibraryRefusedError:
        pass
    else:
        raise AssertionError("unknown license imported")


def test_library_nc_blocks_commercial(tmp_path, monkeypatch):
    import coordinator.app.library_sources as libmod
    _lib_env(tmp_path, monkeypatch)
    lic = {"source_library": "wikimedia-commons",
           "license": "CC BY-NC 4.0"}
    try:
        libmod.gate_import(lic, intended_use="commercial")
    except libmod.LibraryRefusedError:
        pass
    else:
        raise AssertionError("NC model cleared for sale")
    gated = libmod.gate_import(lic, intended_use="private")
    assert gated["allowed"] is True


def test_library_nd_blocks_remix(tmp_path, monkeypatch):
    import coordinator.app.library_sources as libmod
    _lib_env(tmp_path, monkeypatch)
    lic = {"source_library": "wikimedia-commons",
           "license": "CC BY-ND 4.0"}
    try:
        libmod.gate_import(lic, intended_use="remix")
    except libmod.LibraryRefusedError:
        pass
    else:
        raise AssertionError("ND model cleared for remix")


def test_library_missing_source_license_no_import(tmp_path,
                                                 monkeypatch):
    import coordinator.app.library_sources as libmod
    _lib_env(tmp_path, monkeypatch)
    _fake_http_get_factory(monkeypatch,
                           download_bytes=_mini_stl())
    for bad in ({"source": "no-such-library",
                 "file_url": "https://example.com/x.stl",
                 "license": {"license": "CC0-1.0"}},
                {"source": "nasa-3d",
                 "file_url": "https://science.nasa.gov/x.stl",
                 "license": {"source_library": "nasa-3d"}}):
        try:
            libmod.import_downloaded(
                source=bad["source"], file_url=bad["file_url"],
                license=bad["license"], intended_use="private")
        except (libmod.LibraryRefusedError, ValueError):
            continue
        raise AssertionError(f"import without basis: {bad}")


def test_library_duplicate_sha_no_double_file(tmp_path,
                                              monkeypatch):
    import coordinator.app.library_sources as libmod
    from coordinator.app.workshop3d import library_models
    _lib_env(tmp_path, monkeypatch)
    _fake_http_get_factory(monkeypatch,
                           download_bytes=_mini_stl())
    lic = {"source_library": "nasa-3d", "license": "NASA",
           "original_model_url": "https://science.nasa.gov/m"}
    first = libmod.import_downloaded(
        source="nasa-3d",
        file_url="https://science.nasa.gov/moon.stl",
        filename="moon.stl", license=lic, intended_use="private")
    assert first["model"]["model_id"].startswith("mdl_")
    try:
        libmod.import_downloaded(
            source="nasa-3d",
            file_url="https://science.nasa.gov/moon2.stl",
            filename="moon2.stl", license=lic,
            intended_use="private")
    except libmod.LibraryRefusedError:
        pass
    else:
        raise AssertionError("duplicate bytes registered twice")
    assert len(library_models(limit=10)) == 1


def test_library_provenance_preserved(tmp_path, monkeypatch):
    import coordinator.app.library_sources as libmod
    _lib_env(tmp_path, monkeypatch)
    _fake_http_get_factory(monkeypatch,
                           download_bytes=_mini_stl())
    result = libmod.import_downloaded(
        source="wikimedia-commons",
        file_url=("https://upload.wikimedia.org/wikipedia/"
                  "commons/m/Moon_test.stl"),
        license={"source_library": "wikimedia-commons",
                 "source_url": "https://commons.wikimedia.org/",
                 "author": "Test Maker",
                 "license": "CC BY-SA 4.0",
                 "original_model_url": ("https://commons.wikimedia"
                                        ".org/wiki/File:Moon_test"
                                        ".stl")},
        intended_use="private")
    fields = result["fields"]
    block = fields["metadata"]["license"]
    for key in ("source_library", "source_url", "author",
                "license", "commercial_use", "remix_allowed",
                "attribution_required", "original_model_url",
                "imported_at"):
        assert key in block
    assert block["author"] == "Test Maker"
    assert "CC BY-SA 4.0" in fields["description"]
    assert result["model"]["license"]["license"] == "CC BY-SA 4.0"


def test_library_yes_gate_still_required(tmp_path, monkeypatch):
    import pytest
    import coordinator.app.library_sources as libmod
    from coordinator.app.controlled_writes import (
        decide_write,
        request_write_approval,
        revalidate,
    )
    from coordinator.app.inventory_writes import (
        propose_inventory_write,
    )
    _lib_env(tmp_path, monkeypatch)
    _fake_http_get_factory(monkeypatch,
                           download_bytes=_mini_stl())
    result = libmod.import_downloaded(
        source="nasa-3d",
        file_url="https://science.nasa.gov/moon.stl",
        license={"source_library": "nasa-3d", "license": "NASA"},
        intended_use="private")
    proposal = propose_inventory_write(
        "wrt-libgate1", "create", "file", result["fields"],
        actor="bibliotheek-import")
    request = request_write_approval(proposal)
    # Exact YES approves; anything else never executes.
    approved = decide_write(request, proposal, "YES",
                            decided_by="jelles")
    assert approved.approved is True
    rejected = decide_write(request, proposal, "NO")
    with pytest.raises(ValueError, match="Only an approved"):
        revalidate(proposal, rejected)


def test_library_api_and_3d_section(tmp_path, monkeypatch):
    import coordinator.app.library_sources as libmod
    from coordinator.app import forge as forge_mod
    _lib_env(tmp_path, monkeypatch)
    _fake_http_get_factory(monkeypatch,
                           download_bytes=_mini_stl())
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", "test-op")
    for test_client in make_client(tmp_path, monkeypatch):
        catalog = test_client.get(
            "/api/v1/workshop/libraries").json()
        assert {entry["source_library"]
                for entry in catalog["libraries"]} == {
            "wikimedia-commons", "nih-3d", "nasa-3d"}
        searched = test_client.post(
            "/api/v1/workshop/libraries/search",
            json={"source": "wikimedia-commons",
                  "query": "moon"}).json()
        assert len(searched["results"]) == 1
        manual = test_client.post(
            "/api/v1/workshop/libraries/search",
            json={"source": "nih-3d", "query": "moon"}).json()
        assert manual["results"] == []
        assert "hint" in manual
        imported = test_client.post(
            "/api/v1/workshop/libraries/import",
            json={"source": "wikimedia-commons",
                  "file_url": ("https://upload.wikimedia.org/"
                               "wikipedia/commons/m/Moon_test.stl"),
                  "license": {
                      "source_library": "wikimedia-commons",
                      "author": "Test Maker",
                      "license": "CC BY-SA 4.0",
                      "original_model_url": ("https://commons."
                                             "wikimedia.org/wiki/"
                                             "File:Moon_test.stl")},
                  "intended_use": "private"}).json()
        assert imported["model_id"].startswith("mdl_")
        assert imported["proposal_id"].startswith("wrt-")
        page = test_client.get(
            "/3d?lib_source=wikimedia-commons&lib_q=moon").text
        assert "Modelbibliotheken" in page
        assert "Moon test.stl" in page
        assert "Importvoorstel" in page
        assert "JA" in page
