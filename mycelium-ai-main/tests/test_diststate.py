"""Distributed state tests (BIG #10, deel 1).

Envelope validation, stable ids, idempotent apply, duplicate
and out-of-order safety, revision conflicts, provenance,
cursor reads, bounded batches.
"""

import pytest

from coordinator.app.diststate import (
    DistStateRefusedError,
    apply_envelope,
    detect_conflict,
    entity_history,
    known_event_ids,
    list_conflicts,
    mergeable_update,
    new_conflict,
    new_envelope,
    payload_hash,
    read_log,
    resolve_conflict,
    save_conflict,
    save_envelope,
)
from coordinator.app.inventory_read import Provenance


def use_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "ds.db"))


def make_envelope(**overrides):
    record = {
        "origin_node_id": "node-a",
        "entity_id": "obj_1",
        "entity_type": "object",
        "event_type": "entity.observed",
        "entity_revision": "rev-1",
        "base_revision": "",
        "payload": {"note": "saw it"},
    }
    record.update(overrides)
    return new_envelope(**record)


def test_envelope_validation():
    envelope = make_envelope()
    assert envelope.event_id.startswith("dsevt_")
    assert envelope.provenance.human_verified is False
    assert envelope.epoch == 0
    for bad in ({"event_type": "nuke"},
                {"entity_id": ""},
                {"entity_type": ""},
                {"origin_node_id": ""},
                {"payload": {"command": "rm"}},
                {"payload": {"x": "y" * 1001}},
                {"payload": "not-a-dict"},
                {"epoch": -1}):
        with pytest.raises(DistStateRefusedError):
            make_envelope(**bad)
    assert payload_hash({"a": 1}) == payload_hash({"a": 1})
    assert payload_hash({"a": 1}) != payload_hash({"a": 2})


def test_idempotent_apply_and_duplicates(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    envelope = make_envelope()
    assert apply_envelope(envelope)["status"] == "applied"
    assert apply_envelope(envelope)["status"] == "duplicate"
    assert known_event_ids([envelope.event_id]) == {
        envelope.event_id}
    assert known_event_ids(["dsevt_missing"]) == set()
    history = entity_history("obj_1")
    assert len(history) == 1
    assert history[0].event_id == envelope.event_id


def test_out_of_order_safe(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    first = make_envelope(entity_revision="rev-1")
    second = make_envelope(entity_revision="rev-2",
                           base_revision="rev-1",
                           payload={"note": "later"})
    assert apply_envelope(second)["status"] == "applied"
    assert apply_envelope(first)["status"] == "applied"
    assert len(entity_history("obj_1")) == 2


def test_conflict_detected_and_preserved(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    base = make_envelope(entity_revision="rev-1")
    assert apply_envelope(base)["status"] == "applied"
    mine = make_envelope(origin_node_id="node-a",
                         entity_revision="rev-2a",
                         base_revision="rev-1",
                         payload={"color": "red"})
    theirs = make_envelope(origin_node_id="node-b",
                           entity_revision="rev-2b",
                           base_revision="rev-1",
                           payload={"color": "blue"})
    assert apply_envelope(mine)["status"] == "applied"
    outcome = apply_envelope(theirs)
    assert outcome["status"] == "conflict"
    conflicts = list_conflicts()
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.status == "open"
    assert conflict.first_origin == "node-a"
    assert conflict.second_origin == "node-b"
    # Both versions preserved, neither rewritten.
    history = entity_history("obj_1")
    assert len(history) == 3
    assert resolve_conflict(conflict.conflict_id, "resolved") is True
    assert resolve_conflict(conflict.conflict_id, "resolved") is False
    assert list_conflicts(status="open") == []
    with pytest.raises(DistStateRefusedError):
        resolve_conflict(conflict.conflict_id, "merge")
    with pytest.raises(DistStateRefusedError):
        list_conflicts(status="bogus")


def test_same_payload_no_conflict(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    apply_envelope(make_envelope(entity_revision="rev-1"))
    echo = make_envelope(origin_node_id="node-b",
                         entity_revision="rev-1",
                         payload={"note": "saw it"})
    assert apply_envelope(echo)["status"] == "applied"
    assert list_conflicts() == []


def test_mergeable_metadata_only():
    current = {"cursor": "5", "last_seen": "t"}
    merged = mergeable_update(
        current, {"cursor": "9", "last_seen": "t2"})
    assert merged == {"cursor": "9", "last_seen": "t2"}
    assert mergeable_update(current, {"color": "red"}) is None
    assert mergeable_update(current, "nope") is None


def test_cursor_read_bounded(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    for index in range(3):
        apply_envelope(make_envelope(
            entity_id=f"obj_{index}", payload={"n": index}))
    items, latest = read_log(after_rowid=0, limit=2)
    assert len(items) == 2
    assert latest == 3
    rest, _ = read_log(after_rowid=2, limit=100)
    assert len(rest) == 1
    assert rest[0]["entity_id"] == "obj_2"
    with pytest.raises(DistStateRefusedError):
        read_log(after_rowid="nope")
    with pytest.raises(DistStateRefusedError):
        apply_envelope("not-an-envelope")


def test_conflict_record_shape(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    conflict = new_conflict("obj_9", "rev-1", "dsevt_a",
                            "dsevt_b", "node-a", "node-b")
    assert conflict.conflict_id.startswith("dscon_")
    assert conflict.status == "open"
    save_conflict(conflict)
    assert len(list_conflicts()) == 1
    # No history yet: nothing to conflict with.
    assert detect_conflict(make_envelope(
        entity_id="obj_fresh")) is None
