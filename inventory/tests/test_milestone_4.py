"""Tests voor INVENTory Milestone 4.1 — FTS5 foundation (database-laag).

Uitsluitend tijdelijke databases via INVENTORY_DATABASE_PATH. Geen echte
gebruikersdata wordt geraakt. M4.1 bouwt geen publieke search-endpoint;
deze tests bevragen de FTS-tabellen direct via SQL.
"""
import os

from app.database import (
    FTS_TABLES,
    connection,
    dump,
    init_database,
    rebuild_fts,
)

PROV = dump({"source_type": "user-created", "creator_id": "test",
             "human_verified": True})


def use_tmp_db(tmp_path, name="test_fts.db"):
    os.environ["INVENTORY_DATABASE_PATH"] = str(tmp_path / name)
    init_database()


def match_ids(table, query):
    with connection() as db:
        rows = db.execute(
            f"SELECT entity_id FROM {table} WHERE {table} MATCH ?", (query,)
        ).fetchall()
    return sorted(row["entity_id"] for row in rows)


# =============================================================================
# FTS-tabellen bestaan
# =============================================================================

def test_fts_tables_exist(tmp_path):
    use_tmp_db(tmp_path)
    with connection() as db:
        tables = [row["name"] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    for fts in FTS_TABLES:
        assert fts in tables


def test_fts_triggers_exist(tmp_path):
    use_tmp_db(tmp_path)
    with connection() as db:
        triggers = [row["name"] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()]
    for base in ("objects", "projects", "ideas", "relationships"):
        for operation in ("insert", "delete", "update"):
            assert f"{base}_fts_{operation}" in triggers


# =============================================================================
# Bestaande records indexeerbaar (init/rebuild indexeert mee)
# =============================================================================

def test_existing_records_indexed_on_init(tmp_path):
    os.environ["INVENTORY_DATABASE_PATH"] = str(tmp_path / "test_fts.db")
    init_database()
    # Records die vóór (her-)initialisatie bestaan, moeten daarna vindbaar zijn.
    with connection() as db:
        db.execute(
            "INSERT INTO objects (id, name, description, quantity, provenance,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("obj_legacy", "Legacy Moer", "oude voorraad", 3, PROV, "t", "t"),
        )
        db.execute(
            "INSERT INTO projects (id, name, description, status, provenance,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("proj_legacy", "Legacy Printer", "oude build", "active", PROV, "t", "t"),
        )
        db.execute(
            "INSERT INTO ideas (id, name, description, status, provenance,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("idea_legacy", "Legacy Droger", "oud plan", "raw", PROV, "t", "t"),
        )
    init_database()
    assert match_ids("objects_fts", "Legacy") == ["obj_legacy"]
    assert match_ids("projects_fts", "Legacy") == ["proj_legacy"]
    assert match_ids("ideas_fts", "Legacy") == ["idea_legacy"]


# =============================================================================
# Nieuwe records, updates, deletes
# =============================================================================

def test_new_records_auto_indexed(tmp_path):
    use_tmp_db(tmp_path)
    with connection() as db:
        db.execute(
            "INSERT INTO objects (id, name, description, quantity, provenance,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("obj_step", "Nema Stappenmotor", "1.8 graden 12V", 2, PROV, "t", "t"),
        )
        db.execute(
            "INSERT INTO projects (id, name, description, status, provenance,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("proj_step", "Printer Build", "stappenmotor montage", "planned",
             PROV, "t", "t"),
        )
        db.execute(
            "INSERT INTO ideas (id, name, description, status, provenance,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("idea_step", "Filament Idee", "droger met stappenmotor", "raw",
             PROV, "t", "t"),
        )
    assert match_ids("objects_fts", "Stappenmotor") == ["obj_step"]
    assert match_ids("projects_fts", "stappenmotor") == ["proj_step"]
    assert match_ids("ideas_fts", "stappenmotor") == ["idea_step"]


def test_update_syncs_fts(tmp_path):
    use_tmp_db(tmp_path)
    with connection() as db:
        db.execute(
            "INSERT INTO objects (id, name, description, quantity, provenance,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("obj_upd", "Oude Naam", "beschrijving", 1, PROV, "t", "t"),
        )
    assert match_ids("objects_fts", "Oude") == ["obj_upd"]
    with connection() as db:
        db.execute("UPDATE objects SET name=? WHERE id=?", ("Nieuwe Naam", "obj_upd"))
    assert match_ids("objects_fts", "Oude") == []
    assert match_ids("objects_fts", "Nieuwe") == ["obj_upd"]


