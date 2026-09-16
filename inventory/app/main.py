import logging
from contextlib import asynccontextmanager
from html import escape
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from .database import connection, dump, init_database, load, sanitize_fts_query, search_fts, SEARCHABLE_TYPES
from .ids import (
    generate_actuator_id,
    generate_camera_id,
    generate_event_id,
    generate_file_id,
    generate_hardware_id,
    generate_idea_id,
    generate_location_id,
    generate_model_id,
    generate_object_id,
    generate_project_id,
    generate_relationship_id,
    generate_sensor_id,
    generate_task_id,
)
from .schemas import (
    ActuatorCreate,
    ActuatorResponse,
    ActuatorUpdate,
    CameraCreate,
    CameraResponse,
    CameraUpdate,
    EventResponse,
    EventType,
    FileCreate,
    FileResponse,
    FileUpdate,
    HardwareCreate,
    HardwareResponse,
    HardwareUpdate,
    IdeaCreate,
    IdeaResponse,
    IdeaStatus,
    IdeaUpdate,
    LocationCreate,
    LocationResponse,
    LocationUpdate,
    ModelCreate,
    ModelResponse,
    ModelUpdate,
    ObjectCreate,
    ObjectResponse,
    ObjectUpdate,
    ProjectCreate,
    ProjectResponse,
    ProjectStatus,
    ProjectUpdate,
    Provenance,
    RelationshipCreate,
    RelationshipResponse,
    GraphEdge,
    GraphNode,
    GraphResponse,
    SearchResponse,
    SearchResult,
    SensorCreate,
    SensorResponse,
    SensorUpdate,
    SourceType,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
    utc_now,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("inventory.api")

SYSTEM_PROV = Provenance(source_type="user-created", creator_id="system", human_verified=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database()
    logger.info("inventory_started")
    yield


app = FastAPI(title="INVENTory", version="0.2.0", lifespan=lifespan)


# =============================================================================
# HELPERS
# =============================================================================

def _append_event(db, event_type: EventType, entity_id: str, data: dict, prov: Provenance | None = None) -> None:
    evt_id = generate_event_id()
    evt_prov = prov or SYSTEM_PROV
    db.execute(
        "INSERT INTO events (id, event_type, entity_id, timestamp, data, provenance) VALUES (?, ?, ?, ?, ?, ?)",
        (evt_id, event_type, entity_id, utc_now(), dump(data), dump(evt_prov.model_dump())),
    )


def _parse_form(body_bytes: bytes) -> dict:
    return parse_qs(body_bytes.decode("utf-8"), keep_blank_values=True)


def _form_str(form: dict, key: str, default: str = "") -> str:
    return form.get(key, [default])[0].strip()


def _form_int(form: dict, key: str, default: int = 1) -> int:
    try:
        return int(form.get(key, [str(default)])[0])
    except (ValueError, TypeError):
        return default


def _form_source(form: dict) -> SourceType:
    raw = form.get("source_type", ["user-created"])[0]
    valid = ("user-created", "imported", "ai-generated", "sensor-observed", "external-source")
    return raw if raw in valid else "user-created"


def _row_to_object(row) -> ObjectResponse:
    return ObjectResponse(
        id=row["id"], name=row["name"], description=row["description"],
        quantity=row["quantity"], provenance=Provenance(**load(row["provenance"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_project(row) -> ProjectResponse:
    return ProjectResponse(
        id=row["id"], name=row["name"], description=row["description"],
        status=row["status"], provenance=Provenance(**load(row["provenance"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_idea(row) -> IdeaResponse:
    return IdeaResponse(
        id=row["id"], name=row["name"], description=row["description"],
        status=row["status"], provenance=Provenance(**load(row["provenance"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_hardware(row) -> HardwareResponse:
    return HardwareResponse(
        id=row["id"], name=row["name"], manufacturer=row["manufacturer"],
        model=row["model"], category=row["category"], description=row["description"],
        status=row["status"], capabilities=load(row["capabilities"]),
        interfaces=load(row["interfaces"]), metadata=load(row["metadata"]),
        provenance=Provenance(**load(row["provenance"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_sensor(row) -> SensorResponse:
    return SensorResponse(
        id=row["id"], name=row["name"], sensor_type=row["sensor_type"],
        manufacturer=row["manufacturer"], model=row["model"],
        description=row["description"], unit=row["unit"],
        measurement_type=row["measurement_type"], status=row["status"],
        capabilities=load(row["capabilities"]), interfaces=load(row["interfaces"]),
        metadata=load(row["metadata"]),
        provenance=Provenance(**load(row["provenance"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_camera(row) -> CameraResponse:
    return CameraResponse(
        id=row["id"], name=row["name"], camera_type=row["camera_type"],
        manufacturer=row["manufacturer"], model=row["model"],
        description=row["description"], resolution=row["resolution"],
        status=row["status"], capabilities=load(row["capabilities"]),
        interfaces=load(row["interfaces"]), metadata=load(row["metadata"]),
        provenance=Provenance(**load(row["provenance"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_location(row) -> LocationResponse:
    return LocationResponse(
        id=row["id"], name=row["name"], location_type=row["location_type"],
        description=row["description"], status=row["status"],
        metadata=load(row["metadata"]),
        provenance=Provenance(**load(row["provenance"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_model(row) -> ModelResponse:
    return ModelResponse(
        id=row["id"], name=row["name"], provider=row["provider"],
        model_identifier=row["model_identifier"], model_type=row["model_type"],
        description=row["description"], version=row["version"],
        status=row["status"], capabilities=load(row["capabilities"]),
        interfaces=load(row["interfaces"]), metadata=load(row["metadata"]),
        provenance=Provenance(**load(row["provenance"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_task(row) -> TaskResponse:
    return TaskResponse(
        id=row["id"], name=row["name"], task_type=row["task_type"],
        description=row["description"], status=row["status"],
        priority=row["priority"],
        input_requirements=load(row["input_requirements"]),
        expected_output=row["expected_output"],
        parameters=load(row["parameters"]), metadata=load(row["metadata"]),
        provenance=Provenance(**load(row["provenance"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_actuator(row) -> ActuatorResponse:
    return ActuatorResponse(
        id=row["id"], name=row["name"], actuator_type=row["actuator_type"],
        manufacturer=row["manufacturer"], model=row["model"],
        description=row["description"], status=row["status"],
        capabilities=load(row["capabilities"]),
        interfaces=load(row["interfaces"]),
        parameters=load(row["parameters"]), metadata=load(row["metadata"]),
        provenance=Provenance(**load(row["provenance"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_file(row) -> FileResponse:
    return FileResponse(
        id=row["id"], name=row["name"], file_kind=row["file_kind"],
        mime_type=row["mime_type"], sha256=row["sha256"],
        size_bytes=row["size_bytes"], description=row["description"],
        status=row["status"], metadata=load(row["metadata"]),
        provenance=Provenance(**load(row["provenance"])),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_relationship(row) -> RelationshipResponse:
    return RelationshipResponse(
        id=row["id"], from_id=row["from_id"], predicate=row["predicate"],
        to_id=row["to_id"], metadata=load(row["metadata"]),
        provenance=Provenance(**load(row["provenance"])), created_at=row["created_at"],
    )


def _row_to_event(row) -> EventResponse:
    return EventResponse(
        id=row["id"], event_type=row["event_type"], entity_id=row["entity_id"],
        timestamp=row["timestamp"], data=load(row["data"]),
        provenance=Provenance(**load(row["provenance"])),
    )


def _get_relationships_for(entity_id: str) -> list[RelationshipResponse]:
    with connection() as db:
        rows = db.execute(
            "SELECT * FROM relationships WHERE from_id = ? OR to_id = ? ORDER BY created_at DESC",
            (entity_id, entity_id),
        ).fetchall()
    return [_row_to_relationship(r) for r in rows]


def _get_events_for(entity_id: str) -> list[EventResponse]:
    with connection() as db:
        rows = db.execute(
            "SELECT * FROM events WHERE entity_id = ? ORDER BY timestamp DESC",
            (entity_id,),
        ).fetchall()
    return [_row_to_event(r) for r in rows]


# =============================================================================
# REST API — HEALTH
# =============================================================================

@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "healthy", "service": "inventory", "version": "0.2.0"}


# =============================================================================
# REST API — OBJECTS
# =============================================================================

@app.get("/api/v1/objects", response_model=list[ObjectResponse])
def list_objects() -> list[ObjectResponse]:
    with connection() as db:
        rows = db.execute("SELECT * FROM objects ORDER BY created_at DESC").fetchall()
    return [_row_to_object(r) for r in rows]


@app.post("/api/v1/objects", response_model=ObjectResponse, status_code=201)
def create_object(payload: ObjectCreate) -> ObjectResponse:
    obj_id = generate_object_id()
    now_str = utc_now()
    prov = payload.provenance or Provenance(source_type="user-created", creator_id="user", human_verified=True)
    with connection() as db:
        db.execute(
            "INSERT INTO objects (id, name, description, quantity, provenance, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (obj_id, payload.name.strip(), payload.description.strip(), payload.quantity, dump(prov.model_dump()), now_str, now_str),
        )
        _append_event(db, "object_created", obj_id, {"name": payload.name.strip(), "quantity": payload.quantity}, prov)
    logger.info("object_created id=%s name=%s", obj_id, payload.name)
    return ObjectResponse(id=obj_id, name=payload.name.strip(), description=payload.description.strip(),
                          quantity=payload.quantity, provenance=prov, created_at=now_str, updated_at=now_str)


@app.get("/api/v1/objects/{object_id}", response_model=ObjectResponse)
def get_object(object_id: str) -> ObjectResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM objects WHERE id = ?", (object_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Object '{object_id}' not found")
    return _row_to_object(row)


@app.patch("/api/v1/objects/{object_id}", response_model=ObjectResponse)
def update_object(object_id: str, payload: ObjectUpdate) -> ObjectResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM objects WHERE id = ?", (object_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Object '{object_id}' not found")
        new_name = payload.name.strip() if payload.name is not None else row["name"]
        new_desc = payload.description.strip() if payload.description is not None else row["description"]
        new_qty = payload.quantity if payload.quantity is not None else row["quantity"]
        new_prov = payload.provenance or Provenance(**load(row["provenance"]))
        now_str = utc_now()
        db.execute(
            "UPDATE objects SET name=?, description=?, quantity=?, provenance=?, updated_at=? WHERE id=?",
            (new_name, new_desc, new_qty, dump(new_prov.model_dump()), now_str, object_id),
        )
        _append_event(db, "object_updated", object_id, {"name": new_name, "quantity": new_qty}, new_prov)
    logger.info("object_updated id=%s", object_id)
    return ObjectResponse(id=object_id, name=new_name, description=new_desc, quantity=new_qty,
                          provenance=new_prov, created_at=row["created_at"], updated_at=now_str)


@app.delete("/api/v1/objects/{object_id}", status_code=204)
def delete_object(object_id: str) -> Response:
    with connection() as db:
        row = db.execute("SELECT * FROM objects WHERE id = ?", (object_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Object '{object_id}' not found")
        _append_event(db, "object_deleted", object_id, {"name": row["name"]})
        db.execute("DELETE FROM objects WHERE id = ?", (object_id,))
    logger.info("object_deleted id=%s", object_id)
    return Response(status_code=204)


# =============================================================================
# REST API — PROJECTS
# =============================================================================

@app.get("/api/v1/projects", response_model=list[ProjectResponse])
def list_projects() -> list[ProjectResponse]:
    with connection() as db:
        rows = db.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    return [_row_to_project(r) for r in rows]


@app.post("/api/v1/projects", response_model=ProjectResponse, status_code=201)
def create_project(payload: ProjectCreate) -> ProjectResponse:
    proj_id = generate_project_id()
    now_str = utc_now()
    prov = payload.provenance or Provenance(source_type="user-created", creator_id="user", human_verified=True)
    with connection() as db:
        db.execute(
            "INSERT INTO projects (id, name, description, status, provenance, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (proj_id, payload.name.strip(), payload.description.strip(), payload.status, dump(prov.model_dump()), now_str, now_str),
        )
        _append_event(db, "project_created", proj_id, {"name": payload.name.strip(), "status": payload.status}, prov)
    logger.info("project_created id=%s name=%s", proj_id, payload.name)
    return ProjectResponse(id=proj_id, name=payload.name.strip(), description=payload.description.strip(),
                           status=payload.status, provenance=prov, created_at=now_str, updated_at=now_str)


@app.get("/api/v1/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str) -> ProjectResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return _row_to_project(row)


@app.patch("/api/v1/projects/{project_id}", response_model=ProjectResponse)
def update_project(project_id: str, payload: ProjectUpdate) -> ProjectResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        new_name = payload.name.strip() if payload.name is not None else row["name"]
        new_desc = payload.description.strip() if payload.description is not None else row["description"]
        new_status = payload.status if payload.status is not None else row["status"]
        new_prov = payload.provenance or Provenance(**load(row["provenance"]))
        now_str = utc_now()
        db.execute(
            "UPDATE projects SET name=?, description=?, status=?, provenance=?, updated_at=? WHERE id=?",
            (new_name, new_desc, new_status, dump(new_prov.model_dump()), now_str, project_id),
        )
        _append_event(db, "project_updated", project_id, {"name": new_name, "status": new_status}, new_prov)
    return ProjectResponse(id=project_id, name=new_name, description=new_desc, status=new_status,
                           provenance=new_prov, created_at=row["created_at"], updated_at=now_str)


@app.delete("/api/v1/projects/{project_id}", status_code=204)
def delete_project(project_id: str) -> Response:
    with connection() as db:
        row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        _append_event(db, "project_deleted", project_id, {"name": row["name"]})
        db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    logger.info("project_deleted id=%s", project_id)
    return Response(status_code=204)


# =============================================================================
# REST API — IDEAS
# =============================================================================

@app.get("/api/v1/ideas", response_model=list[IdeaResponse])
def list_ideas() -> list[IdeaResponse]:
    with connection() as db:
        rows = db.execute("SELECT * FROM ideas ORDER BY created_at DESC").fetchall()
    return [_row_to_idea(r) for r in rows]


@app.post("/api/v1/ideas", response_model=IdeaResponse, status_code=201)
def create_idea(payload: IdeaCreate) -> IdeaResponse:
    idea_id = generate_idea_id()
    now_str = utc_now()
    prov = payload.provenance or Provenance(source_type="user-created", creator_id="user", human_verified=True)
    with connection() as db:
        db.execute(
            "INSERT INTO ideas (id, name, description, status, provenance, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (idea_id, payload.name.strip(), payload.description.strip(), payload.status, dump(prov.model_dump()), now_str, now_str),
        )
        _append_event(db, "idea_created", idea_id, {"name": payload.name.strip(), "status": payload.status}, prov)
    logger.info("idea_created id=%s name=%s", idea_id, payload.name)
    return IdeaResponse(id=idea_id, name=payload.name.strip(), description=payload.description.strip(),
                        status=payload.status, provenance=prov, created_at=now_str, updated_at=now_str)


@app.get("/api/v1/ideas/{idea_id}", response_model=IdeaResponse)
def get_idea(idea_id: str) -> IdeaResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Idea '{idea_id}' not found")
    return _row_to_idea(row)


@app.patch("/api/v1/ideas/{idea_id}", response_model=IdeaResponse)
def update_idea(idea_id: str, payload: IdeaUpdate) -> IdeaResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Idea '{idea_id}' not found")
        new_name = payload.name.strip() if payload.name is not None else row["name"]
        new_desc = payload.description.strip() if payload.description is not None else row["description"]
        new_status = payload.status if payload.status is not None else row["status"]
        new_prov = payload.provenance or Provenance(**load(row["provenance"]))
        now_str = utc_now()
        db.execute(
            "UPDATE ideas SET name=?, description=?, status=?, provenance=?, updated_at=? WHERE id=?",
            (new_name, new_desc, new_status, dump(new_prov.model_dump()), now_str, idea_id),
        )
        _append_event(db, "idea_updated", idea_id, {"name": new_name, "status": new_status}, new_prov)
    return IdeaResponse(id=idea_id, name=new_name, description=new_desc, status=new_status,
                        provenance=new_prov, created_at=row["created_at"], updated_at=now_str)


@app.delete("/api/v1/ideas/{idea_id}", status_code=204)
def delete_idea(idea_id: str) -> Response:
    with connection() as db:
        row = db.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Idea '{idea_id}' not found")
        _append_event(db, "idea_deleted", idea_id, {"name": row["name"]})
        db.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))
    logger.info("idea_deleted id=%s", idea_id)
    return Response(status_code=204)


# =============================================================================
# REST API — HARDWARE (M3.1)
# =============================================================================

def _clean_str_list(values) -> list[str]:
    cleaned = []
    for value in values or []:
        text = str(value).strip()
        if text and text not in cleaned:
            cleaned.append(text[:120])
    return cleaned


@app.get("/api/v1/hardware", response_model=list[HardwareResponse])
def list_hardware() -> list[HardwareResponse]:
    with connection() as db:
        rows = db.execute("SELECT * FROM hardware ORDER BY created_at DESC").fetchall()
    return [_row_to_hardware(r) for r in rows]


@app.post("/api/v1/hardware", response_model=HardwareResponse, status_code=201)
def create_hardware(payload: HardwareCreate) -> HardwareResponse:
    hw_id = generate_hardware_id()
    now_str = utc_now()
    prov = payload.provenance or Provenance(source_type="user-created", creator_id="user", human_verified=True)
    capabilities = _clean_str_list(payload.capabilities)
    interfaces = _clean_str_list(payload.interfaces)
    with connection() as db:
        db.execute(
            "INSERT INTO hardware (id, name, manufacturer, model, category, description,"
            " status, capabilities, interfaces, metadata, provenance, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (hw_id, payload.name.strip(), payload.manufacturer.strip(), payload.model.strip(),
             payload.category.strip(), payload.description.strip(), payload.status,
             dump(capabilities), dump(interfaces), dump(payload.metadata),
             dump(prov.model_dump()), now_str, now_str),
        )
        _append_event(db, "hardware_created", hw_id,
                      {"name": payload.name.strip(), "category": payload.category.strip()}, prov)
    logger.info("hardware_created id=%s name=%s", hw_id, payload.name)
    return HardwareResponse(id=hw_id, name=payload.name.strip(),
                            manufacturer=payload.manufacturer.strip(),
                            model=payload.model.strip(), category=payload.category.strip(),
                            description=payload.description.strip(), status=payload.status,
                            capabilities=capabilities, interfaces=interfaces,
                            metadata=payload.metadata, provenance=prov,
                            created_at=now_str, updated_at=now_str)


@app.get("/api/v1/hardware/{hardware_id}", response_model=HardwareResponse)
def get_hardware(hardware_id: str) -> HardwareResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM hardware WHERE id = ?", (hardware_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Hardware '{hardware_id}' not found")
    return _row_to_hardware(row)


@app.patch("/api/v1/hardware/{hardware_id}", response_model=HardwareResponse)
def update_hardware(hardware_id: str, payload: HardwareUpdate) -> HardwareResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM hardware WHERE id = ?", (hardware_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Hardware '{hardware_id}' not found")
        new_name = payload.name.strip() if payload.name is not None else row["name"]
        new_manufacturer = payload.manufacturer.strip() if payload.manufacturer is not None else row["manufacturer"]
        new_model = payload.model.strip() if payload.model is not None else row["model"]
        new_category = payload.category.strip() if payload.category is not None else row["category"]
        new_desc = payload.description.strip() if payload.description is not None else row["description"]
        new_status = payload.status if payload.status is not None else row["status"]
        new_capabilities = _clean_str_list(payload.capabilities) if payload.capabilities is not None else load(row["capabilities"])
        new_interfaces = _clean_str_list(payload.interfaces) if payload.interfaces is not None else load(row["interfaces"])
        new_metadata = payload.metadata if payload.metadata is not None else load(row["metadata"])
        new_prov = payload.provenance or Provenance(**load(row["provenance"]))
        now_str = utc_now()
        db.execute(
            "UPDATE hardware SET name=?, manufacturer=?, model=?, category=?, description=?,"
            " status=?, capabilities=?, interfaces=?, metadata=?, provenance=?, updated_at=? WHERE id=?",
            (new_name, new_manufacturer, new_model, new_category, new_desc, new_status,
             dump(new_capabilities), dump(new_interfaces), dump(new_metadata),
             dump(new_prov.model_dump()), now_str, hardware_id),
        )
        _append_event(db, "hardware_updated", hardware_id,
                      {"name": new_name, "category": new_category}, new_prov)
    logger.info("hardware_updated id=%s", hardware_id)
    return HardwareResponse(id=hardware_id, name=new_name, manufacturer=new_manufacturer,
                            model=new_model, category=new_category, description=new_desc,
                            status=new_status, capabilities=new_capabilities,
                            interfaces=new_interfaces, metadata=new_metadata,
                            provenance=new_prov, created_at=row["created_at"], updated_at=now_str)


@app.delete("/api/v1/hardware/{hardware_id}", status_code=204)
def delete_hardware(hardware_id: str) -> Response:
    with connection() as db:
        row = db.execute("SELECT * FROM hardware WHERE id = ?", (hardware_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Hardware '{hardware_id}' not found")
        _append_event(db, "hardware_deleted", hardware_id, {"name": row["name"]})
        db.execute("DELETE FROM hardware WHERE id = ?", (hardware_id,))
    logger.info("hardware_deleted id=%s", hardware_id)
    return Response(status_code=204)


# =============================================================================
# REST API — SENSORS (M3.2, world model only: no readout, no hardware access)
# =============================================================================

@app.get("/api/v1/sensors", response_model=list[SensorResponse])
def list_sensors() -> list[SensorResponse]:
    with connection() as db:
        rows = db.execute("SELECT * FROM sensors ORDER BY created_at DESC").fetchall()
    return [_row_to_sensor(r) for r in rows]


@app.post("/api/v1/sensors", response_model=SensorResponse, status_code=201)
def create_sensor(payload: SensorCreate) -> SensorResponse:
    sns_id = generate_sensor_id()
    now_str = utc_now()
    prov = payload.provenance or Provenance(source_type="user-created", creator_id="user", human_verified=True)
    capabilities = _clean_str_list(payload.capabilities)
    interfaces = _clean_str_list(payload.interfaces)
    with connection() as db:
        db.execute(
            "INSERT INTO sensors (id, name, sensor_type, manufacturer, model, description,"
            " unit, measurement_type, status, capabilities, interfaces, metadata,"
            " provenance, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sns_id, payload.name.strip(), payload.sensor_type.strip(),
             payload.manufacturer.strip(), payload.model.strip(),
             payload.description.strip(), payload.unit.strip(),
             payload.measurement_type.strip(), payload.status,
             dump(capabilities), dump(interfaces), dump(payload.metadata),
             dump(prov.model_dump()), now_str, now_str),
        )
        _append_event(db, "sensor_created", sns_id,
                      {"name": payload.name.strip(),
                       "sensor_type": payload.sensor_type.strip()}, prov)
    logger.info("sensor_created id=%s name=%s", sns_id, payload.name)
    return SensorResponse(id=sns_id, name=payload.name.strip(),
                          sensor_type=payload.sensor_type.strip(),
                          manufacturer=payload.manufacturer.strip(),
                          model=payload.model.strip(),
                          description=payload.description.strip(),
                          unit=payload.unit.strip(),
                          measurement_type=payload.measurement_type.strip(),
                          status=payload.status, capabilities=capabilities,
                          interfaces=interfaces, metadata=payload.metadata,
                          provenance=prov, created_at=now_str, updated_at=now_str)


@app.get("/api/v1/sensors/{sensor_id}", response_model=SensorResponse)
def get_sensor(sensor_id: str) -> SensorResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM sensors WHERE id = ?", (sensor_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Sensor '{sensor_id}' not found")
    return _row_to_sensor(row)


@app.patch("/api/v1/sensors/{sensor_id}", response_model=SensorResponse)
def update_sensor(sensor_id: str, payload: SensorUpdate) -> SensorResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM sensors WHERE id = ?", (sensor_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Sensor '{sensor_id}' not found")
        new_name = payload.name.strip() if payload.name is not None else row["name"]
        new_sensor_type = payload.sensor_type.strip() if payload.sensor_type is not None else row["sensor_type"]
        new_manufacturer = payload.manufacturer.strip() if payload.manufacturer is not None else row["manufacturer"]
        new_model = payload.model.strip() if payload.model is not None else row["model"]
        new_desc = payload.description.strip() if payload.description is not None else row["description"]
        new_unit = payload.unit.strip() if payload.unit is not None else row["unit"]
        new_measurement_type = payload.measurement_type.strip() if payload.measurement_type is not None else row["measurement_type"]
        new_status = payload.status if payload.status is not None else row["status"]
        new_capabilities = _clean_str_list(payload.capabilities) if payload.capabilities is not None else load(row["capabilities"])
        new_interfaces = _clean_str_list(payload.interfaces) if payload.interfaces is not None else load(row["interfaces"])
        new_metadata = payload.metadata if payload.metadata is not None else load(row["metadata"])
        new_prov = payload.provenance or Provenance(**load(row["provenance"]))
        now_str = utc_now()
        db.execute(
            "UPDATE sensors SET name=?, sensor_type=?, manufacturer=?, model=?, description=?,"
            " unit=?, measurement_type=?, status=?, capabilities=?, interfaces=?, metadata=?,"
            " provenance=?, updated_at=? WHERE id=?",
            (new_name, new_sensor_type, new_manufacturer, new_model, new_desc, new_unit,
             new_measurement_type, new_status, dump(new_capabilities), dump(new_interfaces),
             dump(new_metadata), dump(new_prov.model_dump()), now_str, sensor_id),
        )
        _append_event(db, "sensor_updated", sensor_id,
                      {"name": new_name, "sensor_type": new_sensor_type}, new_prov)
    logger.info("sensor_updated id=%s", sensor_id)
    return SensorResponse(id=sensor_id, name=new_name, sensor_type=new_sensor_type,
                          manufacturer=new_manufacturer, model=new_model,
                          description=new_desc, unit=new_unit,
                          measurement_type=new_measurement_type, status=new_status,
                          capabilities=new_capabilities, interfaces=new_interfaces,
                          metadata=new_metadata, provenance=new_prov,
                          created_at=row["created_at"], updated_at=now_str)


@app.delete("/api/v1/sensors/{sensor_id}", status_code=204)
def delete_sensor(sensor_id: str) -> Response:
    with connection() as db:
        row = db.execute("SELECT * FROM sensors WHERE id = ?", (sensor_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Sensor '{sensor_id}' not found")
        _append_event(db, "sensor_deleted", sensor_id, {"name": row["name"]})
        db.execute("DELETE FROM sensors WHERE id = ?", (sensor_id,))
    logger.info("sensor_deleted id=%s", sensor_id)
    return Response(status_code=204)


# =============================================================================
# REST API — CAMERAS (M3.3, world model only: no capture, no hardware access)
# =============================================================================

@app.get("/api/v1/cameras", response_model=list[CameraResponse])
def list_cameras() -> list[CameraResponse]:
    with connection() as db:
        rows = db.execute("SELECT * FROM cameras ORDER BY created_at DESC").fetchall()
    return [_row_to_camera(r) for r in rows]


@app.post("/api/v1/cameras", response_model=CameraResponse, status_code=201)
def create_camera(payload: CameraCreate) -> CameraResponse:
    cam_id = generate_camera_id()
    now_str = utc_now()
    prov = payload.provenance or Provenance(source_type="user-created", creator_id="user", human_verified=True)
    capabilities = _clean_str_list(payload.capabilities)
    interfaces = _clean_str_list(payload.interfaces)
    with connection() as db:
        db.execute(
            "INSERT INTO cameras (id, name, camera_type, manufacturer, model, description,"
            " resolution, status, capabilities, interfaces, metadata,"
            " provenance, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cam_id, payload.name.strip(), payload.camera_type.strip(),
             payload.manufacturer.strip(), payload.model.strip(),
             payload.description.strip(), payload.resolution.strip(), payload.status,
             dump(capabilities), dump(interfaces), dump(payload.metadata),
             dump(prov.model_dump()), now_str, now_str),
        )
        _append_event(db, "camera_created", cam_id,
                      {"name": payload.name.strip(),
                       "camera_type": payload.camera_type.strip()}, prov)
    logger.info("camera_created id=%s name=%s", cam_id, payload.name)
    return CameraResponse(id=cam_id, name=payload.name.strip(),
                          camera_type=payload.camera_type.strip(),
                          manufacturer=payload.manufacturer.strip(),
                          model=payload.model.strip(),
                          description=payload.description.strip(),
                          resolution=payload.resolution.strip(),
                          status=payload.status, capabilities=capabilities,
                          interfaces=interfaces, metadata=payload.metadata,
                          provenance=prov, created_at=now_str, updated_at=now_str)


@app.get("/api/v1/cameras/{camera_id}", response_model=CameraResponse)
def get_camera(camera_id: str) -> CameraResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    return _row_to_camera(row)


@app.patch("/api/v1/cameras/{camera_id}", response_model=CameraResponse)
def update_camera(camera_id: str, payload: CameraUpdate) -> CameraResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
        new_name = payload.name.strip() if payload.name is not None else row["name"]
        new_camera_type = payload.camera_type.strip() if payload.camera_type is not None else row["camera_type"]
        new_manufacturer = payload.manufacturer.strip() if payload.manufacturer is not None else row["manufacturer"]
        new_model = payload.model.strip() if payload.model is not None else row["model"]
        new_desc = payload.description.strip() if payload.description is not None else row["description"]
        new_resolution = payload.resolution.strip() if payload.resolution is not None else row["resolution"]
        new_status = payload.status if payload.status is not None else row["status"]
        new_capabilities = _clean_str_list(payload.capabilities) if payload.capabilities is not None else load(row["capabilities"])
        new_interfaces = _clean_str_list(payload.interfaces) if payload.interfaces is not None else load(row["interfaces"])
        new_metadata = payload.metadata if payload.metadata is not None else load(row["metadata"])
        new_prov = payload.provenance or Provenance(**load(row["provenance"]))
        now_str = utc_now()
        db.execute(
            "UPDATE cameras SET name=?, camera_type=?, manufacturer=?, model=?, description=?,"
            " resolution=?, status=?, capabilities=?, interfaces=?, metadata=?,"
            " provenance=?, updated_at=? WHERE id=?",
            (new_name, new_camera_type, new_manufacturer, new_model, new_desc,
             new_resolution, new_status, dump(new_capabilities), dump(new_interfaces),
             dump(new_metadata), dump(new_prov.model_dump()), now_str, camera_id),
        )
        _append_event(db, "camera_updated", camera_id,
                      {"name": new_name, "camera_type": new_camera_type}, new_prov)
    logger.info("camera_updated id=%s", camera_id)
    return CameraResponse(id=camera_id, name=new_name, camera_type=new_camera_type,
                          manufacturer=new_manufacturer, model=new_model,
                          description=new_desc, resolution=new_resolution,
                          status=new_status, capabilities=new_capabilities,
                          interfaces=new_interfaces, metadata=new_metadata,
                          provenance=new_prov, created_at=row["created_at"], updated_at=now_str)


@app.delete("/api/v1/cameras/{camera_id}", status_code=204)
def delete_camera(camera_id: str) -> Response:
    with connection() as db:
        row = db.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
        _append_event(db, "camera_deleted", camera_id, {"name": row["name"]})
        db.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
    logger.info("camera_deleted id=%s", camera_id)
    return Response(status_code=204)


# =============================================================================
# REST API — LOCATIONS (M3.4, world model only: no GIS, hierarchy via relationships)
# =============================================================================

@app.get("/api/v1/locations", response_model=list[LocationResponse])
def list_locations() -> list[LocationResponse]:
    with connection() as db:
        rows = db.execute("SELECT * FROM locations ORDER BY created_at DESC").fetchall()
    return [_row_to_location(r) for r in rows]


@app.post("/api/v1/locations", response_model=LocationResponse, status_code=201)
def create_location(payload: LocationCreate) -> LocationResponse:
    loc_id = generate_location_id()
    now_str = utc_now()
    prov = payload.provenance or Provenance(source_type="user-created", creator_id="user", human_verified=True)
    with connection() as db:
        db.execute(
            "INSERT INTO locations (id, name, location_type, description, status,"
            " metadata, provenance, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (loc_id, payload.name.strip(), payload.location_type.strip(),
             payload.description.strip(), payload.status, dump(payload.metadata),
             dump(prov.model_dump()), now_str, now_str),
        )
        _append_event(db, "location_created", loc_id,
                      {"name": payload.name.strip(),
                       "location_type": payload.location_type.strip()}, prov)
    logger.info("location_created id=%s name=%s", loc_id, payload.name)
    return LocationResponse(id=loc_id, name=payload.name.strip(),
                            location_type=payload.location_type.strip(),
                            description=payload.description.strip(),
                            status=payload.status, metadata=payload.metadata,
                            provenance=prov, created_at=now_str, updated_at=now_str)


@app.get("/api/v1/locations/{location_id}", response_model=LocationResponse)
def get_location(location_id: str) -> LocationResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM locations WHERE id = ?", (location_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Location '{location_id}' not found")
    return _row_to_location(row)


@app.patch("/api/v1/locations/{location_id}", response_model=LocationResponse)
def update_location(location_id: str, payload: LocationUpdate) -> LocationResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM locations WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Location '{location_id}' not found")
        new_name = payload.name.strip() if payload.name is not None else row["name"]
        new_location_type = payload.location_type.strip() if payload.location_type is not None else row["location_type"]
        new_desc = payload.description.strip() if payload.description is not None else row["description"]
        new_status = payload.status if payload.status is not None else row["status"]
        new_metadata = payload.metadata if payload.metadata is not None else load(row["metadata"])
        new_prov = payload.provenance or Provenance(**load(row["provenance"]))
        now_str = utc_now()
        db.execute(
            "UPDATE locations SET name=?, location_type=?, description=?,"
            " status=?, metadata=?, provenance=?, updated_at=? WHERE id=?",
            (new_name, new_location_type, new_desc, new_status,
             dump(new_metadata), dump(new_prov.model_dump()), now_str, location_id),
        )
        _append_event(db, "location_updated", location_id,
                      {"name": new_name, "location_type": new_location_type}, new_prov)
    logger.info("location_updated id=%s", location_id)
    return LocationResponse(id=location_id, name=new_name, location_type=new_location_type,
                            description=new_desc, status=new_status,
                            metadata=new_metadata, provenance=new_prov,
                            created_at=row["created_at"], updated_at=now_str)


@app.delete("/api/v1/locations/{location_id}", status_code=204)
def delete_location(location_id: str) -> Response:
    with connection() as db:
        row = db.execute("SELECT * FROM locations WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Location '{location_id}' not found")
        _append_event(db, "location_deleted", location_id, {"name": row["name"]})
        db.execute("DELETE FROM locations WHERE id = ?", (location_id,))
    logger.info("location_deleted id=%s", location_id)
    return Response(status_code=204)


# =============================================================================
# REST API — MODELS (M3.5, world model data only: no runtime, no inference)
# =============================================================================

@app.get("/api/v1/models", response_model=list[ModelResponse])
def list_models() -> list[ModelResponse]:
    with connection() as db:
        rows = db.execute("SELECT * FROM models ORDER BY created_at DESC").fetchall()
    return [_row_to_model(r) for r in rows]


@app.post("/api/v1/models", response_model=ModelResponse, status_code=201)
def create_model(payload: ModelCreate) -> ModelResponse:
    mod_id = generate_model_id()
    now_str = utc_now()
    prov = payload.provenance or Provenance(source_type="user-created", creator_id="user", human_verified=True)
    capabilities = _clean_str_list(payload.capabilities)
    interfaces = _clean_str_list(payload.interfaces)
    with connection() as db:
        db.execute(
            "INSERT INTO models (id, name, provider, model_identifier, model_type,"
            " description, version, status, capabilities, interfaces, metadata,"
            " provenance, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (mod_id, payload.name.strip(), payload.provider.strip(),
             payload.model_identifier.strip(), payload.model_type,
             payload.description.strip(), payload.version.strip(), payload.status,
             dump(capabilities), dump(interfaces), dump(payload.metadata),
             dump(prov.model_dump()), now_str, now_str),
        )
        _append_event(db, "model_created", mod_id,
                      {"name": payload.name.strip(),
                       "model_type": payload.model_type}, prov)
    logger.info("model_created id=%s name=%s", mod_id, payload.name)
    return ModelResponse(id=mod_id, name=payload.name.strip(),
                         provider=payload.provider.strip(),
                         model_identifier=payload.model_identifier.strip(),
                         model_type=payload.model_type,
                         description=payload.description.strip(),
                         version=payload.version.strip(),
                         status=payload.status, capabilities=capabilities,
                         interfaces=interfaces, metadata=payload.metadata,
                         provenance=prov, created_at=now_str, updated_at=now_str)


@app.get("/api/v1/models/{model_id}", response_model=ModelResponse)
def get_model(model_id: str) -> ModelResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    return _row_to_model(row)


@app.patch("/api/v1/models/{model_id}", response_model=ModelResponse)
def update_model(model_id: str, payload: ModelUpdate) -> ModelResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
        new_name = payload.name.strip() if payload.name is not None else row["name"]
        new_provider = payload.provider.strip() if payload.provider is not None else row["provider"]
        new_identifier = payload.model_identifier.strip() if payload.model_identifier is not None else row["model_identifier"]
        new_model_type = payload.model_type if payload.model_type is not None else row["model_type"]
        new_desc = payload.description.strip() if payload.description is not None else row["description"]
        new_version = payload.version.strip() if payload.version is not None else row["version"]
        new_status = payload.status if payload.status is not None else row["status"]
        new_capabilities = _clean_str_list(payload.capabilities) if payload.capabilities is not None else load(row["capabilities"])
        new_interfaces = _clean_str_list(payload.interfaces) if payload.interfaces is not None else load(row["interfaces"])
        new_metadata = payload.metadata if payload.metadata is not None else load(row["metadata"])
        new_prov = payload.provenance or Provenance(**load(row["provenance"]))
        now_str = utc_now()
        db.execute(
            "UPDATE models SET name=?, provider=?, model_identifier=?, model_type=?,"
            " description=?, version=?, status=?, capabilities=?, interfaces=?,"
            " metadata=?, provenance=?, updated_at=? WHERE id=?",
            (new_name, new_provider, new_identifier, new_model_type, new_desc,
             new_version, new_status, dump(new_capabilities), dump(new_interfaces),
             dump(new_metadata), dump(new_prov.model_dump()), now_str, model_id),
        )
        _append_event(db, "model_updated", model_id,
                      {"name": new_name, "model_type": new_model_type}, new_prov)
    logger.info("model_updated id=%s", model_id)
    return ModelResponse(id=model_id, name=new_name, provider=new_provider,
                         model_identifier=new_identifier, model_type=new_model_type,
                         description=new_desc, version=new_version,
                         status=new_status, capabilities=new_capabilities,
                         interfaces=new_interfaces, metadata=new_metadata,
                         provenance=new_prov, created_at=row["created_at"], updated_at=now_str)


@app.delete("/api/v1/models/{model_id}", status_code=204)
def delete_model(model_id: str) -> Response:
    with connection() as db:
        row = db.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
        _append_event(db, "model_deleted", model_id, {"name": row["name"]})
        db.execute("DELETE FROM models WHERE id = ?", (model_id,))
    logger.info("model_deleted id=%s", model_id)
    return Response(status_code=204)


# =============================================================================
# REST API — TASKS (M3.6, world model data only: describes work, never executes)
# =============================================================================

@app.get("/api/v1/tasks", response_model=list[TaskResponse])
def list_tasks() -> list[TaskResponse]:
    with connection() as db:
        rows = db.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    return [_row_to_task(r) for r in rows]


@app.post("/api/v1/tasks", response_model=TaskResponse, status_code=201)
def create_task(payload: TaskCreate) -> TaskResponse:
    task_id = generate_task_id()
    now_str = utc_now()
    prov = payload.provenance or Provenance(source_type="user-created", creator_id="user", human_verified=True)
    input_requirements = _clean_str_list(payload.input_requirements)
    with connection() as db:
        db.execute(
            "INSERT INTO tasks (id, name, task_type, description, status, priority,"
            " input_requirements, expected_output, parameters, metadata,"
            " provenance, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, payload.name.strip(), payload.task_type,
             payload.description.strip(), payload.status, payload.priority,
             dump(input_requirements), payload.expected_output.strip(),
             dump(payload.parameters), dump(payload.metadata),
             dump(prov.model_dump()), now_str, now_str),
        )
        _append_event(db, "task_created", task_id,
                      {"name": payload.name.strip(),
                       "task_type": payload.task_type}, prov)
    logger.info("task_created id=%s name=%s", task_id, payload.name)
    return TaskResponse(id=task_id, name=payload.name.strip(),
                        task_type=payload.task_type,
                        description=payload.description.strip(),
                        status=payload.status, priority=payload.priority,
                        input_requirements=input_requirements,
                        expected_output=payload.expected_output.strip(),
                        parameters=payload.parameters, metadata=payload.metadata,
                        provenance=prov, created_at=now_str, updated_at=now_str)


@app.get("/api/v1/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str) -> TaskResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return _row_to_task(row)


@app.patch("/api/v1/tasks/{task_id}", response_model=TaskResponse)
def update_task(task_id: str, payload: TaskUpdate) -> TaskResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
        new_name = payload.name.strip() if payload.name is not None else row["name"]
        new_task_type = payload.task_type if payload.task_type is not None else row["task_type"]
        new_desc = payload.description.strip() if payload.description is not None else row["description"]
        new_status = payload.status if payload.status is not None else row["status"]
        new_priority = payload.priority if payload.priority is not None else row["priority"]
        new_input_requirements = _clean_str_list(payload.input_requirements) if payload.input_requirements is not None else load(row["input_requirements"])
        new_expected_output = payload.expected_output.strip() if payload.expected_output is not None else row["expected_output"]
        new_parameters = payload.parameters if payload.parameters is not None else load(row["parameters"])
        new_metadata = payload.metadata if payload.metadata is not None else load(row["metadata"])
        new_prov = payload.provenance or Provenance(**load(row["provenance"]))
        now_str = utc_now()
        db.execute(
            "UPDATE tasks SET name=?, task_type=?, description=?, status=?, priority=?,"
            " input_requirements=?, expected_output=?, parameters=?, metadata=?,"
            " provenance=?, updated_at=? WHERE id=?",
            (new_name, new_task_type, new_desc, new_status, new_priority,
             dump(new_input_requirements), new_expected_output,
             dump(new_parameters), dump(new_metadata),
             dump(new_prov.model_dump()), now_str, task_id),
        )
        _append_event(db, "task_updated", task_id,
                      {"name": new_name, "task_type": new_task_type}, new_prov)
    logger.info("task_updated id=%s", task_id)
    return TaskResponse(id=task_id, name=new_name, task_type=new_task_type,
                        description=new_desc, status=new_status, priority=new_priority,
                        input_requirements=new_input_requirements,
                        expected_output=new_expected_output,
                        parameters=new_parameters, metadata=new_metadata,
                        provenance=new_prov, created_at=row["created_at"], updated_at=now_str)


@app.delete("/api/v1/tasks/{task_id}", status_code=204)
def delete_task(task_id: str) -> Response:
    with connection() as db:
        row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
        _append_event(db, "task_deleted", task_id, {"name": row["name"]})
        db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    logger.info("task_deleted id=%s", task_id)
    return Response(status_code=204)


# =============================================================================
# REST API — ACTUATORS (M3.7, world model data only: describes a possible
# executor, never executes anything)
# =============================================================================

@app.get("/api/v1/actuators", response_model=list[ActuatorResponse])
def list_actuators() -> list[ActuatorResponse]:
    with connection() as db:
        rows = db.execute("SELECT * FROM actuators ORDER BY created_at DESC").fetchall()
    return [_row_to_actuator(r) for r in rows]


@app.post("/api/v1/actuators", response_model=ActuatorResponse, status_code=201)
def create_actuator(payload: ActuatorCreate) -> ActuatorResponse:
    act_id = generate_actuator_id()
    now_str = utc_now()
    prov = payload.provenance or Provenance(source_type="user-created", creator_id="user", human_verified=True)
    capabilities = _clean_str_list(payload.capabilities)
    interfaces = _clean_str_list(payload.interfaces)
    with connection() as db:
        db.execute(
            "INSERT INTO actuators (id, name, actuator_type, manufacturer, model,"
            " description, status, capabilities, interfaces, parameters, metadata,"
            " provenance, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (act_id, payload.name.strip(), payload.actuator_type,
             payload.manufacturer.strip(), payload.model.strip(),
             payload.description.strip(), payload.status,
             dump(capabilities), dump(interfaces), dump(payload.parameters),
             dump(payload.metadata), dump(prov.model_dump()), now_str, now_str),
        )
        _append_event(db, "actuator_created", act_id,
                      {"name": payload.name.strip(),
                       "actuator_type": payload.actuator_type}, prov)
    logger.info("actuator_created id=%s name=%s", act_id, payload.name)
    return ActuatorResponse(id=act_id, name=payload.name.strip(),
                            actuator_type=payload.actuator_type,
                            manufacturer=payload.manufacturer.strip(),
                            model=payload.model.strip(),
                            description=payload.description.strip(),
                            status=payload.status, capabilities=capabilities,
                            interfaces=interfaces, parameters=payload.parameters,
                            metadata=payload.metadata, provenance=prov,
                            created_at=now_str, updated_at=now_str)


@app.get("/api/v1/actuators/{actuator_id}", response_model=ActuatorResponse)
def get_actuator(actuator_id: str) -> ActuatorResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM actuators WHERE id = ?", (actuator_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Actuator '{actuator_id}' not found")
    return _row_to_actuator(row)


@app.patch("/api/v1/actuators/{actuator_id}", response_model=ActuatorResponse)
def update_actuator(actuator_id: str, payload: ActuatorUpdate) -> ActuatorResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM actuators WHERE id = ?", (actuator_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Actuator '{actuator_id}' not found")
        new_name = payload.name.strip() if payload.name is not None else row["name"]
        new_actuator_type = payload.actuator_type if payload.actuator_type is not None else row["actuator_type"]
        new_manufacturer = payload.manufacturer.strip() if payload.manufacturer is not None else row["manufacturer"]
        new_model = payload.model.strip() if payload.model is not None else row["model"]
        new_desc = payload.description.strip() if payload.description is not None else row["description"]
        new_status = payload.status if payload.status is not None else row["status"]
        new_capabilities = _clean_str_list(payload.capabilities) if payload.capabilities is not None else load(row["capabilities"])
        new_interfaces = _clean_str_list(payload.interfaces) if payload.interfaces is not None else load(row["interfaces"])
        new_parameters = payload.parameters if payload.parameters is not None else load(row["parameters"])
        new_metadata = payload.metadata if payload.metadata is not None else load(row["metadata"])
        new_prov = payload.provenance or Provenance(**load(row["provenance"]))
        now_str = utc_now()
        db.execute(
            "UPDATE actuators SET name=?, actuator_type=?, manufacturer=?, model=?,"
            " description=?, status=?, capabilities=?, interfaces=?, parameters=?,"
            " metadata=?, provenance=?, updated_at=? WHERE id=?",
            (new_name, new_actuator_type, new_manufacturer, new_model, new_desc,
             new_status, dump(new_capabilities), dump(new_interfaces),
             dump(new_parameters), dump(new_metadata),
             dump(new_prov.model_dump()), now_str, actuator_id),
        )
        _append_event(db, "actuator_updated", actuator_id,
                      {"name": new_name, "actuator_type": new_actuator_type}, new_prov)
    logger.info("actuator_updated id=%s", actuator_id)
    return ActuatorResponse(id=actuator_id, name=new_name, actuator_type=new_actuator_type,
                            manufacturer=new_manufacturer, model=new_model,
                            description=new_desc, status=new_status,
                            capabilities=new_capabilities, interfaces=new_interfaces,
                            parameters=new_parameters, metadata=new_metadata,
                            provenance=new_prov, created_at=row["created_at"], updated_at=now_str)


@app.delete("/api/v1/actuators/{actuator_id}", status_code=204)
def delete_actuator(actuator_id: str) -> Response:
    with connection() as db:
        row = db.execute("SELECT * FROM actuators WHERE id = ?", (actuator_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Actuator '{actuator_id}' not found")
        _append_event(db, "actuator_deleted", actuator_id, {"name": row["name"]})
        db.execute("DELETE FROM actuators WHERE id = ?", (actuator_id,))
    logger.info("actuator_deleted id=%s", actuator_id)
    return Response(status_code=204)


# =============================================================================
# REST API — FILES (M7.5, record only: never opens, copies or executes files)
# =============================================================================

@app.get("/api/v1/files", response_model=list[FileResponse])
def list_files() -> list[FileResponse]:
    with connection() as db:
        rows = db.execute("SELECT * FROM files ORDER BY created_at DESC").fetchall()
    return [_row_to_file(r) for r in rows]


@app.post("/api/v1/files", response_model=FileResponse, status_code=201)
def create_file(payload: FileCreate) -> FileResponse:
    file_id = generate_file_id()
    now_str = utc_now()
    prov = payload.provenance or Provenance(source_type="user-created", creator_id="user", human_verified=True)
    with connection() as db:
        db.execute(
            "INSERT INTO files (id, name, file_kind, mime_type, sha256, size_bytes,"
            " description, status, metadata, provenance, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (file_id, payload.name.strip(), payload.file_kind,
             payload.mime_type.strip(), payload.sha256,
             payload.size_bytes, payload.description.strip(), payload.status,
             dump(payload.metadata), dump(prov.model_dump()), now_str, now_str),
        )
        _append_event(db, "file_created", file_id,
                      {"name": payload.name.strip(),
                       "file_kind": payload.file_kind}, prov)
    logger.info("file_created id=%s name=%s", file_id, payload.name)
    return FileResponse(id=file_id, name=payload.name.strip(),
                        file_kind=payload.file_kind,
                        mime_type=payload.mime_type.strip(),
                        sha256=payload.sha256,
                        size_bytes=payload.size_bytes,
                        description=payload.description.strip(),
                        status=payload.status, metadata=payload.metadata,
                        provenance=prov, created_at=now_str, updated_at=now_str)


@app.get("/api/v1/files/{file_id}", response_model=FileResponse)
def get_file(file_id: str) -> FileResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"File '{file_id}' not found")
    return _row_to_file(row)


@app.patch("/api/v1/files/{file_id}", response_model=FileResponse)
def update_file(file_id: str, payload: FileUpdate) -> FileResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"File '{file_id}' not found")
        new_name = payload.name.strip() if payload.name is not None else row["name"]
        new_file_kind = payload.file_kind if payload.file_kind is not None else row["file_kind"]
        new_mime_type = payload.mime_type.strip() if payload.mime_type is not None else row["mime_type"]
        new_sha256 = payload.sha256 if payload.sha256 is not None else row["sha256"]
        new_size_bytes = payload.size_bytes if payload.size_bytes is not None else row["size_bytes"]
        new_desc = payload.description.strip() if payload.description is not None else row["description"]
        new_status = payload.status if payload.status is not None else row["status"]
        new_metadata = payload.metadata if payload.metadata is not None else load(row["metadata"])
        new_prov = payload.provenance or Provenance(**load(row["provenance"]))
        now_str = utc_now()
        db.execute(
            "UPDATE files SET name=?, file_kind=?, mime_type=?, sha256=?, size_bytes=?,"
            " description=?, status=?, metadata=?, provenance=?, updated_at=? WHERE id=?",
            (new_name, new_file_kind, new_mime_type, new_sha256, new_size_bytes,
             new_desc, new_status, dump(new_metadata),
             dump(new_prov.model_dump()), now_str, file_id),
        )
        _append_event(db, "file_updated", file_id,
                      {"name": new_name, "file_kind": new_file_kind}, new_prov)
    logger.info("file_updated id=%s", file_id)
    return FileResponse(id=file_id, name=new_name, file_kind=new_file_kind,
                        mime_type=new_mime_type, sha256=new_sha256,
                        size_bytes=new_size_bytes, description=new_desc,
                        status=new_status, metadata=new_metadata,
                        provenance=new_prov, created_at=row["created_at"], updated_at=now_str)


@app.delete("/api/v1/files/{file_id}", status_code=204)
def delete_file(file_id: str) -> Response:
    with connection() as db:
        row = db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"File '{file_id}' not found")
        _append_event(db, "file_deleted", file_id, {"name": row["name"]})
        db.execute("DELETE FROM files WHERE id = ?", (file_id,))
    logger.info("file_deleted id=%s", file_id)
    return Response(status_code=204)


# =============================================================================
# REST API — RELATIONSHIPS
# =============================================================================

@app.get("/api/v1/relationships", response_model=list[RelationshipResponse])
def list_relationships(entity_id: str | None = None) -> list[RelationshipResponse]:
    with connection() as db:
        if entity_id:
            rows = db.execute(
                "SELECT * FROM relationships WHERE from_id=? OR to_id=? ORDER BY created_at DESC",
                (entity_id, entity_id),
            ).fetchall()
        else:
            rows = db.execute("SELECT * FROM relationships ORDER BY created_at DESC").fetchall()
    return [_row_to_relationship(r) for r in rows]


@app.post("/api/v1/relationships", response_model=RelationshipResponse, status_code=201)
def create_relationship(payload: RelationshipCreate) -> RelationshipResponse:
    rel_id = generate_relationship_id()
    now_str = utc_now()
    prov = payload.provenance or Provenance(source_type="user-created", creator_id="user", human_verified=True)
    with connection() as db:
        db.execute(
            "INSERT INTO relationships (id, from_id, predicate, to_id, metadata, provenance, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rel_id, payload.from_id, payload.predicate, payload.to_id, dump(payload.metadata), dump(prov.model_dump()), now_str),
        )
        _append_event(db, "relationship_created", rel_id,
                      {"from_id": payload.from_id, "predicate": payload.predicate, "to_id": payload.to_id}, prov)
    logger.info("relationship_created id=%s %s -[%s]-> %s", rel_id, payload.from_id, payload.predicate, payload.to_id)
    return RelationshipResponse(id=rel_id, from_id=payload.from_id, predicate=payload.predicate,
                                to_id=payload.to_id, metadata=payload.metadata, provenance=prov, created_at=now_str)


@app.delete("/api/v1/relationships/{rel_id}", status_code=204)
def delete_relationship(rel_id: str) -> Response:
    with connection() as db:
        row = db.execute("SELECT * FROM relationships WHERE id = ?", (rel_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Relationship '{rel_id}' not found")
        _append_event(db, "relationship_deleted", rel_id,
                      {"from_id": row["from_id"], "predicate": row["predicate"], "to_id": row["to_id"]})
        db.execute("DELETE FROM relationships WHERE id = ?", (rel_id,))
    logger.info("relationship_deleted id=%s", rel_id)
    return Response(status_code=204)


# =============================================================================
# REST API — EVENTS
# =============================================================================

@app.get("/api/v1/events", response_model=list[EventResponse])
def list_events(entity_id: str | None = None, limit: int = 100, since: str | None = None) -> list[EventResponse]:
    """Bounded event feed with an optional ``since`` timestamp cursor
    (BIG #10 change feed). Additive: existing entity_id/limit behavior
    is unchanged. No dumps: limit is clamped to 1..500."""
    try:
        count = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="limit must be an integer")
    cursor = None
    if since:
        from datetime import datetime
        try:
            cursor = datetime.fromisoformat(since)
        except ValueError:
            raise HTTPException(status_code=422, detail="since must be an ISO timestamp")
    with connection() as db:
        if entity_id and cursor is not None:
            rows = db.execute(
                "SELECT * FROM events WHERE entity_id=? AND timestamp>? ORDER BY timestamp DESC LIMIT ?",
                (entity_id, since, count),
            ).fetchall()
        elif entity_id:
            rows = db.execute(
                "SELECT * FROM events WHERE entity_id=? ORDER BY timestamp DESC LIMIT ?",
                (entity_id, count),
            ).fetchall()
        elif cursor is not None:
            rows = db.execute("SELECT * FROM events WHERE timestamp>? ORDER BY timestamp DESC LIMIT ?", (since, count)).fetchall()
        else:
            rows = db.execute("SELECT * FROM events ORDER BY timestamp DESC LIMIT ?", (count,)).fetchall()
    return [_row_to_event(r) for r in rows]


# =============================================================================
# REST API — SEARCH (M4.2, read-only over the FTS foundation)
# =============================================================================

def _search_result_for(entity_type: str, row) -> SearchResult:
    prov = Provenance(**load(row["provenance"]))
    if entity_type == "relationships":
        metadata = load(row["metadata"])
        return SearchResult(
            entity_type="relationship",
            entity_id=row["id"],
            title=f"{row['from_id']} —[{row['predicate']}]→ {row['to_id']}",
            snippet=dump(metadata),
            provenance=prov,
            details={"from_id": row["from_id"], "predicate": row["predicate"],
                     "to_id": row["to_id"], "metadata": metadata},
        )
    singular = {"objects": "object", "projects": "project", "ideas": "idea",
                "hardware": "hardware", "sensors": "sensor",
                "cameras": "camera", "locations": "location",
                "models": "model", "tasks": "task",
                "actuators": "actuator", "files": "file"}[entity_type]
    details: dict = {}
    if entity_type == "objects":
        details = {"quantity": row["quantity"]}
    elif entity_type == "hardware":
        details = {"category": row["category"], "status": row["status"],
                   "manufacturer": row["manufacturer"], "model": row["model"]}
    elif entity_type == "sensors":
        details = {"sensor_type": row["sensor_type"], "status": row["status"],
                   "unit": row["unit"], "manufacturer": row["manufacturer"]}
    elif entity_type == "cameras":
        details = {"camera_type": row["camera_type"], "status": row["status"],
                   "resolution": row["resolution"], "manufacturer": row["manufacturer"]}
    elif entity_type == "locations":
        details = {"location_type": row["location_type"], "status": row["status"]}
    elif entity_type == "models":
        details = {"model_type": row["model_type"], "status": row["status"],
                   "provider": row["provider"]}
    elif entity_type == "tasks":
        details = {"task_type": row["task_type"], "status": row["status"],
                   "priority": row["priority"]}
    elif entity_type == "actuators":
        details = {"actuator_type": row["actuator_type"], "status": row["status"],
                   "manufacturer": row["manufacturer"]}
    elif entity_type == "files":
        details = {"file_kind": row["file_kind"], "mime_type": row["mime_type"],
                   "status": row["status"]}
    else:
        details = {"status": row["status"]}
    return SearchResult(
        entity_type=singular,  # type: ignore[arg-type]
        entity_id=row["id"],
        title=row["name"],
        snippet=row["description"],
        provenance=prov,
        details=details,
    )


@app.get("/api/v1/search", response_model=SearchResponse)
def search(q: str = "", type: str | None = None) -> SearchResponse:
    sanitized = sanitize_fts_query(q)
    if sanitized is None:
        raise HTTPException(status_code=422, detail="Query 'q' must be non-empty text (max 200 chars)")
    if type is not None and type not in SEARCHABLE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown type '{type}'; expected one of {sorted(SEARCHABLE_TYPES)}",
        )
    hits = search_fts(sanitized, [type] if type else None)
    canonical = {"objects": "objects", "projects": "projects",
                 "ideas": "ideas", "relationships": "relationships",
                 "hardware": "hardware", "sensors": "sensors",
                 "cameras": "cameras", "locations": "locations",
                 "models": "models", "tasks": "tasks",
                 "actuators": "actuators", "files": "files"}
    results: list[SearchResult] = []
    with connection() as db:
        for entity_type, entity_id in hits:
            row = db.execute(
                f"SELECT * FROM {canonical[entity_type]} WHERE id = ?", (entity_id,)
            ).fetchone()
            if row is None:
                continue
            results.append(_search_result_for(entity_type, row))
    return SearchResponse(query=q.strip(), results=results, total=len(results))


# =============================================================================
# REST API — GRAPH (M4.3, read-only traversal over relationships)
# =============================================================================

GRAPH_MAX_DEPTH = 2
GRAPH_MAX_EDGES = 200

_GRAPH_TABLES = (("object", "objects"), ("project", "projects"), ("idea", "ideas"),
                 ("hardware", "hardware"), ("sensor", "sensors"),
                 ("camera", "cameras"), ("location", "locations"),
                 ("model", "models"), ("task", "tasks"),
                 ("actuator", "actuators"), ("file", "files"))


def _graph_node_for(entity_type: str, row) -> GraphNode:
    details: dict = {}
    if entity_type == "object":
        details = {"quantity": row["quantity"]}
    elif entity_type == "hardware":
        details = {"category": row["category"], "status": row["status"]}
    elif entity_type == "sensor":
        details = {"sensor_type": row["sensor_type"], "status": row["status"]}
    elif entity_type == "camera":
        details = {"camera_type": row["camera_type"], "status": row["status"]}
    elif entity_type == "location":
        details = {"location_type": row["location_type"], "status": row["status"]}
    elif entity_type == "model":
        details = {"model_type": row["model_type"], "status": row["status"]}
    elif entity_type == "task":
        details = {"task_type": row["task_type"], "status": row["status"]}
    elif entity_type == "actuator":
        details = {"actuator_type": row["actuator_type"], "status": row["status"]}
    elif entity_type == "file":
        details = {"file_kind": row["file_kind"], "status": row["status"]}
    else:
        details = {"status": row["status"]}
    return GraphNode(
        entity_type=entity_type,  # type: ignore[arg-type]
        entity_id=row["id"],
        title=row["name"],
        provenance=Provenance(**load(row["provenance"])),
        details=details,
    )


def _find_graph_node(db, entity_id: str) -> GraphNode | None:
    for entity_type, table in _GRAPH_TABLES:
        row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (entity_id,)).fetchone()
        if row is not None:
            return _graph_node_for(entity_type, row)
    return None


@app.get("/api/v1/graph", response_model=GraphResponse)
def graph(entity_id: str | None = None, depth: int = 1) -> GraphResponse:
    if not entity_id or not entity_id.strip():
        raise HTTPException(status_code=422, detail="Query 'entity_id' must not be empty")
    if depth < 1 or depth > GRAPH_MAX_DEPTH:
        raise HTTPException(
            status_code=422,
            detail=f"Query 'depth' must be between 1 and {GRAPH_MAX_DEPTH}",
        )
    entity_id = entity_id.strip()
    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}
    with connection() as db:
        start = _find_graph_node(db, entity_id)
        if start is None:
            raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
        nodes[entity_id] = start
        visited = {entity_id}
        frontier = [entity_id]
        for _ in range(depth):
            next_frontier: list[str] = []
            for current in frontier:
                rows = db.execute(
                    "SELECT * FROM relationships WHERE from_id = ? OR to_id = ?"
                    " ORDER BY created_at DESC",
                    (current, current),
                ).fetchall()
                for row in rows:
                    if len(edges) >= GRAPH_MAX_EDGES:
                        break
                    rel = _row_to_relationship(row)
                    edges.setdefault(rel.id, GraphEdge(
                        id=rel.id, from_id=rel.from_id, predicate=rel.predicate,
                        to_id=rel.to_id, metadata=rel.metadata,
                        provenance=rel.provenance,
                    ))
                    other = rel.to_id if rel.from_id == current else rel.from_id
                    if other not in visited:
                        visited.add(other)
                        node = _find_graph_node(db, other)
                        if node is not None:
                            nodes[other] = node
                        next_frontier.append(other)
            frontier = next_frontier
    return GraphResponse(entity_id=entity_id, depth=depth,
                         nodes=list(nodes.values()), edges=list(edges.values()))


# =============================================================================
# UI HELPERS — DARK MODERN THEME
# =============================================================================

STYLE = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0f1117; --surface: #1a1d27; --surface2: #232638;
  --border: #2e3150; --text: #e2e8f0; --text-muted: #8892b0;
  --accent: #6366f1; --accent-hover: #818cf8;
  --danger: #ef4444; --danger-hover: #f87171;
  --success: #22c55e; --warning: #f59e0b;
  --radius: 8px; --radius-sm: 5px;
}
body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg);
  color: var(--text); min-height: 100vh; font-size: 15px; line-height: 1.6; }
a { color: var(--accent-hover); text-decoration: none; }
a:hover { text-decoration: underline; }
nav { background: var(--surface); border-bottom: 1px solid var(--border);
  padding: 0 1.5rem; display: flex; align-items: center; gap: 2rem; }
nav .logo { font-weight: 700; font-size: 1.1rem; color: var(--text);
  padding: 1rem 0; letter-spacing: 0.03em; }
nav .logo span { color: var(--accent); }
nav a { color: var(--text-muted); padding: 1rem 0.25rem; border-bottom: 2px solid transparent;
  font-size: 14px; font-weight: 500; transition: color 0.15s; }
nav a:hover, nav a.active { color: var(--text); border-bottom-color: var(--accent);
  text-decoration: none; }
.container { max-width: 1100px; margin: 0 auto; padding: 2rem 1.5rem; }
h1 { font-size: 1.6rem; font-weight: 700; color: var(--text); margin-bottom: 0.25rem; }
h2 { font-size: 1.2rem; font-weight: 600; color: var(--text); margin-bottom: 1rem; }
h3 { font-size: 1rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.75rem;
  text-transform: uppercase; letter-spacing: 0.05em; font-size: 0.75rem; }
.subtitle { color: var(--text-muted); font-size: 14px; margin-bottom: 2rem; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 1.5rem; margin-bottom: 1.5rem; }
.card-sm { padding: 1rem; }
table { width: 100%; border-collapse: collapse; }
th { text-align: left; padding: 0.6rem 0.75rem; font-size: 12px; font-weight: 600;
  color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em;
  border-bottom: 1px solid var(--border); }
td { padding: 0.75rem; border-bottom: 1px solid var(--border); font-size: 14px;
  color: var(--text); vertical-align: middle; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: var(--surface2); }
code { background: var(--surface2); color: var(--accent-hover); padding: 0.15rem 0.4rem;
  border-radius: var(--radius-sm); font-family: ui-monospace, monospace; font-size: 12px; }
pre { background: #0a0c14; color: #a5f3fc; padding: 1rem; border-radius: var(--radius);
  overflow-x: auto; font-size: 13px; line-height: 1.5; border: 1px solid var(--border); }
label { display: block; font-size: 13px; font-weight: 500; color: var(--text-muted);
  margin-bottom: 0.35rem; }
input, select, textarea { width: 100%; padding: 0.55rem 0.75rem;
  background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius-sm);
  color: var(--text); font-size: 14px; outline: none; transition: border-color 0.15s; }
input:focus, select:focus, textarea:focus { border-color: var(--accent); }
select option { background: var(--surface2); }
.form-row { display: grid; gap: 1rem; margin-bottom: 1rem; }
.form-row.cols-2 { grid-template-columns: 1fr 1fr; }
.form-row.cols-3 { grid-template-columns: 1fr 1fr 1fr; }
.form-row.cols-4 { grid-template-columns: 2fr 2fr 1fr 1.5fr; }
.form-row.cols-5 { grid-template-columns: 2fr 3fr 1fr 2fr auto; }
.btn { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.5rem 1rem;
  border: none; border-radius: var(--radius-sm); font-size: 14px; font-weight: 500;
  cursor: pointer; text-decoration: none; transition: background 0.15s; white-space: nowrap; }
.btn-primary { background: var(--accent); color: white; }
.btn-primary:hover { background: var(--accent-hover); text-decoration: none; color: white; }
.btn-ghost { background: transparent; border: 1px solid var(--border); color: var(--text-muted); }
.btn-ghost:hover { background: var(--surface2); color: var(--text); text-decoration: none; }
.btn-danger { background: transparent; border: 1px solid var(--danger); color: var(--danger); }
.btn-danger:hover { background: var(--danger); color: white; text-decoration: none; }
.btn-sm { padding: 0.3rem 0.65rem; font-size: 13px; }
.badge { display: inline-flex; align-items: center; gap: 0.25rem; padding: 0.2rem 0.55rem;
  border-radius: 9999px; font-size: 12px; font-weight: 500; }
.badge-user { background: #1e3a5f; color: #93c5fd; }
.badge-ai-uv { background: #422006; color: #fcd34d; border: 1px solid #854d0e; }
.badge-ai-v { background: #14532d; color: #86efac; }
.badge-sensor { background: #1e1b4b; color: #a5b4fc; }
.badge-imported { background: #2e1065; color: #d8b4fe; }
.badge-ext { background: var(--surface2); color: var(--text-muted); }
.status-badge { padding: 0.2rem 0.55rem; border-radius: 9999px; font-size: 12px; font-weight: 500; }
.s-idea { background: #1e1b4b; color: #a5b4fc; }
.s-planned { background: #0c4a6e; color: #7dd3fc; }
.s-active { background: #14532d; color: #86efac; }
.s-paused { background: #422006; color: #fcd34d; }
.s-completed { background: #1a2e1a; color: #86efac; }
.s-archived { background: #1c1917; color: #a8a29e; }
.s-raw { background: #1e1b4b; color: #a5b4fc; }
.s-considered { background: #0c4a6e; color: #7dd3fc; }
.s-rejected { background: #450a0a; color: #fca5a5; }
.s-converted { background: #14532d; color: #86efac; }
.flex { display: flex; } .gap-2 { gap: 0.5rem; } .gap-3 { gap: 0.75rem; }
.items-center { align-items: center; } .justify-between { justify-content: space-between; }
.mb-1 { margin-bottom: 0.5rem; } .mb-2 { margin-bottom: 1rem; }
.mb-3 { margin-bottom: 1.5rem; } .mt-2 { margin-top: 1rem; } .mt-3 { margin-top: 1.5rem; }
.text-muted { color: var(--text-muted); } .text-sm { font-size: 13px; }
.empty { text-align: center; padding: 2.5rem; color: var(--text-muted); font-size: 14px; }
.detail-grid { display: grid; grid-template-columns: 140px 1fr; gap: 0.5rem 1rem;
  font-size: 14px; align-items: start; }
.detail-grid dt { color: var(--text-muted); font-size: 13px; padding-top: 0.1rem; }
.detail-grid dd { color: var(--text); }
.section-header { display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 1rem; }
.event-row { display: flex; gap: 1rem; padding: 0.6rem 0; border-bottom: 1px solid var(--border);
  align-items: flex-start; font-size: 13px; }
.event-row:last-child { border-bottom: none; }
.event-type { color: var(--accent-hover); font-family: ui-monospace, monospace; min-width: 160px; }
.event-time { color: var(--text-muted); min-width: 150px; }
hr { border: none; border-top: 1px solid var(--border); margin: 1.5rem 0; }
@media (max-width: 700px) {
  .form-row.cols-4, .form-row.cols-5 { grid-template-columns: 1fr; }
  .form-row.cols-2, .form-row.cols-3 { grid-template-columns: 1fr; }
  nav { gap: 1rem; } .container { padding: 1rem; }
}
"""


def _nav(active: str) -> str:
    items = [("objects", "/", "📦 Objects"), ("projects", "/projects", "🗂 Projects"), ("ideas", "/ideas", "💡 Ideas"), ("hardware", "/hardware", "🔧 Hardware"), ("sensors", "/sensors", "📡 Sensors"), ("cameras", "/cameras", "📷 Cameras"), ("locations", "/locations", "📍 Locations"), ("models", "/models", "🧠 Models"), ("tasks", "/tasks", "✅ Tasks"), ("actuators", "/actuators", "🦾 Actuators"), ("files", "/files", "📁 Files"), ("search", "/search", "🔍 Search")]
    links = ""
    for key, href, label in items:
        cls = ' class="active"' if key == active else ""
        links += f'<a href="{href}"{cls}>{label}</a>'
    return f'<nav><span class="logo">IN<span>VENT</span>ory</span>{links}<a href="/docs" style="margin-left:auto;font-size:13px;" target="_blank">API Docs ↗</a></nav>'


def _prov_badge(prov: dict) -> str:
    st = prov.get("source_type", "user-created")
    verified = prov.get("human_verified", False)
    if st == "ai-generated":
        return ('<span class="badge badge-ai-v">🤖 AI ✓</span>' if verified
                else '<span class="badge badge-ai-uv">🤖 AI ⚠</span>')
    if st == "user-created":
        return '<span class="badge badge-user">👤 User</span>'
    if st == "sensor-observed":
        return '<span class="badge badge-sensor">📡 Sensor</span>'
    if st == "imported":
        return '<span class="badge badge-imported">📥 Import</span>'
    return f'<span class="badge badge-ext">{escape(st)}</span>'


def _status_badge(status: str) -> str:
    return f'<span class="status-badge s-{escape(status)}">{escape(status)}</span>'


def _source_options(selected: str = "user-created") -> str:
    opts = [
        ("user-created", "👤 Handmatig"),
        ("ai-generated", "🤖 AI Observatie"),
        ("sensor-observed", "📡 Sensor"),
        ("imported", "📥 Geïmporteerd"),
        ("external-source", "🌐 Externe Bron"),
    ]
    return "".join(f'<option value="{v}"{"  selected" if v == selected else ""}>{l}</option>' for v, l in opts)


def _project_status_options(selected: str = "planned") -> str:
    opts = ["idea", "planned", "active", "paused", "completed", "archived"]
    return "".join(f'<option value="{s}"{"  selected" if s == selected else ""}>{s}</option>' for s in opts)


def _idea_status_options(selected: str = "raw") -> str:
    opts = ["raw", "considered", "planned", "rejected", "converted"]
    return "".join(f'<option value="{s}"{"  selected" if s == selected else ""}>{s}</option>' for s in opts)


def _predicate_options(selected: str = "related_to") -> str:
    opts = ["used_in", "uses", "related_to", "part_of", "contains", "became", "led_to", "depends_on", "produced_by", "stored_in"]
    return "".join(f'<option value="{s}"{"  selected" if s == selected else ""}>{s}</option>' for s in opts)


def _page(title: str, nav_active: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} · INVENTory</title>
  <style>{STYLE}</style>
</head>
<body>
{_nav(nav_active)}
<div class="container">
{body}
</div>
</body>
</html>"""


def _render_relationships(rels: list[RelationshipResponse], current_id: str) -> str:
    if not rels:
        return '<p class="text-muted text-sm">Geen relaties.</p>'
    rows = ""
    for r in rels:
        direction = "→" if r.from_id == current_id else "←"
        other = r.to_id if r.from_id == current_id else r.from_id
        rows += f"""<div class="flex gap-2 items-center" style="padding:0.5rem 0;border-bottom:1px solid var(--border);font-size:13px;">
          <code>{escape(r.from_id)}</code>
          <span class="text-muted">—[{escape(r.predicate)}]→</span>
          <code>{escape(r.to_id)}</code>
          <span class="text-muted" style="margin-left:auto;">{escape(r.created_at[:10])}</span>
          <form method="post" action="/web/relationships/{escape(r.id)}/delete" style="display:inline;" onsubmit="return confirm('Relatie verwijderen?')">
            <button class="btn btn-danger btn-sm" type="submit">✕</button>
          </form>
        </div>"""
    return rows


def _render_events(events: list[EventResponse]) -> str:
    if not events:
        return '<p class="text-muted text-sm">Geen historische events.</p>'
    rows = ""
    for e in events:
        rows += f"""<div class="event-row">
          <span class="event-type">{escape(e.event_type)}</span>
          <span class="event-time">{escape(e.timestamp[:19].replace("T", " "))}</span>
          <span class="text-muted">{escape(str(e.data))}</span>
        </div>"""
    return rows


# =============================================================================
# WEB UI — OBJECTS
# =============================================================================

@app.get("/", response_class=HTMLResponse)
def web_objects_index() -> str:
    with connection() as db:
        rows = db.execute("SELECT * FROM objects ORDER BY created_at DESC").fetchall()

    table_rows = ""
    for r in rows:
        prov = load(r["provenance"])
        badge = _prov_badge(prov)
        table_rows += f"""<tr>
          <td><a href="/objects/{escape(r['id'])}"><code>{escape(r['id'])}</code></a></td>
          <td><strong>{escape(r['name'])}</strong></td>
          <td class="text-muted">{escape(r['description'][:60] + '…' if len(r['description']) > 60 else r['description'] or '—')}</td>
          <td>{r['quantity']}</td>
          <td>{badge}</td>
          <td class="text-sm text-muted">{r['created_at'][:10]}</td>
        </tr>"""

    empty = f'<tr><td colspan="6" class="empty">Nog geen objecten. Voeg er hieronder één toe.</td></tr>' if not rows else ""

    body = f"""
<div class="flex justify-between items-center mb-3">
  <div>
    <h1>📦 Objects</h1>
    <p class="subtitle">Fysieke en digitale objecten in je wereldmodel ({len(rows)} totaal)</p>
  </div>
</div>
<div class="card mb-3">
  <h3>🔍 Zoeken</h3>
  <form method="get" action="/search">
    <div class="form-row cols-3">
      <div><label>Zoekterm</label><input name="q" placeholder="bijv. stappenmotor"></div>
      <div><label>Type</label><select name="type"><option value="">Alle types</option><option value="objects">Objects</option><option value="projects">Projecten</option><option value="ideas">Ideeën</option><option value="relationships">Relaties</option></select></div>
      <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary" type="submit">Zoeken</button></div>
    </div>
  </form>
</div>
<div class="card mb-3">
  <h3>Nieuw Object</h3>
  <form method="post" action="/web/objects">
    <div class="form-row cols-4">
      <div><label>Naam *</label><input name="name" required placeholder="bijv. Nema 17 Stappenmotor"></div>
      <div><label>Omschrijving</label><input name="description" placeholder="bijv. 1.8°, 12V, 2A"></div>
      <div><label>Aantal</label><input name="quantity" type="number" value="1" min="0"></div>
      <div><label>Herkomst</label><select name="source_type">{_source_options()}</select></div>
    </div>
    <button class="btn btn-primary" type="submit">+ Object toevoegen</button>
  </form>
</div>
<div class="card">
  <table>
    <thead><tr><th>ID</th><th>Naam</th><th>Omschrijving</th><th>Aantal</th><th>Herkomst</th><th>Aangemaakt</th></tr></thead>
    <tbody>{table_rows}{empty}</tbody>
  </table>
</div>"""
    return _page("Objects", "objects", body)


@app.post("/web/objects", response_class=RedirectResponse)
async def web_create_object(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    prov = Provenance(source_type=_form_source(form), creator_id="web_ui",
                      human_verified=(_form_source(form) == "user-created"))
    create_object(ObjectCreate(name=name, description=_form_str(form, "description"),
                               quantity=max(0, _form_int(form, "quantity")), provenance=prov))
    return RedirectResponse(url="/", status_code=303)


@app.get("/objects/{object_id}", response_class=HTMLResponse)
def web_object_detail(object_id: str, edited: bool = False) -> str:
    obj = get_object(object_id)
    rels = _get_relationships_for(object_id)
    events = _get_events_for(object_id)
    badge = _prov_badge(obj.provenance.model_dump())
    prov_verified = "✅ Ja" if obj.provenance.human_verified else "⚠️ Nee"

    predicates = [("used_in", "gebruikt in"), ("uses", "gebruikt"), ("related_to", "gerelateerd aan"),
                  ("part_of", "onderdeel van"), ("contains", "bevat"), ("became", "werd"),
                  ("led_to", "leidde tot"), ("depends_on", "afhankelijk van"),
                  ("produced_by", "geproduceerd door"), ("stored_in", "opgeslagen in")]

    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/" class="btn btn-ghost btn-sm">← Terug</a>
  <span class="text-muted text-sm">Object detail</span>
</div>
<div class="card mb-2">
  <div class="flex justify-between items-center mb-2">
    <div>
      <h1>{escape(obj.name)}</h1>
      <code class="text-sm">{escape(obj.id)}</code>
    </div>
    <div class="flex gap-2">{badge}
      <a href="/objects/{escape(obj.id)}/edit" class="btn btn-ghost btn-sm">✏ Bewerken</a>
      <form method="post" action="/web/objects/{escape(obj.id)}/delete"
            onsubmit="return confirm('Weet je zeker dat je «{escape(obj.name)}» wilt verwijderen? Deze actie wordt geregistreerd in de eventgeschiedenis.')">
        <button class="btn btn-danger btn-sm" type="submit">🗑 Verwijderen</button>
      </form>
    </div>
  </div>
  <p style="color:var(--text-muted);margin-bottom:1.5rem;">{escape(obj.description or 'Geen omschrijving.')}</p>
  <div class="form-row cols-2">
    <div>
      <h3>Details</h3>
      <dl class="detail-grid">
        <dt>Aantal</dt><dd>{obj.quantity}</dd>
        <dt>Aangemaakt</dt><dd>{escape(obj.created_at[:19].replace("T", " "))}</dd>
        <dt>Bijgewerkt</dt><dd>{escape(obj.updated_at[:19].replace("T", " "))}</dd>
      </dl>
    </div>
    <div>
      <h3>Provenance</h3>
      <dl class="detail-grid">
        <dt>Bron</dt><dd>{escape(obj.provenance.source_type)}</dd>
        <dt>Aangemaakt door</dt><dd>{escape(obj.provenance.creator_id)}</dd>
        <dt>Geverifieerd</dt><dd>{prov_verified}</dd>
      </dl>
    </div>
  </div>
</div>
<div class="card mb-2">
  <h3>Relaties ({len(rels)})</h3>
  {_render_relationships(rels, object_id)}
  <hr>
  <h3 class="mt-2">Relatie toevoegen</h3>
  <form method="post" action="/web/relationships" class="form-row cols-3">
    <input type="hidden" name="from_id" value="{escape(obj.id)}">
    <div><label>Predikaat</label><select name="predicate">{_predicate_options()}</select></div>
    <div><label>Naar entiteit (ID)</label><input name="to_id" placeholder="proj_... / idea_... / obj_..."></div>
    <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary" type="submit">+ Koppelen</button></div>
  </form>
</div>
<div class="card">
  <h3>Geschiedenis / Events ({len(events)})</h3>
  {_render_events(events)}
</div>"""
    return _page(obj.name, "objects", body)


@app.get("/objects/{object_id}/edit", response_class=HTMLResponse)
def web_object_edit_form(object_id: str) -> str:
    obj = get_object(object_id)
    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/objects/{escape(obj.id)}" class="btn btn-ghost btn-sm">← Terug</a>
</div>
<div class="card">
  <h2>✏ Object bewerken</h2>
  <form method="post" action="/web/objects/{escape(obj.id)}/edit">
    <div class="form-row cols-2">
      <div><label>Naam *</label><input name="name" required value="{escape(obj.name)}"></div>
      <div><label>Aantal</label><input name="quantity" type="number" value="{obj.quantity}" min="0"></div>
    </div>
    <div class="form-row">
      <div><label>Omschrijving</label><textarea name="description" rows="3">{escape(obj.description)}</textarea></div>
    </div>
    <div class="flex gap-2">
      <button class="btn btn-primary" type="submit">💾 Opslaan</button>
      <a href="/objects/{escape(obj.id)}" class="btn btn-ghost">Annuleren</a>
    </div>
  </form>
</div>"""
    return _page(f"Bewerken: {obj.name}", "objects", body)


@app.post("/web/objects/{object_id}/edit", response_class=RedirectResponse)
async def web_update_object(object_id: str, request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    update_object(object_id, ObjectUpdate(
        name=name,
        description=_form_str(form, "description"),
        quantity=max(0, _form_int(form, "quantity")),
    ))
    return RedirectResponse(url=f"/objects/{object_id}", status_code=303)


@app.post("/web/objects/{object_id}/delete", response_class=RedirectResponse)
def web_delete_object(object_id: str) -> RedirectResponse:
    delete_object(object_id)
    return RedirectResponse(url="/", status_code=303)


# =============================================================================
# WEB UI — PROJECTS
# =============================================================================

@app.get("/projects", response_class=HTMLResponse)
def web_projects_index() -> str:
    with connection() as db:
        rows = db.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()

    table_rows = ""
    for r in rows:
        prov = load(r["provenance"])
        table_rows += f"""<tr>
          <td><a href="/projects/{escape(r['id'])}"><code>{escape(r['id'])}</code></a></td>
          <td><strong>{escape(r['name'])}</strong></td>
          <td class="text-muted">{escape(r['description'][:60] + '…' if len(r['description']) > 60 else r['description'] or '—')}</td>
          <td>{_status_badge(r['status'])}</td>
          <td>{_prov_badge(prov)}</td>
          <td class="text-sm text-muted">{r['created_at'][:10]}</td>
        </tr>"""

    empty = f'<tr><td colspan="6" class="empty">Nog geen projecten. Maak er hieronder één aan.</td></tr>' if not rows else ""

    body = f"""
<div class="flex justify-between items-center mb-3">
  <div>
    <h1>🗂 Projects</h1>
    <p class="subtitle">Actieve en geplande projecten ({len(rows)} totaal)</p>
  </div>
</div>
<div class="card mb-3">
  <h3>Nieuw Project</h3>
  <form method="post" action="/web/projects">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required placeholder="bijv. 3D-Printer build"></div>
      <div><label>Omschrijving</label><input name="description" placeholder="Korte omschrijving"></div>
      <div><label>Status</label><select name="status">{_project_status_options()}</select></div>
    </div>
    <button class="btn btn-primary" type="submit">+ Project aanmaken</button>
  </form>
</div>
<div class="card">
  <table>
    <thead><tr><th>ID</th><th>Naam</th><th>Omschrijving</th><th>Status</th><th>Herkomst</th><th>Aangemaakt</th></tr></thead>
    <tbody>{table_rows}{empty}</tbody>
  </table>
</div>"""
    return _page("Projects", "projects", body)


@app.post("/web/projects", response_class=RedirectResponse)
async def web_create_project(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    status_raw = _form_str(form, "status", "planned")
    status: ProjectStatus = status_raw if status_raw in ("idea", "planned", "active", "paused", "completed", "archived") else "planned"
    prov = Provenance(source_type="user-created", creator_id="web_ui", human_verified=True)
    create_project(ProjectCreate(name=name, description=_form_str(form, "description"), status=status, provenance=prov))
    return RedirectResponse(url="/projects", status_code=303)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def web_project_detail(project_id: str) -> str:
    proj = get_project(project_id)
    rels = _get_relationships_for(project_id)
    events = _get_events_for(project_id)

    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/projects" class="btn btn-ghost btn-sm">← Terug</a>
</div>
<div class="card mb-2">
  <div class="flex justify-between items-center mb-2">
    <div>
      <h1>{escape(proj.name)}</h1>
      <code class="text-sm">{escape(proj.id)}</code>
    </div>
    <div class="flex gap-2">
      {_status_badge(proj.status)}
      <a href="/projects/{escape(proj.id)}/edit" class="btn btn-ghost btn-sm">✏ Bewerken</a>
      <form method="post" action="/web/projects/{escape(proj.id)}/delete"
            onsubmit="return confirm('Project «{escape(proj.name)}» verwijderen?')">
        <button class="btn btn-danger btn-sm" type="submit">🗑 Verwijderen</button>
      </form>
    </div>
  </div>
  <p style="color:var(--text-muted);margin-bottom:1.5rem;">{escape(proj.description or 'Geen omschrijving.')}</p>
  <dl class="detail-grid">
    <dt>Status</dt><dd>{_status_badge(proj.status)}</dd>
    <dt>Aangemaakt</dt><dd>{escape(proj.created_at[:19].replace("T", " "))}</dd>
    <dt>Bijgewerkt</dt><dd>{escape(proj.updated_at[:19].replace("T", " "))}</dd>
    <dt>Bron</dt><dd>{escape(proj.provenance.source_type)}</dd>
  </dl>
</div>
<div class="card mb-2">
  <h3>Relaties ({len(rels)})</h3>
  {_render_relationships(rels, project_id)}
  <hr>
  <h3 class="mt-2">Relatie toevoegen</h3>
  <form method="post" action="/web/relationships" class="form-row cols-3">
    <input type="hidden" name="from_id" value="{escape(proj.id)}">
    <div><label>Predikaat</label><select name="predicate">{_predicate_options()}</select></div>
    <div><label>Naar entiteit (ID)</label><input name="to_id" placeholder="obj_... / idea_... / proj_..."></div>
    <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary" type="submit">+ Koppelen</button></div>
  </form>
</div>
<div class="card">
  <h3>Geschiedenis ({len(events)})</h3>
  {_render_events(events)}
</div>"""
    return _page(proj.name, "projects", body)


@app.get("/projects/{project_id}/edit", response_class=HTMLResponse)
def web_project_edit_form(project_id: str) -> str:
    proj = get_project(project_id)
    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/projects/{escape(proj.id)}" class="btn btn-ghost btn-sm">← Terug</a>
</div>
<div class="card">
  <h2>✏ Project bewerken</h2>
  <form method="post" action="/web/projects/{escape(proj.id)}/edit">
    <div class="form-row cols-2">
      <div><label>Naam *</label><input name="name" required value="{escape(proj.name)}"></div>
      <div><label>Status</label><select name="status">{_project_status_options(proj.status)}</select></div>
    </div>
    <div class="form-row">
      <div><label>Omschrijving</label><textarea name="description" rows="3">{escape(proj.description)}</textarea></div>
    </div>
    <div class="flex gap-2">
      <button class="btn btn-primary" type="submit">💾 Opslaan</button>
      <a href="/projects/{escape(proj.id)}" class="btn btn-ghost">Annuleren</a>
    </div>
  </form>
</div>"""
    return _page(f"Bewerken: {proj.name}", "projects", body)


@app.post("/web/projects/{project_id}/edit", response_class=RedirectResponse)
async def web_update_project(project_id: str, request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    status_raw = _form_str(form, "status", "planned")
    status: ProjectStatus = status_raw if status_raw in ("idea", "planned", "active", "paused", "completed", "archived") else "planned"
    update_project(project_id, ProjectUpdate(name=name, description=_form_str(form, "description"), status=status))
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@app.post("/web/projects/{project_id}/delete", response_class=RedirectResponse)
def web_delete_project(project_id: str) -> RedirectResponse:
    delete_project(project_id)
    return RedirectResponse(url="/projects", status_code=303)


# =============================================================================
# WEB UI — IDEAS
# =============================================================================

@app.get("/ideas", response_class=HTMLResponse)
def web_ideas_index() -> str:
    with connection() as db:
        rows = db.execute("SELECT * FROM ideas ORDER BY created_at DESC").fetchall()

    table_rows = ""
    for r in rows:
        prov = load(r["provenance"])
        table_rows += f"""<tr>
          <td><a href="/ideas/{escape(r['id'])}"><code>{escape(r['id'])}</code></a></td>
          <td><strong>{escape(r['name'])}</strong></td>
          <td class="text-muted">{escape(r['description'][:60] + '…' if len(r['description']) > 60 else r['description'] or '—')}</td>
          <td>{_status_badge(r['status'])}</td>
          <td>{_prov_badge(prov)}</td>
          <td class="text-sm text-muted">{r['created_at'][:10]}</td>
        </tr>"""

    empty = f'<tr><td colspan="6" class="empty">Nog geen ideeën. Leg er hieronder één vast.</td></tr>' if not rows else ""

    body = f"""
<div class="flex justify-between items-center mb-3">
  <div>
    <h1>💡 Ideas</h1>
    <p class="subtitle">Ruwe ideeën tot concrete plannen ({len(rows)} totaal)</p>
  </div>
</div>
<div class="card mb-3">
  <h3>Nieuw Idee</h3>
  <form method="post" action="/web/ideas">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required placeholder="bijv. Filament droger bouwen"></div>
      <div><label>Omschrijving</label><input name="description" placeholder="Eerste gedachte"></div>
      <div><label>Status</label><select name="status">{_idea_status_options()}</select></div>
    </div>
    <button class="btn btn-primary" type="submit">+ Idee vastleggen</button>
  </form>
</div>
<div class="card">
  <table>
    <thead><tr><th>ID</th><th>Naam</th><th>Omschrijving</th><th>Status</th><th>Herkomst</th><th>Aangemaakt</th></tr></thead>
    <tbody>{table_rows}{empty}</tbody>
  </table>
</div>"""
    return _page("Ideas", "ideas", body)


@app.post("/web/ideas", response_class=RedirectResponse)
async def web_create_idea(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    status_raw = _form_str(form, "status", "raw")
    status: IdeaStatus = status_raw if status_raw in ("raw", "considered", "planned", "rejected", "converted") else "raw"
    prov = Provenance(source_type="user-created", creator_id="web_ui", human_verified=True)
    create_idea(IdeaCreate(name=name, description=_form_str(form, "description"), status=status, provenance=prov))
    return RedirectResponse(url="/ideas", status_code=303)


@app.get("/ideas/{idea_id}", response_class=HTMLResponse)
def web_idea_detail(idea_id: str) -> str:
    idea = get_idea(idea_id)
    rels = _get_relationships_for(idea_id)
    events = _get_events_for(idea_id)

    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/ideas" class="btn btn-ghost btn-sm">← Terug</a>
</div>
<div class="card mb-2">
  <div class="flex justify-between items-center mb-2">
    <div>
      <h1>{escape(idea.name)}</h1>
      <code class="text-sm">{escape(idea.id)}</code>
    </div>
    <div class="flex gap-2">
      {_status_badge(idea.status)}
      <a href="/ideas/{escape(idea.id)}/edit" class="btn btn-ghost btn-sm">✏ Bewerken</a>
      <form method="post" action="/web/ideas/{escape(idea.id)}/delete"
            onsubmit="return confirm('Idee «{escape(idea.name)}» verwijderen?')">
        <button class="btn btn-danger btn-sm" type="submit">🗑 Verwijderen</button>
      </form>
    </div>
  </div>
  <p style="color:var(--text-muted);margin-bottom:1.5rem;">{escape(idea.description or 'Geen omschrijving.')}</p>
  <dl class="detail-grid">
    <dt>Status</dt><dd>{_status_badge(idea.status)}</dd>
    <dt>Aangemaakt</dt><dd>{escape(idea.created_at[:19].replace("T", " "))}</dd>
    <dt>Bijgewerkt</dt><dd>{escape(idea.updated_at[:19].replace("T", " "))}</dd>
    <dt>Bron</dt><dd>{escape(idea.provenance.source_type)}</dd>
  </dl>
</div>
<div class="card mb-2">
  <h3>Relaties ({len(rels)})</h3>
  {_render_relationships(rels, idea_id)}
  <hr>
  <h3 class="mt-2">Relatie toevoegen</h3>
  <form method="post" action="/web/relationships" class="form-row cols-3">
    <input type="hidden" name="from_id" value="{escape(idea.id)}">
    <div><label>Predikaat</label><select name="predicate">{_predicate_options()}</select></div>
    <div><label>Naar entiteit (ID)</label><input name="to_id" placeholder="proj_... / obj_... / idea_..."></div>
    <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary" type="submit">+ Koppelen</button></div>
  </form>
</div>
<div class="card">
  <h3>Geschiedenis ({len(events)})</h3>
  {_render_events(events)}
</div>"""
    return _page(idea.name, "ideas", body)


@app.get("/ideas/{idea_id}/edit", response_class=HTMLResponse)
def web_idea_edit_form(idea_id: str) -> str:
    idea = get_idea(idea_id)
    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/ideas/{escape(idea.id)}" class="btn btn-ghost btn-sm">← Terug</a>
</div>
<div class="card">
  <h2>✏ Idee bewerken</h2>
  <form method="post" action="/web/ideas/{escape(idea.id)}/edit">
    <div class="form-row cols-2">
      <div><label>Naam *</label><input name="name" required value="{escape(idea.name)}"></div>
      <div><label>Status</label><select name="status">{_idea_status_options(idea.status)}</select></div>
    </div>
    <div class="form-row">
      <div><label>Omschrijving</label><textarea name="description" rows="3">{escape(idea.description)}</textarea></div>
    </div>
    <div class="flex gap-2">
      <button class="btn btn-primary" type="submit">💾 Opslaan</button>
      <a href="/ideas/{escape(idea.id)}" class="btn btn-ghost">Annuleren</a>
    </div>
  </form>
</div>"""
    return _page(f"Bewerken: {idea.name}", "ideas", body)


@app.post("/web/ideas/{idea_id}/edit", response_class=RedirectResponse)
async def web_update_idea(idea_id: str, request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    status_raw = _form_str(form, "status", "raw")
    status: IdeaStatus = status_raw if status_raw in ("raw", "considered", "planned", "rejected", "converted") else "raw"
    update_idea(idea_id, IdeaUpdate(name=name, description=_form_str(form, "description"), status=status))
    return RedirectResponse(url=f"/ideas/{idea_id}", status_code=303)


@app.post("/web/ideas/{idea_id}/delete", response_class=RedirectResponse)
def web_delete_idea(idea_id: str) -> RedirectResponse:
    delete_idea(idea_id)
    return RedirectResponse(url="/ideas", status_code=303)


# =============================================================================
# WEB UI — RELATIONSHIPS
# =============================================================================

@app.post("/web/relationships", response_class=RedirectResponse)
async def web_create_relationship(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    from_id = _form_str(form, "from_id")
    to_id = _form_str(form, "to_id")
    predicate_raw = _form_str(form, "predicate", "related_to")
    if not from_id or not to_id:
        raise HTTPException(status_code=422, detail="from_id and to_id required")
    valid_predicates = ("used_in", "uses", "related_to", "part_of", "contains", "became",
                        "led_to", "depends_on", "produced_by", "stored_in")
    from .schemas import RelationshipPredicate
    predicate: RelationshipPredicate = predicate_raw if predicate_raw in valid_predicates else "related_to"
    prov = Provenance(source_type="user-created", creator_id="web_ui", human_verified=True)
    create_relationship(RelationshipCreate(from_id=from_id, predicate=predicate, to_id=to_id, provenance=prov))
    # Redirect back to the from_id entity detail page
    if from_id.startswith("proj_"):
        return RedirectResponse(url=f"/projects/{from_id}", status_code=303)
    if from_id.startswith("idea_"):
        return RedirectResponse(url=f"/ideas/{from_id}", status_code=303)
    if from_id.startswith("hw_"):
        return RedirectResponse(url=f"/hardware/{from_id}", status_code=303)
    if from_id.startswith("sns_"):
        return RedirectResponse(url=f"/sensors/{from_id}", status_code=303)
    if from_id.startswith("cam_"):
        return RedirectResponse(url=f"/cameras/{from_id}", status_code=303)
    if from_id.startswith("loc_"):
        return RedirectResponse(url=f"/locations/{from_id}", status_code=303)
    if from_id.startswith("mod_"):
        return RedirectResponse(url=f"/models/{from_id}", status_code=303)
    if from_id.startswith("task_"):
        return RedirectResponse(url=f"/tasks/{from_id}", status_code=303)
    if from_id.startswith("act_"):
        return RedirectResponse(url=f"/actuators/{from_id}", status_code=303)
    if from_id.startswith("file_"):
        return RedirectResponse(url=f"/files/{from_id}", status_code=303)
    return RedirectResponse(url=f"/objects/{from_id}", status_code=303)


@app.post("/web/relationships/{rel_id}/delete", response_class=RedirectResponse)
async def web_delete_relationship_form(rel_id: str, request: Request) -> RedirectResponse:
    # Find out from_id to redirect back
    with connection() as db:
        row = db.execute("SELECT from_id FROM relationships WHERE id=?", (rel_id,)).fetchone()
    from_id = row["from_id"] if row else None
    delete_relationship(rel_id)
    if from_id:
        if from_id.startswith("proj_"):
            return RedirectResponse(url=f"/projects/{from_id}", status_code=303)
        if from_id.startswith("idea_"):
            return RedirectResponse(url=f"/ideas/{from_id}", status_code=303)
        if from_id.startswith("hw_"):
            return RedirectResponse(url=f"/hardware/{from_id}", status_code=303)
        if from_id.startswith("sns_"):
            return RedirectResponse(url=f"/sensors/{from_id}", status_code=303)
        if from_id.startswith("cam_"):
            return RedirectResponse(url=f"/cameras/{from_id}", status_code=303)
        if from_id.startswith("loc_"):
            return RedirectResponse(url=f"/locations/{from_id}", status_code=303)
        if from_id.startswith("mod_"):
            return RedirectResponse(url=f"/models/{from_id}", status_code=303)
        if from_id.startswith("task_"):
            return RedirectResponse(url=f"/tasks/{from_id}", status_code=303)
        if from_id.startswith("act_"):
            return RedirectResponse(url=f"/actuators/{from_id}", status_code=303)
        if from_id.startswith("file_"):
            return RedirectResponse(url=f"/files/{from_id}", status_code=303)
        return RedirectResponse(url=f"/objects/{from_id}", status_code=303)
    return RedirectResponse(url="/", status_code=303)


# =============================================================================
# WEB UI — SEARCH & GRAPH (M4.4, read-only views over the search/graph APIs)
# =============================================================================

def _type_options(selected: str | None) -> str:
    opts = [("", "Alle types"), ("objects", "Objects"), ("projects", "Projecten"),
            ("ideas", "Ideeën"), ("relationships", "Relaties")]
    return "".join(
        f'<option value="{v}"{" selected" if v == (selected or "") else ""}>{l}</option>'
        for v, l in opts
    )


def _detail_url(entity_type: str, entity_id: str) -> str | None:
    if entity_type == "object":
        return f"/objects/{escape(entity_id)}"
    if entity_type == "project":
        return f"/projects/{escape(entity_id)}"
    if entity_type == "idea":
        return f"/ideas/{escape(entity_id)}"
    if entity_type == "hardware":
        return f"/hardware/{escape(entity_id)}"
    if entity_type == "sensor":
        return f"/sensors/{escape(entity_id)}"
    if entity_type == "camera":
        return f"/cameras/{escape(entity_id)}"
    if entity_type == "location":
        return f"/locations/{escape(entity_id)}"
    if entity_type == "model":
        return f"/models/{escape(entity_id)}"
    if entity_type == "task":
        return f"/tasks/{escape(entity_id)}"
    if entity_type == "actuator":
        return f"/actuators/{escape(entity_id)}"
    if entity_type == "file":
        return f"/files/{escape(entity_id)}"
    return None


def _search_form(q: str = "", selected_type: str | None = None) -> str:
    return f"""
<div class="card mb-3">
  <h3>🔍 Zoeken</h3>
  <form method="get" action="/search">
    <div class="form-row cols-3">
      <div><label>Zoekterm</label><input name="q" value="{escape(q)}" placeholder="bijv. stappenmotor"></div>
      <div><label>Type</label><select name="type">{_type_options(selected_type)}</select></div>
      <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary" type="submit">Zoeken</button></div>
    </div>
  </form>
</div>"""


@app.get("/search", response_class=HTMLResponse)
def web_search(q: str = "", type: str | None = None) -> str:
    form = _search_form(q, type)
    if not q.strip():
        body = f"""
<div class="flex justify-between items-center mb-3">
  <div><h1>🔍 Search</h1><p class="subtitle">Doorzoek objecten, projecten, ideeën en relaties</p></div>
</div>
{form}
<div class="card"><p class="text-muted text-sm">Vul hierboven een zoekterm in.</p></div>"""
        return _page("Search", "search", body)
    try:
        result = search(q, type)
    except HTTPException as error:
        body = f"""
<div class="flex justify-between items-center mb-3">
  <div><h1>🔍 Search</h1><p class="subtitle">Doorzoek objecten, projecten, ideeën en relaties</p></div>
</div>
{form}
<div class="card"><p class="text-muted text-sm">{escape(str(error.detail))}</p></div>"""
        return _page("Search", "search", body)

    rows = ""
    for r in result.results:
        detail = _detail_url(r.entity_type, r.entity_id)
        title = (f'<a href="{detail}"><strong>{escape(r.title)}</strong></a>'
                 if detail else f"<strong>{escape(r.title)}</strong>")
        rows += f"""<tr>
          <td class="text-sm text-muted">{escape(r.entity_type)}</td>
          <td>{title}<br><code class="text-sm">{escape(r.entity_id)}</code></td>
          <td class="text-muted">{escape(r.snippet[:120] + '…' if len(r.snippet) > 120 else r.snippet or '—')}</td>
          <td>{_prov_badge(r.provenance.model_dump())}</td>
          <td><a class="btn btn-ghost btn-sm" href="/graph/{escape(r.entity_id) if r.entity_type != 'relationship' else escape(r.details.get('from_id', r.entity_id))}">⛨ Graaf</a></td>
        </tr>"""
    empty = (f'<tr><td colspan="5" class="empty">Geen resultaten voor «{escape(q.strip())}».</td></tr>'
             if not result.results else "")
    body = f"""
<div class="flex justify-between items-center mb-3">
  <div><h1>🔍 Search</h1><p class="subtitle">{result.total} resultaat/resultaten voor «{escape(result.query)}»</p></div>
</div>
{form}
<div class="card">
  <table>
    <thead><tr><th>Type</th><th>Titel</th><th>Fragment</th><th>Herkomst</th><th></th></tr></thead>
    <tbody>{rows}{empty}</tbody>
  </table>
</div>"""
    return _page("Search", "search", body)


@app.get("/graph/{entity_id}", response_class=HTMLResponse)
def web_graph(entity_id: str, depth: int = 1):
    try:
        result = graph(entity_id, depth)
    except HTTPException as error:
        status = error.status_code if error.status_code == 404 else 422
        body = f"""<div class="card"><p class="text-muted">Graaf niet beschikbaar: {escape(str(error.detail))}</p>
<p class="mt-2"><a href="/search" class="btn btn-ghost btn-sm">← Naar zoeken</a></p></div>"""
        return HTMLResponse(_page("Graph", "search", body), status_code=status)
    start = next((n for n in result.nodes if n.entity_id == result.entity_id), None)
    depth_links = " ".join(
        f'<a class="btn {"btn-primary" if d == result.depth else "btn-ghost"} btn-sm" href="/graph/{escape(result.entity_id)}?depth={d}">Diepte {d}</a>'
        for d in (1, 2)
    )
    node_rows = ""
    for node in result.nodes:
        node_rows += f"""<tr>
          <td class="text-sm text-muted">{escape(node.entity_type)}</td>
          <td><a href="/graph/{escape(node.entity_id)}"><strong>{escape(node.title)}</strong></a><br><code class="text-sm">{escape(node.entity_id)}</code></td>
          <td>{_prov_badge(node.provenance.model_dump())}</td>
        </tr>"""
    edge_rows = ""
    for edge in result.edges:
        edge_rows += f"""<div class="flex gap-2 items-center" style="padding:0.5rem 0;border-bottom:1px solid var(--border);font-size:13px;">
          <a href="/graph/{escape(edge.from_id)}"><code>{escape(edge.from_id)}</code></a>
          <span class="text-muted">—[{escape(edge.predicate)}]→</span>
          <a href="/graph/{escape(edge.to_id)}"><code>{escape(edge.to_id)}</code></a>
          {_prov_badge(edge.provenance.model_dump())}
        </div>"""
    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/search" class="btn btn-ghost btn-sm">← Zoeken</a>
  <span class="text-muted text-sm">Graaf</span>
</div>
<div class="card mb-2">
  <div class="flex justify-between items-center mb-2">
    <div>
      <h1>{escape(start.title) if start else escape(result.entity_id)}</h1>
      <code class="text-sm">{escape(result.entity_id)}</code>
    </div>
    <div class="flex gap-2">{depth_links}</div>
  </div>
</div>
<div class="card mb-2">
  <h3>Nodes ({len(result.nodes)})</h3>
  <table>
    <thead><tr><th>Type</th><th>Titel</th><th>Herkomst</th></tr></thead>
    <tbody>{node_rows}</tbody>
  </table>
</div>
<div class="card">
  <h3>Relaties ({len(result.edges)})</h3>
  {edge_rows if edge_rows else '<p class="text-muted text-sm">Geen relaties.</p>'}
</div>"""
    return _page(f"Graph: {start.title if start else result.entity_id}", "search", body)


# =============================================================================
# WEB UI — HARDWARE (M3.1, mirrors the objects pages)
# =============================================================================

def _hardware_status_options(selected: str = "unknown") -> str:
    opts = ["available", "in_use", "maintenance", "retired", "unknown"]
    return "".join(f'<option value="{s}"{" selected" if s == selected else ""}>{s}</option>' for s in opts)


@app.get("/hardware", response_class=HTMLResponse)
def web_hardware_index() -> str:
    with connection() as db:
        rows = db.execute("SELECT * FROM hardware ORDER BY created_at DESC").fetchall()

    table_rows = ""
    for r in rows:
        prov = load(r["provenance"])
        table_rows += f"""<tr>
          <td><a href="/hardware/{escape(r['id'])}"><code>{escape(r['id'])}</code></a></td>
          <td><strong>{escape(r['name'])}</strong></td>
          <td class="text-muted">{escape(r['category'] or '—')}</td>
          <td>{_status_badge(r['status'])}</td>
          <td>{_prov_badge(prov)}</td>
          <td class="text-sm text-muted">{r['created_at'][:10]}</td>
        </tr>"""

    empty = f'<tr><td colspan="6" class="empty">Nog geen hardware. Voeg er hieronder één toe.</td></tr>' if not rows else ""

    body = f"""
<div class="flex justify-between items-center mb-3">
  <div>
    <h1>🔧 Hardware</h1>
    <p class="subtitle">Fysieke apparaten in je wereldmodel ({len(rows)} totaal)</p>
  </div>
</div>
<div class="card mb-3">
  <h3>Nieuwe Hardware</h3>
  <form method="post" action="/web/hardware">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required placeholder="bijv. Raspberry Pi 5"></div>
      <div><label>Categorie *</label><input name="category" required placeholder="bijv. single-board-computer"></div>
      <div><label>Status</label><select name="status">{_hardware_status_options()}</select></div>
    </div>
    <div class="form-row cols-3">
      <div><label>Fabrikant</label><input name="manufacturer" placeholder="bijv. Raspberry Pi Ltd"></div>
      <div><label>Model</label><input name="model" placeholder="bijv. Pi 5 8GB"></div>
      <div><label>Omschrijving</label><input name="description" placeholder="Korte omschrijving"></div>
    </div>
    <button class="btn btn-primary" type="submit">+ Hardware toevoegen</button>
  </form>
</div>
<div class="card">
  <table>
    <thead><tr><th>ID</th><th>Naam</th><th>Categorie</th><th>Status</th><th>Herkomst</th><th>Aangemaakt</th></tr></thead>
    <tbody>{table_rows}{empty}</tbody>
  </table>
</div>"""
    return _page("Hardware", "hardware", body)


@app.post("/web/hardware", response_class=RedirectResponse)
async def web_create_hardware(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    category = _form_str(form, "category")
    if not name or not category:
        raise HTTPException(status_code=422, detail="Name and category are required")
    status_raw = _form_str(form, "status", "unknown")
    status = status_raw if status_raw in ("available", "in_use", "maintenance", "retired", "unknown") else "unknown"
    prov = Provenance(source_type="user-created", creator_id="web_ui", human_verified=True)
    created = create_hardware(HardwareCreate(name=name, category=category, status=status,
                                             manufacturer=_form_str(form, "manufacturer"),
                                             model=_form_str(form, "model"),
                                             description=_form_str(form, "description"),
                                             provenance=prov))
    return RedirectResponse(url=f"/hardware/{created.id}", status_code=303)


@app.get("/hardware/{hardware_id}", response_class=HTMLResponse)
def web_hardware_detail(hardware_id: str) -> str:
    hw = get_hardware(hardware_id)
    rels = _get_relationships_for(hardware_id)
    events = _get_events_for(hardware_id)
    badge = _prov_badge(hw.provenance.model_dump())

    caps = ", ".join(hw.capabilities) if hw.capabilities else "—"
    ifaces = ", ".join(hw.interfaces) if hw.interfaces else "—"

    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/hardware" class="btn btn-ghost btn-sm">← Terug</a>
  <span class="text-muted text-sm">Hardware detail</span>
</div>
<div class="card mb-2">
  <div class="flex justify-between items-center mb-2">
    <div>
      <h1>{escape(hw.name)}</h1>
      <code class="text-sm">{escape(hw.id)}</code>
    </div>
    <div class="flex gap-2">
      {_status_badge(hw.status)}
      <a href="/hardware/{escape(hw.id)}/edit" class="btn btn-ghost btn-sm">✏ Bewerken</a>
      <a href="/graph/{escape(hw.id)}" class="btn btn-ghost btn-sm">⛨ Graaf</a>
      <form method="post" action="/web/hardware/{escape(hw.id)}/delete"
            onsubmit="return confirm('Weet je zeker dat je «{escape(hw.name)}» wilt verwijderen? Deze actie wordt geregistreerd in de eventgeschiedenis.')">
        <button class="btn btn-danger btn-sm" type="submit">🗑 Verwijderen</button>
      </form>
    </div>
  </div>
  <p style="color:var(--text-muted);margin-bottom:1.5rem;">{escape(hw.description or 'Geen omschrijving.')}</p>
  <dl class="detail-grid">
    <dt>Categorie</dt><dd>{escape(hw.category)}</dd>
    <dt>Fabrikant</dt><dd>{escape(hw.manufacturer or '—')}</dd>
    <dt>Model</dt><dd>{escape(hw.model or '—')}</dd>
    <dt>Capabilities</dt><dd>{escape(caps)}</dd>
    <dt>Interfaces</dt><dd>{escape(ifaces)}</dd>
    <dt>Aangemaakt</dt><dd>{escape(hw.created_at[:19].replace("T", " "))}</dd>
    <dt>Bijgewerkt</dt><dd>{escape(hw.updated_at[:19].replace("T", " "))}</dd>
    <dt>Bron</dt><dd>{escape(hw.provenance.source_type)} {badge}</dd>
  </dl>
</div>
<div class="card mb-2">
  <h3>Relaties ({len(rels)})</h3>
  {_render_relationships(rels, hardware_id)}
  <hr>
  <h3 class="mt-2">Relatie toevoegen</h3>
  <form method="post" action="/web/relationships" class="form-row cols-3">
    <input type="hidden" name="from_id" value="{escape(hw.id)}">
    <div><label>Predikaat</label><select name="predicate">{_predicate_options()}</select></div>
    <div><label>Naar entiteit (ID)</label><input name="to_id" placeholder="obj_... / proj_... / hw_..."></div>
    <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary" type="submit">+ Koppelen</button></div>
  </form>
</div>
<div class="card">
  <h3>Geschiedenis / Events ({len(events)})</h3>
  {_render_events(events)}
</div>"""
    return _page(hw.name, "hardware", body)


@app.get("/hardware/{hardware_id}/edit", response_class=HTMLResponse)
def web_hardware_edit_form(hardware_id: str) -> str:
    hw = get_hardware(hardware_id)
    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/hardware/{escape(hw.id)}" class="btn btn-ghost btn-sm">← Terug</a>
</div>
<div class="card">
  <h2>✏ Hardware bewerken</h2>
  <form method="post" action="/web/hardware/{escape(hw.id)}/edit">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required value="{escape(hw.name)}"></div>
      <div><label>Categorie *</label><input name="category" required value="{escape(hw.category)}"></div>
      <div><label>Status</label><select name="status">{_hardware_status_options(hw.status)}</select></div>
    </div>
    <div class="form-row cols-2">
      <div><label>Fabrikant</label><input name="manufacturer" value="{escape(hw.manufacturer)}"></div>
      <div><label>Model</label><input name="model" value="{escape(hw.model)}"></div>
    </div>
    <div class="form-row">
      <div><label>Omschrijving</label><textarea name="description" rows="3">{escape(hw.description)}</textarea></div>
    </div>
    <div class="flex gap-2">
      <button class="btn btn-primary" type="submit">💾 Opslaan</button>
      <a href="/hardware/{escape(hw.id)}" class="btn btn-ghost">Annuleren</a>
    </div>
  </form>
</div>"""
    return _page(f"Bewerken: {hw.name}", "hardware", body)


@app.post("/web/hardware/{hardware_id}/edit", response_class=RedirectResponse)
async def web_update_hardware(hardware_id: str, request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    category = _form_str(form, "category")
    if not name or not category:
        raise HTTPException(status_code=422, detail="Name and category are required")
    status_raw = _form_str(form, "status", "unknown")
    status = status_raw if status_raw in ("available", "in_use", "maintenance", "retired", "unknown") else "unknown"
    update_hardware(hardware_id, HardwareUpdate(
        name=name, category=category, status=status,
        manufacturer=_form_str(form, "manufacturer"),
        model=_form_str(form, "model"),
        description=_form_str(form, "description"),
    ))
    return RedirectResponse(url=f"/hardware/{hardware_id}", status_code=303)


@app.post("/web/hardware/{hardware_id}/delete", response_class=RedirectResponse)
def web_delete_hardware(hardware_id: str) -> RedirectResponse:
    delete_hardware(hardware_id)
    return RedirectResponse(url="/hardware", status_code=303)


# =============================================================================
# WEB UI — SENSORS (M3.2, mirrors the hardware pages; world model only)
# =============================================================================

def _sensor_status_options(selected: str = "unknown") -> str:
    opts = ["available", "in_use", "maintenance", "retired", "unknown"]
    return "".join(f'<option value="{s}"{" selected" if s == selected else ""}>{s}</option>' for s in opts)


@app.get("/sensors", response_class=HTMLResponse)
def web_sensors_index() -> str:
    with connection() as db:
        rows = db.execute("SELECT * FROM sensors ORDER BY created_at DESC").fetchall()

    table_rows = ""
    for r in rows:
        prov = load(r["provenance"])
        table_rows += f"""<tr>
          <td><a href="/sensors/{escape(r['id'])}"><code>{escape(r['id'])}</code></a></td>
          <td><strong>{escape(r['name'])}</strong></td>
          <td class="text-muted">{escape(r['sensor_type'] or '—')}</td>
          <td>{_status_badge(r['status'])}</td>
          <td>{_prov_badge(prov)}</td>
          <td class="text-sm text-muted">{r['created_at'][:10]}</td>
        </tr>"""

    empty = f'<tr><td colspan="6" class="empty">Nog geen sensoren. Voeg er hieronder één toe.</td></tr>' if not rows else ""

    body = f"""
<div class="flex justify-between items-center mb-3">
  <div>
    <h1>📡 Sensors</h1>
    <p class="subtitle">Fysieke sensoren in je wereldmodel ({len(rows)} totaal)</p>
  </div>
</div>
<div class="card mb-3">
  <h3>Nieuwe Sensor</h3>
  <form method="post" action="/web/sensors">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required placeholder="bijv. DHT22 Woonkamer"></div>
      <div><label>Sensortype *</label><input name="sensor_type" required placeholder="bijv. temperatuur"></div>
      <div><label>Status</label><select name="status">{_sensor_status_options()}</select></div>
    </div>
    <div class="form-row cols-3">
      <div><label>Fabrikant</label><input name="manufacturer" placeholder="bijv. Aosong"></div>
      <div><label>Model</label><input name="model" placeholder="bijv. DHT22"></div>
      <div><label>Eenheid</label><input name="unit" placeholder="bijv. °C"></div>
    </div>
    <button class="btn btn-primary" type="submit">+ Sensor toevoegen</button>
  </form>
</div>
<div class="card">
  <table>
    <thead><tr><th>ID</th><th>Naam</th><th>Type</th><th>Status</th><th>Herkomst</th><th>Aangemaakt</th></tr></thead>
    <tbody>{table_rows}{empty}</tbody>
  </table>
</div>"""
    return _page("Sensors", "sensors", body)


@app.post("/web/sensors", response_class=RedirectResponse)
async def web_create_sensor(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    sensor_type = _form_str(form, "sensor_type")
    if not name or not sensor_type:
        raise HTTPException(status_code=422, detail="Name and sensor_type are required")
    status_raw = _form_str(form, "status", "unknown")
    status = status_raw if status_raw in ("available", "in_use", "maintenance", "retired", "unknown") else "unknown"
    prov = Provenance(source_type="user-created", creator_id="web_ui", human_verified=True)
    created = create_sensor(SensorCreate(name=name, sensor_type=sensor_type, status=status,
                                         manufacturer=_form_str(form, "manufacturer"),
                                         model=_form_str(form, "model"),
                                         unit=_form_str(form, "unit"),
                                         provenance=prov))
    return RedirectResponse(url=f"/sensors/{created.id}", status_code=303)


@app.get("/sensors/{sensor_id}", response_class=HTMLResponse)
def web_sensor_detail(sensor_id: str) -> str:
    sns = get_sensor(sensor_id)
    rels = _get_relationships_for(sensor_id)
    events = _get_events_for(sensor_id)
    badge = _prov_badge(sns.provenance.model_dump())

    caps = ", ".join(sns.capabilities) if sns.capabilities else "—"
    ifaces = ", ".join(sns.interfaces) if sns.interfaces else "—"

    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/sensors" class="btn btn-ghost btn-sm">← Terug</a>
  <span class="text-muted text-sm">Sensor detail</span>
</div>
<div class="card mb-2">
  <div class="flex justify-between items-center mb-2">
    <div>
      <h1>{escape(sns.name)}</h1>
      <code class="text-sm">{escape(sns.id)}</code>
    </div>
    <div class="flex gap-2">
      {_status_badge(sns.status)}
      <a href="/sensors/{escape(sns.id)}/edit" class="btn btn-ghost btn-sm">✏ Bewerken</a>
      <a href="/graph/{escape(sns.id)}" class="btn btn-ghost btn-sm">⛨ Graaf</a>
      <form method="post" action="/web/sensors/{escape(sns.id)}/delete"
            onsubmit="return confirm('Weet je zeker dat je «{escape(sns.name)}» wilt verwijderen? Deze actie wordt geregistreerd in de eventgeschiedenis.')">
        <button class="btn btn-danger btn-sm" type="submit">🗑 Verwijderen</button>
      </form>
    </div>
  </div>
  <p style="color:var(--text-muted);margin-bottom:1.5rem;">{escape(sns.description or 'Geen omschrijving.')}</p>
  <dl class="detail-grid">
    <dt>Type</dt><dd>{escape(sns.sensor_type)}</dd>
    <dt>Fabrikant</dt><dd>{escape(sns.manufacturer or '—')}</dd>
    <dt>Model</dt><dd>{escape(sns.model or '—')}</dd>
    <dt>Eenheid</dt><dd>{escape(sns.unit or '—')}</dd>
    <dt>Meetwaarde</dt><dd>{escape(sns.measurement_type or '—')}</dd>
    <dt>Capabilities</dt><dd>{escape(caps)}</dd>
    <dt>Interfaces</dt><dd>{escape(ifaces)}</dd>
    <dt>Aangemaakt</dt><dd>{escape(sns.created_at[:19].replace("T", " "))}</dd>
    <dt>Bijgewerkt</dt><dd>{escape(sns.updated_at[:19].replace("T", " "))}</dd>
    <dt>Bron</dt><dd>{escape(sns.provenance.source_type)} {badge}</dd>
  </dl>
</div>
<div class="card mb-2">
  <h3>Relaties ({len(rels)})</h3>
  {_render_relationships(rels, sensor_id)}
  <hr>
  <h3 class="mt-2">Relatie toevoegen</h3>
  <form method="post" action="/web/relationships" class="form-row cols-3">
    <input type="hidden" name="from_id" value="{escape(sns.id)}">
    <div><label>Predikaat</label><select name="predicate">{_predicate_options()}</select></div>
    <div><label>Naar entiteit (ID)</label><input name="to_id" placeholder="hw_... / obj_... / proj_..."></div>
    <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary" type="submit">+ Koppelen</button></div>
  </form>
</div>
<div class="card">
  <h3>Geschiedenis / Events ({len(events)})</h3>
  {_render_events(events)}
</div>"""
    return _page(sns.name, "sensors", body)


@app.get("/sensors/{sensor_id}/edit", response_class=HTMLResponse)
def web_sensor_edit_form(sensor_id: str) -> str:
    sns = get_sensor(sensor_id)
    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/sensors/{escape(sns.id)}" class="btn btn-ghost btn-sm">← Terug</a>
</div>
<div class="card">
  <h2>✏ Sensor bewerken</h2>
  <form method="post" action="/web/sensors/{escape(sns.id)}/edit">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required value="{escape(sns.name)}"></div>
      <div><label>Sensortype *</label><input name="sensor_type" required value="{escape(sns.sensor_type)}"></div>
      <div><label>Status</label><select name="status">{_sensor_status_options(sns.status)}</select></div>
    </div>
    <div class="form-row cols-3">
      <div><label>Fabrikant</label><input name="manufacturer" value="{escape(sns.manufacturer)}"></div>
      <div><label>Model</label><input name="model" value="{escape(sns.model)}"></div>
      <div><label>Eenheid</label><input name="unit" value="{escape(sns.unit)}"></div>
    </div>
    <div class="flex gap-2">
      <button class="btn btn-primary" type="submit">💾 Opslaan</button>
      <a href="/sensors/{escape(sns.id)}" class="btn btn-ghost">Annuleren</a>
    </div>
  </form>
</div>"""
    return _page(f"Bewerken: {sns.name}", "sensors", body)


@app.post("/web/sensors/{sensor_id}/edit", response_class=RedirectResponse)
async def web_update_sensor(sensor_id: str, request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    sensor_type = _form_str(form, "sensor_type")
    if not name or not sensor_type:
        raise HTTPException(status_code=422, detail="Name and sensor_type are required")
    status_raw = _form_str(form, "status", "unknown")
    status = status_raw if status_raw in ("available", "in_use", "maintenance", "retired", "unknown") else "unknown"
    update_sensor(sensor_id, SensorUpdate(
        name=name, sensor_type=sensor_type, status=status,
        manufacturer=_form_str(form, "manufacturer"),
        model=_form_str(form, "model"),
        unit=_form_str(form, "unit"),
    ))
    return RedirectResponse(url=f"/sensors/{sensor_id}", status_code=303)


@app.post("/web/sensors/{sensor_id}/delete", response_class=RedirectResponse)
def web_delete_sensor(sensor_id: str) -> RedirectResponse:
    delete_sensor(sensor_id)
    return RedirectResponse(url="/sensors", status_code=303)


# =============================================================================
# WEB UI — CAMERAS (M3.3, mirrors the sensor pages; world model only)
# =============================================================================

def _camera_status_options(selected: str = "unknown") -> str:
    opts = ["available", "in_use", "maintenance", "retired", "unknown"]
    return "".join(f'<option value="{s}"{" selected" if s == selected else ""}>{s}</option>' for s in opts)


@app.get("/cameras", response_class=HTMLResponse)
def web_cameras_index() -> str:
    with connection() as db:
        rows = db.execute("SELECT * FROM cameras ORDER BY created_at DESC").fetchall()

    table_rows = ""
    for r in rows:
        prov = load(r["provenance"])
        table_rows += f"""<tr>
          <td><a href="/cameras/{escape(r['id'])}"><code>{escape(r['id'])}</code></a></td>
          <td><strong>{escape(r['name'])}</strong></td>
          <td class="text-muted">{escape(r['camera_type'] or '—')}</td>
          <td>{_status_badge(r['status'])}</td>
          <td>{_prov_badge(prov)}</td>
          <td class="text-sm text-muted">{r['created_at'][:10]}</td>
        </tr>"""

    empty = f'<tr><td colspan="6" class="empty">Nog geen camera\'s. Voeg er hieronder één toe.</td></tr>' if not rows else ""

    body = f"""
<div class="flex justify-between items-center mb-3">
  <div>
    <h1>📷 Cameras</h1>
    <p class="subtitle">Camera's in je wereldmodel ({len(rows)} totaal)</p>
  </div>
</div>
<div class="card mb-3">
  <h3>Nieuwe Camera</h3>
  <form method="post" action="/web/cameras">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required placeholder="bijv. Werkplaats USB-cam"></div>
      <div><label>Cameratype *</label><input name="camera_type" required placeholder="bijv. webcam"></div>
      <div><label>Status</label><select name="status">{_camera_status_options()}</select></div>
    </div>
    <div class="form-row cols-3">
      <div><label>Fabrikant</label><input name="manufacturer" placeholder="bijv. Logitech"></div>
      <div><label>Model</label><input name="model" placeholder="bijv. C920"></div>
      <div><label>Resolutie</label><input name="resolution" placeholder="bijv. 1920x1080"></div>
    </div>
    <button class="btn btn-primary" type="submit">+ Camera toevoegen</button>
  </form>
</div>
<div class="card">
  <table>
    <thead><tr><th>ID</th><th>Naam</th><th>Type</th><th>Status</th><th>Herkomst</th><th>Aangemaakt</th></tr></thead>
    <tbody>{table_rows}{empty}</tbody>
  </table>
</div>"""
    return _page("Cameras", "cameras", body)


@app.post("/web/cameras", response_class=RedirectResponse)
async def web_create_camera(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    camera_type = _form_str(form, "camera_type")
    if not name or not camera_type:
        raise HTTPException(status_code=422, detail="Name and camera_type are required")
    status_raw = _form_str(form, "status", "unknown")
    status = status_raw if status_raw in ("available", "in_use", "maintenance", "retired", "unknown") else "unknown"
    prov = Provenance(source_type="user-created", creator_id="web_ui", human_verified=True)
    created = create_camera(CameraCreate(name=name, camera_type=camera_type, status=status,
                                         manufacturer=_form_str(form, "manufacturer"),
                                         model=_form_str(form, "model"),
                                         resolution=_form_str(form, "resolution"),
                                         provenance=prov))
    return RedirectResponse(url=f"/cameras/{created.id}", status_code=303)


@app.get("/cameras/{camera_id}", response_class=HTMLResponse)
def web_camera_detail(camera_id: str) -> str:
    cam = get_camera(camera_id)
    rels = _get_relationships_for(camera_id)
    events = _get_events_for(camera_id)
    badge = _prov_badge(cam.provenance.model_dump())

    caps = ", ".join(cam.capabilities) if cam.capabilities else "—"
    ifaces = ", ".join(cam.interfaces) if cam.interfaces else "—"

    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/cameras" class="btn btn-ghost btn-sm">← Terug</a>
  <span class="text-muted text-sm">Camera detail</span>
</div>
<div class="card mb-2">
  <div class="flex justify-between items-center mb-2">
    <div>
      <h1>{escape(cam.name)}</h1>
      <code class="text-sm">{escape(cam.id)}</code>
    </div>
    <div class="flex gap-2">
      {_status_badge(cam.status)}
      <a href="/cameras/{escape(cam.id)}/edit" class="btn btn-ghost btn-sm">✏ Bewerken</a>
      <a href="/graph/{escape(cam.id)}" class="btn btn-ghost btn-sm">⛨ Graaf</a>
      <form method="post" action="/web/cameras/{escape(cam.id)}/delete"
            onsubmit="return confirm('Weet je zeker dat je «{escape(cam.name)}» wilt verwijderen? Deze actie wordt geregistreerd in de eventgeschiedenis.')">
        <button class="btn btn-danger btn-sm" type="submit">🗑 Verwijderen</button>
      </form>
    </div>
  </div>
  <p style="color:var(--text-muted);margin-bottom:1.5rem;">{escape(cam.description or 'Geen omschrijving.')}</p>
  <dl class="detail-grid">
    <dt>Type</dt><dd>{escape(cam.camera_type)}</dd>
    <dt>Fabrikant</dt><dd>{escape(cam.manufacturer or '—')}</dd>
    <dt>Model</dt><dd>{escape(cam.model or '—')}</dd>
    <dt>Resolutie</dt><dd>{escape(cam.resolution or '—')}</dd>
    <dt>Capabilities</dt><dd>{escape(caps)}</dd>
    <dt>Interfaces</dt><dd>{escape(ifaces)}</dd>
    <dt>Aangemaakt</dt><dd>{escape(cam.created_at[:19].replace("T", " "))}</dd>
    <dt>Bijgewerkt</dt><dd>{escape(cam.updated_at[:19].replace("T", " "))}</dd>
    <dt>Bron</dt><dd>{escape(cam.provenance.source_type)} {badge}</dd>
  </dl>
</div>
<div class="card mb-2">
  <h3>Relaties ({len(rels)})</h3>
  {_render_relationships(rels, camera_id)}
  <hr>
  <h3 class="mt-2">Relatie toevoegen</h3>
  <form method="post" action="/web/relationships" class="form-row cols-3">
    <input type="hidden" name="from_id" value="{escape(cam.id)}">
    <div><label>Predikaat</label><select name="predicate">{_predicate_options()}</select></div>
    <div><label>Naar entiteit (ID)</label><input name="to_id" placeholder="hw_... / obj_... / proj_..."></div>
    <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary" type="submit">+ Koppelen</button></div>
  </form>
</div>
<div class="card">
  <h3>Geschiedenis / Events ({len(events)})</h3>
  {_render_events(events)}
</div>"""
    return _page(cam.name, "cameras", body)


@app.get("/cameras/{camera_id}/edit", response_class=HTMLResponse)
def web_camera_edit_form(camera_id: str) -> str:
    cam = get_camera(camera_id)
    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/cameras/{escape(cam.id)}" class="btn btn-ghost btn-sm">← Terug</a>
</div>
<div class="card">
  <h2>✏ Camera bewerken</h2>
  <form method="post" action="/web/cameras/{escape(cam.id)}/edit">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required value="{escape(cam.name)}"></div>
      <div><label>Cameratype *</label><input name="camera_type" required value="{escape(cam.camera_type)}"></div>
      <div><label>Status</label><select name="status">{_camera_status_options(cam.status)}</select></div>
    </div>
    <div class="form-row cols-3">
      <div><label>Fabrikant</label><input name="manufacturer" value="{escape(cam.manufacturer)}"></div>
      <div><label>Model</label><input name="model" value="{escape(cam.model)}"></div>
      <div><label>Resolutie</label><input name="resolution" value="{escape(cam.resolution)}"></div>
    </div>
    <div class="flex gap-2">
      <button class="btn btn-primary" type="submit">💾 Opslaan</button>
      <a href="/cameras/{escape(cam.id)}" class="btn btn-ghost">Annuleren</a>
    </div>
  </form>
</div>"""
    return _page(f"Bewerken: {cam.name}", "cameras", body)


@app.post("/web/cameras/{camera_id}/edit", response_class=RedirectResponse)
async def web_update_camera(camera_id: str, request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    camera_type = _form_str(form, "camera_type")
    if not name or not camera_type:
        raise HTTPException(status_code=422, detail="Name and camera_type are required")
    status_raw = _form_str(form, "status", "unknown")
    status = status_raw if status_raw in ("available", "in_use", "maintenance", "retired", "unknown") else "unknown"
    update_camera(camera_id, CameraUpdate(
        name=name, camera_type=camera_type, status=status,
        manufacturer=_form_str(form, "manufacturer"),
        model=_form_str(form, "model"),
        resolution=_form_str(form, "resolution"),
    ))
    return RedirectResponse(url=f"/cameras/{camera_id}", status_code=303)


@app.post("/web/cameras/{camera_id}/delete", response_class=RedirectResponse)
def web_delete_camera(camera_id: str) -> RedirectResponse:
    delete_camera(camera_id)
    return RedirectResponse(url="/cameras", status_code=303)


# =============================================================================
# WEB UI — LOCATIONS (M3.4, mirrors the sensor pages; world model only)
# =============================================================================

def _location_status_options(selected: str = "unknown") -> str:
    opts = ["available", "in_use", "maintenance", "retired", "unknown"]
    return "".join(f'<option value="{s}"{" selected" if s == selected else ""}>{s}</option>' for s in opts)


@app.get("/locations", response_class=HTMLResponse)
def web_locations_index() -> str:
    with connection() as db:
        rows = db.execute("SELECT * FROM locations ORDER BY created_at DESC").fetchall()

    table_rows = ""
    for r in rows:
        prov = load(r["provenance"])
        table_rows += f"""<tr>
          <td><a href="/locations/{escape(r['id'])}"><code>{escape(r['id'])}</code></a></td>
          <td><strong>{escape(r['name'])}</strong></td>
          <td class="text-muted">{escape(r['location_type'] or '—')}</td>
          <td>{_status_badge(r['status'])}</td>
          <td>{_prov_badge(prov)}</td>
          <td class="text-sm text-muted">{r['created_at'][:10]}</td>
        </tr>"""

    empty = f'<tr><td colspan="6" class="empty">Nog geen locaties. Voeg er hieronder één toe.</td></tr>' if not rows else ""

    body = f"""
<div class="flex justify-between items-center mb-3">
  <div>
    <h1>📍 Locations</h1>
    <p class="subtitle">Fysieke plaatsen in je wereldmodel ({len(rows)} totaal)</p>
  </div>
</div>
<div class="card mb-3">
  <h3>Nieuwe Location</h3>
  <form method="post" action="/web/locations">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required placeholder="bijv. Werkplaats"></div>
      <div><label>Locatietype *</label><input name="location_type" required placeholder="bijv. kamer"></div>
      <div><label>Status</label><select name="status">{_location_status_options()}</select></div>
    </div>
    <div class="form-row">
      <div><label>Omschrijving</label><input name="description" placeholder="Korte omschrijving"></div>
    </div>
    <button class="btn btn-primary" type="submit">+ Location toevoegen</button>
  </form>
</div>
<div class="card">
  <table>
    <thead><tr><th>ID</th><th>Naam</th><th>Type</th><th>Status</th><th>Herkomst</th><th>Aangemaakt</th></tr></thead>
    <tbody>{table_rows}{empty}</tbody>
  </table>
</div>"""
    return _page("Locations", "locations", body)


@app.post("/web/locations", response_class=RedirectResponse)
async def web_create_location(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    location_type = _form_str(form, "location_type")
    if not name or not location_type:
        raise HTTPException(status_code=422, detail="Name and location_type are required")
    status_raw = _form_str(form, "status", "unknown")
    status = status_raw if status_raw in ("available", "in_use", "maintenance", "retired", "unknown") else "unknown"
    prov = Provenance(source_type="user-created", creator_id="web_ui", human_verified=True)
    created = create_location(LocationCreate(name=name, location_type=location_type,
                                             status=status,
                                             description=_form_str(form, "description"),
                                             provenance=prov))
    return RedirectResponse(url=f"/locations/{created.id}", status_code=303)


@app.get("/locations/{location_id}", response_class=HTMLResponse)
def web_location_detail(location_id: str) -> str:
    loc = get_location(location_id)
    rels = _get_relationships_for(location_id)
    events = _get_events_for(location_id)
    badge = _prov_badge(loc.provenance.model_dump())

    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/locations" class="btn btn-ghost btn-sm">← Terug</a>
  <span class="text-muted text-sm">Location detail</span>
</div>
<div class="card mb-2">
  <div class="flex justify-between items-center mb-2">
    <div>
      <h1>{escape(loc.name)}</h1>
      <code class="text-sm">{escape(loc.id)}</code>
    </div>
    <div class="flex gap-2">
      {_status_badge(loc.status)}
      <a href="/locations/{escape(loc.id)}/edit" class="btn btn-ghost btn-sm">✏ Bewerken</a>
      <a href="/graph/{escape(loc.id)}" class="btn btn-ghost btn-sm">⛨ Graaf</a>
      <form method="post" action="/web/locations/{escape(loc.id)}/delete"
            onsubmit="return confirm('Weet je zeker dat je «{escape(loc.name)}» wilt verwijderen? Deze actie wordt geregistreerd in de eventgeschiedenis.')">
        <button class="btn btn-danger btn-sm" type="submit">🗑 Verwijderen</button>
      </form>
    </div>
  </div>
  <p style="color:var(--text-muted);margin-bottom:1.5rem;">{escape(loc.description or 'Geen omschrijving.')}</p>
  <dl class="detail-grid">
    <dt>Type</dt><dd>{escape(loc.location_type)}</dd>
    <dt>Aangemaakt</dt><dd>{escape(loc.created_at[:19].replace("T", " "))}</dd>
    <dt>Bijgewerkt</dt><dd>{escape(loc.updated_at[:19].replace("T", " "))}</dd>
    <dt>Bron</dt><dd>{escape(loc.provenance.source_type)} {badge}</dd>
  </dl>
</div>
<div class="card mb-2">
  <h3>Relaties ({len(rels)})</h3>
  {_render_relationships(rels, location_id)}
  <hr>
  <h3 class="mt-2">Relatie toevoegen</h3>
  <form method="post" action="/web/relationships" class="form-row cols-3">
    <input type="hidden" name="from_id" value="{escape(loc.id)}">
    <div><label>Predikaat</label><select name="predicate">{_predicate_options()}</select></div>
    <div><label>Naar entiteit (ID)</label><input name="to_id" placeholder="loc_... / hw_... / obj_..."></div>
    <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary" type="submit">+ Koppelen</button></div>
  </form>
</div>
<div class="card">
  <h3>Geschiedenis / Events ({len(events)})</h3>
  {_render_events(events)}
</div>"""
    return _page(loc.name, "locations", body)


@app.get("/locations/{location_id}/edit", response_class=HTMLResponse)
def web_location_edit_form(location_id: str) -> str:
    loc = get_location(location_id)
    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/locations/{escape(loc.id)}" class="btn btn-ghost btn-sm">← Terug</a>
</div>
<div class="card">
  <h2>✏ Location bewerken</h2>
  <form method="post" action="/web/locations/{escape(loc.id)}/edit">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required value="{escape(loc.name)}"></div>
      <div><label>Locatietype *</label><input name="location_type" required value="{escape(loc.location_type)}"></div>
      <div><label>Status</label><select name="status">{_location_status_options(loc.status)}</select></div>
    </div>
    <div class="form-row">
      <div><label>Omschrijving</label><textarea name="description" rows="3">{escape(loc.description)}</textarea></div>
    </div>
    <div class="flex gap-2">
      <button class="btn btn-primary" type="submit">💾 Opslaan</button>
      <a href="/locations/{escape(loc.id)}" class="btn btn-ghost">Annuleren</a>
    </div>
  </form>
</div>"""
    return _page(f"Bewerken: {loc.name}", "locations", body)


@app.post("/web/locations/{location_id}/edit", response_class=RedirectResponse)
async def web_update_location(location_id: str, request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    location_type = _form_str(form, "location_type")
    if not name or not location_type:
        raise HTTPException(status_code=422, detail="Name and location_type are required")
    status_raw = _form_str(form, "status", "unknown")
    status = status_raw if status_raw in ("available", "in_use", "maintenance", "retired", "unknown") else "unknown"
    update_location(location_id, LocationUpdate(
        name=name, location_type=location_type, status=status,
        description=_form_str(form, "description"),
    ))
    return RedirectResponse(url=f"/locations/{location_id}", status_code=303)


@app.post("/web/locations/{location_id}/delete", response_class=RedirectResponse)
def web_delete_location(location_id: str) -> RedirectResponse:
    delete_location(location_id)
    return RedirectResponse(url="/locations", status_code=303)


# =============================================================================
# WEB UI — MODELS (M3.5, mirrors the camera pages; world model data only)
# =============================================================================

def _model_type_options(selected: str = "other") -> str:
    opts = ["llm", "vlm", "vision", "detection", "ocr", "speech_to_text",
            "embedding", "other"]
    return "".join(f'<option value="{s}"{" selected" if s == selected else ""}>{s}</option>' for s in opts)


def _model_status_options(selected: str = "unknown") -> str:
    opts = ["available", "in_use", "maintenance", "retired", "unknown"]
    return "".join(f'<option value="{s}"{" selected" if s == selected else ""}>{s}</option>' for s in opts)


@app.get("/models", response_class=HTMLResponse)
def web_models_index() -> str:
    with connection() as db:
        rows = db.execute("SELECT * FROM models ORDER BY created_at DESC").fetchall()

    table_rows = ""
    for r in rows:
        prov = load(r["provenance"])
        table_rows += f"""<tr>
          <td><a href="/models/{escape(r['id'])}"><code>{escape(r['id'])}</code></a></td>
          <td><strong>{escape(r['name'])}</strong></td>
          <td class="text-muted">{escape(r['model_type'] or '—')}</td>
          <td>{_status_badge(r['status'])}</td>
          <td>{_prov_badge(prov)}</td>
          <td class="text-sm text-muted">{r['created_at'][:10]}</td>
        </tr>"""

    empty = f'<tr><td colspan="6" class="empty">Nog geen modellen. Voeg er hieronder één toe.</td></tr>' if not rows else ""

    body = f"""
<div class="flex justify-between items-center mb-3">
  <div>
    <h1>🧠 Models</h1>
    <p class="subtitle">AI/ML-modellen in je wereldmodel ({len(rows)} totaal; beschrijvingen, geen runtime)</p>
  </div>
</div>
<div class="card mb-3">
  <h3>Nieuw Model</h3>
  <form method="post" action="/web/models">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required placeholder="bijv. Moondream 2"></div>
      <div><label>Modeltype *</label><select name="model_type">{_model_type_options("vlm")}</select></div>
      <div><label>Status</label><select name="status">{_model_status_options()}</select></div>
    </div>
    <div class="form-row cols-3">
      <div><label>Provider</label><input name="provider" placeholder="bijv. lokaal"></div>
      <div><label>Identifier</label><input name="model_identifier" placeholder="bijv. moondream2"></div>
      <div><label>Versie</label><input name="version" placeholder="bijv. 2026-09"></div>
    </div>
    <button class="btn btn-primary" type="submit">+ Model toevoegen</button>
  </form>
</div>
<div class="card">
  <table>
    <thead><tr><th>ID</th><th>Naam</th><th>Type</th><th>Status</th><th>Herkomst</th><th>Aangemaakt</th></tr></thead>
    <tbody>{table_rows}{empty}</tbody>
  </table>
</div>"""
    return _page("Models", "models", body)


@app.post("/web/models", response_class=RedirectResponse)
async def web_create_model(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    model_type_raw = _form_str(form, "model_type", "other")
    valid_types = ("llm", "vlm", "vision", "detection", "ocr", "speech_to_text",
                   "embedding", "other")
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    model_type = model_type_raw if model_type_raw in valid_types else "other"
    status_raw = _form_str(form, "status", "unknown")
    status = status_raw if status_raw in ("available", "in_use", "maintenance", "retired", "unknown") else "unknown"
    prov = Provenance(source_type="user-created", creator_id="web_ui", human_verified=True)
    created = create_model(ModelCreate(name=name, model_type=model_type, status=status,
                                       provider=_form_str(form, "provider"),
                                       model_identifier=_form_str(form, "model_identifier"),
                                       version=_form_str(form, "version"),
                                       provenance=prov))
    return RedirectResponse(url=f"/models/{created.id}", status_code=303)


@app.get("/models/{model_id}", response_class=HTMLResponse)
def web_model_detail(model_id: str) -> str:
    mod = get_model(model_id)
    rels = _get_relationships_for(model_id)
    events = _get_events_for(model_id)
    badge = _prov_badge(mod.provenance.model_dump())

    caps = ", ".join(mod.capabilities) if mod.capabilities else "—"
    ifaces = ", ".join(mod.interfaces) if mod.interfaces else "—"

    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/models" class="btn btn-ghost btn-sm">← Terug</a>
  <span class="text-muted text-sm">Model detail (beschrijving, geen runtime)</span>
</div>
<div class="card mb-2">
  <div class="flex justify-between items-center mb-2">
    <div>
      <h1>{escape(mod.name)}</h1>
      <code class="text-sm">{escape(mod.id)}</code>
    </div>
    <div class="flex gap-2">
      {_status_badge(mod.status)}
      <a href="/models/{escape(mod.id)}/edit" class="btn btn-ghost btn-sm">✏ Bewerken</a>
      <a href="/graph/{escape(mod.id)}" class="btn btn-ghost btn-sm">⛨ Graaf</a>
      <form method="post" action="/web/models/{escape(mod.id)}/delete"
            onsubmit="return confirm('Weet je zeker dat je «{escape(mod.name)}» wilt verwijderen? Deze actie wordt geregistreerd in de eventgeschiedenis.')">
        <button class="btn btn-danger btn-sm" type="submit">🗑 Verwijderen</button>
      </form>
    </div>
  </div>
  <p style="color:var(--text-muted);margin-bottom:1.5rem;">{escape(mod.description or 'Geen omschrijving.')}</p>
  <dl class="detail-grid">
    <dt>Type</dt><dd>{escape(mod.model_type)}</dd>
    <dt>Provider</dt><dd>{escape(mod.provider or '—')}</dd>
    <dt>Identifier</dt><dd>{escape(mod.model_identifier or '—')}</dd>
    <dt>Versie</dt><dd>{escape(mod.version or '—')}</dd>
    <dt>Capabilities</dt><dd>{escape(caps)}</dd>
    <dt>Interfaces</dt><dd>{escape(ifaces)}</dd>
    <dt>Aangemaakt</dt><dd>{escape(mod.created_at[:19].replace("T", " "))}</dd>
    <dt>Bijgewerkt</dt><dd>{escape(mod.updated_at[:19].replace("T", " "))}</dd>
    <dt>Bron</dt><dd>{escape(mod.provenance.source_type)} {badge}</dd>
  </dl>
</div>
<div class="card mb-2">
  <h3>Relaties ({len(rels)})</h3>
  {_render_relationships(rels, model_id)}
  <hr>
  <h3 class="mt-2">Relatie toevoegen</h3>
  <form method="post" action="/web/relationships" class="form-row cols-3">
    <input type="hidden" name="from_id" value="{escape(mod.id)}">
    <div><label>Predikaat</label><select name="predicate">{_predicate_options()}</select></div>
    <div><label>Naar entiteit (ID)</label><input name="to_id" placeholder="hw_... / obj_... / proj_..."></div>
    <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary" type="submit">+ Koppelen</button></div>
  </form>
</div>
<div class="card">
  <h3>Geschiedenis / Events ({len(events)})</h3>
  {_render_events(events)}
</div>"""
    return _page(mod.name, "models", body)


@app.get("/models/{model_id}/edit", response_class=HTMLResponse)
def web_model_edit_form(model_id: str) -> str:
    mod = get_model(model_id)
    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/models/{escape(mod.id)}" class="btn btn-ghost btn-sm">← Terug</a>
</div>
<div class="card">
  <h2>✏ Model bewerken</h2>
  <form method="post" action="/web/models/{escape(mod.id)}/edit">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required value="{escape(mod.name)}"></div>
      <div><label>Modeltype</label><select name="model_type">{_model_type_options(mod.model_type)}</select></div>
      <div><label>Status</label><select name="status">{_model_status_options(mod.status)}</select></div>
    </div>
    <div class="form-row cols-3">
      <div><label>Provider</label><input name="provider" value="{escape(mod.provider)}"></div>
      <div><label>Identifier</label><input name="model_identifier" value="{escape(mod.model_identifier)}"></div>
      <div><label>Versie</label><input name="version" value="{escape(mod.version)}"></div>
    </div>
    <div class="flex gap-2">
      <button class="btn btn-primary" type="submit">💾 Opslaan</button>
      <a href="/models/{escape(mod.id)}" class="btn btn-ghost">Annuleren</a>
    </div>
  </form>
</div>"""
    return _page(f"Bewerken: {mod.name}", "models", body)


@app.post("/web/models/{model_id}/edit", response_class=RedirectResponse)
async def web_update_model(model_id: str, request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    model_type_raw = _form_str(form, "model_type", "other")
    valid_types = ("llm", "vlm", "vision", "detection", "ocr", "speech_to_text",
                   "embedding", "other")
    model_type = model_type_raw if model_type_raw in valid_types else "other"
    status_raw = _form_str(form, "status", "unknown")
    status = status_raw if status_raw in ("available", "in_use", "maintenance", "retired", "unknown") else "unknown"
    update_model(model_id, ModelUpdate(
        name=name, model_type=model_type, status=status,
        provider=_form_str(form, "provider"),
        model_identifier=_form_str(form, "model_identifier"),
        version=_form_str(form, "version"),
    ))
    return RedirectResponse(url=f"/models/{model_id}", status_code=303)


@app.post("/web/models/{model_id}/delete", response_class=RedirectResponse)
def web_delete_model(model_id: str) -> RedirectResponse:
    delete_model(model_id)
    return RedirectResponse(url="/models", status_code=303)


# =============================================================================
# WEB UI — TASKS (M3.6, mirrors the model pages; describes work, never executes)
# =============================================================================

def _task_type_options(selected: str = "other") -> str:
    opts = ["observe", "identify", "measure", "classify", "inspect", "transform",
            "analyze", "monitor", "other"]
    return "".join(f'<option value="{s}"{" selected" if s == selected else ""}>{s}</option>' for s in opts)


def _task_status_options(selected: str = "pending") -> str:
    opts = ["pending", "ready", "running", "completed", "failed", "cancelled"]
    return "".join(f'<option value="{s}"{" selected" if s == selected else ""}>{s}</option>' for s in opts)


@app.get("/tasks", response_class=HTMLResponse)
def web_tasks_index() -> str:
    with connection() as db:
        rows = db.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()

    table_rows = ""
    for r in rows:
        prov = load(r["provenance"])
        table_rows += f"""<tr>
          <td><a href="/tasks/{escape(r['id'])}"><code>{escape(r['id'])}</code></a></td>
          <td><strong>{escape(r['name'])}</strong></td>
          <td class="text-muted">{escape(r['task_type'] or '—')}</td>
          <td>{_status_badge(r['status'])}</td>
          <td>{_prov_badge(prov)}</td>
          <td class="text-sm text-muted">{r['created_at'][:10]}</td>
        </tr>"""

    empty = f'<tr><td colspan="6" class="empty">Nog geen taken. Voeg er hieronder één toe.</td></tr>' if not rows else ""

    body = f"""
<div class="flex justify-between items-center mb-3">
  <div>
    <h1>✅ Tasks</h1>
    <p class="subtitle">Taken in je wereldmodel ({len(rows)} totaal; beschrijvingen, geen uitvoering)</p>
  </div>
</div>
<div class="card mb-3">
  <h3>Nieuwe Task</h3>
  <form method="post" action="/web/tasks">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required placeholder="bijv. Werkplaats inspecteren"></div>
      <div><label>Taaktype</label><select name="task_type">{_task_type_options("inspect")}</select></div>
      <div><label>Status</label><select name="status">{_task_status_options()}</select></div>
    </div>
    <div class="form-row cols-2">
      <div><label>Omschrijving</label><input name="description" placeholder="Korte omschrijving"></div>
      <div><label>Verwacht resultaat</label><input name="expected_output" placeholder="bijv. fotoreeks"></div>
    </div>
    <button class="btn btn-primary" type="submit">+ Task toevoegen</button>
  </form>
</div>
<div class="card">
  <table>
    <thead><tr><th>ID</th><th>Naam</th><th>Type</th><th>Status</th><th>Herkomst</th><th>Aangemaakt</th></tr></thead>
    <tbody>{table_rows}{empty}</tbody>
  </table>
</div>"""
    return _page("Tasks", "tasks", body)


@app.post("/web/tasks", response_class=RedirectResponse)
async def web_create_task(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    task_type_raw = _form_str(form, "task_type", "other")
    valid_types = ("observe", "identify", "measure", "classify", "inspect",
                   "transform", "analyze", "monitor", "other")
    task_type = task_type_raw if task_type_raw in valid_types else "other"
    status_raw = _form_str(form, "status", "pending")
    status = status_raw if status_raw in ("pending", "ready", "running", "completed",
                                          "failed", "cancelled") else "pending"
    prov = Provenance(source_type="user-created", creator_id="web_ui", human_verified=True)
    created = create_task(TaskCreate(name=name, task_type=task_type, status=status,
                                     description=_form_str(form, "description"),
                                     expected_output=_form_str(form, "expected_output"),
                                     provenance=prov))
    return RedirectResponse(url=f"/tasks/{created.id}", status_code=303)


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
def web_task_detail(task_id: str) -> str:
    task = get_task(task_id)
    rels = _get_relationships_for(task_id)
    events = _get_events_for(task_id)
    badge = _prov_badge(task.provenance.model_dump())

    requirements = ", ".join(task.input_requirements) if task.input_requirements else "—"

    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/tasks" class="btn btn-ghost btn-sm">← Terug</a>
  <span class="text-muted text-sm">Task detail (beschrijving, geen uitvoering)</span>
</div>
<div class="card mb-2">
  <div class="flex justify-between items-center mb-2">
    <div>
      <h1>{escape(task.name)}</h1>
      <code class="text-sm">{escape(task.id)}</code>
    </div>
    <div class="flex gap-2">
      {_status_badge(task.status)}
      <a href="/tasks/{escape(task.id)}/edit" class="btn btn-ghost btn-sm">✏ Bewerken</a>
      <a href="/graph/{escape(task.id)}" class="btn btn-ghost btn-sm">⛨ Graaf</a>
      <form method="post" action="/web/tasks/{escape(task.id)}/delete"
            onsubmit="return confirm('Weet je zeker dat je «{escape(task.name)}» wilt verwijderen? Deze actie wordt geregistreerd in de eventgeschiedenis.')">
        <button class="btn btn-danger btn-sm" type="submit">🗑 Verwijderen</button>
      </form>
    </div>
  </div>
  <p style="color:var(--text-muted);margin-bottom:1.5rem;">{escape(task.description or 'Geen omschrijving.')}</p>
  <dl class="detail-grid">
    <dt>Type</dt><dd>{escape(task.task_type)}</dd>
    <dt>Prioriteit</dt><dd>{task.priority}</dd>
    <dt>Inputvereisten</dt><dd>{escape(requirements)}</dd>
    <dt>Verwacht resultaat</dt><dd>{escape(task.expected_output or '—')}</dd>
    <dt>Aangemaakt</dt><dd>{escape(task.created_at[:19].replace("T", " "))}</dd>
    <dt>Bijgewerkt</dt><dd>{escape(task.updated_at[:19].replace("T", " "))}</dd>
    <dt>Bron</dt><dd>{escape(task.provenance.source_type)} {badge}</dd>
  </dl>
</div>
<div class="card mb-2">
  <h3>Relaties ({len(rels)})</h3>
  {_render_relationships(rels, task_id)}
  <hr>
  <h3 class="mt-2">Relatie toevoegen</h3>
  <form method="post" action="/web/relationships" class="form-row cols-3">
    <input type="hidden" name="from_id" value="{escape(task.id)}">
    <div><label>Predikaat</label><select name="predicate">{_predicate_options()}</select></div>
    <div><label>Naar entiteit (ID)</label><input name="to_id" placeholder="mod_... / hw_... / obj_..."></div>
    <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary" type="submit">+ Koppelen</button></div>
  </form>
</div>
<div class="card">
  <h3>Geschiedenis / Events ({len(events)})</h3>
  {_render_events(events)}
</div>"""
    return _page(task.name, "tasks", body)


@app.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def web_task_edit_form(task_id: str) -> str:
    task = get_task(task_id)
    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/tasks/{escape(task.id)}" class="btn btn-ghost btn-sm">← Terug</a>
</div>
<div class="card">
  <h2>✏ Task bewerken</h2>
  <form method="post" action="/web/tasks/{escape(task.id)}/edit">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required value="{escape(task.name)}"></div>
      <div><label>Taaktype</label><select name="task_type">{_task_type_options(task.task_type)}</select></div>
      <div><label>Status</label><select name="status">{_task_status_options(task.status)}</select></div>
    </div>
    <div class="form-row cols-2">
      <div><label>Omschrijving</label><textarea name="description" rows="3">{escape(task.description)}</textarea></div>
      <div><label>Verwacht resultaat</label><input name="expected_output" value="{escape(task.expected_output)}"></div>
    </div>
    <div class="flex gap-2">
      <button class="btn btn-primary" type="submit">💾 Opslaan</button>
      <a href="/tasks/{escape(task.id)}" class="btn btn-ghost">Annuleren</a>
    </div>
  </form>
</div>"""
    return _page(f"Bewerken: {task.name}", "tasks", body)


@app.post("/web/tasks/{task_id}/edit", response_class=RedirectResponse)
async def web_update_task(task_id: str, request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    task_type_raw = _form_str(form, "task_type", "other")
    valid_types = ("observe", "identify", "measure", "classify", "inspect",
                   "transform", "analyze", "monitor", "other")
    task_type = task_type_raw if task_type_raw in valid_types else "other"
    status_raw = _form_str(form, "status", "pending")
    status = status_raw if status_raw in ("pending", "ready", "running", "completed",
                                          "failed", "cancelled") else "pending"
    update_task(task_id, TaskUpdate(
        name=name, task_type=task_type, status=status,
        description=_form_str(form, "description"),
        expected_output=_form_str(form, "expected_output"),
    ))
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@app.post("/web/tasks/{task_id}/delete", response_class=RedirectResponse)
def web_delete_task(task_id: str) -> RedirectResponse:
    delete_task(task_id)
    return RedirectResponse(url="/tasks", status_code=303)


# =============================================================================
# WEB UI — ACTUATORS (M3.7, mirrors the task pages; world model data only)
# =============================================================================

def _actuator_type_options(selected: str = "other") -> str:
    opts = ["motor", "relay", "led", "servo", "pump", "valve", "heater", "fan",
            "display", "speaker", "robotic", "other"]
    return "".join(f'<option value="{s}"{" selected" if s == selected else ""}>{s}</option>' for s in opts)


def _actuator_status_options(selected: str = "unknown") -> str:
    opts = ["available", "in_use", "maintenance", "retired", "unknown"]
    return "".join(f'<option value="{s}"{" selected" if s == selected else ""}>{s}</option>' for s in opts)


@app.get("/actuators", response_class=HTMLResponse)
def web_actuators_index() -> str:
    with connection() as db:
        rows = db.execute("SELECT * FROM actuators ORDER BY created_at DESC").fetchall()

    table_rows = ""
    for r in rows:
        prov = load(r["provenance"])
        table_rows += f"""<tr>
          <td><a href="/actuators/{escape(r['id'])}"><code>{escape(r['id'])}</code></a></td>
          <td><strong>{escape(r['name'])}</strong></td>
          <td class="text-muted">{escape(r['actuator_type'] or '—')}</td>
          <td>{_status_badge(r['status'])}</td>
          <td>{_prov_badge(prov)}</td>
          <td class="text-sm text-muted">{r['created_at'][:10]}</td>
        </tr>"""

    empty = f'<tr><td colspan="6" class="empty">Nog geen actuatoren. Voeg er hieronder één toe.</td></tr>' if not rows else ""

    body = f"""
<div class="flex justify-between items-center mb-3">
  <div>
    <h1>🦾 Actuators</h1>
    <p class="subtitle">Mogelijke uitvoerders in je wereldmodel ({len(rows)} totaal)</p>
    <p class="text-sm text-muted">Een Actuator is een beschrijving van mogelijke fysieke uitvoering. M3.7 voert geen hardware-acties uit.</p>
  </div>
</div>
<div class="card mb-3">
  <h3>Nieuwe Actuator</h3>
  <form method="post" action="/web/actuators">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required placeholder="bijv. Ventilator Werkplaats"></div>
      <div><label>Actuatortype</label><select name="actuator_type">{_actuator_type_options("fan")}</select></div>
      <div><label>Status</label><select name="status">{_actuator_status_options()}</select></div>
    </div>
    <div class="form-row cols-3">
      <div><label>Fabrikant</label><input name="manufacturer" placeholder="bijv. Noctua"></div>
      <div><label>Model</label><input name="model" placeholder="bijv. NF-A12"></div>
      <div><label>Omschrijving</label><input name="description" placeholder="Korte omschrijving"></div>
    </div>
    <button class="btn btn-primary" type="submit">+ Actuator toevoegen</button>
  </form>
</div>
<div class="card">
  <table>
    <thead><tr><th>ID</th><th>Naam</th><th>Type</th><th>Status</th><th>Herkomst</th><th>Aangemaakt</th></tr></thead>
    <tbody>{table_rows}{empty}</tbody>
  </table>
</div>"""
    return _page("Actuators", "actuators", body)


@app.post("/web/actuators", response_class=RedirectResponse)
async def web_create_actuator(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    actuator_type_raw = _form_str(form, "actuator_type", "other")
    valid_types = ("motor", "relay", "led", "servo", "pump", "valve", "heater",
                   "fan", "display", "speaker", "robotic", "other")
    actuator_type = actuator_type_raw if actuator_type_raw in valid_types else "other"
    status_raw = _form_str(form, "status", "unknown")
    status = status_raw if status_raw in ("available", "in_use", "maintenance", "retired", "unknown") else "unknown"
    prov = Provenance(source_type="user-created", creator_id="web_ui", human_verified=True)
    created = create_actuator(ActuatorCreate(name=name, actuator_type=actuator_type,
                                             status=status,
                                             manufacturer=_form_str(form, "manufacturer"),
                                             model=_form_str(form, "model"),
                                             description=_form_str(form, "description"),
                                             provenance=prov))
    return RedirectResponse(url=f"/actuators/{created.id}", status_code=303)


@app.get("/actuators/{actuator_id}", response_class=HTMLResponse)
def web_actuator_detail(actuator_id: str) -> str:
    act = get_actuator(actuator_id)
    rels = _get_relationships_for(actuator_id)
    events = _get_events_for(actuator_id)
    badge = _prov_badge(act.provenance.model_dump())

    caps = ", ".join(act.capabilities) if act.capabilities else "—"
    ifaces = ", ".join(act.interfaces) if act.interfaces else "—"

    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/actuators" class="btn btn-ghost btn-sm">← Terug</a>
  <span class="text-muted text-sm">Actuator detail (beschrijving, geen uitvoering)</span>
</div>
<div class="card mb-2">
  <div class="flex justify-between items-center mb-2">
    <div>
      <h1>{escape(act.name)}</h1>
      <code class="text-sm">{escape(act.id)}</code>
    </div>
    <div class="flex gap-2">
      {_status_badge(act.status)}
      <a href="/actuators/{escape(act.id)}/edit" class="btn btn-ghost btn-sm">✏ Bewerken</a>
      <a href="/graph/{escape(act.id)}" class="btn btn-ghost btn-sm">⛨ Graaf</a>
      <form method="post" action="/web/actuators/{escape(act.id)}/delete"
            onsubmit="return confirm('Weet je zeker dat je «{escape(act.name)}» wilt verwijderen? Deze actie wordt geregistreerd in de eventgeschiedenis.')">
        <button class="btn btn-danger btn-sm" type="submit">🗑 Verwijderen</button>
      </form>
    </div>
  </div>
  <p style="color:var(--text-muted);margin-bottom:1.5rem;">{escape(act.description or 'Geen omschrijving.')}</p>
  <p class="text-sm text-muted mb-2">Een Actuator is een beschrijving van mogelijke fysieke uitvoering. M3.7 voert geen hardware-acties uit.</p>
  <dl class="detail-grid">
    <dt>Type</dt><dd>{escape(act.actuator_type)}</dd>
    <dt>Fabrikant</dt><dd>{escape(act.manufacturer or '—')}</dd>
    <dt>Model</dt><dd>{escape(act.model or '—')}</dd>
    <dt>Capabilities</dt><dd>{escape(caps)}</dd>
    <dt>Interfaces</dt><dd>{escape(ifaces)}</dd>
    <dt>Aangemaakt</dt><dd>{escape(act.created_at[:19].replace("T", " "))}</dd>
    <dt>Bijgewerkt</dt><dd>{escape(act.updated_at[:19].replace("T", " "))}</dd>
    <dt>Bron</dt><dd>{escape(act.provenance.source_type)} {badge}</dd>
  </dl>
</div>
<div class="card mb-2">
  <h3>Relaties ({len(rels)})</h3>
  {_render_relationships(rels, actuator_id)}
  <hr>
  <h3 class="mt-2">Relatie toevoegen</h3>
  <form method="post" action="/web/relationships" class="form-row cols-3">
    <input type="hidden" name="from_id" value="{escape(act.id)}">
    <div><label>Predikaat</label><select name="predicate">{_predicate_options()}</select></div>
    <div><label>Naar entiteit (ID)</label><input name="to_id" placeholder="hw_... / loc_... / obj_..."></div>
    <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary" type="submit">+ Koppelen</button></div>
  </form>
</div>
<div class="card">
  <h3>Geschiedenis / Events ({len(events)})</h3>
  {_render_events(events)}
</div>"""
    return _page(act.name, "actuators", body)


@app.get("/actuators/{actuator_id}/edit", response_class=HTMLResponse)
def web_actuator_edit_form(actuator_id: str) -> str:
    act = get_actuator(actuator_id)
    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/actuators/{escape(act.id)}" class="btn btn-ghost btn-sm">← Terug</a>
</div>
<div class="card">
  <h2>✏ Actuator bewerken</h2>
  <form method="post" action="/web/actuators/{escape(act.id)}/edit">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required value="{escape(act.name)}"></div>
      <div><label>Actuatortype</label><select name="actuator_type">{_actuator_type_options(act.actuator_type)}</select></div>
      <div><label>Status</label><select name="status">{_actuator_status_options(act.status)}</select></div>
    </div>
    <div class="form-row cols-2">
      <div><label>Fabrikant</label><input name="manufacturer" value="{escape(act.manufacturer)}"></div>
      <div><label>Model</label><input name="model" value="{escape(act.model)}"></div>
    </div>
    <div class="flex gap-2">
      <button class="btn btn-primary" type="submit">💾 Opslaan</button>
      <a href="/actuators/{escape(act.id)}" class="btn btn-ghost">Annuleren</a>
    </div>
  </form>
</div>"""
    return _page(f"Bewerken: {act.name}", "actuators", body)


@app.post("/web/actuators/{actuator_id}/edit", response_class=RedirectResponse)
async def web_update_actuator(actuator_id: str, request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    actuator_type_raw = _form_str(form, "actuator_type", "other")
    valid_types = ("motor", "relay", "led", "servo", "pump", "valve", "heater",
                   "fan", "display", "speaker", "robotic", "other")
    actuator_type = actuator_type_raw if actuator_type_raw in valid_types else "other"
    status_raw = _form_str(form, "status", "unknown")
    status = status_raw if status_raw in ("available", "in_use", "maintenance", "retired", "unknown") else "unknown"
    update_actuator(actuator_id, ActuatorUpdate(
        name=name, actuator_type=actuator_type, status=status,
        manufacturer=_form_str(form, "manufacturer"),
        model=_form_str(form, "model"),
    ))
    return RedirectResponse(url=f"/actuators/{actuator_id}", status_code=303)


@app.post("/web/actuators/{actuator_id}/delete", response_class=RedirectResponse)
def web_delete_actuator(actuator_id: str) -> RedirectResponse:
    delete_actuator(actuator_id)
    return RedirectResponse(url="/actuators", status_code=303)


# =============================================================================
# WEB UI — FILES (M7.5, mirrors the task pages; record only, never touches files)
# =============================================================================

def _file_kind_options(selected: str = "other") -> str:
    opts = ["cad", "mesh", "gcode", "image", "document", "data", "other"]
    return "".join(f'<option value="{s}"{" selected" if s == selected else ""}>{s}</option>' for s in opts)


def _file_status_options(selected: str = "unknown") -> str:
    opts = ["available", "in_use", "maintenance", "retired", "unknown"]
    return "".join(f'<option value="{s}"{" selected" if s == selected else ""}>{s}</option>' for s in opts)


@app.get("/files", response_class=HTMLResponse)
def web_files_index() -> str:
    with connection() as db:
        rows = db.execute("SELECT * FROM files ORDER BY created_at DESC").fetchall()

    table_rows = ""
    for r in rows:
        prov = load(r["provenance"])
        table_rows += f"""<tr>
          <td><a href="/files/{escape(r['id'])}"><code>{escape(r['id'])}</code></a></td>
          <td><strong>{escape(r['name'])}</strong></td>
          <td class="text-muted">{escape(r['file_kind'] or '—')}</td>
          <td>{_status_badge(r['status'])}</td>
          <td>{_prov_badge(prov)}</td>
          <td class="text-sm text-muted">{r['created_at'][:10]}</td>
        </tr>"""

    empty = f'<tr><td colspan="6" class="empty">Nog geen files. Voeg er hieronder één toe.</td></tr>' if not rows else ""

    body = f"""
<div class="flex justify-between items-center mb-3">
  <div>
    <h1>📁 Files</h1>
    <p class="subtitle">Bestandsrecords in je wereldmodel ({len(rows)} totaal)</p>
    <p class="text-sm text-muted">File-record only — M7.5 leest of wijzigt het daadwerkelijke bestand niet.</p>
  </div>
</div>
<div class="card mb-3">
  <h3>Nieuw File-record</h3>
  <form method="post" action="/web/files">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required placeholder="bijv. behuizing-v3.stl"></div>
      <div><label>File-kind</label><select name="file_kind">{_file_kind_options("mesh")}</select></div>
      <div><label>Status</label><select name="status">{_file_status_options()}</select></div>
    </div>
    <div class="form-row cols-3">
      <div><label>SHA-256 *</label><input name="sha256" required placeholder="64 hex-tekens"></div>
      <div><label>MIME-type</label><input name="mime_type" placeholder="bijv. model/stl"></div>
      <div><label>Grootte (bytes)</label><input name="size_bytes" type="number" value="0" min="0"></div>
    </div>
    <button class="btn btn-primary" type="submit">+ File-record toevoegen</button>
  </form>
</div>
<div class="card">
  <table>
    <thead><tr><th>ID</th><th>Naam</th><th>Kind</th><th>Status</th><th>Herkomst</th><th>Aangemaakt</th></tr></thead>
    <tbody>{table_rows}{empty}</tbody>
  </table>
</div>"""
    return _page("Files", "files", body)


@app.post("/web/files", response_class=RedirectResponse)
async def web_create_file(request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    sha256 = _form_str(form, "sha256")
    if not name or not sha256:
        raise HTTPException(status_code=422, detail="Name and sha256 are required")
    file_kind_raw = _form_str(form, "file_kind", "other")
    valid_kinds = ("cad", "mesh", "gcode", "image", "document", "data", "other")
    file_kind = file_kind_raw if file_kind_raw in valid_kinds else "other"
    status_raw = _form_str(form, "status", "unknown")
    status = status_raw if status_raw in ("available", "in_use", "maintenance", "retired", "unknown") else "unknown"
    try:
        size_bytes = max(0, _form_int(form, "size_bytes"))
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="size_bytes must be a non-negative integer")
    prov = Provenance(source_type="user-created", creator_id="web_ui", human_verified=True)
    try:
        created = create_file(FileCreate(name=name, file_kind=file_kind, sha256=sha256,
                                         mime_type=_form_str(form, "mime_type"),
                                         size_bytes=size_bytes, provenance=prov))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return RedirectResponse(url=f"/files/{created.id}", status_code=303)


@app.get("/files/{file_id}", response_class=HTMLResponse)
def web_file_detail(file_id: str) -> str:
    record = get_file(file_id)
    rels = _get_relationships_for(file_id)
    events = _get_events_for(file_id)
    badge = _prov_badge(record.provenance.model_dump())

    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/files" class="btn btn-ghost btn-sm">← Terug</a>
  <span class="text-muted text-sm">File detail (record only, geen bestandstoegang)</span>
</div>
<div class="card mb-2">
  <div class="flex justify-between items-center mb-2">
    <div>
      <h1>{escape(record.name)}</h1>
      <code class="text-sm">{escape(record.id)}</code>
    </div>
    <div class="flex gap-2">
      {_status_badge(record.status)}
      <a href="/files/{escape(record.id)}/edit" class="btn btn-ghost btn-sm">✏ Bewerken</a>
      <a href="/graph/{escape(record.id)}" class="btn btn-ghost btn-sm">⛨ Graaf</a>
      <form method="post" action="/web/files/{escape(record.id)}/delete"
            onsubmit="return confirm('Weet je zeker dat je «{escape(record.name)}» wilt verwijderen? Alleen het record wordt verwijderd, nooit een bestand. Deze actie wordt geregistreerd in de eventgeschiedenis.')">
        <button class="btn btn-danger btn-sm" type="submit">🗑 Verwijderen</button>
      </form>
    </div>
  </div>
  <p style="color:var(--text-muted);margin-bottom:1.5rem;">{escape(record.description or 'Geen omschrijving.')}</p>
  <p class="text-sm text-muted mb-2">File-record only — M7.5 leest of wijzigt het daadwerkelijke bestand niet.</p>
  <dl class="detail-grid">
    <dt>Kind</dt><dd>{escape(record.file_kind)}</dd>
    <dt>MIME-type</dt><dd>{escape(record.mime_type or '—')}</dd>
    <dt>SHA-256</dt><dd><code class="text-sm">{escape(record.sha256)}</code></dd>
    <dt>Grootte</dt><dd>{record.size_bytes} bytes</dd>
    <dt>Aangemaakt</dt><dd>{escape(record.created_at[:19].replace("T", " "))}</dd>
    <dt>Bijgewerkt</dt><dd>{escape(record.updated_at[:19].replace("T", " "))}</dd>
    <dt>Bron</dt><dd>{escape(record.provenance.source_type)} {badge}</dd>
  </dl>
</div>
<div class="card mb-2">
  <h3>Relaties ({len(rels)})</h3>
  {_render_relationships(rels, file_id)}
  <hr>
  <h3 class="mt-2">Relatie toevoegen</h3>
  <form method="post" action="/web/relationships" class="form-row cols-3">
    <input type="hidden" name="from_id" value="{escape(record.id)}">
    <div><label>Predikaat</label><select name="predicate">{_predicate_options()}</select></div>
    <div><label>Naar entiteit (ID)</label><input name="to_id" placeholder="obj_... / mod_... / hw_..."></div>
    <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary" type="submit">+ Koppelen</button></div>
  </form>
</div>
<div class="card">
  <h3>Geschiedenis / Events ({len(events)})</h3>
  {_render_events(events)}
</div>"""
    return _page(record.name, "files", body)


@app.get("/files/{file_id}/edit", response_class=HTMLResponse)
def web_file_edit_form(file_id: str) -> str:
    record = get_file(file_id)
    body = f"""
<div class="flex gap-2 items-center mb-3">
  <a href="/files/{escape(record.id)}" class="btn btn-ghost btn-sm">← Terug</a>
</div>
<div class="card">
  <h2>✏ File-record bewerken</h2>
  <form method="post" action="/web/files/{escape(record.id)}/edit">
    <div class="form-row cols-3">
      <div><label>Naam *</label><input name="name" required value="{escape(record.name)}"></div>
      <div><label>File-kind</label><select name="file_kind">{_file_kind_options(record.file_kind)}</select></div>
      <div><label>Status</label><select name="status">{_file_status_options(record.status)}</select></div>
    </div>
    <div class="form-row cols-3">
      <div><label>SHA-256 *</label><input name="sha256" required value="{escape(record.sha256)}"></div>
      <div><label>MIME-type</label><input name="mime_type" value="{escape(record.mime_type)}"></div>
      <div><label>Grootte (bytes)</label><input name="size_bytes" type="number" value="{record.size_bytes}" min="0"></div>
    </div>
    <div class="flex gap-2">
      <button class="btn btn-primary" type="submit">💾 Opslaan</button>
      <a href="/files/{escape(record.id)}" class="btn btn-ghost">Annuleren</a>
    </div>
  </form>
</div>"""
    return _page(f"Bewerken: {record.name}", "files", body)


@app.post("/web/files/{file_id}/edit", response_class=RedirectResponse)
async def web_update_file(file_id: str, request: Request) -> RedirectResponse:
    form = _parse_form(await request.body())
    name = _form_str(form, "name")
    sha256 = _form_str(form, "sha256")
    if not name or not sha256:
        raise HTTPException(status_code=422, detail="Name and sha256 are required")
    file_kind_raw = _form_str(form, "file_kind", "other")
    valid_kinds = ("cad", "mesh", "gcode", "image", "document", "data", "other")
    file_kind = file_kind_raw if file_kind_raw in valid_kinds else "other"
    status_raw = _form_str(form, "status", "unknown")
    status = status_raw if status_raw in ("available", "in_use", "maintenance", "retired", "unknown") else "unknown"
    try:
        size_bytes = max(0, _form_int(form, "size_bytes"))
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="size_bytes must be a non-negative integer")
    try:
        update_file(file_id, FileUpdate(
            name=name, file_kind=file_kind, sha256=sha256,
            mime_type=_form_str(form, "mime_type"), size_bytes=size_bytes,
            status=status,
        ))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return RedirectResponse(url=f"/files/{file_id}", status_code=303)


@app.post("/web/files/{file_id}/delete", response_class=RedirectResponse)
def web_delete_file(file_id: str) -> RedirectResponse:
    delete_file(file_id)
    return RedirectResponse(url="/files", status_code=303)
