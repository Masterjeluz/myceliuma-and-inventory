"""Human-interface API tests (BIG #9).

Sessions, interface/voice chat convergence, STT/TTS routes,
capture sessions, events polling, notifications, status,
voice-approval flow into existing gates, phone camera, mobile
page. No microphone, no speaker, no phone hardware needed.
"""

import os

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.voice import audio_dir, delete_audio


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "hi.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "hi-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def make_clip(name="aud-hi1.wav"):
    path = os.path.join(audio_dir(), name)
    with open(path, "wb") as handle:
        handle.write(b"RIFF-HI\n")
    return name


def test_sessions_lifecycle(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        opened = test_client.post("/api/v1/interface/sessions",
                                  json={"interface_id": "iface-web"})
        assert opened.status_code == 201, opened.text
        session_id = opened.json()["session_id"]
        assert test_client.get(
            "/api/v1/interface/sessions").status_code == 200
        assert test_client.post(
            f"/api/v1/interface/sessions/{session_id}/touch"
        ).status_code == 200
        revoked = test_client.post(
            f"/api/v1/interface/sessions/{session_id}/revoke").json()
        assert revoked["status"] == "revoked"
        assert test_client.post(
            "/api/v1/interface/sessions/sess-missing/touch"
        ).status_code == 404


def test_interface_chat_converges(tmp_path, monkeypatch):
    from coordinator.app.ollama_advisor import AdviceResponse

    class FakeProvider:
        async def advise(self, question, records):
            return AdviceResponse(
                question=question, advice="advies", model="fake",
                records_used=len(records), sources=[])

    for test_client in make_client(tmp_path, monkeypatch):
        monkeypatch.setattr(main_mod, "get_provider",
                            lambda name=None, **k: FakeProvider())
        session_id = test_client.post(
            "/api/v1/interface/sessions",
            json={"interface_id": "iface-web"}).json()["session_id"]
        answer = test_client.post("/api/v1/interface/chat", json={
            "session_id": session_id, "content": "Hoi Mycelium",
            "input_type": "voice"})
        assert answer.status_code == 200, answer.text
        assert answer.json()["chat"]["reply"] == "advies"
        assert answer.json()["interface"]["output_type"] == "voice"
        bad_session = test_client.post("/api/v1/interface/chat",
                                       json={
                                           "session_id": "sess-nope",
                                           "content": "Hoi"})
        assert bad_session.status_code == 409
        bad_type = test_client.post("/api/v1/interface/chat", json={
            "content": "Hoi", "input_type": "sms"})
        assert bad_type.status_code == 422
        events = test_client.get("/api/v1/events",
                                 params={"type": "conversation.message",
                                         "limit": 10}).json()
        assert len(events) >= 1


def test_voice_transcribe_synthesize_unavailable(tmp_path,
                                                monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        ref = make_clip()
        try:
            refused = test_client.post("/api/v1/voice/transcribe",
                                       json={"audio_ref": ref})
            # No backend configured: honest 502, never fabricated.
            assert refused.status_code == 502
            missing = test_client.post("/api/v1/voice/transcribe",
                                       json={"audio_ref":
                                             "aud-missing.wav"})
            assert missing.status_code in (422, 502)
            tts = test_client.post("/api/v1/voice/synthesize",
                                   json={"text": "Hallo"})
            assert tts.status_code == 502
        finally:
            delete_audio(ref)


def test_voice_chat_test_providers(tmp_path, monkeypatch):
    from coordinator.app.ollama_advisor import AdviceResponse

    class FakeProvider:
        async def advise(self, question, records):
            return AdviceResponse(
                question=question, advice="advies", model="fake",
                records_used=len(records), sources=[])

    for test_client in make_client(tmp_path, monkeypatch):
        monkeypatch.setattr(main_mod, "get_provider",
                            lambda name=None, **k: FakeProvider())
        answer = test_client.post("/api/v1/voice/chat", json={
            "transcript": "wat ligt er op mijn werkbank",
            "provider": "test-only", "speak": True})
        assert answer.status_code == 200, answer.text
        assert answer.json()["chat"]["reply"] == "advies"
        assert answer.json()["spoken"]["audio_ref"].endswith(
            ".wav")
        empty = test_client.post("/api/v1/voice/chat", json={})
        assert empty.status_code == 422
        # Speaking without a backend refuses honestly.
        nospeak = test_client.post("/api/v1/voice/chat", json={
            "transcript": "hoi", "speak": True})
        assert nospeak.status_code == 502


def test_capture_contracts(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-phone9", "hostname": "phone",
            "capabilities": ["phone.microphone.read"],
            "node_token": "phone9-token-123456"})
        opened = test_client.post("/api/v1/voice/capture/open",
                                  json={"node_id": "node-phone9",
                                        "max_seconds": 30})
        assert opened.status_code == 201, opened.text
        session_id = opened.json()["session_id"]
        ref = make_clip("aud-cap9.wav")
        try:
            closed = test_client.post("/api/v1/voice/capture/close",
                                      json={"session_id": session_id,
                                            "audio_ref": ref})
            assert closed.json()["status"] == "closed"
            deleted = test_client.delete(
                "/api/v1/voice/audio/aud-cap9.wav").json()
            assert deleted == {"audio_ref": "aud-cap9.wav",
                               "removed": True}
        finally:
            delete_audio(ref)
        # Node without the capability cannot open capture.
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-plain9", "hostname": "h",
            "capabilities": [],
            "node_token": "plain9-token-123456"})
        refused = test_client.post("/api/v1/voice/capture/open",
                                   json={"node_id": "node-plain9"})
        assert refused.status_code == 422
        assert test_client.post("/api/v1/voice/capture/open",
                                json={
                                    "node_id": "node-ghost"}
                                ).status_code == 404
        assert test_client.delete(
            "/api/v1/voice/audio/../x.wav").status_code == 404
        # Normalized away by routing; an invalid suffix still 422s.
        assert test_client.delete(
            "/api/v1/voice/audio/x.mp4").status_code == 422


