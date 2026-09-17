from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .adapter_contracts import AdapterProposal
from .approval import ApprovalResult
from .ollama_advisor import AdviceResponse


NodeTier = Literal["seed", "worker", "core"]


class NodeRegistration(BaseModel):
    node_id: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    hostname: str = Field(min_length=1, max_length=120)
    tier: NodeTier = "seed"
    capabilities: list[str] = Field(default_factory=list, max_length=50)
    cpu_cores: int = Field(default=1, ge=1, le=512)
    memory_mb: int = Field(default=0, ge=0)
    energy_source: str = Field(default="unknown", max_length=40)
    display_name: str = Field(default="", max_length=120)
    models: list[dict[str, Any]] = Field(default_factory=list,
                                         max_length=20)
    executors: list[str] = Field(default_factory=list, max_length=20)
    resources: dict[str, Any] = Field(default_factory=dict)
    locality_zone: str = Field(default="local_network", min_length=1,
                               max_length=20)
    node_token: str | None = Field(default=None, min_length=8,
                                   max_length=256)
    operator_key: str = Field(default="", max_length=256)
    coordinator_capable: bool = False


class OperatorBody(BaseModel):
    """Operator authorization for identity administration
    (enable/disable). Key lives in local env, never in DB."""

    operator_key: str = Field(default="", max_length=256)


class NodeRotateBody(BaseModel):
    """Bind or rotate a node token. Bound identities need
    the current token; legacy identities need the operator
    key. The new token must be non-trivial."""

    current_token: str = Field(default="", max_length=256)
    new_token: str = Field(min_length=1, max_length=256)
    operator_key: str = Field(default="", max_length=256)


class NodeResponse(NodeRegistration):
    last_seen: datetime
    status: str


class Heartbeat(BaseModel):
    cpu_load_percent: float | None = Field(default=None, ge=0, le=100)
    free_memory_mb: int | None = Field(default=None, ge=0)
    available: bool = True
    node_token: str | None = Field(default=None, min_length=8,
                                   max_length=256)
    capabilities: list[str] | None = Field(default=None,
                                           max_length=50)
    models: list[dict[str, Any]] | None = Field(default=None,
                                                max_length=20)
    executors: list[str] | None = Field(default=None, max_length=20)
    resources: dict[str, Any] | None = None


class TaskCreate(BaseModel):
    kind: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    payload: dict[str, Any] = Field(default_factory=dict)
    required_capabilities: list[str] = Field(default_factory=list, max_length=20)
    preferred_tier: NodeTier | None = None
    priority: int = Field(default=0, ge=-10, le=10)
    requirements: dict[str, Any] = Field(default_factory=dict)


class TaskAssignBody(BaseModel):
    """Explicit (re-)assignment of one queued task. node_id empty
    means auto-route; a given node_id must prove eligible."""

    node_id: str | None = Field(default=None, min_length=3,
                                max_length=80)
    policy: dict[str, Any] = Field(default_factory=dict)


class TaskRouteBody(BaseModel):
    """Dry-run routing: requirements + policy, no assignment."""

    requirements: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)


class ClaimedTask(BaseModel):
    id: int
    kind: str
    payload: dict[str, Any]
    required_capabilities: list[str]


class TaskResult(BaseModel):
    success: bool = True
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = Field(default=None, max_length=2000)


class AdviseRequest(BaseModel):
    q: str | None = Field(default=None, min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=500)
    type: str | None = None
    mode: str = Field(default="hybrid", min_length=1, max_length=20)


class AdviseResponse(AdviceResponse):
    """Advice plus an optional validated AI proposal (M8.3).

    The proposal is a best-effort enrichment for the operator: either a
    validated AdapterProposal (ai-generated, unverified, approval still
    required) or None when the advice carries no usable proposal block.
    Never approved, staged, queued or dispatched here.
    """

    proposal: AdapterProposal | None = None
    retrieval_mode: str = "lexical"


class DecideApprovalBody(BaseModel):
    """Explicit operator decision on one full proposal (M8.4).

    The complete proposal travels with the decision because M8.3 proposals
    are never stored server-side: binding is verified on content, never on
    a bare proposal_id. Only an exact "YES" approves; anything else denies.
    """

    proposal: AdapterProposal
    response: str = Field(min_length=1, max_length=80)
    decided_by: str = Field(default="human", min_length=1, max_length=80)


