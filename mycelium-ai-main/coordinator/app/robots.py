"""Robot domain (BIG #11-15, Phase 5).

Robots are allow-listed capability holders with an explicit
safety state. The flow is intent → plan → simulation note →
proposal → approval → task → lease → execute → telemetry →
observation → verification, but this module implements the
data half: proposal, approval record, telemetry validation
and independent verification. Physical execution itself is
HARDWARE_REQUIRED and never simulated as real.

Safety: physical actions (move/grab/place/navigate) need
safety_state safe|supervised AND a human approval. locked/
estop refuse everything physical. No wildcards, ever.
"""

import secrets
import time

from pydantic import BaseModel, Field

from .inventory_read import Provenance

ROBOT_TYPES = (
    "robotic_arm",
    "mobile_rover",
    "stationary",
    "other",
)

ROBOT_CAPABILITIES = (
    "robot.move",
    "robot.observe",
    "robot.grab",
    "robot.place",
    "robot.speak",
    "robot.navigate",
    "robot.stop",
    "robot.status",
)

PHYSICAL_ACTIONS = (
    "robot.move",
    "robot.grab",
    "robot.place",
    "robot.navigate",
)

SAFETY_STATES = (
    "safe",
    "supervised",
    "locked",
    "estop",
    "unknown",
)

ROBOT_STATUSES = (
    "idle",
    "busy",
    "offline",
    "maintenance",
)


class RobotRefusedError(ValueError):
    """Fail-closed robot validation."""


def now() -> str:
    import datetime
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def generate_robot_id() -> str:
    return f"rbt_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def generate_action_id() -> str:
    return f"ract_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


class Robot(BaseModel):
    robot_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    robot_type: str = Field(default="other", max_length=20)
    capabilities: list[str] = Field(default_factory=list,
                                    max_length=20)
    location: str = Field(default="", max_length=200)
    status: str = Field(default="idle", max_length=20)
    safety_state: str = Field(default="safe", max_length=20)
    node_id: str = Field(default="", max_length=80)
    sensors: list[str] = Field(default_factory=list,
                               max_length=20)
    actuators: list[str] = Field(default_factory=list,
                                 max_length=20)
    provenance: Provenance
    updated_at: str = Field(default="", max_length=80)


class RobotActionProposal(BaseModel):
    action_id: str = Field(min_length=3, max_length=80)
    robot_id: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=40)
    params: dict = Field(default_factory=dict)
    physical: bool = False
    safety_state: str = Field(default="safe", max_length=20)
    simulation_note: str = Field(default="", max_length=500)
    status: str = Field(default="proposed", max_length=20)
    approved_by: str = Field(default="", max_length=80)
    created_at: str = Field(default="", max_length=80)


class RobotTelemetry(BaseModel):
    action_id: str = Field(min_length=1, max_length=80)
    robot_id: str = Field(min_length=1, max_length=80)
    status: str = Field(min_length=1, max_length=40)
    detail: str = Field(default="", max_length=500)
    observed_at: str = Field(default="", max_length=80)


def new_robot(name: str, *, robot_type: str = "other",
              capabilities: list | None = None,
              location: str = "", node_id: str = "",
              sensors: list | None = None,
              actuators: list | None = None,
              provenance: Provenance | None = None) -> Robot:
    if not isinstance(name, str) or not name.strip():
        raise RobotRefusedError("robot needs a name")
    if robot_type not in ROBOT_TYPES:
        raise RobotRefusedError(
            f"Unknown robot type '{robot_type}'")
    caps = []
    for cap in (capabilities or []):
        if cap not in ROBOT_CAPABILITIES:
            raise RobotRefusedError(
                f"Unknown robot capability '{cap}'; no "
                "wildcards, no custom capabilities")
        caps.append(cap)
    return Robot(
        robot_id=generate_robot_id(), name=name.strip()[:200],
        robot_type=robot_type, capabilities=caps,
        location=str(location or "")[:200],
        status="idle", safety_state="safe",
        node_id=str(node_id or "")[:80],
        sensors=[str(item)[:80]
                 for item in (sensors or [])][:20],
        actuators=[str(item)[:80]
                   for item in (actuators or [])][:20],
        provenance=provenance or Provenance(
            source_type="user-created", creator_id="robots",
            human_verified=True),
        updated_at=now())


def _row_to_robot(row) -> Robot:
    from .database import load
    return Robot(
        robot_id=row["robot_id"], name=row["name"],
        robot_type=row["robot_type"],
        capabilities=load(row["capabilities"]),
        location=row["location"], status=row["status"],
        safety_state=row["safety_state"],
        node_id=row["node_id"],
        sensors=[], actuators=[],
        provenance=Provenance(**load(row["provenance"])),
        updated_at=row["updated_at"])


