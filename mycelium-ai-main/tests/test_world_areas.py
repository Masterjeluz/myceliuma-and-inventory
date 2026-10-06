"""Area grouping derivation for /world (contains/part_of only).

Pure-function tests over graph payloads: no database, no server,
no coordinates invented. Direction, filtering and bounds only.
"""
from coordinator.app.main import (
    MAX_AREAS,
    MAX_AREA_MEMBERS,
    _world_areas,
)


def _node(id, label="", type="object"):
    return {"id": id, "type": type, "label": label or id,
            "source": "inventory", "metadata": {}}


def _edge(frm, predicate, to):
    return {"from": frm, "predicate": predicate, "to": to,
            "provenance": {}}


def test_contains_flows_area_to_member():
    graph = {"nodes": [_node("loc_a", "Werkplaats", "location"),
                       _node("obj_1", "Moer")],
             "edges": [_edge("loc_a", "contains", "obj_1")]}
    assert _world_areas(graph) == [
        {"id": "loc_a", "label": "Werkplaats", "members": ["obj_1"]}]


def test_part_of_flows_member_to_area():
    graph = {"nodes": [_node("loc_a", "Werkplaats", "location"),
                       _node("obj_1", "Moer")],
             "edges": [_edge("obj_1", "part_of", "loc_a")]}
    assert _world_areas(graph) == [
        {"id": "loc_a", "label": "Werkplaats", "members": ["obj_1"]}]


def test_other_predicates_never_become_areas():
    graph = {"nodes": [_node("obj_1", "Moer"), _node("obj_2", "Bout")],
             "edges": [_edge("obj_1", "related_to", "obj_2"),
                       _edge("obj_1", "uses", "obj_2"),
                       _edge("obj_2", "led_to", "obj_1")]}
    assert _world_areas(graph) == []


def test_unknown_members_self_loops_and_empty_drop_out():
    graph = {"nodes": [_node("loc_a", "Werkplaats", "location"),
                       _node("obj_1", "Moer")],
             "edges": [_edge("loc_a", "contains", "obj_ghost"),
                       _edge("loc_a", "contains", "loc_a"),
                       _edge("loc_empty", "contains", "obj_ghost")]}
    assert _world_areas(graph) == []
    assert _world_areas({"nodes": [], "edges": []}) == []
    assert _world_areas({}) == []


def test_label_falls_back_to_id_and_output_bounded():
    nodes = [_node(f"obj_{i}") for i in range(5)]
    edges = [_edge("loc_x", "contains", f"obj_{i}") for i in range(5)]
    areas = _world_areas({"nodes": nodes, "edges": edges})
    assert areas[0]["label"] == "loc_x"[:24]
    big = {"nodes": [_node(f"m_{i}") for i in range(MAX_AREA_MEMBERS + 10)],
           "edges": [_edge("loc_big", "contains", f"m_{i}")
                     for i in range(MAX_AREA_MEMBERS + 10)]}
    assert len(_world_areas(big)[0]["members"]) == MAX_AREA_MEMBERS
    many = {"nodes": [_node("obj_1")],
            "edges": [_edge(f"loc_{i}", "contains", "obj_1")
                      for i in range(MAX_AREAS + 10)]}
    assert len(_world_areas(many)) == MAX_AREAS