class TaskFromProposalBody(BaseModel):
    """Explicit operator trigger from approval to task (M8.5).

    Stateless like M8.4: the full proposal, its ApprovalResult and the
    fingerprint recorded at approval time travel together. The server
    revalidates everything through the existing M6.4 conversion only.
    The result is a task representation with status "approved" — never
    queued, staged, promoted or dispatched here.
    """

    proposal: AdapterProposal
    approval: ApprovalResult
    approved_fingerprint: str = Field(min_length=64, max_length=64)
    task_id: str | None = Field(default=None, min_length=3, max_length=80)
    task_type: str = Field(default="other", min_length=1, max_length=40)
    input: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    """One chat turn: message plus optional conversation/project/provider."""

    conversation_id: str | None = Field(default=None, min_length=3,
                                        max_length=80)
    message: str = Field(min_length=1, max_length=4000)
    project_ref: str = Field(default="", max_length=200)
    provider: str = Field(default="ollama", min_length=1, max_length=40)
    mode: str = Field(default="hybrid", min_length=1, max_length=20)
    observation_ids: list[str] = Field(default_factory=list,
                                       max_length=3)
    input_type: str = Field(default="text", min_length=1,
                            max_length=20)


class ChatResponse(BaseModel):
    """Stored assistant turn: reply, sources, optional plan/proposal."""

    conversation_id: str
    message_id: str
    reply: str
    model: str = ""
    records_used: int = 0
    sources: list[dict[str, Any]] = Field(default_factory=list)
    proposal: AdapterProposal | None = None
    provider_error: str | None = None
    retrieval_mode: str = "lexical"


class PlanStepBody(BaseModel):
    step_id: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=500)
    required_capabilities: list[str] = Field(default_factory=list,
                                             max_length=10)
    requires_approval: bool = True


class PlanBody(BaseModel):
    plan_id: str = Field(min_length=3, max_length=80)
    goal: str = Field(min_length=1, max_length=500)
    summary: str = Field(default="", max_length=2000)
    steps: list[PlanStepBody] = Field(min_length=1, max_length=20)
    risks: list[str] = Field(default_factory=list, max_length=20)


class PlanToProposalBody(BaseModel):
    plan: PlanBody
    adapter_id: str = Field(min_length=1, max_length=80)
    request_id: str = Field(min_length=3, max_length=80)


class DesktopActionBody(BaseModel):
    action_id: str | None = Field(default=None, min_length=3, max_length=80)
    action_type: str = Field(min_length=1, max_length=40)
    parameters: dict[str, Any] = Field(default_factory=dict)


class DesktopDecisionBody(BaseModel):
    response: str = Field(min_length=1, max_length=80)
    decided_by: str = Field(default="human", min_length=1, max_length=80)


class DesktopResultBody(BaseModel):
    status: str = Field(min_length=1, max_length=20)
    error: str = Field(default="", max_length=2000)
    observation_reference: str = Field(default="", max_length=80)


class DesktopClaimBody(BaseModel):
    """Agent claim for the next approved action (BIG #2).

    The server re-checks registration, freshness and capabilities;
    the node_id pins the dispatch owner.
    """

    node_id: str = Field(min_length=3, max_length=80)
    node_token: str | None = Field(default=None, min_length=8,
                                   max_length=256)


class DesktopDispatchBody(BaseModel):
    """Manual dispatch, optionally pinning the lease holder."""

    node_id: str | None = Field(default=None, min_length=3, max_length=80)


class MissionStepBody(BaseModel):
    kind: str = Field(min_length=1, max_length=20)
    description: str = Field(min_length=1, max_length=500)
    action_type: str = Field(default="", max_length=40)
    parameters: dict[str, Any] = Field(default_factory=dict)
    required_capabilities: list[str] = Field(default_factory=list,
                                             max_length=10)
    requires_approval: bool = False


