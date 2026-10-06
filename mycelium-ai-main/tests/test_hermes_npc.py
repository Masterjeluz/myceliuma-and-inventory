"""Hermes NPC tests: identity/session/context + chat route.
Live Hermes never needed (fake bridge); validation and error
mapping are the contract."""

from fastapi.testclient import TestClient

import coordinator.app.hermes_npc as npc_mod
import coordinator.app.main as main_mod
from coordinator.app.hermes_bridge import (
    HermesRefusedError,
    HermesUnavailable,
)


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "hnpc.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "hnpc-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", "hnpc-operator")
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://127.0.0.1:9")
    with TestClient(main_mod.app) as test_client:
        yield test_client


class _FakeBridge:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def send(self, session_key, message, max_tokens=500):
        self.calls.append((session_key, message, max_tokens))
        assert "Mos" in message or "mos" in session_key
        return {"session_key": session_key, "message_id": "m1",
                "model": "hermes-agent", "text": "Hoi, ik ben Mos.",
                "finish_reason": "stop"}


def test_session_key_stable_and_unknown_refused():
    assert npc_mod.npc_session_key("mos", "play_abc") == \
        "npc-mos-play_abc"
    assert npc_mod.npc_session_key("mos", None) == "npc-mos-shared"
    try:
        npc_mod.npc_session_key("dragon", "play_abc")
    except HermesRefusedError:
        pass
    else:
        raise AssertionError("unknown npc must refuse")


def test_context_never_raises(tmp_path, monkeypatch):
    for _ in api(tmp_path, monkeypatch):
        text = npc_mod.build_npc_context("play_nope")
        assert isinstance(text, str)
        assert "Mycelium" in text


def test_context_includes_screen_state(tmp_path, monkeypatch):
    from coordinator.app.world_observations import (
        new_observation,
        save_observation,
    )
    for test_client in api(tmp_path, monkeypatch):
        made = test_client.post("/api/v1/world/observations", json={
            "node_id": "node-screen1", "source": "screen",
            "note": "IDE open", "media_ref": "shot-1.png",
            "provenance": {"window": "Mycelium IDE"}}).json()
        assert made["obs_id"].startswith("wobs_")
        text = npc_mod.build_npc_context(None)
        assert "Schermstatus (alleen lezen, nooit handelen)" in text
        assert "node-screen1" in text
        assert "shot-1.png" in text
        assert "Mycelium IDE" in text


def test_chat_route_uses_bridge(tmp_path, monkeypatch):
    fakes = []

    def factory(*args, **kwargs):
        fake = _FakeBridge()
        fakes.append(fake)
        return fake

    monkeypatch.setattr(npc_mod, "HermesBridge", factory)
    for test_client in api(tmp_path, monkeypatch):
        res = test_client.post("/api/v1/hermes/chat", json={
            "npc_id": "mos", "message": "Hoi Mos!",
            "session_id": "play_abc"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["npc_id"] == "mos"
        assert body["npc_name"] == "Mos"
        assert body["session_key"] == "npc-mos-play_abc"
        assert body["text"] == "Hoi, ik ben Mos."
        assert len(fakes) == 1
        session_key, message, _ = fakes[0].calls[0]
        assert session_key == "npc-mos-play_abc"
        assert "Wereldcontext" in message


def test_chat_route_validation(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        assert test_client.post(
            "/api/v1/hermes/chat",
            json={"npc_id": "dragon",
                  "message": "hi"}).status_code == 422
        assert test_client.post(
            "/api/v1/hermes/chat",
            json={"npc_id": "mos", "message": "  "}).status_code == 422


def test_chat_route_missing_key_is_503(tmp_path, monkeypatch):
    class _NoKey:
        def __init__(self, *args, **kwargs):
            raise HermesRefusedError("Hermes API key missing: set X")

    monkeypatch.setattr(npc_mod, "HermesBridge", _NoKey)
    for test_client in api(tmp_path, monkeypatch):
        res = test_client.post("/api/v1/hermes/chat", json={
            "npc_id": "mos", "message": "hi"})
        assert res.status_code == 503, res.text


def test_side_mos_agent_markers(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        html = test_client.get("/side").text
        for marker in ("mostalk", "mossend", "mospropose",
                       "echte agent", "hermes/chat",
                       "Missie 0", "/approvals"):
            assert marker in html, marker


def test_chat_route_unavailable_is_502(tmp_path, monkeypatch):
    class _Down:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, *args, **kwargs):
            raise HermesUnavailable("Hermes unreachable: down")

    monkeypatch.setattr(npc_mod, "HermesBridge", _Down)
    for test_client in api(tmp_path, monkeypatch):
        res = test_client.post("/api/v1/hermes/chat", json={
            "npc_id": "mos", "message": "hi"})
        assert res.status_code == 502, res.text
