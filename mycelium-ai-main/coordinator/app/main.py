import hashlib
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import FastAPI, HTTPException, Request, Response
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
from .computer_actions import capability_for, new_action
from .conversations import (
    generate_conversation_id,
    new_message,
)
from .database import chat_connection, connection, dump, init_chat_database, init_database, load
from .mission_executor import ExecutorDeps, ExecutorError, MissionExecutor
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
from .ollama_advisor import (
    OllamaAdvisor,
    OllamaRefusedError,
    OllamaUnavailable,
)
from .schemas import AdviseRequest, AdviseResponse, ChatMissionBody, ChatRequest, ChatResponse, ClaimedTask, DecideApprovalBody, DesktopActionBody, DesktopClaimBody, DesktopDecisionBody, DesktopDispatchBody, DesktopResultBody, Heartbeat, MissionApproveBody, MissionCreateBody, MissionStepBody, NodeRegistration, PlanBody, PlanToProposalBody, SuggestStepsBody, TaskCreate, TaskFromProposalBody, TaskResult

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
    yield


app = FastAPI(title="Mycelium AI Coordinator", version="0.1.0", lifespan=lifespan)


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "healthy", "service": "mycelium-coordinator"}


@app.post("/api/v1/nodes/register", status_code=201)
def register_node(node: NodeRegistration) -> dict[str, str]:
    with connection() as db:
        db.execute("""INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'online')
        ON CONFLICT(node_id) DO UPDATE SET hostname=excluded.hostname, tier=excluded.tier,
        capabilities=excluded.capabilities, cpu_cores=excluded.cpu_cores, memory_mb=excluded.memory_mb,
        energy_source=excluded.energy_source, last_seen=excluded.last_seen, status='online'""",
        (node.node_id, node.hostname, node.tier, dump(node.capabilities), node.cpu_cores,
         node.memory_mb, node.energy_source, now()))
    logger.info("node_registered node_id=%s tier=%s", node.node_id, node.tier)
    return {"node_id": node.node_id, "status": "registered"}


@app.post("/api/v1/nodes/{node_id}/heartbeat", status_code=204)
def heartbeat(node_id: str, heartbeat_data: Heartbeat) -> Response:
    with connection() as db:
        found = db.execute("UPDATE nodes SET last_seen=?, status=? WHERE node_id=?",
                           (now(), "online" if heartbeat_data.available else "busy", node_id)).rowcount
    if not found:
        raise HTTPException(404, "Node is not registered")
    return Response(status_code=204)


@app.get("/api/v1/nodes")
def list_nodes() -> list[dict]:
    with connection() as db:
        rows = db.execute("SELECT * FROM nodes ORDER BY last_seen DESC").fetchall()
    return [{**dict(row), "capabilities": load(row["capabilities"])} for row in rows]


@app.post("/api/v1/tasks", status_code=201)
def create_task(task: TaskCreate) -> dict[str, object]:
    with connection() as db:
        cursor = db.execute("""INSERT INTO tasks (kind,payload,required_capabilities,preferred_tier,priority,status,created_at)
        VALUES (?, ?, ?, ?, ?, 'queued', ?)""",
        (task.kind, dump(task.payload), dump(task.required_capabilities), task.preferred_tier, task.priority, now()))
    logger.info("task_created task_id=%s kind=%s", cursor.lastrowid, task.kind)
    return {"id": cursor.lastrowid, "status": "queued"}


@app.post("/api/v1/tasks/claim/{node_id}", response_model=ClaimedTask | None)
def claim_task(node_id: str) -> ClaimedTask | None:
    return _claim_task(node_id, now())