def save_robot(robot: Robot) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO robots
        (robot_id, name, robot_type, capabilities, location,
         status, safety_state, node_id, provenance,
         updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(robot_id) DO UPDATE SET
         location=excluded.location, status=excluded.status,
         safety_state=excluded.safety_state,
         node_id=excluded.node_id,
         updated_at=excluded.updated_at""",
                     (robot.robot_id, robot.name,
                      robot.robot_type,
                      dump(robot.capabilities), robot.location,
                      robot.status, robot.safety_state,
                      robot.node_id,
                      dump(robot.provenance.model_dump(
                          mode="json")), robot.updated_at))


def get_robot(robot_id: str) -> Robot | None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM robots WHERE robot_id=?",
                         (robot_id,)).fetchone()
    return _row_to_robot(row) if row is not None else None


def list_robots() -> list[Robot]:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute("SELECT * FROM robots ORDER BY "
                          "updated_at DESC LIMIT 100").fetchall()
    return [_row_to_robot(row) for row in rows]


def set_safety(robot_id: str, safety_state: str) -> Robot:
    if safety_state not in SAFETY_STATES:
        raise RobotRefusedError(
            f"Unknown safety state '{safety_state}'")
    robot = get_robot(robot_id)
    if robot is None:
        raise RobotRefusedError("robot not found")
    updated = robot.model_copy(update={
        "safety_state": safety_state, "updated_at": now()})
    save_robot(updated)
    return updated


def propose_action(robot_id: str, action: str, params: dict,
                   *, simulation_note: str = "") -> RobotActionProposal:
    """Intent → proposal. Physical actions are flagged and
    need approval + safe|supervised state at approve time."""
    robot = get_robot(robot_id)
    if robot is None:
        raise RobotRefusedError("robot not found")
    if action not in ROBOT_CAPABILITIES:
        raise RobotRefusedError(
            f"Unknown robot action '{action}'")
    if action not in robot.capabilities:
        raise RobotRefusedError(
            f"robot lacks capability '{action}'")
    if not isinstance(params, dict) or len(params) > 10:
        raise RobotRefusedError("params must be a small object")
    return RobotActionProposal(
        action_id=generate_action_id(), robot_id=robot_id,
        action=action, params=dict(params),
        physical=action in PHYSICAL_ACTIONS,
        safety_state=robot.safety_state,
        simulation_note=str(simulation_note or "")[:500],
        status="proposed", created_at=now())


def approve_action(proposal: RobotActionProposal,
                   approved_by: str) -> RobotActionProposal:
    """Human approval. Physical actions refuse unless the
    robot is safe|supervised right now."""
    if not str(approved_by or "").strip():
        raise RobotRefusedError(
            "robot actions need a human approver")
    robot = get_robot(proposal.robot_id)
    if robot is None:
        raise RobotRefusedError("robot not found")
    if proposal.physical and robot.safety_state not in (
            "safe", "supervised"):
        raise RobotRefusedError(
            f"physical action refused: safety state is "
            f"'{robot.safety_state}'")
    if robot.status not in ("idle",):
        raise RobotRefusedError(
            f"robot is '{robot.status}'; only idle robots "
            "take new actions")
    save_robot(robot.model_copy(update={
        "status": "busy", "updated_at": now()}))
    return proposal.model_copy(update={
        "status": "approved",
        "approved_by": approved_by.strip()[:80]})


def record_telemetry(action_id: str, robot_id: str,
                     status: str, detail: str = ""
                     ) -> RobotTelemetry:
    """Validated telemetry envelope. Data in, no execution."""
    if not isinstance(status, str) or not status.strip() or \
            len(status) > 40:
        raise RobotRefusedError("telemetry needs a status")
    return RobotTelemetry(
        action_id=action_id, robot_id=robot_id,
        status=status.strip()[:40],
        detail=str(detail or "")[:500], observed_at=now())


def verify_action(telemetry: RobotTelemetry,
                  observation: str) -> dict:
    """Independent verification: telemetry alone never
    verifies; an observation note is required."""
    if not str(observation or "").strip():
        raise RobotRefusedError(
            "verification needs an independent observation; "
            "telemetry never verifies alone")
    robot = get_robot(telemetry.robot_id)
    if robot is not None:
        save_robot(robot.model_copy(update={
            "status": "idle", "updated_at": now()}))
    verdict = "verified" if telemetry.status in (
        "completed", "success", "done") else "not_verified"
    return {"action_id": telemetry.action_id,
            "verdict": verdict,
            "method": "telemetry status + independent "
                      "observation",
            "observation": str(observation)[:500]}
