"""Project context: which project Mycelium works on (Fase L).

One active project at a time: a name, a repository path and a working
directory. Nothing is hardcoded to a single project — the default
resolves from MYCELIUM_PROJECT_ROOT (falling back to the current
working directory) and any explicit, existing directory may take over
later ("ga verder met mijn camperproject" becomes a new context, not
a code change).

Rules (tested):

- repository and working_directory must be existing local
  directories; anything else is refused before use.
- names are 1..120 chars; no URLs, no commands, no traversal tricks
  survive: paths resolve to absolute directories.
- contexts carry provenance (who set them) but never secrets.
"""

import os

from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import Provenance

PROJECT_ENV_VAR = "MYCELIUM_PROJECT_ROOT"
MAX_NAME_CHARS = 120


class ProjectContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    repository: str = Field(min_length=1, max_length=500)
    working_directory: str = Field(min_length=1, max_length=500)
    provenance: Provenance = Field(default_factory=Provenance)


def _checked_dir(label: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Project {label} must be non-empty text")
    path = os.path.abspath(value.strip())
    if not os.path.isdir(path):
        raise ValueError(f"Project {label} is not a directory: {value[:200]}")
    return path


def new_context(project_id: str, name: str, repository: str,
                working_directory: str | None = None,
                set_by: str = "human") -> ProjectContext:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Project name must be non-empty text")
    repo = _checked_dir("repository", repository)
    work = _checked_dir("working_directory",
                        working_directory or repository)
    return ProjectContext(
        project_id=project_id,
        name=name.strip()[:MAX_NAME_CHARS],
        repository=repo,
        working_directory=work,
        provenance=Provenance(
            source_type="user-created",
            creator_id=set_by,
            human_verified=True,
        ),
    )


def default_context() -> ProjectContext:
    """Active project from environment, else current directory."""
    root = os.environ.get(PROJECT_ENV_VAR, "").strip() or os.getcwd()
    path = os.path.abspath(root)
    if not os.path.isdir(path):
        raise ValueError(f"Project root is not a directory: {root[:200]}")
    name = os.path.basename(path) or "mycelium-project"
    return ProjectContext(
        project_id=f"prj-{name.lower()[:40]}",
        name=name[:MAX_NAME_CHARS],
        repository=path,
        working_directory=path,
        provenance=Provenance(
            source_type="user-created",
            creator_id="default-context",
            human_verified=True,
            notes=f"resolved from {PROJECT_ENV_VAR or 'cwd'}; "
                  "override per project",
        ),
    )