def test_delete_syncs_fts(tmp_path):
    use_tmp_db(tmp_path)
    with connection() as db:
        db.execute(
            "INSERT INTO projects (id, name, description, status, provenance,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("proj_del", "Weg Project", "verdwijnt", "planned", PROV, "t", "t"),
        )
    assert match_ids("projects_fts", "Weg") == ["proj_del"]
    with connection() as db:
        db.execute("DELETE FROM projects WHERE id=?", ("proj_del",))
    assert match_ids("projects_fts", "Weg") == []


def test_relationships_metadata_indexed(tmp_path):
    use_tmp_db(tmp_path)
    with connection() as db:
        db.execute(
            "INSERT INTO relationships (id, from_id, predicate, to_id, metadata,"
            " provenance, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("rel_meta", "obj_a", "stored_in", "proj_b",
             dump({"basis": "werkplaatsplank"}), PROV, "t"),
        )
    assert match_ids("relationships_fts", "stored_in") == ["rel_meta"]
    assert match_ids("relationships_fts", "werkplaatsplank") == ["rel_meta"]


# =============================================================================
# Rebuild en canonieke integriteit
# =============================================================================

def test_rebuild_restores_and_reports_counts(tmp_path):
    use_tmp_db(tmp_path)
    with connection() as db:
        db.execute(
            "INSERT INTO objects (id, name, description, quantity, provenance,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("obj_rb", "Rebuild Moer", "test", 1, PROV, "t", "t"),
        )
        db.execute("DELETE FROM objects_fts")
    assert match_ids("objects_fts", "Rebuild") == []
    counts = rebuild_fts()
    assert counts["objects_fts"] == 1
    assert match_ids("objects_fts", "Rebuild") == ["obj_rb"]
    # Rebuild is idempotent: geen duplicaten.
    counts_again = rebuild_fts()
    assert counts_again == counts
    assert match_ids("objects_fts", "Rebuild") == ["obj_rb"]


def test_canonical_tables_intact(tmp_path):
    use_tmp_db(tmp_path)
    with connection() as db:
        db.execute(
            "INSERT INTO objects (id, name, description, quantity, provenance,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("obj_int", "Intact Ding", "blijft", 5, PROV, "t1", "t2"),
        )
    rebuild_fts()
    with connection() as db:
        row = db.execute("SELECT * FROM objects WHERE id=?", ("obj_int",)).fetchone()
        columns = [r["name"] for r in db.execute("PRAGMA table_info(objects)").fetchall()]
    assert row["name"] == "Intact Ding"
    assert row["quantity"] == 5
    assert row["created_at"] == "t1"
    assert columns == ["id", "name", "description", "quantity",
                       "provenance", "created_at", "updated_at"]


# =============================================================================
# M4.2 — sanitize_fts_query()
# =============================================================================

def test_sanitize_normal_text():
    from app.database import sanitize_fts_query
    assert sanitize_fts_query("stappenmotor") == '"stappenmotor"'
    assert sanitize_fts_query("  printer  build ") == '"printer" "build"'


def test_sanitize_empty_and_whitespace():
    from app.database import sanitize_fts_query
    assert sanitize_fts_query("") is None
    assert sanitize_fts_query("   ") is None
    assert sanitize_fts_query(None) is None
    assert sanitize_fts_query(123) is None


def test_sanitize_neutralises_special_syntax():
    from app.database import sanitize_fts_query
    assert sanitize_fts_query('"quoted"') == '"quoted"'
    assert sanitize_fts_query("a*b (c) OR d:e") == '"a*b" "(c)" "OR" "d:e"'
    assert sanitize_fts_query('"""') is None
    assert sanitize_fts_query("x" * 201) is None


def test_search_fts_limit(tmp_path):
    from app.database import sanitize_fts_query, search_fts
    use_tmp_db(tmp_path)
    with connection() as db:
        for i in range(60):
            db.execute(
                "INSERT INTO objects (id, name, description, quantity, provenance,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"obj_bulk{i}", f"Bulk Ding {i}", "bulkterm voorraad", 1,
                 PROV, "t", "t"),
            )
    hits = search_fts(sanitize_fts_query("bulkterm"))
    assert 0 < len(hits) <= 50


# =============================================================================
# M4.2 — GET /api/v1/search
# =============================================================================

def _search_client(tmp_path):
    import importlib
    os.environ["INVENTORY_DATABASE_PATH"] = str(tmp_path / "test_search.db")
    import app.database as db_mod
    import app.main as main_mod
    importlib.reload(db_mod)
    importlib.reload(main_mod)
    from fastapi.testclient import TestClient
    return TestClient(main_mod.app)


