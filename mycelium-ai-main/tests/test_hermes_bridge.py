"""Hermes bridge tests: validation refuses locally, transport
errors surface as HermesUnavailable. Live server never needed
(mock transport only)."""

import httpx
import pytest

from coordinator.app.hermes_bridge import (
    HermesBridge,
    HermesRefusedError,
    HermesUnavailable,
)


def _ok_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["X-Hermes-Session-Key"] == "game-1"
        return httpx.Response(200, json={
            "id": "chatcmpl-1", "model": "hermes-agent",
            "choices": [{"message": {"role": "assistant",
                                     "content": "hi"},
                         "finish_reason": "stop"}]})
    return httpx.MockTransport(handler)


def test_send_roundtrip():
    bridge = HermesBridge(base_url="http://127.0.0.1:8642",
                          api_key="test-key",
                          transport=_ok_transport())
    out = bridge.send("game-1", "hello")
    assert out["text"] == "hi"
    assert out["session_key"] == "game-1"
    assert out["message_id"] == "chatcmpl-1"
    assert out["finish_reason"] == "stop"


def test_refuses_non_loopback():
    with pytest.raises(HermesRefusedError):
        HermesBridge(base_url="http://192.168.1.10:8642",
                     api_key="test-key")


def test_refuses_missing_key(monkeypatch):
    monkeypatch.delenv("HERMES_API_KEY", raising=False)
    with pytest.raises(HermesRefusedError):
        HermesBridge(base_url="http://127.0.0.1:8642")


def test_refuses_bad_input():
    bridge = HermesBridge(base_url="http://127.0.0.1:8642",
                          api_key="test-key",
                          transport=_ok_transport())
    with pytest.raises(HermesRefusedError):
        bridge.send("", "hello")
    with pytest.raises(HermesRefusedError):
        bridge.send("game-1", "   ")
    with pytest.raises(HermesRefusedError):
        bridge.send("game-1", "x" * 64_001)


def test_auth_failure_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "nope"})
    bridge = HermesBridge(base_url="http://127.0.0.1:8642",
                          api_key="bad-key",
                          transport=httpx.MockTransport(handler))
    with pytest.raises(HermesUnavailable):
        bridge.send("game-1", "hello")


def test_timeout_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")
    bridge = HermesBridge(base_url="http://127.0.0.1:8642",
                          api_key="test-key",
                          transport=httpx.MockTransport(handler))
    with pytest.raises(HermesUnavailable):
        bridge.send("game-1", "hello")


def test_health_roundtrip():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})
    bridge = HermesBridge(base_url="http://127.0.0.1:8642",
                          api_key="test-key",
                          transport=httpx.MockTransport(handler))
    assert bridge.health() == {"ok": True}