class MissionCreateBody(BaseModel):
    conversation_id: str = Field(min_length=3, max_length=80)
    goal: str = Field(min_length=1, max_length=500)
    steps: list[MissionStepBody] | None = Field(default=None, min_length=1,
                                                max_length=20)
    max_steps: int = Field(default=10, ge=1, le=20)


class MissionApproveBody(BaseModel):
    response: str = Field(min_length=1, max_length=80)
    decided_by: str = Field(default="human", min_length=1, max_length=80)


class ChatMissionBody(BaseModel):
    goal: str = Field(min_length=1, max_length=500)
    steps: list[MissionStepBody] | None = Field(default=None, min_length=1,
                                                max_length=20)
    max_steps: int = Field(default=10, ge=1, le=20)


class SuggestStepsBody(BaseModel):
    goal: str = Field(min_length=1, max_length=500)
    context: str = Field(default="", max_length=1000)


class TemplateMissionBody(BaseModel):
    template_id: str = Field(min_length=1, max_length=80)
    conversation_id: str = Field(min_length=3, max_length=80)
    goal: str = Field(min_length=1, max_length=500)
    max_steps: int | None = Field(default=None, ge=1, le=20)


class CameraRegisterBody(BaseModel):
    device_id: str | None = Field(default=None, min_length=3, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    kinds: list[str] = Field(min_length=1, max_length=4)
    source: str = Field(min_length=1, max_length=20)
    notes: str = Field(default="", max_length=500)


class InventoryWriteBody(BaseModel):
    """One inventory write proposal (BIG #5). Inert until approved."""

    proposal_id: str | None = Field(default=None, min_length=3,
                                    max_length=80)
    mutation: str = Field(min_length=1, max_length=40)
    entity_type: str = Field(default="", min_length=1, max_length=40)
    entity_id: str = Field(default="", max_length=100)
    fields: dict[str, Any] = Field(default_factory=dict)
    actor: str = Field(default="mycelium", min_length=1, max_length=80)


class GitCommitBody(BaseModel):
    """One git-commit proposal (BIG #5). Inert until approved."""

    proposal_id: str | None = Field(default=None, min_length=3,
                                    max_length=80)
    repository: str = Field(min_length=1, max_length=500)
    branch: str = Field(min_length=1, max_length=120)
    expected_head: str = Field(min_length=7, max_length=40)
    message: str = Field(min_length=1, max_length=500)
    files: list[str] = Field(min_length=1, max_length=20)
    changeset_fingerprint: str = Field(min_length=64, max_length=64)
    actor: str = Field(default="mycelium", min_length=1, max_length=80)


class WriteDecisionBody(BaseModel):
    response: str = Field(min_length=1, max_length=80)
    decided_by: str = Field(default="human", min_length=1, max_length=80)


class VisionAnalyzeBody(BaseModel):
    """One VLM analysis over a stored observation (BIG #6). Advice."""

    observation_id: str = Field(min_length=3, max_length=80)
    question: str = Field(default="Wat zie je op deze foto?",
                          min_length=1, max_length=500)
    provider: str = Field(default="ollama", min_length=1, max_length=40)


class VisionProposeBody(BaseModel):
    """One inert inventory proposal from a stored vision analysis."""

    analysis_id: str = Field(min_length=3, max_length=80)
    kind: str = Field(default="object", min_length=1, max_length=20)
    proposal_id: str | None = Field(default=None, min_length=3,
                                    max_length=80)
    actor: str = Field(default="mycelium", min_length=1, max_length=80)


class StreamStartBody(BaseModel):
    """One bounded local-only stream session (BIG #6)."""

    device_id: str = Field(min_length=3, max_length=80)
    max_frames: int = Field(default=100, ge=1, le=10000)
    max_seconds: int = Field(default=300, ge=1, le=3600)


class FabGenerateBody(BaseModel):
    """One bounded 3D generation run (BIG #7). Test-only geometry."""

    description: str = Field(min_length=1, max_length=500)
    generator: str = Field(default="procedural-test", min_length=1,
                           max_length=40)
    source_object_id: str = Field(default="", max_length=100)
    source_idea_id: str = Field(default="", max_length=100)


class FabSliceBody(BaseModel):
    """One bounded slicing run over a validated mesh (BIG #7)."""

    artifact_ref: str = Field(min_length=1, max_length=200)
    profile: str = Field(min_length=1, max_length=40)
    printer_id: str = Field(min_length=3, max_length=80)
    slicer: str = Field(default="test-slicer", min_length=1,
                        max_length=40)


class PrinterRegisterBody(BaseModel):
    """One printer device registration (BIG #7). Execution
    authority stays with the coordinator; no motion here."""

    printer_id: str | None = Field(default=None, min_length=3,
                                   max_length=80)
    name: str = Field(min_length=1, max_length=120)
    capabilities: list[str] = Field(default_factory=list,
                                    max_length=10)
    inventory_hardware_id: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=500)