def test_events_and_notifications(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-phone8", "hostname": "phone",
            "capabilities": ["phone.notification.send"],
            "node_token": "phone8-token-123456"})
        created = test_client.post("/api/v1/notifications", json={
            "recipient_node_id": "node-phone8",
            "type": "approval_required",
            "title": "Missie wacht op YES",
            "related_mission": "mission_1"})
        assert created.status_code == 201, created.text
        notification_id = created.json()["notification_id"]
        listed = test_client.get("/api/v1/notifications",
                                 params={
                                     "node_id": "node-phone8"}).json()
        assert len(listed) == 1
        assert test_client.post(
            f"/api/v1/notifications/{notification_id}/read",
            params={"node_id": "node-phone8"}).status_code == 200
        assert test_client.get("/api/v1/notifications", params={
            "node_id": "node-phone8",
            "unread_only": True}).json() == []
        assert test_client.post("/api/v1/notifications", json={
            "recipient_node_id": "node-ghost",
            "type": "info", "title": "x"}).status_code == 404
        assert test_client.post("/api/v1/notifications", json={
            "recipient_node_id": "node-phone8",
            "type": "launch", "title": "x"}).status_code == 422
        # Polling works with cursor + filter.
        first = test_client.get("/api/v1/events",
                                params={"limit": 1}).json()
        assert isinstance(first, list)
        second = test_client.get("/api/v1/events", params={
            "after": first[0]["event_id"] if first else "",
            "limit": 50}).json()
        assert isinstance(second, list)


def test_status_bounded_no_secrets(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-st1", "hostname": "h",
            "capabilities": [], "node_token": "tok-st-123456789"})
        status = test_client.get("/api/v1/status").json()
        assert status["coordinator"] == "online"
        assert status["nodes"]["total"] == 1
        assert "pending_approvals" in status
        text = str(status)
        assert "tok-st-1" not in text
        assert "auth_token_hash" not in text
        assert "mycelium.db" not in text


