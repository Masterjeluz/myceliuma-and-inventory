"""Local VLM provider abstraction for Mycelium (BIG #6).

Vision output is ADVICE/ANALYSIS — never FACT, never verified,
never a write. The chain stays:

    observation -> VLM analysis -> proposal -> approval
        -> controlled write -> verification

Rules (tested, all fail-closed):

- Local-first: Ollama on loopback is the only backend
  (``VISION_MODEL`` configures the model, default below).
  No runtime downloads, no cloud, no credentials anywhere.
- Input security: the VLM reads exactly one explicitly named
  local media file inside the camera dir. Plain filename only
  (existing ``check_image_ref``), known suffix, capped size,
  boundary-checked path. Traversal, hidden scans, credential
  files and arbitrary extensions are inexpressible here.
- Output is structured (labels, detected objects with model-
  supplied confidence, description, OCR text, uncertainty) plus
  the raw text for audit. Malformed model output refuses —
  structure is never fabricated.
- Provenance is set by this module (ai-generated, unverified,
  referencing the observation). Model-supplied provenance or
  ``human_verified`` claims are ignored entirely.
- Missing model / missing backend refuses with an explicit
  reason and a no-download policy note (Mycelium never pulls
  models itself).
"""

import base64
import os
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .cameras import camera_dir
from .inventory_read import Provenance
from .observations import check_image_ref
from .ollama_advisor import LOOPBACK_HOSTS
from .model_router import DEFAULT_VISION_MODEL as _ROUTER_VISION_MODEL

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
BASE_URL_ENV_VAR = "OLLAMA_BASE_URL"
VISION_MODEL_ENV_VAR = "VISION_MODEL"
# Normal default owned by the central model router (value unchanged;
# explicit-arg > VISION_MODEL env > this fallback is untouched).
DEFAULT_VISION_MODEL = _ROUTER_VISION_MODEL
TIMEOUT_ENV_VAR = "OLLAMA_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_TIMEOUT_SECONDS = 120.0
CHAT_PATH = "/api/chat"

MAX_MEDIA_BYTES = 10 * 1024 * 1024
MAX_QUESTION_CHARS = 500
MAX_LABELS = 20
MAX_LABEL_CHARS = 120
MAX_TEXT_CHARS = 2000


class VisionUnavailable(RuntimeError):
    """No vision result. Fail-closed, never a fabricated analysis."""


class VisionRefusedError(ValueError):
    """Local validation refused; no media was read, nothing sent."""


class VisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(min_length=3, max_length=80)
    device_id: str = Field(min_length=3, max_length=80)
    media_ref: str = Field(min_length=1, max_length=200)
    question: str = Field(default="Wat zie je op deze foto?",
                          max_length=MAX_QUESTION_CHARS)


class DetectedObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=MAX_LABEL_CHARS)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class VisionResult(BaseModel):
    """Structured model analysis. ADVICE — never fact, never verified."""

    model_config = ConfigDict(extra="forbid")

    analysis_id: str = Field(min_length=3, max_length=80)
    observation_id: str = Field(min_length=3, max_length=80)
    device_id: str = Field(min_length=3, max_length=80)
    labels: list[str] = Field(default_factory=list,
                              max_length=MAX_LABELS)
    detected_objects: list[DetectedObject] = Field(
        default_factory=list, max_length=MAX_LABELS)
    description: str = Field(default="", max_length=MAX_TEXT_CHARS)
    ocr_text: str = Field(default="", max_length=MAX_TEXT_CHARS)
    uncertainty: str = Field(default="", max_length=1000)
    raw_text: str = Field(default="", max_length=4000)
    model: str = Field(default="", max_length=120)
    observed_at: str = ""
    provenance: Provenance = Field(default_factory=Provenance)