class PrintProposeBody(BaseModel):
    """One inert physical-execution proposal (BIG #7). The second,
    explicit approval: mission YES never starts the machine."""

    proposal_id: str | None = Field(default=None, min_length=3,
                                    max_length=80)
    job_id: str | None = Field(default=None, min_length=3,
                               max_length=80)
    printer_id: str = Field(min_length=3, max_length=80)
    gcode_ref: str = Field(min_length=1, max_length=200)
    gcode_sha256: str = Field(min_length=64, max_length=64)
    profile: str = Field(min_length=1, max_length=40)
    actor: str = Field(default="mycelium", min_length=1, max_length=80)


class PrintCancelBody(BaseModel):
    job_id: str = Field(min_length=3, max_length=80)


class SessionOpenBody(BaseModel):
    """Open one interface session (presence only, no permission)."""

    interface_id: str = Field(min_length=1, max_length=80)
    node_id: str = Field(default="", max_length=80)
    conversation_id: str = Field(default="", max_length=80)
    ttl_seconds: int = Field(default=86400, ge=1, le=604800)


class InterfaceChatBody(BaseModel):
    """One interface turn converging into the chat flow."""

    session_id: str = Field(default="", max_length=80)
    conversation_id: str | None = Field(default=None, min_length=3,
                                        max_length=80)
    content: str = Field(min_length=1, max_length=4000)
    input_type: str = Field(default="text", min_length=1,
                            max_length=20)
    observation_ids: list[str] = Field(default_factory=list,
                                       max_length=3)
    speak: bool = False


class VoiceTranscribeBody(BaseModel):
    audio_ref: str = Field(min_length=1, max_length=200)
    provider: str = Field(default="unavailable", min_length=1,
                          max_length=40)


class VoiceSynthesizeBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    provider: str = Field(default="unavailable", min_length=1,
                          max_length=40)


class VoiceChatBody(BaseModel):
    """Voice turn: transcript and/or audio, converging into chat."""

    transcript: str = Field(default="", max_length=4000)
    audio_ref: str = Field(default="", max_length=200)
    provider: str = Field(default="unavailable", min_length=1,
                          max_length=40)
    session_id: str = Field(default="", max_length=80)
    conversation_id: str | None = Field(default=None, min_length=3,
                                        max_length=80)
    speak: bool = False


class CaptureOpenBody(BaseModel):
    node_id: str = Field(min_length=3, max_length=80)
    max_seconds: int = Field(default=60, ge=1, le=600)


class CaptureCloseBody(BaseModel):
    session_id: str = Field(min_length=3, max_length=80)
    audio_ref: str = Field(default="", max_length=200)


class NotifyBody(BaseModel):
    """Create one informational notification (never executable)."""

    recipient_node_id: str = Field(min_length=3, max_length=80)
    type: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=1000)
    severity: str = Field(default="info", min_length=1,
                          max_length=20)
    related_entity: str = Field(default="", max_length=100)
    related_mission: str = Field(default="", max_length=80)
    related_task: str = Field(default="", max_length=80)


class VoiceApprovalRequestBody(BaseModel):
    """Open one voice-approval request. Target must be pending;
    physical kinds are refused outright."""

    kind: str = Field(min_length=1, max_length=20)
    target_id: str = Field(min_length=3, max_length=80)
    fingerprint: str = Field(default="", max_length=64)
    summary: str = Field(default="", max_length=500)
    ttl_seconds: int = Field(default=300, ge=30, le=3600)


class VoiceApproveBody(BaseModel):
    approval_id: str = Field(min_length=3, max_length=80)
    transcript: str = Field(min_length=1, max_length=200)


