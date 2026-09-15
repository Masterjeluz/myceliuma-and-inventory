"""Agent action results: what the desktop agent reports back (Fase J).

A result closes one ComputerAction. Statuses are completed, failed,
cancelled or blocked — never "verified": a result describes what
happened, and verification stays a separate human act. Provenance is
always agent-reported/unverified here.

Rules (tested):

- status must be known; unknown statuses fail closed.
- completed results carry no error; failed/blocked results must carry
  one (max 2000 chars, matching the coordinator TaskResult budget).
- cancelled results are terminal and operator-initiated.
- observation_reference, when present, must be a plain observation ID.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import Provenance

ResultStatus = Literal["completed", "failed", "cancelled", "blocked"]
VALID_STATUSES = frozenset({"completed", "failed", "cancelled", "blocked"})
MAX_ERROR_CHARS = 2000


class AgentActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=3, max_length=80)
    status: str = Field(min_length=1, max_length=20)
    started_at: str = ""
    completed_at: str = ""
    error: str = Field(default="", max_length=MAX_ERROR_CHARS)
    observation_reference: str = Field(default="", max_length=80)
    provenance: Provenance = Field(default_factory=Provenance)


def new_result(action_id: str, status: str, *,
               error: str = "",
               observation_reference: str = "") -> AgentActionResult:
    if status not in VALID_STATUSES:
        raise ValueError(f"Unknown result status '{status}'")
    text = str(error or "")
    if status in ("failed", "blocked") and not text.strip():
        raise ValueError(f"Status '{status}' needs an error description")
    if status == "completed" and text.strip():
        raise ValueError("Completed results carry no error")
    reference = str(observation_reference or "").strip()
    if reference and not reference.startswith("obs-"):
        raise ValueError("observation_reference must be an observation ID")
    return AgentActionResult(
        action_id=action_id,
        status=status,
        error=text.strip()[:MAX_ERROR_CHARS],
        observation_reference=reference,
        provenance=Provenance(
            source_type="sensor-observed",
            creator_id="desktop-agent",
            human_verified=False,
            notes="agent-reported outcome; not human verified",
        ),
    )
