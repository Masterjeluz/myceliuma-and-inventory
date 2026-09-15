"""Tests for the Mycelium project index layer (project_index.py).

All tests are local-only and use synthetic discovery documents or tmp_path
fixtures — never the real Desktop/Documents/Downloads folders and never
the real discovery.json / project_index.json.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent
import project_index
from project_index import build_index, project_id


def make_discovery(paths, computer="PC-TEST", **extra):
    projects = []
    for spec in paths:
        if isinstance(spec, str):
            spec = {"path": spec}
        entry = {
            "path": spec["path"],
            "name": spec.get("name", Path(spec["path"]).name),
            "types": spec.get("types", ["python"]),
            "git": spec.get("git", False),
            "git_remote": spec.get("git_remote"),
            "last_modified": spec.get("last_modified"),
            "file_count": spec.get("file_count", 0),
            "recognized_files": spec.get("recognized_files", []),
            "is_backup_copy": spec.get("is_backup_copy", False),
            "is_nested": spec.get("is_nested", False),
            "parent_project": spec.get("parent_project"),
        }
        projects.append(entry)
    doc = {
        "timestamp": "2026-09-11T00:00:00",
        "computer": computer,
        "scanner": {"name": "mycelium-desktop-agent", "version": "0.2.0",
                    "mode": "local-readonly", "source": "local-filesystem-scan"},
        "projects": projects,
    }
    doc.update(extra)
    return doc


def by_id(index, pid):
    matches = [p for p in index["projects"] if p["id"] == pid]
    assert matches, f"expected id {pid} in index"
    return matches[0]


def test_ids_deterministic_across_builds():
    doc = make_discovery(["C:/dev/alpha", "C:/dev/beta"])
    first = build_index(doc, indexed_at="2026-01-01T00:00:00")
    second = build_index(doc, indexed_at="2026-06-01T00:00:00")
    assert [p["id"] for p in first["projects"]] == [p["id"] for p in second["projects"]]


def test_same_computer_and_path_same_id():
    one = build_index(make_discovery(["C:/dev/alpha"], computer="PC-A"))
    two = build_index(make_discovery(["C:/dev/alpha"], computer="PC-A"))
    assert one["projects"][0]["id"] == two["projects"][0]["id"]


def test_id_case_insensitive_path():
    assert project_id("PC-A", "C:/Dev/Alpha") == project_id("pc-a", "c:/dev/alpha")


def test_different_paths_different_ids():
    doc = make_discovery(["C:/dev/alpha", "C:/dev/beta"])
    ids = [p["id"] for p in build_index(doc)["projects"]]
    assert len(set(ids)) == 2


def test_different_computers_different_ids():
    one = build_index(make_discovery(["C:/dev/alpha"], computer="PC-A"))
    two = build_index(make_discovery(["C:/dev/alpha"], computer="PC-B"))
    assert one["projects"][0]["id"] != two["projects"][0]["id"]


def test_id_matches_scanner_scheme():
    doc = make_discovery(["C:/dev/alpha"], computer="PC-A")
    entry = build_index(doc)["projects"][0]
    assert entry["id"] == agent.stable_id("PC-A", "C:/dev/alpha")


def test_metadata_preserved():
    doc = make_discovery([{
        "path": "C:/dev/alpha", "name": "alpha",
        "types": ["git", "python", "documented"], "git": True,
        "git_remote": "https://example.com/org/alpha.git",
        "last_modified": "2026-09-01T12:00:00",
        "file_count": 42, "recognized_files": ["pyproject.toml", "README.md"],
        "is_backup_copy": True,
    }])
    entry = build_index(doc)["projects"][0]
    assert entry["path"] == "C:/dev/alpha"
    assert entry["name"] == "alpha"
    assert entry["types"] == ["documented", "git", "python"]
    assert entry["git"] is True
    assert entry["git_remote"] == "https://example.com/org/alpha.git"
    assert entry["last_modified"] == "2026-09-01T12:00:00"
    assert entry["file_count"] == 42
    assert entry["recognized_files"] == ["README.md", "pyproject.toml"]
    assert entry["is_backup_copy"] is True


def test_minimal_entry_tolerated():
    doc = {"computer": "PC-X", "projects": [{"path": "C:/dev/min", "types": ["node"], "git": False}]}
    entry = build_index(doc)["projects"][0]
    assert entry["id"] == project_id("PC-X", "C:/dev/min")
    assert entry["name"] == "min"
    assert entry["git_remote"] is None
    assert entry["file_count"] == 0
    assert entry["relations"]["possible_copy_ids"] == []


def test_entries_without_path_skipped():
    doc = {"computer": "PC-X", "projects": [{"types": ["python"]}, "oops",
                                            {"path": "C:/dev/ok", "types": ["python"]}]}
    index = build_index(doc)
    assert [p["path"] for p in index["projects"]] == ["C:/dev/ok"]


def test_nested_relations_resolved_to_ids():
    doc = make_discovery([
        {"path": "C:/dev/outer", "name": "outer", "types": ["git", "documented"],
         "git": True, "is_nested": False, "parent_project": None},
        {"path": "C:/dev/outer/inner", "name": "inner", "types": ["documented"],
         "is_nested": True, "parent_project": "C:/dev/outer"},
    ])
    index = build_index(doc)
    outer_id = project_id("PC-TEST", "C:/dev/outer")
    inner = by_id(index, project_id("PC-TEST", "C:/dev/outer/inner"))
    assert inner["parent_id"] == outer_id
    assert inner["relations"]["parent_id"] == outer_id
    outer = by_id(index, outer_id)
    assert inner["id"] in outer["relations"]["nested_children_ids"]


def test_same_remote_relations():
    url = "https://example.com/org/shared.git"
    doc = make_discovery([
        {"path": "C:/a/one", "name": "one", "types": ["git"], "git": True, "git_remote": url},
        {"path": "C:/b/two", "name": "two", "types": ["git"], "git": True, "git_remote": url},
        {"path": "C:/c/three", "name": "three", "types": ["git"], "git": True,
         "git_remote": "https://example.com/org/other.git"},
    ])
    index = build_index(doc)
    one = by_id(index, project_id("PC-TEST", "C:/a/one"))
    two = by_id(index, project_id("PC-TEST", "C:/b/two"))
    three = by_id(index, project_id("PC-TEST", "C:/c/three"))
    assert one["relations"]["same_remote_ids"] == [two["id"]]
    assert two["relations"]["same_remote_ids"] == [one["id"]]
    assert three["relations"]["same_remote_ids"] == []


def test_shared_name_relations():
    doc = make_discovery([
        {"path": "C:/a/app", "name": "app"},
        {"path": "C:/b/app", "name": "app"},
    ])
    index = build_index(doc)
    first = by_id(index, project_id("PC-TEST", "C:/a/app"))
    second = by_id(index, project_id("PC-TEST", "C:/b/app"))
    assert first["relations"]["shared_name_ids"] == [second["id"]]
    assert second["relations"]["shared_name_ids"] == [first["id"]]


def test_possible_copies_union_of_remote_and_name():
    url = "https://example.com/org/shared.git"
    doc = make_discovery([
        {"path": "C:/a/app", "name": "app", "types": ["git"], "git": True, "git_remote": url},
        {"path": "C:/b/app", "name": "app", "types": ["python"]},
        {"path": "C:/c/solo", "name": "solo", "types": ["python"]},
    ])
    index = build_index(doc)
    first = by_id(index, project_id("PC-TEST", "C:/a/app"))
    second = by_id(index, project_id("PC-TEST", "C:/b/app"))
    solo = by_id(index, project_id("PC-TEST", "C:/c/solo"))
    assert first["relations"]["possible_copy_ids"] == [second["id"]]
    assert second["relations"]["possible_copy_ids"] == [first["id"]]
    assert solo["relations"]["possible_copy_ids"] == []


def test_provenance_present_everywhere():
    index = build_index(make_discovery(["C:/dev/alpha"]))
    assert index["provenance"]["source"] == "mycelium-desktop-agent:discovery.json"
    assert index["provenance"]["indexer"] == "mycelium-project-index"
    assert index["provenance"]["indexer_version"] == project_index.INDEX_VERSION
    assert index["provenance"]["discovery_timestamp"] == "2026-09-11T00:00:00"
    entry = index["projects"][0]
    assert entry["provenance"]["source"] == "mycelium-desktop-agent:discovery.json"
    assert entry["provenance"]["scanner"] == "mycelium-desktop-agent"
    assert entry["provenance"]["scanner_version"] == "0.2.0"
    assert entry["provenance"]["indexed_at"]


def test_full_index_json_deterministic():
    doc = make_discovery(["C:/dev/alpha", "C:/dev/beta"])
    first = json.dumps(build_index(doc, indexed_at="2026-01-01T00:00:00"), sort_keys=True)
    second = json.dumps(build_index(doc, indexed_at="2026-01-01T00:00:00"), sort_keys=True)
    assert first == second


def test_save_load_roundtrip(tmp_path):
    index = build_index(make_discovery(["C:/dev/alpha"]))
    target = tmp_path / "project_index.json"
    project_index.save_index(index, target)
    assert project_index.load_index(target) == index


def test_end_to_end_from_scan(tmp_path):
    (tmp_path / "outer").mkdir()
    (tmp_path / "outer" / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    inner = tmp_path / "outer" / "inner"
    inner.mkdir()
    (inner / "README.md").write_text("# inner\n", encoding="utf-8")
    projects = agent.find_projects(scan_roots=[tmp_path], computer="PC-E2E")
    assert len(projects) == 2
    index = build_index({"computer": "PC-E2E", "timestamp": "t",
                         "scanner": {"name": "x"}, "projects": projects})
    assert index["summary"]["total_projects"] == 2
    assert index["summary"]["nested_count"] == 1
    inner_id = project_id("PC-E2E", str(inner))
    outer_id = project_id("PC-E2E", str(tmp_path / "outer"))
    assert by_id(index, inner_id)["parent_id"] == outer_id


def test_main_writes_output(tmp_path):
    discovery_path = tmp_path / "discovery.json"
    output_path = tmp_path / "project_index.json"
    discovery_path.write_text(json.dumps(make_discovery(["C:/dev/alpha"])), encoding="utf-8")
    index = project_index.main(discovery_path=discovery_path, output_path=output_path)
    assert output_path.exists()
    assert project_index.load_index(output_path)["summary"]["total_projects"] == 1
    assert index["summary"]["total_projects"] == 1


def test_rejects_invalid_documents():
    try:
        build_index({"projects": "nope"})
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for non-list projects")
    try:
        build_index("nope")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for non-object document")
