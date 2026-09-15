from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


NodeTier = Literal["seed", "worker", "core"]


class NodeRegistration(BaseModel):
    node_id: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    hostname: str = Field(min_length=1, max_length=120)
    tier: NodeTier = "seed"
    capabilities: list[str] = Field(default_factory=list, max_length=30)
    cpu_cores: int = Field(default=1, ge=1, le=512)
    memory_mb: int = Field(default=0, ge=0)
    energy_source: str = Field(default="unknown", max_length=40)


class NodeResponse(NodeRegistration):
    last_seen: datetime
    status: str


class Heartbeat(BaseModel):
    cpu_load_percent: float | None = Field(default=None, ge=0, le=100)
    free_memory_mb: int | None = Field(default=None, ge=0)
    available: bool = True


class TaskCreate(BaseModel):
    kind: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    payload: dict[str, Any] = Field(default_factory=dict)
    required_capabilities: list[str] = Field(default_factory=list, max_length=20)
    preferred_tier: NodeTier | None = None
    priority: int = Field(default=0, ge=-10, le=10)


class ClaimedTask(BaseModel):
    id: int
    kind: str
    payload: dict[str, Any]
    required_capabilities: list[str]


class TaskResult(BaseModel):
    success: bool = True
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = Field(default=None, max_length=2000)