def test_voice_approval_write_flow(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        proposed = test_client.post("/api/v1/writes/inventory",
                                    json={
                                        "proposal_id": "wrt-vap1",
                                        "mutation": "create",
                                        "entity_type": "object",
                                        "fields": {
                                            "name": "Spraakbout"}})
        assert proposed.status_code == 201
        opened = test_client.post(
            "/api/v1/voice/approval-requests",
            json={"kind": "write", "target_id": "wrt-vap1",
                  "summary": "Maak Spraakbout"})
        assert opened.status_code == 201, opened.text
        approval_id = opened.json()["approval_id"]
        # Competing request refuses while one is pending.
        assert test_client.post(
            "/api/v1/voice/approval-requests",
            json={"kind": "write",
                  "target_id": "wrt-vap1"}).status_code == 409
        # Casual speech refuses; the proposal stays proposed.
        assert test_client.post("/api/v1/voice/approve", json={
            "approval_id": approval_id,
            "transcript": "doe maar"}).status_code == 422
        assert test_client.get(
            "/api/v1/writes/wrt-vap1").json()["status"] == "proposed"
        # Exact YES word approves through the existing gate.
        granted = test_client.post("/api/v1/voice/approve", json={
            "approval_id": approval_id, "transcript": "ja"})
        assert granted.status_code == 200, granted.text
        assert granted.json()["approved"] is True
        assert test_client.get(
            "/api/v1/writes/wrt-vap1").json()["status"] == "approved"
        # Resolved requests cannot be reused.
        assert test_client.post("/api/v1/voice/approve", json={
            "approval_id": approval_id,
            "transcript": "YES"}).status_code == 409


def test_voice_approval_physical_never(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        assert test_client.post(
            "/api/v1/voice/approval-requests",
            json={"kind": "physical",
                  "target_id": "wrt-x"}).status_code == 422
        assert test_client.post(
            "/api/v1/voice/approval-requests",
            json={"kind": "write",
                  "target_id": "wrt-missing"}).status_code == 404


def test_voice_approval_mission_flow(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        created = test_client.post("/api/v1/missions", json={
            "conversation_id": "conv-vap1",
            "goal": "Ruim de werkbank op",
            "steps": [{"kind": "readout",
                       "description": "Lees project",
                       "parameters": {"source": "project"}}]})
        assert created.status_code == 201
        mission_id = created.json()["mission_id"]
        opened = test_client.post(
            "/api/v1/voice/approval-requests",
            json={"kind": "mission", "target_id": mission_id})
        assert opened.status_code == 201
        granted = test_client.post("/api/v1/voice/approve", json={
            "approval_id": opened.json()["approval_id"],
            "transcript": "YES"})
        assert granted.status_code == 200
        assert test_client.get(
            f"/api/v1/missions/{mission_id}").json()[
                "status"] == "approved"


def test_phone_camera_registration(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-phone7", "hostname": "phone",
            "capabilities": ["phone.camera.snapshot",
                             "phone.microphone.read"],
            "node_token": "phone7-token-123456"})
        registered = test_client.post(
            "/api/v1/phone/node-phone7/camera",
            json={"node_id": "node-phone7",
                  "name": "Telefooncamera"})
        assert registered.status_code == 201, registered.text
        assert registered.json()["source"] == "phone"
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-plain7", "hostname": "h",
            "capabilities": [],
            "node_token": "plain7-token-123456"})
        refused = test_client.post(
            "/api/v1/phone/node-plain7/camera",
            json={"node_id": "node-plain7"})
        assert refused.status_code == 422
        assert test_client.post(
            "/api/v1/phone/node-ghost/camera",
            json={"node_id": "node-ghost"}).status_code == 404


def test_phone_auth_reuses_node_tokens(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        test_client.post("/api/v1/nodes/register", json={
            "node_id": "node-phone6", "hostname": "phone",
            "capabilities": ["phone.notification.send"],
            "node_token": "phone-token-6123456"})
        assert test_client.post(
            "/api/v1/nodes/node-phone6/heartbeat",
            json={"available": True,
                  "node_token": "wrong-token"}).status_code == 403
        assert test_client.post(
            "/api/v1/nodes/node-phone6/heartbeat",
            json={"available": True,
                  "node_token": "phone-token-6123456"}
        ).status_code == 204


def test_route_annotations_resolve():
    """Regression tripwire: PEP 649 lazy annotations hide missing
    imports until FastAPI inspects them (then params degrade to
    query args). Every route annotation must resolve."""
    import coordinator.app.main as main_mod
    bad = []
    for route in main_mod.app.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        try:
            annotations = endpoint.__annotations__
            for value in annotations.values():
                str(value)
        except NameError as error:
            bad.append((endpoint.__name__, str(error)))
    assert bad == []


def test_mobile_page_and_chat_panel(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        page = test_client.get("/mobile")
        assert page.status_code == 200
        assert 'name="viewport"' in page.text
        assert "Notifications" in page.text
        chat = test_client.get("/chat")
        assert chat.status_code == 200
        assert "Interface: web" in chat.text
        assert "/api/v1/status" in chat.text
