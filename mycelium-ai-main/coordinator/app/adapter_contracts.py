"""Adapter data contracts for Mycelium (M6.1).

This module defines the REASON/PLAN half of a future sense–reason–plan–
approve–execute loop. It stops at PROPOSAL: there is no execution surface
here and nothing in this module performs I/O of any kind.

- AdapterRequest carries validated input plus its provenance.
- AdapterProposal carries a proposed action plus its own provenance, and
  always requires human approval (``requires_approval`` is forced True).

ID rules reuse the stable world-model prefixes where they apply: ``mod_``
for INVENTory models, ``task_`` for INVENTory tasks. Adapter and node IDs
follow the coordinator's safe identifier pattern. No INVENTory code is
imported; the local Provenance mirror in inventory_read is reused.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .inventory_read import Provenance

MODEL_ID_PREFIX = "mod_"
TASK_ID_PREFIX = "task_"
SAFE_ID_PATTERN = r"^[a-zA-Z0-9._-]+$"


class AdapterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=3, max_length=80, pattern=SAFE_ID_PATTERN)
    adapter_id: str = Field(min_length=1, max_length=80, pattern=SAFE_ID_PATTERN)
    model_id: str | None = Field(default=None, max_length=120)
    node_id: str | None = Field(default=None, min_length=3, max_length=80,
                                pattern=SAFE_ID_PATTERN)
    task_id: str | None = Field(default=None, max_length=120)
    input: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance = Field(default_factory=Provenance)

    @field_validator("model_id")
    @classmethod
    def _check_model_id(cls, value):
        if value is not None and not value.startswith(MODEL_ID_PREFIX):
            raise ValueError(f"model_id must start with '{MODEL_ID_PREFIX}'")
        return value

    @field_validator("task_id")
    @classmethod
    def _check_task_id(cls, value):
        if value is not None and not value.startswith(TASK_ID_PREFIX):
            raise ValueError(f"task_id must start with '{TASK_ID_PREFIX}'")
        return value


class AdapterProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=3, max_length=80, pattern=SAFE_ID_PATTERN)
    request_id: str = Field(min_length=3, max_length=80, pattern=SAFE_ID_PATTERN)
    adapter_id: str = Field(min_length=1, max_length=80, pattern=SAFE_ID_PATTERN)
    model_id: str | None = Field(default=None, max_length=120)
    node_id: str | None = Field(default=None, min_length=3, max_length=80,
                                pattern=SAFE_ID_PATTERN)
    task_id: str | None = Field(default=None, max_length=120)
    proposed_action: str = Field(min_length=1, max_length=2000)
    expected_output: str = Field(default="", max_length=2000)
    risks: list[str] = Field(default_factory=list, max_length=20)
    provenance: Provenance = Field(default_factory=Provenance)
    requires_approval: bool = True

    @field_validator("model_id")
    @classmethod
    def _check_model_id(cls, value):
        if value is not None and not value.startswith(MODEL_ID_PREFIX):
            raise ValueError(f"model_id must start with '{MODEL_ID_PREFIX}'")
        return value

    @field_validator("task_id")
    @classmethod
    def _check_task_id(cls, value):
        if value is not None and not value.startswith(TASK_ID_PREFIX):
            raise ValueError(f"task_id must start with '{TASK_ID_PREFIX}'")
        return value

    @model_validator(mode="after")
    def _force_approval(self) -> "AdapterProposal":
        if self.requires_approval is not True:
            raise ValueError("AdapterProposal always requires human approval")
        if self.provenance.human_verified:
            raise ValueError("AdapterProposal provenance must not claim human approval")
        return self
