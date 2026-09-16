"""Interface adapter + message + session tests (BIG #9).

Text/voice convergence, closed types, bounded content, session
lifecycle (never credentials), adapter contracts.
"""

import pytest

from coordinator.app.interface import (
    InterfaceRefusedError,
    TextInterface,
    VoiceInterface,
    generate_interface_id,
    list_sessions,
    load_session,
    new_interface_message,
    new_session,
    revoke_session,
    save_session,
    session_usable,
    touch_session,
)


def test_text_interface_roundtrip():
    adapter = TextInterface()
    message = adapter.receive_input({
        "message_id": "msg-1", "conversation_id": "conv-1",
        "content": "Wat ligt er op mijn werkbank?"})
    assert message.role == "user"
    assert message.input_type == "text"
    rendered = adapter.send_response(message)
    assert rendered["content"] == message.content
    with pytest.raises(InterfaceRefusedError):
        adapter.receive_input({"message_id": "msg-1"})
    with pytest.raises(InterfaceRefusedError):
        adapter.receive_input({"message_id": "m", "conversation_id": "c",
                               "content": "x", "input_type": "sms"})


def test_voice_converges_to_text_turn():
    adapter = VoiceInterface()
    message = adapter.receive_input({
        "message_id": "msg-v1", "conversation_id": "conv-1",
        "transcript": "zet de camera aan",
        "stt_model": "test-only"})
    assert message.role == "user"
    assert message.input_type == "voice"
    assert message.content == "zet de camera aan"
    assert "transcribed" in message.provenance.notes
    rendered = adapter.send_response(message)
    assert rendered["output_type"] == "voice"
    with pytest.raises(InterfaceRefusedError):
        adapter.receive_input({"content": "   "})


def test_message_bounds_and_roles():
    with pytest.raises(InterfaceRefusedError):
        new_interface_message("msg-1", "conv-1", "robot", "hoi")
    with pytest.raises(InterfaceRefusedError):
        new_interface_message("msg-1", "conv-1", "user", "   ")
    with pytest.raises(InterfaceRefusedError):
        new_interface_message("msg-1", "conv-1", "user", "x" * 4001)
    with pytest.raises(InterfaceRefusedError):
        new_interface_message("msg-1", "conv-1", "user", "x",
                              output_type="exec")
    from coordinator.app.inventory_read import Provenance
    with pytest.raises(InterfaceRefusedError):
        new_interface_message(
            "msg-1", "conv-1", "assistant", "advies",
            provenance=Provenance(source_type="ai-generated",
                                  creator_id="m",
                                  human_verified=True))
    with pytest.raises(InterfaceRefusedError):
        generate_interface_id("hologram")


def test_session_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "iface.db"))
    session = new_session("iface-text-1", node_id="node-phone1")
    assert session.status == "active"
    assert session_usable(session) is True
    assert session_usable(session,
                          "2999-01-01T00:00:00+00:00") is False
    assert load_session(session.session_id) is None
    save_session(session)
    assert load_session(session.session_id).status == "active"
    touched = touch_session(session)
    assert touched.status == "active"
    revoked = revoke_session(session)
    save_session(revoked)
    assert session_usable(load_session(
        session.session_id)) is False
    assert load_session("sess-missing") is None
    assert len(list_sessions("iface-text-1")) == 1
    expired = touch_session(
        session, "2999-01-01T00:00:00+00:00")
    assert expired.status == "expired"
    assert touch_session(expired).status == "expired"
    with pytest.raises(InterfaceRefusedError):
        new_session("")
    with pytest.raises(InterfaceRefusedError):
        new_session("iface-x", ttl_seconds=10**9)
