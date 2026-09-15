"""Tests for the M5.1 read-only INVENTory bridge (inventory_read.py).

All HTTP is faked with httpx.MockTransport. No real INVENTory server, no real
network, no database. Async client calls run via asyncio.run (no new deps).
"""
import asyncio

import httpx
import pytest

from coordinator.app.inventory_read import (
    BROWSE_MAX_TOTAL,
    BROWSE_PER_COLLECTION,
    LIST_TYPES,
    MAX_SEARCH_RESULTS,
    InventoryReader,
    InventoryRefusedError,
    InventoryUnavailable,
)

PROV = {"source_type": "user-created", "creator_id": "user",
        "human_verified": True, "created_at": "2026-09-11T00:00:00+00:00"}


def run(coro):
    return asyncio.run(coro)


class Recorder:
    """MockTransport handler that records requests and serves canned JSON."""

    def __init__(self, payload=None, status=200):
        self.requests = []
        self.payload = payload if payload is not None else {}
        self.status = status

    def __call__(self, request):
        self.requests.append(request)
        return httpx.Response(self.status, json=self.payload)


def reader(handler, **kwargs):
    kwargs.setdefault("base_url", "http://127.0.0.1:8080")
    return InventoryReader(transport=httpx.MockTransport(handler), **kwargs)


def list_item(entity_id="obj_abc", name="Moer M8", description="rvs zeskant"):
    return {"id": entity_id, "name": name, "description": description,
            "quantity": 4, "provenance": PROV,
            "created_at": "t", "updated_at": "t",
            "future_field": "tolerated"}


# --- correct requests ----------------------------------------------------------

def test_search_request():
    seen = []

    def handle(request):
        seen.append(request)
        if request.url.path == "/api/v1/objects":
            return httpx.Response(200, json=[list_item()])
        return httpx.Response(200, json=[])

    res = run(reader(handle).search("moer"))
    assert {req.url.path for req in seen} == {f"/api/v1/{c}" for c in LIST_TYPES}
    assert {req.method for req in seen} == {"GET"}
    for req in seen:
        assert "q" not in req.url.params
        assert "type" not in req.url.params
    assert res.query == "moer"
    assert res.total == 1
    assert res.results[0].entity_id == "obj_abc"
    assert res.results[0].entity_type == "object"
    assert res.results[0].title == "Moer M8"
    assert res.results[0].snippet == "rvs zeskant"
    assert res.results[0].details["future_field"] == "tolerated"


def test_search_type_filter():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json=[
            {"id": "proj_1", "name": "Bouwplan", "description": "tekening",
             "provenance": PROV},
            {"id": "proj_2", "name": "Tuin", "description": "zaden",
             "provenance": PROV}])

    res = run(reader(handle).search("bouw", type="projects"))
    assert [req.url.path for req in seen] == ["/api/v1/projects"]
    assert seen[0].method == "GET"
    assert res.total == 1
    assert res.results[0].entity_id == "proj_1"
    assert res.results[0].entity_type == "project"


def test_search_matches_name_description_and_id_case_insensitive():
    def handle(request):
        return httpx.Response(200, json=[
            list_item("obj_1", "Moer M8", "rvs"),
            list_item("obj_2", "Schroef", "verzinkt"),
            list_item("obj_3", "Ring", "past op MOER M8")])

    res = run(reader(handle).search("moer", type="objects"))
    assert {r.entity_id for r in res.results} == {"obj_1", "obj_3"}
    res = run(reader(handle).search("OBJ_2", type="objects"))
    assert [r.entity_id for r in res.results] == ["obj_2"]
    res = run(reader(handle).search("niets-te-vinden", type="objects"))
    assert res.total == 0
    assert res.results == []


def test_search_skips_missing_collections():
    seen = []

    def handle(request):
        seen.append(request)
        if request.url.path == "/api/v1/objects":
            return httpx.Response(200, json=[list_item()])
        return httpx.Response(404, json={"detail": "Not Found"})

    res = run(reader(handle).search("moer"))
    assert len(seen) == len(LIST_TYPES)
    assert res.total == 1
    assert res.results[0].entity_id == "obj_abc"


