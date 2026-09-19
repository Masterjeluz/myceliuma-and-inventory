"""Human hardware links (BIG #42).

Explicit human-controlled verification for node/device claims.

Trust levels (see nodes.hardware_trust):
- ADVERTISED: the node said so (default, never a fact).
- OBSERVED: connected + fresh telemetry (<300s). Derived automatically.
- VERIFIED: ONLY via a row in this store with status VERIFIED,
  created by PROPOSE (anyone) + VERIFY (operator key only).

No automatic promotion exists: new_link() always creates PROPOSED,
verify_link() requires a non-empty human verified_by AND is only
called from routes that already checked the operator key. Nodes can
never self-verify with their own token. Revocation is operator-only
and sticks (a REVOKED link never counts as verified again).

Audit trail: every propose/verify/revoke emits a closed bus event
(hardware.linked / hardware.verified / hardware.revoked) naming the
human, node, device and evidence — never secrets.

Storage: chat DB table hardware_links (additive, idempotent).
"""

from __future__ import annotations

import re as _re
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

LINK_STATUSES = ("PROPOSED", "VERIFIED", "REVOKED")

_LINK_ID_RE = _re.compile(r"^hv_[0-9a-f]{8,32}$")


class HardwareLinkRefusedError(ValueError):
    """Local validation refused; nothing was stored."""


class HardwareLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_id: str = Field(min_length=4, max_length=80)
    human_ref: str = Field(min_length=1, max_length=120)
    node_id: str = Field(min_length=1, max_length=80)
    device_ref: str = Field(min_length=1, max_length=120)
    device_kind: str = Field(default="", max_length=60)
    capability: str = Field(default="", max_length=120)
    evidence: str = Field(default="", max_length=2000)
    status: str = Field(default="PROPOSED", max_length=16)
    verified_by: str = Field(default="", max_length=120)
    verified_at: str = Field(default="", max_length=40)
    created_at: str = ""
    updated_at: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_link_id() -> str:
    return f"hv_{int(time.time() * 1000):x}{secrets.token_hex(4)}"


