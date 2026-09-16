"""Tests voor INVENTory M7.5 — File-entiteit (record only).

Uitsluitend tijdelijke databases via INVENTORY_DATABASE_PATH. Geen echte
gebruikersdata wordt geraakt. Een File-record beschrijft een artefact; deze
tests openen, kopiëren, importeren of lezen geen enkel bestand: alle
SHA-256-waarden zijn vaste teststrings, nooit berekend over echte data.
"""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SHA = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
SHA2 = "5feceb66ffc86f38d952786c6d696c79c2dbc239dd4e91b46729d73a27fb57e9"


@pytest.fixture()
def client(tmp_path):
    os.environ["INVENTORY_DATABASE_PATH"] = str(tmp_path / "test_file.db")
    import importlib
    import app.database as db_mod
    import app.main as main_mod
    importlib.reload(db_mod)
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def make_file(client, **overrides):
    payload = {"name": "behuizing-v3.stl", "file_kind": "mesh",
               "mime_type": "model/stl", "sha256": SHA, "size_bytes": 1048576,
               "description": "behuizing werkplaats-controller"}
    payload.update(overrides)
    res = client.post("/api/v1/files", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def relate(client, from_id, predicate, to_id):
    res = client.post("/api/v1/relationships",
                      json={"from_id": from_id, "predicate": predicate,
                            "to_id": to_id})
    assert res.status_code == 201, res.text
    return res.json()


# =============================================================================
# CRUD
# =============================================================================

def test_create_file(client):
    record = make_file(client, metadata={"bron": "cad-programma"})
    assert record["id"].startswith("file_")
    assert record["name"] == "behuizing-v3.stl"
    assert record["file_kind"] == "mesh"
    assert record["mime_type"] == "model/stl"
    assert record["sha256"] == SHA
    assert record["size_bytes"] == 1048576
    assert record["metadata"] == {"bron": "cad-programma"}


def test_file_ids_unique(client):
    ids = {make_file(client, name=f"Bestand {i}")["id"] for i in range(5)}
    assert len(ids) == 5
    assert all(file_id.startswith("file_") for file_id in ids)


def test_list_files(client):
    make_file(client, name="a.stl", file_kind="mesh")
    make_file(client, name="b.gcode", file_kind="gcode", sha256=SHA2)
    res = client.get("/api/v1/files")
    assert res.status_code == 200
    names = {record["name"] for record in res.json()}
    assert {"a.stl", "b.gcode"} <= names


def test_get_file_detail(client):
    created = make_file(client)
    res = client.get(f"/api/v1/files/{created['id']}")
    assert res.status_code == 200
    assert res.json() == created
    assert client.get("/api/v1/files/file_bestaatniet").status_code == 404


def test_patch_file(client):
    created = make_file(client)
    res = client.patch(f"/api/v1/files/{created['id']}",
                       json={"description": "herziene versie",
                             "sha256": SHA2, "size_bytes": 2097152})
    assert res.status_code == 200
    updated = res.json()
    assert updated["description"] == "herziene versie"
    assert updated["sha256"] == SHA2
    assert updated["size_bytes"] == 2097152
    assert updated["name"] == "behuizing-v3.stl"
    assert client.patch("/api/v1/files/file_bestaatniet",
                        json={"description": "x"}).status_code == 404


def test_delete_file(client):
    created = make_file(client)
    assert client.delete(f"/api/v1/files/{created['id']}").status_code == 204
    assert client.get(f"/api/v1/files/{created['id']}").status_code == 404
    assert client.delete("/api/v1/files/file_bestaatniet").status_code == 404


# =============================================================================
# SHA-256-validatie
# =============================================================================

def test_invalid_sha256_rejected(client):
    for bad in ["", "xyz", "9f86", "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a0",
                "gf86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
                "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a0"
                "extra"]:
        res = client.post("/api/v1/files",
                          json={"name": "x.stl", "sha256": bad})
        assert res.status_code == 422, bad


def test_uppercase_sha256_normalized(client):
    record = make_file(client, sha256=SHA.upper())
    assert record["sha256"] == SHA


def test_sha256_length_and_kind_allowlist(client):
    assert client.post("/api/v1/files",
                       json={"name": "x", "sha256": SHA,
                             "file_kind": "spreadsheet"}).status_code == 422
    for kind in ("cad", "mesh", "gcode", "image", "document", "data", "other"):
        record = make_file(client, name=f"Kind {kind}", file_kind=kind)
        assert record["file_kind"] == kind


# =============================================================================
# Provenance, metadata, events
# =============================================================================

def test_file_provenance_default_and_events(client):
    record = make_file(client)
    assert record["provenance"]["source_type"] == "user-created"
    assert record["provenance"]["human_verified"] is True
    events = client.get("/api/v1/events",
                        params={"entity_id": record["id"]}).json()
    assert events and events[0]["event_type"] == "file_created"


def test_file_ai_provenance_unverified(client):
    record = make_file(client, provenance={"source_type": "ai-generated",
                                           "creator_id": "test-model"})
    assert record["provenance"]["source_type"] == "ai-generated"
    assert record["provenance"]["human_verified"] is False


# =============================================================================
# Relaties (bestaande predicaten, geen nieuwe)
# =============================================================================

def test_file_relationships(client):
    record = make_file(client)
    task = client.post("/api/v1/tasks",
                       json={"name": "Printen", "task_type": "other"}).json()
    obj = client.post("/api/v1/objects", json={"name": "Behuizing"}).json()
    rel_task = relate(client, task["id"], "uses", record["id"])
    assert rel_task["predicate"] == "uses"
    rel_obj = relate(client, record["id"], "related_to", obj["id"])
    assert rel_obj["predicate"] == "related_to"
    linked = {r["to_id"] for r in client.get(
        "/api/v1/relationships", params={"entity_id": record["id"]}).json()}
    assert obj["id"] in linked


# =============================================================================
# Search en graph (M4-integratie)
# =============================================================================

def test_search_finds_file(client):
    record = make_file(client, name="Unieke Beugel", file_kind="cad",
                       mime_type="model/step")
    res = client.get("/api/v1/search", params={"q": "Unieke Beugel"})
    assert res.status_code == 200
    found = {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]}
    assert ("file", record["id"]) in found
    res = client.get("/api/v1/search", params={"q": "model/step", "type": "files"})
    assert res.status_code == 200
    assert {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]} == {
        ("file", record["id"])}


