"""Read-only INVENTory client for the Mycelium coordinator (M5.1).

The coordinator never sees files or sensor data; this bridge exposes only the
curated world-model records INVENTory already serves over HTTP (search results,
single entities, graph context), including their provenance.

Safety properties (enforced by construction, all covered by tests):

- HTTP GET only. This module contains no POST/PATCH/PUT/DELETE capability.
- Loopback-only base URL (127.0.0.1, localhost, ::1). Anything else is refused
  before any socket is opened. Redirects are never followed.
- Bounded inputs: q <= 200 chars, entity IDs limited to known ``xxx_``
  prefixes, graph depth strictly 1 or 2.
- Bounded time: timeout clamped to at most 5 seconds; connection problems and
  timeouts surface as :class:`InventoryUnavailable`, never as raw tracebacks
  and never as a coordinator crash.
- No INVENTory code is imported. Local pydantic models mirror only the fields
  Mycelium needs and tolerate extra fields, so INVENTory can evolve (M3
  entities included) without breaking this bridge.
"""

import os
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
BASE_URL_ENV_VAR = "INVENTORY_BASE_URL"
MAX_TIMEOUT_SECONDS = 5.0
MAX_QUERY_LENGTH = 200
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
ENTITY_ID_PREFIXES = ("obj_", "proj_", "idea_", "rel_", "evt_",
                      "hw_", "sns_", "cam_", "loc_", "mod_", "task_", "act_")
GET_TYPES = {"object": "objects", "project": "projects", "idea": "ideas",
             "hardware": "hardware", "sensor": "sensors", "camera": "cameras",
             "location": "locations", "model": "models", "task": "tasks",
             "actuator": "actuators"}
SEARCH_TYPES = frozenset({"objects", "projects", "ideas", "relationships",
                          "hardware", "sensors", "cameras", "locations",
                          "models", "tasks", "actuators"})
GRAPH_DEPTHS = (1, 2)


class InventoryUnavailable(RuntimeError):
    """INVENTory could not be reached or answered with an error."""


class InventoryRefusedError(ValueError):
    """Local validation refused the request; nothing was sent."""