class PhoneCameraBody(BaseModel):
    """Register a phone-owned camera device (explicit, no capture)."""

    node_id: str = Field(min_length=3, max_length=80)
    name: str = Field(default="Phone camera", min_length=1,
                      max_length=120)
    kinds: list[str] = Field(default_factory=lambda: ["snapshot"],
                             min_length=1, max_length=4)


class CampaignBody(BaseModel):
    """Seek or renew the coordinator lease (BIG #10)."""

    node_id: str = Field(min_length=3, max_length=80)


class MissionRunBody(BaseModel):
    """Drive one autonomous loop run (BIG #21). Bounded;
    stops at every gate, never approves, never executes
    beyond the existing executor."""

    max_rounds: int = Field(default=10, ge=1, le=10)


class DistEnvelopeBody(BaseModel):
    """One distributed change envelope for sync apply."""

    event_id: str = Field(min_length=3, max_length=80)
    origin_node_id: str = Field(min_length=1, max_length=80)
    entity_id: str = Field(min_length=1, max_length=100)
    entity_type: str = Field(min_length=1, max_length=40)
    entity_revision: str = Field(default="", max_length=120)
    base_revision: str = Field(default="", max_length=120)
    event_type: str = Field(min_length=1, max_length=40)
    timestamp: str = Field(default="", max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    epoch: int = Field(default=0, ge=0)


class SyncApplyBody(BaseModel):
    items: list[DistEnvelopeBody] = Field(default_factory=list,
                                          max_length=100)


class LiveSessionBody(BaseModel):
    """Open one capability-scoped Live session (least privilege)."""

    interface: str = Field(min_length=1, max_length=40)
    actor: str = Field(min_length=1, max_length=80)
    capabilities: list[str] = Field(default_factory=list,
                                    max_length=20)
    context_scope: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int = Field(default=3600, ge=1, le=86400)


class LiveContextBody(BaseModel):
    session_id: str = Field(min_length=3, max_length=80)
    query: str = Field(default="", max_length=500)
    budget: int = Field(default=8000, ge=512, le=20000)
    entity_id: str = Field(default="", max_length=100)


class LiveProposeBody(BaseModel):
    """Propose through a Live session. Capability-gated; the
    proposal itself still needs the existing approval flow."""

    session_id: str = Field(min_length=3, max_length=80)
    kind: str = Field(min_length=1, max_length=40)
    target: str = Field(default="", max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)
    actor: str = Field(default="", max_length=80)


class TransformBody(BaseModel):
    """Preview (and optionally persist locally) one mesh
    transform. Persistence is a local working file; INVENTory
    registration still needs the file proposal flow."""

    artifact_ref: str = Field(min_length=1, max_length=200)
    op: str = Field(min_length=1, max_length=20)
    params: dict[str, Any] = Field(default_factory=dict)
    persist: bool = False
    max_tris: int = Field(default=5000, ge=1, le=5000)


class MemoryCreateBody(BaseModel):
    """Store one memory entry. AI callers land on
    ai_inference/ai_suggestion; fact tiers need human
    provenance."""

    memory_type: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=200)
    truth: str = Field(default="ai_suggestion", min_length=1,
                       max_length=20)
    content: str = Field(default="", max_length=4000)
    data: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="", max_length=200)
    provenance: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    project_ref: str = Field(default="", max_length=100)
    entity_refs: list[str] = Field(default_factory=list,
                                   max_length=20)
    event_refs: list[str] = Field(default_factory=list,
                                  max_length=20)
    derived_from: list[str] = Field(default_factory=list,
                                    max_length=20)
    expiry: str = Field(default="", max_length=80)
    observed_at: str = Field(default="", max_length=80)


class MemoryVerifyBody(BaseModel):
    verified_by: str = Field(min_length=1, max_length=80)
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)


class MemoryRetrieveBody(BaseModel):
    query: str = Field(default="", max_length=500)
    memory_types: list[str] = Field(default_factory=list,
                                    max_length=10)
    project_ref: str = Field(default="", max_length=100)
    truth: str = Field(default="", max_length=20)
    limit: int = Field(default=10, ge=1, le=50)
    semantic: bool = False
    include_health: bool = False