def _seed_search_data(client):
    obj = client.post("/api/v1/objects",
                      json={"name": "Zoek Moer", "description": "uniekzoekterm bout"}).json()
    proj = client.post("/api/v1/projects",
                       json={"name": "Zoek Project", "description": "uniekzoekterm plan",
                             "status": "active"}).json()
    idea = client.post("/api/v1/ideas",
                       json={"name": "Zoek Idee", "description": "uniekzoekterm gedachte"}).json()
    rel = client.post("/api/v1/relationships",
                      json={"from_id": obj["id"], "predicate": "used_in",
                            "to_id": proj["id"],
                            "metadata": {"notitie": "uniekzoekterm koppeling"}}).json()
    return obj, proj, idea, rel


def test_search_finds_all_types_without_filter(tmp_path):
    with _search_client(tmp_path) as client:
        obj, proj, idea, rel = _seed_search_data(client)
        res = client.get("/api/v1/search", params={"q": "uniekzoekterm"})
        assert res.status_code == 200
        data = res.json()
        assert data["query"] == "uniekzoekterm"
        found = {(r["entity_type"], r["entity_id"]) for r in data["results"]}
        assert ("object", obj["id"]) in found
        assert ("project", proj["id"]) in found
        assert ("idea", idea["id"]) in found
        assert ("relationship", rel["id"]) in found
        assert data["total"] == len(data["results"])
        for result in data["results"]:
            assert result["title"] and result["entity_id"]
            assert result["provenance"]["source_type"] in (
                "user-created", "imported", "ai-generated",
                "sensor-observed", "external-source")


def test_search_type_filters(tmp_path):
    with _search_client(tmp_path) as client:
        obj, proj, idea, rel = _seed_search_data(client)
        expectations = {
            "objects": ("object", obj["id"]),
            "projects": ("project", proj["id"]),
            "ideas": ("idea", idea["id"]),
            "relationships": ("relationship", rel["id"]),
        }
        for entity_type, expected in expectations.items():
            res = client.get("/api/v1/search",
                             params={"q": "uniekzoekterm", "type": entity_type})
            assert res.status_code == 200
            found = {(r["entity_type"], r["entity_id"]) for r in res.json()["results"]}
            assert found == {expected}


def test_search_unknown_type_rejected(tmp_path):
    with _search_client(tmp_path) as client:
        res = client.get("/api/v1/search", params={"q": "iets", "type": "conversations"})
        assert res.status_code == 422


def test_search_empty_and_whitespace_rejected(tmp_path):
    with _search_client(tmp_path) as client:
        assert client.get("/api/v1/search", params={"q": ""}).status_code == 422
        assert client.get("/api/v1/search", params={"q": "   "}).status_code == 422
        assert client.get("/api/v1/search").status_code == 422


def test_search_special_chars_do_not_crash(tmp_path):
    with _search_client(tmp_path) as client:
        _seed_search_data(client)
        for tricky in ['"quote"', "a*b (c) OR d:e", "' OR '1'='1", "--", "x" * 201]:
            res = client.get("/api/v1/search", params={"q": tricky})
            assert res.status_code in (200, 422)


def test_search_injection_attempt_is_literal(tmp_path):
    with _search_client(tmp_path) as client:
        _seed_search_data(client)
        res = client.get("/api/v1/search", params={"q": '" OR 1=1 --'})
        assert res.status_code == 200
        assert res.json()["results"] == []


# =============================================================================
# M4.3 — GET /api/v1/graph
# =============================================================================

def _seed_chain(client):
    obj = client.post("/api/v1/objects",
                      json={"name": "Graaf Moer", "description": "keten"}).json()
    proj = client.post("/api/v1/projects",
                       json={"name": "Graaf Project", "description": "keten"}).json()
    idea = client.post("/api/v1/ideas",
                       json={"name": "Graaf Idee", "description": "keten"}).json()
    rel1 = client.post("/api/v1/relationships",
                       json={"from_id": obj["id"], "predicate": "used_in",
                             "to_id": proj["id"]}).json()
    rel2 = client.post("/api/v1/relationships",
                       json={"from_id": proj["id"], "predicate": "led_to",
                             "to_id": idea["id"]}).json()
    return obj, proj, idea, rel1, rel2


def test_graph_one_hop(tmp_path):
    with _search_client(tmp_path) as client:
        obj, proj, idea, rel1, rel2 = _seed_chain(client)
        res = client.get("/api/v1/graph",
                         params={"entity_id": obj["id"], "depth": 1})
        assert res.status_code == 200
        data = res.json()
        assert data["entity_id"] == obj["id"]
        assert data["depth"] == 1
        node_ids = {n["entity_id"] for n in data["nodes"]}
        assert node_ids == {obj["id"], proj["id"]}
        assert [e["id"] for e in data["edges"]] == [rel1["id"]]


