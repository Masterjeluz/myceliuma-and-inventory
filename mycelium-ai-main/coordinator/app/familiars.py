"""Familiars: one capability model for every helper
(BIG #11-15, Phase 5).

A familiar is a physical or digital helper — desktop agent,
phone, robot, drone, camera, workshop machine, future AR
device. One model prevents every device from becoming its
own AI system: identity + kind + allow-listed capabilities
+ link to the backing entity.
"""

import secrets
import time

from pydantic import BaseModel, Field

from .inventory_read import Provenance

FAMILIAR_KINDS = (
    "desktop_agent",
    "phone",
    "robot",
    "drone",
    "camera",
    "machine",
    "ar_device",
    "digital",
)

# Per-kind capability allow-lists. Closed; no wildcards.
FAMILIAR_CAPABILITIES = {
    "desktop_agent": ("desktop.observe", "desktop.act"),
    "phone": ("phone.camera", "phone.mic", "phone.notify"),
    "robot": ("robot.observe", "robot.status"),
    "drone": ("drone.observe", "drone.position"),
    "camera": ("camera.snapshot", "camera.observe"),
    "machine": ("machine.status", "machine.telemetry"),
    "ar_device": ("ar.overlay", "ar.observe"),
    "digital": ("task.read", "memory.read"),
}

FAMILIAR_STATUSES = ("idle", "busy", "offline")


class FamiliarRefusedError(ValueError):
    """Fail-closed familiar validation."""


def now() -> str:
    import datetime
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def generate_familiar_id() -> str:
    return f"fam_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


class Familiar(BaseModel):
    familiar_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=20)
    capabilities: list[str] = Field(default_factory=list,
                                    max_length=20)
    linked_id: str = Field(default="", max_length=120)
    status: str = Field(default="idle", max_length=20)
    provenance: Provenance
    updated_at: str = Field(default="", max_length=80)


def capabilities_for(kind: str) -> tuple:
    if kind not in FAMILIAR_KINDS:
        raise FamiliarRefusedError(
            f"Unknown familiar kind '{kind}'")
    return FAMILIAR_CAPABILITIES[kind]


def new_familiar(name: str, kind: str, *,
                 linked_id: str = "",
                 provenance: Provenance | None = None
                 ) -> Familiar:
    if not isinstance(name, str) or not name.strip():
        raise FamiliarRefusedError("familiar needs a name")
    caps = capabilities_for(kind)
    return Familiar(
        familiar_id=generate_familiar_id(),
        name=name.strip()[:200], kind=kind,
        capabilities=list(caps),
        linked_id=str(linked_id or "")[:120], status="idle",
        provenance=provenance or Provenance(
            source_type="user-created",
            creator_id="familiars", human_verified=False),
        updated_at=now())


def _row_to_familiar(row) -> Familiar:
    from .database import load
    return Familiar(
        familiar_id=row["familiar_id"], name=row["name"],
        kind=row["kind"],
        capabilities=load(row["capabilities"]),
        linked_id=row["linked_id"], status=row["status"],
        provenance=Provenance(**load(row["provenance"])),
        updated_at=row["updated_at"])


def save_familiar(familiar: Familiar) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        db.execute("""INSERT INTO familiars
        (familiar_id, name, kind, capabilities, linked_id,
         status, provenance, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(familiar_id) DO UPDATE SET
         status=excluded.status,
         updated_at=excluded.updated_at""",
                     (familiar.familiar_id, familiar.name,
                      familiar.kind,
                      dump(familiar.capabilities),
                      familiar.linked_id, familiar.status,
                      dump(familiar.provenance.model_dump(
                          mode="json")),
                      familiar.updated_at))


def get_familiar(familiar_id: str) -> Familiar | None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        row = db.execute("SELECT * FROM familiars WHERE "
                         "familiar_id=?",
                         (familiar_id,)).fetchone()
    return _row_to_familiar(row) if row is not None else None


def list_familiars() -> list[Familiar]:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        rows = db.execute("SELECT * FROM familiars ORDER BY "
                          "updated_at DESC LIMIT 100").fetchall()
    return [_row_to_familiar(row) for row in rows]


def familiar_can(familiar: Familiar, capability: str) -> bool:
    """Capability check against the kind allow-list and the
    stored set. No wildcards on either side."""
    if not isinstance(capability, str) or "*" in capability:
        return False
    allowed = set(capabilities_for(familiar.kind))
    return capability in allowed and capability in set(
        familiar.capabilities or [])