class MemoryConsolidateBody(BaseModel):
    raw_texts: list[str] = Field(min_length=1, max_length=50)
    project_ref: str = Field(default="", max_length=100)
    source: str = Field(default="consolidation", min_length=1,
                        max_length=200)


class HealthMeasureBody(BaseModel):
    """Log one health measurement. Source is explicit."""

    metric: str = Field(min_length=1, max_length=40)
    value: float
    source: str = Field(default="manual", min_length=1,
                        max_length=20)
    observed_at: str = Field(default="", max_length=80)
    provenance: dict[str, Any] = Field(default_factory=dict)


class FoodCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    nutrients: dict[str, float] = Field(default_factory=dict)
    vegan_status: str = Field(default="unknown", min_length=1,
                              max_length=20)
    vegan_evidence: str = Field(default="", max_length=500)
    source: str = Field(default="manual", min_length=1,
                        max_length=20)
    provenance: dict[str, Any] = Field(default_factory=dict)


class MealItemBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    food_id: str = Field(default="", max_length=80)
    portion_g: float = Field(default=100.0, gt=0, le=5000)
    nutrients: dict[str, float] = Field(default_factory=dict)
    vegan_status: str = Field(default="unknown", min_length=1,
                              max_length=20)


class MealCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    items: list[MealItemBody] = Field(min_length=1,
                                      max_length=30)
    source: str = Field(default="manual", min_length=1,
                        max_length=20)
    observed_at: str = Field(default="", max_length=80)
    provenance: dict[str, Any] = Field(default_factory=dict)


class GarminImportBody(BaseModel):
    provider: str = Field(default="mock", min_length=1,
                          max_length=20)
    since: str = Field(default="", max_length=80)
    cursor: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)


class ResearchSourceBody(BaseModel):
    source_type: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(default="", max_length=20000)
    external_id: str = Field(default="", max_length=200)
    reference: str = Field(default="", max_length=500)
    author: str = Field(default="", max_length=200)
    topics: list[str] = Field(default_factory=list,
                              max_length=20)
    entities: list[str] = Field(default_factory=list,
                                max_length=20)
    published_at: str = Field(default="", max_length=80)
    provenance: dict[str, Any] = Field(default_factory=dict)


class ResearchAdvanceBody(BaseModel):
    to_stage: str = Field(min_length=1, max_length=20)
    approved_by: str = Field(default="", max_length=80)


class ResearchClaimBody(BaseModel):
    claim: str = Field(min_length=1, max_length=1000)
    source_ids: list[str] = Field(min_length=1, max_length=10)
    evidence: str = Field(default="", max_length=2000)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    interpretation: str = Field(default="", max_length=1000)


class ResearchRecordBody(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    claims: list[ResearchClaimBody] = Field(min_length=1,
                                            max_length=30)
    synthesis: str = Field(default="", max_length=5000)
    provenance: dict[str, Any] = Field(default_factory=dict)


class InstagramImportBody(BaseModel):
    export: dict[str, Any]
    collection: str = Field(default="", max_length=100)


class SkillCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=1000)
    prerequisites: list[str] = Field(default_factory=list,
                                     max_length=20)
    related_skills: list[str] = Field(default_factory=list,
                                      max_length=20)
    stage: str = Field(default="discovered", min_length=1,
                       max_length=20)
    proficiency: str = Field(default="unknown", min_length=1,
                             max_length=20)
    project_refs: list[str] = Field(default_factory=list,
                                    max_length=20)
    source: str = Field(default="", max_length=200)
    provenance: dict[str, Any] = Field(default_factory=dict)


class SkillEvidenceBody(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    ref: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=300)


class SkillAdvanceBody(BaseModel):
    to_stage: str = Field(min_length=1, max_length=20)
    confirmed_by: str = Field(default="", max_length=80)


class SkillDiscoverBody(BaseModel):
    project_text: str = Field(min_length=1, max_length=5000)
    project_ref: str = Field(default="", max_length=100)


class SkillAcceptBody(BaseModel):
    accepted_by: str = Field(min_length=1, max_length=80)


