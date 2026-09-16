"""Voice tests (BIG #9): STT/TTS abstractions, audio security,
capture sessions, no fabricated audio, no cloud.
"""

import asyncio
import os

import httpx
import pytest

from coordinator.app.voice import (
    LocalSTTProvider,
    TestSTTProvider,
    TestTTSProvider,
    UnavailableSTTProvider,
    UnavailableTTSProvider,
    VoiceRefusedError,
    VoiceUnavailable,
    audio_dir,
    audio_facts,
    check_audio_ref,
    clear_capture_sessions,
    close_capture_session,
    delete_audio,
    get_capture_session,
    get_stt_provider,
    get_tts_provider,
    open_capture_session,
    prune_audio,
    read_audio_bytes,
)


def run(coro):
    return asyncio.run(coro)


def make_clip(name="aud-test1.wav", body=b"RIFF-FAKE\n"):
    path = os.path.join(audio_dir(), name)
    with open(path, "wb") as handle:
        handle.write(body)
    return name


def test_audio_ref_security():
    assert check_audio_ref("aud-x.wav") == "aud-x.wav"
    for evil in ("../x.wav", "..\\x.wav", "/abs/x.wav",
                 "C:\\w\\x.wav", "\\\\host\\x.wav", "x.mp4",
                 "x.txt", "", "x" * 201):
        with pytest.raises(VoiceRefusedError):
            check_audio_ref(evil)
    with pytest.raises(VoiceRefusedError):
        read_audio_bytes("aud-missing.wav")


def test_audio_facts_and_retention():
    ref = make_clip()
    facts = audio_facts(ref)
    assert facts["size_bytes"] > 0
    assert len(facts["sha256"]) == 64
    assert delete_audio(ref) is True
    assert delete_audio(ref) is False
    assert prune_audio() >= 0


def test_oversized_audio_refused():
    from coordinator.app.voice import MAX_AUDIO_BYTES
    path = os.path.join(audio_dir(), "aud-big.wav")
    with open(path, "wb") as handle:
        handle.write(b"\x00" * (MAX_AUDIO_BYTES + 1))
    try:
        with pytest.raises(VoiceRefusedError, match="max"):
            read_audio_bytes("aud-big.wav")
    finally:
        os.remove(path)


def test_unavailable_providers_refuse():
    with pytest.raises(VoiceUnavailable, match="no automatic"):
        run(get_stt_provider("unavailable").transcribe("aud-x.wav"))
    with pytest.raises(VoiceUnavailable, match="no automatic"):
        run(get_tts_provider("unavailable").synthesize("hoi"))
    with pytest.raises(VoiceRefusedError, match="Unknown STT"):
        get_stt_provider("cloud-stt")
    with pytest.raises(VoiceRefusedError, match="Unknown TTS"):
        get_tts_provider("cloud-tts")


def test_test_providers_are_marked():
    ref = make_clip("aud-stt1.wav")
    try:
        result = run(TestSTTProvider(
            text="zet de camera aan").transcribe(ref))
        assert result.text == "zet de camera aan"
        assert result.confidence == 0.5
        assert result.provenance.human_verified is False
        assert "test-origin" in result.provenance.notes
        assert "never authorization" in result.provenance.notes
        with pytest.raises(VoiceUnavailable, match="synthetic"):
            run(TestSTTProvider(fail=True).transcribe(ref))
        synthesis = run(TestTTSProvider().synthesize("Hallo Jelles"))
        assert synthesis.audio_ref.endswith(".wav")
        assert synthesis.provenance.human_verified is False
        assert "test-origin" in synthesis.provenance.notes
        with pytest.raises(VoiceRefusedError):
            run(TestTTSProvider().synthesize("   "))
    finally:
        delete_audio(ref)
        delete_audio("aud-stt1.wav")


def test_local_stt_loops_back():
    ref = make_clip("aud-local1.wav")
    try:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/transcribe"
            return httpx.Response(200, json={
                "text": "werkbank is rommelig",
                "language": "nl", "confidence": 0.8})

        provider = LocalSTTProvider(
            base_url="http://127.0.0.1:19999", model="test-mdl",
            transport=httpx.MockTransport(handler))
        result = run(provider.transcribe(ref))
        assert result.text == "werkbank is rommelig"
        assert result.language == "nl"
        assert result.provenance.human_verified is False

        def empty(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"text": "  "})

        with pytest.raises(VoiceUnavailable, match="usable text"):
            run(LocalSTTProvider(
                base_url="http://127.0.0.1:19999", model="m",
                transport=httpx.MockTransport(empty)).transcribe(
                    ref))
    finally:
        delete_audio(ref)


def test_local_stt_boundaries():
    with pytest.raises(VoiceRefusedError, match="loopback"):
        LocalSTTProvider(base_url="http://192.168.1.9:9000")
    with pytest.raises(VoiceRefusedError, match="set text"):
        LocalSTTProvider(base_url="")
    with pytest.raises(VoiceRefusedError, match="Unknown STT"):
        get_stt_provider("Deepgram")


def test_capture_sessions_explicit_only():
    clear_capture_sessions()
    session = open_capture_session("node-phone1", max_seconds=30)
    assert session.status == "open"
    assert get_capture_session(session.session_id) is not None
    ref = make_clip("aud-cap1.wav")
    try:
        closed = close_capture_session(session.session_id, ref)
        assert closed.status == "closed"
        assert closed.audio_ref == ref
        assert close_capture_session(
            session.session_id).status == "closed"
    finally:
        delete_audio(ref)
    with pytest.raises(VoiceRefusedError, match="unknown"):
        close_capture_session("cap-missing")
    with pytest.raises(VoiceRefusedError):
        open_capture_session("node-phone1", max_seconds=10**9)
    with pytest.raises(VoiceRefusedError):
        open_capture_session("not a node id!!", max_seconds=10)
    clear_capture_sessions()
    assert get_capture_session(session.session_id) is None


def test_no_cloud_or_shell_surface():
    import pathlib
    import coordinator.app.voice as module
    source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    for token in ("https://", "boto", "deepgram", "openai",
                  "elevenlabs", "subprocess", "os.system",
                  "pyaudio", "sounddevice", "speech_recognition"):
        assert token not in source, f"forbidden token: {token}"
    assert "LOOPBACK" in source
    assert "follow_redirects=False" in source