def test_search_explicit_missing_collection_is_unavailable():
    def handle(request):
        return httpx.Response(404, json={"detail": "Not Found"})

    with pytest.raises(InventoryUnavailable):
        run(reader(handle).search("moer", type="hardware"))


def test_search_relationships_filter_refused():
    rec = Recorder()
    with pytest.raises(InventoryRefusedError):
        run(reader(rec).search("moer", type="relationships"))
    assert rec.requests == []


# --- browse (q-less, bounded, deterministic) -----------------------------------

def browse_item(entity_id, name="Naam"):
    return {"id": entity_id, "name": name, "description": "beschrijving",
            "provenance": PROV}


def test_browse_uses_list_routes_bounded_and_deterministic():
    seen = []

    offer = {"objects": "obj", "projects": "proj", "ideas": "idea",
             "hardware": "hw"}

    def handle(request):
        seen.append(request)
        collection = request.url.path.rsplit("/", 1)[-1]
        if collection not in offer:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[
            browse_item(f"{offer[collection]}_{i}") for i in range(5)])

    first = run(reader(handle).browse())
    assert [req.url.path for req in seen] == [
        "/api/v1/objects", "/api/v1/projects", "/api/v1/ideas",
        "/api/v1/hardware"]
    assert {req.method for req in seen} == {"GET"}
    for req in seen:
        assert dict(req.url.params) == {}
    assert first.query == ""
    assert first.total == BROWSE_MAX_TOTAL
    assert len(first.results) == BROWSE_MAX_TOTAL
    objects = [r for r in first.results if r.entity_type == "object"]
    assert len(objects) == BROWSE_PER_COLLECTION
    assert [r.entity_id for r in objects] == ["obj_0", "obj_1", "obj_2"]
    assert [r.entity_id for r in first.results
            if r.entity_type == "hardware"] == ["hw_0"]
    second = run(reader(handle).browse())
    assert [(r.entity_type, r.entity_id) for r in second.results] == [
        (r.entity_type, r.entity_id) for r in first.results]


def test_browse_explicit_type_single_collection():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json=[browse_item("proj_1", "Bouw")])

    res = run(reader(handle).browse(type="projects"))
    assert [req.url.path for req in seen] == ["/api/v1/projects"]
    assert res.total == 1
    assert res.results[0].entity_type == "project"
    assert res.results[0].provenance.source_type == "user-created"


def test_browse_skips_missing_collections():
    def handle(request):
        if request.url.path == "/api/v1/objects":
            return httpx.Response(200, json=[browse_item("obj_1")])
        return httpx.Response(404, json={"detail": "Not Found"})

    res = run(reader(handle).browse())
    assert res.total == 1
    assert res.results[0].entity_id == "obj_1"


def test_browse_explicit_missing_collection_is_unavailable():
    def handle(request):
        return httpx.Response(404, json={"detail": "Not Found"})

    with pytest.raises(InventoryUnavailable):
        run(reader(handle).browse(type="hardware"))


def test_browse_invalid_type_refused():
    rec = Recorder()
    for bad in ["conversations", "relationships"]:
        with pytest.raises(InventoryRefusedError):
            run(reader(rec).browse(type=bad))
    assert rec.requests == []


def test_browse_invalid_list_shape_is_unavailable():
    rec = Recorder({"not": "a list"})
    with pytest.raises(InventoryUnavailable):
        run(reader(rec).browse())


def test_browse_empty_database_is_empty():
    def handle(request):
        return httpx.Response(200, json=[])

    res = run(reader(handle).browse())
    assert res.total == 0
    assert res.results == []


def test_search_invalid_list_shape_is_unavailable():
    rec = Recorder({"query": "moer", "results": []})
    with pytest.raises(InventoryUnavailable):
        run(reader(rec).search("moer"))


def test_search_result_cap():
    def handle(request):
        return httpx.Response(200, json=[
            list_item(f"obj_{i}", f"Ding {i} moer", "vulling")
            for i in range(MAX_SEARCH_RESULTS + 30)])

    res = run(reader(handle).search("moer", type="objects"))
    assert res.total == MAX_SEARCH_RESULTS
    assert len(res.results) == MAX_SEARCH_RESULTS


