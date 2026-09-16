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
            human_verified=False),
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


def build_drone_proposal(drone_id: str, kind: str,
                         params: dict, actor: str, *,
                         autonomous: bool = False,
                         geofence: str = "",
                         max_altitude_m: float = 0.0):
    """Intent → inert WriteProposal (mutation type
    drone.mission). Same exact-YES/fingerprint/staleness
    machinery as every other mutation. Autonomous flight
    needs geofence + altitude cap at propose time; human
    approval still required later."""
    from .controlled_writes import propose_write
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
    if not isinstance(actor, str) or not actor.strip():
        raise DroneRefusedError("proposal needs an actor")
    try:
        altitude = float(max_altitude_m or 0.0)
    except (TypeError, ValueError):
        raise DroneRefusedError(
            "max_altitude_m must be numeric")
    if not 0.0 <= altitude <= 120.0:
        raise DroneRefusedError(
            "max_altitude_m must be 0..120")
    if autonomous and (not str(geofence or "").strip()
                       or not altitude > 0):
        raise DroneRefusedError(
            "autonomous flight needs a named geofence and a "
            "positive altitude cap")
    return propose_write(
        generate_mission_id(), "drone.mission",
        f"drone:{drone_id}",
        {"kind": capability, "params": dict(params),
         "autonomous": bool(autonomous),
         "geofence": str(geofence or "")[:200],
         "max_altitude_m": altitude,
         "safety_state": drone.safety_state,
         "capabilities": sorted(drone.capabilities)},
        actor=actor.strip()[:80])


def check_drone_state_for_approval(drone_id: str,
                                   proposal) -> Drone:
    """Pre-approval recheck against live state (not the
    client body): target binding, capability still owned,
    safety still safe|supervised."""
    drone = get_drone(drone_id)
    if drone is None:
        raise DroneRefusedError("drone not found")
    payload = proposal.payload or {}
    if proposal.target != f"drone:{drone_id}":
        raise DroneRefusedError(
            "proposal target does not bind to this drone")
    kind = str(payload.get("kind", ""))
    if kind not in drone.capabilities:
        raise DroneRefusedError(
            f"drone no longer holds capability '{kind}'")
    if drone.safety_state not in ("safe", "supervised"):
        raise DroneRefusedError(
            f"mission refused: safety state is "
            f"'{drone.safety_state}'")
    return drone
