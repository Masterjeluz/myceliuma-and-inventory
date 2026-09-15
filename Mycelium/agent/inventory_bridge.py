"""M2B mapping/import layer: safe bridge from project_index.json to INVENTory.

Architecture boundary (see ARCHITECTURE_CONTRACT.md and CANONICAL_PROJECTS.md):

- Desktop Agent = discovery / index / orchestration boundary. It observes and
  proposes; it never decides identity.
- INVENTory = canonical world model / database / provenance. Its ``proj_`` IDs
  are a separate identity space, assigned server-side on creation.
- The desktop ``stable_id`` from ``project_index.json`` is the ONLY desktop
  project identity. It is never merged, never guessed, never rewritten.

Safety rules (binding for this module):

- Default to dry-run. :func:`build_plan` and :func:`dry_run` are pure
  functions: they perform zero INVENTory writes, zero network I/O and zero
  file writes. They only read the index document given to them.
- Index relationships (``parent_id``, ``nested_children_ids``,
  ``same_remote_ids``, ``shared_name_ids``, ``possible_copy_ids``) are treated
  as *evidence*, never as proof of identity. A shared remote or a shared name
  never merges two desktop projects.
- Copies and nested repositories remain distinguishable: they get their own
  mapping records with ``copy`` / ``nested`` status instead of being folded
  into another project.
- This milestone implements NO write path to INVENTory. There is deliberately
  no HTTP client, no SQLite access and no import of INVENTory code in this
  module. Any future write operation must go through the existing permission
  system (``permissions.request_permission`` with an explicit human ``YES``)
  and is out of scope for M2B.
"""

from pathlib import Path
import json
from datetime import datetime, timezone

BRIDGE_NAME = "mycelium-inventory-bridge"
BRIDGE_VERSION = "1.0.0"
BRIDGE_SOURCE = "mycelium-desktop-agent:inventory-bridge"
BRIDGE_MODE = "dry-run-proposal"

BASE = Path(__file__).parent
DEFAULT_INDEX_PATH = BASE / "project_index.json"

# Every mapping record distinguishes exactly these lifecycle states.
MAPPING_STATUSES = (
    "unmapped",   # tracked before (or freshly registered) but no decision yet
    "proposed",   # clean standalone project; exactly one proposal, needs YES
    "mapped",     # linked to an existing INVENTory proj_ ID via a stored table
    "copy",       # evidence this path is a copy/backup; never auto-imported
    "nested",     # nested inside another indexed project; stays distinguishable
    "rejected",   # invalid entry or human-declined; nothing will be imported
    "conflict",   # ambiguous evidence (shared remote/name); needs human review
)

