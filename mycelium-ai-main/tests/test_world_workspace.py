"""Workspace scoping for /world (roots + 1-hop closure, no model).

Pure filter tests need no database. Store-backed tests use tmp
databases: workspace roots come from existing conversations,
missions, context records and research links only.
"""
import coordinator.app.main as main_mod
from coordinator.app.main import (
    _world_quest_trails_html,
    _world_workspace_filter,
    _world_workspace_roots,
)


def _node(id, type="object", label="", project_ref=""):
    metadata = {}
    if project_ref:
        metadata["project_ref"] = project_ref
    return {"id": id, "type": type, "label": label or id,
            "source": "inventory", "metadata": metadata}


def _edge(frm, predicate, to):
    return {"from": frm, "predicate": predicate, "to": to,
            "provenance": {}}


def _graph():
    return {
        "nodes": [_node("proj_camper", "project", "Camper"),
                  _node("obj_moer", "object", "Moer"),
                  _node("loc_werk", "location", "Werkplaats"),
                  _node("obj_far", "object", "Far"),
                  _node("mem_1", "memory", "Notitie",
                         project_ref="camper")],
        "edges": [_edge("loc_werk", "contains", "obj_moer"),
                  _edge("proj_camper", "part_of", "loc_werk"),
                  _edge("obj_far", "related_to", "obj_moer"),
                  _edge("mem_1", "remembers", "obj_moer")],
    }


def test_filter_keeps_roots_and_closure():
    out = _world_workspace_filter(_graph(), "camper", {"proj_camper"})
    ids = {node["id"] for node in out["nodes"]}
    assert "proj_camper" in ids  # root
    assert "loc_werk" in ids  # neighbour via part_of edge
    assert "mem_1" in ids  # metadata.project_ref == wid
    assert "obj_moer" in ids  # neighbour via mem_1 remembers edge
    assert "obj_far" not in ids  # only reachable past kept nodes


def test_filter_project_ref_overlay_is_root():
    out = _world_workspace_filter(_graph(), "camper", set())
    ids = {node["id"] for node in out["nodes"]}
    assert "mem_1" in ids
    assert "obj_moer" in ids  # neighbour via remembers edge
    assert "proj_camper" not in ids
    assert "loc_werk" not in ids
    assert "obj_far" not in ids


def test_filter_edges_need_both_ends():
    out = _world_workspace_filter(_graph(), "camper", {"proj_camper"})
    pairs = {(edge["from"], edge["to"]) for edge in out["edges"]}
    assert ("proj_camper", "loc_werk") in pairs
    assert not any("obj_far" in pair for pair in pairs)
    # original dict untouched
    assert len(_graph()["edges"]) == 4


def test_filter_empty_graph_and_empty_roots():
    assert _world_workspace_filter(
        {"nodes": [], "edges": []}, "camper", set()) == {
            "nodes": [], "edges": []}
    out = _world_workspace_filter(_graph(), "camper", set())
    # only project_ref overlay root + its neighbour
    assert {node["id"] for node in out["nodes"]} == {
        "mem_1", "obj_moer"}


def _seed_quests():
    from coordinator.app.quests import new_quest, save_quest
    save_quest(new_quest("Inside quest", [
        {"key": "s1", "label": "Pak moer", "kind": "entity",
         "ref": "obj_moer"}]))
    save_quest(new_quest("Outside quest", [
        {"key": "s1", "label": "Pak ver ding", "kind": "entity",
         "ref": "obj_far"}]))
    save_quest(new_quest("Seed quest", [
        {"key": "s1", "label": "Algemeen", "kind": "note",
         "ref": ""}]))


def test_quest_trails_do_not_leak_across_workspaces(tmp_path,
                                                    monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "queue.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "chat.db"))
    _seed_quests()
    scoped = _world_quest_trails_html(
        keep={"obj_moer", "proj_camper", "loc_werk"})
    assert "Inside quest" in scoped
    assert "Seed quest" in scoped  # no refs: global seed
    assert "Outside quest" not in scoped
    unscoped = _world_quest_trails_html(keep=None)
    assert "Inside quest" in unscoped
    assert "Outside quest" in unscoped


def test_roots_come_from_workspace_stores(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "queue.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "chat.db"))
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "fab"))
    from coordinator.app.workspaces import ensure_conversation
    conv = ensure_conversation("camper", "Camper praat")
    conv_id = conv["conversation_id"]
    mission = main_mod._executor().create(
        conv_id, "Isoleer de camper",
        [{"kind": "research", "description": "zoek isolatie"}],
        max_steps=5,
        context_records=[{"entity_type": "project",
                          "entity_id": "proj_camper",
                          "title": "Camper"}])
    roots = _world_workspace_roots("camper")
    assert conv_id in roots
    assert mission.mission_id in roots
    assert "proj_camper" in roots  # mission-context link
    assert _world_workspace_roots("leeg-nest") == set()
