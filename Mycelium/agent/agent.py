"""Mycelium Desktop Agent — local-first, read-only discovery scanner.

Scans Desktop, Documents and Downloads for recognizable project folders
and writes a JSON inventory to discovery.json next to this file.

Read-only: never deletes, moves or modifies user projects.
No network, no external APIs, no AI models.
"""

from pathlib import Path
import configparser
import hashlib
import json
import os
from datetime import datetime

SCANNER_NAME = "mycelium-desktop-agent"
SCANNER_MODE = "local-readonly"

HOME = Path.home()

SCAN_ROOTS = [
    HOME / "Desktop",
    HOME / "Documents",
    HOME / "Downloads",
]

IGNORE = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
}

# Marker file/dir -> project type. Original five mappings are kept intact
# for backward compatibility with the Flask UI; the rest only extends.
MARKERS = {
    ".git": "git",
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "requirements.txt": "python",
    "package.json": "node",
    "package-lock.json": "node",
    "yarn.lock": "node",
    "README.md": "documented",
    "README.rst": "documented",
    "README.txt": "documented",
}

# Recognizable project files reported per project (existence only, safe).
RECOGNIZED_FILES = [
    ".git",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "README.md",
    "README.rst",
    "README.txt",
    "LICENSE",
    "LICENSE.md",
    ".gitignore",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Makefile",
]

BACKUP_KEYWORDS = (
    "backup",
    "-bak",
    "_bak",
    ".bak",
    "copy",
    "kopie",
    "-old",
    "_old",
    ".old",
    "(1)",
    "(2)",
    " - copy",
    "_copy",
    "-copy",
)

FILE_COUNT_LIMIT = 5000
GIT_CONFIG_MAX_BYTES = 102_400


def scanner_version() -> str:
    """Single source of truth: agent.json next to this file."""
    try:
        meta = json.loads((Path(__file__).parent / "agent.json").read_text(encoding="utf-8"))
        version = str(meta.get("version", "0.2.0"))
        return version if version else "0.2.0"
    except (OSError, ValueError):
        return "0.2.0"


def computer_name() -> str:
    return (
        os.environ.get("COMPUTERNAME")
        or os.environ.get("COMPUTER")
        or os.environ.get("HOSTNAME")
        or "unknown"
    )


def _is_ignored(path: Path) -> bool:
    return any(part in IGNORE for part in path.parts)


def _detect_types(path: Path) -> list:
    found = []
    for marker, kind in MARKERS.items():
        try:
            if (path / marker).exists() and kind not in found:
                found.append(kind)
        except OSError:
            continue
    return found


def is_backup_copy(path: Path) -> bool:
    name = path.name.lower()
    return any(keyword in name for keyword in BACKUP_KEYWORDS)


def _resolve_git_dir(project_path: Path) -> Path | None:
    """Resolve the .git directory without running any git command.

    Handles both a .git directory and a .git file (worktree/gitlink).
    Returns None when there is no usable git dir. Read-only.
    """
    dot_git = project_path / ".git"
    try:
        if dot_git.is_dir():
            return dot_git
        if dot_git.is_file():
            try:
                content = dot_git.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                return None
            if content.lower().startswith("gitdir:"):
                target = content.split(":", 1)[1].strip()
                candidate = (project_path / target).resolve() if not os.path.isabs(target) else Path(target)
                try:
                    if candidate.is_dir():
                        return candidate
                except OSError:
                    return None
            return None
    except OSError:
        return None
    return None


def read_git_remote_safe(project_path: Path) -> str | None:
    """Read the origin remote URL from .git/config only. No subprocess, no network.

    Returns the URL string or None when absent/unreadable. Never raises.
    """
    try:
        git_dir = _resolve_git_dir(project_path)
        if git_dir is None:
            return None
        config_path = git_dir / "config"
        if not config_path.is_file():
            return None
        if config_path.stat().st_size > GIT_CONFIG_MAX_BYTES:
            return None
        parser = configparser.ConfigParser()
        try:
            parser.read(config_path, encoding="utf-8")
        except (OSError, configparser.Error, UnicodeError):
            return None
        for section in parser.sections():
            if section.strip().lower() == 'remote "origin"':
                try:
                    url = parser.get(section, "url", fallback=None)
                except configparser.Error:
                    url = None
                if url:
                    url = url.strip()
                    return url or None
                return None
        return None
    except OSError:
        return None


def count_files_safe(path: Path, limit: int = FILE_COUNT_LIMIT) -> int:
    """Count files under path, pruning ignored dirs. Capped at limit. Never raises."""
    total = 0
    try:
        for current, dirnames, filenames in os.walk(path, onerror=lambda err: None, followlinks=False):
            # Prune ignored directories to keep scans fast and avoid venv/node_modules noise.
            dirnames[:] = [d for d in dirnames if d not in IGNORE]
            total += len(filenames)
            if total >= limit:
                return limit
    except OSError:
        pass
    return total


