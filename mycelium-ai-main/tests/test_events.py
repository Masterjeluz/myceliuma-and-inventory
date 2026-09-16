"""Event bus + notification tests (BIG #9).

Closed types, non-executable payloads, cursor polling,
notifications as information-only, retention bounds.
"""

import pytest

from coordinator.app.events import (
    EventRefusedError,
    list_events,
    list_notifications,
    mark_notification_read,
    new_event,
    new_notification,
    prune_events,
    save_event,
    save_notification,
)


def use_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "bus.db"))


def test_event_types_closed():
    event = new_event("task.completed", "Task 1 klaar", task_id="1")
    assert event.event_type == "task.completed"
    assert event.created_at != ""
    with pytest.raises(EventRefusedError):
        new_event("task.launch_missiles", "x")


def test_payload_never_executable():
    for key in ("command", "exec", "execute", "shell", "code",
                "url", "approved", "decision", "execute_now"):
        with pytest.raises(EventRefusedError, match="executable"):
            new_event("task.completed", "x",
                      payload={key: "whatever"})
    with pytest.raises(EventRefusedError):
        new_event("task.completed", "x", payload="not-a-dict")
    with pytest.raises(EventRefusedError):
        new_event("task.completed", "x",
                  payload={f"k{i}": "v" for i in range(25)})
    event = new_event("node.online", "Node up",
                      node_id="node-1",
                      payload={"tier": "seed", "attempt": 1})
    assert event.payload["attempt"] == 1


def test_poll_cursor_and_filter(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    first = new_event("task.queued", "t1", task_id="1")
    second = new_event("task.completed", "t1 klaar", task_id="1")
    third = new_event("node.online", "n1 up", node_id="n1")
    for event in (first, second, third):
        save_event(event)
    assert len(list_events(limit=50)) == 3
    after_first = list_events(limit=50, after=first.event_id)
    assert [event.event_id for event in after_first] == [
        second.event_id, third.event_id]
    assert list_events(limit=1)[0].event_id == first.event_id
    only_nodes = list_events(limit=50, event_type="node.online")
    assert [event.event_id for event in only_nodes] == [
        third.event_id]
    with pytest.raises(EventRefusedError):
        list_events(event_type="nope")
    assert prune_events(keep=2) == 1
    assert len(list_events(limit=50)) == 2


def test_notifications_informational(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    notification = new_notification(
        "node-phone1", "approval_required", "Goedkeuring nodig",
        "Missie wacht op YES", related_mission="mission_1")
    assert notification.read is False
    save_notification(notification)
    found = list_notifications("node-phone1")
    assert len(found) == 1
    assert found[0].title == "Goedkeuring nodig"
    assert list_notifications("node-other") == []
    assert mark_notification_read(notification.notification_id,
                                  "node-phone1") is True
    assert list_notifications("node-phone1",
                              unread_only=True) == []
    assert mark_notification_read(notification.notification_id,
                                  "node-other") is False
    with pytest.raises(EventRefusedError):
        new_notification("node-phone1", "launch", "x")
    with pytest.raises(EventRefusedError):
        new_notification("node-phone1", "info", "   ")
    with pytest.raises(EventRefusedError):
        new_notification("??", "info", "x")
