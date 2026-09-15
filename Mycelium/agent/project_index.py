"""Mycelium Desktop Agent — local project index layer.

Builds a deterministic, local-only PROJECT INDEX from discovery.json
without touching user projects. No network, no external APIs, no AI.

Pipeline:  agent.py (scan) -> discovery.json -> project_index.py -> project_index.json

Project IDs are stable: same computer + same path always yields the same ID
(case-insensitive, so Windows path casing cannot fork identities).
The ID scheme is shared with the discovery scanner (agent.stable_id),
which is the single source of truth for ID computation.
"""

from pathlib import Path
import json
from datetime import datetime

from agent import stable_id, SCANNER_NAME

INDEXER_NAME = "mycelium-project-index"
INDEX_VERSION = "1.0.0"
INDEX_SOURCE = "mycelium-desktop-agent:discovery.json"

BASE = Path(__file__).parent
DISCOVERY_PATH = BASE / "discovery.json"
INDEX_PATH = BASE / "project_index.json"


def project_id(computer: str, path_str: str) -> str:
    """Stable project ID. Same computer + same path -> same ID. Never raises."""
    computer = (computer or "unknown").strip() or "unknown"
    path_str = (path_str or "").strip()
    return stable_id(computer, path_str)


def load_discovery(path=None) -> dict:
    """Read a discovery document. Raises FileNotFoundError/ValueError on problems."""
    target = Path(path) if path is not None else DISCOVERY_PATH
    raw = target.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Discovery document is not an object: {target}")
    projects = data.get("projects", [])
    if not isinstance(projects, list):
        raise ValueError(f"Discovery document has no project list: {target}")
    return data


def _normalize_entry(raw: object) -> dict | None:
    """Normalize one discovery entry to index metadata. Returns None when unusable."""
    if not isinstance(raw, dict):
        return None
    path_str = raw.get("path")
    if not isinstance(path_str, str) or not path_str.strip():
        return None
    path_str = path_str.strip()

    types = raw.get("types", [])
    types = list(types) if isinstance(types, list) else []
    types = sorted({str(t) for t in types})

    recognized = raw.get("recognized_files", [])
    recognized = list(recognized) if isinstance(recognized, list) else []
    recognized = sorted({str(f) for f in recognized})

    name = raw.get("name")
    if not isinstance(name, str) or not name:
        name = Path(path_str).name or path_str

    git_remote = raw.get("git_remote")
    if not isinstance(git_remote, str) or not git_remote.strip():
        git_remote = None
    else:
        git_remote = git_remote.strip()

    last_modified = raw.get("last_modified")
    if not isinstance(last_modified, str):
        last_modified = None

    file_count = raw.get("file_count", 0)
    if isinstance(file_count, bool) or not isinstance(file_count, int):
        try:
            file_count = int(file_count)
        except (TypeError, ValueError):
            file_count = 0
    if file_count < 0:
        file_count = 0

    parent = raw.get("parent_project")
    if not isinstance(parent, str) or not parent.strip():
        parent = None
    else:
        parent = parent.strip()

    return {
        "path": path_str,
        "name": name,
        "types": types,
        "git": bool(raw.get("git", False)),
        "git_remote": git_remote,
        "last_modified": last_modified,
        "file_count": file_count,
        "recognized_files": recognized,
        "is_backup_copy": bool(raw.get("is_backup_copy", False)),
        "is_nested": bool(raw.get("is_nested", False)),
        "parent_project": parent,
    }


