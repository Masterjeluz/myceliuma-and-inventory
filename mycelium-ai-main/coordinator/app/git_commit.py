"""Git controlled-commit capability (BIG #5).

The read-only context (``git_context.py``: status/branch/diff)
stays exactly as it is. This module adds ONE write capability —
create a commit — behind the same proposal/approval/fingerprint
machinery as every other controlled write.

What is NOT here (deliberately, no exceptions):

- no push, no fetch, no force-push, no branch deletion;
- no checkout, no merge, no arbitrary git command;
- no shell: only fixed argv lists through ``subprocess.run``
  with ``shell=False`` and a 10s timeout;
- no credential or secret handling of any kind.

A commit executes only when ALL of these hold:

- the repository is on an explicit operator allow-list
  (``MYCELIUM_GIT_WRITE_REPOS``, OS path separator; default
  empty means everything refuses);
- the WriteApproval binds to the exact proposal (fingerprint,
  non-stale) via ``controlled_writes.revalidate``;
- the current branch matches and HEAD still equals expected_head;
- every file is inside the repository, relative, without
  traversal, and on the proposal's file allow-list;
- the working tree contains NO changes outside the allow-listed
  files (unexpected changes BLOCK, never auto-commit);
- the message is bounded operator-approved text.

Verification re-reads HEAD, parent and branch afterwards and
compares them — a ``commit`` return code alone never verifies.
"""

import os
import subprocess

from .controlled_writes import (
    WriteApproval,
    WriteProposal,
    WriteResult,
    now,
    propose_write,
    revalidate,
)
from .inventory_read import Provenance

ALLOW_LIST_ENV_VAR = "MYCELIUM_GIT_WRITE_REPOS"
GIT_TIMEOUT_SECONDS = 10.0
MAX_MESSAGE_CHARS = 500
MAX_FILES = 20

STATUS_ARGV = ["status", "--porcelain=v1", "-b"]
HEAD_ARGV = ["rev-parse", "HEAD"]
BRANCH_ARGV = ["branch", "--show-current"]
LOG_ARGV = ["log", "-1", "--format=%H%x00%P%x00%s"]


class GitWriteRefusedError(ValueError):
    """Local validation refused the commit; nothing was executed."""


class GitWriteFailedError(RuntimeError):
    """The commit failed; nothing is verified."""


def allow_listed_repos() -> list[str]:
    """Operator allow-list of writable repositories (absolute paths)."""
    raw = os.environ.get(ALLOW_LIST_ENV_VAR, "")
    repos: list[str] = []
    for entry in raw.split(os.pathsep):
        entry = entry.strip()
        if not entry:
            continue
        path = os.path.abspath(entry)
        if os.path.isdir(path) and path not in repos:
            repos.append(path)
    return repos


def _repository_path(repo: str, allow_list: list[str] | None) -> str:
    if not isinstance(repo, str) or not repo.strip():
        raise GitWriteRefusedError("Repository must be non-empty text")
    path = os.path.abspath(repo.strip())
    allowed = allow_list if allow_list is not None else allow_listed_repos()
    if path not in [os.path.abspath(entry) for entry in allowed]:
        raise GitWriteRefusedError(
            f"Repository '{repo.strip()[:120]}' is not on the "
            "operator write allow-list; refusing")
    if not os.path.isdir(path):
        raise GitWriteRefusedError(f"Not a directory: {path[:200]}")
    if not os.path.isdir(os.path.join(path, ".git")):
        raise GitWriteRefusedError(f"Not a git repository: {path[:200]}")
    return path


def _checked_files(files, repo: str) -> list[str]:
    if not isinstance(files, list) or not files:
        raise GitWriteRefusedError(
            "Commit needs a non-empty file allow-list")
    if len(files) > MAX_FILES:
        raise GitWriteRefusedError(
            f"Too many files (max {MAX_FILES})")
    clean: list[str] = []
    for entry in files:
        if not isinstance(entry, str) or not entry.strip():
            raise GitWriteRefusedError("File entries must be non-empty text")
        text = entry.strip().replace("\\", "/")
        if (text.startswith("/") or text.startswith("~")
                or ".." in text.split("/")):
            raise GitWriteRefusedError(
                f"File '{entry[:120]}' escapes the repository; refusing")
        resolved = os.path.abspath(os.path.join(repo, text))
        if resolved != repo and not resolved.startswith(repo + os.sep):
            raise GitWriteRefusedError(
                f"File '{entry[:120]}' is outside the repository; refusing")
        if text in clean:
            raise GitWriteRefusedError(f"Duplicate file '{text}'")
        clean.append(text)
    return clean


def _checked_message(message: str) -> str:
    if not isinstance(message, str) or not message.strip():
        raise GitWriteRefusedError(
            "Commit message must be non-empty text")
    if len(message.strip()) > MAX_MESSAGE_CHARS:
        raise GitWriteRefusedError(
            f"Commit message exceeds {MAX_MESSAGE_CHARS} characters")
    return message.strip()


