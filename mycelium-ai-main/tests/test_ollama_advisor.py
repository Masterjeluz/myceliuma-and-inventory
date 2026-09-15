"""Tests for the M8.1 local Ollama advisor (read-only advice only).

Ollama is fully faked with httpx.MockTransport. No real model, no real
network, no filesystem writes, no database. Async calls run via asyncio.
"""
import asyncio
from pathlib import Path

import httpx
import pytest

from coordinator.app.ollama_advisor import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_CONTEXT_LENGTH,
    MAX_QUESTION_LENGTH,
    MAX_RECORDS,
    MAX_TIMEOUT_SECONDS,
    OllamaAdvisor,
    OllamaRefusedError,
    OllamaUnavailable,
    TIMEOUT_ENV_VAR,
    build_prompt,
    redact_paths,
)


def run(coro):
    return asyncio.run(coro)


def record(entity_id="obj_1", title="Moer M8",
           snippet="rvs zeskant", entity_type="object"):
    return {"entity_type": entity_type, "entity_id": entity_id, "title": title,
            "snippet": snippet,
            "provenance": {"source_type": "user-created",
                           "creator_id": "tester", "human_verified": True}}


def advisor(handler, **kwargs):
    kwargs.setdefault("base_url", "http://127.0.0.1:11434")
    kwargs.setdefault("model", "test-model")
    return OllamaAdvisor(transport=httpx.MockTransport(handler), **kwargs)


def ok_handler(expected=None):
    def handle(request):
        if expected is not None:
            expected.append(request)
        return httpx.Response(200, json={"response": "Gebruik de Moer M8."})
    return handle


# --- normal advice -----------------------------------------------------------------

def test_normal_advice():
    seen = []
    res = run(advisor(ok_handler(seen)).advise(
        "Wat kan ik maken?", [record(), record("proj_2", "Bouw", "plan",
                                                "project")]))
    assert res.advice == "Gebruik de Moer M8."
    assert res.question == "Wat kan ik maken?"
    assert res.model == "test-model"
    assert res.records_used == 2
    assert len(res.sources) == 2
    assert res.sources[0].entity_id == "obj_1"
    assert res.sources[0].human_verified is True
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/api/generate"


def test_think_disabled_in_generate_payload():
    import json as _json

    seen = []
    res = run(advisor(ok_handler(seen)).advise("Wat kan ik maken?", [record()]))
    assert res.advice == "Gebruik de Moer M8."
    assert len(seen) == 1
    payload = _json.loads(seen[0].content.decode("utf-8"))
    assert payload["think"] is False
    assert payload["stream"] is False
    assert payload["model"] == "test-model"
    assert "prompt" in payload and "Wat kan ik maken?" in payload["prompt"]


def test_prompt_construction():
    prompt, sources = build_prompt("  Vraag?  ", [record()])
    assert "Vraag?" in prompt
    assert "Moer M8" in prompt
    assert "obj_1" in prompt
    assert len(sources) == 1
    assert build_prompt("Vraag?", [record()]) == build_prompt("Vraag?", [record()])


def test_question_length_cap():
    with pytest.raises(OllamaRefusedError):
        build_prompt("x" * (MAX_QUESTION_LENGTH + 1), [record()])
    with pytest.raises(OllamaRefusedError):
        build_prompt("   ", [record()])
    prompt, _ = build_prompt("x" * MAX_QUESTION_LENGTH, [record()])
    assert "x" * MAX_QUESTION_LENGTH in prompt


def test_context_caps():
    many = [record(f"obj_{i}", f"Ding {i}", "vulling") for i in range(50)]
    prompt, sources = build_prompt("Wat?", many)
    assert len(sources) == MAX_RECORDS
    assert len(prompt) <= MAX_CONTEXT_LENGTH + 1000
    assert "Ding 49" not in prompt


def test_path_redaction():
    text = "staat op C:\\Temp\\werkplaats en \\\\nas\\share map"
    assert "C:\\Temp" not in redact_paths(text)
    assert "\\\\nas" not in redact_paths(text)
    assert "[redacted-path]" in redact_paths(text)
    prompt, _ = build_prompt("Waar?", [record(snippet=text)])
    assert "C:\\Temp" not in prompt
    assert "[redacted-path]" in prompt


def test_provenance_in_context():
    prompt, sources = build_prompt("Wat?", [record()])
    assert "user-created" in prompt
    assert sources[0].source_type == "user-created"


# --- URL safety ----------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "http://example.com:11434", "http://192.168.1.5:11434/",
    "https://127.0.0.1:11434/", "http://127.0.0.1.evil.com/",
    "http://user@127.0.0.1:11434/", "file:///tmp/x", "", "notaurl",
])
def test_non_loopback_refused(url):
    def fail(request):  # pragma: no cover
        raise AssertionError("no HTTP must happen")
    with pytest.raises(OllamaRefusedError):
        OllamaAdvisor(base_url=url, model="m",
                      transport=httpx.MockTransport(fail))


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:11434", "http://localhost:11434/", "http://[::1]:11434",
])
def test_loopback_accepted(url):
    def fail(request):  # pragma: no cover
        raise AssertionError("no HTTP must happen")
    OllamaAdvisor(base_url=url, model="m", transport=httpx.MockTransport(fail))


