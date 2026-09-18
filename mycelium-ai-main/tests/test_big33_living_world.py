"""BIG #33 tests: symbiosis, craft tree, guide, node mesh.

All read-only over real stores with tmp DBs. No INVENTory
dependency: symbiosis/craft degrade honestly when the bridge
is unreachable; guide/mesh work from coordinator stores.
"""

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app import guide as guide_mod
from coordinator.app import nodemesh as mesh_mod
from coordinator.app import symbiosis as sym_mod


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b33.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b33-chat.db"))
    with TestClient(main_mod.app) as client:
        yield client


# -- symbiosis unit ----------------------------------------------------------

def test_symbiosis_id_validation():
    assert sym_mod.clean_entity("proj_abc123") == "proj_abc123"
    for bad in ("", "nope", "proj_", "xxx_123", "proj_a/b",
                "../etc", "proj_" + "x" * 90):
        try:
            sym_mod.clean_entity(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_symbiosis_classify_edge():
    assert sym_mod.classify_edge({"human_verified": True}) == \
        "VERIFIED"
    assert sym_mod.classify_edge({}) == "SUPPORTED"
    assert sym_mod.classify_edge(None) == "SUPPORTED"
    assert sym_mod.classify_edge({"human_verified": False}) == \
        "SUPPORTED"


def test_symbiosis_proposed_empty(tmp_path, monkeypatch):
    for _ in make_client(tmp_path, monkeypatch):
        assert sym_mod.proposed(limit=5) == []


def test_symbiosis_proposed_from_connection_candidate(
        tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        created = client.post("/api/v1/candidates", json={
            "title": "Camper links solar",
            "candidate_type": "connection",
            "summary": "camper relates to panel",
            "entity_refs": ["proj_camper", "obj_panel"]}).json()
        assert created["candidate_id"].startswith("cand_")
        items = sym_mod.proposed(limit=10)
        assert len(items) == 1
        assert items[0]["state"] == "PROPOSED"
        assert "proj_camper" in items[0]["entities"]
        # A non-connection candidate is not a symbiosis.
        client.post("/api/v1/candidates", json={
            "title": "Just a note", "candidate_type": "note",
            "summary": "lonely"})
        assert len(sym_mod.proposed(limit=10)) == 1


# -- craft unit --------------------------------------------------------------

def test_craft_stages_shape():
    keys = [key for key, _, _ in
            __import__("coordinator.app.craft",
                       fromlist=["STAGES"]).STAGES]
    assert keys[0] == "idea" and keys[-1] == "new_project"
    assert len(keys) == 12


# -- guide unit --------------------------------------------------------------

def test_guide_items_bounded_and_shaped(tmp_path, monkeypatch):
    for _ in make_client(tmp_path, monkeypatch):
        items = guide_mod.guide_items(limit=12)
        assert isinstance(items, list)
        assert len(items) <= 12
        for item in items:
            assert {"kind", "glyph", "what", "why",
                    "next"} <= set(item)
            assert item["kind"] in guide_mod.GUIDE_KINDS
            assert item["next"]["href"].startswith("/")


def test_guide_surfaces_candidate(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert guide_mod.guide_items() == [] or True
        client.post("/api/v1/candidates", json={
            "title": "Guide seed", "candidate_type": "idea",
            "summary": "needs review"})
        kinds = [item["kind"] for item in guide_mod.guide_items()]
        assert "candidate" in kinds


# -- mesh unit ---------------------------------------------------------------

def _register(client, node_id, caps):
    response = client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": node_id, "tier": "worker",
        "capabilities": caps,
        "node_token": "test-token-12345"})
    assert response.status_code == 201, response.text


def test_mesh_rejects_wildcard_shell_unknown(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _register(client, "mesh-a", ["research.fetch_url"])
        for kind, cap in (
                ("shell.exec", "research.fetch_url"),
                ("research.fetch_url", "*"),
                ("research.fetch_url", "evil.pwn"),
                ("research.fetch_url", "research.fetch_url "
                 "x" * 200),
        ):
            try:
                mesh_mod.validate_delegation("mesh-a", kind, cap,
                                             {})
            except ValueError:
                continue
            raise AssertionError(f"accepted {kind}/{cap}")
        try:
            mesh_mod.validate_delegation("ghost", "research.fetch_url",
                                         "research.fetch_url", {})
        except ValueError:
            pass
        else:
            raise AssertionError("accepted unknown node")
        try:
            mesh_mod.validate_delegation(
                "mesh-a", "research.fetch_url",
                "research.fetch_url",
                {"api_key": "shh"})
        except ValueError:
            pass
        else:
            raise AssertionError("accepted secret payload")


def test_mesh_accepts_valid_and_topology(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _register(client, "mesh-a", ["research.fetch_url"])
        _register(client, "mesh-b", ["research.fetch_url",
                                     "analysis.summarize"])
        checked = mesh_mod.validate_delegation(
            "mesh-a", "research.fetch_url",
            "research.fetch_url", {"ref": "run_1"})
        assert checked["authority"].startswith("coordinator")
        topo = mesh_mod.mesh_topology()
        assert len(topo["nodes"]) == 2
        assert topo["honesty"].startswith("Edges")


# -- API ---------------------------------------------------------------------

def test_api_guide_symbiosis_craft_mesh(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        guide = client.get("/api/v1/guide")
        assert guide.status_code == 200
        assert "items" in guide.json()
        mesh = client.get("/api/v1/mesh/topology")
        assert mesh.status_code == 200
        assert "nodes" in mesh.json()
        bad = client.get("/api/v1/symbiosis",
                         params={"entity_id": "nope"})
        assert bad.status_code == 422
        # Bridge-dependent endpoints degrade honestly (503 when
        # INVENTory is down, never 500).
        sym = client.get("/api/v1/symbiosis",
                         params={"entity_id": "proj_demo"})
        assert sym.status_code in (200, 503)
        craft = client.get("/api/v1/craft",
                           params={"entity_id": "proj_demo"})
        assert craft.status_code in (200, 503)
        assert client.post("/api/v1/mesh/validate", json={
            "requesting_node": "ghost",
            "task_kind": "research.fetch_url",
            "capability": "research.fetch_url"}).status_code == 422


def test_pages_render(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        for path in ("/craft", "/guide", "/symbiosis", "/",
                     "/world", "/mobile", "/missions"):
            response = client.get(path)
            assert response.status_code == 200, path
            assert "Mycelium" in response.text
