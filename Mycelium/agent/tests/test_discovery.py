"""Tests for the smarter Mycelium Desktop Agent discovery.

All tests use isolated tmp_path fixtures — never the real Desktop,
Documents or Downloads folders. Read-only scanner behavior is verified.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent


def make_project(base: Path, name: str, files: dict | None = None, dirs: list | None = None) -> Path:
    project = base / name
    project.mkdir(parents=True, exist_ok=True)
    for filename, content in (files or {}).items():
        target = project / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    for dirname in dirs or []:
        (project / dirname).mkdir(parents=True, exist_ok=True)
    return project


def write_git_config(project: Path, url: str) -> None:
    git_dir = project / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "config").write_text(
        '[core]\n\trepositoryformatversion = 0\n[remote "origin"]\n\turl = '
        + url
        + "\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n",
        encoding="utf-8",
    )


def by_name(projects: list, name: str) -> dict:
    matches = [p for p in projects if p["name"] == name]
    assert matches, f"expected project {name!r} in results"
    return matches[0]


def test_detect_python_project(tmp_path):
    make_project(tmp_path, "pyproj", files={"pyproject.toml": "[project]\nname='x'\n"})
    projects = agent.find_projects(scan_roots=[tmp_path])
    entry = by_name(projects, "pyproj")
    assert "python" in entry["types"]
    assert entry["git"] is False
    assert entry["path"] == str(tmp_path / "pyproj")


def test_detect_node_project(tmp_path):
    make_project(tmp_path, "nodeproj", files={"package.json": '{"name":"x"}'})
    projects = agent.find_projects(scan_roots=[tmp_path])
    entry = by_name(projects, "nodeproj")
    assert "node" in entry["types"]
    assert "package.json" in entry["recognized_files"]


def test_detect_git_with_remote_safe(tmp_path):
    project = make_project(tmp_path, "gitproj", files={"README.md": "# hi"})
    write_git_config(project, "https://example.com/org/gitproj.git")
    projects = agent.find_projects(scan_roots=[tmp_path])
    entry = by_name(projects, "gitproj")
    assert entry["git"] is True
    assert "git" in entry["types"]
    assert "documented" in entry["types"]
    assert entry["git_remote"] == "https://example.com/org/gitproj.git"


def test_git_without_remote_returns_none(tmp_path):
    make_project(tmp_path, "plainrepo", dirs=[".git"], files={"README.md": "# hi"})
    projects = agent.find_projects(scan_roots=[tmp_path])
    entry = by_name(projects, "plainrepo")
    assert entry["git"] is True
    assert entry["git_remote"] is None


def test_backup_copy_detection(tmp_path):
    make_project(
        tmp_path,
        "INVENTory-Milestone-1E-BACKUP",
        files={"requirements.txt": "flask\n", "README.md": "# backup"},
    )
    projects = agent.find_projects(scan_roots=[tmp_path])
    entry = by_name(projects, "INVENTory-Milestone-1E-BACKUP")
    assert entry["is_backup_copy"] is True


def test_non_backup_not_flagged(tmp_path):
    make_project(tmp_path, "myapp", files={"pyproject.toml": "[project]\n"})
    projects = agent.find_projects(scan_roots=[tmp_path])
    entry = by_name(projects, "myapp")
    assert entry["is_backup_copy"] is False


def test_nested_repository_detection(tmp_path):
    outer = make_project(tmp_path, "outer", files={"README.md": "# outer"})
    write_git_config(outer, "https://example.com/org/outer.git")
    inner = outer / "INVENTory"
    inner.mkdir()
    (inner / "README.md").write_text("# inner", encoding="utf-8")
    (inner / ".git").mkdir()
    projects = agent.find_projects(scan_roots=[tmp_path])
    inner_entry = by_name(projects, "INVENTory")
    outer_entry = by_name(projects, "outer")
    assert inner_entry["is_nested"] is True
    assert inner_entry["parent_project"] == str(outer)
    assert outer_entry["is_nested"] is False
    assert outer_entry["parent_project"] is None


def test_duplicate_name_detection(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    make_project(root_a, "myapp", files={"pyproject.toml": "[project]\n"})
    make_project(root_b, "myapp", files={"package.json": "{}"})
    projects = agent.find_projects(scan_roots=[root_a, root_b])
    matches = [p for p in projects if p["name"] == "myapp"]
    assert len(matches) == 2
    for entry in matches:
        assert entry["duplicate_group"] == "name:myapp"
        assert len(entry["duplicate_candidates"]) == 1


def test_same_remote_candidates(tmp_path):
    url = "https://example.com/org/shared.git"
    first = make_project(tmp_path / "r1", "clone-a", files={"README.md": "# a"})
    second = make_project(tmp_path / "r2", "clone-b", files={"README.md": "# b"})
    write_git_config(first, url)
    write_git_config(second, url)
    projects = agent.find_projects(scan_roots=[tmp_path])
    first_entry = by_name(projects, "clone-a")
    second_entry = by_name(projects, "clone-b")
    assert str(second) in first_entry["same_remote_candidates"]
    assert str(first) in second_entry["same_remote_candidates"]


def test_metadata_fields_present(tmp_path):
    project = make_project(
        tmp_path,
        "meta",
        files={
            "pyproject.toml": "[project]\n",
            "README.md": "# meta",
            "LICENSE": "MIT",
            "src/app.py": "print('hi')\n",
        },
    )
    projects = agent.find_projects(scan_roots=[tmp_path])
    entry = by_name(projects, "meta")
    assert entry["name"] == "meta"
    assert entry["last_modified"] is not None
    assert entry["file_count"] >= 3
    assert "pyproject.toml" in entry["recognized_files"]
    assert "README.md" in entry["recognized_files"]
    assert "LICENSE" in entry["recognized_files"]
    assert project.exists()  # scanner did not remove anything


def test_backward_compatible_keys(tmp_path):
    make_project(tmp_path, "compat", files={"package.json": "{}"})
    projects = agent.find_projects(scan_roots=[tmp_path])
    entry = by_name(projects, "compat")
    assert "path" in entry and isinstance(entry["path"], str)
    assert "types" in entry and isinstance(entry["types"], list)
    assert "git" in entry and isinstance(entry["git"], bool)


def test_provenance_per_project(tmp_path):
    make_project(tmp_path, "prov", files={"README.md": "# p"})
    projects = agent.find_projects(scan_roots=[tmp_path])
    entry = by_name(projects, "prov")
    provenance = entry["provenance"]
    assert provenance["source"] == "local-filesystem-scan"
    assert provenance["found_at"]
    assert provenance["scanner"] == "mycelium-desktop-agent"
    assert provenance["scanner_version"]


def test_inventory_linkage_ready(tmp_path):
    make_project(tmp_path, "linkme", files={"pyproject.toml": "[project]\n"})
    first = agent.find_projects(scan_roots=[tmp_path], computer="PC-TEST")
    second = agent.find_projects(scan_roots=[tmp_path], computer="PC-TEST")
    first_entry = by_name(first, "linkme")
    second_entry = by_name(second, "linkme")
    inventory = first_entry["inventory"]
    assert inventory["entity_type"] == "local_project"
    assert inventory["sync_ready"] is True
    assert inventory["stable_id"]
    # Deterministic: same computer + path gives same id.
    assert inventory["stable_id"] == second_entry["inventory"]["stable_id"]


def test_top_level_result_provenance_and_summary(tmp_path):
    make_project(tmp_path, "top", files={"pyproject.toml": "[project]\n"})
    result = agent.build_result(scan_roots=[tmp_path])
    assert result["timestamp"]
    assert result["computer"]
    assert result["scanner"]["name"] == "mycelium-desktop-agent"
    assert result["scanner"]["mode"] == "local-readonly"
    assert result["scanner"]["source"] == "local-filesystem-scan"
    assert result["scanner"]["version"]
    assert result["scan_roots"] == [str(tmp_path)]
    assert result["summary"]["total_projects"] >= 1
    assert result["summary"]["python_count"] >= 1
    # JSON-serializable for future INVENTory/Mycelium coupling.
    json.dumps(result)


def test_missing_scan_root_skipped(tmp_path):
    missing = tmp_path / "does-not-exist"
    projects = agent.find_projects(scan_roots=[missing])
    assert projects == []


def test_ignored_directories_skipped(tmp_path):
    make_project(
        tmp_path,
        "withvenv",
        files={"pyproject.toml": "[project]\n", ".venv/pyvenv.cfg": "x\n"},
    )
    projects = agent.find_projects(scan_roots=[tmp_path])
    paths = [p["path"] for p in projects]
    assert not any(".venv" in path for path in paths)
