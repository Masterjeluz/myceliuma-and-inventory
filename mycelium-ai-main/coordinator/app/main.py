import hashlib
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import ValidationError

from .adapter_contracts import AdapterProposal
from .advisor_proposals import extract_proposal
from .agent_loop import (
    DesktopActionRecord,
    cancel as agent_cancel,
    decide as agent_decide,
    describe as agent_describe,
    dispatch as agent_dispatch,
    propose as agent_propose,
    record_result as agent_record_result,
)
from .approval import ApprovalResult, decide as decide_approval, request_approval
from .controlled_writes import (
    WriteApproval,
    WriteProposal,
    WriteResult,
    decide_write,
    request_write_approval,
    write_fingerprint,
)
from .fab_flow import (
    FabricationRecord,
    PrintFailedError,
    PrintRefusedError,
    execute_print,
    list_fabrications,
    load_fabrication,
    new_fabrication,
    new_telemetry_request,
    print_verdict,
    propose_print,
    record_event,
    save_fabrication,
    verify_print_camera,
    verify_print_telemetry,
)
from .failover import (
    ElectionRefusedError,
    FencingError,
    campaign as failover_campaign,
    current_epoch,
    release as failover_release,
    require_epoch,
    require_writer_epoch,
    sync_status as failover_status,
)
from .live import (
    GIT_PUSH_CAPABILITY,
    LiveRefusedError,
    check_capabilities as live_check_caps,
    live_can,
    load_live_session,
    open_session as live_open_session,
    pack_context,
    revoke_live_session,
    save_live_session,
    session_live,
)
from .reports import (
    ReportRefusedError,
    assemble_report,
    make_block,
    morning_report,
)
from .sync import (
    SyncRefusedError,
    apply_pulled,
    fetch_inventory_changes,
    pull_changes,
    sync_status as dist_sync_status,
)
from .watcher import (
    WatcherRefusedError,
    scan_blocked_tasks,
    scan_device_staleness,
    scan_entities,
    scan_failed_tasks,
    scan_projects,
    scan_provenance,
    scan_relationships,
    scan_stale_tasks,
    scan_unfinished_designs,
)
from .mesh3d import (
    MeshRefusedError,
    MeshUnavailable,
    assess_printability,
    check_artifact_ref,
    check_transform,
    file_payload_for_mesh,
    get_generator,
    mesh_facets,
    read_artifact_bytes,
    transform_facets,
    validate_mesh,
    write_derived_mesh,
)
from .git_commit import (
    GitWriteFailedError,
    GitWriteRefusedError,
    execute_git_commit,
    propose_git_commit,
    verify_git_commit,
)
from .inventory_writes import (
    InventoryWriteFailedError,
    InventoryWriteRefusedError,
    InventoryWriter,
    execute_inventory_write,
    propose_inventory_write,
)
from .project_package import (
    assemble_project_package,
    summarize_for_chat,
)
from .printer3d import (
    PrinterRefusedError as PrinterDeviceRefusedError,
    PrinterUnavailable,
    adapter_capabilities as printer_capabilities,
    adapter_for_printer,
    get_printer,
    list_printers,
    list_stored_printers,
    load_printer,
    new_job,
    new_printer,
    register_printer,
    save_printer,
)
from .slicer3d import (
    SlicerRefusedError,
    SlicerUnavailable,
    check_slicer_request,
    file_payload_for_gcode,
    get_slicer,
    validate_gcode,
)
from .verification import (
    VerificationRequest,
    is_verified,
    new_verification_request,
    verify_inventory_write,
)
from .diststate import (
    DistStateRefusedError,
    apply_envelope,
    detect_conflict,
    entity_history,
    known_event_ids,
    list_conflicts,
    new_conflict,
    new_envelope,
    read_log,
    resolve_conflict,
    save_conflict,
    save_envelope,
)
from .domains import (
    DomainRefusedError,
    domain_info,
    ingestion_stage,
    list_domains,
)
from .events import (
    EventRefusedError,
    list_events as bus_events,
    list_notifications,
    mark_notification_read,
    new_event as bus_event,
    new_notification,
    prune_events,
    save_event as save_bus_event,
    save_notification,
)
from .interface import (
    InterfaceRefusedError,
    TextInterface,
    VoiceInterface,
    generate_interface_id,
    list_sessions,
    load_session,
    new_interface_message,
    new_session,
    revoke_session,
    save_session,
    session_usable,
    touch_session,
)
from .vision_flow import (
    VisionAnalysisRecord,
    identification_candidates,
    list_analyses,
    load_analysis,
    save_analysis,
    verify_observation,
    vision_to_file_proposal,
    vision_to_object_proposal,
)
from .voice import (
    TestSTTProvider,
    TestTTSProvider,
    UnavailableSTTProvider,
    UnavailableTTSProvider,
    VoiceRefusedError,
    VoiceUnavailable,
    audio_facts,
    check_audio_ref,
    clear_capture_sessions,
    close_capture_session,
    delete_audio,
    get_capture_session,
    get_stt_provider,
    get_tts_provider,
    open_capture_session,
    prune_audio,
    read_audio_bytes,
)
from .voice_approval import (
    VOICE_APPROVABLE_KINDS,
    VoiceApprovalRefusedError,
    VoiceApprovalRequest,
    load_voice_request,
    mark_voice_resolved,
    now as voice_now,
    pending_voice_requests,
    resolve_voice_approval,
    save_voice_request,
)
from .vision_ingest import (
    IngestRefusedError,
    StreamManager,
    adapter_for,
    file_payload_for,
    ingest_snapshot,
    media_facts,
    probe_availability,
)
from .vision_provider import (
    VisionRefusedError,
    VisionRequest,
    VisionResult,
    VisionUnavailable,
    get_vision_provider,
)
from .cameras import (
    CameraRefusedError,
    CameraUnavailable,
    detect_local_imaging_devices,
    get_device,
    list_devices,
    list_observations,
    new_device,
    save_device,
    save_observation,
    take_snapshot,
)
from .computer_actions import capability_for, new_action
from .conversations import (
    generate_conversation_id,
    new_message,
)
from .database import chat_connection, connection, dump, init_chat_database, init_database, load
from .mission_executor import ExecutorDeps, ExecutorError, MissionExecutor
from .mission_templates import get_template, instantiate, list_templates
from .missions import (
    DISPATCHABLE_KINDS,
    MissionConflictError,
    bindings_for_mission,
    dispatch_source_urls,
    dispatchable_task,
    get_binding,
    list_events,
    list_missions,
    load_mission,
    new_event,
    save_event,
    save_mission,
    set_step,
)
from .git_context import (
    GitRefusedError,
    GitUnavailable,
    git_branch,
    git_diff,
    git_status,
)
from .plans import Plan, PlanStep, plan_to_proposal, validate_plan
from .project_context import default_context
from .proposal_tasks import CoordinatorTask, proposal_to_task
from .worldgraph import build_world_graph
from .providers import (
    ProviderRefusedError,
    ProviderUnavailable,
    get_provider,
)
from .inventory_read import (
    EntityRecord,
    GraphResponse,
    InventoryReader,
    InventoryRefusedError,
    InventoryUnavailable,
    SearchResponse,
)
from .nodes import (
    NodeAuthError,
    NodeRefusedError,
    authenticate,
    check_capabilities,
    check_display_name,
    check_executors,
    check_locality,
    check_models,
    check_node_id,
    check_node_token_strength,
    check_operator_key,
    check_resources,
    derive_status,
    hash_token,
)
from .ollama_advisor import (
    OllamaAdvisor,
    OllamaRefusedError,
    OllamaUnavailable,
)
from .routing import (
    RouteDecision,
    TaskRequirements,
    check_policy,
    check_requirements,
    requirements_from_payload,
    route_task,
)
from .schemas import AdviseRequest, AdviseResponse, AdvancedOpBody, CadDocumentBody, CadOpBody, CadPartBody, CampaignBody, CameraRegisterBody, CaptureCloseBody, CaptureOpenBody, ChatMissionBody, ChatRequest, ChatResponse, ClaimedTask, DecideApprovalBody, DesktopActionBody, DesktopClaimBody, DesktopDecisionBody, DesktopDispatchBody, DesktopResultBody,     DistEnvelopeBody, DroneCreateBody, DroneMissionApproveBody, DroneMissionBody,     FabGenerateBody, FabSliceBody, FamiliarCreateBody, FoodCreateBody, GarminImportBody, GitCommitBody, HealthMeasureBody, Heartbeat, InstagramImportBody,     InterfaceChatBody, IntegrationEnvelopeBody, IntegrationKeyBody, IntegrationTriggerBody, InventoryWriteBody, JobRunBody, LiveContextBody, LiveProposeBody, LiveSessionBody, MealCreateBody, MealItemBody, MemoryConsolidateBody, MemoryCreateBody, MemoryRetrieveBody, MemoryVerifyBody,     MissionApproveBody, MissionCreateBody, MissionDispatchBody, MissionRunBody, MissionStepBody, NodeRegistration, NodeRotateBody,     NotifyBody, OperatorBody, OutboxAckBody, OutboxEnqueueBody,     PhoneCameraBody,     PlanBody, RemoteInputSessionBody, RemoteInputMoveBody, RemoteInputActionBody, RemoteInputPollBody, PlanToProposalBody, PipelinePlanBody, PrintCancelBody, PrintProposeBody, PrinterRegisterBody, PrinterSelectBody, PromptEditBody, ResearchAdvanceBody, ResearchClaimBody, ResearchRecordBody, ResearchSourceBody, RobotActionBody, RobotApproveBody, RobotCreateBody, RobotSafetyBody, RobotTelemetryBody, SessionOpenBody,     StreamStartBody, SuggestStepsBody, WorkspaceForkBody, WorkspaceMissionAttachBody, WorkspaceResearchStartBody, SkillAcceptBody, SkillAdvanceBody, SkillCreateBody, SkillDiscoverBody, SkillEvidenceBody, SpoolCreateBody, SyncApplyBody, TaskAssignBody, TaskCreate, TaskFromProposalBody, TaskResult, TaskRouteBody,     TemplateMissionBody, TransformBody, TwinLinkBody, VisionAnalyzeBody, VisionProposeBody, VoiceApprovalRequestBody, VoiceApproveBody, VoiceChatBody,     VoiceSynthesizeBody, VoiceTranscribeBody, WriteDecisionBody, CommandBody, RecoverBody, AgendaImportBody, BootstrapBody, ResearchRunBody, ResearchExecuteBody, PresenceTriageBody, PresenceNotifyBody, MeshDelegateBody, MeshPreviewBody, HardwareLinkBody, CampaignCreateBody, HardwareVerifyBody, HardwareRevokeBody, FinanceRecordBody, FinanceStatusBody, EnergyRecordBody, QuestCreateBody, WorkflowDispatchBody

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("mycelium.coordinator")

# M7.4 lease/stale/attempt policy. Explicit, deterministic, injectable in
# tests via the now_str parameters of the core functions below.
LEASE_SECONDS = 300
MAX_ATTEMPTS = 3
NODE_STALE_SECONDS = 60


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def node_is_stale(last_seen: str, now_str: str | None = None) -> bool:
    """A node whose heartbeat is older than NODE_STALE_SECONDS is stale."""
    try:
        current = _parse_time(now_str) if now_str else datetime.now(timezone.utc)
        age = current - _parse_time(last_seen)
    except (ValueError, TypeError):
        return True
    return age > timedelta(seconds=NODE_STALE_SECONDS)


def _lease_until(now_str: str) -> str:
    return (_parse_time(now_str) + timedelta(seconds=LEASE_SECONDS)).isoformat()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database()
    logger.info("coordinator_started")
    try:
        _v1_startup_scan()
    except Exception as error:
        logger.warning("startup_scan_skipped cause=%s", error)
    yield


def _v1_startup_scan() -> None:
    """Boot recovery inspection (BIG #25): reconstruct unfinished
    missions, log the verdicts, execute NOTHING. Safe read-only
    steps resume only through an explicit POST /api/v1/command
    ('ga verder') or POST /api/v1/missions/recover call."""
    from .agenda import init_agenda_tables
    init_chat_database()
    with chat_connection() as db:
        init_agenda_tables(db)
    try:
        from .research_engine import init_engine_tables
        with chat_connection() as db:
            init_engine_tables(db)
    except Exception as error:
        logger.warning("engine_tables_skipped cause=%s", error)
    from .missions import bindings_for_mission, list_missions
    from .recovery import scan
    missions = list_missions(limit=100)
    if not missions:
        logger.info("startup_scan no_missions")
        return
    report = scan(missions,
                  lambda mission_id: bindings_for_mission(mission_id))
    logger.info("startup_scan total=%d counts=%s",
                report["total"], report["counts"])
    for item in report["verdicts"]:
        if item["verdict"] in ("needs_reapproval", "waiting_agent"):
            logger.info("startup_scan mission=%s verdict=%s reason=%s",
                        item["mission_id"], item["verdict"],
                        item["reason"][:160])


app = FastAPI(title="Mycelium AI Coordinator", version="0.1.0", lifespan=lifespan)

try:
    from .routes_conversations import router as _conv_router
    app.include_router(_conv_router)
except Exception:
    pass


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "healthy", "service": "mycelium-coordinator"}


@app.post("/api/v1/nodes/register", status_code=201)
def register_node(node: NodeRegistration) -> dict[str, str]:
    """Register or refresh a node. New identities require a
    non-trivial token (403 without): choosing a node_id alone
    never creates authority. Token-bound identities verify on
    every refresh. Legacy (tokenless) identities keep working
    but frozen — only freshness updates, never advertisement
    or authority changes — until operator rotation binds a
    token. A disabled node stays disabled (fail-closed).
    Never returns or logs credentials."""
    try:
        node_id = check_node_id(node.node_id)
        capabilities = check_capabilities(node.capabilities)
        models = check_models(node.models)
        executors = check_executors(node.executors)
        resources = check_resources(node.resources)
        locality_zone = check_locality(node.locality_zone)
        display_name = check_display_name(node.display_name)
    except NodeRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    if node.energy_source not in ("grid", "solar", "battery",
                                  "unknown"):
        raise HTTPException(status_code=422,
                            detail="energy_source unknown")
    capable = bool(node.coordinator_capable)
    with connection() as db:
        existing = db.execute(
            "SELECT status, auth_token_hash FROM nodes WHERE node_id=?",
            (node_id,)).fetchone()
        stored_hash = (existing["auth_token_hash"]
                       if existing else None)
        if existing is None and not node.node_token:
            raise HTTPException(
                status_code=403,
                detail="new node identities require a "
                       "node_token; choosing a node_id alone "
                       "creates no authority")
        if node.node_token:
            try:
                check_node_token_strength(node.node_token)
            except NodeRefusedError as error:
                raise HTTPException(status_code=422,
                                    detail=str(error))
        try:
            auth_mode = authenticate(node_id, stored_hash,
                                     node.node_token)
        except NodeAuthError:
            raise HTTPException(status_code=403,
                                detail="node credential rejected")
        bound_hash = stored_hash
        if node.node_token and not stored_hash:
            if existing is None:
                bound_hash = hash_token(node_id,
                                        node.node_token)
                auth_mode = "token"
            else:
                # Binding a token to an already-seen identity
                # is rotation: operator key required, otherwise
                # anyone could claim a legacy node_id.
                try:
                    check_operator_key(node.operator_key)
                except NodeAuthError:
                    raise HTTPException(
                        status_code=403,
                        detail="token binding on an existing "
                               "identity needs operator rotation")
                bound_hash = hash_token(node_id,
                                        node.node_token)
                auth_mode = "token"
        status = "online"
        if existing is not None and existing["status"] == "disabled":
            status = "disabled"
        if existing is not None and stored_hash is None \
                and not node.node_token:
            # Legacy freeze: freshness only. Advertisement,
            # authority flags and credentials never change
            # without a token or operator rotation.
            db.execute(
                "UPDATE nodes SET last_seen=?, status=?, "
                "last_auth=? WHERE node_id=?",
                (now(), status, auth_mode, node_id))
            logger.info("node_heartbeat_legacy node_id=%s",
                        node_id)
            emit_event("node.online",
                       f"Node {node_id} refreshed (legacy)",
                       node_id=node_id)
            return {"node_id": node_id, "status": "registered"}
        db.execute("""INSERT INTO nodes
        (node_id, hostname, tier, capabilities, cpu_cores, memory_mb,
         energy_source, last_seen, status, auth_token_hash,
         display_name, models, executors, resources, locality_zone,
         last_auth, coordinator_capable)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(node_id) DO UPDATE SET hostname=excluded.hostname,
        tier=excluded.tier, capabilities=excluded.capabilities,
        cpu_cores=excluded.cpu_cores, memory_mb=excluded.memory_mb,
        energy_source=excluded.energy_source,
        last_seen=excluded.last_seen, status=excluded.status,
        auth_token_hash=excluded.auth_token_hash,
        display_name=excluded.display_name, models=excluded.models,
        executors=excluded.executors, resources=excluded.resources,
        locality_zone=excluded.locality_zone,
        last_auth=excluded.last_auth,
        coordinator_capable=excluded.coordinator_capable""",
            (node_id, node.hostname, node.tier,
             dump(capabilities), node.cpu_cores, node.memory_mb,
             node.energy_source, now(), status, bound_hash,
             display_name, dump(models), dump(executors),
             dump(resources), locality_zone, auth_mode,
             1 if capable else 0))
    logger.info("node_registered node_id=%s tier=%s auth=%s",
                node_id, node.tier,
                "token" if auth_mode == "token" else "legacy")
    emit_event("node.online", f"Node {node_id} registered",
               node_id=node_id)
    return {"node_id": node_id, "status": "registered"}


@app.post("/api/v1/nodes/{node_id}/heartbeat", status_code=204)
def heartbeat(node_id: str, heartbeat_data: Heartbeat) -> Response:
    """Heartbeat with credential check and optional advertisement
    refresh. Unknown nodes 404; bad credentials and disabled
    nodes are refused; nothing secret is logged or returned.

    BIG #39: Accepts telemetry, hardware inventory, compute capabilities,
    and energy state for Hardware Reality Layer.
    """
    with connection() as db:
        row = db.execute(
            "SELECT status, auth_token_hash FROM nodes WHERE node_id=?",
            (node_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Node is not registered")
    if row["status"] == "disabled":
        raise HTTPException(status_code=403, detail="node disabled")
    try:
        auth_mode = authenticate(node_id, row["auth_token_hash"],
                                 heartbeat_data.node_token)
    except NodeAuthError:
        raise HTTPException(status_code=403,
                            detail="node credential rejected")
    if row["auth_token_hash"] is None:
        # Legacy freeze: freshness only, never advertisement.
        # Bind a token via operator rotation to refresh.
        with connection() as db:
            db.execute(
                "UPDATE nodes SET last_seen=?, status=?, "
                "last_auth=? WHERE node_id=?",
                (now(), "online" if heartbeat_data.available
                 else "busy", auth_mode, node_id))
        return Response(status_code=204)
    updates: dict[str, object] = {
        "last_seen": now(),
        "status": "online" if heartbeat_data.available else "busy",
        "last_auth": auth_mode,
    }
    try:
        if heartbeat_data.capabilities is not None:
            updates["capabilities"] = dump(check_capabilities(
                heartbeat_data.capabilities))
        if heartbeat_data.models is not None:
            updates["models"] = dump(check_models(
                heartbeat_data.models))
        if heartbeat_data.executors is not None:
            updates["executors"] = dump(check_executors(
                heartbeat_data.executors))
        if heartbeat_data.resources is not None:
            updates["resources"] = dump(check_resources(
                heartbeat_data.resources))
        # BIG #39: Hardware Reality Layer telemetry
        from .nodes import (
            check_telemetry, check_hardware, check_compute_capabilities,
            check_energy_state, check_displays
        )
        if heartbeat_data.telemetry is not None:
            updates["telemetry"] = dump(check_telemetry(
                heartbeat_data.telemetry))
            updates["telemetry_timestamp"] = now()
        if heartbeat_data.hardware is not None:
            updates["hardware"] = dump(check_hardware(
                heartbeat_data.hardware))
        if heartbeat_data.compute_capabilities is not None:
            updates["compute_capabilities"] = dump(check_compute_capabilities(
                heartbeat_data.compute_capabilities))
        if heartbeat_data.energy_state is not None:
            updates["energy_state"] = dump(check_energy_state(
                heartbeat_data.energy_state))
        # VERTICAL SLICE 1: read-only display report (node-state).
        if heartbeat_data.displays is not None:
            updates["displays"] = dump(check_displays(
                heartbeat_data.displays))
    except NodeRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    with connection() as db:
        # Build dynamic UPDATE for all provided fields
        set_clauses = ["last_seen=?", "status=?", "last_auth=?"]
        params = [updates["last_seen"], updates["status"], updates["last_auth"]]
        optional_fields = ("capabilities", "models", "executors", "resources",
                           "telemetry", "telemetry_timestamp", "hardware",
                           "compute_capabilities", "energy_state", "displays")
        for field in optional_fields:
            if field in updates:
                set_clauses.append(f"{field}=COALESCE(?, {field})")
                params.append(updates[field])
        params.append(node_id)
        db.execute(
            f"UPDATE nodes SET {', '.join(set_clauses)} WHERE node_id=?",
            tuple(params))
    return Response(status_code=204)


NODE_PUBLIC_COLUMNS = (
    "node_id, hostname, tier, capabilities, cpu_cores, memory_mb, "
    "energy_source, last_seen, status, display_name, models, "
    "executors, resources, locality_zone, last_auth, "
    "coordinator_capable, telemetry, telemetry_timestamp, hardware, "
    "compute_capabilities, energy_state, health, displays"
)


def _assigned_tasks_map() -> dict:
    """Nodes → their currently assigned task (if any). One
    indexed query; best-effort (empty on any failure). Drives
    the `current_task` node field and Routing 2.0 workload
    hints. Read-only."""
    try:
        with connection() as db:
            rows = db.execute(
                "SELECT id, kind, assigned_node_id FROM tasks "
                "WHERE status='assigned' AND assigned_node_id "
                "IS NOT NULL ORDER BY id ASC").fetchall()
    except Exception:
        return {}
    tasks: dict[str, dict] = {}
    for row in rows:
        node_id = str(row["assigned_node_id"] or "")
        if node_id and node_id not in tasks:
            tasks[node_id] = {"task_id": row["id"],
                              "kind": str(row["kind"] or "")}
    return tasks


def _node_to_json(row, tasks_by_node: dict | None = None) -> dict:
    record = dict(row)
    for key in ("capabilities", "models", "executors", "resources",
                "telemetry", "hardware", "compute_capabilities", "energy_state",
                "displays"):
        try:
            record[key] = load(record.get(key) or (
                "[]" if key not in ("resources", "telemetry", "energy_state") else "{}"))
        except ValueError:
            record[key] = [] if key not in ("resources", "telemetry", "energy_state") else {}
    if not isinstance(record.get("displays"), list):
        record["displays"] = []
    record["derived_status"] = derive_status(
        record.get("status", "unknown"), record.get("last_seen", ""))
    try:
        record["coordinator_capable"] = bool(
            int(record.get("coordinator_capable", 0) or 0))
    except (TypeError, ValueError):
        record["coordinator_capable"] = False
    # Compute health status from telemetry freshness and node state
    record["health_status"] = _compute_health_status(record)
    # BIG #41: currently executing task, if any (read-only join).
    if tasks_by_node is None:
        record["current_task"] = None
    else:
        record["current_task"] = tasks_by_node.get(
            record.get("node_id", ""))
    return record


def _compute_health_status(record: dict) -> str:
    """Compute node health from telemetry freshness and state."""
    derived = record.get("derived_status", "unknown")
    if derived == "disabled":
        return "OFFLINE"
    if derived == "offline":
        return "OFFLINE"
    if derived == "stale":
        return "STALE"
    # Online/busy nodes: check telemetry freshness
    telemetry_ts = record.get("telemetry_timestamp", "")
    if telemetry_ts:
        try:
            from datetime import datetime, timezone, timedelta
            ts = datetime.fromisoformat(telemetry_ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - ts
            if age > timedelta(minutes=5):
                return "DEGRADED"
        except (ValueError, TypeError):
            pass
    return "ONLINE"


@app.get("/api/v1/nodes")
def list_nodes() -> list[dict]:
    with connection() as db:
        rows = db.execute(
            f"SELECT {NODE_PUBLIC_COLUMNS} FROM nodes "
            "ORDER BY last_seen DESC").fetchall()
    tasks_by_node = _assigned_tasks_map()
    return [_node_to_json(row, tasks_by_node) for row in rows]


@app.get("/api/v1/nodes/{node_id}")
def get_node(node_id: str) -> dict:
    with connection() as db:
        row = db.execute(
            f"SELECT {NODE_PUBLIC_COLUMNS} FROM nodes WHERE node_id=?",
            (node_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Node is not registered")
    return _node_to_json(row, _assigned_tasks_map())


@app.get("/api/v1/digital-world")
def digital_world() -> dict:
    """Derived NODE -> DISPLAY view (VERTICAL SLICE 1).

    Read-only: pure derivation over the node registry
    (derive_digital_world). No writes, no node contact, no
    display database — the snapshot is a VIEW of node-state
    with provenance 'derived'. Unknown display values stay
    null; UI position/scale/selection live client-side only."""
    from .nodes import derive_digital_world
    return derive_digital_world(list_nodes())


@app.get("/api/v1/nodes/{node_id}/reality")
def node_reality(node_id: str) -> dict:
    """Live hardware reality for one node (BIG #41).

    Derived now from the registry row + assigned task:
    online state, heartbeat age, telemetry summary, hardware
    with ADVERTISED/OBSERVED trust, compute, energy, role,
    current task. VERIFIED is defined but never auto-derived:
    only an explicit human link (like printer twins) may
    verify a claim. Read-only; unknown nodes 404.
    """
    from .nodes import hardware_trust
    with connection() as db:
        row = db.execute(
            f"SELECT {NODE_PUBLIC_COLUMNS} FROM nodes WHERE node_id=?",
            (node_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Node is not registered")
    record = _node_to_json(row, _assigned_tasks_map())
    telemetry = record.get("telemetry", {})
    if not isinstance(telemetry, dict):
        telemetry = {}
    try:
        from datetime import datetime, timezone
        seen = record.get("last_seen", "")
        moment = datetime.fromisoformat(seen)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        heartbeat_age_s = int(
            (datetime.now(timezone.utc) - moment).total_seconds())
    except (ValueError, TypeError):
        heartbeat_age_s = -1
    hardware = []
    try:
        from .hardware_links import trust_for as _human_trust
    except Exception:
        _human_trust = None
    for item in record.get("hardware", []) or []:
        if not isinstance(item, dict):
            continue
        trust, why = hardware_trust(
            item, record.get("telemetry_timestamp", ""))
        # BIG #42 human-link overlay: a live VERIFIED link for this
        # exact node + device ref upgrades trust to VERIFIED.
        # Nothing else may — hardware_trust() itself can never
        # return VERIFIED.
        if _human_trust is not None:
            try:
                verified, verified_why = _human_trust(
                    record.get("node_id", ""),
                    str(item.get("identifier", "")))
            except Exception:
                verified, verified_why = ("", "")
            if verified == "VERIFIED":
                trust, why = verified, verified_why
        hardware.append({
            "kind": str(item.get("kind", "")),
            "identifier": str(item.get("identifier", "")),
            "status": str(item.get("status", "")),
            "details": item.get("details", {})
            if isinstance(item.get("details"), dict) else {},
            "trust": trust,
            "trust_reason": why,
        })
    compute = [entry for entry in
               (record.get("compute_capabilities", []) or [])
               if isinstance(entry, dict)]
    return {
        "node_id": record["node_id"],
        "derived_status": record.get("derived_status", "unknown"),
        "health_status": record.get("health_status", "UNKNOWN"),
        "heartbeat_age_seconds": heartbeat_age_s,
        "telemetry": {key: telemetry.get(key) for key in
                      ("cpu_percent", "cpu_count",
                       "memory_percent", "memory_total_mb",
                       "memory_available_mb", "disk_percent",
                       "disk_total_gb", "disk_free_gb",
                       "temperature_celsius", "uptime_seconds",
                       "load_average")},
        "telemetry_timestamp": record.get("telemetry_timestamp",
                                          ""),
        "hardware": hardware,
        "compute_capabilities": [
            {"capability": str(entry.get("capability", "")),
             "status": str(entry.get("status", ""))}
            for entry in compute],
        "energy_state": record.get("energy_state", {})
        if isinstance(record.get("energy_state"), dict) else {},
        "displays": record.get("displays", [])
        if isinstance(record.get("displays"), list) else [],
        "roles": _node_role_list(record),
        "current_task": record.get("current_task"),
        "last_seen": record.get("last_seen", ""),
        "provenance": {"source_type": "derived",
                       "creator_id": "hardware-reality",
                       "human_verified": False},
    }


@app.post("/api/v1/nodes/{node_id}/rotate-token")
def rotate_node_token(node_id: str,
                      body: NodeRotateBody) -> dict:
    """Bind or rotate a node token. Bound identities present
    the current token; legacy identities need the operator
    key (local env). Never returns the token or its hash."""
    try:
        new_token = check_node_token_strength(body.new_token)
    except NodeRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    with connection() as db:
        row = db.execute(
            "SELECT auth_token_hash FROM nodes WHERE node_id=?",
            (node_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Node is not registered")
    stored_hash = row["auth_token_hash"]
    if stored_hash:
        try:
            authenticate(node_id, stored_hash,
                         body.current_token)
        except NodeAuthError:
            raise HTTPException(
                status_code=403,
                detail="current token rejected; rotation refused")
    else:
        try:
            check_operator_key(body.operator_key)
        except NodeAuthError:
            raise HTTPException(
                status_code=403,
                detail="binding a token to a legacy identity "
                       "needs the operator key")
    with connection() as db:
        db.execute("UPDATE nodes SET auth_token_hash=?, "
                   "last_auth=? WHERE node_id=?",
                   (hash_token(node_id, new_token), "token",
                    node_id))
    logger.info("node_token_rotated node_id=%s", node_id)
    return {"node_id": node_id, "bound": True}


@app.post("/api/v1/nodes/{node_id}/disable")
def disable_node(node_id: str, body: OperatorBody) -> dict:
    """Disable a node. Operator key required: an
    unauthenticated caller cannot mutate node state."""
    try:
        check_operator_key(body.operator_key)
    except NodeAuthError:
        raise HTTPException(
            status_code=403,
            detail="operator authorization rejected")
    with connection() as db:
        changed = db.execute(
            "UPDATE nodes SET status='disabled' WHERE node_id=?",
            (node_id,)).rowcount
    if not changed:
        raise HTTPException(404, "Node is not registered")
    logger.info("node_disabled node_id=%s", node_id)
    return {"node_id": node_id, "status": "disabled"}


@app.post("/api/v1/nodes/{node_id}/enable")
def enable_node(node_id: str, body: OperatorBody) -> dict:
    """Re-enable a node. Operator key required: disabled
    stickiness cannot be cleared by the node itself."""
    try:
        check_operator_key(body.operator_key)
    except NodeAuthError:
        raise HTTPException(
            status_code=403,
            detail="operator authorization rejected")
    with connection() as db:
        changed = db.execute(
            "UPDATE nodes SET status='online', last_seen=? "
            "WHERE node_id=?",
            (now(), node_id)).rowcount
    if not changed:
        raise HTTPException(404, "Node is not registered")
    logger.info("node_enabled node_id=%s", node_id)
    return {"node_id": node_id, "status": "online"}


@app.post("/api/v1/tasks", status_code=201)
def create_task(task: TaskCreate) -> dict[str, object]:
    """Create one queued task. Routing requirements come from the
    explicit field and (validated, merged) the reserved payload
    key; the payload never keeps a shadow copy afterwards.
    mission_id is traceability only: it must reference a real
    mission, never causes execution, and stays NULL for
    general/system tasks."""
    try:
        requirements = check_requirements(task.requirements or {})
        embedded = requirements_from_payload(task.payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    merged = embedded.model_dump(mode="json")
    explicit = requirements.model_dump(mode="json")
    for key, value in explicit.items():
        if value != TaskRequirements.model_fields[key].default:
            merged[key] = value
    try:
        requirements = check_requirements(merged)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    mission_id = (task.mission_id or "").strip() or None
    if mission_id is not None:
        from .missions import load_mission as _load_mission
        if _load_mission(mission_id) is None:
            raise HTTPException(status_code=422,
                                detail="unknown mission_id")
    payload = dict(task.payload)
    payload.pop("routing", None)
    with connection() as db:
        cursor = db.execute("""INSERT INTO tasks (kind,payload,required_capabilities,preferred_tier,priority,status,created_at,routing,mission_id)
        VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
        (task.kind, dump(payload), dump(task.required_capabilities), task.preferred_tier, task.priority, now(),
          dump(requirements.model_dump(mode="json")), mission_id))
    logger.info("task_created task_id=%s kind=%s", cursor.lastrowid, task.kind)
    emit_event("task.queued", f"Task {cursor.lastrowid} ({task.kind}) queued",
               task_id=str(cursor.lastrowid),
               mission_id=mission_id or "")
    return {"id": cursor.lastrowid, "status": "queued"}


def _routing_candidates(now_str: str | None = None) -> list[dict]:
    """Node rows projected to routing input. Never credentials."""
    with connection() as db:
        rows = db.execute(
            f"SELECT {NODE_PUBLIC_COLUMNS}, auth_token_hash "
            "FROM nodes").fetchall()
    assigned = _assigned_tasks_map()
    workload = {node_id: 1 for node_id in assigned}
    candidates = []
    for row in rows:
        record = _node_to_json(row, assigned)
        stored = str(record.get("status", "unknown"))
        derived = derive_status(stored, record.get("last_seen", ""),
                                now_str)
        last_auth = str(record.get("last_auth", ""))
        has_token = bool(row["auth_token_hash"])
        candidates.append({
            "node_id": record["node_id"],
            "capabilities": record["capabilities"],
            "models": record["models"],
            "executors": record["executors"],
            "resources": record["resources"],
            "locality_zone": record.get("locality_zone",
                                        "local_network"),
            "status": derived,
            "fresh": derived in ("online", "busy"),
            "has_token": has_token,
            "last_auth": last_auth,
            "authenticated": last_auth == "token",
            # BIG #39: Hardware Reality Layer projection for
            # telemetry-aware routing (already-validated store
            # data; never credentials).
            "hardware": record["hardware"],
            "compute_capabilities": record["compute_capabilities"],
            "telemetry_timestamp": record.get(
                "telemetry_timestamp", ""),
            "health_status": record.get("health_status",
                                        "UNKNOWN"),
            # BIG #41: Routing 2.0 workload hint (ordering
            # only, never eligibility).
            "running_tasks": workload.get(record["node_id"], 0),
        })
    return candidates


def _decision_for(task_id: int, requirements, policy,
                  only_node: str | None = None,
                  now_str: str | None = None) -> RouteDecision:
    try:
        policy_checked = check_policy(policy or {})
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    candidates = _routing_candidates(now_str)
    if only_node is not None:
        candidates = [entry for entry in candidates
                      if entry["node_id"] == only_node]
        if not candidates:
            raise HTTPException(404, "Node is not registered")
    for entry in candidates:
        # Legacy nodes (never bound a token) count as
        # authenticated only when the policy does not require it.
        if not entry["has_token"] and \
                not policy_checked.require_authenticated:
            entry["authenticated"] = True
    return route_task(requirements, candidates, policy_checked,
                      now_str)


@app.post("/api/v1/tasks/route")
def route_preview(body: TaskRouteBody) -> dict:
    """Dry-run routing: requirements + policy in, decision out.
    Nothing is assigned, queued or started here. The response
    carries a transparent WHY block (BIG #41 Routing 2.0):
    eligible / waiting / blocked / unavailable with reasons."""
    from .routing import explain_decision
    try:
        requirements = check_requirements(body.requirements or {})
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    decision = _decision_for(0, requirements, body.policy or {})
    stamped = decision.model_dump(mode="json")
    try:
        stamped["why"] = explain_decision(
            decision, _routing_candidates())
    except Exception:
        stamped["why"] = {"summary": "explanation unavailable",
                          "eligible": [], "waiting": [],
                          "blocked": [], "unavailable": [],
                          "lines": {}}
    return stamped


@app.post("/api/v1/tasks/{task_id}/assign")
def assign_task(task_id: int, body: TaskAssignBody) -> dict:
    """Explicit assignment of one queued task. Empty node_id
    auto-routes; a given node must prove eligible. The node must
    still pull/claim the task — assignment constrains, never
    pushes executable work."""
    with connection() as db:
        row = db.execute("SELECT * FROM tasks WHERE id=?",
                         (task_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Task not found")
    if row["status"] != "queued":
        raise HTTPException(
            status_code=409,
            detail=f"Task is {row['status']}; only queued tasks assign")
    try:
        stored = load(row["routing"] or "{}")
        requirements = check_requirements(stored)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    needed = set()
    try:
        needed = set(load(row["required_capabilities"]) or [])
    except ValueError:
        needed = set()
    merged_caps = sorted({str(cap) for cap in
                          list(requirements.required_capabilities)
                          + [str(cap) for cap in needed]})
    requirements = requirements.model_copy(
        update={"required_capabilities": merged_caps})
    decision = _decision_for(task_id, requirements,
                             body.policy or {},
                             only_node=body.node_id)
    if decision.selected_node_id is None:
        raise HTTPException(
            status_code=422,
            detail="; ".join(
                reason for entry in decision.rejected
                for reason in entry.reasons) or "no eligible node")
    stamped = decision.model_dump(mode="json")
    stamped["epoch"] = current_epoch()
    with connection() as db:
        changed = db.execute(
            "UPDATE tasks SET assigned_node_id=?, routing_decision=? "
            "WHERE id=? AND status='queued'",
            (decision.selected_node_id,
             dump(stamped), task_id)).rowcount
    if not changed:
        raise HTTPException(status_code=409,
                            detail="Task changed state; refusing")
    logger.info("task_assigned task_id=%s node_id=%s", task_id,
                decision.selected_node_id)
    emit_event("task.assigned", f"Task {task_id} assigned to "
               f"{decision.selected_node_id}",
               task_id=str(task_id),
               node_id=decision.selected_node_id or "")
    return {"id": task_id, "assigned_node_id":
            decision.selected_node_id,
            "routing": stamped}


@app.post("/api/v1/tasks/claim/{node_id}", response_model=ClaimedTask | None)
def claim_task(node_id: str, node_token: str | None = None) -> ClaimedTask | None:
    return _claim_task(node_id, now(), node_token=node_token)


def _claim_task(node_id: str, now_str: str,
                node_token: str | None = None) -> ClaimedTask | None:
    """Claim one queued task for a live node. Fail-closed on every doubt.

    On success the transition queued -> assigned is atomic and carries an
    assignment timestamp, a lease deadline and an incremented attempt count.
    Pre-assigned tasks only go to their assignee; routing requirements
    (model types, executor) revalidate against live advertisements;
    token-bound nodes must present their credential.
    Stale leases expire first (same rules as expire_leases, same
    desktop-claim precedent): a crashed worker never pins a task,
    and no scheduler, daemon or background thread is involved.
    """
    with connection() as db:
        node = db.execute(
            "SELECT tier, capabilities, status, last_seen, models, "
            "executors, auth_token_hash FROM nodes WHERE node_id=?",
            (node_id,)).fetchone()
        if node is None:
            raise HTTPException(404, "Node is not registered")
        try:
            authenticate(node_id, node["auth_token_hash"], node_token)
        except NodeAuthError:
            raise HTTPException(status_code=403,
                                detail="node credential rejected")
        if node["status"] != "online" or node_is_stale(node["last_seen"], now_str):
            return None
        # Piggyback lease recovery on the authenticated claim path
        # (mirrors desktop_claim_next): crashed workers never pin
        # tasks, without any scheduler, daemon or background thread.
        expire_leases(now_str)
        try:
            node_models = load(node["models"] or "[]")
        except ValueError:
            node_models = []
        try:
            node_executors = load(node["executors"] or "[]")
        except ValueError:
            node_executors = []
        capabilities = set(load(node["capabilities"]))
        # Bounded hot path: the 500 most urgent queued tasks.
        # EXPLAIN QUERY PLAN uses idx_tasks_status.
        candidates = db.execute("SELECT * FROM tasks WHERE status='queued' ORDER BY priority DESC, id ASC LIMIT 500").fetchall()
        for task in candidates:
            if task["assigned_node_id"] not in (None, node_id):
                continue
            try:
                assigned = load(task["routing_decision"] or "{}")
                if not isinstance(assigned, dict):
                    assigned = {}
                require_epoch(assigned.get("epoch", 0), now_str)
            except (ValueError, FencingError):
                logger.info(
                    "task_claim_fenced task_id=%s node_id=%s",
                    task["id"], node_id)
                continue
            needed = set(load(task["required_capabilities"]))
            tier_ok = task["preferred_tier"] is None or task["preferred_tier"] == node["tier"]
            attempts = task["attempt_count"] if "attempt_count" in task.keys() else 0
            if attempts is None:
                attempts = 0
            if not (tier_ok and needed.issubset(capabilities) and attempts < MAX_ATTEMPTS):
                continue
            try:
                stored = load(task["routing"] or "{}")
                requirements = check_requirements(stored)
            except ValueError:
                continue
            node_types = {str(entry.get("model_type", ""))
                          for entry in node_models
                          if isinstance(entry, dict)}
            if any(kind not in node_types
                   for kind in requirements.required_model_types):
                continue
            if requirements.required_executor and \
                    requirements.required_executor not in {
                        str(item).strip().lower()
                        for item in node_executors}:
                continue
            changed = db.execute("UPDATE tasks SET status='assigned', assigned_node_id=?, assigned_at=?, lease_until=?, attempt_count=? WHERE id=? AND status='queued'",
                                  (node_id, now_str, _lease_until(now_str), attempts + 1, task["id"])).rowcount
            if changed:
                logger.info("task_claimed task_id=%s node_id=%s attempt=%s", task["id"], node_id, attempts + 1)
                return ClaimedTask(id=task["id"], kind=task["kind"], payload=load(task["payload"]),
                                   required_capabilities=list(needed),
                                   mission_id=task["mission_id"] if "mission_id" in task.keys() else None)
    return None


@app.post("/api/v1/tasks/{task_id}/complete", status_code=204)
async def complete_task(task_id: int, request: Request, node_id: str | None = None) -> Response:
    """Close an assigned task. The completing node identifies itself
    via query (?node_id=) or body (node_id), matching how existing
    workers already send it; anonymous or foreign completions are
    refused exactly like unknown tasks (no identity oracle)."""
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="invalid JSON body")
    claimed = node_id or body.get("node_id")
    try:
        result = TaskResult.model_validate(body)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=str(error))
    _complete_task(task_id, result, completing_node_id=claimed, now_str=now())
    return Response(status_code=204)


def _complete_task(task_id: int, result: TaskResult, completing_node_id: str | None = None, now_str: str | None = None) -> None:
    """Complete an assigned task within its lease. Fail-closed otherwise.

    The completing node must identify itself and match the assignment:
    anonymous or foreign completions are refused exactly like
    unknown tasks (no identity oracle). Expired assignments can
    never complete.
    """
    current = now_str or now()
    with connection() as db:
        row = db.execute("SELECT status, assigned_node_id, lease_until, routing_decision FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None or row["status"] != "assigned":
            raise HTTPException(404, "Assigned task not found")
        if not completing_node_id or row["assigned_node_id"] != completing_node_id:
            raise HTTPException(404, "Assigned task not found")
        try:
            stamped = load(row["routing_decision"] or "{}")
            assigned_epoch = stamped.get("epoch", 0) if isinstance(stamped, dict) else 0
        except ValueError:
            assigned_epoch = 0
        try:
            require_writer_epoch(assigned_epoch, current)
        except FencingError as error:
            raise HTTPException(status_code=409, detail=str(error))
        try:
            lease_valid = row["lease_until"] is not None and _parse_time(row["lease_until"]) > _parse_time(current)
        except (ValueError, TypeError):
            lease_valid = False
        if not lease_valid:
            raise HTTPException(404, "Assigned task not found")
        status = "completed" if result.success else "failed"
        changed = db.execute("UPDATE tasks SET status=?, result=?, completed_at=? WHERE id=? AND status='assigned'",
                              (status, dump(result.model_dump()), current, task_id)).rowcount
    if not changed:
        raise HTTPException(404, "Assigned task not found")
    logger.info("task_finished task_id=%s status=%s", task_id, status)
    emit_event(f"task.{status}", f"Task {task_id} {status}",
               task_id=str(task_id),
               node_id=completing_node_id or "")
    if status == "completed":
        try:
            _ingest_research_fetch(task_id, result,
                                   completing_node_id or "")
        except Exception as error:
            logger.warning("research_fetch_ingest_skipped task_id=%s "
                           "cause=%s", task_id, error)
        try:
            _closeout_dispatched_step(task_id)
        except Exception as error:
            logger.warning("mission_closeout_skipped task_id=%s "
                           "cause=%s", task_id, error)


def _ingest_research_fetch(task_id: int, result: TaskResult,
                           node_id: str) -> None:
    """Completion hook: a finished research.fetch_url task becomes
    a real SourceRecord on its run. Validates everything again —
    node output is data, never trusted. Never breaks completion
    (callers swallow all errors)."""
    from .research import (content_hash_for, extract_source,
                           get_source_by_hash, new_source,
                           save_source)
    from .research_engine import load_run, save_run
    with connection() as db:
        row = db.execute(
            "SELECT kind, payload FROM tasks WHERE id=?",
            (task_id,)).fetchone()
    if row is None or row["kind"] != "research.fetch_url":
        return
    try:
        payload = load(row["payload"] or "{}")
    except ValueError:
        return
    run_id = str((payload or {}).get("run_id", ""))
    if not run_id:
        return
    data = result.result if isinstance(result.result, dict) else {}
    url = str(data.get("url", ""))[:500]
    text = str(data.get("text", ""))[:20000]
    if not url or not text.strip():
        return
    from .research_transport import (TransportRefusedError,
                                     validate_url)
    try:
        canonical = validate_url(url)
    except TransportRefusedError:
        return
    if get_source_by_hash(content_hash_for(text.strip())) \
            is not None:
        return
    entry = new_source(
        "web", title=f"Node fetch: {canonical[:200]}",
        content=text.strip(), reference=canonical,
        topics=["node-fetched"],
        provenance=None)
    entry = entry.model_copy(update={
        "provenance": entry.provenance.model_copy(update={
            "creator_id": f"node:{node_id or 'unknown'}",
            "notes": ((entry.provenance.notes or "") +
                      " | fetched by a Linux node task; "
                      "coordinator-validated URL").strip(" |")})})
    try:
        entry = extract_source(entry)
    except ValueError:
        pass
    try:
        save_source(entry)
    except ValueError:
        return
    run = load_run(run_id)
    if run is None:
        return
    if entry.source_id not in (run.source_ids or []):
        updated = run.model_copy(update={
            "source_ids": [*list(run.source_ids or []),
                           entry.source_id],
            "sources_meta": [*list(run.sources_meta or []), {
                "source_id": entry.source_id,
                "title": entry.title, "url": canonical,
                "provider": f"node:{node_id or 'unknown'}",
                "retrieved_at": entry.captured_at}],
            "metadata": {**(run.metadata or {}),
                         "node_fetched": int(
                             (run.metadata or {}).get(
                                 "node_fetched", 0)) + 1}})
        save_run(updated)
    emit_event("research.fetched",
               f"Node {node_id or '?'} fetched {canonical[:120]} "
               f"for run {run_id}",
               task_id=str(task_id), node_id=node_id or "")


def _closeout_dispatched_step(task_id: int) -> None:
    """H3 close-out: a successfully completed H1-dispatched task may
    close its mission step. Only tasks carrying
    payload["mission_step_id"] plus a valid task.mission_id qualify;
    everything else keeps exact current behavior (return silently).
    The mission is reloaded before any change; only a step still in
    status "dispatched" may move to "completed", via the existing
    conditional save_mission(expected=...) so concurrent completions
    never silently overwrite each other (MissionConflictError is
    caught and logged, never raised). The existing "step_completed"
    mission event is written exactly once. When several tasks link
    to one step, the step closes only after every linked task reads
    "completed"; a single failed sibling keeps the step dispatched.
    Never advances the mission, never approves, never executes —
    the executor/tick stays responsible for further progress. Never
    breaks task completion (all unexpected paths log and return)."""
    with connection() as db:
        row = db.execute(
            "SELECT mission_id, payload, status FROM tasks WHERE id=?",
            (task_id,)).fetchone()
    if row is None:
        return
    if row["status"] != "completed":
        return
    mission_id = str(row["mission_id"] or "").strip()
    if not mission_id:
        return
    try:
        payload = load(row["payload"] or "{}")
    except ValueError:
        logger.warning("mission_closeout_skipped task_id=%s "
                       "cause=unreadable payload", task_id)
        return
    if not isinstance(payload, dict):
        return
    step_id = str(payload.get("mission_step_id", "") or "").strip()
    if not step_id:
        return
    mission = load_mission(mission_id)
    if mission is None:
        logger.warning("mission_closeout_skipped task_id=%s "
                       "cause=unknown mission '%s'", task_id, mission_id)
        return
    step = next((entry for entry in mission.steps
                 if entry.step_id == step_id), None)
    if step is None:
        logger.warning("mission_closeout_skipped task_id=%s "
                       "cause=unknown step '%s' for mission '%s'",
                       task_id, step_id, mission_id)
        return
    if step.status != "dispatched":
        return
    with connection() as db:
        siblings = db.execute(
            "SELECT id, payload, status FROM tasks WHERE mission_id=?",
            (mission.mission_id,)).fetchall()
    linked: list = []
    for sibling in siblings:
        try:
            sibling_payload = load(sibling["payload"] or "{}")
        except ValueError:
            continue
        if (isinstance(sibling_payload, dict)
                and str(sibling_payload.get("mission_step_id", "")
                        or "").strip() == step_id):
            linked.append(sibling)
    if not linked:
        return
    if any(str(entry["status"]) != "completed" for entry in linked):
        return
    old_status, old_step = mission.status, mission.current_step
    result_text = (step.result_text
                   or f"Dispatched task {task_id} completed "
                   "(research.fetch_url).")[:4000]
    updated = set_step(mission, step_id, status="completed",
                       result_text=result_text,
                       completed_at=now())
    try:
        save_mission(updated, expected=(old_status, old_step))
    except MissionConflictError as error:
        logger.warning("mission_closeout_conflict task_id=%s "
                       "mission_id=%s step_id=%s cause=%s",
                       task_id, mission_id, step_id, error)
        return
    save_event(new_event(
        mission.conversation_id, "step_completed",
        f"Stap {step.sequence + 1} voltooid via queue-task "
        f"{task_id}: {step.description}",
        mission_id=mission.mission_id, step_id=step_id,
        metadata={"task_id": task_id}))
    logger.info("mission_step_closed task_id=%s mission_id=%s "
                "step_id=%s", task_id, mission_id, step_id)


def expire_leases(now_str: str | None = None) -> dict[str, int]:
    """Recover assigned tasks whose lease expired. Atomic per task.

    Tasks below MAX_ATTEMPTS return to 'queued' with cleared assignment;
    tasks at the limit fail. Physical tasks with uncertain execution
    (at least one attempt ran somewhere) become 'blocked' instead of
    requeueing: a printer start, click or other physical action is
    never silently duplicated because a node disappeared.
    """
    current = now_str or now()
    summary = {"requeued": 0, "failed": 0, "blocked": 0}
    with connection() as db:
        rows = db.execute("SELECT id, lease_until, attempt_count, routing FROM tasks WHERE status='assigned'").fetchall()
        for task in rows:
            try:
                expired = task["lease_until"] is None or _parse_time(task["lease_until"]) <= _parse_time(current)
            except (ValueError, TypeError):
                expired = True
            if not expired:
                continue
            attempts = task["attempt_count"] if task["attempt_count"] is not None else 0
            physical = False
            try:
                stored = load(task["routing"] or "{}")
                physical = bool(check_requirements(stored).physical_action)
            except ValueError:
                physical = False
            if physical and attempts > 0:
                changed = db.execute("UPDATE tasks SET status='blocked', assigned_node_id=NULL, assigned_at=NULL, lease_until=NULL WHERE id=? AND status='assigned' AND (lease_until=? OR (lease_until IS NULL AND ? IS NULL))",
                                      (task["id"], task["lease_until"], task["lease_until"])).rowcount
                if changed:
                    summary["blocked"] += 1
                    logger.info("task_lease_expired task_id=%s blocked physical-uncertain", task["id"])
            elif attempts < MAX_ATTEMPTS:
                changed = db.execute("UPDATE tasks SET status='queued', assigned_node_id=NULL, assigned_at=NULL, lease_until=NULL WHERE id=? AND status='assigned' AND (lease_until=? OR (lease_until IS NULL AND ? IS NULL))",
                                      (task["id"], task["lease_until"], task["lease_until"])).rowcount
                if changed:
                    summary["requeued"] += 1
                    logger.info("task_lease_expired task_id=%s requeued", task["id"])
            else:
                changed = db.execute("UPDATE tasks SET status='failed', assigned_node_id=NULL, assigned_at=NULL, lease_until=NULL WHERE id=? AND status='assigned' AND (lease_until=? OR (lease_until IS NULL AND ? IS NULL))",
                                      (task["id"], task["lease_until"], task["lease_until"])).rowcount
                if changed:
                    summary["failed"] += 1
                    logger.info("task_lease_expired task_id=%s failed attempts=%s", task["id"], attempts)
    return summary


def expire_desktop_leases(now_str: str | None = None) -> dict[str, int]:
    """Recover dispatched desktop actions whose lease expired.

    A dead agent must never pin an action forever: expired
    leases return to approved while attempts remain (another
    claim may pick the action up), and block when attempts
    are exhausted. Each transition is conditional, so a
    late agent report still wins its own race instead of
    being silently overwritten. Runs lazily on every
    desktop claim.
    """
    from .agent_loop import DESKTOP_MAX_ATTEMPTS
    current = now_str or now()
    summary = {"recovered": 0, "blocked": 0}
    for row in _desktop_list(limit=100, status="dispatched"):
        try:
            record = DesktopActionRecord.model_validate(
                load(row["record"]))
        except ValueError:
            continue
        try:
            expired = not record.lease_until or _parse_time(
                record.lease_until) <= _parse_time(current)
        except (ValueError, TypeError):
            expired = True
        if not expired:
            continue
        if record.attempt_count >= DESKTOP_MAX_ATTEMPTS:
            updated = record.model_copy(update={
                "status": "blocked",
                "note": "dispatch lease expired with no "
                        "attempts left; operator reviews"})
            key = "blocked"
        else:
            updated = record.model_copy(update={
                "status": "approved", "dispatched_by": "",
                "dispatched_at": "", "lease_until": "",
                "note": "dispatch lease expired; released "
                        "for re-claim"})
            key = "recovered"
        try:
            _desktop_save(updated, current,
                          expected_from=("dispatched",))
        except (DesktopConflictError, ValueError):
            continue
        summary[key] += 1
        logger.info("desktop_lease_expired action_id=%s %s",
                    record.action.action_id, key)
    return summary


@app.get("/api/v1/tasks/by-id/{task_id}")
def get_task(task_id: int) -> dict:
    """One task with requirements, assignment and routing
    explanation. Read-only; chat and missions use this to
    describe where work goes and why — never to bypass
    routing (assignment stays on the explicit endpoint).
    The by-id prefix avoids shadowing literal task paths."""
    with connection() as db:
        row = db.execute("SELECT * FROM tasks WHERE id=?",
                         (task_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Task not found")
    record = dict(row)
    record["payload"] = load(row["payload"])
    record["required_capabilities"] = load(
        row["required_capabilities"])
    record["result"] = load(row["result"]) if row["result"] else None
    try:
        record["routing"] = load(row["routing"] or "{}")
    except ValueError:
        record["routing"] = {}
    try:
        record["routing_decision"] = load(
            row["routing_decision"] or "{}") or None
    except ValueError:
        record["routing_decision"] = None
    return record


@app.get("/api/v1/tasks")
def list_tasks() -> list[dict]:
    with connection() as db:
        rows = db.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 100").fetchall()
    items = []
    for row in rows:
        record = dict(row)
        record["payload"] = load(row["payload"])
        record["required_capabilities"] = load(row["required_capabilities"])
        record["result"] = load(row["result"]) if row["result"] else None
        try:
            record["routing"] = load(row["routing"] or "{}")
        except ValueError:
            record["routing"] = {}
        try:
            record["routing_decision"] = load(row["routing_decision"] or "{}") or None
        except ValueError:
            record["routing_decision"] = None
        items.append(record)
    return items


# =============================================================================
# INTEGRATION PASS — smallest UI connections over existing backend truth.
# Every route below is a read-only view (or a thin web-form bridge onto an
# existing POST API) over stores/APIs that already exist: tasks queue,
# nodes, missions, desktop approvals, write proposals, voice approvals,
# model_router (pure), interface events, jobs. No new queue, no new bus,
# no new registry, no new auth, no new scheduler — only visibility.
# =============================================================================


@app.get("/api/v1/models/routes")
def model_routes() -> dict:
    """Read-only model-router status: one resolution per task class.

    Pure decision layer (model_router.resolve_model): no I/O, no
    execution, no downloads. tool_execution has no automatic route
    by design and reports its refusal openly."""
    from .model_router import (
        PROVEN_LOCAL_TOOL_MODELS,
        TASK_CLASSES,
        ModelRefusedError,
        code_model_pin,
        resolve_model,
    )
    routes: dict[str, dict] = {}
    for task_class in sorted(TASK_CLASSES):
        try:
            resolved = resolve_model(task_class)
        except ModelRefusedError as error:
            routes[task_class] = {"routed": False,
                                  "reason": str(error)[:300]}
            continue
        routes[task_class] = {"routed": True,
                              "provider": resolved.provider,
                              "model": resolved.model,
                              "local": resolved.local,
                              "operator_override": resolved.operator_override,
                              "reason": resolved.reason}
    return {"routes": routes,
            "code_pin": code_model_pin(),
            "proven_local_tool_models": sorted(PROVEN_LOCAL_TOOL_MODELS)}


@app.get("/api/v1/events/stream")
async def events_stream(after: str = "", type: str = "",
                        limit: int = 50, once: bool = False) -> StreamingResponse:
    """Minimal read-only SSE tail over the existing interface event bus.

    Same store and validation as GET /api/v1/events (poll remains the
    fallback): `after` is an event_id cursor, `type` filters one event
    type, `limit` bounds the initial replay. Emits `data:` JSON lines
    for backlog + new rows, `: ping` keep-alives every 2s when quiet.
    `once=true` sends the backlog plus the hello comment and closes
    (snapshot for tests/curl); default keeps the tail open.
    Events inform; they never authorize."""
    from .events import EventRefusedError, POLL_LIMIT
    try:
        count = max(1, min(int(limit or 50), POLL_LIMIT))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422,
                            detail="limit must be an integer")
    try:
        backlog = bus_events(limit=count, after=after,
                             event_type=type)
    except EventRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))

    async def _generate():
        import asyncio as _asyncio
        cursor = after
        for event in backlog:
            yield f"data: {json.dumps(event.model_dump(mode='json'))}\n\n"
            cursor = event.event_id
        yield ": connected — poll fallback: GET /api/v1/events\n\n"
        if once:
            return
        while True:
            await _asyncio.sleep(2.0)
            try:
                fresh = bus_events(limit=count, after=cursor,
                                   event_type=type)
            except (EventRefusedError, ValueError):
                yield ": refusing — filter rejected, stream closing\n\n"
                return
            except Exception:
                yield ": ping\n\n"
                continue
            if not fresh:
                yield ": ping\n\n"
                continue
            for event in fresh:
                yield (f"data: "
                       f"{json.dumps(event.model_dump(mode='json'))}\n\n")
                cursor = event.event_id

    return StreamingResponse(_generate(),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})


def _task_status_counts(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("status", "unknown"))
        counts[key] = counts.get(key, 0) + 1
    return counts


@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(status: str = "") -> str:
    """Task dashboard over the existing queue: every row links to its
    mission, node, context and events. No gate bypass: assignment,
    claim and completion stay on the existing POST APIs."""
    from . import ui as _ui
    try:
        rows = list_tasks()
    except Exception:
        rows = []
    wanted = (status or "").strip().lower()
    if wanted:
        rows = [row for row in rows
                if str(row.get("status", "")).lower() == wanted]
    counts = _task_status_counts(list_tasks() if wanted else rows)
    chips = " ".join(
        f"<a class=\"chip\" href=\"/tasks\">{'all'}</a>",
        ) + "".join(
        f" <a class=\"chip\" href=\"/tasks?status={_ui.esc(key)}\">"
        f"{_ui.esc(key)} {value}</a>"
        for key, value in sorted(counts.items()))
    cards = "".join(
        f"<div class=\"sprout\">"
        f"<b>#{row.get('id')} {_ui.esc(str(row.get('kind', '')))}</b><br>"
        f"{_ui.status_dot(str(row.get('status', '')))}"
        f"{_ui.chip(str(row.get('status', '')))}"
        + (f" <span class=\"muted\">mission "
           f"<a href=\"/missions/{_ui.esc(str(row.get('mission_id') or ''))}\">"
           f"{_ui.esc(str(row.get('mission_id') or '')[:24])}</a></span>"
           if row.get("mission_id") else "")
        + (f" <span class=\"muted\">→ "
           f"{_ui.esc(str(row.get('assigned_node_id') or ''))}</span>"
           if row.get("assigned_node_id") else "")
        + (f" <span class=\"muted\">attempt "
           f"{_ui.esc(str(row.get('attempt_count', 0)))}/3</span>")
        + f"<br><a href=\"/tasks/{row.get('id')}\">Open task</a></div>"
        for row in rows[:100]) or _ui.empty(
            "No tasks yet — queue one below or via POST /api/v1/tasks.")
    main = f"""<h1>Tasks — delegation units</h1>
    <p class="muted">TASK = one delegatable unit. Queued → assigned (lease 300s, max 3 attempts) → completed/failed. MISSION = the plan it belongs to. Nodes pull; the coordinator never pushes.</p>
    <div class="panel"><p>{chips}</p>
    <form method="post" action="/web/tasks">
    <input type="text" name="kind" placeholder="kind, e.g. system_inventory" style="width:26%" aria-label="Task kind">
    <input type="text" name="capabilities" placeholder="capabilities, comma separated" style="width:26%" aria-label="Required capabilities">
    <input type="text" name="mission_id" placeholder="mission_id (optional)" style="width:22%" aria-label="Mission id">
    <button type="submit">Queue task</button></form>
    <form method="post" action="/web/maintenance/sweep" style="display:inline">
    <button type="submit">Sweep expired leases</button></form>
    <p class="muted">mission_id is traceability only and must reference a real mission; the task never executes on creation.</p></div>
    <div class="grove">{cards}</div>"""
    return _ui.shell("Tasks", "/tasks", main, _ui.command_bar())


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_page(task_id: int):
    """One task: goal, mission, node, capability, status, attempts,
    lease, result, provenance-relevant links. Read-only."""
    from . import ui as _ui
    try:
        record = get_task(task_id)
    except HTTPException as error:
        return HTMLResponse(f"Task not found ({error.status_code})",
                            status_code=error.status_code)
    payload = record.get("payload") or {}
    goal = ""
    if isinstance(payload, dict):
        for key in ("goal", "question", "url", "summary", "text"):
            if payload.get(key):
                goal = str(payload[key])[:300]
                break
    result = record.get("result") or {}
    routing = record.get("routing") or {}
    decision = record.get("routing_decision") or {}
    events = ""
    try:
        matches = [event for event in bus_events(limit=200)
                   if str(event.task_id) == str(task_id)][-15:]
        events = "".join(
            f"<li><small>{_ui.esc(event.created_at)}</small> "
            f"<b>{_ui.esc(event.event_type)}</b> "
            f"{_ui.esc(event.summary[:200])}</li>"
            for event in matches) or "<li>No events yet.</li>"
    except Exception:
        events = "<li>Events unavailable.</li>"
    mission = record.get("mission_id") or ""
    node = record.get("assigned_node_id") or ""
    main = f"""<h1>Task #{_ui.esc(str(record.get('id')))}</h1>
    <div class="panel">
    <p><b>{_ui.esc(str(record.get('kind', '')))}</b> {_ui.status_dot(str(record.get('status', '')))}{_ui.chip(str(record.get('status', '')))}</p>
    {f"<p>{_ui.esc(goal)}</p>" if goal else ""}
    <p class="muted">mission: {(f"<a href='/missions/{_ui.esc(str(mission))}'>{_ui.esc(str(mission)[:40])}</a>" if mission else "— (general/system task)")}</p>
    <p class="muted">claimed by: {(f"<a href='/nodes'>{_ui.esc(str(node))}</a>" if node else "— (queued, unclaimed)")}</p>
    <p class="muted">capabilities: {_ui.esc(', '.join(record.get('required_capabilities') or []) or 'none')} · tier: {_ui.esc(str(record.get('preferred_tier') or 'any'))} · priority: {_ui.esc(str(record.get('priority', 0)))}</p>
    <p class="muted">attempts: {_ui.esc(str(record.get('attempt_count', 0)))}/3 · lease until: {_ui.esc(str(record.get('lease_until') or '—'))} · created: {_ui.esc(str(record.get('created_at', ''))[:16])}</p>
    <p class="muted">routing: {_ui.esc(str((routing or {}).get('required_executor', '') or (decision or {}).get('selected_node_id', '') or 'auto'))} · <a href="/api/v1/tasks/by-id/{_ui.esc(str(record.get('id')))}">raw JSON</a></p>
    <p class="muted">context: <a href="/api/v1/context/packet?goal={_ui.esc(str(record.get('kind', ''))[:80])}">context packet for this kind</a> (bounded; same packet the code worker fetches) · world: <a href="/world">INVENTory</a></p>
    </div>
    <h2>Result</h2><div class="panel"><p>{_ui.esc(str((result or {}).get('error', '') or (result or {}).get('result', '') or '— no result yet —')[:1000])}</p></div>
    <h2>Assign</h2><div class="panel">
    <form method="post" action="/web/tasks/{_ui.esc(str(record.get('id')))}/assign">
    <input type="text" name="node_id" placeholder="node_id (empty = auto-route)" style="width:40%" aria-label="Node id">
    <button type="submit">Assign</button></form>
    <p class="muted">Explicit assignment constrains the next claim; the node still pulls the task. Empty node_id auto-routes via the existing routing decision.</p></div>
    <h2>Events</h2><ul>{events}</ul>
    <p class="muted">Stuck or expired? <code>POST /api/v1/maintenance/sweep-leases</code> requeues expired leases (physical-uncertain tasks block instead of duplicating). Retry happens by re-queueing, never by forcing.</p>"""
    return _ui.shell(f"Task #{task_id}", "/tasks", main,
                     _ui.command_bar())


@app.post("/web/tasks/{task_id}/assign")
async def web_task_assign(task_id: int, request: Request) -> RedirectResponse:
    """Smallest UI bridge onto POST /api/v1/tasks/{id}/assign: same
    eligibility proof, same routing decision. Assignment constrains,
    never pushes executable work."""
    from fastapi import HTTPException as _HTTPException
    fields = await _form_fields(request)
    node_id = fields.get("node_id", "").strip() or None
    try:
        assign_task(task_id, TaskAssignBody(node_id=node_id, policy={}))
    except (_HTTPException, ValueError):
        pass
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@app.post("/web/maintenance/sweep")
async def web_maintenance_sweep() -> RedirectResponse:
    """Smallest UI bridge onto POST /api/v1/maintenance/sweep-leases:
    existing expiry rules only (requeue/fail/block), creates nothing,
    executes nothing. Repeated sweeps are safe by conditional update."""
    maintenance_sweep_leases()
    return RedirectResponse("/tasks", status_code=303)


@app.post("/web/tasks")
async def web_task_create(request: Request) -> RedirectResponse:
    """Smallest UI bridge onto POST /api/v1/tasks: same validation,
    same traceability rule, no execution."""
    from fastapi import HTTPException as _HTTPException
    fields = await _form_fields(request)
    kind = fields.get("kind", "").strip()
    if not kind:
        return RedirectResponse("/tasks", status_code=303)
    capabilities = [part.strip() for part in
                    fields.get("capabilities", "").replace(";", ",").split(",")
                    if part.strip()][:20]
    mission_id = fields.get("mission_id", "").strip() or None
    try:
        created = create_task(TaskCreate(kind=kind,
                                         required_capabilities=capabilities,
                                         mission_id=mission_id))
    except (_HTTPException, ValueError):
        return RedirectResponse("/tasks", status_code=303)
    return RedirectResponse(f"/tasks/{created.get('id', '')}",
                            status_code=303)


def _mission_tasks_html(mission_id: str) -> str:
    """Tasks bound to one mission via task.mission_id (traceability
    link, read-only)."""
    from . import ui as _ui
    try:
        linked = [row for row in list_tasks()
                  if str(row.get("mission_id") or "") == str(mission_id)]
    except Exception:
        linked = []
    rows = "".join(
        f"<li>{_ui.status_dot(str(row.get('status', '')))}"
        f"<a href=\"/tasks/{row.get('id')}\">#{row.get('id')} "
        f"{_ui.esc(str(row.get('kind', '')))}</a> — "
        f"{_ui.esc(str(row.get('status', '')))}"
        + (f" → {_ui.esc(str(row.get('assigned_node_id') or ''))}"
           if row.get("assigned_node_id") else "")
        + "</li>"
        for row in linked)
    return rows or ("<li>No tasks bound — queue one from "
                    "<a href=\"/tasks\">Tasks</a> with this mission_id.</li>")


@app.get("/approvals", response_class=HTMLResponse)
def approvals_page() -> str:
    """One human gate: desktop actions + write proposals + voice
    requests + missions waiting. Read-only aggregation; every decide
    control lives on its existing route. Nothing auto-approves."""
    from . import ui as _ui
    try:
        desktop = [row for row in agent_status().get("waiting", [])
                   if row.get("status") == "pending_approval"]
    except Exception:
        desktop = []
    try:
        writes = [item for item in _write_list(limit=100)
                  if str(item.get("status", "")).lower() in
                  ("proposed", "pending", "pending_approval")]
    except Exception:
        writes = []
    try:
        voice = pending_voice_requests()
    except Exception:
        voice = []
    try:
        missions_waiting = [m for m in
                            (_mission_to_json(mission)
                             for mission in list_missions())
                            if m.get("status") == "pending_approval"]
    except Exception:
        missions_waiting = []
    desktop_html = "".join(
        f"<li>{_ui.status_dot(entry.get('status', ''))}"
        f"<code>{_ui.esc(entry.get('action_type', ''))}</code> "
        f"{_ui.esc(entry.get('action_id', ''))} "
        f"<a href=\"/agents\">decide in Agents</a></li>"
        for entry in desktop[:20]) or "<li>None.</li>"
    writes_html = "".join(
        f"<li><code>{_ui.esc(item.get('proposal_id', ''))}</code> "
        f"{_ui.esc(item.get('summary', ''))} "
        f"<a href=\"/writes\">decide in Writes (exact YES)</a></li>"
        for item in writes[:20]) or "<li>None.</li>"
    voice_html = "".join(
        f"<li><code>{_ui.esc(item.approval_id)}</code> "
        f"{_ui.esc(item.kind)} → {_ui.esc(item.target_id)} "
        f"<span class=\"muted\">{_ui.esc(item.summary[:120])}</span></li>"
        for item in voice[:20]) or "<li>None.</li>"
    missions_html = "".join(
        f"<li><a href=\"/missions/{_ui.esc(m.get('mission_id', ''))}\">"
        f"{_ui.esc(m.get('goal', '')[:100])}</a></li>"
        for m in missions_waiting[:20]) or "<li>None.</li>"
    total = len(desktop) + len(writes) + len(voice) + len(missions_waiting)
    main = f"""<h1>Approvals — the human gate</h1>
    <p class="muted"><b>{total}</b> waiting. Approval is permission, never verification, never execution. Nothing here auto-approves.</p>
    <div class="panel"><h2>Missions ({len(missions_waiting)})</h2><ul>{missions_html}</ul></div>
    <div class="panel"><h2>Desktop actions ({len(desktop)})</h2><ul>{desktop_html}</ul></div>
    <div class="panel"><h2>Write proposals ({len(writes)})</h2><ul>{writes_html}</ul></div>
    <div class="panel"><h2>Voice requests ({len(voice)})</h2><ul>{voice_html}</ul></div>"""
    return _ui.shell("Approvals", "/approvals", main,
                     _ui.command_bar())


@app.get("/system", response_class=HTMLResponse)
def system_page() -> str:
    """System truth: model routing, coordinator counts, jobs. All
    read-only; the scheduler stays on-demand (jobs run via API/n8n
    cron, never a background thread)."""
    from . import ui as _ui
    try:
        routes = model_routes()
    except Exception:
        routes = {"routes": {}, "code_pin": "?", "proven_local_tool_models": []}
    route_rows = "".join(
        f"<tr><td><code>{_ui.esc(task_class)}</code></td>"
        f"<td>{'refused' if not info.get('routed') else _ui.esc(str(info.get('provider', '')) + '/' + str(info.get('model', '')))}</td>"
        f"<td>{'yes' if info.get('local') else 'no' if info.get('routed') else '—'}</td>"
        f"<td class=\"muted\">{_ui.esc(str(info.get('reason', ''))[:140])}</td></tr>"
        for task_class, info in sorted(routes.get("routes", {}).items())
    ) or "<tr><td colspan='4'>Router unavailable.</td></tr>"
    try:
        status = coordinator_status()
    except Exception:
        status = {}
    try:
        jobs = job_list()
    except Exception:
        jobs = []
    jobs_html = "".join(
        f"<li><code>{_ui.esc(str(job.get('job_name', '')))}</code> "
        f"<span class=\"muted\">{_ui.esc(str(job.get('trigger', '')))}</span> "
        f"<form method=\"post\" action=\"/web/jobs/run\" "
        f"style=\"display:inline\">"
        f"<input type=\"hidden\" name=\"job_name\" "
        f"value=\"{_ui.esc(str(job.get('job_name', '')))}\">"
        f"<button type=\"submit\">Run</button></form></li>"
        for job in (jobs if isinstance(jobs, list) else [])[:20]
    ) or "<li>No jobs registered.</li>"
    main = f"""<h1>System — routing, counts, jobs</h1>
    <div class="panel"><h2>Model routing (existing router, read-only)</h2>
    <table><tr><th>Task class</th><th>Provider/model</th><th>Local</th><th>Why</th></tr>{route_rows}</table>
    <p class="muted">Code pin (worker safety override): <code>{_ui.esc(str(routes.get('code_pin', '')))}</code> · proven local tool models: {_ui.esc(', '.join(routes.get('proven_local_tool_models', [])) or 'none — tool execution needs an explicit operator model')}.</p>
    <p class="muted">Full JSON: <a href="/api/v1/models/routes">/api/v1/models/routes</a></p></div>
    <div class="panel"><h2>Coordinator</h2><p class="muted">{_ui.esc(str(status)[:600])}</p>
    <p class="muted">JSON: <a href="/api/v1/status">/api/v1/status</a> · live events: <a href="/api/v1/events/stream">SSE stream</a> (poll fallback: <a href="/api/v1/events">/api/v1/events</a>)</p></div>
    <div class="panel"><h2>Jobs (on-demand scheduler)</h2><ul>{jobs_html}</ul>
    <p class="muted">No background thread by design — jobs run via <code>POST /api/v1/jobs/run</code> or n8n cron. Runs: <a href="/automation">Automation</a>.</p></div>"""
    return _ui.shell("System", "/system", main, _ui.command_bar())


@app.post("/web/jobs/run")
async def web_job_run(request: Request) -> RedirectResponse:
    """Smallest UI bridge onto POST /api/v1/jobs/run: same validation,
    same idempotent run_key discipline (unique key per click, so every
    explicit click runs). No auto-run anywhere."""
    import secrets as _secrets
    import time as _time
    from fastapi import HTTPException as _HTTPException
    fields = await _form_fields(request)
    job_name = fields.get("job_name", "").strip()
    if not job_name:
        return RedirectResponse("/system", status_code=303)
    try:
        job_run(JobRunBody(
            job_name=job_name, params={},
            run_key=f"web-{int(_time.time())}-{_secrets.token_hex(2)}"))
    except (_HTTPException, ValueError):
        pass
    return RedirectResponse("/system", status_code=303)


# =============================================================================
# READ-ONLY WORLD PROXY (M5.2) — INVENTory reads through InventoryReader only.
# No database access for world data, no writes, no INVENTory imports beyond the
# local bridge module. Validation lives in InventoryReader; refused requests
# become 4xx, an unreachable INVENTory becomes 502 without internals leaking.
# =============================================================================

def _world_reader() -> InventoryReader:
    return InventoryReader()


@app.get("/api/v1/world/search", response_model=SearchResponse)
async def world_search(q: str = "", type: str | None = None) -> SearchResponse:
    try:
        return await _world_reader().search(q, type)
    except InventoryRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except InventoryUnavailable:
        raise HTTPException(status_code=502, detail="INVENTory unavailable")


@app.get("/api/v1/world/entity/{entity_type}/{entity_id}", response_model=EntityRecord)
async def world_entity(entity_type: str, entity_id: str) -> EntityRecord:
    try:
        record = await _world_reader().get(entity_type, entity_id)
    except InventoryRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except InventoryUnavailable:
        raise HTTPException(status_code=502, detail="INVENTory unavailable")
    if record is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    return record


@app.get("/api/v1/world/graph", response_model=GraphResponse)
async def world_graph(entity_id: str | None = None, depth: int = 1) -> GraphResponse:
    try:
        return await _world_reader().graph(entity_id, depth)
    except InventoryRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except InventoryUnavailable:
        raise HTTPException(status_code=502, detail="INVENTory unavailable")


# =============================================================================
# LIVE ADVICE (M8.3) — compositie-only: InventoryReader.search/browse ->
# records -> OllamaAdvisor.advise -> optioneel gevalideerd voorstel via
# extract_proposal. Zonder q kiest de route de begrensde browse-modus.
# Het voorstel is uitsluitend een verrijking voor de operator: nooit
# opgeslagen, nooit goedgekeurd, nooit gestaged, nooit verstuurd.
# Geen DB-schrijfacties, geen approvals, geen queue, geen dispatch.
# Validatie en caps leven in de hergebruikte modules; geweigerde input
# wordt 422, een onbereikbare achterkant wordt 502.
# =============================================================================

ADVISE_ADAPTER_ID = "mycelium-advise"


def _advisor() -> OllamaAdvisor:
    return OllamaAdvisor()


def _advise_request_id(body: AdviseRequest) -> str:
    """Deterministic caller-controlled ID for proposal extraction.

    Same request content always yields the same ID (no clock, no random);
    proposals are never stored, so reuse across identical requests is safe.
    """
    canonical = json.dumps({"q": body.q, "question": body.question,
                            "type": body.type},
                           sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"adv-{digest}"


def _extract_advise_proposal(advice_text: str,
                             body: AdviseRequest) -> AdapterProposal | None:
    """Best-effort proposal enrichment. Never fails the advice itself."""
    try:
        return extract_proposal(advice_text, adapter_id=ADVISE_ADAPTER_ID,
                                request_id=_advise_request_id(body))
    except Exception as error:
        logger.warning("advise_proposal_skipped q=%r cause=%s", body.q, error)
        return None


@app.post("/api/v1/advise", response_model=AdviseResponse)
async def advise(body: AdviseRequest) -> AdviseResponse:
    if body.mode not in ("lexical", "semantic", "hybrid"):
        raise HTTPException(status_code=422,
                            detail="Unknown retrieval mode")
    if body.q is None:
        try:
            found = await _world_reader().browse(body.type)
        except InventoryRefusedError as error:
            raise HTTPException(status_code=422, detail=str(error))
        except InventoryUnavailable:
            raise HTTPException(status_code=502,
                                detail="INVENTory unavailable")
        records = [
            {
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "title": item.title,
                "snippet": item.snippet,
                "provenance": item.provenance.model_dump(mode="json"),
                "match_type": "lexical",
                "score": 0.0,
                "why": "browse context without query",
            }
            for item in found.results
        ]
        retrieval_mode = "lexical"
    else:
        if not body.q.strip():
            raise HTTPException(status_code=422,
                                detail="Search query must be non-empty text")
        records, inventory_error, retrieval = await _chat_world_context(
            body.q, mode=body.mode)
        if inventory_error:
            raise HTTPException(status_code=502,
                                detail="INVENTory unavailable")
        if body.type is not None:
            from .inventory_read import LIST_TYPES
            singular = LIST_TYPES.get(body.type)
            records = [record for record in records
                       if record.get("entity_type") == singular]
        retrieval_mode = retrieval.get("mode_used", "lexical")
    try:
        answered = await _advisor().advise(body.question, records)
    except OllamaRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except OllamaUnavailable as error:
        logger.warning("ollama_unavailable q=%r records=%d cause=%s",
                       body.q, len(records), error)
        raise HTTPException(status_code=502, detail="Ollama unavailable")
    proposal = _extract_advise_proposal(answered.advice, body)
    return AdviseResponse(**answered.model_dump(), proposal=proposal,
                          retrieval_mode=retrieval_mode)


# =============================================================================
# EXPLICIT APPROVAL (M8.4) — operator decision on one full AI proposal.
# Stateless by design: M8.3 proposals are never stored, so the complete
# proposal travels with the decision and binding is verified on content
# via the existing M6.3 gate (request_approval + decide). Only an exact
# YES approves; anything else denies. The result is data only: no task,
# no staging, no queue, no dispatch, no provenance change, no DB writes.
# =============================================================================

@app.post("/api/v1/approvals", response_model=ApprovalResult)
def approve_proposal(body: DecideApprovalBody) -> ApprovalResult:
    try:
        approval_request = request_approval(body.proposal)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        result = decide_approval(approval_request, body.proposal,
                                 body.response, decided_by=body.decided_by)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    logger.info("approval_decided proposal_id=%s decision=%s by=%s",
                result.proposal_id, result.decision, result.decided_by)
    return result


# =============================================================================
# MYCELIUM CHAT (Fase A/B/C/N) — conversation + INVENTory context + provider.
# One turn: store user message -> read-only world context -> provider
# advice -> best-effort proposal enrichment -> store assistant message.
# The provider is unresolved per request (default local Ollama); when
# the model is unreachable the turn still completes honestly: the
# reply says what was found and that AI advice is unavailable, marked
# via provider_error. Advice is never fabricated.
# =============================================================================

CHAT_ADAPTER_ID = "mycelium-chat"


def _chat_request_id(conversation_id: str, message: str) -> str:
    canonical = json.dumps({"c": conversation_id, "m": message},
                           sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"chat-{digest}"


def _chat_ensure_conversation(conversation_id: str, title: str,
                              project_ref: str, created: str) -> None:
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO conversations
        (conversation_id, title, project_ref, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(conversation_id) DO NOTHING""",
                   (conversation_id, title[:120], project_ref[:200],
                    created))


def _chat_store_message(message_id: str, conversation_id: str, role: str,
                        content: str, created: str, provenance: str,
                        sources: str) -> None:
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO messages
        (message_id, conversation_id, role, content, created_at,
         provenance, sources) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                   (message_id, conversation_id, role, content, created,
                    provenance, sources))


def _chat_messages(conversation_id: str, limit: int = 100) -> list[dict]:
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute(
            """SELECT * FROM messages WHERE conversation_id=?
            ORDER BY created_at ASC LIMIT ?""",
            (conversation_id, max(1, min(limit, 100)))).fetchall()
    return [dict(row) for row in rows]


async def _chat_world_context(
        message: str, mode: str = "hybrid"
) -> tuple[list[dict], str | None, dict]:
    """Read-only INVENTory context for one chat message.

    Hybrid retrieval (lexical + semantic + relationship expansion)
    with automatic lexical fallback. Returns (records,
    inventory_error, retrieval_info). Refused queries become a caller
    error; an unreachable INVENTory yields empty context with a note.
    Enriched records carry match_type/score/why audit trails;
    provenance passes through untouched.
    """
    from .embeddings import EmbeddingUnavailable, get_embed_provider
    from .retrieval import hybrid_retrieve
    query = message.strip()[:200]
    if not query:
        try:
            found = await _world_reader().browse(None)
        except InventoryRefusedError as error:
            raise HTTPException(status_code=422, detail=str(error))
        except InventoryUnavailable:
            return [], "INVENTory unavailable", {"mode_used": "lexical"}
        records = [
            {
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "title": item.title,
                "snippet": item.snippet,
                "provenance": item.provenance.model_dump(mode="json"),
                "match_type": "lexical",
                "score": 0.0,
                "why": "browse context without query",
            }
            for item in found.results[:10]
        ]
        return records, None, {"mode_used": "lexical",
                               "semantic_available": False}
    embedder = None
    if mode in ("hybrid", "semantic"):
        try:
            embedder = get_embed_provider("ollama")
        except Exception:
            embedder = None
    try:
        result = await hybrid_retrieve(query, _world_reader(), embedder,
                                       mode=mode, depth=1, limit=15)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except EmbeddingUnavailable as error:
        if mode == "semantic":
            raise HTTPException(status_code=502,
                                detail=f"Semantic unavailable: {error}")
        result = await hybrid_retrieve(query, _world_reader(), None,
                                       mode="lexical", depth=1, limit=15)
    except InventoryRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except InventoryUnavailable:
        return [], "INVENTory unavailable", {"mode_used": "lexical"}
    return result["results"][:10], None, {
        "mode_used": result["mode_used"],
        "semantic_available": result["semantic_available"],
        "embed_model": result["embed_model"],
        "expansions": result["expansions"],
    }


def _chat_fallback_reply(records: list[dict],
                         inventory_error: str | None) -> str:
    lines = ["Mijn lokale AI-model is momenteel onbereikbaar, "
             "dus dit is geen AI-advies maar wat ik wél kan zeggen."]
    if inventory_error:
        lines.append(f"INVENTory-context: {inventory_error}.")
    elif not records:
        lines.append("INVENTory-context: geen records gevonden "
                     "voor deze vraag.")
    else:
        lines.append(f"INVENTory-context ({len(records)} records):")
        for record in records[:10]:
            lines.append(f"- [{record['entity_type']}] {record['title']} "
                         f"({record['entity_id']})")
    lines.append("Zodra het lokale model weer bereikbaar is, geef ik "
                 "advies op basis van deze context.")
    return "\n".join(lines)


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    try:
        provider = get_provider(body.provider)
    except ProviderRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    from .interface import VALID_INPUT_TYPES as _VALID_INPUT
    if body.input_type not in _VALID_INPUT:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown input type '{body.input_type}'")
    conversation_id = body.conversation_id or generate_conversation_id()
    created = now()
    user_provenance = None
    if body.input_type == "voice":
        from .inventory_read import Provenance as _Provenance
        user_provenance = _Provenance(
            source_type="user-created", creator_id="voice-interface",
            human_verified=True,
            notes="spoken turn; interpretation pending, never "
                  "authorization")
    user_message = new_message(conversation_id, "user", body.message,
                               provenance=user_provenance)
    _chat_ensure_conversation(
        conversation_id, body.message.strip()[:120],
        body.project_ref, created)
    _chat_store_message(
        user_message.message_id, conversation_id, "user",
        user_message.content, created,
        dump(user_message.provenance.model_dump(mode="json")), "[]")
    records, inventory_error, retrieval = await _chat_world_context(
        body.message, mode=body.mode)
    if body.observation_ids:
        try:
            extra = []
            for observation_id in body.observation_ids[:3]:
                observation = _observation_load(observation_id)
                if observation is None:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Observation '{observation_id}' not found")
                extra.append(observation)
            records = records + _observation_summaries(extra)
        except HTTPException:
            raise
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))
    sources = [
        {"entity_id": record["entity_id"],
         "source_type": record["provenance"].get("source_type", "unknown"),
         "human_verified": bool(record["provenance"].get(
             "human_verified", False)),
         "match_type": record.get("match_type", "lexical"),
         "score": record.get("score", 0.0)}
        for record in records
    ]
    provider_error: str | None = inventory_error
    try:
        answered = await provider.advise(body.message, records)
    except ProviderRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except ProviderUnavailable as error:
        answered = None
        provider_error = "; ".join(
            part for part in [provider_error, str(error)] if part)
    if answered is None:
        reply_text = _chat_fallback_reply(records, inventory_error)
        model_name = ""
        proposal = None
    else:
        reply_text = answered.advice
        model_name = answered.model
        try:
            proposal = extract_proposal(
                answered.advice, adapter_id=CHAT_ADAPTER_ID,
                request_id=_chat_request_id(conversation_id, body.message))
        except Exception as error:
            logger.warning("chat_proposal_skipped cause=%s", error)
            proposal = None
    assistant_message = new_message(
        conversation_id, "assistant", reply_text,
        sources=[dict(entry) for entry in sources])
    assistant_created = now()
    _chat_store_message(
        assistant_message.message_id, conversation_id, "assistant",
        assistant_message.content, assistant_created,
        dump(assistant_message.provenance.model_dump(mode="json")),
        dump(sources))
    logger.info("chat_turn conversation_id=%s records=%d model=%s",
                conversation_id, len(records), model_name or "none")
    emit_event("conversation.message",
               f"Chat turn in {conversation_id} "
               f"({body.input_type}, {len(sources)} sources)",
               conversation_id=conversation_id)
    return ChatResponse(
        conversation_id=conversation_id,
        message_id=assistant_message.message_id,
        reply=reply_text,
        model=model_name,
        records_used=len(sources),
        sources=sources,
        proposal=proposal,
        provider_error=provider_error,
        retrieval_mode=retrieval.get("mode_used", "lexical"),
    )


@app.get("/api/v1/conversations")
def list_conversations() -> list[dict]:
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute(
            """SELECT * FROM conversations ORDER BY created_at DESC
            LIMIT 50""").fetchall()
    return [dict(row) for row in rows]


@app.get("/api/v1/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> dict:
    init_chat_database()
    with chat_connection() as db:
        row = db.execute(
            "SELECT * FROM conversations WHERE conversation_id=?",
            (conversation_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Conversation not found")
    messages = _chat_messages(conversation_id)
    for message in messages:
        message["provenance"] = load(message["provenance"])
        message["sources"] = load(message["sources"])
    return {**dict(row), "messages": messages}


# =============================================================================
# PROJECT WORKSPACES (vertical slice 1) — minimal connection, no new store.
# A workspace is the existing conversations.project_ref; one workspace
# holds many conversations, missions follow their conversation, forks
# copy rows and re-links update rows. Seeds (mycelium-ai, inventory,
# forge-studio) are views over existing pages, never new entities.
# Events reuse the existing conversation_events + interface bus.
# =============================================================================

@app.get("/api/v1/workspaces")
def workspace_list() -> list[dict]:
    from .workspaces import list_workspaces as _list_workspaces
    return _list_workspaces()


@app.get("/api/v1/workspaces/{workspace_id}")
def workspace_get(workspace_id: str) -> dict:
    from .workspaces import WorkspaceRefusedError
    from .workspaces import get_workspace as _get_workspace
    try:
        return _get_workspace(workspace_id)
    except WorkspaceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/conversations/{conversation_id}/fork",
          status_code=201)
def conversation_fork(conversation_id: str,
                      body: WorkspaceForkBody | None = None) -> dict:
    from .workspaces import WorkspaceNotFoundError, WorkspaceRefusedError
    from .workspaces import fork_conversation as _fork
    try:
        record = _fork(conversation_id,
                       (body.target_workspace
                        if body is not None else ""))
    except WorkspaceNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except WorkspaceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    emit_event("conversation.message",
               f"Conversation {conversation_id} forked to "
               f"{record['conversation_id']}",
               conversation_id=record["conversation_id"])
    return record


@app.post("/api/v1/workspaces/{workspace_id}/conversations/"
          "{conversation_id}/attach")
def conversation_attach(workspace_id: str,
                        conversation_id: str) -> dict:
    from .workspaces import WorkspaceNotFoundError, WorkspaceRefusedError
    from .workspaces import attach_conversation as _attach
    try:
        record = _attach(conversation_id, workspace_id)
    except WorkspaceNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except WorkspaceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    emit_event("conversation.message",
               f"Conversation {conversation_id} linked to "
               f"workspace '{record['workspace_id']}'",
               conversation_id=conversation_id)
    return record


@app.post("/api/v1/workspaces/{workspace_id}/missions/"
          "{mission_id}/attach")
def mission_attach(workspace_id: str, mission_id: str,
                   body: WorkspaceMissionAttachBody) -> dict:
    from .workspaces import WorkspaceNotFoundError, WorkspaceRefusedError
    from .workspaces import attach_mission as _attach_mission
    from .workspaces import check_workspace_id
    try:
        check_workspace_id(workspace_id)
        record = _attach_mission(mission_id, body.conversation_id)
    except WorkspaceNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except WorkspaceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    if record["workspace_id"] != workspace_id:
        raise HTTPException(
            status_code=422,
            detail=f"Conversation {body.conversation_id} lives in "
                   f"workspace '{record['workspace_id'] or '-'}', "
                   f"not '{workspace_id}'; link it there first")
    emit_event("mission.updated",
               f"Mission {mission_id} linked to workspace "
               f"'{workspace_id}' via {body.conversation_id}",
               conversation_id=body.conversation_id,
               mission_id=mission_id)
    return record


# =============================================================================
# WORKSPACE RESEARCH (vertical slice 1) — one real end-to-end flow over
# existing pieces only: workspace conversation -> research_topic mission
# (pending_approval, human YES required) -> research run (mission_id +
# project_ref) -> node-first fetch tasks (pull-only workers) or local
# approve/tick -> dossier -> explicit report back into the conversation.
# No scheduler, no background thread, no auto-approval, no canonical
# mutation: the dossier stays UNVERIFIED external-source until a human
# acts through the existing candidate/approval/write gates.
# =============================================================================

async def _start_workspace_research(workspace_id: str, question: str,
                                    objective: str, route: str,
                                    seed_urls_raw: list,
                                    conversation_id: str,
                                    max_sources: int) -> dict:
    """Shared start logic for the API route and the web form."""
    from .mission_templates import instantiate as _instantiate
    from .research_engine import new_run as _new_run
    from .research_engine import save_run as _save_run
    from .research_transport import TransportRefusedError as _TRefused
    from .research_transport import validate_url as _validate_url
    from .workspaces import WorkspaceNotFoundError, WorkspaceRefusedError
    from .workspaces import attach_conversation as _attach
    from .workspaces import check_workspace_id as _check_ws
    from .workspaces import ensure_conversation as _ensure_conv
    try:
        wid = _check_ws(workspace_id)
    except WorkspaceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    clean_route = str(route or "node-first").strip().lower()
    if clean_route not in ("local", "node-first"):
        raise HTTPException(
            status_code=422,
            detail="route must be local or node-first")
    clean_question = str(question or "").strip()
    if not clean_question:
        raise HTTPException(status_code=422,
                            detail="question is required")
    if len(clean_question) > 500:
        raise HTTPException(status_code=422,
                            detail="question too long (max 500)")
    seed_urls: list[str] = []
    for raw in (seed_urls_raw or [])[:3]:
        try:
            seed_urls.append(_validate_url(str(raw)))
        except _TRefused as error:
            raise HTTPException(status_code=422, detail=str(error))
    if clean_route == "node-first" and not seed_urls:
        raise HTTPException(
            status_code=422,
            detail="node-first needs 1..3 seed_urls; use local "
                   "for provider-side retrieval")
    conv_id = str(conversation_id or "").strip()
    if conv_id:
        with chat_connection() as db:
            init_chat_database()
            row = db.execute(
                "SELECT project_ref FROM conversations "
                "WHERE conversation_id=?", (conv_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Conversation not found")
        ref = str(row["project_ref"] or "")
        if ref and ref != wid:
            raise HTTPException(
                status_code=422,
                detail=f"Conversation lives in workspace '{ref}', "
                       f"not '{wid}'; link it there first")
        if not ref:
            try:
                _attach(conv_id, wid)
            except (WorkspaceNotFoundError,
                    WorkspaceRefusedError) as error:
                raise HTTPException(status_code=422,
                                    detail=str(error))
    else:
        conv_id = _ensure_conv(wid, clean_question[:120])[
            "conversation_id"]
    records, _, _ = await _chat_world_context(clean_question)
    try:
        steps, template_max = _instantiate("research_topic",
                                           clean_question)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        mission = _executor().create(
            conv_id, clean_question, steps,
            max_steps=template_max, context_records=records)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except ExecutorError as error:
        raise _mission_error(error)
    try:
        run = _new_run(
            clean_question, objective=str(objective or "")[:500],
            project_ref=wid, mission_id=mission.mission_id,
            requested_by="workspace",
            metadata={"provider": "wikipedia",
                      "max_sources": max(1, min(int(max_sources or 6),
                                               6)),
                      "route": clean_route,
                      "seed_urls": seed_urls, "workspace": wid})
        _save_run(run)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    routed: dict = {"routed": False, "task_ids": []}
    if clean_route == "node-first":
        routed = _route_run_to_nodes(run)
    opener = (
        f"Research geopend: {clean_question[:200]}\n"
        f"Missie {mission.mission_id} wacht op jouw YES; "
        f"run {run.run_id} is draft. "
        + (f"{len(routed.get('task_ids', []))} fetch-taak/taakjes "
           f"staan klaar voor workers met research.fetch."
           if routed.get("routed") else
           f"Status: {routed.get('reason', 'lokaal')[:160]}"))
    try:
        opening = new_message(conv_id, "assistant", opener)
        _chat_store_message(
            opening.message_id, conv_id, "assistant",
            opening.content, now(),
            dump(opening.provenance.model_dump(mode="json")), "[]")
    except ValueError:
        pass
    emit_event("research.queued",
               f"Workspace '{wid}': {clean_question[:120]} "
               f"(run {run.run_id}, missie {mission.mission_id})",
               conversation_id=conv_id,
               mission_id=mission.mission_id)
    emit_event("mission.started",
               f"Mission {mission.mission_id}: {clean_question[:120]}",
               conversation_id=conv_id,
               mission_id=mission.mission_id)
    return {
        "workspace_id": wid,
        "conversation_id": conv_id,
        "mission_id": mission.mission_id,
        "mission_status": mission.status,
        "run_id": run.run_id,
        "run_status": run.status,
        "route": clean_route,
        "routed": bool(routed.get("routed", False)),
        "task_ids": list(routed.get("task_ids", [])),
        "status_note": str(routed.get("reason", "") or (
            "wacht op missie-YES, daarna approve/tick" if clean_route
            == "local" else ""))[:300],
    }


@app.post("/api/v1/workspaces/{workspace_id}/research",
          status_code=201)
async def workspace_research_start(
        workspace_id: str, body: WorkspaceResearchStartBody) -> dict:
    return await _start_workspace_research(
        workspace_id, body.question, body.objective, body.route,
        body.seed_urls, body.conversation_id, body.max_sources)


def _workspace_task_states(task_ids: list) -> list[dict]:
    """Bounded task status view for a research run. Read-only,
    best-effort: missing rows simply do not appear."""
    out: list[dict] = []
    try:
        with connection() as db:
            for raw in (task_ids or [])[:10]:
                try:
                    tid = int(raw)
                except (TypeError, ValueError):
                    continue
                row = db.execute(
                    "SELECT id, kind, status, assigned_node_id "
                    "FROM tasks WHERE id=?", (tid,)).fetchone()
                if row is not None:
                    out.append(dict(row))
    except Exception:
        pass
    return out


@app.post("/api/v1/workspaces/{workspace_id}/research/{run_id}/report")
def workspace_research_report(workspace_id: str, run_id: str) -> dict:
    """Report one run's dossier back into its workspace conversation.

    Explicit and idempotent (no scheduler, no background): the first
    call posts a bounded UNVERIFIED dossier message + mission/bus
    events and records reported_to on the run metadata; later calls
    report already-reported. Waiting/failed runs return status only —
    the mission is never touched here, so an outage cannot corrupt
    mission state. Never approves, never writes canonical state.
    """
    from .missions import load_mission as _load_mission
    from .missions import new_event as _new_mission_event
    from .missions import save_event as _save_mission_event
    from .research_engine import dossier_for_run as _dossier_for
    from .research_engine import load_run as _load_run
    from .research_engine import save_run as _save_run
    from .workspaces import WorkspaceRefusedError
    from .workspaces import check_workspace_id as _check_ws
    try:
        wid = _check_ws(workspace_id)
    except WorkspaceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    run = _load_run(run_id)
    if run is None:
        raise HTTPException(404, "Research run not found")
    if run.project_ref and run.project_ref != wid:
        raise HTTPException(
            status_code=422,
            detail=f"Run belongs to workspace '{run.project_ref}', "
                   f"not '{wid}'")
    mission = _load_mission(run.mission_id) if run.mission_id else None
    if mission is None:
        raise HTTPException(
            status_code=422,
            detail="Run has no known mission; refusing to report "
                   "into the void")
    conv_id = str(mission.conversation_id or "")
    with chat_connection() as db:
        init_chat_database()
        row = db.execute(
            "SELECT project_ref FROM conversations "
            "WHERE conversation_id=?", (conv_id,)).fetchone()
    if row is None or str(row["project_ref"] or "") != wid:
        raise HTTPException(
            status_code=422,
            detail="Mission conversation is not in this workspace; "
                   "link it there first")
    dossier = _dossier_for(run_id)
    task_ids = list((run.metadata or {}).get("routed_task_ids", []))
    tasks = _workspace_task_states(task_ids)
    if dossier is None:
        return {
            "reported": False, "run_id": run_id,
            "workspace_id": wid, "conversation_id": conv_id,
            "mission_id": mission.mission_id,
            "mission_status": mission.status,
            "status": run.status,
            "execution_state": run.execution_state,
            "reason": (run.error or "nog geen dossier; workers "
                       "onderweg of run nog niet uitgevoerd")[:300],
            "sources": len(run.source_ids or []),
            "tasks": tasks,
        }
    if (run.metadata or {}).get("reported_to") == conv_id:
        return {
            "reported": False, "run_id": run_id,
            "workspace_id": wid, "conversation_id": conv_id,
            "mission_id": mission.mission_id,
            "mission_status": mission.status,
            "reason": "already-reported",
            "dossier_id": dossier.dossier_id,
            "tasks": tasks,
        }
    sources = list(dossier.sources or [])[:10]
    source_lines = "\n".join(
        f"- {str(item.get('title', ''))[:100]} "
        f"({str(item.get('url', ''))[:120]} · "
        f"{str(item.get('execution_state', ''))})" for item in sources
    ) or "- (geen bronnen)"
    text = (
        f"Onderzoeksresultaat [{dossier.execution_state}]: "
        f"{run.question[:200]}\n\n"
        f"{dossier.summary[:1500]}\n\n"
        f"Bronnen ({len(dossier.sources)}):\n{source_lines}\n\n"
        f"Claims: {len(dossier.claims)}, open vragen: "
        f"{len(dossier.open_questions)}, tegenstrijdigheden: "
        f"{len(dossier.contradictions)}. Dossier "
        f"{dossier.dossier_id}."
        f"{' Research-memory ' + run.memory_id + '.' if run.memory_id else ''}\n\n"
        "UNVERIFIED — mensenreview vereist. Geen feit, geen "
        "automatische write; promotie loopt uitsluitend via de "
        "bestaande candidate/approval/write-gates.")
    try:
        message = new_message(conv_id, "assistant", text)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    _chat_store_message(
        message.message_id, conv_id, "assistant", message.content,
        now(), dump(message.provenance.model_dump(mode="json")),
        "[]")
    try:
        _save_mission_event(_new_mission_event(
            conv_id, "note",
            f"Dossier {dossier.dossier_id} gerapporteerd "
            f"({dossier.execution_state}, {len(dossier.sources)} "
            "bronnen, UNVERIFIED).",
            mission_id=mission.mission_id))
    except ValueError:
        pass
    emit_event("conversation.message",
               f"Dossier {dossier.dossier_id} voor run {run_id} "
               f"staat in {conv_id} (UNVERIFIED)",
               conversation_id=conv_id,
               mission_id=mission.mission_id)
    try:
        _save_run(run.model_copy(update={
            "metadata": {**(run.metadata or {}),
                         "reported_to": conv_id}}))
    except ValueError:
        pass
    return {
        "reported": True, "run_id": run_id,
        "workspace_id": wid, "conversation_id": conv_id,
        "mission_id": mission.mission_id,
        "mission_status": mission.status,
        "dossier_id": dossier.dossier_id,
        "execution_state": dossier.execution_state,
        "message_id": message.message_id,
        "sources": len(dossier.sources),
        "tasks": tasks,
    }


@app.get("/api/v1/workspaces/{workspace_id}/workstreams")
def workspace_workstreams(workspace_id: str) -> dict:
    """All live workstreams in one workspace, read-only.

    One workstream per mission (conversation + steps + tasks +
    research + proposals + greenlight), plus shared workers, the
    Forge registry counts and the workspace event tails. Pure
    aggregation over existing stores: no new database, queue,
    bus, scheduler or engine — independent streams stay
    independent, this only shows them side by side.
    """
    from .workspaces import WorkspaceRefusedError
    from .workspaces import workstream_overview as _overview
    try:
        return _overview(workspace_id)
    except WorkspaceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))


async def _linked_inventory_projects(workspace_id: str) -> dict:
    """Resolve demonstrably linked INVENTory projects, read-only.

    Candidate ids come from existing rows only
    (workspaces.inventory_project_refs); each resolves through
    the existing single-GET bridge with its own provenance
    intact. Unresolvable ids never appear as projects — no
    false positives, no writes, linkage labelled derived.
    """
    from .inventory_read import InventoryRefusedError
    from .inventory_read import InventoryUnavailable
    from .workspaces import inventory_project_refs
    refs = inventory_project_refs(workspace_id)
    reader = _world_reader()
    resolved: list[dict] = []
    unresolved = 0
    for ref in refs[:10]:
        try:
            record = await reader.get("project", ref["entity_id"])
        except (InventoryRefusedError, InventoryUnavailable,
                ValueError, AttributeError):
            unresolved += 1
            continue
        if record is None:
            unresolved += 1
            continue
        try:
            provenance = record.provenance.model_dump(mode="json")
        except (ValueError, AttributeError):
            provenance = {"source_type": "unknown",
                          "human_verified": False}
        resolved.append({
            "entity_id": record.entity_id,
            "title": record.title[:200],
            "status": str((record.details or {}).get(
                "status", ""))[:40],
            "via": ref["via"],
            "link": "derived: workspace row references this id; "
                    "INVENTory stays source of truth",
            "provenance": {
                "source_type": str(provenance.get(
                    "source_type", "unknown")),
                "human_verified": bool(provenance.get(
                    "human_verified", False)),
                "creator_id": str(provenance.get(
                    "creator_id", "unknown"))[:80],
            },
            "href": f"/world?entity_id={record.entity_id}",
        })
    return {"workspace_id": workspace_id,
            "candidate_refs": len(refs),
            "projects": resolved,
            "unresolved": unresolved,
            "reader": "inventory_read.get(project) single-GET"}


@app.get("/api/v1/workspaces/{workspace_id}/inventory-projects")
async def workspace_inventory_projects(workspace_id: str) -> dict:
    from .workspaces import WorkspaceRefusedError
    try:
        return await _linked_inventory_projects(workspace_id)
    except WorkspaceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))


# =============================================================================
# PLANNING (Fase D) — stateless like M8.4/M8.5: validate a plan, convert a
# validated plan into one AdapterProposal for the existing approval gate.
# No storage, no queue, no dispatch, no second approval mechanism.
# =============================================================================

@app.post("/api/v1/plans")
def create_plan(body: PlanBody) -> Plan:
    try:
        plan = Plan(
            plan_id=body.plan_id,
            goal=body.goal,
            summary=body.summary,
            steps=[PlanStep(**step.model_dump()) for step in body.steps],
            risks=list(body.risks),
        )
        return validate_plan(plan)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/plans/to-proposal", response_model=AdapterProposal)
def plan_to_proposal_route(body: PlanToProposalBody) -> AdapterProposal:
    try:
        plan = Plan(
            plan_id=body.plan.plan_id,
            goal=body.plan.goal,
            summary=body.plan.summary,
            steps=[PlanStep(**step.model_dump())
                   for step in body.plan.steps],
            risks=list(body.plan.risks),
        )
        return plan_to_proposal(plan, adapter_id=body.adapter_id,
                                request_id=body.request_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


# =============================================================================
# DESKTOP AGENT LOOP (Fase I/J/K) — propose -> approve -> dispatch -> result.
# The coordinator stores and gates actions; it never executes input
# itself. A local runtime performs dispatched actions after
# re-checking approval state. Cancel works from every waiting state.
# =============================================================================

class DesktopConflictError(RuntimeError):
    """Conditional desktop update found another status: lost the race."""


def _desktop_save(record: DesktopActionRecord, created: str,
                  expected_from: tuple[str, ...] | None = None) -> None:
    """Store a record, optionally only when the stored status matches.

    The conditional UPDATE is the lease: exactly one claimant moves
    approved -> dispatched, exactly one closer moves dispatched ->
    terminal. A lost race raises DesktopConflictError (HTTP 409);
    semantic violations are still ValueError (HTTP 422) from the
    agent_loop transition itself.
    """
    init_chat_database()
    with chat_connection() as db:
        if expected_from is None:
            db.execute("""INSERT INTO desktop_actions
            (action_id, record, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(action_id) DO UPDATE SET record=excluded.record,
            status=excluded.status, updated_at=excluded.updated_at""",
                       (record.action.action_id,
                        dump(record.model_dump(mode="json")),
                        record.status, created, now()))
            return
        changed = db.execute(
            """UPDATE desktop_actions SET record=?, status=?,
            updated_at=? WHERE action_id=? AND status IN ({})""".format(
                ",".join("?" * len(expected_from))),
            (dump(record.model_dump(mode="json")), record.status, now(),
             record.action.action_id, *expected_from)).rowcount
        if not changed:
            raise DesktopConflictError(
                f"Action '{record.action.action_id}' changed state; "
                "refusing to overwrite")


def _desktop_load(action_id: str) -> DesktopActionRecord:
    init_chat_database()
    with chat_connection() as db:
        row = db.execute(
            "SELECT record FROM desktop_actions WHERE action_id=?",
            (action_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Desktop action not found")
    return DesktopActionRecord.model_validate(load(row["record"]))


def _desktop_list(limit: int = 50, status: str | None = None) -> list[dict]:
    init_chat_database()
    with chat_connection() as db:
        if status is None:
            rows = db.execute(
                """SELECT record, status, created_at, updated_at
                FROM desktop_actions ORDER BY updated_at DESC LIMIT ?""",
                (max(1, min(limit, 100)),)).fetchall()
        else:
            rows = db.execute(
                """SELECT record, status, created_at, updated_at
                FROM desktop_actions WHERE status=?
                ORDER BY updated_at ASC LIMIT ?""",
                (status, max(1, min(limit, 100)))).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/v1/desktop/actions", status_code=201)
def desktop_propose(body: DesktopActionBody) -> dict:
    import secrets
    action_id = (body.action_id
                 or f"dact-{secrets.token_hex(4)}")
    try:
        action = new_action(action_id, body.action_type, body.parameters)
        record = agent_propose(action)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    _desktop_save(record, now())
    logger.info("desktop_action_proposed action_id=%s type=%s status=%s",
                action_id, body.action_type, record.status)
    return _with_binding(agent_describe(record))


@app.get("/api/v1/desktop/actions")
def desktop_list(status: str | None = None) -> list[dict]:
    if status is not None and status not in (
            "pending_approval", "approved", "rejected", "cancelled",
            "dispatched", "completed", "failed", "blocked"):
        raise HTTPException(status_code=422, detail="Unknown action status")
    items = []
    for row in _desktop_list(status=status):
        record = DesktopActionRecord.model_validate(load(row["record"]))
        items.append({**_with_binding(agent_describe(record)),
                      "updated_at": row["updated_at"]})
    return items


@app.get("/api/v1/desktop/actions/{action_id}")
def desktop_get(action_id: str) -> dict:
    return _with_binding(agent_describe(_desktop_load(action_id)))


@app.post("/api/v1/desktop/actions/{action_id}/decision")
def desktop_decide(action_id: str, body: DesktopDecisionBody) -> dict:
    record = _desktop_load(action_id)
    try:
        updated = agent_decide(record, action_id, body.response,
                               decided_by=body.decided_by)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        _desktop_save(updated, now(), expected_from=("pending_approval",))
    except DesktopConflictError as error:
        raise HTTPException(status_code=409, detail=str(error))
    logger.info("desktop_action_decided action_id=%s status=%s by=%s",
                action_id, updated.status, updated.decided_by)
    return agent_describe(updated)


@app.post("/api/v1/desktop/actions/{action_id}/cancel")
def desktop_cancel(action_id: str, body: DesktopDecisionBody) -> dict:
    record = _desktop_load(action_id)
    try:
        updated = agent_cancel(record, action_id,
                               decided_by=body.decided_by or "human")
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        _desktop_save(updated, now(),
                      expected_from=("pending_approval", "approved",
                                     "dispatched"))
    except DesktopConflictError as error:
        raise HTTPException(status_code=409, detail=str(error))
    logger.info("desktop_action_cancelled action_id=%s", action_id)
    return agent_describe(updated)


@app.post("/api/v1/desktop/actions/{action_id}/dispatch")
def desktop_dispatch(action_id: str,
                     body: DesktopDispatchBody | None = None) -> dict:
    """Release an approved action to the local runtime. No input happens
    here: dispatch is a status transition only. An optional node_id
    pins the lease holder; the standalone agent only runs actions
    dispatched to itself."""
    record = _desktop_load(action_id)
    try:
        updated = agent_dispatch(
            record, action_id,
            by=(body.node_id if body and body.node_id else ""),
            at=now())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        _desktop_save(updated, now(), expected_from=("approved",))
    except DesktopConflictError as error:
        raise HTTPException(status_code=409, detail=str(error))
    logger.info("desktop_action_dispatched action_id=%s by=%s", action_id,
                updated.dispatched_by or "manual")
    return agent_describe(updated)


@app.post("/api/v1/desktop/actions/{action_id}/result")
def desktop_result(action_id: str, body: DesktopResultBody) -> dict:
    record = _desktop_load(action_id)
    try:
        updated = agent_record_result(
            record, action_id, body.status, error=body.error,
            observation_reference=body.observation_reference)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        _desktop_save(updated, now(), expected_from=("dispatched",))
    except DesktopConflictError as error:
        raise HTTPException(status_code=409, detail=str(error))
    logger.info("desktop_action_closed action_id=%s status=%s",
                action_id, updated.status)
    return agent_describe(updated)


# =============================================================================
# AGENT CLAIM (BIG #2) — one atomic step from approved to dispatched-to-me.
# The standalone desktop agent polls this instead of reading the list:
# the conditional UPDATE guarantees exactly one claimant wins. Claim
# reuses the existing node protocol: the node must be registered,
# online and fresh, and the action's required capability must be a
# subset of the node's advertised capabilities. Returns the action or
# null (mirroring the task-claim route). No input happens here.
# =============================================================================

@app.post("/api/v1/desktop/actions/next")
def desktop_claim_next(body: DesktopClaimBody) -> dict | None:
    moment = now()
    with connection() as db:
        node = db.execute(
            "SELECT capabilities, status, last_seen, auth_token_hash FROM nodes WHERE node_id=?",
            (body.node_id,)).fetchone()
    if node is None:
        raise HTTPException(404, "Node is not registered")
    try:
        authenticate(body.node_id, node["auth_token_hash"],
                     body.node_token)
    except NodeAuthError:
        raise HTTPException(status_code=403,
                            detail="node credential rejected")
    if node["status"] != "online" or node_is_stale(node["last_seen"],
                                                   moment):
        return None
    expire_desktop_leases(moment)
    advertised = {str(cap).strip().lower()
                  for cap in load(node["capabilities"])}
    for row in _desktop_list(limit=100, status="approved"):
        record = DesktopActionRecord.model_validate(load(row["record"]))
        try:
            needed = capability_for(record.action.action_type)
        except ValueError:
            continue
        if needed is not None and needed.lower() not in advertised:
            continue
        try:
            updated = agent_dispatch(record, record.action.action_id,
                                     by=body.node_id, at=moment)
        except ValueError:
            continue
        try:
            _desktop_save(updated, moment, expected_from=("approved",))
        except DesktopConflictError:
            continue
        logger.info("desktop_action_claimed action_id=%s node_id=%s",
                    record.action.action_id, body.node_id)
        return _with_binding(agent_describe(updated))
    return None


# =============================================================================
# REMOTE INPUT SLICE 1 — ephemeral mouse sessions (no new transport).
# Browser -> coordinator -> node pull -> OS input. The coordinator never
# pushes: the node polls POST .../poll with its node_token (same auth
# as the desktop claim). Sessions + moves live only in the
# process-local registry (no table, no queue, no persistence):
# restart wipes them, fail-closed. CONNECT is the explicit human
# YES; DISCONNECT (or expiry, or a stale node) ends input.
# =============================================================================

def _remote_node_gate(node_id: str,
                      need: set[str] | None = None) -> dict:
    """Shared fail-closed gate: registered + online/fresh + capable.

    Returns the node record dict. Unknown nodes 404; stale/disabled
    nodes and nodes missing any needed capability are refused (403).
    Default need is the mouse capability (slice 1 compat).
    """
    from .remote_input import MOUSE_CAPABILITY
    needed = set(need) if need else {MOUSE_CAPABILITY}
    with connection() as db:
        row = db.execute(
            f"SELECT {NODE_PUBLIC_COLUMNS}, auth_token_hash "
            "FROM nodes WHERE node_id=?",
            (node_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Node is not registered")
    record = _node_to_json(row)
    if record.get("derived_status") not in ("online", "busy"):
        raise HTTPException(status_code=403,
                            detail="node is not online; refusing")
    advertised = {str(cap).strip().lower()
                  for cap in (record.get("capabilities") or [])}
    missing = {cap for cap in needed if cap not in advertised}
    if missing:
        raise HTTPException(status_code=403,
                            detail="node lacks "
                                   f"{sorted(missing)[0]}; refusing")
    return record


@app.post("/api/v1/remote-input/sessions", status_code=201)
def remote_input_connect(body: RemoteInputSessionBody) -> dict:
    """CONNECT: explicit human YES for one ephemeral mouse session.

    Idempotent: an already-open session for the node is returned
    instead of a second one. Expired sessions never resurrect.
    """
    import time as _time
    from .remote_input import REGISTRY, describe, open_session
    try:
        node_id = check_node_id(body.node_id)
    except NodeRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    _remote_node_gate(node_id)
    existing = REGISTRY.open_for_node(node_id)
    if existing is not None:
        return describe(existing, _time.time())
    session = open_session(node_id)
    REGISTRY.put(session)
    logger.info("remote_input_connected node_id=%s session=%s",
                node_id, session.session_id[:12])
    return describe(session, _time.time())


@app.get("/api/v1/remote-input/sessions/{session_id}")
def remote_input_status(session_id: str) -> dict:
    """Session status for the UI (open/closed). Read-only."""
    import time as _time
    from .remote_input import REGISTRY, RemoteInputGoneError, describe, require_live
    session = REGISTRY.get(session_id)
    if session is None:
        raise HTTPException(404, "Unknown remote-input session")
    try:
        require_live(session, _time.time())
    except RemoteInputGoneError:
        pass
    return describe(session, _time.time())


@app.post("/api/v1/remote-input/sessions/{session_id}/move",
          status_code=204)
def remote_input_move(session_id: str,
                      body: RemoteInputMoveBody) -> Response:
    """One mouse move inside an open session. Never stored: latest
    wins in the ephemeral buffer, consumed by the next node poll."""
    from .remote_input import (
        REGISTRY, RemoteInputGoneError, RemoteInputRefusedError, check_move,
    )
    import time as _time
    session = REGISTRY.get(session_id)
    if session is None:
        raise HTTPException(404, "Unknown remote-input session")
    # The node must still be live: a stale node auto-closes input.
    try:
        _remote_node_gate(session.node_id)
    except HTTPException as error:
        if error.status_code in (403, 404):
            from .remote_input import close_session
            close_session(session)
            raise HTTPException(status_code=403,
                                detail="node no longer live; "
                                       "session closed")
        raise
    try:
        check_move(session, body.x, body.y, now=_time.time())
    except RemoteInputGoneError as error:
        raise HTTPException(status_code=410, detail=str(error))
    except RemoteInputRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return Response(status_code=204)


@app.post("/api/v1/remote-input/sessions/{session_id}/close")
def remote_input_close(session_id: str) -> dict:
    """DISCONNECT: further moves and polls are refused."""
    import time as _time
    from .remote_input import REGISTRY, close_session, describe
    session = REGISTRY.get(session_id)
    if session is None:
        raise HTTPException(404, "Unknown remote-input session")
    close_session(session)
    logger.info("remote_input_closed node_id=%s session=%s",
                session.node_id, session.session_id[:12])
    return describe(session, _time.time())


def _remote_session_input(session_id: str,
                          need: set[str]) -> tuple:
    """Shared gate for session input routes: known session + live
    node advertising `need`. A dead node auto-closes the session."""
    import time as _time
    from .remote_input import REGISTRY, close_session
    session = REGISTRY.get(session_id)
    if session is None:
        raise HTTPException(404, "Unknown remote-input session")
    try:
        _remote_node_gate(session.node_id, need)
    except HTTPException as error:
        if error.status_code in (403, 404):
            close_session(session)
            raise HTTPException(status_code=403,
                                detail="node no longer live; "
                                       "session closed")
        raise
    return session, _time.time()


@app.post("/api/v1/remote-input/sessions/{session_id}/input",
          status_code=204)
def remote_input_action(session_id: str,
                        body: RemoteInputActionBody) -> Response:
    """One discrete input action inside an open session (click,
    key_press, hotkey, type_text, scroll, mouse_down, mouse_up,
    clipboard_set). Closed kind vocabulary, per-kind validation,
    capability-gated per kind, bounded fifo (refuse-when-full).
    Never stored beyond the ephemeral buffer."""
    from .remote_input import (
        REGISTRY, RemoteInputGoneError, RemoteInputRefusedError,
        capability_for_kind, queue_action,
    )
    session = REGISTRY.get(session_id)
    if session is None:
        raise HTTPException(404, "Unknown remote-input session")
    try:
        need = capability_for_kind(body.kind)
    except RemoteInputRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    session, moment = _remote_session_input(session_id, need)
    try:
        queue_action(session, body.kind,
                     body.params if isinstance(body.params, dict)
                     else {}, now=moment)
    except RemoteInputGoneError as error:
        raise HTTPException(status_code=410, detail=str(error))
    except RemoteInputRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return Response(status_code=204)


@app.post("/api/v1/remote-input/sessions/{session_id}/clipboard/request",
          status_code=204)
def remote_input_clipboard_request(session_id: str) -> Response:
    """Browser asks the node for its clipboard text (one-shot).

    The node delivers on its next polls; the browser reads via
    GET .../clipboard. Text-only, single ephemeral slot.
    """
    from .remote_input import (
        CLIPBOARD_READ_CAPABILITY, RemoteInputGoneError,
        RemoteInputRefusedError, request_clipboard,
    )
    session, moment = _remote_session_input(
        session_id, {CLIPBOARD_READ_CAPABILITY})
    try:
        request_clipboard(session, now=moment)
    except RemoteInputGoneError as error:
        raise HTTPException(status_code=410, detail=str(error))
    except RemoteInputRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return Response(status_code=204)


@app.get("/api/v1/remote-input/sessions/{session_id}/clipboard")
def remote_input_clipboard_read(session_id: str) -> dict:
    """Read delivered clipboard text once (consume-on-read).

    Returns {"text": ...} or {"text": null} when nothing arrived
    yet. No history, no persistence."""
    import time as _time
    from .remote_input import (
        REGISTRY, RemoteInputGoneError, take_clipboard,
    )
    session = REGISTRY.get(session_id)
    if session is None:
        raise HTTPException(404, "Unknown remote-input session")
    try:
        text = take_clipboard(session, now=_time.time())
    except RemoteInputGoneError as error:
        raise HTTPException(status_code=410, detail=str(error))
    return {"text": text}


@app.post("/api/v1/remote-input/poll")
def remote_input_poll(body: RemoteInputPollBody) -> dict | None:
    """Node pull: pending move (latest wins) + drained discrete
    actions + clipboard-request flag, or null when idle.

    Existing node auth (token) + freshness on every poll. A stale
    node auto-closes its session. A known-but-closed session
    answers 410 Gone (so a node holding a drag button releases
    it); a node that never had a session stays quiet (null).
    clipboard_text in the body is accepted only after the
    browser requested it (text-only, validated, single slot).
    Nothing here is persisted or replayed.
    """
    import time as _time
    from .remote_input import (
        MOUSE_CAPABILITY, REGISTRY, RemoteInputGoneError,
        RemoteInputRefusedError, close_session, store_clipboard,
        take_actions, take_pending,
    )
    try:
        node_id = check_node_id(body.node_id)
    except NodeRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    with connection() as db:
        row = db.execute(
            "SELECT status, last_seen, auth_token_hash, capabilities "
            "FROM nodes WHERE node_id=?",
            (node_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Node is not registered")
    try:
        authenticate(node_id, row["auth_token_hash"],
                     body.node_token)
    except NodeAuthError:
        raise HTTPException(status_code=403,
                            detail="node credential rejected")
    moment = now()
    session = REGISTRY.open_for_node(node_id)
    if session is None:
        # Closed session the node still polls: tell it to stop
        # (and release any held drag button). Never-seen: quiet.
        if REGISTRY.latest_for_node(node_id) is not None:
            raise HTTPException(status_code=410,
                                detail="no open remote-input session")
        return None
    if row["status"] != "online" or node_is_stale(row["last_seen"],
                                                  moment):
        close_session(session)
        raise HTTPException(status_code=410,
                            detail="node stale; session closed")
    advertised = {str(cap).strip().lower()
                  for cap in load(row["capabilities"] or "[]")}
    if MOUSE_CAPABILITY not in advertised:
        close_session(session)
        raise HTTPException(status_code=410,
                            detail="capability gone; session closed")
    if body.clipboard_text is not None:
        try:
            store_clipboard(session, body.clipboard_text,
                            now=_time.time())
        except RemoteInputGoneError as error:
            raise HTTPException(status_code=410, detail=str(error))
        except RemoteInputRefusedError as error:
            raise HTTPException(status_code=422, detail=str(error))
    try:
        move = take_pending(session, now=_time.time())
        actions = take_actions(session, now=_time.time())
    except RemoteInputGoneError:
        raise HTTPException(status_code=410,
                            detail="session closed")
    if move is None and not actions and not session.clipboard_request:
        return None
    answer: dict = {"session_id": session.session_id,
                    "node_id": node_id,
                    "clipboard_request": bool(
                        session.clipboard_request)}
    if move is not None:
        answer["move"] = move
    if actions:
        answer["actions"] = actions
    return answer


@app.get("/api/v1/agent/status")
def agent_status() -> dict:
    with connection() as db:
        nodes = db.execute(
            f"SELECT {NODE_PUBLIC_COLUMNS} FROM nodes ORDER BY last_seen DESC").fetchall()
    desktops = [_node_to_json(row) for row in nodes
                if any("desktop" in str(cap).lower()
                       for cap in _node_to_json(row)["capabilities"])]
    waiting: list[dict] = []
    current: dict | None = None
    for row in _desktop_list(limit=10):
        record = DesktopActionRecord.model_validate(load(row["record"]))
        summary = agent_describe(record)
        if record.status in ("pending_approval", "approved", "dispatched"):
            waiting.append(summary)
            if current is None and record.status in ("approved",
                                                     "dispatched"):
                current = summary
    return {
        "agents_online": len(desktops),
        "desktop_nodes": [
            {"node_id": node["node_id"], "hostname": node["hostname"],
             "status": node["derived_status"],
             "last_seen": node["last_seen"],
             "capabilities": node["capabilities"]}
            for node in desktops
        ],
        "waiting": waiting,
        "current_action": current,
        "activity": [
            {**agent_describe(DesktopActionRecord.model_validate(
                load(row["record"]))),
             "updated_at": row["updated_at"]}
            for row in _desktop_list(limit=10)
        ],
    }


# =============================================================================
# READ-ONLY GIT + PROJECT CONTEXT (Fase L/M) — look, never touch.
# =============================================================================

def _project_root(repo: str | None) -> str:
    if repo and repo.strip():
        return repo.strip()
    try:
        return default_context().repository
    except ValueError:
        import os as _os
        return _os.getcwd()


@app.get("/api/v1/git/status")
def git_status_route(repo: str | None = None) -> dict:
    try:
        result = git_status(_project_root(repo))
        result["branch"] = git_branch(_project_root(repo))["branch"]
        return result
    except GitRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except GitUnavailable as error:
        raise HTTPException(status_code=502, detail=str(error))


@app.get("/api/v1/git/diff")
def git_diff_route(repo: str | None = None,
                   stat_only: bool = True) -> dict:
    try:
        return git_diff(_project_root(repo), stat_only=stat_only)
    except GitRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except GitUnavailable as error:
        raise HTTPException(status_code=502, detail=str(error))


@app.get("/api/v1/project/context")
def project_context_route() -> dict:
    try:
        return default_context().model_dump()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


# =============================================================================
# MISSIONS (BIG #3) — conversational agency inside approved plans.
# The MissionExecutor orchestrates; thin wrappers below map its
# ExecutorError to HTTP (404 for unknown missions, 422 for refused
# transitions, 409 for lost races). Desktop input always flows
# through the existing action gate; the executor only links results
# back into steps with a proven (mission, step, action) binding.
# =============================================================================

def _executor() -> MissionExecutor:
    async def _advise(question: str, records: list[dict]):
        return await get_provider("ollama").advise(question, records)

    async def _inventory_search(query: str) -> list[dict]:
        records, _, _ = await _chat_world_context(query)
        return records

    def _git_read(source: str) -> dict:
        root = _project_root(None)
        if source == "git-status":
            result = git_status(root)
            result["branch"] = git_branch(root)["branch"]
            return result
        if source == "git-branch":
            return git_branch(root)
        if source == "git-diff":
            return git_diff(root, stat_only=False)
        raise ExecutorError(f"Unknown readout source '{source}'")

    def _project_read() -> dict:
        return default_context().model_dump()

    async def _observe_camera(mission, step) -> dict:
        device_id = str(step.parameters.get("device_id", ""))
        device = get_device(device_id)
        if device is None:
            raise ExecutorError(
                f"Camera '{device_id}' unknown; observe steps bind "
                "to a registered device")
        adapter = adapter_for(device_id)
        test_origin = getattr(adapter, "name", "") in (
            "synthetic-test", "test-only")
        try:
            result = ingest_snapshot(device, adapter,
                                     test_origin=test_origin)
        except IngestRefusedError as error:
            raise ExecutorError(str(error)) from error
        except CameraUnavailable as error:
            raise ExecutorError(str(error)) from error
        save_observation(result.observation)
        return {"status": "completed",
                "observation_id":
                    result.observation.observation_id,
                "detail": (f"media {result.media.media_ref} "
                           f"({result.media.size_bytes} bytes, local "
                           "only); geen automatische write."),
                "verified": False}

    def _propose_desktop(action_id: str, action_type: str,
                         parameters: dict):
        try:
            action = new_action(action_id, action_type, parameters)
            record = agent_propose(action)
        except ValueError as error:
            raise ExecutorError(str(error)) from error
        _desktop_save(record, now())
        return record

    def _load_desktop(action_id: str):
        try:
            return _desktop_load(action_id)
        except HTTPException:
            return None

    async def _fabricate_runner(mission, step) -> dict:
        description = str(step.parameters.get("description", ""))
        method = str(step.parameters.get("method",
                                        "procedural-test"))
        try:
            generator = get_generator(method)
        except MeshRefusedError as error:
            raise ExecutorError(str(error)) from error
        try:
            generated = generator.generate(description, {})
        except MeshUnavailable as error:
            raise ExecutorError(str(error)) from error
        report = validate_mesh(generated.artifact_ref)
        assessment = assess_printability(report)
        fabrication = new_fabrication()
        fabrication = fabrication.model_copy(update={
            "mesh_ref": generated.artifact_ref,
            "mesh_sha256": generated.sha256,
            "mesh_validation": report.verdict,
            "status": "mesh_validated"})
        fabrication = record_event(
            fabrication, "mission_generate",
            f"missie {mission.mission_id}: {generated.artifact_ref} "
            f"({report.verdict})")
        save_fabrication(fabrication)
        return {"status": "completed",
                "result_text": (
                    f"Mesh {generated.artifact_ref} "
                    f"({report.verdict}, {report.faces} faces, "
                    f"printability {assessment.verdict}; "
                    "metadata alleen, geen release)."),
                "verification": (f"validatie: {report.verdict}; "
                                 "generatie is nooit verificatie"),
                "verified": False}

    async def _slice_runner(mission, step) -> dict:
        try:
            request = check_slicer_request(
                str(step.parameters.get("artifact_ref", "")),
                str(step.parameters.get("profile", "")),
                str(step.parameters.get("printer_id", "")))
        except (SlicerRefusedError, MeshRefusedError,
                ValueError) as error:
            raise ExecutorError(str(error)) from error
        try:
            slicer = get_slicer("test-slicer")
        except SlicerRefusedError as error:
            raise ExecutorError(str(error)) from error
        try:
            result = slicer.slice(request)
        except SlicerUnavailable as error:
            raise ExecutorError(str(error)) from error
        safety = validate_gcode(result.gcode_ref)
        return {"status": "completed",
                "result_text": (
                    f"G-code {result.gcode_ref} "
                    f"({result.line_count} regels, safety "
                    f"{safety.verdict}; test-artefact, geen release)."),
                "verification": (f"safety: {safety.verdict}; "
                                 "assessment is geen toestemming"),
                "verified": False}

    async def _print_runner(mission, step) -> dict:
        from .missions import new_event as _new_event
        from .missions import save_event as _save_event
        proposal_id = str(step.parameters.get("proposal_id", ""))
        record = _write_load(proposal_id)
        if record is None:
            raise ExecutorError(
                f"Print '{proposal_id}' unknown; physical steps need "
                "a stored, approved print proposal")
        if record["status"] != "approved" or not record["approval"]:
            return {"status": "blocked",
                    "result_text": (
                        f"Print '{proposal_id}' is {record['status']}; "
                        "expliciete fysieke YES vereist — missie-"
                        "goedkeuring start de machine nooit."),
                    "verification": "no approval; no verification",
                    "verified": False}
        _save_event(_new_event(
            mission.conversation_id, "print_started",
            f"Print {proposal_id} gestart na fysieke approval.",
            mission_id=mission.mission_id, step_id=step.step_id,
            metadata={"proposal_id": proposal_id}))
        try:
            result = await _write_execute_record(record)
        except (PrintRefusedError, PrinterDeviceRefusedError,
                ValueError) as error:
            raise ExecutorError(str(error)) from error
        proposal = WriteProposal.model_validate(record["record"])
        approval = WriteApproval.model_validate(record["approval"])
        status = ("executed" if result.outcome == "executed"
                  else result.outcome)
        _write_save(proposal, status, approval=approval,
                    result=result)
        if result.outcome != "executed":
            _save_event(_new_event(
                mission.conversation_id, "print_failed",
                f"Print {proposal_id} {result.outcome}: "
                f"{result.error[:300]}",
                mission_id=mission.mission_id, step_id=step.step_id,
                metadata={"proposal_id": proposal_id}))
            return {"status": result.outcome,
                    "result_text": (
                        f"Print '{proposal_id}' {result.outcome}: "
                        f"{result.error[:500]}"),
                    "verification": "no execution; no verification",
                    "verified": False}
        _save_event(_new_event(
            mission.conversation_id, "print_completed",
            f"Print {proposal_id} uitgevoerd (telemetrie); "
            "fysieke verificatie nog open.",
            mission_id=mission.mission_id, step_id=step.step_id,
            metadata={"proposal_id": proposal_id}))
        return {"status": "completed",
                "result_text": (
                    f"Print '{proposal_id}' uitgevoerd "
                    f"(job {result.after.get('print_result', {}).get('job_id', '?')}); "
                    "telemetrie alleen — camera-verificatie nog open."),
                "verification": ("telemetrie ≠ verificatie; "
                                 "niet geverifieerd"),
                "verified": False}

    def _post_message(conversation_id: str, role: str, content: str,
                      sources: list) -> str:
        message = new_message(conversation_id, role, content,
                              sources=[dict(entry) for entry in sources])
        _chat_store_message(
            message.message_id, conversation_id, role, message.content,
            now(), dump(message.provenance.model_dump(mode="json")),
            dump(sources))
        return message.message_id

    async def _research_runner(mission, step) -> dict:
        """One bounded read-only research run (BIG #29). Creates
        or resumes the run, drives it through the engine with
        the Wikipedia provider (REAL attempt) + Ollama
        synthesis when available, and reports the dossier.
        Completes UNVERIFIED: research is interpretation with
        cited sources, never fact."""
        from .research_engine import (
            EngineRefusedError as _EngineRefused,
            execute_run as _execute_run,
            load_run as _load_run,
            load_dossier as _load_dossier,
            new_run as _new_run,
            save_run as _save_run,
        )
        from .research_transport import (
            TransportUnavailableError as _TransportDown,
            WikipediaSearchProvider as _Wiki,
        )
        run_id = str(step.parameters.get("research_run_id", ""))
        run = _load_run(run_id) if run_id else None
        try:
            max_sources = int(
                step.parameters.get("max_sources", 6) or 6)
        except (TypeError, ValueError):
            max_sources = 6
        max_sources = max(1, min(max_sources, 6))
        if run is None:
            question = str(step.parameters.get("question", ""))
            if not question.strip():
                raise ExecutorError(
                    "Research step needs a question or an "
                    "existing research_run_id")
            try:
                run = _new_run(
                    question.strip()[:500],
                    project_ref=str(step.parameters.get(
                        "project_ref", ""))[:100],
                    mission_id=mission.mission_id,
                    requested_by="mission",
                    metadata={"step_id": step.step_id})
                _save_run(run)
            except _EngineRefused as error:
                raise ExecutorError(str(error)) from error
        try:
            provider = _Wiki(language="nl")
        except _EngineRefused as error:
            raise ExecutorError(str(error)) from error
        try:
            from .memory import retrieve_memories as _recall

            def _memory_search(query: str):
                return _recall(query, limit=10)

            finished = await _execute_run(
                run.run_id, search_provider=provider,
                advise_fn=_advise,
                inventory_search=_inventory_search,
                list_memories_fn=_memory_search,
                project_read_fn=_project_read,
                max_sources=max_sources,
                seed_urls=[str(item or "")[:2000] for item in (
                    step.parameters.get("source_urls", "") or [])][:6])
        except _EngineRefused as error:
            raise ExecutorError(str(error)) from error
        except _TransportDown as error:
            return {"status": "blocked",
                    "result_text": (
                        "Ik heb geen echte bronnen kunnen ophalen: "
                        f"{error}. Geen findings, geen dossier."),
                    "verification": "no sources; no verification",
                    "verified": False}
        if finished.status == "completed" and finished.dossier_id:
            dossier = _load_dossier(finished.dossier_id)
            summary = (dossier.summary if dossier
                       else "")[:2000]
            return {"status": "completed",
                    "result_text": (
                        f"Onderzoek '{finished.question[:160]}' "
                        f"[{finished.execution_state}]: "
                        f"{len(finished.source_ids)} bronnen, "
                        f"{len(finished.claims)} claims, "
                        f"{len(finished.contradictions)} "
                        f"tegenstrijdigheden. Dossier "
                        f"{finished.dossier_id}. Samenvatting: "
                        f"{summary}"),
                    "verification": (
                        "research is interpretatie met "
                        "bronverwijzingen; nooit FACT"),
                    "verified": False}
        if finished.status == "unavailable":
            return {"status": "blocked",
                    "result_text": (
                        finished.error or "Ik heb geen echte "
                        "bronnen kunnen ophalen."),
                    "verification": "no sources; no verification",
                    "verified": False}
        return {"status": "blocked",
                "result_text": (
                    finished.error or
                    f"Research {finished.status}; review nodig."),
                "verification": "no verification",
                "verified": False}

    def _dispatch_queue_dep(mission_id: str, step_id: str) -> dict:
        """Executor injection for H1 auto-dispatch (sync, like the
        other deps). Raises ValueError/MissionConflictError, never
        HTTP — the executor maps those onto step outcomes."""
        return dispatch_step_task(mission_id, step_id)

    return MissionExecutor(ExecutorDeps(
        propose_desktop=_propose_desktop,
        load_desktop=_load_desktop,
        post_message=_post_message,
        advise=_advise,
        inventory_search=_inventory_search,
        git_read=_git_read,
        project_read=_project_read,
        run_write=_run_write_step,
        observe_camera=_observe_camera,
        fabricate_runner=_fabricate_runner,
        slice_runner=_slice_runner,
        print_runner=_print_runner,
        research_runner=_research_runner,
        dispatch_queue=_dispatch_queue_dep,
    ))


def _mission_error(error: ExecutorError) -> HTTPException:
    text = str(error)
    if "not found" in text.lower():
        return HTTPException(status_code=404, detail=text)
    if "changed state" in text:
        return HTTPException(status_code=409, detail=text)
    return HTTPException(status_code=422, detail=text)


def _mission_to_json(mission) -> dict:
    return mission.model_dump(mode="json")


@app.post("/api/v1/missions", status_code=201)
def mission_create(body: MissionCreateBody) -> dict:
    try:
        mission = _executor().create(
            body.conversation_id, body.goal,
            [step.model_dump() for step in body.steps]
            if body.steps is not None else None,
            max_steps=body.max_steps)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except ExecutorError as error:
        raise _mission_error(error)
    emit_event("mission.started", f"Mission {mission.mission_id}: "
               f"{mission.goal[:120]}",
               conversation_id=mission.conversation_id,
               mission_id=mission.mission_id)
    return _mission_to_json(mission)


@app.get("/api/v1/missions")
def mission_list(conversation_id: str | None = None) -> list[dict]:
    return [_mission_to_json(mission)
            for mission in list_missions(conversation_id)]


@app.get("/api/v1/missions/{mission_id}")
def mission_get(mission_id: str) -> dict:
    mission = load_mission(mission_id)
    if mission is None:
        raise HTTPException(404, "Mission not found")
    data = _mission_to_json(mission)
    data["bindings"] = [
        {"action_id": action_id, "step_id": step_id}
        for action_id, (_, step_id) in
        bindings_for_mission(mission_id).items()
    ]
    return data


@app.get("/api/v1/missions/{mission_id}/steps")
def mission_steps(mission_id: str) -> list[dict]:
    mission = load_mission(mission_id)
    if mission is None:
        raise HTTPException(404, "Mission not found")
    return [step.model_dump(mode="json") for step in mission.steps]


@app.get("/api/v1/missions/{mission_id}/events")
def mission_events(mission_id: str) -> list[dict]:
    mission = load_mission(mission_id)
    if mission is None:
        raise HTTPException(404, "Mission not found")
    return [event.model_dump(mode="json")
            for event in list_events(mission_id=mission_id)]


@app.post("/api/v1/missions/{mission_id}/approve")
def mission_approve(mission_id: str, body: MissionApproveBody) -> dict:
    try:
        mission = _executor().approve(mission_id, body.response,
                                      decided_by=body.decided_by)
    except ExecutorError as error:
        raise _mission_error(error)
    emit_event("approval.resolved",
               f"Mission {mission_id} approved",
               conversation_id=mission.conversation_id,
               mission_id=mission_id)
    return _mission_to_json(mission)


@app.post("/api/v1/missions/{mission_id}/pause")
def mission_pause(mission_id: str) -> dict:
    try:
        mission = _executor().pause(mission_id)
    except ExecutorError as error:
        raise _mission_error(error)
    return _mission_to_json(mission)


@app.post("/api/v1/missions/{mission_id}/resume")
def mission_resume(mission_id: str) -> dict:
    try:
        mission = _executor().resume(mission_id)
    except ExecutorError as error:
        raise _mission_error(error)
    return _mission_to_json(mission)


@app.post("/api/v1/missions/{mission_id}/cancel")
def mission_cancel(mission_id: str) -> dict:
    try:
        mission = _executor().cancel(mission_id)
    except ExecutorError as error:
        raise _mission_error(error)
    return _mission_to_json(mission)


def dispatch_step_task(mission_id: str, step_id: str) -> dict:
    """Queue one dispatchable mission step (H1 auto-dispatch).

    Reuses create_task (queue), the conditional mission save
    (race safety) and the mission event store. Never approves,
    never executes: the mission must already be approved/running
    and only DISPATCHABLE_KINDS map onto a queue task. Raises
    ValueError (404 when unknown, else 422) or
    MissionConflictError (409) for races and wrong statuses.
    Idempotent: an existing queued/assigned task for the same
    (mission, step, url) is returned, never duplicated.
    """
    mission = load_mission(mission_id)
    if mission is None:
        raise ValueError(f"Mission '{mission_id}' not found")
    step = next((entry for entry in mission.steps
                 if entry.step_id == step_id), None)
    if step is None:
        raise ValueError(
            f"Step '{step_id}' not found in mission '{mission_id}'")
    if mission.status not in ("approved", "running"):
        raise MissionConflictError(
            f"Mission '{mission_id}' is {mission.status}; dispatch "
            "needs an approved or running mission")
    if step.kind not in DISPATCHABLE_KINDS:
        raise ValueError(
            f"Step '{step_id}' (kind '{step.kind}') is never "
            "auto-dispatched")
    urls = dispatch_source_urls(step)
    if not urls:
        raise ValueError(
            f"Step '{step_id}' has no source URLs to dispatch")
    with connection() as db:
        rows = db.execute(
            "SELECT id, payload FROM tasks WHERE mission_id=? "
            "AND status IN ('queued','assigned')",
            (mission.mission_id,)).fetchall()
    live: dict[str, int] = {}
    for row in rows:
        try:
            payload = load(row["payload"] or "{}")
        except ValueError:
            continue
        if (isinstance(payload, dict)
                and payload.get("mission_step_id") == step_id
                and isinstance(payload.get("url"), str)):
            live[str(payload["url"])] = int(row["id"])
    task_ids: list[int] = []
    created_ids: list[int] = []
    for target in urls:
        if target in live:
            task_ids.append(live[target])
            continue
        spec = dispatchable_task(step, url=target)
        if spec is None:  # pragma: no cover - urls validated above
            continue
        made = create_task(TaskCreate(
            kind=str(spec["kind"]),
            payload=dict(spec["payload"]),
            required_capabilities=list(
                spec["required_capabilities"]),
            mission_id=mission.mission_id))
        task_ids.append(int(made["id"]))
        created_ids.append(int(made["id"]))
    old_status, old_step = mission.status, mission.current_step
    mission = set_step(
        mission, step_id, status="dispatched",
        started_at=step.started_at or now())
    save_mission(mission, expected=(old_status, old_step))
    if created_ids:
        save_event(new_event(
            mission.conversation_id, "task_dispatched",
            f"Stap {step.sequence + 1} gedispatched: "
            f"{len(created_ids)} queue-task(s) "
            f"({', '.join(str(task_id) for task_id in created_ids)}).",
            mission_id=mission.mission_id, step_id=step_id,
            metadata={"task_ids": created_ids}))
    wanted = (dispatchable_task(step) or {}).get(
        "required_capabilities", []) or ["research.fetch"]
    return {"mission_id": mission.mission_id, "step_id": step_id,
            "task_ids": task_ids,
            "eligible_nodes": eligible_nodes_for(str(wanted[0]))}


@app.post("/api/v1/missions/{mission_id}/dispatch")
def mission_dispatch(mission_id: str,
                     body: MissionDispatchBody) -> dict:
    """Queue one dispatchable step of an approved/running mission.

    Operator- or tick-triggered staging only: creates queued
    tasks, marks the step dispatched, never approves, never
    executes. H3 closes the step after task completion."""
    try:
        return dispatch_step_task(mission_id.strip(),
                                  body.step_id.strip())
    except MissionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except ValueError as error:
        text = str(error)
        if "not found" in text.lower():
            raise HTTPException(status_code=404, detail=text)
        raise HTTPException(status_code=422, detail=text)


@app.post("/api/v1/missions/{mission_id}/tick")
async def mission_tick(mission_id: str) -> dict:
    try:
        return await _executor().tick(mission_id)
    except ExecutorError as error:
        raise _mission_error(error)


@app.post("/api/v1/missions/{mission_id}/run")
async def mission_run(mission_id: str,
                      body: MissionRunBody) -> dict:
    """Drive one bounded autonomous loop run (BIG #21).
    Advances approved work to the next gate, reports the
    exact stop reason, stores one memory on terminal
    states. Never approves, never invents steps, never
    executes beyond the existing executor."""
    from .mission_loop import (
        MissionLoopRefusedError,
        run_loop,
    )
    try:
        return await run_loop(mission_id,
                              max_rounds=body.max_rounds)
    except MissionLoopRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/chat/{conversation_id}/missions", status_code=201)
async def chat_mission(conversation_id: str,
                       body: ChatMissionBody) -> dict:
    with chat_connection() as db:
        init_chat_database()
        row = db.execute(
            "SELECT conversation_id FROM conversations "
            "WHERE conversation_id=?", (conversation_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Conversation not found")
    records, _, _ = await _chat_world_context(body.goal)
    try:
        _active = default_context()
        import os as _os
        records = [{
            "entity_type": "project-context",
            "entity_id": _active.project_id,
            "title": _active.name,
            "snippet": f"Actief project {_active.name} "
                       f"({_os.path.basename(_active.repository)}). "
                       "Details staan in INVENTory; dit is context, "
                       "geen toestemming.",
            "provenance": {"source_type": "user-created",
                           "human_verified": True},
            "match_type": "project",
            "score": 0.0,
        }] + records
    except ValueError:
        pass
    try:
        mission = _executor().create(
            conversation_id, body.goal,
            [step.model_dump() for step in body.steps]
            if body.steps is not None else None,
            max_steps=body.max_steps,
            context_records=records)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except ExecutorError as error:
        raise _mission_error(error)
    return _mission_to_json(mission)


@app.post("/api/v1/missions/suggest")
async def mission_suggest(body: SuggestStepsBody) -> dict:
    """Advisor-drafted step descriptions only. Untrusted: the operator
    assembles the real mission (kinds, actions, approvals) — the
    provider never decides permissions or execution."""
    records, _, _ = await _chat_world_context(
        f"{body.goal} {body.context}"[:200])
    try:
        answered = await get_provider("ollama").advise(
            f"Stel concrete stappen voor om dit doel te bereiken "
            f"(alleen beschrijvingen, één per regel beginnend met '- '): "
            f"{body.goal}"[:500], records)
    except ProviderRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except ProviderUnavailable as error:
        raise HTTPException(status_code=502, detail=str(error))
    suggestions = []
    for line in answered.advice.splitlines():
        text = line.strip()
        if text.startswith("- "):
            text = text[2:].strip()
        elif text[:2].strip("0123456789.") == "" and "." in text:
            text = text.split(".", 1)[1].strip()
        else:
            continue
        if text and len(suggestions) < 10:
            suggestions.append({"description": text[:500]})
    return {"goal": body.goal, "suggestions": suggestions,
            "note": "Advies alleen: kies soort/actie/goedkeuring zelf bij "
                    "het aanmaken van de missie."}


def _with_binding(summary: dict) -> dict:
    """Attach (mission_id, step_id) proof to an action summary, if any."""
    bound = get_binding(summary.get("action_id", ""))
    return {**summary,
            "mission_id": bound[0] if bound else None,
            "step_id": bound[1] if bound else None}


# =============================================================================
# MISSION TEMPLATES (BIG #4) — named starting points, same gates.
# Instantiation renders step descriptions and runs through the exact
# same mission validation/approval as hand-built missions.
# =============================================================================

@app.get("/api/v1/mission-templates")
def mission_templates_list() -> list[dict]:
    return list_templates()


@app.post("/api/v1/missions/from-template", status_code=201)
async def mission_from_template(body: TemplateMissionBody) -> dict:
    try:
        steps, template_max = instantiate(body.template_id, body.goal)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    with chat_connection() as db:
        init_chat_database()
        row = db.execute(
            "SELECT conversation_id FROM conversations "
            "WHERE conversation_id=?", (body.conversation_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Conversation not found")
    records, _, _ = await _chat_world_context(body.goal)
    try:
        mission = _executor().create(
            body.conversation_id, body.goal,
            steps,
            max_steps=body.max_steps or template_max,
            context_records=records)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except ExecutorError as error:
        raise _mission_error(error)
    return _mission_to_json(mission)


# =============================================================================
# MYCELIUM V1 (BIG #23-28) — command center, decisions, recovery,
# agenda, bootstrap, research capability, physical readiness.
# Adds NO new execution power: commands build missions from the
# existing safe templates, decisions only read state, recovery
# only resumes read-only steps explicitly, agenda is read-only
# context, bootstrap missions wait honestly for a real research
# transport. Every boundary below fails closed.
# =============================================================================

def _v1_conversation(conversation_id: str, title: str) -> str:
    """Use the given conversation or start one for a command."""
    from .conversations import generate_conversation_id
    init_chat_database()
    if conversation_id:
        with chat_connection() as db:
            row = db.execute(
                "SELECT conversation_id FROM conversations "
                "WHERE conversation_id=?", (conversation_id,)).fetchone()
        if row is not None:
            return conversation_id
    fresh = generate_conversation_id()
    _chat_ensure_conversation(fresh, title[:120], "", now())
    return fresh


def _v1_waiting_reason(mission) -> str:
    """Exact human-readable wait reason for a mission card."""
    from .missions import current_step_of
    step = current_step_of(mission)
    if mission.status == "pending_approval":
        return "Ik wacht op jouw YES voor dit plan."
    if mission.status == "paused":
        return "Gepauzeerd — hervat expliciet om verder te gaan."
    if step is None:
        return "Geen huidige stap; opnieuw ticken na statuswijziging."
    if step.status == "waiting_approval":
        return (f"Ik wacht op jouw toestemming voor: "
                f"{step.action_type or step.kind} "
                f"({step.desktop_action_id or 'zonder id'}) — "
                f"exact YES via de desktop-actie.")
    if step.status == "dispatched":
        return (f"Actie {step.desktop_action_id or '?'} loopt bij de "
                f"desktop-agent; ik wacht op zijn verslag.")
    if step.kind == "proposal":
        return ("Voorstel klaar als data — goedkeuren loopt via "
                "/api/v1/approvals, nooit automatisch.")
    if step.kind in ("write", "fabricate", "slice", "physical_print"):
        return (f"Een {step.kind}-stap heeft een eigen exacte YES plus "
                f"fingerprint-herbevestiging nodig.")
    if step.status in ("failed", "blocked"):
        return (f"Stap '{step.description[:80]}' is {step.status}: "
                f"{step.error[:160] or 'zie events'}.")
    return (f"Volgende: {step.kind} — "
            f"'{step.description[:100]}' ({step.status}).")


@app.post("/api/v1/command")
async def command_center(body: CommandBody) -> dict:
    """Command Center: NL/EN text -> intent -> status answer,
    safe template mission, or mission control. One brain: advice
    still flows through chat(); routing is deterministic."""
    from .command import EXAMPLE_COMMANDS, parse_command
    try:
        command = parse_command(body.text)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    intent = command.intent
    if intent == "help":
        return {"intent": intent, "confidence": command.confidence,
                "reply": ("Dit kun je me vragen:\n" + "\n".join(
                    f"- {example}" for example in EXAMPLE_COMMANDS)
                    + "\nIk maak alleen veilige lees-/onderzoeksplannen; "
                      "klikken, schrijven, publiceren en fysieke acties "
                      "vragen altijd eerst jouw YES."),
                "examples": list(EXAMPLE_COMMANDS)}
    if intent == "chat":
        answer = await chat(ChatRequest(
            conversation_id=body.conversation_id or None,
            message=command.raw))
        return {"intent": intent, "confidence": command.confidence,
                "reply": answer.reply,
                "conversation_id": answer.conversation_id}
    if intent == "morning_report":
        report = report_morning()
        sections = report.get("sections", [])
        lines = []
        for section in sections:
            items = section.get("items", [])[:4]
            if items:
                lines.append(f"{section.get('title', '?')}: "
                             + "; ".join(str(item)[:120]
                                         for item in items))
        waiting = [line for line in lines if line]
        reply = ("Goedemorgen — dit heb ik gevonden:\n" + "\n".join(
            f"- {line}" for line in waiting[:12])
            if waiting else "Nog geen nieuws van vannacht.")
        return {"intent": intent, "confidence": command.confidence,
                "reply": reply, "morning": report}
    if intent == "agenda_today":
        from .agenda import init_agenda_tables, list_events
        init_chat_database()
        with chat_connection() as db:
            init_agenda_tables(db)
            events = list_events(db, upcoming_only=True, limit=20)
        if not events:
            return {"intent": intent,
                    "confidence": command.confidence,
                    "reply": ("Geen agendapunten gevonden. Importeer een "
                              ".ics via /agenda als je wilt dat ik "
                              "meekijk."),
                    "events": []}
        lines = [f"{event.get('start', '?')} — "
                 f"{event.get('title', '?')}"
                 + (f" ({event.get('location', '')})"
                    if event.get("location") else "")
                 for event in events]
        return {"intent": intent, "confidence": command.confidence,
                "reply": "Vandaag op je agenda:\n" + "\n".join(
                    f"- {line}" for line in lines),
                "events": events}
    if intent == "mission_status":
        from .missions import list_missions
        missions = [mission for mission in list_missions(limit=20)
                    if mission.status not in (
                        "completed", "failed", "cancelled")]
        if not missions:
            return {"intent": intent,
                    "confidence": command.confidence,
                    "reply": "Geen openstaande missies — alles is afgerond "
                             "of gestopt.",
                    "missions": []}
        cards = [{"mission_id": mission.mission_id,
                  "goal": mission.goal, "status": mission.status,
                  "waiting_reason": _v1_waiting_reason(mission)}
                 for mission in missions]
        lines = [f"{card['goal'][:90]} [{card['status']}] — "
                 f"{card['waiting_reason']}" for card in cards]
        return {"intent": intent, "confidence": command.confidence,
                "reply": "Dit loopt er nu:\n" + "\n".join(
                    f"- {line}" for line in lines),
                "missions": cards}
    if intent == "mission_stop":
        from .missions import list_missions
        if command.mission_id:
            mission = load_mission(command.mission_id)
            if mission is None:
                raise HTTPException(404, "Mission not found")
            targets = [mission]
        else:
            targets = [mission for mission in list_missions(limit=50)
                       if mission.status in ("running", "approved")]
        stopped = []
        for mission in targets:
            try:
                if mission.status == "running":
                    _executor().pause(mission.mission_id)
                    stopped.append(mission.mission_id)
                elif mission.status in ("approved", "pending_approval",
                                        "paused"):
                    _executor().cancel(mission.mission_id)
                    stopped.append(mission.mission_id)
            except ExecutorError:
                continue
        if not stopped:
            return {"intent": intent,
                    "confidence": command.confidence,
                    "reply": "Er liep niets dat ik kon stoppen.",
                    "stopped": []}
        return {"intent": intent, "confidence": command.confidence,
                "reply": ("Gestopt en veilig weggezet "
                          f"({len(stopped)} missie(s)). Zeg 'ga verder' "
                          "om een veilige missie te hervatten."),
                "stopped": stopped}
    if intent == "mission_resume":
        from .missions import bindings_for_mission, list_missions
        from .recovery import scan
        if command.mission_id:
            mission = load_mission(command.mission_id)
            if mission is None:
                raise HTTPException(404, "Mission not found")
            targets = [mission]
        else:
            targets = list_missions(limit=50)
        bindings = {mission.mission_id: bindings_for_mission(
            mission.mission_id) for mission in targets}
        report = scan(targets, bindings.get)
        resumed = []
        for item in report["verdicts"]:
            if item["verdict"] != "safe_to_resume":
                continue
            if len(resumed) >= 5:
                break
            try:
                current = load_mission(item["mission_id"])
                if current is None:
                    continue
                if current.status == "paused":
                    _executor().resume(current.mission_id)
                from .mission_loop import run_loop
                result = await run_loop(current.mission_id,
                                        max_rounds=5)
                resumed.append({"mission_id": current.mission_id,
                                "stop_reason": result.get(
                                    "stop_reason",
                                    result.get("outcome", "?"))})
            except (ExecutorError, ValueError):
                continue
        waiting = [item for item in report["verdicts"]
                   if item["verdict"] == "needs_reapproval"]
        reply = ("Niets veilig hervatbaar gevonden."
                 if not resumed else
                 f"{len(resumed)} veilige missie(s) hervat (alleen lezen).")
        if waiting:
            reply += (f" {len(waiting)} missie(s) wachten op jouw YES.")
        return {"intent": intent, "confidence": command.confidence,
                "reply": reply, "resumed": resumed,
                "waiting": waiting}
    # research_project / inventory_status / project_overview:
    # build a mission from the existing safe template.
    # research_project uses the research_topic template: one
    # bounded read-only webrun (REAL/TEST/UNAVAILABLE labelled).
    conversation_id = _v1_conversation(
        body.conversation_id, command.target or command.raw[:80])
    goal = (f"Onderzoek {command.target}" if command.target
            else command.raw[:200])
    template_id = command.template_id or "investigate_inventory"
    try:
        steps, template_max = instantiate(template_id, goal)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    records, _, _ = await _chat_world_context(goal)
    try:
        mission = _executor().create(
            conversation_id, goal, steps, max_steps=template_max,
            context_records=records)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except ExecutorError as error:
        raise _mission_error(error)
    is_web = any(step.kind == "research" for step in mission.steps)
    if is_web:
        reply = (f"RESEARCH_STARTED — ik ga '{goal[:120]}' "
                 f"onderzoeken op basis van je project-context. "
                 f"Alleen read-only bronnen; bronnen en "
                 f"onzekerheden toon ik apart. Geef YES op het plan, "
                 f"dan start de webrun (REAL/TEST/UNAVAILABLE gelabeld).")
    else:
        reply = (f"Ik heb een onderzoeksplan gemaakt voor "
                 f"'{goal[:120]}' ({len(mission.steps)} stappen, "
                 "alleen lezen). Geef YES op het plan, dan ga ik "
                 "zelfstandig verder tot ik je nodig heb.")
    return {"intent": intent, "confidence": command.confidence,
            "reply": reply,
            "research_state": ("RESEARCH_STARTED" if is_web else ""),
            "mission": _mission_to_json(mission),
            "conversation_id": conversation_id}


@app.post("/api/v1/missions/{mission_id}/decide")
def mission_decide(mission_id: str) -> dict:
    """Evaluate the current step into an explicit decision
    (BIG #24). Read-only: never mutates, never approves."""
    from .decisions import StepOutcome, decide
    from .missions import current_step_of
    mission = load_mission(mission_id)
    if mission is None:
        raise HTTPException(404, "Mission not found")
    step = current_step_of(mission)
    if step is None:
        outcome = StepOutcome(
            kind="", step_status="completed", ok=True,
            mission_status=mission.status)
    else:
        attempts = 0
        try:
            attempts = int((mission.metadata or {}).get(
                f"attempts:{step.step_id}", 0))
        except (ValueError, TypeError, AttributeError):
            attempts = 0
        outcome = StepOutcome(
            kind=step.kind, step_status=step.status,
            ok=step.status == "completed", error=step.error,
            attempts=attempts,
            waiting_detail=(step.desktop_action_id
                            or step.description)[:200],
            mission_status=mission.status)
    decision = decide(outcome)
    return {"mission_id": mission_id, "status": mission.status,
            "decision": decision.state, "reason": decision.reason,
            "retry_in_seconds": decision.retry_in_seconds,
            "needs": dict(decision.needs)}


@app.post("/api/v1/missions/recover")
async def missions_recover(body: RecoverBody) -> dict:
    """Startup/restart recovery scan (BIG #25). Report-only by
    default; resume_safe drives ONLY safe_to_resume missions
    through the bounded loop (read-only steps, never gated)."""
    from .missions import list_missions
    from .recovery import scan
    report = scan(list_missions(limit=100),
                  lambda mission_id: bindings_for_mission(mission_id))
    resumed: list[dict] = []
    if body.resume_safe:
        from .mission_loop import run_loop
        for item in report["verdicts"]:
            if item["verdict"] != "safe_to_resume":
                continue
            if len(resumed) >= body.max_resume:
                break
            try:
                current = load_mission(item["mission_id"])
                if current is None:
                    continue
                if current.status not in ("approved", "running",
                                          "paused"):
                    continue
                if current.status == "paused":
                    _executor().resume(current.mission_id)
                result = await run_loop(current.mission_id,
                                        max_rounds=5)
                resumed.append({
                    "mission_id": current.mission_id,
                    "stop_reason": result.get(
                        "stop_reason", result.get("outcome", "?"))})
            except (ExecutorError, ValueError):
                continue
    report["resumed"] = resumed
    return report


@app.get("/api/v1/research/capability")
async def research_capability(probe: bool = False) -> dict:
    """Honest research-transport status. Unprobed by default;
    probe=true runs one tiny local-model call (bounded 10s)."""
    from .ollama_advisor import (DEFAULT_BASE_URL, DEFAULT_MODEL)
    available: str | bool = "unprobed"
    detail = ("Oproepbaar via een analyse-stap; status onbekend tot "
              "een probe of een missie echt draait.")
    if probe:
        try:
            provider = get_provider("ollama", timeout=10)
            answered = await provider.advise("Zeg alleen: ok", [])
            available = True
            detail = (f"Lokaal model antwoordt "
                      f"({answered.model or DEFAULT_MODEL}).")
        except ProviderUnavailable as error:
            available = False
            detail = f"Lokaal model onbereikbaar: {error}"
        except ProviderRefusedError as error:
            available = False
            detail = f"Probe geweigerd: {error}"
    return {"research_transport": "local-analysis",
            "provider": "ollama",
            "base_url": DEFAULT_BASE_URL,
            "model": DEFAULT_MODEL,
            "available": available,
            "detail": detail,
            "search": {
                "provider": "wikipedia",
                "execution_state": "REAL-when-reachable",
                "hosts": ["nl/en/de/fr.wikipedia.org"],
                "budgets": {"max_queries": 3, "max_sources": 6,
                            "max_bytes": 200000}},
            "fetch": {"mode": "GET-only, SSRF-hardened",
                      "timeout_seconds": 10,
                      "redirects": 3, "posts": False,
                      "credentials": False},
            "test_provider": "provider=test met expliciete "
                             "test_pages (TEST-label)",
            "note": ("Bootstrap-missies wachten als "
                     "WAITING_FOR_RESEARCH_CAPABILITY tot een echte "
                     "transportlaag draait; voltooiing wordt nooit "
                     "gefaket.")}


@app.post("/api/v1/agenda/import")
def agenda_import(body: AgendaImportBody) -> dict:
    """ICS import with preview-first discipline. preview_only
    parses and reports; preview_only=false stores with UID dedup."""
    from .agenda import (AgendaRefusedError, init_agenda_tables,
                         parse_ics, store_preview)
    try:
        preview = parse_ics(body.ics_text,
                            source_label=body.source_label)
    except AgendaRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    if body.preview_only:
        return {"preview": True,
                "source_label": preview.source_label,
                "event_count": len(preview.events),
                "events": [event.__dict__
                           for event in preview.events[:50]]}
    init_chat_database()
    with chat_connection() as db:
        init_agenda_tables(db)
        try:
            result = store_preview(db, preview)
        except AgendaRefusedError as error:
            raise HTTPException(status_code=422, detail=str(error))
    return {"preview": False, **result}


@app.get("/api/v1/agenda/events")
def agenda_events(upcoming_only: bool = False,
                  limit: int = 100) -> list[dict]:
    """Stored agenda events: read-only context, never facts."""
    from .agenda import init_agenda_tables, list_events
    init_chat_database()
    with chat_connection() as db:
        init_agenda_tables(db)
        return list_events(db, limit=limit,
                           upcoming_only=upcoming_only)


@app.get("/api/v1/agenda/sources")
def agenda_sources() -> list[dict]:
    from .agenda import init_agenda_tables, list_sources
    init_chat_database()
    with chat_connection() as db:
        init_agenda_tables(db)
        return list_sources(db)


@app.post("/api/v1/bootstrap/ensure", status_code=201)
async def bootstrap_ensure(body: BootstrapBody) -> dict:
    """Create the bootstrap research campaign once (BIG #28 §26).
    Idempotent via metadata bootstrap keys; auto_approve=false
    leaves plans pending (human YES per plan)."""
    from .bootstrap import (BOOTSTRAP_DOMAINS, mission_metadata,
                            missing_domains)
    from .missions import list_missions, save_mission
    with chat_connection() as db:
        init_chat_database()
        row = db.execute(
            "SELECT conversation_id FROM conversations "
            "WHERE conversation_id=?", (body.conversation_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Conversation not found")
    missing = missing_domains(list_missions(limit=100))
    created: list[dict] = []
    for domain in missing:
        if len(created) >= len(BOOTSTRAP_DOMAINS):
            break
        steps, template_max = instantiate(domain["template"],
                                          domain["goal"])
        records, _, _ = await _chat_world_context(domain["goal"])
        try:
            mission = _executor().create(
                body.conversation_id, domain["goal"], steps,
                max_steps=template_max, context_records=records)
        except (ValueError, ExecutorError):
            continue
        stamped = mission.model_copy(update={
            "metadata": {**(mission.metadata or {}),
                         **mission_metadata(domain)}})
        try:
            save_mission(stamped)
        except (ValueError, MissionConflictError):
            continue
        created.append({"mission_id": stamped.mission_id,
                        "domain": domain["domain"],
                        "goal": domain["goal"][:160]})
    if body.auto_approve:
        approved = []
        for item in created:
            try:
                _executor().approve(item["mission_id"], "YES",
                                    decided_by="bootstrap-operator")
                approved.append(item["mission_id"])
            except ExecutorError:
                continue
        return {"created": created, "approved": approved,
                "skipped": len(BOOTSTRAP_DOMAINS) - len(missing)}
    return {"created": created, "approved": [],
            "skipped": len(BOOTSTRAP_DOMAINS) - len(missing)}


@app.get("/api/v1/bootstrap/status")
def bootstrap_status() -> dict:
    """Which bootstrap domains have a mission, which are missing."""
    from .bootstrap import BOOTSTRAP_DOMAINS, missing_domains
    from .missions import list_missions
    missions = list_missions(limit=100)
    missing = missing_domains(missions)
    missing_keys = {domain["key"] for domain in missing}
    present = [{"key": domain["key"], "domain": domain["domain"],
                "mission_id": next((
                    mission.mission_id for mission in missions
                    if (mission.metadata or {}).get("bootstrap_key")
                    == domain["key"]), "")}
               for domain in BOOTSTRAP_DOMAINS
               if domain["key"] not in missing_keys]
    return {"campaign": "bootstrap-campaign-v1",
            "present": present,
            "missing": [{"key": domain["key"],
                         "domain": domain["domain"]}
                        for domain in missing]}


@app.get("/api/v1/physical/status")
def physical_status() -> dict:
    """Honest physical-world readiness matrix. No fake LIVE."""
    capabilities: list[dict] = []
    try:
        printers = [printer.model_dump(mode="json")
                    if hasattr(printer, "model_dump") else dict(printer)
                    for printer in list_printers()]
    except (ValueError, AttributeError):
        printers = []
    for printer in printers:
        capabilities.append({
            "device": printer.get("printer_id", "printer"),
            "kind": "printer",
            "status": "SIMULATED",
            "gate": "PROPOSE → APPROVE → REVALIDATE → EXECUTE → "
                    "OBSERVE → VERIFY",
            "note": "Simulated until a real transport + physical "
                    "YES + fingerprint exists."})
    try:
        from .robots import list_robots
        robots = list_robots()
    except (ValueError, AttributeError, ImportError):
        robots = []
    for robot in robots:
        robot_id = (robot.get("robot_id", "robot")
                    if isinstance(robot, dict)
                    else str(getattr(robot, "robot_id", "robot")))
        capabilities.append({"device": robot_id, "kind": "robot",
                             "status": "HARDWARE_REQUIRED",
                             "gate": "own exact YES + fingerprint",
                             "note": "No hardware attached."})
    try:
        from .drones import list_drones
        drones = list_drones()
    except (ValueError, AttributeError, ImportError):
        drones = []
    for drone in drones:
        drone_id = (drone.get("drone_id", "drone")
                    if isinstance(drone, dict)
                    else str(getattr(drone, "drone_id", "drone")))
        capabilities.append({"device": drone_id, "kind": "drone",
                             "status": "HARDWARE_REQUIRED",
                             "gate": "own exact YES + fingerprint",
                             "note": "No hardware attached."})
    if not capabilities:
        capabilities.append({
            "device": "none-registered", "kind": "none",
            "status": "UNAVAILABLE",
            "gate": "register a device first",
            "note": "No physical devices registered; nothing can "
                    "move until one is."})
    capabilities.append({"device": "garmin", "kind": "integration",
                         "status": "UNAVAILABLE",
                         "gate": "official OAuth + operator approval",
                         "note": "No credentials, no fabricated OAuth."})
    capabilities.append({"device": "n8n", "kind": "transport",
                         "status": "CONFIGURED-TRANSPORT",
                         "gate": "Mycelium stays authority; n8n only "
                                 "transports",
                         "note": "Useful without n8n; check disk space "
                                 "before installing anything new."})
    return {"capabilities": capabilities}


# =============================================================================
# CAMERAS (BIG #4) — generic device abstraction, Insta360-ready.
# Registration is explicit; discovery is read-only names; snapshots
# require an injected capture adapter and refuse without one.
# No production adapter ships in this slice: snapshot calls
# fail-closed (409) instead of fabricating bytes.
# =============================================================================

@app.post("/api/v1/cameras/register", status_code=201)
def camera_register(body: CameraRegisterBody) -> dict:
    import secrets
    device_id = (body.device_id or f"cam-{secrets.token_hex(4)}")
    try:
        device = new_device(device_id, body.name, body.kinds,
                            body.source, notes=body.notes)
    except CameraRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    save_device(device)
    logger.info("camera_registered device_id=%s source=%s kinds=%s",
                device_id, body.source, ",".join(device.kinds))
    return device.model_dump(mode="json")


@app.get("/api/v1/cameras")
def cameras_list() -> list[dict]:
    return [device.model_dump(mode="json") for device in list_devices()]


@app.get("/api/v1/cameras/detected")
def cameras_detected() -> dict:
    """Read-only local imaging-device enumeration. No activation."""
    return detect_local_imaging_devices()


@app.get("/api/v1/cameras/{device_id}")
def camera_get(device_id: str) -> dict:
    device = get_device(device_id)
    if device is None:
        raise HTTPException(404, "Camera not found")
    return device.model_dump(mode="json")


@app.get("/api/v1/cameras/{device_id}/observations")
def camera_observations(device_id: str) -> list[dict]:
    if get_device(device_id) is None:
        raise HTTPException(404, "Camera not found")
    return [obs.model_dump(mode="json")
            for obs in list_observations(device_id)]


@app.post("/api/v1/cameras/{device_id}/snapshot", status_code=201)
def camera_snapshot(device_id: str) -> dict:
    device = get_device(device_id)
    if device is None:
        raise HTTPException(404, "Camera not found")
    try:
        observation = take_snapshot(device, None)
    except CameraRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except CameraUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error))
    save_observation(observation)
    return observation.model_dump(mode="json")


# =============================================================================
# VISION INGESTION + OBSERVATIONS + LOCAL VLM (BIG #6) — camera to
# verified world change. Chain: ingest (observation + local media)
# -> VLM analysis (ADVICE) -> inert proposal -> exact-YES approval
# -> BIG #5 controlled write -> independent verification.
# Observations are sensor-observed, never FACT; VLM output never
# self-verifies; no write ever follows automatically.
# =============================================================================

_STREAMS = StreamManager()


def _observation_load(observation_id: str):
    """Load one stored camera observation by id (any device)."""
    from .cameras import CameraObservation
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT record FROM camera_observations "
                         "WHERE observation_id=?",
                         (observation_id,)).fetchone()
    if row is None:
        return None
    return CameraObservation.model_validate(load(row["record"]))


def _observation_summaries(observations) -> list[dict]:
    """Bounded metadata summaries for chat/context. No pixels."""
    summaries = []
    for observation in list(observations or [])[:5]:
        record = (observation.model_dump(mode="json")
                  if hasattr(observation, "model_dump")
                  else dict(observation))
        labels: list[str] = []
        try:
            for analysis in list_analyses(
                    str(record.get("observation_id", "")), limit=1):
                labels = list(analysis.result.get("labels", []))[:5]
        except ValueError:
            labels = []
        summaries.append({
            "entity_type": "camera-observation",
            "entity_id": str(record.get("observation_id", "")),
            "title": (f"Observatie via "
                      f"{record.get('device_id', '?')}"),
            "snippet": (
                f"{record.get('created_at', '?')}; media "
                f"{record.get('media_ref', '?')}"
                + (f"; VLM: {', '.join(str(label) for label in labels)}"
                   if labels else "; nog geen VLM-analyse")),
            "provenance": {"source_type": "sensor-observed",
                           "human_verified": False},
            "match_type": "observation",
            "score": 0.0,
        })
    return summaries


def _recent_observations(limit: int = 5) -> list:
    """Latest stored observations across devices (metadata only)."""
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute(
            """SELECT record FROM camera_observations
            ORDER BY created_at DESC LIMIT ?""",
            (max(1, min(limit, 20)),)).fetchall()
    from .cameras import CameraObservation
    return [CameraObservation.model_validate(load(row["record"]))
            for row in rows]


@app.get("/api/v1/cameras/{device_id}/availability")
def camera_availability(device_id: str) -> dict:
    """Honest state of one camera: registered/detected/connected/
    capturable/unavailable. Never claims capturable without proof."""
    device = get_device(device_id)
    if device is None:
        raise HTTPException(404, "Camera not found")
    try:
        detected = bool(detect_local_imaging_devices().get("devices"))
    except Exception:
        detected = False
    try:
        return probe_availability(device, adapter_for(device_id),
                                  detected=detected)
    except IngestRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/cameras/{device_id}/ingest", status_code=201)
def camera_ingest(device_id: str) -> dict:
    """Capture + ingest one still: stored observation, media facts
    (hash/size, local only) and an INERT File payload for the BIG #5
    approval flow. No adapter (or a failing one) refuses."""
    device = get_device(device_id)
    if device is None:
        raise HTTPException(404, "Camera not found")
    adapter = adapter_for(device_id)
    test_origin = getattr(adapter, "name", "") in (
        "synthetic-test", "test-only")
    try:
        result = ingest_snapshot(device, adapter,
                                 test_origin=test_origin)
    except IngestRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except CameraUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error))
    save_observation(result.observation)
    logger.info("camera_ingested device_id=%s observation_id=%s",
                device_id, result.observation.observation_id)
    emit_event("observation.created",
               f"Observation {result.observation.observation_id} "
               f"via {device_id}",
               node_id=device_id)
    return result.model_dump(mode="json")


@app.get("/api/v1/observations/recent")
def observations_recent(limit: int = 5) -> list[dict]:
    """Latest observations, metadata only. No pixels leave the host."""
    return _observation_summaries(_recent_observations(limit))


@app.post("/api/v1/vision/analyze", status_code=201)
async def vision_analyze(body: VisionAnalyzeBody) -> dict:
    """Run the local VLM over one stored observation. The result is
    structured ADVICE (labels + confidences + description), stored
    beside the observation — never a fact, never verified."""
    observation = _observation_load(body.observation_id)
    if observation is None:
        raise HTTPException(404, "Observation not found")
    try:
        provider = get_vision_provider(body.provider)
    except VisionRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    request = VisionRequest(
        observation_id=observation.observation_id,
        device_id=observation.device_id,
        media_ref=observation.media_ref or "",
        question=body.question)
    if not request.media_ref:
        raise HTTPException(
            status_code=422,
            detail="Observation carries no local media; refusing")
    try:
        result = await provider.analyze(request)
    except VisionRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except VisionUnavailable as error:
        raise HTTPException(status_code=502, detail=str(error))
    record = VisionAnalysisRecord(
        analysis_id=result.analysis_id,
        observation_id=observation.observation_id,
        device_id=observation.device_id,
        result=result.model_dump(mode="json"),
        created_at=result.observed_at)
    try:
        save_analysis(record)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    logger.info("vision_analyzed observation_id=%s analysis_id=%s",
                observation.observation_id, result.analysis_id)
    return {"analysis": result.model_dump(mode="json"),
            "candidates": [{"label": label, "confidence": confidence}
                           for label, confidence in
                           identification_candidates(result)]}


@app.post("/api/v1/vision/propose", status_code=201)
def vision_propose(body: VisionProposeBody) -> dict:
    """One INERT inventory proposal from a stored vision analysis.
    kind=object (top candidate label) or kind=file (captured media).
    Nothing executes here; approval + BIG #5 write flow decide."""
    import secrets as _secrets
    analysis = load_analysis(body.analysis_id)
    if analysis is None:
        raise HTTPException(404, "Vision analysis not found")
    proposal_id = (body.proposal_id
                   or f"wrt-{_secrets.token_hex(4)}")
    try:
        if body.kind == "object":
            result = VisionResult.model_validate(analysis.result)
            observation = _observation_load(analysis.observation_id)
            if observation is None:
                raise HTTPException(
                    404, "Observation for this analysis not found")
            proposal = vision_to_object_proposal(
                result, observation, proposal_id=proposal_id)
        elif body.kind == "file":
            observation = _observation_load(analysis.observation_id)
            if observation is None or not observation.media_ref:
                raise HTTPException(
                    404, "Observation carries no local media")
            media = media_facts(observation.media_ref,
                                width=observation.width,
                                height=observation.height)
            payload = file_payload_for(
                media,
                f"{observation.device_id}-"
                f"{observation.observation_id}",
                observation.device_id)
            proposal = vision_to_file_proposal(
                payload, proposal_id=proposal_id)
        else:
            raise HTTPException(
                status_code=422,
                detail="kind must be 'object' or 'file'")
    except IngestRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except (InventoryWriteRefusedError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    _write_save(proposal, "proposed")
    logger.info("vision_proposed analysis_id=%s proposal_id=%s kind=%s",
                body.analysis_id, proposal_id, body.kind)
    return _write_to_json(_write_load(proposal.proposal_id))


@app.post("/api/v1/streams/start", status_code=201)
def stream_start(body: StreamStartBody) -> dict:
    """Start one bounded local-only stream session. Explicit stop
    required; budgets cap frames/seconds; expiry stops the rest."""
    device = get_device(body.device_id)
    if device is None:
        raise HTTPException(404, "Camera not found")
    try:
        session = _STREAMS.start(
            body.device_id, list(device.kinds),
            max_frames=body.max_frames, max_seconds=body.max_seconds)
    except IngestRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return session.model_dump(mode="json")


@app.post("/api/v1/streams/{session_id}/tick")
def stream_tick(session_id: str) -> dict:
    """Record one captured frame interval. Expired or stopped
    sessions refuse instead of running on."""
    try:
        session = _STREAMS.tick(session_id)
    except IngestRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return session.model_dump(mode="json")


@app.post("/api/v1/streams/{session_id}/stop")
def stream_stop(session_id: str) -> dict:
    try:
        session = _STREAMS.stop(session_id)
    except IngestRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return session.model_dump(mode="json")


@app.get("/api/v1/streams")
def streams_list() -> list[dict]:
    return [session.model_dump(mode="json")
            for session in _STREAMS.list()]


# =============================================================================
# FABRICATION — 3D + SLICING + PHYSICAL EXECUTION (BIG #7).
# Digital object to physical object through the same gates as
# everything else: proposal -> exact-YES approval (physical
# approval is a second, explicit YES) -> revalidated execution
# -> telemetry result -> observation -> two-half verification.
# No motion without the physical YES; telemetry never verifies
# the object; software cancel is documented as NOT e-stop.
# =============================================================================

def _fab_record_or_404(fabrication_id: str) -> FabricationRecord:
    record = load_fabrication(fabrication_id)
    if record is None:
        raise HTTPException(404, "Fabrication not found")
    return record


@app.post("/api/v1/fab/generate", status_code=201)
def fab_generate(body: FabGenerateBody) -> dict:
    """Bounded 3D generation: deterministic test geometry only,
    validated immediately, printability assessed, all recorded.
    The bytes are never valid/printable/safe by themselves."""
    try:
        fabrication = new_fabrication(
            source_object_id=body.source_object_id,
            source_idea_id=body.source_idea_id)
    except PrintRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        generator = get_generator(body.generator)
    except MeshRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        generated = generator.generate(body.description, {})
    except MeshUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error))
    report = validate_mesh(generated.artifact_ref)
    assessment = assess_printability(report)
    fabrication = fabrication.model_copy(update={
        "mesh_ref": generated.artifact_ref,
        "mesh_sha256": generated.sha256,
        "mesh_validation": report.verdict,
        "status": "mesh_validated" if report.verdict == "valid"
                  else "mesh_" + report.verdict})
    fabrication = record_event(
        fabrication, "generated",
        f"{generated.generator} -> {generated.artifact_ref} "
        f"({report.verdict}, {report.faces} faces)")
    save_fabrication(fabrication)
    logger.info("fab_generated fabrication_id=%s verdict=%s",
                fabrication.fabrication_id, report.verdict)
    return {"fabrication": fabrication.model_dump(mode="json"),
            "generation": generated.model_dump(mode="json"),
            "validation": report.model_dump(mode="json"),
            "printability": assessment.model_dump(mode="json")}


@app.post("/api/v1/fab/validate")
def fab_validate(artifact_ref: str) -> dict:
    """Validate one mesh artifact. No generation, no motion."""
    try:
        report = validate_mesh(artifact_ref)
    except (MeshRefusedError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return report.model_dump(mode="json")


@app.post("/api/v1/fab/assess")
def fab_assess(mesh_ref: str = "", description: str = "") -> dict:
    """Project-aware printability advice: inspect (mesh or idea),
    assess, propose the next step. Never prints, never slices."""
    if mesh_ref:
        try:
            report = validate_mesh(mesh_ref)
        except (MeshRefusedError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error))
        assessment = assess_printability(report)
        next_step = ("slice with an allow-listed profile, then "
                     "safety assessment, then physical proposal"
                     if assessment.verdict == "printable"
                     else "fix the mesh concerns first; no slicing")
        return {"assessment": assessment.model_dump(mode="json"),
                "validation": report.model_dump(mode="json"),
                "next_step": next_step}
    if not description.strip():
        raise HTTPException(
            status_code=422,
            detail="Assess needs a mesh_ref or a description")
    return {"assessment": None, "validation": None,
            "next_step": ("no mesh yet: generate test geometry via "
                          "/api/v1/fab/generate, validate it, then "
                          "assess again")}


@app.post("/api/v1/fab/slice", status_code=201)
def fab_slice(body: FabSliceBody) -> dict:
    """Bounded slicing run: test slicer or explicit unavailable,
    G-code validated for safety immediately. The artifact is
    never production G-code unless a reviewed runtime made it."""
    try:
        request = check_slicer_request(
            body.artifact_ref, body.profile, body.printer_id)
    except (SlicerRefusedError, MeshRefusedError,
            ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        slicer = get_slicer(body.slicer)
    except SlicerRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        result = slicer.slice(request)
    except SlicerUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error))
    safety = validate_gcode(result.gcode_ref)
    logger.info("fab_sliced gcode=%s safety=%s", result.gcode_ref,
                safety.verdict)
    return {"slice": result.model_dump(mode="json"),
            "safety": safety.model_dump(mode="json")}


@app.post("/api/v1/printers/register", status_code=201)
def printer_register(body: PrinterRegisterBody) -> dict:
    """Register one printer device. Execution authority, no motion:
    capabilities are allow-listed, the INVENTory twin is an
    optional hw_ link, and no adapter means unavailable."""
    import secrets as _secrets
    printer_id = (body.printer_id or f"prt-{_secrets.token_hex(4)}")
    try:
        device = new_printer(
            printer_id, body.name, list(body.capabilities),
            inventory_hardware_id=body.inventory_hardware_id,
            notes=body.notes)
    except PrinterDeviceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    save_printer(device)
    logger.info("printer_registered printer_id=%s caps=%s",
                printer_id, ",".join(device.capabilities))
    return device.model_dump(mode="json")


@app.get("/api/v1/printers")
def printers_list() -> list[dict]:
    return [device.model_dump(mode="json")
            for device in list_stored_printers()]


@app.get("/api/v1/printers/{printer_id}")
def printer_get(printer_id: str) -> dict:
    device = load_printer(printer_id)
    if device is None:
        raise HTTPException(404, "Printer not found")
    adapter = adapter_for_printer(printer_id)
    return {**device.model_dump(mode="json"),
            "adapter": getattr(adapter, "name", None),
            "adapter_capabilities": (
                printer_capabilities(adapter)
                if adapter is not None else []),
            "estop_note": ("software cancel/stop is a state "
                            "transition only, not a physical "
                            "emergency stop")}


@app.post("/api/v1/prints/propose", status_code=201)
def print_propose(body: PrintProposeBody) -> dict:
    """One INERT physical-execution proposal. Requires a recorded
    safety assessment that is not unsafe; mission/plan approval
    never substitutes for the exact YES on this proposal."""
    import secrets as _secrets
    import hashlib as _hashlib
    device = load_printer(body.printer_id)
    if device is None:
        raise HTTPException(404, "Printer not found")
    try:
        reference = check_artifact_ref(body.gcode_ref)
    except (MeshRefusedError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        data = read_artifact_bytes(reference)
    except (MeshRefusedError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    if _hashlib.sha256(data).hexdigest() != body.gcode_sha256.lower():
        raise HTTPException(
            status_code=422,
            detail="gcode_sha256 does not match the stored artifact; "
                   "refusing")
    safety = validate_gcode(reference)
    job_id = body.job_id or f"pjob-{_secrets.token_hex(4)}"
    try:
        from .slicer3d import check_profile
        check_profile(body.profile)
        job = new_job(job_id, body.printer_id, reference,
                      body.gcode_sha256.lower(), body.profile,
                      body.actor)
        proposal = propose_print(
            body.proposal_id or f"wrt-{_secrets.token_hex(4)}",
            job, safety_verdict=safety.verdict, actor=body.actor)
    except (PrintRefusedError, PrinterDeviceRefusedError,
            SlicerRefusedError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    _write_save(proposal, "proposed")
    logger.info("print_proposed proposal_id=%s job_id=%s safety=%s",
                proposal.proposal_id, job_id, safety.verdict)
    return {**_write_to_json(_write_load(proposal.proposal_id)),
            "safety": safety.model_dump(mode="json")}


@app.post("/api/v1/prints/cancel")
def print_cancel(body: PrintCancelBody) -> dict:
    """Cancel a print job: adapter-level cancel where possible,
    plus proposal withdrawal before execution. Software cancel is
    a state transition, never a physical emergency stop."""
    found = None
    for printer in list_stored_printers():
        adapter = adapter_for_printer(printer.printer_id)
        if adapter is None or not hasattr(adapter,
                                           "request_cancel"):
            continue
        try:
            adapter.request_cancel(body.job_id)
            found = printer.printer_id
        except (PrinterUnavailable, ValueError):
            continue
    return {"job_id": body.job_id, "cancel_requested": found,
            "cancelled_at_adapter": found,
            "estop_note": ("software cancel is not a physical "
                            "emergency stop")}


@app.post("/api/v1/writes/{proposal_id}/verify-print")
async def write_verify_print(proposal_id: str,
                             observation_id: str = "") -> dict:
    """Combined print verification: telemetry half (bound G-code
    completed) AND camera half (observation confirms the object).
    Verified only if BOTH halves pass; needs an observation id."""
    record = _write_load(proposal_id)
    if record is None:
        raise HTTPException(404, "Write proposal not found")
    if not record["result"]:
        raise HTTPException(
            status_code=409, detail="Write has no result yet; execute first")
    if not observation_id:
        raise HTTPException(
            status_code=422,
            detail="Print verification needs an observation_id")
    proposal = WriteProposal.model_validate(record["record"])
    result = WriteResult.model_validate(record["result"])
    if proposal.mutation_type != "printer.execute":
        raise HTTPException(
            status_code=422,
            detail="Print verification needs a printer.execute result")
    observation = _observation_load(observation_id)
    if observation is None:
        raise HTTPException(404, "Observation not found")
    try:
        telemetry_request = _verification_request_for(proposal,
                                                      result)
        telemetry = verify_print_telemetry(telemetry_request,
                                           result)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    import os as _os
    from .cameras import camera_dir
    media_ok = bool(
        observation.media_ref
        and _os.path.isfile(_os.path.join(
            camera_dir(), observation.media_ref)))
    camera_request = VerificationRequest(
        verification_id=telemetry_request.verification_id,
        proposal_id=proposal.proposal_id,
        result_fingerprint=result.fingerprint,
        method="print.camera_readback",
        expected={"kind": "print-observation",
                  "observation_id": observation.observation_id,
                  "device_id": observation.device_id,
                  "media_ref": observation.media_ref,
                  "media_exists": media_ok})
    camera = verify_print_camera(camera_request, observation)
    verdict = print_verdict(telemetry, camera)
    combined = camera.model_copy(update={
        "method": "print.camera_readback",
        "observed": {"telemetry": telemetry.model_dump(mode="json"),
                     "camera": camera.model_dump(mode="json"),
                     "verdict": verdict},
        "outcome": ("passed" if verdict == "verified" else
                    camera.outcome
                    if camera.outcome in ("failed", "inconclusive")
                    else "failed"),
        "note": (f"telemetry={telemetry.outcome}, "
                 f"camera={camera.outcome}; final: {verdict}"),
    })
    approval = WriteApproval.model_validate(record["approval"])
    _write_save(proposal, record["status"], approval=approval,
                result=result, verification=combined)
    logger.info("print_verified proposal_id=%s verdict=%s",
                proposal_id, verdict)
    return _write_to_json(_write_load(proposal_id))


@app.get("/api/v1/fabrication/records")
def fabrication_records(limit: int = 20) -> list[dict]:
    return [record.model_dump(mode="json")
            for record in list_fabrications(limit)]


def _fabrication_overlay(fabrication_id: str) -> list[dict]:
    """Project one fabrication chain as graph overlay nodes."""
    record = load_fabrication(fabrication_id)
    if record is None:
        raise ValueError(
            f"Fabrication '{fabrication_id}' not found")
    data = record.model_dump(mode="json")
    nodes: list[dict] = []
    if data.get("mesh_sha256"):
        nodes.append({"id": f"mesh:{data['fabrication_id']}",
                      "kind": "artifact",
                      "label": f"mesh {data.get('mesh_ref', '?')}",
                      "status": data.get("mesh_validation", ""),
                      "sha256": data["mesh_sha256"],
                      "links": ([{"predicate": "derived_from",
                                  "to": data["source_object_id"]}]
                                if data.get("source_object_id") else [])})
    if data.get("gcode_sha256"):
        nodes.append({"id": f"gcode:{data['fabrication_id']}",
                      "kind": "artifact",
                      "label": f"gcode {data.get('gcode_ref', '?')}",
                      "status": data.get("gcode_safety", ""),
                      "sha256": data["gcode_sha256"],
                      "links": [{"predicate": "sliced_to",
                                 "to": f"mesh:{data['fabrication_id']}"}]})
    if data.get("job_id"):
        job_links = (([{"predicate": "executed_as",
                        "to": f"gcode:{data['fabrication_id']}"}]
                      if data.get("gcode_sha256") else [])
                     + ([{"predicate": "observed_by",
                          "to": data["observation_id"]}]
                        if data.get("observation_id") else []))
        nodes.append({"id": f"job:{data['job_id']}",
                      "kind": "print_job",
                      "label": f"print {data['job_id']}",
                      "status": data.get("status", ""),
                      "links": job_links})
    if data.get("observation_id"):
        nodes.append({"id": data["observation_id"],
                      "kind": "observation",
                      "label": f"observatie {data['observation_id']}",
                      "status": "",
                      "links": []})
    return nodes


# =============================================================================
# HUMAN INTERFACE — VOICE, PHONE NODES, EVENTS (BIG #9).
# The interface is never a second coordinator: adapters carry
# structured turns, STT/TTS render locally, events inform but
# never authorize, and every decision still flows through chat,
# proposals, approvals, routing and verification. Voice
# recognition is not authorization; notifications are not
# commands; sessions are presence, not credentials.
# =============================================================================

def emit_event(event_type: str, summary: str = "", **fields) -> None:
    """Best-effort bus event. Event failures never break flows."""
    try:
        save_bus_event(bus_event(event_type, summary, **fields))
    except (EventRefusedError, ValueError):
        pass


def _usable_session_or_none(session_id: str):
    if not session_id:
        return None
    try:
        session = load_session(session_id)
    except ValueError:
        return None
    if session is None:
        return None
    touched = touch_session(session)
    if touched is not session:
        try:
            save_session(touched)
        except ValueError:
            pass
    return touched if session_usable(touched) else None


@app.post("/api/v1/interface/sessions", status_code=201)
def interface_session_open(body: SessionOpenBody) -> dict:
    """Open one interface session (presence only). Never a
    credential, never node identity."""
    try:
        session = new_session(body.interface_id,
                              node_id=body.node_id,
                              conversation_id=body.conversation_id,
                              ttl_seconds=body.ttl_seconds)
    except InterfaceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        save_session(session)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return session.model_dump(mode="json")


@app.get("/api/v1/interface/sessions")
def interface_sessions(interface_id: str = "") -> list[dict]:
    try:
        sessions = list_sessions(interface_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return [session.model_dump(mode="json") for session in sessions]


@app.post("/api/v1/interface/sessions/{session_id}/touch")
def interface_session_touch(session_id: str) -> dict:
    session = load_session(session_id)
    if session is None:
        raise HTTPException(404, "Session not found")
    touched = touch_session(session)
    try:
        save_session(touched)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return touched.model_dump(mode="json")


@app.post("/api/v1/interface/sessions/{session_id}/revoke")
def interface_session_revoke(session_id: str) -> dict:
    session = load_session(session_id)
    if session is None:
        raise HTTPException(404, "Session not found")
    revoked = revoke_session(session)
    save_session(revoked)
    return revoked.model_dump(mode="json")


@app.post("/api/v1/interface/chat")
async def interface_chat(body: InterfaceChatBody) -> dict:
    """One interface turn converging into the chat flow. Text and
    voice arrive here identically; the coordinator cannot tell
    them apart beyond provenance."""
    from .interface import VALID_INPUT_TYPES as _VALID_INPUT
    if body.input_type not in _VALID_INPUT:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown input type '{body.input_type}'")
    session = None
    if body.session_id:
        session = _usable_session_or_none(body.session_id)
        if session is None:
            raise HTTPException(
                status_code=409,
                detail="Session unknown, expired or revoked")
    try:
        envelope = new_interface_message(
            __import__("secrets").token_hex(4),
            body.conversation_id or
            generate_conversation_id(),
            "user", body.content,
            session_id=body.session_id,
            input_type=body.input_type)
    except InterfaceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    answer = await chat(ChatRequest(
        conversation_id=envelope.conversation_id,
        message=body.content,
        observation_ids=list(body.observation_ids),
        input_type=body.input_type))
    if session is not None:
        touched = touch_session(session)
        try:
            save_session(touched)
        except ValueError:
            pass
    adapter = VoiceInterface() if body.input_type == "voice" \
        else TextInterface()
    return {"chat": answer.model_dump(mode="json"),
            "interface": adapter.send_response(
                new_interface_message(
                    answer.message_id, answer.conversation_id,
                    "assistant", answer.reply,
                    session_id=body.session_id,
                    input_type=body.input_type,
                    output_type=("voice" if body.input_type ==
                                 "voice" else "text")))}


@app.post("/api/v1/voice/transcribe", status_code=201)
async def voice_transcribe(body: VoiceTranscribeBody) -> dict:
    """Transcribe one local audio file. Interpretation input only:
    the text that comes back is never FACT and never a gate."""
    try:
        provider = get_stt_provider(body.provider)
    except VoiceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        result = await provider.transcribe(body.audio_ref)
    except VoiceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except VoiceUnavailable as error:
        raise HTTPException(status_code=502, detail=str(error))
    emit_event("voice.transcribed",
               f"Transcription {result.transcript_id} "
               f"({result.provider})",
               node_id="")
    return result.model_dump(mode="json")


@app.post("/api/v1/voice/synthesize", status_code=201)
async def voice_synthesize(body: VoiceSynthesizeBody) -> dict:
    """Render coordinator text to local audio. Rendering only:
    authorization semantics unchanged."""
    try:
        provider = get_tts_provider(body.provider)
    except VoiceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        result = await provider.synthesize(body.text)
    except VoiceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except VoiceUnavailable as error:
        raise HTTPException(status_code=502, detail=str(error))
    return result.model_dump(mode="json")


@app.post("/api/v1/voice/chat")
async def voice_chat(body: VoiceChatBody) -> dict:
    """Voice turn end to end: audio -> STT -> conversation ->
    advice/task -> response (+ optional spoken rendering). Typed
    and voice commands converge in chat(); no voice-specific
    task pipeline exists."""
    text = (body.transcript or "").strip()
    if body.audio_ref:
        try:
            provider = get_stt_provider(body.provider)
        except VoiceRefusedError as error:
            raise HTTPException(status_code=422, detail=str(error))
        try:
            transcription = await provider.transcribe(
                body.audio_ref)
        except VoiceRefusedError as error:
            raise HTTPException(status_code=422, detail=str(error))
        except VoiceUnavailable as error:
            raise HTTPException(status_code=502, detail=str(error))
        emit_event("voice.transcribed",
                   f"Transcription {transcription.transcript_id} "
                   f"for voice chat")
        if not text:
            text = transcription.text
    if not text:
        raise HTTPException(
            status_code=422,
            detail="Voice chat needs transcript text or audio")
    session = None
    if body.session_id:
        session = _usable_session_or_none(body.session_id)
        if session is None:
            raise HTTPException(
                status_code=409,
                detail="Session unknown, expired or revoked")
    answer = await chat(ChatRequest(
        conversation_id=body.conversation_id,
        message=text[:4000], input_type="voice"))
    spoken = None
    if body.speak:
        try:
            tts = get_tts_provider(body.provider)
        except VoiceRefusedError as error:
            raise HTTPException(status_code=422, detail=str(error))
        try:
            spoken = (await tts.synthesize(
                answer.reply)).model_dump(mode="json")
        except VoiceRefusedError as error:
            raise HTTPException(status_code=422, detail=str(error))
        except VoiceUnavailable as error:
            raise HTTPException(status_code=502, detail=str(error))
    if session is not None:
        try:
            save_session(touch_session(session))
        except ValueError:
            pass
    return {"chat": answer.model_dump(mode="json"),
            "spoken": spoken}


@app.post("/api/v1/voice/capture/open", status_code=201)
def voice_capture_open(body: CaptureOpenBody) -> dict:
    """Open one explicit microphone window on a node that
    advertises phone.microphone.read. Recording starts only
    here — never in the background, never silently."""
    with connection() as db:
        row = db.execute(
            "SELECT capabilities FROM nodes WHERE node_id=?",
            (body.node_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Node is not registered")
    try:
        advertised = {str(cap).strip().lower()
                      for cap in load(row["capabilities"])}
    except ValueError:
        advertised = set()
    if "phone.microphone.read" not in advertised:
        raise HTTPException(
            status_code=422,
            detail="Node does not advertise phone.microphone.read; "
                   "no capture without the explicit capability")
    try:
        session = open_capture_session(body.node_id,
                                       body.max_seconds)
    except VoiceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return session.model_dump(mode="json")


@app.post("/api/v1/voice/capture/close")
def voice_capture_close(body: CaptureCloseBody) -> dict:
    try:
        session = close_capture_session(body.session_id,
                                        body.audio_ref)
    except VoiceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return session.model_dump(mode="json")


@app.delete("/api/v1/voice/audio/{audio_ref}")
def voice_audio_delete(audio_ref: str) -> dict:
    """Explicit audio expiry. Missing files report removed=False."""
    try:
        removed = delete_audio(audio_ref)
    except VoiceRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"audio_ref": audio_ref, "removed": removed}


@app.get("/api/v1/events")
def events_poll(after: str = "", limit: int = 50,
                type: str = "") -> list[dict]:
    """Bounded pollable event feed with cursor replay. Events
    inform; they never authorize."""
    from .events import list_events as _list_events
    try:
        found = _list_events(limit=limit, after=after,
                             event_type=type)
    except EventRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return [event.model_dump(mode="json") for event in found]


@app.post("/api/v1/notifications", status_code=201)
def notification_create(body: NotifyBody) -> dict:
    """Create one informational notification. Reading it performs
    nothing; approvals still need the approval mechanism."""
    with connection() as db:
        row = db.execute("SELECT node_id FROM nodes WHERE node_id=?",
                         (body.recipient_node_id,)).fetchone()
    if row is None:
        raise HTTPException(
            404, "Recipient node is not registered")
    try:
        notification = new_notification(
            body.recipient_node_id, body.type, body.title,
            body.body, severity=body.severity,
            related_entity=body.related_entity,
            related_mission=body.related_mission,
            related_task=body.related_task)
    except EventRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        save_notification(notification)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return notification.model_dump(mode="json")


@app.get("/api/v1/notifications")
def notifications_list(node_id: str, limit: int = 50,
                       unread_only: bool = False) -> list[dict]:
    try:
        found = list_notifications(node_id, limit=limit,
                                   unread_only=unread_only)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return [item.model_dump(mode="json") for item in found]


@app.post("/api/v1/notifications/{notification_id}/read")
def notification_read(notification_id: str,
                      node_id: str) -> dict:
    if not mark_notification_read(notification_id, node_id):
        raise HTTPException(404, "Notification not found")
    return {"notification_id": notification_id, "read": True}


@app.get("/api/v1/status")
def coordinator_status() -> dict:
    """Bounded coordinator summary for interfaces. Counts and
    states only: no secrets, no dumps, no filesystem paths."""
    with connection() as db:
        node_rows = db.execute(
            "SELECT status, last_seen FROM nodes").fetchall()
        task_rows = db.execute(
            "SELECT status FROM tasks").fetchall()
    online = 0
    stale = 0
    for row in node_rows:
        derived = derive_status(row["status"], row["last_seen"])
        if derived in ("online", "busy"):
            online += 1
        elif derived == "stale":
            stale += 1
    by_status: dict[str, int] = {}
    for row in task_rows:
        key = str(row["status"])
        by_status[key] = by_status.get(key, 0) + 1
    init_chat_database()
    with chat_connection() as db:
        missions = db.execute(
            "SELECT status, COUNT(*) AS n FROM missions "
            "GROUP BY status").fetchall()
        pending_actions = db.execute(
            "SELECT COUNT(*) AS n FROM desktop_actions WHERE "
            "status='pending_approval'").fetchone()["n"]
        proposed_writes = db.execute(
            "SELECT COUNT(*) AS n FROM write_proposals WHERE "
            "status='proposed'").fetchone()["n"]
        pending_missions = db.execute(
            "SELECT COUNT(*) AS n FROM missions WHERE "
            "status='pending_approval'").fetchone()["n"]
    return {
        "coordinator": "online",
        "nodes": {"total": len(node_rows), "online": online,
                  "stale": stale},
        "tasks": by_status,
        "missions": {str(row["status"]): row["n"]
                     for row in missions},
        "pending_approvals": {
            "desktop_actions": pending_actions,
            "write_proposals": proposed_writes,
            "missions": pending_missions,
        },
    }


@app.post("/api/v1/voice/approval-requests", status_code=201)
def voice_approval_open(body: VoiceApprovalRequestBody) -> dict:
    """Open one voice-approval request against a still-pending
    target. Refuses when another voice request is already
    pending (ambiguity never approves) and for physical kinds
    (voice never satisfies physical approval)."""
    import secrets as _secrets
    if body.kind not in VOICE_APPROVABLE_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"kind '{body.kind}' never resolves by voice")
    if pending_voice_requests():
        raise HTTPException(
            status_code=409,
            detail="another voice approval is already pending; "
                   "resolve it first")
    fingerprint = ""
    if body.kind == "write":
        record = _write_load(body.target_id)
        if record is None:
            raise HTTPException(404, "Write proposal not found")
        if record["status"] != "proposed":
            raise HTTPException(
                status_code=409,
                detail="Write proposal is not pending")
        proposal = WriteProposal.model_validate(record["record"])
        if proposal.mutation_type in ("printer.execute",
                                      "robot.execute",
                                      "drone.mission"):
            raise HTTPException(
                status_code=422,
                detail=f"mutation '{proposal.mutation_type}' "
                       "never resolves by voice; physical "
                       "approval stays on its explicit channel")
        from .controlled_writes import write_fingerprint as _fp
        fingerprint = _fp(proposal)
        if body.fingerprint and body.fingerprint != fingerprint:
            raise HTTPException(
                status_code=422,
                detail="Fingerprint does not match the proposal")
    elif body.kind == "mission":
        mission = load_mission(body.target_id)
        if mission is None:
            raise HTTPException(404, "Mission not found")
        if mission.status != "pending_approval":
            raise HTTPException(
                status_code=409,
                detail="Mission is not pending approval")
    elif body.kind == "desktop":
        try:
            record = _desktop_load(body.target_id)
        except HTTPException:
            raise HTTPException(404, "Desktop action not found")
        if record.status != "pending_approval":
            raise HTTPException(
                status_code=409,
                detail="Desktop action is not pending approval")
    else:  # pragma: no cover - kind gate above
        raise HTTPException(status_code=422, detail="unknown kind")
    from datetime import timedelta as _delta
    created = now()
    request = VoiceApprovalRequest(
        approval_id=f"vapr-{_secrets.token_hex(4)}",
        kind=body.kind, target_id=body.target_id,
        fingerprint=fingerprint,
        summary=body.summary or f"{body.kind} {body.target_id}",
        created_at=created, expires_at=(
            _parse_time(created) + _delta(
                seconds=body.ttl_seconds)).isoformat())
    save_voice_request(request)
    emit_event("approval.required",
               f"Voice approval requested for {body.kind} "
               f"{body.target_id}",
               proposal_id=(body.target_id if body.kind == "write"
                            else ""),
               mission_id=(body.target_id if body.kind == "mission"
                           else ""))
    return request.model_dump(mode="json")


@app.post("/api/v1/voice/approve")
def voice_approve(body: VoiceApproveBody) -> dict:
    """Resolve one spoken answer. Exactly one pending request,
    unexpired, target still pending with unchanged binding,
    allowed word — otherwise refusal. Physical kinds cannot
    reach this path. On YES the EXISTING decide path runs."""
    stored = load_voice_request(body.approval_id)
    if stored is None:
        raise HTTPException(404, "Voice approval not found")
    if stored.status != "pending":
        raise HTTPException(
            status_code=409, detail="Voice approval not pending")
    others = [request for request in pending_voice_requests()
              if request.approval_id != stored.approval_id]
    if others:
        raise HTTPException(
            status_code=409,
            detail="competing approval requests; refusing")
    target_ok = _voice_target_ok(stored)
    try:
        outcome = resolve_voice_approval(
            [stored], body.transcript, kind=stored.kind,
            target_ok=target_ok)
    except VoiceApprovalRefusedError as error:
        if not error.retryable:
            mark_voice_resolved(stored.approval_id, "rejected")
        raise HTTPException(status_code=422, detail=str(error))
    if not outcome["approved"]:
        mark_voice_resolved(stored.approval_id, "rejected")
        emit_event("approval.resolved",
                   f"Voice approval {stored.approval_id} declined",
                   proposal_id=(stored.target_id
                                if stored.kind == "write" else ""))
        return outcome
    try:
        _voice_execute_decide(stored)
    except (ValueError, HTTPException) as error:
        mark_voice_resolved(stored.approval_id, "rejected")
        detail = (error.detail if isinstance(error, HTTPException)
                  else str(error))
        raise HTTPException(status_code=422, detail=detail)
    mark_voice_resolved(stored.approval_id, "resolved")
    emit_event("approval.resolved",
               f"Voice approval {stored.approval_id} granted via "
               f"existing {stored.kind} gate",
               proposal_id=(stored.target_id
                            if stored.kind == "write" else ""),
               mission_id=(stored.target_id
                           if stored.kind == "mission" else ""))
    return outcome


def _voice_target_ok(stored: VoiceApprovalRequest) -> bool:
    """Recheck the target live: still pending, binding unchanged."""
    if stored.kind == "write":
        record = _write_load(stored.target_id)
        if record is None or record["status"] != "proposed":
            return False
        from .controlled_writes import write_fingerprint as _fp
        try:
            current = _fp(
                WriteProposal.model_validate(record["record"]))
        except ValueError:
            return False
        return current == stored.fingerprint
    if stored.kind == "mission":
        mission = load_mission(stored.target_id)
        return mission is not None and \
            mission.status == "pending_approval"
    if stored.kind == "desktop":
        try:
            record = _desktop_load(stored.target_id)
        except HTTPException:
            return False
        return record.status == "pending_approval"
    return False


def _voice_execute_decide(stored: VoiceApprovalRequest) -> None:
    """Run the EXISTING decide path for a voice-approved request."""
    if stored.kind == "write":
        record = _write_load(stored.target_id)
        proposal = WriteProposal.model_validate(record["record"])
        approval = decide_write(
            request_write_approval(proposal), proposal, "YES",
            decided_by=f"voice:{stored.approval_id}")
        _write_save(proposal, "approved", approval=approval)
    elif stored.kind == "mission":
        _executor().approve(stored.target_id, "YES",
                            decided_by=f"voice:{stored.approval_id}")
    elif stored.kind == "desktop":
        desktop_decide(stored.target_id,
                       DesktopDecisionBody(response="YES",
                                           decided_by="voice:"
                                           f"{stored.approval_id}"))
    else:  # pragma: no cover - kind gate at open time
        raise VoiceApprovalRefusedError("unknown kind")


@app.post("/api/v1/phone/{node_id}/camera", status_code=201)
def phone_camera_register(node_id: str,
                          body: PhoneCameraBody) -> dict:
    """Register a phone-owned camera device. Explicit only: the
    node must advertise phone.camera.snapshot, capture still
    runs through the existing ingest path with its own gates."""
    with connection() as db:
        row = db.execute(
            "SELECT capabilities FROM nodes WHERE node_id=?",
            (node_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Node is not registered")
    try:
        advertised = {str(cap).strip().lower()
                      for cap in load(row["capabilities"])}
    except ValueError:
        advertised = set()
    if "phone.camera.snapshot" not in advertised:
        raise HTTPException(
            status_code=422,
            detail="Node does not advertise phone.camera.snapshot")
    import secrets as _secrets
    try:
        device = new_device(f"cam-{_secrets.token_hex(4)}",
                            body.name,
                            list(body.kinds), "phone",
                            notes=f"phone-owned by {node_id}; no "
                                  "background capture, explicit "
                                  "ingest only")
    except CameraRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    save_device(device)
    emit_event("observation.created",
               f"Phone camera {device.device_id} registered "
               f"for {node_id}",
               node_id=node_id)
    return device.model_dump(mode="json")


# =============================================================================
# DISTRIBUTED STATE + FAILOVER + SYNC + LIVE + WORKSHOP (BIG #10).
# Event-log sync (never DB copies), epoch/fencing election,
# capability-scoped Live sessions, uniform graph overlays,
# interactive workshop UI. No Raft, no brokers, no cloud.
# =============================================================================

def _election_nodes() -> list[dict]:
    """Nodes projected for election: identity, capability flag,
    status, freshness. Never credentials."""
    with connection() as db:
        rows = db.execute(
            "SELECT node_id, status, last_seen, "
            "coordinator_capable FROM nodes").fetchall()
    return [{
        "node_id": row["node_id"],
        "status": row["status"],
        "last_seen": row["last_seen"],
        "coordinator_capable": bool(row["coordinator_capable"]),
    } for row in rows]


@app.post("/api/v1/coordinator/campaign")
def coordinator_campaign(body: CampaignBody) -> dict:
    """Seek or renew the coordinator lease. Deterministic order,
    quorum or explicit degraded mode; a live foreign holder
    refuses. Only token-bound identities may campaign: legacy
    nodes bind a token through operator rotation first.
    Fail-closed on every doubt."""
    with connection() as db:
        row = db.execute(
            "SELECT auth_token_hash FROM nodes WHERE node_id=?",
            (body.node_id,)).fetchone()
    if row is None or not row["auth_token_hash"]:
        raise HTTPException(
            status_code=409,
            detail="campaigning needs a token-bound identity; "
                   "bind a token through operator rotation first")
    try:
        result = failover_campaign(body.node_id, _election_nodes)
    except ElectionRefusedError as error:
        raise HTTPException(status_code=409, detail=str(error))
    emit_event("coordinator.epoch",
               f"Coordinator epoch {result['epoch']} "
               f"({result['mode']}) held by {result['node_id']}",
               node_id=result["node_id"])
    return result


@app.post("/api/v1/coordinator/release")
def coordinator_release(body: CampaignBody) -> dict:
    released = failover_release(body.node_id)
    return {"node_id": body.node_id, "released": released}


@app.get("/api/v1/coordinator/status")
def coordinator_election_status() -> dict:
    """Election snapshot: epoch, holder, expiry, voters, mode."""
    return failover_status(_election_nodes())


@app.get("/api/v1/sync/changes")
def sync_changes(after: int = 0, limit: int = 100) -> dict:
    """Bounded pull page over the durable log. No dumps."""
    try:
        items, latest = read_log(after_rowid=after, limit=limit)
    except DistStateRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"items": items, "latest": latest}


@app.post("/api/v1/sync/apply")
def sync_apply(body: SyncApplyBody) -> dict:
    """Validate + idempotently apply pulled envelopes. Duplicates
    acknowledge without mutation; conflicts record explicitly."""
    try:
        envelopes = [DistEnvelopeBody.model_validate(item)
                     for item in body.items]
    except Exception as error:
        raise HTTPException(status_code=422, detail=str(error))
    from .diststate import DistEnvelope as _Envelope
    summary = apply_pulled([
        _Envelope.model_validate(item.model_dump(mode="json"))
        for item in envelopes])
    return summary


@app.get("/api/v1/sync/status")
def sync_status(cursor: int = 0) -> dict:
    """Local sync snapshot: cursor, log size, conflicts, epoch."""
    with connection() as db:
        nodes = db.execute(
            "SELECT status, last_seen FROM nodes").fetchall()
    return dist_sync_status(
        [{"status": row["status"], "last_seen": row["last_seen"],
          "derived_status": derive_status(
              row["status"], row["last_seen"])}
         for row in nodes],
        cursor=cursor)


@app.get("/api/v1/inventory/changes")
async def inventory_changes(since: str = "",
                            limit: int = 100) -> dict:
    """INVENTory change feed over HTTP (cursor + bounded page).
    The SQLite file is never copied and never opened."""
    try:
        items = await fetch_inventory_changes(
            _world_reader(), since=since, limit=limit)
    except InventoryRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except InventoryUnavailable:
        raise HTTPException(status_code=502,
                            detail="INVENTory unavailable")
    return {"items": items}


@app.get("/api/v1/dist/conflicts")
def dist_conflicts(status: str = "") -> list[dict]:
    try:
        found = list_conflicts(status=status)
    except DistStateRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return [item.model_dump(mode="json") for item in found]


@app.post("/api/v1/dist/conflicts/{conflict_id}/resolve")
def dist_conflict_resolve(conflict_id: str) -> dict:
    try:
        resolved = resolve_conflict(conflict_id, "resolved")
    except DistStateRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    if not resolved:
        raise HTTPException(404, "Conflict not found or not open")
    return {"conflict_id": conflict_id, "status": "resolved"}


def _live_session_or_403(session_id: str):
    from .live import load_live_session as _load
    session = _load(session_id)
    if session is None:
        raise HTTPException(404, "Live session not found")
    if not session_live(session):
        raise HTTPException(status_code=403,
                            detail="Live session expired or revoked")
    return session


@app.post("/api/v1/live/sessions", status_code=201)
def live_session_open(body: LiveSessionBody) -> dict:
    """Open one capability-scoped Live session. Least privilege:
    only listed capabilities; git.push is never granted."""
    from .live import open_session as _open
    try:
        session = _open(body.interface, body.actor,
                        list(body.capabilities),
                        context_scope=dict(body.context_scope),
                        ttl_seconds=body.ttl_seconds)
    except LiveRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        save_live_session(session)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return session.model_dump(mode="json")


@app.get("/api/v1/live/sessions/{session_id}")
def live_session_get(session_id: str) -> dict:
    return _live_session_or_403(session_id).model_dump(mode="json")


@app.post("/api/v1/live/sessions/{session_id}/revoke")
def live_session_revoke(session_id: str) -> dict:
    if not revoke_live_session(session_id):
        raise HTTPException(404, "Live session not found")
    return {"session_id": session_id, "active": False}


@app.post("/api/v1/live/context")
async def live_context(body: LiveContextBody) -> dict:
    """Pack a bounded context package for one live session.
    Each section passes through its capability gate and the
    existing readers; file contents, secrets and absolute
    paths are stripped."""
    session = _live_session_or_403(body.session_id)
    scope = dict(session.context_scope or {})
    if body.entity_id:
        scope["entity_id"] = body.entity_id
    sources: dict = {}
    if live_can(session, "project.read"):
        try:
            sources["project"] = default_context().model_dump(
                mode="json")
        except ValueError:
            pass
    if live_can(session, "inventory.read") and scope.get(
            "entity_id"):
        try:
            record = await _world_reader().get(
                scope.get("entity_type", "object") or "object",
                scope["entity_id"])
            if record is not None:
                sources["object"] = record.model_dump(mode="json")
        except (InventoryRefusedError, InventoryUnavailable,
                ValueError):
            pass
    if live_can(session, "mission.read") and scope.get(
            "mission_id"):
        mission = load_mission(scope["mission_id"])
        if mission is not None:
            sources["mission"] = {
                "mission_id": mission.mission_id,
                "goal": mission.goal, "status": mission.status}
    if live_can(session, "camera.read") and scope.get(
            "include_observations", True):
        sources["observations"] = [
            obs.model_dump(mode="json")
            for obs in _recent_observations(5)]
    if live_can(session, "graph.read") and scope.get("entity_id"):
        try:
            graph = await _world_reader().graph(
                scope["entity_id"], 1)
            sources["relationships"] = [
                {"from_id": edge.from_id,
                 "predicate": edge.predicate,
                 "to_id": edge.to_id}
                for edge in graph.edges[:20]]
        except (InventoryRefusedError, InventoryUnavailable,
                ValueError):
            pass
    if live_can(session, "task.read"):
        sources["tasks"] = [{
            "id": item["id"], "kind": item.get("kind", ""),
            "status": item.get("status", "")}
            for item in list_tasks()[:20]]
    if live_can(session, "node.read"):
        sources["nodes"] = list_nodes()[:20]
    if live_can(session, "git.read") and scope.get("include_git"):
        try:
            root = _project_root(None)
            branch = git_branch(root)["branch"]
            sources["git"] = {"branch": branch}
        except (GitRefusedError, GitUnavailable, ValueError):
            pass
    if live_can(session, "memory.read"):
        try:
            from .memory import retrieve_memories as _recall
            sources["memory"] = _recall(
                body.query, project_ref=str(
                    scope.get("project_id", "") or ""),
                limit=8, include_health=bool(
                    live_can(session, "health.read")
                    and scope.get("include_health")))
        except Exception:
            pass
    if live_can(session, "health.read") and scope.get(
            "include_health"):
        try:
            from .health import personal_health_index as _index
            index = _index()
            sources["health"] = [
                {"dimension": name,
                 "value": info["value"],
                 "completeness": info["completeness"]}
                for name, info in
                index["dimensions"].items()]
        except Exception:
            pass
    if live_can(session, "research.read"):
        try:
            from .research import list_sources as _sources
            sources["research"] = [
                {"id": item.source_id,
                 "title": item.title,
                 "type": item.source_type}
                for item in _sources(limit=8)]
        except Exception:
            pass
    if live_can(session, "skills.read"):
        try:
            from .skills import list_skills as _skills
            sources["skills"] = [
                {"skill_id": item.skill_id, "name": item.name,
                 "stage": item.stage}
                for item in _skills(limit=8)]
        except Exception:
            pass
    if live_can(session, "workshop.read"):
        try:
            from .printer3d import list_stored_printers as _printers
            sources["workshop"] = [
                {"id": item.printer_id, "name": item.name,
                 "status": item.status}
                for item in _printers()[:8]]
        except Exception:
            pass
    if live_can(session, "fabrication.read"):
        try:
            init_chat_database()
            with chat_connection() as db:
                fab_rows = db.execute(
                    "SELECT fabrication_id, status FROM "
                    "fabrications ORDER BY fabrication_id DESC "
                    "LIMIT 8").fetchall()
            sources["fabrication"] = [
                {"id": row["fabrication_id"],
                 "status": row["status"]} for row in fab_rows]
        except Exception:
            pass
    if live_can(session, "twin.read"):
        try:
            from .twin import staleness_report as _stale
            report = _stale()
            sources["twin"] = {
                "fresh": len(report["fresh"]),
                "stale": len(report["stale"])}
        except Exception:
            pass
    if live_can(session, "watcher.read"):
        try:
            from datetime import datetime as _dt
            from datetime import timezone as _tz
            with connection() as db:
                task_rows = db.execute(
                    "SELECT id, status, created_at FROM tasks "
                    "ORDER BY id DESC LIMIT 50").fetchall()
            sources["findings"] = [
                item.summary for item in scan_stale_tasks(
                    [dict(row) for row in task_rows],
                    _dt.now(_tz.utc))[:8]]
        except Exception:
            pass
    if scope.get("include_events", True):
        sources["events"] = [
            event.model_dump(mode="json")
            for event in bus_events(limit=20)]
    try:
        return pack_context(session, sources, query=body.query,
                            budget=body.budget)
    except LiveRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/live/propose", status_code=201)
def live_propose(body: LiveProposeBody) -> dict:
    """Propose through a Live session. Capability-gated; the
    proposal itself is inert and still needs the existing
    approval flow. git.push is unavailable, always."""
    import secrets as _secrets
    session = _live_session_or_403(body.session_id)
    actor = (body.actor or session.actor).strip()[:80]
    if not actor:
        raise HTTPException(status_code=422,
                            detail="actor must be non-empty text")
    if body.kind == "inventory_write":
        if not live_can(session, "inventory.propose_write"):
            raise HTTPException(
                status_code=403,
                detail="session lacks inventory.propose_write")
        try:
            proposal = propose_inventory_write(
                f"wrt-{_secrets.token_hex(4)}", "create",
                body.payload.get("entity_type", ""),
                dict(body.payload.get("fields", {})),
                entity_id=str(body.payload.get("entity_id", "")),
                actor=actor)
        except (InventoryWriteRefusedError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error))
        _write_save(proposal, "proposed")
        return _write_to_json(_write_load(proposal.proposal_id))
    if body.kind == "git_commit":
        if not live_can(session, "git.commit"):
            raise HTTPException(status_code=403,
                                detail="session lacks git.commit")
        fields = body.payload
        try:
            proposal = propose_git_commit(
                f"wrt-{_secrets.token_hex(4)}",
                str(fields.get("repository", "")),
                str(fields.get("branch", "")),
                str(fields.get("expected_head", "")),
                str(fields.get("message", "")),
                list(fields.get("files", [])),
                changeset_fingerprint=str(fields.get(
                    "changeset_fingerprint", "")),
                actor=actor)
        except (GitWriteRefusedError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error))
        _write_save(proposal, "proposed")
        return _write_to_json(_write_load(proposal.proposal_id))
    if body.kind == "transform":
        if not live_can(session, "3d.propose_transform"):
            raise HTTPException(
                status_code=403,
                detail="session lacks 3d.propose_transform")
        return _transform_artifact(
            str(body.payload.get("artifact_ref", "")),
            str(body.payload.get("op", "")),
            body.payload.get("params", {}),
            persist=bool(body.payload.get("persist", False)))
    if body.kind in ("task", "mission", "research", "project",
                     "desktop", "git_push"):
        raise HTTPException(
            status_code=422,
            detail=f"kind '{body.kind}' is not wired yet; "
                   "git.push is never available")
    raise HTTPException(status_code=422,
                        detail=f"Unknown propose kind '{body.kind}'")


@app.get("/api/v1/fab/mesh/preview")
def fab_mesh_preview(artifact_ref: str,
                     max_tris: int = 1000) -> dict:
    """Bounded wireframe preview data for one mesh artifact.
    Preview only: no files written, no registration."""
    from .mesh3d import mesh_facets
    try:
        facets, format_name, total, truncated = mesh_facets(
            artifact_ref, max_tris)
    except (MeshRefusedError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {
        "artifact_ref": artifact_ref, "format": format_name,
        "total_tris": total, "truncated": truncated,
        "tris": [[[float(value) for value in point]
                  for point in facet] for facet in facets],
    }


@app.post("/api/v1/fab/transform", status_code=201)
def fab_transform(body: TransformBody) -> dict:
    """Preview (and optionally persist locally) one mesh
    transform. Persistence is a local working file; INVENTory
    registration still needs the file proposal flow."""
    return _transform_artifact(body.artifact_ref, body.op,
                               dict(body.params or {}),
                               persist=body.persist,
                               max_tris=body.max_tris)


def _transform_artifact(artifact_ref: str, op: str, params: dict,
                        persist: bool = False,
                        max_tris: int = 5000) -> dict:
    from .mesh3d import (
        check_transform,
        file_payload_for_mesh,
        mesh_facets,
        transform_facets,
        validate_mesh,
        write_derived_mesh,
    )
    try:
        cleaned = check_transform(op, params)
        facets, format_name, total, _ = mesh_facets(
            artifact_ref, max_tris)
    except (MeshRefusedError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    moved = transform_facets(facets, op, cleaned)
    preview = [[[round(float(value), 3) for value in point]
                for point in facet] for facet in moved]
    result: dict = {
        "source_ref": artifact_ref, "op": op,
        "params": cleaned, "format": format_name,
        "total_tris": total,
        "preview_tris": preview,
        "executed": False,
    }
    if persist:
        try:
            derived_ref, digest, size = write_derived_mesh(
                artifact_ref, op, moved)
        except (MeshRefusedError, ValueError, OSError) as error:
            raise HTTPException(status_code=422, detail=str(error))
        report = validate_mesh(derived_ref)
        try:
            payload = file_payload_for_mesh(
                report, digest, size, derived_ref)
        except (MeshRefusedError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error))
        result.update({
            "executed": True,
            "derived_ref": derived_ref,
            "sha256": digest,
            "size_bytes": size,
            "validation": report.model_dump(mode="json"),
            "file_payload": payload,
        })
    return result


@app.get("/api/v1/watcher/scan")
async def watcher_scan() -> dict:
    """Run watcher detectors over bounded live sources. Findings
    only — never execution, never writes."""
    from datetime import datetime as _dt
    from datetime import timezone as _tz
    current = _dt.now(_tz.utc)
    try:
        with connection() as db:
            task_rows = db.execute(
                "SELECT id, status, created_at FROM tasks "
                "ORDER BY id DESC LIMIT 200").fetchall()
        tasks = [dict(row) for row in task_rows]
    except ValueError:
        tasks = []
    findings = []
    try:
        findings += scan_stale_tasks(tasks, current)
    except WatcherRefusedError:
        pass
    try:
        findings += scan_blocked_tasks(tasks, current)
    except WatcherRefusedError:
        pass
    try:
        findings += scan_failed_tasks(tasks, current)
    except WatcherRefusedError:
        pass
    try:
        browsed = await _world_reader().browse("projects")
        projects = []
        for record in browsed.results:
            details = record.details \
                if isinstance(record.details, dict) else {}
            projects.append({
                "id": record.entity_id,
                "status": details.get("status", ""),
                "updated_at": details.get("updated_at", ""),
                "created_at": details.get("created_at", "")})
    except (InventoryRefusedError, InventoryUnavailable,
            ValueError, AttributeError):
        projects = []
    try:
        findings += scan_projects(projects, current)
    except WatcherRefusedError:
        pass
    try:
        init_chat_database()
        with chat_connection() as db:
            fab_rows = db.execute(
                "SELECT fabrication_id, status FROM fabrications "
                "LIMIT 200").fetchall()
        findings += scan_unfinished_designs(
            [dict(row) for row in fab_rows], current)
    except (WatcherRefusedError, ValueError):
        pass
    try:
        with connection() as db:
            node_rows = db.execute(
                "SELECT node_id AS id, status, last_seen "
                "FROM nodes LIMIT 200").fetchall()
        findings += scan_device_staleness(
            [dict(row) for row in node_rows], current)
    except (WatcherRefusedError, ValueError):
        pass
    return {"findings": [item.model_dump(mode="json")
                         for item in findings[:50]]}


@app.get("/api/v1/reports/morning")
def report_morning() -> dict:
    """Deterministic morning report over bounded live sources.
    Same inputs, same report; sources are counts and short
    capped lines, never dumps. Fifteen independent sections;
    each loads on its own."""
    from datetime import datetime as _dt
    from datetime import timezone as _tz
    with connection() as db:
        node_rows = db.execute(
            "SELECT node_id, status, last_seen FROM nodes").fetchall()
        recent_tasks = db.execute(
            "SELECT id, kind, status FROM tasks ORDER BY id DESC "
            "LIMIT 15").fetchall()
    online = sum(1 for row in node_rows
                 if derive_status(row["status"],
                                  row["last_seen"])
                 in ("online", "busy"))
    init_chat_database()
    with chat_connection() as db:
        missions = db.execute(
            "SELECT record FROM missions ORDER BY created_at DESC "
            "LIMIT 10").fetchall()
        try:
            fabs = db.execute(
                "SELECT fabrication_id, status FROM fabrications "
                "ORDER BY fabrication_id DESC LIMIT 5").fetchall()
        except Exception:
            fabs = []
        try:
            owned_skills = db.execute(
                "SELECT name, stage FROM skills ORDER BY "
                "updated_at DESC LIMIT 8").fetchall()
        except Exception:
            owned_skills = []
    mission_titles = []
    for row in missions:
        try:
            record = load(row["record"])
            mission_titles.append(
                f"{record.get('goal', '?')} "
                f"[{record.get('status', '?')}]")
        except ValueError:
            continue
    notes = list_notifications_for_report()
    current = _dt.now(_tz.utc)
    try:
        findings = scan_stale_tasks(
            [{"id": row["id"], "status": row["status"],
              "created_at": ""} for row in recent_tasks],
            current)[:5]
    except WatcherRefusedError:
        findings = []
    try:
        from .agenda import init_agenda_tables as _agenda_init
        from .agenda import list_events as _agenda_events
        with chat_connection() as _adb:
            _agenda_init(_adb)
            _agenda_upcoming = _agenda_events(
                _adb, upcoming_only=True, limit=8)
    except Exception:
        _agenda_upcoming = []
    _waiting_lines = []
    for row in missions:
        try:
            _record = load(row["record"])
        except ValueError:
            continue
        if _record.get("status") in ("pending_approval", "paused"):
            _waiting_lines.append(
                f"{str(_record.get('goal', '?'))[:100]} "
                f"[{_record.get('status', '?')}]")
    _agenda_lines = [
        f"{str(event.get('start', '?'))} — "
        f"{str(event.get('title', '?'))[:100]}"
        for event in _agenda_upcoming]
    try:
        from .research_engine import list_dossiers as _dossiers
        _recent_dossiers = _dossiers(limit=5)
    except Exception:
        _recent_dossiers = []
    _research_lines = []
    for dossier in _recent_dossiers:
        domains = sorted({str(meta.get("url", "")).split("/")[2]
                          for meta in dossier.sources
                          if str(meta.get("url", "")).startswith(
                              "http") and "/" in str(meta.get(
                                  "url", ""))})
        _research_lines.append(
            f"{dossier.title[:100]} — {len(dossier.sources)} "
            f"bronnen ({', '.join(domains[:3]) or 'onbekend'}), "
            f"{len(dossier.claims)} claims, "
            f"{len(dossier.contradictions)} verschillen "
            f"[{dossier.execution_state}]")
    if not _research_lines:
        _research_lines = ["Geen nieuwe externe "
                           "onderzoeksresultaten beschikbaar."]
    sections = {
        "today": [current.strftime("%A %Y-%m-%d"),
                  f"{online}/{len(node_rows)} nodes online"],
        "missions": mission_titles,
        "tasks": [f"#{row['id']} {row['kind']} "
                  f"[{row['status']}]" for row in recent_tasks],
        "devices": [f"{row['node_id']} "
                    f"[{derive_status(row['status'], row['last_seen'])}]"
                    for row in node_rows[:10]],
        "findings": [item.summary for item in findings],
        "suggestions": [
            f"{online} nodes online, "
            f"{len(node_rows) - online} other",
            f"{len(notes)} unread notifications"],
    }
    if fabs:
        sections["fabrication"] = [
            f"{row['fabrication_id']} [{row['status']}]"
            for row in fabs]
    try:
        from .automation import list_runs as _auto_runs
        _auto_lines = [
            f"{run.run_id} {run.goal[:80]} [{run.state}]"
            for run in _auto_runs(limit=10)]
    except Exception:
        _auto_lines = []
    if _auto_lines:
        sections["automation"] = _auto_lines[:8]
    if _waiting_lines:
        sections["waiting"] = _waiting_lines[:8]
    if _agenda_lines:
        sections["agenda"] = _agenda_lines[:8]
    sections["research"] = _research_lines[:8]
    if owned_skills:
        sections["skills"] = [
            f"{row['name']} [{row['stage']}]"
            for row in owned_skills]
    try:
        from .presence import morning_presence_sections
        for key, lines in morning_presence_sections().items():
            sections[key] = lines[:8]
    except Exception:
        pass
    # BIG #42 ecosystem sections — only when real data exists,
    # never filler.
    try:
        from .hardware_links import list_links as _hw_all
        _hw_links = _hw_all(limit=200)
        if _hw_links:
            _verified = sum(1 for link in _hw_links
                            if link.status == "VERIFIED")
            _proposed = sum(1 for link in _hw_links
                            if link.status == "PROPOSED")
            sections["hardware"] = [
                f"{len(_hw_links)} link(s): {_verified} verified, "
                f"{_proposed} proposed",
                *[f"{link.link_id} {link.node_id}/"
                  f"{link.device_ref[:40]} [{link.status}]"
                  for link in _hw_links[:6]]]
    except Exception:
        pass
    try:
        from .quests import list_quest_details as _quest_all
        _quests = _quest_all(limit=20)
        if _quests:
            sections["quests"] = [
                f"{quest.get('title', '')[:90]} "
                f"{quest.get('done', 0)}/{quest.get('total', 0)} "
                f"[{quest.get('state', '')}]"
                for quest in _quests[:8]]
    except Exception:
        pass
    try:
        from .energy import summarize as _energy_sum
        _esum = _energy_sum()
        if _esum.get("total"):
            sections["energy"] = [
                f"{_esum['total']} record(s), "
                f"{_esum.get('unknown_values', 0)} unknown "
                "value(s)",
                *[f"{source}: {bucket['count']} record(s)"
                  for source, bucket in
                  list(_esum.get("by_source", {}).items())[:6]]]
    except Exception:
        pass
    try:
        from .finance import summarize as _finance_sum
        _fsum = _finance_sum()
        if _fsum.get("total"):
            sections["finance"] = [
                f"{_fsum['total']} record(s), "
                f"{_fsum.get('unknown_amounts', 0)} unknown "
                "amount(s)"]
    except Exception:
        pass
    # BIG #43 living game layer: current campaign — only when
    # campaigns exist, never filler.
    try:
        from .campaigns import list_campaign_details as _camps43
        _camps = _camps43(limit=5)
        if _camps:
            sections["campaigns"] = [
                f"{campaign.get('title', '')[:90]} "
                f"{campaign.get('completed_count', 0)}/"
                f"{campaign.get('total_count', 0)} "
                f"[{campaign.get('state', '')}]"
                for campaign in _camps[:5]]
    except Exception:
        pass
    # BIG #45 living connections: ecosystem section — only
    # when real connections exist, never filler.
    try:
        from .symbiosis import proposed as _props45
        from .hardware_links import list_links as _hw45
        _open_props = _props45(limit=60)
        _verified_hw = [link for link in _hw45(limit=200)
                        if link.status == "VERIFIED"]
        _conn_lines = []
        if _open_props:
            _conn_lines.append(
                f"{len(_open_props)} open proposal(s) "
                f"(seedlings awaiting review)")
            for prop in _open_props[:4]:
                _conn_lines.append(
                    f"{str(prop.get('title', ''))[:90]}: "
                    f"{', '.join(prop.get('entities', [])[:2])}")
        if _verified_hw:
            _conn_lines.append(
                f"{len(_verified_hw)} verified hardware "
                f"link(s) (established)")
        try:
            from .connections import project_refs as _refs45
            from .finance import list_records as _fin45
            _confirmed = sum(
                1 for record in _fin45(limit=200)
                if record.status == "CONFIRMED")
            if _confirmed:
                _conn_lines.append(
                    f"{_confirmed} confirmed finance "
                    f"record(s)")
            _refs = _refs45(limit=10)
            if len(_refs) >= 2:
                _conn_lines.append(
                    f"{len(_refs)} linked projects: "
                    f"{', '.join(_refs[:4])}")
        except Exception:
            pass
        if _conn_lines:
            sections["connections"] = _conn_lines[:8]
    except Exception:
        pass
    try:
        from .energy import list_records as _e_list42
        from .finance import list_records as _f_list42
        _proj_refs = sorted({
            record.project_ref for record in
            _f_list42(limit=200)} | {
            record.project_ref for record in
            _e_list42(limit=200)} - {""})[:8]
        if _proj_refs:
            sections["projects"] = [
                f"{ref[:100]} (finance/energy linked)"
                for ref in _proj_refs]
    except Exception:
        pass
    try:
        report = morning_report(sections)
    except ReportRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return report.model_dump(mode="json")


def list_notifications_for_report(limit: int = 10) -> list:
    from .database import chat_connection, init_chat_database
    from .events import Notification
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute(
            "SELECT * FROM notifications ORDER BY created_at DESC "
            "LIMIT ?", (max(1, min(limit, 20)),)).fetchall()
    return [Notification(**{**dict(row),
                            "read": bool(row["read"])})
            for row in rows]


@app.get("/api/v1/domains")
def domains_list() -> list[dict]:
    return [item.model_dump(mode="json") for item in list_domains()]


@app.get("/api/v1/domains/{domain}")
def domain_get(domain: str) -> dict:
    try:
        return domain_info(domain).model_dump(mode="json")
    except DomainRefusedError as error:
        raise HTTPException(status_code=404, detail=str(error))


# =============================================================================
# MEMORY (BIG #11-15, Phase 1). Ten typed memories with truth
# tiers; AI output never auto-promotes. Tombstones on delete.
# =============================================================================

def _memory_provenance(raw: dict) -> "Provenance":
    from .inventory_read import Provenance as _Provenance
    if not raw:
        return _Provenance(source_type="ai-generated",
                           creator_id="memory-api",
                           human_verified=False)
    try:
        return _Provenance.model_validate(raw)
    except Exception as error:
        raise HTTPException(status_code=422,
                            detail=f"bad provenance: {error}")


@app.post("/api/v1/memory", status_code=201)
def memory_create(body: MemoryCreateBody) -> dict:
    """Store one typed memory. Fact tiers need human
    provenance; AI content without it refuses."""
    from .memory import MemoryRefusedError as _Refused
    from .memory import new_memory as _new
    from .memory import save_memory as _save
    try:
        entry = _new(
            body.memory_type, body.title, truth=body.truth,
            content=body.content, data=dict(body.data),
            source=body.source,
            provenance=_memory_provenance(
                dict(body.provenance)),
            confidence=body.confidence,
            importance=body.importance,
            project_ref=body.project_ref,
            entity_refs=list(body.entity_refs),
            event_refs=list(body.event_refs),
            derived_from=list(body.derived_from),
            expiry=body.expiry, observed_at=body.observed_at)
        _save(entry)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return entry.model_dump(mode="json")


@app.get("/api/v1/memory")
def memory_list(memory_type: str = "", truth: str = "",
                project_ref: str = "",
                include_health: bool = False,
                limit: int = 50) -> list[dict]:
    from .memory import MemoryRefusedError as _Refused
    from .memory import list_memories as _list
    try:
        entries = _list(memory_type=memory_type, truth=truth,
                        project_ref=project_ref,
                        include_health=include_health,
                        limit=limit)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return [entry.model_dump(mode="json") for entry in entries]


@app.get("/api/v1/memory/{memory_id}")
def memory_get(memory_id: str) -> dict:
    from .memory import get_memory as _get
    entry = _get(memory_id)
    if entry is None or entry.status == "deleted":
        raise HTTPException(404, "Memory not found")
    return entry.model_dump(mode="json")


@app.post("/api/v1/memory/{memory_id}/verify")
def memory_verify(memory_id: str,
                  body: MemoryVerifyBody) -> dict:
    """Explicit human promotion to verified. AI content
    without human_verified provenance refuses."""
    from .memory import MemoryRefusedError as _Refused
    from .memory import get_memory as _get
    from .memory import save_memory as _save
    from .memory import verify_memory as _verify
    entry = _get(memory_id)
    if entry is None or entry.status == "deleted":
        raise HTTPException(404, "Memory not found")
    try:
        verified = _verify(entry, body.verified_by,
                           confidence=body.confidence)
        _save(verified)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return verified.model_dump(mode="json")


@app.delete("/api/v1/memory/{memory_id}")
def memory_delete(memory_id: str) -> dict:
    from .memory import delete_memory as _delete
    if not _delete(memory_id):
        raise HTTPException(404, "Memory not found")
    return {"memory_id": memory_id, "status": "deleted"}


@app.post("/api/v1/memory/retrieve")
def memory_retrieve(body: MemoryRetrieveBody) -> dict:
    """Bounded recall over stored memories."""
    from .memory import MemoryRefusedError as _Refused
    from .memory import retrieve_memories as _retrieve
    try:
        results = _retrieve(
            body.query, memory_types=list(
                body.memory_types or []),
            project_ref=body.project_ref, truth=body.truth,
            limit=body.limit, semantic=body.semantic,
            include_health=body.include_health)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"results": results}


@app.post("/api/v1/memory/consolidate")
def memory_consolidate(body: MemoryConsolidateBody) -> dict:
    """Propose candidates from raw texts. Stores nothing;
    contradictions come back flagged for review."""
    from .memory import MemoryRefusedError as _Refused
    from .memory import propose_consolidation as _propose
    try:
        return _propose(list(body.raw_texts),
                        project_ref=body.project_ref,
                        source=body.source)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


# =============================================================================
# HEALTH + NUTRITION + GARMIN (BIG #11-15, Phase 2). Tracking and
# trends only: no illness assessment anywhere, no hidden scores,
# vegan claims need evidence, Garmin live stays off without a
# real transport (mock provider for tests/dev).
# =============================================================================

@app.post("/api/v1/health/measurements", status_code=201)
def health_measure(body: HealthMeasureBody) -> dict:
    from .health import HealthRefusedError as _Refused
    from .health import new_measurement as _new
    from .health import save_measurement as _save
    try:
        entry = _new(body.metric, body.value,
                     source=body.source,
                     observed_at=body.observed_at,
                     provenance=_memory_provenance(
                         dict(body.provenance))
                     if body.provenance else None)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    stored = _save(entry)
    payload = entry.model_dump(mode="json")
    payload["stored"] = stored
    payload["duplicate"] = not stored
    return payload


@app.get("/api/v1/health/measurements")
def health_measurements(metric: str = "", source: str = "",
                        since: str = "",
                        limit: int = 100) -> list[dict]:
    from .health import HealthRefusedError as _Refused
    from .health import list_measurements as _list
    try:
        entries = _list(metric=metric, source=source,
                        since=since, limit=limit)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    out = []
    for entry in entries:
        payload = entry.model_dump(mode="json")
        payload["origin"] = entry.provenance.creator_id
        out.append(payload)
    return out


@app.get("/api/v1/health/trends/{metric}")
def health_trend(metric: str, limit: int = 30) -> dict:
    from .health import HealthRefusedError as _Refused
    from .health import trend_for as _trend
    try:
        return _trend(metric, limit=limit)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.get("/api/v1/health/index")
def health_index() -> dict:
    """Transparent per-dimension index. Method and
    completeness on every dimension; nothing hidden."""
    from .health import personal_health_index as _index
    return _index()


@app.post("/api/v1/nutrition/foods", status_code=201)
def nutrition_food_create(body: FoodCreateBody) -> dict:
    from .nutrition import NutritionRefusedError as _Refused
    from .nutrition import new_food as _new
    from .nutrition import save_food as _save
    try:
        food = _new(body.name, dict(body.nutrients),
                    vegan_status=body.vegan_status,
                    vegan_evidence=body.vegan_evidence,
                    source=body.source,
                    provenance=_memory_provenance(
                        dict(body.provenance))
                    if body.provenance else None)
        _save(food)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return food.model_dump(mode="json")


@app.get("/api/v1/nutrition/foods")
def nutrition_food_lookup(name: str = "") -> dict:
    from .nutrition import NUTRIENTS as _nutrients
    if not name:
        return {"nutrients": _nutrients, "foods": []}
    from .nutrition import find_food as _find
    found = _find(name)
    return {"nutrients": _nutrients,
            "foods": [found.model_dump(mode="json")]
            if found is not None else []}


@app.post("/api/v1/nutrition/meals", status_code=201)
def nutrition_meal_create(body: MealCreateBody) -> dict:
    from .nutrition import NutritionRefusedError as _Refused
    from .nutrition import new_meal as _new
    from .nutrition import save_meal as _save
    try:
        meal = _new(
            body.name,
            [item.model_dump(mode="json")
             for item in body.items],
            source=body.source, observed_at=body.observed_at,
            provenance=_memory_provenance(
                dict(body.provenance))
            if body.provenance else None)
        _save(meal)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return meal.model_dump(mode="json")


@app.get("/api/v1/nutrition/daily")
def nutrition_daily(day: str) -> dict:
    from .nutrition import NutritionRefusedError as _Refused
    from .nutrition import coverage_for as _coverage
    from .nutrition import daily_totals as _totals
    try:
        totals = _totals(day)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"totals": totals,
            "coverage": _coverage(totals["totals"])}


@app.get("/api/v1/nutrition/weekly")
def nutrition_weekly(end_day: str) -> dict:
    from .nutrition import NutritionRefusedError as _Refused
    from .nutrition import weekly_trend as _trend
    try:
        return _trend(end_day)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.get("/api/v1/integrations/garmin/status")
def garmin_status(provider: str = "unavailable") -> dict:
    """Honest provider state: UNAVAILABLE by default, MOCK for
    tests/dev, never a fake LIVE."""
    from .garmin import get_garmin_provider as _get
    return _get(provider).status()


@app.post("/api/v1/integrations/garmin/import")
def garmin_import(body: GarminImportBody) -> dict:
    """Import one bounded page into health measurements
    (source=wearable, external-source provenance, deduped)."""
    from .garmin import GarminRefusedError as _Refused
    from .garmin import get_garmin_provider as _get
    from .garmin import import_samples as _import
    try:
        return _import(_get(body.provider), since=body.since,
                       cursor=body.cursor, limit=body.limit)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


# =============================================================================
# RESEARCH + INGESTION + SKILLS (BIG #11-15, Phase 3). Sources
# never write to INVENTory directly; claims cite stored
# sources; candidates are not skills; Instagram is
# manual-export only.
# =============================================================================

@app.post("/api/v1/research/sources", status_code=201)
def research_source_receive(body: ResearchSourceBody) -> dict:
    from .research import ResearchRefusedError as _Refused
    from .research import extract_source as _extract
    from .research import new_source as _new
    from .research import save_source as _save
    try:
        entry = _new(
            body.source_type, body.title, content=body.content,
            external_id=body.external_id,
            reference=body.reference, author=body.author,
            topics=list(body.topics),
            entities=list(body.entities),
            published_at=body.published_at,
            provenance=_memory_provenance(
                dict(body.provenance))
            if body.provenance else None)
        entry = _extract(entry)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    stored = _save(entry)
    payload = entry.model_dump(mode="json")
    payload["stored"] = stored
    payload["duplicate"] = not stored
    return payload


@app.get("/api/v1/research/sources")
def research_source_list(source_type: str = "",
                         limit: int = 50) -> list[dict]:
    from .research import ResearchRefusedError as _Refused
    from .research import list_sources as _list
    try:
        entries = _list(source_type=source_type, limit=limit)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return [entry.model_dump(mode="json") for entry in entries]


@app.post("/api/v1/research/sources/{source_id}/advance")
def research_source_advance(source_id: str,
                            body: ResearchAdvanceBody) -> dict:
    from .research import ResearchRefusedError as _Refused
    from .research import advance_source as _advance
    try:
        return _advance(source_id, body.to_stage,
                        approved_by=body.approved_by).model_dump(
                            mode="json")
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/research/records", status_code=201)
def research_record_create(body: ResearchRecordBody) -> dict:
    """QUESTION → cited claims → synthesis. Uncited claims
    refuse; synthesis stays interpretation."""
    from .research import ResearchRefusedError as _Refused
    from .research import new_research_record as _new
    from .research import save_research_record as _save
    try:
        record = _new(
            body.question,
            [item.model_dump(mode="json")
             for item in body.claims],
            synthesis=body.synthesis,
            provenance=_memory_provenance(
                dict(body.provenance))
            if body.provenance else None)
        _save(record)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return record.model_dump(mode="json")


@app.get("/api/v1/research/records/{record_id}")
def research_record_get(record_id: str) -> dict:
    from .research import get_research_record as _get
    record = _get(record_id)
    if record is None:
        raise HTTPException(404, "Research record not found")
    return record.model_dump(mode="json")


# =============================================================================
# RESEARCH ENGINE (BIG #29) — question -> dossier. Read-only by
# default; REAL/TEST/UNAVAILABLE labelled; claims cite stored
# sources; synthesis is interpretation, never fact.
# =============================================================================

def _research_provider(name: str,
                       test_pages: dict | None = None):
    """Resolve a research provider by name. Unknown names and
    fixture smuggling refuse; explicit test pages stay TEST."""
    from .research_transport import (
        TestResearchTransport as _Test,
        TransportRefusedError as _TransportRefused,
        UnavailableSearchProvider as _Down,
        WikipediaSearchProvider as _Wiki,
    )
    clean = str(name or "wikipedia").strip().lower()
    if clean == "wikipedia":
        if test_pages:
            raise HTTPException(
                status_code=422,
                detail="test pages need provider 'test'")
        return _Wiki(language="nl")
    if clean == "test":
        pages: dict = {}
        for path, pair in (test_pages or {}).items():
            if len(pages) >= 10:
                break
            if not isinstance(path, str) or not path.strip() \
                    or len(path) > 120:
                continue
            if not isinstance(pair, list) or len(pair) != 2:
                continue
            title, text = str(pair[0])[:200], str(pair[1])[:8000]
            key = path.strip().strip("/")[:120]
            if key and title and text:
                pages[key] = (title, text)
        if not pages:
            raise HTTPException(
                status_code=422,
                detail="provider 'test' needs test_pages "
                       "{path: [title, text]}")
        return _Test(pages)
    if clean == "unavailable":
        return _Down()
    raise HTTPException(
        status_code=422,
        detail=f"Unknown research provider '{name}' "
               "(wikipedia|test|unavailable)")


async def _execute_research_run(run_id: str, provider,
                                max_sources: int,
                                seed_urls: list | None = None
                                ) -> dict:
    """Drive one run with the coordinator's real context
    sources (INVENTory bridge, recall without health scope,
    project context, Ollama advice)."""
    from .memory import retrieve_memories as _recall
    from .research_engine import execute_run as _execute

    async def _search(query: str) -> list[dict]:
        records, _, _ = await _chat_world_context(query)
        return records

    def _memory_search(query: str):
        return _recall(query, limit=10)

    def _project() -> dict:
        return default_context().model_dump()

    try:
        finished = await _execute(
            run_id, search_provider=provider,
            advise_fn=get_provider("ollama").advise,
            inventory_search=_search,
            list_memories_fn=_memory_search,
            project_read_fn=_project,
            max_sources=max(1, min(int(max_sources or 6), 6)),
            seed_urls=[str(url or "")[:2000]
                       for url in (seed_urls or [])][:6])
    except Exception as error:
        from .research_engine import EngineRefusedError as _Refused
        if isinstance(error, _Refused):
            raise HTTPException(status_code=422, detail=str(error))
        raise HTTPException(status_code=502, detail=str(error)[:300])
    return _run_to_json(finished.run_id)


def _run_to_json(run_id: str) -> dict:
    from .research_engine import (
        dossier_for_run as _dossier_for,
        load_run as _load,
    )
    run = _load(run_id)
    if run is None:
        raise HTTPException(404, "Research run not found")
    payload = run.model_dump(mode="json")
    payload["source_count"] = len(run.source_ids)
    payload["claim_count"] = len(run.claims)
    payload["contradiction_count"] = len(run.contradictions)
    dossier = _dossier_for(run_id)
    payload["dossier_id"] = dossier.dossier_id if dossier else ""
    return payload


@app.post("/api/v1/research/runs", status_code=201)
async def research_run_create(body: ResearchRunBody) -> dict:
    """Open (+ optionally execute) a research run. provider
    wikipedia attempts REAL retrieval; test uses explicit
    fixtures (TEST); unavailable is an honest no-op."""
    from .research_engine import (
        EngineRefusedError as _Refused,
        new_run as _new,
        save_run as _save,
    )
    provider = _research_provider(body.provider, body.test_pages)
    try:
        run = _new(body.question, objective=body.objective,
                   project_ref=body.project_ref,
                   mission_id=body.mission_id,
                   requested_by="api",
                   metadata={"provider": provider.provider_name})
        _save(run)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    if not body.execute:
        return _run_to_json(run.run_id)
    return await _execute_research_run(
        run.run_id, provider, body.max_sources,
        seed_urls=body.source_urls)


@app.get("/api/v1/research/runs")
def research_run_list(limit: int = 50) -> list[dict]:
    from .research_engine import list_runs as _list
    return [{"run_id": run.run_id, "question": run.question,
             "status": run.status,
             "execution_state": run.execution_state,
             "source_count": len(run.source_ids),
             "claim_count": len(run.claims),
             "contradiction_count": len(run.contradictions),
             "dossier_id": run.dossier_id,
             "created_at": run.created_at}
            for run in _list(limit=limit)]


@app.get("/api/v1/research/runs/{run_id}")
def research_run_get(run_id: str) -> dict:
    return _run_to_json(run_id)


@app.post("/api/v1/research/runs/{run_id}/execute")
async def research_run_execute(run_id: str,
                               body: ResearchExecuteBody) -> dict:
    from .research_engine import load_run as _load
    run = _load(run_id)
    if run is None:
        raise HTTPException(404, "Research run not found")
    if run.status not in ("draft", "blocked", "failed"):
        raise HTTPException(
            status_code=409,
            detail=f"Run is {run.status}; only draft/blocked/"
                   "failed runs execute")
    provider = _research_provider(body.provider, body.test_pages)
    return await _execute_research_run(
        run_id, provider, body.max_sources,
        seed_urls=body.source_urls)


@app.get("/api/v1/research/dossiers")
def research_dossier_list(limit: int = 50) -> list[dict]:
    from .research_engine import list_dossiers as _list
    return [{"dossier_id": item.dossier_id, "run_id": item.run_id,
             "title": item.title,
             "execution_state": item.execution_state,
             "synthesis_available": item.synthesis_available,
             "sources": len(item.sources),
             "claims": len(item.claims),
             "created_at": item.created_at}
            for item in _list(limit=limit)]


@app.get("/api/v1/research/dossiers/{dossier_id}")
def research_dossier_get(dossier_id: str) -> dict:
    from .research_engine import load_dossier as _load
    dossier = _load(dossier_id)
    if dossier is None:
        raise HTTPException(404, "Research dossier not found")
    return dossier.model_dump(mode="json")


@app.get("/api/v1/integrations/instagram/status")
def instagram_status() -> dict:
    from .research import INSTAGRAM_STATUS as _status
    return dict(_status)


@app.post("/api/v1/ingest/instagram")
def instagram_ingest(body: InstagramImportBody) -> dict:
    """Ingest a user-owned manual export (or the mock).
    Anything else refuses; live access is unavailable."""
    from .research import ResearchRefusedError as _Refused
    from .research import instagram_export_to_sources as _map
    from .research import save_source as _save
    try:
        sources = _map(dict(body.export),
                       collection=body.collection)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    stored = sum(1 for entry in sources if _save(entry))
    return {"received": len(sources), "stored": stored,
            "duplicates": len(sources) - stored,
            "sources": [entry.model_dump(mode="json")
                        for entry in sources]}


# =============================================================================
# n8n INTEGRATION PLANE (BIG #17). External automation around
# Mycelium — never the coordinator. Webhooks are observations,
# never facts/approvals/execution. Mycelium never calls n8n;
# delivery flows through a poll-model outbox with allow-listed
# labels. Secrets never cross: n8n holds all external
# credentials in its own store.
# =============================================================================

@app.get("/api/v1/integrations")
def integrations_list() -> list[dict]:
    """Public registry: sources, capabilities, statuses and
    mock/live honesty. No secrets, no keys."""
    from .n8n import list_specs as _list
    return _list()


@app.post("/api/v1/integrations/{integration_id}/keys",
          status_code=201)
def integration_issue_key(integration_id: str,
                          body: IntegrationKeyBody) -> dict:
    """Operator issues (or rotates) an integration bearer key.
    Plaintext returns exactly once; only the hash is stored."""
    from .n8n import IntegrationRefusedError as _Refused
    from .n8n import issue_integration_key as _issue
    try:
        check_operator_key(body.operator_key)
    except NodeAuthError:
        raise HTTPException(
            status_code=403,
            detail="operator authorization rejected")
    try:
        token = _issue(integration_id,
                       list(body.capabilities or []))
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"integration_id": integration_id,
            "key": token,
            "warning": "store this key in n8n now; it is never "
                       "shown again"}


@app.post("/api/v1/integrations/events", status_code=201)
def integrations_ingest(body: IntegrationEnvelopeBody,
                        x_integration_key: str | None = Header(
                            default=None)) -> dict:
    """n8n webhook boundary: authenticated, capability-gated,
    bounded, idempotent. A webhook is an observation/input —
    never fact, never approval, never execution."""
    from .n8n import IntegrationAuthError as _AuthRefused
    from .n8n import IntegrationRefusedError as _Refused
    from .n8n import ingest_envelope as _ingest
    from .n8n import require_capability as _require
    if not x_integration_key:
        raise HTTPException(status_code=401,
                            detail="integration key required")
    try:
        _require(body.integration_id, x_integration_key,
                 "integration:ingest")
    except _AuthRefused:
        raise HTTPException(status_code=403,
                            detail="integration credential "
                                   "rejected")
    try:
        result = _ingest(body.model_dump(mode="json"))
    except _Refused as error:
        emit_event("integration.rejected",
                   f"Integration {body.integration_id} "
                   f"envelope refused",
                   payload={"integration_id":
                            body.integration_id,
                            "external_event_id":
                            body.external_event_id})
        raise HTTPException(status_code=422, detail=str(error))
    emit_event(f"integration.{result['outcome']}",
               f"Integration {body.integration_id} "
               f"{result['outcome']}: "
               f"{body.external_event_id}",
               payload={"integration_id": body.integration_id,
                        "external_event_id":
                        body.external_event_id})
    return result


@app.get("/api/v1/integrations/events")
def integrations_events(
        integration_id: str = "", status: str = "",
        limit: int = 50,
        x_integration_key: str | None = Header(default=None),
        operator_key: str = "") -> list[dict]:
    """Ingestion ledger: received/accepted/duplicate/
    conflict/rejected/failed. Integration key with status
    capability, or the operator key — never public."""
    from .n8n import IntegrationAuthError as _AuthRefused
    from .n8n import IntegrationRefusedError as _Refused
    from .n8n import list_ingested as _list
    from .n8n import require_capability as _require
    allowed = False
    if x_integration_key and integration_id:
        try:
            _require(integration_id, x_integration_key,
                     "integration:status")
            allowed = True
        except _AuthRefused:
            pass
    if not allowed:
        try:
            check_operator_key(operator_key)
            allowed = True
        except NodeAuthError:
            pass
    if not allowed:
        raise HTTPException(status_code=403,
                            detail="integration credential "
                                   "rejected")
    try:
        return _list(integration_id=integration_id,
                     status=status, limit=limit)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/integrations/trigger", status_code=201)
def integrations_trigger(
        body: IntegrationTriggerBody,
        x_integration_key: str | None = Header(default=None)
        ) -> dict:
    """n8n scheduler trigger: runs one KNOWN job by name.
    n8n says which registered job runs — never what code
    runs. Bounded, idempotent, recorded by jobs.run_job."""
    from .n8n import IntegrationAuthError as _AuthRefused
    from .n8n import IntegrationRefusedError as _Refused
    from .n8n import require_capability as _require
    from .n8n import trigger_job as _trigger
    if not x_integration_key:
        raise HTTPException(status_code=401,
                            detail="integration key required")
    try:
        _require(body.integration_id, x_integration_key,
                 "integration:trigger")
    except _AuthRefused:
        raise HTTPException(status_code=403,
                            detail="integration credential "
                                   "rejected")
    try:
        return _trigger(body.job_name, dict(body.params or {}),
                        run_key=body.run_key)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/integrations/outbox", status_code=201)
def integrations_outbox_enqueue(
        body: OutboxEnqueueBody) -> dict:
    """Queue one delivery label for n8n to poll. Operator
    only; labels allow-listed per integration spec. No URLs,
    no secrets, no callbacks — n8n decides the external how."""
    from .n8n import IntegrationRefusedError as _Refused
    from .n8n import enqueue_delivery as _enqueue
    try:
        check_operator_key(body.operator_key)
    except NodeAuthError:
        raise HTTPException(
            status_code=403,
            detail="operator authorization rejected")
    try:
        return _enqueue(body.target_label,
                        dict(body.payload or {}),
                        created_by="operator")
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.get("/api/v1/integrations/outbox")
def integrations_outbox_list(
        status: str = "pending", limit: int = 50,
        integration_id: str = "",
        x_integration_key: str | None = Header(default=None)
        ) -> list[dict]:
    """n8n polls pending deliveries here, delivers externally,
    then acks. Trigger capability required."""
    from .n8n import IntegrationAuthError as _AuthRefused
    from .n8n import IntegrationRefusedError as _Refused
    from .n8n import list_outbox as _list
    from .n8n import require_capability as _require
    if not x_integration_key or not integration_id:
        raise HTTPException(status_code=401,
                            detail="integration key and id "
                                   "required")
    try:
        _require(integration_id, x_integration_key,
                 "integration:trigger")
    except _AuthRefused:
        raise HTTPException(status_code=403,
                            detail="integration credential "
                                   "rejected")
    try:
        return _list(status=status, limit=limit)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/integrations/outbox/{outbox_id}/ack")
def integrations_outbox_ack(
        outbox_id: str, body: OutboxAckBody,
        x_integration_key: str | None = Header(default=None)
        ) -> dict:
    from .n8n import IntegrationAuthError as _AuthRefused
    from .n8n import IntegrationRefusedError as _Refused
    from .n8n import ack_outbox as _ack
    from .n8n import require_capability as _require
    if not x_integration_key:
        raise HTTPException(status_code=401,
                            detail="integration key required")
    try:
        _require(body.integration_id, x_integration_key,
                 "integration:trigger")
    except _AuthRefused:
        raise HTTPException(status_code=403,
                            detail="integration credential "
                                   "rejected")
    try:
        return _ack(outbox_id, body.integration_id,
                    failed=body.failed)
    except _Refused as error:
        raise HTTPException(status_code=404, detail=str(error))


@app.get("/api/v1/integrations/garmin/readiness")
def integrations_garmin_readiness() -> dict:
    """Garmin readiness: UNAVAILABLE until official
    credentials plus a reviewed live transport exist.
    States exactly what is missing; mock stays for tests."""
    from .n8n import get_spec as _spec
    spec = _spec("garmin")
    return {
        "integration_id": "garmin",
        "state": spec["status"],
        "mock": spec["mock"],
        "requirements": [
            "user-owned official Garmin API access "
            "(Garmin Health API with OAuth client credentials)",
            "operator consent + data scope selection",
            "reviewed live transport (loopback service, "
            "bounded fetch, no scraping, no private APIs)",
            "n8n credential entry holding the OAuth secret "
            "(never in Mycelium)",
            "mapping review for new Garmin sample types",
        ],
        "ready_path": "n8n → Garmin integration → "
                      "POST /api/v1/integrations/events "
                      "(health.measurements) → existing import "
                      "pipeline",
        "mock_path": "MockGarminProvider for tests and "
                     "development; always labelled MOCK",
    }


@app.post("/api/v1/skills", status_code=201)
def skill_create(body: SkillCreateBody) -> dict:
    from .skills import SkillRefusedError as _Refused
    from .skills import new_skill as _new
    from .skills import save_skill as _save
    try:
        skill = _new(
            body.name, category=body.category,
            description=body.description,
            prerequisites=list(body.prerequisites),
            related_skills=list(body.related_skills),
            stage=body.stage, proficiency=body.proficiency,
            project_refs=list(body.project_refs),
            source=body.source,
            provenance=_memory_provenance(
                dict(body.provenance))
            if body.provenance else None)
        _save(skill)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return skill.model_dump(mode="json")


@app.get("/api/v1/skills")
def skill_list(stage: str = "", limit: int = 100) -> list[dict]:
    from .skills import SkillRefusedError as _Refused
    from .skills import list_skills as _list
    try:
        found = _list(stage=stage, limit=limit)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return [item.model_dump(mode="json") for item in found]


@app.get("/api/v1/skills/{skill_id}")
def skill_get(skill_id: str) -> dict:
    from .skills import get_skill as _get
    skill = _get(skill_id)
    if skill is None:
        raise HTTPException(404, "Skill not found")
    return skill.model_dump(mode="json")


@app.post("/api/v1/skills/{skill_id}/evidence")
def skill_evidence(skill_id: str,
                   body: SkillEvidenceBody) -> dict:
    from .skills import SkillRefusedError as _Refused
    from .skills import add_evidence as _add
    try:
        return _add(skill_id, body.kind, body.ref,
                    note=body.note).model_dump(mode="json")
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/skills/{skill_id}/advance")
def skill_advance(skill_id: str,
                  body: SkillAdvanceBody) -> dict:
    from .skills import SkillRefusedError as _Refused
    from .skills import advance_skill as _advance
    try:
        return _advance(skill_id, body.to_stage,
                        confirmed_by=body.confirmed_by
                        ).model_dump(mode="json")
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/skills/discover")
def skill_discover(body: SkillDiscoverBody) -> dict:
    """Deterministic candidates from project text. Saved as
    proposed; acceptance is a separate human step."""
    from .skills import SkillRefusedError as _Refused
    from .skills import discover_candidates as _discover
    from .skills import save_candidate as _save
    try:
        candidates = _discover(body.project_text,
                               project_ref=body.project_ref)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    for candidate in candidates:
        _save(candidate)
    return {"candidates": [item.model_dump(mode="json")
                           for item in candidates]}


@app.post("/api/v1/skills/candidates/{candidate_id}/accept")
def skill_candidate_accept(candidate_id: str,
                           body: SkillAcceptBody) -> dict:
    from .skills import SkillRefusedError as _Refused
    from .skills import accept_candidate as _accept
    try:
        return _accept(candidate_id,
                       accepted_by=body.accepted_by
                       ).model_dump(mode="json")
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


# =============================================================================
# ADVANCED 3D + CAD + FABRICATION (BIG #11-15, Phase 4). Safe ops
# only; prompt edits parse to explicit ops; physical start
# stays behind existing approval gates.
# =============================================================================

def _advanced_facets(artifact_ref: str, op: str, params: dict,
                     extra_refs: list, max_tris: int) -> tuple:
    from .mesh3d import MeshRefusedError, mesh_facets
    from .meshops import (MeshOpRefusedError, bounds_of,
                          check_advanced_op, extend_facets,
                          merge_facets, mirror_facets,
                          orient_facets)
    try:
        cleaned = check_advanced_op(op, dict(params))
        facets, format_name, total, _ = mesh_facets(
            artifact_ref, max_tris)
    except (MeshRefusedError, MeshOpRefusedError,
            ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        if op == "mirror":
            moved = mirror_facets(facets, cleaned["plane"])
            detail: dict = {"plane": cleaned["plane"]}
        elif op == "extend":
            moved = extend_facets(facets, cleaned["axis"],
                                  cleaned["delta_mm"])
            detail = {"axis": cleaned["axis"],
                      "delta_mm": cleaned["delta_mm"]}
        elif op == "orient":
            moved, detail = orient_facets(facets)
        else:
            groups = [facets]
            for ref in (extra_refs or [])[:9]:
                more, _, _, _ = mesh_facets(ref, max_tris)
                groups.append(more)
            moved = merge_facets(groups)
            detail = {"groups": len(groups)}
    except (MeshRefusedError, MeshOpRefusedError,
            ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return moved, format_name, total, detail


@app.post("/api/v1/fab/advanced", status_code=201)
def fab_advanced(body: AdvancedOpBody) -> dict:
    """Preview (optionally persist) one advanced op. Persist
    writes a derived working file; INVENTory registration
    still needs the file proposal flow."""
    from .mesh3d import validate_mesh, write_derived_mesh
    moved, format_name, total, detail = _advanced_facets(
        body.artifact_ref, body.op, dict(body.params),
        list(body.extra_refs), body.max_tris)
    preview = [[[round(float(value), 3) for value in point]
                for point in facet] for facet in moved[:50]]
    result: dict = {
        "source_ref": body.artifact_ref, "op": body.op,
        "detail": detail, "format": format_name,
        "total_tris": total, "result_tris": len(moved),
        "preview_tris": preview, "executed": False}
    if body.persist:
        try:
            derived_ref, digest, size = write_derived_mesh(
                body.artifact_ref, body.op, moved)
        except (ValueError, OSError) as error:
            raise HTTPException(status_code=422,
                                detail=str(error))
        report = validate_mesh(derived_ref)
        result.update({
            "executed": True, "derived_ref": derived_ref,
            "sha256": digest, "size_bytes": size,
            "validation": report.model_dump(mode="json")})
    return result


@app.post("/api/v1/fab/prompt-edit", status_code=201)
def fab_prompt_edit(body: PromptEditBody) -> dict:
    """Parse a prompt edit to an explicit op and preview it.
    Persist needs a human approver by name."""
    from .meshops import MeshOpRefusedError, parse_prompt_edit
    try:
        parsed = parse_prompt_edit(body.text)
    except MeshOpRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    if body.persist and not body.approved_by.strip():
        raise HTTPException(status_code=422, detail=
                            "persisting a prompt edit needs "
                            "approved_by (human)")
    moved, format_name, total, detail = _advanced_facets(
        body.artifact_ref, parsed["op"], parsed["params"], [],
        body.max_tris)
    preview = [[[round(float(value), 3) for value in point]
                for point in facet] for facet in moved[:50]]
    result: dict = {
        "source_ref": body.artifact_ref,
        "interpretation": parsed["interpretation"],
        "op": parsed["op"], "detail": detail,
        "format": format_name, "total_tris": total,
        "result_tris": len(moved), "preview_tris": preview,
        "executed": False, "approved_by": body.approved_by}
    if body.persist:
        from .mesh3d import validate_mesh, write_derived_mesh
        try:
            derived_ref, digest, size = write_derived_mesh(
                body.artifact_ref, parsed["op"], moved)
        except (ValueError, OSError) as error:
            raise HTTPException(status_code=422,
                                detail=str(error))
        report = validate_mesh(derived_ref)
        result.update({
            "executed": True, "derived_ref": derived_ref,
            "sha256": digest, "size_bytes": size,
            "validation": report.model_dump(mode="json")})
    return result


@app.get("/api/v1/fab/volume")
def fab_volume(artifact_ref: str) -> dict:
    """Mesh volume estimate in cm³ (filament math input)."""
    from .mesh3d import MeshRefusedError, mesh_facets
    from .meshops import MeshOpRefusedError, mesh_volume_cm3
    try:
        facets, _, total, _ = mesh_facets(artifact_ref)
        volume = mesh_volume_cm3(facets)
    except (MeshRefusedError, MeshOpRefusedError,
            ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"artifact_ref": artifact_ref, "volume_cm3": volume,
            "facets": total}


@app.post("/api/v1/cad/documents", status_code=201)
def cad_document_create(body: CadDocumentBody) -> dict:
    from .cad import CadRefusedError as _Refused
    from .cad import new_document as _new
    from .cad import save_document as _save
    try:
        document = _new(
            body.name, provenance=_memory_provenance(
                dict(body.provenance))
            if body.provenance else None)
        _save(document)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return document.model_dump(mode="json")


@app.get("/api/v1/cad/documents/{document_id}")
def cad_document_get(document_id: str) -> dict:
    from .cad import get_document as _get
    document = _get(document_id)
    if document is None:
        raise HTTPException(404, "CAD document not found")
    return document.model_dump(mode="json")


@app.get("/api/v1/cad/adapters")
def cad_adapters() -> list[dict]:
    from .cad import adapter_status as _status
    return _status()


@app.post("/api/v1/cad/documents/{document_id}/parts",
          status_code=201)
def cad_part_add(document_id: str,
                 body: CadPartBody) -> dict:
    from .cad import CadRefusedError as _Refused
    from .cad import add_part as _add
    from .cad import get_document as _get
    from .cad import save_document as _save
    document = _get(document_id)
    if document is None:
        raise HTTPException(404, "CAD document not found")
    try:
        updated = _add(document, body.name)
        _save(updated)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return updated.model_dump(mode="json")


@app.post("/api/v1/cad/documents/{document_id}/operate")
def cad_operate(document_id: str, body: CadOpBody) -> dict:
    from .cad import CadRefusedError as _Refused
    from .cad import add_operation as _add
    from .cad import get_document as _get
    from .cad import save_document as _save
    document = _get(document_id)
    if document is None:
        raise HTTPException(404, "CAD document not found")
    try:
        updated = _add(document, body.part_id, body.op,
                       dict(body.params), adapter=body.adapter)
        _save(updated)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return updated.model_dump(mode="json")


@app.post("/api/v1/cad/documents/{document_id}/build")
def cad_build(document_id: str) -> dict:
    """Execute the procedural op stack to derived meshes.
    External adapters refuse; nothing subprocesses."""
    from .cad import CadRefusedError as _Refused
    from .cad import execute_document as _execute
    from .cad import get_document as _get
    from .cad import save_document as _save
    document = _get(document_id)
    if document is None:
        raise HTTPException(404, "CAD document not found")
    try:
        built = _execute(document)
        _save(built)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return built.model_dump(mode="json")


@app.post("/api/v1/filament/spools", status_code=201)
def filament_spool_create(body: SpoolCreateBody) -> dict:
    from .fabrication import FabricationRefusedError as _Refused
    from .fabrication import new_spool as _new
    from .fabrication import save_spool as _save
    try:
        spool = _new(
            body.material, body.weight_g, color=body.color,
            diameter_mm=body.diameter_mm,
            compatible_profiles=list(
                body.compatible_profiles),
            source=body.source, location=body.location,
            provenance=_memory_provenance(
                dict(body.provenance))
            if body.provenance else None)
        _save(spool)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return spool.model_dump(mode="json")


@app.get("/api/v1/filament/spools")
def filament_spool_list() -> list[dict]:
    from .fabrication import list_spools as _list
    return [item.model_dump(mode="json") for item in _list()]


@app.get("/api/v1/filament/check")
def filament_check(spool_id: str, grams: float) -> dict:
    from .fabrication import FabricationRefusedError as _Refused
    from .fabrication import spool_check as _check
    try:
        return _check(spool_id, grams)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/fab/select-printer")
def fab_select_printer(body: PrinterSelectBody) -> dict:
    from .fabrication import FabricationRefusedError as _Refused
    from .fabrication import select_printer as _select
    try:
        return _select({"capabilities": list(
            body.capabilities), "profile": body.profile,
            "printer_id": body.printer_id})
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/fab/plan")
def fab_plan(body: PipelinePlanBody) -> dict:
    from .fabrication import FabricationRefusedError as _Refused
    from .fabrication import plan_pipeline as _plan
    try:
        return _plan(source_object_id=body.source_object_id,
                     source_idea_id=body.source_idea_id,
                     profile=body.profile,
                     material=body.material)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


# =============================================================================
# ROBOTS + DRONES + FAMILIARS + DIGITAL TWIN (BIG #11-15, Phase 5).
# Capabilities allow-listed, safety states explicit, physical
# execution HARDWARE_REQUIRED. Proposals approve, telemetry
# reports, verification stays independent.
# =============================================================================

@app.post("/api/v1/robots", status_code=201)
def robot_register(body: RobotCreateBody) -> dict:
    from .robots import RobotRefusedError as _Refused
    from .robots import new_robot as _new
    from .robots import save_robot as _save
    try:
        robot = _new(
            body.name, robot_type=body.robot_type,
            capabilities=list(body.capabilities),
            location=body.location, node_id=body.node_id,
            sensors=list(body.sensors),
            actuators=list(body.actuators),
            provenance=_memory_provenance(
                dict(body.provenance))
            if body.provenance else None)
        _save(robot)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return robot.model_dump(mode="json")


@app.get("/api/v1/robots")
def robot_list() -> list[dict]:
    from .robots import list_robots as _list
    return [item.model_dump(mode="json") for item in _list()]


@app.get("/api/v1/robots/{robot_id}")
def robot_get(robot_id: str) -> dict:
    from .robots import get_robot as _get
    robot = _get(robot_id)
    if robot is None:
        raise HTTPException(404, "Robot not found")
    return robot.model_dump(mode="json")


@app.post("/api/v1/robots/{robot_id}/safety")
def robot_safety(robot_id: str,
                 body: RobotSafetyBody) -> dict:
    from .robots import RobotRefusedError as _Refused
    from .robots import set_safety as _set
    try:
        return _set(robot_id,
                    body.safety_state).model_dump(mode="json")
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/robots/{robot_id}/propose")
def robot_propose(robot_id: str,
                  body: RobotActionBody) -> dict:
    """One inert robot-execution proposal (mutation type
    robot.execute). Approval runs through the generic
    write-approval flow (exact YES + fingerprint +
    staleness); execution itself stays HARDWARE_REQUIRED."""
    from .robots import RobotRefusedError as _Refused
    from .robots import build_robot_proposal as _build
    try:
        proposal = _build(robot_id, body.action,
                          dict(body.params), body.actor,
                          simulation_note=body.simulation_note)
        _write_save(proposal, "proposed")
    except (_Refused, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return _write_to_json(_write_load(proposal.proposal_id))


@app.post("/api/v1/robots/{robot_id}/approve")
def robot_approve(robot_id: str,
                  body: RobotApproveBody) -> dict:
    """Approve one stored robot proposal: exact YES only,
    fingerprint/staleness/target bound by the generic flow,
    plus a live recheck of safety state, capability and
    idleness (never trusted from the client body)."""
    from .robots import RobotRefusedError as _Refused
    from .robots import check_robot_state_for_approval as _check
    from .robots import mark_robot_busy as _busy
    record = _write_load(body.proposal_id)
    if record is None:
        raise HTTPException(404, "Proposal not found")
    if record["status"] != "proposed":
        raise HTTPException(
            status_code=409,
            detail=f"Proposal is {record['status']}; only "
                   "proposed proposals decide")
    proposal = WriteProposal.model_validate(record["record"])
    if proposal.mutation_type != "robot.execute":
        raise HTTPException(status_code=422, detail=
                            "not a robot execution proposal")
    try:
        _check(robot_id, proposal)
        request = request_write_approval(proposal)
        approval = decide_write(request, proposal,
                                body.response,
                                decided_by=body.decided_by)
    except (_Refused, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    status = "approved" if approval.approved else "rejected"
    _write_save(proposal, status, approval=approval)
    if approval.approved:
        try:
            _busy(robot_id)
        except _Refused as error:
            raise HTTPException(status_code=422,
                                detail=str(error))
    return _write_to_json(_write_load(body.proposal_id))


@app.post("/api/v1/robots/{robot_id}/telemetry")
def robot_telemetry(robot_id: str,
                    body: RobotTelemetryBody) -> dict:
    """Record telemetry and, with a cited stored observation,
    verify. Caller text alone never verifies."""
    from .robots import RobotRefusedError as _Refused
    from .robots import record_telemetry as _record
    from .robots import verify_action as _verify
    try:
        telemetry = _record(body.action_id, robot_id,
                            body.status, body.detail)
        if not body.observation_ref.strip():
            return {"telemetry": telemetry.model_dump(
                mode="json"), "verification": None,
                "note": "no cited observation supplied; "
                        "not verified"}
        return {"telemetry": telemetry.model_dump(mode="json"),
                "verification": _verify(
                    telemetry, body.observation_ref)}
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/drones", status_code=201)
def drone_register(body: DroneCreateBody) -> dict:
    from .drones import DroneRefusedError as _Refused
    from .drones import new_drone as _new
    from .drones import save_drone as _save
    try:
        drone = _new(
            body.name, capabilities=list(body.capabilities),
            home_location=body.home_location,
            provenance=_memory_provenance(
                dict(body.provenance))
            if body.provenance else None)
        _save(drone)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return drone.model_dump(mode="json")


@app.get("/api/v1/drones")
def drone_list() -> list[dict]:
    from .drones import list_drones as _list
    return [item.model_dump(mode="json") for item in _list()]


@app.post("/api/v1/drones/{drone_id}/mission")
def drone_mission(drone_id: str,
                  body: DroneMissionBody) -> dict:
    """One inert drone-mission proposal (mutation type
    drone.mission). Approval runs through the generic
    write-approval flow (exact YES + fingerprint +
    staleness); flight itself stays HARDWARE_REQUIRED."""
    from .drones import DroneRefusedError as _Refused
    from .drones import build_drone_proposal as _build
    try:
        proposal = _build(
            drone_id, body.kind, dict(body.params),
            body.actor, autonomous=body.autonomous,
            geofence=body.geofence,
            max_altitude_m=body.max_altitude_m)
        _write_save(proposal, "proposed")
    except (_Refused, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    return _write_to_json(_write_load(proposal.proposal_id))


@app.post("/api/v1/drones/{drone_id}/mission/approve")
def drone_mission_approve(drone_id: str,
                          body: DroneMissionApproveBody) -> dict:
    """Approve one stored drone proposal: exact YES only,
    fingerprint/staleness/target bound by the generic flow,
    plus a live recheck of safety state and capability."""
    from .drones import DroneRefusedError as _Refused
    from .drones import check_drone_state_for_approval as _check
    record = _write_load(body.proposal_id)
    if record is None:
        raise HTTPException(404, "Proposal not found")
    if record["status"] != "proposed":
        raise HTTPException(
            status_code=409,
            detail=f"Proposal is {record['status']}; only "
                   "proposed proposals decide")
    proposal = WriteProposal.model_validate(record["record"])
    if proposal.mutation_type != "drone.mission":
        raise HTTPException(status_code=422, detail=
                            "not a drone mission proposal")
    try:
        _check(drone_id, proposal)
        request = request_write_approval(proposal)
        approval = decide_write(request, proposal,
                                body.response,
                                decided_by=body.decided_by)
    except (_Refused, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    status = "approved" if approval.approved else "rejected"
    _write_save(proposal, status, approval=approval)
    return _write_to_json(_write_load(body.proposal_id))


@app.post("/api/v1/familiars", status_code=201)
def familiar_register(body: FamiliarCreateBody) -> dict:
    from .familiars import FamiliarRefusedError as _Refused
    from .familiars import new_familiar as _new
    from .familiars import save_familiar as _save
    try:
        familiar = _new(
            body.name, body.kind, linked_id=body.linked_id,
            provenance=_memory_provenance(
                dict(body.provenance))
            if body.provenance else None)
        _save(familiar)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return familiar.model_dump(mode="json")


@app.get("/api/v1/familiars")
def familiar_list() -> list[dict]:
    from .familiars import list_familiars as _list
    return [item.model_dump(mode="json") for item in _list()]


@app.post("/api/v1/twin/links", status_code=201)
def twin_link_create(body: TwinLinkBody) -> dict:
    from .twin import TwinRefusedError as _Refused
    from .twin import new_link as _new
    from .twin import save_link as _save
    try:
        link = _new(
            body.physical_ref, body.digital_ref,
            body.link_type, source=body.source,
            confidence=body.confidence,
            last_observed_at=body.last_observed_at,
            provenance=_memory_provenance(
                dict(body.provenance))
            if body.provenance else None)
        _save(link)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return link.model_dump(mode="json")


@app.get("/api/v1/twin/links")
def twin_link_list(status: str = "") -> list[dict]:
    from .twin import TwinRefusedError as _Refused
    from .twin import list_links as _list
    try:
        links = _list(status=status)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))
    return [item.model_dump(mode="json") for item in links]


@app.post("/api/v1/twin/links/{link_id}/observe")
def twin_link_observe(link_id: str) -> dict:
    from .twin import observe_link as _observe
    updated = _observe(link_id)
    if updated is None:
        raise HTTPException(404, "Twin link not found")
    return updated.model_dump(mode="json")


@app.get("/api/v1/twin/staleness")
def twin_staleness(stale_hours: float = 24.0) -> dict:
    from .twin import TwinRefusedError as _Refused
    from .twin import staleness_report as _report
    try:
        return _report(stale_hours=stale_hours)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


# =============================================================================
# JOBS (BIG #11-15, Phase 6). Named bounded runs: observable,
# retryable, cancellable, idempotent via run_key. No background
# threads; runs trigger via API.
# =============================================================================

@app.get("/api/v1/jobs")
def job_list() -> list[dict]:
    from .jobs import JOB_NAMES as _names
    return [{"job_name": name,
             "trigger": "POST /api/v1/jobs/run"}
            for name in _names]


@app.post("/api/v1/jobs/run", status_code=201)
def job_run(body: JobRunBody) -> dict:
    from .jobs import JobRefusedError as _Refused
    from .jobs import run_job as _run
    try:
        return _run(body.job_name, dict(body.params),
                    run_key=body.run_key)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.get("/api/v1/jobs/runs")
def job_runs(job_name: str = "", limit: int = 20) -> list[dict]:
    from .jobs import JobRefusedError as _Refused
    from .jobs import list_runs as _list
    try:
        return _list(job_name=job_name, limit=limit)
    except _Refused as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/jobs/runs/{run_id}/cancel")
def job_cancel(run_id: str) -> dict:
    from .jobs import cancel_run as _cancel
    return {"run_id": run_id,
            "cancelled": _cancel(run_id)}


# =============================================================================
# MAINTENANCE (BIG #16, Fase 4). Operator-triggered retention over
# log tables. dist_events, dist_conflicts and write_proposals
# are never pruned (sync cursors, live conflicts, approval
# lifecycle depend on them).
# =============================================================================

@app.post("/api/v1/maintenance/prune")
def maintenance_prune() -> dict:
    """Run deterministic retention passes. Returns per-table
    removed counts plus the excluded tables."""
    from .retention import run_retention as _run
    return _run()


@app.post("/api/v1/maintenance/sweep-leases")
def maintenance_sweep_leases() -> dict:
    """Recover expired task + desktop-action leases without waiting
    for a claim call. Calls only the existing expiry functions, so
    the exact claim-path rules apply: requeue below MAX_ATTEMPTS,
    fail at the limit, block physical-uncertain tasks, recover
    dispatched actions to approved (block when attempts are
    exhausted). Conditional updates make repeated sweeps safe.
    Creates nothing, executes nothing, extends no lease.
    Same convention as maintenance/prune: operator-triggered,
    loopback-bound server, no per-endpoint auth layer."""
    return {"tasks": expire_leases(),
            "desktop_actions": expire_desktop_leases()}


@app.get("/workshop/graph", response_class=HTMLResponse)
async def workshop_graph_page(entity_id: str = "", depth: int = 1,
                              show: str = "missions,nodes"):
    """Living Workshop graph: same explorer as /world.
    Server data, vanilla SVG + JS, bounded depth 1|2."""
    from . import ui as _ui
    import json as _json
    flags = {part.strip() for part in show.split(",")}
    graph, error = ({"nodes": [], "edges": []}, "")
    if entity_id:
        graph, error = await _graph_data(entity_id, depth,
                                         flags)
    main = f"""<h1>Living Workshop — Graph</h1>
    <p class="muted">The full explorer lives at <a href="/world">/world</a> — same data, same grammar. WORLD (INVENTory) entities render solid; Mycelium overlays dashed.</p>
    {_ui.graph_panel(_json.dumps(graph), "/workshop/graph", entity_id, depth, show, error)}"""
    return _ui.shell("Workshop Graph", "/workshop/graph", main,
                     "", _ui.command_bar())


# =============================================================================
# WORLD GRAPH (BIG #4) — uniform projection, no new source of truth.
# =============================================================================

@app.get("/api/v1/graph")
async def world_graph_unified(entity_id: str, depth: int = 1,
                              include_missions: bool = False,
                              include_observations: bool = False,
                              include_fabrication: bool = False,
                              fabrication_id: str = "",
                              include_nodes: bool = False,
                              include_printers: bool = False,
                              include_knowledge: bool = False,
                              include_conversations: bool = False,
                              truth: str = "all",
                              source: str = "all",
                              kind: str = "all",
                              since: str = "") -> dict:
    try:
        with connection() as db:
            agent_rows = db.execute(
                "SELECT node_id, capabilities FROM nodes").fetchall()
        agents = [{"node_id": row["node_id"],
                    "capabilities": load(row["capabilities"])}
                    for row in agent_rows]
        observations = ([obs.model_dump(mode="json")
                         for obs in _recent_observations(20)]
                        if include_observations else None)
        fabrication = (_fabrication_overlay(fabrication_id)
                       if include_fabrication else None)
        registry_nodes = (list_nodes()
                          if include_nodes else None)
        printers = ([device.model_dump(mode="json")
                     for device in list_stored_printers()]
                    if include_printers else None)
        memories = None
        candidates = None
        conversations = None
        if include_knowledge:
            try:
                from .memory import list_memories
                memories = [entry.model_dump(mode="json")
                            for entry in list_memories(limit=60)]
            except Exception:
                memories = None
            try:
                from .knowledge import list_candidates
                candidates = [entry.model_dump(mode="json")
                              for entry in list_candidates(limit=60)]
            except Exception:
                candidates = None
        if include_conversations:
            try:
                from .conversation_bridge import list_imports
                conversations = list_imports(limit=20)
            except Exception:
                conversations = None
        graph = await build_world_graph(
            _world_reader(), entity_id, depth,
            include_missions=include_missions, agent_nodes=agents,
            observations=observations, fabrication=fabrication,
            registry_nodes=registry_nodes, printers=printers,
            memories=memories, candidates=candidates,
            conversations=conversations, truth=truth,
            source=source, kind=kind, since=since)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except InventoryRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except InventoryUnavailable:
        raise HTTPException(status_code=502, detail="INVENTory unavailable")
    return graph


# =============================================================================
# EXPLICIT TRANSLATION (M8.5) — approved proposal to CoordinatorTask.
# Stateless like M8.4: the operator supplies the full proposal, its
# ApprovalResult and the fingerprint recorded at approval time. Conversion
# runs exclusively through the existing M6.4 proposal_to_task(). The result
# carries status "approved" only: no queue, no staging, no promotion,
# no dispatch, no executor, no DB writes.
# =============================================================================

@app.post("/api/v1/tasks/from-proposal", response_model=CoordinatorTask)
def task_from_proposal(body: TaskFromProposalBody) -> CoordinatorTask:
    try:
        task = proposal_to_task(
            body.proposal, body.approval, task_id=body.task_id,
            task_type=body.task_type, input=body.input,
            approved_fingerprint=body.approved_fingerprint)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    logger.info("task_translated task_id=%s proposal_id=%s type=%s",
                task.task_id, task.proposal_id, task.task_type)
    return task


# =============================================================================
# CONTROLLED WRITES + VERIFICATION (BIG #5) — proposal to verified change.
# Flow: propose (inert) -> exact-YES approval (bound by fingerprint) ->
# execute (revalidated, allow-listed mutation only) -> independent
# verification (readback, never the result payload). Approval is
# permission, verification is truth; neither implies the other.
# The INVENTory read bridge above stays read-only; writes below use
# the separate InventoryWriter capability. No SQL, no shell, no
# arbitrary HTTP writes, no push/force anywhere in this section.
# =============================================================================

def _write_save(proposal: WriteProposal, status: str,
                approval: WriteApproval | None = None,
                result: WriteResult | None = None,
                verification=None) -> None:
    init_chat_database()
    with chat_connection() as db:
        db.execute(
            """INSERT INTO write_proposals
            (proposal_id, record, status, approval, result, verification,
             created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(proposal_id) DO UPDATE SET record=excluded.record,
            status=excluded.status, approval=excluded.approval,
            result=excluded.result, verification=excluded.verification,
            updated_at=excluded.updated_at""",
            (proposal.proposal_id,
             dump(proposal.model_dump(mode="json")), status,
             dump(approval.model_dump(mode="json") if approval else {}),
             dump(result.model_dump(mode="json") if result else {}),
             dump(verification.model_dump(mode="json")
                  if verification else {}),
             proposal.created_at, now()))


def _write_load(proposal_id: str) -> dict | None:
    init_chat_database()
    with chat_connection() as db:
        row = db.execute(
            "SELECT * FROM write_proposals WHERE proposal_id=?",
            (proposal_id,)).fetchone()
    if row is None:
        return None
    record = dict(row)
    for key in ("record", "approval", "result", "verification"):
        try:
            record[key] = load(record[key]) if record[key] else {}
        except ValueError:
            record[key] = {}
    return record


def _write_to_json(record: dict) -> dict:
    proposal = WriteProposal.model_validate(record["record"])
    return {
        "proposal": proposal.model_dump(mode="json"),
        "fingerprint": write_fingerprint(proposal),
        "status": record["status"],
        "approval": record["approval"] or None,
        "result": record["result"] or None,
        "verification": record["verification"] or None,
    }


@app.post("/api/v1/writes/inventory", status_code=201)
def write_propose_inventory(body: InventoryWriteBody) -> dict:
    import secrets as _secrets
    proposal_id = (body.proposal_id
                   or f"wrt-{_secrets.token_hex(4)}")
    try:
        proposal = propose_inventory_write(
            proposal_id, body.mutation, body.entity_type,
            dict(body.fields), entity_id=body.entity_id,
            actor=body.actor)
    except InventoryWriteRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    _write_save(proposal, "proposed")
    logger.info("write_proposed proposal_id=%s type=%s",
                proposal.proposal_id, proposal.mutation_type)
    return _write_to_json(_write_load(proposal.proposal_id))


@app.post("/api/v1/writes/git-commit", status_code=201)
def write_propose_git(body: GitCommitBody) -> dict:
    import secrets as _secrets
    proposal_id = (body.proposal_id
                   or f"wrt-{_secrets.token_hex(4)}")
    try:
        proposal = propose_git_commit(
            proposal_id, body.repository, body.branch,
            body.expected_head, body.message, list(body.files),
            changeset_fingerprint=body.changeset_fingerprint,
            actor=body.actor)
    except GitWriteRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    _write_save(proposal, "proposed")
    logger.info("write_proposed proposal_id=%s type=git.commit",
                proposal.proposal_id)
    return _write_to_json(_write_load(proposal.proposal_id))


@app.get("/api/v1/writes/{proposal_id}")
def write_get(proposal_id: str) -> dict:
    record = _write_load(proposal_id)
    if record is None:
        raise HTTPException(404, "Write proposal not found")
    return _write_to_json(record)


@app.post("/api/v1/writes/{proposal_id}/approve")
def write_approve(proposal_id: str, body: WriteDecisionBody) -> dict:
    record = _write_load(proposal_id)
    if record is None:
        raise HTTPException(404, "Write proposal not found")
    if record["status"] != "proposed":
        raise HTTPException(
            status_code=409,
            detail=f"Write is {record['status']}; only proposed writes decide")
    proposal = WriteProposal.model_validate(record["record"])
    request = request_write_approval(proposal)
    try:
        approval = decide_write(request, proposal, body.response,
                                decided_by=body.decided_by)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    status = "approved" if approval.approved else "rejected"
    _write_save(proposal, status, approval=approval)
    logger.info("write_decided proposal_id=%s decision=%s",
                proposal_id, approval.decision)
    emit_event("approval.resolved",
               f"Write {proposal_id} {approval.decision}",
               proposal_id=proposal_id)
    return _write_to_json(_write_load(proposal_id))


async def _write_execute_record(record: dict) -> WriteResult:
    """Execute one stored, approved proposal and persist the result."""
    proposal = WriteProposal.model_validate(record["record"])
    approval = WriteApproval.model_validate(record["approval"])
    if proposal.mutation_type in ("robot.execute",
                                  "drone.mission"):
        raise PrintRefusedError(
            f"Mutation '{proposal.mutation_type}' has no "
            "executor: physical-agent execution is "
            "HARDWARE_REQUIRED and never runs from the "
            "generic write path")
    if proposal.mutation_type == "git.commit":
        return execute_git_commit(proposal, approval)
    if proposal.mutation_type == "printer.execute":
        payload = proposal.payload
        device = load_printer(
            payload.get("printer_id", ""))
        if device is None:
            raise PrintRefusedError(
                f"Printer '{payload.get('printer_id', '')}' "
                "unknown; refusing motion")
        return execute_print(
            proposal, approval, device=device,
            adapter=adapter_for_printer(device.printer_id),
            safety_verdict=str(payload.get("safety_verdict",
                                           "inconclusive")))
    return await execute_inventory_write(
        proposal, approval, reader=_world_reader(),
        writer=InventoryWriter())


@app.post("/api/v1/writes/{proposal_id}/execute")
async def write_execute(proposal_id: str) -> dict:
    record = _write_load(proposal_id)
    if record is None:
        raise HTTPException(404, "Write proposal not found")
    if record["result"]:
        return _write_to_json(record)
    if record["status"] != "approved":
        raise HTTPException(
            status_code=409,
            detail=f"Write is {record['status']}; only approved writes execute")
    proposal = WriteProposal.model_validate(record["record"])
    approval = WriteApproval.model_validate(record["approval"])
    try:
        result = await _write_execute_record(record)
    except (InventoryWriteRefusedError, GitWriteRefusedError,
            ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error))
    except (InventoryWriteFailedError, GitWriteFailedError) as error:
        raise HTTPException(status_code=502, detail=str(error))
    status = ("executed" if result.outcome == "executed"
              else result.outcome)
    _write_save(proposal, status, approval=approval, result=result)
    logger.info("write_executed proposal_id=%s outcome=%s",
                proposal_id, result.outcome)
    return _write_to_json(_write_load(proposal_id))


def _verification_request_for(proposal: WriteProposal,
                              result: WriteResult):
    if proposal.mutation_type == "inventory.create":
        fields = proposal.payload.get("fields", {})
        entity_type = proposal.payload.get("entity_type", "")
        entity_id = str(result.after.get("entity_id", ""))
        expected: dict = {"kind": "entity",
                          "entity_type": entity_type,
                          "entity_id": entity_id}
        for key in ("name", "description", "quantity", "status"):
            if key in fields:
                expected[key] = fields[key]
        return new_verification_request(
            proposal.proposal_id, result.fingerprint,
            "inventory.readback", expected)
    if proposal.mutation_type == "inventory.update":
        fields = proposal.payload.get("fields", {})
        expected = {"kind": "entity",
                    "entity_type": proposal.payload.get("entity_type", ""),
                    "entity_id": proposal.payload.get("entity_id", "")}
        for key in ("name", "description", "quantity", "status"):
            if key in fields:
                expected[key] = fields[key]
        return new_verification_request(
            proposal.proposal_id, result.fingerprint,
            "inventory.readback", expected)
    if proposal.mutation_type == "inventory.create_relationship":
        fields = proposal.payload.get("fields", {})
        return new_verification_request(
            proposal.proposal_id, result.fingerprint,
            "inventory.graph_readback",
            {"kind": "relationship",
             "from_id": fields.get("from_id", ""),
             "predicate": fields.get("predicate", ""),
             "to_id": fields.get("to_id", "")})
    if proposal.mutation_type == "git.commit":
        payload = proposal.payload
        return new_verification_request(
            proposal.proposal_id, result.fingerprint, "git.readback",
            {"kind": "commit",
             "repository": payload.get("repository", ""),
             "branch": payload.get("branch", ""),
             "parent": payload.get("expected_head", "")})
    if proposal.mutation_type == "printer.execute":
        payload = proposal.payload
        return new_telemetry_request(
            proposal.proposal_id, result.fingerprint,
            str(payload.get("gcode_sha256", "")))
    raise ValueError(
        f"Mutation '{proposal.mutation_type}' has no verification path")


@app.post("/api/v1/writes/{proposal_id}/verify")
async def write_verify(proposal_id: str) -> dict:
    record = _write_load(proposal_id)
    if record is None:
        raise HTTPException(404, "Write proposal not found")
    if not record["result"]:
        raise HTTPException(
            status_code=409, detail="Write has no result yet; execute first")
    if record["verification"]:
        return _write_to_json(record)
    proposal = WriteProposal.model_validate(record["record"])
    result = WriteResult.model_validate(record["result"])
    approval = WriteApproval.model_validate(record["approval"])
    try:
        request = _verification_request_for(proposal, result)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        if proposal.mutation_type == "git.commit":
            verification = verify_git_commit(request, result)
        elif proposal.mutation_type == "printer.execute":
            verification = verify_print_telemetry(request, result)
        else:
            verification = await verify_inventory_write(
                request, result, reader=_world_reader())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except InventoryWriteFailedError as error:
        raise HTTPException(status_code=502, detail=str(error))
    _write_save(proposal, record["status"], approval=approval,
                result=result, verification=verification)
    logger.info("write_verified proposal_id=%s outcome=%s",
                proposal_id, verification.outcome)
    return _write_to_json(_write_load(proposal_id))


@app.get("/api/v1/project/package")
async def project_package_route(q: str = "",
                                conversation_id: str = "") -> dict:
    """Bounded project-aware context: identity, related entities,
    missions, events, git. Read-only; never file contents, never
    secrets, never a permission."""
    from .missions import list_events as _list_events
    from .missions import list_missions as _list_missions
    try:
        project = default_context()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    missions: list = []
    events: list[dict] = []
    if conversation_id:
        try:
            missions = _list_missions(conversation_id, limit=5)
        except ValueError:
            missions = []
        try:
            events = [event.model_dump(mode="json") for event in
                      _list_events(conversation_id=conversation_id,
                                   limit=10)]
        except ValueError:
            events = []
    git: dict = {}
    try:
        root = _project_root(None)
        git = git_status(root)
        git["branch"] = git_branch(root)["branch"]
    except (GitRefusedError, GitUnavailable, ValueError):
        git = {}
    try:
        package = await assemble_project_package(
            project, _world_reader(), query=q,
            missions=missions, events=events, git=git)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    package["summary"] = summarize_for_chat(package)
    return package


async def _run_write_step(mission, step) -> dict:
    """Mission write-step capability: approved stored proposal ->
    execute (once) -> verify. Anything unapproved, stale or
    mismatched BLOCKs; the executor maps the dict to step state."""
    proposal_id = str(step.parameters.get("proposal_id", ""))
    record = _write_load(proposal_id)
    if record is None:
        raise ExecutorError(
            f"Write '{proposal_id}' unknown; writes need a stored, "
            "approved proposal")
    if record["status"] not in ("approved", "executed", "failed",
                                "blocked"):
        return {"status": "blocked",
                "result_text": f"Write '{proposal_id}' is "
                               f"{record['status']}; explicit human "
                               "approval required first.",
                "verification": "no approval; no verification",
                "verified": False}
    proposal = WriteProposal.model_validate(record["record"])
    try:
        check_binding = proposal.proposal_id
    except AttributeError as error:  # pragma: no cover - defensive
        raise ExecutorError(f"Write binding broken: {error}") from error
    if check_binding != proposal_id:
        raise ExecutorError("Write binding mismatch; refusing")
    if not record["result"]:
        try:
            result = await _write_execute_record(record)
        except (InventoryWriteRefusedError, GitWriteRefusedError,
                ValueError) as error:
            raise ExecutorError(str(error)) from error
        except (InventoryWriteFailedError,
                GitWriteFailedError) as error:
            raise ExecutorError(str(error)) from error
        approval = WriteApproval.model_validate(record["approval"])
        status = ("executed" if result.outcome == "executed"
                  else result.outcome)
        _write_save(proposal, status, approval=approval, result=result)
        record = _write_load(proposal_id)
        result = WriteResult.model_validate(record["result"])
    else:
        result = WriteResult.model_validate(record["result"])
    if result.outcome != "executed":
        return {"status": result.outcome,
                "result_text": f"Write '{proposal_id}' "
                               f"{result.outcome}: {result.error[:500]}",
                "verification": "no execution; no verification",
                "verified": False}
    if not record["verification"]:
        approval = WriteApproval.model_validate(record["approval"])
        request = _verification_request_for(proposal, result)
        if proposal.mutation_type == "git.commit":
            verification = verify_git_commit(request, result)
        else:
            verification = await verify_inventory_write(
                request, result, reader=_world_reader())
        _write_save(proposal, record["status"], approval=approval,
                    result=result, verification=verification)
        record = _write_load(proposal_id)
    verification_data = record["verification"] or {}
    outcome = str(verification_data.get("outcome", "inconclusive"))
    note = str(verification_data.get("note", ""))
    verified = outcome == "passed"
    return {"status": "completed",
            "result_text": f"Write '{proposal_id}' {result.outcome}.",
            "verification": f"{outcome}: {note}",
            "verified": verified}


@app.get("/", response_class=HTMLResponse)
async def dashboard(entity_id: str = "") -> str:
    """Living World home: the world graph at the center,
    missions/nodes/notifications around it, chat below.
    Same data as the old dashboard, grown into a place."""
    from . import ui as _ui
    import json as _json
    graph: dict = {"nodes": [], "edges": []}
    error = ""
    if entity_id:
        graph, error = await _graph_data(entity_id, 1,
                                         {"missions", "nodes"})
    seeds = await _world_seeds()
    with connection() as db:
        node_rows = db.execute(
            f"SELECT {NODE_PUBLIC_COLUMNS} FROM nodes ORDER BY last_seen DESC LIMIT 12").fetchall()
        task_rows = db.execute(
            "SELECT id, kind, status, assigned_node_id FROM tasks ORDER BY id DESC LIMIT 8").fetchall()
    nodes = [_node_to_json(row) for row in node_rows]
    try:
        missions = list_missions(limit=6)
    except ValueError:
        missions = []
    notes = list_notifications_for_report(limit=8)
    try:
        status = coordinator_status()
    except ValueError:
        status = {}
    seed_chips = "".join(
        f"<a class=\"chip\" href=\"/?entity_id={_ui.esc(item['id'])}\">{_ui.esc(item['label'])}</a>"
        for item in seeds) or _ui.empty("INVENTory unreachable — start it on :8080.")
    mission_cards = "".join(
        f"<div class=\"sprout\"><b>{_ui.esc(mission.goal[:80])}</b><br>"
        f"{_ui.status_dot(mission.status)}{_ui.chip(mission.status)}"
        f"<br><a href=\"/missions/{_ui.esc(mission.mission_id)}\">Open mission</a></div>"
        for mission in missions) or _ui.empty("No missions yet.")
    node_rows_html = "".join(
        f"<tr><td>{_ui.status_dot(record.get('derived_status', ''))}{_ui.esc(record['node_id'])}</td>"
        f"<td>{_ui.esc(record.get('tier', ''))}</td>"
        f"<td style=\"white-space:nowrap\">{_ui.esc(str(record.get('last_seen', ''))[:10])}</td></tr>"
        for record in nodes) or "<tr><td colspan='3'>No nodes yet.</td></tr>"
    note_items = "".join(
        f"<li>{_ui.esc(item.title)}</li>" for item in notes)
    task_items = "".join(
        f"<li>{_ui.status_dot(row['status'])}{_ui.esc(row['kind'])} "
        f"<span class=\"muted\">#{row['id']} · {_ui.esc(row['status'])}"
        f"{' → ' + _ui.esc(row['assigned_node_id']) if row['assigned_node_id'] else ''}</span></li>"
        for row in task_rows)
    main = f"""<h1>Living World</h1>
    <p class="muted">The graph is the center. Everything around it supports it. Memory lives at <a href="/memory">/memory</a>. New: <a href="/guide">Guide</a> · <a href="/craft">Craft Tree</a> · <a href="/symbiosis">Symbiosis</a> — one living workshop, no loose pages.</p>
    {_guide_panel()}
    {_ui.graph_panel(_json.dumps(graph), "/", entity_id, 1, "missions,nodes", error) if entity_id else ""}
    <h2>Grow from a seed</h2><p class="flowline">{seed_chips}</p>
    <p class="muted">Pick a seed to open its craft tree and symbioses: every seed links to <a href="/craft">/craft</a> and <a href="/symbiosis">/symbiosis</a>.</p>
    <h2>Active missions</h2><div class="grove">{mission_cards}</div>
    <h2>Recent Tasks</h2><ul>{task_items or "<li>No tasks yet.</li>"}</ul>"""
    context = _ui.context_block(
        "Nodes",
        f"<table><tr><th>Node</th><th>Tier</th><th>Seen</th></tr>{node_rows_html}</table>") + \
        _ui.context_block("Status", _ui.kv_list([
            ("coordinator", status.get("coordinator", "?")),
            ("nodes online", str((status.get("nodes") or {}).get("online", "?"))),
            ("pending approvals", str(sum((status.get("pending_approvals") or {}).values()) if isinstance(status.get("pending_approvals"), dict) else "?"))])) + \
        _ui.context_block("Notifications", f"<ul>{note_items or '<li>Quiet.</li>'}</ul>")
    return _ui.shell("Living World", "/", _ui.living_bg() + main,
                     context,
                     _ui.command_bar())


def _guide_panel() -> str:
    """Home guide strip: WHAT/WHY/NEXT from live state."""
    from . import ui as _ui
    try:
        from .guide import guide_items
        items = guide_items(limit=3)
    except Exception:
        items = []
    if not items:
        return ("<div class=\"panel living\"><h2>Guide</h2>"
                "<p class=\"muted\">🌱 Your world is quiet. "
                "<a href=\"/guide\">Open the guide</a> for "
                "first seeds.</p></div>")
    cards = "".join(_ui.guide_card(item) for item in items)
    return (f"<div class=\"panel living\"><h2>Guide — "
            f"where the world needs you</h2>"
            f"<div class=\"grove\">{cards}</div>"
            f"<p><a href=\"/guide\">All guide items →</a></p></div>")


def _research_runs(limit: int = 20) -> list:
    """Recent research runs for the world-graph overlay."""
    from .research_engine import list_runs
    try:
        return list_runs(limit=limit)
    except Exception:
        return []


def _last_flow_panel() -> str:
    """Latest command flow as INTENT → CONTEXT → RESULT steps.
    Read-only history; empty when nothing ran yet."""
    from . import ui as _ui
    try:
        from .context_engine import recent_traces
        traces = recent_traces(limit=1)
    except Exception:
        traces = []
    if not traces:
        return ""
    trace = traces[0]
    steps = "".join(
        f"<span class=\"step done\">{_ui.esc(str(step.get('stage', '')))}"
        f": {_ui.esc(str(step.get('detail', ''))[:80])}</span>"
        for step in trace.get("steps", [])[:6])
    return (
        "<div class=\"panel\"><h2>Last flow</h2>"
        f"<p class=\"muted\">“{_ui.esc(trace.get('intent', ''))}” · "
        f"{_ui.esc(str(trace.get('created_at', ''))[:16])}</p>"
        f"<div class=\"path\" aria-label=\"Last command flow\">"
        f"{steps}</div></div>")


async def _graph_data(entity_id: str, depth: int,
                      flags: set, filters: dict | None = None) -> tuple:
    """Shared graph builder for /, /world, /workshop/graph."""
    from .worldgraph import GRAPH_DEPTHS
    graph: dict = {"nodes": [], "edges": []}
    error = ""
    selected = dict(filters or {})

    def _overlay_memories() -> list[dict] | None:
        if "memory" not in flags and "knowledge" not in flags:
            return None
        try:
            from .memory import list_memories
            return [entry.model_dump(mode="json")
                    for entry in list_memories(limit=60)]
        except Exception:
            return None

    def _overlay_candidates() -> list[dict] | None:
        if "knowledge" not in flags and "candidates" not in flags:
            return None
        try:
            from .knowledge import list_candidates
            return [entry.model_dump(mode="json")
                    for entry in list_candidates(limit=60)]
        except Exception:
            return None

    def _overlay_conversations() -> list[dict] | None:
        if "conversations" not in flags and \
                "knowledge" not in flags:
            return None
        try:
            from .conversation_bridge import list_imports
            return list_imports(limit=20)
        except Exception:
            return None

    def _overlay_intel() -> list[dict] | None:
        if "intel" not in flags:
            return None
        try:
            from .conversation_intel import list_intel
            return list_intel(limit=40)
        except Exception:
            return None

    try:
        clean_depth = depth if depth in GRAPH_DEPTHS else 1
        graph = await build_world_graph(
            _world_reader(), entity_id, clean_depth,
            include_missions="missions" in flags,
            agent_nodes=[{"node_id": row["node_id"],
                          "capabilities": row["capabilities"]}
                         for row in list_nodes()]
            if "nodes" in flags else None,
            observations=([obs.model_dump(mode="json")
                           for obs in _recent_observations(10)]
                          if "observations" in flags else None),
            registry_nodes=list_nodes()
            if "nodes" in flags else None,
            printers=([device.model_dump(mode="json")
                       for device in list_stored_printers()]
                      if "printers" in flags else None),
            research_runs=([run.model_dump(mode="json")
                            for run in _research_runs(20)]
                           if "research" in flags else None),
            memories=_overlay_memories(),
            candidates=_overlay_candidates(),
            conversations=_overlay_conversations(),
            intel=_overlay_intel(),
            truth=str(selected.get("truth", "all")),
            source=str(selected.get("source", "all")),
            kind=str(selected.get("kind", "all")),
            since=str(selected.get("since", "")),
            # BIG #39: Hardware Reality Layer overlays from the
            # node registry (node-reported runtime state, never
            # world truth).
            include_hardware="hardware" in flags,
            include_compute="compute" in flags)
    except (ValueError, InventoryRefusedError) as exc:
        error = str(exc)
    except InventoryUnavailable:
        error = "INVENTory unavailable"
    return graph, error


async def _world_seeds() -> list:
    """Bounded project/object chips to grow the graph from.
    Human titles where the bridge provides them, short ids
    otherwise — never raw 40-char identifiers."""
    seeds = []
    try:
        for kind in ("projects", "objects"):
            browsed = await _world_reader().browse(kind)
            for record in (browsed.results or [])[:8]:
                title = record.entity_id
                details = record.details \
                    if isinstance(record.details, dict) else {}
                for key in ("name", "title", "goal",
                            "description"):
                    if details.get(key):
                        title = str(details[key])[:40]
                        break
                else:
                    title = record.entity_id[:12] + "…"
                seeds.append({"id": record.entity_id,
                              "label": f"{kind[:-1]}: {title}"})
    except (InventoryRefusedError, InventoryUnavailable,
            ValueError, AttributeError):
        pass
    return seeds[:12]


def _world_hud_html() -> str:
    """Lightweight world HUD (BIG #44): current campaign /
    quest, attention, nodes, active work, discoveries. Only
    values that exist — never scores. Best-effort."""
    from . import ui as _ui
    try:
        from .world import world_hud
        hud = world_hud()
    except Exception:
        return ""
    cells = []
    campaign = hud.get("campaign", {}) or {}
    if campaign.get("title"):
        cells.append(
            f"<div class=\"hud-cell\"><small>CAMPAIGN</small><br>"
            f"<a href=\"{_ui.esc(campaign.get('href', '/campaigns'))}\">"
            f"{_ui.esc(campaign['title'])}</a> "
            f"{_ui.esc(campaign.get('progress', ''))}</div>")
    quest = hud.get("quest", {}) or {}
    if quest.get("title"):
        cells.append(
            f"<div class=\"hud-cell\"><small>QUEST</small><br>"
            f"<a href=\"{_ui.esc(quest.get('href', '/quests'))}\">"
            f"{_ui.esc(quest['title'])}</a> "
            f"{_ui.esc(quest.get('progress', ''))}</div>")
    attention = hud.get("attention", {}) or {}
    if any(attention.get(key, 0) for key in
           ("needs", "waiting", "discovered", "offline")):
        cells.append(
            f"<div class=\"hud-cell\"><small>ATTENTION</small><br>"
            f"<a href=\"/presence\">"
            f"{attention.get('needs', 0)} needs · "
            f"{attention.get('waiting', 0)} waiting · "
            f"{attention.get('discovered', 0)} discovered · "
            f"{attention.get('offline', 0)} quiet</a></div>")
    nodes = hud.get("nodes", {}) or {}
    if nodes.get("total"):
        cells.append(
            f"<div class=\"hud-cell\"><small>NODES</small><br>"
            f"<a href=\"/nodes\">{nodes.get('awake', 0)}/"
            f"{nodes.get('total', 0)} awake</a></div>")
    work = hud.get("work", {}) or {}
    if work.get("busy_nodes"):
        cells.append(
            f"<div class=\"hud-cell\"><small>ACTIVE WORK</small><br>"
            f"<a href=\"/activity\">{work.get('busy_nodes', 0)} "
            f"node(s) busy</a></div>")
    discoveries = hud.get("discoveries", {}) or {}
    if discoveries.get("open"):
        cells.append(
            f"<div class=\"hud-cell\"><small>DISCOVERIES</small><br>"
            f"<a href=\"/symbiosis\">{discoveries.get('open', 0)} "
            f"open</a></div>")
    if not cells:
        return ""
    return ("<div class=\"panel hud\" role=\"status\" "
            "aria-label=\"World summary\">"
            "<div class=\"hud-row\">" + "".join(cells) +
            "</div></div>")


def _world_objects_html() -> str:
    """World-object shelf (BIG #44): NODE/PROJECT/MACHINE/
    ENERGY/CAMPAIGN/CRAFT/DISCOVERY/SYMBIOSIS/RESEARCH cards
    with state, trust, activity, href + text. Best-effort."""
    from . import ui as _ui
    try:
        from .world import world_objects
        objects = world_objects(limit=12)
    except Exception:
        return ""
    if not objects:
        return ""
    cards = []
    for item in objects:
        trust = (f" · trust {_ui.esc(item['trust'])}"
                 if item.get("trust") else "")
        attention = (f" · <b>{_ui.esc(item['attention'])}</b>"
                     if item.get("attention") else "")
        activity = (f"<br><small class=\"muted\">"
                    f"{_ui.esc(item['activity'])}</small>"
                    if item.get("activity") else "")
        cards.append(
            f"<div class=\"sprout wobject kind-"
            f"{_ui.esc(item['kind'].lower())}\">"
            f"<b>{_ui.esc(item['glyph'])} "
            f"{_ui.esc(item['label'])}</b> "
            f"<span class=\"muted\">"
            f"{_ui.esc(item['kind'])} · "
            f"{_ui.esc(item['state'])}{trust}{attention}</span>"
            f"{activity}<br>"
            f"<a href=\"{_ui.esc(item['href'])}\">Open →</a>"
            f"<span class=\"sr\">{_ui.esc(item['text'])}</span>"
            f"</div>")
    return ("<div class=\"panel\"><h2>World objects</h2>"
            "<p class=\"muted\">Every object is a real record — "
            "open it to reach entity, campaign, quest, guide, "
            "craft, symbiosis or evidence. No decoration without "
            "a destination.</p>"
            "<div class=\"grove\">" + "".join(cards) +
            "</div></div>")


async def _world_symbiosis_html(entity_id: str) -> str:
    """Symbiosis network tree (BIG #44): PROJECT with branch
    children carrying state + strength + href. Best-effort."""
    from . import ui as _ui
    try:
        from .world import symbiosis_network, symbiosis_seedlings
    except Exception:
        return ""
    network = None
    if entity_id:
        try:
            network = await symbiosis_network(
                entity_id, limit=12)
        except ValueError:
            return ("<div class=\"panel\"><p>Unknown entity — "
                    "use a prefix_id like proj_….</p></div>")
        except Exception:
            network = None
    if network and network.get("children"):
        branches = []
        for child in network["children"]:
            strength = child.get("strength", "seedling")
            branches.append(
                f"<li><span class=\"strength {strength}\">"
                f"</span> <b>"
                f"{_ui.esc(child.get('group', ''))}</b> "
                f"<a href=\"{_ui.esc(child['href'])}\">"
                f"{_ui.esc(child['entity_id'][:60])}</a> "
                f"<span class=\"muted\">"
                f"{_ui.esc(child.get('predicate', ''))} · "
                f"{_ui.esc(child.get('state', ''))} "
                f"({strength})</span></li>")
        counts = network.get("counts", {})
        return (
            f"<div class=\"panel\"><h2>Symbiosis network</h2>"
            f"<p><b>{_ui.esc(network['root'][:60])}</b> "
            f"<span class=\"muted\">{counts.get('verified', 0)} "
            f"established · {counts.get('supported', 0)} "
            f"growing · {counts.get('proposed', 0)} "
            f"seedlings</span></p>"
            f"<ul class=\"symtree\">{''.join(branches)}</ul>"
            f"<p><a href=\"/symbiosis?entity_id="
            f"{_ui.esc(network['root'])}\">Full symbiosis →</a>"
            f"</p></div>")
    try:
        seedlings = symbiosis_seedlings(limit=6)
    except Exception:
        return ""
    if not seedlings:
        return ""
    rows = "".join(
        f"<li><span class=\"strength seedling\"></span> "
        f"<a href=\"{_ui.esc(seed['href'])}\">"
        f"{_ui.esc(seed['entity_id'][:80])}</a> "
        f"<span class=\"muted\">seedling — uncertain until "
        f"reviewed</span></li>" for seed in seedlings)
    return (f"<div class=\"panel\"><h2>Symbiosis network</h2>"
            f"<p class=\"muted\">Open seedlings waiting for "
            f"review — pick an entity above to grow its "
            f"network.</p><ul class=\"symtree\">{rows}</ul>"
            f"</div>")


async def _world_craft_html(entity_id: str) -> str:
    """Craft world chain (BIG #44): vertical IDEA→…→PROJECT
    with evidence states for the focused entity. Best-effort."""
    from . import ui as _ui
    if not entity_id:
        return ""
    try:
        from .craft import craft_tree, stage_states
        tree = await craft_tree(entity_id, 1)
        states = {entry["key"]: entry
                  for entry in stage_states(tree)}
    except Exception:
        return ""
    stops = []
    for stage in tree.get("stages", []):
        entry = states.get(stage.get("key", ""), {})
        glyph = entry.get("glyph", "○")
        word = entry.get("state", "missing")
        stops.append(
            f"<div class=\"trail-stop trail-{_ui.esc(word)}\">"
            f"<span class=\"trail-glyph\">{_ui.esc(glyph)}</span> "
            f"<b>{_ui.esc(stage.get('title', ''))}</b> "
            f"<span class=\"muted\">{_ui.esc(word)}</span>"
            f"</div>")
    if not stops:
        return ""
    return (
        f"<div class=\"panel\"><h2>Craft world</h2>"
        f"<p class=\"muted\">Growth: "
        f"{_ui.esc(tree.get('growth', 'seed'))} — ✓ evidence, "
        f"● active, ○ missing, ! blocked. Never invented.</p>"
        f"<div class=\"trail\">" +
        "<div class=\"trail-link\">↓</div>".join(stops) +
        f"</div><p><a href=\"/craft?entity_id="
        f"{_ui.esc(entity_id)}\">Open craft tree →</a></p></div>")


def _world_campaign_html() -> str:
    """Campaigns as world progression (BIG #44): title,
    current, next, blocked, progress — all from live campaign
    state. Best-effort."""
    from . import ui as _ui
    try:
        from .campaigns import list_campaign_details
        campaigns = list_campaign_details(limit=3)
    except Exception:
        return ""
    if not campaigns:
        return ""
    cards = []
    for campaign in campaigns:
        current = campaign.get("current_quest", {}) or {}
        nxt = campaign.get("next_action", {}) or {}
        blocked = campaign.get("blocked_count", 0)
        cards.append(
            f"<div class=\"sprout campaign\">"
            f"<b>🌱 {_ui.esc(campaign.get('title', ''))}</b> "
            f"<span class=\"muted\">"
            f"{campaign.get('completed_count', 0)}/"
            f"{campaign.get('total_count', 0)}</span><br>"
            f"<small>Current: "
            f"{_ui.esc(current.get('title', '—')[:60])}</small>"
            f"<br><small>Next: "
            f"{_ui.esc(nxt.get('step', '—')[:60])}</small>"
            + (f"<br><small><b>Blocked:</b> {blocked} "
               f"quest(s)</small>" if blocked else "") +
            f"<br><a href=\"/campaigns\">Open campaign →</a>"
            f"</div>")
    return ("<div class=\"panel\"><h2>World progression</h2>"
            "<div class=\"grove\">" + "".join(cards) +
            "</div></div>")


def _world_energy_html() -> str:
    """Energy in the world (BIG #44): only when real records
    exist. Solar flow, battery store, machine activity, grid
    link — words first, glyphs second."""
    from . import ui as _ui
    try:
        from .world import energy_objects
        objects = energy_objects(limit=6)
    except Exception:
        return ""
    if not objects:
        return ""
    rows = "".join(
        f"<li>{_ui.esc(item['glyph'])} "
        f"<b>{_ui.esc(item['label'])}</b> "
        f"<span class=\"muted\">{_ui.esc(item['state'])} · "
        f"{_ui.esc(item['detail'])}</span></li>"
        for item in objects)
    return (f"<div class=\"panel\"><h2>Energy in the world</h2>"
            f"<ul class=\"energyflow\">{rows}</ul>"
            f"<p><a href=\"/energy\">Energy detail →</a> "
            f"<span class=\"muted\">Unknown stays unknown; no "
            f"routing changes.</span></p></div>")


def _world_presence_html() -> str:
    """Presence in the world (BIG #44): bands as world states
    with real hrefs. Semantics unchanged."""
    from . import ui as _ui
    try:
        from .game import presence_as_stakes
        stakes = presence_as_stakes(limit=60)
    except Exception:
        return ""
    bands = stakes.get("bands", {}) or {}
    parts = []
    meta = {"needs": ("📌 needs", "attention marker"),
            "waiting": ("⏳ waiting", "paused, quiet objects"),
            "available": ("🟢 available", "workshop resources"),
            "discovered": ("🔵 discovered", "discovery glow"),
            "offline": ("🌙 quiet", "dimmed nodes")}
    for band in ("needs", "waiting", "available", "discovered",
                 "offline"):
        items = bands.get(band, []) or []
        if not items:
            continue
        title, reads = meta[band]
        lines = "".join(
            f"<li><a href=\"{_ui.esc(item.get('href', '/presence'))}\">"
            f"{_ui.esc(item.get('title', '')[:70])}</a></li>"
            for item in items[:3])
        parts.append(
            f"<div class=\"sprout band-{band}\"><b>{title}</b> "
            f"<span class=\"muted\">({reads})</span>"
            f"<ul>{lines}</ul></div>")
    if not parts:
        return ""
    return ("<div class=\"panel\"><h2>World attention</h2>"
            "<div class=\"grove\">" + "".join(parts) +
            "</div><p><a href=\"/presence\">Full attention →</a> "
            "· <a href=\"/guide\">Why? Ask the guide →</a></p>"
            "</div>")


def _world_state_strip() -> str:
    """Compact living world-state for the cockpit (BIG #41).

    Living state + presence counts + top attention, derived
    now from sync sources only (async-safe). Best-effort:
    empty string on any failure, never breaks the page.
    """
    from . import ui as _ui
    try:
        from .living_state import current_state
        from .presence import attention_snapshot
        state = current_state()
        snapshot = attention_snapshot(limit=60)
        counts = snapshot.get("counts", {})
        top = "".join(
            f"<li><a href=\"{_ui.esc(item['open_href'])}\">"
            f"{_ui.esc(item['title'][:80])}</a></li>"
            for item in snapshot.get("bands", {}).get(
                "needs", [])[:3])
        # BIG #42 ecosystem line: quests, hardware trust,
        # finance/energy — progressive disclosure (only when
        # real data exists), same ambient strip.
        extra = ""
        try:
            from .quests import list_quest_details as _strip_q
            _qs = _strip_q(limit=10)
            _open_q = sum(1 for _q in _qs if _q.get("state")
                          not in ("COMPLETED",))
            if _qs:
                extra += (f" · 🌱 <a href=\"/quests\">"
                          f"{_open_q} open quest(s)</a>")
        except Exception:
            pass
        try:
            from .hardware_links import list_links as _strip_hw
            _hw = _strip_hw(limit=200)
            _ver = sum(1 for _l in _hw
                       if _l.status == "VERIFIED")
            if _hw:
                extra += (f" · 🔗 <a href=\"/hardware\">"
                          f"{_ver}/{len(_hw)} verified</a>")
        except Exception:
            pass
        try:
            from .energy import summarize as _strip_en
            from .finance import summarize as _strip_fin
            _fen = _strip_fin().get("total", 0)
            _een = _strip_en().get("total", 0)
            if _fen:
                extra += (f" · 💰 <a href=\"/finance\">"
                          f"{_fen} finance</a>")
            if _een:
                extra += (f" · ⚡ <a href=\"/energy\">"
                          f"{_een} energy</a>")
        except Exception:
            pass
        return (
            f"<p>{_ui.esc(state.get('glyph', ''))} "
            f"<b>{_ui.esc(state.get('line', ''))}</b> · "
            f"{counts.get('needs', 0)} waiting · "
            f"{counts.get('discovered', 0)} discoveries · "
            f"{counts.get('offline', 0)} offline{extra} — "
            f"<a href=\"/presence\">attention →</a> · "
            f"<a href=\"/api/v1/ecosystem/overview\">"
            f"overview (JSON)</a></p>"
            f"{f'<ul>{top}</ul>' if top else ''}")
    except Exception:
        return ""


@app.get("/world", response_class=HTMLResponse)
async def world_page(entity_id: str = "", depth: int = 1,
                     show: str = "missions,nodes",
                     truth: str = "all", source: str = "all",
                     kind: str = "all", since: str = "") -> str:
    """Full world-graph explorer: pan, zoom, select, focus,
    neighborhood expansion, source + type filters. Real data
    only, bounded depth, keyboard navigable."""
    from . import ui as _ui
    import json as _json
    from .worldgraph import TRUTH_FILTERS
    flags = {part.strip() for part in show.split(",")}
    filters = {"truth": truth[:20], "source": source[:20],
               "kind": kind[:20], "since": since[:10]}
    if filters["truth"] not in TRUTH_FILTERS:
        filters["truth"] = "all"
    graph, error = ({"nodes": [], "edges": []}, "")
    if entity_id:
        graph, error = await _graph_data(entity_id, depth,
                                         flags, filters)
    # BIG #44 living world panels (all best-effort, "" when
    # their stores are empty — never filler).
    try:
        _symbiosis_panel = await _world_symbiosis_html(
            entity_id.strip()[:100] if entity_id else "")
    except Exception:
        _symbiosis_panel = ""
    try:
        _craft_panel = await _world_craft_html(
            entity_id.strip()[:100] if entity_id else "")
    except Exception:
        _craft_panel = ""
    # BIG #45 ecosystem connections (best-effort).
    try:
        _connections_panel = await _world_connections_html(
            entity_id.strip()[:100] if entity_id else "")
    except Exception:
        _connections_panel = ""
    truth_options = "".join(
        f"<option value='{name}'"
        + (" selected" if name == filters["truth"] else "")
        + f">{name}</option>" for name in sorted(TRUTH_FILTERS))
    shown = len(graph.get("nodes", []))
    loaded = graph.get("node_count", shown)
    filter_note = (
        f"<p class=\"muted\">{shown} shown"
        + (f" · truth={_ui.esc(filters['truth'])}" if filters["truth"] != "all" else "")
        + (f" · source={_ui.esc(filters['source'])}" if filters["source"] != "all" else "")
        + (f" · kind={_ui.esc(filters['kind'])}" if filters["kind"] != "all" else "")
        + (f" · since={_ui.esc(filters['since'])}" if filters["since"] else "")
        + ". Overlays are dashed Mycelium context, never world truth.</p>")
    main = f"""<h1>Living Workshop — one ecosystem</h1>
    <div class="panel"><h2>Command Center — wat kan ik voor je doen?</h2>
    <p>Typ hieronder in gewone taal. Ik maak een veilig lees-/onderzoeksplan, voer het zelfstandig uit tot ik je nodig heb, en leg precies uit waar ik stop.</p>
    <p class="muted">Probeer: “Onderzoek mijn camper.” · “Kijk wat er nog openstaat voor INVENTory.” · “Maak een overzicht van mijn lopende projecten.” · “Wat heb je vannacht gevonden?” · “Wat staat er vandaag op mijn agenda?”</p>
    <form method="post" action="/web/command" role="search" aria-label="Command Center">
    <input type="text" name="message" placeholder="Onderzoek mijn projecten en kijk wat er vandaag logisch is…" style="width:70%" aria-label="Command" autocomplete="off">
    <button type="submit">Ask Mycelium</button></form></div>
    <div class="panel"><h2>Ecosystem — alive at a glance</h2>
    <p><a href="/nodes">Nodes</a> · <a href="/conversations">Conversations</a> · <a href="/research">Research</a> · <a href="/missions">Missions</a> · <a href="/memory">Memory</a> · <a href="/cameras">Cameras</a> · <a href="/workshop/3d">3D</a> · <a href="/mobile">Mobile input</a> · <a href="/activity">Activity</a> · <a href="/search">Search</a> · <a href="/quests">Quests</a> · <a href="/hardware">Hardware</a> · <a href="/finance">Finance</a> · <a href="/energy">Energy</a></p>
    <p class="muted">Jelles ↔ chat ↔ mobile ↔ brain ↔ missions ↔ research ↔ memory ↔ INVENTory ↔ cameras ↔ 3D ↔ projects ↔ files ↔ nodes ↔ fabrication ↔ verification — one workshop, no loose pages. Statuses stay honest: REAL / TEST / SIMULATED / UNAVAILABLE.</p>
    {_world_state_strip()}</div>
    {_world_hud_html()}
    {_last_flow_panel()}
    <div class="panel"><h2>Layers & truth</h2>
    <form method="get" action="/world" aria-label="Graph layers and filters">
    <input type="hidden" name="entity_id" value="{_ui.esc(entity_id)}">
    <input type="hidden" name="depth" value="{depth}">
    <label>Overlays <input type="text" name="show" value="{_ui.esc(show)}" style="width:14rem" aria-label="Overlays"></label>
    <label>Truth <select name="truth" aria-label="Truth filter">{truth_options}</select></label>
    <label>Source <select name="source" aria-label="Source filter"><option value="all">all</option><option value="inventory">world</option><option value="mycelium">mycelium</option></select></label>
    <label>Since <input type="text" name="since" placeholder="2026-01-01" value="{_ui.esc(filters['since'])}" style="width:7rem" aria-label="Since date"></label>
    <button type="submit">Grow</button></form>
    <p class="muted">Overlay layers: missions, nodes, hardware, compute, research, observations, printers, memory, candidates, conversations. Truth: all · verified · memory · candidate · observation. Health never enters the graph.</p></div>
    {filter_note}
    <p class="muted">Every node is real: world entities from INVENTory, overlays from Mycelium. Select to inspect — the context rail opens here, no page jump — or open a neighborhood to grow.</p>
    {_ui.graph_panel(_json.dumps(graph), "/world", entity_id, depth, show, error)}
    {_world_campaign_html()}
    {_world_objects_html()}
    {_symbiosis_panel}
    {_connections_panel}
    {_craft_panel}
    {_world_energy_html()}
    {_world_presence_html()}
    <div class="panel"><h2>Do something with this</h2>
    <p class="muted">Pick a node above, then act through real endpoints: research continues in <a href="/research">Research</a>, plans wait in <a href="/missions">Missions</a>, imports land in <a href="/conversations">Conversations</a>, approvals wait in <a href="/agents">Agents</a>. Growth views: <a href="/craft">Craft Tree</a> · <a href="/symbiosis">Symbiosis</a> · <a href="/guide">Guide</a>.</p></div>"""
    context = _ui.context_block(
        "Reading the graph",
        "<ul><li><b>Rings</b> are projects — clusters of work.</li>"
        "<li><b>Diamonds</b> are ideas — seeds.</li>"
        "<li><b>Halos</b> are memories and missions — alive.</li>"
        "<li><b>Squares</b> are technical nodes.</li>"
        "<li><b>Dashed</b> outlines are Mycelium overlays, not world truth.</li></ul>")
    return _ui.shell("World Graph", "/world", _ui.living_bg() + main,
                     context,
                     _ui.command_bar())


def _workspace_research_html(workspace_id: str) -> str:
    """Research NPC panel: a role over existing workers, not an agent.

    The NPC is UI + identity only — starting uses the workspace
    research route (mission + run + pull-only fetch tasks), workers
    are the registered nodes, review stays human (mission YES,
    UNVERIFIED dossiers, existing gates). Best-effort reads; an
    empty panel never breaks the page.
    """
    from . import ui as _ui
    wid = _ui.esc(str(workspace_id))
    try:
        workers = [entry["node_id"]
                   for entry in eligible_nodes_for("research.fetch")]
    except Exception:
        workers = []
    try:
        queued = len(_queue_list(limit=50))
    except Exception:
        queued = 0
    try:
        from .research_engine import list_runs as _list_runs
        runs = [run for run in _list_runs(limit=50)
                if run.project_ref == workspace_id][:10]
    except Exception:
        runs = []
    worker_line = (", ".join(_ui.esc(name) for name in workers[:6])
                   or "geen worker met research.fetch online")
    run_rows = "".join(
        f"<tr><td class=\"muted\">{_ui.esc(run.run_id[:20])}</td>"
        f"<td>{_ui.esc(run.question[:70])}</td>"
        f"<td>{_ui.chip(run.status)} "
        f"<span class=\"muted\">{_ui.esc(run.execution_state)} · "
        f"{len(run.source_ids or [])} bronnen</span></td>"
        f"<td><form method=\"post\" action=\"/web/workspaces/"
        f"{wid}/research/{_ui.esc(run.run_id)}/report\" "
        f"style=\"display:inline\">"
        f"<button type=\"submit\">Report</button></form> "
        + (f"<a href=\"/api/v1/research/dossiers/"
           f"{_ui.esc(run.dossier_id)}\">dossier</a>"
           if run.dossier_id else "<span class=\"muted\">"
           "nog geen dossier</span>") + "</td></tr>"
        for run in runs
    ) or ("<tr><td colspan='4'>Nog geen research-runs in deze "
          "workspace.</td></tr>")
    return (
        f"<div class=\"panel living\"><h2>🔍 Research NPC</h2>"
        f"<p>Geen nieuw agent-framework — deze rol start de "
        f"bestaande keten: research-missie (wacht op jouw YES) → "
        f"fetch-taken voor workers → echte research met bronnen → "
        f"dossier terug in de conversatie (UNVERIFIED, jij "
        f"reviewt). Niets schrijft canoniek zonder de bestaande "
        f"gates.</p>"
        f"<p class=\"muted\">Workers: {worker_line} · "
        f"research-queue: {queued}</p>"
        f"<table><tr><th>Run</th><th>Vraag</th><th>Status</th>"
        f"<th></th></tr>{run_rows}</table>"
        f"<form method=\"post\" "
        f"action=\"/web/workspaces/{wid}/research\">"
        f"<input type=\"text\" name=\"question\" "
        f"placeholder=\"Onderzoeksvraag…\" style=\"width:60%\" "
        f"aria-label=\"Research question\"> "
        f"<select name=\"route\" aria-label=\"Route\">"
        f"<option value=\"node-first\">node-first (workers)</option>"
        f"<option value=\"local\">local (approve/tick)</option>"
        f"</select><br><br>"
        f"<input type=\"text\" name=\"seed_urls\" "
        f"placeholder=\"seed-URL's (komma/regel-gescheiden, voor node-first)\" "
        f"style=\"width:60%\" aria-label=\"Seed URLs\"> "
        f"<button type=\"submit\">Start research</button></form>"
        f"<p class=\"muted\">Missie-approval blijft mensenwerk op "
        f"<a href=\"/missions\">/missions</a>; dossiers krijgen "
        f"alleen betekenis via jouw review.</p></div>")


def _workspace_workstreams_html(workspace_id: str) -> str:
    """Side-by-side workstreams: one block per mission.

    Read-only aggregation (conversations, missions + greenlight,
    tasks, research, proposals) plus shared workers/registry.
    Streams stay independent — claiming, approving or reporting
    one never touches another; this panel only shows them next
    to each other. Best-effort: "" on any failure.
    """
    from . import ui as _ui
    try:
        from .workspaces import FORGE_STEP_KINDS
        from .workspaces import workstream_overview as _overview
        view = _overview(str(workspace_id))
    except Exception:
        return ""
    blocks = []
    for stream in view.get("workstreams", []):
        steps = "".join(
            f"<span class=\"chip\">"
            f"{_ui.esc(step['kind'])}:"
            f"{_ui.esc(step['status'])}</span>"
            for step in stream.get("steps", [])[:10])
        stream_tasks = "".join(
            f"<li>{_ui.esc(task['kind'])} "
            f"{_ui.chip(task['status'])}"
            + (f" <span class=\"muted\">→ "
               f"{_ui.esc(task['assigned_node_id'])}</span>"
               if task["assigned_node_id"] else "")
            + "</li>"
            for task in stream.get("tasks", [])[:10])
        stream_runs = "".join(
            f"<li><span class=\"muted\">"
            f"{_ui.esc(run['run_id'][:20])}</span> "
            f"{_ui.chip(run['status'])} "
            f"{_ui.esc(run['execution_state'])}"
            + (f" <a href=\"/api/v1/research/dossiers/"
               f"{_ui.esc(run['dossier_id'])}\">dossier</a>"
               if run["dossier_id"] else "")
            + "</li>"
            for run in stream.get("research", [])[:6])
        stream_props = "".join(
            f"<li>{_ui.esc(prop['kind'])} "
            f"{_ui.chip(prop['status'])} "
            f"<span class=\"muted\">"
            f"{_ui.esc(prop['proposal_id'][:24])}</span></li>"
            for prop in stream.get("proposals", [])[:6])
        forge_steps = [step for step in stream.get("steps", [])
                       if step["kind"] in FORGE_STEP_KINDS]
        forge_line = ""
        if forge_steps:
            forge_line = (
                f"<p>🔨 Forge: "
                f"{', '.join(_ui.esc(step['kind']) + ':' + _ui.esc(step['status']) for step in forge_steps)} "
                f"· <a href=\"/forge\">Forge Studio</a></p>")
        mib = _ui.esc(stream["mission_id"])
        opening = stream.get("open", {}) or {}
        open_links = (
            f"<a href=\"{_ui.esc(opening.get('mission', ''))}\">"
            f"Mission</a>"
            f" · <a href=\"{_ui.esc(opening.get('conversation', ''))}\">"
            f"Conversation</a>")
        if opening.get("forge"):
            open_links += (
                f" · <a href=\"{_ui.esc(opening['forge'])}\">Forge</a>")
        if opening.get("research"):
            open_links += (
                f" · <a href=\"{_ui.esc(opening['research'])}\">"
                f"Research</a>")
            for run_link in stream.get("research_links", [])[:3]:
                if run_link.get("dossier_id"):
                    open_links += (
                        f" · <a href=\"/api/v1/research/dossiers/"
                        f"{_ui.esc(run_link['dossier_id'])}\">"
                        f"dossier</a>")
                    break
        if opening.get("approve"):
            open_links += (
                f" · <a href=\"{_ui.esc(opening['approve'])}\">"
                f"Approve</a>")
        blocks.append(
            f"<div class=\"sprout\" id=\"stream-{mib[:20]}\"><b>"
            f"{_ui.esc(stream['goal'][:80] or stream['mission_id'])}"
            f"</b><br>"
            f"{_ui.chip(stream['greenlight'])} "
            f"{_ui.chip(stream['status'])}<br>"
            f"<span class=\"muted\">missie "
            f"<a href=\"{_ui.esc(stream['href'])}\">{mib[:20]}</a> "
            f"· <a href=\"{_ui.esc(opening.get('conversation', ''))}\">"
            f"conversatie</a>"
            f"</span><br>{steps}{forge_line}"
            f"{f'<ul>{stream_tasks}</ul>' if stream_tasks else ''}"
            f"{f'<ul>{stream_runs}</ul>' if stream_runs else ''}"
            f"{f'<ul>{stream_props}</ul>' if stream_props else ''}"
            f"<p><b>OPEN:</b> {open_links}</p>"
            f"</div>")
    counts = " · ".join(
        f"{total} {state}"
        for state, total in sorted(view.get("task_counts", {}).items())
    ) or "geen taken"
    empty = ("<p>Geen missies - start een research of koppel "
             "een conversatie.</p>")
    cards = "".join(blocks) or empty
    return (
        f"<div class=\"panel\"><h2>ACTIVE WORKSTREAMS</h2>"
        f"<p class=\"muted\">Taken: {counts} · "
        f"<a href=\"/api/v1/workspaces/"
        f"{_ui.esc(str(workspace_id))}/workstreams\">JSON</a> · "
        f"workers, events en registers staan hieronder bij "
        f"SHARED RESOURCES en ACTIVITY.</p>"
        f"<div class=\"grove\">"
        f"{cards}"
        f"</div>"
        f"</div>")


@app.get("/workspaces", response_class=HTMLResponse)
def workspaces_page() -> str:
    """Project workspaces (slice 1): one project, many conversations.

    Derived view only — seeds (Mycelium AI, INVENTory, Forge Studio)
    plus every used project_ref. Fork/attach run on the existing
    conversation/mission rows; context and packages stay where they
    were (/api/v1/project/package, /api/v1/context/packet).
    """
    from . import ui as _ui
    from .workspaces import list_workspaces as _list_workspaces
    try:
        items = _list_workspaces()
    except Exception:
        items = []
    cards = "".join(
        f"<div class=\"sprout\"><b>{_ui.esc(item['title'])}</b><br>"
        f"{_ui.chip(item['kind'])} "
        f"<span class=\"muted\">{item['conversations']} conversation(s) "
        f"· {item['missions']} mission(s)</span><br>"
        + (f"<span class=\"muted\">"
           f"{_ui.esc(str(item.get('view', ''))[:140])}</span><br>"
           if item.get("view") else "")
        + f"<a href=\"{_ui.esc(item['href'])}\">Open workspace</a></div>"
        for item in items) or _ui.empty("No workspaces yet.")
    main = (f"<h1>Project workspaces</h1>"
            f"<p class=\"muted\">One project holds many conversations; "
            f"a conversation forks and keeps going on its own; "
            f"anything re-links later. Seeds below are existing "
            f"views — <a href=\"/missions\">Mycelium AI</a>, "
            f"<a href=\"/projects\">INVENTory</a>, "
            f"<a href=\"/forge\">Forge Studio</a> — not new systems.</p>"
            f"<div class=\"grove\">{cards}</div>")
    return _ui.shell("Workspaces", "/workspaces", main, "",
                     _ui.command_bar())


def _workspace_tree_ul(tree: dict, node_id: str, wid: str) -> str:
    """One nested tree branch. Parent edges exist only when the
    fork bookkeeping proves them; nothing is guessed."""
    from . import ui as _ui
    nodes = tree.get("nodes", {}) or {}
    children = tree.get("children", {}) or {}
    node = nodes.get(node_id, {})
    if not node:
        return ""
    label = _ui.esc(str(node.get("title", node_id))[:70])
    info = (
        f"<a href=\"{_ui.esc(node.get('open_href', ''))}\">{label}</a> "
        f"<span class=\"muted\">({node.get('messages', 0)} msgs)</span>")
    if node.get("parent"):
        info += (
            f" <span class=\"chip\">fork van "
            f"{_ui.esc(str(node['parent'])[:20])}</span>")
    info += (
        f" <a href=\"{_ui.esc(node.get('open_href', ''))}\">OPEN</a>"
        f" <form method=\"post\" action=\"/web/conversations/"
        f"{_ui.esc(node_id)}/fork\" style=\"display:inline\">"
        f"<input type=\"hidden\" name=\"target_workspace\" "
        f"value=\"{_ui.esc(wid)}\">"
        f"<button type=\"submit\">Fork</button></form>")
    branch = "".join(
        _workspace_tree_ul(tree, child, wid)
        for child in children.get(node_id, []))
    if branch:
        return f"<li>{info}<ul>{branch}</ul></li>"
    return f"<li>{info}</li>"


def _workspace_tree_html(view: dict, wid: str) -> str:
    """CONVERSATIONS panel: MAIN tree plus management forms.

    Fork/attach reuse the existing routes; new conversations reuse
    the existing ensure_conversation store through a thin web form.
    """
    from . import ui as _ui
    tree = view.get("tree", {}) or {}
    roots = tree.get("roots", []) or []
    main_tree = "".join(
        _workspace_tree_ul(tree, root, wid) for root in roots)
    if not main_tree:
        main_tree = "<li>Nog geen conversations.</li>"
    return (
        f"<div class=\"panel\"><h2>CONVERSATIONS</h2>"
        f"<p class=\"muted\">MAIN (alleen bewezen fork-relaties; "
        f"de rest staat plat, nooit gegokt)</p>"
        f"<ul class=\"convtree\">{main_tree}</ul>"
        f"<form method=\"post\" "
        f"action=\"/web/workspaces/{_ui.esc(wid)}/conversations/new\">"
        f"<input type=\"text\" name=\"title\" "
        f"placeholder=\"Titel voor nieuwe conversation\" "
        f"style=\"width:16rem\" aria-label=\"Title\">"
        f"<button type=\"submit\">NEW CONVERSATION</button></form>"
        f"<form method=\"post\" "
        f"action=\"/web/workspaces/{_ui.esc(wid)}/attach-conversation\">"
        f"<input type=\"text\" name=\"conversation_id\" "
        f"placeholder=\"conv-… / conv_… om te koppelen\" "
        f"style=\"width:16rem\" aria-label=\"Conversation ID\">"
        f"<button type=\"submit\">ATTACH</button></form>"
        f"<form method=\"post\" "
        f"action=\"/web/workspaces/{_ui.esc(wid)}/attach-mission\">"
        f"<input type=\"text\" name=\"mission_id\" "
        f"placeholder=\"mission_…\" style=\"width:12rem\" "
        f"aria-label=\"Mission ID\">"
        f"<input type=\"text\" name=\"conversation_id\" "
        f"placeholder=\"doel-conversatie\" style=\"width:12rem\" "
        f"aria-label=\"Target conversation\">"
        f"<button type=\"submit\">Link mission here</button></form>"
        f"</div>")


def _workspace_pending_html(view: dict) -> str:
    """PENDING HUMAN ACTIONS: every row opens an existing gate.

    Mission approvals (mission page), desktop items (/approvals),
    writes (/writes), research reports (existing report action).
    This panel never approves or executes anything itself.
    """
    from . import ui as _ui
    pending = view.get("pending", {}) or {}
    wid = _ui.esc(str(view.get("workspace_id", "")))
    rows = "".join(
        f"<li>mission: "
        f"<a href=\"{_ui.esc(item['href'])}\">"
        f"{_ui.esc(item['label'][:70])}</a> "
        f"{_ui.chip('wacht op YES')}</li>"
        for item in pending.get("mission_approvals", [])[:10])
    rows += "".join(
        f"<li>desktop: "
        f"{_ui.esc(item['label'][:40])} "
        f"<span class=\"muted\">"
        f"{_ui.esc(item['mission_id'][:20])}</span> "
        f"<a href=\"/approvals\">review</a></li>"
        for item in pending.get("desktop", [])[:10])
    rows += "".join(
        f"<li>write: "
        f"{_ui.esc(item['label'][:40])} "
        f"<span class=\"muted\">"
        f"{_ui.esc(item['mission_id'][:20])}</span> "
        f"<a href=\"/writes\">review</a></li>"
        for item in pending.get("writes", [])[:10])
    rows += "".join(
        f"<li>research-report: "
        f"{_ui.esc(item['label'][:70])} "
        f"<form method=\"post\" action=\"/web/workspaces/"
        f"{wid}/research/{_ui.esc(item['run_id'])}/report\" "
        f"style=\"display:inline\">"
        f"<button type=\"submit\">Report</button></form></li>"
        for item in pending.get("research_reports", [])[:10])
    return (
        f"<div class=\"panel\"><h2>PENDING HUMAN ACTIONS</h2>"
        f"<p class=\"muted\">{pending.get('total', 0)} open — "
        f"elke actie loopt via de bestaande gates "
        f"(<a href=\"/approvals\">approvals</a> · "
        f"<a href=\"/writes\">writes</a> · "
        f"<a href=\"/missions\">missions</a>).</p>"
        f"<ul>{rows or '<li>Nothing waiting.</li>'}</ul></div>")


def _workspace_activity_html(view: dict) -> str:
    """ACTIVITY: existing conversation events + interface bus tail."""
    from . import ui as _ui
    stored = "".join(
        f"<li>{_ui.esc(item.get('event_type', ''))} — "
        f"{_ui.esc(str(item.get('message', ''))[:120])} "
        f"<span class=\"muted\">"
        f"{_ui.esc(str(item.get('created_at', ''))[:16])}</span></li>"
        for item in view.get("events", [])[:10])
    bus = "".join(
        f"<li>{_ui.esc(item.get('event_type', ''))} — "
        f"{_ui.esc(str(item.get('summary', ''))[:120])} "
        f"<span class=\"muted\">"
        f"{_ui.esc(str(item.get('created_at', ''))[:16])}</span></li>"
        for item in view.get("bus_events", [])[:12])
    return (
        f"<div class=\"panel\"><h2>ACTIVITY</h2>"
        f"<ul>{stored}{bus or ''}"
        f"{'' if (stored or bus) else '<li>Quiet.</li>'}</ul></div>")


def _workspace_shared_html(view: dict, inventory_html: str) -> str:
    """SHARED RESOURCES: workers, Forge, research, INVENTory.

    Workers and registries are global and labelled shared;
    per-workstream assignment lives on the tasks above.
    """
    from . import ui as _ui
    available = [worker for worker in view.get("workers", [])
                 if worker.get("available")]
    workers = "".join(
        f"<li>{_ui.esc(worker['node_id'])} "
        f"{_ui.chip(worker['status'])} "
        f"<span class=\"muted\">"
        f"{_ui.esc(', '.join(worker.get('capabilities', [])[:6]))}"
        f"</span></li>"
        for worker in available[:12])
    forge = view.get("forge", {}) or {}
    registry = forge.get("registry", {}) or {}
    runs = "".join(
        f"<li><span class=\"muted\">"
        f"{_ui.esc(run['run_id'][:20])}</span> "
        f"{_ui.esc(run['question'][:70])} "
        f"{_ui.chip(run['status'])}"
        + (f" <a href=\"/api/v1/research/dossiers/"
           f"{_ui.esc(run['dossier_id'])}\">dossier</a>"
           if run["dossier_id"] else "")
        + "</li>"
        for run in view.get("research", [])[:8])
    return (
        f"<div class=\"panel\"><h2>SHARED RESOURCES</h2>"
        f"<h3>Workers</h3>"
        f"<ul>{workers or '<li>WAITING — geen workers online.</li>'}</ul>"
        f"<p><a href=\"/nodes\">All nodes</a></p>"
        f"<h3>Forge models</h3>"
        f"<p>{registry.get('models', 0)} modellen, "
        f"{registry.get('fabjobs', 0)} fabjobs (gedeeld register) · "
        f"<a href=\"/forge\">Forge Studio</a>"
        f"</p>"
        f"<h3>Research runs</h3>"
        f"<ul>{runs or '<li>—</li>'}</ul>"
        f"<p><a href=\"/research\">Research</a></p>"
        f"{inventory_html}"
        f"<p><a href=\"/projects\">Projects</a> · "
        f"<a href=\"/world\">World graph</a></p>"
        f"</div>")


async def _workspace_inventory_html(workspace_id: str) -> str:
    """Linked INVENTory projects + browse sample, all read-only.

    Linked records resolve only from demonstrable row relations
    (workspace id, mission context, research links) with their
    own provenance; the browse sample is explicitly unlinked.
    Any outage renders UNAVAILABLE — never invented data.
    """
    from . import ui as _ui
    wid = str(workspace_id)
    try:
        linked = await _linked_inventory_projects(wid)
    except Exception:
        linked = {"projects": [], "unresolved": 0,
                  "candidate_refs": 0}
    if linked["projects"]:
        linked_html = "<ul>" + "".join(
            f"<li><a href=\"{_ui.esc(item['href'])}\">"
            f"{_ui.esc(item['title'] or item['entity_id'])}</a> "
            f"<span class=\"muted\">{_ui.esc(item['entity_id'][:24])}"
            f" · via {_ui.esc(item['via'])} · "
            f"{_ui.esc(item['status'] or 'unknown')} · "
            f"provenance "
            f"{_ui.esc(item['provenance']['source_type'])}"
            f"{'/verified' if item['provenance']['human_verified'] else '/unverified'}"
            f"</span></li>"
            for item in linked["projects"]) + "</ul>"
    elif linked["unresolved"]:
        linked_html = (
            f"<p class=\"muted\">INVENTory: UNAVAILABLE — "
            f"{linked['unresolved']} gekoppelde id(s) niet op te "
            f"lossen; niets verzonnen.</p>")
    else:
        linked_html = (
            "<p class=\"muted\">Geen aantoonbaar gekoppeld "
            "INVENTory-project (alleen exacte proj_-relaties "
            "tellen).</p>")
    try:
        browsed = await _world_reader().browse("projects")
        records = [(record.entity_id, record.title)
                   for record in (browsed.results or [])][:8]
        if records:
            sample_html = "<ul>" + "".join(
                f"<li><a href=\"/world?entity_id={_ui.esc(rid)}\">"
                f"{_ui.esc(title[:60] or rid)}</a> "
                f"<span class=\"muted\">{_ui.esc(rid[:20])}</span></li>"
                for rid, title in records) + "</ul>"
        else:
            sample_html = ("<p class=\"muted\">Geen project-records "
                           "gevonden.</p>")
    except Exception as error:
        sample_html = (
            f"<p class=\"muted\">INVENTory: UNAVAILABLE "
            f"({_ui.esc(str(error)[:120])}) — geen verzonnen data.</p>")
    return (
        f"<h3>Inventory / project records</h3>"
        f"<h4>Gekoppeld (bewezen relaties)</h4>{linked_html}"
        f"<p class=\"muted\"><a href=\"/api/v1/workspaces/"
        f"{_ui.esc(wid)}/inventory-projects\">JSON</a></p>"
        f"<h4>Sample (niet gekoppeld)</h4>{sample_html}")


@app.get("/workspaces/{workspace_id}", response_class=HTMLResponse)
async def workspace_page(workspace_id: str) -> str:
    """Workspace development cockpit: independent workstreams side
    by side. VIEW ONLY — every action below reuses an existing
    route/gate; no new state, no orchestration, no auto-anything."""
    from . import ui as _ui
    from .workspaces import WorkspaceRefusedError
    from .workspaces import get_workspace as _get_workspace
    from .workspaces import workstream_overview as _overview
    try:
        workspace = _get_workspace(workspace_id)
    except WorkspaceRefusedError:
        return HTMLResponse("Unknown workspace", status_code=422)
    wid = _ui.esc(workspace["workspace_id"])
    try:
        view = _overview(workspace["workspace_id"])
    except Exception:
        view = None
    seed_view = ""
    if workspace.get("view"):
        seed_view = (
            f"<div class=\"panel\"><h2>Existing view</h2>"
            f"<p>{_ui.esc(workspace['view'])}</p>"
            f"<p><a href=\"{_ui.esc(workspace['href'])}\">"
            f"Open {_ui.esc(workspace['title'])} →</a></p></div>")
    if view is None:
        main = (f"<h1>{_ui.esc(workspace['title'])}</h1>"
                f"{seed_view}"
                f"<div class=\"panel\"><p>UNAVAILABLE — "
                f"workstream-overzicht kon niet worden gelezen.</p>"
                f"</div>")
        return _ui.shell(workspace["title"], "/workspaces", main, "",
                         _ui.command_bar())
    try:
        inventory_html = await _workspace_inventory_html(
            workspace["workspace_id"])
    except Exception:
        inventory_html = ("<h3>Inventory / project records</h3>"
                          "<p class=\"muted\">UNAVAILABLE.</p>")
    streams_panel = _workspace_workstreams_html(
        workspace["workspace_id"])
    research_panel = _workspace_research_html(
        workspace["workspace_id"])
    main = f"""<h1>{_ui.esc(workspace['title'])}</h1>
    <p class="muted">workspace <code>{wid}</code> · {workspace['kind']} ·
    development cockpit (alleen kijken; handelen via bestaande gates) ·
    <a href="{_ui.esc(workspace['package_href'])}">project package (JSON)</a> ·
    <a href="{_ui.esc(workspace['context_href'])}">context packet (JSON)</a></p>
    {seed_view}
    {streams_panel}
    {_workspace_tree_html(view, workspace['workspace_id'])}
    {_workspace_pending_html(view)}
    {_workspace_activity_html(view)}
    {_workspace_shared_html(view, inventory_html)}
    {research_panel}"""
    return _ui.shell(workspace["title"], "/workspaces", main, "",
                     _ui.command_bar())


@app.post("/web/conversations/{conversation_id}/fork")
async def web_conversation_fork(conversation_id: str,
                                request: Request) -> Response:
    from .workspaces import WorkspaceNotFoundError, WorkspaceRefusedError
    from .workspaces import fork_conversation as _fork
    fields = await _form_fields(request)
    try:
        record = _fork(conversation_id,
                       fields.get("target_workspace", ""))
    except (WorkspaceNotFoundError, WorkspaceRefusedError):
        return RedirectResponse("/workspaces", status_code=303)
    return RedirectResponse(
        f"/api/v1/conversations/{record['conversation_id']}",
        status_code=303)


@app.post("/web/workspaces/{workspace_id}/attach-conversation")
async def web_workspace_attach_conversation(
        workspace_id: str, request: Request) -> Response:
    from .workspaces import WorkspaceNotFoundError, WorkspaceRefusedError
    from .workspaces import attach_conversation as _attach
    fields = await _form_fields(request)
    try:
        _attach(fields.get("conversation_id", ""), workspace_id)
    except (WorkspaceNotFoundError, WorkspaceRefusedError):
        pass
    return RedirectResponse(f"/workspaces/{workspace_id}",
                            status_code=303)


@app.post("/web/workspaces/{workspace_id}/conversations/new")
async def web_workspace_conversation_new(
        workspace_id: str, request: Request) -> Response:
    """Open one conversation row in this workspace, then continue
    it in /chat. Reuses the existing ensure_conversation store;
    no workstream record, no orchestration."""
    from .workspaces import WorkspaceRefusedError
    from .workspaces import ensure_conversation as _ensure
    fields = await _form_fields(request)
    try:
        record = _ensure(workspace_id, fields.get("title", ""))
    except WorkspaceRefusedError:
        return RedirectResponse(f"/workspaces/{workspace_id}",
                                status_code=303)
    return RedirectResponse(
        f"/chat?id={record['conversation_id']}", status_code=303)


@app.post("/web/workspaces/{workspace_id}/attach-mission")
async def web_workspace_attach_mission(
        workspace_id: str, request: Request) -> Response:
    from .workspaces import WorkspaceNotFoundError, WorkspaceRefusedError
    from .workspaces import attach_mission as _attach_mission
    fields = await _form_fields(request)
    try:
        record = _attach_mission(fields.get("mission_id", ""),
                                 fields.get("conversation_id", ""))
        target = (f"/workspaces/{record['workspace_id']}"
                  if record["workspace_id"] else
                  f"/workspaces/{workspace_id}")
    except (WorkspaceNotFoundError, WorkspaceRefusedError):
        target = f"/workspaces/{workspace_id}"
    return RedirectResponse(target, status_code=303)


@app.post("/web/workspaces/{workspace_id}/research")
async def web_workspace_research_start(
        workspace_id: str, request: Request) -> Response:
    fields = await _form_fields(request)
    seeds = [line.strip() for line in
             fields.get("seed_urls", "").replace(",", "\n").splitlines()
             if line.strip()][:3]
    try:
        record = await _start_workspace_research(
            workspace_id, fields.get("question", ""),
            fields.get("objective", ""),
            fields.get("route", "node-first"), seeds,
            fields.get("conversation_id", ""), 6)
    except HTTPException:
        return RedirectResponse(f"/workspaces/{workspace_id}",
                                status_code=303)
    return RedirectResponse(
        f"/workspaces/{record['workspace_id']}", status_code=303)


@app.post("/web/workspaces/{workspace_id}/research/{run_id}/report")
async def web_workspace_research_report(
        workspace_id: str, run_id: str) -> Response:
    try:
        workspace_research_report(workspace_id, run_id)
    except HTTPException:
        pass
    return RedirectResponse(f"/workspaces/{workspace_id}",
                            status_code=303)


@app.get("/projects", response_class=HTMLResponse)
async def projects_page(project_id: str = "") -> str:
    """Projects as visual ecosystems: goal, components,
    tasks, missions, research, skills. Precise data kept."""
    from . import ui as _ui
    items = []
    error = ""
    try:
        browsed = await _world_reader().browse("projects")
        for record in (browsed.results or [])[:30]:
            details = record.details \
                if isinstance(record.details, dict) else {}
            items.append({"id": record.entity_id,
                          "title": str(details.get(
                              "name", details.get(
                                  "title", record.entity_id)))[:80],
                          "status": str(details.get(
                              "status", ""))})
    except (InventoryRefusedError, InventoryUnavailable,
            ValueError, AttributeError) as exc:
        error = str(exc)
    detail_html = ""
    if project_id:
        graph, _ = await _graph_data(project_id, 1,
                                     {"missions"})
        names = [f"<li>{_ui.esc(n.get('label', n.get('id', '')))} "
                 f"<span class=\"muted\">{_ui.esc(n.get('type', ''))}</span></li>"
                 for n in graph.get("nodes", [])[:20]]
        detail_html = f"""<div class="panel"><h2>Ecosystem</h2><ul>{"".join(names) or "<li>No linked entities.</li>"}</ul>
        <p><a href="/world?entity_id={_ui.esc(project_id)}">Open in world graph</a></p></div>"""
    cards = "".join(
        f"<div class=\"sprout\"><b>{_ui.esc(item['title'])}</b><br>"
        f"{_ui.chip(item['status'] or 'unknown')}<br>"
        f"<a href=\"/projects?project_id={_ui.esc(item['id'])}\">Open ecosystem</a></div>"
        for item in items) or _ui.empty(
            "No projects found. " + error if error else
            "No projects found.")
    main = f"<h1>Projects</h1>{detail_html}<div class=\"grove\">{cards}</div>"
    return _ui.shell("Projects", "/projects", main, "",
                     _ui.command_bar())


@app.get("/activity", response_class=HTMLResponse)
def activity_page() -> str:
    """Elegant activity stream: observations, memory updates,
    mission transitions, node changes, integration events,
    verifications, approvals. Provenance stays visible."""
    from . import ui as _ui
    try:
        from .ecosystem import activity_feed as _feed
        feed = _feed(limit=30)
    except Exception:
        feed = []
    items = []
    if feed:
        for entry in feed:
            link = entry.get("link", "/activity")
            items.append(
                f"<tr><td>{_ui.esc(entry.get('voice', ''))}<br><small>"
                f"{_ui.esc(entry.get('event_type', ''))}</small></td>"
                f"<td><a href=\"{_ui.esc(link)}\">"
                f"{_ui.esc(entry.get('summary', '')[:120])}</a></td>"
                f"<td class=\"muted\">"
                f"{_ui.esc(str(entry.get('created_at', ''))[:16])}</td></tr>")
    else:
        for event in bus_events(limit=30):
            items.append(
                f"<tr><td>{_ui.status_dot(event.event_type.split('.')[0])}{_ui.esc(event.event_type)}</td>"
                f"<td>{_ui.esc(event.summary[:120])}</td>"
                f"<td class=\"muted\">{_ui.esc(event.created_at[:16])}</td></tr>")
    notes = "".join(
        f"<li>{_ui.esc(item.title)} <span class=\"muted\">[{_ui.esc(item.severity)}]</span></li>"
        for item in list_notifications_for_report(limit=15))
    main = f"""<h1>Activity — the world breathing</h1>
    <p class="muted">Every line is a real event with provenance. Mycelium voice up front, technical detail one click away in <a href="/activity">events</a> and <a href="/morning">Morning</a>.</p>
    <div class="panel"><h2>Stream</h2><table><tr><th>Event</th><th>What</th><th>When</th></tr>
    {"".join(items) or "<tr><td colspan='3'>Quiet.</td></tr>"}</table></div>"""
    context = _ui.context_block("Notifications",
                                f"<ul>{notes or '<li>None.</li>'}</ul>")
    return _ui.shell("Activity", "/activity", _ui.living_bg() + main,
                     context,
                     _ui.command_bar())


async def _form_fields(request: Request) -> dict[str, str]:
    """Parse urlencoded HTML forms with stdlib only (no new dependency)."""
    from urllib.parse import parse_qs
    body = (await request.body()).decode("utf-8", "replace")[:8000]
    return {key: values[0] for key, values in parse_qs(
        body, keep_blank_values=True).items() if values}


#: BIG #43 living game layer: game-like morning headers.
#: Presentation only — report JSON titles stay stable.
_GAME_TITLE = {
    "Today": "🌱 World state",
    "Current campaign": "🎯 Current campaign",
    "Energy": "⚡ Energy",
    "Workshop": "🔧 Workshop",
    "Hardware verification": "🔧 Hardware",
    "Discoveries": "🧠 Discoveries",
    "Devices": "🌐 Node mesh",
    "Needs you": "📌 What needs me",
}


@app.get("/morning", response_class=HTMLResponse)
def morning_page() -> str:
    """Mobile-first morning report: cards per section."""
    from . import ui as _ui
    report = report_morning()
    try:
        from .context_engine import get_mode
        mode = get_mode()
    except Exception:
        mode = {"mode": "DAY", "detail": "", "updated_at": ""}
    try:
        from .ecosystem import discoveries as _discoveries
        found = _discoveries(limit=6)
    except Exception:
        found = {"items": [], "research_open_questions": []}
    overnight_html = ""
    try:
        overnight_html = "".join(
            f"<li>{_ui.esc(item['question'][:160])} "
            f"<span class=\"muted\">(<a href=\"{_ui.esc(item['link'])}\">"
            f"dossier</a>)</span></li>"
            for item in found.get("research_open_questions", [])[:6])
    except (AttributeError, TypeError, KeyError):
        overnight_html = ""
    cards = "".join(
        f"<div class=\"sprout\"><h3>"
        f"{_ui.esc(_GAME_TITLE.get(section['title'], section['title']))}"
        f"</h3><ul>"
        + "".join(f"<li>{_ui.esc(item)}</li>"
                  for item in section["items"][:15])
        + "</ul></div>"
        for section in report.get("sections", []))
    main = f"""<h1>Good morning, Jelles 🌱</h1>
    <p class="muted">{_ui.esc(str(report.get('generated_at', '')))} · {_ui.esc(str(report.get('report_id', '')))} · mode: <b>{_ui.esc(mode.get('mode', 'DAY'))}</b></p>
    <div class="panel"><h2>Overnight</h2>
    <ul>{overnight_html or "<li>Nog niets onderzocht vannacht — zet de queue klaar via <a href=\"/research\">Research</a> of de <a href=\"/api/v1/research/queue\">queue (JSON)</a>.</li>"}</ul>
    <form method="post" action="/web/mode">
    <select name="mode" aria-label="Mode"><option value="DAY">DAY</option><option value="OVERNIGHT">OVERNIGHT</option></select>
    <input type="text" name="detail" placeholder="Waarom (optioneel)" style="width:40%" aria-label="Detail">
    <button type="submit">Set mode</button></form>
    <p class="muted">OVERNIGHT betekent: veilige research, analyse en rapporten mogen doorlopen. Fysiek, desktop-input, publiceren en approvals blijven altijd mensenwerk.</p></div>
    <div class="grove">{cards or _ui.empty()}</div>"""
    return _ui.shell("Morning", "/morning", main, "",
                     _ui.command_bar())


@app.get("/agenda", response_class=HTMLResponse)
def agenda_page() -> str:
    """Agenda importer: .ics plakken, preview, bevestigen.
    Read-only context; nooit een verplichting-fact."""
    from . import ui as _ui
    from .agenda import init_agenda_tables, list_events, list_sources
    init_chat_database()
    with chat_connection() as db:
        init_agenda_tables(db)
        events = list_events(db, limit=50)
        sources = list_sources(db)
    rows = "".join(
        f"<tr><td>{_ui.esc(str(event.get('start', ''))[:16])}</td>"
        f"<td>{_ui.esc(str(event.get('title', ''))[:80])}</td>"
        f"<td class=\"muted\">"
        f"{_ui.esc(str(event.get('location', ''))[:60])}</td></tr>"
        for event in events)
    srcs = "".join(
        f"<li>{_ui.esc(str(source.get('label', '')))} — "
        f"{source.get('event_count', 0)} events "
        f"<span class=\"muted\">({ _ui.esc(str(source.get('imported_at', ''))[:16])})</span></li>"
        for source in sources)
    main = f"""<h1>Agenda — today in the ecosystem</h1>
    <p class="muted">Today's soil: appointments give missions and research their timing. Import stays preview → dedup → confirm; events link to projects and missions as context, never as orders.</p>
    <div class="panel"><h2>Importeer agenda (.ics)</h2>
    <p class="muted">Plak .ics-tekst, bekijk de preview, bevestig pas daarna. Duplicaten (zelfde UID) worden nooit dubbel opgeslagen. Alles blijft alleen-lezen context.</p>
    <form method="post" action="/web/agenda/import">
    <input type="text" name="source_label" placeholder="Bron (bv. gezin)" style="width:30%" aria-label="Source label"><br><br>
    <textarea name="ics_text" rows="6" style="width:100%" placeholder="Plak hier .ics-tekst…" aria-label="ICS text"></textarea><br><br>
    <button type="submit" name="preview_only" value="true">Preview</button>
    <button type="submit" name="preview_only" value="false">Bevestig import</button></form></div>
    <div class="panel"><h2>Bronnen</h2><ul>{srcs or "<li>Nog geen.</li>"}</ul></div>
    <div class="panel"><h2>Aankomend</h2><table><tr><th>Wanneer</th><th>Wat</th><th>Waar</th></tr>
    {rows or "<tr><td colspan='3'>Leeg — importeer een .ics.</td></tr>"}</table></div>"""
    return _ui.shell("Agenda", "/agenda", main, "",
                     _ui.command_bar())


@app.post("/web/agenda/import")
async def web_agenda_import(request: Request) -> Response:
    from .agenda import (AgendaRefusedError, init_agenda_tables,
                         parse_ics, store_preview)
    fields = await _form_fields(request)
    ics_text = fields.get("ics_text", "")
    label = fields.get("source_label", "import") or "import"
    preview_only = fields.get("preview_only", "true") != "false"
    try:
        preview = parse_ics(ics_text[:500000], source_label=label)
    except AgendaRefusedError:
        return RedirectResponse("/agenda", status_code=303)
    if preview_only:
        return RedirectResponse("/agenda", status_code=303)
    init_chat_database()
    with chat_connection() as db:
        init_agenda_tables(db)
        try:
            store_preview(db, preview)
        except AgendaRefusedError:
            pass
    return RedirectResponse("/agenda", status_code=303)


@app.post("/web/command")
async def web_command(request: Request) -> Response:
    """Command Center form: route NL text through /api/v1/command
    and land on the right page (mission, morning, chat)."""
    fields = await _form_fields(request)
    text = fields.get("message", "").strip()
    conversation_id = fields.get("conversation_id", "").strip()
    if not text:
        return RedirectResponse("/world", status_code=303)
    try:
        result = await command_center(CommandBody(
            text=text[:500], conversation_id=conversation_id[:80]))
    except HTTPException:
        return RedirectResponse("/world", status_code=303)
    intent = result.get("intent", "chat")
    landing = "/chat"
    if intent in ("research_project", "inventory_status",
                  "project_overview") and result.get("mission"):
        landing = f"/missions/{result['mission']['mission_id']}"
    elif intent == "morning_report":
        landing = "/morning"
    elif intent == "agenda_today":
        landing = "/agenda"
    elif intent in ("mission_status", "mission_stop", "mission_resume"):
        landing = "/missions"
    else:
        convo = result.get("conversation_id", "") or conversation_id
        landing = f"/chat?id={convo}" if convo else "/chat"
    try:
        from .context_engine import record_trace
        record_trace(text[:300], [
            {"stage": "INTENT", "detail": intent},
            {"stage": "CONTEXT",
             "detail": "bounded compose (inventory/memory/research/"
                       "nodes/missions)"},
            {"stage": "RESULT", "detail": f"landed on {landing}"},
        ], {"intent": intent, "landing": landing})
    except Exception:
        pass
    return RedirectResponse(landing, status_code=303)


@app.get("/memory", response_class=HTMLResponse)
def memory_page(memory_type: str = "") -> str:
    from . import ui as _ui
    from .memory import MEMORY_TYPES, list_memories
    try:
        entries = list_memories(memory_type=memory_type,
                                limit=50)
    except Exception:
        entries = []
    options = "".join(
        f"<option value='{kind}'"
        + (" selected" if kind == memory_type else "")
        + f">{kind or 'all types'}</option>"
        for kind in ["", *MEMORY_TYPES])
    cards = "".join(
        f"<div class=\"sprout\"><b>{_ui.esc(entry.title)}</b><br>"
        f"{_ui.chip(entry.memory_type)}{_ui.truth_chip(entry.truth)}"
        f"<br><span class=\"muted\">importance {entry.importance:.1f} · "
        f"{_ui.esc(entry.project_ref or 'no project')} · "
        f"{_ui.esc(entry.observed_at[:10])}</span></div>"
        for entry in entries) or _ui.empty()
    main = f"""<h1>Memory</h1>
    <p class="muted">Truth tiers stay visible: verified and user facts read different from AI suggestions. Health memories only appear with explicit health scope.</p>
    <form method='get' action='/memory' role="search" aria-label="Filter memories"><select name='memory_type' onchange='this.form.submit()' aria-label="Memory type">{options}</select></form>
    <div class="grove">{cards}</div>"""
    return _ui.shell("Memory", "/memory", main, "",
                     _ui.command_bar())


@app.get("/health", response_class=HTMLResponse)
def health_page() -> str:
    from . import ui as _ui
    from .health import list_measurements, personal_health_index
    index = personal_health_index()
    dims = "".join(
        f"<tr><td>{_ui.esc(name)}</td>"
        f"<td>{_ui.esc(str(info['value']))}</td>"
        f"<td>{_ui.esc(str(info['completeness']))}</td>"
        f"<td><small>{_ui.esc(str(info['method']))}</small></td></tr>"
        for name, info in index["dimensions"].items())
    recent = list_measurements(limit=20)
    rows = "".join(
        f"<tr><td>{_ui.esc(entry.metric)}</td>"
        f"<td>{_ui.esc(str(entry.value))}</td>"
        f"<td>{_ui.esc(entry.unit)}</td>"
        f"<td>{_ui.esc(entry.source)}"
        f"{' (MOCK: ' + _ui.esc(entry.provenance.creator_id) + ')' if 'mock' in entry.provenance.creator_id else ''}</td>"
        f"<td>{_ui.esc(entry.observed_at[:16])}</td></tr>"
        for entry in recent) or "<tr><td colspan='5'>—</td></tr>"
    main = f"""<h1>Health</h1>
    <p class="muted">Tracking only — { _ui.esc(str(index['overall_completeness']))} · overall {_ui.esc(str(index['overall']))} ({_ui.esc(index['overall_method'])})</p>
    <h2>Index dimensions</h2><table><tr><th>Dimension</th><th>Value</th><th>Completeness</th><th>Method</th></tr>{dims}</table>
    <h2>Recent measurements</h2><table><tr><th>Metric</th><th>Value</th><th>Unit</th><th>Source</th><th>Observed</th></tr>{rows}</table>"""
    return _ui.shell("Health", "/health", main, "",
                     _ui.command_bar())


@app.get("/skills", response_class=HTMLResponse)
def skills_page() -> str:
    from . import ui as _ui
    from .skills import list_candidates, list_skills
    owned = list_skills(limit=100)
    candidates = list_candidates()
    skill_cards = "".join(
        f"<div class=\"sprout\"><b>{_ui.esc(skill.name)}</b><br>"
        f"{_ui.chip(skill.stage)}{_ui.chip(skill.proficiency)}"
        f"<br><span class=\"muted\">{len(skill.evidence)} evidence</span></div>"
        for skill in owned) or _ui.empty("No owned skills yet — discover some from a project.")
    cand_rows = "".join(
        f"<tr><td>{_ui.esc(item.name)}</td>"
        f"<td>{_ui.esc(item.project_ref or '—')}</td>"
        f"<td>{_ui.esc(item.status)}</td></tr>"
        for item in candidates) or "<tr><td colspan='3'>—</td></tr>"
    main = f"""<h1>Skills</h1>
    <h2>Owned</h2><div class="grove">{skill_cards}</div>
    <h2>Candidates</h2><table><tr><th>Name</th><th>Project</th><th>Status</th></tr>{cand_rows}</table>"""
    return _ui.shell("Skills", "/skills", main, "",
                     _ui.command_bar())


@app.get("/research", response_class=HTMLResponse)
def research_page() -> str:
    """Living research workshop: runs, dossiers, findings,
    sources, contradictions, open questions. SOURCE vs
    MYCELIUM SYNTHESIS stay labelled; TEST/REAL/UNAVAILABLE
    states stay visible."""
    from . import ui as _ui
    from .research_engine import list_dossiers, list_runs
    runs = list_runs(limit=20)
    dossiers = list_dossiers(limit=10)
    run_cards = "".join(
        f"<div class=\"sprout\"><b>{_ui.esc(run.question[:90])}</b><br>"
        f"{_ui.status_dot(run.status)}{_ui.chip(run.status)}"
        f"{_ui.chip(run.execution_state)}"
        f"<span class=\"muted\">{len(run.source_ids)} bronnen · "
        f"{len(run.claims)} claims · "
        f"{len(run.contradictions)} verschillen</span><br>"
        + (f"<a href='/research/{_ui.esc(run.dossier_id)}'>"
            "Open dossier</a>" if run.dossier_id else
            "<span class=\"muted\">nog geen dossier</span>")
        + "</div>"
        for run in runs) or _ui.empty(
            "Nog geen onderzoek — stel hieronder een vraag.")
    dossier_cards = "".join(
        f"<div class=\"sprout\"><b>{_ui.esc(item.title[:90])}</b><br>"
        f"{_ui.chip(item.execution_state)}"
        f"<span class=\"muted\">"
        f"{'AI-synthesis' if item.synthesis_available else 'extractie'}</span><br>"
        f"<a href='/research/{_ui.esc(item.dossier_id)}'>"
        "Open dossier</a></div>"
        for item in dossiers)
    open_q = []
    for item in dossiers[:5]:
        open_q.extend(item.open_questions[:3])
    questions = "".join(
        f"<li>{_ui.esc(question[:200])} "
        f"<span class=\"muted\">[OPEN QUESTION]</span></li>"
        for question in open_q[:8])
    main = f"""<h1>Research workshop</h1>
    <p class="muted">The research network, read-only always: bounded questions, allow-listed transports, provenance on every claim. Phone → coordinator → queue → Linux nodes → Ollama → dossier → knowledge → project → mission. Which node researched what is visible per run; contradictions surface as candidates.</p>
    <div class="panel"><h2>Onderzoeksvraag</h2>
    <form method="post" action="/web/research">
    <input type="text" name="question" placeholder="Onderzoek mijn camper…" style="width:70%" aria-label="Research question" autocomplete="off">
    <select name="provider" aria-label="Provider"><option value="wikipedia">web (Wikipedia)</option><option value="unavailable">droog (unavailable-pad)</option></select>
    <button type="submit">Start research</button></form>
    <p class="muted">Start een dossier direct, of vraag via het Command Center — een missie vraagt eerst jouw YES.</p></div>
    <h2>Active research</h2><div class="grove">{run_cards}</div>
    <h2>Recent dossiers</h2><div class="grove">{dossier_cards or _ui.empty("Nog geen dossiers.")}</div>
    <h2>Open questions</h2><ul>{questions or "<li>—</li>"}</ul>"""
    return _ui.shell("Research", "/research", main, "",
                     _ui.command_bar())


@app.get("/research/{dossier_id}", response_class=HTMLResponse)
def research_dossier_page(dossier_id: str):
    """Dossier detail: every claim links back to its source."""
    from . import ui as _ui
    from .research import get_source
    from .research_engine import load_dossier, load_run
    dossier = load_dossier(dossier_id)
    if dossier is None:
        return HTMLResponse("Dossier not found", status_code=404)
    run = load_run(dossier.run_id)
    findings = "".join(
        f"<li><span class=\"chip\">{_ui.esc(str(finding.get('label', 'SOURCE')))}</span> "
        f"{_ui.esc(str(finding.get('text', ''))[:300])}<br>"
        f"<span class=\"muted\">bron: {_ui.esc(str(finding.get('source_id', '')))} · "
        f"{_ui.esc(str(finding.get('execution_state', '')))}</span></li>"
        for finding in dossier.key_findings)
    claims = "".join(
        f"<li>{_ui.esc(str(claim.get('text', ''))[:280])}<br>"
        f"<span class=\"muted\">{_ui.esc(str(claim.get('claim_type', '')))} · "
        f"bewijs: {_ui.esc(str(claim.get('evidence', ''))[:200])}</span></li>"
        for claim in dossier.claims)
    sources = ""
    for meta in dossier.sources:
        entry = get_source(str(meta.get("source_id", "")))
        evidence = (entry.content[:400] if entry else "")
        sources += (
            f"<div class=\"sprout\"><b>SOURCE · "
            f"{_ui.esc(str(meta.get('title', ''))[:100])}</b><br>"
            f"<span class=\"muted\">"
            f"{_ui.esc(str(meta.get('url', ''))[:120])}</span><br>"
            f"<span class=\"muted\">opgehaald "
            f"{_ui.esc(str(meta.get('retrieved_at', ''))[:16])} · "
            f"{_ui.esc(str(meta.get('execution_state', '')))} · "
            f"{_ui.esc(str(meta.get('provider', '')))} · "
            f"{meta.get('claims', 0)} claims</span>"
            f"<p>{_ui.esc(evidence[:400])}</p></div>")
    contradictions = "".join(
        f"<li><b>{_ui.esc(str(group.get('subject', '')))} · "
        f"{_ui.esc(str(group.get('predicate', '')))}</b><br>"
        f"<span class=\"muted\">{_ui.esc(str(group.get('detected_reason', ''))[:300])} "
        f"[onopgelost]</span></li>"
        for group in dossier.contradictions)
    questions = "".join(
        f"<li>{_ui.esc(question[:220])}<br>"
        f"<form method=\"post\" action=\"/web/research/dossiers/"
        f"{_ui.esc(dossier.dossier_id)}/questions/{number}/candidate\" "
        f"style=\"display:inline\">"
        f"<button type=\"submit\">Remember as candidate</button></form></li>"
        for number, question in enumerate(dossier.open_questions))
    entities = "".join(
        f"<li>{_ui.esc(str(link.get('entity_id', '')))} — "
        f"{_ui.esc(str(link.get('reason', ''))[:120])}"
        f"{' [kandidaat]' if link.get('candidate') else ''}</li>"
        for link in dossier.related_entities)
    timeline = ""
    if run is not None:
        timeline = (
            f"<li>aangemaakt { _ui.esc(run.created_at[:16])}</li>"
            f"<li>gestart { _ui.esc(run.started_at[:16])}</li>"
            f"<li>afgerond { _ui.esc(run.completed_at[:16])}</li>"
            f"<li>queries: { _ui.esc(', '.join(query.text[:60] for query in run.queries[:3]))}</li>")
    main = f"""<h1>{_ui.esc(dossier.title[:120])}</h1>
    <p>{_ui.status_dot(dossier.execution_state)}<b>{_ui.esc(dossier.execution_state)}</b> · status run: {_ui.esc(run.status if run else '?')} · {'<b>MYCELIUM SYNTHESIS</b> (' + _ui.esc(dossier.generated_by) + ')' if dossier.synthesis_available else '<b>EXTRACTIE</b> (geen AI-synthesis — model unavailable)'}</p>
    <div class="panel"><h2>Samenvatting</h2><p>{_ui.esc(dossier.summary[:2000])}</p></div>
    <h2>Key findings</h2><ul>{findings or "<li>—</li>"}</ul>
    <h2>Claims</h2><ul>{claims or "<li>—</li>"}</ul>
    <h2>Source evidence</h2><div class="grove">{sources or _ui.empty()}</div>
    <h2>Contradictions</h2><ul>{contradictions or "<li>Geen verschillen gevonden.</li>"}</ul>
    <h2>Open questions</h2><ul>{questions or "<li>—</li>"}</ul>
    <h2>Related entities</h2><ul>{entities or "<li>—</li>"}</ul>
    <h2>Provenance</h2><p class="muted">external-source · {_ui.esc(dossier.provenance.creator_id)} · human_verified=false · run {_ui.esc(dossier.run_id)}{' · memory ' + _ui.esc(run.memory_id) if run and run.memory_id else ''}</p>
    <h2>Maak taak van dossier</h2><div class="panel">
    <form method="post" action="/web/research/dossiers/{_ui.esc(dossier.dossier_id)}/task">
    <input type="text" name="kind" placeholder="kind, e.g. research.fetch_url" style="width:30%" aria-label="Task kind">
    <input type="text" name="question_index" placeholder="open question # (optional)" style="width:24%" aria-label="Open question index">
    <button type="submit">Queue task</button></form>
    <p class="muted">Dossiers zijn geen AdapterProposals (daarvoor bestaat proposal_to_task), dus deze bridge gebruikt de bestaande POST /api/v1/tasks met dossier/run/question in de payload als provenance. Geen uitvoering bij creatie.</p></div>
    <h2>Timeline</h2><ul>{timeline}</ul>"""
    return _ui.shell("Dossier", "/research", main, "",
                     _ui.command_bar())


@app.post("/web/research/dossiers/{dossier_id}/questions/{index}/candidate")
async def web_question_to_candidate(dossier_id: str,
                                    index: int) -> Response:
    from .events import new_event as _bus_new, \
        save_event as _bus_save
    from .inventory_read import Provenance
    from .knowledge import (CandidateRefusedError, new_candidate,
                            save_candidate)
    from .research_engine import load_dossier
    dossier = load_dossier(dossier_id)
    try:
        question = (dossier.open_questions or [])[int(index)]
    except (AttributeError, IndexError, ValueError, TypeError):
        return RedirectResponse(f"/research/{dossier_id}",
                                status_code=303)
    if dossier is None:
        return RedirectResponse("/research", status_code=303)
    try:
        entry = new_candidate(
            f"research question: {question[:140]}", "question",
            summary=question[:1500],
            provenance=Provenance(
                source_type="external-source",
                creator_id=f"research:{dossier.run_id}",
                human_verified=False),
            source_refs=[{"kind": "research", "id": dossier_id,
                          "label": dossier.title[:120]}])
        save_candidate(entry)
        _bus_save(_bus_new(
            "candidate.observed",
            f"Candidate {entry.candidate_id} from dossier "
            f"{dossier_id}"))
    except CandidateRefusedError:
        pass
    return RedirectResponse(f"/research/{dossier_id}",
                            status_code=303)


@app.post("/web/research/dossiers/{dossier_id}/task")
async def web_dossier_task_create(dossier_id: str,
                                  request: Request) -> Response:
    """Smallest UI bridge: queue one task carrying this dossier as
    payload provenance via the existing create_task. proposal_to_task
    does not apply here (dossiers are not AdapterProposals); the
    dossier/run/question travel in the payload, never as commands."""
    from fastapi import HTTPException as _HTTPException
    from .research_engine import load_dossier
    dossier = load_dossier(dossier_id)
    if dossier is None:
        return RedirectResponse("/research", status_code=303)
    fields = await _form_fields(request)
    kind = fields.get("kind", "").strip()
    if not kind:
        return RedirectResponse(f"/research/{dossier_id}",
                                status_code=303)
    question = ""
    raw_index = fields.get("question_index", "").strip()
    if raw_index.isdigit():
        try:
            question = str((dossier.open_questions or [])[int(raw_index)])
        except (IndexError, ValueError, TypeError):
            question = ""
    try:
        created = create_task(TaskCreate(
            kind=kind,
            payload={"dossier_id": dossier_id, "run_id": dossier.run_id,
                     "question": question[:500],
                     "title": dossier.title[:200]},
            required_capabilities=[]))
    except (_HTTPException, ValueError):
        return RedirectResponse(f"/research/{dossier_id}",
                                status_code=303)
    return RedirectResponse(f"/tasks/{created.get('id', '')}",
                            status_code=303)


@app.post("/web/research")
async def web_research(request: Request) -> Response:
    """Research form: open + execute a run directly (explicit
    operator action), then land on the dossier or the run."""
    from .research_engine import load_run as _load
    fields = await _form_fields(request)
    question = fields.get("question", "").strip()
    provider_name = fields.get("provider", "wikipedia").strip()
    if not question:
        return RedirectResponse("/research", status_code=303)
    try:
        provider = _research_provider(provider_name, None)
    except HTTPException:
        return RedirectResponse("/research", status_code=303)
    from .research_engine import new_run as _new, save_run as _save
    try:
        run = _new(question[:500], requested_by="web")
        _save(run)
    except Exception:
        return RedirectResponse("/research", status_code=303)
    try:
        finished = await _execute_research_run(
            run.run_id, provider, 6)
    except HTTPException:
        return RedirectResponse("/research", status_code=303)
    if finished.get("dossier_id"):
        return RedirectResponse(
            f"/research/{finished['dossier_id']}", status_code=303)
    return RedirectResponse("/research", status_code=303)


@app.get("/devices", response_class=HTMLResponse)
def devices_page() -> str:
    from . import ui as _ui
    from .drones import list_drones
    from .familiars import list_familiars
    from .robots import list_robots
    cards = "".join(
        f"<div class=\"sprout\"><b>{_ui.esc(item.name)}</b> {_ui.chip('robot')}<br>"
        f"{_ui.status_dot(item.status)}{_ui.esc(item.status)} · safety {_ui.esc(item.safety_state)}</div>"
        for item in list_robots())
    cards += "".join(
        f"<div class=\"sprout\"><b>{_ui.esc(item.name)}</b> {_ui.chip('drone')}<br>"
        f"{_ui.status_dot(item.status)}{_ui.esc(item.status)} · safety {_ui.esc(item.safety_state)}</div>"
        for item in list_drones())
    cards += "".join(
        f"<div class=\"sprout\"><b>{_ui.esc(item.name)}</b> {_ui.chip(item.kind)}<br>"
        f"{_ui.status_dot(item.status)}{_ui.esc(item.status)}</div>"
        for item in list_familiars())
    main = f"""<h1>Devices</h1>
    <p class="muted">One capability model for every helper. Physical execution stays behind safety gates — nothing here moves on its own.</p>
    <div class="grove">{cards or _ui.empty('No devices registered.')}</div>"""
    return _ui.shell("Devices", "/devices", main, "",
                     _ui.command_bar())


@app.get("/watcher", response_class=HTMLResponse)
def watcher_page() -> str:
    from . import ui as _ui
    from datetime import datetime as _dt
    from datetime import timezone as _tz
    current = _dt.now(_tz.utc)
    with connection() as db:
        task_rows = db.execute(
            "SELECT id, status, created_at FROM tasks "
            "ORDER BY id DESC LIMIT 200").fetchall()
    findings = []
    try:
        findings += scan_stale_tasks(
            [dict(row) for row in task_rows], current)
        findings += scan_failed_tasks(
            [dict(row) for row in task_rows], current)
        findings += scan_blocked_tasks(
            [dict(row) for row in task_rows], current)
    except WatcherRefusedError:
        pass
    cards = "".join(
        f"<div class=\"sprout\"><b>{_ui.esc(item.kind.replace('_', ' '))}</b><br>"
        f"{_ui.esc(item.summary)}</div>"
        for item in findings[:50]) or \
        _ui.empty("All quiet — the watcher found nothing.")
    main = f"""<h1>Watcher findings</h1>
    <p class="muted">Findings only — the watcher never executes. Each card explains why it exists.</p>
    <div class="grove">{cards}</div>"""
    return _ui.shell("Watcher", "/watcher", main, "",
                     _ui.command_bar())


@app.get("/chat", response_class=HTMLResponse)
def chat_page(id: str | None = None) -> str:
    from . import ui as _ui
    init_chat_database()
    with chat_connection() as db:
        conversations = db.execute(
            """SELECT conversation_id, title, created_at FROM conversations
            ORDER BY created_at DESC LIMIT 20""").fetchall()
    active = id or (conversations[0]["conversation_id"]
                    if conversations else None)
    history = _chat_messages(active) if active else []
    waiting = [row for row in _desktop_list(limit=100,
                                            status="pending_approval")]
    options = "".join(
        f"<option value='{_ui.esc(row['conversation_id'])}'"
        + (" selected" if row["conversation_id"] == active else "")
        + f">{_ui.esc(row['title'] or row['conversation_id'])}</option>"
        for row in conversations)
    turns = "".join(
        f"<article class='sprout' aria-label='{msg['role']} message'>"
        f"<b>{_ui.esc(msg['role'])}</b>"
        f"<p>{_ui.link_entities(msg['content'])}</p></article>"
        for msg in history)
    try:
        live = coordinator_status()
        live_html = (
            f"<p class=\"muted\">Interface: web · nodes "
            f"{live['nodes']['online']} online / "
            f"{live['nodes']['stale']} stale · open approvals: "
            f"desktop {live['pending_approvals']['desktop_actions']}, "
            f"writes {live['pending_approvals']['write_proposals']}, "
            f"missions {live['pending_approvals']['missions']} · "
            f"<a href='/mobile'>mobile</a> · "
            f"<a href='/api/v1/status'>status (JSON)</a></p>")
    except (ValueError, KeyError):
        live_html = ""
    main = f"""<h1>Mycelium Chat</h1>
    {live_html}
    <p><label>Conversation: <select onchange="location='/chat?id='+this.value" aria-label="Conversation">{options}</select></label>
    <a href="/chat">+ new conversation</a></p>
    {f"<div class='panel'>⏳ <a href='/agents'>{len(waiting)} desktop action(s) waiting for approval</a> — the Desktop Agent only acts after your YES.</div>" if waiting else ""}
    <form method="post" action="/web/missions">
    <input type="hidden" name="conversation_id" value="{_ui.esc(active or '')}">
    <input type="text" name="goal" placeholder="Start a mission…" style="width:70%" aria-label="Mission goal">
    <button type="submit">Start mission</button></form>
    {turns or "<p>Ask anything — entity references like obj_… or mem_… become clickable and focus the world.</p>"}
    <form method="post" action="/web/chat">
    <input type="hidden" name="conversation_id" value="{_ui.esc(active or '')}">
    <textarea name="message" placeholder="What can I make with my parts?" aria-label="Message"></textarea><br><br>
    <button type="submit">Send</button></form>"""
    return _ui.shell("Chat", "/chat", main, "",
                     _ui.command_bar())


@app.post("/web/chat")
async def web_chat(request: Request) -> RedirectResponse:
    fields = await _form_fields(request)
    try:
        body = ChatRequest(
            conversation_id=fields.get("conversation_id", "").strip() or None,
            message=fields.get("message", "").strip())
    except ValueError:
        # Oversized/malformed input refuses honestly, never 500s.
        return RedirectResponse("/chat", status_code=303)
    if not body.message:
        return RedirectResponse("/chat", status_code=303)
    answer = await chat(body)
    return RedirectResponse(f"/chat?id={answer.conversation_id}",
                            status_code=303)


@app.get("/agents", response_class=HTMLResponse)
def agents_page() -> str:
    from . import ui as _ui
    status = agent_status()
    online = status["agents_online"] > 0
    current = status["current_action"]
    if current:
        current_html = (
            f"<p>Current action: <code>{_ui.esc(current['action_type'])}</code> "
            f"with {_ui.esc(str(current['parameters']))}</p>"
            f"<p>Status: {_ui.status_dot(current['status'])}{_ui.esc(current['status'])}"
            + (f" · approved by {_ui.esc(current['decided_by'])}"
               if current["decided_by"] else "")
            + (f" · dispatched by {_ui.esc(current['dispatched_by'])}"
               if current["dispatched_by"] else "")
            + "</p>")
    else:
        current_html = "<p>No running action.</p>"
    nodes_html = "".join(
        f"<li>{_ui.status_dot(node['status'])}{_ui.esc(node['node_id'])} "
        f"({_ui.esc(node['status'])}, seen {_ui.esc(str(node['last_seen']))})<br><small>"
        f"{_ui.esc(', '.join(node['capabilities']))}</small></li>"
        for node in status["desktop_nodes"]) or "<li>No desktop agent</li>"
    try:
        _queue_rows = list_tasks()
    except Exception:
        _queue_rows = []
    try:
        _queue_nodes = [node for node in list_nodes()
                        if not any("desktop" in str(cap).lower()
                                   for cap in node.get("capabilities", []))]
    except Exception:
        _queue_nodes = []
    workers_html = "".join(
        f"<li>{_ui.status_dot(node.get('derived_status', ''))}"
        f"{_ui.esc(node.get('node_id', ''))} "
        f"({_ui.esc(node.get('derived_status', ''))}, tier "
        f"{_ui.esc(str(node.get('tier', '')))}, seen "
        f"{_ui.esc(str(node.get('last_seen', ''))[:16])})<br><small>"
        f"{_ui.esc(', '.join(node.get('capabilities', [])[:10]))}</small>"
        + (f"<br><small>⚙ <a href=\"/tasks/{(node.get('current_task') or {}).get('task_id', '')}\">task #{(node.get('current_task') or {}).get('task_id', '')}</a></small>"
           if node.get("current_task") else "<br><small>idle</small>")
        + "</li>"
        for node in _queue_nodes) or "<li>No queue workers registered</li>"
    queue_open = sum(1 for row in _queue_rows
                     if str(row.get("status", "")) == "queued")
    queue_busy = sum(1 for row in _queue_rows
                     if str(row.get("status", "")) == "assigned")
    waiting = sum(1 for entry in status["waiting"]
                  if entry["status"] == "pending_approval")
    done = sum(1 for entry in status["activity"]
               if entry["status"] == "completed")
    items = "".join(
        f"<li>{_ui.status_dot(entry['status'])}"
        f"<code>{_ui.esc(entry['action_type'])}</code> "
        f"{_ui.esc(entry['action_id'])} — {_ui.esc(entry['status'])}"
        + (f" · decided_by {_ui.esc(entry['decided_by'])}"
           if entry["decided_by"] else "")
        + (f" · dispatched_by {_ui.esc(entry['dispatched_by'])}"
           if entry["dispatched_by"] else "")
        + (_result_suffix(entry) or "")
        + (f" <form style='display:inline' method='post' action=\"/web/desktop/{_ui.esc(entry['action_id'])}/decision\">"
           f"<input type='hidden' name='response' value='YES'>"
           f"<button>Approve</button></form>"
           f" <form style='display:inline' method='post' action=\"/web/desktop/{_ui.esc(entry['action_id'])}/decision\">"
           f"<input type='hidden' name='response' value='NO'>"
           f"<button>Reject</button></form>"
            f" <form style='display:inline' method='post' action=\"/web/desktop/{_ui.esc(entry['action_id'])}/cancel\">"
            f"<button>Stop</button></form>" if entry["status"] == "pending_approval" else "")
        + (f" <form style='display:inline' method='post' action=\"/web/desktop/{_ui.esc(entry['action_id'])}/dispatch\">"
           f"<button>Dispatch</button></form>"
           f"<span class=\"muted\">approved — releases to the local runtime; the agent claims via its poll loop</span>"
           if entry["status"] == "approved" else "")
        + "</li>"
        for entry in status["activity"])
    main = f"""<h1>Agents</h1>
    <div class="panel"><p>Desktop Agent: <b>{"online" if online else "offline"}</b> ({status["agents_online"]} desktop node(s))</p>
    <p class="muted"><b>AI thinks</b> · <b>agent acts</b> · <b>human approval decides</b></p>
    <p>Waiting approval: <b>{waiting}</b> · completed: <b>{done}</b> · progress via <a href="/chat">Chat</a></p>
    <p>Queue: <b>{queue_open}</b> open · <b>{queue_busy}</b> assigned — full view in <a href="/tasks">Tasks</a>, all gates in <a href="/approvals">Approvals</a></p>
    {current_html}</div>
    <h2>Desktop agents</h2><ul>{nodes_html}</ul>
    <h2>Queue workers (task nodes)</h2><ul>{workers_html}</ul>
    <h2>Activity</h2><ul>{items or "<li>No actions yet</li>"}</ul>"""
    return _ui.shell("Agents", "/agents", main, "",
                     _ui.command_bar())


def _result_suffix(entry: dict) -> str:
    result = entry.get("result") or {}
    if not result:
        return ""
    parts = f" → {escape(str(result.get('status', '')))}"
    if result.get("observation_reference"):
        parts += f" · obs {escape(str(result['observation_reference']))}"
    if result.get("error"):
        parts += f" · {escape(str(result['error'])[:120])}"
    return parts


@app.get("/missions", response_class=HTMLResponse)
def missions_page() -> str:
    from . import ui as _ui
    from .missions import current_step_of as _current_step
    cards = ""
    for m in [_mission_to_json(mission)
              for mission in list_missions()]:
        loaded = load_mission(m["mission_id"])
        waiting = _v1_waiting_reason(loaded) if loaded else ""
        dot = _ui.mission_glyph(m["status"])
        done_steps = sum(1 for step in m["steps"]
                         if step.get("status") in
                         ("done", "completed", "skipped"))
        growth = _ui.growth_class(m["status"], done_steps,
                                  len(m["steps"]))
        quest = _ui.quest_steps([
            {"status": step.get("status", "open"),
             "description": f"{step.get('kind', '')} — "
                            f"{step.get('description', '')[:80]}"}
            for step in m["steps"][:6]])
        cards += (
            f"<div class=\"sprout {growth} grain\"><b>{dot} "
            f"{_ui.esc(m['goal'][:90])}</b><br>"
            f"{_ui.status_dot(m['status'])}{_ui.chip(m['status'])}"
            f"<span class=\"muted\">step {m['current_step']}/"
            f"{len(m['steps'])}</span><br>"
            f"<span class=\"muted\">{_ui.esc(waiting[:220])}</span><br>"
            f"{quest}"
            f"<a href='/missions/{_ui.esc(m['mission_id'])}'>"
            "Open process</a></div>")
    main = f"""<h1>Missions — quests with guardrails</h1>
    <p class="muted">Quests are missions wearing work clothes: same plan, same exact-YES approvals, same visible steps. No game button ever skips a safety gate.</p>
    <div class="panel"><p>Autonomy exists only <b>inside</b> an approved plan. Approved is not executed — execution is a separate, visible step.</p>
    <form method="post" action="/web/missions/from-template">
    <select name="template_id" aria-label="Template">
    <option value="inspect_project">Explore project</option>
    <option value="investigate_inventory">Investigate INVENTory</option>
    <option value="analyze_problem">Analyze problem</option>
     <option value="prepare_build_plan">Prepare build plan</option>
     <option value="inspect_desktop_project">View desktop project</option>
     <option value="research_topic">Research topic (web)</option>
    </select>
    <input type="text" name="goal" placeholder="Goal" style="width:40%" aria-label="Goal">
    <button type="submit">Start from template</button></form>
    <p class="muted">Tip: start from <a href="/chat">chat</a> — a mission belongs to a conversation.</p></div>
    <div class="grove">{cards or _ui.empty("No missions yet — start one from Chat.")}</div>"""
    return _ui.shell("Missions", "/missions", main, "",
                     _ui.command_bar())


@app.get("/missions/{mission_id}", response_class=HTMLResponse)
def mission_page(mission_id: str) -> str:
    from . import ui as _ui
    mission = load_mission(mission_id)
    if mission is None:
        return HTMLResponse("Mission not found", status_code=404)
    done = sum(1 for step in mission.steps
               if step.status in ("completed", "skipped"))
    total = len(mission.steps)
    percent = int(100 * done / total) if total else 0
    path = []
    for index, step in enumerate(mission.steps):
        cls = "done" if step.status in ("completed", "skipped") \
            else "now" if index == mission.current_step and \
            mission.status in ("approved", "running") else ""
        if step.status in ("failed", "blocked"):
            cls = "blocked"
        path.append(
            f"<span class=\"step {cls}\">{_ui.esc(step.kind)} · "
            f"{_ui.esc(step.status)}</span>")
    steps = "".join(
        f"<li>{_ui.status_dot(step.status)}<b>{_ui.esc(step.kind)}</b> "
        f"{_ui.esc(step.description)} — {_ui.esc(step.status)}"
        + (f" · obs {_ui.esc(step.observation_reference)}"
           if step.observation_reference else "")
        + (f" · action {_ui.esc(step.desktop_action_id)}"
           if step.desktop_action_id else "")
        + (f" · <i>{_ui.esc(step.error[:160])}</i>" if step.error else "")
        + "</li>"
        for step in mission.steps)
    events = "".join(
        f"<li><small>{_ui.esc(event.created_at)}</small> "
        f"<b>{_ui.esc(event.event_type)}</b> {_ui.esc(event.message[:200])}</li>"
        for event in list_events(mission_id=mission_id)[-20:])
    first_entity = ""
    for record in (mission.context_records or []):
        if record.get("entity_id"):
            first_entity = str(record["entity_id"])
            break
    buttons = ""
    if mission.status == "pending_approval":
        buttons += (f"<form style='display:inline' method='post' action='/web/missions/{_ui.esc(mission_id)}/approve'>"
                    "<button>APPROVE plan</button></form> ")
    if mission.status in ("approved", "running"):
        buttons += (f"<form style='display:inline' method='post' action='/web/missions/{_ui.esc(mission_id)}/tick'>"
                    "<button>Next step</button></form> ")
    if mission.status in ("approved", "running"):
        buttons += (f"<form style='display:inline' method='post' action='/web/missions/{_ui.esc(mission_id)}/run'>"
                    "<button>Run loop</button></form> ")
    if mission.status == "running":
        buttons += (f"<form style='display:inline' method='post' action='/web/missions/{_ui.esc(mission_id)}/pause'>"
                    "<button>Pause</button></form> ")
    if mission.status == "paused":
        buttons += (f"<form style='display:inline' method='post' action='/web/missions/{_ui.esc(mission_id)}/resume'>"
                    "<button>Resume</button></form> ")
    if mission.status not in ("completed", "failed", "cancelled",
                              "blocked"):
        buttons += (f"<form style='display:inline' method='post' action='/web/missions/{_ui.esc(mission_id)}/cancel'>"
                    "<button>STOP</button></form>")
    main = f"""<h1>MISSION</h1>
    <div class="panel"><p>{_ui.esc(mission.goal)}</p>
    <p>{percent}% · {_ui.status_dot(mission.status)}<b>{_ui.esc(mission.status)}</b> · step {mission.current_step}/{total}</p>
    <div class="path" aria-label="Mission steps">{"<span class='arrow'>→</span>".join(path)}</div>
    <p class="muted">Proposed and approved are not executed. Execution shows as its own step with its own result.</p>
    <p>{buttons}</p>
    {f"<p class=\"muted\">World: <a href='/world?entity_id={_ui.esc(first_entity)}'>graph around first context entity</a></p>" if first_entity else ""}</div>
    <h2>Queue a task of this plan</h2><div class="panel">
    <form method="post" action="/web/missions/{_ui.esc(mission_id)}/tasks">
    <input type="text" name="kind" placeholder="kind, e.g. system_inventory" style="width:30%" aria-label="Task kind">
    <input type="text" name="capabilities" placeholder="capabilities, comma separated" style="width:40%" aria-label="Required capabilities">
    <button type="submit">Queue task</button></form>
    <p class="muted">The task carries this mission_id as traceability; it never executes on creation. Nodes claim via the existing queue.</p></div>
    <h2>Steps</h2><ul>{steps}</ul>
    <h2>Tasks (delegation of this plan)</h2><ul>{_mission_tasks_html(mission_id)}</ul>
    <h2>Events</h2><ul>{events or "<li>—</li>"}</ul>
    <h2>Automation</h2><ul>{_mission_automation_html(mission_id)}</ul>"""
    return _ui.shell("Mission", "/missions", main, "",
                     _ui.command_bar())


@app.post("/web/missions/{mission_id}/tasks")
async def web_mission_task_create(mission_id: str,
                                  request: Request) -> RedirectResponse:
    """Smallest UI bridge: queue one task bound to this mission via the
    existing create_task (same mission_id traceability validation, no
    execution). Unknown missions refuse back to the mission list."""
    from fastapi import HTTPException as _HTTPException
    if load_mission(mission_id) is None:
        return RedirectResponse("/missions", status_code=303)
    fields = await _form_fields(request)
    kind = fields.get("kind", "").strip()
    if not kind:
        return RedirectResponse(f"/missions/{mission_id}",
                                status_code=303)
    capabilities = [part.strip() for part in
                    fields.get("capabilities", "").replace(";", ",").split(",")
                    if part.strip()][:20]
    try:
        created = create_task(TaskCreate(
            kind=kind, required_capabilities=capabilities,
            mission_id=mission_id))
    except (_HTTPException, ValueError):
        return RedirectResponse(f"/missions/{mission_id}",
                                status_code=303)
    return RedirectResponse(f"/tasks/{created.get('id', '')}",
                            status_code=303)


def _mission_automation_html(mission_id: str) -> str:
    """Automation runs linked to one mission, with drive buttons."""
    from . import ui as _ui
    try:
        from .automation import list_runs
        linked = [run for run in list_runs(limit=200)
                  if run.mission_id == mission_id][:5]
    except Exception:
        linked = []
    rows = "".join(
        f"<li><a href=\"/automation/{_ui.esc(run.run_id)}\">"
        f"{_ui.esc(run.goal[:80])}</a> "
        f"{_ui.status_dot(run.state)}{_ui.esc(run.state)} "
        f"<form method=\"post\" "
        f"action=\"/web/automation/runs/{_ui.esc(run.run_id)}/drive\" "
        f"style=\"display:inline\"><button>Drive</button></form></li>"
        for run in linked)
    return rows or ("<li>No automation linked — start one from "
                    "<a href=\"/automation\">Automation</a>.</li>")


@app.post("/web/missions/from-template")
async def web_mission_from_template(request: Request) -> RedirectResponse:
    fields = await _form_fields(request)
    goal = fields.get("goal", "").strip()
    template_id = fields.get("template_id", "").strip()
    if not goal or not template_id:
        return RedirectResponse("/missions", status_code=303)
    init_chat_database()
    with chat_connection() as db:
        row = db.execute(
            """SELECT conversation_id FROM conversations
            ORDER BY created_at DESC LIMIT 1""").fetchone()
    if row is None:
        return RedirectResponse("/chat", status_code=303)
    try:
        steps, template_max = instantiate(template_id, goal)
        records, _, _ = await _chat_world_context(goal)
        mission = _executor().create(row["conversation_id"], goal,
                                     steps, max_steps=template_max,
                                     context_records=records)
    except (ValueError, ExecutorError):
        return RedirectResponse("/missions", status_code=303)
    return RedirectResponse(f"/missions/{mission.mission_id}",
                            status_code=303)


@app.post("/web/missions")
async def web_mission_create(request: Request) -> RedirectResponse:
    fields = await _form_fields(request)
    conversation_id = fields.get("conversation_id", "").strip()
    goal = fields.get("goal", "").strip()
    if not conversation_id or not goal:
        return RedirectResponse("/chat", status_code=303)
    answer = await chat_mission(
        conversation_id, ChatMissionBody(goal=goal))
    return RedirectResponse(f"/missions/{answer['mission_id']}",
                            status_code=303)


@app.post("/web/missions/{mission_id}/{op}")
async def web_mission_op(mission_id: str, op: str) -> RedirectResponse:
    try:
        if op == "approve":
            _executor().approve(mission_id, "YES", decided_by="web")
        elif op == "pause":
            _executor().pause(mission_id)
        elif op == "resume":
            _executor().resume(mission_id)
        elif op == "cancel":
            _executor().cancel(mission_id)
        elif op == "tick":
            await _executor().tick(mission_id)
        elif op == "run":
            from .mission_loop import run_loop
            await run_loop(mission_id)
    except ExecutorError:
        pass
    except ValueError:
        pass
    return RedirectResponse(f"/missions/{mission_id}", status_code=303)


@app.get("/cameras", response_class=HTMLResponse)
def cameras_page() -> str:
    from . import ui as _ui
    rows = []
    for device in list_devices():
        latest = list_observations(device.device_id, limit=1)
        last = (f"{latest[0].observation_id} "
                f"({latest[0].created_at})" if latest else "— none")
        test_badge = ""
        if latest and "test-only" in str(
                latest[0].provenance.notes or ""):
            test_badge = _ui.chip("[TEST]", "state-TEST")
        rows.append(
            f"<li><b>{_ui.esc(device.name)}</b> "
            f"({_ui.esc(device.device_id)}, {_ui.esc(device.source)}){test_badge} — "
            f"{_ui.esc(', '.join(device.kinds))} · "
            f"<a href='/api/v1/cameras/{_ui.esc(device.device_id)}/availability'>"
            "availability (JSON)</a> · "
            f"<a href='/api/v1/cameras/{_ui.esc(device.device_id)}/observations'>"
            "observations (JSON)</a> · latest: "
            f"{_ui.esc(last)}</li>")
    devices = "".join(rows)
    detected = detect_local_imaging_devices()
    found = "".join(
        f"<li><small>{_ui.esc(str(entry.get('path', '?')))}</small></li>"
        for entry in detected.get("devices", []))
    main = f"""<h1>Camera Lab</h1>
    <p class="muted">Your Insta360 journey: camera → observation → candidate object → project → craft tree → research → dossier → world growth. Every step is real and labeled.</p>
    <div class="panel"><p>Cameras are <b>observation sources</b>, never actuators. Snapshots need a
    capture runtime; without one the API refuses (409) instead of inventing pixels.</p>
    <p class="muted">Workflow: CAMERA → CONNECT → SOURCE → SNAPSHOT → OBSERVATION → INVENTORY → ANALYSIS. Elke stap toont eerlijk wat werkt. Observations feed <a href="/craft">Craft Tree</a> and <a href="/knowledge">Knowledge</a>.</p></div>
    <div class="panel"><h2>How to connect (honest)</h2>
    <p class="muted"><b>WHAT EXISTS:</b> registration, local device scan (names only), snapshot ingest pipeline, multi-file ingest sessions, observation store, VLM description (REAL when Ollama answers, honest fallback otherwise), candidate proposals, possible-match linking, availability probe. <b>WHAT IS MISSING:</b> live Insta360 transport — no reviewed SDK path, capture refused until a real adapter lands. <b>WHAT JELLES NEEDS TO DO:</b> register the camera below, copy files into the inbox, then run a multi-file ingest session from the camera detail page.</p>
    <p>Insta360 state: <b>REGISTERED</b> possible, <b>CONNECTED</b> only with a working adapter, otherwise <b>UNAVAILABLE</b> — never fake-connected.</p></div>
    {_camera_guide_panel()}
    <h2>Registered</h2><ul>{devices or "<li>No cameras</li>"}</ul>
    <h2>Detected locally (names only, read-only)</h2><ul>{found or "<li>Nothing found / unsupported</li>"}</ul>
    <h2>Register</h2><form method="post" action="/web/cameras/register">
    <input type="text" name="name" placeholder="Name, e.g. Insta360 X4" aria-label="Camera name">
    <select name="kinds" aria-label="Kinds"><option value="snapshot">snapshot</option><option value="snapshot,webcam">snapshot+webcam</option><option value="snapshot,webcam,stream,p360">all (Insta360)</option></select>
    <select name="source" aria-label="Source"><option value="manual">manual</option><option value="usb">usb</option><option value="insta360">insta360</option></select>
    <button type="submit">Register</button></form>"""
    return _ui.shell("Cameras", "/cameras", main, "",
                     _ui.command_bar())


def _camera_guide_panel() -> str:
    """Practical Insta360 guide: how a file becomes world knowledge."""
    from . import ui as _ui
    steps = "".join(
        f"<li>{_ui.esc(text)}</li>" for text in
        ("Shoot photo/video on the Insta360.",
         "Export the file (still, frame or 360 still).",
         "Copy it into the camera inbox (names at "
         "/api/v1/camera-inbox).",
         "Run a multi-file ingest session from the camera page.",
         "Ask for a VLM description (REAL) or take the honest "
         "fallback (UNAVAILABLE).",
         "Review observations; propose candidates.",
         "YES keeps a candidate; link it to a project/item.",
         "The world graph, craft tree and guide pick it up."))
    return (f"<div class=\"panel living\"><h2>Camera Guide — "
            f"from Insta360 file to living world</h2><ol>{steps}</ol>"
            f"<p class=\"muted\">Direct live transport: UNAVAILABLE — "
            f"verified transport adapter required. File ingest is REAL."
            f"</p></div>")


@app.post("/web/cameras/register")
async def web_camera_register(request: Request) -> RedirectResponse:
    import secrets
    fields = await _form_fields(request)
    kinds = [kind.strip() for kind in
             fields.get("kinds", "snapshot").split(",") if kind.strip()]
    try:
        device = new_device(f"cam-{secrets.token_hex(4)}",
                            fields.get("name", "Camera"), kinds,
                            fields.get("source", "manual"))
    except CameraRefusedError:
        return RedirectResponse("/cameras", status_code=303)
    save_device(device)
    return RedirectResponse("/cameras", status_code=303)


def _printer_is_simulated(printer_id: str) -> bool:
    """True when the bound adapter reports simulated. Guards
    the UI badge; never raises."""
    try:
        adapter = adapter_for_printer(printer_id)
    except (ValueError, AttributeError):
        return False
    if adapter is None:
        return False
    try:
        status = adapter.status(None)
    except (ValueError, AttributeError, TypeError):
        return getattr(adapter, "name", "") == "simulated-test"
    return bool(isinstance(status, dict)
                and status.get("simulated"))


@app.get("/fabrication", response_class=HTMLResponse)
def fabrication_page() -> str:
    from . import ui as _ui
    runs = "".join(
        f"<div class=\"sprout\"><b>{_ui.esc(record.fabrication_id)}</b> "
        f"{_ui.status_dot(record.status)}{_ui.chip(record.status)}<br>"
        f"<span class=\"muted\">mesh {_ui.esc(record.mesh_ref or '—')} "
        f"({_ui.esc(record.mesh_validation or '?')}) · gcode "
        f"{_ui.esc(record.gcode_ref or '—')} "
        f"({_ui.esc(record.gcode_safety or '?')}) · job "
        f"{_ui.esc(record.job_id or '—')}</span></div>"
        for record in list_fabrications(20))
    printers = "".join(
        f"<li><b>{_ui.esc(device.name)}</b> "
        f"({_ui.esc(device.printer_id)}) — "
        f"{_ui.esc(', '.join(device.capabilities))}"
        f"{' ' + _ui.chip('[SIMULATED]', 'state-SIMULATED') if _printer_is_simulated(device.printer_id) else ''}</li>"
        for device in list_stored_printers())
    main = f"""<h1>Fabrication</h1>
    <div class="panel"><p class="muted">Digital → physical through proposal → <b>exact YES (physical approval)</b> →
    execution → observation → verification. Telemetry never verifies the object; a software cancel is
    not a physical e-stop.</p></div>
    <h2>Pipeline runs</h2><div class="grove">{runs or _ui.empty("No runs yet.")}</div>
    <h2>Printers</h2><ul>{printers or "<li>No printers</li>"}</ul>"""
    return _ui.shell("Fabrication", "/fabrication", main, "",
                     _ui.command_bar())


@app.get("/workshop", response_class=HTMLResponse)
def workshop_page(fabrication_id: str = "") -> str:
    """Combined Workshop view (BIG #10, deel 7): object →
    mesh → sliced file → G-code → printer → execution →
    observation → verification. Read-only chain display; every
    transition still runs through its own gates."""
    from . import ui as _ui
    records = list_fabrications(20)
    chain_html = ""
    if fabrication_id:
        record = load_fabrication(fabrication_id)
        if record is None:
            chain_html = "<p>Unknown fabrication.</p>"
        else:
            data = record.model_dump(mode="json")
            stages = [
                ("Project/object", data.get("source_object_id")
                 or data.get("source_idea_id") or "○"),
                ("Mesh", f"{data.get('mesh_ref') or '○'} "
                 f"({data.get('mesh_validation') or '?'})"),
                ("Mesh-File", data.get("mesh_file_id") or "○"),
                ("G-code", f"{data.get('gcode_ref') or '○'} "
                 f"({data.get('gcode_safety') or '?'})"),
                ("G-code-File", data.get("gcode_file_id") or "○"),
                ("Printer/job", data.get("job_id") or "○"),
                ("Observatie", data.get("observation_id") or "○"),
                ("Status", data.get("status") or "?"),
            ]
            chain_html = "<div class=\"path\" aria-label=\"Fabrication chain\">" + \
                "<span class='arrow'>→</span>".join(
                    f"<span class=\"step{' done' if value not in ('○', '?', '') else ''}\">{_ui.esc(title)}: {_ui.esc(value)}</span>"
                    for title, value in stages) + "</div>"
            history = "".join(
                f"<li><small>{_ui.esc(str(entry.get('at', '')))}</small> "
                f"<b>{_ui.esc(str(entry.get('stage', '')))}</b> — "
                f"{_ui.esc(str(entry.get('detail', ''))[:160])}</li>"
                for entry in data.get("history", [])[-20:])
            chain_html += f"<h2>History</h2><ul>{history}</ul>"
    runs = "".join(
        f"<li><a href='/workshop?fabrication_id="
        f"{_ui.esc(record.fabrication_id)}'>"
        f"{_ui.esc(record.fabrication_id)}</a> — "
        f"{_ui.status_dot(record.status)}{_ui.esc(record.status)}</li>"
        for record in records)
    main = f"""<h1>Living Workshop</h1>
    <div class="panel"><p>Project → object → mesh → G-code → printer →
    execution → observation → verification. This view <b>shows</b> where a
    process stands; every transition runs through proposal → approval → execution →
    verification. No printer action from this page.</p></div>
    <div class="panel"><h2>Keten</h2>{chain_html or "<p>Pick a run.</p>"}</div>
    <div class="panel"><h2>Runs</h2><ul>{runs or "<li>No runs</li>"}</ul></div>
    <p><a href="/fabrication">All fabrication runs</a> · <a href="/workshop/3d">3D view</a></p>"""
    return _ui.shell("Workshop", "/workshop", main, "",
                     _ui.command_bar())


@app.get("/workshop/3d", response_class=HTMLResponse)
def workshop_3d_page(artifact: str = "") -> str:
    """Interactive 3D Workshop foundation (BIG #10, deel 6):
    wireframe preview of mesh artifacts with rotate/pan/zoom +
    inspect, plus validated transform proposals (rotate /
    translate / scale). Viewing is free; persisting a derived
    file returns a file_payload for the BIG #5 proposal flow —
    registration still needs approval. No CAD kernel, no
    scripting, no printer commands."""
    from . import ui as _ui
    main = f"""<h1>3D Workshop</h1>
    <p class="muted">From idea to thing you can hold: observation → candidate object → 3D model → edit → slice → fabrication → physical result → observation → improvement. Follow the <a href="/craft">Craft Tree</a>; every stage shows status, provenance, next action.</p>
    <div class="panel"><form id="loadform">
    <input type="text" id="ref" placeholder="artifact_ref, e.g. fab-test-cube.stl"
    value="{_ui.esc(artifact)}" style="width:50%" aria-label="Artifact reference">
    <button type="submit">Load</button>
    <span id="meta"></span></form></div>
    <canvas id="view" width="960" height="420" style="width:100%;height:420px;background:var(--soil-2);border:1px solid var(--line);border-radius:var(--r)" role="img" aria-label="Mesh wireframe preview"></canvas>
    <div class="panel"><h2>Transformatie-voorstel</h2>
    <form id="tform">
    <select id="op" aria-label="Operation"><option value="rotate">rotate</option>
    <option value="translate">translate</option><option value="scale">scale</option></select>
    <input type="text" id="params" placeholder='e.g. {{"axis":"z","degrees":90}}' style="width:50%" aria-label="Parameters">
    <label><input type="checkbox" id="persist"> persist locally (derived file)</label>
    <button type="submit">Preview</button></form>
    <p class="muted">Rotate/pan/scale show a preview. Persisting makes a local
    derived file + file_payload for the existing
    proposal/approval path — INVENTory registration never happens automatically.</p>
    <div id="info">Load a mesh artifact.</div></div>
    <script>
    let tris = [], rotX = 0.5, rotY = 0.6, scale = 1, ox = 0, oy = 0;
    const canvas = document.getElementById('view');
    const ctx = canvas.getContext('2d');
    function project(p) {{
        const [x, y, z] = p;
        const cx = Math.cos(rotY), sx = Math.sin(rotY);
        const cy = Math.cos(rotX), sy = Math.sin(rotX);
        const x1 = x * cx - z * sx, z1 = x * sx + z * cx;
        const y1 = y * cy - z1 * sy;
        return [480 + (x1 * scale) + ox, 210 - (y1 * scale) + oy];
    }}
    function draw() {{
        ctx.clearRect(0, 0, 960, 420);
        ctx.strokeStyle = '#a5c48a'; ctx.lineWidth = 1;
        ctx.beginPath();
        tris.forEach(t => {{
            const [a, b, c] = t.map(project);
            ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]);
            ctx.lineTo(c[0], c[1]); ctx.closePath();
        }});
        ctx.stroke();
    }}
    async function loadPreview(ref) {{
        const r = await fetch('/api/v1/fab/mesh/preview?artifact_ref=' + encodeURIComponent(ref));
        if (!r.ok) {{ document.getElementById('info').textContent = 'Preview failed: ' + r.status; return; }}
        const j = await r.json();
        tris = j.tris || [];
        document.getElementById('meta').textContent =
            j.format + ' · ' + j.total_tris + ' tris' + (j.truncated ? ' (capped)' : '');
        document.getElementById('info').textContent =
            'ref=' + j.artifact_ref + '\\nformat=' + j.format + '\\ntris=' + j.total_tris;
        draw();
    }}
    document.getElementById('loadform').onsubmit = e => {{
        e.preventDefault();
        loadPreview(document.getElementById('ref').value);
    }};
    document.getElementById('tform').onsubmit = async e => {{
        e.preventDefault();
        const ref = document.getElementById('ref').value;
        let params = {{}};
        try {{ params = JSON.parse(document.getElementById('params').value || '{{}}'); }}
        catch (err) {{ document.getElementById('info').textContent = 'Params must be JSON.'; return; }}
        const r = await fetch('/api/v1/fab/transform', {{
            method: 'POST', headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{artifact_ref: ref,
                op: document.getElementById('op').value, params,
                persist: document.getElementById('persist').checked}})
        }});
        const j = await r.json();
        if (!r.ok) {{ document.getElementById('info').textContent = 'Refused: ' + JSON.stringify(j); return; }}
        tris = j.preview_tris || tris;
        document.getElementById('info').textContent =
            'op=' + j.op + ' total_tris=' + j.total_tris +
            (j.executed ? '\\nderived=' + j.derived_ref + '\\nsha256=' + j.sha256 +
             '\\nfile_payload ready for proposal flow (not registered)' : '\\npreview only');
        draw();
    }};
    let drag = null;
    canvas.addEventListener('pointerdown', e => {{ drag = [e.clientX, e.clientY]; canvas.setPointerCapture(e.pointerId); }});
    canvas.addEventListener('pointerup', () => drag = null);
    canvas.addEventListener('pointermove', e => {{
        if (!drag) return;
        rotY += (e.clientX - drag[0]) * 0.01; rotX += (e.clientY - drag[1]) * 0.01;
        drag = [e.clientX, e.clientY]; draw();
    }});
    canvas.addEventListener('wheel', e => {{
        e.preventDefault(); scale *= e.deltaY < 0 ? 1.1 : 0.9; draw();
    }}, {{passive: false}});
    const initial = document.getElementById('ref').value;
    if (initial) loadPreview(initial);
    draw();
    </script>"""
    return _ui.shell("3D Workshop", "/workshop/3d", main, "",
                     _ui.command_bar())


def _mobile_waiting_html() -> str:
    """Waiting missions with inline approve buttons (exact-YES
    semantics via the existing web op route). Read-only when quiet."""
    from . import ui as _ui
    try:
        waiting = [mission for mission in list_missions(limit=20)
                   if mission.status in ("pending_approval", "paused")]
    except Exception:
        return ""
    if not waiting:
        return "<p class=\"muted\">Nothing waiting — quiet. 🌱</p>"
    rows = "".join(
        f"<li><b>{_ui.esc(mission.goal[:90])}</b> "
        f"<span class=\"muted\">[{_ui.esc(mission.status)}]</span><br>"
        f"<form method=\"post\" action=\"/web/missions/"
        f"{_ui.esc(mission.mission_id)}/approve\" style=\"display:inline\">"
        f"<button type=\"submit\">YES, doorgaan</button></form> "
        f"<a href=\"/missions/{_ui.esc(mission.mission_id)}\">details</a>"
        f"</li>"
        for mission in waiting[:5])
    return f"<ul>{rows}</ul>"


@app.get("/api/v1/mobile/dashboard")
def api_mobile_dashboard(node: str = "") -> dict:
    """One bounded snapshot behind /mobile. Read-only."""
    from .mobile import dashboard
    return dashboard(node[:80])


@app.get("/mobile", response_class=HTMLResponse)
def mobile_page(node: str = "") -> str:
    """Mobile command surface: NOW, WAITING FOR YOU, ACTIVE,
    INPUT, GUIDE ME, CAMERA, CONTINUE ELSEWHERE, CRAFT,
    SYMBIOSIS, NODES, RECENT. Same backend and gates as
    desktop — a surface, not a second app."""
    from . import ui as _ui
    from .mobile import dashboard
    try:
        dash = dashboard(node[:80])
    except Exception:
        dash = {"waiting_count": 0, "cards": [], "guide": [],
                "camera": {}, "craft": [], "symbiosis": [],
                "nodes": {"nodes": [], "path": []},
                "progress": {"quests": []}, "notifications": [],
                "packet": {}, "living": {}}
    living = dash.get("living", {})
    main = f"""<h1>Mycelium</h1>
    {_mobile_now_html(dash)}
    {_mobile_presence_html(dash)}
    {_mobile_waiting_html_v2(dash)}
    {_mobile_active_html(dash)}
    <div class="panel" id="input"><h2>Wat wil je doen?</h2>
    <form method="post" action="/web/chat">
    <textarea name="message" placeholder="Onderzoek dit / maak hier een project van / wat staat er open?…" aria-label="Message"></textarea><br><br>
    <button type="submit">Send</button></form>
    <p class="muted">PHONE → coordinator → routing → node → result → mobile. INPUT → PROCESSING → NODE → RESULT. Nooit doen alsof een node iets uitvoerde als het niet werkelijk gebeurd is.</p>
    <p><b>Quick actions</b> (bestaande routes): <a href="/research">Research</a> · <a href="/cameras">Observe</a> · <a href="/chat">Ask Mycelium</a> · <a href="/world">INVENTory</a> · <a href="/workshop/3d">3D</a> · <a href="/projects">Project</a> · <a href="/nodes">Nodes</a> · <a href="/missions">Tasks</a> · <a href="/conversations">Import conversation</a></p>
    <div class="quickgrid" aria-label="Quick input actions">
    <a href="/research">🔍<small>Onderzoek</small></a>
    <a href="/cameras">📷<small>Kijk hiernaar</small></a>
    <a href="/knowledge">🧠<small>Onthoud dit</small></a>
    <a href="/conversations">💡<small>Nieuw idee</small></a>
    <a href="/writes">📦<small>Voeg toe</small></a>
    <a href="/fabrication">🛠<small>Maak</small></a>
    <a href="/guide">🌱<small>Ga verder</small></a>
    <a href="/missions">📋<small>Wat staat open?</small></a>
    <a href="/conversations">📥<small>Import chat</small></a>
    <a href="/conversations">🔍<small>What did we miss?</small></a>
    <a href="#intel">🧵<small>Open threads</small></a>
    <a href="#intel">⚖<small>Decisions</small></a>
    </div>
    <p class="muted">PROCESSING: Mycelium verwerkt dit (INPUT → PROCESSING → NODE → RESULT). RESULT verschijnt hieronder bij events en in <a href="/activity">Activity</a>. NEEDS YOU: alles met een YES-button wacht op jou — <a href="/guide">Guide</a> wijst de weg.</p></div>
    {_mobile_guide_panel_v2(dash)}
    <div class="panel"><h2>Hoe gebruik ik Mycelium?</h2>
    <p class="muted">1. Typ wat je wilt. 2. Mycelium bepaalt wat nodig is. 3. Een node kan het uitvoeren. 4. Je ziet wat er gebeurt. 5. Toestemming blijft expliciet. 6. Resultaat komt terug op je telefoon. Jij blijft degene die acties goedkeurt.</p></div>
    {_mobile_camera_v2_html(dash)}
    {_mobile_packet_html(dash)}
    {_mobile_intel_html(dash)}
    {_mobile_craft_html(dash)}
    {_mobile_symbiosis_html(dash)}
    {_mobile_nodes_html(dash)}
    {_mobile_connected_html(dash)}
    {_mobile_world_html(dash)}
    {_mobile_recent_html(dash, node)}
    <div class="panel"><h2>Remember this</h2>
    <form method="post" action="/web/candidates">
    <input type="text" name="title" placeholder="Onthoud dit…" style="width:70%" aria-label="Remember" autocomplete="off">
    <input type="hidden" name="candidate_type" value="note">
    <button type="submit">Remember</button></form>
    <p class="muted">Becomes a candidate (never a fact) in <a href="/knowledge">Knowledge</a>.</p></div>
    <div class="panel"><h2>Look into this</h2>
    <form method="post" action="/web/research/queue">
    <input type="text" name="question" placeholder="Zoek dit uit…" style="width:70%" aria-label="Research question" autocomplete="off">
    <button type="submit">Queue research</button></form>
    <p><a href="/api/v1/discoveries">What did we miss?</a></p></div>
    {_mobile_workshop_html()}
    <div class="panel"><h2>Status</h2>
    <p class="muted">IN_APP is live (polling); WEB PUSH is UNAVAILABLE — <a href="/api/v1/notifications/capability">capability (JSON)</a>. Nodes online: {_ui.esc(str(living.get('nodes_online', '?')))}.</p></div>"""
    return _ui.shell("Mobile", "/mobile", _ui.living_bg() + main, "",
                     _ui.command_bar())


def _mobile_guide_panel() -> str:
    """Guide strip for the phone: next real action, one tap away."""
    from . import ui as _ui
    try:
        from .guide import guide_items
        items = guide_items(limit=2)
    except Exception:
        items = []
    if not items:
        return ""
    cards = "".join(_ui.guide_card(item) for item in items)
    return (f"<div class=\"panel\"><h2>Needs you</h2>"
            f"<div class=\"grove\">{cards}</div>"
            f"<p><a href=\"/guide\">All guide items →</a></p></div>")


def _mobile_camera_html() -> str:
    """Phone camera flow: add → processing → review → YES/REVIEW."""
    from . import ui as _ui
    try:
        from .vision_ingest import list_inbox_files
        inbox = list_inbox_files(limit=5)
    except Exception:
        inbox = []
    try:
        from .knowledge import list_candidates
        camera_candidates = sum(
            1 for entry in list_candidates(limit=100)
            if (entry.provenance.creator_id or "") in
            ("camera-vlm", "camera-ecosystem"))
    except Exception:
        camera_candidates = 0
    if inbox:
        state = (f"PROCESSING: {len(inbox)} photo(s) wait in the "
                 f"inbox. Open <a href=\"/cameras\">Camera Lab</a>, "
                 f"run a session, and Mycelium describes what it sees.")
    elif camera_candidates:
        state = (f"RESULT: {camera_candidates} camera candidate(s) "
                 f"wait. <a href=\"/knowledge\">Bekijk</a> — "
                 f"YES keeps one, REVIEW inspects, ignore leaves it.")
    else:
        state = ("📷 CAMERA: voeg een foto toe via "
                 "<a href=\"/cameras\">Camera Lab</a> — copy the file "
                 "into the inbox first. No native upload; the inbox "
                 "is the honest path.")
    return f"<p>{state}</p>"


def _mobile_workshop_html() -> str:
    """Workbench quick actions: input only, coordinator decides,
    YES gates never bypassed."""
    from . import ui as _ui
    try:
        from .workshop3d import list_fabjobs, list_models
        models = len(list_models(limit=50))
        active = sum(1 for job in list_fabjobs(limit=50)
                     if job.get("stage") not in
                     ("verified", "cancelled", "blocked"))
    except Exception:
        models, active = 0, 0
    return (
        f"<div class=\"panel\"><h2>Workbench</h2>"
        f"<p class=\"muted\">{models} model(s), {active} active "
        f"fab job(s). The coordinator decides what can happen.</p>"
        f"<p><a href=\"/3d\">Scan this</a> · "
        f"<a href=\"/3d\">Add model</a> · "
        f"<a href=\"/3d\">Find material</a> · "
        f"<a href=\"/3d\">Connect to project</a> · "
        f"<a href=\"/craft\">What can I build?</a> · "
        f"<a href=\"/fabrication\">Continue fabrication</a> · "
        f"<a href=\"/cameras\">Verify this print</a></p></div>")


def _mobile_now_html(dash: dict) -> str:
    """NOW: one honest line about the living state."""
    from . import ui as _ui
    living = dash.get("living", {})
    pending = living.get("pending_approvals", {})
    total_waiting = 0
    try:
        total_waiting = sum(int(pending.get(key, 0)) for key in
                            ("desktop_actions", "write_proposals",
                             "missions"))
    except Exception:
        total_waiting = 0
    line = (f"{dash.get('waiting_count', 0)} approval card(s) · "
            f"nodes online: "
            f"{_ui.esc(str(living.get('nodes_online', '?')))}")
    if total_waiting:
        line += f" · {total_waiting} raw approval(s) in stores"
    return (f"<div class=\"panel living\" id=\"now\"><h2>Now</h2>"
            f"<p>{_ui.esc('Mycelium is ' + ('waiting for you.' if dash.get('waiting_count') else 'quiet — nothing waits.'))}</p>"
            f"<p class=\"muted\">{line} · "
            f"<a href=\"/api/v1/mobile/dashboard\">dashboard "
            f"(JSON)</a></p></div>")


def _triage_card_html(card: dict) -> str:
    """One approval card: WHAT/WHY/SOURCE/SCOPE + what YES
    does and does NOT do. YES/NO post to existing gates;
    DEFER is an honest non-action (open later)."""
    from . import ui as _ui
    kind = str(card.get("kind", ""))
    ident = str(card.get("id", ""))
    yes_action = str(card.get("yes_action", ""))
    no_action = str(card.get("no_action", ""))
    open_href = str(card.get("open_href", "/"))
    yes_label = "YES, doorgaan" if kind == "mission" else "YES"
    yes_field = ("<input type=\"hidden\" name=\"response\" "
                 "value=\"YES\">" if kind != "mission" else "")
    no_field = ("<input type=\"hidden\" name=\"response\" "
                "value=\"NO\">" if kind != "mission" else "")
    no_label = "NO" if kind != "mission" else "Cancel plan"
    no_form = (f"<form method=\"post\" action=\"{_ui.esc(no_action)}\" "
               f"style=\"display:inline\">{no_field}"
               f"<button type=\"submit\">{_ui.esc(no_label)}</button>"
               f"</form>" if no_action else "")
    return (
        f"<div class=\"sprout\"><b>{_ui.esc(card.get('what', ''))}</b> "
        f"{_ui.chip(kind)}{_ui.chip(str(card.get('state', '')))}<br>"
        f"<small><b>WHY:</b> {_ui.esc(card.get('why', ''))}</small><br>"
        f"<small><b>SOURCE:</b> {_ui.esc(card.get('source', ''))} · "
        f"<b>SCOPE:</b> {_ui.esc(card.get('scope', ''))}</small><br>"
        f"<small><b>YES:</b> {_ui.esc(card.get('will_happen', ''))}"
        f"</small><br>"
        f"<small><b>NOT:</b> {_ui.esc(card.get('will_not_happen', ''))}"
        f"</small><br>"
        f"<form method=\"post\" action=\"{_ui.esc(yes_action)}\" "
        f"style=\"display:inline\">{yes_field}"
        f"<button type=\"submit\">{_ui.esc(yes_label)}</button></form> "
        f"{no_form} "
        f"<a href=\"{_ui.esc(open_href)}\">OPEN</a> · "
        f"<a href=\"{_ui.esc(open_href)}\" title=\"Nothing changes; "
        f"decide later\">DEFER</a></div>")


def _mobile_presence_html(dash: dict) -> str:
    """Presence bands: GOOD MORNING/NOW + NEEDS/WAITING/
    AVAILABLE/DISCOVERED/OFFLINE cards with WHAT/WHY/SOURCE/
    NEXT + YES/NO/OPEN/DEFER over existing gates."""
    from . import ui as _ui
    from .presence import BAND_META
    presence = dash.get("presence", {}) if isinstance(
        dash.get("presence"), dict) else {}
    bands = presence.get("bands", {}) if isinstance(
        presence.get("bands"), dict) else {}
    greeting = str(dash.get("greeting", "NOW"))
    order = ("needs", "waiting", "available", "discovered",
             "offline")
    sections = []
    for band in order:
        items = bands.get(band, []) or []
        meta = BAND_META.get(band, {"glyph": "•",
                                    "title": band})
        body = "".join(_ui.presence_card(item)
                       for item in items[:4])
        sections.append(
            f"<div class=\"panel\" id=\"presence-{band}\">"
            f"<h2>{meta['glyph']} {meta['title']} "
            f"({len(items)})</h2>"
            f"<div class=\"grove\">"
            f"{body or _ui.empty('Nothing here.')}</div></div>")
    return (
        f"<div class=\"panel living\" id=\"presence\">"
        f"<h2>{_ui.esc(greeting)}, Jelles 🌱</h2>"
        f"<p class=\"muted\">What deserves attention, why, "
        f"and what you can do — derived live. YES/NO run the "
        f"existing gates; DEFER changes nothing. "
        f"<a href=\"/presence\">Full attention view →</a></p>"
        f"</div>" + "".join(sections))


def _mobile_waiting_html_v2(dash: dict) -> str:
    """WAITING FOR YOU: triage cards over the same gates."""
    from . import ui as _ui
    cards = dash.get("cards", [])
    body = "".join(_triage_card_html(card) for card in cards[:6]) \
        or _ui.empty("Nothing waiting — quiet. 🌱")
    return (
        f"<div class=\"panel\" id=\"waiting\"><h2>Waiting for you</h2>"
        f"<p class=\"muted\">Every YES runs the existing gate; "
        f"DEFER changes nothing. "
        f"<a href=\"/agents\">Agents</a> · "
        f"<a href=\"/missions\">Review missions</a> · "
        f"<a href=\"/writes\">Review writes</a></p>"
        f"<div class=\"grove\">{body}</div></div>")


def _mobile_active_html(dash: dict) -> str:
    """ACTIVE: quest progress from real backend states."""
    from . import ui as _ui
    quests = dash.get("progress", {}).get("quests", [])
    rows = []
    for quest in quests[:6]:
        done = quest.get("done", -1)
        total = quest.get("total", -1)
        if isinstance(done, int) and isinstance(total, int) \
                and done >= 0 and total > 0:
            detail = f"{done}/{total}"
        else:
            detail = str(quest.get("status", ""))
        rows.append(
            f"<li><a href=\"{_ui.esc(quest.get('href', '/missions'))}\">"
            f"{_ui.esc(quest.get('title', ''))}</a> "
            f"<span class=\"muted\">[{_ui.esc(detail)}]</span></li>")
    return (
        f"<div class=\"panel\" id=\"active\"><h2>Active</h2>"
        f"<ul>{''.join(rows) or '<li>No active quests.</li>'}</ul>"
        f"<p><a href=\"/missions\">View plans</a> · "
        f"<a href=\"/morning\">Morning report</a></p></div>")


def _mobile_guide_panel_v2(dash: dict) -> str:
    """GUIDE ME: real next actions, WHAT/WHY/NEXT."""
    from . import ui as _ui
    cards = "".join(_ui.guide_card(item)
                    for item in dash.get("guide", [])[:4]) or \
        _ui.empty("Nothing to point at — the world is quiet. 🌱")
    return (
        f"<div class=\"panel\" id=\"guide-me\"><h2>Guide me</h2>"
        f"<div class=\"grove\">{cards}</div>"
        f"<p><a href=\"/guide\">All guide items →</a></p></div>")


def _mobile_camera_v2_html(dash: dict) -> str:
    """CAMERA: inbox → sessions → observations → candidates."""
    from . import ui as _ui
    panel = dash.get("camera", {})
    return (
        f"<div class=\"panel\" id=\"camera\"><h2>Camera</h2>"
        f"<p>{panel.get('inbox', 0)} file(s) in inbox · "
        f"{panel.get('sessions', 0)} session(s) · "
        f"{panel.get('observations', 0)} observation(s) · "
        f"{panel.get('candidates_waiting', 0)} candidate(s) "
        f"waiting.</p>"
        f"<p class=\"muted\">FILE → SESSION → OBSERVATION → "
        f"DESCRIBE → REVIEW → CANDIDATE → LINK → YES. "
        f"Insta360 live transport: UNAVAILABLE; the inbox in "
        f"<a href=\"/cameras\">Camera Lab</a> is the honest path."
        f"</p>"
        f"<p><a href=\"/cameras\">Open Camera Lab</a></p></div>")


def _mobile_packet_html(dash: dict) -> str:
    """CONTINUE ELSEWHERE: the existing packet-v2, one tap away."""
    from . import ui as _ui
    preview = dash.get("packet", {})
    return (
        f"<div class=\"panel\" id=\"packet\"><h2>Continue elsewhere</h2>"
        f"<p class=\"muted\">goal: "
        f"{_ui.esc(str(preview.get('goal', ''))[:100] or '—')} · "
        f"{preview.get('missions', 0)} mission(s) · "
        f"{preview.get('entities', 0)} entit(ies) · "
        f"{preview.get('memories', 0)} memor(ies) · "
        f"{preview.get('open_questions', 0)} open question(s)</p>"
        f"<p><a class=\"btn\" href=\"/api/v1/context/packet.md\">"
        f"Copy context</a> "
        f"<a href=\"/api/v1/context/packet\">packet (JSON)</a> · "
        f"<a href=\"/api/v1/context/continue\">continuation "
        f"(JSON)</a> · "
        f"<a href=\"/api/v1/workshop/packet\">3D packet</a></p>"
        f"<p class=\"muted\">Take it to ChatGPT, Claude, Gemini, "
        f"Codex, OpenCode or Ollama — models work, Mycelium keeps "
        f"state. No secrets inside.</p></div>")


def _mobile_intel_html(dash: dict) -> str:
    """Conversation intelligence: open threads, decisions
    awaiting CONFIRM, research proposals. Links only."""
    from . import ui as _ui
    panel = dash.get("intel", {}) if isinstance(
        dash.get("intel"), dict) else {}
    threads = "".join(
        f"<li><a href=\"{_ui.esc(item.get('href', '/conversations'))}\">"
        f"{_ui.esc(item.get('text', ''))}</a></li>"
        for item in panel.get("threads", [])[:4])
    decisions = "".join(
        f"<li><a href=\"{_ui.esc(item.get('href', '/conversations'))}\">"
        f"{_ui.esc(item.get('text', ''))}</a> "
        f"<span class=\"muted\">[awaiting CONFIRM]</span></li>"
        for item in panel.get("decisions", [])[:3])
    research = "".join(
        f"<li><a href=\"{_ui.esc(item.get('href', '/conversations'))}\">"
        f"{_ui.esc(item.get('text', ''))}</a></li>"
        for item in panel.get("research", [])[:3])
    return (
        f"<div class=\"panel\" id=\"intel\"><h2>Threads</h2>"
        f"<h3>Open threads</h3>"
        f"<ul>{threads or '<li>No open contradictions.</li>'}</ul>"
        f"<h3>Decisions</h3>"
        f"<ul>{decisions or '<li>No decisions awaiting CONFIRM.</li>'}</ul>"
        f"<h3>Research this</h3>"
        f"<ul>{research or '<li>No research proposals.</li>'}</ul>"
        f"<p><a href=\"/conversations\">Import chat</a> · "
        f"<a href=\"/conversations\">What did we miss?</a> · "
        f"<a href=\"/api/v1/context/packet\">Continue elsewhere</a></p>"
        f"</div>")


def _mobile_craft_html(dash: dict) -> str:
    """CRAFT: checklists with ✓/●/○ from real presence."""
    from . import ui as _ui
    blocks = []
    for entry in dash.get("craft", [])[:4]:
        rows = "".join(
            f"<li>{'✓' if present else '○'} {_ui.esc(label)}</li>"
            for label, present in entry.get("checklist", []))
        blocks.append(
            f"<div class=\"sprout\"><b>{_ui.esc(entry.get('entity_id', ''))}</b> "
            f"<span class=\"muted\">{entry.get('done', 0)}/"
            f"{entry.get('total', 0)}</span><ul>{rows}</ul>"
            f"<a href=\"{_ui.esc(entry.get('href', '/craft'))}\">"
            f"Open craft tree →</a></div>")
    return (
        f"<div class=\"panel\" id=\"craft\"><h2>Craft</h2>"
        f"<div class=\"grove\">{''.join(blocks) or _ui.empty('No craft chains linked yet.')}</div></div>")


def _mobile_symbiosis_html(dash: dict) -> str:
    """SYMBIOSIS: proposed connections with WHY/SOURCE/STATUS."""
    from . import ui as _ui
    rows = "".join(
        f"<div class=\"sprout\"><b>{_ui.esc(item.get('title', ''))}</b> "
        f"{_ui.symbiosis_chip('PROPOSED')}<br>"
        f"<small><b>WHY:</b> {_ui.esc(item.get('why', ''))}</small><br>"
        f"<small class=\"muted\">{_ui.esc(', '.join(item.get('entities', [])))}</small><br>"
        f"<a href=\"{_ui.esc(item.get('href', '/knowledge'))}\">YES via Knowledge →</a></div>"
        for item in dash.get("symbiosis", [])[:5])
    return (
        f"<div class=\"panel\" id=\"symbiosis\"><h2>Symbiosis</h2>"
        f"<p class=\"muted\">POSSIBLE links only — YES runs the "
        f"guarded relationship flow.</p>"
        f"<div class=\"grove\">{rows or _ui.empty('No open proposals.')}</div></div>")


def _mobile_nodes_html(dash: dict) -> str:
    """NODES: health + telemetry + hardware + WHAT IT CAN DO."""
    from . import ui as _ui

    def _node_detail(node: dict) -> str:
        telemetry = node.get("telemetry", {})
        hardware = node.get("hardware", {})
        compute = node.get("compute", {})
        energy = node.get("energy", {})
        bits: list[str] = []
        if isinstance(telemetry, dict):
            cpu = telemetry.get("cpu_percent")
            mem = telemetry.get("memory_percent")
            if cpu is not None or mem is not None:
                bits.append(
                    f"cpu {cpu}% · mem {mem}%"
                    if cpu is not None and mem is not None
                    else f"cpu {cpu}%"
                    if cpu is not None else f"mem {mem}%")
            uptime = telemetry.get("uptime_seconds")
            if uptime is not None:
                bits.append(f"up {_ui.esc(str(uptime))}s")
        if isinstance(hardware, dict):
            kinds = hardware.get("kinds", [])
            if kinds:
                bits.append(
                    f"hw {hardware.get('connected', 0)}/"
                    f"{hardware.get('count', 0)}: "
                    f"{_ui.esc(', '.join(str(kind) for kind in kinds[:6]))}")
        if isinstance(compute, dict):
            caps = compute.get("capabilities", [])
            if caps:
                bits.append(
                    f"compute {compute.get('available', 0)}/"
                    f"{compute.get('count', 0)}: "
                    f"{_ui.esc(', '.join(str(cap) for cap in caps[:6]))}")
        if isinstance(energy, dict) and energy.get("source"):
            level = energy.get("level_percent")
            bits.append(f"power {_ui.esc(str(energy.get('source')))}"
                        + (f" {level}%" if level is not None
                           else ""))
        current = node.get("current_task")
        if isinstance(current, dict) and current.get("task_id"):
            bits.append(f"busy: task #{_ui.esc(str(current.get('task_id')))} "
                        f"({_ui.esc(str(current.get('kind', '')))})")
        return "<br>".join(
            f"<small class=\"muted\">{bit}</small>" for bit in bits)

    panel = dash.get("nodes", {})
    rows = "".join(
        f"<li>{_ui.status_dot(node.get('status', ''))}"
        f"<b>{_ui.esc(node.get('node_id', ''))}</b> — "
        f"{_ui.esc(node.get('status', ''))} · "
        f"health {_ui.esc(node.get('health', 'UNKNOWN'))}<br>"
        f"{_node_detail(node)}<br>"
        f"<small>WHAT IT CAN DO: "
        f"{_ui.esc(', '.join(node.get('capabilities', [])))}</small></li>"
        for node in panel.get("nodes", [])[:12]) or \
        "<li>No nodes</li>"
    path = "".join(
        f"<li><small>{_ui.esc(step)}</small></li>"
        for step in panel.get("path", []))
    return (
        f"<div class=\"panel\" id=\"nodes\"><h2>Nodes</h2>"
        f"<ul>{rows}</ul>"
        f"<h3>Mesh path</h3><ul>{path}</ul>"
        f"<p class=\"muted\">PHONE → COORDINATOR → NODE(S). "
        f"Coordinator stays authoritative; no shell, no wildcard. "
        f"<a href=\"/nodes\">Open nodes</a></p></div>")


def _mobile_world_html(dash: dict) -> str:
    """World HUD for the phone (BIG #44): campaign, quest,
    attention, nodes, work, discoveries — same HUD as /world,
    small words, same hrefs. NOW/WAITING/AVAILABLE/DISCOVERED/
    OFFLINE vocabulary stays shared with desktop."""
    from . import ui as _ui
    panel = dash.get("world", {}) if isinstance(
        dash.get("world"), dict) else {}
    hud = panel.get("hud", {}) if isinstance(
        panel.get("hud"), dict) else {}
    rows = []
    campaign = hud.get("campaign", {}) or {}
    if campaign.get("title"):
        rows.append(
            f"<li>🗺 <a href=\""
            f"{_ui.esc(campaign.get('href', '/campaigns'))}\">"
            f"{_ui.esc(campaign['title'])}</a> "
            f"{_ui.esc(campaign.get('progress', ''))}</li>")
    quest = hud.get("quest", {}) or {}
    if quest.get("title"):
        rows.append(
            f"<li>🧭 <a href=\""
            f"{_ui.esc(quest.get('href', '/quests'))}\">"
            f"{_ui.esc(quest['title'])}</a> "
            f"{_ui.esc(quest.get('progress', ''))}</li>")
    attention = hud.get("attention", {}) or {}
    if any(attention.get(key, 0) for key in
           ("needs", "waiting", "discovered", "offline")):
        rows.append(
            f"<li>📌 <a href=\"/presence\">"
            f"{attention.get('needs', 0)} needs · "
            f"{attention.get('waiting', 0)} waiting · "
            f"{attention.get('discovered', 0)} discovered · "
            f"{attention.get('offline', 0)} quiet</a></li>")
    nodes = hud.get("nodes", {}) or {}
    if nodes.get("total"):
        rows.append(
            f"<li>⬢ <a href=\"/nodes\">{nodes.get('awake', 0)}/"
            f"{nodes.get('total', 0)} awake</a></li>")
    if not rows:
        return ""
    return (
        f"<div class=\"panel\" id=\"world\"><h2>World</h2>"
        f"<ul>{''.join(rows)}</ul>"
        f"<p><a href=\"/world\">Open living world →</a> · "
        f"<a href=\"/game\">Game view →</a></p></div>")


def _mobile_connected_html(dash: dict) -> str:
    """Connected ecosystem for the phone (BIG #45): CONNECTED
    / WAITING / DISCOVERED counts + seedlings. No graph on
    the phone — counts and links only."""
    from . import ui as _ui
    panel = dash.get("connected", {}) if isinstance(
        dash.get("connected"), dict) else {}
    if not panel:
        return ""
    seedlings = "".join(
        f"<li>🌱 <a href=\""
        f"{_ui.esc(item.get('href', '/symbiosis'))}\">"
        f"{_ui.esc(item.get('title', '')[:70])}</a></li>"
        for item in panel.get("discovered", [])[:4])
    return (
        f"<div class=\"panel\" id=\"connected\">"
        f"<h2>Connected ecosystem</h2>"
        f"<p>{panel.get('connected', 0)} connected · "
        f"{panel.get('waiting', 0)} waiting · "
        f"<a href=\"/world\">world →</a></p>"
        + (f"<ul>{seedlings}</ul>" if seedlings else "") +
        f"</div>")


def _mobile_recent_html(dash: dict, node: str) -> str:
    """RECENT: notifications with deeplinks + latest events."""
    from . import ui as _ui
    notes = "".join(
        f"<li><a href=\"{_ui.esc(item.get('href', '/activity'))}\">"
        f"{_ui.esc(item.get('title', ''))}</a> "
        f"<span class=\"muted\">[{_ui.esc(item.get('type', ''))}"
        f"{_ui.esc(' · ' + item.get('at', '')) if item.get('at') else ''}]</span></li>"
        for item in dash.get("notifications", [])[:8])
    try:
        events = bus_events(limit=8)
        event_rows = "".join(
            f"<li><small>{_ui.esc(event.created_at[:16])}</small> "
            f"<b>{_ui.esc(event.event_type)}</b> — "
            f"{_ui.esc(event.summary[:100])}</li>"
            for event in events)
    except Exception:
        event_rows = ""
    title = f"Notifications{_ui.esc(' for ' + node) if node else ''}"
    if not node:
        notes = notes or \
            "<li>link ?node=&lt;node_id&gt; for per-node notifications</li>"
    return (
        f"<div class=\"panel\" id=\"recent\"><h2>{title}</h2>"
        f"<p class=\"muted\">IN_APP is live (polling); WEB PUSH is "
        f"UNAVAILABLE — <a href=\"/api/v1/notifications/capability\">"
        f"capability (JSON)</a>. Tapping opens the real object.</p>"
        f"<ul>{notes or '<li>Quiet.</li>'}</ul>"
        f"<h3>Recent events</h3>"
        f"<ul>{event_rows or '<li>No events</li>'}</ul></div>")


@app.post("/web/desktop/{action_id}/decision")
async def web_desktop_decision(action_id: str,
                               request: Request) -> RedirectResponse:
    fields = await _form_fields(request)
    try:
        desktop_decide(action_id, DesktopDecisionBody(
            response=fields.get("response", "")))
    except HTTPException:
        pass
    return RedirectResponse("/agents", status_code=303)


@app.post("/web/desktop/{action_id}/cancel")
async def web_desktop_cancel(action_id: str) -> RedirectResponse:
    try:
        desktop_cancel(action_id, DesktopDecisionBody(response="NO"))
    except HTTPException:
        pass
    return RedirectResponse("/agents", status_code=303)


@app.post("/web/desktop/{action_id}/dispatch")
async def web_desktop_dispatch(action_id: str) -> RedirectResponse:
    """Smallest UI bridge onto POST /api/v1/desktop/actions/{id}/dispatch:
    approved -> dispatched status transition only; no input happens here.
    The standalone agent claims via its poll loop. Gate refusals (404/409/
    422 for non-approved actions) redirect back unchanged."""
    from fastapi import HTTPException as _HTTPException
    try:
        desktop_dispatch(action_id, None)
    except _HTTPException:
        pass
    return RedirectResponse("/agents", status_code=303)


# =============================================================================
# BIG #30 — THE LIVING ECOSYSTEM. One interconnected workshop:
# conversations in, context packets out, entity-first links, honest
# REAL/TEST/SIMULATED/UNAVAILABLE labels everywhere. No fake transports.
# =============================================================================


@app.get("/api/v1/conversation-imports")
def api_conversation_imports(limit: int = 50) -> dict:
    from .conversation_bridge import list_imports
    return {"imports": list_imports(limit=limit)}


@app.get("/api/v1/conversation-imports/{conversation_id}")
def api_conversation_import_get(conversation_id: str) -> dict:
    from .conversation_bridge import (get_import, import_messages,
                                      load_analysis)
    meta = get_import(conversation_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Unknown import")
    return {"import": meta,
            "messages": import_messages(conversation_id)[:50],
            "analysis": load_analysis(conversation_id)}


@app.post("/api/v1/conversations/{conversation_id}/analyze")
def api_conversation_analyze(conversation_id: str) -> dict:
    from .conversation_bridge import (BridgeRefusedError, analyze_import,
                                      missed_items)
    try:
        record = analyze_import(conversation_id)
        return {"analysis": record,
                "missed_items": missed_items(conversation_id, record)}
    except BridgeRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/conversations/{conversation_id}/missed")
def api_conversation_missed(conversation_id: str) -> dict:
    from .conversation_bridge import BridgeRefusedError, missed_items
    try:
        return {"missed_items": missed_items(conversation_id)}
    except BridgeRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/conversation-intel/{conversation_id}")
def api_conversation_intel(conversation_id: str) -> dict:
    from .conversation_intel import (IntelRefusedError,
                                     analyze_conversation)
    try:
        return analyze_conversation(conversation_id)
    except IntelRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/conversation-intel/{conversation_id}/timeline")
def api_conversation_timeline(conversation_id: str,
                              limit: int = 40) -> dict:
    from .conversation_intel import IntelRefusedError, timeline
    try:
        return {"timeline": timeline(conversation_id, limit=limit)}
    except IntelRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/conversation-intel/{conversation_id}/graph")
def api_conversation_graph(conversation_id: str,
                           limit: int = 40) -> dict:
    from .conversation_intel import IntelRefusedError, intel_graph
    try:
        return intel_graph(conversation_id, limit=limit)
    except IntelRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/conversation-intel-cross")
def api_conversation_intel_cross(limit: int = 10) -> dict:
    from .conversation_intel import cross_conversation
    return cross_conversation(limit=limit)


@app.post("/api/v1/conversation-intel/{conversation_id}/materialize",
          status_code=201)
def api_conversation_materialize(conversation_id: str,
                                 body: dict) -> dict:
    from .conversation_intel import (IntelRefusedError,
                                     materialize)
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    try:
        return materialize(
            conversation_id, str(body.get("fingerprint", "")),
            str(body.get("action", "")))
    except IntelRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/web/conversations/{conversation_id}/analyze-intel")
async def web_conversation_analyze_intel(
        conversation_id: str) -> Response:
    from .conversation_bridge import BridgeRefusedError
    from .conversation_intel import (IntelRefusedError,
                                     analyze_conversation)
    try:
        from .conversation_bridge import analyze_import
        analyze_import(conversation_id)
    except BridgeRefusedError:
        pass
    try:
        analyze_conversation(conversation_id)
    except IntelRefusedError:
        pass
    return RedirectResponse(f"/conversations/{conversation_id}",
                            status_code=303)


@app.post("/web/conversation-intel/{conversation_id}/materialize")
async def web_conversation_materialize(conversation_id: str,
                                       request: Request
                                       ) -> Response:
    from .conversation_intel import (IntelRefusedError,
                                     materialize)
    fields = await _form_fields(request)
    try:
        materialize(conversation_id,
                    fields.get("fingerprint", ""),
                    fields.get("action", "candidate"))
    except IntelRefusedError:
        pass
    return RedirectResponse(f"/conversations/{conversation_id}",
                            status_code=303)


@app.get("/api/v1/context/packet")
def api_context_packet(goal: str = "", project_id: str = "",
                       conversation_id: str = "",
                       include_health: str = "") -> dict:
    from .context_packet import build_context_packet
    return build_context_packet(
        goal=goal[:500], project_id=project_id[:80],
        conversation_id=conversation_id[:80],
        include_health=include_health.lower() == "true")


@app.post("/api/v1/context/packet")
def api_context_packet_post(body: dict) -> dict:
    from .context_packet import build_context_packet
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    return build_context_packet(
        goal=str(body.get("goal", ""))[:500],
        project_id=str(body.get("project_id", ""))[:80],
        conversation_id=str(body.get("conversation_id", ""))[:80],
        include_health=bool(body.get("include_health", False)))


@app.get("/api/v1/context/continue")
def api_context_continue(goal: str = "", project_id: str = "",
                         conversation_id: str = "",
                         next_step: str = "") -> dict:
    from .context_packet import build_continuation
    return build_continuation(
        goal=goal[:500], project_id=project_id[:80],
        conversation_id=conversation_id[:80], next_step=next_step[:500])


@app.get("/api/v1/ecosystem/summary")
def api_ecosystem_summary() -> dict:
    from .ecosystem import ecosystem_summary
    return ecosystem_summary()


@app.get("/api/v1/ecosystem/entity")
async def api_ecosystem_entity(entity_id: str, depth: int = 1) -> dict:
    from .ecosystem import entity_context
    try:
        return await entity_context(entity_id, depth)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/ecosystem/overview")
def api_ecosystem_overview() -> dict:
    """One coherent ecosystem model (BIG #41 V2 foundation):
    exists / connected / happening / needs / next /
    nodes-can-do / blocked / growing. Composed from existing
    stores, read-only."""
    from .ecosystem import ecosystem_overview
    return ecosystem_overview()


@app.get("/api/v1/notifications/capability")
def api_notify_capability() -> dict:
    from .notify_center import capability
    return capability()


@app.post("/api/v1/notifications/send", status_code=201)
def api_notify_send(body: dict) -> dict:
    from .notify_center import NotifyRefusedError, send
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    try:
        return send(str(body.get("recipient_node_id", "")),
                    str(body.get("type", "")),
                    str(body.get("title", "")),
                    str(body.get("body", "")),
                    related_entity=str(body.get("related_entity", ""))[:100],
                    related_mission=str(body.get("related_mission", ""))[:80],
                    related_task=str(body.get("related_task", ""))[:80])
    except (NotifyRefusedError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/linux-nodes")
def api_linux_node_contract() -> dict:
    from .linux_node import LINUX_CAPABILITIES, NODE_SETUP_STEPS
    return {"capabilities": list(LINUX_CAPABILITIES),
            "setup_steps": list(NODE_SETUP_STEPS),
            "transport": "pull-only; no inbound ports; no shell",
            "state": "AVAILABLE"}


@app.post("/api/v1/linux-nodes/check")
def api_linux_node_check(body: dict) -> dict:
    from .linux_node import bootstrap_check
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    return bootstrap_check(
        python_version=str(body.get("python_version", "")),
        coordinator_url=str(body.get("coordinator_url", "")),
        node_id=str(body.get("node_id", "")),
        capabilities=body.get("capabilities", []))


@app.get("/api/v1/activity/feed")
def api_activity_feed(limit: int = 30) -> dict:
    from .ecosystem import activity_feed
    return {"items": activity_feed(limit=limit)}


@app.get("/conversations", response_class=HTMLResponse)
def conversations_page() -> str:
    """Conversation bridge: external chats become Mycelium context."""
    from . import ui as _ui
    from .conversation_bridge import KNOWN_PLATFORMS, list_imports
    try:
        imports = list_imports(limit=30)
    except Exception:
        imports = []
    rows = "".join(
        f"<tr><td><a href=\"/conversations/{_ui.esc(item['conversation_id'])}\">"
        f"{_ui.esc(item['title'][:70])}</a></td>"
        f"<td>{_ui.esc(item['source_platform'])}</td>"
        f"<td>{item['message_count']}</td>"
        f"<td class=\"muted\">{_ui.esc(str(item['imported_at'])[:16])}</td></tr>"
        for item in imports) or "<tr><td colspan='4'>No imports yet.</td></tr>"
    platforms = "".join(
        f"<option value='{_ui.esc(name)}'>{_ui.esc(name)}</option>"
        for name in KNOWN_PLATFORMS)
    try:
        from .ecosystem import discoveries as _discoveries
        found = _discoveries(limit=8)
    except Exception:
        found = {"items": [], "research_open_questions": []}
    show_items = "".join(
        f"<li><b>{_ui.esc(item['kind'])}</b> — "
        f"{_ui.esc(item['text'][:160])}<br>"
        f"<span class=\"muted\">uit: <a href=\"{_ui.esc(item['link'])}\">"
        f"{_ui.esc(item['title'][:60])}</a> · evidence: "
        f"{_ui.esc(item['evidence'][:100])}</span></li>"
        for item in found.get("items", [])[:8])
    show_research = "".join(
        f"<li>{_ui.esc(item['question'][:160])} "
        f"<span class=\"muted\">(<a href=\"{_ui.esc(item['link'])}\">"
        f"dossier</a>)</span></li>"
        for item in found.get("research_open_questions", [])[:6])
    main = f"""<h1>AI Conversation Archive</h1>
    <p class="muted">Not another chat app — the bridge between every AI you talk to and the workshop. Import → analyse → missed ideas → candidates → projects → research → context packet → continue anywhere. <a href="/guide">Guide</a> shows what each import still needs.</p>
    <div class="panel"><h2>Te tonen aan Jelles</h2>
    <ul>{show_items or "<li>Nog niets — importeer een gesprek.</li>"}</ul>
    <h3>Open researchvragen</h3><ul>{show_research or "<li>—</li>"}</ul>
    <p><a href="/api/v1/discoveries">discoveries (JSON)</a> · <a href="/api/v1/imports-compare">compare imports (JSON)</a></p></div>
    {_conversations_intel_html()}
    <div class="panel"><h2>Import a conversation</h2>
    <form method="post" action="/web/conversations/import">
    <input type="text" name="title" placeholder="Title" style="width:40%" aria-label="Title"><br><br>
    <select name="source_platform" aria-label="Source platform">{platforms}</select>
    <select name="format" aria-label="Format"><option value="plain">pasted text</option><option value="markdown">markdown</option><option value="txt">txt</option><option value="json">json</option><option value="html">html export</option></select><br><br>
    <textarea name="content" rows="8" style="width:100%" placeholder="Paste the conversation here…" aria-label="Conversation content"></textarea><br><br>
    <button type="submit">Import</button></form></div>
    <div class="panel"><h2>Imported</h2><table><tr><th>Title</th><th>Platform</th><th>Msgs</th><th>When</th></tr>{rows}</table></div>"""
    return _ui.shell("Conversations", "/conversations", main,
                     _ui.command_bar())


def _conversations_intel_html() -> str:
    """Archive overview: RECENT, THEMES, OPEN THREADS,
    DECISIONS, PROMISES, CONTRADICTIONS, MISSED, RESEARCH,
    PROJECT LINKS — all from real intel records."""
    from . import ui as _ui
    try:
        from .conversation_intel import cross_conversation
        aggregate = cross_conversation(limit=10)
    except Exception:
        return ""
    if not aggregate.get("unique_items"):
        return ""
    themes = "".join(
        f"<li>{_ui.esc(entry.get('term', ''))} "
        f"<span class=\"muted\">({len(entry.get('conversations', []))}x)</span></li>"
        for entry in aggregate.get("themes", [])[:10])
    threads = "".join(
        f"<li>{_ui.esc(item.get('text', ''))[:140]} "
        f"<span class=\"muted\">[UNRESOLVED]</span></li>"
        for item in aggregate.get("contradictions", [])[:5])
    revisits = "".join(
        f"<li>{_ui.esc(item.get('text', ''))[:160]}</li>"
        for item in aggregate.get("revisits", [])[:5])
    promises = "".join(
        f"<li>{_ui.esc(item.get('text', ''))[:140]} "
        f"<span class=\"muted\">[{_ui.esc(str(item.get('status', 'UNKNOWN')))}]</span></li>"
        for item in aggregate.get("open_promises", [])[:5])
    return (
        f"<div class=\"panel\"><h2>What the archive holds</h2>"
        f"<h3>Themes</h3><ul>{themes or '<li>—</li>'}</ul>"
        f"<h3>Open threads</h3><ul>{threads or '<li>—</li>'}</ul>"
        f"<h3>Decisions &amp; promises</h3><ul>{promises or '<li>—</li>'}</ul>"
        f"<h3>Revisit?</h3><ul>{revisits or '<li>—</li>'}</ul>"
        f"<p class=\"muted\">Per-conversation detail lives behind "
        f"each import below. Analysis is OBSERVATION/CANDIDATE — "
        f"never fact.</p></div>")


def _conversation_discovery_html(conversation_id: str) -> str:
    """DISCOVERY banner: genuinely new, unmaterialized items.
    UI feedback only — every number is a real count."""
    from . import ui as _ui
    try:
        from .conversation_intel import list_intel
        items = list_intel(conversation_id, limit=200)
    except Exception:
        return ""
    fresh = sum(1 for item in items
                if not item.get("materialized"))
    if not items:
        return ""
    kinds: dict[str, int] = {}
    for item in items:
        kind = str(item.get("kind", ""))
        kinds[kind] = kinds.get(kind, 0) + 1
    summary = " · ".join(f"{count} {kind}"
                         for kind, count in sorted(kinds.items()))
    return (
        f"<div class=\"panel living\"><h2>✨ Discovery</h2>"
        f"<p>{_ui.esc(summary)}. "
        f"{fresh} item(s) not yet materialized — review below, "
        f"then CONFIRM, queue research, or link.</p></div>")


def _conversation_intel_html(conversation_id: str) -> str:
    """Detail sections: themes, decisions, promises, questions,
    contradictions, missed, research, entity links, symbiosis,
    timeline — each with materialize actions."""
    from . import ui as _ui
    try:
        from .conversation_intel import list_intel, timeline
        items = list_intel(conversation_id, limit=200)
        line = timeline(conversation_id, limit=30)
    except Exception:
        return ""
    if not items:
        return ""
    by_kind: dict[str, list[dict]] = {}
    for item in items:
        by_kind.setdefault(str(item.get("kind", "")), []).append(
            item)

    def _materialize_form(item: dict, actions: list[str]) -> str:
        if item.get("materialized"):
            materialized = item["materialized"]
            return (
                f"<span class=\"muted\">→ "
                f"{_ui.esc(str(materialized.get('action', '')))}: "
                f"{_ui.esc(str(materialized.get('candidate_id', materialized.get('run_id', ''))))}</span>")
        buttons = "".join(
            f"<form method=\"post\" action=\"/web/conversation-intel/"
            f"{_ui.esc(conversation_id)}/materialize\" "
            f"style=\"display:inline\">"
            f"<input type=\"hidden\" name=\"fingerprint\" value=\""
            f"{_ui.esc(str(item.get('fingerprint', '')))}\">"
            f"<input type=\"hidden\" name=\"action\" value=\"{action}\">"
            f"<button type=\"submit\">{_ui.esc(action)}</button></form> "
            for action in actions)
        return buttons

    def _section(title: str, kind: str, actions: list[str],
                 extra=None) -> str:
        rows = ""
        for item in by_kind.get(kind, [])[:12]:
            detail = ""
            if extra is not None:
                try:
                    detail = extra(item)
                except Exception:
                    detail = ""
            rows += (
                f"<li>{_ui.esc(str(item.get('text', ''))[:220])}<br>"
                f"<span class=\"muted\">evidence: "
                f"{_ui.esc(str(item.get('evidence', ''))[:160])} · "
                f"{_ui.esc(str(item.get('confidence', item.get('status', ''))))}"
                f"</span><br>{detail}"
                f"{_materialize_form(item, actions)}</li>")
        if not rows:
            return ""
        return f"<div class=\"panel\"><h2>{_ui.esc(title)}</h2><ul>{rows}</ul></div>"

    def _decision_extra(item: dict) -> str:
        return (f"<span class=\"muted\">resolution: "
                f"{_ui.esc(str(item.get('resolution', 'UNRESOLVED')))} · "
                f"CONFIRM/REJECT via the candidate buttons</span><br>")

    def _promise_extra(item: dict) -> str:
        return (f"<span class=\"muted\">owner: "
                f"{_ui.esc(str(item.get('owner', '')))} · status: "
                f"{_ui.esc(str(item.get('status', 'UNKNOWN')))} · "
                f"{_ui.esc(str(item.get('completion_evidence', ''))[:160])}"
                f"</span><br>")

    def _contradiction_extra(item: dict) -> str:
        return (f"<span class=\"muted\">A: "
                f"{_ui.esc(str(item.get('side_a', ''))[:140])}<br>B: "
                f"{_ui.esc(str(item.get('side_b', ''))[:140])}<br>"
                f"status: UNRESOLVED — human resolves</span><br>")

    timeline_rows = "".join(
        f"<li><span class=\"muted\">"
        f"{_ui.esc(str(entry.get('at', 'unknown')))}</span> "
        f"<b>{_ui.esc(str(entry.get('kind', '')))}</b> — "
        f"{_ui.esc(str(entry.get('text', ''))[:140])}</li>"
        for entry in line)
    return (
        _section("Themes", "theme", []) +
        _section("Decisions", "decision", ["candidate"],
                 _decision_extra) +
        _section("Promises", "promise", ["candidate"],
                 _promise_extra) +
        _section("Open questions & research", "research_proposal",
                 ["candidate", "research-queue"]) +
        _section("Contradictions", "contradiction", ["candidate"],
                 _contradiction_extra) +
        _section("Missed items", "missed", ["candidate"]) +
        _section("Entity links", "entity_link", ["link"]) +
        _section("Possible symbioses", "symbiosis", ["link"]) +
        f"<div class=\"panel\"><h2>Timeline</h2><ul class=\"timeline\">"
        f"{timeline_rows}</ul></div>")


@app.get("/conversations/{conversation_id}", response_class=HTMLResponse)
def conversation_detail_page(conversation_id: str):
    from . import ui as _ui
    from .conversation_bridge import (get_import, import_messages,
                                      load_analysis, missed_items)
    meta = get_import(conversation_id)
    if meta is None:
        return HTMLResponse("Unknown conversation", status_code=404)
    messages = import_messages(conversation_id)[:100]
    analysis = load_analysis(conversation_id)
    try:
        missed = missed_items(conversation_id, analysis)
    except Exception:
        missed = []
    turns = "".join(
        f"<article class='sprout'><b>{_ui.esc(str(msg.get('role', '')))}</b>"
        f"<p>{_ui.link_entities(str(msg.get('content', ''))[:2000])}</p></article>"
        for msg in messages)
    findings_list = list((analysis or {}).get("findings", [])[:40])
    findings = "".join(
        f"<li><span class=\"chip\">{_ui.esc(str(item.get('state', '')))}</span> "
        f"<b>{_ui.esc(str(item.get('kind', '')))}</b> - "
        f"{_ui.esc(str(item.get('text', ''))[:220])}<br>"
        f"<span class=\"muted\">evidence: {_ui.esc(str(item.get('evidence', ''))[:160])}</span><br>"
        f"<form method=\"post\" action=\"/web/conversations/"
        f"{_ui.esc(conversation_id)}/findings/{number}/candidate\" "
        f"style=\"display:inline\">"
        f"<button type=\"submit\">Remember as candidate</button></form></li>"
        for number, item in enumerate(findings_list))
    missed_html = "".join(
        f"<li><b>{_ui.esc(str(item.get('kind', '')))}</b> — "
        f"{_ui.esc(str(item.get('text', ''))[:220])}<br>"
        f"<span class=\"muted\">evidence: {_ui.esc(str(item.get('evidence', ''))[:160])}</span></li>"
        for item in missed)
    main = f"""<h1>{_ui.esc(meta['title'][:100])}</h1>
    <p class="muted">{_ui.esc(meta['source_platform'])} · {meta['message_count']} messages · imported {_ui.esc(str(meta['imported_at'])[:16])} · {_ui.esc(meta['execution_state'])} · provenance imported/human_verified=false</p>
    {_conversation_discovery_html(conversation_id)}
    <div class="panel"><h2>What did we miss?</h2><ul>{missed_html or "<li>Nothing flagged — import more context.</li>"}</ul></div>
    <div class="panel"><h2>Analysis (OBSERVATION / CANDIDATE — never fact)</h2><ul>{findings or "<li>Not analyzed yet.</li>"}</ul>
    <p><form method="post" action="/web/conversations/{_ui.esc(conversation_id)}/analyze"><button type="submit">Analyze</button></form> <form method="post" action="/web/conversations/{_ui.esc(conversation_id)}/analyze-intel" style="display:inline"><button type="submit">Analyze intelligence</button></form></p></div>
    {_conversation_intel_html(conversation_id)}
    <div class="panel"><h2>Context bridge — continue elsewhere</h2>
    <p><a href="/api/v1/context/packet?conversation_id={_ui.esc(conversation_id)}">Context packet (JSON)</a> · <a href="/api/v1/context/continue?conversation_id={_ui.esc(conversation_id)}">Continuation (JSON)</a> · <a href="/api/v1/context/packet.md?conversation_id={_ui.esc(conversation_id)}">Packet v2 (Markdown)</a> · <a href="/api/v1/conversation-imports/{_ui.esc(conversation_id)}/markdown">This import (Markdown)</a> · <a href="/api/v1/conversation-imports/{_ui.esc(conversation_id)}/relevance">INVENTory relevance (JSON)</a></p>
    <p><button type="button" id="copypacket">Copy context (Markdown)</button> <span id="copied" class="muted" role="status"></span></p>
    <script>
    document.getElementById('copypacket').addEventListener('click', async e => {{
        const btn = e.currentTarget;
        try {{
            const r = await fetch('/api/v1/context/packet.md?conversation_id={_ui.esc(conversation_id)}');
            const text = await r.text();
            await navigator.clipboard.writeText(text);
            document.getElementById('copied').textContent = 'Copied — paste it into any model.';
        }} catch (err) {{
            document.getElementById('copied').textContent = 'Copy failed — use the Markdown link instead.';
        }}
    }});
    </script>
    <p class="muted">Mycelium is the persistent layer — take the packet to ChatGPT, Claude, Gemini, Codex or any model, bring the answer back as a new import. External AI never approves, never verifies.</p></div>
    <h2>Messages</h2>{turns or "<p>No messages.</p>"}"""
    return _ui.shell("Conversation", "/conversations", main,
                     _ui.command_bar())


@app.post("/web/conversations/import")
async def web_conversation_import(request: Request) -> Response:
    from .conversation_bridge import BridgeRefusedError
    from .conversation_bridge import import_conversation as _import
    fields = await _form_fields(request)
    try:
        record = _import(fields.get("title", "")[:120],
                         fields.get("content", ""),
                         fields.get("format", "plain"),
                         fields.get("source_platform", "other"))
    except BridgeRefusedError:
        return RedirectResponse("/conversations", status_code=303)
    return RedirectResponse(
        f"/conversations/{record['conversation_id']}", status_code=303)


@app.post("/web/conversations/{conversation_id}/findings/{index}/candidate")
async def web_finding_to_candidate(conversation_id: str,
                                   index: int) -> Response:
    from .conversation_bridge import load_analysis
    from .events import new_event as _bus_new, \
        save_event as _bus_save
    from .knowledge import (CandidateRefusedError,
                            candidate_from_finding)
    analysis = load_analysis(conversation_id) or {}
    findings = analysis.get("findings", [])
    try:
        entry = candidate_from_finding(
            conversation_id, findings[int(index)])
        _bus_save(_bus_new(
            "candidate.observed",
            f"Candidate {entry.candidate_id} from "
            f"{conversation_id} finding {index}"))
    except (CandidateRefusedError, IndexError, ValueError,
            TypeError):
        pass
    return RedirectResponse(f"/conversations/{conversation_id}",
                            status_code=303)


@app.post("/web/conversations/{conversation_id}/analyze")
async def web_conversation_analyze(conversation_id: str) -> Response:
    from .conversation_bridge import BridgeRefusedError, analyze_import
    try:
        analyze_import(conversation_id)
    except BridgeRefusedError:
        pass
    return RedirectResponse(f"/conversations/{conversation_id}",
                            status_code=303)


@app.get("/nodes", response_class=HTMLResponse)
def nodes_page(check_cap: str = "") -> str:
    """Nodes as ecosystem machines: what each can do, honest status."""
    from . import ui as _ui
    rows = list_nodes()
    cards = "".join(
        f"<div class=\"sprout{' dim-offline' if record['derived_status'] in ('offline', 'stale', 'disabled') else ''}\"><b>{_ui.status_dot(record['derived_status'])}"
        f"{_ui.esc(record['node_id'])}</b><br>"
        f"{_ui.chip(record['derived_status'])}"
        f"{_ui.chip(record.get('tier', 'unknown'))}"
        f"{''.join(_ui.chip(role) for role in _node_role_list(record))}<br>"
        f"<span class=\"muted\">WHAT IT CAN DO:</span><br>"
        f"<small>{_ui.esc(', '.join(record['capabilities'][:12]) or 'no capabilities advertised')}</small><br>"
        + (f"<span>⚙ <a href=\"/tasks/{(record.get('current_task') or {}).get('task_id', '')}\">task #{(record.get('current_task') or {}).get('task_id', '')} ({_ui.esc(str((record.get('current_task') or {}).get('kind', '')))})</a></span><br>"
           if record.get("current_task") else "<span class=\"muted\">idle — no assigned task</span><br>")
        + f"<span class=\"muted\">models {len(record.get('models', []))} · executors {len(record.get('executors', []))} · last seen {_ui.esc(str(record.get('last_seen', ''))[:16])}</span></div>"
        for record in rows) or _ui.empty("No nodes yet — start one.")
    main = f"""<h1>Nodes — small ecosystem machines</h1>
    <p class="muted">Pull-only: nodes poll, the coordinator never pushes commands. ONLINE / STALE (60s) / OFFLINE / DISABLED. Capabilities are owner-advertised, never wildcard. Each card shows WHAT IT CAN DO.</p>
    <div class="panel"><h2>Linux node onboarding</h2>
    <p class="muted">Old laptop → Mycelium node. <a href="/api/v1/linux-nodes">Contract (JSON)</a> · <a href="/api/v1/agent/status">agent JSON</a> · one command: <code>python3 node_client/bootstrap.py --node-id linux-laptop-1</code></p>
    <p>Capabilities that exist: <code>node.status, research.search, research.fetch, analysis.ollama, inventory.read, file.inspect</code> — no shell, no arbitrary commands.</p></div>
    <div class="panel"><h2>Which node can do this?</h2>
    <form method="get" action="/nodes" aria-label="Routing check">
    <input type="text" name="check_cap" placeholder="research.fetch" value="{_ui.esc(check_cap[:80])}" style="width:50%" aria-label="Capability" autocomplete="off">
    <button type="submit">Check</button></form>
    {_routing_answer_html(check_cap)}</div>
    {_mesh_panel_html()}
    {_digital_world_html(rows)}
    <div class="grove">{cards}</div>"""
    return _ui.shell("Nodes", "/nodes", main, _ui.command_bar())


# -- DIGITAL WORLD (VERTICAL SLICE 1) -------------------------------------
# Interactieve NODE -> DISPLAY view op /nodes. Vanilla JS, geen
# framework, geen writes: alle state (selectie, UI-offsets, zoom,
# pan) leeft in de browser. Slepen verandert alleen lokale
# editor-state en wordt expliciet als UI-positie gelabeld.

DWORLD_JS = """
(function(){
"use strict";
var data = (typeof DWDATA !== "undefined" && DWDATA) || {nodes: []};
var svg = document.getElementById("dw-stage");
var details = document.getElementById("dw-details");
if (!svg || !details) return;
var NS = "http://www.w3.org/2000/svg";
var state = {scale: 1, tx: 0, ty: 0, selNode: null, selDisplay: null, ui: {}};
function esc(s){ return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
function fmt(v, suffix){ return (v === null || v === undefined || v === "") ? "onbekend" : esc(v) + (suffix || ""); }
function ukey(n, d){ return n + "\\u0000" + d; }
function findNode(id){ var out = null; (data.nodes || []).forEach(function(n){ if (n.node_id === id) out = n; }); return out; }
function isOffline(n){ return n.derived_status === "offline" || n.derived_status === "stale" || n.derived_status === "disabled"; }
function layout(){
  var placed = [];
  (data.nodes || []).forEach(function(n, i){
    var ox = 40 + i * 470, oy = 70;
    var minX = null, minY = null;
    (n.displays || []).forEach(function(d){
      if (d.x !== null && d.x !== undefined && d.y !== null && d.y !== undefined){
        if (minX === null || d.x < minX) minX = d.x;
        if (minY === null || d.y < minY) minY = d.y;
      }
    });
    var cursorY = 0, boxes = [], bottom = oy + 60;
    (n.displays || []).forEach(function(d){
      var known = !!(d.width && d.height);
      var w = known ? Math.max(14, d.width / 8) : 72;
      var h = known ? Math.max(12, d.height / 8) : 48;
      var bx, by, discovered = false;
      if (d.x !== null && d.x !== undefined && d.y !== null && d.y !== undefined && minX !== null){
        bx = (d.x - minX) / 8; by = (d.y - minY) / 8; discovered = true;
      } else { bx = 0; by = cursorY; cursorY += h + 26; }
      var ui = state.ui[ukey(n.node_id, d.id)] || {dx: 0, dy: 0};
      var bx2 = ox + 16 + bx + ui.dx, by2 = oy + 64 + by + ui.dy;
      boxes.push({d: d, x: bx2, y: by2, w: w, h: h, known: known,
        moved: (ui.dx !== 0 || ui.dy !== 0), discovered: discovered, ui: ui});
      if (by2 + h > bottom) bottom = by2 + h;
    });
    var right = ox + 220;
    boxes.forEach(function(b){ if (b.x + b.w + 16 > right) right = b.x + b.w + 16; });
    placed.push({n: n, ox: ox, oy: oy, w: Math.max(220, right - ox), h: Math.max(110, bottom - oy + 14), boxes: boxes});
  });
  return placed;
}
function el(name, attrs, parent){
  var e = document.createElementNS(NS, name);
  for (var k in attrs){ e.setAttribute(k, attrs[k]); }
  parent.appendChild(e);
  return e;
}
function render(){
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  var g = el("g", {transform: "translate(" + state.tx + "," + state.ty + ") scale(" + state.scale + ")"}, svg);
  var placed = layout();
  if (!placed.length){
    var t = el("text", {x: 40, y: 60}, g);
    t.textContent = "Nog geen nodes — start een node om de wereld te vullen.";
  }
  placed.forEach(function(p){
    var n = p.n;
    var grp = el("g", {"class": "w-node", tabindex: "0", role: "button",
      "aria-label": "Node " + n.node_id + (isOffline(n) ? " (offline)" : "")}, g);
    if (isOffline(n)) grp.setAttribute("opacity", "0.55");
    var sel = (state.selNode === n.node_id && !state.selDisplay);
    el("rect", {x: p.ox, y: p.oy, width: p.w, height: p.h, rx: 8,
      fill: "var(--surface)", stroke: sel ? "var(--amber)" : "var(--line)",
      "stroke-width": sel ? 3 : 1.5, "data-node": n.node_id}, grp);
    var title = el("text", {x: p.ox + 10, y: p.oy + 22, "font-weight": "bold"}, grp);
    title.textContent = (n.hostname || n.node_id) + " [" + n.derived_status + "]";
    var sub = el("text", {x: p.ox + 10, y: p.oy + 38}, grp);
    var osName = (n.identity && n.identity.os) || "OS onbekend";
    sub.textContent = osName + " · " + (n.displays || []).length + " display(s)";
    p.boxes.forEach(function(b){
      var d = b.d;
      var dsel = (state.selNode === n.node_id && state.selDisplay === d.id);
      var r = el("rect", {x: b.x, y: b.y, width: b.w, height: b.h, rx: 3,
        fill: dsel ? "var(--amber-dim)" : "var(--soil-2)",
        stroke: dsel ? "var(--amber)" : (d.primary ? "var(--moss-bright)" : "var(--moss)"),
        "stroke-width": dsel ? 3 : (d.primary ? 2.5 : 1.5),
        "stroke-dasharray": b.known ? "" : "5 3",
        "data-node": n.node_id, "data-display": d.id,
        tabindex: "0", role: "button",
        "aria-label": "Display " + (d.name || d.id)}, grp);
      r.style.cursor = "grab";
      var label = (d.name || d.id) + " " + ((d.width && d.height) ? d.width + "x" + d.height : "onbekend");
      var lt = el("text", {x: b.x + 4, y: b.y + 14, "data-node": n.node_id, "data-display": d.id}, grp);
      lt.textContent = String(label).slice(0, 26);
      if (b.moved){
        var mv = el("text", {x: b.x + 4, y: b.y + b.h - 5, "data-node": n.node_id, "data-display": d.id}, grp);
        mv.textContent = "UI-pos (niet fysiek)";
      }
      r.addEventListener("click", function(ev){ if (suppressClick){ return; } ev.stopPropagation(); select(n.node_id, d.id); });
      r.addEventListener("keydown", function(ev){
        if (ev.key === "Enter" || ev.key === " "){ ev.preventDefault(); select(n.node_id, d.id); }
      });
      r.addEventListener("pointerdown", function(ev){ startDisplayDrag(ev, n.node_id, d.id); });
      lt.addEventListener("click", function(ev){ if (suppressClick){ return; } ev.stopPropagation(); select(n.node_id, d.id); });
      lt.addEventListener("pointerdown", function(ev){ startDisplayDrag(ev, n.node_id, d.id); });
    });
    grp.addEventListener("click", function(ev){
      if (suppressClick) return;
      if (ev.target && ev.target.getAttribute && ev.target.getAttribute("data-display")) return;
      select(n.node_id, null);
    });
    grp.addEventListener("keydown", function(ev){
      if (ev.key === "Enter" || ev.key === " "){ ev.preventDefault(); select(n.node_id, null); }
    });
  });
}
function select(nodeId, displayId){
  state.selNode = nodeId; state.selDisplay = displayId || null;
  render(); showDetails();
}
function showDetails(){
  var n = state.selNode ? findNode(state.selNode) : null;
  if (!n){ details.innerHTML = "<p class=\\"muted\\">Selecteer een node of display hierboven voor details.</p>"; return; }
  var ident = n.identity || {}, hw = n.hardware || {}, net = n.network || {};
  function row(k, v){ return "<tr><th scope=\\"row\\">" + esc(k) + "</th><td>" + v + "</td></tr>"; }
  var gpu = (hw.gpu && hw.gpu.length) ? esc(hw.gpu.join(", ")) : "onbekend";
  var ifaces = (net.interfaces && net.interfaces.length) ? esc(net.interfaces.join(", ")) : "onbekend";
  var html = "<h3>" + esc(n.hostname || n.node_id) + " <span class=\\"muted\\">" + esc(n.node_id) + "</span></h3>";
  html += "<h4>IDENTITY (gerapporteerd)</h4><table><tbody>";
  html += row("node_id", esc(n.node_id)) + row("hostname", fmt(n.hostname));
  html += row("OS", fmt(ident.os)) + row("architectuur", fmt(ident.architecture));
  html += row("platform", fmt(ident.platform)) + row("status", esc(n.derived_status) + " / " + esc(n.health_status || "?"));
  html += row("laatst gezien", fmt(n.last_seen)) + "</tbody></table>";
  html += "<h4>HARDWARE (indien gerapporteerd)</h4><table><tbody>";
  html += row("CPU cores", fmt(hw.cpu_count)) + row("RAM", fmt(hw.memory_total_mb, " MB")) + row("GPU", gpu);
  html += "</tbody></table>";
  html += "<h4>NETWORK</h4><table><tbody>";
  html += row("connectiviteit", esc(net.connectivity || n.derived_status)) + row("interfaces", ifaces);
  html += "</tbody></table>";
  html += "<h4>DISPLAYS (" + (n.displays || []).length + ")</h4>";
  html = dwRemoteHTML(n) + html;
  if (!(n.displays || []).length){
    html += "<p class=\\"muted\\">Deze node rapporteert geen displays (headless of discovery niet beschikbaar) — geen data verzonnen.</p>";
  } else {
    html += "<table><thead><tr><th>display</th><th>resolutie</th><th>fysiek</th><th>refresh</th><th>positie (discovered)</th><th>primary</th></tr></thead><tbody>";
    (n.displays || []).forEach(function(d){
      var res = (d.width && d.height) ? esc(d.width + "×" + d.height) : "onbekend";
      var phys = (d.physical_width_mm && d.physical_height_mm) ? esc(d.physical_width_mm + "×" + d.physical_height_mm + " mm") : "onbekend";
      var hz = (d.refresh_rate !== null && d.refresh_rate !== undefined) ? esc(d.refresh_rate) + " Hz" : "onbekend";
      var pos = (d.x !== null && d.x !== undefined && d.y !== null && d.y !== undefined) ? esc("x=" + d.x + " y=" + d.y) : "onbekend";
      var mark = (state.selDisplay === d.id) ? " ★" : "";
      html += "<tr><td>" + esc(d.name || d.id) + mark + "<br><small class=\\"muted\\">" + esc(d.id) + "</small></td><td>" + res + "</td><td>" + phys + "</td><td>" + hz + "</td><td>" + pos + "</td><td>" + (d.primary ? "ja" : "nee") + "</td></tr>";
    });
    html += "</tbody></table>";
    html += "<p class=\\"muted\\">DISCOVERED = door de node gerapporteerd (alleen lezen). Versleepte UI-posities zijn lokale weergave en veranderen nooit de fysieke configuratie.</p>";
  }
  details.innerHTML = html;
  dwBindRemote(n);
}
var DWSESSION = {id: null, node: null, lastSend: 0, lastScroll: 0, padW: 0, padH: 0, padX: null, padY: null, dragging: false};
var DWCAPS = [
  ["Mouse", ["desktop.mouse.move"]],
  ["Click", ["desktop.mouse.click"]],
  ["Keyboard", ["desktop.keyboard.type", "desktop.keyboard.press"]],
  ["Scroll", ["desktop.mouse.scroll"]],
  ["Drag", ["desktop.mouse.move", "desktop.mouse.click"]],
  ["Clipboard", ["desktop.clipboard.write", "desktop.clipboard.read"]]
];
function dwHas(n, cap){ return (n.capabilities || []).indexOf(cap) !== -1; }
function dwCapSupported(n, name){
  if (name === "Clipboard") return dwHas(n, "desktop.clipboard.write") || dwHas(n, "desktop.clipboard.read");
  var need = null;
  DWCAPS.forEach(function(c){ if (c[0] === name) need = c[1]; });
  if (!need) return false;
  for (var i = 0; i < need.length; i++){ if (!dwHas(n, need[i])) return false; }
  return true;
}
function dwCapState(n, name){
  if (isOffline(n)) return "OFFLINE";
  if (!dwCapSupported(n, name)) return "UNSUPPORTED";
  if (DWSESSION.id && DWSESSION.node === n.node_id) return "CONNECTED";
  return "AVAILABLE";
}
function dwPadSize(n){
  var prim = null, first = null;
  (n.displays || []).forEach(function(d){
    if (d.width && d.height){
      if (!first) first = d;
      if (d.primary) prim = d;
    }
  });
  var pick = prim || first;
  if (pick) return {w: pick.width, h: pick.height, approx: false};
  return {w: 1920, h: 1080, approx: true};
}
function dwRemoteHTML(n){
  var connected = (DWSESSION.id && DWSESSION.node === n.node_id);
  var state = "AVAILABLE";
  if (isOffline(n)) state = "OFFLINE";
  else if (n.remote_mouse !== "supported") state = "UNSUPPORTED";
  else if (connected) state = "CONNECTED";
  var html = "<h4>REMOTE CONTROL</h4>";
  html += "<p>STATUS: <b id=\"dw-conn-state\">" + state + "</b> <span class=\"muted\">expliciet en tijdelijk, nooit automatisch</span></p>";
  html += "<table><thead><tr><th>capability</th><th>status</th></tr></thead><tbody>";
  DWCAPS.forEach(function(c){
    html += "<tr><td>" + c[0] + "</td><td id=\"dw-cap-" + c[0] + "\">" + dwCapState(n, c[0]) + "</td></tr>";
  });
  html += "</tbody></table>";
  if (state === "CONNECTED"){
    var size = dwPadSize(n);
    html += "<div id=\"dw-pad\" tabindex=\"0\" role=\"application\" aria-label=\"Remote vlak: bewegen = muis, klikken = klik, slepen = drag, wiel = scroll\" style=\"height:180px;border:1px solid var(--amber);border-radius:6px;display:flex;align-items:center;justify-content:center;cursor:crosshair;touch-action:none\">Beweeg / klik / sleep in dit vlak. Wiel = scroll.</div>";
    html += "<p class=\"muted\">Mapping: " + size.w + "x" + size.h + (size.approx ? " (bij benadering — geen display-rapport, node klemt af)" : " (primaire display)") + "</p>";
    html += "<p class=\"flowline\">"
      + "<button type=\"button\" id=\"dw-click-left\">Left click</button>"
      + "<button type=\"button\" id=\"dw-click-middle\">Middle</button>"
      + "<button type=\"button\" id=\"dw-click-right\">Right click</button>"
      + "</p>";
    html += "<p><input type=\"text\" id=\"dw-kbd\" placeholder=\"Typ hier (Enter = verstuur tekst)\" autocomplete=\"off\" style=\"width:60%\" aria-label=\"Remote keyboard\"> "
      + "<span class=\"muted\" id=\"dw-kbd-msg\"></span></p>";
    html += "<p class=\"flowline\">"
      + "<button type=\"button\" data-dwkey=\"enter\">Enter</button>"
      + "<button type=\"button\" data-dwkey=\"escape\">Esc</button>"
      + "<button type=\"button\" data-dwkey=\"tab\">Tab</button>"
      + "<button type=\"button\" data-dwkey=\"backspace\">Backspace</button>"
      + "<button type=\"button\" data-dwkey=\"up\">↑</button>"
      + "<button type=\"button\" data-dwkey=\"down\">↓</button>"
      + "<button type=\"button\" data-dwkey=\"left\">←</button>"
      + "<button type=\"button\" data-dwkey=\"right\">→</button>"
      + "</p>";
    html += "<p><textarea id=\"dw-clip\" rows=\"2\" style=\"width:100%\" placeholder=\"Clipboard-tekst (alleen tekst, max 64k)\" aria-label=\"Clipboard tekst\"></textarea></p>";
    html += "<p class=\"flowline\">"
      + "<button type=\"button\" id=\"dw-clip-send\">Send to node</button>"
      + "<button type=\"button\" id=\"dw-clip-request\">Request from node</button>"
      + "<span class=\"muted\" id=\"dw-clip-msg\"></span></p>";
    html += "<p class=\"muted\" id=\"dw-clip-out\" aria-live=\"polite\"></p>";
    html += "<p><button type=\"button\" id=\"dw-disconnect\">DISCONNECT</button> <span class=\"muted\" id=\"dw-conn-msg\"></span></p>";
  } else if (state === "AVAILABLE"){
    html += "<p><button type=\"button\" id=\"dw-connect\">CONNECT</button> <span class=\"muted\" id=\"dw-conn-msg\"></span></p>";
  } else if (state === "OFFLINE"){
    html += "<p class=\"muted\">Node is offline — remote input wordt geweigerd.</p>";
  } else {
    html += "<p class=\"muted\">Node adverteert desktop.mouse.move niet — start de node met --remote-mouse (en --remote-click/--remote-keyboard/--remote-scroll/--remote-clipboard) op een ondersteund OS.</p>";
  }
  return html;
}
  return html;
}
function dwMsg(t){ var m = document.getElementById("dw-conn-msg"); if (m) m.textContent = t; }
function dwSetError(t){ var s = document.getElementById("dw-conn-state"); if (s) s.textContent = "ERROR"; dwMsg(t); }
function dwBindRemote(n){
  var c = document.getElementById("dw-connect");
  if (c) c.addEventListener("click", function(){ dwConnect(n.node_id); });
  var d = document.getElementById("dw-disconnect");
  if (d) d.addEventListener("click", function(){ dwDisconnect(); });
  var pad = document.getElementById("dw-pad");
  if (pad){
    var size = dwPadSize(n);
    DWSESSION.padW = size.w; DWSESSION.padH = size.h;
    pad.addEventListener("pointermove", function(ev){ dwPadMove(ev, pad); });
    pad.addEventListener("pointerdown", function(ev){
      if (!DWSESSION.id) return;
      ev.preventDefault();
      try { pad.setPointerCapture(ev.pointerId); } catch (e) {}
      var pos = dwPadXY(ev, pad);
      DWSESSION.dragging = true;
      dwInput("mouse_down", {x: pos.x, y: pos.y, button: "left"});
    });
    pad.addEventListener("pointerup", function(ev){
      if (!DWSESSION.dragging) return;
      DWSESSION.dragging = false;
      var pos = dwPadXY(ev, pad);
      dwInput("mouse_up", {x: pos.x, y: pos.y, button: "left"});
    });
    pad.addEventListener("pointercancel", function(){
      if (!DWSESSION.dragging) return;
      DWSESSION.dragging = false;
      dwInput("mouse_up", {x: DWSESSION.padX === null ? Math.round(DWSESSION.padW / 2) : DWSESSION.padX, y: DWSESSION.padY === null ? Math.round(DWSESSION.padH / 2) : DWSESSION.padY, button: "left"});
    });
    pad.addEventListener("pointerleave", function(){
      if (!DWSESSION.dragging) return;
      DWSESSION.dragging = false;
      dwInput("mouse_up", {x: DWSESSION.padX === null ? Math.round(DWSESSION.padW / 2) : DWSESSION.padX, y: DWSESSION.padY === null ? Math.round(DWSESSION.padH / 2) : DWSESSION.padY, button: "left"});
    });
    pad.addEventListener("contextmenu", function(ev){
      ev.preventDefault();
      var pos = dwPadXY(ev, pad);
      dwInput("click", {x: pos.x, y: pos.y, button: "right"});
    });
    pad.addEventListener("wheel", function(ev){
      ev.preventDefault();
      if (!DWSESSION.id) return;
      var nowMs = Date.now();
      if (nowMs - DWSESSION.lastScroll < 60) return;
      DWSESSION.lastScroll = nowMs;
      var dy = Math.round(ev.deltaY);
      if (dy === 0) return;
      dy = Math.max(-10000, Math.min(10000, dy));
      dwInput("scroll", {dx: 0, dy: dy});
    }, {passive: false});
  }
  ["left", "middle", "right"].forEach(function(btn){
    var b = document.getElementById("dw-click-" + btn);
    if (b) b.addEventListener("click", function(){
      dwInput("click", {x: DWSESSION.padX === null ? Math.round(DWSESSION.padW / 2) : DWSESSION.padX, y: DWSESSION.padY === null ? Math.round(DWSESSION.padH / 2) : DWSESSION.padY, button: btn});
    });
  });
  var keys = document.querySelectorAll("[data-dwkey]");
  for (var i = 0; i < keys.length; i++){
    (function(btn){
      btn.addEventListener("click", function(){
        dwInput("key_press", {key: btn.getAttribute("data-dwkey")});
      });
    })(keys[i]);
  }
  var kbd = document.getElementById("dw-kbd");
  if (kbd) kbd.addEventListener("keydown", function(ev){ dwKeyDown(ev, kbd); });
  var clipSend = document.getElementById("dw-clip-send");
  if (clipSend) clipSend.addEventListener("click", function(){
    var area = document.getElementById("dw-clip");
    var text = area ? area.value : "";
    if (!text){ dwClipMsg("niets te versturen"); return; }
    dwInput("clipboard_set", {text: text});
  });
  var clipReq = document.getElementById("dw-clip-request");
  if (clipReq) clipReq.addEventListener("click", function(){ dwClipRequest(0); });
}
function dwConnect(nodeId){
  dwMsg("verbinden…");
  fetch("/api/v1/remote-input/sessions", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({node_id: nodeId})}).then(function(res){
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }).then(function(data){
    DWSESSION.id = data.session_id; DWSESSION.node = data.node_id;
    showDetails();
  }).catch(function(err){ DWSESSION.id = null; DWSESSION.node = null; dwSetError("ERROR: " + err.message); });
}
function dwDisconnect(){
  var id = DWSESSION.id;
  DWSESSION.id = null; DWSESSION.node = null;
  showDetails();
  if (!id) return;
  fetch("/api/v1/remote-input/sessions/" + encodeURIComponent(id) + "/close", {method: "POST"}).catch(function(){});
}
function dwPadXY(ev, pad){
  var rect = pad.getBoundingClientRect();
  var x = Math.round((ev.clientX - rect.left) / Math.max(1, rect.width) * DWSESSION.padW);
  var y = Math.round((ev.clientY - rect.top) / Math.max(1, rect.height) * DWSESSION.padH);
  x = Math.max(0, Math.min(16384, x)); y = Math.max(0, Math.min(16384, y));
  DWSESSION.padX = x; DWSESSION.padY = y;
  return {x: x, y: y};
}
function dwPadMove(ev, pad){
  if (!DWSESSION.id) return;
  var nowMs = Date.now();
  if (nowMs - DWSESSION.lastSend < 40) return;
  DWSESSION.lastSend = nowMs;
  var pos = dwPadXY(ev, pad);
  fetch("/api/v1/remote-input/sessions/" + encodeURIComponent(DWSESSION.id) + "/move", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({x: pos.x, y: pos.y})}).then(function(res){
    if (res.status === 410 || res.status === 404 || res.status === 403){
      DWSESSION.id = null; DWSESSION.node = null; DWSESSION.dragging = false;
      showDetails();
      dwMsg("sessie beeindigd door de server — opnieuw CONNECT om door te gaan");
    } else if (!res.ok){
      dwSetError("ERROR: HTTP " + res.status);
    }
  }).catch(function(err){ dwSetError("ERROR: " + err.message); });
}
function dwInput(kind, params){
  if (!DWSESSION.id) return;
  fetch("/api/v1/remote-input/sessions/" + encodeURIComponent(DWSESSION.id) + "/input", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({kind: kind, params: params})}).then(function(res){
    if (res.status === 410 || res.status === 404 || res.status === 403){
      DWSESSION.id = null; DWSESSION.node = null; DWSESSION.dragging = false;
      showDetails();
      dwMsg("sessie beeindigd door de server — opnieuw CONNECT om door te gaan");
    } else if (!res.ok){
      dwSetError("ERROR: HTTP " + res.status);
    }
  }).catch(function(err){ dwSetError("ERROR: " + err.message); });
}
var DWKEYS = {Enter: "enter", Escape: "escape", Esc: "esc", Tab: "tab", Backspace: "backspace", Delete: "delete", ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", Home: "home", End: "end", PageUp: "pageup", PageDown: "pagedown", Insert: "insert", PrintScreen: "printscreen", Pause: "pause"};
for (var _f = 1; _f <= 12; _f++){ DWKEYS["F" + _f] = "f" + _f; }
function dwKeyDown(ev, field){
  if (!DWSESSION.id) return;
  var mods = [];
  if (ev.ctrlKey) mods.push("ctrl");
  if (ev.altKey) mods.push("alt");
  if (ev.shiftKey && DWKEYS[ev.key]) mods.push("shift");
  if (ev.metaKey) mods.push("win");
  if (mods.length && ev.key.length === 1){
    ev.preventDefault();
    mods.push(ev.key.toLowerCase());
    dwInput("hotkey", {keys: mods.slice(0, 4)});
    return;
  }
  if (DWKEYS[ev.key]){
    ev.preventDefault();
    if (ev.key === "Enter" && field.value){
      dwInput("type_text", {text: field.value});
      field.value = "";
    } else {
      dwInput("key_press", {key: DWKEYS[ev.key]});
    }
    return;
  }
  if (ev.key.length === 1 && !ev.ctrlKey && !ev.altKey && !ev.metaKey){
    ev.preventDefault();
    dwInput("type_text", {text: ev.key});
  }
}
function dwClipMsg(t){ var m = document.getElementById("dw-clip-msg"); if (m) m.textContent = t; }
function dwClipOut(t){ var m = document.getElementById("dw-clip-out"); if (m) m.textContent = t; }
function dwClipRequest(attempt){
  if (!DWSESSION.id) return;
  if (attempt === 0){
    dwClipMsg("opvragen…");
    dwClipOut("");
    fetch("/api/v1/remote-input/sessions/" + encodeURIComponent(DWSESSION.id) + "/clipboard/request", {method: "POST"}).then(function(res){
      if (!res.ok){ dwClipMsg("ERROR: HTTP " + res.status); return; }
      setTimeout(function(){ dwClipRequest(1); }, 600);
    }).catch(function(err){ dwClipMsg("ERROR: " + err.message); });
    return;
  }
  fetch("/api/v1/remote-input/sessions/" + encodeURIComponent(DWSESSION.id) + "/clipboard").then(function(res){
    if (!res.ok){ dwClipMsg("ERROR: HTTP " + res.status); return; }
    return res.json();
  }).then(function(data){
    if (!data) return;
    if (data.text !== null && data.text !== undefined){
      dwClipMsg("ontvangen");
      dwClipOut("Node clipboard: " + data.text.slice(0, 500));
    } else if (attempt < 6){
      setTimeout(function(){ dwClipRequest(attempt + 1); }, 500);
    } else {
      dwClipMsg("niets ontvangen (node heeft geen tekst gelezen)");
    }
  }).catch(function(err){ dwClipMsg("ERROR: " + err.message); });
}
var drag = null, suppressClick = false;
function startDisplayDrag(ev, nodeId, displayId){
  ev.stopPropagation();
  var k = ukey(nodeId, displayId);
  var ui = state.ui[k] || {dx: 0, dy: 0};
  drag = {kind: "display", node: nodeId, display: displayId, key: k,
    startX: ev.clientX, startY: ev.clientY, dx: ui.dx, dy: ui.dy, moved: false};
  try { ev.target.setPointerCapture(ev.pointerId); } catch (e) {}
  ev.preventDefault();
}
svg.addEventListener("pointerdown", function(ev){
  if (drag) return;
  drag = {kind: "pan", startX: ev.clientX, startY: ev.clientY, tx: state.tx, ty: state.ty, moved: false};
  try { svg.setPointerCapture(ev.pointerId); } catch (e) {}
});
svg.addEventListener("pointermove", function(ev){
  if (!drag) return;
  var dx = ev.clientX - drag.startX, dy = ev.clientY - drag.startY;
  if (Math.abs(dx) + Math.abs(dy) > 4){ drag.moved = true; suppressClick = true; }
  if (!drag.moved) return;
  if (drag.kind === "pan"){ state.tx = drag.tx + dx; state.ty = drag.ty + dy; render(); }
  else {
    state.ui[drag.key] = {dx: drag.dx + dx / state.scale, dy: drag.dy + dy / state.scale};
    state.selNode = drag.node; state.selDisplay = drag.display;
    render(); showDetails();
  }
});
function endDrag(){
  if (drag && drag.kind === "display" && !drag.moved){ select(drag.node, drag.display); }
  drag = null;
  setTimeout(function(){ suppressClick = false; }, 0);
}
svg.addEventListener("pointerup", endDrag);
svg.addEventListener("pointercancel", function(){ drag = null; suppressClick = false; });
svg.addEventListener("wheel", function(ev){
  ev.preventDefault();
  state.scale = Math.max(0.3, Math.min(3, state.scale * (ev.deltaY < 0 ? 1.1 : 0.9)));
  render();
}, {passive: false});
document.getElementById("dw-zin").addEventListener("click", function(){ state.scale = Math.min(3, state.scale * 1.2); render(); });
document.getElementById("dw-zout").addEventListener("click", function(){ state.scale = Math.max(0.3, state.scale / 1.2); render(); });
document.getElementById("dw-reset").addEventListener("click", function(){
  state.ui = {}; state.scale = 1; state.tx = 0; state.ty = 0;
  state.selNode = null; state.selDisplay = null;
  render(); showDetails();
});
render();
})();
"""


def _digital_world_html(rows: list[dict]) -> str:
    """Interactive DIGITAL WORLD view (VERTICAL SLICE 1).

    Server renders a derived NODE -> DISPLAY snapshot plus a
    server-side fallback list; vanilla JS adds select / drag
    (UI-state only) / zoom / pan / reset. This panel performs
    zero writes: no forms, no POST, no node contact. Dragging a
    display only moves local editor-state and is labelled as
    such — it never claims a physical change."""
    import json as _json
    from . import ui as _ui
    from .nodes import derive_digital_world
    try:
        world = derive_digital_world(rows or [])
    except Exception:
        world = {"nodes": [], "node_count": 0, "display_count": 0,
                 "provenance": "derived", "honesty": ""}
    snapshot = _json.dumps(world, sort_keys=True).replace("</", "<\\/")
    fallback = []
    for node in world.get("nodes", []):
        offline = str(node.get("derived_status", "")) in (
            "offline", "stale", "disabled")
        disp_rows = []
        for disp in node.get("displays", []):
            width, height = disp.get("width"), disp.get("height")
            res = (f"{width}×{height}" if width and height
                   else "resolutie onbekend")
            phys_w, phys_h = (disp.get("physical_width_mm"),
                              disp.get("physical_height_mm"))
            phys = (f"{phys_w}×{phys_h} mm" if phys_w and phys_h
                    else "fysieke maat onbekend")
            rate = disp.get("refresh_rate")
            rate_text = (f"{rate:g} Hz" if rate else "onbekend")
            disp_rows.append(
                f"<div class=\"dw-display\" "
                f"data-display-id=\"{_ui.esc(disp.get('id', ''))}\" "
                f"data-node-id=\"{_ui.esc(node.get('node_id', ''))}\">"
                f"<b>{_ui.esc(disp.get('name') or disp.get('id', ''))}</b> "
                f"{_ui.esc(res)} · {('★ primary' if disp.get('primary') else 'secondary')} · "
                f"{_ui.esc(phys)} · { _ui.esc(rate_text)}</div>")
        displays_html = "".join(disp_rows) or (
            "<div class=\"muted\">geen displays gerapporteerd</div>")
        os_label = ((node.get("identity") or {}).get("os")
                    or "OS onbekend")
        fallback.append(
            f"<div class=\"sprout dw-node{' dim-offline' if offline else ''}\" "
            f"data-node-id=\"{_ui.esc(node.get('node_id', ''))}\">"
            f"<b>{_ui.status_dot(node.get('derived_status', 'unknown'))}"
            f"{_ui.esc(node.get('node_id', ''))}</b> "
            f"{_ui.chip(node.get('derived_status', 'unknown'))} "
            f"{_ui.chip(str(os_label))} "
            f"<span class=\"muted\">{node.get('display_count', 0)} display(s)</span>"
            f"<span class=\"muted dw-remote\">remote mouse: "
            f"{_ui.esc(node.get('remote_mouse', 'unsupported'))}</span>"
            f"{displays_html}</div>")
    fallback_html = "".join(fallback) or _ui.empty(
        "Nog geen nodes — start een node om de digitale wereld te vullen.")
    return f"""<div class="panel"><h2>Digital World — nodes &amp; displays</h2>
    <p class="muted">{_ui.esc(world.get("honesty", ""))}</p>
    <p class="muted">Alleen kijken &amp; schuiven: selecteren en slepen gebeurt lokaal in je browser
    (UI-positie). Er gaat <b>geen enkele write</b> naar een node — geen remote control, geen configuratie.</p>
    <p class="flowline">
    <button type="button" id="dw-zin">Zoom +</button>
    <button type="button" id="dw-zout">Zoom −</button>
    <button type="button" id="dw-reset">Reset layout</button>
    <span class="muted" id="dw-count">{world.get("node_count", 0)} node(s) · {world.get("display_count", 0)} display(s)</span>
    </p>
    <svg id="dw-stage" class="world" viewBox="0 0 1000 420" role="application"
    aria-label="Digitale wereld: nodes en displays. Klik om te selecteren, sleep een display om de UI-positie te veranderen."></svg>
    <div id="dw-details" class="panel"><p class="muted">Selecteer een node of display hierboven voor details.</p></div>
    <h3>Gerapporteerde nodes (server-render, ook zonder JS)</h3>
    <div class="grove" id="dw-fallback">{fallback_html}</div>
    <script>const DWDATA = {snapshot};{DWORLD_JS}</script></div>"""


def _mesh_panel_html() -> str:
    """Node mesh: shared-capability map + safe delegation contract."""
    from . import ui as _ui
    try:
        from .nodemesh import mesh_topology
        topo = mesh_topology()
    except Exception:
        return ""
    nodes = topo.get("nodes", [])
    if not nodes:
        return ("<div class=\"panel\"><h2>Node mesh</h2>"
                "<p class=\"muted\">No nodes registered yet — the "
                "mesh grows when laptops join. Delegation contract: "
                "<a href=\"/api/v1/mesh/topology\">topology "
                "(JSON)</a>. Nodes never dial each other; every "
                "request goes node → coordinator → eligible "
                "node(s).</p></div>")
    edges = "".join(
        f"<li><small>{_ui.esc(edge['from'])} ↔ "
        f"{_ui.esc(edge['to'])} via coordinator "
        f"({ _ui.esc(', '.join(edge.get('shared', [])))})</small></li>"
        for edge in topo.get("edges", [])[:12])
    kinds = ", ".join(f"<code>{_ui.esc(kind)}</code>"
                      for kind in topo.get("allowed_kinds", []))
    return (
        f"<div class=\"panel\"><h2>Node mesh — safe remote help</h2>"
        f"<p class=\"muted\">Node A asks the coordinator, the "
        f"coordinator tasks an eligible Node B. No shell, no "
        f"wildcard, no direct control. Delegable kinds: {kinds}.</p>"
        f"<ul>{edges or '<li>No shared capabilities yet.</li>'}</ul>"
        f"<p class=\"muted\"><a href=\"/api/v1/mesh/topology\">"
        f"Topology (JSON)</a> · validate via "
        f"<code>POST /api/v1/mesh/validate</code> · dispatch via "
        f"the normal task queue.</p></div>")


def _workbench_models_html() -> str:
    """Model library: register + inspect + progress."""
    from . import ui as _ui
    try:
        from .workshop3d import list_models
        models = list_models(limit=12)
    except Exception:
        models = []
    cards = "".join(
        f"<div class=\"sprout\"><b>{_ui.esc(item['filename'][:50])}</b><br>"
        f"<code>{_ui.esc(item['model_id'][:20])}</code> "
        f"{_ui.chip(item.get('status', '?'))}<br>"
        f"<span class=\"muted\">mesh: "
        f"{_ui.esc(str(item.get('inspection', {}).get('mesh_verdict', 'UNKNOWN')))} · "
        f"{_ui.esc(str(item.get('size_bytes', 0)))} bytes</span><br>"
        f"<a href=\"/craft?entity_id={_ui.esc(item['model_id'])}\">Craft</a> · "
        f"<a href=\"/symbiosis?entity_id={_ui.esc(item['model_id'])}\">Symbiosis</a></div>"
        for item in models) or _ui.empty(
            "No models yet — copy an STL/OBJ into the fabrication dir, then register it.")
    progress = _ui.stage_progress(
        "Model library",
        [(f"{item['filename'][:40]}", item.get("status", "open"))
         for item in models[:8]]) if models else ""
    return (
        f"<div class=\"panel\"><h2>Models</h2>"
        f"<form method=\"post\" action=\"/web/workshop/models\">"
        f"<input type=\"text\" name=\"filename\" "
        f"placeholder=\"bracket.stl (already in fabrication dir)\" "
        f"style=\"width:50%\" aria-label=\"Model filename\">"
        f"<button type=\"submit\">Register + inspect</button></form>"
        f"<p class=\"muted\">STL/OBJ get geometric inspection; "
        f"3MF/GLB/GLTF register metadata-only (UNKNOWN). Same bytes "
        f"never register twice.</p>"
        f"<div class=\"grove\">{cards}</div>{progress}</div>")


def _workbench_materials_html() -> str:
    """Material library: known / candidate / unknown."""
    from . import ui as _ui
    try:
        from .workshop3d import list_materials
        materials = list_materials(limit=12)
    except Exception:
        materials = []
    cards = "".join(
        f"<div class=\"sprout\"><b>{_ui.esc(item['name'][:50])}</b><br>"
        f"{_ui.chip(item.get('kind', '?'))}"
        f"{_ui.chip(item.get('state', '?'))}<br>"
        f"<span class=\"muted\">{_ui.esc(item.get('notes', '')[:100])}</span></div>"
        for item in materials) or _ui.empty(
            "No materials yet — name what is on the shelf.")
    return (
        f"<div class=\"panel\"><h2>Materials</h2>"
        f"<form method=\"post\" action=\"/web/workshop/materials\">"
        f"<input type=\"text\" name=\"name\" placeholder=\"PLA green\" "
        f"style=\"width:30%\" aria-label=\"Material name\">"
        f"<select name=\"kind\" aria-label=\"Kind\">"
        f"<option value=\"filament\">filament</option>"
        f"<option value=\"resin\">resin</option>"
        f"<option value=\"fastener\">fastener</option>"
        f"<option value=\"electronics\">electronics</option>"
        f"<option value=\"other\">other</option></select>"
        f"<select name=\"state\" aria-label=\"State\">"
        f"<option value=\"known\">known</option>"
        f"<option value=\"candidate\">candidate</option>"
        f"<option value=\"unknown\">unknown</option></select>"
        f"<button type=\"submit\">Add material</button></form>"
        f"<p class=\"muted\">Sustainability notes are operator notes, "
        f"never verified claims.</p>"
        f"<div class=\"grove\">{cards}</div></div>")


def _workbench_fabjobs_html() -> str:
    """Fab jobs with honest stage chips + progress."""
    from . import ui as _ui
    try:
        from .workshop3d import list_fabjobs
        jobs = list_fabjobs(limit=10)
    except Exception:
        jobs = []
    cards = ""
    for job in jobs:
        actions = ""
        stage = job.get("stage", "")
        if stage == "designed":
            actions = _w3_action(job["job_id"], "prepare", "Prepare")
        elif stage == "prepared":
            actions = _w3_action(job["job_id"], "slice", "Slice (TEST)")
        elif stage == "gcode-ready":
            actions = _w3_action(job["job_id"], "propose",
                                 "Propose print (needs YES)")
        elif stage in ("proposed", "approved", "printing-simulated",
                       "printed-simulated"):
            actions = _w3_action(job["job_id"], "sync", "Sync")
        cards += (
            f"<div class=\"sprout\"><b>{_ui.esc(job['job_id'][:28])}</b><br>"
            f"{_ui.chip(stage)}"
            f"<span class=\"muted\">model "
            f"{_ui.esc(job.get('model_id', '')[:16])} · printer "
            f"{_ui.esc(job.get('printer_id', 'none'))}</span><br>"
            f"{actions}</div>")
    progress = _ui.stage_progress(
        "Fabrication",
        [(f"{job['job_id'][:24]}", job.get("stage", "open"))
         for job in jobs[:8]]) if jobs else ""
    return (
        f"<div class=\"panel\"><h2>Fabrication</h2>"
        f"<form method=\"post\" action=\"/web/workshop/fabjobs\">"
        f"<input type=\"text\" name=\"model_id\" placeholder=\"mdl_…\" "
        f"style=\"width:22%\" aria-label=\"Model id\">"
        f"<input type=\"text\" name=\"material_ref\" placeholder=\"material\" "
        f"style=\"width:18%\" aria-label=\"Material\">"
        f"<input type=\"text\" name=\"printer_id\" placeholder=\"prt_…\" "
        f"style=\"width:18%\" aria-label=\"Printer\">"
        f"<input type=\"text\" name=\"profile\" placeholder=\"profile\" "
        f"style=\"width:14%\" aria-label=\"Profile\">"
        f"<button type=\"submit\">Start fab job</button></form>"
        f"<p class=\"muted\">Execution only via "
        f"<a href=\"/writes\">Writes</a> exact YES; here you prepare, "
        f"slice (TEST), propose and sync honest stages.</p>"
        f"<div class=\"grove\">{cards or _ui.empty('No fab jobs yet.')}</div>"
        f"{progress}</div>")


def _w3_action(job_id: str, action: str, label: str) -> str:
    from . import ui as _ui
    return (
        f"<form method=\"post\" action=\"/web/workshop/fabjobs/"
        f"{_ui.esc(job_id)}/{action}\" style=\"display:inline\">"
        f"<button type=\"submit\">{_ui.esc(label)}</button></form>")


def _w3_printer_badge(printer_id: str) -> str:
    """Honest printer badge: SIMULATED, UNAVAILABLE (no adapter),
    or bare capabilities (registered, execution via YES flow)."""
    from . import ui as _ui
    if _printer_is_simulated(printer_id):
        return " " + _ui.chip("[SIMULATED]", "state-SIMULATED")
    try:
        from .printer3d import adapter_for_printer
        adapter = adapter_for_printer(printer_id)
    except (ValueError, AttributeError):
        adapter = None
    if adapter is None:
        return " " + _ui.chip("[UNAVAILABLE]", "state-UNAVAILABLE")
    return ""


def _workbench_machines_html() -> str:
    """Printers + mesh-capable nodes. Read-only."""
    from . import ui as _ui
    try:
        from .printer3d import list_stored_printers
        printers = list_stored_printers()
    except Exception:
        printers = []
    rows = "".join(
        f"<li><b>{_ui.esc(device.name)}</b> "
        f"({_ui.esc(device.printer_id)}) — "
        f"{_ui.esc(', '.join(device.capabilities))}"
        f"{_w3_printer_badge(device.printer_id)}</li>"
        for device in printers) or "<li>No printers</li>"
    mesh_nodes = ""
    try:
        from .nodemesh import mesh_topology
        topo = mesh_topology()
        capable = [node for node in topo.get("nodes", [])
                   if any("mesh" in cap or "cad" in cap or
                          "analysis" in cap
                          for cap in node.get("capabilities", []))]
        mesh_nodes = "".join(
            f"<li>{_ui.esc(node['node_id'])} — "
            f"{_ui.esc(', '.join(node.get('roles', [])))}</li>"
            for node in capable[:8]) or \
            "<li>No mesh-capable nodes</li>"
    except Exception:
        mesh_nodes = "<li>Mesh unavailable</li>"
    return (
        f"<div class=\"panel\"><h2>Machines</h2><ul>{rows}</ul>"
        f"<h3>Mesh-capable nodes</h3><ul>{mesh_nodes}</ul>"
        f"<p class=\"muted\">Nodes only run allowlisted "
        f"capabilities via <a href=\"/nodes\">task claims</a>; "
        f"no shell, no direct control.</p></div>")


@app.get("/3d", response_class=HTMLResponse)
def model_3d_page(entity_id: str = "") -> str:
    """3D workbench: models, materials, projects, fabrication,
    machines, observations, verification — one workshop, honest
    stage chips, no fake meshes, no fake prints."""
    from . import ui as _ui
    from .fab_flow import list_fabrications
    try:
        runs = list_fabrications(10)
    except Exception:
        runs = []
    rows = "".join(
        f"<li><a href=\"/workshop?fabrication_id={_ui.esc(record.fabrication_id)}\">{_ui.esc(record.fabrication_id)}</a> — {_ui.esc(record.status)}</li>"
        for record in runs) or "<li>No runs yet.</li>"
    related_html = ""
    presence_html = ""
    if entity_id.strip():
        import anyio as _anyio
        try:
            from .ecosystem import entity_context
            context = _anyio.run(
                entity_context, entity_id.strip()[:100], 1)
            links = "".join(
                f"<li><code>{_ui.esc(item['entity_id'][:40])}</code> "
                f"<span class=\"muted\">"
                f"{_ui.esc(item['predicate'])}</span></li>"
                for item in context.get("connected_to", [])[:12])
            empty_relations = (
                "<li>No stored relations yet - propose one "
                "below.</li>")
            related_html = (
                "<div class=\"panel\"><h2>Connected to "
                f"{_ui.esc(entity_id[:40])}</h2>"
                f"<ul>{links or empty_relations}</ul>"
                f"<p><a href=\"/world?entity_id="
                f"{_ui.esc(entity_id)}\">Open in world graph</a></p>"
                "</div>")
        except Exception:
            related_html = (
                "<div class=\"panel\"><p class=\"muted\">Relations "
                "unavailable right now.</p></div>")
        try:
            from .workshop3d import workshop_presence
            presence = workshop_presence(entity_id.strip()[:100])
            presence_html = _ui.stage_progress(
                f"Workshop presence — {entity_id.strip()[:40]}",
                [(label, "completed" if present else "open")
                 for label, present in presence["checklist"]])
        except Exception:
            presence_html = ""
    main = f"""<h1>3D Workbench — from idea to verified object</h1>
    <p class="muted">One workbench: models, materials, projects, fabrication, machines, observations, verification. Every stage REAL / TEST / SIMULATED / UNAVAILABLE, labeled.</p>
    <div class="panel"><div class="path" aria-label="3D pipeline">
    <span class="step done">PHOTO / OBJECT</span><span class="arrow">→</span>
    <span class="step done">OBSERVATION</span><span class="arrow">→</span>
    <span class="step">3D MODEL CANDIDATE</span><span class="arrow">→</span>
    <span class="step">MODEL</span><span class="arrow">→</span>
    <span class="step">PREPARE</span><span class="arrow">→</span>
    <span class="step">SLICE</span><span class="arrow">→</span>
    <span class="step">G-CODE</span><span class="arrow">→</span>
    <span class="step">PRINTER</span><span class="arrow">→</span>
    <span class="step">VERIFY</span></div>
    <p class="muted">Stages: READY / WAITING / SIMULATED / TEST / HARDWARE_REQUIRED / UNAVAILABLE. OBJECT → CREATE 3D MODEL uses the existing procedural/test workflow; true reconstruction transport is UNAVAILABLE and says so. No fake generated mesh. Prints need exact YES in <a href="/writes">Writes</a>; SIMULATED execution never becomes REAL.</p></div>
    {_workbench_models_html()}
    {_workbench_materials_html()}
    {presence_html}
    {_workbench_fabjobs_html()}
    {_workbench_machines_html()}
    """ + related_html + f"""
    <div class="panel"><h2>Connect a model</h2>
    <p class="muted">Link a model, material or fab job to a project, object, idea or machine — as a PROPOSED symbiosis first. Example: model <code>mdl_…</code> <code>used_in</code> project <code>proj_…</code>.</p>
    <form method="post" action="/web/workshop/links">
    <input type="text" name="workshop_id" placeholder="mdl_… / mat_… / fabjob_…" style="width:24%" aria-label="Workshop record">
    <select name="predicate" aria-label="Predicate"><option value="used_in">used_in</option><option value="represents">represents</option><option value="requires">requires</option><option value="generated_from">generated_from</option><option value="fabricated_by">fabricated_by</option><option value="replacement_for">replacement_for</option><option value="compatible_with">compatible_with</option><option value="verified_by">verified_by</option><option value="part_of">part_of</option><option value="related_to">related_to</option></select>
    <input type="text" name="entity_id" placeholder="to: proj_… / obj_…" style="width:24%" aria-label="To entity">
    <button type="submit">Propose link</button></form>
    <p class="muted">Prefer <a href="/writes">Writes</a> for direct INVENTory relations (<code>used_in</code>, <code>part_of</code>, <code>produced_by</code>, <code>related_to</code>, <code>depends_on</code>).</p></div>
    <div class="filament" aria-hidden="true"></div>
    <div class="panel"><h2>Workspace</h2><p><a href="/workshop/3d">Open 3D workshop</a> · <a href="/fabrication">Fabrication</a> · <a href="/workshop">Chain view</a> · <a href="/api/v1/workshop/packet">continuation packet (JSON)</a></p>
    <p><form method="get" action="/3d" aria-label="Related relations"><input type="text" name="entity_id" placeholder="mod_… / file_… / proj_…" value="{_ui.esc(entity_id)}" style="width:40%" aria-label="Entity"> <button type="submit">Show relations</button></form></p></div>
    <div class="panel"><h2>Recent runs</h2><ul>{rows}</ul></div>"""
    return _ui.shell("3D", "/workshop/3d", _ui.living_bg() + main,
                     _ui.command_bar())


# =============================================================================
# BIG #31 — ACTIVATION. Context engine, living state, global search,
# packet v2 handoff, command traces. All reads bounded; no new truth
# stores; mutations stay behind existing gates.
# =============================================================================


@app.get("/api/v1/state")
def api_living_state() -> dict:
    from .living_state import current_state
    return current_state()


@app.get("/api/v1/context/compose")
def api_context_compose(intent: str = "", project_id: str = "",
                        conversation_id: str = "",
                        include_health: str = "") -> dict:
    from .context_engine import compose
    return compose(intent[:500], project_id=project_id[:80],
                   conversation_id=conversation_id[:80],
                   include_health=include_health.lower() == "true")


@app.get("/api/v1/context/packet2")
def api_context_packet_v2(task: str = "", intent: str = "",
                          project_id: str = "",
                          conversation_id: str = "",
                          include_health: str = "",
                          format: str = "json"):
    from .context_packet import (build_packet_v2,
                                 render_packet_v2_markdown)
    packet = build_packet_v2(
        task=task[:500], intent=intent[:500],
        project_id=project_id[:80],
        conversation_id=conversation_id[:80],
        include_health=include_health.lower() == "true")
    if format.lower() == "markdown":
        return Response(content=render_packet_v2_markdown(packet),
                        media_type="text/markdown; charset=utf-8")
    return packet


@app.get("/api/v1/context/packet.md")
def api_context_packet_markdown(task: str = "", intent: str = "",
                               project_id: str = "",
                               conversation_id: str = "") -> Response:
    from .context_packet import (build_packet_v2,
                                 render_packet_v2_markdown)
    packet = build_packet_v2(
        task=task[:500], intent=intent[:500],
        project_id=project_id[:80],
        conversation_id=conversation_id[:80])
    return Response(
        content=render_packet_v2_markdown(packet),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition":
                 "attachment; filename=\"mycelium-context.md\""})


@app.get("/api/v1/command/traces")
def api_command_traces(limit: int = 5) -> dict:
    from .context_engine import recent_traces
    return {"traces": recent_traces(limit=limit)}


@app.get("/api/v1/search")
def api_global_search(query: str = "", limit: int = 10) -> dict:
    """Global search across inventory, memory, conversations,
    missions, research, nodes. Bounded, provenance-aware."""
    from .context_engine import compose
    cleaned = str(query or "").strip()[:200]
    if not cleaned:
        raise HTTPException(status_code=422,
                            detail="A query is required")
    context = compose(cleaned, limit_per_section=max(
        1, min(int(limit or 10), 15)))
    return {"query": cleaned, "engine": context["engine"],
            "sections": context["sections"],
            "total_items": context["total_items"]}


@app.get("/search", response_class=HTMLResponse)
def search_page(query: str = "") -> str:
    """One search across the whole ecosystem: projects, ideas,
    objects, memories, conversations, missions, research, nodes."""
    from . import ui as _ui
    results_html = ""
    if query.strip():
        from .context_engine import compose
        context = compose(query.strip()[:200], limit_per_section=6)
        blocks = []
        for section, items in context["sections"].items():
            if not items:
                continue
            rows = "".join(
                f"<li><b>{_ui.esc(item['title'][:100])}</b> "
                f"<span class=\"muted\">[{_ui.esc(item['source'])}] "
                f"{_ui.esc(item['why'][:100])}</span><br>"
                f"<small>{_ui.esc(item['snippet'][:160])}</small></li>"
                for item in items)
            blocks.append(
                f"<div class=\"panel\"><h2>{_ui.esc(section)}</h2>"
                f"<ul>{rows}</ul></div>")
        results_html = "".join(blocks) or _ui.empty(
            "Nothing found — try fewer or different words.")
    main = f"""<h1>Search the ecosystem</h1>
    <div class="panel"><form method="get" action="/search" role="search" aria-label="Global search">
    <input type="text" name="query" placeholder="camper solar…" value="{_ui.esc(query[:200])}" style="width:70%" aria-label="Query" autocomplete="off">
    <button type="submit">Search</button></form>
    <p class="muted">Inventory + memory + conversations + missions + research + nodes + agenda. Bounded, with provenance — never a dump.</p></div>
    {results_html}"""
    return _ui.shell("Search", "/world", main, _ui.command_bar())


# =============================================================================
# BIG #31 — PHASE D/F. Camera detail + file ingest, writes inbox +
# propose-link, archaeology depth, node roles, overnight mode +
# research queue. Reads bounded; writes only via existing gates.
# =============================================================================


def _node_role_list(record: dict) -> list[str]:
    from .ecosystem import node_roles
    try:
        return node_roles(record)
    except Exception:
        return ["GENERAL"]


def _routing_answer_html(check_cap: str) -> str:
    """Deterministic routing answer: which online nodes carry one
    capability. Read-only dry-run, same rules as task assignment."""
    from . import ui as _ui
    wanted = str(check_cap or "").strip()[:80]
    if not wanted:
        return "<p class=\"muted\">Ask for a capability, e.g. "
        "<code>research.fetch</code> — Mycelium answers from live "
        "registrations, never guesses.</p>"
    eligible = eligible_nodes_for(wanted)
    if not eligible:
        return (f"<p>“{_ui.esc(wanted)}”: <b>WAITING_FOR_AGENT</b> — "
                "no online node advertises this. Add a Linux node or "
                "let the coordinator handle it.</p>")
    rows = "".join(
        f"<li><b>{_ui.esc(entry['node_id'])}</b> "
        f"<span class=\"muted\">[{_ui.esc(entry['status'])} · "
        f"{_ui.esc(entry['tier'])}]</span></li>"
        for entry in eligible)
    return (f"<p>“{_ui.esc(wanted)}” → {len(eligible)} eligible "
            f"node(s):</p><ul>{rows}</ul>")


@app.get("/api/v1/node-roles")
def api_node_roles() -> dict:
    return {"roles": {record["node_id"]: _node_role_list(record)
                      for record in list_nodes()}}


@app.get("/api/v1/mode")
def api_mode_get() -> dict:
    from .context_engine import get_mode
    return get_mode()


@app.post("/api/v1/mode")
def api_mode_set(body: dict) -> dict:
    from .context_engine import set_mode
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    try:
        return set_mode(str(body.get("mode", "")),
                        str(body.get("detail", "")))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/web/mode")
async def web_mode(request: Request) -> Response:
    from .context_engine import set_mode
    fields = await _form_fields(request)
    try:
        set_mode(fields.get("mode", ""),
                 fields.get("detail", "")[:300])
    except ValueError:
        pass
    return RedirectResponse("/morning", status_code=303)


@app.get("/api/v1/discoveries")
def api_discoveries(limit: int = 20) -> dict:
    from .ecosystem import discoveries
    return discoveries(limit=limit)


@app.get("/api/v1/imports-compare")
def api_imports_compare(limit: int = 10) -> dict:
    from .conversation_bridge import compare_imports
    return compare_imports(limit=limit)


@app.get("/api/v1/conversation-imports/{conversation_id}/markdown")
def api_import_markdown(conversation_id: str) -> Response:
    from .conversation_bridge import (BridgeRefusedError,
                                      render_import_markdown)
    try:
        text = render_import_markdown(conversation_id)
    except BridgeRefusedError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return Response(
        content=text, media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition":
                 f"attachment; filename=\"{conversation_id}.md\""})


@app.get("/api/v1/conversation-imports/{conversation_id}/relevance")
async def api_import_relevance(conversation_id: str) -> dict:
    """Which existing INVENTory records are relevant to this import?
    Read-only bridge search over finding keywords; candidates only."""
    from .conversation_bridge import (get_import, load_analysis)
    meta = get_import(conversation_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Unknown import")
    analysis = load_analysis(conversation_id) or {}
    keywords: list[str] = []
    for item in analysis.get("findings", [])[:12]:
        for word in str(item.get("text", "")).split():
            cleaned = "".join(char for char in word if char.isalnum())
            if len(cleaned) >= 4 and cleaned.lower() not in keywords:
                keywords.append(cleaned.lower())
            if len(keywords) >= 8:
                break
    query = " ".join(keywords[:8]) or meta.get("title", "")
    candidates: list[dict] = []
    error = ""
    try:
        records, inventory_error, _ = await _chat_world_context(
            query[:200])
        for record in records[:10]:
            candidates.append({
                "entity_type": record["entity_type"],
                "entity_id": record["entity_id"],
                "title": record["title"],
                "state": "CANDIDATE",
                "why": "keyword overlap with import findings",
                "link": f"/world?entity_id={record['entity_id']}",
            })
        if inventory_error:
            error = inventory_error
    except HTTPException as exc:
        error = str(exc.detail)
    return {"conversation_id": conversation_id, "query": query,
            "candidates": candidates, "inventory_error": error,
            "note": "Candidates link existing records; creating new "
                    "relations needs a write proposal + YES."}


@app.get("/cameras/{device_id}", response_class=HTMLResponse)
def camera_detail_page(device_id: str):
    """One camera: identity, source, connection state, capabilities,
    last observation, media inbox, available actions. Honest states."""
    from . import ui as _ui
    device = get_device(device_id)
    if device is None:
        return HTMLResponse("Camera not found", status_code=404)
    from .vision_ingest import list_inbox_files, probe_availability
    from .vision_ingest import adapter_for as _adapter_for
    try:
        availability = probe_availability(
            device, _adapter_for(device_id))
    except Exception as exc:
        availability = {"state": "unknown", "capturable": False,
                        "reason": str(exc)[:200]}
    latest = list_observations(device.device_id, limit=5)
    obs_rows = "".join(
        f"<li><code>{_ui.esc(obs.observation_id)}</code> "
        f"<span class=\"muted\">{_ui.esc(obs.created_at[:16])} · "
        f"{_ui.esc(obs.media_ref or 'no media')}</span><br>"
        f"<form method=\"post\" action=\"/web/observations/"
        f"{_ui.esc(obs.observation_id)}/candidate\" "
        f"style=\"display:inline\">"
        f"<button type=\"submit\">Review as candidate</button></form> "
        f"<form method=\"post\" action=\"/web/observations/"
        f"{_ui.esc(obs.observation_id)}/describe\" "
        f"style=\"display:inline\">"
        f"<input type=\"hidden\" name=\"device_id\" value=\""
        f"{_ui.esc(device.device_id)}\">"
        f"<button type=\"submit\">Describe (VLM)</button></form> "
        f"<form method=\"post\" action=\"/web/observations/"
        f"{_ui.esc(obs.observation_id)}/propose-candidates\" "
        f"style=\"display:inline\">"
        f"<input type=\"hidden\" name=\"device_id\" value=\""
        f"{_ui.esc(device.device_id)}\">"
        f"<button type=\"submit\">Propose candidates</button></form></li>"
        for obs in latest) or "<li>No observations yet.</li>"
    inbox = "".join(
        f"<li><code>{_ui.esc(entry['filename'])}</code> "
        f"<span class=\"muted\">{entry['size_bytes']} bytes · "
        f"{_ui.esc(entry['origin'])}</span></li>"
        for entry in list_inbox_files(limit=30)) or \
        "<li>Inbox empty — copy Insta360/phone files into the camera dir.</li>"
    main = f"""<h1>{_ui.esc(device.name)}</h1>
    <p class="muted"><code>{_ui.esc(device.device_id)}</code> · source {_ui.esc(device.source)} · kinds {_ui.esc(', '.join(device.kinds))}</p>
    <div class="panel"><h2>Connection</h2>
    <p>State: <b>{_ui.esc(str(availability.get('state', '?')).upper())}</b> · capturable: <b>{_ui.esc(str(availability.get('capturable', False)))}</b></p>
    <p class="muted">{_ui.esc(str(availability.get('reason', ''))[:300])}</p>
    <p class="muted">Direct Insta360 transport: UNAVAILABLE. File ingest below is REAL.</p></div>
    <div class="panel"><h2>Observe via file ingest</h2>
    <p class="muted">FILE → OBSERVATION → ANALYSIS → CANDIDATE → HUMAN REVIEW → INVENTORY. Pick a file from the inbox; ingest creates an observation + inert File payload (registration still needs approval).</p>
    <form method="post" action="/web/cameras/{_ui.esc(device.device_id)}/ingest-file">
    <input type="text" name="filename" placeholder="IMG_0001.png" style="width:50%" aria-label="Inbox filename" autocomplete="off">
    <button type="submit">Ingest file</button></form></div>
    <div class="panel"><h2>Multi-file ingest session</h2>
    <p class="muted">Up to 8 inbox files per session (space/comma separated). Dedupe by content hash; replays refuse as duplicates.</p>
    <form method="post" action="/web/camera-sessions">
    <input type="hidden" name="device_id" value="{_ui.esc(device.device_id)}">
    <input type="text" name="filenames" placeholder="IMG_0001.png IMG_0002.png" style="width:50%" aria-label="Inbox filenames" autocomplete="off">
    <button type="submit">Ingest session</button></form>
    {_camera_sessions_html(device.device_id)}</div>
    <div class="panel"><h2>Media inbox</h2><ul>{inbox}</ul></div>
    <div class="panel"><h2>Observations</h2><ul>{obs_rows}</ul>
    <p><a href="/api/v1/cameras/{_ui.esc(device.device_id)}/observations">observations (JSON)</a> · <a href="/api/v1/cameras/{_ui.esc(device.device_id)}/availability">availability (JSON)</a></p></div>
    <div class="panel"><h2>Suggest a link</h2>
    <p class="muted">Propose observation → entity as PROPOSED symbiosis. YES/NO/REVIEW run through <a href="/knowledge">Knowledge</a>.</p>
    <form method="post" action="/web/camera-suggest-link">
    <input type="hidden" name="device_id" value="{_ui.esc(device.device_id)}">
    <input type="text" name="observation_id" placeholder="obs-…" style="width:24%" aria-label="Observation id">
    <select name="predicate" aria-label="Predicate"><option value="related_to">related_to</option><option value="used_in">used_in</option><option value="component_of">component_of</option><option value="stored_at">stored_at</option><option value="supports">supports</option><option value="evidence_for">evidence_for</option><option value="part_of">part_of</option></select>
    <input type="text" name="entity_id" placeholder="proj_… / obj_…" style="width:24%" aria-label="Entity id">
    <button type="submit">Propose link</button></form></div>
    {_camera_timeline_html(device.device_id)}"""
    return _ui.shell(device.name, "/cameras", main, _ui.command_bar())


def _camera_sessions_html(device_id: str) -> str:
    """Recent ingest sessions for one camera (bounded)."""
    from . import ui as _ui
    try:
        from .camera_ecosystem import list_sessions
        sessions = list_sessions(device_id, limit=5)
    except Exception:
        return ""
    rows = "".join(
        f"<li><code>{_ui.esc(session.session_id)}</code> "
        f"<span class=\"muted\">[{_ui.esc(session.state)}] "
        f"{len(session.items)} file(s) · "
        f"{_ui.esc(session.created_at[:16])}</span> "
        f"<a href=\"/api/v1/camera-sessions/"
        f"{_ui.esc(session.session_id)}\">session (JSON)</a></li>"
        for session in sessions)
    return f"<ul>{rows or '<li>No sessions yet.</li>'}</ul>"


def _camera_timeline_html(device_id: str) -> str:
    """Timeline from the shared bus (no second event system)."""
    from . import ui as _ui
    try:
        from .camera_ecosystem import timeline
        items = timeline(device_id=device_id, limit=12)
    except Exception:
        items = []
    rows = "".join(
        f"<li><span class=\"muted\">"
        f"{_ui.esc(str(item.get('at', ''))[:16])}</span> "
        f"<b>{_ui.esc(str(item.get('type', '')))}</b> — "
        f"{_ui.esc(str(item.get('text', ''))[:140])}</li>"
        for item in items)
    return (f"<div class=\"panel\"><h2>Timeline</h2>"
            f"<ul class=\"timeline\">"
            f"{rows or '<li>Nothing happened yet for this camera.</li>'}"
            f"</ul></div>")


@app.get("/api/v1/camera-inbox")
def api_camera_inbox(limit: int = 100) -> dict:
    from .vision_ingest import list_inbox_files
    return {"inbox": list_inbox_files(limit=limit)}


@app.get("/api/v1/inbox/{filename}/facts")
def api_inbox_facts(filename: str, device_id: str = "",
                    name: str = "") -> dict:
    """Read-only media facts + inert file payload for one inbox
    file. Delegates to existing media_facts/file_payload_for; every
    boundary refuses with 422. No writes, no database, no pixels."""
    from .vision_ingest import (IngestRefusedError, file_payload_for,
                                media_facts)
    try:
        media = media_facts(filename)
    except IngestRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    try:
        payload = file_payload_for(
            media, name.strip() or media.media_ref,
            device_id.strip()[:80])
    except IngestRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"media": media.model_dump(mode="json"),
            "file_payload": payload}


@app.post("/api/v1/cameras/{device_id}/ingest-file", status_code=201)
def camera_ingest_file(device_id: str, body: dict) -> dict:
    """Ingest one inbox file as an observation (REAL file-mode).
    Filename only; traversal and missing files refuse."""
    from .vision_ingest import (FileIngestAdapter, IngestRefusedError,
                                ingest_snapshot)
    device = get_device(device_id)
    if device is None:
        raise HTTPException(404, "Camera not found")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    try:
        adapter = FileIngestAdapter(str(body.get("filename", "")))
        result = ingest_snapshot(device, adapter)
    except IngestRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except CameraUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error))
    save_observation(result.observation)
    emit_event("observation.created",
               f"File ingest {result.observation.observation_id} "
               f"via {device_id}", node_id=device_id)
    return result.model_dump(mode="json")


@app.post("/api/v1/cameras/{device_id}/poll-inbox")
def camera_poll_inbox(device_id: str) -> dict:
    """Explicit operator/n8n poll: inbox files → session →
    observation → VLM → candidates. Synchronous; no scheduler,
    thread or daemon (see jobs.py). Thin delegation; the work
    lives in camera_ecosystem.poll_inbox. No INVENTory writes."""
    from .camera_ecosystem import EcosystemRefusedError, poll_inbox
    if get_device(device_id) is None:
        raise HTTPException(404, "Camera not found")
    try:
        return poll_inbox(device_id)
    except EcosystemRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/web/cameras/{device_id}/ingest-file")
async def web_camera_ingest_file(device_id: str,
                                 request: Request) -> Response:
    from .vision_ingest import (FileIngestAdapter, IngestRefusedError,
                                ingest_snapshot)
    fields = await _form_fields(request)
    device = get_device(device_id)
    if device is None:
        return RedirectResponse("/cameras", status_code=303)
    try:
        adapter = FileIngestAdapter(fields.get("filename", ""))
        result = ingest_snapshot(device, adapter)
    except (IngestRefusedError, CameraUnavailable):
        return RedirectResponse(f"/cameras/{device_id}",
                                status_code=303)
    save_observation(result.observation)
    emit_event("observation.created",
               f"File ingest {result.observation.observation_id} "
               f"via {device_id}", node_id=device_id)
    return RedirectResponse(f"/cameras/{device_id}", status_code=303)


@app.post("/web/observations/{observation_id}/candidate")
async def web_observation_to_candidate(observation_id: str,
                                       request: Request) -> Response:
    from .events import new_event as _bus_new, \
        save_event as _bus_save
    from .inventory_read import Provenance
    from .knowledge import (CandidateRefusedError, new_candidate,
                            save_candidate)
    fields = await _form_fields(request)
    observation = _observation_load(observation_id)
    if observation is None:
        return RedirectResponse("/cameras", status_code=303)
    try:
        entry = new_candidate(
            f"observation {observation_id}: "
            f"{observation.media_ref or 'capture'}",
            "observation",
            summary=fields.get("summary", "")[:1000] or
            f"Camera {observation.device_id} saw "
            f"{observation.media_ref or 'something'}; needs human "
            "review before it means anything.",
            state="observation",
            provenance=Provenance(
                source_type="sensor-observed",
                creator_id=f"camera:{observation.device_id}",
                human_verified=False),
            source_refs=[{"kind": "observation",
                          "id": observation_id,
                          "label": observation.media_ref or ""}],
            evidence=[{"text": f"media {observation.media_ref}",
                       "source": observation.device_id}])
        save_candidate(entry)
        _bus_save(_bus_new(
            "candidate.observed",
            f"Candidate {entry.candidate_id} from observation "
            f"{observation_id}"))
    except CandidateRefusedError:
        pass
    return RedirectResponse(
        f"/cameras/{observation.device_id}", status_code=303)


def _write_list(limit: int = 50) -> list[dict]:
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute(
            "SELECT proposal_id, status, created_at FROM write_proposals "
            "ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit or 50), 100)),)).fetchall()
    out = []
    for row in rows:
        record = _write_load(row["proposal_id"])
        summary = ""
        try:
            proposal = record.get("record", {}) if record else {}
            summary = str(proposal.get("mutation_type", ""))
        except (AttributeError, TypeError):
            summary = ""
        out.append({"proposal_id": row["proposal_id"],
                    "status": row["status"],
                    "created_at": row["created_at"], "summary": summary})
    return out


@app.get("/writes", response_class=HTMLResponse)
def writes_page() -> str:
    """Write-proposal inbox: propose links/objects, approve with
    exact YES. Approval ≠ verification; execution + verification
    stay separate steps."""
    from . import ui as _ui
    from .inventory_writes import RELATIONSHIP_PREDICATES
    rows = "".join(
        f"<tr><td><code>{_ui.esc(item['proposal_id'])}</code></td>"
        f"<td>{_ui.esc(item['summary'])}</td>"
        f"<td>{_ui.status_dot(item['status'])}"
        f"{_ui.esc(item['status'])}</td>"
        f"<td class=\"muted\">{_ui.esc(item['created_at'][:16])}</td>"
        f"<td><form method=\"post\" action=\"/web/writes/"
        f"{_ui.esc(item['proposal_id'])}/approve\">"
        f"<input type=\"text\" name=\"response\" placeholder=\"YES\" "
        f"style=\"width:4rem\" aria-label=\"Exact YES\">"
        f"<button type=\"submit\">Decide</button></form>"
        f"<form method=\"post\" action=\"/web/writes/"
        f"{_ui.esc(item['proposal_id'])}/execute\" "
        f"style=\"display:inline\">"
        f"<button type=\"submit\">Execute</button></form>"
        f"<form method=\"post\" action=\"/web/writes/"
        f"{_ui.esc(item['proposal_id'])}/verify\" "
        f"style=\"display:inline\">"
        f"<button type=\"submit\">Verify</button></form></td></tr>"
        for item in _write_list(limit=50)) or \
        "<tr><td colspan='5'>No proposals yet.</td></tr>"
    predicates = "".join(
        f"<option value='{_ui.esc(name)}'>{_ui.esc(name)}</option>"
        for name in sorted(RELATIONSHIP_PREDICATES))
    main = f"""<h1>Writes — propose, then YES</h1>
    <p class="muted">Every mutation is a proposal first. Exact <code>YES</code> approves; anything else refuses. Execution and independent verification happen afterwards — approval is permission, verification is truth.</p>
    <div class="panel"><h2>Propose a link (3D ↔ project ↔ object ↔ …)</h2>
    <form method="post" action="/web/links/propose">
    <input type="text" name="from_id" placeholder="from: obj_… / proj_… / file_…" style="width:28%" aria-label="From entity">
    <select name="predicate" aria-label="Predicate">{predicates}</select>
    <input type="text" name="to_id" placeholder="to: proj_… / obj_…" style="width:28%" aria-label="To entity">
    <button type="submit">Propose link</button></form>
    <p class="muted">Closed predicates only; endpoints must be known <code>xxx_</code> IDs. The proposal waits here for your YES.</p></div>
    <div class="panel"><h2>Propose an object (e.g. from mobile)</h2>
    <form method="post" action="/web/objects/propose">
    <input type="text" name="name" placeholder="Name, e.g. Camper accu" style="width:40%" aria-label="Object name">
    <input type="text" name="description" placeholder="Description (optional)" style="width:40%" aria-label="Description">
    <button type="submit">Propose object</button></form></div>
    <div class="panel"><h2>Inbox</h2><table><tr><th>Proposal</th><th>Mutation</th><th>Status</th><th>When</th><th>Decide</th></tr>{rows}</table></div>"""
    return _ui.shell("Writes", "/writes", main, _ui.command_bar())


@app.post("/web/links/propose")
async def web_link_propose(request: Request) -> Response:
    import secrets as _secrets
    from .inventory_writes import (InventoryWriteRefusedError,
                                   propose_inventory_write)
    fields = await _form_fields(request)
    try:
        proposal = propose_inventory_write(
            f"wrt-{_secrets.token_hex(4)}", "create_relationship", "",
            {"from_id": fields.get("from_id", "").strip(),
             "predicate": fields.get("predicate", "").strip(),
             "to_id": fields.get("to_id", "").strip(),
             "metadata": {"via": "link-proposal-form"},
             "provenance": {"creator_id": "link-proposal-form"}},
            actor="web")
    except (InventoryWriteRefusedError, ValueError):
        return RedirectResponse("/writes", status_code=303)
    _write_save(proposal, "proposed")
    return RedirectResponse("/writes", status_code=303)


@app.post("/web/objects/propose")
async def web_object_propose(request: Request) -> Response:
    import secrets as _secrets
    from .inventory_writes import (InventoryWriteRefusedError,
                                   propose_inventory_write)
    fields = await _form_fields(request)
    name = fields.get("name", "").strip()
    if not name:
        return RedirectResponse("/writes", status_code=303)
    try:
        proposal = propose_inventory_write(
            f"wrt-{_secrets.token_hex(4)}", "create", "object",
            {"name": name[:200],
             "description": fields.get("description", "")[:1000],
             "provenance": {"creator_id": "object-proposal-form"}},
            actor="web")
    except (InventoryWriteRefusedError, ValueError):
        return RedirectResponse("/writes", status_code=303)
    _write_save(proposal, "proposed")
    return RedirectResponse("/writes", status_code=303)


@app.post("/web/writes/{proposal_id}/approve")
async def web_write_approve(proposal_id: str,
                            request: Request) -> Response:
    from .controlled_writes import decide_write, request_write_approval
    from .controlled_writes import WriteProposal as _WriteProposal
    fields = await _form_fields(request)
    record = _write_load(proposal_id)
    if record is None or record["status"] != "proposed":
        return RedirectResponse("/writes", status_code=303)
    try:
        proposal = _WriteProposal.model_validate(record["record"])
        approval_request = request_write_approval(proposal)
        approval = decide_write(
            approval_request, proposal,
            fields.get("response", ""), decided_by="web")
    except ValueError:
        return RedirectResponse("/writes", status_code=303)
    status = "approved" if approval.approved else "rejected"
    _write_save(proposal, status, approval=approval)
    return RedirectResponse("/writes", status_code=303)


@app.post("/web/writes/{proposal_id}/execute")
async def web_write_execute(proposal_id: str) -> Response:
    """Smallest UI bridge onto POST /api/v1/writes/{id}/execute:
    same gates (approved-only, revalidated allow-list), no approval
    here. Gate refusals (404/409/422/502) redirect back; the reloaded
    inbox shows the unchanged status."""
    from fastapi import HTTPException as _HTTPException
    try:
        await write_execute(proposal_id)
    except _HTTPException:
        pass
    return RedirectResponse("/writes", status_code=303)


@app.post("/web/writes/{proposal_id}/verify")
async def web_write_verify(proposal_id: str) -> Response:
    """Smallest UI bridge onto POST /api/v1/writes/{id}/verify:
    independent readback, never the result payload. Same gates."""
    from fastapi import HTTPException as _HTTPException
    try:
        await write_verify(proposal_id)
    except _HTTPException:
        pass
    return RedirectResponse("/writes", status_code=303)


# -- overnight research queue --------------------------------------------------

QUEUE_PRIORITIES = ("HIGH", "MEDIUM", "LOW")


def _queue_list(limit: int = 50) -> list[dict]:
    from .research_engine import list_runs
    drafts = [run for run in list_runs(limit=200)
              if run.status in ("draft", "blocked", "failed")]
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    drafts.sort(key=lambda run: (
        order.get(str((run.metadata or {}).get("priority", "MEDIUM")),
                  1), run.created_at))
    return [{"run_id": run.run_id, "question": run.question,
             "status": run.status,
             "priority": str((run.metadata or {}).get(
                 "priority", "MEDIUM")),
             "created_at": run.created_at,
             "dossier_id": run.dossier_id}
            for run in drafts[: max(1, min(int(limit or 50), 100))]]


@app.post("/web/research/queue")
async def web_research_queue_add(request: Request) -> Response:
    fields = await _form_fields(request)
    question = fields.get("question", "").strip()
    if not question:
        return RedirectResponse("/research", status_code=303)
    from .research_engine import new_run, save_run
    try:
        run = new_run(question[:500], requested_by="mobile",
                      metadata={"priority": "MEDIUM",
                                "provider": "wikipedia",
                                "max_sources": 6,
                                "route": "local"})
        save_run(run)
    except ValueError:
        pass
    return RedirectResponse("/research", status_code=303)


@app.get("/api/v1/research/queue")
def api_research_queue(limit: int = 50) -> dict:
    from .context_engine import get_mode
    return {"mode": get_mode(), "queued": _queue_list(limit=limit)}


@app.post("/api/v1/research/queue", status_code=201)
def api_research_queue_add(body: dict) -> dict:
    from .research_engine import new_run, save_run
    from .research_transport import (TransportRefusedError,
                                     validate_url)
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    question = str(body.get("question", "")).strip()
    if not question:
        raise HTTPException(status_code=422, detail="question required")
    priority = str(body.get("priority", "MEDIUM")).strip().upper()
    if priority not in QUEUE_PRIORITIES:
        raise HTTPException(
            status_code=422,
            detail=f"priority must be one of {list(QUEUE_PRIORITIES)}")
    route = str(body.get("route", "local")).strip().lower()
    if route not in ("local", "node-first"):
        raise HTTPException(
            status_code=422,
            detail="route must be local or node-first")
    seed_urls: list[str] = []
    for raw in (body.get("seed_urls", []) or [])[:3]:
        try:
            seed_urls.append(validate_url(str(raw)))
        except TransportRefusedError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    try:
        run = new_run(
            question[:500],
            objective=str(body.get("objective", ""))[:500],
            project_ref=str(body.get("project_ref", ""))[:100],
            requested_by="queue",
            metadata={"priority": priority,
                      "provider": str(body.get("provider",
                                               "wikipedia"))[:20],
                      "max_sources": max(1, min(int(body.get(
                          "max_sources", 6)), 10)),
                      "route": route, "seed_urls": seed_urls})
        save_run(run)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        from .events import new_event as _bus_new, \
            save_event as _bus_save
        _bus_save(_bus_new(
            "research.queued",
            f"Queued {run.run_id} [{priority}/{route}]: "
            f"{question[:120]}"))
    except Exception:
        pass
    return {"run_id": run.run_id, "priority": priority,
            "status": run.status, "route": route,
            "seed_urls": seed_urls}


@app.post("/api/v1/research/queue/run-once")
async def api_research_queue_run_once() -> dict:
    """Execute the top queued draft once, bounded. Manual or
    scheduler-triggered (n8n cron); never a background thread.
    route=node-first with seed URLs routes validated fetches to
    eligible nodes (pull-only); otherwise the coordinator fetches
    locally. Physical steps stay behind existing gates."""
    queued = _queue_list(limit=1)
    if not queued:
        return {"ran": False, "reason": "queue empty"}
    top = queued[0]
    from .research_engine import load_run
    run = load_run(top["run_id"])
    if run is None:
        raise HTTPException(status_code=404, detail="Run vanished")
    metadata = run.metadata or {}
    if str(metadata.get("route", "local")) == "node-first" and \
            metadata.get("seed_urls"):
        return _route_run_to_nodes(run)
    if not queued:
        return {"ran": False, "reason": "queue empty"}
    top = queued[0]
    from .research_engine import load_run
    run = load_run(top["run_id"])
    if run is None:
        raise HTTPException(status_code=404, detail="Run vanished")
    metadata = run.metadata or {}
    provider_name = str(metadata.get("provider", "wikipedia"))
    max_sources = max(1, min(int(metadata.get("max_sources", 6)), 10))
    try:
        provider = _research_provider(provider_name, None)
    except HTTPException as exc:
        return {"ran": False, "run_id": run.run_id,
                "reason": str(exc.detail)}
    try:
        finished = await _execute_research_run(
            run.run_id, provider, max_sources)
    except HTTPException as exc:
        return {"ran": False, "run_id": run.run_id,
                "reason": str(exc.detail)}
    return {"ran": True, "run_id": run.run_id,
            "dossier_id": finished.get("dossier_id", "")}


def eligible_nodes_for(capability: str) -> list[dict]:
    """Online nodes advertising one capability. Deterministic,
    read-only: capability providers, never pushed work."""
    wanted = str(capability or "").strip()[:80]
    if not wanted:
        return []
    return [{"node_id": record["node_id"],
             "tier": record.get("tier", ""),
             "status": record.get("derived_status", ""),
             "last_seen": str(record.get("last_seen", ""))[:19],
             "capabilities": list(record.get("capabilities", []))[:20]}
            for record in list_nodes()
            if record.get("derived_status") in ("online", "busy")
            and wanted in (record.get("capabilities") or [])]


@app.get("/api/v1/eligible-nodes")
def api_nodes_eligible(capability: str = "") -> dict:
    return {"capability": str(capability or "")[:80],
            "eligible": eligible_nodes_for(capability)}


def _research_conversation(mission_id: str) -> str:
    """Mission -> conversation linkage for worker payloads.

    Best-effort read over the existing mission store; missing
    missions yield an empty string, never a refusal — the fetch
    itself never depends on linkage metadata.
    """
    try:
        if not mission_id:
            return ""
        from .missions import load_mission as _load_mission
        mission = _load_mission(str(mission_id))
        if mission is None:
            return ""
        return str(mission.conversation_id or "")[:80]
    except Exception:
        return ""


def _route_run_to_nodes(run) -> dict:
    """Queue a run's validated seed URLs as research.fetch_url tasks
    for eligible nodes. Nothing executes here: nodes pull, fetch
    bounded text, and report; the completion hook ingests each
    result as a run source. Honest waiting when nobody qualifies."""
    from .research_engine import save_run
    metadata = run.metadata or {}
    seed_urls = [str(url) for url in
                 (metadata.get("seed_urls", []) or [])][:3]
    if not seed_urls:
        return {"ran": False, "run_id": run.run_id,
                "reason": "node-first needs seed_urls"}
    eligible = eligible_nodes_for("research.fetch")
    if not eligible:
        try:
            from .events import new_event as _bus_new, \
                save_event as _bus_save
            _bus_save(_bus_new(
                "research.routed",
                f"Run {run.run_id} waits: no eligible research "
                "node (WAITING_FOR_AGENT)",
                mission_id=run.mission_id or ""))
        except Exception:
            pass
        return {"ran": False, "run_id": run.run_id,
                "routed": False,
                "reason": "WAITING_FOR_AGENT: no online node with "
                          "research.fetch; fetch locally or add a "
                          "Linux node",
                "eligible": []}
    created: list[int] = []
    # Worker context (additive): the claiming worker receives the
    # bounded research linkage with the fetch — question, workspace,
    # mission/run/conversation ids. Existing url/run_id/max_chars
    # keys stay exactly as they were.
    research_context = {
        "question": str(run.question or "")[:500],
        "project_ref": str(run.project_ref or "")[:100],
        "mission_id": str(run.mission_id or "")[:80],
        "run_id": run.run_id,
        "conversation_id": _research_conversation(run.mission_id),
    }
    for url in seed_urls:
        try:
            made = create_task(TaskCreate(
                kind="research.fetch_url",
                payload={"url": url, "run_id": run.run_id,
                         "max_chars": 65536,
                         "research_context": research_context},
                required_capabilities=["research.fetch"],
                mission_id=run.mission_id or None))
            created.append(int(made.get("id", 0)))
        except HTTPException:
            continue
    created = [task_id for task_id in created if task_id]
    if not created:
        return {"ran": False, "run_id": run.run_id,
                "reason": "task creation refused"}
    updated = run.model_copy(update={
        "metadata": {**metadata, "routed_task_ids": created,
                     "routed_to": [entry["node_id"]
                                   for entry in eligible[:3]]}})
    save_run(updated)
    try:
        from .events import new_event as _bus_new, \
            save_event as _bus_save
        _bus_save(_bus_new(
            "research.routed",
            f"Run {run.run_id}: {len(created)} fetch task(s) "
            f"queued for {len(eligible)} eligible node(s)",
            mission_id=run.mission_id or ""))
    except Exception:
        pass
    return {"ran": False, "run_id": run.run_id, "routed": True,
            "task_ids": created,
            "eligible": [entry["node_id"] for entry in eligible],
            "reason": "tasks queued; nodes pull, fetch and report; "
                      "sources land on the run via completion"}


# =============================================================================
# BIG #32 — KNOWLEDGE LIFECYCLE. Candidates mature visibly:
# observation -> candidate -> supported -> promoted memory.
# Promotion is explicit, conflict-safe, provenance-preserving.
# =============================================================================


def _candidate_to_json(entry) -> dict:
    from .knowledge import support_count
    data = entry.model_dump(mode="json")
    data["supporters"] = support_count(entry)
    return data


@app.get("/api/v1/candidates")
def api_candidates_list(state: str = "", candidate_type: str = "",
                        project_ref: str = "",
                        limit: int = 50) -> dict:
    from .knowledge import CandidateRefusedError, list_candidates
    try:
        entries = list_candidates(
            state=state[:20], candidate_type=candidate_type[:20],
            project_ref=project_ref[:100], limit=limit)
    except CandidateRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"candidates": [_candidate_to_json(entry)
                           for entry in entries]}


@app.post("/api/v1/candidates", status_code=201)
def api_candidate_create(body: dict) -> dict:
    from .knowledge import (CandidateRefusedError, new_candidate,
                            save_candidate)
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    try:
        from .inventory_read import Provenance
        entry = new_candidate(
            str(body.get("title", "")), str(body.get(
                "candidate_type", "note")),
            summary=str(body.get("summary", "")),
            state=str(body.get("state", "candidate")),
            provenance=Provenance(
                source_type="user-created", creator_id="candidate-form",
                human_verified=True),
            source_refs=body.get("source_refs", []),
            evidence=body.get("evidence", []),
            entity_refs=body.get("entity_refs", []),
            project_ref=str(body.get("project_ref", "")))
        save_candidate(entry)
    except CandidateRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        from .events import new_event as _bus_new, \
            save_event as _bus_save
        _bus_save(_bus_new(
            "candidate.observed",
            f"Candidate {entry.candidate_id}: {entry.title[:120]}"))
    except Exception:
        pass
    return _candidate_to_json(entry)


@app.get("/api/v1/candidates/{candidate_id}")
def api_candidate_get(candidate_id: str) -> dict:
    from .knowledge import get_candidate
    entry = get_candidate(candidate_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown candidate")
    return _candidate_to_json(entry)


@app.post("/api/v1/candidates/{candidate_id}/support")
def api_candidate_support(candidate_id: str, body: dict) -> dict:
    from .knowledge import CandidateRefusedError, support_candidate
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    try:
        entry = support_candidate(
            candidate_id, str(body.get("supporter", "")),
            rationale=str(body.get("rationale", "")))
    except CandidateRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        from .events import new_event as _bus_new, \
            save_event as _bus_save
        _bus_save(_bus_new(
            "candidate.supported",
            f"Candidate {candidate_id} supported "
            f"({len(entry.support)} backing(s))"))
    except Exception:
        pass
    return _candidate_to_json(entry)


@app.post("/api/v1/candidates/{candidate_id}/promote")
def api_candidate_promote(candidate_id: str, body: dict) -> dict:
    from .knowledge import CandidateRefusedError, promote_candidate
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    try:
        result = promote_candidate(
            candidate_id, truth=str(body.get("truth", "")),
            verified_by=str(body.get("verified_by", "")),
            importance=body.get("importance", 0.6))
    except CandidateRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        from .events import new_event as _bus_new, \
            save_event as _bus_save
        _bus_save(_bus_new(
            "candidate.promoted",
            f"Candidate {candidate_id} promoted to "
            f"{result['memory_id']} [{result['truth']}]"))
    except Exception:
        pass
    return result


@app.post("/api/v1/candidates/{candidate_id}/reject")
def api_candidate_reject(candidate_id: str, body: dict) -> dict:
    from .knowledge import CandidateRefusedError, reject_candidate
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    try:
        entry = reject_candidate(
            candidate_id, reason=str(body.get("reason", "")),
            decided_by=str(body.get("decided_by", "human")))
    except CandidateRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        from .events import new_event as _bus_new, \
            save_event as _bus_save
        _bus_save(_bus_new("candidate.rejected",
                           f"Candidate {candidate_id} rejected"))
    except Exception:
        pass
    return _candidate_to_json(entry)


@app.post("/api/v1/candidates/{candidate_id}/keep")
def api_candidate_keep(candidate_id: str) -> dict:
    from .knowledge import CandidateRefusedError, touch_candidate
    try:
        entry = touch_candidate(candidate_id)
    except CandidateRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _candidate_to_json(entry)


@app.post("/api/v1/conversation-imports/{conversation_id}/findings/{index}/candidate",
          status_code=201)
def api_finding_to_candidate(conversation_id: str, index: int) -> dict:
    from .conversation_bridge import load_analysis
    from .knowledge import (CandidateRefusedError,
                            candidate_from_finding)
    analysis = load_analysis(conversation_id) or {}
    findings = analysis.get("findings", [])
    if not isinstance(index, int) or not 0 <= index < len(findings):
        raise HTTPException(status_code=404,
                            detail="Finding not found; analyze first")
    try:
        entry = candidate_from_finding(conversation_id,
                                       findings[index])
    except CandidateRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        from .events import new_event as _bus_new, \
            save_event as _bus_save
        _bus_save(_bus_new(
            "candidate.observed",
            f"Candidate {entry.candidate_id} from "
            f"{conversation_id} finding {index}"))
    except Exception:
        pass
    return _candidate_to_json(entry)


@app.post("/api/v1/observations/{observation_id}/candidate",
          status_code=201)
def api_observation_to_candidate(observation_id: str,
                                 body: dict | None = None) -> dict:
    from .inventory_read import Provenance
    from .knowledge import (CandidateRefusedError, new_candidate,
                            save_candidate)
    observation = _observation_load(observation_id)
    if observation is None:
        raise HTTPException(status_code=404,
                            detail="Observation not found")
    try:
        entry = new_candidate(
            f"observation {observation_id}: "
            f"{observation.media_ref or 'capture'}",
            "observation",
            summary=str((body or {}).get("summary", "") or
                        f"Camera {observation.device_id} saw "
                        f"{observation.media_ref or 'something'}; "
                        "needs human review before it means anything."),
            state="observation",
            provenance=Provenance(
                source_type="sensor-observed",
                creator_id=f"camera:{observation.device_id}",
                human_verified=False),
            source_refs=[{"kind": "observation",
                          "id": observation_id,
                          "label": observation.media_ref or ""}],
            evidence=[{"text": f"media {observation.media_ref}",
                       "source": observation.device_id}])
        save_candidate(entry)
    except CandidateRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _candidate_to_json(entry)


@app.post("/api/v1/research/dossiers/{dossier_id}/questions/{index}/candidate",
          status_code=201)
def api_question_to_candidate(dossier_id: str, index: int) -> dict:
    from .inventory_read import Provenance
    from .knowledge import (CandidateRefusedError, new_candidate,
                            save_candidate)
    from .research_engine import load_dossier
    dossier = load_dossier(dossier_id)
    if dossier is None:
        raise HTTPException(status_code=404, detail="Unknown dossier")
    questions = dossier.open_questions or []
    if not isinstance(index, int) or not 0 <= index < len(questions):
        raise HTTPException(status_code=404,
                            detail="Question not found")
    try:
        entry = new_candidate(
            f"research question: {questions[index][:140]}",
            "question", summary=questions[index][:1500],
            provenance=Provenance(
                source_type="external-source",
                creator_id=f"research:{dossier.run_id}",
                human_verified=False),
            source_refs=[{"kind": "research", "id": dossier_id,
                          "label": dossier.title[:120]}])
        save_candidate(entry)
    except CandidateRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _candidate_to_json(entry)


@app.get("/knowledge", response_class=HTMLResponse)
def knowledge_page(state: str = "", candidate_type: str = "") -> str:
    """Knowledge lifecycle: observations mature into candidates,
    supported claims, memories. Nothing promotes itself."""
    from . import ui as _ui
    from .knowledge import (ACTIVE_STATES, CANDIDATE_STATES,
                            CANDIDATE_TYPES, list_candidates,
                            support_count)
    try:
        entries = list_candidates(
            state=state, candidate_type=candidate_type, limit=60)
    except Exception:
        entries = []
    counts = {name: 0 for name in CANDIDATE_STATES}
    try:
        for entry in list_candidates(limit=200):
            counts[entry.state] = counts.get(entry.state, 0) + 1
    except Exception:
        pass
    state_options = "".join(
        f"<option value='{name}'"
        + (" selected" if name == state else "")
        + f">{name or 'all states'}</option>"
        for name in ["", *CANDIDATE_STATES])
    type_options = "".join(
        f"<option value='{name}'"
        + (" selected" if name == candidate_type else "")
        + f">{name or 'all types'}</option>"
        for name in ["", *CANDIDATE_TYPES])
    cards = ""
    for entry in entries:
        supporters = support_count(entry)
        evidence = "".join(
            f"<li><small>{_ui.esc(item.get('text', '')[:160])} "
            f"<span class=\"muted\">[{_ui.esc(item.get('source', ''))}]"
            f"</span></small></li>"
            for item in entry.evidence[:4])
        counter = "".join(
            f"<li><small>{_ui.esc(item.get('text', '')[:160])}</small>"
            f"</li>" for item in entry.counter_evidence[:3])
        next_action = {
            "observation": "Review it — support, research, or reject.",
            "candidate": "Find a second source, link it, or research it.",
            "supported": "Ready for your YES to promote to memory.",
            "promoted": f"Promoted to {entry.promoted_to}.",
            "rejected": "Rejected — kept as audit trail.",
        }.get(entry.state, "")
        actions = (
            f"<form method=\"post\" action=\"/web/candidates/"
            f"{_ui.esc(entry.candidate_id)}/support\" "
            f"style=\"display:inline\">"
            f"<input type=\"text\" name=\"supporter\" placeholder=\"You\" "
            f"style=\"width:5rem\" aria-label=\"Supporter\">"
            f"<button type=\"submit\">Support</button></form> "
            f"<form method=\"post\" action=\"/web/candidates/"
            f"{_ui.esc(entry.candidate_id)}/promote\" "
            f"style=\"display:inline\">"
            f"<input type=\"text\" name=\"verified_by\" "
            f"placeholder=\"verified by (for fact tier)\" "
            f"style=\"width:9rem\" aria-label=\"Verified by\">"
            f"<button type=\"submit\">Promote</button></form> "
            f"<form method=\"post\" action=\"/web/candidates/"
            f"{_ui.esc(entry.candidate_id)}/reject\" "
            f"style=\"display:inline\">"
            f"<button type=\"submit\">Reject</button></form>"
            if entry.state in ACTIVE_STATES else "")
        cards += (
            f"<div class=\"sprout grain\"><b>{_ui.esc(entry.title[:110])}</b><br>"
            f"{_ui.chip(entry.candidate_type)}"
            f"{_ui.chip(entry.state)}"
            f"<span class=\"chip\">♥ {supporters}</span><br>"
            f"<small>{_ui.esc(entry.summary[:200])}</small><br>"
            f"<span class=\"muted\">from "
            f"{_ui.esc(entry.provenance.source_type)} · "
            f"{_ui.esc(entry.provenance.creator_id)} · "
            f"{_ui.esc(entry.created_at[:10])}</span>"
            f"<ul>{evidence}</ul>"
            + (f"<p><small>⚠ counter: </small></p><ul>{counter}</ul>"
               if counter else "")
            + (f"<p><small>→ linked: "
                f"{_ui.esc(', '.join(entry.entity_refs[:5]))}</small></p>"
                if entry.entity_refs else "")
            + f"<p class=\"muted\">Next: {_ui.esc(next_action)}</p>"
            f"<p>{actions}</p></div>")
    pipeline = " → ".join(
        f"{name} ({counts.get(name, 0)})" for name in CANDIDATE_STATES)
    main = f"""<h1>Knowledge — what Mycelium is learning</h1>
    <p class="muted">OBSERVATION → CANDIDATE → SUPPORTED → PROMOTED MEMORY. { _ui.esc(pipeline) }. Nothing promotes itself; verified memories are never overwritten.</p>
    <div class="panel"><form method="get" action="/knowledge" aria-label="Filter candidates">
    <select name="state" aria-label="State">{state_options}</select>
    <select name="candidate_type" aria-label="Type">{type_options}</select>
    <button type="submit">Filter</button></form></div>
    <div class="panel"><h2>New candidate</h2>
    <form method="post" action="/web/candidates">
    <input type="text" name="title" placeholder="Title" style="width:35%" aria-label="Title">
    <select name="candidate_type" aria-label="Type">{"".join(f"<option value='{name}'>{name}</option>" for name in CANDIDATE_TYPES)}</select>
    <input type="text" name="summary" placeholder="Summary" style="width:35%" aria-label="Summary">
    <button type="submit">Remember as candidate</button></form></div>
    <div class="grove">{cards or _ui.empty("🌱 This part of the ecosystem is quiet. Give Mycelium an observation, import a conversation, or run research — candidates grow here, never facts.")}</div>"""
    return _ui.shell("Knowledge", "/knowledge", main, _ui.command_bar())


@app.post("/web/candidates")
async def web_candidate_create(request: Request) -> Response:
    from .inventory_read import Provenance
    from .knowledge import (CandidateRefusedError, new_candidate,
                            save_candidate)
    fields = await _form_fields(request)
    try:
        entry = new_candidate(
            fields.get("title", ""),
            fields.get("candidate_type", "note") or "note",
            summary=fields.get("summary", ""),
            provenance=Provenance(
                source_type="user-created", creator_id="web",
                human_verified=True),
            project_ref=fields.get("project_ref", ""))
        save_candidate(entry)
    except CandidateRefusedError:
        pass
    return RedirectResponse("/knowledge", status_code=303)


@app.post("/web/candidates/{candidate_id}/support")
async def web_candidate_support(candidate_id: str,
                                request: Request) -> Response:
    from .knowledge import CandidateRefusedError, support_candidate
    fields = await _form_fields(request)
    try:
        support_candidate(
            candidate_id, fields.get("supporter", "Jelles") or
            "Jelles",
            rationale=fields.get("rationale", "")[:300])
    except CandidateRefusedError:
        pass
    return RedirectResponse("/knowledge", status_code=303)


@app.post("/web/candidates/{candidate_id}/promote")
async def web_candidate_promote(candidate_id: str,
                                request: Request) -> Response:
    from .events import new_event as _bus_new, \
        save_event as _bus_save
    from .knowledge import CandidateRefusedError, promote_candidate
    fields = await _form_fields(request)
    try:
        result = promote_candidate(
            candidate_id,
            verified_by=fields.get("verified_by", ""))
        _bus_save(_bus_new(
            "candidate.promoted",
            f"Candidate {candidate_id} promoted to "
            f"{result['memory_id']} [{result['truth']}]"))
    except CandidateRefusedError:
        pass
    return RedirectResponse("/knowledge", status_code=303)


@app.post("/web/candidates/{candidate_id}/reject")
async def web_candidate_reject(candidate_id: str,
                               request: Request) -> Response:
    from .knowledge import CandidateRefusedError, reject_candidate
    fields = await _form_fields(request)
    try:
        reject_candidate(candidate_id,
                         reason=fields.get("reason", "")[:300],
                         decided_by="web")
    except CandidateRefusedError:
        pass
    return RedirectResponse("/knowledge", status_code=303)


# =============================================================================
# BIG #33 — Living World: symbiosis, craft tree, guide, node mesh
# =============================================================================


@app.get("/api/v1/guide")
def api_guide(limit: int = 12) -> dict:
    from .guide import guide_items
    try:
        count = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        count = 12
    return {"items": guide_items(limit=count),
            "honesty": "Derived live from approvals, candidates, "
                       "conversations, research, cameras, "
                       "fabrications, nodes, projects. Read-only."}


# =============================================================================
# BIG #40 — Presence ecosystem: attention API
# =============================================================================


@app.get("/api/v1/presence")
def api_presence(limit: int = 120) -> dict:
    """Unified attention: bands + items + cleared + progression
    + overnight digest. Derived live, read-only."""
    from .presence import (attention_snapshot, overnight_digest,
                           progression)
    try:
        count = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        count = 120
    snapshot = attention_snapshot(limit=count)
    snapshot["progression"] = progression()
    snapshot["overnight"] = overnight_digest()
    return snapshot


@app.post("/api/v1/presence/seen")
def api_presence_seen(body: PresenceTriageBody) -> dict:
    """Mark one live attention item SEEN. Bookkeeping only."""
    from .presence import PresenceRefusedError, set_triage
    try:
        return set_triage(body.item_id, "SEEN",
                          decided_by=body.decided_by)
    except PresenceRefusedError as error:
        raise HTTPException(status_code=404, detail=str(error))


@app.post("/api/v1/presence/defer")
def api_presence_defer(body: PresenceTriageBody) -> dict:
    """Defer one live attention item. DEFER performs nothing —
    it only hides the item from the urgent bands."""
    from .presence import PresenceRefusedError, set_triage
    try:
        return set_triage(body.item_id, "DEFERRED",
                          decided_by=body.decided_by)
    except PresenceRefusedError as error:
        raise HTTPException(status_code=404, detail=str(error))


@app.post("/api/v1/presence/notify")
def api_presence_notify(body: PresenceNotifyBody) -> dict:
    """Explicit presence fan-out: deduplicated IN_APP delivery.
    Never background, never push."""
    from .presence import sync_presence_notifications
    return sync_presence_notifications(limit=body.limit)


@app.post("/web/presence/defer")
async def web_presence_defer(request: Request) -> Response:
    """Form DEFER from presence cards. Stores triage only;
    performs nothing, then returns to the attention view."""
    from .presence import PresenceRefusedError, set_triage
    fields = await _form_fields(request)
    try:
        set_triage(str(fields.get("item_id", "")),
                   "DEFERRED", decided_by="web")
    except PresenceRefusedError:
        pass
    return RedirectResponse("/presence", status_code=303)


@app.post("/web/presence/seen")
async def web_presence_seen(request: Request) -> Response:
    """Form SEEN from presence cards. Bookkeeping only."""
    from .presence import PresenceRefusedError, set_triage
    fields = await _form_fields(request)
    try:
        set_triage(str(fields.get("item_id", "")),
                   "SEEN", decided_by="web")
    except PresenceRefusedError:
        pass
    return RedirectResponse("/presence", status_code=303)


@app.get("/api/v1/symbiosis")
async def api_symbiosis(entity_id: str = "",
                        depth: int = 1) -> dict:
    from .symbiosis import clean_entity, for_entity
    try:
        cleaned = clean_entity(entity_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        return await for_entity(cleaned, depth)
    except (InventoryRefusedError, InventoryUnavailable,
            ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/v1/craft")
async def api_craft(entity_id: str = "", depth: int = 1) -> dict:
    from .symbiosis import clean_entity
    from .craft import craft_tree, stage_states
    try:
        cleaned = clean_entity(entity_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        tree = await craft_tree(cleaned, depth)
    except (InventoryRefusedError, InventoryUnavailable,
            ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    try:
        tree["states"] = stage_states(tree)
    except Exception:
        tree["states"] = []
    return tree


@app.get("/api/v1/mesh/topology")
def api_mesh_topology() -> dict:
    from .nodemesh import mesh_topology
    return mesh_topology()


@app.post("/api/v1/mesh/validate")
def api_mesh_validate(body: dict) -> dict:
    from .nodemesh import validate_delegation
    if not isinstance(body, dict):
        raise HTTPException(status_code=422,
                            detail="JSON body required")
    try:
        return validate_delegation(
            str(body.get("requesting_node", "")),
            str(body.get("task_kind", "")),
            str(body.get("capability", "")),
            body.get("payload") if isinstance(
                body.get("payload"), dict) else {})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# =============================================================================
# BIG #41 — V2 remote mesh: targeted delegation through the task queue.
# Validate → authenticate → eligibility precheck → create queued
# task → assign to the pinned target (rollback on failure).
# The target must still pull/claim (liveness + credential
# re-checked at claim). Nothing is pushed, nothing executes here.
# =============================================================================


def _mesh_authenticate(requesting_node: str,
                       node_token: str | None) -> str:
    """Authenticate a delegation requester. Unknown nodes 404;
    bad credentials 403; legacy (never bound) allowed like the
    claim path — delegation only queues work that still must
    be claimed by an eligible node."""
    with connection() as db:
        row = db.execute(
            "SELECT auth_token_hash FROM nodes WHERE node_id=?",
            (requesting_node,)).fetchone()
    if row is None:
        raise HTTPException(404, "Node is not registered")
    try:
        return authenticate(requesting_node,
                            row["auth_token_hash"], node_token)
    except NodeAuthError:
        raise HTTPException(status_code=403,
                            detail="node credential rejected")


def _mesh_receipt(task_id: int, checked: dict) -> dict:
    """WHAT/WHY/WHERE/CAPABILITY/RISK/RESULT receipt. The RISK
    line is static honest mechanics, never a per-task promise."""
    target = checked.get("target_node", "")
    return {
        "task_id": task_id,
        "status": "queued+assigned — target must still claim",
        "what": f"{checked['task_kind']} via capability "
                f"{checked['capability']}",
        "why": checked.get("reason", "") or
               "node→coordinator→node delegation",
        "where": f"coordinator queue → {target}",
        "capability": checked["capability"],
        "risk": "Read-only kind on the target node; result "
                "returns via task completion; no shell, no "
                "standing permission; lease 300s, max 3 attempts; "
                "requester gains no capabilities.",
        "result_href": f"/api/v1/tasks/by-id/{task_id}",
        "activity_href": "/activity",
        "timeout_seconds": checked.get("timeout_seconds", 60),
        "target_node": target,
        "requesting_node": checked["requesting_node"],
    }


@app.post("/api/v1/mesh/preview")
def api_mesh_preview(body: MeshPreviewBody) -> dict:
    """Dry-run delegation: validate + routing explanation.
    Creates nothing."""
    from .nodemesh import validate_delegation
    from .routing import check_requirements, explain_decision
    try:
        checked = validate_delegation(
            body.requesting_node, body.task_kind,
            body.capability, body.payload,
            target_node=body.target_node,
            timeout_seconds=body.timeout_seconds,
            reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    explanation = {"summary": "no pinned target; any eligible "
                              "node may claim",
                   "eligible": [], "waiting": [], "blocked": [],
                   "unavailable": [], "lines": {}}
    if checked.get("target_node"):
        try:
            requirements = check_requirements(
                {"required_capabilities": [checked["capability"]]})
            decision = _decision_for(
                0, requirements, {},
                only_node=checked["target_node"])
            explanation = explain_decision(
                decision, _routing_candidates())
        except HTTPException as exc:
            raise exc
        except ValueError as exc:
            raise HTTPException(status_code=422,
                                detail=str(exc))
    return {"valid": True, "checked": checked,
            "why": explanation,
            "risk": _mesh_receipt(0, checked)["risk"],
            "created": False}


@app.post("/api/v1/mesh/delegate", status_code=201)
def api_mesh_delegate(body: MeshDelegateBody) -> dict:
    """Delegate one bounded task to a pinned target node.

    Authenticate → validate → eligibility precheck → create →
    assign. Assign failure rolls the queued row back so a task
    meant for one node can never drift to another. The target
    must still pull/claim it.
    """
    from .nodemesh import validate_delegation
    from .routing import check_requirements
    _mesh_authenticate(body.requesting_node, body.node_token)
    if not (body.target_node or "").strip():
        raise HTTPException(status_code=422,
                            detail="delegate pins an explicit "
                                   "target_node; untargeted dispatch "
                                   "is POST /api/v1/tasks")
    try:
        checked = validate_delegation(
            body.requesting_node, body.task_kind,
            body.capability, body.payload,
            target_node=body.target_node,
            timeout_seconds=body.timeout_seconds,
            reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        requirements = check_requirements(
            {"required_capabilities": [checked["capability"]]})
        decision = _decision_for(0, requirements, {},
                                 only_node=checked["target_node"])
    except (HTTPException, ValueError) as exc:
        raise HTTPException(status_code=409, detail=
                            f"target not currently eligible; "
                            f"nothing queued ({exc})")
    if decision.selected_node_id != checked["target_node"]:
        raise HTTPException(
            status_code=409,
            detail="target not currently eligible; nothing "
                   "queued ("
                   + "; ".join(reason for entry in
                               decision.rejected
                               for reason in entry.reasons)[:240]
                   + ")")
    created = create_task(TaskCreate(
        kind=checked["task_kind"], payload=dict(checked["payload"]),
        required_capabilities=[checked["capability"]],
        priority=body.priority,
        requirements={"required_capabilities":
                      [checked["capability"]]}))
    task_id = int(created["id"])
    try:
        assign_task(task_id, TaskAssignBody(
            node_id=checked["target_node"], policy={}))
    except HTTPException as exc:
        with connection() as db:
            db.execute("DELETE FROM tasks WHERE id=? AND "
                       "status='queued'", (task_id,))
        logger.info("mesh_delegate_rolled_back task_id=%s "
                    "target=%s cause=%s", task_id,
                    checked["target_node"], exc.detail)
        raise HTTPException(
            status_code=409,
            detail=f"target refused at assign; nothing queued "
                   f"({exc.detail})")
    logger.info("mesh_delegated task_id=%s from=%s target=%s "
                "kind=%s", task_id, checked["requesting_node"],
                checked["target_node"], checked["task_kind"])
    try:
        from .events import new_event as _bus_new, \
            save_event as _bus_save
        _bus_save(_bus_new(
            "task.delegated",
            f"Task {task_id} ({checked['task_kind']}) "
            f"{checked['requesting_node']} → "
            f"{checked['target_node']}: "
            f"{checked.get('reason', '')[:120]}",
            task_id=str(task_id),
            node_id=checked["target_node"]))
    except Exception:
        pass
    return _mesh_receipt(task_id, checked)


# =============================================================================
# BIG #38 — LIVING AUTOMATION. First-class automation runs over
# the existing architecture: safe steps drive automatically,
# consequential work waits with the exact gate named, resume
# re-reads live stores. No second mission engine, no new gates.
# =============================================================================


@app.post("/api/v1/automation/runs", status_code=201)
def api_automation_create(body: dict) -> dict:
    from .automation import (AutomationRefusedError, create_run,
                             run_to_json)
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    try:
        run = create_run(
            str(body.get("goal", "")),
            body.get("steps", []) or [],
            mission_id=str(body.get("mission_id", "")),
            bounds=body.get("bounds"),
            overnight=bool(body.get("overnight", False)),
            actor=str(body.get("actor", "api")))
    except AutomationRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return run_to_json(run)


@app.post("/api/v1/automation/from-template", status_code=201)
def api_automation_from_template(body: dict) -> dict:
    from .automation import (AutomationRefusedError,
                             create_from_template, run_to_json)
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    try:
        run = create_from_template(
            str(body.get("template_id", "")),
            body.get("args") if isinstance(body.get("args"),
                                           dict) else {},
            mission_id=str(body.get("mission_id", "")),
            bounds=body.get("bounds"),
            overnight=bool(body.get("overnight", False)),
            actor=str(body.get("actor", "api")))
    except AutomationRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return run_to_json(run)


@app.get("/api/v1/automation/templates")
def api_automation_templates() -> dict:
    from .automation import list_templates
    return {"templates": list_templates()}


@app.get("/api/v1/automation/runs")
def api_automation_list(state: str = "", limit: int = 50) -> dict:
    from .automation import list_runs, run_to_json
    try:
        count = max(1, min(int(limit or 50), 200))
    except (TypeError, ValueError):
        count = 50
    return {"runs": [run_to_json(run)
                     for run in list_runs(limit=count,
                                          state=state[:30])]}


@app.get("/api/v1/automation/runs/{run_id}")
def api_automation_get(run_id: str) -> dict:
    from .automation import load_run, run_to_json
    run = load_run(run_id)
    if run is None:
        raise HTTPException(status_code=404,
                            detail="automation run not found")
    return run_to_json(run)


@app.get("/api/v1/automation/runs/{run_id}/overnight")
def api_automation_overnight(run_id: str) -> dict:
    from .automation import AutomationRefusedError, overnight_eligible
    try:
        return overnight_eligible(run_id)
    except AutomationRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/v1/automation/runs/{run_id}/drive")
async def api_automation_drive(run_id: str, body: dict | None = None) -> dict:
    from .automation import AutomationRefusedError, drive_run
    payload = body if isinstance(body, dict) else {}
    try:
        budget = int(payload.get("budget_steps", 10))
    except (TypeError, ValueError):
        budget = 10
    try:
        return await drive_run(run_id, budget_steps=budget)
    except AutomationRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/v1/automation/runs/{run_id}/resume")
async def api_automation_resume(run_id: str,
                                body: dict | None = None) -> dict:
    from .automation import AutomationRefusedError, resume_run
    payload = body if isinstance(body, dict) else {}
    try:
        budget = int(payload.get("budget_steps", 10))
    except (TypeError, ValueError):
        budget = 10
    try:
        return await resume_run(run_id, budget_steps=budget)
    except AutomationRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/v1/automation/runs/{run_id}/cancel")
def api_automation_cancel(run_id: str, body: dict | None = None) -> dict:
    from .automation import (AutomationRefusedError, cancel_run,
                             run_to_json)
    payload = body if isinstance(body, dict) else {}
    try:
        run = cancel_run(
            run_id, reason=str(payload.get("reason", "")))
    except AutomationRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return run_to_json(run)


@app.post("/web/automation/from-template")
async def web_automation_from_template(
        request: Request) -> RedirectResponse:
    from .automation import AutomationRefusedError, create_from_template
    fields = await _form_fields(request)
    args = {"goal": fields.get("goal", ""),
            "conversation_id": fields.get("conversation_id", ""),
            "observation_id": fields.get("observation_id", ""),
            "entity_id": fields.get("entity_id", "")}
    try:
        run = create_from_template(
            fields.get("template_id", ""), args, actor="web")
    except AutomationRefusedError:
        return RedirectResponse("/automation", status_code=303)
    return RedirectResponse(f"/automation/{run.run_id}",
                            status_code=303)


@app.post("/web/automation/runs/{run_id}/{op}")
async def web_automation_op(run_id: str,
                            op: str) -> RedirectResponse:
    from .automation import (AutomationRefusedError, cancel_run,
                             drive_run, resume_run)
    try:
        if op == "drive":
            await drive_run(run_id, budget_steps=10)
        elif op == "resume":
            await resume_run(run_id, budget_steps=10)
        elif op == "cancel":
            cancel_run(run_id, reason="operator stop")
    except AutomationRefusedError:
        pass
    return RedirectResponse(f"/automation/{run_id}", status_code=303)


def _automation_quest_html(run_id: str, goal: str, state: str,
                           steps: list) -> str:
    from . import ui as _ui
    trail = _ui.quest_steps([
        {"status": ("done" if step.get("status") == "done"
                    else "open" if step.get("status") == "pending"
                    else step.get("status", "open")),
         "description": f"{step.get('kind', '')} — "
                        f"{step.get('step_id', '')}"}
        for step in steps[:8]])
    return (
        f"<div class=\"sprout { _ui.growth_class(state)}\">"
        f"<b>{_ui.esc(goal[:90])}</b><br>"
        f"{_ui.status_dot(state)}{_ui.chip(state)}"
        f"<br>{trail}"
        f"<a href='/automation/{_ui.esc(run_id)}'>Open run</a></div>")


@app.get("/automation", response_class=HTMLResponse)
def automation_page() -> str:
    """Living automation: runs as quest trails over safe steps."""
    from . import ui as _ui
    from .automation import list_runs, list_templates
    cards = "".join(
        _automation_quest_html(run.run_id, run.goal, run.state,
                               [step.model_dump(mode="json")
                                for step in run.steps])
        for run in list_runs(limit=30)) or \
        _ui.empty("No automation runs yet — start one from a template.")
    templates = "".join(
        f"<li><b>{_ui.esc(template['title'])}</b> "
        f"<span class=\"muted\">{_ui.esc(template['description'][:160])}</span>"
        f"<form method=\"post\" action=\"/web/automation/from-template\" "
        f"style=\"display:inline\">"
        f"<input type=\"hidden\" name=\"template_id\" value=\"{_ui.esc(template['template_id'])}\">"
        f"<input type=\"text\" name=\"goal\" placeholder=\"Goal\" style=\"width:30%\" aria-label=\"Goal\">"
        f"<input type=\"text\" name=\"conversation_id\" placeholder=\"conv_… (optional)\" style=\"width:22%\" aria-label=\"Conversation\">"
        f"<button type=\"submit\">Start</button></form></li>"
        for template in list_templates())
    main = f"""<h1>Automation — the workshop keeps going</h1>
    <p class="muted">Safe steps drive automatically; consequential work waits with the exact gate named; resume re-checks live state. No background threads — every drive is an explicit call.</p>
    <div class="panel"><h2>Start from template</h2><ul>{templates}</ul></div>
    <h2>Runs</h2><div class="grove">{cards}</div>"""
    return _ui.shell("Automation", "/automation",
                     _ui.living_bg() + main, _ui.command_bar())


@app.get("/automation/{run_id}", response_class=HTMLResponse)
def automation_detail_page(run_id: str):
    """One run: quest trail, waiting bundle, actions, packet link."""
    from . import ui as _ui
    from .automation import load_run
    run = load_run(run_id)
    if run is None:
        return HTMLResponse("Automation run not found", status_code=404)
    data = run.model_dump(mode="json")
    waiting = data.get("waiting") or {}
    waiting_html = ""
    if data["state"] in ("waiting_for_human", "waiting_for_agent") \
            and waiting:
        gate = waiting.get("gate") or {}
        approval_url = waiting.get("approval_url", "/activity")
        gate_text = (str(gate.get("type", "")) + " " +
                     str(gate.get("ref", ""))).strip()
        waiting_html = (
            f"<div class=\"panel auto-wait\"><h2>Waiting — exact gate</h2>"
            f"<p><b>{_ui.esc(waiting.get('reason', ''))}</b></p>"
            + _ui.kv_list([
                ("Action", _ui.esc(waiting.get("action", ""))),
                ("Scope", _ui.esc(
                    str(waiting.get("scope", ""))[:300])),
                ("Source", _ui.esc(waiting.get("source", ""))),
                ("Gate", _ui.esc(gate_text)),
                ("Approval",
                 f"<a href=\"{_ui.esc(approval_url)}\">"
                 f"{_ui.esc(approval_url)}</a>")])
            + f"<form method=\"post\" action=\"/web/automation/runs/"
            f"{_ui.esc(run_id)}/resume\" style=\"display:inline\">"
            f"<button>Resume (re-checks live state)</button></form>"
            f"</div>")
    trail = _ui.quest_steps([
        {"status": ("done" if step.get("status") == "done"
                    else "open" if step.get("status") == "pending"
                    else step.get("status", "open")),
         "description": f"{step.get('kind', '')} — "
                        f"{step.get('step_id', '')} "
                        f"{str(step.get('error', ''))[:80]}"}
        for step in data.get("steps", [])])
    bounds = data.get("bounds", {})
    actions = ""
    if data["state"] == "running":
        actions += f"<form method=\"post\" action=\"/web/automation/runs/{_ui.esc(run_id)}/drive\" style=\"display:inline\"><button>Drive 10 steps</button></form> "
    if data["state"] not in ("completed", "failed", "cancelled"):
        actions += f"<form method=\"post\" action=\"/web/automation/runs/{_ui.esc(run_id)}/cancel\" style=\"display:inline\"><button>STOP</button></form>"
    main = f"""<h1>Automation run</h1>
    <div class="panel"><p><b>{_ui.esc(data.get('goal', ''))}</b></p>
    <p>{_ui.status_dot(data['state'])}<b>{_ui.esc(data['state'])}</b> · {data.get('steps_done', 0)}/{data.get('steps_total', len(data.get('steps', [])))} steps · bounds max {bounds.get('max_steps', '?')} steps / {bounds.get('max_runtime_seconds', '?')}s</p>
    <p class=\"muted\">template { _ui.esc(data.get('template_id', '') or '—')} · mission {f"<a href='/missions/{_ui.esc(data.get('mission_id', ''))}'>{_ui.esc(data.get('mission_id', ''))}</a>" if data.get('mission_id') else '—'} · overnight-eligible: <b>{'yes' if _ui.esc(str(data.get('overnight', False))) == 'True' else 'no'}</b></p>
    <p>{actions}</p>
    <p class=\"muted\">Continue elsewhere: <a href=\"/api/v1/context/packet?goal={_ui.esc(data.get('goal', '')[:80])}\">context packet (JSON)</a> · <a href=\"/api/v1/context/packet.md?goal={_ui.esc(data.get('goal', '')[:80])}\">Markdown</a></p></div>
    {waiting_html}
    <h2>Quest trail</h2>{trail}"""
    return _ui.shell("Automation run", "/automation",
                     _ui.living_bg() + main, _ui.command_bar())


@app.get("/guide", response_class=HTMLResponse)
def guide_page() -> str:
    """Mycelium Guide: what needs Jelles, with WHAT/WHY/NEXT."""
    from . import ui as _ui
    from .guide import guide_items
    items = guide_items(limit=12)
    cards = "".join(_ui.guide_card(item) for item in items) or \
        _ui.empty_grove(
            "Your world is quiet. Nothing waits for you — "
            "grow a seed and the guide will notice.",
            [("Create project", "/projects"),
             ("Import conversation", "/conversations"),
             ("Research something", "/research"),
             ("Connect a node", "/nodes")])
    main = (f"<h1>Guide — where the world needs you</h1>"
            f"<p class=\"muted\">Not a tutorial. The guide reads "
            f"live state and points at real work: WHAT, WHY, NEXT."
            f"</p><div class=\"grove\">{cards}</div>")
    return _ui.shell("Guide", "/guide", _ui.living_bg() + main,
                     _ui.command_bar())


def _presence_band_html(band: str, items: list) -> str:
    """One presence band: glyph + title + attention cards."""
    from . import ui as _ui
    from .presence import BAND_META
    meta = BAND_META.get(band, {"glyph": "•", "title": band})
    body = "".join(_ui.presence_card(item) for item in items[:12])
    return (
        f"<div class=\"panel\" id=\"band-{band}\">"
        f"<h2>{meta['glyph']} {meta['title']} ({len(items)})</h2>"
        f"<div class=\"grove\">"
        f"{body or _ui.empty('Nothing here.')}</div></div>")


@app.get("/presence", response_class=HTMLResponse)
def presence_page() -> str:
    """Attention view: bands of live attention items, recently
    cleared, and real progression. Derived now, read-only."""
    from . import ui as _ui
    from .presence import attention_snapshot, progression
    try:
        snapshot = attention_snapshot(limit=120)
    except Exception:
        snapshot = {"bands": {band: [] for band in
                              ("needs", "waiting", "available",
                               "discovered", "offline")},
                    "cleared": [], "counts": {}}
    bands = snapshot.get("bands", {})
    try:
        prog = progression()
    except Exception:
        prog = {"quests": [], "discoveries_24h": 0,
                "observations_24h": 0, "growth_24h": 0,
                "activity_24h": 0, "online_nodes": 0,
                "capabilities_unlocked": []}
    order = ("needs", "waiting", "available", "discovered",
             "offline")
    sections = "".join(
        _presence_band_html(band, bands.get(band, []))
        for band in order)
    cleared = snapshot.get("cleared", [])
    cleared_rows = "".join(
        f"<li><small>{_ui.esc(item.get('title', ''))}</small> "
        f"{_ui.chip('RESOLVED')}</li>" for item in cleared[:10])
    quests = prog.get("quests", [])
    quest_rows = "".join(
        f"<li><small>{_ui.esc(quest.get('title', ''))}</small> "
        f"{_ui.esc(str(quest.get('done', 0)))}/"
        f"{_ui.esc(str(quest.get('total', 0)))} "
        f"{_ui.chip(_ui.esc(quest.get('status', '')))} "
        f"<a href=\"{_ui.esc(quest.get('href', '/'))}\">Open →"
        f"</a></li>" for quest in quests[:8])
    caps = ", ".join(_ui.esc(cap) for cap in
                     prog.get("capabilities_unlocked", [])[:12])
    main = (f"<h1>Presence — what deserves attention</h1>"
            f"<p class=\"muted\">Derived live from approvals, "
            f"missions, nodes, research, candidates, cameras, "
            f"craft, symbiosis and automation. YES/NO run the "
            f"existing gates; DEFER changes nothing.</p>"
            f"{sections}"
            f"<div class=\"panel\"><h2>Recently cleared "
            f"({len(cleared)})</h2><ul>"
            f"{cleared_rows or '<li>Nothing cleared lately.</li>'}"
            f"</ul></div>"
            f"<div class=\"panel\"><h2>Ecosystem activity</h2>"
            f"<p class=\"muted\">{prog.get('activity_24h', 0)} "
            f"events · {prog.get('discoveries_24h', 0)} "
            f"discoveries · {prog.get('observations_24h', 0)} "
            f"observations · {prog.get('growth_24h', 0)} growth "
            f"· {prog.get('online_nodes', 0)} nodes online</p>"
            f"<p class=\"muted\">Capabilities unlocked: "
            f"{caps or '—'}</p>"
            f"<ul class=\"quest\">{quest_rows or '<li>No open quests.</li>'}</ul></div>")
    return _ui.shell("Presence", "/presence",
                     _ui.living_bg() + main, _ui.command_bar())


@app.get("/symbiosis", response_class=HTMLResponse)
async def symbiosis_page(entity_id: str = "") -> str:
    """Symbiosis: explicit mutual influence, PROPOSED/SUPPORTED/VERIFIED."""
    from . import ui as _ui
    from .symbiosis import for_entity, proposed
    detail = ""
    if entity_id:
        try:
            result = await for_entity(entity_id, 1)
            rows = "".join(
                f"<tr><td>{_ui.symbiosis_chip(item['state'])} "
                f"<span class=\"strength "
                f"{'strong' if item['state'] == 'VERIFIED' else 'growing' if item['state'] == 'SUPPORTED' else 'seedling'}\" "
                f"role=\"img\" aria-label=\"connection strength: "
                f"{'strong' if item['state'] == 'VERIFIED' else 'growing' if item['state'] == 'SUPPORTED' else 'seedling'}\"></span></td>"
                f"<td><a href=\"/world?entity_id={_ui.esc(item['entity_b'])}\">"
                f"{_ui.esc(item['entity_b'])}</a></td>"
                f"<td>{_ui.esc(item['predicate'][:80])}</td></tr>"
                for item in result["symbioses"][:30])
            counts = result["counts"]
            detail = (
                f"<div class=\"panel\"><h2>"
                f"{_ui.esc(entity_id)}</h2>"
                f"<p class=\"muted\">{counts['verified']} verified · "
                f"{counts['supported']} supported · "
                f"{counts['proposed']} proposed. "
                f"{_ui.esc(result['honesty'])}</p>"
                f"<table><tr><th>State</th><th>Other</th>"
                f"<th>Through</th></tr>{rows or '<tr><td colspan=3>'
                f'No symbioses yet — relations grow here when you '
                f'link entities.</td></tr>'}</table>"
                f"<p><a href=\"/craft?entity_id={_ui.esc(entity_id)}\">"
                f"Open craft tree →</a></p></div>")
        except (ValueError, InventoryRefusedError,
                InventoryUnavailable) as exc:
            detail = f"<div class=\"panel\"><p>{_ui.esc(str(exc))}</p></div>"
    proposals = proposed(limit=12)
    prop_rows = "".join(
        f"<tr><td>{_ui.symbiosis_chip('PROPOSED')}</td>"
        f"<td>{_ui.esc(prop['title'][:80])}</td>"
        f"<td>{_ui.esc(', '.join(prop['entities'][:4]))}</td>"
        f"<td><a href=\"{_ui.esc(prop['link'])}\">Review</a></td></tr>"
        for prop in proposals) or ("<tr><td colspan='4'>No open "
                                   "proposals. Connection candidates "
                                   "appear here — AI proposes, you "
                                   "decide.</td></tr>")
    main = (f"<h1>Symbiosis — what strengthens what</h1>"
            f"<p class=\"muted\">Two or more entities influencing "
            f"each other through an explicit relation. Never "
            f"invented: SUPPORTED/VERIFIED are real INVENTory "
            f"edges, PROPOSED are open candidates.</p>"
            f"<div class=\"panel\"><h2>Progression</h2>"
            f"<p><span class=\"strength strong\"></span> strong — "
            f"VERIFIED edge (human-verified) · "
            f"<span class=\"strength growing\"></span> growing — "
            f"SUPPORTED edge (real relation) · "
            f"<span class=\"strength seedling\"></span> seedling — "
            f"PROPOSED (uncertain until you review). "
            f"Strength is display only; states never promote "
            f"silently.</p></div>"
            f"<div class=\"panel\"><form method=\"get\" "
            f"action=\"/symbiosis\"><label>Entity "
            f"<input type=\"text\" name=\"entity_id\" "
            f"placeholder=\"proj_… / obj_…\" value=\""
            f"{_ui.esc(entity_id)}\" style=\"width:16rem\"></label>"
            f"<button type=\"submit\">Grow</button></form></div>"
            f"{detail}"
            f"<div class=\"panel\"><h2>Open proposals</h2>"
            f"<table><tr><th>State</th><th>Proposal</th>"
            f"<th>Entities</th><th>Next</th></tr>"
            f"{prop_rows}</table></div>")
    return _ui.shell("Symbiosis", "/symbiosis",
                     _ui.living_bg() + main, _ui.command_bar())


@app.get("/craft", response_class=HTMLResponse)
async def craft_page(entity_id: str = "", depth: int = 1) -> str:
    """Craft Tree: idea → project → … → made thing, on real records."""
    from . import ui as _ui
    from .craft import STAGES, craft_tree
    detail = ""
    if entity_id:
        try:
            from .craft import stage_states as _stage_states
            tree = await craft_tree(entity_id, depth)
            try:
                states = {entry["key"]: entry
                          for entry in _stage_states(tree)}
            except Exception:
                states = {}
            blocks = []
            for stage in tree["stages"]:
                nodes = "".join(
                    f"<li><a href=\"{_ui.esc(node['href'])}\">"
                    f"{_ui.esc(node['label'][:60])}</a> "
                    f"<span class=\"muted\">[{_ui.esc(node['kind'])}"
                    f"]</span></li>"
                    for node in stage["nodes"][:8])
                state = states.get(stage["key"], {})
                mark = state.get("glyph", "")
                word = state.get("state", "")
                cls = "full" if stage["nodes"] else "empty"
                stage_list_html = nodes or (
                    '<li class="muted">Not grown yet.</li>')
                blocks.append(
                    f"<div class=\"craft-stage {cls}\">"
                    f"<h3>{_ui.esc(stage['glyph'])} "
                    f"{_ui.esc(stage['title'])} "
                    f"{_ui.chip(f'{mark} {word}') if word else ''}</h3>"
                    f"<ul>{stage_list_html}</ul></div>")
            gaps = "".join(
                f"<li>{_ui.esc(gap['hint'])} "
                f"<a href=\"{_ui.esc(gap['href'])}\">Act →</a></li>"
                for gap in tree["gaps"])
            detail = (
                f"<p class=\"muted\">Growth: "
                f"{_ui.esc(tree['growth'])} · "
                f"{tree['stages_present']}/12 stages present. "
                f"{_ui.esc(tree['honesty'])}</p>"
                f"{_ui.growth_bar(tree['growth'], tree['growth'])}"
                f"<div class=\"craft\">{''.join(blocks)}</div>"
                + (f"<div class=\"panel\"><h2>What is missing?</h2>"
                    f"<ul>{gaps}</ul></div>" if gaps else "")
                + (f"<p class=\"muted\">{_ui.esc(tree['error'])}"
                    f"</p>" if tree.get("error") else ""))
        except (ValueError, InventoryRefusedError,
                InventoryUnavailable) as exc:
            detail = f"<div class=\"panel\"><p>{_ui.esc(str(exc))}</p></div>"
    else:
        stage_list = "".join(
            f"<span class=\"step\">{glyph} {title}</span>"
            f"<span class=\"arrow\">→</span>"
            for _, glyph, title in STAGES)
        detail = (
            f"<div class=\"panel\"><h2>This craft path has not "
            f"grown yet.</h2><div class=\"path\">{stage_list}</div>"
            f"<p class=\"muted\">Pick a project or object seed — "
            f"every node is a real record, every gap a real "
            f"next action.</p></div>")
    seeds_html = ""
    try:
        seeds = await _world_seeds()
        seeds_html = "".join(
            f"<a class=\"chip\" href=\"/craft?entity_id="
            f"{_ui.esc(item['id'])}\">{_ui.esc(item['label'])}</a>"
            for item in seeds[:8])
    except Exception:
        pass
    main = (f"<h1>Craft Tree — from idea to made thing 🌿</h1>"
            f"<p class=\"muted\">Gameplay over real records: ✓ "
            f"means evidence-backed, ! means blocked, ○ means "
            f"missing with a real next action. "
            f"<a href=\"/campaigns\">Campaigns</a> chain quests "
            f"across these stages; <a href=\"/game\">game view</a> "
            f"shows quest-linked chains.</p>"
            f"<div class=\"panel\"><form method=\"get\" "
            f"action=\"/craft\"><label>Entity "
            f"<input type=\"text\" name=\"entity_id\" "
            f"placeholder=\"proj_… / obj_… / idea_…\" value=\""
            f"{_ui.esc(entity_id)}\" style=\"width:16rem\"></label>"
            f"<button type=\"submit\">Grow</button></form>"
            f"<p class=\"flowline\">{seeds_html}</p></div>"
            f"{detail}")
    return _ui.shell("Craft Tree", "/craft",
                     _ui.living_bg() + main, _ui.command_bar())


# =============================================================================
# BIG #34 — CAMERA ECOSYSTEM. Files become living input:
# FILE → SESSION → OBSERVATION → VLM (or honest fallback) →
# CANDIDATE → POSSIBLE MATCH → LINK PROPOSAL (YES) → SYMBIOSIS
# → CRAFT → GUIDE. Camera never authority; observation never fact.
# =============================================================================


@app.post("/api/v1/camera-sessions", status_code=201)
def api_camera_session_create(body: dict) -> dict:
    from .camera_ecosystem import (EcosystemRefusedError,
                                   create_session)
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    try:
        session = create_session(str(body.get("device_id", "")),
                                 body.get("filenames", []))
    except EcosystemRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return session.model_dump(mode="json")


@app.get("/api/v1/camera-sessions")
def api_camera_sessions(device_id: str = "",
                        limit: int = 20) -> dict:
    from .camera_ecosystem import list_sessions
    sessions = list_sessions(device_id[:80], limit=limit)
    return {"sessions": [session.model_dump(mode="json")
                         for session in sessions]}


@app.get("/api/v1/camera-sessions/{session_id}")
def api_camera_session_get(session_id: str) -> dict:
    from .camera_ecosystem import (EcosystemRefusedError,
                                   load_session,
                                   session_observations)
    try:
        session = load_session(session_id)
    except EcosystemRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if session is None:
        raise HTTPException(404, "Ingest session not found")
    return {"session": session.model_dump(mode="json"),
            "observations": session_observations(session.session_id)}


@app.post("/api/v1/camera-sessions/{session_id}/run")
def api_camera_session_run(session_id: str) -> dict:
    from .camera_ecosystem import (EcosystemRefusedError,
                                   run_session,
                                   session_observations)
    try:
        session = run_session(session_id)
    except EcosystemRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"session": session.model_dump(mode="json"),
            "observations": session_observations(session.session_id)}


@app.post("/api/v1/observations/{observation_id}/describe")
def api_observation_describe(observation_id: str,
                             body: dict | None = None) -> dict:
    from .camera_ecosystem import EcosystemRefusedError, \
        describe_observation
    payload = body if isinstance(body, dict) else {}
    try:
        return describe_observation(
            observation_id, question=str(payload.get("question", "")),
            provider=str(payload.get("provider", "auto")))
    except EcosystemRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/v1/observations/{observation_id}/propose-candidates",
          status_code=201)
def api_observation_propose(observation_id: str) -> dict:
    from .camera_ecosystem import (EcosystemRefusedError,
                                   propose_candidates)
    try:
        created = propose_candidates(observation_id)
    except EcosystemRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"observation_id": observation_id,
            "candidates": created,
            "note": "VLM labels became OBSERVATION candidates. "
                    "Nothing promotes itself."}


@app.get("/api/v1/camera-match")
def api_camera_match(q: str = "", limit: int = 5) -> dict:
    from .camera_ecosystem import (EcosystemRefusedError,
                                   possible_matches)
    try:
        matches = possible_matches(q[:120], limit=limit)
    except EcosystemRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"query": q[:120], "matches": matches,
            "note": "POSSIBLE matches only. Linking needs a "
                    "proposal + YES."}


@app.post("/api/v1/camera-suggest-link", status_code=201)
def api_camera_suggest_link(body: dict) -> dict:
    from .camera_ecosystem import (EcosystemRefusedError,
                                   suggest_link)
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    try:
        return suggest_link(str(body.get("observation_id", "")),
                            str(body.get("entity_id", "")),
                            str(body.get("predicate", "")))
    except EcosystemRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/camera-timeline")
def api_camera_timeline(device_id: str = "",
                        observation_id: str = "",
                        limit: int = 30) -> dict:
    from .camera_ecosystem import EcosystemRefusedError, timeline
    try:
        items = timeline(device_id[:80], observation_id[:80],
                         limit=limit)
    except EcosystemRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"timeline": items}


@app.post("/web/camera-sessions")
async def web_camera_session_create(request: Request) -> Response:
    from .camera_ecosystem import EcosystemRefusedError, create_session
    fields = await _form_fields(request)
    device_id = fields.get("device_id", "")
    raw = fields.get("filenames", "")
    filenames = [part.strip() for part in raw.replace(",", " ").split()
                 if part.strip()]
    try:
        session = create_session(device_id, filenames)
    except EcosystemRefusedError:
        return RedirectResponse("/cameras", status_code=303)
    try:
        from .camera_ecosystem import run_session
        run_session(session.session_id)
    except EcosystemRefusedError:
        pass
    return RedirectResponse(
        f"/cameras/{device_id}", status_code=303)


@app.post("/web/camera-sessions/{session_id}/run")
async def web_camera_session_run(session_id: str) -> Response:
    from .camera_ecosystem import (EcosystemRefusedError,
                                   load_session, run_session)
    try:
        session = run_session(session_id)
        target = f"/cameras/{session.device_id}"
    except EcosystemRefusedError:
        target = "/cameras"
        try:
            loaded = load_session(session_id)
            if loaded is not None:
                target = f"/cameras/{loaded.device_id}"
        except EcosystemRefusedError:
            pass
    return RedirectResponse(target, status_code=303)


@app.post("/web/observations/{observation_id}/describe")
async def web_observation_describe(observation_id: str,
                                   request: Request) -> Response:
    from .camera_ecosystem import (EcosystemRefusedError,
                                   describe_observation)
    fields = await _form_fields(request)
    device_id = fields.get("device_id", "")
    try:
        describe_observation(
            observation_id,
            question=fields.get("question", "")[:500])
    except EcosystemRefusedError:
        pass
    target = f"/cameras/{device_id}" if device_id else "/cameras"
    return RedirectResponse(target, status_code=303)


@app.post("/web/observations/{observation_id}/propose-candidates")
async def web_observation_propose(observation_id: str,
                                  request: Request) -> Response:
    from .camera_ecosystem import (EcosystemRefusedError,
                                   propose_candidates)
    fields = await _form_fields(request)
    device_id = fields.get("device_id", "")
    try:
        propose_candidates(observation_id)
    except EcosystemRefusedError:
        pass
    target = f"/cameras/{device_id}" if device_id else "/cameras"
    return RedirectResponse(target, status_code=303)


@app.post("/web/camera-suggest-link")
async def web_camera_suggest_link(request: Request) -> Response:
    from .camera_ecosystem import (EcosystemRefusedError,
                                   suggest_link)
    fields = await _form_fields(request)
    device_id = fields.get("device_id", "")
    try:
        suggest_link(fields.get("observation_id", ""),
                     fields.get("entity_id", ""),
                     fields.get("predicate", "related_to"))
    except EcosystemRefusedError:
        pass
    target = f"/cameras/{device_id}" if device_id else "/cameras"
    return RedirectResponse(target, status_code=303)


# =============================================================================
# BIG #35 — 3D WORKSHOP ECOSYSTEM. Models become living citizens:
# MODEL ↔ OBJECT ↔ MATERIAL ↔ PROJECT ↔ IDEA ↔ MACHINE ↔
# FABRICATION ↔ OBSERVATION ↔ VERIFICATION ↔ KNOWLEDGE ↔
# SYMBIOSIS ↔ CRAFT. Workshop metadata only; relationships are
# connection candidates; prints need the existing YES flow.
# =============================================================================


@app.post("/api/v1/workshop/models", status_code=201)
def api_workshop_model_register(body: dict) -> dict:
    from .workshop3d import WorkshopRefusedError, register_model
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    try:
        return register_model(str(body.get("filename", "")),
                              source=str(body.get("source", "inbox")))
    except WorkshopRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/workshop/models")
def api_workshop_models(limit: int = 50) -> dict:
    from .workshop3d import list_models
    return {"models": list_models(limit=limit)}


@app.post("/api/v1/workshop/models/{model_id}/inspect")
def api_workshop_model_inspect(model_id: str) -> dict:
    from .workshop3d import WorkshopRefusedError, inspect_model
    try:
        return inspect_model(model_id)
    except WorkshopRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/v1/workshop/materials", status_code=201)
def api_workshop_material_create(body: dict) -> dict:
    from .workshop3d import WorkshopRefusedError, create_material
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    try:
        return create_material(
            str(body.get("name", "")),
            kind=str(body.get("kind", "filament")),
            state=str(body.get("state", "unknown")),
            notes=str(body.get("notes", "")),
            sustainability_note=str(body.get("sustainability_note",
                                             "")),
            linked_entity=str(body.get("linked_entity", "")))
    except WorkshopRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/workshop/materials")
def api_workshop_materials(limit: int = 50) -> dict:
    from .workshop3d import list_materials
    return {"materials": list_materials(limit=limit)}


@app.get("/api/v1/workshop/materials/suggest")
def api_workshop_material_suggest(model_id: str = "",
                                  limit: int = 5) -> dict:
    from .workshop3d import WorkshopRefusedError, suggest_materials
    try:
        suggestions = suggest_materials(model_id, limit=limit)
    except WorkshopRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"model_id": model_id[:80], "suggestions": suggestions,
            "note": "Suggestions, never assignments."}


@app.post("/api/v1/workshop/links", status_code=201)
def api_workshop_link(body: dict) -> dict:
    from .workshop3d import WorkshopRefusedError, propose_workshop_link
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    try:
        return propose_workshop_link(
            str(body.get("workshop_id", "")),
            str(body.get("entity_id", "")),
            str(body.get("predicate", "")))
    except WorkshopRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/v1/workshop/fabjobs", status_code=201)
def api_workshop_fabjob_create(body: dict) -> dict:
    from .workshop3d import WorkshopRefusedError, create_fabjob
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="JSON body required")
    try:
        return create_fabjob(
            str(body.get("model_id", "")),
            material_ref=str(body.get("material_ref", "")),
            printer_id=str(body.get("printer_id", "")),
            profile=str(body.get("profile", "")),
            actor=str(body.get("actor", "api")))
    except WorkshopRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/workshop/fabjobs")
def api_workshop_fabjobs(limit: int = 50) -> dict:
    from .workshop3d import list_fabjobs
    return {"fabjobs": list_fabjobs(limit=limit)}


@app.get("/api/v1/workshop/fabjobs/{job_id}")
def api_workshop_fabjob_get(job_id: str) -> dict:
    from .workshop3d import WorkshopRefusedError, get_fabjob
    try:
        job = get_fabjob(job_id)
    except WorkshopRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if job is None:
        raise HTTPException(404, "Fab job not found")
    return job


@app.post("/api/v1/workshop/fabjobs/{job_id}/{action}")
def api_workshop_fabjob_action(job_id: str, action: str,
                               body: dict | None = None) -> dict:
    from .workshop3d import (WorkshopRefusedError, cancel_job,
                             observe_job, prepare_job, propose_job_print,
                             slice_job, sync_job, verify_job)
    payload = body if isinstance(body, dict) else {}
    try:
        if action == "prepare":
            return prepare_job(job_id)
        if action == "slice":
            return slice_job(
                job_id,
                slicer=str(payload.get("slicer", "test-slicer")))
        if action == "propose":
            return propose_job_print(
                job_id, actor=str(payload.get("actor", "api")))
        if action == "sync":
            return sync_job(job_id)
        if action == "observe":
            return observe_job(
                job_id, str(payload.get("observation_id", "")))
        if action == "verify":
            return verify_job(
                job_id, verified_by=str(payload.get("verified_by",
                                                    "")))
        if action == "cancel":
            return cancel_job(
                job_id, reason=str(payload.get("reason", "")))
    except WorkshopRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    raise HTTPException(
        status_code=422,
        detail="action must be prepare, slice, propose, sync, "
               "observe, verify or cancel")


@app.get("/api/v1/workshop/presence")
def api_workshop_presence(entity_id: str = "") -> dict:
    from .workshop3d import WorkshopRefusedError, workshop_presence
    try:
        return workshop_presence(entity_id)
    except WorkshopRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/workshop/packet")
def api_workshop_packet(project_id: str = "") -> dict:
    from .workshop3d import workshop_packet
    return workshop_packet(project_id[:100])


@app.get("/forge", response_class=HTMLResponse)
def forge_studio_page() -> str:
    """Forge Studio: zelfstandige 3D-werkplek (vertical slice 1).

    Dunne pagina over bestaande contracten: lezen via
    GET /api/v1/forge/session, schrijven uitsluitend via de
    bestaande gated flows (/writes, /web/workshop/*). De
    NPC-presentatie blijft in /play."""
    from .forge import studio_page
    return studio_page()


@app.get("/api/v1/forge/session")
async def api_forge_session() -> dict:
    """Read-only Forge editor bootstrap: default session shape,
    procedural primitives (bestaande CAD-builders), workshop
    snapshot, INVENTory browse, printers, slicer-honesty en de
    Forge-identity. Kleine GET, geen nieuwe registry."""
    from .forge import (default_session, forge_identity,
                        inventory_snapshot, primitive_facets,
                        printer_summary, slicer_status,
                        workshop_snapshot)
    primitives = {}
    for name in ("cube", "cylinder"):
        try:
            primitives[name] = primitive_facets(name)
        except ValueError:
            continue
    return {
        "session": default_session(),
        "primitives": primitives,
        "workshop": workshop_snapshot(),
        "inventory": await inventory_snapshot(),
        "printers": printer_summary(),
        "slicer": slicer_status(),
        "identity": forge_identity(),
        "honesty": "bestaande stores only; lege stores = leeg, "
                   "nooit verzonnen",
    }


@app.post("/api/v1/forge/ask")
async def api_forge_ask(request: Request) -> dict:
    """Ask Forge: READ / ADVISE / PROPOSE only. Pure helper, geen
    writes, geen approvals, geen uitvoering."""
    from .forge import ask_forge
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=422,
                            detail="invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422,
                            detail="invalid JSON body")
    try:
        return ask_forge(body.get("question", ""))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/forge/save", status_code=201)
async def api_forge_save(request: Request) -> dict:
    """Persist Forge editor geometry the existing way: merged
    facets via the cad/mesh3d/meshops builders, a local derived
    working file (same precedent as fab/transform persist) and
    an inert file_payload for the existing writes gate.

    Working file only: creates no proposal, no approval, no
    execution, no registration. The client posts file_payload
    to POST /api/v1/writes/inventory itself."""
    from .forge import ForgeGeometryError, save_editor_geometry
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=422,
                            detail="invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422,
                            detail="invalid JSON body")
    try:
        return save_editor_geometry(
            body.get("design_name", ""),
            body.get("parts", []),
            body.get("forked_from", {}),
            body.get("ai_edits", None))
    except ForgeGeometryError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.get("/api/v1/forge/library")
async def api_forge_library(limit: int = 8) -> dict:
    """Read-only Forge model library: workshop registry,
    INVENTory browse (best-effort), unregistered local mesh
    files, and the honest external NOT_CONNECTED stub. Small
    GET, no new registry, nothing stored."""
    from .forge import forge_library
    return await forge_library(limit)


@app.post("/api/v1/forge/open")
async def api_forge_open(request: Request) -> dict:
    """Import one existing model into Forge editor state.
    Read-only source: workshop/local read existing mesh bytes,
    inventory resolves metadata + provenance via the existing
    read bridge (geometry only when local bytes exist),
    external refuses honestly. Writes nothing, registers
    nothing, proposes nothing."""
    from .forge import (ForgeGeometryError, ForgeUpstreamError,
                        open_inventory_model, open_model)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=422,
                            detail="invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422,
                            detail="invalid JSON body")
    source = str(body.get("source", "")).strip().lower()
    try:
        if source == "inventory":
            return await open_inventory_model(
                body.get("entity_type", ""),
                body.get("ref", ""))
        return open_model(source, body.get("ref", ""))
    except ForgeGeometryError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except ForgeUpstreamError:
        raise HTTPException(status_code=502,
                            detail="INVENTory unavailable")


@app.post("/api/v1/forge/propose")
async def api_forge_propose(request: Request) -> dict:
    """Selection-aware AI edit proposal over editor geometry.
    Pure: validates scene + selection + intent through the
    existing meshops/mesh3d/editor checkers, returns a
    structured proposal with preview + APPLY patch. APPLY and
    DISCARD stay client-side; this route never writes, never
    proposes canonically, never approves, never executes."""
    from .forge import ForgeGeometryError, propose_edit
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=422,
                            detail="invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422,
                            detail="invalid JSON body")
    try:
        return propose_edit(
            body.get("selection", []),
            body.get("prompt", ""),
            body.get("parts", []),
            body.get("op", ""),
            body.get("params", None))
    except ForgeGeometryError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/web/workshop/models")
async def web_workshop_model_register(request: Request) -> Response:
    from .workshop3d import WorkshopRefusedError, register_model
    fields = await _form_fields(request)
    try:
        model = register_model(fields.get("filename", ""),
                               source="inbox")
        from .workshop3d import inspect_model
        try:
            inspect_model(model["model_id"])
        except WorkshopRefusedError:
            pass
    except WorkshopRefusedError:
        pass
    return RedirectResponse("/3d", status_code=303)


@app.post("/web/workshop/materials")
async def web_workshop_material_create(request: Request) -> Response:
    from .workshop3d import WorkshopRefusedError, create_material
    fields = await _form_fields(request)
    try:
        create_material(
            fields.get("name", ""),
            kind=fields.get("kind", "filament") or "filament",
            state=fields.get("state", "unknown") or "unknown",
            notes=fields.get("notes", ""),
            sustainability_note=fields.get("sustainability_note",
                                           ""))
    except WorkshopRefusedError:
        pass
    return RedirectResponse("/3d", status_code=303)


@app.post("/web/workshop/fabjobs")
async def web_workshop_fabjob_create(request: Request) -> Response:
    from .workshop3d import WorkshopRefusedError, create_fabjob
    fields = await _form_fields(request)
    try:
        create_fabjob(
            fields.get("model_id", ""),
            material_ref=fields.get("material_ref", ""),
            printer_id=fields.get("printer_id", ""),
            profile=fields.get("profile", ""), actor="web")
    except WorkshopRefusedError:
        pass
    return RedirectResponse("/3d", status_code=303)


@app.post("/web/workshop/fabjobs/{job_id}/{action}")
async def web_workshop_fabjob_action(job_id: str, action: str,
                                     request: Request) -> Response:
    from .workshop3d import (WorkshopRefusedError, cancel_job,
                             observe_job, prepare_job,
                             propose_job_print, slice_job, sync_job,
                             verify_job)
    fields = await _form_fields(request)
    try:
        if action == "prepare":
            prepare_job(job_id)
        elif action == "slice":
            slice_job(job_id, slicer=fields.get("slicer",
                                                "test-slicer"))
        elif action == "propose":
            propose_job_print(job_id, actor="web")
        elif action == "sync":
            sync_job(job_id)
        elif action == "observe":
            observe_job(job_id, fields.get("observation_id", ""))
        elif action == "verify":
            verify_job(job_id,
                       verified_by=fields.get("verified_by", ""))
        elif action == "cancel":
            cancel_job(job_id, reason=fields.get("reason", ""))
    except WorkshopRefusedError:
        pass
    return RedirectResponse("/3d", status_code=303)


@app.post("/web/workshop/links")
async def web_workshop_link(request: Request) -> Response:
    from .workshop3d import WorkshopRefusedError, propose_workshop_link
    fields = await _form_fields(request)
    try:
        propose_workshop_link(fields.get("workshop_id", ""),
                              fields.get("entity_id", ""),
                              fields.get("predicate",
                                         "related_to"))
    except WorkshopRefusedError:
        pass
    return RedirectResponse("/3d", status_code=303)


# =============================================================================
# BIG #42 — ECOSYSTEM HARDENING + FIRST V2 WORKFLOWS.
# Human hardware links, finance/energy stores, quest trails,
# bounded mesh workflows. Thin glue over existing gates: every
# consequential action keeps its existing approval/operator gate,
# VERIFIED is never derived, amounts/measurements stay UNKNOWN
# unless explicitly recorded.
# =============================================================================


def _require_operator(operator_key: str) -> None:
    from .nodes import NodeAuthError, check_operator_key
    try:
        check_operator_key(operator_key)
    except NodeAuthError:
        raise HTTPException(status_code=403,
                            detail="operator authorization rejected")


@app.post("/api/v1/hardware/links", status_code=201)
def api_hardware_link_propose(body: HardwareLinkBody) -> dict:
    """Propose a human hardware link. Always starts PROPOSED —
    proposing never verifies, and a node token is never enough
    to verify later."""
    from .hardware_links import HardwareLinkRefusedError, audit_propose, \
        new_link, save_link
    try:
        link = new_link(human_ref=body.human_ref,
                        node_id=body.node_id,
                        device_ref=body.device_ref,
                        device_kind=body.device_kind,
                        capability=body.capability,
                        evidence=body.evidence)
    except HardwareLinkRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    with connection() as db:
        row = db.execute(
            "SELECT node_id FROM nodes WHERE node_id=?",
            (link.node_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Node is not registered")
    save_link(link)
    audit_propose(link)
    logger.info("hardware_link_proposed link_id=%s node=%s",
                link.link_id, link.node_id)
    return link.model_dump(mode="json")


@app.get("/api/v1/hardware/links")
def api_hardware_links(node_id: str = "", status: str = "",
                       limit: int = 100) -> dict:
    from .hardware_links import HardwareLinkRefusedError, list_links
    try:
        links = list_links(node_id=node_id, status=status,
                           limit=limit)
    except HardwareLinkRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"links": [link.model_dump(mode="json")
                      for link in links]}


@app.get("/api/v1/hardware/links/{link_id}")
def api_hardware_link_get(link_id: str) -> dict:
    from .hardware_links import get_link
    link = get_link(link_id)
    if link is None:
        raise HTTPException(404, "Hardware link not found")
    return link.model_dump(mode="json")


@app.post("/api/v1/hardware/links/{link_id}/verify")
def api_hardware_link_verify(link_id: str,
                             body: HardwareVerifyBody) -> dict:
    """Verify a PROPOSED link. Operator key required — node
    credentials are never accepted here, so a device cannot
    self-verify. REVOKED links stay revoked."""
    from .hardware_links import HardwareLinkRefusedError, get_link, \
        verify_link
    _require_operator(body.operator_key)
    try:
        link = verify_link(link_id, verified_by=body.verified_by)
    except HardwareLinkRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if link is None:
        raise HTTPException(404, "Hardware link not found")
    logger.info("hardware_link_verified link_id=%s by=%s",
                link.link_id, link.verified_by)
    return link.model_dump(mode="json")


@app.post("/api/v1/hardware/links/{link_id}/revoke")
def api_hardware_link_revoke(link_id: str,
                             body: HardwareRevokeBody) -> dict:
    from .hardware_links import HardwareLinkRefusedError, revoke_link
    _require_operator(body.operator_key)
    try:
        link = revoke_link(link_id, revoked_by=body.revoked_by,
                           reason=body.reason)
    except HardwareLinkRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if link is None:
        raise HTTPException(404, "Hardware link not found")
    logger.info("hardware_link_revoked link_id=%s", link.link_id)
    return link.model_dump(mode="json")


@app.post("/api/v1/finance/records", status_code=201)
def api_finance_create(body: FinanceRecordBody) -> dict:
    """Record one finance fact. Explicit figures only; an omitted
    amount stays UNKNOWN (never zero, never invented)."""
    from .finance import FinanceRefusedError, new_record, save_record
    try:
        record = new_record(kind=body.kind, title=body.title,
                            amount_minor=body.amount_minor,
                            currency=body.currency,
                            project_ref=body.project_ref,
                            note=body.note,
                            recorded_by=body.recorded_by)
    except FinanceRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    save_record(record)
    logger.info("finance_recorded record_id=%s kind=%s",
                record.record_id, record.kind)
    return record.model_dump(mode="json")


@app.get("/api/v1/finance/records")
def api_finance_list(project_ref: str = "", kind: str = "",
                     status: str = "", limit: int = 100) -> dict:
    from .finance import FinanceRefusedError, list_records
    try:
        records = list_records(project_ref=project_ref, kind=kind,
                               status=status, limit=limit)
    except FinanceRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"records": [record.model_dump(mode="json")
                        for record in records]}


@app.get("/api/v1/finance/records/{record_id}")
def api_finance_get(record_id: str) -> dict:
    from .finance import get_record
    record = get_record(record_id)
    if record is None:
        raise HTTPException(404, "Finance record not found")
    return record.model_dump(mode="json")


@app.post("/api/v1/finance/records/{record_id}/status")
def api_finance_status(record_id: str,
                       body: FinanceStatusBody) -> dict:
    from .finance import FinanceRefusedError, set_status
    try:
        record = set_status(record_id, body.status)
    except FinanceRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if record is None:
        raise HTTPException(404, "Finance record not found")
    return record.model_dump(mode="json")


@app.get("/api/v1/finance/summary")
def api_finance_summary(project_ref: str = "") -> dict:
    from .finance import summarize
    return {"project_ref": project_ref,
            "summary": summarize(project_ref=project_ref)}


@app.post("/api/v1/energy/records", status_code=201)
def api_energy_create(body: EnergyRecordBody) -> dict:
    """Record one energy observation. An omitted value stays
    UNKNOWN — measurements are never invented."""
    from .energy import EnergyRefusedError, new_record, save_record
    try:
        record = new_record(source=body.source, kind=body.kind,
                            value=body.value, unit=body.unit,
                            project_ref=body.project_ref,
                            device_ref=body.device_ref,
                            note=body.note,
                            recorded_by=body.recorded_by)
    except EnergyRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    save_record(record)
    logger.info("energy_recorded record_id=%s source=%s",
                record.record_id, record.source)
    return record.model_dump(mode="json")


@app.get("/api/v1/energy/records")
def api_energy_list(project_ref: str = "", device_ref: str = "",
                    source: str = "", kind: str = "",
                    limit: int = 100) -> dict:
    from .energy import EnergyRefusedError, list_records
    try:
        records = list_records(project_ref=project_ref,
                               device_ref=device_ref,
                               source=source, kind=kind,
                               limit=limit)
    except EnergyRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"records": [record.model_dump(mode="json")
                        for record in records]}


@app.get("/api/v1/energy/records/{record_id}")
def api_energy_get(record_id: str) -> dict:
    from .energy import get_record
    record = get_record(record_id)
    if record is None:
        raise HTTPException(404, "Energy record not found")
    return record.model_dump(mode="json")


@app.get("/api/v1/energy/state")
def api_energy_state(project_ref: str = "",
                     device_ref: str = "") -> dict:
    from .energy import current_state
    return {"project_ref": project_ref, "device_ref": device_ref,
            **current_state(project_ref=project_ref,
                            device_ref=device_ref)}


@app.get("/api/v1/energy/summary")
def api_energy_summary(project_ref: str = "") -> dict:
    from .energy import summarize
    return {"project_ref": project_ref,
            "summary": summarize(project_ref=project_ref)}


@app.post("/api/v1/quests", status_code=201)
def api_quest_create(body: QuestCreateBody) -> dict:
    """Define a quest trail over real records. State always
    derives on read — the def stores refs only."""
    from .quests import QuestRefusedError, new_quest, quest_detail, \
        save_quest
    try:
        quest = new_quest(body.title, body.steps)
    except QuestRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    save_quest(quest)
    logger.info("quest_created quest_id=%s", quest.quest_id)
    return quest_detail(quest)


@app.get("/api/v1/quests")
def api_quests(limit: int = 50) -> dict:
    from .quests import list_quest_details
    return {"quests": list_quest_details(limit=limit)}


@app.get("/api/v1/quests/{quest_id}")
def api_quest_get(quest_id: str) -> dict:
    from .quests import get_quest, quest_detail
    quest = get_quest(quest_id)
    if quest is None:
        raise HTTPException(404, "Quest not found")
    return quest_detail(quest)


@app.post("/api/v1/quests/{quest_id}/refresh")
def api_quest_refresh(quest_id: str) -> dict:
    """Re-derive quest state now (read-only; emits an audit event
    so refreshes stay traceable)."""
    from .events import new_event as _bus_new, save_event as _bus_save
    from .quests import get_quest, quest_detail
    quest = get_quest(quest_id)
    if quest is None:
        raise HTTPException(404, "Quest not found")
    detail = quest_detail(quest)
    try:
        _bus_save(_bus_new(
            "quest.updated",
            f"Quest {quest_id} refreshed: "
            f"{detail['done']}/{detail['total']} "
            f"[{detail['state']}]",
            payload={"quest_id": quest_id,
                     "state": detail["state"]}))
    except Exception:
        pass
    return detail


@app.delete("/api/v1/quests/{quest_id}")
def api_quest_delete(quest_id: str) -> dict:
    from .quests import delete_quest
    if not delete_quest(quest_id):
        raise HTTPException(404, "Quest not found")
    return {"quest_id": quest_id, "deleted": True}


@app.post("/api/v1/workflows/dispatch", status_code=201)
def api_workflow_dispatch(body: WorkflowDispatchBody) -> dict:
    """Dispatch a bounded multi-node workflow (BIG #42 remote mesh
    workflows): research on Node A, camera work on Node B, compute
    on Node C — each step one pinned mesh delegation through the
    existing task queue.

    The coordinator stays authoritative (capability validation,
    target validation, leases, retries, task state, provenance);
    nodes stay pull-based. Steps dispatch in order; a failed step
    stops the workflow and rolls back nothing already queued
    (queued tasks keep their own lease/claim lifecycle and stay
    visible — never silently dropped). Max 6 steps, no
    wildcards, no shell, no secret forwarding (same closed
    contracts as /mesh/delegate)."""
    from .nodemesh import validate_delegation
    from .routing import check_requirements
    _mesh_authenticate(body.requesting_node, body.node_token)
    if not isinstance(body.steps, list) or not body.steps:
        raise HTTPException(status_code=422,
                            detail="workflow needs at least one step")
    if len(body.steps) > 6:
        raise HTTPException(status_code=422,
                            detail="workflow has at most 6 steps")
    mission_id = str(body.mission_id or "").strip()[:80]
    receipts: list = []
    created_ids: list = []
    for index, raw in enumerate(body.steps):
        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=422,
                detail=f"step {index} must be an object")
        task_kind = str(raw.get("task_kind", ""))
        capability = str(raw.get("capability", ""))
        target = str(raw.get("target_node", ""))
        if not target:
            raise HTTPException(
                status_code=422,
                detail=f"step {index} pins an explicit target_node")
        try:
            timeout = int(raw.get("timeout_seconds", 60))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail=f"step {index} timeout must be an integer")
        reason = str(raw.get("reason", ""))[:2000]
        try:
            priority = int(raw.get("priority", 0))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail=f"step {index} priority must be an integer")
        if priority < -10 or priority > 10:
            raise HTTPException(
                status_code=422,
                detail=f"step {index} priority is -10..10")
        try:
            checked = validate_delegation(
                body.requesting_node, task_kind, capability,
                raw.get("payload") if isinstance(
                    raw.get("payload"), dict) else {},
                target_node=target, timeout_seconds=timeout,
                reason=reason)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=
                                f"step {index} refused: {exc}")
        try:
            requirements = check_requirements(
                {"required_capabilities": [checked["capability"]]})
            decision = _decision_for(0, requirements, {},
                                     only_node=checked["target_node"])
        except (HTTPException, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail=f"step {index} target not currently "
                       f"eligible; workflow stopped ({exc})")
        if decision.selected_node_id != checked["target_node"]:
            raise HTTPException(
                status_code=409,
                detail=f"step {index} target not currently "
                       "eligible; workflow stopped")
        created = create_task(TaskCreate(
            kind=checked["task_kind"],
            payload=dict(checked["payload"]),
            required_capabilities=[checked["capability"]],
            priority=priority,
            requirements={"required_capabilities":
                          [checked["capability"]]}))
        task_id = int(created["id"])
        try:
            assign_task(task_id, TaskAssignBody(
                node_id=checked["target_node"], policy={}))
        except HTTPException as exc:
            with connection() as db:
                db.execute("DELETE FROM tasks WHERE id=? AND "
                           "status='queued'", (task_id,))
            raise HTTPException(
                status_code=409,
                detail=f"step {index} target refused at assign; "
                       f"workflow stopped ({exc.detail})")
        created_ids.append(task_id)
        receipts.append({"step": index,
                         **_mesh_receipt(task_id, checked)})
    try:
        from .events import new_event as _bus_new, \
            save_event as _bus_save
        _bus_save(_bus_new(
            "workflow.dispatched",
            f"Workflow from {body.requesting_node}: "
            f"{len(receipts)} step(s)"
            + (f" for mission {mission_id}" if mission_id else ""),
            mission_id=mission_id,
            node_id=body.requesting_node,
            payload={"steps": len(receipts),
                     "task_ids": [str(task_id)
                                  for task_id in created_ids][:6]}))
    except Exception:
        pass
    logger.info("workflow_dispatched from=%s steps=%s tasks=%s",
                body.requesting_node, len(receipts), created_ids)
    return {"mission_id": mission_id,
            "requesting_node": body.requesting_node,
            "task_ids": created_ids, "receipts": receipts,
            "steps_dispatched": len(receipts)}


@app.post("/api/v1/workflows/preview")
def api_workflow_preview(body: WorkflowDispatchBody) -> dict:
    """Dry-run a workflow: validate every step, create nothing."""
    from .nodemesh import validate_delegation
    _mesh_authenticate(body.requesting_node, body.node_token)
    if not isinstance(body.steps, list) or not body.steps:
        raise HTTPException(status_code=422,
                            detail="workflow needs at least one step")
    if len(body.steps) > 6:
        raise HTTPException(status_code=422,
                            detail="workflow has at most 6 steps")
    checked_steps: list = []
    for index, raw in enumerate(body.steps):
        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=422,
                detail=f"step {index} must be an object")
        try:
            checked = validate_delegation(
                body.requesting_node,
                str(raw.get("task_kind", "")),
                str(raw.get("capability", "")),
                raw.get("payload") if isinstance(
                    raw.get("payload"), dict) else {},
                target_node=str(raw.get("target_node", "")) or None,
                timeout_seconds=int(raw.get("timeout_seconds", 60)),
                reason=str(raw.get("reason", ""))[:2000])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=
                                f"step {index} refused: {exc}")
        if not checked.get("target_node"):
            raise HTTPException(
                status_code=422,
                detail=f"step {index} pins an explicit target_node")
        checked_steps.append({"step": index, **checked})
    return {"valid": True, "steps": checked_steps, "created": False}


@app.get("/hardware", response_class=HTMLResponse)
def hardware_page(node_id: str = "") -> str:
    """Human hardware links: proposed → verified (operator) →
    revoked. VERIFIED never derives automatically."""
    from . import ui as _ui
    from .hardware_links import list_links
    try:
        links = list_links(
            node_id=node_id.strip()[:80] if node_id else "",
            limit=100)
    except Exception:
        links = []
    rows = []
    for link in links:
        data = link.model_dump(mode="json")
        rows.append(
            f"<div class=\"panel\"><h3>{_ui.esc(data['link_id'])} "
            f"[{_ui.esc(data['status'])}]</h3>"
            f"<p>Node <a href=\"/nodes\">{_ui.esc(data['node_id'])}</a> · "
            f"device {_ui.esc(data['device_ref'])} "
            f"({_ui.esc(data['device_kind'] or 'unknown kind')})</p>"
            f"<p class=\"muted\">proposed by "
            f"{_ui.esc(data['human_ref'])}"
            + (f" · verified by {_ui.esc(data['verified_by'])}"
               if data["verified_by"] else "")
            + (f" · evidence: {_ui.esc(data['evidence'][:160])}"
               if data["evidence"] else "")
            + "</p></div>")
    main = (f"<h1>Hardware verification 🔗</h1>"
            f"<p class=\"muted\">ADVERTISED (node said so) → "
            f"OBSERVED (connected + fresh) → VERIFIED (human link "
            f"only). Propose below; verification needs the operator "
            f"key and never happens automatically.</p>"
            + ("".join(rows) if rows else
               "<p class=\"muted\">No links yet. Propose the first "
               "one via POST /api/v1/hardware/links.</p>")
            + "<p><a href=\"/nodes\">Nodes</a> · "
            "<a href=\"/guide\">Guide</a></p>")
    return _ui.shell("Hardware verification", "/hardware", main,
                     "", _ui.living_bg())


@app.get("/finance", response_class=HTMLResponse)
def finance_page(project_ref: str = "") -> str:
    """Finance records: counts + statuses. Amounts render only
    from this scoped page, never from generic telemetry."""
    from . import ui as _ui
    from .finance import list_records, summarize
    try:
        records = list_records(
            project_ref=project_ref.strip()[:120]
            if project_ref else "", limit=100)
        summary = summarize(
            project_ref=project_ref.strip()[:120]
            if project_ref else "")
    except Exception:
        records = []
        summary = {"total": 0, "by_kind": {},
                   "unknown_amounts": 0}
    rows = []
    for record in records:
        data = record.model_dump(mode="json")
        amount = ("UNKNOWN" if data["amount_minor"] is None
                  else f"{data['amount_minor']} "
                       f"{_ui.esc(data['currency'])}")
        rows.append(
            f"<div class=\"panel\"><h3>{_ui.esc(data['title'])} "
            f"[{_ui.esc(data['kind'])} · {_ui.esc(data['status'])}]"
            f"</h3><p>{amount}"
            + (f" · project {_ui.esc(data['project_ref'])}"
               if data["project_ref"] else "")
            + "</p></div>")
    main = (f"<h1>Finance 💰</h1>"
            f"<p class=\"muted\">{summary['total']} records "
            f"({summary.get('unknown_amounts', 0)} unknown amounts). "
            f"Minimal records — not accounting software.</p>"
            + ("".join(rows) if rows else
               "<p class=\"muted\">No finance records yet.</p>")
            + "<p><a href=\"/symbiosis\">Symbiosis</a> · "
            "<a href=\"/guide\">Guide</a></p>")
    return _ui.shell("Finance", "/finance", main, "",
                     _ui.living_bg())


@app.get("/energy", response_class=HTMLResponse)
def energy_page(project_ref: str = "") -> str:
    """Energy records + current state. Unknown values stay
    UNKNOWN — never invented."""
    from . import ui as _ui
    from .energy import current_state, list_records
    ref = project_ref.strip()[:120] if project_ref else ""
    try:
        records = list_records(project_ref=ref, limit=100)
        state = current_state(project_ref=ref)
    except Exception:
        records = []
        state = {"states": [], "state": "UNKNOWN", "count": 0}
    rows = []
    for record in records:
        data = record.model_dump(mode="json")
        value = ("UNKNOWN" if data["value"] is None
                 else f"{data['value']} {_ui.esc(data['unit'])}")
        rows.append(
            f"<div class=\"panel\"><h3>"
            f"{_ui.esc(data['source'])}/{_ui.esc(data['kind'])}"
            f"</h3><p>{value}"
            + (f" · project {_ui.esc(data['project_ref'])}"
               if data["project_ref"] else "")
            + "</p></div>")
    main = (f"<h1>Energy ⚡</h1>"
            f"<p class=\"muted\">Current state: "
            f"{_ui.esc(str(state.get('state', 'UNKNOWN')))} "
            f"({state.get('count', 0)} state records). "
            f"Unknown stays unknown.</p>"
            + ("".join(rows) if rows else
               "<p class=\"muted\">No energy records yet.</p>")
            + "<p><a href=\"/symbiosis\">Symbiosis</a> · "
            "<a href=\"/guide\">Guide</a></p>")
    return _ui.shell("Energy", "/energy", main, "",
                     _ui.living_bg())


@app.get("/quests", response_class=HTMLResponse)
def quests_page() -> str:
    """Quest trails: real progress (done/total) over real records.
    Clicking a step opens the underlying entity/task/mission."""
    from . import ui as _ui
    from .quests import list_quest_details
    try:
        quests = list_quest_details(limit=30)
    except Exception:
        quests = []
    cards = []
    for quest in quests:
        steps = []
        for step in quest.get("steps", []):
            steps.append(
                f"<li>{_ui.esc(step.get('glyph', '○'))} "
                f"<a href=\"{_ui.esc(step.get('href', '/quests'))}\">"
                f"{_ui.esc(step.get('label', ''))}</a> "
                f"<span class=\"muted\">"
                f"{_ui.esc(step.get('detail', ''))} · "
                f"{_ui.esc(step.get('readiness', ''))}: "
                f"{_ui.esc(step.get('readiness_reason', ''))}"
                f"</span></li>")
        cards.append(
            f"<div class=\"panel\"><h3>"
            f"{_ui.esc(quest.get('title', ''))} "
            f"[{_ui.esc(quest.get('state', ''))}] "
            f"{quest.get('done', 0)}/{quest.get('total', 0)}"
            f"</h3><ul>{''.join(steps)}</ul>"
            f"<p><a href=\"/api/v1/quests/{_ui.esc(quest.get('quest_id', ''))}\">"
            f"quest JSON</a></p></div>")
    main = (f"<h1>Quest trails 🌱</h1>"
            f"<p class=\"muted\">Real work, real progress — no XP. "
            f"Every step links to its underlying record.</p>"
            + ("".join(cards) if cards else
               "<p class=\"muted\">No quests yet. Create one via "
               "POST /api/v1/quests.</p>")
            + "<p><a href=\"/missions\">Missions</a> · "
            "<a href=\"/guide\">Guide</a> · "
            "<a href=\"/world\">World</a> · "
            "<a href=\"/campaigns\">Campaigns</a></p>")
    return _ui.shell("Quest trails", "/quests", main, "",
                     _ui.living_bg())


# =============================================================================
# BIG #43 — LIVING GAME LAYER. Presentation over real state.
# Campaigns group quests; the game-state endpoint aggregates;
# /game + /campaigns render the world as a living workshop.
# Nothing here approves, executes, or stores game truth.
# =============================================================================


@app.post("/api/v1/campaigns", status_code=201)
def api_campaign_create(body: CampaignCreateBody) -> dict:
    """Define a quest campaign over real quests. Unknown quest
    ids refuse — fake quests cannot enter."""
    from .campaigns import CampaignRefusedError, campaign_detail, \
        new_campaign, save_campaign
    try:
        campaign = new_campaign(body.title, body.quest_ids,
                                description=body.description)
    except CampaignRefusedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    save_campaign(campaign)
    logger.info("campaign_created campaign_id=%s quests=%s",
                campaign.campaign_id, len(campaign.quest_ids))
    return campaign_detail(campaign)


@app.get("/api/v1/campaigns")
def api_campaigns(limit: int = 50) -> dict:
    from .campaigns import list_campaign_details
    return {"campaigns": list_campaign_details(limit=limit)}


@app.get("/api/v1/campaigns/{campaign_id}")
def api_campaign_get(campaign_id: str) -> dict:
    from .campaigns import campaign_detail, get_campaign
    campaign = get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    return campaign_detail(campaign)


@app.post("/api/v1/campaigns/{campaign_id}/refresh")
def api_campaign_refresh(campaign_id: str) -> dict:
    """Re-derive campaign state now (read-only; audits so
    refreshes stay traceable)."""
    from .campaigns import campaign_detail, get_campaign
    from .events import new_event as _bus_new, save_event as _bus_save
    campaign = get_campaign(campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    detail = campaign_detail(campaign)
    try:
        _bus_save(_bus_new(
            "campaign.updated",
            f"Campaign {campaign_id} refreshed: "
            f"{detail['completed_count']}/"
            f"{detail['total_count']} [{detail['state']}]",
            payload={"campaign_id": campaign_id,
                     "state": detail["state"]}))
    except Exception:
        pass
    return detail


@app.delete("/api/v1/campaigns/{campaign_id}")
def api_campaign_delete(campaign_id: str) -> dict:
    from .campaigns import delete_campaign
    if not delete_campaign(campaign_id):
        raise HTTPException(404, "Campaign not found")
    return {"campaign_id": campaign_id, "deleted": True}


@app.get("/api/v1/game/state")
def api_game_state() -> dict:
    """Read-only derived game state (BIG #43 living game layer):
    world, campaigns, current quest, presence-as-stakes, craft,
    symbiosis, nodes, energy, workshop, discoveries. A view —
    no second database, no approvals, no execution."""
    from .game import game_state
    return game_state()


@app.get("/campaigns", response_class=HTMLResponse)
def campaigns_page() -> str:
    """Quest campaigns: chains of real quests with live counts,
    current quest, next action and evidence links. No XP."""
    from . import ui as _ui
    from .campaigns import list_campaign_details
    try:
        campaigns = list_campaign_details(limit=20)
    except Exception:
        campaigns = []
    cards = []
    for campaign in campaigns:
        chain = []
        for view in campaign.get("quests", []):
            glyph = {"COMPLETED": "✓", "ACTIVE": "●",
                     "BLOCKED": "!", "FAILED": "!"}.get(
                view.get("state", ""), "○")
            chain.append(
                f"<div class=\"trail-stop trail-"
                f"{_ui.esc(view.get('state', 'WAITING').lower())}\">"
                f"<span class=\"trail-glyph\">{glyph}</span> "
                f"<a href=\"{_ui.esc(view.get('href', '/quests'))}\">"
                f"{_ui.esc(view.get('title', '')[:60])}</a> "
                f"<span class=\"muted\">"
                f"{_ui.esc(view.get('progress', '0/0'))}</span>"
                f"</div>")
        trail = ("<div class=\"trail\">" +
                 "<div class=\"trail-link\">↓</div>".join(chain) +
                 "</div>") if chain else ""
        nxt = campaign.get("next_action", {}) or {}
        next_line = (
            f"<p><b>Next:</b> {_ui.esc(nxt.get('step', ''))} "
            f"— <a href=\"{_ui.esc(nxt.get('href', '/quests'))}\">"
            f"open</a> <span class=\"muted\">"
            f"{_ui.esc(nxt.get('readiness_reason', ''))}</span></p>"
            if nxt.get("step") else
            "<p class=\"muted\">Nothing actionable — "
            "chain complete or empty.</p>")
        cards.append(
            f"<div class=\"panel campaign\">"
            f"<h3>🗺 {_ui.esc(campaign.get('title', ''))} "
            f"[{_ui.esc(campaign.get('state', ''))}] "
            f"{campaign.get('completed_count', 0)}/"
            f"{campaign.get('total_count', 0)}</h3>"
            + (f"<p class=\"muted\">"
               f"{_ui.esc(campaign.get('description', '')[:200])}"
               f"</p>" if campaign.get("description") else "")
            + trail + next_line +
            f"<p><a href=\"/api/v1/campaigns/"
            f"{_ui.esc(campaign.get('campaign_id', ''))}\">"
            f"campaign JSON</a> · "
            f"<a href=\"/game\">game view</a></p></div>")
    main = (f"<h1>Campaigns 🗺</h1>"
            f"<p class=\"muted\">Chains of real quests — every "
            f"step links to its record. No XP, no rewards, just "
            f"the workshop growing.</p>"
            + ("".join(cards) if cards else
               "<p class=\"muted\">No campaigns yet. Create one "
               "via POST /api/v1/campaigns with real quest "
               "ids.</p>")
            + "<p><a href=\"/quests\">Quests</a> · "
            "<a href=\"/game\">Game view</a> · "
            "<a href=\"/world\">World</a></p>")
    return _ui.shell("Campaigns", "/campaigns", main, "",
                     _ui.living_bg())


@app.get("/game", response_class=HTMLResponse)
def game_page() -> str:
    """Living game view: world state, current campaign + quest
    trail, craft progress, symbiosis strength, presence stakes,
    nodes, energy, workshop, discoveries. Every line links to
    its real record."""
    from . import ui as _ui
    from .game import game_state
    try:
        state = game_state()
    except Exception:
        state = {"sections": {}, "honesty": ""}
    sections = state.get("sections", {})

    def _section_data(key):
        return (sections.get(key, {}) or {}).get("data", {})

    world = _section_data("world")
    world_html = (
        f"<div class=\"panel\"><h2>🌱 World state</h2>"
        f"<p>{_ui.esc(world.get('glyph', ''))} "
        f"<b>{_ui.esc(world.get('line', 'quiet'))}</b></p></div>"
        if world else "")
    campaigns = _section_data("campaigns") or []
    if isinstance(campaigns, dict):
        campaigns = []
    campaign_cards = []
    for campaign in campaigns[:3]:
        current = campaign.get("current_quest", {}) or {}
        campaign_cards.append(
            f"<div class=\"panel campaign\">"
            f"<h3>🎯 {_ui.esc(campaign.get('title', ''))} "
            f"{campaign.get('completed_count', 0)}/"
            f"{campaign.get('total_count', 0)}</h3>"
            f"<p>Current: <a href=\""
            f"{_ui.esc(current.get('href', '/quests'))}\">"
            f"{_ui.esc(current.get('title', '—'))}</a> "
            f"({_ui.esc(current.get('progress', ''))})</p>"
            f"<p><a href=\"/campaigns\">all campaigns →</a></p>"
            f"</div>")
    campaign_html = "".join(campaign_cards)
    current_quest = _section_data("current_quest") or {}
    quest_html = ""
    if current_quest.get("quest_id"):
        quest_html = (
            f"<div class=\"panel\"><h2>🧭 Current quest</h2>"
            f"<p><a href=\""
            f"{_ui.esc(current_quest.get('href', '/quests'))}\">"
            f"{_ui.esc(current_quest.get('title', ''))}</a> "
            f"[{_ui.esc(current_quest.get('state', ''))}] "
            f"{_ui.esc(current_quest.get('progress', ''))}</p>"
            f"</div>")
    craft = _section_data("craft") or []
    craft_html = ""
    if craft:
        rows = []
        for chain in craft[:3]:
            stages = " ".join(
                _ui.esc(stage.get("glyph", "○"))
                for stage in chain.get("stages", []))
            rows.append(
                f"<li><a href=\""
                f"{_ui.esc(chain.get('href', '/craft'))}\">"
                f"{_ui.esc(chain.get('entity_id', ''))}</a> "
                f"{stages} {chain.get('done', 0)}/"
                f"{chain.get('total', 0)}</li>")
        craft_html = (f"<div class=\"panel\"><h2>🌿 Craft</h2>"
                      f"<ul>{''.join(rows)}</ul></div>")
    symbiosis = _section_data("symbiosis") or {}
    symb_html = ""
    if (symbiosis.get("open")):
        rows = "".join(
            f"<li>🌱 <a href=\""
            f"{_ui.esc(prop.get('href', '/symbiosis'))}\">"
            f"{_ui.esc(prop.get('title', ''))}</a> "
            f"<span class=\"muted\">seedling — uncertain until "
            f"reviewed</span></li>"
            for prop in symbiosis["open"][:5])
        symb_html = (f"<div class=\"panel\"><h2>🔗 Symbiosis</h2>"
                     f"<ul>{rows}</ul></div>")
    presence = _section_data("presence") or {}
    stakes_html = ""
    bands = presence.get("bands", {}) or {}
    if any(bands.get(band) for band in bands):
        parts = []
        for band in ("needs", "waiting", "available",
                     "discovered", "offline"):
            items = bands.get(band, []) or []
            if not items:
                continue
            glyph = {"needs": "📌", "waiting": "⏳",
                     "available": "🟢", "discovered": "🔵",
                     "offline": "🌙"}.get(band, "•")
            lines = "".join(
                f"<li><a href=\""
                f"{_ui.esc(item.get('href', '/presence'))}\">"
                f"{_ui.esc(item.get('title', '')[:80])}</a></li>"
                for item in items[:3])
            parts.append(
                f"<div class=\"sprout\"><b>{glyph} "
                f"{_ui.esc(band)}</b><ul>{lines}</ul></div>")
        stakes_html = (f"<div class=\"panel\"><h2>📌 Stakes</h2>"
                       f"<div class=\"grove\">"
                       f"{''.join(parts)}</div></div>")
    nodes = _section_data("nodes") or []
    nodes_html = ""
    if nodes:
        awake = sum(1 for node in nodes
                    if node.get("reads_as") == "awake")
        nodes_html = (
            f"<div class=\"panel\"><h2>🌐 Node mesh</h2>"
            f"<p>{awake}/{len(nodes)} awake — "
            f"<a href=\"/nodes\">nodes →</a></p></div>")
    energy = _section_data("energy") or {}
    energy_html = ""
    if energy.get("total"):
        energy_html = (
            f"<div class=\"panel\"><h2>⚡ Energy</h2>"
            f"<p>{energy.get('total', 0)} record(s) — "
            f"<a href=\"/energy\">energy →</a></p></div>")
    main = (f"<h1>Living game 🌱</h1>"
            f"<p class=\"muted\">"
            f"{_ui.esc(state.get('honesty', ''))}</p>"
            + world_html + campaign_html + quest_html
            + craft_html + symb_html + stakes_html + nodes_html
            + energy_html +
            "<p><a href=\"/campaigns\">Campaigns</a> · "
            "<a href=\"/quests\">Quests</a> · "
            "<a href=\"/world\">World</a> · "
            "<a href=\"/api/v1/game/state\">game JSON</a></p>")
    return _ui.shell("Living game", "/game", main, "",
                     _ui.living_bg())


# =============================================================================
# FASE 1 — PLAYABLE GAME SHELL (/play). Presentatielaag only:
# HTML5-canvas + requestAnimationFrame + keyboard, vaste kamer,
# speler (WASD/pijltjes), rechthoek-collision, interactiezone met
# placeholder-NPC Luma, camera-follow, HUD met live game-data.
# Spelerpositie is efemeer (client-side). Geen database, geen XP,
# geen physics-engine, geen framework, geen backend-mutatie:
# deze route leest alleen bestaande afgeleide state.
# =============================================================================


@app.get("/play", response_class=HTMLResponse)
def play_page() -> str:
    """Speelbare shell: beweeg met WASD/pijltjes, bots tegen
    muren en meubels, praat met Luma via E. Read-only."""
    import json as _json
    from . import ui as _ui
    def _text(value, limit=120):
        return str(value or "")[:limit]
    live: dict = {"world": {}, "quest": {}, "counts": {},
                  "luma": {}, "missions": [], "evidence": {},
                  "guide": {}, "notifications": [],
                  "events": [], "tools": {}, "fungi": {}}
    try:
        from .game import game_state
        sections = (game_state().get("sections", {}) or {})
        world = (sections.get("world", {}) or {}).get("data", {})
        quest = (sections.get("current_quest", {}) or {}).get(
            "data", {})
        nodes = (sections.get("nodes", {}) or {}).get("data", [])
        campaigns = (sections.get("campaigns", {}) or {}).get(
            "data", [])
        live["world"] = {
            "glyph": _text(world.get("glyph", ""), 8),
            "line": _text(world.get("line", ""), 160),
            "state": _text(world.get("state", ""), 40)}
        live["quest"] = {
            "title": _text(quest.get("title", "")),
            "state": _text(quest.get("state", ""), 40),
            "progress": _text(quest.get("progress", ""), 20),
            "href": _text(quest.get("href", "/quests"), 200)}
        live["counts"] = {
            "nodes": len(nodes) if isinstance(nodes, list) else 0,
            "campaigns": len(campaigns) if isinstance(
                campaigns, list) else 0}
    except Exception:
        pass
    try:
        from .guide import guide_items
        items = guide_items(limit=5) or []
        first = items[0] if items else {}
        nxt = (first.get("next", {}) or {})
        live["guide"] = {
            "what": _text(first.get("what", ""), 160),
            "label": _text(nxt.get("label", ""), 60),
            "href": _text(nxt.get("href", "/guide"), 200)}
    except Exception:
        pass
    try:
        from .missions import list_missions
        live["missions"] = [{
            "id": _text(m.mission_id, 80),
            "goal": _text(m.goal, 120),
            "status": _text(m.status, 20)} for m in
            list_missions(limit=50)
            if str(m.status) in ("approved", "running",
                                 "pending_approval")][:5]
    except Exception:
        pass
    try:
        from .knowledge import list_candidates
        cands = list_candidates(limit=8) or []
        live["evidence"]["candidates"] = [{
            "title": _text(c.title), "state": _text(
                c.state, 20)} for c in cands]
        live["evidence"]["candidate_open"] = sum(
            1 for c in list_candidates(limit=50) or []
            if str(c.state) in ("observation", "candidate",
                                "supported"))
        live["evidence"]["supported_count"] = sum(
            1 for c in list_candidates(limit=50) or []
            if str(c.state) == "supported")
    except Exception:
        pass
    try:
        inbox = _recent_observations(6) or []
        live["evidence"]["observations"] = [{
            "id": _text(o.observation_id, 80),
            "device": _text(o.device_id, 80),
            "media": _text(o.media_ref, 120),
            "created": _text(o.created_at, 16)} for o in inbox]
    except Exception:
        pass
    try:
        from .vision_ingest import list_inbox_files
        files = list_inbox_files(limit=50) or []
        live["tools"] = {
            "inbox_count": len(files),
            "inbox": [_text((f or {}).get("filename", ""))
                      for f in files[:8]]}
    except Exception:
        pass
    try:
        notes = list_notifications_for_report(limit=10) or []
        live["notifications"] = [{
            "title": _text(n.title),
            "type": _text(n.type, 40),
            "created": _text(n.created_at, 16)} for n in notes]
    except Exception:
        pass
    try:
        live["events"] = [{
            "type": _text(e.event_type, 60),
            "summary": _text(e.summary, 160),
            "created": _text(e.created_at, 16)} for e in
            bus_events(limit=15) or []]
    except Exception:
        pass
    try:
        from .world import derive_fungi_network
        net = derive_fungi_network(limit=120) or {}
        live["fungi"] = {
            "nodes": net.get("nodes", [])[:120],
            "counts": net.get("counts", {}),
            "total": int(net.get("total", 0) or 0),
            "honesty": str(net.get("honesty", ""))[:200]}
    except Exception:
        pass
    try:
        from .familiars import (ensure_npc_familiars,
                                list_familiars)
        ensure_npc_familiars()
        fam_map: dict[str, dict] = {}
        for fam in list_familiars() or []:
            fam_map[str(fam.name or "").strip().lower()] = {
                "id": _text(fam.familiar_id, 80),
                "kind": _text(fam.kind, 20),
                "status": _text(fam.status, 20),
                "capabilities": [
                    _text(c, 40) for c in
                    (fam.capabilities or [])[:8]]}
        live["luma"]["familiar"] = fam_map.get("luma")
    except Exception:
        fam_map = {}
        live["luma"].setdefault("familiar", None)
    # Luma-statusbadge, uitsluitend uit echte data (prioriteit:
    # review-aandacht > nieuwe input > bezig > afgerond).
    try:
        badge, reason = None, "Rustig — geen openstaande signalen."
        if live["evidence"].get("candidate_open", 0) > 0:
            n = live["evidence"]["candidate_open"]
            badge, reason = ("!", f"{n} kandidaat/kandidaten "
                                  "wachten op review.")
        elif live["tools"].get("inbox_count", 0) > 0:
            n = live["tools"]["inbox_count"]
            badge, reason = ("?", f"{n} inbox-bestand(en) "
                                  "wachten op ingest.")
        elif live["missions"]:
            badge, reason = ("…", f"{len(live['missions'])} "
                                  "missie(s) onderweg.")
        else:
            try:
                from .quests import list_quest_details
                done = [q for q in list_quest_details(
                    limit=20) or []
                    if q.get("state") == "COMPLETED"]
                if done:
                    badge, reason = ("✓", f"{len(done)} quest(s) "
                                          "afgerond.")
            except Exception:
                pass
        live["luma"]["badge"] = badge or ""
        live["luma"]["reason"] = reason
        live["luma"]["status"] = ("Idle" if not badge
                                  else {"!": "Aandacht nodig",
                                        "?": "Vraag",
                                        "…": "Bezig",
                                        "✓": "Afgerond"}.get(
                                      badge, "Idle"))
    except Exception:
        live["luma"]["badge"] = ""
        live["luma"]["reason"] = "Status onbekend."
        live["luma"]["status"] = "Idle"
    # -- Forge-data (bestaande workbench/printer-stores, read-only) --
    live["forge"] = {"models": [], "printers": [],
                     "missions": [], "profiles": [],
                     "quests": [], "fabrecords": []}
    try:
        from .workshop3d import list_models
        for item in list_models(limit=8) or []:
            if not isinstance(item, dict):
                continue
            inspection = item.get("inspection", {}) or {}
            live["forge"]["models"].append({
                "filename": _text(item.get("filename", ""), 80),
                "model_id": _text(item.get("model_id", ""), 80),
                "status": _text(item.get("status", ""), 20),
                "verdict": _text(inspection.get("mesh_verdict",
                                                "UNKNOWN"), 20),
                "size": int(item.get("size_bytes", 0) or 0)})
    except Exception:
        pass
    try:
        from .printer3d import (adapter_for_printer,
                                list_printers,
                                list_stored_printers)
        seen_printers: set[str] = set()
        for printer in list(list_stored_printers() or []) + \
                list(list_printers() or []):
            pid = str(printer.printer_id or "")
            if not pid or pid in seen_printers:
                continue
            seen_printers.add(pid)
            try:
                has_adapter = adapter_for_printer(pid) is not None
            except Exception:
                has_adapter = False
            live["forge"]["printers"].append({
                "printer_id": _text(pid, 80),
                "name": _text(printer.name, 120),
                "status": _text(printer.status, 20),
                "adapter": bool(has_adapter)})
        live["forge"]["printers"].sort(
            key=lambda p: p["printer_id"])
    except Exception:
        pass
    try:
        from .slicer3d import SLICER_PROFILES
        live["forge"]["profiles"] = sorted(SLICER_PROFILES)[:12]
    except Exception:
        pass
    try:
        from .campaigns import FABRICATION_SEEDS
        fab_titles = {t for t, _x, _y, _z in FABRICATION_SEEDS}
    except Exception:
        fab_titles = set()
    try:
        from .missions import list_missions
        for mission in sorted(
                list_missions(limit=200) or [],
                key=lambda m: str(m.mission_id)):
            if str(mission.goal or "") not in fab_titles:
                continue
            live["forge"]["missions"].append({
                "id": _text(mission.mission_id, 80),
                "goal": _text(mission.goal, 120),
                "status": _text(mission.status, 20)})
        live["forge"]["missions"].sort(key=lambda m: m["id"])
    except Exception:
        pass
    try:
        from .quests import list_quest_details
        _fab_set = fab_titles | {f"Missie: {t}" for t in fab_titles}
        for detail in list_quest_details(limit=200) or []:
            if str(detail.get("title", "")) not in _fab_set:
                continue
            steps = []
            for step in detail.get("steps", []) or []:
                if not isinstance(step, dict):
                    continue
                steps.append({
                    "label": _text(step.get("label", "")),
                    "kind": _text(step.get("kind", ""), 20),
                    "state": _text(step.get("state", ""), 20),
                    "glyph": _text(step.get("glyph", "○"), 8),
                    "detail": _text(step.get("detail", ""), 160),
                    "readiness": _text(step.get("readiness", ""),
                                       20),
                    "reason": _text(step.get(
                        "readiness_reason", ""), 160)})
            live["forge"]["quests"].append({
                "quest_id": _text(detail.get("quest_id", ""), 80),
                "title": _text(detail.get("title", "")),
                "state": _text(detail.get("state", ""), 40),
                "done": int(detail.get("done", 0) or 0),
                "total": int(detail.get("total", 0) or 0),
                "progress": _text(detail.get("progress", ""), 20),
                "steps": steps})
        live["forge"]["quests"].sort(key=lambda q: q["quest_id"])
    except Exception:
        pass
    try:
        from .fab_flow import list_fabrications
        for record in list_fabrications(limit=8) or []:
            data = record.model_dump(mode="json")
            live["forge"]["fabrecords"].append({
                "fabrication_id": _text(data.get(
                    "fabrication_id", ""), 80),
                "status": _text(data.get("status", ""), 20),
                "mesh_ref": _text(data.get("mesh_ref", ""), 80),
                "gcode_ref": _text(data.get("gcode_ref", ""), 80),
                "job_id": _text(data.get("job_id", ""), 80)})
    except Exception:
        pass
    # -- INVENTory-tellingen (best-effort loopback, alleen aantallen)
    inv_counts: dict[str, int | None] = {
        "files": None, "cameras": None, "hardware": None,
        "models": None}
    try:
        import anyio as _anyio
        _reader = _world_reader()

        async def _browse_counts() -> dict:
            out: dict[str, int | None] = {}
            for _kind in ("files", "cameras", "hardware",
                          "models"):
                try:
                    _found = await _reader.browse(_kind)
                    out[_kind] = len(_found.results or [])
                except Exception:
                    out[_kind] = None
            return out

        inv_counts.update(_anyio.run(_browse_counts) or {})
    except Exception:
        pass
    try:
        from .hardware_links import list_links
        live["verified_hw"] = len(list_links(
            status="VERIFIED", limit=200) or [])
    except Exception:
        live["verified_hw"] = 0
    # -- NPC-missies inclusief drafts (eerlijke statuslabels) --
    _STATUS_LABEL = {"draft": "beschikbaar",
                     "pending_approval": "WAITING",
                     "approved": "ACTIVE", "running": "ACTIVE",
                     "paused": "WAITING"}
    _TERMINAL = {"completed", "failed", "cancelled", "blocked"}
    try:
        from .campaigns import MISSION_SEEDS
        luma_titles = {
            "Documenteer één object",
            "Laat Luma je video begrijpen [FUTURE]"}
    except Exception:
        luma_titles = {"Documenteer één object"}
    try:
        from .missions import list_missions as _list_all
        _all_missions = list_missions(limit=200) or []
    except Exception:
        _all_missions = []

    def _mission_item(mission) -> dict:
        return {
            "id": _text(mission.mission_id, 80),
            "goal": _text(mission.goal, 120),
            "status": _text(mission.status, 20),
            "label": _text(mission.goal, 120),
            "href": f"/missions/{_text(mission.mission_id, 80)}",
            "meta": _STATUS_LABEL.get(
                str(mission.status),
                str(mission.status))}

    live["luma_missions"] = [
        _mission_item(m) for m in _all_missions
        if str(m.goal or "") in luma_titles
        and str(m.status) not in _TERMINAL]
    live["luma_missions"].sort(key=lambda m: m["id"])
    live["docquest"] = {}
    _questlines: list = []
    try:
        from .quests import list_quest_details
        _questlines = list_quest_details(limit=50) or []
        for _qd in _questlines:
            if str(_qd.get("title", "")) == "Documenteer één object":
                live["docquest"] = {
                    "title": _text(_qd.get("title", "")),
                    "state": _text(_qd.get("state", ""), 40),
                    "done": int(_qd.get("done", 0) or 0),
                    "total": int(_qd.get("total", 0) or 0),
                    "progress": _text(_qd.get("progress", ""),
                                      20)}
                break
    except Exception:
        pass
    # -- Missie-tracker: bestaande mission-state als speelbare
    # voortgang (geen tweede quest-engine) --
    _TRACK_GLYPH = {"draft": "○", "pending_approval": "◷",
                    "approved": "…", "running": "…",
                    "paused": "⏸", "completed": "✓",
                    "failed": "!", "cancelled": "○",
                    "blocked": "!"}
    _TRACK_NEEDS = {"draft": "beschikbaar — aannemen via Missies",
                    "pending_approval": "wacht op exacte YES",
                    "approved": "kan tikken — drijft tot gate",
                    "running": "kan tikken — drijft tot gate",
                    "paused": "hervatten via Missies-pagina",
                    "completed": "afgerond",
                    "failed": "aandacht nodig — zie Missies",
                    "cancelled": "geannuleerd",
                    "blocked": "aandacht nodig — zie Missies"}
    live["tracker"] = []
    try:
        for _m in sorted(_all_missions,
                         key=lambda m: str(m.mission_id)):
            _st = str(_m.status)
            if _st in ("cancelled",):
                continue
            live["tracker"].append({
                "id": _text(_m.mission_id, 80),
                "goal": _text(_m.goal, 120),
                "status": _text(_st, 20),
                "glyph": _TRACK_GLYPH.get(_st, "○"),
                "needs": _TRACK_NEEDS.get(_st, _st),
                "href": f"/missions/{_text(_m.mission_id, 80)}"})
            if len(live["tracker"]) >= 12:
                break
    except Exception:
        live["tracker"] = []
    live["questlines"] = []
    try:
        for _qd in _questlines[:20]:
            live["questlines"].append({
                "quest_id": _text(_qd.get("quest_id", ""), 80),
                "title": _text(_qd.get("title", "")),
                "state": _text(_qd.get("state", ""), 40),
                "progress": _text(_qd.get("progress", ""), 20),
                "glyph": ("✓" if _qd.get("state") == "COMPLETED"
                          else "!" if _qd.get("state") in
                          ("FAILED", "BLOCKED") else "○")})
    except Exception:
        live["questlines"] = []
    # -- Discoveries: bestaande evidence-only vondsten --
    live["discoveries"] = {"items": [], "research_open": []}
    try:
        from .ecosystem import discoveries as _findings
        _found = _findings(limit=6) or {}
        for _item in (_found.get("items", []) or [])[:6]:
            if not isinstance(_item, dict):
                continue
            live["discoveries"]["items"].append({
                "title": _text(_item.get("title", "")),
                "kind": _text(_item.get("kind", ""), 40),
                "text": _text(_item.get("text", ""), 200),
                "evidence": _text(_item.get("evidence", ""),
                                  160),
                "link": _text(_item.get("link", "/symbiosis"),
                              200)})
        for _item in (_found.get("research_open_questions", [])
                      or [])[:6]:
            if not isinstance(_item, dict):
                continue
            live["discoveries"]["research_open"].append({
                "question": _text(_item.get("question", ""),
                                  200),
                "link": _text(_item.get("link", "/research"),
                              200)})
    except Exception:
        live["discoveries"] = {"items": [], "research_open": []}
    try:
        from .cameras import list_devices
        live["devices"] = [{
            "device_id": _text(d.device_id, 80),
            "name": _text(d.name, 120)} for d in
            list_devices() or []]
    except Exception:
        live["devices"] = []
    # -- World representations v1 (dunne afbeelding echte records) --
    live["world_reps"] = []
    try:
        import anyio as _anyio2
        from .world import (derive_world_representations,
                            inventory_spotlight)
        _reader2 = _world_reader()

        async def _spotlight() -> list:
            try:
                return await inventory_spotlight(_reader2)
            except Exception:
                return []

        live["world_reps"] = derive_world_representations(
            _anyio2.run(_spotlight) or [])
    except Exception:
        live["world_reps"] = []
    live["npc_anchors"] = []
    try:
        from .world import npc_anchors
        live["npc_anchors"] = npc_anchors()
    except Exception:
        live["npc_anchors"] = []
    # -- Verdant: voorwaardelijke biome uit bestaande signalen --
    live["verdant"] = {"state": "DORMANT", "signals": [],
                       "count": 0, "mission": None,
                       "quests": []}
    try:
        import anyio as _anyio3
        from .world import (collect_verdant_signals,
                            verdant_state_from)
        _reader3 = _world_reader()

        async def _verdant_parts() -> dict:
            try:
                return await collect_verdant_signals(_reader3)
            except Exception:
                return {"inventory": [], "solar": 0,
                        "research": []}

        live["verdant"] = verdant_state_from(
            _anyio3.run(_verdant_parts) or {})
    except Exception:
        live["verdant"] = {"state": "DORMANT", "signals": [],
                           "count": 0, "mission": None,
                           "quests": []}
    try:
        for _m in _all_missions:
            if str(_m.goal or "") == ("Ontwerp een onderdeel voor "
                                      "de hydroponics-workshop"):
                live["verdant"]["mission"] = {
                    "id": _text(_m.mission_id, 80),
                    "goal": _text(_m.goal, 120),
                    "status": _text(_m.status, 20),
                    "href": f"/missions/{_text(_m.mission_id, 80)}"}
                break
        for _qd in _questlines:
            if str(_qd.get("title", "")) in (
                    "Mycelium F: kweek", "Mycelium G: oogst"):
                live["verdant"]["quests"].append({
                    "title": _text(_qd.get("title", "")),
                    "state": _text(_qd.get("state", ""), 40),
                    "progress": _text(_qd.get("progress", ""),
                                      20)})
    except Exception:
        pass
    live["verdant"].setdefault("mission", None)
    live["verdant"].setdefault("quests", [])
    # AWAKENED-representatie: eerste whitelist-signaal wordt één
    # beloopbare representatie in de bioom (zelfde id-vorm, geen
    # dubbele als het record al op de plank staat).
    live["verdant"]["rep"] = None
    try:
        from .world import verdant_rep_from
        if live["verdant"].get("state") == "AWAKENED":
            live["verdant"]["rep"] = verdant_rep_from(
                live["verdant"].get("signals", []) or [],
                shelf_ids={r.get("source_id")
                           for r in live["world_reps"]})
    except Exception:
        live["verdant"]["rep"] = None
    # -- NPC-lijst (data-gedreven; posities blijven client-kaart) --
    fab_open = [m for m in live["forge"]["missions"]
                if m["status"] not in ("draft", "completed",
                                       "failed", "cancelled")]
    fab_draft = [m for m in live["forge"]["missions"]
                 if m["status"] == "draft"]
    if fab_open:
        forge_badge = "…"
        forge_reason = (f"{len(fab_open)} fabricatiemissie(s) "
                        "onderweg.")
        forge_status = "Bezig"
    elif fab_draft:
        forge_badge = ""
        forge_reason = (f"{len(fab_draft)} concept-missie(s) "
                        "beschikbaar; printer: "
                        + ("geen" if not live["forge"]["printers"]
                           else str(len(live["forge"][
                               "printers"])) + " bekend"))
        forge_status = "Idle"
    else:
        forge_badge, forge_reason, forge_status = (
            "", "Werkplaats gereed.", "Idle")
    def _inv_word(count, singular, plural=""):
        if count is None:
            return "INVENTory onbereikbaar", "ONBEREIKBAAR"
        word = singular if count == 1 else (plural or singular + "s")
        return f"{count} {word}", "BESCHIKBAAR"

    _files_word, _files_state = _inv_word(
        inv_counts.get("files"), "file")
    _cams_word, _cams_state = _inv_word(
        inv_counts.get("cameras"), "camera", "camera's")
    _hw_n = inv_counts.get("hardware")
    _hw_word = ("INVENTory onbereikbaar" if _hw_n is None
                else f"{_hw_n} records"
                + (f", {live['verified_hw']} GEVERIFIEERD"
                   if live.get("verified_hw") else ""))
    _hw_state = ("ONBEREIKBAAR" if _hw_n is None else "BESTAAT")
    _models_word, _models_state = _inv_word(
        inv_counts.get("models"), "AI-model", "AI-modellen")
    _n_models = len(live["forge"]["models"])
    _printers = live["forge"]["printers"]
    if not _printers:
        _printer_detail = ("geen printer geregistreerd — "
                           "fysiek printen onmogelijk")
        _printer_state = "AFWEZIG"
    else:
        _printer_detail = (
            f"{len(_printers)} bekend: "
            + ", ".join(
                f"{p['name'] or p['printer_id']} "
                f"[{p['status']}"
                f"{', adapter' if p['adapter'] else ', geen adapter'}]"
                for p in _printers[:4]))
        _printer_state = "BEKEND"
    _exec_available = ("NOT_CONNECTED" if not _printers
                       else "HARDWARE_REQUIRED")
    _exec_reason = ("geen printer-record" if not _printers
                    else "exacte YES + adapter + hardware vereist; "
                         "missie-YES start de machine nooit")
    # -- NPC activity: afgeleide aanwezigheid, geen simulatie --
    live["npc_activity"] = {
        "luma": {"state": "idle", "reason": ""},
        "forge": {"state": "idle", "reason": ""}}
    try:
        from .world import derive_npc_activity
        live["npc_activity"] = derive_npc_activity({
            "candidate_open": live["evidence"].get(
                "candidate_open", 0),
            "supported_count": live["evidence"].get(
                "supported_count", 0),
            "inbox_count": live["tools"].get("inbox_count", 0),
            "missions_active": bool(live["missions"]),
            "quest_completed": bool([
                q for q in live["questlines"]
                if q.get("state") == "COMPLETED"]),
            "fab_open": bool(fab_open),
            "fab_draft": bool(fab_draft),
            "fab_blocked": bool([
                f for f in live["forge"]["fabrecords"]
                if str(f.get("status", "")) in
                ("blocked", "failed")])})
    except Exception:
        pass
    live["npcs"] = [
        {
            "id": "luma", "name": "Luma", "glyph": "🎥",
            "domain": "Media & Observation",
            "role": "Waarnemer",
            "line": "Hey Jelles. Er is hier nog veel te ontdekken.",
            "badge": live["luma"].get("badge", ""),
            "reason": live["luma"].get("reason", ""),
            "status": live["luma"].get("status", "Idle"),
            "familiar": live["luma"].get("familiar")
            or fam_map.get("luma"),
            "activity": live["npc_activity"].get("luma"),
            "panel": {
                "abilities": [
                    {"name": "Inbox bekijken",
                     "via": "bestaande inbox-lijst",
                     "type": "DIGITAL", "available": "AVAILABLE",
                     "reason": "", "tool": "Camera-inbox"},
                    {"name": "Camera-observatie starten",
                     "via": "bestaande ingest/sessie-flow",
                     "type": "DIGITAL", "available": "AVAILABLE",
                     "reason": "", "tool": "Camera-inbox"},
                    {"name": "Foto analyseren",
                     "via": "bestaande describe (VLM of fallback)",
                     "type": "DIGITAL", "available": "AVAILABLE",
                     "reason": "REAL indien Ollama actief, anders "
                               "UNAVAILABLE",
                     "tool": "Vision-model"},
                    {"name": "Kandidaten voorstellen",
                     "via": "bestaande propose-flow",
                     "type": "DIGITAL", "available": "AVAILABLE",
                     "reason": "alleen uit REAL-labels",
                     "tool": "INVENTory"},
                    {"name": "Object/file-voorstel",
                     "via": "bestaande vision→write-flow",
                     "type": "DIGITAL", "available": "AVAILABLE",
                     "reason": "inert tot YES",
                     "tool": "INVENTory"},
                    {"name": "Video/360° verwerken",
                     "via": "bestaat nog niet",
                     "type": "DIGITAL", "available": "FUTURE",
                     "reason": "alleen losse beelden via file-ingest",
                     "tool": "Camera-inbox"}],
                "tools": [
                    {"name": "Camera-inbox",
                     "detail": f"{live['tools'].get('inbox_count', '?')} "
                               "bestand(en)",
                     "state": "BESCHIKBAAR"},
                    {"name": "Vision-model",
                     "detail": "Ollama loopback indien actief, anders "
                               "UNAVAILABLE",
                     "state": "BESTAAT"},
                    {"name": "Camera/file-records",
                     "detail": f"{_cams_word}; {_files_word}",
                     "state": _cams_state},
                    {"name": "INVENTory",
                     "detail": "wereldwaarheid",
                     "state": "BESTAAT"}],
                "missions": live["luma_missions"],
                "evidence": live["evidence"]},
            "mission": {
                "items": (
                    ([{"label": "Guide: " + live["guide"].get(
                        "what", ""),
                      "href": live["guide"].get("href", "/guide"),
                      "meta": live["guide"].get("label", "")}]
                     if live["guide"].get("what") else [])
                    + ([{"label": "Quest: " + live["quest"].get(
                        "title", ""),
                         "href": live["quest"].get("href", "/quests"),
                         "meta": live["quest"].get("state", "")}]
                       if live["quest"].get("title") else [])
                    + [{"label": m.get("goal", ""),
                        "href": f"/missions/{m.get('id', '')}",
                        "meta": m.get("meta", m.get("status", ""))}
                       for m in live["luma_missions"]]),
                "note": "Aannemen gebeurt op de bestaande pagina's — "
                        "de game start niets zelf."},
        },
        {
            "id": "forge", "name": "Forge", "glyph": "🛠️",
            "domain": "Fabrication & 3D",
            "role": "Werkplaatsbeheerder",
            "line": "Welkom in de werkplaats. Ik bereid alles voor — "
                    "printen zelf doen we alleen met jouw YES.",
            "badge": forge_badge,
            "reason": forge_reason,
            "status": forge_status,
            "familiar": fam_map.get("forge"),
            "activity": live["npc_activity"].get("forge"),
            "panel": {
                "abilities": [
                    {"name": "3D-model beoordelen",
                     "via": "bestaande workbench-inspectie",
                     "type": "DIGITAL", "available": "AVAILABLE",
                     "reason": "", "tool": "3D-modellen"},
                    {"name": "Printbaarheid bekijken",
                     "via": "bestaande mesh-verdicts",
                     "type": "DIGITAL", "available": "AVAILABLE",
                     "reason": "", "tool": "Slicer/workbench"},
                    {"name": "Print-missie voorstellen",
                     "via": "bestaande propose + YES-gate",
                     "type": "DIGITAL", "available": "AVAILABLE",
                     "reason": "inert tot exacte YES",
                     "tool": "Printers"},
                    {"name": "Materiaal/model koppelen",
                     "via": "bestaande workshop-links",
                     "type": "DIGITAL", "available": "AVAILABLE",
                     "reason": "", "tool": "CAD/mesh-files"},
                    {"name": "Printerstatus tonen",
                     "via": "bestaande printer-devices",
                     "type": "DIGITAL", "available": "AVAILABLE",
                     "reason": "", "tool": "Printers"},
                    {"name": "Print uitvoeren (fysiek)",
                     "via": "adapter + exacte YES + verificatie",
                     "type": "PHYSICAL",
                     "available": _exec_available,
                     "reason": _exec_reason,
                     "tool": "Printers"}],
                "tools": [
                    {"name": "3D-modellen",
                     "detail": (f"{_n_models} geregistreerd"
                                if _n_models else "geen modellen "
                                "geregistreerd"),
                     "state": ("BESCHIKBAAR" if _n_models
                               else "AFWEZIG")},
                    {"name": "CAD/mesh-files",
                     "detail": _files_word,
                     "state": _files_state},
                    {"name": "Slicer/workbench",
                     "detail": "profielen: " + (
                         ", ".join(live["forge"]["profiles"][:4])
                         if live["forge"]["profiles"]
                         else "onbekend"),
                     "state": "BESTAAT"},
                    {"name": "Printers",
                     "detail": _printer_detail,
                     "state": _printer_state},
                    {"name": "INVENTory hardware",
                     "detail": _hw_word,
                     "state": _hw_state},
                    {"name": "AI-modellen",
                     "detail": _models_word,
                     "state": _models_state}],
                "missions": [{
                    "id": m["id"], "goal": m["goal"],
                    "status": m["status"]} for m in
                    live["forge"]["missions"]],
                "evidence": {
                    "models": live["forge"]["models"],
                    "candidates": [],
                    "fabrecords": live["forge"]["fabrecords"],
                    "quests": live["forge"]["quests"]}},
            "mission": {
                "items": [{
                    "label": m["goal"],
                    "href": f"/missions/{m['id']}",
                    "meta": _STATUS_LABEL.get(
                        m["status"], m["status"])} for m in
                    live["forge"]["missions"]],
                "note": "Fysieke uitvoering vereist altijd exacte YES "
                        "+ adapter + hardware. Draft = beschikbaar."},
        },
    ]
    play_data = _json.dumps(live).replace("</", "<\\/")
    world_line = _ui.esc(live["world"].get("line", "") or
                         "Mycelium ademt — data volgt")
    quest_title = _ui.esc(live["quest"].get("title", "") or
                          "nog geen open quest")
    quest_href = _ui.esc(live["quest"].get("href", "/quests") or
                         "/quests")
    guide_label = _ui.esc(live["guide"].get("label", "") or
                          "Guide")
    guide_href = _ui.esc(live["guide"].get("href", "/guide") or
                         "/guide")
    guide_what = _ui.esc(live["guide"].get("what", "") or
                         "Geen actieve Guide-actie.")
    notif_n = len(live["notifications"])
    fungi_groups: dict[str, list] = {}
    for _node in live["fungi"].get("nodes", []) or []:
        fungi_groups.setdefault(str(_node.get("branch", "?")),
                                []).append(_node)
    fungi_names = {"seed": "🏠 Zaad", "quest": "🧭 Quests",
                   "campaign": "🗺 Campagnes", "mission": "📜 Missies",
                   "observation": "📷 Observaties",
                   "candidate": "🌱 Kandidaten",
                   "hardware": "🔧 Hardware", "knowledge": "📚 Kennis",
                   "node": "⬢ Nodes"}
    # WORLD MEMORY: per tak één betrouwbare "omdat"-regel, direct uit
    # de derive-bron. Geen gokken per node — alleen wat de bron bewijst.
    fungi_why = {"seed": "startpunt van het netwerk",
                 "campaign": "campagne-voortgang uit bestaande records",
                 "quest": "quest-status uit bestaande records",
                 "mission": "goedgekeurde of lopende missie-records",
                 "observation": "echte camera-observaties",
                 "candidate": "wacht op review in Kennis",
                 "hardware": "geverifieerde hardware-links",
                 "knowledge": "opgeslagen kennisrecords",
                 "node": "geregistreerde nodes"}
    fungi_parts = []
    for _branch in ("seed", "campaign", "quest", "mission",
                    "observation", "candidate", "hardware",
                    "knowledge", "node"):
        _items = fungi_groups.get(_branch, [])
        if not _items:
            continue
        _rows = "".join(
            f"<li><a href=\"{_ui.esc(_n.get('href', '/world'))}\">"
            f"{_ui.esc(_n.get('glyph', '•'))} "
            f"{_ui.esc(_n.get('label', ''))}</a></li>"
            for _n in _items[:8])
        _more = (f"<li class=\"muted\">+{len(_items) - 8} "
                 "meer…</li>" if len(_items) > 8 else "")
        fungi_parts.append(
            f"<div class=\"sprout\"><b>{fungi_names.get(_branch, _branch)} "
            f"({_ui.esc(str(len(_items)))})</b>"
            f"<br><small class=\"muted\">Omdat: "
            f"{_ui.esc(fungi_why.get(_branch, 'bestaande records'))}."
            f"</small><ul>{_rows}{_more}</ul>"
            "</div>")
    fungi_html = "".join(fungi_parts) or \
        "<p class=\"muted\">Nog geen groei — het netwerk groeit pas bij echte records.</p>"
    live_fungi_total = _ui.esc(str(live["fungi"].get("total", 0)))
    live_fungi_honesty = _ui.esc(live["fungi"].get(
        "honesty", "Afgeleid uit bestaande records."))
    main = f"""<h1>Play 🎮 <span class="muted">Homebase</span></h1>
    <p class="muted">Bewegen: <code>WASD</code>/<code>pijltjes</code> · Interactie: <code>E</code> · Meldingen: <code>N</code> · Sluiten: <code>Esc</code>. Positie is efemeer (alleen in je browser).</p>
    <div class="panel"><div id="play-hud" class="muted">laden…</div>
    <p>{_ui.esc(live["world"].get("glyph", "🌱"))} <b>{world_line}</b> · 🧭 <a href="{quest_href}">{quest_title}</a></p>
    <p><span id="guide-chip" class="muted">🧭 Guide: {guide_what} — <a href="{guide_href}">{guide_label}</a></span> · <span id="notif-chip" class="muted">🔔 <button id="notif-open">Meldingen ({notif_n})</button></span></p></div>
    <div class="panel"><h2>Live backend <span class="muted">(zelfde waarheid, elke 20s)</span></h2>
    <div id="live-strip" class="muted">live status laden…</div>
    <p class="muted"><a href="/tasks">Tasks</a> · <a href="/missions">Missions</a> · <a href="/activity">Activity</a> · <a href="/api/v1/events/stream?once=true">events (SSE-snapshot)</a></p></div>
    <script>
    (function() {{
      var el = document.getElementById("live-strip");
      if (!el) return;
      function esc(s) {{ return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").slice(0, 160); }}
      async function tick() {{
        try {{
          var er = await fetch("/api/v1/events?limit=3");
          var ev = er.ok ? await er.json() : [];
          var tr = await fetch("/api/v1/tasks");
          var tasks = tr.ok ? await tr.json() : [];
          var open = tasks.filter(function(t) {{ return t.status === "queued"; }}).length;
          var busy = tasks.filter(function(t) {{ return t.status === "assigned"; }}).length;
          var last = (ev.length ? ev[ev.length - 1] : null);
          el.innerHTML = "tasks: <b>" + open + " open / " + busy + " bezig</b>"
            + (last ? " · laatste event: <b>" + esc(last.event_type) + "</b> — " + esc(last.summary || "") : " · nog geen events");
        }} catch (e) {{ el.textContent = "live status onbereikbaar (backend offline?)"; }}
      }}
      tick(); setInterval(tick, 20000);
    }})();
    </script>
    <div class="panel"><canvas id="stage" width="960" height="600" style="width:100%;height:auto;background:#0b0f0b;border:1px solid var(--line);border-radius:var(--r)" role="img" aria-label="Speelbare homebase en bosrand. Beweeg met WASD of pijltjes, praat met Luma via E, meldingen via N."></canvas>
    <div id="interact" class="muted" role="status" style="min-height:1.6em"></div></div>
    <div class="panel"><h2>🍄 Fungi-netwerk <span class="muted">wereldgeheugen (afgeleid, {live_fungi_total} knopen)</span></h2>
    <p class="muted">{live_fungi_honesty}</p>
    <div class="grove">{fungi_html}</div>
    <p><a href="/game">Game-overzicht</a> · <a href="/world">World</a></p></div>
    <div id="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title" hidden>
    <div class="panel"><h2><span id="dialog-title-name">NPC</span> <span id="npc-badge"></span></h2>
    <div id="dialog-choices" role="group" aria-label="Gespreksopties"></div>
    <div id="dialog-body"></div>
    <p class="muted">Alles hieronder is bestaande data of bestaande flows. Acties lopen via echte backend-routes; NPC-persoonlijkheid beïnvloedt nooit permissions of safety.</p>
    <button id="dialog-close">Sluiten (Esc)</button></div></div>
    <div id="notifs" role="dialog" aria-modal="true" aria-labelledby="notifs-title" hidden>
    <div class="panel"><h2 id="notifs-title">🔔 Meldingen</h2>
    <div id="notifs-body"></div>
    <p class="muted">Snapshot bij het laden van de pagina — ververs voor nieuw. Bestaande notification/event-data.</p>
    <button id="notifs-close">Sluiten (Esc)</button></div></div>
    <p class="muted"><a href="/game">Game-overzicht</a> · <a href="/guide">Guide</a> · <a href="/world">World</a> · <a href="/quests">Quests</a></p>
     <script>const PLAYDATA = {play_data};
     window.PLAYDATA = PLAYDATA;
     const WORLD_W = 1600, WORLD_H = 1400, VIEW_W = 960, VIEW_H = 600;
    const DIV_Y = 1000;
    const WALLS = [
      {{x: 0, y: 0, w: WORLD_W, h: 40}},
      {{x: 0, y: WORLD_H - 40, w: WORLD_W, h: 40}},
      {{x: 0, y: 0, w: 40, h: WORLD_H}},
      {{x: WORLD_W - 40, y: 0, w: 40, h: WORLD_H}},
      {{x: 40, y: DIV_Y - 20, w: 690, h: 40}},
      {{x: 870, y: DIV_Y - 20, w: 690, h: 40}}
    ];
    const DOOR = {{x: 730, y: DIV_Y - 20, w: 140, h: 40, label: "deur-bosrand", passable: true}};
    const SOLIDS = [
      {{x: 220, y: 220, w: 320, h: 110, label: "werkbank"}},
      {{x: 1050, y: 200, w: 180, h: 320, label: "stellage"}},
      {{x: 700, y: 620, w: 220, h: 130, label: "tafel"}},
      {{x: 1240, y: 660, w: 120, h: 120, label: "plant"}},
      {{x: 180, y: 640, w: 120, h: 120, label: "plant"}},
      {{x: 200, y: 1120, w: 140, h: 140, label: "boom"}},
      {{x: 1250, y: 1140, w: 150, h: 150, label: "boom"}},
      {{x: 700, y: 1180, w: 120, h: 120, label: "ruine"}}
    ];
    const DECOR = [
      {{x: 480, y: 700, w: 220, h: 140, label: "kleed"}},
      {{x: 880, y: 300, w: 90, h: 90, label: "lamp", light: 1}},
      {{x: 340, y: 420, w: 90, h: 90, label: "lamp", light: 1}},
      {{x: 500, y: 1080, w: 100, h: 60, label: "mos"}},
      {{x: 950, y: 1240, w: 120, h: 70, label: "mos"}}
    ];
    const SLOTS = [
      {{x: 300, y: 1150, w: 150, h: 90, label: "later: Verdant"}}
    ];
     const NPC_FALLBACK = [
       {{id: "luma", name: "Luma", x: 1180, y: 420, r: 18, color: "#c9d66b", glyph: "🎥", radius: 95}},
       {{id: "forge", name: "Forge", x: 1380, y: 380, r: 18, color: "#d9a441", glyph: "🛠️", radius: 95}}
     ];
     const NPCS = (function () {{
       const anchors = ((window.PLAYDATA && PLAYDATA.npc_anchors) || []);
       if (anchors.length) return anchors.map((a) => ({{id: a.id, name: a.name || a.id, x: a.x, y: a.y, r: 18, color: a.color || "#c9d66b", glyph: a.glyph || "•", radius: 95}}));
       return NPC_FALLBACK;
     }})();
     let worldObj = null, worldObjDetail = null;
     function worldReps() {{
       const reps = ((window.PLAYDATA && PLAYDATA.world_reps) || []).slice();
       const verd = ((window.PLAYDATA && PLAYDATA.verdant) || {{}});
       if (verd && verd.rep && verd.rep.source_id) {{
         if (!reps.some((r) => r && r.source_id === verd.rep.source_id)) reps.push(verd.rep);
       }}
       return reps;
     }}
    const CHOICES = {{
       luma: [{{v: "files", l: "Bestanden bekijken"}}, {{v: "lumaflow", l: "Analyse starten"}},
              {{v: "journey", l: "🧭 Reis"}}, {{v: "mission", l: "Missievoorstel"}}, {{v: "later", l: "Sluiten"}}],
       forge: [{{v: "panel", l: "Bekijk"}}, {{v: "abilities", l: "Wat kun je?"}},
               {{v: "print", l: "Help mij iets te printen"}}, {{v: "quest", l: "Missie-evidence"}}, {{v: "later", l: "Later"}}]
    }};
    let flow = null;
    function flowSteps() {{
      const s = (flow && flow.steps) || {{}};
      const mark = (done) => done ? "✓" : "○";
      return '<p class="muted">Stap: ' + mark(s.analyse) + ' Analyse · '
        + mark(s.voorstel) + ' Voorstel · ' + mark(s.uitvoering) + ' Uitvoering · '
        + mark(s.verificatie) + ' Verificatie</p>';
    }}
    function npcData(id) {{
      const list = ((window.PLAYDATA && PLAYDATA.npcs) || []);
      for (const entry of list) {{
        if (entry && entry.id === id) return entry;
      }}
      return {{id: id, name: id, glyph: "•", domain: "", role: "",
               line: "…", badge: "", reason: "", status: "Idle",
               familiar: null,
               panel: {{abilities: [], tools: [], missions: [],
                        evidence: {{}}}},
               mission: {{items: [], note: ""}}}};
    }}
    function npcMerged(npc) {{
      return Object.assign({{}}, npcData(npc.id), npc);
    }}
    const player = {{x: 800, y: 500, r: 14, speed: 250, bob: 0}};
    const cam = {{x: 0, y: 0}};
    const keys = {{}};
    let dialogOpen = false, notifsOpen = false, dialogView = "talk";
    let dialogNpc = NPCS[0];
    const stage = document.getElementById("stage");
    const ctx = stage.getContext("2d");
    const prompt = document.getElementById("interact");
    const dialog = document.getElementById("dialog");
    const dialogBody = document.getElementById("dialog-body");
    const npcBadge = document.getElementById("npc-badge");
    const hud = document.getElementById("play-hud");
    const notifs = document.getElementById("notifs");
    const notifsBody = document.getElementById("notifs-body");
    function escHtml(s) {{
      return String(s === undefined || s === null ? "" : s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }}
    function luma() {{
      return ((window.PLAYDATA && PLAYDATA.luma) || {{}});
    }}
    function circleHitsRect(cx, cy, r, rc) {{
      const nx = Math.max(rc.x, Math.min(cx, rc.x + rc.w));
      const ny = Math.max(rc.y, Math.min(cy, rc.y + rc.h));
      const dx = cx - nx, dy = cy - ny;
      return dx * dx + dy * dy < r * r;
    }}
    function collide(px, py, r) {{
      const solids = WALLS.concat(SOLIDS);
      for (const rc of solids) {{
        if (circleHitsRect(px, py, r, rc)) return rc;
      }}
      return null;
    }}
     function nearestNpc() {{
       let best = null, bestD = 1e9;
       for (const npc of NPCS) {{
         const d = Math.hypot(player.x - npc.x, player.y - npc.y);
         if (d < npc.radius && d < bestD) {{ best = npc; bestD = d; }}
       }}
       return best;
     }}
     function nearestRep() {{
       let best = null, bestD = 1e9;
       for (const rep of worldReps()) {{
         const d = Math.hypot(player.x - rep.x, player.y - rep.y);
         if (d < 70 && d < bestD) {{ best = rep; bestD = d; }}
       }}
       return best;
     }}
     function nearestTarget() {{
       const npc = nearestNpc();
       const rep = nearestRep();
       if (npc && rep) {{
         const dn = Math.hypot(player.x - npc.x, player.y - npc.y);
         const dr = Math.hypot(player.x - rep.x, player.y - rep.y);
         return dn <= dr ? {{npc: npc}} : {{rep: rep}};
       }}
       if (rep) return {{rep: rep}};
       if (npc) return {{npc: npc}};
       return null;
     }}
     function zoneAt() {{
       if (player.y > DIV_Y - 20) {{
         if (Math.hypot(player.x - 375, player.y - 1195) < 150) {{
           const vs = ((window.PLAYDATA && PLAYDATA.verdant) || {{}}).state || "DORMANT";
           return vs === "AWAKENED" ? "Verdant — ontwaakt" : "Verdant — dormant";
         }}
         if (Math.hypot(player.x - 760, player.y - 1240) < 220) return "Ruïne — ontdekking";
         return "Bosrand";
       }}
       if (player.y > DIV_Y - 200 && player.x > DOOR.x - 80 && player.x < DOOR.x + DOOR.w + 80)
         return "Doorgang naar de bosrand";
       if (player.y < 280 && player.x < 660) return "Homebase — Workshop";
       return "Homebase — Werkplaats";
     }}
    function questLine() {{
      const q = ((window.PLAYDATA && PLAYDATA.quest) || {{}});
      return q.title ? ("Huidige quest: " + q.title + " [" + (q.state || "?") + " " + (q.progress || "") + "]") : "Nog geen open quest — kijk bij de Guide.";
    }}
    function renderTalk(npc) {{
      const full = npcMerged(npc);
      let h = "<p><b>" + escHtml(full.line || "…") + "</b></p>"
        + "<p>" + escHtml(full.reason || "") + "</p>";
      if (full.id === "luma") h += '<p class="muted">' + escHtml(questLine()) + "</p>";
      h += '<p><button data-act="goto" data-view="panel">Mogelijkheden bekijken</button></p>';
      return h;
    }}
    function renderFiles() {{
      const inbox = ((((window.PLAYDATA && PLAYDATA.tools) || {{}}).inbox) || []);
      const ev = ((window.PLAYDATA && PLAYDATA.evidence) || {{}});
      const obs = ev.observations || [];
      let h = "<h3>Camera-inbox (" + inbox.length + ")</h3>";
      h += inbox.length ? "<ul>" + inbox.map((f) => "<li>📁 " + escHtml(f) + "</li>").join("") + "</ul>"
        : '<p class="muted">Inbox leeg — leg een JPG in de camera-inbox.</p>';
      h += "<h3>Observaties (" + obs.length + ")</h3>";
      h += obs.length ? "<ul>" + obs.map((o) =>
        '<li>📷 ' + escHtml(o.media || o.id) + ' <span class="muted">' + escHtml(o.device || "") + " " + escHtml(o.created || "") + "</span></li>").join("") + "</ul>"
        : '<p class="muted">Nog geen observaties — start een analyse.</p>';
      h += '<p class="muted">Snapshot bij laden; ververs voor nieuwe data.</p>';
      return h;
    }}
    function renderCandidates() {{
      if (!flow || !flow.observation_id) return '<p class="muted">Start eerst een analyse.</p>';
      const list = flow.candidates || [];
      let h = "<h3>🔎 Kandidaten (" + list.length + ")</h3>" + flowSteps();
      h += list.length ? "<ul>" + list.map((c, i) =>
        '<li><b>' + escHtml(c.label || c.candidate_id) + '</b> <span class="muted">(' + escHtml(String(c.confidence === undefined ? "?" : c.confidence)) + ")</span> "
        + '<button data-act="candidate" data-i="' + i + '">Bekijk</button></li>').join("") + "</ul>"
        + '<p class="muted">Kandidaat bekijken via Bekijk — niets promoveert zichzelf.</p>'
        : '<p class="muted">Geen kandidaten — de VLM vond geen labels (geen proposal mogelijk).</p>';
      h += '<div id="flow-result" class="muted" role="status"></div>';
      return h;
    }}
    function renderCandidateDetail() {{
      const c = flow && flow.candidate;
      if (!c) return renderCandidates();
      const prov = c.provenance || {{}};
      let h = "<h3>🔎 Mogelijk object</h3>"
        + "<p><b>" + escHtml(c.title || "") + "</b></p>"
        + (c.summary ? "<p>" + escHtml(c.summary) + "</p>" : "")
        + '<p class="muted">Staat: ' + escHtml(c.state || "?")
        + " · bron: " + escHtml(prov.source_type || "?") + " door " + escHtml(prov.creator_id || "?")
        + " · human_verified: " + escHtml(String(prov.human_verified)) + "</p>";
      h += ((c.evidence || []).length ? "<ul>" + c.evidence.map((e) =>
        "<li>" + escHtml(e.text || JSON.stringify(e)) + "</li>").join("") + "</ul>" : "")
        + flowSteps()
        + '<p><button data-act="toproposal">Maak voorstel</button> <button data-act="gotocands">Later</button></p>'
        + '<div id="flow-result" class="muted" role="status"></div>'
        + '<p class="muted">Niets promoveert zichzelf — een voorstel is inert tot YES.</p>';
      return h;
    }}
    function renderProposal() {{
      if (!flow || !flow.candidate) return renderCandidates();
      const f = flow;
      let h = "<h3>📝 Voorstel</h3><p><b>Wat gaat er gebeuren?</b></p>" + flowSteps();
      h += '<p><b>Object:</b> ' + escHtml(f.objName || "?") + '<br><span class="muted">' + escHtml((f.objDesc || "").slice(0, 300)) + "</span></p>"
        + '<p><b>File:</b> ' + escHtml(f.fileName || "?") + '<br><span class="muted">sha256 ' + escHtml((f.fileSha || "").slice(0, 16)) + "… · " + escHtml(String(f.fileSize || 0)) + " bytes</span></p>"
        + "<p><b>Bron:</b> " + escHtml(f.filename || "") + " · <b>Provenance:</b> ai-generated, human_verified=False</p>"
        + "<p><b>Status:</b> APPROVAL REQUIRED</p>";
      if (f.objProposalId || f.fileProposalId) {{
        h += "<p><b>Voorstellen:</b> " + escHtml(f.objProposalId || "?") + " / " + escHtml(f.fileProposalId || "?") + "</p>";
      }}
      h += '<p><button data-act="yes">YES — uitvoeren</button> <button data-act="gotocands">Annuleren</button></p>'
        + '<div id="flow-result" class="muted" role="status"></div>';
      return h;
    }}
    function renderWorldChanged() {{
      const f = flow || {{}};
      let h = "<h3>🌱 Wereld veranderd</h3>" + flowSteps();
      h += "<p>Object toegevoegd: <b>" + escHtml(f.objEntity || "?") + "</b><br>File toegevoegd: <b>" + escHtml(f.fileEntity || "?") + "</b></p>";
      const q = ((window.PLAYDATA && PLAYDATA.docquest) || {{}});
      if (q.title) h += '<p><b>QUEST</b> ' + escHtml(q.title) + ' [' + escHtml(q.state || "") + ' ' + escHtml(q.progress || "") + '] <span class="muted">(stand bij laden)</span></p>';
      h += "<p>Luma: <b>Dit is nu onderdeel van je wereld.</b></p>"
        + '<p><button data-act="refresh">Ververs wereld</button> <span class="muted">laadt guide/fungi/meldingen bij</span></p>';
      return h;
    }}
    function renderPanel(npc, section) {{
      const full = npcMerged(npc);
      const panel = full.panel || {{abilities: [], tools: [], missions: [], evidence: {{}}}};
       let h = "<h3>" + escHtml(full.glyph || "") + " " + escHtml(full.name || "") + " — " + escHtml(full.domain || "") + "</h3>"
         + "<p><b>STATUS</b> " + escHtml(full.status || "Idle")
         + (full.badge ? " " + escHtml(full.badge) : "") + " · "
         + escHtml(full.reason || "") + "</p>"
         + '<p class="muted">Rol: ' + escHtml(full.role || "—") + "</p>";
       if (full.activity && full.activity.state) {{
         h += '<p><b>ACTIVITEIT</b> ' + escHtml(full.activity.state) + ' <span class="muted">— ' + escHtml(full.activity.reason || "afgeleid uit backend-state") + "</span></p>";
       }}
      if (full.familiar) {{
        h += '<p class="muted">Familiar-record: ' + escHtml(full.familiar.id) + ' (' + escHtml(full.familiar.kind) + ', ' + escHtml(full.familiar.status) + ')</p>';
      }} else {{
        h += '<p class="muted">Geen familiar-record — placeholder-weergave.</p>';
      }}
      h += '<h3 id="panel-abilities">ABILITIES</h3><ul>' + (panel.abilities || []).map((a) =>
        '<li>' + escHtml(a.name) + ' [' + escHtml(a.type || "?") + ' · ' + escHtml(a.available || "?") + ']'
        + ' <span class="muted">— ' + escHtml(a.via || "") + (a.reason ? ' (' + escHtml(a.reason) + ')' : '') + '</span></li>').join("") + "</ul>";
      h += "<h3>TOOLS</h3><ul>" + (panel.tools || []).map((t) =>
        '<li>' + escHtml(t.name) + ' [' + escHtml(t.state || "?") + '] <span class="muted">— ' + escHtml(t.detail || "") + '</span></li>').join("") + "</ul>";
      const ms = panel.missions || [];
      h += "<h3>MISSIONS</h3>" + (ms.length ? "<ul>" + ms.map((m) =>
        '<li><a href="/missions/' + escHtml(m.id) + '">' + escHtml(m.goal) + '</a> [' + escHtml(m.meta || m.status) + ']</li>').join("") + "</ul>"
        : '<p class="muted">Geen open missies.</p>');
      const ev = panel.evidence || {{}};
      h += "<h3>EVIDENCE</h3><ul>"
        + (ev.observations || []).map((o) => '<li>📷 ' + escHtml(o.media || o.id) + ' <span class="muted">' + escHtml(o.device || "") + ' ' + escHtml(o.created || "") + '</span></li>').join("")
        + (ev.candidates || []).map((c) => '<li>🌱 ' + escHtml(c.title) + ' <span class="muted">[' + escHtml(c.state) + ']</span></li>').join("")
         + (ev.models || []).map((m) => '<li>🧊 ' + escHtml(m.filename || m.model_id) + ' <span class="muted">[' + escHtml(m.verdict || m.status) + ']</span></li>').join("")
         + (ev.fabrecords || []).map((f) => '<li>🧾 ' + escHtml(f.fabrication_id || f.job_id) + ' <span class="muted">[' + escHtml(f.status) + ']</span></li>').join("")
         + (ev.quests || []).map((q) => '<li>🧭 ' + escHtml(q.title) + ' <span class="muted">[' + escHtml(q.state) + ' ' + escHtml(q.progress || "") + ']</span></li>').join("")
         + "</ul>";
      if (section === "abilities") {{
        h += '<p class="muted">↑ abilities hierboven — allemaal bestaande flows, geen nieuwe executie.</p>';
      }}
      return h;
    }}
    function renderMission(npc) {{
      const full = npcMerged(npc);
      const data = full.mission || {{items: [], note: ""}};
      let h = "<h3>Missievoorstel</h3>";
      if (full.id === "luma") {{
        const g = ((window.PLAYDATA && PLAYDATA.guide) || {{}});
        const q = ((window.PLAYDATA && PLAYDATA.quest) || {{}});
        if (g.what) h += '<p><b>Guide:</b> ' + escHtml(g.what) + ' — <a href="' + escHtml(g.href || "/guide") + '">' + escHtml(g.label || "Open") + '</a></p>';
        if (q.title) h += '<p><b>Quest:</b> <a href="' + escHtml(q.href || "/quests") + '">' + escHtml(q.title) + '</a> [' + escHtml(q.state || "") + ' ' + escHtml(q.progress || "") + ']</p>';
      }}
      h += (data.items || []).length ? "<ul>" + data.items.map((m) =>
        '<li><a href="' + escHtml(m.href || "/missions") + '">' + escHtml(m.label) + '</a>' + (m.meta ? ' [' + escHtml(m.meta) + ']' : '') + '</li>').join("") + "</ul>"
        : '<p class="muted">Geen open missies — start er een via <a href="/missions">Missies</a>.</p>';
      if (data.note) h += '<p class="muted">' + escHtml(data.note) + '</p>';
      return h;
    }}
     function renderWorldObj() {{       const r = worldObj;
       if (!r) return '<p class="muted">Geen object gekozen.</p>';
       let h = "<h3>" + escHtml(r.glyph || "•") + " " + escHtml(r.label || r.source_id || "?") + "</h3>"
         + "<p><b>TYPE</b> " + escHtml(r.kind || "?") + " (" + escHtml(r.entity_type || "?") + ")"
         + " · <b>STATUS</b> " + escHtml(r.status || "?") + "</p>"
         + (r.detail ? "<p>" + escHtml(r.detail) + "</p>" : "")
         + '<p class="muted">Bron: INVENTory ' + escHtml(r.source_id || "") + " · zone " + escHtml(r.zone || "") + "</p>";
       if (worldObjDetail) {{
         const d = worldObjDetail;
         const prov = (d && d.provenance) || {{}};
         h += "<h3>Bronrecord</h3>"
           + "<p><b>" + escHtml(d.title || r.label || "?") + "</b></p>"
           + '<p class="muted">provenance: ' + escHtml(prov.source_type || "?") + " door " + escHtml(prov.creator_id || "?")
           + " · human_verified: " + escHtml(String(prov.human_verified)) + "</p>";
       }}
       h += '<p><button data-act="worldrefresh">Detail verversen</button> <a href="' + escHtml(r.href || "/world") + '">Bekijk bron</a></p>'
         + '<p class="muted">Vondsten en onderzoek: <a href="/research">Research</a> · <a href="/symbiosis">Symbiosis</a> · <a href="/knowledge">Kennis</a></p>'
         + '<div id="flow-result" class="muted" role="status"></div>';
       return h;
     }}
     function openWorldObj(rep) {{
       dialogOpen = true;
       dialogNpc = NPCS[0];
       dialogView = "worldobj";
       worldObj = rep;
       worldObjDetail = null;
       npcBadge.textContent = "";
       document.getElementById("dialog-title-name").textContent = (rep.glyph ? rep.glyph + " " : "") + (rep.label || "Object");
       const box = document.getElementById("dialog-choices");
       box.innerHTML = "";
       const b = document.createElement("button");
       b.textContent = "Sluiten";
       b.addEventListener("click", closeDialog);
       box.appendChild(b);
       dialogBody.innerHTML = renderWorldObj();
       dialog.hidden = false;
       document.getElementById("dialog-close").focus();
     }}
     function journeyData() {{
       return ((window.PLAYDATA && PLAYDATA.questlines) || []);
     }}
     function trackerData() {{
       return ((window.PLAYDATA && PLAYDATA.tracker) || []);
     }}
     function discoveryData() {{
       return ((window.PLAYDATA && PLAYDATA.discoveries) || {{items: [], research_open: []}});
     }}
     function trackGlyph(status) {{
       const m = {{draft: "○", pending_approval: "◷", approved: "…", running: "…", paused: "⏸", completed: "✓", failed: "!", cancelled: "○", blocked: "!"}};
       return m[status] || "○";
     }}
     function trackNeeds(status) {{
       const m = {{draft: "beschikbaar — aannemen via Missies", pending_approval: "wacht op exacte YES", approved: "kan tikken — drijft tot gate", running: "kan tikken — drijft tot gate", paused: "hervatten via Missies-pagina", completed: "afgerond", failed: "aandacht nodig — zie Missies", cancelled: "geannuleerd", blocked: "aandacht nodig — zie Missies"}};
       return m[status] || status;
     }}
     function renderJourney() {{
       let h = "<h3>🧭 Reis — echte voortgang, geen XP</h3>";
       const qs = journeyData();
       h += "<h3>Quests (" + qs.length + ")</h3>";
       h += qs.length ? "<ul>" + qs.map((q) =>
         '<li>' + escHtml(q.glyph || "○") + ' <b>' + escHtml(q.title) + '</b> <span class="muted">[' + escHtml(q.state || "?") + " " + escHtml(q.progress || "") + "]</span></li>").join("") + "</ul>"
         : '<p class="muted">Nog geen quests — leg ze aan via <a href="/quests">Quests</a>.</p>';
       const ms = trackerData();
       h += "<h3>Missies (" + ms.length + ")</h3>";
       h += ms.length ? "<ul>" + ms.map((m) =>
         '<li>' + escHtml(m.glyph || trackGlyph(m.status)) + ' <b>' + escHtml(m.goal) + '</b> <span class="muted">[' + escHtml(m.status || "?") + " · " + escHtml(m.needs || trackNeeds(m.status)) + "]</span> "
         + ((m.status === "approved" || m.status === "running") ? '<button data-act="mtick" data-id="' + escHtml(m.id) + '">Tik</button> ' : "")
         + (m.status === "pending_approval" ? '<button data-act="myes" data-id="' + escHtml(m.id) + '">YES — starten</button> ' : "")
         + '<a href="' + escHtml(m.href || "/missions") + '">Missie</a></li>').join("") + "</ul>"
         : '<p class="muted">Nog geen missies — start er een via <a href="/missions">Missies</a>.</p>';
       h += '<p class="muted">Draft = beschikbaar; aannemen gebeurt op de Missies-pagina — de game start niets zelf. Tik drijft goedgekeurd werk tot de eerstvolgende gate.</p>';
       const dc = discoveryData();
       const dn = (dc.items || []).length + (dc.research_open || []).length;
       h += "<h3>Ontdekkingen (" + dn + ")</h3>"
         + (dn ? '<p>Er ligt iets in de Bosrand te wachten. Loop naar de <b>ruïne</b> en druk op E.</p>'
               : '<p class="muted">Geen open ontdekkingen — de ruïne is stil.</p>');
       h += '<p><button data-act="jrefresh">Ververs voortgang</button> <button data-act="refresh">Ververs wereld</button></p>'
         + '<div id="flow-result" class="muted" role="status"></div>';
       return h;
     }}
     function nearDiscovery() {{
       return Math.hypot(player.x - 760, player.y - 1240) < 150;
     }}
     function discoveryCount() {{
       const dc = discoveryData();
       return (dc.items || []).length + (dc.research_open || []).length;
     }}
     function renderDiscovery() {{
       const dc = discoveryData();
       const items = dc.items || [];
       const open = dc.research_open || [];
       let h = "<h3>🗿 Ruïne — ontdekking</h3>";
       if (!items.length && !open.length) {{
         h += '<p class="muted">Nog geen ontdekkingen beschikbaar (FUTURE/UNAVAILABLE). Kom later terug — de wereld groeit met echte vondsten.</p>';
       }} else {{
         h += "<ul>" + items.map((d) =>
            '<li><b>' + escHtml(d.title || d.kind || "Vondst") + '</b> <span class="muted">[' + escHtml(d.kind || "?") + "]</span><br>" + escHtml(d.text || "") + "<br><span class='muted'>" + escHtml(d.evidence || "") + '</span> <a href="' + escHtml(d.link || "/symbiosis") + '">Open</a></li>').join("") + "</ul>";
         h += open.length ? "<h3>Open onderzoeksvragen (" + open.length + ")</h3><ul>" + open.map((d) =>
            "<li>" + escHtml(d.question || "") + ' <a href="' + escHtml(d.link || "/research") + '">Dossier</a></li>').join("") + "</ul>" : "";
         h += '<p class="muted">Alleen bestaande vondsten. Niets opent zichzelf — verder via de echte pagina\u2019s of Luma.</p>';
       }}
       h += '<p><button data-act="journey">Bekijk Reis</button></p>'
         + '<div id="flow-result" class="muted" role="status"></div>';
       return h;
     }}
          function verdantData() {{
       return ((window.PLAYDATA && PLAYDATA.verdant) || {{state: "DORMANT", signals: [], count: 0, mission: null, quests: []}});
     }}
     function nearVerdant() {{
       return Math.hypot(player.x - 375, player.y - 1195) < 150;
     }}
     function renderVerdant() {{
       const v = verdantData();
       const awake = v.state === "AWAKENED";
       let h = "<h3>🌱 Verdant — ecology-bioom [" + escHtml(v.state || "?") + "]</h3>";
       if (!awake) {{
         h += '<p class="muted">Dormant — ontwaakt pas bij echte records (INVENTory-conventie, solar-metingen of ecology-onderzoek). Niets is hier verzonnen.</p>';
       }} else {{
         h += "<p>Ontwaakt door echte data:</p><ul>" + (v.signals || []).map((s) =>
           '<li><b>' + escHtml(s.label || "?") + '</b> <span class="muted">[' + escHtml(s.kind || "?") + (s.detail ? " · " + escHtml(s.detail) : "") + ']</span> <a href="' + escHtml(s.href || "/world") + '">Bron</a></li>').join("") + "</ul>";
       }}
       if (v.mission) {{
         h += '<p><b>Missie-kans:</b> <a href="' + escHtml(v.mission.href || "/missions") + '">' + escHtml(v.mission.goal || "") + '</a> [' + escHtml(v.mission.status || "") + ']</p>';
       }}
       if (v.rep && v.rep.source_id) {{
         h += '<p><b>Representatie in de bioom:</b> ' + escHtml(v.rep.label || v.rep.source_id) + ' <span class="muted">— loop erheen en druk op E om te inspecteren</span></p>';
       }}
       const vq = v.quests || [];
       if (vq.length) {{
         h += "<p><b>Quests:</b> " + vq.map((q) =>
           escHtml(q.title) + ' [' + escHtml(q.state || "") + " " + escHtml(q.progress || "") + "]").join(" · ") + ' — <a href="/quests">Quests</a></p>';
       }}
       h += '<p class="muted">Ruimte voor planten, bodem, water en experimenten — zodra echte data die vult.</p>'
         + '<p><button data-act="refresh">Ververs wereld</button></p>'
         + '<div id="flow-result" class="muted" role="status"></div>';
       return h;
     }}
     function openVerdant() {{
       dialogOpen = true;
       dialogNpc = NPCS[0];
       dialogView = "verdant";
       const v = verdantData();
       npcBadge.textContent = v.state === "AWAKENED" ? "🌱" : "";
       document.getElementById("dialog-title-name").textContent = "🌱 Verdant";
       const box = document.getElementById("dialog-choices");
       box.innerHTML = "";
       const b = document.createElement("button");
       b.textContent = "Sluiten";
       b.addEventListener("click", closeDialog);
       box.appendChild(b);
       dialogBody.innerHTML = renderVerdant();
       dialog.hidden = false;
       document.getElementById("dialog-close").focus();
     }}
     function openDiscovery() {{       dialogOpen = true;
       dialogNpc = NPCS[0];
       dialogView = "discovery";
       npcBadge.textContent = discoveryCount() ? "?" : "";
       document.getElementById("dialog-title-name").textContent = "🗿 Ruïne";
       const box = document.getElementById("dialog-choices");
       box.innerHTML = "";
       const b = document.createElement("button");
       b.textContent = "Sluiten";
       b.addEventListener("click", closeDialog);
       box.appendChild(b);
       dialogBody.innerHTML = renderDiscovery();
       dialog.hidden = false;
       document.getElementById("dialog-close").focus();
     }}
     function renderNotifs() {{
      const ns = ((window.PLAYDATA && PLAYDATA.notifications) || []);
      const ev = ((window.PLAYDATA && PLAYDATA.events) || []);
      let h = "<h3>Meldingen (" + ns.length + ")</h3>";
      h += ns.length ? "<ul>" + ns.map((n) =>
        '<li><b>' + escHtml(n.title) + '</b> <span class="muted">[' + escHtml(n.type) + ' ' + escHtml(n.created) + ']</span></li>').join("") + "</ul>"
        : '<p class="muted">Geen meldingen.</p>';
      h += "<h3>Gebeurtenissen (" + ev.length + ")</h3>";
      h += ev.length ? "<ul>" + ev.map((e) =>
        '<li><b>' + escHtml(e.type) + '</b> ' + escHtml(e.summary) + ' <span class="muted">' + escHtml(e.created) + '</span></li>').join("") + "</ul>"
        : '<p class="muted">Geen gebeurtenissen.</p>';
      return h;
    }}
     let printModel = 0;
     let forgeFlow = null;
     function forgeData() {{
       return ((window.PLAYDATA && PLAYDATA.forge) || {{models: [], printers: [], missions: [], profiles: [], quests: [], fabrecords: []}});
     }}
     function forgeSteps() {{
       const s = (forgeFlow && forgeFlow.steps) || {{}};
       const mark = (done) => done ? "✓" : "○";
       return '<p class="muted">Sessie: ' + mark(s.model) + ' Model · '
         + mark(s.analyse) + ' Analyse · '
         + mark(s.voorstel) + ' Voorstel · ' + mark(s.approval) + ' Approval · '
         + mark(s.hardware) + ' Hardware · ' + mark(s.uitvoering) + ' Uitvoering · '
         + mark(s.verificatie) + ' Verificatie</p>';
     }}
     function forgePrinterBlock() {{
       const F = forgeData();
       if ((F.printers || []).length) {{
         return "<ul>" + F.printers.map((p) =>
           '<li>🖨️ ' + escHtml(p.name || p.printer_id) + ' <span class="muted">[' + escHtml(p.status) + (p.adapter ? ", adapter" : ", geen adapter") + ']</span></li>').join("") + "</ul>";
       }}
       return '<div class="panel"><h3>🖨️ PRINTER</h3><p><b>A1 Mini</b><br>NIET VERBONDEN<br>'
         + '<span class="muted">HARDWARE_REQUIRED — geen printer geregistreerd, geen adapter, fysiek printen onmogelijk.</span></p>'
         + '<p><a href="/hardware">Meer informatie</a></p></div>';
     }}
    function renderLumaFlow() {{
      const devs = ((window.PLAYDATA && PLAYDATA.devices) || []);
      const inbox = ((((window.PLAYDATA && PLAYDATA.tools) || {{}}).inbox) || []);
      const ev = ((window.PLAYDATA && PLAYDATA.evidence) || {{}});
      const obs = ev.observations || [];
      let h = "<h3>Analyseer — inbox &amp; observaties</h3>"
        + '<p class="muted">Poll draait de bestaande sessie-flow (geen writes). Beschrijf draait de VLM of eerlijke fallback.</p>'
        + '<p><select id="flow-device" aria-label="Camera">' + devs.map((d) => '<option value="' + escHtml(d.device_id) + '">' + escHtml(d.name || d.device_id) + '</option>').join("") + '</select> '
        + '<button data-act="poll">Poll inbox nu</button></p>'
        + "<h3>Inbox (" + inbox.length + ")</h3><ul>" + inbox.map((f) => "<li>" + escHtml(f) + "</li>").join("") + "</ul>"
        + "<h3>Observaties (" + obs.length + ")</h3><ul>" + obs.map((o) =>
          '<li>📷 ' + escHtml(o.media || o.id) + ' <span class="muted">' + escHtml(o.device || "") + '</span> '
          + '<button data-act="describe" data-obs="' + escHtml(o.id) + '">Beschrijf</button></li>').join("") + "</ul>"
        + '<div id="flow-result" class="muted" role="status"></div>'
        + '<p class="muted">Resultaten verschijnen hier; ververs daarna de pagina voor nieuwe data.</p>';
      return h;
    }}
    function renderPrintModels() {{
      const F = forgeData();
      let h = "<h3>Help mij iets te printen — kies model</h3>";
      h += F.models.length ? "<ul>" + F.models.map((m, i) =>
        '<li>🧊 ' + escHtml(m.filename || m.model_id) + ' <span class="muted">[' + escHtml(m.verdict || m.status) + ', ' + escHtml(String(m.size || 0)) + ' bytes]</span> '
        + '<button data-act="pickmodel" data-i="' + i + '">Kies</button></li>').join("") + "</ul>"
        : '<p class="muted">Geen modellen — registreer er een via <a href="/workshop/3d">3D-workbench</a>.</p>';
      h += '<div id="flow-result" class="muted" role="status"></div>';
      return h;
    }}
     function renderPrintDetail() {{
       const F = forgeData();
       const m = (F.models || [])[printModel];
       if (!m) return renderPrintModels();
       if (!forgeFlow || forgeFlow.modelId !== m.model_id) {{
         forgeFlow = {{steps: {{model: true}}, modelId: m.model_id, filename: m.filename || ""}};
       }}
       const profs = F.profiles || [];
       let h = "<h3>" + escHtml(m.filename || m.model_id) + "</h3>" + forgeSteps()
         + '<p class="muted">Mesh-verdict: ' + escHtml(m.verdict || "?") + ' · status: ' + escHtml(m.status || "?") + '</p>';
       h += "<h3>Printability</h3>";
       if (forgeFlow.assessment) {{
         h += '<p><b>' + escHtml(forgeFlow.assessment) + '</b> <span class="muted">' + escHtml(forgeFlow.assessNote || "") + '</span></p>';
       }} else {{
         h += '<p class="muted">Nog niet gecontroleerd in deze sessie.</p>';
       }}
       h += '<p><button data-act="inspect">Printability controleren</button> <span class="muted">bestaande inspectie + assess, geen writes</span></p>';
       h += "<h3>Slicer/profile</h3>";
       if (forgeFlow.slice) {{
         h += '<p><b>' + escHtml(forgeFlow.gcodeRef || "") + '</b> <span class="muted">profiel ' + escHtml(forgeFlow.profile || "") + ' · safety ' + escHtml(forgeFlow.safety || "?") + ' · sha ' + escHtml((forgeFlow.gcodeSha || "").slice(0, 12)) + '…</span></p>';
       }}
       h += '<p><label>Profiel <select id="fp-profile">' + profs.map((p) => '<option>' + escHtml(p) + '</option>').join("") + '</select></label> '
         + '<button data-act="slice">Test-slice uitvoeren</button></p>';
       h += "<h3>Printerstatus</h3>" + forgePrinterBlock();
       if (!(F.printers || []).length) {{
         h += '<p class="muted">DIGITAL: modellen beschikbaar · HARDWARE: printer NIET VERBONDEN — registreer via <a href="/hardware">Hardware</a>.</p>';
       }} else {{
         h += '<p><label>Printer <select id="fp-printer">' + F.printers.map((p) => '<option value="' + escHtml(p.printer_id) + '">' + escHtml(p.name || p.printer_id) + '</option>').join("") + '</select></label></p>'
           + '<p><button data-act="topreview">Printvoorstel bekijken</button> <span class="muted">maakt inert voorstel; print nooit automatisch</span></p>'
           + '<p><button data-act="topropose">Print voorbereiden</button> <span class="muted">maakt inert voorstel; print nooit automatisch</span></p>';
       }}
       h += '<div id="flow-result" class="muted" role="status"></div>';
       return h;
     }}
     function renderForgePreview() {{
       const F = forgeData();
       const fl = forgeFlow || {{steps: {{}}}};
       if (!fl.slice || !fl.gcodeRef) return renderPrintDetail();
       const printers = F.printers || [];
       const sel = document.getElementById("fp-printer");
       const pid = fl.printerId || (sel ? sel.value : "") || (printers[0] ? printers[0].printer_id : "");
       fl.printerId = pid;
       const printer = printers.find((p) => p.printer_id === pid);
       let h = "<h3>🖨️ Printvoorstel</h3>" + forgeSteps()
         + "<p><b>MODEL</b> " + escHtml(fl.filename || "?") + "</p>"
         + "<p><b>PRINTABILITY</b> " + escHtml(fl.assessment || "niet gecontroleerd") + "</p>"
         + "<p><b>SLICER</b> " + escHtml(fl.profile || "?") + " · safety " + escHtml(fl.safety || "?") + " · " + escHtml(fl.gcodeRef || "?") + "</p>"
         + "<p><b>PRINTER</b> " + (printer ? escHtml(printer.name || printer.printer_id) + ' <span class="muted">[' + escHtml(printer.status) + (printer.adapter ? ", adapter" : ", geen adapter") + "]</span>" : "A1 Mini — NIET VERBONDEN [HARDWARE_REQUIRED]") + "</p>"
         + "<p><b>RISICO / REQUIREMENTS</b> <span class='muted'>exacte YES vereist · fingerprint-binding · TTL · revalidate direct voor uitvoering · adapter met printer.start vereist · verificatie via telemetrie + camera</span></p>"
         + "<p><b>PROPOSAL</b> Inert printer.execute-voorstel voor exact deze G-code. Niets beweegt tot YES + hardware.</p>"
         + '<p><button data-act="forgeyes">YES</button> <button data-act="gotoprint">Annuleren</button></p>'
         + '<div id="flow-result" class="muted" role="status"></div>';
       return h;
     }}
     function renderForgeResult() {{
       const fl = forgeFlow || {{steps: {{}}}};
       let h = "<h3>🖨️ Voorstelstatus</h3>" + forgeSteps();
       h += "<p><b>Voorstel:</b> " + escHtml(fl.proposalId || "?") + ' <span class="muted">' + escHtml(fl.approval || "niet approved") + "</span></p>";
       h += "<p><b>Hardware:</b> " + escHtml(fl.hardwareNote || "ongecontroleerd") + "</p>";
       h += "<p><b>Uitvoering:</b> " + escHtml(fl.execStatus || "niet uitgevoerd") + (fl.execNote ? ' <span class="muted">' + escHtml(fl.execNote) + "</span>" : "") + "</p>";
       if (fl.verification) {{
         h += "<p><b>Verificatie:</b> " + escHtml(fl.verification) + "</p>";
       }} else if (fl.execStatus === "executed") {{
         h += '<p><button data-act="forgeverify">Controleren</button> <span class="muted">onafhankelijke readback; uitvoering alleen is geen verificatie</span></p>';
       }} else {{
         h += '<p class="muted">Verificatie open — zonder uitvoering valt er niets te verifiëren.</p>';
       }}
       h += '<p><button data-act="forgequest">Missie-evidence bekijken</button> <button data-act="refresh">Ververs wereld</button> <span class="muted">laadt guide/fungi/meldingen bij</span></p>'
         + '<div id="flow-result" class="muted" role="status"></div>';
       return h;
     }}
     function renderForgeQuest() {{
       const F = forgeData();
       const quests = F.quests || [];
       const fabs = F.fabrecords || [];
       let h = "<h3>🧭 Missie-evidence</h3>" + forgeSteps();
       h += quests.length ? "" : '<p class="muted">Geen fabricatiequests geladen — leg ze aan via <a href="/missions">Missies</a> (seeds).</p>';
       for (const q of quests) {{
         h += "<h3>" + escHtml(q.title) + ' <span class="muted">[' + escHtml(q.state) + " " + escHtml(q.progress || "") + "]</span></h3><ul>"
           + (q.steps || []).map((s) => "<li>" + escHtml(s.glyph || "○") + " " + escHtml(s.label) + ' <span class="muted">[' + escHtml(s.state) + (s.readiness ? " · " + escHtml(s.readiness) : "") + "]</span></li>").join("") + "</ul>";
       }}
       h += "<h3>🧾 Fabrication-records (" + fabs.length + ")</h3>";
       h += fabs.length ? "<ul>" + fabs.map((f) =>
         "<li>" + escHtml(f.fabrication_id || f.job_id) + ' <span class="muted">[' + escHtml(f.status) + "]</span></li>").join("") + "</ul>"
         : '<p class="muted">Nog geen fabrication-records — er is niets uitgevoerd.</p>';
       h += '<p class="muted">Alleen bestaande records tellen: een voorstel voedt geen quest-completion. Ververs voor nieuwe data.</p>'
         + '<p><button data-act="refresh">Ververs wereld</button></p>'
         + '<div id="flow-result" class="muted" role="status"></div>';
       return h;
     }}
    function renderPrintPropose() {{
      const F = forgeData();
      const m = (F.models || [])[printModel];
      if (!m) return renderPrintModels();
      const profs = F.profiles || [];
      let h = "<h3>Print voorbereiden — " + escHtml(m.filename || m.model_id) + "</h3>"
        + '<p class="muted">Vereist gcode-artefact + printer. Voorstel is inert; exacte YES gebeurt elders.</p>'
        + '<p><label>Printer <select id="pp-printer">' + F.printers.map((p) => '<option value="' + escHtml(p.printer_id) + '">' + escHtml(p.name || p.printer_id) + '</option>').join("") + '</select></label></p>'
        + '<p><label>gcode_ref <input id="pp-gcode" style="width:60%"></label></p>'
        + '<p><label>gcode_sha256 <input id="pp-sha" style="width:60%"></label></p>'
        + '<p><label>Profiel <select id="pp-profile">' + profs.map((p) => '<option>' + escHtml(p) + '</option>').join("") + '</select></label></p>'
        + '<p><button data-act="propose">Voorstel indienen</button></p>'
        + '<div id="flow-result" class="muted" role="status"></div>';
      return h;
    }}
    async function postJSON(url, body, method) {{
      const m = method || "POST";
      const opts = {{method: m, headers: {{"Content-Type": "application/json"}}}};
      if (m !== "GET") opts.body = body ? JSON.stringify(body) : "{{}}";
      const r = await fetch(url, opts);
      const t = await r.text();
      let j = null;
      try {{ j = JSON.parse(t); }} catch (e) {{}}
      if (!r.ok) {{
        const detail = (j && (j.detail || j.error)) || t;
        throw new Error("HTTP " + r.status + " " + String(detail).slice(0, 200));
      }}
      return j;
    }}
    function obsMedia(oid) {{
      const ev = ((window.PLAYDATA && PLAYDATA.evidence) || {{}});
      for (const o of (ev.observations || [])) {{
        if (o.id === oid) return o.media || "";
      }}
      return "";
    }}
    function flowResult(msg) {{
      const el = document.getElementById("flow-result");
      if (el) el.textContent = msg;
    }}
    function openDialog(npc, view) {{
      dialogOpen = true;
      dialogNpc = npc;
      dialogView = view || "talk";
      const full = npcMerged(npc);
      npcBadge.textContent = full.badge || "";
      document.getElementById("dialog-title-name").textContent = (full.glyph ? full.glyph + " " : "") + (full.name || "NPC");
      const box = document.getElementById("dialog-choices");
      box.innerHTML = "";
      const choices = CHOICES[full.id] || CHOICES.luma;
      choices.forEach((c) => {{
        const b = document.createElement("button");
        b.textContent = c.l;
        b.setAttribute("data-view", c.v);
        b.addEventListener("click", () => {{
          if (c.v === "later") closeDialog();
          else openDialog(dialogNpc, c.v);
        }});
        box.appendChild(b);
      }});
      if (dialogView === "panel" || dialogView === "abilities") dialogBody.innerHTML = renderPanel(npc, dialogView);
      else if (dialogView === "mission") dialogBody.innerHTML = renderMission(npc);
       else if (dialogView === "files") dialogBody.innerHTML = renderFiles();
       else if (dialogView === "journey") dialogBody.innerHTML = renderJourney();
       else if (dialogView === "discovery") dialogBody.innerHTML = renderDiscovery();
      else if (dialogView === "lumaflow") dialogBody.innerHTML = renderLumaFlow();
      else if (dialogView === "candidates") dialogBody.innerHTML = renderCandidates();
      else if (dialogView === "candidate") dialogBody.innerHTML = renderCandidateDetail();
      else if (dialogView === "proposal") dialogBody.innerHTML = renderProposal();
      else if (dialogView === "worldchanged") dialogBody.innerHTML = renderWorldChanged();
       else if (dialogView === "print") dialogBody.innerHTML = renderPrintModels();
       else if (dialogView === "printdetail") dialogBody.innerHTML = renderPrintDetail();
       else if (dialogView === "printpropose") dialogBody.innerHTML = renderPrintPropose();
       else if (dialogView === "printpreview") dialogBody.innerHTML = renderForgePreview();
       else if (dialogView === "forgeresult") dialogBody.innerHTML = renderForgeResult();
       else if (dialogView === "quest") dialogBody.innerHTML = renderForgeQuest();
      else dialogBody.innerHTML = renderTalk(npc);
      dialog.hidden = false;
      document.getElementById("dialog-close").focus();
    }}
    function closeDialog() {{
      dialogOpen = false;
      dialog.hidden = true;
      stage.focus();
    }}
    function openNotifs() {{
      notifsOpen = true;
      notifsBody.innerHTML = renderNotifs();
      notifs.hidden = false;
      document.getElementById("notifs-close").focus();
    }}
    function closeNotifs() {{
      notifsOpen = false;
      notifs.hidden = true;
      stage.focus();
    }}
    document.getElementById("dialog-close").addEventListener("click", closeDialog);
    document.getElementById("notifs-close").addEventListener("click", closeNotifs);
    document.getElementById("notif-open").addEventListener("click", () => {{ if (!notifsOpen) openNotifs(); }});
    document.getElementById("guide-chip").addEventListener("click", (e) => {{
      if (e.target.tagName !== "A") {{
        const npc = NPCS[0];
        openDialog(npc, "mission");
      }}
    }});
    dialogBody.addEventListener("click", async (e) => {{
      const btn = (e.target && e.target.closest) ? e.target.closest("button[data-act]") : null;
      if (!btn) return;
      const act = btn.getAttribute("data-act");
      try {{
        if (act === "poll") {{
          const sel = document.getElementById("flow-device");
          const dev = sel ? sel.value : "";
          if (!dev) throw new Error("geen camera gekozen");
          const res = await postJSON("/api/v1/cameras/" + encodeURIComponent(dev) + "/poll-inbox");
          const ing = (res && res.ingested) || [];
          flow = {{steps: {{}}, device_id: dev}};
          if (ing.length) {{
            flow.observation_id = ing[0].observation_id || "";
            flow.filename = ing[0].filename || "";
          }}
          flowResult("Poll klaar: " + ing.length + " verwerkt, " + (((res && res.duplicates) || []).length) + " duplicaten, " + (((res && res.refused) || []).length) + " geweigerd. Ververs voor nieuwe data.");
        }} else if (act === "describe") {{
          const oid = btn.getAttribute("data-obs") || "";
          const dev = btn.getAttribute("data-dev") || "";
          const res = await postJSON("/api/v1/observations/" + encodeURIComponent(oid) + "/describe", {{}});
          const an = (res && res.analysis) || {{}};
          const labels = (an.labels || []).join(", ");
          const det = (an.detected_objects || []).map((d) => (d.label || "") + " (" + d.confidence + ")").join(", ");
          flow = flow || {{steps: {{}}}};
          flow.observation_id = oid;
          flow.device_id = dev;
          flow.filename = flow.filename || obsMedia(oid);
          flow.vlm_state = (res && res.vlm_state) || "?";
          flow.labels = an.labels || [];
          flow.description = an.description || "";
          flow.candidates = [];
          flow.steps = flow.steps || {{}};
          if (flow.vlm_state === "REAL" && flow.labels.length) {{
            const pc = await postJSON("/api/v1/observations/" + encodeURIComponent(oid) + "/propose-candidates", {{}});
            flow.candidates = (pc && pc.candidates) || [];
          }}
          flow.steps.analyse = true;
          dialogBody.innerHTML = renderCandidates();
          flowResult("VLM " + flow.vlm_state + (labels ? ": " + labels : " (geen labels — geen proposal)") + (det ? " | " + det : ""));
        }} else if (act === "goto") {{
          openDialog(dialogNpc, btn.getAttribute("data-view") || "panel");
        }} else if (act === "gotocands") {{
          dialogBody.innerHTML = renderCandidates();
        }} else if (act === "candidate") {{
          const i = parseInt(btn.getAttribute("data-i") || "0", 10) || 0;
          const item = ((flow && flow.candidates) || [])[i];
          if (!item) throw new Error("kandidaat onbekend");
          const detail = await postJSON("/api/v1/candidates/" + encodeURIComponent(item.candidate_id), null, "GET");
          flow.candidate = detail;
          flow.candidateLabel = item.label || "";
          flow.candidateConfidence = (item.confidence === undefined ? "" : String(item.confidence));
          dialogBody.innerHTML = renderCandidateDetail();
        }} else if (act === "toproposal") {{
          if (!flow || !flow.candidate) throw new Error("geen kandidaat gekozen");
          const c = flow.candidate;
          if (!flow.filename) flow.filename = obsMedia(flow.observation_id);
          if (!flow.filename) throw new Error("bestandsnaam onbekend — ververs en analyseer opnieuw");
          const facts = await postJSON("/api/v1/inbox/" + encodeURIComponent(flow.filename) + "/facts?device_id=" + encodeURIComponent(flow.device_id || ""), null, "GET");
          const fp = (facts && facts.file_payload) || {{}};
          flow.fileName = fp.name || flow.filename || "";
          flow.fileSha = fp.sha256 || "";
          flow.fileSize = fp.size_bytes || 0;
          flow.filePayload = fp;
          flow.objName = (flow.candidateLabel || c.title || "object").slice(0, 200);
          flow.objDesc = ((c.summary || "") + " | VLM: " + (flow.labels || []).join(", ") + " | observatie " + (flow.observation_id || "")).slice(0, 900);
          flow.objProposalId = ""; flow.fileProposalId = "";
          dialogBody.innerHTML = renderProposal();
        }} else if (act === "yes") {{
          if (!flow || !flow.filePayload) throw new Error("geen voorstel voorbereid");
          flowResult("Voorstellen aanmaken…");
          const obj = await postJSON("/api/v1/writes/inventory", {{mutation: "create", entity_type: "object", fields: {{name: flow.objName, description: flow.objDesc}}, actor: "game-jelles"}});
          flow.objProposalId = (obj && obj.proposal && obj.proposal.proposal_id) || "";
          const fil = await postJSON("/api/v1/writes/inventory", {{mutation: "create", entity_type: "file", fields: flow.filePayload, actor: "game-jelles"}});
          flow.fileProposalId = (fil && fil.proposal && fil.proposal.proposal_id) || "";
          if (!flow.objProposalId || !flow.fileProposalId) throw new Error("voorstel niet opgeslagen");
          flow.steps.voorstel = true;
          flowResult("Beide voorstellen opgeslagen — nu approven + uitvoeren…");
          const okO = await postJSON("/api/v1/writes/" + encodeURIComponent(flow.objProposalId) + "/approve", {{response: "YES", decided_by: "jelles"}});
          const okF = await postJSON("/api/v1/writes/" + encodeURIComponent(flow.fileProposalId) + "/approve", {{response: "YES", decided_by: "jelles"}});
          if ((okO && okO.status) !== "approved" || (okF && okF.status) !== "approved") throw new Error("YES geweigerd door bestaande gate");
          flowResult("YES vastgelegd — uitvoeren…");
          const exO = await postJSON("/api/v1/writes/" + encodeURIComponent(flow.objProposalId) + "/execute", {{}});
          const exF = await postJSON("/api/v1/writes/" + encodeURIComponent(flow.fileProposalId) + "/execute", {{}});
          if ((exO && exO.status) !== "executed" || (exF && exF.status) !== "executed") throw new Error("execute niet geslaagd — niets is geverifieerd");
          flow.steps.uitvoering = true;
          flow.execResult = {{obj: exO, file: exF}};
          dialogBody.innerHTML = renderProposal();
          flowResult("Uitgevoerd — controleer nu via [Controleren]. Uitvoering alleen is geen verificatie.");
          const bar = document.createElement("p");
          bar.innerHTML = '<button data-act="verify">Controleren</button>';
          dialogBody.appendChild(bar);
        }} else if (act === "verify") {{
          if (!flow || !flow.objProposalId) throw new Error("niets uit te voeren controles");
          flowResult("Onafhankelijke readback loopt…");
          const vO = await postJSON("/api/v1/writes/" + encodeURIComponent(flow.objProposalId) + "/verify", {{}});
          const vF = await postJSON("/api/v1/writes/" + encodeURIComponent(flow.fileProposalId) + "/verify", {{}});
          const oO = vO && vO.verification && vO.verification.outcome;
          const oF = vF && vF.verification && vF.verification.outcome;
          if (oO === "passed" && oF === "passed") {{
            flow.steps.verificatie = true;
            const aO = (vO.result && vO.result.after) || {{}};
            const aF = (vF.result && vF.result.after) || {{}};
            flow.objEntity = aO.id || aO.entity_id || "?";
            flow.fileEntity = aF.id || aF.entity_id || "?";
            dialogBody.innerHTML = renderWorldChanged();
          }} else {{
            flowResult("Verificatie: object=" + oO + " file=" + oF + " — NIET verified. Geen wereldverandering geclaimd.");
          }}
        }} else if (act === "refresh") {{
          window.location.reload();
         }} else if (act === "pickmodel") {{
           printModel = parseInt(btn.getAttribute("data-i") || "0", 10) || 0;
           dialogBody.innerHTML = renderPrintDetail();
         }} else if (act === "journey") {{
           dialogBody.innerHTML = renderJourney();
         }} else if (act === "jrefresh") {{
           flowResult("Voortgang verversen (read-only)…");
           try {{
             const ml = await postJSON("/api/v1/missions", null, "GET");
             const list = Array.isArray(ml) ? ml : [];
             const tracks = [];
             for (const m of list) {{
               const st = String((m && m.status) || "");
               if (st === "cancelled") continue;
               const mid = String((m && (m.mission_id || m.id)) || "");
               tracks.push({{id: mid, goal: String((m && m.goal) || ""), status: st, glyph: trackGlyph(st), needs: trackNeeds(st), href: "/missions/" + mid}});
               if (tracks.length >= 12) break;
             }}
             tracks.sort((a, b) => (a.id < b.id ? -1 : 1));
             if (window.PLAYDATA) PLAYDATA.tracker = tracks;
             const ql = await postJSON("/api/v1/quests?limit=20", null, "GET");
             const qs = ((ql && ql.quests) || []);
             if (window.PLAYDATA) PLAYDATA.questlines = qs.slice(0, 20).map((q) => ({{quest_id: q.quest_id || "", title: q.title || "", state: q.state || "", progress: q.progress || "", glyph: q.state === "COMPLETED" ? "✓" : (q.state === "FAILED" || q.state === "BLOCKED") ? "!" : "○"}}));
           }} catch (eJ) {{
             flowResult("Verversen geweigerd: " + ((eJ && eJ.message) || ""));
             return;
           }}
           dialogBody.innerHTML = renderJourney();
           flowResult("Voortgang bijgewerkt uit bestaande records.");
         }} else if (act === "mtick") {{
           const mid = btn.getAttribute("data-id") || "";
           if (!mid) throw new Error("missie onbekend");
           flowResult("Tik loopt — drijft tot de eerstvolgende gate…");
           const res = await postJSON("/api/v1/missions/" + encodeURIComponent(mid) + "/tick", {{}});
           const st = String((res && (res.status || (res.mission && res.mission.status))) || "?");
           flowResult("Tik klaar: missie-status " + st + ". Ververs de Reis voor het volledige beeld.");
         }} else if (act === "myes") {{
           const mid = btn.getAttribute("data-id") || "";
           if (!mid) throw new Error("missie onbekend");
           flowResult("Exacte YES vastleggen via bestaande gate…");
           const res = await postJSON("/api/v1/missions/" + encodeURIComponent(mid) + "/approve", {{response: "YES", decided_by: "jelles"}});
           const st = String((res && (res.status || (res.mission && res.status))) || "?");
           if (st !== "approved") throw new Error("YES geweigerd door bestaande gate (" + st + ")");
           flowResult("Missie approved — tik nu om te drijven.");
           dialogBody.innerHTML = renderJourney();
         }} else if (act === "gotoprint") {{
           dialogBody.innerHTML = renderPrintModels();
         }} else if (act === "worldrefresh") {{
           const r = worldObj;
           if (!r || !r.source_id) throw new Error("geen bronrecord om te verversen");
           flowResult("Bronrecord ophalen (read-only)…");
           const detail = await postJSON("/api/v1/world/entity/" + encodeURIComponent(r.entity_type || "") + "/" + encodeURIComponent(r.source_id), null, "GET");
           worldObjDetail = detail;
           dialogBody.innerHTML = renderWorldObj();
           flowResult("Bronrecord geladen — dit is een afbeelding, geen kopie.");
         }} else if (act === "inspect") {{
           const F = forgeData();
           const m = (F.models || [])[printModel];
           if (!m) throw new Error("geen model gekozen");
           forgeFlow = forgeFlow || {{steps: {{model: true}}}};
           flowResult("Inspectie loopt…");
           const insp = await postJSON("/api/v1/workshop/models/" + encodeURIComponent(m.model_id) + "/inspect", {{}});
           const verdict = ((insp && insp.inspection) || {{}}).mesh_verdict || "?";
           let assess = "?";
           try {{
             const ar = await postJSON("/api/v1/fab/assess?mesh_ref=" + encodeURIComponent(m.filename || ""), {{}});
             assess = ((ar && ar.assessment) || {{}}).verdict || "?";
             forgeFlow.assessNote = (ar && ar.next_step) || "";
           }} catch (e2) {{
             assess = "assess geweigerd";
             forgeFlow.assessNote = (e2 && e2.message) || "";
           }}
           forgeFlow.assessment = verdict + " / " + assess;
           forgeFlow.steps.analyse = true;
           dialogBody.innerHTML = renderPrintDetail();
           flowResult("Analyse: inspect=" + verdict + " assess=" + assess + ". Niets is gesliced of voorgesteld.");
         }} else if (act === "slice") {{
           const F = forgeData();
           const m = (F.models || [])[printModel];
           if (!m) throw new Error("geen model gekozen");
           const printers = F.printers || [];
           if (!printers.length) throw new Error("geen printer verbonden — slicen wacht op hardware");
           const sel = document.getElementById("fp-printer");
           const pid = (sel ? sel.value : "") || printers[0].printer_id;
           const profSel = document.getElementById("fp-profile");
           const prof = (profSel ? profSel.value : "") || (F.profiles || [])[0] || "draft-pla";
           forgeFlow = forgeFlow || {{steps: {{model: true}}}};
           flowResult("Test-slice loopt…");
           const res = await postJSON("/api/v1/fab/slice", {{artifact_ref: m.filename || "", profile: prof, printer_id: pid}});
           const sl = (res && res.slice) || {{}};
           forgeFlow.slice = true;
           forgeFlow.profile = prof;
           forgeFlow.printerId = pid;
           forgeFlow.gcodeRef = sl.gcode_ref || "";
           forgeFlow.gcodeSha = sl.sha256 || "";
           forgeFlow.safety = ((res && res.safety) || {{}}).verdict || "?";
           if (!forgeFlow.gcodeRef || !forgeFlow.gcodeSha) throw new Error("slice leverde geen gcode-artefact");
           dialogBody.innerHTML = renderPrintDetail();
           flowResult("Slice klaar: " + forgeFlow.gcodeRef + " safety=" + forgeFlow.safety + ". Bekijk nu het voorstel.");
         }} else if (act === "topreview") {{
           dialogBody.innerHTML = renderForgePreview();
         }} else if (act === "forgeyes") {{
           const fl = forgeFlow || {{steps: {{}}}};
           if (!fl.gcodeRef || !fl.gcodeSha || !fl.printerId) throw new Error("geen volledig voorstel — controleer en slice eerst");
           flowResult("Voorstel aanmaken (inert)…");
           const res = await postJSON("/api/v1/prints/propose", {{printer_id: fl.printerId, gcode_ref: fl.gcodeRef, gcode_sha256: fl.gcodeSha, profile: fl.profile || "draft-pla", actor: "game-jelles"}});
           fl.proposalId = (res && res.proposal_id) || (res && res.proposal && res.proposal.proposal_id) || "";
           if (!fl.proposalId) throw new Error("voorstel niet opgeslagen");
           fl.steps.voorstel = true;
           flowResult("Voorstel " + fl.proposalId + " opgeslagen — nu exacte YES…");
           const ok = await postJSON("/api/v1/writes/" + encodeURIComponent(fl.proposalId) + "/approve", {{response: "YES", decided_by: "jelles"}});
           if ((ok && ok.status) !== "approved") throw new Error("YES geweigerd door bestaande gate");
           fl.approval = "approved (exacte YES)";
           fl.steps.approval = true;
           let hwNote = "geen adapter bekend";
           try {{
             const info = await postJSON("/api/v1/printers/" + encodeURIComponent(fl.printerId), null, "GET");
             hwNote = info && info.adapter ? ("adapter " + info.adapter) : "printer bekend, geen adapter";
             if (info && info.adapter) fl.steps.hardware = true;
           }} catch (eH) {{
             hwNote = "printer onleesbaar: " + ((eH && eH.message) || "");
           }}
           fl.hardwareNote = hwNote;
           flowResult("YES vastgelegd — hardware-check en uitvoering…");
           const ex = await postJSON("/api/v1/writes/" + encodeURIComponent(fl.proposalId) + "/execute", {{}});
           fl.execStatus = (ex && ex.status) || "?";
           const exRes = (ex && ex.result) || {{}};
           fl.execNote = exRes.error || ("outcome=" + (exRes.outcome || "?"));
           if (fl.execStatus === "executed") {{
             fl.steps.hardware = true;
             fl.steps.uitvoering = true;
           }}
           dialogBody.innerHTML = renderForgeResult();
           if (fl.execStatus === "executed") {{
             flowResult("Uitgevoerd — controleer nu via [Controleren]. Uitvoering alleen is geen verificatie.");
           }} else {{
             flowResult("Eerlijk gestopt: status=" + fl.execStatus + " — geen beweging, geen fake succes. " + (fl.execNote || ""));
           }}
         }} else if (act === "forgeverify") {{
           const fl = forgeFlow || {{}};
           if (!fl.proposalId) throw new Error("niets te controleren");
           flowResult("Onafhankelijke readback loopt (telemetrie-helft)…");
           const v = await postJSON("/api/v1/writes/" + encodeURIComponent(fl.proposalId) + "/verify", {{}});
           const out = v && v.verification && v.verification.outcome;
           if (out === "passed") {{
             fl.steps.verificatie = true;
             fl.verification = "passed (telemetrie-helft; camera-helft vereist een observatie via /observations)";
             dialogBody.innerHTML = renderForgeResult();
             flowResult("Geverifieerd wat verifieerbaar is. Ververs de wereld voor guide/fungi/meldingen.");
           }} else {{
             fl.verification = "niet verified: " + out;
             dialogBody.innerHTML = renderForgeResult();
             flowResult("Verificatie: " + out + " — NIET verified. Geen wereldverandering geclaimd.");
           }}
         }} else if (act === "forgequest") {{
           try {{
             const F = forgeData();
             const qs = F.quests || [];
             if (qs.length && qs[0].quest_id) {{
               const fresh = await postJSON("/api/v1/quests/" + encodeURIComponent(qs[0].quest_id), null, "GET");
               if (fresh && fresh.quest_id) {{
                 const idx = (forgeData().quests || []).findIndex((q) => q.quest_id === fresh.quest_id);
                 if (idx >= 0) forgeData().quests[idx] = fresh;
               }}
             }}
           }} catch (eQ) {{
             flowResult("Quest-verversing geweigerd: " + ((eQ && eQ.message) || ""));
             dialogBody.innerHTML = renderForgeQuest();
             return;
           }}
           dialogBody.innerHTML = renderForgeQuest();
        }} else if (act === "topropose") {{
          dialogBody.innerHTML = renderPrintPropose();
        }} else if (act === "propose") {{
          const pid = ((document.getElementById("pp-printer") || {{}}).value) || "";
          const gcode = ((document.getElementById("pp-gcode") || {{}}).value) || "";
          const sha = ((document.getElementById("pp-sha") || {{}}).value) || "";
          const prof = ((document.getElementById("pp-profile") || {{}}).value) || "";
          const res = await postJSON("/api/v1/prints/propose", {{printer_id: pid, gcode_ref: gcode, gcode_sha256: sha, profile: prof, actor: "game-jelles"}});
          flowResult("Voorstel " + ((res && res.proposal_id) || (res && res.proposal && res.proposal.proposal_id) || "?") + " opgeslagen (inert). Exacte YES via /writes. Ververs voor nieuwe data.");
        }}
      }} catch (err) {{
        flowResult("Geweigerd: " + ((err && err.message) ? err.message : String(err)));
      }}
    }});
    window.addEventListener("keydown", (e) => {{
      const k = e.key;
      if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " "].includes(k)) e.preventDefault();
      keys[k.toLowerCase()] = true;
      if (k === "Escape") {{
        if (notifsOpen) closeNotifs();
        else if (dialogOpen) closeDialog();
        return;
      }}
       if ((k === "e" || k === "E") && !dialogOpen && !notifsOpen) {{
         const target = nearestTarget();
         if (target && target.rep) openWorldObj(target.rep);
         else if (target && target.npc) openDialog(target.npc, "talk");
         else if (nearVerdant()) openVerdant();
         else if (nearDiscovery()) openDiscovery();
       }} else if ((k === "n" || k === "N") && !dialogOpen) {{
        if (notifsOpen) closeNotifs();
        else openNotifs();
      }}
    }});
    window.addEventListener("keyup", (e) => {{ keys[e.key.toLowerCase()] = false; }});
    let last = 0, fps = 0, frames = 0, fpsAt = 0;
    function step(t) {{
      window.requestAnimationFrame(step);
      const dt = Math.min(0.05, (t - last) / 1000 || 0.016);
      last = t;
      frames++; fpsAt += dt;
      if (fpsAt >= 0.5) {{ fps = Math.round(frames / fpsAt); frames = 0; fpsAt = 0; }}
      if (!dialogOpen && !notifsOpen) {{
        let dx = 0, dy = 0;
        if (keys["a"] || keys["arrowleft"]) dx -= 1;
        if (keys["d"] || keys["arrowright"]) dx += 1;
        if (keys["w"] || keys["arrowup"]) dy -= 1;
        if (keys["s"] || keys["arrowdown"]) dy += 1;
        if (dx && dy) {{ dx *= 0.7071; dy *= 0.7071; }}
        const nx = player.x + dx * player.speed * dt;
        if (!collide(nx, player.y, player.r)) player.x = nx;
        const ny = player.y + dy * player.speed * dt;
        if (!collide(player.x, ny, player.r)) player.y = ny;
        player.x = Math.max(40 + player.r, Math.min(WORLD_W - 40 - player.r, player.x));
        player.y = Math.max(40 + player.r, Math.min(WORLD_H - 40 - player.r, player.y));
        if (dx || dy) player.bob += dt * 10;
      }}
      cam.x = Math.max(0, Math.min(WORLD_W - VIEW_W, player.x - VIEW_W / 2));
      cam.y = Math.max(0, Math.min(WORLD_H - VIEW_H, player.y - VIEW_H / 2));
       draw();
       const target = (!dialogOpen && !notifsOpen) ? nearestTarget() : null;
       const atRuin = (!dialogOpen && !notifsOpen) && nearDiscovery();
       const atVerdant = (!dialogOpen && !notifsOpen) && nearVerdant();
       const verdantState = (verdantData() || {{}}).state || "DORMANT";
       if (target && target.rep) {{
         prompt.textContent = "[E] Bekijk " + (target.rep.label || target.rep.source_id || "object");
       }} else if (target && target.npc) {{
         prompt.textContent = "[E] Praat met " + target.npc.name;
       }} else if (atVerdant) {{
         prompt.textContent = verdantState === "AWAKENED" ? "[E] Betreed Verdant (🌱)" : "[E] Bekijk Verdant (dormant)";
       }} else if (atRuin) {{
         prompt.textContent = discoveryCount() ? "[E] Onderzoek de ruïne (?)" : "[E] Bekijk de ruïne";
       }} else {{
         prompt.textContent = "";
       }}
      hud.textContent = "fps " + fps + " · x " + Math.round(player.x) + " y " + Math.round(player.y) + " · " + zoneAt();
    }}
    function draw() {{
      const g = ctx.createLinearGradient(0, 0, 0, VIEW_H);
      g.addColorStop(0, "#0d1420"); g.addColorStop(0.45, "#101410"); g.addColorStop(1, "#0b0f0b");
      ctx.fillStyle = g; ctx.fillRect(0, 0, VIEW_W, VIEW_H);
      ctx.fillStyle = "rgba(201,214,107,0.5)";
      for (let i = 0; i < 40; i++) {{
        const sx = ((i * 173) % WORLD_W - cam.x * 0.2 + WORLD_W) % WORLD_W;
        const sy = (i * 97) % 220;
        if (sx < VIEW_W) ctx.fillRect(sx, sy * 0.4, 2, 2);
      }}
      ctx.fillStyle = "#14201a";
      for (let i = 0; i < 12; i++) {{
        const tx = ((i * 271 + 120) % WORLD_W - cam.x * 0.5 + WORLD_W) % WORLD_W;
        if (tx < -60 || tx > VIEW_W + 60) continue;
        const th = 120 + (i * 37) % 90;
        ctx.beginPath();
        ctx.moveTo(tx, 300 - cam.y * 0.15); ctx.lineTo(tx + 26, 300 - cam.y * 0.15 - th); ctx.lineTo(tx + 52, 300 - cam.y * 0.15);
        ctx.closePath(); ctx.fill();
      }}
      const ox = -cam.x, oy = -cam.y;
      ctx.fillStyle = "#161c16";
      ctx.fillRect(40 + ox, 40 + oy, WORLD_W - 80, WORLD_H - 80);
      ctx.strokeStyle = "#2e3a2c"; ctx.lineWidth = 2;
      for (let gx = 40; gx <= WORLD_W - 40; gx += 80) {{
        ctx.beginPath(); ctx.moveTo(gx + ox, 40 + oy); ctx.lineTo(gx + ox, WORLD_H - 40 + oy); ctx.stroke();
      }}
      for (let gy = 40; gy <= WORLD_H - 40; gy += 80) {{
        ctx.beginPath(); ctx.moveTo(40 + ox, gy + oy); ctx.lineTo(WORLD_W - 40 + ox, gy + oy); ctx.stroke();
      }}
      for (const d of DECOR) {{
        if (d.label === "kleed") {{
          ctx.fillStyle = "#1e2a24";
          ctx.fillRect(d.x + ox, d.y + oy, d.w, d.h);
        }} else if (d.label === "lamp") {{
          const lx = d.x + d.w / 2 + ox, ly = d.y + d.h / 2 + oy;
          const lg = ctx.createRadialGradient(lx, ly, 4, lx, ly, 130);
          lg.addColorStop(0, "rgba(217,164,65,0.35)"); lg.addColorStop(1, "rgba(217,164,65,0)");
          ctx.fillStyle = lg; ctx.fillRect(lx - 130, ly - 130, 260, 260);
          ctx.fillStyle = "#d9a441"; ctx.fillRect(lx - 5, ly - 5, 10, 10);
        }}
      }}
      ctx.fillStyle = "#3a2f22";
      for (const rc of WALLS) ctx.fillRect(rc.x + ox, rc.y + oy, rc.w, rc.h);
      ctx.fillStyle = "#1e2a24";
      ctx.fillRect(DOOR.x + ox, DOOR.y + oy, DOOR.w, DOOR.h);
      ctx.fillStyle = "#6b5844";
      ctx.fillRect(DOOR.x + ox - 8, DOOR.y + oy - 10, 10, DOOR.h + 20);
      ctx.fillRect(DOOR.x + DOOR.w + ox - 2, DOOR.y + oy - 10, 10, DOOR.h + 20);
      ctx.fillStyle = "#8a9184"; ctx.font = "12px sans-serif";
      ctx.fillText("bosrand ↓", DOOR.x + ox + 32, DOOR.y + oy + 25);
      for (const rc of SOLIDS) {{
        ctx.fillStyle = rc.label === "plant" ? "#2c4a2e" : "#4a3d2c";
        ctx.fillRect(rc.x + ox, rc.y + oy, rc.w, rc.h);
        ctx.strokeStyle = "#6b5844"; ctx.strokeRect(rc.x + ox, rc.y + oy, rc.w, rc.h);
        if (rc.label === "plant") {{
          ctx.fillStyle = "#7d9b6a";
          ctx.beginPath(); ctx.arc(rc.x + rc.w / 2 + ox, rc.y + 30 + oy, 22, 0, 7); ctx.fill();
        }}
        if (rc.label === "werkbank") {{
          ctx.fillStyle = "#8a9184"; ctx.font = "12px sans-serif";
          ctx.fillText("werkbank", rc.x + ox + 12, rc.y + oy + 24);
        }}
        if (rc.label === "boom" || rc.label === "ruine") {{
          ctx.fillStyle = rc.label === "boom" ? "#2c4a2e" : "#3d3a35";
          ctx.beginPath(); ctx.arc(rc.x + rc.w / 2 + ox, rc.y + 34 + oy, 30, 0, 7); ctx.fill();
          ctx.fillStyle = "#7d9b6a";
          ctx.beginPath(); ctx.arc(rc.x + rc.w / 2 - 12 + ox, rc.y + 22 + oy, 12, 0, 7); ctx.fill();
        }}
      }}
      const nowS = Date.now() / 1000;
      ctx.fillStyle = "rgba(150,200,160,0.8)";
      for (let i = 0; i < 14; i++) {{
        const fx = ((i * 211 + 300) % (WORLD_W - 80) + 40 - cam.x + 2 * WORLD_W) % WORLD_W;
        const fy = DIV_Y + 60 + ((i * 137) % (WORLD_H - DIV_Y - 140));
        if (fx < -10 || fx > VIEW_W + 10) continue;
        const tw = 0.5 + 0.5 * Math.sin(nowS * 2 + i * 1.7);
        ctx.fillRect(fx, fy + Math.sin(nowS + i) * 6, 2 + tw, 2 + tw);
      }}
       ctx.font = "12px sans-serif";
       ctx.fillStyle = "#8a9184";
       ctx.fillText("Homebase — Werkplaats", 60 + ox, 66 + oy);
       ctx.fillText("Workshop-plank (echte records)", 80 + ox, 80 + oy);
       ctx.fillText("Bosrand (wilderness)", 60 + ox, DIV_Y + 80 + oy);
       for (const s of SLOTS) {{
         ctx.strokeStyle = "rgba(138,145,132,0.7)";
         ctx.setLineDash([6, 5]);
         ctx.strokeRect(s.x + ox, s.y + oy, s.w, s.h);
         ctx.setLineDash([]);
         ctx.fillStyle = "#8a9184";
         ctx.fillText(s.label, s.x + ox + 10, s.y + oy + 22);
       }}
       const REP_STROKE = {{REAL: "#6b5844", OBSERVED: "#7d9b6a", VERIFIED: "#d9a441", PROPOSED: "#8a9184", UNAVAILABLE: "#5a5a5a", FUTURE: "#5a5a5a"}};
       for (const rep of worldReps()) {{
         const rx = rep.x + ox, ry = rep.y + oy;
         const selected = worldObj && worldObj.id === rep.id;
         ctx.fillStyle = "#1e2a24";
         ctx.fillRect(rx - 32, ry - 20, 64, 40);
         ctx.strokeStyle = selected ? "#ece7d8" : (REP_STROKE[rep.status] || "#6b5844");
         ctx.lineWidth = selected ? 3 : 2;
         ctx.strokeRect(rx - 32, ry - 20, 64, 40);
         ctx.lineWidth = 2;
         ctx.fillStyle = "#ece7d8"; ctx.font = "16px sans-serif";
         ctx.fillText(rep.glyph || "•", rx - 9, ry + 5);
         ctx.font = "10px sans-serif";
         ctx.fillText(String(rep.label || "").slice(0, 12), rx - 30, ry + 32);
         if (Math.hypot(player.x - rep.x, player.y - rep.y) < 70) {{
           ctx.fillStyle = "#ece7d8"; ctx.font = "12px sans-serif";
           ctx.fillText("[E]", rx - 8, ry + 48);
         }}
       }}
       ctx.font = "12px sans-serif";
       ctx.fillStyle = "#8a9184";
       ctx.fillText("Ruïne — ontdekking", 700 + ox - 20, 1180 + oy - 12);
       const verd = verdantData();
       if (verd.state === "AWAKENED") {{
         ctx.fillStyle = "rgba(44,74,46,0.85)";
         ctx.fillRect(300 + ox, 1150 + oy, 150, 90);
         ctx.strokeStyle = "#7d9b6a";
         ctx.strokeRect(300 + ox, 1150 + oy, 150, 90);
         ctx.fillStyle = "#a5c48a";
         ctx.fillText("Verdant 🌱 ontwaakt", 300 + ox + 8, 1150 + oy + 22);
         ctx.fillStyle = "#d9a441"; ctx.font = "bold 20px sans-serif";
         ctx.fillText("?", 375 + ox - 6, 1150 + oy - 12);
         ctx.font = "12px sans-serif";
       }} else {{
         ctx.fillStyle = "#5a5a5a";
         ctx.fillText("Verdant — dormant", 300 + ox + 8, 1150 + oy + 102);
       }}
       if (discoveryCount() > 0) {{
         ctx.fillStyle = "#d9a441"; ctx.font = "bold 20px sans-serif";
         ctx.fillText("?", 760 + ox - 6, 1180 + oy - 26);
         ctx.font = "12px sans-serif";
       }}
       for (const npc of NPCS) {{
         const nx = npc.x + ox, ny = npc.y + oy;
         const ng = ctx.createRadialGradient(nx, ny, 4, nx, ny, 70);
         ng.addColorStop(0, "rgba(201,214,107,0.30)"); ng.addColorStop(1, "rgba(201,214,107,0)");
         ctx.fillStyle = ng; ctx.fillRect(nx - 70, ny - 70, 140, 140);
         ctx.strokeStyle = "rgba(201,214,107,0.5)";
         ctx.beginPath(); ctx.arc(nx, ny, npc.radius, 0, 7); ctx.stroke();
         ctx.fillStyle = npc.color;
         ctx.beginPath(); ctx.arc(nx, ny, npc.r, 0, 7); ctx.fill();
         ctx.fillStyle = "#101410"; ctx.font = "bold 20px sans-serif";
         ctx.fillText(npc.glyph || "🎥", nx - 10, ny + 7);
         ctx.fillStyle = "#ece7d8"; ctx.font = "bold 13px sans-serif";
         ctx.fillText(npc.name || npc.id, nx - 16, ny - 28);
        const badge = (npcData(npc.id).badge) || "";
        if (badge) {{
          ctx.fillStyle = "#d9a441"; ctx.font = "bold 16px sans-serif";
          ctx.fillText(badge, nx - 5, ny - 46);
        }}
        if (Math.hypot(player.x - npc.x, player.y - npc.y) < npc.radius) {{
          ctx.fillStyle = "#ece7d8"; ctx.font = "12px sans-serif";
          ctx.fillText("[E]", nx - 8, ny + 34);
        }}
      }}
      const bobY = Math.sin(player.bob) * 2;
      const px = player.x + ox, py = player.y + oy + bobY;
      const pg = ctx.createRadialGradient(px, py, 4, px, py, 60);
      pg.addColorStop(0, "rgba(165,196,138,0.30)"); pg.addColorStop(1, "rgba(165,196,138,0)");
      ctx.fillStyle = pg; ctx.fillRect(px - 60, py - 60, 120, 120);
      ctx.fillStyle = "#a5c48a";
      ctx.beginPath(); ctx.arc(px, py, player.r, 0, 7); ctx.fill();
      ctx.fillStyle = "#101410";
      ctx.beginPath(); ctx.arc(px - 5, py - 3, 2.5, 0, 7); ctx.arc(px + 5, py - 3, 2.5, 0, 7); ctx.fill();
    }}
    stage.tabIndex = 0;
    window.requestAnimationFrame(step);
    </script>"""
    return _ui.shell("Play", "/play", main, "", _ui.living_bg())


# =============================================================================
# BIG #45 — LIVING ECOSYSTEM CONNECTIONS. Read-only aggregation
# over existing relationship systems. No parallel graph, no
# invented relations, no silent merges. All routes GET-only:
# the world layer has zero execution authority.
# =============================================================================


@app.get("/api/v1/connections")
async def api_connections(entity_id: str,
                          depth: int = 1) -> dict:
    """Unified connections for one entity: symbiosis edges +
    proposals + finance/energy/hardware/quest/campaign/
    research/node links. Read-only."""
    from .connections import entity_connections
    try:
        return await entity_connections(entity_id, depth)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/connections/network")
async def api_connection_network(projects: str = "",
                                 limit: int = 8) -> dict:
    """Cross-project network over shared real records.
    `projects` is a comma-separated list (max 6), each a
    known entity id or registered node name."""
    from .connections import project_network
    try:
        count = max(1, min(int(limit or 8), 12))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422,
                            detail="limit must be an integer")
    try:
        return await project_network(
            [part for part in
             str(projects or "").split(",") if part.strip()],
            limit_per_project=count)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/connections/detail")
async def api_connection_detail(a: str, b: str) -> dict:
    """One relationship in Guide vocabulary: WHAT / WHY /
    SOURCE / STATUS / EVIDENCE / NEXT. Fabricates nothing."""
    from .connections import connection_detail
    try:
        return await connection_detail(a, b)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/connections/campaign/{campaign_id}")
def api_campaign_ecosystem(campaign_id: str) -> dict:
    """A campaign's ecosystem context: quest chain + grouped
    real records. Only what the chain names."""
    from .connections import campaign_ecosystem
    try:
        return campaign_ecosystem(campaign_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/connections/possible")
async def api_possible_connections(entity_id: str = "",
                                   limit: int = 8) -> dict:
    """Possible connections (discovery, not relationship):
    proposals, craft gaps, unlinked quest steps — each with
    its gate href."""
    from .connections import possible_connections
    try:
        count = max(1, min(int(limit or 8), 16))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422,
                            detail="limit must be an integer")
    cleaned = str(entity_id or "").strip()[:100]
    if cleaned:
        from .connections import _check_entity
        try:
            _check_entity(cleaned)
        except ValueError as exc:
            raise HTTPException(status_code=422,
                                detail=str(exc))
    return {"entity_id": cleaned,
            "possible": await possible_connections(
                cleaned, limit=count)}


def _connection_row_html(entry: dict) -> str:
    """One connection row: groups, predicate, state, origin,
    evidence + detail link. Escaped at the boundary."""
    from . import ui as _ui
    state = str(entry.get("state", ""))
    strength = ("established" if state == "VERIFIED" else
                "growing" if state == "SUPPORTED" else
                "seedling" if state in ("PROPOSED",
                                        "POSSIBLE") else "")
    bar = (f"<span class=\"strength {strength}\"></span> "
           if strength else "")
    detail_href = (
        f"/connections?a={_ui.esc(entry.get('source_id', ''))}"
        f"&b={_ui.esc(entry.get('target_id', ''))}")
    return (
        f"<li>{bar}<b>"
        f"{_ui.esc(entry.get('source_kind', ''))} → "
        f"{_ui.esc(entry.get('target_kind', ''))}</b> "
        f"<span class=\"muted\">"
        f"{_ui.esc(entry.get('predicate', ''))} · "
        f"{_ui.esc(state)} · "
        f"{_ui.esc(entry.get('origin', ''))}</span><br>"
        f"<small>{_ui.esc(entry.get('detail', ''))}</small> "
        f"<a href=\"{detail_href}\">Why? →</a> "
        f"<a href=\"{_ui.esc(entry.get('href', '/world'))}\">"
        f"Open →</a></li>")


async def _world_connections_html(entity_id: str) -> str:
    """Ecosystem connections panel (BIG #45): focused entity
    gets grouped connections; otherwise cross-project
    clusters with expand/collapse + shared-record links.
    Best-effort, empty means absent."""
    from . import ui as _ui
    cleaned = str(entity_id or "").strip()[:100]
    if cleaned:
        try:
            from .connections import entity_connections
            result = await entity_connections(cleaned, depth=1)
        except ValueError:
            return ("<div class=\"panel\"><p>Unknown entity — "
                    "use a prefix_id like proj_….</p></div>")
        except Exception:
            return ""
        entries = result.get("connections", [])
        if not entries:
            return ""
        groups: dict = {}
        for entry in entries:
            key = (f"{entry.get('source_kind', '')} → "
                   f"{entry.get('target_kind', '')}")
            groups.setdefault(key, []).append(entry)
        parts = []
        for key in sorted(groups):
            rows = "".join(
                _connection_row_html(entry)
                for entry in groups[key][:10])
            parts.append(
                f"<details class=\"conn-cluster\"><summary>"
                f"<b>{_ui.esc(key)}</b> "
                f"({len(groups[key])})</summary>"
                f"<ul>{rows}</ul></details>")
        counts = result.get("counts", {})
        return (
            f"<div class=\"panel\"><h2>Ecosystem connections"
            f"</h2><p class=\"muted\">"
            f"{counts.get('verified', 0)} established · "
            f"{counts.get('supported', 0)} growing · "
            f"{counts.get('proposed', 0)} seedlings · "
            f"DISCOVERY ≠ RELATIONSHIP.</p>"
            + "".join(parts) + "</div>")
    try:
        from .connections import project_network, project_refs
        refs = project_refs(limit=4)
    except Exception:
        return ""
    if len(refs) < 1:
        return ""
    try:
        network = await project_network(refs, limit_per_project=8)
    except Exception:
        return ""
    clusters = []
    for cluster in network.get("clusters", []):
        rows = "".join(
            f"<li><span class=\"strength "
            f"{'established' if child.get('state') == 'VERIFIED' else 'growing' if child.get('state') in ('SUPPORTED', 'LINKED', 'WORKING', 'AVAILABLE') else 'seedling'}\"></span> "
            f"<b>{_ui.esc(child.get('group', ''))}</b> "
            f"<a href=\"{_ui.esc(child.get('href', '/world'))}\">"
            f"{_ui.esc(child.get('entity_id', '')[:60])}</a> "
            f"<span class=\"muted\">"
            f"{_ui.esc(child.get('predicate', ''))} · "
            f"{_ui.esc(child.get('state', ''))}</span></li>"
            for child in cluster.get("children", [])[:8])
        clusters.append(
            f"<details class=\"conn-cluster\" open><summary>"
            f"<b>🌿 {_ui.esc(cluster.get('project', ''))}</b> "
            f"({len(cluster.get('children', []))} links)"
            f"</summary>"
            f"<ul>{rows or '<li class=\"muted\">No recorded links yet.</li>'}</ul>"
            f"<p><a href=\"/world?entity_id="
            f"{_ui.esc(cluster.get('project', ''))}\">Focus →</a></p>"
            f"</details>")
    cross = "".join(
        f"<li><a href=\"{_ui.esc(link.get('href', '/world'))}\">"
        f"{_ui.esc(link.get('record', '')[:60])}</a> "
        f"<span class=\"muted\">shared by "
        f"{_ui.esc(', '.join(link.get('projects', []))[:80])}"
        f"</span></li>"
        for link in network.get("cross_links", [])[:8])
    return (
        f"<div class=\"panel\"><h2>Ecosystem connections</h2>"
        f"<p class=\"muted\">Project clusters from store "
        f"links; cross-links only where projects share the "
        f"same record.</p>" + "".join(clusters) +
        (f"<h3>Shared records</h3><ul>{cross}</ul>"
         if cross else "") + "</div>")


@app.get("/connections", response_class=HTMLResponse)
async def connection_page(a: str = "", b: str = "") -> str:
    """One relationship explained: WHAT / WHY / SOURCE /
    STATUS / EVIDENCE / NEXT in Guide vocabulary."""
    from . import ui as _ui
    from .connections import connection_detail
    try:
        detail = await connection_detail(a, b)
    except ValueError as exc:
        main = (f"<h1>Connection 🔗</h1>"
                f"<p>{_ui.esc(str(exc))}</p>"
                f"<p><a href=\"/world\">Back to world</a></p>")
        return _ui.shell("Connection", "/connections", main,
                         "", _ui.living_bg())
    main = (
        f"<h1>Connection 🔗</h1>"
        f"<div class=\"panel\"><h2>"
        f"{_ui.esc(detail['what'][:140])}</h2>"
        f"<p><b>WHY:</b> {_ui.esc(detail['why'])}</p>"
        f"<p><b>SOURCE:</b> {_ui.esc(detail['source'])} · "
        f"<b>STATUS:</b> {_ui.esc(detail['status'])}</p>"
        f"<p><b>EVIDENCE:</b> "
        f"{_ui.esc(detail.get('evidence', '') or '—')}</p>"
        f"<p><b>NEXT:</b> <a href=\""
        f"{_ui.esc(detail['next']['href'])}\">"
        f"{_ui.esc(detail['next']['label'])} →</a> · "
        f"<a href=\"{_ui.esc(detail.get('href', '/world'))}\">"
        f"Open record →</a></p></div>"
        f"<p><a href=\"/world\">World</a> · "
        f"<a href=\"/symbiosis\">Symbiosis</a> · "
        f"<a href=\"/guide\">Guide</a></p>")
    return _ui.shell("Connection", "/connections", main, "",
                     _ui.living_bg())