def test_graph_shows_file(client):
    record = make_file(client)
    obj = client.post("/api/v1/objects", json={"name": "Beugel"}).json()
    relate(client, record["id"], "related_to", obj["id"])
    res = client.get("/api/v1/graph", params={"entity_id": record["id"], "depth": 1})
    assert res.status_code == 200
    data = res.json()
    by_id = {n["entity_id"]: n for n in data["nodes"]}
    assert by_id[record["id"]]["entity_type"] == "file"
    assert by_id[record["id"]]["provenance"]["source_type"]
    assert obj["id"] in by_id
    res = client.get("/api/v1/graph", params={"entity_id": obj["id"], "depth": 1})
    assert record["id"] in {n["entity_id"] for n in res.json()["nodes"]}


# =============================================================================
# UI (bestaand server-rendered patroon, met record-only disclaimer)
# =============================================================================

def test_file_ui_pages(client):
    record = make_file(client)
    index = client.get("/files")
    assert index.status_code == 200
    assert "behuizing-v3.stl" in index.text
    assert "leest of wijzigt het daadwerkelijke bestand niet" in index.text
    detail = client.get(f"/files/{record['id']}")
    assert detail.status_code == 200
    assert SHA in detail.text
    assert "leest of wijzigt het daadwerkelijke bestand niet" in detail.text
    assert f"/graph/{record['id']}" in detail.text
    assert client.get("/files/file_bestaatniet").status_code == 404


def test_unknown_file_id_404(client):
    assert client.get("/api/v1/files/file_bestaatniet").status_code == 404


# =============================================================================
# Events change feed: bounded `since` cursor (BIG #10, additief)
# =============================================================================

def test_events_since_cursor_bounded(client):
    first = make_file(client)
    events = client.get("/api/v1/events",
                        params={"entity_id": first["id"]}).json()
    assert events and events[0]["event_type"] == "file_created"
    cursor = events[0]["timestamp"]
    # Nothing newer yet: empty page, no dump.
    assert client.get("/api/v1/events",
                      params={"since": cursor}).json() == []
    make_file(client, name="tweede.stl", sha256=SHA2)
    newer = client.get("/api/v1/events",
                       params={"since": cursor}).json()
    assert newer
    assert all(evt["timestamp"] > cursor for evt in newer)
    # Fail-closed on garbage; limit stays clamped.
    assert client.get("/api/v1/events",
                      params={"since": "geen-tijdstempel"}).status_code == 422
    assert client.get("/api/v1/events",
                      params={"since": cursor, "limit": 1}).json() != []
    capped = client.get("/api/v1/events",
                        params={"since": cursor, "limit": 5000}).json()
    assert len(capped) <= 500


# =============================================================================
# Safety: geen filesystem/network/subprocess-toegang
# =============================================================================

def test_no_filesystem_network_subprocess_access():
    import app.main as main_mod
    import inspect
    source = inspect.getsource(main_mod)
    # Note: `from urllib.parse import parse_qs` is pre-existing form parsing,
    # not network access; only actual network/file/execution calls are banned.
    for token in ("open(", "pathlib", "shutil", "subprocess", "os.system",
                  "socket", "httpx", "requests", "urllib.request", "urlopen",
                  "hashlib"):
        assert token not in source, f"INVENTory app must not use {token}"
    app_file = Path(main_mod.__file__)
    assert app_file.parent.name == "app"


def test_real_inventory_db_untouched():
    real_db = Path("C:/Users/Jelles/Desktop/Projects/myceliuma-and-inventory"
                   "/inventory/data/inventory.db")
    assert real_db.exists()
    assert real_db.stat().st_size == 73728
