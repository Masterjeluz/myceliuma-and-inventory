import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse

from .database import connection, dump, init_database, load
from .inventory_read import (
    EntityRecord,
    GraphResponse,
    InventoryReader,
    InventoryRefusedError,
    InventoryUnavailable,
    SearchResponse,
)
from .schemas import ClaimedTask, Heartbeat, NodeRegistration, TaskCreate, TaskResult

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


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    with connection() as db:
        nodes = db.execute("SELECT node_id, hostname, tier, status, last_seen FROM nodes ORDER BY last_seen DESC").fetchall()
        tasks = db.execute("SELECT id, kind, status, assigned_node_id FROM tasks ORDER BY id DESC LIMIT 20").fetchall()
    def rows(items, fields):
        return "".join("<tr>" + "".join(f"<td>{escape(str(item[field] or '—'))}</td>" for field in fields) + "</tr>" for item in items) or "<tr><td colspan='5'>Nog geen gegevens</td></tr>"
    return f"""<!doctype html><html><head><title>Mycelium AI</title><style>
    body{{font:16px system-ui;max-width:960px;margin:3rem auto;padding:0 1rem;color:#17352a;background:#f4f5ed}} h1{{color:#2f6b45}} table{{width:100%;border-collapse:collapse;background:white;margin-bottom:2rem}} td,th{{padding:.7rem;text-align:left;border-bottom:1px solid #dde5dc}} code{{background:#e5eee2;padding:.15rem .3rem}}</style></head>
    <body><h1>Mycelium AI</h1><p>Lokale coördinator · <code>v0.1.0</code></p><h2>Nodes</h2><table><tr><th>ID</th><th>Naam</th><th>Type</th><th>Status</th><th>Laatst gezien</th></tr>{rows(nodes, ['node_id','hostname','tier','status','last_seen'])}</table>
    <h2>Taken</h2><table><tr><th>ID</th><th>Soort</th><th>Status</th><th>Node</th></tr>{rows(tasks, ['id','kind','status','assigned_node_id'])}</table></body></html>"""