def last_modified_safe(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return None


def recognized_files_safe(path: Path) -> list:
    present = []
    for filename in RECOGNIZED_FILES:
        try:
            if (path / filename).exists():
                present.append(filename)
        except OSError:
            continue
    return present


def stable_id(computer: str, path_str: str) -> str:
    digest = hashlib.sha1(f"{computer.lower()}|{path_str.lower()}".encode("utf-8")).hexdigest()
    return digest[:16]


def find_projects(scan_roots=None, found_at: str | None = None, computer: str | None = None) -> list:
    """Scan for projects and enrich each entry with safe metadata.

    Keeps backward-compatible keys: path, types, git.
    Accepts custom scan_roots for testability. Read-only, never raises
    for unreadable directories; those entries are skipped or marked None.
    """
    roots = list(scan_roots) if scan_roots is not None else list(SCAN_ROOTS)
    timestamp = found_at or datetime.now().isoformat()
    host = computer or computer_name()
    version = scanner_version()

    candidates: list[dict] = []

    for root in roots:
        root = Path(root)
        try:
            if not root.exists():
                continue
        except OSError:
            continue

        try:
            entries = root.rglob("*")
        except OSError:
            continue

        for path in entries:
            try:
                if not path.is_dir():
                    continue
            except OSError:
                continue

            if _is_ignored(path):
                continue

            types = _detect_types(path)
            if not types:
                continue

            try:
                path_str = str(path)
            except OSError:
                continue

            has_git = "git" in types
            candidates.append({
                # Backward-compatible keys (used by the Flask UI).
                "path": path_str,
                "types": types,
                "git": has_git,
                # Enriched metadata (all safe, existence/mtime only).
                "name": path.name,
                "git_remote": read_git_remote_safe(path) if has_git else None,
                "last_modified": last_modified_safe(path),
                "file_count": count_files_safe(path),
                "recognized_files": recognized_files_safe(path),
                "is_backup_copy": is_backup_copy(path),
                # Filled in second pass below.
                "is_nested": False,
                "parent_project": None,
                "duplicate_group": None,
                "duplicate_candidates": [],
                "same_remote_candidates": [],
                # Future INVENTory/Mycelium linkage (deterministic, local only).
                "inventory": {
                    "entity_type": "local_project",
                    "stable_id": stable_id(host, path_str),
                    "sync_ready": True,
                },
                # Provenance: locally found, when, by which scanner.
                "provenance": {
                    "source": "local-filesystem-scan",
                    "found_at": timestamp,
                    "scanner": SCANNER_NAME,
                    "scanner_version": version,
                },
            })

    # Deterministic output order.
    candidates.sort(key=lambda item: item["path"].lower())

    # Second pass: nested repositories (a project inside another project).
    path_set = {item["path"] for item in candidates}
    for item in candidates:
        parents = list(Path(item["path"]).parents)
        parent_hit = None
        for parent in parents:
            if str(parent) in path_set:
                # Nearest ancestor wins: parents are ordered nearest-first.
                if parent_hit is None or len(str(parent)) > len(parent_hit):
                    parent_hit = str(parent)
        if parent_hit is not None:
            item["is_nested"] = True
            item["parent_project"] = parent_hit

    # Second pass: possible duplicate locations (same folder name, >1 location).
    by_name: dict[str, list[dict]] = {}
    for item in candidates:
        by_name.setdefault(item["name"].lower(), []).append(item)
    for name_lower, group in by_name.items():
        if len(group) > 1:
            group_id = f"name:{name_lower}"
            for item in group:
                item["duplicate_group"] = group_id
                item["duplicate_candidates"] = sorted(
                    other["path"] for other in group if other["path"] != item["path"]
                )

    # Second pass: same git remote in multiple locations (copies/clones).
    by_remote: dict[str, list[dict]] = {}
    for item in candidates:
        remote = item.get("git_remote")
        if remote:
            by_remote.setdefault(remote, []).append(item)
    for group in by_remote.values():
        if len(group) > 1:
            for item in group:
                item["same_remote_candidates"] = sorted(
                    other["path"] for other in group if other["path"] != item["path"]
                )

    return candidates


def build_result(scan_roots=None) -> dict:
    timestamp = datetime.now().isoformat()
    host = computer_name()
    version = scanner_version()
    roots = [str(Path(r)) for r in (scan_roots if scan_roots is not None else SCAN_ROOTS)]
    projects = find_projects(scan_roots=scan_roots, found_at=timestamp, computer=host)

    duplicate_groups = sorted({p["duplicate_group"] for p in projects if p.get("duplicate_group")})

    return {
        # Backward-compatible top-level keys.
        "timestamp": timestamp,
        "computer": host,
        "projects": projects,
        # Provenance of this scan.
        "scanner": {
            "name": SCANNER_NAME,
            "version": version,
            "mode": SCANNER_MODE,
            "source": "local-filesystem-scan",
        },
        "scan_roots": roots,
        "summary": {
            "total_projects": len(projects),
            "git_count": sum(1 for p in projects if p.get("git")),
            "python_count": sum(1 for p in projects if "python" in p.get("types", [])),
            "node_count": sum(1 for p in projects if "node" in p.get("types", [])),
            "documented_count": sum(1 for p in projects if "documented" in p.get("types", [])),
            "backup_copy_count": sum(1 for p in projects if p.get("is_backup_copy")),
            "nested_count": sum(1 for p in projects if p.get("is_nested")),
            "duplicate_groups": len(duplicate_groups),
        },
    }


def main():
    result = build_result()

    output = Path(__file__).parent / "discovery.json"
    output.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8"
    )

    print(f"Found {len(result['projects'])} project locations.")
    print(f"Saved: {output.resolve()}")


if __name__ == "__main__":
    main()
