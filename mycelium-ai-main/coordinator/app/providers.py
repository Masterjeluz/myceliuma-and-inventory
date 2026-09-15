"""AI provider abstraction for Mycelium (Fase C).

Mycelium reasons through an AIProvider, never by calling one model
directly. The existing OllamaAdvisor stays untouched; OllamaProvider is
a thin adapter around it. ExternalProvider is an explicit stub: it
carries a name and non-secret configuration only, stores no
credentials, performs no network calls, and always fails closed until
an operator configures a real, reviewed implementation.

Rules (tested):

- provider names are explicit (``ollama`` local default, ``external``
  stub family); unknown names are refused before anything runs.
- every provider returns the shared AdviceResponse shape, so callers
  never branch on model internals.
- any failure (unreachable model, unconfigured external provider,
  refused input) surfaces as ProviderUnavailable/ProviderRefused;
  plain-text advice is never fabricated as a fallback.
- no secrets are accepted anywhere in this module: constructors take
  only base URLs, model names and timeouts. Credential material raises.
"""

from typing import Any

from .ollama_advisor import (
    AdviceResponse,
    OllamaAdvisor,
    OllamaRefusedError,
    OllamaUnavailable,
)

OLLAMA_PROVIDER_NAME = "ollama"
EXTERNAL_PROVIDER_NAME = "external"

_FORBIDDEN_CONFIG_KEYS = frozenset({
    "api_key", "apikey", "secret", "token", "password", "credential",
    "credentials", "bearer", "authorization",
})


class ProviderUnavailable(RuntimeError):
    """The provider could not produce advice. Always fail-closed."""


class ProviderRefusedError(ValueError):
    """Local validation refused the provider request; nothing was sent."""


def _reject_secrets(config: dict) -> None:
    if not isinstance(config, dict):
        raise ProviderRefusedError("Provider config must be an object")
    for key in config:
        if str(key).lower() in _FORBIDDEN_CONFIG_KEYS:
            raise ProviderRefusedError(
                f"Provider config must not contain credentials (got '{key}')")


class AIProvider:
    """Interface for reasoning sources. Subclasses implement advise()."""

    name = "base"

    async def advise(self, question: str,
                     records: list[dict]) -> AdviceResponse:
        raise NotImplementedError


class OllamaProvider(AIProvider):
    """Local Ollama provider. Thin wrapper; all policy lives in M8.1."""

    name = OLLAMA_PROVIDER_NAME

    def __init__(self, base_url=None, model=None, timeout=None,
                 transport=None):
        try:
            self._advisor = OllamaAdvisor(base_url=base_url, model=model,
                                          timeout=timeout,
                                          transport=transport)
        except OllamaRefusedError as error:
            raise ProviderRefusedError(str(error)) from error

    async def advise(self, question: str,
                     records: list[dict]) -> AdviceResponse:
        try:
            return await self._advisor.advise(question, records)
        except OllamaRefusedError as error:
            raise ProviderRefusedError(str(error)) from error
        except OllamaUnavailable as error:
            raise ProviderUnavailable(str(error)) from error


class ExternalProvider(AIProvider):
    """Stub for future external models (OpenAI/Gemini/...).

    Safe by construction: it never performs network I/O and always
    raises ProviderUnavailable with an explicit reason. A real
    implementation needs its own review (credential handling, data
    minimization, explicit operator consent) and does not exist yet.
    """

    name = EXTERNAL_PROVIDER_NAME

    def __init__(self, provider: str = "unconfigured",
                 config: dict | None = None):
        if not isinstance(provider, str) or not provider.strip():
            raise ProviderRefusedError("External provider needs a name")
        _reject_secrets(config or {})
        self.provider = provider.strip()[:80]
        self.config: dict[str, Any] = dict(config or {})

    async def advise(self, question: str,
                     records: list[dict]) -> AdviceResponse:
        raise ProviderUnavailable(
            f"External provider '{self.provider}' is not configured; "
            "local Ollama remains the only active reasoning source")


def get_provider(name: str | None = None, **kwargs) -> AIProvider:
    """Resolve a provider by name. Unknown names fail closed."""
    resolved = (name or OLLAMA_PROVIDER_NAME).strip().lower()
    if resolved == OLLAMA_PROVIDER_NAME:
        return OllamaProvider(**kwargs)
    if resolved == EXTERNAL_PROVIDER_NAME:
        return ExternalProvider(**kwargs)
    raise ProviderRefusedError(f"Unknown AI provider '{name}'")