def init_hardware_tables(db) -> None:
    """Additive, idempotent table setup (agenda-pattern)."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS hardware_links (
            link_id TEXT PRIMARY KEY,
            human_ref TEXT NOT NULL DEFAULT '',
            node_id TEXT NOT NULL DEFAULT '',
            device_ref TEXT NOT NULL DEFAULT '',
            device_kind TEXT NOT NULL DEFAULT '',
            capability TEXT NOT NULL DEFAULT '',
            evidence TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'PROPOSED',
            verified_by TEXT NOT NULL DEFAULT '',
            verified_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            provenance TEXT NOT NULL DEFAULT '{}'
        );
        """)
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_hw_links_node
            ON hardware_links(node_id, status);
        """)


def _ensure(db) -> None:
    init_hardware_tables(db)


def _check_id(value: str, name: str, limit: int = 120) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise HardwareLinkRefusedError(f"{name} is required")
    if len(cleaned) > limit:
        raise HardwareLinkRefusedError(f"{name} is too long")
    if _re.search(r"[\x00-\x1f\x7f]", cleaned):
        raise HardwareLinkRefusedError(f"{name} has control chars")
    return cleaned


def new_link(*, human_ref: str, node_id: str, device_ref: str,
             device_kind: str = "", capability: str = "",
             evidence: str = "", provenance: dict | None = None) -> HardwareLink:
    """Propose a human link. ALWAYS starts as PROPOSED — there is no
    parameter that can create a VERIFIED link directly."""
    from .nodes import check_node_id
    try:
        node = check_node_id(node_id)
    except ValueError as error:
        raise HardwareLinkRefusedError(str(error)) from error
    human = _check_id(human_ref, "human_ref")
    device = _check_id(device_ref, "device_ref")
    kind = str(device_kind or "").strip()[:60]
    cap = str(capability or "").strip()[:120]
    ev = str(evidence or "").strip()[:2000]
    stamp = now()
    prov = dict(provenance) if isinstance(provenance, dict) else {}
    prov.update({"source_type": "human-link-proposed",
                 "creator_id": human, "human_verified": False})
    return HardwareLink(
        link_id=generate_link_id(), human_ref=human, node_id=node,
        device_ref=device, device_kind=kind, capability=cap,
        evidence=ev, status="PROPOSED", verified_by="",
        verified_at="", created_at=stamp, updated_at=stamp,
        provenance=prov)


def save_link(link: HardwareLink) -> None:
    from .database import chat_connection, dump, init_chat_database
    init_chat_database()
    with chat_connection() as db:
        _ensure(db)
        db.execute(
            """INSERT INTO hardware_links
            (link_id, human_ref, node_id, device_ref, device_kind,
             capability, evidence, status, verified_by, verified_at,
             created_at, updated_at, provenance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(link_id) DO UPDATE SET
             evidence=excluded.evidence, status=excluded.status,
             verified_by=excluded.verified_by,
             verified_at=excluded.verified_at,
             updated_at=excluded.updated_at,
             provenance=excluded.provenance""",
            (link.link_id, link.human_ref, link.node_id,
             link.device_ref, link.device_kind, link.capability,
             link.evidence, link.status, link.verified_by,
             link.verified_at, link.created_at, link.updated_at,
             dump(link.provenance)))


def _row_to_link(row) -> HardwareLink:
    from .database import load
    try:
        prov = load(row["provenance"])
    except Exception:
        prov = {}
    if not isinstance(prov, dict):
        prov = {}
    return HardwareLink(
        link_id=row["link_id"], human_ref=row["human_ref"],
        node_id=row["node_id"], device_ref=row["device_ref"],
        device_kind=row["device_kind"] or "",
        capability=row["capability"] or "",
        evidence=row["evidence"] or "",
        status=row["status"] or "PROPOSED",
        verified_by=row["verified_by"] or "",
        verified_at=row["verified_at"] or "",
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
        provenance=prov)


def get_link(link_id: str) -> HardwareLink | None:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    cleaned = str(link_id or "").strip()[:80]
    if not cleaned:
        return None
    with chat_connection() as db:
        _ensure(db)
        row = db.execute(
            "SELECT * FROM hardware_links WHERE link_id=?",
            (cleaned,)).fetchone()
    if row is None:
        return None
    return _row_to_link(row)


def list_links(*, node_id: str = "", status: str = "",
               limit: int = 100) -> list[HardwareLink]:
    from .database import chat_connection, init_chat_database
    init_chat_database()
    count = max(1, min(int(limit or 100), 200))
    query = "SELECT * FROM hardware_links"
    args: list = []
    clauses: list = []
    if node_id:
        clauses.append("node_id=?")
        args.append(str(node_id)[:80])
    if status:
        if status not in LINK_STATUSES:
            raise HardwareLinkRefusedError(
                f"Unknown link status '{status}'")
        clauses.append("status=?")
        args.append(status)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY updated_at DESC LIMIT ?"
    args.append(count)
    with chat_connection() as db:
        _ensure(db)
        rows = db.execute(query, tuple(args)).fetchall()
    return [_row_to_link(row) for row in rows]


def verify_link(link_id: str, *, verified_by: str) -> HardwareLink | None:
    """Mark a PROPOSED link VERIFIED. Caller MUST have checked the
    operator key first — this function enforces the human + state
    gates (non-empty verifier, PROPOSED only, never REVOKED)."""
    verifier = _check_id(verified_by, "verified_by")
    link = get_link(link_id)
    if link is None:
        return None
    if link.status == "VERIFIED":
        return link
    if link.status != "PROPOSED":
        raise HardwareLinkRefusedError(
            f"Link {link_id} is {link.status}; only PROPOSED links "
            "can be verified")
    link.status = "VERIFIED"
    link.verified_by = verifier
    link.verified_at = now()
    link.updated_at = link.verified_at
    prov = dict(link.provenance or {})
    prov.update({"source_type": "human-verified",
                 "human_verified": True,
                 "verified_by": verifier})
    link.provenance = prov
    save_link(link)
    _audit("hardware.verified",
           f"Hardware link {link.link_id} verified by {verifier}",
           node_id=link.node_id,
           payload={"link_id": link.link_id,
                    "device_ref": link.device_ref,
                    "verified_by": verifier})
    return link


def revoke_link(link_id: str, *, revoked_by: str,
                reason: str = "") -> HardwareLink | None:
    """Revoke a link. REVOKED sticks: verify_link() refuses to
    re-verify a revoked link."""
    actor = _check_id(revoked_by, "revoked_by")
    link = get_link(link_id)
    if link is None:
        return None
    link.status = "REVOKED"
    link.updated_at = now()
    prov = dict(link.provenance or {})
    prov.update({"human_verified": False,
                 "revoked_by": actor,
                 "revoke_reason": str(reason or "")[:500]})
    link.provenance = prov
    save_link(link)
    _audit("hardware.revoked",
           f"Hardware link {link.link_id} revoked by {actor}",
           node_id=link.node_id,
           payload={"link_id": link.link_id,
                    "revoked_by": actor})
    return link


def audit_propose(link: HardwareLink) -> None:
    _audit("hardware.linked",
           f"Hardware link {link.link_id} proposed by "
           f"{link.human_ref} for {link.node_id}/{link.device_ref}",
           node_id=link.node_id,
           payload={"link_id": link.link_id,
                    "device_ref": link.device_ref,
                    "human_ref": link.human_ref})


def verified_device_refs(node_id: str) -> set[str]:
    """Device refs with a live VERIFIED link for this node."""
    try:
        links = list_links(node_id=str(node_id or "")[:80],
                           status="VERIFIED", limit=200)
    except Exception:
        return set()
    return {link.device_ref for link in links
            if link.status == "VERIFIED"}


def trust_for(node_id: str, device_ref: str) -> tuple[str, str]:
    """Human-link trust overlay: VERIFIED iff a live VERIFIED link
    names this exact node + device ref. Pure read, never derives."""
    ref = str(device_ref or "").strip()
    if not ref:
        return ("ADVERTISED", "no device reference")
    if ref in verified_device_refs(node_id):
        return ("VERIFIED", "explicit human link (operator-verified)")
    return ("", "")


def _audit(event_type: str, summary: str, *,
           node_id: str = "", payload: dict | None = None) -> None:
    try:
        from .events import new_event, save_event
        save_event(new_event(event_type, summary, node_id=node_id,
                             payload=payload or {}))
    except Exception:
        pass
