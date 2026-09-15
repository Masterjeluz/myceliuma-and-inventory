"""Tests for the M2B mapping/import layer (inventory_bridge.py).

Dry-run only: every test uses synthetic index documents or tmp_path fixtures.
No INVENTory process, database, network call or real project path is used.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import inventory_bridge as bridge
from inventory_bridge import (
    MAPPING_STATUSES,
    build_plan,
    classify_entry,
    dry_run,
    new_mapping_record,
)

STAMP = "2026-09-11T00:00:00+00:00"


def now():
    return STAMP


def make_entry(pid, path, name="app", **overrides):
    entry = {
        "id": pid,
        "path": path,
        "name": name,
        "types": ["python"],
        "git": False,
        "git_remote": None,
        "last_modified": None,
        "file_count": 1,
        "recognized_files": [],
        "is_backup_copy": False,
        "is_nested": False,
        "parent_id": None,
        "relations": {
            "parent_id": None,
            "nested_children_ids": [],
            "same_remote_ids": [],
            "shared_name_ids": [],
            "possible_copy_ids": [],
        },
    }
    entry.update(overrides)
    return entry


def make_index(entries, **extra):
    doc = {
        "index_version": "1.0.0",
        "computer": "PC-TEST",
        "provenance": {
            "source": "mycelium-desktop-agent:discovery.json",
            "discovery_timestamp": "2026-09-11T00:00:00",
            "indexed_at": STAMP,
            "indexer": "mycelium-project-index",
            "indexer_version": "1.0.0",
        },
        "projects": entries,
    }
    doc.update(extra)
    return doc


def mapping_by_id(plan, pid):
    matches = [m for m in plan["mappings"] if m["desktop_project_id"] == pid]
    assert matches, f"expected mapping for {pid}"
    return matches[0]


# --- record shape -----------------------------------------------------------

def test_mapping_record_has_required_fields():
    record = new_mapping_record("abc123", "C:/dev/alpha", "proposed", now=now)
    for field in ("desktop_project_id", "desktop_path", "inventory_project_id",
                  "mapping_status", "mapping_reason", "provenance", "created_at"):
        assert field in record, f"missing field {field}"
    assert record["provenance"]["source"] == "mycelium-desktop-agent:inventory-bridge"
    assert record["created_at"] == STAMP


def test_mapping_status_vocabulary():
    assert set(MAPPING_STATUSES) == {
        "unmapped", "proposed", "mapped", "copy",
        "nested", "rejected", "conflict",
    }


def test_fresh_record_defaults_to_unmapped_and_needs_approval():
    record = new_mapping_record("abc123", "C:/dev/alpha", now=now)
    assert record["mapping_status"] == "unmapped"
    assert record["requires_approval"] is True
    assert record["inventory_project_id"] is None


# --- classification ----------------------------------------------------------

def test_clean_project_yields_one_proposed_mapping():
    plan = build_plan(make_index([make_entry("id1", "C:/dev/alpha")]), now=now)
    mapping = mapping_by_id(plan, "id1")
    assert mapping["mapping_status"] == "proposed"
    assert mapping["requires_approval"] is True
    assert mapping["inventory_project_id"] is None
    assert mapping["proposed_inventory_project"] is not None
    assert plan["summary"]["proposed_mappings"] == 1
    assert plan["summary"]["desktop_projects_discovered"] == 1


def test_duplicate_paths_are_deduplicated():
    entries = [
        make_entry("id1", "C:/dev/alpha"),
        make_entry("id1", "C:/dev/alpha"),
    ]
    plan = build_plan(make_index(entries), now=now)
    assert plan["summary"]["desktop_projects_discovered"] == 1
    assert plan["summary"]["duplicate_paths_deduped"] == 1


def test_same_remote_does_not_merge_projects():
    url = "https://example.com/org/shared.git"
    entries = [
        make_entry("id1", "C:/a/one", git_remote=url, git=True, relations={
            "parent_id": None, "nested_children_ids": [],
            "same_remote_ids": ["id2"], "shared_name_ids": [],
            "possible_copy_ids": ["id2"]}),
        make_entry("id2", "C:/b/two", git_remote=url, git=True, relations={
            "parent_id": None, "nested_children_ids": [],
            "same_remote_ids": ["id1"], "shared_name_ids": [],
            "possible_copy_ids": ["id1"]}),
    ]
    plan = build_plan(make_index(entries), now=now)
    first = mapping_by_id(plan, "id1")
    second = mapping_by_id(plan, "id2")
    assert first["mapping_status"] == "conflict"
    assert second["mapping_status"] == "conflict"
    assert first["desktop_project_id"] != second["desktop_project_id"]
    # No silent merge: no shared inventory ID, no proposed project payload.
    assert first["inventory_project_id"] is None
    assert second["inventory_project_id"] is None
    assert first["proposed_inventory_project"] is None
    assert second["proposed_inventory_project"] is None
    assert plan["summary"]["ambiguous_mappings"] == 2


def test_shared_name_alone_is_conflict_not_merge():
    entries = [
        make_entry("id1", "C:/a/app", relations={
            "parent_id": None, "nested_children_ids": [],
            "same_remote_ids": [], "shared_name_ids": ["id2"],
            "possible_copy_ids": ["id2"]}),
        make_entry("id2", "C:/b/app", relations={
            "parent_id": None, "nested_children_ids": [],
            "same_remote_ids": [], "shared_name_ids": ["id1"],
            "possible_copy_ids": ["id1"]}),
    ]
    plan = build_plan(make_index(entries), now=now)
    assert mapping_by_id(plan, "id1")["mapping_status"] == "conflict"
    assert mapping_by_id(plan, "id2")["mapping_status"] == "conflict"


def test_nested_repositories_remain_distinguishable():
    entries = [
        make_entry("outer", "C:/dev/outer", relations={
            "parent_id": None, "nested_children_ids": ["inner"],
            "same_remote_ids": [], "shared_name_ids": [],
            "possible_copy_ids": []}),
        make_entry("inner", "C:/dev/outer/inner", is_nested=True,
                   parent_id="outer", relations={
                       "parent_id": "outer", "nested_children_ids": [],
                       "same_remote_ids": [], "shared_name_ids": [],
                       "possible_copy_ids": []}),
    ]
    plan = build_plan(make_index(entries), now=now)
    inner = mapping_by_id(plan, "inner")
    outer = mapping_by_id(plan, "outer")
    assert inner["mapping_status"] == "nested"
    assert inner["desktop_project_id"] != outer["desktop_project_id"]
    assert inner["evidence"]["parent_id"] == "outer"
    # Nested projects still get their own separate proposal, never folded in.
    assert inner["proposed_inventory_project"] is not None
    assert inner["proposed_inventory_project"]["for_desktop_id"] == "inner"
    assert any(p["desktop_project_id"] == "inner" for p in plan["nested"])
    assert plan["summary"]["nested_mappings"] == 1
    assert plan["summary"]["nested_relationships"] == 1


def test_backup_copy_is_marked_copy_and_not_proposed():
    entry = make_entry("bak1", "C:/backups/app", is_backup_copy=True)
    plan = build_plan(make_index([entry]), now=now)
    mapping = mapping_by_id(plan, "bak1")
    assert mapping["mapping_status"] == "copy"
    assert mapping["requires_approval"] is True
    assert mapping["proposed_inventory_project"] is None
    assert plan["summary"]["copy_mappings"] == 1


def test_ambiguous_mappings_require_approval():
    entry = make_entry("id1", "C:/a/one", relations={
        "parent_id": None, "nested_children_ids": [],
        "same_remote_ids": ["id2"], "shared_name_ids": [],
        "possible_copy_ids": ["id2"]})
    mapping = classify_entry(entry, now=now)
    assert mapping["mapping_status"] == "conflict"
    assert mapping["requires_approval"] is True


def test_existing_mapping_table_links_to_mapped():
    entry = make_entry("id1", "C:/dev/alpha")
    plan = build_plan(make_index([entry]),
                      existing_mappings={"id1": "proj_abc123"},
                      existing_inventory_ids=["proj_abc123"],
                      now=now)
    mapping = mapping_by_id(plan, "id1")
    assert mapping["mapping_status"] == "mapped"
    assert mapping["inventory_project_id"] == "proj_abc123"
    assert mapping["requires_approval"] is False
    assert plan["summary"]["mapped_mappings"] == 1


def test_stored_mapping_to_unknown_inventory_id_becomes_conflict():
    entry = make_entry("id1", "C:/dev/alpha")
    plan = build_plan(make_index([entry]),
                      existing_mappings={"id1": "proj_ghost"},
                      existing_inventory_ids=["proj_real"],
                      now=now)
    mapping = mapping_by_id(plan, "id1")
    assert mapping["mapping_status"] == "conflict"
    assert mapping["inventory_project_id"] is None
    assert mapping["requires_approval"] is True


def test_previously_tracked_without_decision_is_unmapped():
    entry = make_entry("id1", "C:/dev/alpha")
    plan = build_plan(make_index([entry]),
                      existing_mappings={"id1": None},
                      now=now)
    mapping = mapping_by_id(plan, "id1")
    assert mapping["mapping_status"] == "unmapped"
    assert mapping["requires_approval"] is True


# --- provenance ----------------------------------------------------------------

def test_provenance_exists_on_plan_and_every_mapping():
    entries = [make_entry("id1", "C:/dev/alpha"),
               make_entry("bak", "C:/backups/app", is_backup_copy=True)]
    plan = build_plan(make_index(entries), now=now)
    assert plan["provenance"]["source"] == "mycelium-desktop-agent:inventory-bridge"
    assert plan["provenance"]["mode"] == "dry-run-proposal"
    assert plan["provenance"]["created_at"] == STAMP
    for mapping in plan["mappings"]:
        assert mapping["provenance"]["source"] == "mycelium-desktop-agent:inventory-bridge"
        assert mapping["provenance"]["desktop_project_id"] == mapping["desktop_project_id"]
        assert mapping["created_at"] == STAMP
        assert mapping["mapping_reason"]
    for payload in plan["proposed_projects"]:
        assert payload["provenance"]["source_type"] == "imported"
        assert payload["provenance"]["human_verified"] is False


# --- zero writes -----------------------------------------------------------------

def test_dry_run_performs_zero_inventory_writes(tmp_path):
    index_path = tmp_path / "project_index.json"
    index_path.write_text(json.dumps(make_index([make_entry("id1", "C:/dev/alpha")])),
                          encoding="utf-8")
    plan = dry_run(index_path=index_path, now=now)
    assert plan["mode"] == "dry-run"
    assert plan["writes_performed"] == 0
    assert plan["summary"]["writes_performed"] == 0
    assert plan["would_create"]["writes_now"] == 0
    # Only the fixture file we created exists; dry-run wrote nothing new.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["project_index.json"]


def test_bridge_module_has_no_inventory_io():
    source = Path(bridge.__file__).read_text(encoding="utf-8")
    for forbidden in ("import app", "from app", "sqlite3", "http.client",
                      "urllib.request", "requests", "TestClient", "uvicorn"):
        assert forbidden not in source, f"bridge must not use {forbidden}"


def test_existing_inventory_projects_are_not_overwritten():
    entry = make_entry("id1", "C:/dev/alpha")
    plan = build_plan(make_index([entry]),
                      existing_inventory_ids=["proj_existing"],
                      now=now)
    # Create-only payloads: the bridge never assigns or reuses proj_ IDs.
    for payload in plan["proposed_projects"]:
        assert "id" not in payload
    for mapping in plan["mappings"]:
        assert mapping["inventory_project_id"] in (None,)
    operations = {m["mapping_status"] for m in plan["mappings"]}
    assert operations <= set(MAPPING_STATUSES)


# --- invalid input -----------------------------------------------------------------

def test_invalid_entries_are_handled_safely():
    index = make_index([
        make_entry("good", "C:/dev/good"),
        {"no": "id-or-path"},
        "not-a-dict",
        {"id": "nopath"},
    ])
    plan = build_plan(index, now=now)
    # "good" is proposed; {"id": "nopath"} keeps a rejected record (it has an
    # id to key on); the two entries without any id cannot form a mapping and
    # are skipped safely.
    assert plan["summary"]["desktop_projects_discovered"] == 2
    assert mapping_by_id(plan, "good")["mapping_status"] == "proposed"
    rejected = mapping_by_id(plan, "nopath")
    assert rejected["mapping_status"] == "rejected"
    assert rejected["requires_approval"] is False
    assert rejected["proposed_inventory_project"] is None
    assert plan["summary"]["rejected_mappings"] == 1
    assert plan["summary"]["skipped_invalid"] == 2
    assert len(plan["skipped_invalid"]) == 2


def test_rejects_non_index_documents():
    for bad in ("nope", {"projects": "nope"}, {"nothing": []}, None):
        try:
            build_plan(bad, now=now)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {bad!r}")


def test_missing_index_file_raises_without_side_effects(tmp_path):
    try:
        dry_run(index_path=tmp_path / "does-not-exist.json", now=now)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected FileNotFoundError")


# --- dry-run answers ------------------------------------------------------------------

def test_dry_run_answers_all_seven_questions():
    outer = make_entry("outer", "C:/dev/outer", relations={
        "parent_id": None, "nested_children_ids": ["inner"],
        "same_remote_ids": [], "shared_name_ids": [], "possible_copy_ids": []})
    inner = make_entry("inner", "C:/dev/outer/inner", is_nested=True,
                       parent_id="outer", relations={
                           "parent_id": "outer", "nested_children_ids": [],
                           "same_remote_ids": [], "shared_name_ids": [],
                           "possible_copy_ids": []})
    solo = make_entry("solo", "C:/dev/solo")
    plan = build_plan(make_index([outer, inner, solo]), now=now)
    assert len(plan["discovered"]) == 3                      # 1. discovered
    # 2. proposed: solo (clean) + outer (clean parent) + inner (nested but
    #    kept distinguishable with its own separate proposal)
    assert len(plan["proposed_projects"]) == 3
    assert plan["copies"] == []                              # 3. copies
    assert len(plan["nested"]) == 1                          # 4. nested
    assert plan["ambiguous"] == []                           # 5. ambiguous
    assert set(plan["requires_approval"]) == {"outer", "inner", "solo"}  # 6. approval
    assert plan["would_create"]["projects"] == plan["proposed_projects"]  # 7. would-create
    assert plan["would_create"]["relationships"]
    # Whole plan stays machine-readable JSON.
    json.dumps(plan)


def test_plan_json_roundtrip(tmp_path):
    plan = build_plan(make_index([make_entry("id1", "C:/dev/alpha")]), now=now)
    target = tmp_path / "plan.json"
    bridge.save_plan(plan, target)
    assert json.loads(target.read_text(encoding="utf-8"))["summary"]["proposed_mappings"] == 1
