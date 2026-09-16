"""INVENTory controlled-write capability (BIG #5).

The ONLY write path from Mycelium to INVENTory. The read bridge
(``inventory_read.py``) stays untouched and read-only; this module
is a separate, explicitly approved capability.

Supported mutations (closed — anything else is refused):

- ``inventory.create`` — POST one of object/project/idea/file
- ``inventory.update`` — PATCH one existing object/project/idea/file
- ``inventory.create_relationship`` — POST one relationship

Deletes, events and every M3+ entity type beyond the curated
ones are out of scope and refused: the writer only covers the
entity shapes whose API/database semantics were verified
against ``inventory/app/main.py`` + ``schemas.py`` (files added
in BIG #6 for camera-media registration: FileCreate needs a
name, a file_kind, a sha256 and a size).

Safety properties (enforced by construction, tested):

- HTTP POST/PATCH only, to an allow-listed route derived from the
  validated mutation — never from free text.
- Loopback-only base URL, timeout clamped to 5s, redirects never
  followed (same posture as the read bridge).
- Every execution needs a bound, non-stale WriteApproval over the
  exact proposal content (``controlled_writes.revalidate``).
- Payloads are schema-validated here AND by INVENTory itself;
  unknown fields, bad enums and ``human_verified=True`` from AI
  output are refused before anything is sent.
- ``before``/``after`` snapshots come from independent reads so
  the audit trail shows what was, what was proposed and what
  actually changed.
"""

import os
from typing import Any

import httpx

from .controlled_writes import (
    WriteApproval,
    WriteProposal,
    WriteResult,
    now,
    revalidate,
)
from .inventory_read import (
    ENTITY_ID_PREFIXES,
    LOOPBACK_HOSTS,
    MAX_TIMEOUT_SECONDS,
    InventoryReader,
    Provenance,
)

BASE_URL_ENV_VAR = "INVENTORY_BASE_URL"
DEFAULT_BASE_URL = "http://127.0.0.1:8080"

#: Entity types with verified create/update semantics. Maps the
#: proposal entity_type to (collection, id prefix, creatable fields,
#: updatable fields). ``name`` is required on create everywhere.
ENTITY_CONTRACTS: dict[str, dict[str, Any]] = {
    "object": {
        "collection": "objects",
        "prefix": "obj_",
        "create_required": ("name",),
        "create_optional": ("description", "quantity"),
        "update_fields": ("name", "description", "quantity"),
        "capability": "inventory.objects.write",
    },
    "project": {
        "collection": "projects",
        "prefix": "proj_",
        "create_required": ("name",),
        "create_optional": ("description", "status"),
        "update_fields": ("name", "description", "status"),
        "status_values": ("idea", "planned", "active", "paused",
                          "completed", "archived"),
        "capability": "inventory.projects.write",
    },
    "idea": {
        "collection": "ideas",
        "prefix": "idea_",
        "create_required": ("name",),
        "create_optional": ("description", "status"),
        "update_fields": ("name", "description", "status"),
        "status_values": ("raw", "considered", "planned", "rejected",
                          "converted"),
        "capability": "inventory.ideas.write",
    },
    "file": {
        "collection": "files",
        "prefix": "file_",
        "create_required": ("name", "sha256"),
        "create_optional": ("description", "file_kind", "mime_type",
                            "size_bytes", "status", "metadata"),
        "update_fields": ("name", "description", "file_kind",
                          "mime_type", "size_bytes", "status",
                          "metadata"),
        "file_kinds": ("cad", "mesh", "gcode", "image", "document",
                       "data", "other"),
        "file_statuses": ("available", "in_use", "maintenance",
                          "retired", "unknown"),
        "capability": "inventory.files.write",
    },
}

RELATIONSHIP_PREDICATES = frozenset({
    "used_in", "uses", "related_to", "part_of", "contains", "became",
    "led_to", "depends_on", "produced_by", "stored_in",
})

#: ID prefixes accepted as relationship endpoints (bridge prefixes
#: plus file_, which inventory/app/ids.py also generates).
RELATIONSHIP_ID_PREFIXES = ENTITY_ID_PREFIXES + ("file_",)

