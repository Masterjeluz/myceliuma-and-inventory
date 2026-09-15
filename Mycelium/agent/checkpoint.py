"""Local, read-before-write Git checkpoint layer for the Desktop Agent."""

from pathlib import Path
import subprocess
from datetime import datetime, timezone

from permissions import PermissionDeniedError, request_permission

CHECKPOINT_ACTION = "create_git_checkpoint"
CHECKPOINT_COMPONENT = "checkpoint"
CHECKPOINT_SOURCE = "mycelium-desktop-agent:checkpoint"
CHECKPOINT_VERSION = "1.0.0"
GIT_TIMEOUT_SECONDS = 30
FORBIDDEN_GIT_OPERATIONS = {
    "push",
    "reset",
    "clean",
    "rm",
    "stash",
    "checkout",
    "fetch",
    "pull",
}
ALLOWED_GIT_OPERATIONS = {"rev-parse", "status", "branch", "commit"}


class RepositoryError(RuntimeError):
    pass


class DirtyRepositoryError(RepositoryError):
    pass


class UnbornRepositoryError(RepositoryError):
    pass


class RepositoryChangedError(RepositoryError):
    pass


class ForbiddenGitOperationError(RepositoryError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_operation(arguments: list[str]) -> str:
    index = 0
    while index < len(arguments) and arguments[index] == "-c":
        index += 2
    return arguments[index] if index < len(arguments) else ""


def _run_git(repository: Path, arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    operation = _git_operation(arguments)
    if operation not in ALLOWED_GIT_OPERATIONS or operation in FORBIDDEN_GIT_OPERATIONS:
        raise ForbiddenGitOperationError(f"Git operation is not allowed: {operation or 'empty'}")
    if operation == "commit":
        commit_index = arguments.index("commit")
        commit_arguments = arguments[commit_index:]
        forbidden_commit_options = {
            "--amend",
            "--reset-author",
            "--author",
            "--no-gpg-sign",
            "--gpg-sign",
            "--signoff",
            "--reuse-message",
            "--reedit-message",
            "--fixup",
            "--squash",
        }
        if any(argument in forbidden_commit_options for argument in commit_arguments):
            raise ForbiddenGitOperationError("Checkpoint commit uses an unsafe option")
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if check and completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "Git command failed"
        raise RepositoryError(message)
    return completed


def _repository_path(repository) -> Path:
    path = Path(repository).expanduser()
    if not path.exists() or not path.is_dir():
        raise RepositoryError(f"Repository does not exist or is not a directory: {path}")
    return path.resolve()


def inspect_repository(repository) -> dict:
    """Inspect a local Git repository without changing it."""
    path = _repository_path(repository)
    work_tree = _run_git(path, ["rev-parse", "--is-inside-work-tree"]).stdout.strip()
    if work_tree != "true":
        raise RepositoryError(f"Not a Git work tree: {path}")
    root_text = _run_git(path, ["rev-parse", "--show-toplevel"]).stdout.strip()
    root = Path(root_text).resolve()
    status_result = _run_git(path, ["status", "--porcelain=v1", "--untracked-files=all"])
    status = status_result.stdout
    status_lines = [line for line in status.splitlines() if line]
    head_result = _run_git(path, ["rev-parse", "--verify", "HEAD"], check=False)
    head = head_result.stdout.strip() if head_result.returncode == 0 else None
    branch_result = _run_git(path, ["branch", "--show-current"], check=False)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
    if head is None:
        cleanliness = "unborn"
    elif status_lines:
        cleanliness = "dirty"
    else:
        cleanliness = "clean"
    return {
        "path": str(path),
        "root": str(root),
        "is_repository": True,
        "cleanliness": cleanliness,
        "clean": cleanliness == "clean",
        "status": status,
        "status_lines": status_lines,
        "current_head": head,
        "branch": branch or None,
        "inspected_at": _utc_now(),
        "provenance": {
            "source": CHECKPOINT_SOURCE,
            "component": CHECKPOINT_COMPONENT,
            "version": CHECKPOINT_VERSION,
            "mode": "local-git-inspection",
        },
    }


def request_checkpoint_permission(
    repository,
    inspection: dict | None = None,
    details: dict | None = None,
    *,
    input_func=None,
    log_path=None,
) -> dict:
    """Request explicit human permission for a checkpoint commit."""
    path = _repository_path(repository)
    request_details = {
        "reason": "Create a local Git checkpoint before a controlled modification.",
        "inspection": inspection or inspect_repository(path),
    }
    if details:
        request_details.update(details)
    return request_permission(
        CHECKPOINT_ACTION,
        path,
        request_details,
        input_func=input_func,
        log_path=log_path,
    )


def _approval_matches(approval: dict, action: str, target: str) -> bool:
    return (
        isinstance(approval, dict)
        and approval.get("approved") is True
        and approval.get("action") == action
        and approval.get("target") == target
    )


def create_checkpoint(repository, approval: dict | None = None, message: str | None = None, permission_func=request_permission) -> dict:
    """Create one local checkpoint commit after inspection and explicit approval.

    The repository must be clean before permission is requested and again
    immediately before the commit. No remote, destructive, or hook operation is
    used.
    """
    path = _repository_path(repository)
    before = inspect_repository(path)
    if before["cleanliness"] != "clean":
        raise DirtyRepositoryError(
            f"Checkpoint refused: repository is {before['cleanliness']}; inspect and resolve changes first"
        )
    if before["current_head"] is None:
        raise UnbornRepositoryError("Checkpoint refused: repository has no HEAD commit")

    if approval is None:
        approval = permission_func(
            CHECKPOINT_ACTION,
            path,
            {
                "reason": "Create a local Git checkpoint before a controlled modification.",
                "inspection": before,
            },
        )
    target = str(path)
    if not _approval_matches(approval, CHECKPOINT_ACTION, target):
        raise PermissionDeniedError("Checkpoint refused: explicit matching approval is required")

    after_permission = inspect_repository(path)
    if not after_permission["clean"] or after_permission["current_head"] != before["current_head"]:
        raise RepositoryChangedError("Checkpoint refused: repository changed after permission was granted")
    before_commit = inspect_repository(path)
    if not before_commit["clean"] or before_commit["current_head"] != before["current_head"]:
        raise RepositoryChangedError("Checkpoint refused: repository changed before commit")

    checkpoint_message = (message or f"Mycelium checkpoint {before_commit['inspected_at']}").strip()
    if not checkpoint_message:
        raise RepositoryError("Checkpoint message must not be empty")
    _run_git(
        path,
        [
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "--no-verify",
            "-m",
            checkpoint_message,
        ],
    )
    after = inspect_repository(path)
    if after["current_head"] == before["current_head"]:
        raise RepositoryError("Checkpoint commit did not create a new HEAD")
    return {
        "repository": str(path),
        "checkpoint_id": after["current_head"],
        "previous_head": before["current_head"],
        "message": checkpoint_message,
        "created_at": after["inspected_at"],
        "inspection_before": before,
        "inspection_after_permission": after_permission,
        "inspection_after": after,
        "approval": approval,
        "provenance": {
            "source": CHECKPOINT_SOURCE,
            "component": CHECKPOINT_COMPONENT,
            "version": CHECKPOINT_VERSION,
            "mode": "local-git-checkpoint",
            "permission_action": CHECKPOINT_ACTION,
        },
    }