class AdvancedOpBody(BaseModel):
    """One advanced mesh op (mirror/merge/extend/orient).
    Preview always; persist writes a derived working file."""

    artifact_ref: str = Field(min_length=1, max_length=200)
    op: str = Field(min_length=1, max_length=20)
    params: dict[str, Any] = Field(default_factory=dict)
    extra_refs: list[str] = Field(default_factory=list,
                                  max_length=9)
    persist: bool = False
    max_tris: int = Field(default=5000, ge=1, le=5000)


class PromptEditBody(BaseModel):
    """'maak deze bracket 5mm langer'. Parsed to an explicit
    op; persist needs a human approver."""

    artifact_ref: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=500)
    persist: bool = False
    approved_by: str = Field(default="", max_length=80)
    max_tris: int = Field(default=5000, ge=1, le=5000)


class CadDocumentBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    provenance: dict[str, Any] = Field(default_factory=dict)


class CadPartBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CadOpBody(BaseModel):
    part_id: str = Field(min_length=1, max_length=80)
    op: str = Field(min_length=1, max_length=20)
    params: dict[str, Any] = Field(default_factory=dict)
    adapter: str = Field(default="procedural", min_length=1,
                         max_length=20)


class SpoolCreateBody(BaseModel):
    material: str = Field(min_length=1, max_length=20)
    weight_g: float = Field(ge=0, le=10000)
    color: str = Field(default="", max_length=40)
    diameter_mm: float = Field(default=1.75, gt=0, le=5)
    compatible_profiles: list[str] = Field(
        default_factory=list, max_length=10)
    source: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=200)
    provenance: dict[str, Any] = Field(default_factory=dict)


class PrinterSelectBody(BaseModel):
    capabilities: list[str] = Field(default_factory=list,
                                    max_length=20)
    profile: str = Field(default="", max_length=40)
    printer_id: str = Field(default="", max_length=80)


class PipelinePlanBody(BaseModel):
    source_object_id: str = Field(default="", max_length=100)
    source_idea_id: str = Field(default="", max_length=100)
    profile: str = Field(default="draft-pla", min_length=1,
                         max_length=40)
    material: str = Field(default="PLA", min_length=1,
                          max_length=20)


class RobotCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    robot_type: str = Field(default="other", min_length=1,
                            max_length=20)
    capabilities: list[str] = Field(default_factory=list,
                                    max_length=20)
    location: str = Field(default="", max_length=200)
    node_id: str = Field(default="", max_length=80)
    sensors: list[str] = Field(default_factory=list,
                               max_length=20)
    actuators: list[str] = Field(default_factory=list,
                                 max_length=20)
    provenance: dict[str, Any] = Field(default_factory=dict)


class RobotSafetyBody(BaseModel):
    safety_state: str = Field(min_length=1, max_length=20)