def test_redirects_refused():
    def redirect(request):
        return httpx.Response(302, headers={"location": "http://example.com/"})
    with pytest.raises(OllamaUnavailable):
        run(advisor(redirect).advise("Wat?", [record()]))


# --- failure modes ---------------------------------------------------------------------

def test_timeout_fail_closed():
    def slow(request):
        raise httpx.ConnectTimeout("too slow")
    with pytest.raises(OllamaUnavailable):
        run(advisor(slow).advise("Wat?", [record()]))


def test_connection_error_fail_closed():
    def dead(request):
        raise httpx.ConnectError("refused")
    with pytest.raises(OllamaUnavailable):
        run(advisor(dead).advise("Wat?", [record()]))


def test_http_500_fail_closed():
    def broken(request):
        return httpx.Response(500, json={"error": "boom"})
    with pytest.raises(OllamaUnavailable):
        run(advisor(broken).advise("Wat?", [record()]))


@pytest.mark.parametrize("payload", [
    {}, {"response": None}, {"response": 123}, {"response": "   "},
    {"something": "else"},
])
def test_malformed_response_fail_closed(payload):
    def weird(request):
        return httpx.Response(200, json=payload)
    with pytest.raises(OllamaUnavailable):
        run(advisor(weird).advise("Wat?", [record()]))


def test_invalid_json_fail_closed():
    def binary(request):
        return httpx.Response(200, content=b"\xff\xfe")
    with pytest.raises(OllamaUnavailable):
        run(advisor(binary).advise("Wat?", [record()]))


# --- absence of side effects ------------------------------------------------------------------

def test_only_generate_endpoint_used():
    seen = []
    run(advisor(ok_handler(seen)).advise("Wat?", [record()]))
    assert seen, "expected a request to inspect"
    assert {request.url.path for request in seen} == {"/api/generate"}
    assert {request.method for request in seen} == {"POST"}


def test_no_proposal_dispatch_approval_surface():
    advisor_instance = advisor(ok_handler())
    for name in ("propose", "dispatch", "approve", "stage", "queue", "claim",
                 "complete", "register", "execute"):
        assert not hasattr(advisor_instance, name), (
            f"advisor must not offer {name}")


def test_advise_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run(advisor(ok_handler()).advise("Wat?", [record()]))
    assert list(tmp_path.iterdir()) == []


def test_timeout_default_suits_local_models(monkeypatch):
    monkeypatch.delenv(TIMEOUT_ENV_VAR, raising=False)
    assert OllamaAdvisor(transport=httpx.MockTransport(ok_handler())).timeout == DEFAULT_TIMEOUT_SECONDS
    assert DEFAULT_TIMEOUT_SECONDS == 120.0
    assert MAX_TIMEOUT_SECONDS == 120.0


def test_timeout_env_configured(monkeypatch):
    monkeypatch.setenv(TIMEOUT_ENV_VAR, "60")
    assert OllamaAdvisor(transport=httpx.MockTransport(ok_handler())).timeout == 60.0


def test_timeout_never_above_maximum(monkeypatch):
    monkeypatch.delenv(TIMEOUT_ENV_VAR, raising=False)
    assert OllamaAdvisor(timeout=1000, transport=httpx.MockTransport(ok_handler())).timeout == MAX_TIMEOUT_SECONDS
    monkeypatch.setenv(TIMEOUT_ENV_VAR, "1000")
    assert OllamaAdvisor(transport=httpx.MockTransport(ok_handler())).timeout == MAX_TIMEOUT_SECONDS


@pytest.mark.parametrize("raw", ["", "geen-getal", "0", "-5", "None"])
def test_timeout_invalid_falls_back_to_default(monkeypatch, raw):
    monkeypatch.setenv(TIMEOUT_ENV_VAR, raw)
    assert OllamaAdvisor(transport=httpx.MockTransport(ok_handler())).timeout == DEFAULT_TIMEOUT_SECONDS


def test_timeout_explicit_wins_over_env(monkeypatch):
    monkeypatch.setenv(TIMEOUT_ENV_VAR, "60")
    assert OllamaAdvisor(timeout=30, transport=httpx.MockTransport(ok_handler())).timeout == 30.0


def test_no_io_tokens_in_implementation():
    source = (Path(__file__).resolve().parent.parent
              / "coordinator" / "app" / "ollama_advisor.py").read_text(
                  encoding="utf-8")
    for token in ("subprocess", "os.system", "socket", "requests",
                  "torch", "transformers", "ollama", "serial", "GPIO",
                  "threading", "asyncio", "pathlib", "shutil", "open(",
                  "execute", "inference", "download", "filesystem"):
        assert token not in source, f"advisor must not use {token}"
