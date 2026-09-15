"""Provider layer tests (Fase C/Q).

Contract, Ollama compatibility, unavailable-provider and fail-closed
behaviour. Ollama HTTP is faked with httpx.MockTransport; no real
model is ever contacted. Async providers run via asyncio.run (no
extra test dependency).
"""

import asyncio

import httpx
import pytest

from coordinator.app.ollama_advisor import AdviceResponse
from coordinator.app.providers import (
    ExternalProvider,
    OllamaProvider,
    ProviderRefusedError,
    ProviderUnavailable,
    get_provider,
)


def ok_handler(request):
    return httpx.Response(200, json={"response": "advies-tekst"})


def make_ollama(**kwargs):
    kwargs.setdefault("transport", httpx.MockTransport(ok_handler))
    return OllamaProvider(**kwargs)


def test_ollama_provider_returns_shared_advice_shape():
    answered = asyncio.run(make_ollama().advise(
        "Wat kan ik maken?", [{"entity_id": "obj_x", "title": "t",
                                "snippet": "s", "provenance": {}}]))
    assert isinstance(answered, AdviceResponse)
    assert answered.advice == "advies-tekst"
    assert answered.records_used == 1


def test_ollama_provider_unavailable_fails_closed():
    def fail(request):
        raise httpx.ConnectError("down")

    provider = OllamaProvider(transport=httpx.MockTransport(fail))
    with pytest.raises(ProviderUnavailable):
        asyncio.run(provider.advise("vraag?", []))


def test_ollama_provider_refused_input_fails_closed():
    with pytest.raises(ProviderRefusedError):
        asyncio.run(make_ollama().advise("   ", []))


def test_ollama_provider_bad_url_refused():
    with pytest.raises(ProviderRefusedError):
        OllamaProvider(base_url="http://example.com:11434")


def test_external_provider_always_unavailable():
    provider = ExternalProvider(provider="openai", config={"region": "eu"})
    with pytest.raises(ProviderUnavailable) as caught:
        asyncio.run(provider.advise("vraag?", []))
    assert "not configured" in str(caught.value)


def test_external_provider_rejects_credentials():
    with pytest.raises(ProviderRefusedError):
        ExternalProvider(provider="x", config={"api_key": "secret"})
    with pytest.raises(ProviderRefusedError):
        ExternalProvider(provider="x", config={"TOKEN": "secret"})
    with pytest.raises(ProviderRefusedError):
        ExternalProvider(provider="x", config={"password": "p"})


def test_external_provider_needs_name():
    with pytest.raises(ProviderRefusedError):
        ExternalProvider(provider="  ")


def test_get_provider_defaults_to_ollama():
    assert isinstance(get_provider(None), OllamaProvider)
    assert isinstance(get_provider("ollama"), OllamaProvider)
    assert isinstance(get_provider("external"), ExternalProvider)


def test_get_provider_unknown_name_refused():
    with pytest.raises(ProviderRefusedError):
        get_provider("chatgpt-direct")
