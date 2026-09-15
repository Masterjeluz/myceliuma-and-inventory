from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SourceType = Literal[
    "user-created",
    "imported",
    "ai-generated",
    "sensor-observed",
    "external-source",
]

ProjectStatus = Literal["idea", "planned", "active", "paused", "completed", "archived"]
IdeaStatus = Literal["raw", "considered", "planned", "rejected", "converted"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Provenance(BaseModel):
    source_type: SourceType = "user-created"
    creator_id: str = Field(default="user", min_length=1, max_length=120)
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    human_verified: bool = True
    verified_by: str | None = Field(default=None, max_length=120)
    created_at: str = Field(default_factory=utc_now)
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def enforce_ai_unverified_rule(self) -> "Provenance":
        """Enforce that AI-generated data is not marked as human-verified by default."""
        if self.source_type == "ai-generated" and not self.verified_by:
            self.human_verified = False
        elif self.source_type == "user-created" and not self.verified_by:
            self.human_verified = True
        return self


# --- Object ---

class ObjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    quantity: int = Field(default=1, ge=0)
    provenance: Provenance | None = None


class ObjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    quantity: int | None = Field(default=None, ge=0)
    provenance: Provenance | None = None


class ObjectResponse(BaseModel):
    id: str = Field(pattern=r"^obj_[a-z0-9_-]+$")
    name: str
    description: str
    quantity: int
    provenance: Provenance
    created_at: str
    updated_at: str


# --- Project ---

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    status: ProjectStatus = "planned"
    provenance: Provenance | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: ProjectStatus | None = None
    provenance: Provenance | None = None


class ProjectResponse(BaseModel):
    id: str = Field(pattern=r"^proj_[a-z0-9_-]+$")
    name: str
    description: str
    status: ProjectStatus
    provenance: Provenance
    created_at: str
    updated_at: str


# --- Idea ---

class IdeaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    status: IdeaStatus = "raw"
    provenance: Provenance | None = None


class IdeaUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: IdeaStatus | None = None
    provenance: Provenance | None = None


class IdeaResponse(BaseModel):
    id: str = Field(pattern=r"^idea_[a-z0-9_-]+$")
    name: str
    description: str
    status: IdeaStatus
    provenance: Provenance
    created_at: str
    updated_at: str


# --- Hardware (M3.1) ---

HardwareStatus = Literal["available", "in_use", "maintenance", "retired", "unknown"]


class HardwareCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    manufacturer: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=200)
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    status: HardwareStatus = "unknown"
    capabilities: list[str] = Field(default_factory=list, max_length=50)
    interfaces: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance | None = None


class HardwareUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    manufacturer: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    status: HardwareStatus | None = None
    capabilities: list[str] | None = Field(default=None, max_length=50)
    interfaces: list[str] | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None
    provenance: Provenance | None = None


class HardwareResponse(BaseModel):
    id: str = Field(pattern=r"^hw_[a-z0-9_-]+$")
    name: str
    manufacturer: str
    model: str
    category: str
    description: str
    status: HardwareStatus
    capabilities: list[str]
    interfaces: list[str]
    metadata: dict[str, Any]
    provenance: Provenance
    created_at: str
    updated_at: str


# --- Sensor (M3.2, world model only: no readout, no hardware access) ---

SensorStatus = Literal["available", "in_use", "maintenance", "retired", "unknown"]


class SensorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sensor_type: str = Field(min_length=1, max_length=100)
    manufacturer: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=5000)
    unit: str = Field(default="", max_length=40)
    measurement_type: str = Field(default="", max_length=40)
    status: SensorStatus = "unknown"
    capabilities: list[str] = Field(default_factory=list, max_length=50)
    interfaces: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance | None = None


class SensorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sensor_type: str | None = Field(default=None, min_length=1, max_length=100)
    manufacturer: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    unit: str | None = Field(default=None, max_length=40)
    measurement_type: str | None = Field(default=None, max_length=40)
    status: SensorStatus | None = None
    capabilities: list[str] | None = Field(default=None, max_length=50)
    interfaces: list[str] | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None
    provenance: Provenance | None = None


class SensorResponse(BaseModel):
    id: str = Field(pattern=r"^sns_[a-z0-9_-]+$")
    name: str
    sensor_type: str
    manufacturer: str
    model: str
    description: str
    unit: str
    measurement_type: str
    status: SensorStatus
    capabilities: list[str]
    interfaces: list[str]
    metadata: dict[str, Any]
    provenance: Provenance
    created_at: str
    updated_at: str


# --- Camera (M3.3, world model only: no capture, no hardware access) ---

CameraStatus = Literal["available", "in_use", "maintenance", "retired", "unknown"]


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    camera_type: str = Field(min_length=1, max_length=100)
    manufacturer: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=5000)
    resolution: str = Field(default="", max_length=40)
    status: CameraStatus = "unknown"
    capabilities: list[str] = Field(default_factory=list, max_length=50)
    interfaces: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance | None = None


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    camera_type: str | None = Field(default=None, min_length=1, max_length=100)
    manufacturer: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    resolution: str | None = Field(default=None, max_length=40)
    status: CameraStatus | None = None
    capabilities: list[str] | None = Field(default=None, max_length=50)
    interfaces: list[str] | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None
    provenance: Provenance | None = None


class CameraResponse(BaseModel):
    id: str = Field(pattern=r"^cam_[a-z0-9_-]+$")
    name: str
    camera_type: str
    manufacturer: str
    model: str
    description: str
    resolution: str
    status: CameraStatus
    capabilities: list[str]
    interfaces: list[str]
    metadata: dict[str, Any]
    provenance: Provenance
    created_at: str
    updated_at: str


# --- Location (M3.4, world model only: no GIS, no 3D, hierarchy via relationships) ---

LocationStatus = Literal["available", "in_use", "maintenance", "retired", "unknown"]


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    location_type: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    status: LocationStatus = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance | None = None


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    location_type: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    status: LocationStatus | None = None
    metadata: dict[str, Any] | None = None
    provenance: Provenance | None = None


class LocationResponse(BaseModel):
    id: str = Field(pattern=r"^loc_[a-z0-9_-]+$")
    name: str
    location_type: str
    description: str
    status: LocationStatus
    metadata: dict[str, Any]
    provenance: Provenance
    created_at: str
    updated_at: str


# --- Model (M3.5, world model data only: no runtime, no inference, no network) ---

ModelType = Literal["llm", "vlm", "vision", "detection", "ocr", "speech_to_text",
                    "embedding", "other"]
ModelStatus = Literal["available", "in_use", "maintenance", "retired", "unknown"]


class ModelCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(min_length=1, max_length=200)
    provider: str = Field(default="", max_length=200)
    model_identifier: str = Field(default="", max_length=200)
    model_type: ModelType = "other"
    description: str = Field(default="", max_length=5000)
    version: str = Field(default="", max_length=100)
    status: ModelStatus = "unknown"
    capabilities: list[str] = Field(default_factory=list, max_length=50)
    interfaces: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance | None = None


class ModelUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str | None = Field(default=None, min_length=1, max_length=200)
    provider: str | None = Field(default=None, max_length=200)
    model_identifier: str | None = Field(default=None, max_length=200)
    model_type: ModelType | None = None
    description: str | None = Field(default=None, max_length=5000)
    version: str | None = Field(default=None, max_length=100)
    status: ModelStatus | None = None
    capabilities: list[str] | None = Field(default=None, max_length=50)
    interfaces: list[str] | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None
    provenance: Provenance | None = None


class ModelResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: str = Field(pattern=r"^mod_[a-z0-9_-]+$")
    name: str
    provider: str
    model_identifier: str
    model_type: ModelType
    description: str
    version: str
    status: ModelStatus
    capabilities: list[str]
    interfaces: list[str]
    metadata: dict[str, Any]
    provenance: Provenance
    created_at: str
    updated_at: str


# --- Task (M3.6, world model data only: describes work, never executes it) ---

TaskType = Literal["observe", "identify", "measure", "classify", "inspect",
                   "transform", "analyze", "monitor", "other"]
TaskStatus = Literal["pending", "ready", "running", "completed", "failed",
                     "cancelled"]


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    task_type: TaskType = "other"
    description: str = Field(default="", max_length=5000)
    status: TaskStatus = "pending"
    priority: int = Field(default=0, ge=0, le=100)
    input_requirements: list[str] = Field(default_factory=list, max_length=50)
    expected_output: str = Field(default="", max_length=2000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance | None = None


class TaskUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    task_type: TaskType | None = None
    description: str | None = Field(default=None, max_length=5000)
    status: TaskStatus | None = None
    priority: int | None = Field(default=None, ge=0, le=100)
    input_requirements: list[str] | None = Field(default=None, max_length=50)
    expected_output: str | None = Field(default=None, max_length=2000)
    parameters: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    provenance: Provenance | None = None


class TaskResponse(BaseModel):
    id: str = Field(pattern=r"^task_[a-z0-9_-]+$")
    name: str
    task_type: TaskType
    description: str
    status: TaskStatus
    priority: int
    input_requirements: list[str]
    expected_output: str
    parameters: dict[str, Any]
    metadata: dict[str, Any]
    provenance: Provenance
    created_at: str
    updated_at: str


# --- Actuator (M3.7, world model data only: describes a possible executor,
# never executes anything; no drivers, no GPIO, no network) ---

ActuatorType = Literal["motor", "relay", "led", "servo", "pump", "valve",
                       "heater", "fan", "display", "speaker", "robotic", "other"]
ActuatorStatus = Literal["available", "in_use", "maintenance", "retired", "unknown"]


class ActuatorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    actuator_type: ActuatorType = "other"
    manufacturer: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=5000)
    status: ActuatorStatus = "unknown"
    capabilities: list[str] = Field(default_factory=list, max_length=50)
    interfaces: list[str] = Field(default_factory=list, max_length=50)
    parameters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance | None = None


class ActuatorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    actuator_type: ActuatorType | None = None
    manufacturer: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: ActuatorStatus | None = None
    capabilities: list[str] | None = Field(default=None, max_length=50)
    interfaces: list[str] | None = Field(default=None, max_length=50)
    parameters: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    provenance: Provenance | None = None


class ActuatorResponse(BaseModel):
    id: str = Field(pattern=r"^act_[a-z0-9_-]+$")
    name: str
    actuator_type: ActuatorType
    manufacturer: str
    model: str
    description: str
    status: ActuatorStatus
    capabilities: list[str]
    interfaces: list[str]
    parameters: dict[str, Any]
    metadata: dict[str, Any]
    provenance: Provenance
    created_at: str
    updated_at: str


# --- File (M7.5, record only: never opens, copies, executes or imports files) ---

FileKind = Literal["cad", "mesh", "gcode", "image", "document", "data", "other"]
FileStatus = Literal["available", "in_use", "maintenance", "retired", "unknown"]
SHA256_PATTERN = r"^[0-9a-f]{64}$"


def normalize_sha256(value) -> str:
    """Lowercase and validate a SHA-256 hex digest. Never hashes anything."""
    if not isinstance(value, str):
        raise ValueError("sha256 must be a 64-character hex digest")
    cleaned = value.strip().lower()
    if len(cleaned) != 64 or any(char not in "0123456789abcdef" for char in cleaned):
        raise ValueError("sha256 must be a 64-character hex digest")
    return cleaned


class FileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    file_kind: FileKind = "other"
    mime_type: str = Field(default="", max_length=200)
    sha256: str = Field(min_length=1, max_length=64)
    size_bytes: int = Field(default=0, ge=0)
    description: str = Field(default="", max_length=5000)
    status: FileStatus = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance | None = None

    @field_validator("sha256")
    @classmethod
    def _check_sha256(cls, value):
        return normalize_sha256(value)


class FileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    file_kind: FileKind | None = None
    mime_type: str | None = Field(default=None, max_length=200)
    sha256: str | None = Field(default=None, min_length=1, max_length=64)
    size_bytes: int | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=5000)
    status: FileStatus | None = None
    metadata: dict[str, Any] | None = None
    provenance: Provenance | None = None

    @field_validator("sha256")
    @classmethod
    def _check_sha256(cls, value):
        if value is None:
            return value
        return normalize_sha256(value)


class FileResponse(BaseModel):
    id: str = Field(pattern=r"^file_[a-z0-9_-]+$")
    name: str
    file_kind: FileKind
    mime_type: str
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: int
    description: str
    status: FileStatus
    metadata: dict[str, Any]
    provenance: Provenance
    created_at: str
    updated_at: str


# --- Relationship ---

RelationshipPredicate = Literal[
    "used_in",
    "uses",
    "related_to",
    "part_of",
    "contains",
    "became",
    "led_to",
    "depends_on",
    "produced_by",
    "stored_in",
]


class RelationshipCreate(BaseModel):
    from_id: str = Field(min_length=3, max_length=100)
    predicate: RelationshipPredicate
    to_id: str = Field(min_length=3, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def check_not_self_referential(self) -> "RelationshipCreate":
        if self.from_id == self.to_id:
            raise ValueError("from_id and to_id must differ")
        return self


class RelationshipResponse(BaseModel):
    id: str = Field(pattern=r"^rel_[a-z0-9_-]+$")
    from_id: str
    predicate: str
    to_id: str
    metadata: dict[str, Any]
    provenance: Provenance
    created_at: str


# --- Event ---

EventType = Literal[
    "object_created", "object_updated", "object_deleted",
    "project_created", "project_updated", "project_deleted",
    "idea_created", "idea_updated", "idea_deleted",
    "hardware_created", "hardware_updated", "hardware_deleted",
    "sensor_created", "sensor_updated", "sensor_deleted",
    "camera_created", "camera_updated", "camera_deleted",
    "location_created", "location_updated", "location_deleted",
    "model_created", "model_updated", "model_deleted",
    "task_created", "task_updated", "task_deleted",
    "actuator_created", "actuator_updated", "actuator_deleted",
    "file_created", "file_updated", "file_deleted",
    "relationship_created", "relationship_deleted",
]


class EventResponse(BaseModel):
    id: str = Field(pattern=r"^evt_[a-z0-9_-]+$")
    event_type: EventType
    entity_id: str
    timestamp: str
    data: dict[str, Any]
    provenance: Provenance


# --- Search (M4.2, read-only over the FTS foundation) ---

SearchEntityType = Literal["object", "project", "idea", "relationship", "hardware",
                           "sensor", "camera", "location", "model", "task",
                           "actuator", "file"]


class SearchResult(BaseModel):
    entity_type: SearchEntityType
    entity_id: str
    title: str
    snippet: str
    provenance: Provenance
    details: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    total: int


# --- Graph (M4.3, read-only traversal over relationships) ---

GraphNodeType = Literal["object", "project", "idea", "hardware", "sensor", "camera",
                        "location", "model", "task", "actuator", "file"]


class GraphNode(BaseModel):
    entity_type: GraphNodeType
    entity_id: str
    title: str
    provenance: Provenance
    details: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str = Field(pattern=r"^rel_[a-z0-9_-]+$")
    from_id: str
    predicate: str
    to_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance


class GraphResponse(BaseModel):
    entity_id: str
    depth: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]
