"""Fase 5a: NPC-aanwezigheid als projectie (town_actors).

Tests draaien op tmp-DB's; Ollama/Hermes expres dood
(poort 9) zodat geen enkel model geraadpleegd wordt.
"""

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def dbtmp(tmp_path, monkeypatch):
    """Chat-DB naar een tmp-bestand: directe aanroepen
    (set_actor, record_activity, sync) mogen nooit de
    default data/mycelium-chat.db raken."""
    monkeypatch.setenv(
        "MYCELIUM_CHAT_DATABASE_PATH",
        str(tmp_path / "chat.db"))
    return str(tmp_path / "chat.db")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MYCELIUM_DATABASE_PATH",
        str(tmp_path / "mycelium.db"))
    monkeypatch.setenv(
        "MYCELIUM_CHAT_DATABASE_PATH",
        str(tmp_path / "chat.db"))
    monkeypatch.setenv(
        "INVENTORY_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("HERMES_API_KEY", raising=False)
    monkeypatch.setenv(
        "OLLAMA_BASE_URL", "http://127.0.0.1:9")
    import coordinator.app.main as main
    with TestClient(main.app) as c:
        yield c


def test_desk_deterministic_and_inside():
    from coordinator.app.town_actors import (
        NPC_ORDER, npc_desk)
    seen = {}
    for npc in NPC_ORDER:
        desk = npc_desk(npc)
        assert 0 <= desk["x"] <= 3840
        assert 0 <= desk["y"] <= 1400
        assert npc_desk(npc) == desk
        seen[npc] = desk
    assert len({(v["x"], v["y"])
                for v in seen.values()}) == 6


def test_set_actor_validation(dbtmp):
    from coordinator.app.town_actors import (
        ActorRefusedError, set_actor)
    good = set_actor("mos", x=100, y=100,
                     activity="walking", detail="naar plein",
                     status="walking", source="player")
    assert good["npc_id"] == "mos"
    for npc, kw in (
            ("nope", {"x": 100, "y": 100}),
            ("mos", {"x": "abc", "y": 100}),
            ("mos", {"x": 99999, "y": 100}),
            ("mos", {"x": 100, "y": 100,
                     "activity": "sleeping"}),
            ("mos", {"x": 100, "y": 100,
                     "source": "magic"})):
        try:
            set_actor(npc, **kw)
        except ActorRefusedError:
            pass
        else:
            raise AssertionError(
                f"accepted {npc}/{kw}")


def test_list_actors_idle_fallback(dbtmp):
    from coordinator.app.town_actors import list_actors
    rows = list_actors()
    assert len(rows) == 6
    assert all(row["status"] == "idle"
               for row in rows)
    assert all(row["source"] == "system"
               for row in rows)


def test_activity_feed_bounded(dbtmp):
    from coordinator.app.town_actors import (
        activity_feed, record_activity)
    for i in range(12):
        record_activity("mos", "test", f"line {i}")
    feed = activity_feed(limit=5)
    assert len(feed) == 5
    assert feed[-1]["detail"] == "line 11"


def test_sync_from_signals_working_then_idle(dbtmp):
    from coordinator.app.town_actors import (
        list_actors, set_actor, sync_from_signals)
    set_actor("mos", x=100, y=100)
    tasks = [{"id": 1, "status": "assigned",
              "node_id": "town-mos",
              "goal": "research solar panels"}]
    out = sync_from_signals(tasks=tasks)
    mos = [a for a in out if a["npc_id"] == "mos"][0]
    assert mos["status"] == "working"
    assert "research solar panels" in mos["detail"]
    assert mos["source"] == "queue"
    done = sync_from_signals(
        tasks=[{"id": 1, "status": "completed",
                "node_id": "town-mos", "goal": "x"}])
    mos2 = [a for a in done
            if a["npc_id"] == "mos"][0]
    assert mos2["status"] == "idle"
    assert mos2["source"] == "system"
    assert list_actors()[0]["npc_id"] == "mos"


def test_actors_api(client):
    res = client.get("/api/v1/town/actors")
    assert res.status_code == 200
    body = res.json()
    assert len(body["actors"]) == 6
    assert isinstance(body["activity"], list)


def test_targeted_npc_chat(client, monkeypatch):
    """Loop-naar-toe: npc_id in het bericht → die NPC
    reageert (Ollama gemockt; Hermes en model dood)."""
    from types import SimpleNamespace

    import httpx as _httpx

    def fake_post(url, json=None, timeout=None):
        assert url == "http://127.0.0.1:9/api/chat"
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "message": {"content": "Hallo, ik hoor je."}})
    monkeypatch.setattr(_httpx, "post", fake_post)
    opened = client.post(
        "/api/v1/town/conversations", json={
            "title": "T", "participants": ["you"]})
    assert opened.status_code == 201, opened.text
    cid = opened.json()["conversation_id"]
    res = client.post(
        f"/api/v1/town/conversations/{cid}/messages",
        json={"speaker": "you", "role": "human",
              "text": "Hallo?", "npc_id": "archivaris"})
    assert res.status_code == 201, res.text
    turn = res.json()["npc_turn"]
    assert turn["role"] == "npc:archivaris"
    assert turn["content"] == "Hallo, ik hoor je."


def test_solarpunk_page_carries_actors(client):
    res = client.get("/solarpunk")
    assert res.status_code == 200
    assert 'id="spc-actors"' in res.text
    assert 'id="spc-actors-feed"' in res.text
    assert 'id="spc-near"' in res.text
    assert "mos" in res.text
