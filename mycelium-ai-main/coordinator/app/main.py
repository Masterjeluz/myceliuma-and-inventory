import hashlib
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

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
    MissionConflictError,
    bindings_for_mission,
    get_binding,
    list_events,
    list_missions,
    load_mission,
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
from .schemas import AdviseRequest, AdviseResponse, AdvancedOpBody, CadDocumentBody, CadOpBody, CadPartBody, CampaignBody, CameraRegisterBody, CaptureCloseBody, CaptureOpenBody, ChatMissionBody, ChatRequest, ChatResponse, ClaimedTask, DecideApprovalBody, DesktopActionBody, DesktopClaimBody, DesktopDecisionBody, DesktopDispatchBody, DesktopResultBody,     DistEnvelopeBody, DroneCreateBody, DroneMissionApproveBody, DroneMissionBody,     FabGenerateBody, FabSliceBody, FamiliarCreateBody, FoodCreateBody, GarminImportBody, GitCommitBody, HealthMeasureBody, Heartbeat, InstagramImportBody,     InterfaceChatBody, IntegrationEnvelopeBody, IntegrationKeyBody, IntegrationTriggerBody, InventoryWriteBody, JobRunBody, LiveContextBody, LiveProposeBody, LiveSessionBody, MealCreateBody, MealItemBody, MemoryConsolidateBody, MemoryCreateBody, MemoryRetrieveBody, MemoryVerifyBody,     MissionApproveBody, MissionCreateBody, MissionRunBody, MissionStepBody, NodeRegistration, NodeRotateBody,     NotifyBody, OperatorBody, OutboxAckBody, OutboxEnqueueBody, PhoneCameraBody,     PlanBody, PlanToProposalBody, PipelinePlanBody, PrintCancelBody, PrintProposeBody, PrinterRegisterBody, PrinterSelectBody, PromptEditBody, ResearchAdvanceBody, ResearchClaimBody, ResearchRecordBody, ResearchSourceBody, RobotActionBody, RobotApproveBody, RobotCreateBody, RobotSafetyBody, RobotTelemetryBody, SessionOpenBody,     StreamStartBody, SuggestStepsBody, SkillAcceptBody, SkillAdvanceBody, SkillCreateBody, SkillDiscoverBody, SkillEvidenceBody, SpoolCreateBody, SyncApplyBody, TaskAssignBody, TaskCreate, TaskFromProposalBody, TaskResult, TaskRouteBody,     TemplateMissionBody, TransformBody, TwinLinkBody, VisionAnalyzeBody, VisionProposeBody, VoiceApprovalRequestBody, VoiceApproveBody, VoiceChatBody,     VoiceSynthesizeBody, VoiceTranscribeBody, WriteDecisionBody, CommandBody, RecoverBody, AgendaImportBody, BootstrapBody, ResearchRunBody, ResearchExecuteBody, PresenceTriageBody, PresenceNotifyBody, MeshDelegateBody, MeshPreviewBody, HardwareLinkBody, CampaignCreateBody, HardwareVerifyBody, HardwareRevokeBody, FinanceRecordBody, FinanceStatusBody, EnergyRecordBody, QuestCreateBody, WorkflowDispatchBody

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
            check_energy_state
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
    except NodeRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    with connection() as db:
        # Build dynamic UPDATE for all provided fields
        set_clauses = ["last_seen=?", "status=?", "last_auth=?"]
        params = [updates["last_seen"], updates["status"], updates["last_auth"]]
        optional_fields = ("capabilities", "models", "executors", "resources",
                           "telemetry", "telemetry_timestamp", "hardware",
                           "compute_capabilities", "energy_state")
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
    "compute_capabilities, energy_state, health"
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
                "telemetry", "hardware", "compute_capabilities", "energy_state"):
        try:
            record[key] = load(record.get(key) or (
                "[]" if key not in ("resources", "telemetry", "energy_state") else "{}"))
        except ValueError:
            record[key] = [] if key not in ("resources", "telemetry", "energy_state") else {}
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
    key; the payload never keeps a shadow copy afterwards."""
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
    payload = dict(task.payload)
    payload.pop("routing", None)
    with connection() as db:
        cursor = db.execute("""INSERT INTO tasks (kind,payload,required_capabilities,preferred_tier,priority,status,created_at,routing)
        VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)""",
        (task.kind, dump(payload), dump(task.required_capabilities), task.preferred_tier, task.priority, now(),
         dump(requirements.model_dump(mode="json"))))
    logger.info("task_created task_id=%s kind=%s", cursor.lastrowid, task.kind)
    emit_event("task.queued", f"Task {cursor.lastrowid} ({task.kind}) queued",
               task_id=str(cursor.lastrowid))
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
                                   required_capabilities=list(needed))
    return None


@app.post("/api/v1/tasks/{task_id}/complete", status_code=204)
def complete_task(task_id: int, result: TaskResult, node_id: str | None = None) -> Response:
    _complete_task(task_id, result, completing_node_id=node_id, now_str=now())
    return Response(status_code=204)


def _complete_task(task_id: int, result: TaskResult, completing_node_id: str | None = None, now_str: str | None = None) -> None:
    """Complete an assigned task within its lease. Fail-closed otherwise.

    Requires status 'assigned', a still-valid lease, and — when the caller
    identifies itself — a matching assigned node. Expired or foreign
    assignments can never complete.
    """
    current = now_str or now()
    with connection() as db:
        row = db.execute("SELECT status, assigned_node_id, lease_until, routing_decision FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None or row["status"] != "assigned":
            raise HTTPException(404, "Assigned task not found")
        if completing_node_id is not None and row["assigned_node_id"] != completing_node_id:
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
        + "</li>"
        for entry in status["activity"])
    main = f"""<h1>Agents</h1>
    <div class="panel"><p>Desktop Agent: <b>{"online" if online else "offline"}</b> ({status["agents_online"]} desktop node(s))</p>
    <p class="muted"><b>AI thinks</b> · <b>agent acts</b> · <b>human approval decides</b></p>
    <p>Waiting approval: <b>{waiting}</b> · completed: <b>{done}</b> · progress via <a href="/chat">Chat</a></p>
    {current_html}</div>
    <h2>Desktop agents</h2><ul>{nodes_html}</ul>
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
    <h2>Steps</h2><ul>{steps}</ul>
    <h2>Events</h2><ul>{events or "<li>—</li>"}</ul>
    <h2>Automation</h2><ul>{_mission_automation_html(mission_id)}</ul>"""
    return _ui.shell("Mission", "/missions", main, "",
                     _ui.command_bar())


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
        f"<span class=\"muted\">models {len(record.get('models', []))} · executors {len(record.get('executors', []))} · last seen {_ui.esc(str(record.get('last_seen', ''))[:16])}</span></div>"
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
    <div class="grove">{cards}</div>"""
    return _ui.shell("Nodes", "/nodes", main, _ui.command_bar())


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
        f"<button type=\"submit\">Decide</button></form></td></tr>"
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
    for url in seed_urls:
        try:
            made = create_task(TaskCreate(
                kind="research.fetch_url",
                payload={"url": url, "run_id": run.run_id,
                         "max_chars": 65536},
                required_capabilities=["research.fetch"]))
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
