"""Read-only Git context for Mycelium/agent (Fase M).

The agent may look at version control but never change it: this module
exposes exactly three facts — status, current branch, diff — through
fixed git argument lists. There is no push, no merge, no commit, no
checkout and no generic "run this git command" entry point; adding
write access needs an explicit, separately approved capability and
does not exist here.

Rules (tested):

- repository must be an existing local directory; missing paths and
  files fail closed before any process starts.
- only fixed argv lists are ever executed (no shell, no user flags,
  10s timeout); stderr/stdout are size-capped.
- a non-git directory or missing git binary surfaces as
  GitUnavailable, never as a traceback and never as partial output.
- diff output is truncated to DIFF_MAX_CHARS; status lines are
  line-capped. No automatic push exists anywhere in this module.
"""

import os
import subprocess

STATUS_ARGV = ["status", "--porcelain=v1", "-b"]
BRANCH_ARGV = ["branch", "--show-current"]
DIFF_STAT_ARGV = ["diff", "--stat"]
DIFF_ARGV = ["diff", "--no-color", "--no-ext-diff", "--"]
GIT_TIMEOUT_SECONDS = 10.0
DIFF_MAX_CHARS = 20000
STATUS_MAX_LINES = 200
BRANCH_MAX_CHARS = 120


class GitUnavailable(RuntimeError):
    """Git context could not be read. Fail-closed, no partial facts."""


class GitRefusedError(ValueError):
    """Local validation refused the request; nothing was executed."""


def _repository_path(repo: str) -> str:
    if not isinstance(repo, str) or not repo.strip():
        raise GitRefusedError("Repository must be non-empty text")
    path = os.path.abspath(repo.strip())
    if not os.path.isdir(path):
        raise GitRefusedError(f"Not a directory: {repo.strip()[:200]}")
    return path


def _run_git(repo: str, argv: list[str]) -> str:
    path = _repository_path(repo)
    try:
        completed = subprocess.run(
            ["git", "-C", path, *argv],
            capture_output=True, text=True,
            timeout=GIT_TIMEOUT_SECONDS, shell=False)
    except FileNotFoundError as error:
        raise GitUnavailable("git binary not available") from error
    except subprocess.TimeoutExpired as error:
        raise GitUnavailable("git timed out") from error
    except OSError as error:
        raise GitUnavailable(f"git could not run: {error}") from error
    if completed.returncode != 0:
        raise GitUnavailable(
            f"git refused: {(completed.stderr or '').strip()[:200]}")
    return completed.stdout or ""


def git_status(repo: str) -> dict:
    """Porcelain status, line-capped. Read-only."""
    output = _run_git(repo, STATUS_ARGV)
    lines = [line for line in output.splitlines() if line.strip()]
    return {"repository": _repository_path(repo),
            "lines": lines[:STATUS_MAX_LINES],
            "truncated": len(lines) > STATUS_MAX_LINES}


def git_branch(repo: str) -> dict:
    """Current branch name. Read-only."""
    output = _run_git(repo, BRANCH_ARGV)
    return {"repository": _repository_path(repo),
            "branch": output.strip()[:BRANCH_MAX_CHARS] or "(geen branch)"}


def git_diff(repo: str, stat_only: bool = True) -> dict:
    """Diff stat (default) or full capped diff. Read-only, never pushed."""
    argv = DIFF_STAT_ARGV if stat_only else DIFF_ARGV
    output = _run_git(repo, argv)
    truncated = len(output) > DIFF_MAX_CHARS
    return {"repository": _repository_path(repo),
            "diff": output[:DIFF_MAX_CHARS],
            "truncated": truncated}
