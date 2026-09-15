"""Persistent mapping table: desktop stable_id <-> INVENTory proj_-ID (M2B).

The table lives inside ``agent/`` and uses the terminology of
``inventory_bridge.py``. It records decisions; it never makes them:

- a row is created as ``unmapped`` / ``proposed`` / ``nested`` / ``copy`` /
  ``conflict`` by a dry-run plan or by explicit operator action;
- only the approval-gated writer (``inventory_writer.py``) may flip a row to
  ``mapped``, and only after a real ``proj_`` ID was returned by INVENTory.

The store never contacts INVENTory and never touches user projects. With
``path=None`` it is purely in-memory and performs no file I/O at all.
"""

from pathlib import Path
import json
from datetime import datetime, timezone

from inventory_bridge import MAPPING_STATUSES

STORE_NAME = "mycelium-mapping-store"
STORE_VERSION = "1.0.0"
STORE_SOURCE = "mycelium-desktop-agent:mapping-store"

BASE = Path(__file__).parent
DEFAULT_STORE_PATH = BASE / "inventory_mappings.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MappingStore:
    """Small JSON-backed table of desktop -> INVENTory mappings."""

    def __init__(self, path=None, now=None):
        self.path = Path(path) if path is not None else None
        self.now = now or _utc_now
        self._rows = {}
        if self.path is not None and self.path.exists():
            self.load()

    def load(self) -> dict:
        if self.path is None:
            return dict(self._rows)
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("mappings"), dict):
            raise ValueError(f"Not a valid mapping store: {self.path}")
        self._rows = {str(k): v for k, v in raw["mappings"].items()}
        return dict(self._rows)

    def save(self) -> Path | None:
        """Persist to the configured path. Memory-only stores save nothing."""
        if self.path is None:
            return None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "store": {"name": STORE_NAME, "version": STORE_VERSION},
            "source": STORE_SOURCE,
            "updated_at": self.now(),
            "mappings": self._rows,
        }
        self.path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
        return self.path

    def get(self, stable_id) -> dict | None:
        return self._rows.get(str(stable_id))

    def all(self) -> dict:
        return dict(self._rows)

    def record(self, stable_id, desktop_path, mapping_status, approval=None,
               inventory_project_id=None, provenance=None) -> dict:
        """Insert or replace a row. Only ``mapped`` rows may carry a proj_ ID."""
        stable_id = str(stable_id)
        if mapping_status not in MAPPING_STATUSES:
            raise ValueError(f"Unknown mapping status: {mapping_status!r}")
        if inventory_project_id is not None and mapping_status != "mapped":
            raise ValueError("Only mapped rows may carry an inventory_project_id")
        stamp = self.now()
        previous = self._rows.get(stable_id)
        row = {
            "stable_id": stable_id,
            "desktop_path": str(desktop_path),
            "inventory_project_id": str(inventory_project_id) if inventory_project_id else None,
            "mapping_status": mapping_status,
            "approval": approval,
            "provenance": provenance or {
                "source": STORE_SOURCE,
                "component": "mapping_store",
                "version": STORE_VERSION,
            },
            "source": STORE_SOURCE,
            "created_at": (previous or {}).get("created_at", stamp),
            "updated_at": stamp,
        }
        self._rows[stable_id] = row
        return row

    def mark_mapped(self, stable_id, desktop_path, inventory_project_id,
                    approval, provenance=None) -> dict:
        """Flip a row to ``mapped`` after INVENTory returned a real proj_ ID."""
        if not str(inventory_project_id or "").startswith("proj_"):
            raise ValueError("Refusing to store a non-proj_ inventory ID")
        return self.record(stable_id, desktop_path, "mapped",
                           approval=approval,
                           inventory_project_id=str(inventory_project_id),
                           provenance=provenance)