class Provenance(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_type: str = "unknown"
    creator_id: str = "unknown"
    confidence_score: float | None = None
    human_verified: bool = False
    verified_by: str | None = None
    created_at: str | None = None
    notes: str | None = None


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    entity_type: str
    entity_id: str
    title: str = ""
    snippet: str = ""
    provenance: Provenance = Field(default_factory=Provenance)
    details: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    query: str = ""
    results: list[SearchResult] = Field(default_factory=list)
    total: int = 0


class EntityRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    entity_type: str
    entity_id: str
    title: str = ""
    provenance: Provenance = Field(default_factory=Provenance)
    details: dict[str, Any] = Field(default_factory=dict)


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    entity_type: str
    entity_id: str
    title: str = ""
    provenance: Provenance = Field(default_factory=Provenance)
    details: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    from_id: str
    predicate: str
    to_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance = Field(default_factory=Provenance)


class GraphResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    entity_id: str
    depth: int
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


def _validate_base_url(raw) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise InventoryRefusedError("INVENTory base URL must be non-empty text")
    try:
        parts = urlsplit(raw.strip())
    except ValueError as error:
        raise InventoryRefusedError(f"Invalid INVENTory base URL: {error}") from error
    if parts.scheme != "http":
        raise InventoryRefusedError("INVENTory base URL must use http")
    if parts.username or parts.password:
        raise InventoryRefusedError("INVENTory base URL must not contain credentials")
    host = (parts.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        raise InventoryRefusedError(
            f"INVENTory host '{host or '?'}' is not loopback; refusing"
        )
    if not parts.port:
        return f"http://{parts.hostname}"
    return f"http://{parts.hostname}:{parts.port}"


def _check_query(query) -> str:
    if not isinstance(query, str) or not query.strip():
        raise InventoryRefusedError("Search query must be non-empty text")
    if len(query) > MAX_QUERY_LENGTH:
        raise InventoryRefusedError(
            f"Search query exceeds {MAX_QUERY_LENGTH} characters"
        )
    return query.strip()


def _check_entity_id(entity_id) -> str:
    if not isinstance(entity_id, str) or not entity_id.strip():
        raise InventoryRefusedError("Entity ID must be non-empty text")
    clean = entity_id.strip()
    if not clean.startswith(ENTITY_ID_PREFIXES):
        raise InventoryRefusedError(
            f"Entity ID '{clean[:32]}' has an unknown prefix; refusing"
        )
    return clean


def _check_depth(depth) -> int:
    if isinstance(depth, bool) or not isinstance(depth, int):
        raise InventoryRefusedError("Graph depth must be 1 or 2")
    if depth not in GRAPH_DEPTHS:
        raise InventoryRefusedError("Graph depth must be 1 or 2")
    return depth


class InventoryReader:
    """Minimal read-only bridge to INVENTory. GET only, loopback only."""

    def __init__(self, base_url=None, timeout=MAX_TIMEOUT_SECONDS, transport=None):
        raw = base_url if base_url is not None else os.environ.get(
            BASE_URL_ENV_VAR, DEFAULT_BASE_URL
        )
        self.base_url = _validate_base_url(raw)
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

    async def _get(self, path: str, params: dict | None = None):
        try:
            async with self._client() as client:
                response = await client.get(path, params=params or {})
        except httpx.TimeoutException as error:
            raise InventoryUnavailable(f"INVENTory timed out: {error}") from error
        except httpx.HTTPError as error:
            raise InventoryUnavailable(f"INVENTory unreachable: {error}") from error
        if response.status_code in (301, 302, 303, 307, 308):
            raise InventoryUnavailable("INVENTory redirect refused")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise InventoryUnavailable(
                f"INVENTory answered with HTTP {response.status_code}"
            )
        try:
            return response.json()
        except ValueError as error:
            raise InventoryUnavailable("INVENTory answered with invalid JSON") from error

    async def search(self, q, type=None) -> SearchResponse:
        """Full-text search over objects, projects, ideas and relationships."""
        query = _check_query(q)
        if type is not None and type not in SEARCH_TYPES:
            raise InventoryRefusedError(
                f"Unknown search type '{type}'; expected one of {sorted(SEARCH_TYPES)}"
            )
        params = {"q": query}
        if type is not None:
            params["type"] = type
        data = await self._get("/api/v1/search", params)
        if data is None:  # pragma: no cover - search never 404s by contract
            raise InventoryUnavailable("INVENTory search returned 404")
        return SearchResponse.model_validate(data)

    async def get(self, entity_type, entity_id) -> EntityRecord | None:
        """Fetch one entity by ID. None when it does not exist.

        Only entity types with a single-GET contract in INVENTory are
        supported (object, project, idea, hardware, sensor, camera, location,
        model, task, actuator). Relationships and events have no single-GET
        contract in INVENTory, so they are refused here rather than guessed.
        """
        if entity_type not in GET_TYPES:
            raise InventoryRefusedError(
                f"Unsupported get type '{entity_type}'; "
                f"expected one of {sorted(GET_TYPES)}"
            )
        clean_id = _check_entity_id(entity_id)
        data = await self._get(f"/api/v1/{GET_TYPES[entity_type]}/{clean_id}")
        if data is None:
            return None
        if not isinstance(data, dict):
            raise InventoryUnavailable("INVENTory answered with invalid JSON")
        raw_provenance = data.get("provenance")
        details = {
            key: value for key, value in data.items()
            if key not in ("id", "name", "provenance")
        }
        return EntityRecord(
            entity_type=entity_type,
            entity_id=str(data.get("id", clean_id)),
            title=str(data.get("name", clean_id)),
            provenance=Provenance.model_validate(
                raw_provenance if isinstance(raw_provenance, dict) else {}
            ),
            details=details,
        )

    async def graph(self, entity_id, depth=1) -> GraphResponse:
        """Graph context around one entity, at most 2 hops out."""
        clean_id = _check_entity_id(entity_id)
        clean_depth = _check_depth(depth)
        data = await self._get(
            "/api/v1/graph", {"entity_id": clean_id, "depth": clean_depth}
        )
        if data is None:
            raise InventoryUnavailable("INVENTory graph returned 404")
        return GraphResponse.model_validate(data)