def _validate_base_url(raw) -> str:
    from urllib.parse import urlsplit
    if not isinstance(raw, str) or not raw.strip():
        raise VisionRefusedError(
            "Vision base URL must be non-empty text")
    try:
        parts = urlsplit(raw.strip())
    except ValueError as error:
        raise VisionRefusedError(
            f"Invalid vision base URL: {error}") from error
    if parts.scheme != "http":
        raise VisionRefusedError("Vision base URL must use http")
    if parts.username or parts.password:
        raise VisionRefusedError(
            "Vision base URL must not contain credentials")
    host = (parts.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        raise VisionRefusedError(
            f"Vision host '{host or '?'}' is not loopback; refusing")
    return raw.strip()


def read_vision_media(media_ref: str) -> tuple[bytes, str]:
    """Read one allow-listed local media file. Returns (bytes, mime).

    Plain filename only, inside the camera dir or the screen-
    observation dir (both operator-local %TEMP% dirs), known
    suffix, capped size. Everything else refuses before any byte
    is read. Screen files are included so an explicit opt-in VLM
    text summary can describe them; raw pixels still never leave
    this layer except toward the loopback model.
    """
    try:
        reference = check_image_ref(media_ref)
    except ValueError as error:
        raise VisionRefusedError(str(error)) from error
    if not reference:
        raise VisionRefusedError("Vision needs a media reference")
    roots = [os.path.abspath(camera_dir())]
    try:
        from .desktop_runtime import observation_dir
        roots.append(os.path.abspath(observation_dir()))
    except Exception:
        pass
    path = ""
    for root in roots:
        candidate = os.path.abspath(os.path.join(root, reference))
        if candidate != root and candidate.startswith(root + os.sep):
            if os.path.isfile(candidate):
                path = candidate
                break
    if not path:
        raise VisionRefusedError(
            f"Media '{reference}' is outside the allow-listed "
            "camera/screen directories; refusing")
    size = os.path.getsize(path)
    if size <= 0:
        raise VisionRefusedError("Media is empty; refusing")
    if size > MAX_MEDIA_BYTES:
        raise VisionRefusedError(
            f"Media is {size} bytes (max {MAX_MEDIA_BYTES}); refusing")
    with open(path, "rb") as handle:
        data = handle.read(MAX_MEDIA_BYTES + 1)
    if len(data) > MAX_MEDIA_BYTES:  # pragma: no cover - TOCTOU guard
        raise VisionRefusedError("Media grew past the cap; refusing")
    lowered = reference.lower()
    if lowered.endswith(".bmp"):
        mime = "image/bmp"
    elif lowered.endswith((".jpg", ".jpeg")):
        mime = "image/jpeg"
    else:
        mime = "image/png"
    return data, mime


def _clean_label(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if len(text) > MAX_LABEL_CHARS:
        return None
    return text


def parse_vision_text(text: str) -> dict:
    """Parse model text into structure. Best-effort extraction with
    honest uncertainty: labels come from explicit `label:` /
    `object:` lines, the rest stays description. Unparseable text
    yields empty labels — never invented ones."""
    labels: list[str] = []
    seen: list[str] = []
    detected: list[dict] = []
    description_lines: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if lowered.startswith(("label:", "object:", "voorwerp:")):
            chunk = stripped.split(":", 1)[1].strip()
            # Optional trailing confidence: "moer (0.8)".
            confidence = 0.0
            if chunk.endswith(")") and "(" in chunk:
                head, _, tail = chunk.rpartition("(")
                try:
                    confidence = max(0.0, min(1.0, float(
                        tail.rstrip(")").strip())))
                    chunk = head.strip()
                except ValueError:
                    confidence = 0.0
            label = _clean_label(chunk)
            if label and label.lower() not in seen:
                seen.append(label.lower())
                labels.append(label)
                detected.append({"label": label,
                                 "confidence": confidence})
                if len(labels) >= MAX_LABELS:
                    break
        else:
            description_lines.append(stripped)
    return {
        "labels": labels,
        "detected_objects": detected,
        "description": "\n".join(description_lines)[:MAX_TEXT_CHARS],
    }


class VisionProvider:
    """Interface for vision sources. Subclasses implement analyze()."""

    name = "base"

    async def analyze(self, request: VisionRequest) -> VisionResult:
        raise NotImplementedError


class OllamaVisionProvider(VisionProvider):
    """Local Ollama vision. One endpoint, loopback only, base64
    image from the allow-listed media root. Missing model refuses
    with a pull hint — Mycelium never downloads anything itself."""

    name = "ollama"

    def __init__(self, base_url=None, model=None, timeout=None,
                 transport=None):
        raw = (base_url if base_url is not None
               else os.environ.get(BASE_URL_ENV_VAR, DEFAULT_BASE_URL))
        try:
            self.base_url = _validate_base_url(raw)
        except VisionRefusedError as error:
            raise error
        name = (model if model is not None
                else os.environ.get(VISION_MODEL_ENV_VAR,
                                    DEFAULT_VISION_MODEL))
        if not isinstance(name, str) or not name.strip():
            raise VisionRefusedError(
                "Vision model name must be non-empty text")
        self.model = name.strip()
        try:
            self.timeout = min(float(
                timeout if timeout is not None else os.environ.get(
                    TIMEOUT_ENV_VAR, DEFAULT_TIMEOUT_SECONDS)),
                MAX_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            self.timeout = DEFAULT_TIMEOUT_SECONDS
        if self.timeout <= 0:
            self.timeout = DEFAULT_TIMEOUT_SECONDS
        self._transport = transport

    async def analyze(self, request: VisionRequest) -> VisionResult:
        if not isinstance(request, VisionRequest):
            raise VisionRefusedError("Vision needs a VisionRequest")
        try:
            media, _mime = read_vision_media(request.media_ref)
        except VisionRefusedError as error:
            raise error
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [{
                "role": "user",
                "content": (
                    f"{request.question} Antwoord met eerst regels "
                    f"als 'label: <naam> (0..1)' voor elk herkend "
                    f"voorwerp, daarna een korte beschrijving."),
                "images": [base64.b64encode(media).decode("ascii")],
            }],
        }
        try:
            async with httpx.AsyncClient(
                    base_url=self.base_url, timeout=self.timeout,
                    follow_redirects=False,
                    transport=self._transport) as client:
                response = await client.post(CHAT_PATH, json=payload)
        except httpx.TimeoutException as error:
            raise VisionUnavailable(
                f"Vision model timed out: {error}") from error
        except httpx.HTTPError as error:
            raise VisionUnavailable(
                f"Vision backend unreachable: {error}") from error
        if response.status_code in (301, 302, 303, 307, 308):
            raise VisionUnavailable("Vision backend redirect refused")
        if response.status_code == 404:
            raise VisionUnavailable(
                f"Vision model '{self.model}' not found on the local "
                f"backend (no automatic download; ask the operator "
                f"to `ollama pull {self.model}`)")
        if response.status_code != 200:
            raise VisionUnavailable(
                f"Vision backend answered HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as error:
            raise VisionUnavailable(
                "Vision backend answered invalid JSON") from error
        text = _response_text(data)
        if not text:
            raise VisionUnavailable(
                "Vision backend answered without usable text")
        return build_result(request, text, self.model)

    def config(self) -> dict:
        return {"backend": "ollama-loopback", "base_url": self.base_url,
                "model": self.model, "timeout": self.timeout}


def _response_text(data) -> str:
    if not isinstance(data, dict):
        return ""
    message = data.get("message")
    if isinstance(message, dict):
        content = message.get("content", "")
        return content.strip() if isinstance(content, str) else ""
    # Fallback: generate-style shape (never relied upon, just read).
    response = data.get("response", "")
    return response.strip() if isinstance(response, str) else ""


def build_result(request: VisionRequest, text: str,
                 model: str) -> VisionResult:
    """Assemble a structured, explicitly unverified VisionResult."""
    import secrets
    import time
    from datetime import datetime, timezone
    parsed = parse_vision_text(text)
    return VisionResult(
        analysis_id=f"vis_{int(time.time() * 1000):x}"
                    f"{secrets.token_hex(4)}",
        observation_id=request.observation_id,
        device_id=request.device_id,
        labels=parsed["labels"],
        detected_objects=[
            DetectedObject(label=item["label"],
                           confidence=item["confidence"])
            for item in parsed["detected_objects"]],
        description=parsed["description"],
        ocr_text="",
        uncertainty=("model output is advice; identity and counts "
                     "are unconfirmed until human approval and "
                     "independent verification"),
        raw_text=text.strip()[:4000],
        model=model,
        observed_at=datetime.now(timezone.utc).isoformat(),
        provenance=Provenance(
            source_type="ai-generated",
            creator_id=f"vision:{model}",
            human_verified=False,
            notes=f"VLM analysis of {request.observation_id}; "
                  "advice only, never fact"),
    )


class UnavailableVisionProvider(VisionProvider):
    """Fail-closed stub: no backend configured. Always refuses with
    an explicit reason (mirrors ExternalProvider)."""

    name = "unavailable"

    def __init__(self, reason: str = "no vision backend configured"):
        self.reason = reason

    async def analyze(self, request: VisionRequest) -> VisionResult:
        raise VisionUnavailable(
            f"{self.reason}; no automatic download, no cloud fallback")


class TestVisionProvider(VisionProvider):
    """Deterministic test provider. Canned structure, test-marked."""

    name = "test-only"

    def __init__(self, labels=None, fail: bool = False):
        self._labels = list(labels) if labels is not None else ["moer"]
        self._fail = fail

    async def analyze(self, request: VisionRequest) -> VisionResult:
        if self._fail:
            raise VisionUnavailable("synthetic vision failure (test)")
        lines = [f"label: {label} (0.5)" for label in self._labels]
        lines.append("Een testbeschrijving, geen echte waarneming.")
        return build_result(request, "\n".join(lines), "test-only")


def get_vision_provider(name: str | None = None, **kwargs
                        ) -> VisionProvider:
    """Resolve a vision provider by name. Unknown names fail closed."""
    resolved = (name or "unavailable").strip().lower()
    if resolved == "ollama":
        try:
            return OllamaVisionProvider(**kwargs)
        except VisionRefusedError as error:
            raise error
    if resolved == "unavailable":
        return UnavailableVisionProvider(**kwargs)
    if resolved == "test-only":
        return TestVisionProvider(**kwargs)
    raise VisionRefusedError(f"Unknown vision provider '{name}'")