# Statuses that require an explicit human YES before anything may be created.
REQUIRES_APPROVAL = {"unmapped", "proposed", "copy", "nested", "conflict"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_id_list(value) -> list:
    if not isinstance(value, (list, tuple, set)):
        return []
    return sorted({str(item) for item in value if isinstance(item, (str, int)) and str(item).strip()})


def new_mapping_record(desktop_project_id, desktop_path, status="unmapped",
                       now=None) -> dict:
    """Create a fresh mapping record. Defaults to ``unmapped``: no decision."""
    if status not in MAPPING_STATUSES:
        raise ValueError(f"Unknown mapping status: {status!r}")
    stamp = (now or _utc_now)()
    return {
        "desktop_project_id": str(desktop_project_id),
        "desktop_path": str(desktop_path),
        "inventory_project_id": None,
        "mapping_status": status,
        "mapping_reason": "registered; no mapping decision yet",
        "requires_approval": status in REQUIRES_APPROVAL,
        "provenance": {
            "source": BRIDGE_SOURCE,
            "component": "inventory_bridge",
            "version": BRIDGE_VERSION,
            "mode": BRIDGE_MODE,
            "default": "no-write",
            "desktop_project_id": str(desktop_project_id),
            "created_at": stamp,
        },
        "created_at": stamp,
    }


def _mapping_provenance(desktop_id, index_provenance, stamp) -> dict:
    return {
        "source": BRIDGE_SOURCE,
        "component": "inventory_bridge",
        "version": BRIDGE_VERSION,
        "mode": BRIDGE_MODE,
        "default": "no-write",
        "desktop_project_id": desktop_id,
        "discovery_timestamp": (index_provenance or {}).get("discovery_timestamp"),
        "indexer": (index_provenance or {}).get("indexer"),
        "indexer_version": (index_provenance or {}).get("indexer_version"),
        "created_at": stamp,
    }


def _proposed_project_payload(entry, stamp) -> dict:
    """Build the INVENTory ProjectCreate-shaped payload that *would* be sent.

    Create-only shape: no ``id`` field is ever set (``proj_`` IDs are assigned
    server-side). Returned for human review only; nothing is transmitted.
    """
    name = entry.get("name") or Path(entry.get("path", "unknown")).name or "unknown"
    return {
        "name": str(name),
        "description": (
            f"Desktop project {name!r} at {entry.get('path')} "
            f"(desktop_id={entry.get('id')}). "
            f"Proposed by {BRIDGE_NAME} dry-run; requires human approval."
        ),
        "status": "planned",
        "provenance": {
            "source_type": "imported",
            "creator_id": BRIDGE_SOURCE,
            "human_verified": False,
            "verified_by": None,
            "created_at": stamp,
            "notes": (
                f"dry-run proposal for desktop_id={entry.get('id')}; "
                "not verified, not written anywhere"
            ),
        },
        "for_desktop_id": entry.get("id"),
        "for_desktop_path": entry.get("path"),
    }


def _proposed_relationships(entry) -> list:
    """Translate index relations into relationship *proposals* (evidence only).

    ``possible_copy_ids`` becomes ``related_to`` with the basis recorded in
    metadata, per the contract: never an automatic merge.
    """
    relations = entry.get("relations") or {}
    proposals = []
    parent = entry.get("parent_id") or relations.get("parent_id")
    if parent:
        proposals.append({
            "from_desktop_id": entry.get("id"),
            "predicate": "part_of",
            "to_desktop_id": parent,
            "basis": "nested-parent",
            "metadata": {
                "basis": "nested-parent",
                "note": "evidence only; nested project stays distinguishable",
            },
        })
    for child in _as_id_list(relations.get("nested_children_ids")):
        proposals.append({
            "from_desktop_id": entry.get("id"),
            "predicate": "contains",
            "to_desktop_id": child,
            "basis": "nested-child",
            "metadata": {
                "basis": "nested-child",
                "note": "evidence only; nested project stays distinguishable",
            },
        })
    same_remote = set(_as_id_list(relations.get("same_remote_ids")))
    shared_name = set(_as_id_list(relations.get("shared_name_ids")))
    possible = set(_as_id_list(relations.get("possible_copy_ids"))) | same_remote | shared_name
    for other in sorted(possible):
        if other == entry.get("id"):
            continue
        if other in same_remote and other in shared_name:
            basis = "same_remote+shared_name"
        elif other in same_remote:
            basis = "same_remote"
        else:
            basis = "shared_name"
        proposals.append({
            "from_desktop_id": entry.get("id"),
            "predicate": "related_to",
            "to_desktop_id": other,
            "basis": basis,
            "metadata": {
                "basis": basis,
                "note": "evidence only; shared remote/name never merges projects",
            },
        })
    return proposals


def classify_entry(entry, existing_mappings=None, now=None) -> dict:
    """Classify one index entry into a mapping record. Never writes anything."""
    stamp = (now or _utc_now)()
    existing_mappings = existing_mappings or {}
    desktop_id = entry.get("id") if isinstance(entry, dict) else None
    desktop_path = entry.get("path") if isinstance(entry, dict) else None
    if not isinstance(entry, dict) or not desktop_id or not desktop_path:
        return {
            "desktop_project_id": str(desktop_id) if desktop_id else None,
            "desktop_path": str(desktop_path) if desktop_path else None,
            "inventory_project_id": None,
            "mapping_status": "rejected",
            "mapping_reason": "invalid index entry: missing id or path; skipped safely",
            "requires_approval": False,
            "evidence": {},
            "proposed_inventory_project": None,
            "proposed_relationships": [],
            "provenance": _mapping_provenance(str(desktop_id), None, stamp),
            "created_at": stamp,
        }

    desktop_id = str(desktop_id)
    relations = entry.get("relations") or {}
    evidence = {
        "parent_id": entry.get("parent_id") or relations.get("parent_id"),
        "is_nested": bool(entry.get("is_nested", False)),
        "is_backup_copy": bool(entry.get("is_backup_copy", False)),
        "same_remote_ids": _as_id_list(relations.get("same_remote_ids")),
        "shared_name_ids": _as_id_list(relations.get("shared_name_ids")),
        "possible_copy_ids": _as_id_list(relations.get("possible_copy_ids")),
        "nested_children_ids": _as_id_list(relations.get("nested_children_ids")),
    }

    record = {
        "desktop_project_id": desktop_id,
        "desktop_path": str(desktop_path),
        "inventory_project_id": None,
        "mapping_status": "unmapped",
        "mapping_reason": "",
        "requires_approval": True,
        "evidence": evidence,
        "proposed_inventory_project": None,
        "proposed_relationships": _proposed_relationships(entry),
        "provenance": None,  # filled below
        "created_at": stamp,
    }

    if desktop_id in existing_mappings:
        target = existing_mappings[desktop_id]
        if target:
            record["mapping_status"] = "mapped"
            record["mapping_reason"] = (
                f"already linked to INVENTory project {target} via stored mapping table"
            )
            record["inventory_project_id"] = str(target)
            record["requires_approval"] = False
        else:
            record["mapping_status"] = "unmapped"
            record["mapping_reason"] = "tracked before; still no mapping decision"
            record["requires_approval"] = True
    elif evidence["is_nested"] or evidence["parent_id"]:
        record["mapping_status"] = "nested"
        record["mapping_reason"] = (
            f"nested inside parent {evidence['parent_id']}; "
            "stays a distinguishable project, requires human approval"
        )
        record["proposed_inventory_project"] = _proposed_project_payload(entry, stamp)
    elif evidence["is_backup_copy"]:
        record["mapping_status"] = "copy"
        record["mapping_reason"] = (
            "flagged as backup copy; never imported as a standalone project "
            "without explicit human approval"
        )
    elif evidence["possible_copy_ids"] or evidence["same_remote_ids"] or evidence["shared_name_ids"]:
        record["mapping_status"] = "conflict"
        others = sorted(set(evidence["possible_copy_ids"])
                        | set(evidence["same_remote_ids"])
                        | set(evidence["shared_name_ids"]))
        record["mapping_reason"] = (
            f"ambiguous evidence shared with {len(others)} other project(s) "
            f"({', '.join(others)}); shared remote/name is not identity, "
            "requires human approval, never auto-merged"
        )
    else:
        record["mapping_status"] = "proposed"
        record["mapping_reason"] = (
            "clean standalone project with no conflicting evidence; "
            "exactly one INVENTory project proposed, requires human approval"
        )
        record["proposed_inventory_project"] = _proposed_project_payload(entry, stamp)

    record["provenance"] = _mapping_provenance(desktop_id, None, stamp)
    return record


def build_plan(index, existing_mappings=None, existing_inventory_ids=None,
               now=None) -> dict:
    """Build a dry-run import/mapping plan from a project index. Pure: no I/O.

    ``existing_inventory_ids`` (list of known ``proj_`` IDs) is accepted only
    to *avoid* collisions: proposed payloads never carry an ``id`` and mapped
    links are never rewritten. Nothing is read from or written to INVENTory.
    """
    stamp = (now or _utc_now)()
    if not isinstance(index, dict) or not isinstance(index.get("projects"), list):
        raise ValueError("Not a valid project index: expected object with project list")
    existing_mappings = dict(existing_mappings or {})
    known_inventory = {str(i) for i in (existing_inventory_ids or []) if str(i).strip()}

    mappings = []
    skipped_invalid = []
    seen_ids = set()
    duplicates_deduped = 0
    for raw in index.get("projects", []):
        desktop_id = raw.get("id") if isinstance(raw, dict) else None
        if desktop_id is not None and str(desktop_id) in seen_ids:
            duplicates_deduped += 1
            continue
        record = classify_entry(raw, existing_mappings, now=lambda: stamp)
        if record["mapping_status"] == "rejected" and not record["desktop_project_id"]:
            skipped_invalid.append({
                "reason": record["mapping_reason"],
                "entry": str(raw)[:200],
            })
            continue
        if desktop_id is not None:
            seen_ids.add(str(desktop_id))
        if (record["inventory_project_id"]
                and record["inventory_project_id"] not in known_inventory
                and known_inventory):
            # Stored table points at an unknown proj_ ID: do not trust it.
            record["mapping_status"] = "conflict"
            record["mapping_reason"] = (
                f"stored mapping points at unknown INVENTory ID "
                f"{record['inventory_project_id']}; requires human review"
            )
            record["inventory_project_id"] = None
            record["requires_approval"] = True
        mappings.append(record)

    mappings.sort(key=lambda m: (m["desktop_project_id"] or ""))
    by_status = {}
    for mapping in mappings:
        by_status.setdefault(mapping["mapping_status"], []).append(mapping["desktop_project_id"])

    proposed = [m for m in mappings if m["mapping_status"] == "proposed"]
    nested = [m for m in mappings if m["mapping_status"] == "nested"]
    copies = [m for m in mappings if m["mapping_status"] == "copy"]
    ambiguous = [m for m in mappings if m["mapping_status"] == "conflict"]
    needs_approval = [m["desktop_project_id"] for m in mappings if m["requires_approval"]]
    would_create_projects = [
        m["proposed_inventory_project"] for m in mappings
        if m["proposed_inventory_project"] is not None
    ]
    would_create_relationships = [
        rel for m in mappings for rel in m["proposed_relationships"]
    ]

    index_provenance = index.get("provenance") if isinstance(index.get("provenance"), dict) else {}
    plan = {
        "bridge": {"name": BRIDGE_NAME, "version": BRIDGE_VERSION},
        "mode": "dry-run",
        "writes_performed": 0,
        "generated_at": stamp,
        "provenance": {
            "source": BRIDGE_SOURCE,
            "component": "inventory_bridge",
            "version": BRIDGE_VERSION,
            "mode": BRIDGE_MODE,
            "default": "no-write",
            "discovery_timestamp": index_provenance.get("discovery_timestamp"),
            "indexer": index_provenance.get("indexer"),
            "indexer_version": index_provenance.get("indexer_version"),
            "created_at": stamp,
        },
        # 1. Which desktop projects were discovered?
        "discovered": [
            {"desktop_project_id": m["desktop_project_id"],
             "desktop_path": m["desktop_path"]}
            for m in mappings
        ],
        # 2. Which logical INVENTory projects are proposed?
        "proposed_projects": would_create_projects,
        # 3. Which paths appear to be copies?
        "copies": [
            {"desktop_project_id": m["desktop_project_id"],
             "desktop_path": m["desktop_path"],
             "reason": m["mapping_reason"]}
            for m in copies
        ],
        # 4. Which paths are nested?
        "nested": [
            {"desktop_project_id": m["desktop_project_id"],
             "desktop_path": m["desktop_path"],
             "parent_id": m["evidence"]["parent_id"],
             "reason": m["mapping_reason"]}
            for m in nested
        ],
        # 5. Which mappings are ambiguous?
        "ambiguous": [
            {"desktop_project_id": m["desktop_project_id"],
             "desktop_path": m["desktop_path"],
             "reason": m["mapping_reason"]}
            for m in ambiguous
        ],
        # 6. Which projects require human approval?
        "requires_approval": needs_approval,
        "approval_gate": {
            "mode": "explicit-human-confirmation",
            "mechanism": "permissions.request_permission",
            "rule": "no project or relationship is created without an explicit human YES per mapping",
        },
        # 7. What would be created if approved?
        "would_create": {
            "projects": would_create_projects,
            "relationships": would_create_relationships,
            "writes_now": 0,
            "note": (
                "Nothing was written. If every approval were granted, the "
                "payloads above would be POSTed as new INVENTory projects "
                "(server-assigned proj_ IDs) plus related_to/part_of/contains "
                "relationships. Copies and conflicts would still create "
                "nothing until a human reclassifies them."
            ),
        },
        "mappings": mappings,
        "skipped_invalid": skipped_invalid,
        "summary": {
            "desktop_projects_discovered": len(mappings),
            "proposed_mappings": len(proposed),
            "nested_mappings": len(nested),
            "copy_mappings": len(copies),
            "ambiguous_mappings": len(ambiguous),
            "mapped_mappings": len(by_status.get("mapped", [])),
            "unmapped_mappings": len(by_status.get("unmapped", [])),
            "rejected_mappings": len(by_status.get("rejected", [])),
            "require_approval": len(needs_approval),
            "would_create_projects": len(would_create_projects),
            "would_create_relationships": len(would_create_relationships),
            "copy_relationships": len(copies),
            "nested_relationships": len(nested),
            "duplicate_paths_deduped": duplicates_deduped,
            "skipped_invalid": len(skipped_invalid),
            "writes_performed": 0,
        },
    }
    return plan


def load_index_document(path=None) -> dict:
    target = Path(path) if path is not None else DEFAULT_INDEX_PATH
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
        raise ValueError(f"Not a valid project index: {target}")
    return data


def dry_run(index=None, index_path=None, existing_mappings=None,
            existing_inventory_ids=None, now=None) -> dict:
    """Dry-run the import: plan without writing. Reads only the index file."""
    if index is None:
        index = load_index_document(index_path)
    return build_plan(index, existing_mappings, existing_inventory_ids, now)


def plan_to_json(plan) -> str:
    return json.dumps(plan, indent=2, sort_keys=True)


def save_plan(plan, path) -> Path:
    """Write a plan to an explicitly given path. Never called implicitly."""
    target = Path(path)
    target.write_text(plan_to_json(plan), encoding="utf-8")
    return target


def main(index_path=None, output_path=None):
    import sys
    plan = dry_run(index_path=index_path)
    summary = plan["summary"]
    print(
        f"Discovered {summary['desktop_projects_discovered']} desktop projects: "
        f"{summary['proposed_mappings']} proposed, "
        f"{summary['nested_mappings']} nested, "
        f"{summary['copy_mappings']} copies, "
        f"{summary['ambiguous_mappings']} ambiguous, "
        f"{summary['require_approval']} require approval. "
        f"Writes performed: {summary['writes_performed']}.",
        file=sys.stderr,
    )
    if output_path is not None:
        target = save_plan(plan, output_path)
        print(f"Saved plan: {target.resolve()}", file=sys.stderr)
    else:
        print(plan_to_json(plan))
    return plan


if __name__ == "__main__":
    main()
