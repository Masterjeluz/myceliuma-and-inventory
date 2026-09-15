"""Tests for the M2B mapping store (mapping_store.py).

Memory-only or tmp_path only. The real default store file inside agent/ is
never created by these tests.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import mapping_store
from mapping_store import DEFAULT_STORE_PATH, MappingStore


def approval():
    return {"approved": True, "action": "import_project_to_inventory",
            "target": "C:/dev/alpha", "request_id": "test"}


def test_memory_store_roundtrip():
    store = MappingStore()
    assert store.save() is None
    store.record("abc123", "C:/dev/alpha", "proposed", approval=approval())
    row = store.get("abc123")
    assert row["stable_id"] == "abc123"
    assert row["desktop_path"] == "C:/dev/alpha"
    assert row["mapping_status"] == "proposed"
    assert row["inventory_project_id"] is None
    assert row["approval"] == approval()
    assert row["provenance"]["source"] == "mycelium-desktop-agent:mapping-store"
    assert row["created_at"] and row["updated_at"] and row["source"]


def test_file_roundtrip_in_tmp_path(tmp_path):
    store = MappingStore(tmp_path / "mappings.json")
    store.record("abc123", "C:/dev/alpha", "conflict", approval={"approved": False})
    store.save()
    reloaded = MappingStore(tmp_path / "mappings.json")
    assert reloaded.get("abc123")["mapping_status"] == "conflict"


def test_mark_mapped_stores_proj_id():
    store = MappingStore()
    row = store.mark_mapped("abc123", "C:/dev/alpha", "proj_test123", approval())
    assert row["mapping_status"] == "mapped"
    assert row["inventory_project_id"] == "proj_test123"


def test_mark_mapped_rejects_non_proj_id():
    store = MappingStore()
    with pytest.raises(ValueError):
        store.mark_mapped("abc123", "C:/dev/alpha", "desktop-abc123", approval())


def test_only_mapped_rows_may_carry_inventory_id():
    store = MappingStore()
    with pytest.raises(ValueError):
        store.record("abc123", "C:/dev/alpha", "proposed",
                     inventory_project_id="proj_test123")


def test_unknown_status_rejected():
    store = MappingStore()
    with pytest.raises(ValueError):
        store.record("abc123", "C:/dev/alpha", "canonical")


def test_invalid_store_file_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"nope": true}', encoding="utf-8")
    with pytest.raises(ValueError):
        MappingStore(bad)


def test_default_store_file_is_never_created():
    assert not DEFAULT_STORE_PATH.exists()
    assert mapping_store.DEFAULT_STORE_PATH.parent.name == "agent"