def build_index(discovery: dict, indexed_at: str | None = None) -> dict:
    """Build a deterministic project index from a discovery document.

    Pure function of its input (plus indexed_at timestamp): same discovery
    content -> same IDs, same relations, same ordering. Never touches disk.
    """
    if not isinstance(discovery, dict):
        raise ValueError("Discovery document must be an object")
    raw_projects = discovery.get("projects", [])
    if not isinstance(raw_projects, list):
        raise ValueError("Discovery document has no project list")

    computer = discovery.get("computer", "unknown")
    computer = computer if isinstance(computer, str) and computer.strip() else "unknown"
    discovery_timestamp = discovery.get("timestamp")
    if not isinstance(discovery_timestamp, str):
        discovery_timestamp = None
    scanner = discovery.get("scanner")
    scanner = dict(scanner) if isinstance(scanner, dict) else {}
    stamped = indexed_at or datetime.now().isoformat()

    # First pass: normalize + assign stable IDs, dedupe by normalized path.
    by_path: dict[str, dict] = {}
    for raw in raw_projects:
        entry = _normalize_entry(raw)
        if entry is None:
            continue
        key = entry["path"].lower()
        if key in by_path:
            continue  # deterministic: first occurrence wins
        entry["id"] = project_id(computer, entry["path"])
        by_path[key] = entry

    path_to_id = {entry["path"]: entry["id"] for entry in by_path.values()}
    # Parent links may differ in casing from indexed paths (Windows-safe lookup).
    lower_to_id = {entry["path"].lower(): entry["id"] for entry in by_path.values()}

    # Second pass: resolve parent links to IDs.
    for entry in by_path.values():
        parent_id = None
        if entry["parent_project"]:
            parent_id = lower_to_id.get(entry["parent_project"].lower())
        entry["parent_id"] = parent_id

    # Groupings for relations (all lookups case-normalized where applicable).
    by_remote: dict[str, list[str]] = {}
    by_name: dict[str, list[str]] = {}
    children: dict[str, list[str]] = {}
    for entry in by_path.values():
        if entry["git_remote"]:
            by_remote.setdefault(entry["git_remote"], []).append(entry["id"])
        by_name.setdefault(entry["name"].lower(), []).append(entry["id"])
        if entry["parent_id"] is not None:
            children.setdefault(entry["parent_id"], []).append(entry["id"])

    # Third pass: attach relations (sorted ID lists, self excluded).
    index_projects = []
    for entry in sorted(by_path.values(), key=lambda e: e["id"]):
        pid = entry["id"]
        same_remote = sorted(i for i in by_remote.get(entry["git_remote"], []) if i != pid) \
            if entry["git_remote"] else []
        shared_name = sorted(i for i in by_name.get(entry["name"].lower(), []) if i != pid)
        possible_copies = sorted(set(same_remote) | set(shared_name))
        nested_children = sorted(children.get(pid, []))

        index_projects.append({
            "id": pid,
            "path": entry["path"],
            "name": entry["name"],
            "types": entry["types"],
            "git": entry["git"],
            "git_remote": entry["git_remote"],
            "last_modified": entry["last_modified"],
            "file_count": entry["file_count"],
            "recognized_files": entry["recognized_files"],
            "is_backup_copy": entry["is_backup_copy"],
            "is_nested": entry["is_nested"],
            "parent_id": entry["parent_id"],
            "relations": {
                "parent_id": entry["parent_id"],
                "nested_children_ids": nested_children,
                "same_remote_ids": same_remote,
                "shared_name_ids": shared_name,
                "possible_copy_ids": possible_copies,
            },
            "provenance": {
                "source": INDEX_SOURCE,
                "discovery_timestamp": discovery_timestamp,
                "scanner": scanner.get("name", SCANNER_NAME),
                "scanner_version": scanner.get("version"),
                "indexed_at": stamped,
                "indexer": INDEXER_NAME,
                "indexer_version": INDEX_VERSION,
            },
        })

    related = sum(1 for p in index_projects if p["relations"]["possible_copy_ids"])

    return {
        "index_version": INDEX_VERSION,
        "indexer": {"name": INDEXER_NAME, "version": INDEX_VERSION},
        "computer": computer,
        "generated_at": stamped,
        "discovery_timestamp": discovery_timestamp,
        "scanner": scanner,
        "provenance": {
            "source": INDEX_SOURCE,
            "discovery_timestamp": discovery_timestamp,
            "indexed_at": stamped,
            "indexer": INDEXER_NAME,
            "indexer_version": INDEX_VERSION,
        },
        "summary": {
            "total_projects": len(index_projects),
            "git_count": sum(1 for p in index_projects if p["git"]),
            "backup_copy_count": sum(1 for p in index_projects if p["is_backup_copy"]),
            "nested_count": sum(1 for p in index_projects if p["is_nested"]),
            "with_remote_count": sum(1 for p in index_projects if p["git_remote"]),
            "related_count": related,
        },
        "projects": index_projects,
    }


def save_index(index: dict, path=None) -> Path:
    """Write the index as JSON. Only ever writes inside the agent directory by default."""
    target = Path(path) if path is not None else INDEX_PATH
    target.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return target


def load_index(path=None) -> dict:
    target = Path(path) if path is not None else INDEX_PATH
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
        raise ValueError(f"Not a valid project index: {target}")
    return data


def main(discovery_path=None, output_path=None):
    discovery = load_discovery(discovery_path)
    index = build_index(discovery)
    target = save_index(index, output_path)
    summary = index["summary"]
    print(f"Indexed {summary['total_projects']} projects "
          f"({summary['related_count']} with relations).")
    print(f"Saved: {target.resolve()}")
    return index


if __name__ == "__main__":
    main()