def test_graph_two_hops(tmp_path):
    with _search_client(tmp_path) as client:
        obj, proj, idea, rel1, rel2 = _seed_chain(client)
        res = client.get("/api/v1/graph",
                         params={"entity_id": obj["id"], "depth": 2})
        assert res.status_code == 200
        data = res.json()
        node_ids = {n["entity_id"] for n in data["nodes"]}
        assert node_ids == {obj["id"], proj["id"], idea["id"]}
        assert {e["id"] for e in data["edges"]} == {rel1["id"], rel2["id"]}


def test_graph_invalid_depth_rejected(tmp_path):
    with _search_client(tmp_path) as client:
        obj, _, _, _, _ = _seed_chain(client)
        for bad in (0, -1, 3, 99):
            res = client.get("/api/v1/graph",
                             params={"entity_id": obj["id"], "depth": bad})
            assert res.status_code == 422
        res = client.get("/api/v1/graph",
                         params={"entity_id": obj["id"], "depth": "diep"})
        assert res.status_code == 422


def test_graph_cycle_terminates(tmp_path):
    with _search_client(tmp_path) as client:
        a = client.post("/api/v1/objects", json={"name": "Knoop A"}).json()
        b = client.post("/api/v1/objects", json={"name": "Knoop B"}).json()
        c = client.post("/api/v1/objects", json={"name": "Knoop C"}).json()
        client.post("/api/v1/relationships",
                    json={"from_id": a["id"], "predicate": "related_to",
                          "to_id": b["id"]})
        client.post("/api/v1/relationships",
                    json={"from_id": b["id"], "predicate": "related_to",
                          "to_id": c["id"]})
        client.post("/api/v1/relationships",
                    json={"from_id": c["id"], "predicate": "related_to",
                          "to_id": a["id"]})
        res = client.get("/api/v1/graph", params={"entity_id": a["id"], "depth": 2})
        assert res.status_code == 200
        data = res.json()
        assert {n["entity_id"] for n in data["nodes"]} == {a["id"], b["id"], c["id"]}
        assert len(data["edges"]) == 3


def test_graph_unknown_entity_404(tmp_path):
    with _search_client(tmp_path) as client:
        res = client.get("/api/v1/graph", params={"entity_id": "obj_bestaatniet"})
        assert res.status_code == 404
        assert client.get("/api/v1/graph", params={"entity_id": "  "}).status_code == 422
        assert client.get("/api/v1/graph").status_code == 422


def test_graph_predicates_and_provenance(tmp_path):
    with _search_client(tmp_path) as client:
        obj, proj, idea, rel1, rel2 = _seed_chain(client)
        res = client.get("/api/v1/graph",
                         params={"entity_id": proj["id"], "depth": 1})
        assert res.status_code == 200
        data = res.json()
        by_id = {e["id"]: e for e in data["edges"]}
        assert by_id[rel1["id"]]["predicate"] == "used_in"
        assert by_id[rel2["id"]]["predicate"] == "led_to"
        for node in data["nodes"]:
            assert node["title"] and node["entity_type"] in ("object", "project", "idea")
            assert node["provenance"]["source_type"]
        for edge in data["edges"]:
            assert edge["provenance"]["source_type"]


# =============================================================================
# M4.4 — server-rendered search & graph UI
# =============================================================================

def test_ui_home_has_searchbox(tmp_path):
    with _search_client(tmp_path) as client:
        res = client.get("/")
        assert res.status_code == 200
        assert 'action="/search"' in res.text
        assert 'name="q"' in res.text


def test_ui_search_results(tmp_path):
    with _search_client(tmp_path) as client:
        obj, _, _, _ = _seed_search_data(client)
        res = client.get("/search", params={"q": "uniekzoekterm"})
        assert res.status_code == 200
        assert "Zoek Moer" in res.text
        assert "object" in res.text
        assert f"/graph/{obj['id']}" in res.text
        assert "👤 User" in res.text or "User" in res.text


def test_ui_search_empty_and_unknown_type(tmp_path):
    with _search_client(tmp_path) as client:
        assert client.get("/search", params={"q": ""}).status_code == 200
        assert "zoekterm" in client.get("/search", params={"q": "   "}).text.lower()
        res = client.get("/search", params={"q": "iets", "type": "conversations"})
        assert res.status_code == 200
        assert "Unknown type" in res.text


def test_ui_graph_page(tmp_path):
    with _search_client(tmp_path) as client:
        obj, proj, _, _, _ = _seed_chain(client)
        res = client.get(f"/graph/{obj['id']}", params={"depth": 2})
        assert res.status_code == 200
        assert "Graaf Project" in res.text
        assert "used_in" in res.text
        assert f"/graph/{proj['id']}" in res.text
        assert "depth=1" in res.text and "depth=2" in res.text
        assert "👤 User" in res.text or "User" in res.text


def test_ui_graph_unknown_entity_404(tmp_path):
    with _search_client(tmp_path) as client:
        assert client.get("/graph/obj_bestaatniet").status_code == 404
