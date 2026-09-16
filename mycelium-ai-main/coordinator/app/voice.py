"""Voice abstractions for Mycelium (BIG #9).

Speech-to-text in, text-to-speech out — both local-first, both
fail-closed, neither ever authorization. Voice converges with
typed text as early as possible: after STT, a spoken turn IS a
conversation turn with voice provenance.

Audio security (tested, all fail-closed):

- Audio lives under exactly one local root (audio dir, temp).
  Plain filenames only (existing check_image_ref discipline
  extended to .wav/.mp3/.ogg), boundary-checked, capped size
  (MAX_AUDIO_BYTES) and capped duration metadata.
- No upload, no cloud storage, no public URLs, no arbitrary
  file reads, no traversal, no credentials in logs.
- Retention: latest AUDIO_RETENTION files; explicit delete API;
  cleanup never touches world-model entities.
- Transcription is interpretation input, never FACT; STT
  confidence never authorizes anything (no such field flows
  into any gate).

Providers:

- SpeechToTextProvider interface; LocalSTTProvider speaks to a
  loopback STT backend when configured (STT_BACKEND_URL, model
  STT_MODEL); UnavailableSTTProvider refuses with an explicit
  reason; TestSTTProvider returns deterministic canned text,
  always test-marked. No downloads, no installs, no cloud.
- TextToSpeechProvider interface; UnavailableTTSProvider and
  TestTTSProvider (deterministic audio reference, test-marked).
  TTS output never alters authorization semantics.
"""

import hashlib
import os
import tempfile
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .inventory_read import Provenance

AUDIO_DIR_NAME = "mycelium-audio"
AUDIO_RETENTION = 5
AUDIO_SUFFIXES = (".wav", ".mp3", ".ogg")

#: 25 MiB per audio file; duration metadata capped separately.
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_DURATION_SECONDS = 600
MAX_TEXT_CHARS = 4000
MAX_REF_CHARS = 200

STT_BACKEND_ENV_VAR = "STT_BACKEND_URL"
STT_MODEL_ENV_VAR = "STT_MODEL"
DEFAULT_STT_MODEL = "whisper-base"
STT_TRANSCRIBE_PATH = "/api/transcribe"

TTS_BACKEND_ENV_VAR = "TTS_BACKEND_URL"
TTS_MODEL_ENV_VAR = "TTS_MODEL"
DEFAULT_TTS_MODEL = "local-tts"
TTS_SYNTHESIZE_PATH = "/api/synthesize"

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_TIMEOUT_SECONDS = 120.0

TEST_ORIGIN_MARK = "test-origin: synthetic audio/text, never a real recording"


class VoiceRefusedError(ValueError):
    """Local validation refused; no audio was read or sent."""


class VoiceUnavailable(RuntimeError):
    """No voice path. Fail-closed, never fabricated audio/text."""


class Transcription(BaseModel):
    """STT output. Interpretation input — never FACT, never a gate."""

    model_config = ConfigDict(extra="forbid")

    transcript_id: str = Field(min_length=3, max_length=80)
    text: str = Field(default="", max_length=MAX_TEXT_CHARS)
    language: str = Field(default="", max_length=20)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    provider: str = Field(default="", max_length=80)
    model_id: str = Field(default="", max_length=120)
    audio_ref: str = Field(default="", max_length=MAX_REF_CHARS)
    observed_at: str = ""
    provenance: Provenance = Field(default_factory=Provenance)


class Synthesis(BaseModel):
    """TTS output. Rendering of coordinator text — authorization
    semantics unchanged."""

    model_config = ConfigDict(extra="forbid")

    synthesis_id: str = Field(min_length=3, max_length=80)
    audio_ref: str = Field(min_length=1, max_length=MAX_REF_CHARS)
    provider: str = Field(default="", max_length=80)
    model_id: str = Field(default="", max_length=120)
    duration_seconds: float = Field(default=0.0, ge=0.0)
    observed_at: str = ""
    provenance: Provenance = Field(default_factory=Provenance)