def _checked_head(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GitWriteRefusedError("expected_head must be non-empty text")
    text = value.strip()
    if len(text) < 7 or len(text) > 40:
        raise GitWriteRefusedError("expected_head is not a plausible SHA")
    if any(char not in "0123456789abcdef" for char in text.lower()):
        raise GitWriteRefusedError("expected_head is not a hex SHA")
    return text.lower()


def propose_git_commit(proposal_id: str, repository: str, branch: str,
                       expected_head: str, message: str,
                       files: list[str], *,
                       changeset_fingerprint: str,
                       actor: str = "mycelium",
                       allow_list: list[str] | None = None) -> WriteProposal:
    """Build a validated git-commit proposal. Performs nothing.

    ``changeset_fingerprint`` binds the approval to the exact diff
    the human reviewed (e.g. sha256 of the approved diff stat); a
    changed worktree re-fingerprints differently at execution and
    refuses.
    """
    repo = _repository_path(repository, allow_list)
    if not isinstance(branch, str) or not branch.strip():
        raise GitWriteRefusedError("branch must be non-empty text")
    if "/" in branch.strip() or ".." in branch.strip():
        raise GitWriteRefusedError("branch must be a plain branch name")
    head = _checked_head(expected_head)
    text = _checked_message(message)
    clean_files = _checked_files(files, repo)
    if (not isinstance(changeset_fingerprint, str)
            or len(changeset_fingerprint) != 64
            or any(char not in "0123456789abcdef"
                   for char in changeset_fingerprint.lower())):
        raise GitWriteRefusedError(
            "changeset_fingerprint must be a sha256 hex digest")
    payload = {
        "repository": repo,
        "branch": branch.strip(),
        "expected_head": head,
        "message": text,
        "files": clean_files,
        "changeset_fingerprint": changeset_fingerprint.lower(),
    }
    return propose_write(proposal_id, "git.commit",
                         f"git:{repo}", payload, actor=actor)


def capability_for(_proposal: WriteProposal) -> str:
    return "git.write.commit"


def _run_git(repo: str, argv: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", repo, *argv],
            capture_output=True, text=True,
            timeout=GIT_TIMEOUT_SECONDS, shell=False)
    except FileNotFoundError as error:
        raise GitWriteFailedError("git binary not available") from error
    except subprocess.TimeoutExpired as error:
        raise GitWriteFailedError("git timed out") from error
    except OSError as error:
        raise GitWriteFailedError(f"git could not run: {error}") from error
    if completed.returncode != 0:
        raise GitWriteFailedError(
            f"git refused: {(completed.stderr or '').strip()[:200]}")
    return completed.stdout or ""


def read_commit_state(repo: str,
                      allow_list: list[str] | None = None) -> dict:
    """Independent readback of branch, HEAD and worktree. Read-only."""
    path = _repository_path(repo, allow_list)
    head = _run_git(path, HEAD_ARGV).strip()
    branch = _run_git(path, BRANCH_ARGV).strip()
    status = _run_git(path, STATUS_ARGV)
    changed = sorted(
        line[3:].strip() for line in status.splitlines()
        if line.strip() and not line.startswith("##"))
    return {"repository": path, "head": head, "branch": branch,
            "changed_files": changed}


def execute_git_commit(proposal: WriteProposal,
                       approval: WriteApproval, *,
                       allow_list: list[str] | None = None,
                       now_str: str | None = None) -> WriteResult:
    """Execute one approved commit proposal. Fixed argv only.

    Any boundary violation BLOCKs with no commit; transport/git
    failures yield a failed result — never a false success.
    """
    fingerprint = revalidate(proposal, approval,
                             now_str or now())
    if proposal.mutation_type != "git.commit":
        raise GitWriteRefusedError(
            f"Mutation '{proposal.mutation_type}' is not a git commit")
    payload = proposal.payload
    repo = _repository_path(payload.get("repository", ""), allow_list)
    branch = str(payload.get("branch", ""))
    expected_head = _checked_head(payload.get("expected_head", ""))
    message = _checked_message(payload.get("message", ""))
    files = _checked_files(payload.get("files", []), repo)
    before = _git_state_safe(repo, allow_list)
    try:
        _preconditions(repo, branch, expected_head, files, allow_list)
        _run_git(repo, ["add", "--", *files])
        _post_add_check(repo, files, allow_list)
        _run_git(repo, ["commit", "-m", message])
        after_state = read_commit_state(repo, allow_list)
    except (GitWriteRefusedError, GitWriteFailedError) as error:
        return WriteResult(
            proposal_id=proposal.proposal_id,
            fingerprint=fingerprint, outcome="blocked",
            before={"commit_state": before}, after={},
            actor=proposal.actor, executed_at=now(),
            error=str(error)[:2000],
            provenance=Provenance(
                source_type="ai-generated",
                creator_id=proposal.actor, human_verified=False,
                notes="git commit blocked/failed; nothing is verified"),
        )
    log = _run_git(repo, LOG_ARGV)
    parts = log.split("\x00")
    sha = parts[0].strip() if parts else ""
    parent = parts[1].strip() if len(parts) > 1 else ""
    return WriteResult(
        proposal_id=proposal.proposal_id, fingerprint=fingerprint,
        outcome="executed",
        before={"commit_state": before},
        after={"commit_state": after_state, "commit_sha": sha,
               "parent": parent,
               "subject": parts[2].strip() if len(parts) > 2 else ""},
        actor=proposal.actor, executed_at=now(),
        provenance=Provenance(
            source_type="ai-generated", creator_id=proposal.actor,
            human_verified=False,
            notes=f"controlled git commit {proposal.proposal_id}; "
                  "unverified until independent verification"),
    )


def _git_state_safe(repo: str,
                    allow_list: list[str] | None) -> dict:
    try:
        return read_commit_state(repo, allow_list)
    except (GitWriteRefusedError, GitWriteFailedError) as error:
        return {"repository": repo, "read_error": str(error)[:200]}


def _preconditions(repo: str, branch: str, expected_head: str,
                   files: list[str],
                   allow_list: list[str] | None) -> None:
    state = read_commit_state(repo, allow_list)
    if state["branch"] != branch:
        raise GitWriteRefusedError(
            f"Branch is '{state['branch']}'; proposal targets "
            f"'{branch}'; refusing")
    if not state["head"].lower().startswith(expected_head):
        raise GitWriteRefusedError(
            "HEAD moved since approval (expected "
            f"{expected_head[:12]}); refusing")
    unexpected = [entry for entry in state["changed_files"]
                  if entry not in files]
    if unexpected:
        raise GitWriteRefusedError(
            f"Unexpected worktree changes: {unexpected[:5]}; refusing")


def _post_add_check(repo: str, files: list[str],
                      allow_list: list[str] | None) -> None:
    """After staging, the worktree must still show only approved files."""
    state = read_commit_state(repo, allow_list)
    unexpected = [entry for entry in state["changed_files"]
                  if entry not in files]
    if unexpected:
        raise GitWriteRefusedError(
            f"Worktree changed during staging: {unexpected[:5]}; refusing")


def verify_git_commit(request, result: WriteResult, *,
                      allow_list: list[str] | None = None,
                      now_str: str | None = None):
    """Verify one git commit by independent readback (branch, HEAD,
    parent chain). A commit return code alone never verifies."""
    from datetime import datetime, timezone
    from .verification import VerificationResult
    if not isinstance(result, WriteResult):
        raise ValueError("Verification needs a WriteResult")
    if result.proposal_id != request.proposal_id:
        raise ValueError("Verification does not belong to this result")
    if request.result_fingerprint != result.fingerprint:
        raise ValueError("Verification binds to a different result")
    stamp = now_str or datetime.now(timezone.utc).isoformat()
    base = {
        "verification_id": request.verification_id,
        "proposal_id": request.proposal_id,
        "result_fingerprint": request.result_fingerprint,
        "method": "git.readback",
        "expected": dict(request.expected),
        "observer": "mycelium-verifier",
        "provenance": Provenance(
            source_type="sensor-observed",
            creator_id="mycelium-verifier", human_verified=False,
            notes="independent git readback"),
    }
    if result.outcome != "executed":
        return VerificationResult(
            **base, outcome="failed",
            observed={"execution_outcome": result.outcome},
            source="write-result", verified_at=stamp,
            note="execution did not succeed; nothing to verify")
    expected = request.expected
    try:
        state = read_commit_state(
            str(expected.get("repository", "")), allow_list)
    except (GitWriteRefusedError, GitWriteFailedError) as error:
        return VerificationResult(
            **base, outcome="inconclusive",
            observed={"read_error": str(error)[:500]},
            source="git-readback", verified_at=stamp,
            note="repository unreadable; verification inconclusive")
    observed = {
        "repository": state["repository"],
        "branch": state["branch"],
        "head": state["head"],
    }
    sha = str(result.after.get("commit_sha", ""))
    if sha and not state["head"].lower().startswith(sha.lower()[:7]):
        return VerificationResult(
            **base, outcome="failed", observed=observed,
            source="git-readback", verified_at=stamp,
            note="HEAD does not contain the recorded commit; NOT verified")
    checks = [
        ("repository", expected.get("repository"), state["repository"]),
        ("branch", expected.get("branch"), state["branch"]),
    ]
    for label, want, got in checks:
        if want is not None and want != got:
            return VerificationResult(
                **base, outcome="failed", observed=observed,
                source="git-readback", verified_at=stamp,
                note=f"{label} mismatch (expected {want!r}); NOT verified")
    want_parent = str(expected.get("parent", "") or "")
    got_parent = str(result.after.get("parent", "") or "")
    if want_parent and want_parent != got_parent:
        return VerificationResult(
            **base, outcome="failed", observed=observed,
            source="git-readback", verified_at=stamp,
            note="parent mismatch; possible history rewrite; NOT verified")
    return VerificationResult(
        **base, outcome="passed", observed=observed,
        source="git-readback", verified_at=stamp,
        note="independent readback matches repository, branch, HEAD "
             "and parent")
