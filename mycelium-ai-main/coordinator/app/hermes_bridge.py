"""Minimal Hermes agent bridge for the Mycelium coordinator.

Speaks to a local Hermes gateway's OpenAI-compatible API server
(http://127.0.0.1:8642 by default). Deliberately small:

- send one message, receive one response (chat completions);
- agent/session identity via ``X-Hermes-Session-Key`` (the gateway
  converges same-key first requests onto one live session);
- bounded time (default 60s, max 120s — agent runs take longer
  than inventory reads);
- clear error states, never raw tracebacks.

Safety properties (mirror inventory_read.py, all covered by tests):

- HTTP POST only to the two chat endpoints. No other methods.
- Loopback-only base URL (127.0.0.1, localhost, ::1). Anything
  else is refused before any socket is opened. Redirects never
  followed.
- Bounded inputs: session key <= 256 chars (gateway cap),
  message <= 64_000 chars, model <= 120 chars.
- API key via ``HERMES_API_KEY`` env (or explicit arg), never
  logged, never committed. Missing key -> HermesRefusedError
  before any socket is opened.
- Connection problems and timeouts surface as
  :class:`HermesUnavailable`, never as raw tracebacks.

NOT wired to any route, game, scheduler or worker. Callers
opt in explicitly. No INVENTory writes, no approvals touched.
"""

import os
from urllib.parse import urlsplit

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8642"
BASE_URL_ENV_VAR = "HERMES_API_URL"
API_KEY_ENV_VAR = "HERMES_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_TIMEOUT_SECONDS = 120.0
MAX_SESSION_KEY_LENGTH = 256
MAX_MESSAGE_LENGTH = 64_000
MAX_MODEL_LENGTH = 120
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_MODEL = "hermes-agent"


class HermesUnavailable(RuntimeError):
    """Hermes could not be reached or answered with an error."""


class HermesRefusedError(ValueError):
    """Local validation refused the request; nothing was sent."""


def _validate_base_url(raw) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise HermesRefusedError("Hermes base URL must be non-empty text")
    try:
        parts = urlsplit(raw.strip())
    except ValueError as error:
        raise HermesRefusedError(f"Invalid Hermes base URL: {error}") from error
    if parts.scheme != "http":
        raise HermesRefusedError("Hermes base URL must use http")
    if parts.username or parts.password:
        raise HermesRefusedError("Hermes base URL must not contain credentials")
    host = (parts.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        raise HermesRefusedError(
            f"Hermes host '{host or '?'}' is not loopback; refusing"
        )
    if not parts.port:
        return f"http://{parts.hostname}"
    return f"http://{parts.hostname}:{parts.port}"


def _check_session_key(key) -> str:
    if not isinstance(key, str) or not key.strip():
        raise HermesRefusedError("Session key must be non-empty text")
    clean = key.strip()
    if len(clean) > MAX_SESSION_KEY_LENGTH:
        raise HermesRefusedError(
            f"Session key exceeds {MAX_SESSION_KEY_LENGTH} characters"
        )
    return clean


def _check_message(message) -> str:
    if not isinstance(message, str) or not message.strip():
        raise HermesRefusedError("Message must be non-empty text")
    if len(message) > MAX_MESSAGE_LENGTH:
        raise HermesRefusedError(
            f"Message exceeds {MAX_MESSAGE_LENGTH} characters"
        )
    return message


def _check_model(model) -> str:
    if not isinstance(model, str) or not model.strip():
        raise HermesRefusedError("Model must be non-empty text")
    clean = model.strip()
    if len(clean) > MAX_MODEL_LENGTH:
        raise HermesRefusedError(
            f"Model exceeds {MAX_MODEL_LENGTH} characters"
        )
    return clean


class HermesBridge:
    """Minimal send/receive client for one Hermes agent."""

    def __init__(self, base_url=None, api_key=None,
                 timeout=DEFAULT_TIMEOUT_SECONDS, transport=None):
        raw = base_url if base_url is not None else os.environ.get(
            BASE_URL_ENV_VAR, DEFAULT_BASE_URL
        )
        self.base_url = _validate_base_url(raw)
        key = api_key if api_key is not None else os.environ.get(
            API_KEY_ENV_VAR, ""
        )
        if not isinstance(key, str) or not key.strip():
            raise HermesRefusedError(
                f"Hermes API key missing: set {API_KEY_ENV_VAR}"
            )
        self._api_key = key.strip()
        try:
            self.timeout = min(float(timeout), MAX_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            self.timeout = DEFAULT_TIMEOUT_SECONDS
        if self.timeout <= 0:
            self.timeout = DEFAULT_TIMEOUT_SECONDS
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            follow_redirects=False,
            transport=self._transport,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

    def send(self, session_key, message, model=DEFAULT_MODEL,
             max_tokens=500) -> dict:
        """Send one message, return the assistant text + ids.

        Returns ``{"session_key", "message_id", "model", "text",
        "finish_reason"}``. Raises :class:`HermesRefusedError` on
        bad input, :class:`HermesUnavailable` on transport/API
        errors.
        """
        key = _check_session_key(session_key)
        text = _check_message(message)
        clean_model = _check_model(model)
        try:
            count = max(1, min(int(max_tokens or 500), 4000))
        except (TypeError, ValueError):
            raise HermesRefusedError("max_tokens must be an integer")
        payload = {
            "model": clean_model,
            "messages": [{"role": "user", "content": text}],
            "max_tokens": count,
        }
        try:
            with self._client() as client:
                response = client.post(
                    "/v1/chat/completions",
                    json=payload,
                    headers={"X-Hermes-Session-Key": key},
                )
        except httpx.TimeoutException as error:
            raise HermesUnavailable(f"Hermes timed out: {error}") from error
        except httpx.HTTPError as error:
            raise HermesUnavailable(f"Hermes unreachable: {error}") from error
        if response.status_code in (301, 302, 303, 307, 308):
            raise HermesUnavailable("Hermes redirect refused")
        if response.status_code == 401:
            raise HermesUnavailable(
                "Hermes refused the API key (401)"
            )
        if response.status_code != 200:
            raise HermesUnavailable(
                f"Hermes answered with HTTP {response.status_code}"
            )
        try:
            data = response.json()
        except ValueError as error:
            raise HermesUnavailable(
                "Hermes answered with invalid JSON") from error
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise HermesUnavailable(
                "Hermes answer has no usable choice") from error
        return {
            "session_key": key,
            "message_id": str(data.get("id", "")),
            "model": str(data.get("model", clean_model)),
            "text": str(content),
            "finish_reason": str(choice.get("finish_reason", "")),
        }

    def health(self) -> dict:
        """Unauthenticated liveness probe. Returns raw dict."""
        try:
            with self._client() as client:
                response = client.get("/health")
        except httpx.TimeoutException as error:
            raise HermesUnavailable(f"Hermes timed out: {error}") from error
        except httpx.HTTPError as error:
            raise HermesUnavailable(f"Hermes unreachable: {error}") from error
        if response.status_code != 200:
            raise HermesUnavailable(
                f"Hermes health answered HTTP {response.status_code}"
            )
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