def test_search_provenance_fallback_is_unverified():
    def handle(request):
        return httpx.Response(200, json=[
            {"id": "obj_1", "name": "Moer", "description": "rvs"},
            {"id": "obj_2", "name": "Moer", "description": "rvs",
             "provenance": {"source_type": "user-created"}},
            {"id": "obj_3", "name": "Schroef", "description": "verzinkt"}])

    res = run(reader(handle).search("moer", type="objects"))
    assert res.total == 2
    for result in res.results:
        assert result.provenance.human_verified is False


def test_get_request():
    rec = Recorder({"id": "proj_abc", "name": "Bouw", "description": "d",
                    "status": "active", "provenance": PROV,
                    "created_at": "t", "updated_at": "t"})
    res = run(reader(rec).get("project", "proj_abc"))
    req = rec.requests[0]
    assert req.method == "GET"
    assert req.url.path == "/api/v1/projects/proj_abc"
    assert res.entity_type == "project"
    assert res.title == "Bouw"
    assert res.details["status"] == "active"


def test_graph_request():
    rec = Recorder({"entity_id": "obj_abc", "depth": 2, "nodes": [], "edges": []})
    res = run(reader(rec).graph("obj_abc", depth=2))
    req = rec.requests[0]
    assert req.method == "GET"
    assert req.url.path == "/api/v1/graph"
    assert req.url.params["entity_id"] == "obj_abc"
    assert req.url.params["depth"] == "2"
    assert res.depth == 2


def test_provenance_preserved():
    def handle(request):
        if request.url.path == "/api/v1/objects":
            return httpx.Response(200, json=[list_item()])
        return httpx.Response(200, json=[])

    res = run(reader(handle).search("moer"))
    assert res.results[0].provenance.source_type == "user-created"
    assert res.results[0].provenance.human_verified is True

    rec = Recorder({"id": "obj_abc", "name": "Moer", "description": "",
                    "quantity": 1, "provenance": PROV,
                    "created_at": "t", "updated_at": "t"})
    res = run(reader(rec).get("object", "obj_abc"))
    assert res.provenance.creator_id == "user"

    rec = Recorder({"entity_id": "obj_abc", "depth": 1,
                    "nodes": [{"entity_type": "object", "entity_id": "obj_abc",
                               "title": "Moer", "provenance": PROV}],
                    "edges": [{"id": "rel_x", "from_id": "obj_abc",
                               "predicate": "used_in", "to_id": "proj_y",
                               "metadata": {}, "provenance": PROV}]})
    res = run(reader(rec).graph("obj_abc"))
    assert res.nodes[0].provenance.source_type == "user-created"
    assert res.edges[0].predicate == "used_in"
    assert res.edges[0].provenance.human_verified is True


# --- failure modes ---------------------------------------------------------------

def test_timeout_is_unavailable():
    def slow(request):
        raise httpx.ConnectTimeout("too slow")
    with pytest.raises(InventoryUnavailable):
        run(reader(slow, timeout=5.0).search("moer"))


def test_connection_failure_is_unavailable():
    def dead(request):
        raise httpx.ConnectError("refused")
    with pytest.raises(InventoryUnavailable):
        run(reader(dead).get("object", "obj_abc"))


def test_server_error_is_unavailable():
    rec = Recorder({"detail": "boom"}, status=500)
    with pytest.raises(InventoryUnavailable):
        run(reader(rec).search("moer"))


def test_get_missing_returns_none():
    rec = Recorder({"detail": "not found"}, status=404)
    assert run(reader(rec).get("object", "obj_nope")) is None


# --- local refusals (no HTTP at all) ------------------------------------------------

NON_LOOPBACK = [
    "http://example.com:8080",
    "http://192.168.1.5:8080",
    "http://10.0.0.2/",
    "http://[::2]:8080/",
    "https://127.0.0.1:8080/",
    "http://127.0.0.1.evil.com/",
    "http://user@127.0.0.1:8080/",
    "file:///tmp/x",
    "not-a-url",
    "",
]