def _claim_task(node_id: str, now_str: str) -> ClaimedTask | None:
    """Claim one queued task for a live node. Fail-closed on every doubt.

    On success the transition queued -> assigned is atomic and carries an
    assignment timestamp, a lease deadline and an incremented attempt count.
    """
    with connection() as db:
        node = db.execute("SELECT tier, capabilities, status, last_seen FROM nodes WHERE node_id=?", (node_id,)).fetchone()
        if node is None:
            raise HTTPException(404, "Node is not registered")
        if node["status"] != "online" or node_is_stale(node["last_seen"], now_str):
            return None
        capabilities = set(load(node["capabilities"]))
        candidates = db.execute("SELECT * FROM tasks WHERE status='queued' ORDER BY priority DESC, id ASC").fetchall()
        for task in candidates:
            needed = set(load(task["required_capabilities"]))
            tier_ok = task["preferred_tier"] is None or task["preferred_tier"] == node["tier"]
            attempts = task["attempt_count"] if "attempt_count" in task.keys() else 0
            if attempts is None:
                attempts = 0
            if tier_ok and needed.issubset(capabilities) and attempts < MAX_ATTEMPTS:
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
        row = db.execute("SELECT status, assigned_node_id, lease_until FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None or row["status"] != "assigned":
            raise HTTPException(404, "Assigned task not found")
        if completing_node_id is not None and row["assigned_node_id"] != completing_node_id:
            raise HTTPException(404, "Assigned task not found")
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


def expire_leases(now_str: str | None = None) -> dict[str, int]:
    """Recover assigned tasks whose lease expired. Atomic per task.

    Tasks below MAX_ATTEMPTS return to 'queued' with cleared assignment;
    tasks at the limit fail. A task never jumps straight back to assigned.
    Recovery of the same lease cannot happen twice: the second pass finds
    no matching assigned row.
    """
    current = now_str or now()
    summary = {"requeued": 0, "failed": 0}
    with connection() as db:
        rows = db.execute("SELECT id, lease_until, attempt_count FROM tasks WHERE status='assigned'").fetchall()
        for task in rows:
            try:
                expired = task["lease_until"] is None or _parse_time(task["lease_until"]) <= _parse_time(current)
            except (ValueError, TypeError):
                expired = True
            if not expired:
                continue
            attempts = task["attempt_count"] if task["attempt_count"] is not None else 0
            if attempts < MAX_ATTEMPTS:
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


@app.get("/api/v1/tasks")
def list_tasks() -> list[dict]:
    with connection() as db:
        rows = db.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 100").fetchall()
    return [{**dict(row), "payload": load(row["payload"]), "required_capabilities": load(row["required_capabilities"]),
             "result": load(row["result"]) if row["result"] else None} for row in rows]


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
    try:
        if body.q is None:
            found = await _world_reader().browse(body.type)
        else:
            found = await _world_reader().search(body.q, body.type)
    except InventoryRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except InventoryUnavailable:
        raise HTTPException(status_code=502, detail="INVENTory unavailable")
    records = [
        {
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "title": item.title,
            "snippet": item.snippet,
            "provenance": item.provenance.model_dump(mode="json"),
        }
        for item in found.results
    ]
    try:
        answered = await _advisor().advise(body.question, records)
    except OllamaRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except OllamaUnavailable as error:
        logger.warning("ollama_unavailable q=%r records=%d cause=%s",
                       body.q, len(records), error)
        raise HTTPException(status_code=502, detail="Ollama unavailable")
    proposal = _extract_advise_proposal(answered.advice, body)
    return AdviseResponse(**answered.model_dump(), proposal=proposal)


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


async def _chat_world_context(message: str) -> tuple[list[dict], str | None]:
    """Read-only INVENTory context for one chat message.

    Returns (records, inventory_error). Refused queries become a caller
    error; an unreachable INVENTory yields empty context with a note.
    """
    query = message.strip()[:200]
    try:
        if query:
            found = await _world_reader().search(query)
        else:
            found = await _world_reader().browse(None)
    except InventoryRefusedError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except InventoryUnavailable:
        return [], "INVENTory unavailable"
    records = [
        {
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "title": item.title,
            "snippet": item.snippet,
            "provenance": item.provenance.model_dump(mode="json"),
        }
        for item in found.results[:10]
    ]
    return records, None


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
    conversation_id = body.conversation_id or generate_conversation_id()
    created = now()
    user_message = new_message(conversation_id, "user", body.message)
    _chat_ensure_conversation(
        conversation_id, body.message.strip()[:120],
        body.project_ref, created)
    _chat_store_message(
        user_message.message_id, conversation_id, "user",
        user_message.content, created,
        dump(user_message.provenance.model_dump(mode="json")), "[]")
    records, inventory_error = await _chat_world_context(body.message)
    sources = [
        {"entity_id": record["entity_id"],
         "source_type": record["provenance"].get("source_type", "unknown"),
         "human_verified": bool(record["provenance"].get(
             "human_verified", False))}
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
    return ChatResponse(
        conversation_id=conversation_id,
        message_id=assistant_message.message_id,
        reply=reply_text,
        model=model_name,
        records_used=len(sources),
        sources=sources,
        proposal=proposal,
        provider_error=provider_error,
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
            "SELECT capabilities, status, last_seen FROM nodes WHERE node_id=?",
            (body.node_id,)).fetchone()
    if node is None:
        raise HTTPException(404, "Node is not registered")
    if node["status"] != "online" or node_is_stale(node["last_seen"],
                                                   moment):
        return None
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
            "SELECT * FROM nodes ORDER BY last_seen DESC").fetchall()
    desktops = [dict(row) for row in nodes
                if any("desktop" in str(cap).lower()
                       for cap in load(row["capabilities"]))]
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
             "status": node["status"], "last_seen": node["last_seen"],
             "capabilities": load(node["capabilities"])}
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
        records, _ = await _chat_world_context(query)
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

    def _post_message(conversation_id: str, role: str, content: str,
                      sources: list) -> str:
        message = new_message(conversation_id, role, content,
                              sources=[dict(entry) for entry in sources])
        _chat_store_message(
            message.message_id, conversation_id, role, message.content,
            now(), dump(message.provenance.model_dump(mode="json")),
            dump(sources))
        return message.message_id

    return MissionExecutor(ExecutorDeps(
        propose_desktop=_propose_desktop,
        load_desktop=_load_desktop,
        post_message=_post_message,
        advise=_advise,
        inventory_search=_inventory_search,
        git_read=_git_read,
        project_read=_project_read,
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
    records, _ = await _chat_world_context(body.goal)
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
    records, _ = await _chat_world_context(
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


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    with connection() as db:
        nodes = db.execute("SELECT node_id, hostname, tier, status, last_seen FROM nodes ORDER BY last_seen DESC").fetchall()
        tasks = db.execute("SELECT id, kind, status, assigned_node_id FROM tasks ORDER BY id DESC LIMIT 20").fetchall()
    init_chat_database()
    with chat_connection() as chat_db:
        pending = chat_db.execute("SELECT COUNT(*) AS n FROM desktop_actions WHERE status='pending_approval'").fetchone()["n"]
    def rows(items, fields):
        return "".join("<tr>" + "".join(f"<td>{escape(str(item[field] or '—'))}</td>" for field in fields) + "</tr>" for item in items) or "<tr><td colspan='5'>Nog geen gegevens</td></tr>"
    return f"""<!doctype html><html><head><title>Mycelium AI</title><style>
    body{{font:16px system-ui;max-width:960px;margin:3rem auto;padding:0 1rem;color:#17352a;background:#f4f5ed}} h1{{color:#2f6b45}} table{{width:100%;border-collapse:collapse;background:white;margin-bottom:2rem}} td,th{{padding:.7rem;text-align:left;border-bottom:1px solid #dde5dc}} code{{background:#e5eee2;padding:.15rem .3rem}} nav{{margin:1rem 0}} nav a{{margin-right:1rem;color:#2f6b45}} .warn{{background:#fff3cd;padding:.7rem;border:1px solid #e6c200;margin-bottom:1rem}}</style></head>
    <body>{_workspace_nav()}
    <h1>Mycelium AI</h1><p>Lokale coördinator · <code>v0.1.0</code> · redeneren hier, uitvoeren op de desktop-agent, wereldmodel in INVENTory</p>
    {f"<div class='warn'>⏳ <a href='/agents'>{pending} desktop-actie(s) wachten op goedkeuring</a></div>" if pending else ""}
    <h2>Nodes</h2><table><tr><th>ID</th><th>Naam</th><th>Type</th><th>Status</th><th>Laatst gezien</th></tr>{rows(nodes, ['node_id','hostname','tier','status','last_seen'])}</table>
    <h2>Taken</h2><table><tr><th>ID</th><th>Soort</th><th>Status</th><th>Node</th></tr>{rows(tasks, ['id','kind','status','assigned_node_id'])}</table></body></html>"""


async def _form_fields(request: Request) -> dict[str, str]:
    """Parse urlencoded HTML forms with stdlib only (no new dependency)."""
    from urllib.parse import parse_qs
    body = (await request.body()).decode("utf-8", "replace")[:8000]
    return {key: values[0] for key, values in parse_qs(
        body, keep_blank_values=True).items() if values}


def _workspace_nav() -> str:    return ("""<nav><a href="/">Mycelium</a><a href="/chat">Chat</a>"""
            """<a href="/agents">Agents</a><a href="/missions">Plans</a>"""
            """<a href="http://127.0.0.1:8080" target="_blank">INVENTory</a>"""
            """<a href="/api/v1/agent/status">Agent-status (JSON)</a></nav>""")


@app.get("/chat", response_class=HTMLResponse)
def chat_page(id: str | None = None) -> str:
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
        f"<option value='{escape(row['conversation_id'])}'"
        + (" selected" if row["conversation_id"] == active else "")
        + f">{escape(row['title'] or row['conversation_id'])}</option>"
        for row in conversations)
    turns = "".join(
        f"<div class='msg {escape(msg['role'])}'><b>{escape(msg['role'])}</b>"
        f"<p>{escape(msg['content'])}</p></div>"
        for msg in history)
    return f"""<!doctype html><html><head><title>Mycelium Chat</title><style>
    body{{font:16px system-ui;max-width:860px;margin:2rem auto;padding:0 1rem;color:#17352a;background:#f4f5ed}} h1{{color:#2f6b45}} nav a{{margin-right:1rem;color:#2f6b45}}
    .msg{{background:white;border:1px solid #dde5dc;padding:.6rem .9rem;margin-bottom:.6rem;border-radius:6px}} .msg.user{{border-left:4px solid #2f6b45}} .msg.assistant{{border-left:4px solid #6b5ca5}} .msg.agent{{border-left:4px solid #b5892e}} .msg.system{{border-left:4px solid #888}}
    form{{background:white;padding:1rem;border:1px solid #dde5dc;border-radius:6px}} textarea{{width:100%;min-height:4rem}} button{{background:#2f6b45;color:white;border:0;padding:.5rem 1rem;border-radius:4px}}</style></head>
    <body>{_workspace_nav()}<h1>Mycelium Chat</h1>
    <p><label>Gesprek: <select onchange="location='/chat?id='+this.value">{options}</select></label>
    <a href="/chat">+ nieuw gesprek</a></p>
    {f"<p>⏳ <a href='/agents'>{len(waiting)} desktop-actie(s) wachten op goedkeuring</a> — de Desktop Agent voert ze pas uit na jouw YES.</p>" if waiting else ""}
    <form method="post" action="/web/missions">
    <input type="hidden" name="conversation_id" value="{escape(active or '')}">
    <input type="text" name="goal" placeholder="Start missie, bijv. Bekijk mijn project en kijk wat er nog moet gebeuren" style="width:70%">
    <button type="submit">Start missie</button></form>
    {turns or "<p>Nog geen berichten. Stel een vraag — Mycelium gebruikt INVENTory als context en lokaal AI-advies.</p>"}
    <form method="post" action="/web/chat">
    <input type="hidden" name="conversation_id" value="{escape(active or '')}">
    <textarea name="message" placeholder="Bijv. Wat kan ik maken met mijn onderdelen?"></textarea><br><br>
    <button type="submit">Verstuur</button></form></body></html>"""


@app.post("/web/chat")
async def web_chat(request: Request) -> RedirectResponse:
    fields = await _form_fields(request)
    body = ChatRequest(
        conversation_id=fields.get("conversation_id", "").strip() or None,
        message=fields.get("message", "").strip())
    if not body.message:
        return RedirectResponse("/chat", status_code=303)
    answer = await chat(body)
    return RedirectResponse(f"/chat?id={answer.conversation_id}",
                            status_code=303)


@app.get("/agents", response_class=HTMLResponse)
def agents_page() -> str:
    status = agent_status()
    online = "● online" if status["agents_online"] else "○ offline"
    current = status["current_action"]
    if current:
        current_html = (
            f"<p>Huidige actie: <code>{escape(current['action_type'])}</code> "
            f"met {escape(str(current['parameters']))}</p>"
            f"<p>Status: {escape(current['status'])}"
            + (f" · goedgekeurd door {escape(current['decided_by'])}"
               if current["decided_by"] else "")
            + (f" · uitgevoerd door {escape(current['dispatched_by'])}"
               if current["dispatched_by"] else "")
            + "</p>")
    else:
        current_html = "<p>Geen lopende actie.</p>"
    nodes_html = "".join(
        f"<li>{escape(node['node_id'])} ({escape(node['status'])}, "
        f"gezien {escape(str(node['last_seen']))})<br><small>"
        f"{escape(', '.join(node['capabilities']))}</small></li>"
        for node in status["desktop_nodes"]) or "<li>○ geen desktop-agent</li>"
    waiting = sum(1 for entry in status["waiting"]
                  if entry["status"] == "pending_approval")
    done = sum(1 for entry in status["activity"]
               if entry["status"] == "completed")
    icons = {"completed": "✓", "failed": "✗", "blocked": "■",
             "cancelled": "■", "rejected": "■", "approved": "⏳",
             "pending_approval": "⏳", "dispatched": "▶"}
    items = "".join(
        f"<li>{icons.get(entry['status'], '○')} "
        f"<code>{escape(entry['action_type'])}</code> "
        f"{escape(entry['action_id'])} — {escape(entry['status'])}"
        + (f" · decided_by {escape(entry['decided_by'])}"
           if entry["decided_by"] else "")
        + (f" · dispatched_by {escape(entry['dispatched_by'])}"
           if entry["dispatched_by"] else "")
        + (_result_suffix(entry) or "")
        + (f" <form style='display:inline' method='post' action=\"/web/desktop/{escape(entry['action_id'])}/decision\">"
           f"<input type='hidden' name='response' value='YES'>"
           f"<button>Approve</button></form>"
           f" <form style='display:inline' method='post' action=\"/web/desktop/{escape(entry['action_id'])}/decision\">"
           f"<input type='hidden' name='response' value='NO'>"
           f"<button>Reject</button></form>"
           f" <form style='display:inline' method='post' action=\"/web/desktop/{escape(entry['action_id'])}/cancel\">"
           f"<button>Stop</button></form>" if entry["status"] == "pending_approval" else "")
        + "</li>"
        for entry in status["activity"])
    return f"""<!doctype html><html><head><title>Mycelium Agents</title><style>
    body{{font:16px system-ui;max-width:860px;margin:2rem auto;padding:0 1rem;color:#17352a;background:#f4f5ed}} h1{{color:#2f6b45}} nav a{{margin-right:1rem;color:#2f6b45}}
    .panel{{background:white;border:1px solid #dde5dc;padding:1rem;border-radius:6px;margin-bottom:1rem}} button{{background:#2f6b45;color:white;border:0;padding:.3rem .7rem;border-radius:4px;margin:.1rem}} small{{color:#5a6b5f}}</style></head>
    <body>{_workspace_nav()}<h1>Agent-paneel</h1>
    <div class="panel"><p>Desktop Agent: <b>{online}</b> ({status["agents_online"]} desktop-node(s))</p>
    <p><b>AI DENKT</b> · <b>AGENT HANDELT</b> · <b>MENSELIJKE APPROVAL BESLIST</b></p>
    <p>Wachtend op goedkeuring: <b>{waiting}</b> · voltooid: <b>{done}</b> ·
    voortgang via <a href="/chat">Chat</a></p>
    {current_html}</div>
    <h2>Desktop-agents</h2><ul>{nodes_html}</ul>
    <h2>Activiteit</h2><ul>{items or "<li>○ nog geen acties</li>"}</ul></body></html>"""


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
    items = "".join(
        f"<li><a href='/missions/{escape(m['mission_id'])}'>"
        f"{escape(m['goal'])}</a> — {escape(m['status'])} "
        f"({m['current_step']}/{len(m['steps'])})</li>"
        for m in [_mission_to_json(mission)
                  for mission in list_missions()])
    return f"""<!doctype html><html><head><title>Mycelium Plans</title><style>
    body{{font:16px system-ui;max-width:860px;margin:2rem auto;padding:0 1rem;color:#17352a;background:#f4f5ed}} h1{{color:#2f6b45}} nav a{{margin-right:1rem;color:#2f6b45}}
    .panel{{background:white;border:1px solid #dde5dc;padding:1rem;border-radius:6px;margin-bottom:1rem}} button{{background:#2f6b45;color:white;border:0;padding:.4rem .9rem;border-radius:4px}}</style></head>
    <body>{_workspace_nav()}<h1>Missies &amp; plannen</h1>
    <div class="panel"><p>Autonomie bestaat alleen <b>binnen</b> een goedgekeurd plan. Desktop-input blijft per stap approval-gated.</p></div>
    <ul>{items or "<li>○ nog geen missies — start er een vanuit <a href='/chat'>Chat</a></li>"}</ul></body></html>"""


@app.get("/missions/{mission_id}", response_class=HTMLResponse)
def mission_page(mission_id: str) -> str:
    mission = load_mission(mission_id)
    if mission is None:
        return HTMLResponse("Missie niet gevonden", status_code=404)
    done = sum(1 for step in mission.steps
               if step.status in ("completed", "skipped"))
    total = len(mission.steps)
    percent = int(100 * done / total) if total else 0
    bar = "█" * (percent // 10) + "░" * (10 - percent // 10)
    icons = {"completed": "✓", "failed": "✗", "blocked": "■",
             "waiting_approval": "⏳", "dispatched": "▶",
             "pending": "○", "skipped": "–"}
    steps = "".join(
        f"<li>{icons.get(step.status, '?')} <b>{escape(step.kind)}</b> "
        f"{escape(step.description)} — {escape(step.status)}"
        + (f" · obs {escape(step.observation_reference)}"
           if step.observation_reference else "")
        + (f" · actie {escape(step.desktop_action_id)}"
           if step.desktop_action_id else "")
        + (f" · <i>{escape(step.error[:160])}</i>" if step.error else "")
        + "</li>"
        for step in mission.steps)
    events = "".join(
        f"<li><small>{escape(event.created_at)}</small> "
        f"<b>{escape(event.event_type)}</b> {escape(event.message[:200])}</li>"
        for event in list_events(mission_id=mission_id)[-20:])
    buttons = ""
    if mission.status == "pending_approval":
        buttons += (f"<form style='display:inline' method='post' action='/web/missions/{escape(mission_id)}/approve'>"
                    "<button>APPROVE plan</button></form> ")
    if mission.status in ("approved", "running"):
        buttons += (f"<form style='display:inline' method='post' action='/web/missions/{escape(mission_id)}/tick'>"
                    "<button>Volgende stap</button></form> ")
    if mission.status == "running":
        buttons += (f"<form style='display:inline' method='post' action='/web/missions/{escape(mission_id)}/pause'>"
                    "<button>Pauzeer</button></form> ")
    if mission.status == "paused":
        buttons += (f"<form style='display:inline' method='post' action='/web/missions/{escape(mission_id)}/resume'>"
                    "<button>Hervat</button></form> ")
    if mission.status not in ("completed", "failed", "cancelled",
                              "blocked"):
        buttons += (f"<form style='display:inline' method='post' action='/web/missions/{escape(mission_id)}/cancel'>"
                    "<button>STOP</button></form>")
    return f"""<!doctype html><html><head><title>Missie</title><style>
    body{{font:16px system-ui;max-width:860px;margin:2rem auto;padding:0 1rem;color:#17352a;background:#f4f5ed}} h1{{color:#2f6b45}} nav a{{margin-right:1rem;color:#2f6b45}}
    .panel{{background:white;border:1px solid #dde5dc;padding:1rem;border-radius:6px;margin-bottom:1rem}} button{{background:#2f6b45;color:white;border:0;padding:.4rem .9rem;border-radius:4px;margin:.1rem}}</style></head>
    <body>{_workspace_nav()}<h1>MISSION</h1>
    <div class="panel"><p>{escape(mission.goal)}</p>
    <p><code>{bar}</code> {percent}% · status <b>{escape(mission.status)}</b> · stap {mission.current_step}/{total}</p>
    <p>{buttons}</p></div>
    <h2>Stappen</h2><ul>{steps}</ul>
    <h2>Gebeurtenissen</h2><ul>{events or "<li>○</li>"}</ul></body></html>"""


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
    except ExecutorError:
        pass
    return RedirectResponse(f"/missions/{mission_id}", status_code=303)


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
