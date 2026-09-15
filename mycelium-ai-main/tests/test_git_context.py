"""Git read-only context tests (Fase M/Q).

Status/branch/diff from a scratch repo; missing paths refused;
no push/merge/commit surface exists anywhere in the module.
"""

import subprocess

import pytest

from coordinator.app import git_context
from coordinator.app.git_context import git_branch, git_diff, git_status

try:
    subprocess.run(["git", "--version"], capture_output=True, timeout=10)
    GIT_AVAILABLE = True
except (OSError, subprocess.SubprocessError):
    GIT_AVAILABLE = False

needs_git = pytest.mark.skipif(not GIT_AVAILABLE, reason="git missing")


def make_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True,
                   check=True, timeout=30)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=str(path),
                   capture_output=True, check=True, timeout=30)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(path),
                   capture_output=True, check=True, timeout=30)
    (path / "a.txt").write_text("een\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True,
                   check=True, timeout=30)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(path),
                   capture_output=True, check=True, timeout=30)
    (path / "a.txt").write_text("een\ntwee\n", encoding="utf-8")
    return str(path)


@needs_git
def test_status_branch_diff_readonly(tmp_path):
    repo = make_repo(tmp_path / "repo")
    status = git_status(repo)
    assert any("a.txt" in line for line in status["lines"])
    branch = git_branch(repo)
    assert branch["branch"]
    diff = git_diff(repo)
    assert "a.txt" in diff["diff"]


@needs_git
def test_non_git_directory_unavailable(tmp_path):
    with pytest.raises(Exception):
        git_status(str(tmp_path))


def test_missing_path_refused(tmp_path):
    with pytest.raises(ValueError):
        git_status(str(tmp_path / "bestaat-niet"))
    with pytest.raises(ValueError):
        git_branch("")
    with pytest.raises(ValueError):
        git_diff(str(tmp_path / "file.txt"))


def test_no_write_surface_in_module():
    names = set(dir(git_context))
    for banned in ("push", "merge", "commit", "checkout", "pull",
                   "reset", "execute", "run_command"):
        assert banned not in names
    source = open(git_context.__file__, encoding="utf-8").read()
    assert "shell=True" not in source
    assert '"push"' not in source and "'push'" not in source
    assert '"checkout"' not in source and "'checkout'" not in source