MAX_NAME_CHARS = 200
MAX_DESCRIPTION_CHARS = 5000


class InventoryWriteRefusedError(ValueError):
    """Local validation refused the mutation; nothing was sent."""


class InventoryWriteFailedError(RuntimeError):
    """The write was refused or failed remotely; nothing is verified."""


def _check_base_url(raw) -> str:
    from urllib.parse import urlsplit
    if not isinstance(raw, str) or not raw.strip():
        raise InventoryWriteRefusedError(
            "INVENTory base URL must be non-empty text")
    try:
        parts = urlsplit(raw.strip())
    except ValueError as error:
        raise InventoryWriteRefusedError(
            f"Invalid INVENTory base URL: {error}") from error
    if parts.scheme != "http":
        raise InventoryWriteRefusedError(
            "INVENTory base URL must use http")
    if parts.username or parts.password:
        raise InventoryWriteRefusedError(
            "INVENTory base URL must not contain credentials")
    host = (parts.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        raise InventoryWriteRefusedError(
            f"INVENTory host '{host or '?'}' is not loopback; refusing")
    if not parts.port:
        return f"http://{parts.hostname}"
    return f"http://{parts.hostname}:{parts.port}"


def _check_entity_id(entity_id, label: str = "Entity ID") -> str:
    if not isinstance(entity_id, str) or not entity_id.strip():
        raise InventoryWriteRefusedError(f"{label} must be non-empty text")
    clean = entity_id.strip()
    if not clean.startswith(RELATIONSHIP_ID_PREFIXES):
        raise InventoryWriteRefusedError(
            f"{label} '{clean[:32]}' has an unknown prefix; refusing")
    return clean


def _check_name(value, label: str = "name") -> str:
    if not isinstance(value, str) or not value.strip():
        raise InventoryWriteRefusedError(f"{label} must be non-empty text")
    if len(value.strip()) > MAX_NAME_CHARS:
        raise InventoryWriteRefusedError(f"{label} exceeds "
                                        f"{MAX_NAME_CHARS} characters")
    return value.strip()


def _check_description(value) -> str:
    if not isinstance(value, str):
        raise InventoryWriteRefusedError("description must be text")
    if len(value) > MAX_DESCRIPTION_CHARS:
        raise InventoryWriteRefusedError("description too long")
    return value


def _check_quantity(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InventoryWriteRefusedError("quantity must be an integer")
    if value < 0:
        raise InventoryWriteRefusedError("quantity must be >= 0")
    return value


def _check_status(value, allowed) -> str:
    if value not in allowed:
        raise InventoryWriteRefusedError(
            f"status '{value}' unknown; expected one of {sorted(allowed)}")
    return value


def _check_sha256(value) -> str:
    if not isinstance(value, str):
        raise InventoryWriteRefusedError("sha256 must be text")
    text = value.strip().lower()
    if len(text) != 64 or any(
            char not in "0123456789abcdef" for char in text):
        raise InventoryWriteRefusedError(
            "sha256 must be a 64-char hex digest")
    return text


def _check_mime_type(value) -> str:
    if not isinstance(value, str):
        raise InventoryWriteRefusedError("mime_type must be text")
    text = value.strip()
    if len(text) > 200:
        raise InventoryWriteRefusedError("mime_type too long")
    if any(char in text for char in ("<>\"'")) or "\n" in text:
        raise InventoryWriteRefusedError("mime_type is not plain text")
    return text


def _check_size_bytes(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InventoryWriteRefusedError("size_bytes must be an integer")
    if value < 0:
        raise InventoryWriteRefusedError("size_bytes must be >= 0")
    return value


def _check_file_kind(value, allowed) -> str:
    if value not in allowed:
        raise InventoryWriteRefusedError(
            f"file_kind '{value}' unknown; expected one of "
            f"{sorted(allowed)}")
    return value


def _check_metadata(value) -> dict:
    if not isinstance(value, dict):
        raise InventoryWriteRefusedError("metadata must be an object")
    return dict(value)


def _apply_file_fields(body: dict, fields: dict, contract: dict,
                       for_update: bool) -> None:
    """Shared file-kind/status/mime/size/sha/metadata handling."""
    if "sha256" in fields:
        body["sha256"] = _check_sha256(fields["sha256"])
    elif not for_update and "sha256" in contract["create_required"]:
        raise InventoryWriteRefusedError("sha256 is required")
    if "file_kind" in fields:
        body["file_kind"] = _check_file_kind(fields["file_kind"],
                                             contract["file_kinds"])
    if "mime_type" in fields:
        body["mime_type"] = _check_mime_type(fields["mime_type"])
    if "size_bytes" in fields:
        body["size_bytes"] = _check_size_bytes(fields["size_bytes"])
    if "metadata" in fields:
        body["metadata"] = _check_metadata(fields["metadata"])


def _check_provenance(value) -> dict:
    """Provenance supplied with a write. AI output can never smuggle
    human_verified=True through here."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InventoryWriteRefusedError("provenance must be an object")
    allowed_keys = {"source_type", "creator_id", "confidence_score",
                    "human_verified", "verified_by", "notes"}
    unknown = set(value) - allowed_keys
    if unknown:
        raise InventoryWriteRefusedError(
            f"provenance carries unknown fields: {sorted(unknown)}")
    if value.get("human_verified") is True and not value.get("verified_by"):
        raise InventoryWriteRefusedError(
            "human_verified=True without verified_by is refused; "
            "AI output never self-verifies")
    return dict(value)


def build_create_payload(entity_type: str, fields: dict) -> dict:
    """Validate create fields for one entity type. Fail-closed."""
    contract = ENTITY_CONTRACTS.get(entity_type)
    if contract is None:
        raise InventoryWriteRefusedError(
            f"Create of '{entity_type}' is not a controlled mutation; "
            f"supported: {sorted(ENTITY_CONTRACTS)}")
    if not isinstance(fields, dict):
        raise InventoryWriteRefusedError("Create fields must be an object")
    allowed = set(contract["create_required"]) | set(
        contract["create_optional"]) | {"provenance"}
    unknown = set(fields) - allowed
    if unknown:
        raise InventoryWriteRefusedError(
            f"Create carries unauthorized fields: {sorted(unknown)}")
    body: dict[str, Any] = {}
    for field in contract["create_required"]:
        if field == "name":
            body["name"] = _check_name(fields.get("name", ""))
        elif field == "sha256":
            body["sha256"] = _check_sha256(fields.get("sha256", ""))
        else:  # pragma: no cover - current contracts require name/sha256
            body[field] = fields[field]
    if "description" in fields:
        body["description"] = _check_description(fields["description"])
    if "quantity" in fields and "quantity" in allowed:
        body["quantity"] = _check_quantity(fields["quantity"])
    if "status" in fields and "status" in allowed:
        status_values = (contract.get("status_values")
                         or contract.get("file_statuses", ()))
        body["status"] = _check_status(fields["status"], status_values)
    if "file_kinds" in contract:
        _apply_file_fields(body, fields, contract, for_update=False)
    body["provenance"] = _write_provenance(fields.get("provenance"))
    return body


def build_update_payload(entity_type: str, fields: dict) -> dict:
    """Validate patch fields for one entity type. Fail-closed."""
    contract = ENTITY_CONTRACTS.get(entity_type)
    if contract is None:
        raise InventoryWriteRefusedError(
            f"Update of '{entity_type}' is not a controlled mutation; "
            f"supported: {sorted(ENTITY_CONTRACTS)}")
    if not isinstance(fields, dict) or not fields:
        raise InventoryWriteRefusedError(
            "Update fields must be a non-empty object")
    allowed = set(contract["update_fields"]) | {"provenance"}
    unknown = set(fields) - allowed
    if unknown:
        raise InventoryWriteRefusedError(
            f"Update carries unauthorized fields: {sorted(unknown)}")
    body: dict[str, Any] = {}
    if "name" in fields:
        body["name"] = _check_name(fields["name"])
    if "description" in fields:
        body["description"] = _check_description(fields["description"])
    if "quantity" in fields:
        body["quantity"] = _check_quantity(fields["quantity"])
    if "status" in fields:
        status_values = (contract.get("status_values")
                         or contract.get("file_statuses", ()))
        body["status"] = _check_status(fields["status"], status_values)
    if "file_kinds" in contract:
        _apply_file_fields(body, fields, contract, for_update=True)
    if "provenance" in fields:
        body["provenance"] = _write_provenance(fields["provenance"])
    else:
        body["provenance"] = _write_provenance(None)
    return body


def build_relationship_payload(fields: dict) -> dict:
    """Validate one relationship creation. Fail-closed."""
    if not isinstance(fields, dict):
        raise InventoryWriteRefusedError(
            "Relationship fields must be an object")
    allowed = {"from_id", "predicate", "to_id", "metadata", "provenance"}
    unknown = set(fields) - allowed
    if unknown:
        raise InventoryWriteRefusedError(
            f"Relationship carries unauthorized fields: {sorted(unknown)}")
    from_id = _check_entity_id(fields.get("from_id", ""), "from_id")
    to_id = _check_entity_id(fields.get("to_id", ""), "to_id")
    if from_id == to_id:
        raise InventoryWriteRefusedError(
            "from_id and to_id must differ")
    predicate = fields.get("predicate", "")
    if predicate not in RELATIONSHIP_PREDICATES:
        raise InventoryWriteRefusedError(
            f"predicate '{predicate}' unknown; expected one of "
            f"{sorted(RELATIONSHIP_PREDICATES)}")
    metadata = fields.get("metadata", {})
    if not isinstance(metadata, dict):
        raise InventoryWriteRefusedError("metadata must be an object")
    return {
        "from_id": from_id,
        "predicate": predicate,
        "to_id": to_id,
        "metadata": dict(metadata),
        "provenance": _write_provenance(fields.get("provenance")),
    }


def _write_provenance(value) -> dict:
    """Execution provenance: AI-generated, human-approved, unverified."""
    checked = _check_provenance(value)
    provenance = {
        "source_type": "ai-generated",
        "creator_id": str(checked.get("creator_id", "mycelium-write")),
        "human_verified": False,
        "notes": "human-approved controlled write; "
                 "verification is a separate step",
    }
    if checked.get("confidence_score") is not None:
        provenance["confidence_score"] = checked["confidence_score"]
    return provenance


def propose_inventory_write(proposal_id: str, mutation: str,
                            entity_type: str, fields: dict, *,
                            entity_id: str = "",
                            actor: str = "mycelium",
                            provenance: Provenance | None = None,
                            ) -> WriteProposal:
    """Build a validated inventory write proposal. Performs nothing.

    ``mutation`` is one of ``create`` / ``update`` /
    ``create_relationship``; fields are validated now (fail fast)
    and revalidated at execution.
    """
    from .controlled_writes import propose_write
    if mutation == "create":
        body = build_create_payload(entity_type, fields)
        target = f"inventory:{entity_type}"
        mutation_type = "inventory.create"
        payload = {"entity_type": entity_type, "fields": body}
    elif mutation == "update":
        contract = ENTITY_CONTRACTS.get(entity_type)
        if contract is None:
            raise InventoryWriteRefusedError(
                f"Update of '{entity_type}' is not controlled")
        clean_id = _check_entity_id(entity_id)
        if not clean_id.startswith(contract["prefix"]):
            raise InventoryWriteRefusedError(
                f"Entity ID '{clean_id[:32]}' does not match "
                f"'{entity_type}' (expected {contract['prefix']}*)")
        body = build_update_payload(entity_type, fields)
        target = f"inventory:{entity_type}:{clean_id}"
        mutation_type = "inventory.update"
        payload = {"entity_type": entity_type, "entity_id": clean_id,
                   "fields": body}
    elif mutation == "create_relationship":
        body = build_relationship_payload(fields)
        target = (f"inventory:relationship:"
                  f"{body['from_id']}->{body['to_id']}")
        mutation_type = "inventory.create_relationship"
        payload = {"entity_type": "relationship", "fields": body}
    else:
        raise InventoryWriteRefusedError(
            f"Unknown inventory mutation '{mutation}'; expected "
            "create, update or create_relationship")
    return propose_write(proposal_id, mutation_type, target, payload,
                         actor=actor, provenance=provenance)


def capability_for(proposal: WriteProposal) -> str:
    """Dotted capability for one inventory write proposal."""
    if proposal.mutation_type == "inventory.create":
        entity_type = proposal.payload.get("entity_type", "")
        contract = ENTITY_CONTRACTS.get(entity_type)
        if contract is None:
            raise InventoryWriteRefusedError(
                f"Create of '{entity_type}' is not controlled")
        return str(contract["capability"])
    if proposal.mutation_type == "inventory.update":
        entity_type = proposal.payload.get("entity_type", "")
        contract = ENTITY_CONTRACTS.get(entity_type)
        if contract is None:
            raise InventoryWriteRefusedError(
                f"Update of '{entity_type}' is not controlled")
        return str(contract["capability"])
    if proposal.mutation_type == "inventory.create_relationship":
        return "inventory.relationships.write"
    raise InventoryWriteRefusedError(
        f"Mutation '{proposal.mutation_type}' is not an inventory write")


class InventoryWriter:
    """Executes approved inventory write proposals. POST/PATCH only."""

    def __init__(self, base_url=None,
                 timeout: float = MAX_TIMEOUT_SECONDS,
                 transport=None):
        raw = (base_url if base_url is not None
               else os.environ.get(BASE_URL_ENV_VAR, DEFAULT_BASE_URL))
        self.base_url = _check_base_url(raw)
        try:
            self.timeout = min(float(timeout), MAX_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            self.timeout = MAX_TIMEOUT_SECONDS
        if self.timeout <= 0:
            self.timeout = MAX_TIMEOUT_SECONDS
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            follow_redirects=False,
            transport=self._transport,
        )

    async def _send(self, method: str, path: str,
                    body: dict) -> dict:
        if method not in ("POST", "PATCH"):
            raise InventoryWriteRefusedError(
                f"HTTP {method} is not a controlled write method")
        try:
            async with self._client() as client:
                if method == "POST":
                    response = await client.post(path, json=body)
                else:
                    response = await client.patch(path, json=body)
        except httpx.TimeoutException as error:
            raise InventoryWriteFailedError(
                f"INVENTory write timed out: {error}") from error
        except httpx.HTTPError as error:
            raise InventoryWriteFailedError(
                f"INVENTory unreachable: {error}") from error
        if response.status_code in (301, 302, 303, 307, 308):
            raise InventoryWriteFailedError("INVENTory redirect refused")
        if response.status_code not in (200, 201):
            raise InventoryWriteFailedError(
                f"INVENTory refused the write "
                f"(HTTP {response.status_code})")
        try:
            data = response.json()
        except ValueError as error:
            raise InventoryWriteFailedError(
                "INVENTory answered with invalid JSON") from error
        if not isinstance(data, dict):
            raise InventoryWriteFailedError(
                "INVENTory answered with invalid JSON")
        return data


async def execute_inventory_write(proposal: WriteProposal,
                                  approval: WriteApproval, *,
                                  reader: InventoryReader,
                                  writer: InventoryWriter,
                                  now_str: str | None = None) -> WriteResult:
    """Execute one approved proposal. Revalidates first, snapshots
    before/after through independent reads. Transport failures yield
    a failed WriteResult — never a false success."""
    fingerprint = revalidate(proposal, approval,
                             now_str or now())
    capability_for(proposal)  # fail-closed on non-inventory mutations
    if proposal.mutation_type == "inventory.create":
        return await _execute_create(proposal, fingerprint, reader,
                                     writer)
    if proposal.mutation_type == "inventory.update":
        return await _execute_update(proposal, fingerprint, reader,
                                     writer)
    if proposal.mutation_type == "inventory.create_relationship":
        return await _execute_relationship(proposal, fingerprint,
                                           writer)
    raise InventoryWriteRefusedError(
        f"Mutation '{proposal.mutation_type}' is not an inventory write")


async def _execute_create(proposal: WriteProposal, fingerprint: str,
                          reader: InventoryReader,
                          writer: InventoryWriter) -> WriteResult:
    entity_type = proposal.payload["entity_type"]
    fields = build_create_payload(entity_type,
                                  proposal.payload.get("fields", {}))
    contract = ENTITY_CONTRACTS[entity_type]
    try:
        created = await writer._send(
            "POST", f"/api/v1/{contract['collection']}", fields)
    except InventoryWriteFailedError as error:
        return _failed(proposal, fingerprint, {}, str(error))
    entity_id = str(created.get("id", ""))
    after = await _readback(reader, entity_type, entity_id)
    return WriteResult(
        proposal_id=proposal.proposal_id, fingerprint=fingerprint,
        outcome="executed", before={},
        after=after or created,
        actor=proposal.actor, executed_at=now(),
        provenance=Provenance(
            source_type="ai-generated", creator_id=proposal.actor,
            human_verified=False,
            notes=f"controlled write {proposal.proposal_id}; "
                  "unverified until independent verification"),
    )


async def _execute_update(proposal: WriteProposal, fingerprint: str,
                          reader: InventoryReader,
                          writer: InventoryWriter) -> WriteResult:
    entity_type = proposal.payload["entity_type"]
    entity_id = proposal.payload["entity_id"]
    fields = build_update_payload(entity_type,
                                  proposal.payload.get("fields", {}))
    contract = ENTITY_CONTRACTS[entity_type]
    before_record = await _safe_get(reader, entity_type, entity_id)
    if before_record is None:
        return _failed(proposal, fingerprint, {},
                       f"Target '{entity_id}' does not exist; refusing")
    before = {"entity_id": entity_id,
              "title": before_record.title,
              "details": dict(before_record.details)}
    try:
        await writer._send(
            "PATCH",
            f"/api/v1/{contract['collection']}/{entity_id}", fields)
    except InventoryWriteFailedError as error:
        return _failed(proposal, fingerprint, before, str(error))
    after = await _readback(reader, entity_type, entity_id)
    return WriteResult(
        proposal_id=proposal.proposal_id, fingerprint=fingerprint,
        outcome="executed", before=before,
        after=after or {"entity_id": entity_id},
        actor=proposal.actor, executed_at=now(),
        provenance=Provenance(
            source_type="ai-generated", creator_id=proposal.actor,
            human_verified=False,
            notes=f"controlled write {proposal.proposal_id}; "
                  "unverified until independent verification"),
    )


async def _execute_relationship(proposal: WriteProposal,
                                fingerprint: str,
                                writer: InventoryWriter) -> WriteResult:
    fields = build_relationship_payload(
        proposal.payload.get("fields", {}))
    try:
        created = await writer._send(
            "POST", "/api/v1/relationships", fields)
    except InventoryWriteFailedError as error:
        return _failed(proposal, fingerprint, {}, str(error))
    return WriteResult(
        proposal_id=proposal.proposal_id, fingerprint=fingerprint,
        outcome="executed", before={},
        after={"relationship_id": str(created.get("id", "")),
               "from_id": fields["from_id"],
               "predicate": fields["predicate"],
               "to_id": fields["to_id"]},
        actor=proposal.actor, executed_at=now(),
        provenance=Provenance(
            source_type="ai-generated", creator_id=proposal.actor,
            human_verified=False,
            notes=f"controlled write {proposal.proposal_id}; "
                  "unverified until independent verification"),
    )


async def _safe_get(reader: InventoryReader, entity_type: str,
                    entity_id: str):
    try:
        return await reader.get(entity_type, entity_id)
    except Exception:
        return None


async def _readback(reader: InventoryReader, entity_type: str,
                    entity_id: str) -> dict:
    record = await _safe_get(reader, entity_type, entity_id)
    if record is None:
        return {}
    return {"entity_id": record.entity_id, "title": record.title,
            "provenance": record.provenance.model_dump(mode="json"),
            "details": dict(record.details)}


def _failed(proposal: WriteProposal, fingerprint: str, before: dict,
            error: str) -> WriteResult:
    return WriteResult(
        proposal_id=proposal.proposal_id, fingerprint=fingerprint,
        outcome="failed", before=before, after={},
        actor=proposal.actor, executed_at=now(),
        error=error[:2000],
        provenance=Provenance(
            source_type="ai-generated", creator_id=proposal.actor,
            human_verified=False,
            notes="controlled write failed; nothing is verified"),
    )
