"""Embedding providers for semantic retrieval (BIG #4).

Minimal interface: embed a bounded list of texts, get back vectors
of a declared dimension. Local-first, fail-closed:

- OllamaEmbeddingProvider talks to ONE loopback endpoint
  (POST {base}/api/embed) with an operator-chosen model. No
  download, no install, no hidden traffic: a missing model is
  EmbeddingUnavailable with an explicit `ollama pull` hint, never
  a silent fetch.
- UnavailableEmbeddingProvider always raises: the honest "no
  semantic runtime here" used for fallback tests and dry runs.

Rules (tested): loopback-only base URL, bounded input
(MAX_TEXTS texts of MAX_TEXT_CHARS), timeout clamped, non-empty
vectors of consistent dimension, zero-vectors refused (they carry
no signal and would fake similarity).
"""

import os

import httpx

from .model_router import DEFAULT_EMBED_MODEL as _ROUTER_EMBED_MODEL

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
BASE_URL_ENV_VAR = "OLLAMA_BASE_URL"
MODEL_ENV_VAR = "OLLAMA_EMBED_MODEL"
# Normal default owned by the central model router (value unchanged;
# explicit-arg > OLLAMA_EMBED_MODEL env > this fallback is untouched).
DEFAULT_MODEL = _ROUTER_EMBED_MODEL
TIMEOUT_ENV_VAR = "OLLAMA_EMBED_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 30.0
EMBED_PATH = "/api/embed"
MAX_TEXTS = 64
MAX_TEXT_CHARS = 2000
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class EmbeddingUnavailable(RuntimeError):
    """No usable embedding runtime. Fall back to lexical, never fake."""


class EmbeddingRefusedError(ValueError):
    """Local validation refused; nothing was sent anywhere."""


def _validate_base_url(raw) -> str:
    from urllib.parse import urlsplit
    if not isinstance(raw, str) or not raw.strip():
        raise EmbeddingRefusedError("Embed base URL must be non-empty")
    try:
        parts = urlsplit(raw.strip())
    except ValueError as error:
        raise EmbeddingRefusedError(f"Invalid URL: {error}") from error
    if parts.scheme != "http":
        raise EmbeddingRefusedError("Embed base URL must use http")
    if parts.username or parts.password:
        raise EmbeddingRefusedError("Embed base URL must not "
                                    "contain credentials")
    host = (parts.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        raise EmbeddingRefusedError(
            f"Embed host '{host or '?'}' is not loopback; refusing")
    return raw.strip()


def _resolve_timeout(raw) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    if not (value > 0):
        return DEFAULT_TIMEOUT_SECONDS
    return min(value, MAX_TIMEOUT_SECONDS)


def check_texts(texts) -> list[str]:
    if not isinstance(texts, (list, tuple)) or not texts:
        raise EmbeddingRefusedError("Texts must be a non-empty list")
    if len(texts) > MAX_TEXTS:
        raise EmbeddingRefusedError(f"At most {MAX_TEXTS} texts per call")
    cleaned = []
    for text in texts:
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingRefusedError("Each text must be non-empty")
        cleaned.append(text.strip()[:MAX_TEXT_CHARS])
    return cleaned


def check_vectors(vectors, expected_dim: int = 0) -> list[list[float]]:
    if not isinstance(vectors, list) or not vectors:
        raise EmbeddingRefusedError("No vectors returned")
    checked = []
    for vector in vectors:
        if (not isinstance(vector, (list, tuple)) or not vector
                or any(not isinstance(x, (int, float)) for x in vector)):
            raise EmbeddingRefusedError("Invalid vector shape")
        floats = [float(x) for x in vector]
        if all(x == 0.0 for x in floats):
            raise EmbeddingRefusedError("Zero vector carries no signal")
        checked.append(floats)
    dims = {len(vector) for vector in checked}
    if len(dims) != 1:
        raise EmbeddingRefusedError("Inconsistent vector dimensions")
    if expected_dim and dims.pop() != expected_dim:
        raise EmbeddingRefusedError("Unexpected vector dimension")
    return checked


class EmbeddingProvider:
    """Interface: embed texts -> vectors. Name + dimension declared."""

    name = "base"
    model = "none"
    dim = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Local Ollama embeddings. Model must already be pulled."""

    name = "ollama"

    def __init__(self, base_url=None, model=None, timeout=None,
                 transport=None):
        raw = (base_url if base_url is not None
               else os.environ.get(BASE_URL_ENV_VAR, DEFAULT_BASE_URL))
        self.base_url = _validate_base_url(raw)
        name = (model if model is not None
                else os.environ.get(MODEL_ENV_VAR, DEFAULT_MODEL))
        if not isinstance(name, str) or not name.strip():
            raise EmbeddingRefusedError("Model name must be non-empty")
        self.model = name.strip()
        raw_timeout = (timeout if timeout is not None
                       else os.environ.get(TIMEOUT_ENV_VAR,
                                           DEFAULT_TIMEOUT_SECONDS))
        self.timeout = _resolve_timeout(raw_timeout)
        self._transport = transport

    async def embed(self, texts: list[str]) -> list[list[float]]:
        cleaned = check_texts(texts)
        try:
            async with httpx.AsyncClient(
                    base_url=self.base_url, timeout=self.timeout,
                    follow_redirects=False, trust_env=False,
                    transport=self._transport) as client:
                response = await client.post(
                    EMBED_PATH,
                    json={"model": self.model, "input": cleaned})
        except httpx.TimeoutException as error:
            raise EmbeddingUnavailable(f"Embed timed out: {error}") from error
        except httpx.HTTPError as error:
            raise EmbeddingUnavailable(
                f"Embed unreachable: {error}") from error
        if response.status_code in (301, 302, 303, 307, 308):
            raise EmbeddingUnavailable("Embed redirect refused")
        if response.status_code == 404:
            raise EmbeddingUnavailable(
                f"Model '{self.model}' not present locally; operator "
                f"must `ollama pull {self.model}` first — Mycelium "
                "never downloads models by itself")
        if response.status_code != 200:
            raise EmbeddingUnavailable(
                f"Embed answered HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as error:
            raise EmbeddingUnavailable("Embed answered invalid JSON") from error
        vectors = (data.get("embeddings") if isinstance(data, dict)
                   else None)
        try:
            checked = check_vectors(vectors or [])
        except EmbeddingRefusedError as error:
            raise EmbeddingUnavailable(
                f"Embed returned unusable vectors: {error}") from error
        if len(checked) != len(cleaned):
            raise EmbeddingUnavailable("Embed count mismatch")
        self.dim = len(checked[0])
        return checked


class UnavailableEmbeddingProvider(EmbeddingProvider):
    """Honest absence of a semantic runtime. Always fail-closed."""

    name = "unavailable"

    def __init__(self, reason: str = "no embedding runtime installed"):
        self._reason = str(reason or "unavailable")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        check_texts(texts)
        raise EmbeddingUnavailable(f"Semantic unavailable: {self._reason}")


def get_embed_provider(name: str | None = None, **kwargs) -> EmbeddingProvider:
    resolved = (name or "ollama").strip().lower()
    if resolved == "ollama":
        return OllamaEmbeddingProvider(**kwargs)
    if resolved == "unavailable":
        return UnavailableEmbeddingProvider(**kwargs)
    raise EmbeddingRefusedError(f"Unknown embedding provider '{name}'")