@pytest.mark.parametrize("url", NON_LOOPBACK)
def test_non_loopback_base_url_refused(url):
    def fail(request):  # pragma: no cover
        raise AssertionError("no HTTP must happen")
    with pytest.raises(InventoryRefusedError):
        InventoryReader(base_url=url, transport=httpx.MockTransport(fail))


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8080",
    "http://localhost:8080/",
    "http://[::1]:8080",
    "http://127.0.0.1",
])
def test_loopback_base_urls_accepted(url):
    def fail(request):  # pragma: no cover
        raise AssertionError("no HTTP must happen")
    InventoryReader(base_url=url, transport=httpx.MockTransport(fail))


def test_invalid_entity_id_refused():
    rec = Recorder()
    for bad in ["", "   ", "proj", "OBJ_ABC", "../etc/passwd",
                "http://127.0.0.1:8080/api/v1/objects/obj_abc", None, 123]:
        with pytest.raises(InventoryRefusedError):
            run(reader(rec).graph(bad))
        with pytest.raises(InventoryRefusedError):
            run(reader(rec).get("object", bad))
    assert rec.requests == []


def test_prefix_valid_id_travels_encoded():
    rec = Recorder({"entity_id": "obj_abc", "depth": 1, "nodes": [], "edges": []})
    res = run(reader(rec).graph("obj_abc;DROP"))
    assert rec.requests[0].method == "GET"
    assert res.depth == 1


def test_bad_depth_refused():
    rec = Recorder()
    for bad in [0, 3, 99, -1, True, "2", None, 1.5]:
        with pytest.raises(InventoryRefusedError):
            run(reader(rec).graph("obj_abc", depth=bad))
    assert rec.requests == []


def test_bad_query_refused():
    rec = Recorder()
    for bad in ["", "   ", None, 123, "x" * 201]:
        with pytest.raises(InventoryRefusedError):
            run(reader(rec).search(bad))
    assert rec.requests == []


def test_unknown_search_type_refused():
    rec = Recorder()
    with pytest.raises(InventoryRefusedError):
        run(reader(rec).search("moer", type="conversations"))
    assert rec.requests == []


def test_unsupported_get_types_refused():
    rec = Recorder()
    for entity_type in ["relationship", "event", "conversations", ""]:
        with pytest.raises(InventoryRefusedError):
            run(reader(rec).get(entity_type, "rel_abc"))
    assert rec.requests == []


# --- GET-only proof ------------------------------------------------------------------

def test_only_get_is_used():
    seen = []

    def dispatch(request):
        seen.append(request)
        if request.url.path == "/api/v1/objects":
            return httpx.Response(200, json=[list_item()])
        if request.url.path == "/api/v1/graph":
            return httpx.Response(200, json={"entity_id": "obj_abc", "depth": 1,
                                             "nodes": [], "edges": []})
        return httpx.Response(200, json=[])

    r = InventoryReader(base_url="http://127.0.0.1:8080",
                        transport=httpx.MockTransport(dispatch))
    run(r.search("moer"))
    run(r.graph("obj_abc"))
    assert seen, "expected requests to inspect"
    assert {req.method for req in seen} == {"GET"}
    for name in ("post", "put", "patch", "delete"):
        assert not hasattr(r, name), f"reader must not offer {name}"


def test_extra_fields_tolerated():
    def handle(request):
        if request.url.path == "/api/v1/objects":
            return httpx.Response(200, json=[dict(
                list_item(), brand_new_section=[1, 2])])
        return httpx.Response(200, json=[])

    res = run(reader(handle).search("moer"))
    assert res.total == 1
    assert res.results[0].entity_id == "obj_abc"


def test_env_override_and_defaults(monkeypatch):
    def fail(request):  # pragma: no cover
        raise AssertionError("no HTTP must happen")
    transport = httpx.MockTransport(fail)
    monkeypatch.delenv("INVENTORY_BASE_URL", raising=False)
    assert InventoryReader(transport=transport).base_url == "http://127.0.0.1:8080"
    assert InventoryReader(transport=transport).timeout == 5.0
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://localhost:8080")
    assert InventoryReader(transport=transport).base_url == "http://localhost:8080"
    assert InventoryReader(transport=transport, timeout=99).timeout == 5.0
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://example.com/")
    with pytest.raises(InventoryRefusedError):
        InventoryReader(transport=transport)


