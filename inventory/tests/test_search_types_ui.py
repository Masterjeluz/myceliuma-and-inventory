"""Tests voor INVENTory MOKERPASS item I — alle SEARCHABLE_TYPES in UI.

Uitsluitend tijdelijke databases via INVENTORY_DATABASE_PATH. Geen echte
gebruikersdata wordt geraakt.
"""
import os

import pytest
from fastapi.testclient import TestClient

EXPECTED_TYPES = ["objects", "projects", "ideas", "relationships",
                  "hardware", "sensors", "cameras", "locations",
                  "models", "tasks", "actuators", "files"]


@pytest.fixture()
def client(tmp_path):
    os.environ["INVENTORY_DATABASE_PATH"] = str(tmp_path / "test_uisearch.db")
    import importlib
    import app.database as db_mod
    import app.main as main_mod
    importlib.reload(db_mod)
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def test_search_filter_lists_all_searchable_types(client):
    res = client.get("/search", params={"q": "leeg"})
    assert res.status_code == 200
    for entity_type in EXPECTED_TYPES:
        assert f'value="{entity_type}"' in res.text, entity_type
    res = client.get("/search")
    assert res.status_code == 200
    for entity_type in EXPECTED_TYPES:
        assert f'value="{entity_type}"' in res.text, entity_type


def test_search_type_filter_end_to_end_per_type(client):
    created = client.post("/api/v1/hardware", json={
        "name": "UniekeMokerBoormachine", "category": "tools",
        "description": "mokerpass zoekfilter"}).json()
    assert created["id"].startswith("hw_")
    res = client.get("/api/v1/search",
                     params={"q": "UniekeMokerBoormachine",
                             "type": "hardware"})
    assert res.status_code == 200
    assert any(item["entity_id"] == created["id"]
               for item in res.json()["results"])
    page = client.get("/search",
                      params={"q": "UniekeMokerBoormachine",
                              "type": "hardware"})
    assert page.status_code == 200
    assert created["id"] in page.text
    assert 'value="hardware" selected' in page.text


def test_search_files_type_filter(client):
    created = client.post("/api/v1/files", json={
        "name": "UniekeMokerBeugel",
        "file_kind": "document",
        "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        "description": "mokerpass bestanden"}).json()
    res = client.get("/api/v1/search",
                     params={"q": "UniekeMokerBeugel", "type": "files"})
    assert res.status_code == 200
    assert any(item["entity_id"] == created["id"]
               for item in res.json()["results"])