class CaptureSession(BaseModel):
    """Explicit microphone capture session. No background
    recording: sessions are created explicitly, bounded in time,
    and closed explicitly."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=3, max_length=80)
    node_id: str = Field(min_length=1, max_length=80)
    status: str = Field(default="open", max_length=20)
    max_seconds: int = Field(default=60, ge=1, le=MAX_DURATION_SECONDS)
    started_at: str = ""
    ended_at: str = ""
    audio_ref: str = Field(default="", max_length=MAX_REF_CHARS)


def audio_dir() -> str:
    path = os.path.join(tempfile.gettempdir(), AUDIO_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def prune_audio(keep: int = AUDIO_RETENTION) -> int:
    try:
        entries = os.listdir(audio_dir())
    except OSError:
        return 0
    clips = sorted(entry for entry in entries
                   if entry.startswith("aud-")
                   and entry.lower().endswith(AUDIO_SUFFIXES))
    removed = 0
    for entry in clips[:max(0, len(clips) - keep)]:
        try:
            os.remove(os.path.join(audio_dir(), entry))
            removed += 1
        except OSError:
            continue
    return removed


def delete_audio(audio_ref: str) -> bool:
    """Explicit expiry support. Returns True when removed."""
    path = audio_path(audio_ref)
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def check_audio_ref(value: str) -> str:
    """Audio filename only: no paths, URLs, schemes or traversal,
    and a known audio suffix. Fail-closed."""
    if not isinstance(value, str):
        raise VoiceRefusedError("audio_ref must be text")
    text = value.strip()
    if not text:
        raise VoiceRefusedError("audio_ref must be non-empty text")
    if len(text) > MAX_REF_CHARS:
        raise VoiceRefusedError("audio_ref too long")
    lowered = text.lower()
    if ("://" in lowered or text.startswith("\\\\")
            or text.startswith("/") or ":" in text):
        raise VoiceRefusedError(
            "audio_ref must be a plain local filename")
    if ".." in text or "/" in text or "\\" in text:
        raise VoiceRefusedError("audio_ref must not contain a path")
    if not lowered.endswith(AUDIO_SUFFIXES):
        raise VoiceRefusedError(
            "audio_ref must be a .wav, .mp3 or .ogg file")
    return text


def audio_path(audio_ref: str) -> str:
    reference = check_audio_ref(audio_ref)
    root = os.path.abspath(audio_dir())
    path = os.path.abspath(os.path.join(root, reference))
    if path != root and not path.startswith(root + os.sep):
        raise VoiceRefusedError(
            "Audio escapes the audio directory")
    return path


def read_audio_bytes(audio_ref: str) -> bytes:
    """Read one allow-listed audio file, capped. Everything else
    refuses before any byte is read."""
    path = audio_path(audio_ref)
    if not os.path.isfile(path):
        raise VoiceRefusedError(
            f"Audio '{audio_ref}' does not exist; refusing")
    size = os.path.getsize(path)
    if size <= 0:
        raise VoiceRefusedError("Audio is empty; refusing")
    if size > MAX_AUDIO_BYTES:
        raise VoiceRefusedError(
            f"Audio is {size} bytes (max {MAX_AUDIO_BYTES}); refusing")
    with open(path, "rb") as handle:
        return handle.read(MAX_AUDIO_BYTES + 1)


def audio_facts(audio_ref: str) -> dict:
    """Hash + size facts for one local audio file. No bytes leave."""
    data = read_audio_bytes(audio_ref)
    return {"audio_ref": check_audio_ref(audio_ref),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data)}


def _validate_base_url(raw, label: str) -> str:
    from urllib.parse import urlsplit
    if not isinstance(raw, str) or not raw.strip():
        raise VoiceRefusedError(f"{label} base URL must be set text")
    try:
        parts = urlsplit(raw.strip())
    except ValueError as error:
        raise VoiceRefusedError(
            f"Invalid {label} base URL: {error}") from error
    if parts.scheme != "http":
        raise VoiceRefusedError(f"{label} base URL must use http")
    if parts.username or parts.password:
        raise VoiceRefusedError(
            f"{label} base URL must not contain credentials")
    host = (parts.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        raise VoiceRefusedError(
            f"{label} host '{host or '?'}' is not loopback; refusing")
    return raw.strip()


# -- STT -----------------------------------------------------------------

class SpeechToTextProvider:
    """Interface for speech-to-text. Subclasses implement transcribe()."""

    name = "base"

    async def transcribe(self, audio_ref: str) -> Transcription:
        raise NotImplementedError


def _transcription(audio_ref: str, text: str, provider: str,
                   model_id: str, language: str = "",
                   confidence: float = 0.0) -> Transcription:
    import secrets
    import time
    from datetime import datetime, timezone
    return Transcription(
        transcript_id=f"trs_{int(time.time() * 1000):x}"
                      f"{secrets.token_hex(4)}",
        text=text.strip()[:MAX_TEXT_CHARS],
        language=language[:20],
        confidence=max(0.0, min(1.0, float(confidence or 0.0))),
        provider=provider, model_id=model_id,
        audio_ref=audio_ref,
        observed_at=datetime.now(timezone.utc).isoformat(),
        provenance=Provenance(
            source_type="sensor-observed",
            creator_id=f"stt:{provider}",
            human_verified=False,
            notes="transcription is interpretation input; "
                  "never FACT, never authorization"))


class LocalSTTProvider(SpeechToTextProvider):
    """Loopback STT backend (multipart audio upload to a local
    service). Configured, never auto-installed; missing backend
    refuses with an explicit reason."""

    name = "local-stt"

    def __init__(self, base_url=None, model=None, timeout=None,
                 transport=None):
        raw = (base_url if base_url is not None
               else os.environ.get(STT_BACKEND_ENV_VAR, ""))
        self.base_url = _validate_base_url(raw, "STT")
        name = (model if model is not None
                else os.environ.get(STT_MODEL_ENV_VAR,
                                    DEFAULT_STT_MODEL))
        if not isinstance(name, str) or not name.strip():
            raise VoiceRefusedError(
                "STT model name must be non-empty text")
        self.model = name.strip()
        try:
            self.timeout = min(float(
                timeout if timeout is not None
                else DEFAULT_TIMEOUT_SECONDS),
                MAX_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            self.timeout = DEFAULT_TIMEOUT_SECONDS
        if self.timeout <= 0:
            self.timeout = DEFAULT_TIMEOUT_SECONDS
        self._transport = transport

    async def transcribe(self, audio_ref: str) -> Transcription:
        data = read_audio_bytes(audio_ref)
        try:
            async with httpx.AsyncClient(
                    base_url=self.base_url, timeout=self.timeout,
                    follow_redirects=False,
                    transport=self._transport) as client:
                response = await client.post(
                    STT_TRANSCRIBE_PATH,
                    files={"audio": (audio_ref, data)},
                    data={"model": self.model})
        except httpx.TimeoutException as error:
            raise VoiceUnavailable(
                f"STT backend timed out: {error}") from error
        except httpx.HTTPError as error:
            raise VoiceUnavailable(
                f"STT backend unreachable: {error}") from error
        if response.status_code in (301, 302, 303, 307, 308):
            raise VoiceUnavailable("STT backend redirect refused")
        if response.status_code != 200:
            raise VoiceUnavailable(
                f"STT backend answered HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as error:
            raise VoiceUnavailable(
                "STT backend answered invalid JSON") from error
        if not isinstance(payload, dict) or not str(
                payload.get("text", "")).strip():
            raise VoiceUnavailable(
                "STT backend answered without usable text")
        return _transcription(
            audio_ref, str(payload["text"]),
            self.name, self.model,
            language=str(payload.get("language", "")),
            confidence=payload.get("confidence", 0.0))


class UnavailableSTTProvider(SpeechToTextProvider):
    """Fail-closed stub: no STT backend configured."""

    name = "unavailable"

    def __init__(self, reason: str = "no STT backend configured"):
        self.reason = reason

    async def transcribe(self, audio_ref: str) -> Transcription:
        raise VoiceUnavailable(
            f"{self.reason}; no automatic download, no cloud "
            "fallback, no fabricated transcription")


class TestSTTProvider(SpeechToTextProvider):
    """Deterministic TEST transcription. Canned text, test-marked."""

    name = "test-only"

    def __init__(self, text: str = "zet de camera aan",
                 fail: bool = False):
        self._text = text
        self._fail = fail

    async def transcribe(self, audio_ref: str) -> Transcription:
        check_audio_ref(audio_ref)
        if self._fail:
            raise VoiceUnavailable("synthetic STT failure (test)")
        result = _transcription(audio_ref, self._text, self.name,
                                "test-only", language="nl",
                                confidence=0.5)
        return result.model_copy(update={
            "provenance": Provenance(
                source_type="sensor-observed",
                creator_id="stt:test-only",
                human_verified=False,
                notes=TEST_ORIGIN_MARK + "; never FACT, never "
                      "authorization")})


def get_stt_provider(name: str | None = None, **kwargs
                     ) -> SpeechToTextProvider:
    resolved = (name or "unavailable").strip().lower()
    if resolved == "local-stt":
        return LocalSTTProvider(**kwargs)
    if resolved == "unavailable":
        return UnavailableSTTProvider(**kwargs)
    if resolved == "test-only":
        return TestSTTProvider(**kwargs)
    raise VoiceRefusedError(f"Unknown STT provider '{name}'")


# -- TTS -----------------------------------------------------------------

class TextToSpeechProvider:
    """Interface for text-to-speech. Rendering only."""

    name = "base"

    async def synthesize(self, text: str) -> Synthesis:
        raise NotImplementedError


def _synthesis(audio_ref: str, provider: str, model_id: str,
               duration: float = 0.0) -> Synthesis:
    import secrets
    import time
    from datetime import datetime, timezone
    return Synthesis(
        synthesis_id=f"tts_{int(time.time() * 1000):x}"
                     f"{secrets.token_hex(4)}",
        audio_ref=audio_ref, provider=provider, model_id=model_id,
        duration_seconds=max(0.0, float(duration or 0.0)),
        observed_at=datetime.now(timezone.utc).isoformat(),
        provenance=Provenance(
            source_type="ai-generated",
            creator_id=f"tts:{provider}",
            human_verified=False,
            notes="rendered coordinator text; authorization "
                  "semantics unchanged"))


class UnavailableTTSProvider(TextToSpeechProvider):
    """Fail-closed stub: no TTS backend configured."""

    name = "unavailable"

    def __init__(self, reason: str = "no TTS backend configured"):
        self.reason = reason

    async def synthesize(self, text: str) -> Synthesis:
        raise VoiceUnavailable(
            f"{self.reason}; no automatic download, no cloud "
            "fallback, no fabricated audio")


class TestTTSProvider(TextToSpeechProvider):
    """Deterministic TEST synthesis. Writes a tiny marker file so
    audio_ref resolves locally; always test-marked."""

    name = "test-only"

    async def synthesize(self, text: str) -> Synthesis:
        import secrets
        import time
        if not isinstance(text, str) or not text.strip():
            raise VoiceRefusedError("TTS needs non-empty text")
        if len(text) > MAX_TEXT_CHARS:
            raise VoiceRefusedError("TTS text too long")
        reference = (f"aud-tts-{int(time.time() * 1000):x}"
                     f"{secrets.token_hex(2)}.wav")
        path = os.path.join(audio_dir(), reference)
        with open(path, "wb") as handle:
            handle.write(b"RIFF-TEST-MARKER\n")
        prune_audio()
        result = _synthesis(reference, self.name, "test-only",
                            duration=len(text) / 15.0)
        return result.model_copy(update={
            "provenance": Provenance(
                source_type="ai-generated",
                creator_id="tts:test-only",
                human_verified=False,
                notes=TEST_ORIGIN_MARK)})


def get_tts_provider(name: str | None = None, **kwargs
                     ) -> TextToSpeechProvider:
    resolved = (name or "unavailable").strip().lower()
    if resolved == "unavailable":
        return UnavailableTTSProvider(**kwargs)
    if resolved == "test-only":
        return TestTTSProvider(**kwargs)
    raise VoiceRefusedError(f"Unknown TTS provider '{name}'")


# -- capture sessions (explicit, bounded, no background) ------------------

_capture_sessions: dict[str, CaptureSession] = {}
_capture_counter = 0


def open_capture_session(node_id: str,
                         max_seconds: int = 60) -> CaptureSession:
    """Explicitly open one microphone capture window. Recording
    starts only through this call — never in the background."""
    from .nodes import check_node_id
    try:
        clean_node = check_node_id(node_id)
    except ValueError as error:
        raise VoiceRefusedError(str(error)) from error
    try:
        window = int(max_seconds)
    except (TypeError, ValueError):
        raise VoiceRefusedError("max_seconds must be an integer")
    if not 1 <= window <= MAX_DURATION_SECONDS:
        raise VoiceRefusedError(
            f"max_seconds must be 1..{MAX_DURATION_SECONDS}")
    global _capture_counter
    _capture_counter += 1
    import secrets
    import time
    from datetime import datetime, timezone
    session = CaptureSession(
        session_id=f"cap-{int(time.time() * 1000):x}"
                   f"{secrets.token_hex(2)}",
        node_id=clean_node, status="open", max_seconds=window,
        started_at=datetime.now(timezone.utc).isoformat())
    _capture_sessions[session.session_id] = session
    return session


def close_capture_session(session_id: str,
                          audio_ref: str = "") -> CaptureSession:
    """Close one capture window, optionally binding the recorded
    local file. Stopped sessions never reopen."""
    session = _capture_sessions.get(session_id)
    if session is None:
        raise VoiceRefusedError(
            f"Capture session '{session_id}' unknown")
    if session.status != "open":
        return session
    from datetime import datetime, timezone
    reference = ""
    if audio_ref:
        reference = check_audio_ref(audio_ref)
        audio_path(reference)
    updated = session.model_copy(update={
        "status": "closed",
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "audio_ref": reference})
    _capture_sessions[session_id] = updated
    return updated


def get_capture_session(session_id: str) -> CaptureSession | None:
    return _capture_sessions.get(session_id)


def clear_capture_sessions() -> None:
    _capture_sessions.clear()