# --- M5.3: full M3 entity coverage ---------------------------------------------------

M3_TYPES = {
    "hardware": ("hardware", "hw_x"),
    "sensor": ("sensors", "sns_x"),
    "camera": ("cameras", "cam_x"),
    "location": ("locations", "loc_x"),
    "model": ("models", "mod_x"),
    "task": ("tasks", "task_x"),
    "actuator": ("actuators", "act_x"),
}


@pytest.mark.parametrize("entity_type,path", [
    ("hardware", "hardware"), ("sensor", "sensors"), ("camera", "cameras"),
    ("location", "locations"), ("model", "models"), ("task", "tasks"),
    ("actuator", "actuators"),
])
def test_search_type_filter_per_m3_type(entity_type, path):
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json=[
            {"id": "x_1", "name": "Unieke vondst", "description": "d",
             "provenance": PROV}])

    res = run(reader(handle).search("uniek", type=path))
    assert [req.url.path for req in seen] == [f"/api/v1/{path}"]
    assert "type" not in seen[0].url.params
    assert res.total == 1
    assert res.results[0].entity_type == entity_type


@pytest.mark.parametrize("entity_type,path,example_id", [
    ("hardware", "hardware", "hw_x"), ("sensor", "sensors", "sns_x"),
    ("camera", "cameras", "cam_x"), ("location", "locations", "loc_x"),
    ("model", "models", "mod_x"), ("task", "tasks", "task_x"),
    ("actuator", "actuators", "act_x"),
])
def test_get_per_m3_type(entity_type, path, example_id):
    rec = Recorder({"id": example_id, "name": "Naam", "description": "d",
                    "provenance": PROV, "created_at": "t", "updated_at": "t"})
    res = run(reader(rec).get(entity_type, example_id))
    assert rec.requests[0].method == "GET"
    assert rec.requests[0].url.path == f"/api/v1/{path}/{example_id}"
    assert res.entity_type == entity_type
    assert res.entity_id == example_id
    assert res.title == "Naam"
    assert res.provenance.source_type == "user-created"


def test_search_without_type_represents_m3_results():
    seen = []

    def handle(request):
        seen.append(request)
        if request.url.path == "/api/v1/hardware":
            return httpx.Response(200, json=[
                {"id": "hw_1", "name": "Unieke Pi", "description": "s",
                 "provenance": PROV}])
        if request.url.path == "/api/v1/tasks":
            return httpx.Response(200, json=[
                {"id": "task_1", "name": "Unieke ronde", "description": "s",
                 "provenance": PROV}])
        return httpx.Response(200, json=[])

    res = run(reader(handle).search("uniek"))
    for req in seen:
        assert "type" not in req.url.params
    assert {(r.entity_type, r.entity_id) for r in res.results} == {
        ("hardware", "hw_1"), ("task", "task_1")}


@pytest.mark.parametrize("example_id", [
    "hw_x", "sns_x", "cam_x", "loc_x", "mod_x", "task_x", "act_x",
])
def test_graph_per_m3_prefix(example_id):
    rec = Recorder({"entity_id": example_id, "depth": 1, "nodes": [], "edges": []})
    res = run(reader(rec).graph(example_id))
    assert rec.requests[0].url.params["entity_id"] == example_id
    assert res.entity_id == example_id


@pytest.mark.parametrize("bad", ["hw", "sns", "cam", "loc", "mod", "task", "act",
                                 "HW_X", "actuator_x", "model_x"])
def test_m3_adjacent_invalid_prefixes_refused(bad):
    rec = Recorder()
    with pytest.raises(InventoryRefusedError):
        run(reader(rec).graph(bad))
    assert rec.requests == []


def test_unknown_search_type_still_refused():
    rec = Recorder()
    with pytest.raises(InventoryRefusedError):
        run(reader(rec).search("q", type="conversations"))
    assert rec.requests == []
