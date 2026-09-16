"""Git controlled-commit tests (BIG #5).

Boundary enforcement, approval binding, commit execution with
fixed argv only, and readback verification. Uses disposable
local repositories; nothing is pushed anywhere.
"""

import hashlib
import os
import subprocess

import pytest

from coordinator.app.controlled_writes import (
    decide_write,
    request_write_approval,
    write_fingerprint,
)
from coordinator.app.git_commit import (
    GitWriteFailedError,
    GitWriteRefusedError,
    execute_git_commit,
    propose_git_commit,
    read_commit_state,
    verify_git_commit,
)
from coordinator.app.verification import (
    is_verified,
    new_verification_request,
)


def git(*args, cwd):
    completed = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        timeout=30)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def make_repo(tmp_path, name="repo"):
    repo = tmp_path / name
    repo.mkdir()
    git("init", cwd=str(repo))
    git("config", "user.email", "test@local", cwd=str(repo))
    git("config", "user.name", "test", cwd=str(repo))
    (repo / "notes.txt").write_text("basis\n", encoding="utf-8")
    git("add", "--", "notes.txt", cwd=str(repo))
    git("commit", "-m", "basis", cwd=str(repo))
    return str(repo)


def diff_fingerprint(repo):
    diff = subprocess.run(
        ["git", "-C", repo, "diff", "--stat"],
        capture_output=True, text=True, timeout=30).stdout
    return hashlib.sha256(diff.encode()).hexdigest()


def approve(proposal):
    request = request_write_approval(proposal)
    return decide_write(request, proposal, "YES", decided_by="jelles")


def test_propose_valid_commit(tmp_path):
    repo = make_repo(tmp_path)
    head = git("rev-parse", "HEAD", cwd=repo)
    branch = git("branch", "--show-current", cwd=repo)
    proposal = propose_git_commit(
        "wrt-git1", repo, branch, head, "testcommit",
        ["notes.txt"], changeset_fingerprint="0" * 64,
        actor="t", allow_list=[repo])
    assert proposal.mutation_type == "git.commit"
    assert proposal.provenance.human_verified is False
    assert len(write_fingerprint(proposal)) == 64


def test_repository_outside_allow_list_refused(tmp_path):
    repo = make_repo(tmp_path)
    head = git("rev-parse", "HEAD", cwd=repo)
    branch = git("branch", "--show-current", cwd=repo) or "main"
    with pytest.raises(GitWriteRefusedError, match="allow-list"):
        propose_git_commit(
            "wrt-gitx", repo, branch, head, "x", ["notes.txt"],
            changeset_fingerprint="0" * 64, actor="t",
            allow_list=[str(tmp_path / "elsewhere")])


