"""Drone abstraction (BIG #11-15, Phase 5).

Capabilities, safety state, missions and observations as
data — no real drone SDK, no autonomous flight without an
explicit safety architecture. Autonomous flight additionally
needs a named geofence, an altitude cap and human approval;
anything less refuses.

Same honesty rule as robots: proposal/approval/telemetry/
verification exist; physical flight is HARDWARE_REQUIRED.
"""

import secrets
import time

from pydantic import BaseModel, Field

from .inventory_read import Provenance

DRONE_CAPABILITIES = (
    "drone.observe",
    "drone.photograph",
    "drone.video",
    "drone.navigate",
    "drone.position",
    "drone.return_home",
    "drone.land",
)

DRONE_STATUSES = (
    "grounded",
    "ready",
    "airborne",
    "returning",
    "maintenance",
)

DRONE_SAFETY = (
    "safe",
    "supervised",
    "locked",
    "grounded_lock",
    "unknown",
)


class DroneRefusedError(ValueError):
    """Fail-closed drone validation."""


def now() -> str:
    import datetime
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def generate_drone_id() -> str:
    return f"drn_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def generate_mission_id() -> str:
    return f"dmis_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


class Drone(BaseModel):
    drone_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    capabilities: list[str] = Field(default_factory=list,
                                    max_length=20)
    status: str = Field(default="grounded", max_length=20)
    safety_state: str = Field(default="safe", max_length=20)
    home_location: str = Field(default="", max_length=200)
    provenance: Provenance
    updated_at: str = Field(default="", max_length=80)


class DroneMission(BaseModel):
    mission_id: str = Field(min_length=3, max_length=80)
    drone_id: str = Field(min_length=1, max_length=80)
    kind: str = Field(min_length=1, max_length=40)
    params: dict = Field(default_factory=dict)
    autonomous: bool = False
    geofence: str = Field(default="", max_length=200)
    max_altitude_m: float = Field(default=0.0, ge=0, le=120)
    status: str = Field(default="proposed", max_length=20)
    approved_by: str = Field(default="", max_length=80)
    created_at: str = Field(default="", max_length=80)


def new_drone(name: str, *,
              capabilities: list | None = None,
              home_location: str = "",
              provenance: Provenance | None = None) -> Drone:
    if not isinstance(name, str) or not name.strip():
        raise DroneRefusedError("drone needs a name")
    caps = []
    for cap in (capabilities or []):
        if cap not in DRONE_CAPABILITIES:
            raise DroneRefusedError(
                f"Unknown drone capability '{cap}'")
        caps.append(cap)
    return Drone(
        drone_id=generate_drone_id(), name=name.strip()[:200],
        capabilities=caps, status="grounded",
        safety_state="safe",
        home_location=str(home_location or "")[:200],
        provenance=provenance or Provenance(
            source_type="user-created", creator_id="drones",
            human_verified=True),
        updated_at=now())


def _row_to_drone(row) -> Drone:
    from .database import load
    return Drone(
        drone_id=row["drone_id"], name=row["name"],
        capabilities=load(row["capabilities"]),
        status=row["status"],
        safety_state=row["safety_state"],
        home_location=row["home_location"],
        provenance=Provenance(**load(row["provenance"])),
        updated_at=row["updated_at"])


def save_drone(drone: Drone) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO drones
        (drone_id, name, capabilities, status, safety_state,
         home_location, provenance, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(drone_id) DO UPDATE SET
         status=excluded.status,
         safety_state=excluded.safety_state,
         updated_at=excluded.updated_at""",
                     (drone.drone_id, drone.name,
                      dump(drone.capabilities), drone.status,
                      drone.safety_state, drone.home_location,
                      dump(drone.provenance.model_dump(
                          mode="json")), drone.updated_at))


def get_drone(drone_id: str) -> Drone | None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM drones WHERE drone_id=?",
                         (drone_id,)).fetchone()
    return _row_to_drone(row) if row is not None else None


def list_drones() -> list[Drone]:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute("SELECT * FROM drones ORDER BY "
                          "updated_at DESC LIMIT 100").fetchall()
    return [_row_to_drone(row) for row in rows]


def propose_mission(drone_id: str, kind: str, params: dict, *,
                    autonomous: bool = False,
                    geofence: str = "",
                    max_altitude_m: float = 0.0) -> DroneMission:
    """Mission proposal. Autonomous flight needs geofence +
    altitude cap now; human approval still required later."""
    drone = get_drone(drone_id)
    if drone is None:
        raise DroneRefusedError("drone not found")
    capability = f"drone.{kind}" if not kind.startswith(
        "drone.") else kind
    if capability not in DRONE_CAPABILITIES:
        raise DroneRefusedError(
            f"Unknown drone mission kind '{kind}'")
    if capability not in drone.capabilities:
        raise DroneRefusedError(
            f"drone lacks capability '{capability}'")
    if not isinstance(params, dict) or len(params) > 10:
        raise DroneRefusedError("params must be a small object")
    if autonomous and (not str(geofence or "").strip() or not
                       float(max_altitude_m or 0) > 0):
        raise DroneRefusedError(
            "autonomous flight needs a named geofence and a "
            "positive altitude cap")
    return DroneMission(
        mission_id=generate_mission_id(), drone_id=drone_id,
        kind=capability, params=dict(params),
        autonomous=bool(autonomous),
        geofence=str(geofence or "")[:200],
        max_altitude_m=float(max_altitude_m or 0.0),
        status="proposed", created_at=now())


def approve_mission(mission: DroneMission,
                    approved_by: str) -> DroneMission:
    if not str(approved_by or "").strip():
        raise DroneRefusedError(
            "drone missions need a human approver")
    drone = get_drone(mission.drone_id)
    if drone is None:
        raise DroneRefusedError("drone not found")
    if drone.safety_state not in ("safe", "supervised"):
        raise DroneRefusedError(
            f"mission refused: safety state is "
            f"'{drone.safety_state}'")
    return mission.model_copy(update={
        "status": "approved",
        "approved_by": approved_by.strip()[:80]})