class RobotActionBody(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    params: dict[str, Any] = Field(default_factory=dict)
    simulation_note: str = Field(default="", max_length=500)
    actor: str = Field(min_length=1, max_length=80)


class RobotApproveBody(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=80)
    response: str = Field(min_length=1, max_length=20)
    decided_by: str = Field(min_length=1, max_length=80)


class RobotTelemetryBody(BaseModel):
    action_id: str = Field(min_length=1, max_length=80)
    robot_id: str = Field(min_length=1, max_length=80)
    status: str = Field(min_length=1, max_length=40)
    detail: str = Field(default="", max_length=500)
    observation_ref: str = Field(default="", max_length=120)


class DroneCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    capabilities: list[str] = Field(default_factory=list,
                                    max_length=20)
    home_location: str = Field(default="", max_length=200)
    provenance: dict[str, Any] = Field(default_factory=dict)


class DroneMissionBody(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    params: dict[str, Any] = Field(default_factory=dict)
    autonomous: bool = False
    geofence: str = Field(default="", max_length=200)
    max_altitude_m: float = Field(default=0.0, ge=0, le=120)
    actor: str = Field(min_length=1, max_length=80)


class DroneMissionApproveBody(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=80)
    response: str = Field(min_length=1, max_length=20)
    decided_by: str = Field(min_length=1, max_length=80)


class FamiliarCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=20)
    linked_id: str = Field(default="", max_length=120)
    provenance: dict[str, Any] = Field(default_factory=dict)


class TwinLinkBody(BaseModel):
    physical_ref: str = Field(min_length=1, max_length=200)
    digital_ref: str = Field(min_length=1, max_length=120)
    link_type: str = Field(min_length=1, max_length=20)
    source: str = Field(default="", max_length=200)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    last_observed_at: str = Field(default="", max_length=80)
    provenance: dict[str, Any] = Field(default_factory=dict)


class JobRunBody(BaseModel):
    job_name: str = Field(min_length=1, max_length=40)
    params: dict[str, Any] = Field(default_factory=dict)
    run_key: str = Field(default="", max_length=80)


class IntegrationKeyBody(BaseModel):
    """Issue (or rotate) an integration bearer key. Operator
    only; the plaintext returns exactly once."""

    operator_key: str = Field(default="", max_length=256)
    capabilities: list[str] = Field(default_factory=list,
                                    max_length=10)


class IntegrationEnvelopeBody(BaseModel):
    """One inbound n8n envelope. Observation/input only:
    never fact, never approval, never execution."""

    integration_id: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=40)
    external_event_id: str = Field(min_length=1, max_length=200)
    event_type: str = Field(min_length=1, max_length=40)
    occurred_at: str = Field(min_length=1, max_length=80)
    received_at: str = Field(default="", max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_hash: str = Field(default="", max_length=80)
    provenance: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = Field(default="1", max_length=10)
    idempotency_key: str = Field(min_length=1, max_length=200)


class IntegrationTriggerBody(BaseModel):
    integration_id: str = Field(min_length=1, max_length=80)
    job_name: str = Field(min_length=1, max_length=40)
    params: dict[str, Any] = Field(default_factory=dict)
    run_key: str = Field(default="", max_length=80)


class OutboxEnqueueBody(BaseModel):
    target_label: str = Field(min_length=1, max_length=40)
    payload: dict[str, Any] = Field(default_factory=dict)
    operator_key: str = Field(default="", max_length=256)


class OutboxAckBody(BaseModel):
    integration_id: str = Field(min_length=1, max_length=80)
    failed: bool = False


class CommandBody(BaseModel):
    """One natural-language command for the Command Center."""

    text: str = Field(min_length=1, max_length=500)
    conversation_id: str = Field(default="", max_length=80)


class RecoverBody(BaseModel):
    """Mission recovery scan; resume_safe drives read-only resumes."""

    resume_safe: bool = False
    max_resume: int = Field(default=5, ge=1, le=20)


class AgendaImportBody(BaseModel):
    """ICS import: preview first, confirm stores with UID dedup."""

    ics_text: str = Field(min_length=1, max_length=500000)
    source_label: str = Field(default="import", max_length=120)
    preview_only: bool = True


class BootstrapBody(BaseModel):
    """Idempotent bootstrap campaign creation."""

    conversation_id: str = Field(min_length=3, max_length=80)
    auto_approve: bool = False


class ResearchRunBody(BaseModel):
    """Open a research run. provider: wikipedia (REAL attempt),
    test (deterministic fixtures, TEST label), unavailable
    (honest no-op). source_urls: explicit operator-supplied
    URLs, REAL direct fetch through the hardened transport.
    test_pages only for explicit fixtures."""

    question: str = Field(min_length=1, max_length=500)
    objective: str = Field(default="", max_length=500)
    project_ref: str = Field(default="", max_length=100)
    mission_id: str = Field(default="", max_length=80)
    provider: str = Field(default="wikipedia", max_length=20)
    max_sources: int = Field(default=6, ge=1, le=6)
    source_urls: list[str] = Field(default_factory=list,
                                   max_length=6)
    test_pages: dict[str, list[str]] = Field(default_factory=dict)
    execute: bool = True


class ResearchExecuteBody(BaseModel):
    """Re-drive a draft/blocked/failed run."""

    provider: str = Field(default="wikipedia", max_length=20)
    max_sources: int = Field(default=6, ge=1, le=6)
    source_urls: list[str] = Field(default_factory=list,
                                   max_length=6)
    test_pages: dict[str, list[str]] = Field(default_factory=dict)