def test_empty_allow_list_refuses_everything(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_GIT_WRITE_REPOS", "")
    repo = make_repo(tmp_path)
    head = git("rev-parse", "HEAD", cwd=repo)
    with pytest.raises(GitWriteRefusedError, match="allow-list"):
        propose_git_commit(
            "wrt-gity", repo, "main", head, "x", ["notes.txt"],
            changeset_fingerprint="0" * 64, actor="t")


@pytest.mark.parametrize("evil", [
    "../buiten.txt", "/absoluut/pad.txt", "..\\windows.txt",
    "sub/../../ontsnapt.txt",
])
def test_path_traversal_refused(tmp_path, evil):
    repo = make_repo(tmp_path)
    head = git("rev-parse", "HEAD", cwd=repo)
    with pytest.raises(GitWriteRefusedError,
                       match="escapes|outside|plain"):
        propose_git_commit(
            "wrt-gitz", repo, "main", head, "x", [evil],
            changeset_fingerprint="0" * 64, actor="t",
            allow_list=[repo])


def test_successful_commit_and_verification(tmp_path):
    repo = make_repo(tmp_path)
    head = git("rev-parse", "HEAD", cwd=repo)
    branch = git("branch", "--show-current", cwd=repo)
    (open(os.path.join(repo, "nieuw.txt"), "w",
          encoding="utf-8")).write("hallo mycelium\n")
    fingerprint = diff_fingerprint(repo)
    proposal = propose_git_commit(
        "wrt-git2", repo, branch, head, "voeg nieuw bestand toe",
        ["nieuw.txt"], changeset_fingerprint=fingerprint,
        actor="t", allow_list=[repo])
    result = execute_git_commit(
        proposal, approve(proposal), allow_list=[repo])
    assert result.outcome == "executed"
    assert result.after["commit_sha"]
    new_head = git("rev-parse", "HEAD", cwd=repo)
    assert new_head == result.after["commit_sha"]
    # Independent verification passes.
    request = new_verification_request(
        proposal.proposal_id, result.fingerprint, "git.readback",
        {"kind": "commit", "repository": repo, "branch": branch,
         "parent": head})
    verification = verify_git_commit(request, result,
                                     allow_list=[repo])
    assert verification.outcome == "passed"
    assert is_verified(verification) is True


def test_expected_head_mismatch_blocked(tmp_path):
    repo = make_repo(tmp_path)
    branch = git("branch", "--show-current", cwd=repo)
    proposal = propose_git_commit(
        "wrt-git3", repo, branch, "0" * 40, "oude head",
        ["notes.txt"], changeset_fingerprint="0" * 64,
        actor="t", allow_list=[repo])
    result = execute_git_commit(
        proposal, approve(proposal), allow_list=[repo])
    assert result.outcome == "blocked"
    assert "HEAD moved" in result.error


def test_unexpected_worktree_changes_blocked(tmp_path):
    repo = make_repo(tmp_path)
    head = git("rev-parse", "HEAD", cwd=repo)
    branch = git("branch", "--show-current", cwd=repo)
    (open(os.path.join(repo, "goedgekeurd.txt"), "w",
          encoding="utf-8")).write("ok\n")
    (open(os.path.join(repo, "stiekem.txt"), "w",
          encoding="utf-8")).write("niet goedgekeurd\n")
    proposal = propose_git_commit(
        "wrt-git4", repo, branch, head, "alleen goedgekeurd",
        ["goedgekeurd.txt"],
        changeset_fingerprint=diff_fingerprint(repo),
        actor="t", allow_list=[repo])
    result = execute_git_commit(
        proposal, approve(proposal), allow_list=[repo])
    assert result.outcome == "blocked"
    assert "Unexpected" in result.error
    # Nothing was committed.
    assert git("rev-parse", "HEAD", cwd=repo) == head


def test_wrong_branch_blocked(tmp_path):
    repo = make_repo(tmp_path)
    head = git("rev-parse", "HEAD", cwd=repo)
    proposal = propose_git_commit(
        "wrt-git5", repo, "niet-deze-branch", head, "x",
        ["notes.txt"], changeset_fingerprint="0" * 64,
        actor="t", allow_list=[repo])
    result = execute_git_commit(
        proposal, approve(proposal), allow_list=[repo])
    assert result.outcome == "blocked"
    assert "Branch" in result.error


def test_commit_without_approval_raises(tmp_path):
    repo = make_repo(tmp_path)
    head = git("rev-parse", "HEAD", cwd=repo)
    branch = git("branch", "--show-current", cwd=repo)
    proposal = propose_git_commit(
        "wrt-git6", repo, branch, head, "x", ["notes.txt"],
        changeset_fingerprint="0" * 64, actor="t",
        allow_list=[repo])
    request = request_write_approval(proposal)
    rejected = decide_write(request, proposal, "NO")
    with pytest.raises(ValueError, match="Only an approved"):
        execute_git_commit(proposal, rejected, allow_list=[repo])


def test_verification_detects_history_change(tmp_path):
    repo = make_repo(tmp_path)
    head = git("rev-parse", "HEAD", cwd=repo)
    branch = git("branch", "--show-current", cwd=repo)
    (open(os.path.join(repo, "a.txt"), "w",
          encoding="utf-8")).write("a\n")
    proposal = propose_git_commit(
        "wrt-git7", repo, branch, head, "commit a", ["a.txt"],
        changeset_fingerprint=diff_fingerprint(repo),
        actor="t", allow_list=[repo])
    result = execute_git_commit(
        proposal, approve(proposal), allow_list=[repo])
    assert result.outcome == "executed"
    # Expectation names a parent that never existed.
    request = new_verification_request(
        proposal.proposal_id, result.fingerprint, "git.readback",
        {"kind": "commit", "repository": repo, "branch": branch,
         "parent": "f" * 40})
    verification = verify_git_commit(request, result,
                                     allow_list=[repo])
    assert verification.outcome == "failed"
    assert is_verified(verification) is False


def test_no_push_force_or_arbitrary_command_exists():
    import coordinator.app.git_commit as module
    import pathlib
    source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    for token in ('"push"', "'push'", '"fetch"', '"checkout"',
                  '"merge"', '"remote"', '"clone"', '"--force"',
                  "shell=True", "os.system", "eval(", "exec("):
        assert token not in source, f"forbidden token: {token}"
    assert "shell=False" in source


def test_read_commit_state_is_read_only(tmp_path):
    repo = make_repo(tmp_path)
    head = git("rev-parse", "HEAD", cwd=repo)
    state = read_commit_state(repo, allow_list=[repo])
    assert state["head"] == head
    assert state["changed_files"] == []
    assert git("rev-parse", "HEAD", cwd=repo) == head
