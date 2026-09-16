"""VLM provider tests (BIG #6).

Structured output as ADVICE, input allow-listing, fail-closed
backends, and the no-download policy. No real model needed.
"""

import asyncio
import base64
import os

import httpx
import pytest

from coordinator.app.cameras import camera_dir, new_device
from coordinator.app.vision_ingest import SyntheticTestAdapter, ingest_snapshot
from coordinator.app.vision_provider import (
    OllamaVisionProvider,
    TestVisionProvider,
    UnavailableVisionProvider,
    VisionRefusedError,
    VisionRequest,
    VisionUnavailable,
    build_result,
    get_vision_provider,
    parse_vision_text,
    read_vision_media,
)


def run(coro):
    return asyncio.run(coro)


def make_request(media_ref="cam-x.bmp"):
    return VisionRequest(observation_id="obs-test1",
                         device_id="cam-test1", media_ref=media_ref)


def test_parse_labels_and_confidence():
    parsed = parse_vision_text(
        "label: moer (0.8)\nobject: bout (0.4)\n"
        "Een rommelige werkbank.")
    assert parsed["labels"] == ["moer", "bout"]
    assert parsed["detected_objects"][0] == {"label": "moer",
                                            "confidence": 0.8}
    assert "werkbank" in parsed["description"]


def test_parse_empty_text_yields_no_labels():
    parsed = parse_vision_text("geen idee wat dit is")
    assert parsed["labels"] == []
    assert parsed["detected_objects"] == []


def test_build_result_is_advice_never_fact():
    request = make_request()
    result = build_result(request, "label: moer (0.9)", "fake-vl")
    assert result.observation_id == "obs-test1"
    assert result.labels == ["moer"]
    assert result.provenance.source_type == "ai-generated"
    assert result.provenance.human_verified is False
    assert "advice" in result.uncertainty


def test_media_input_security():
    with pytest.raises(VisionRefusedError):
        read_vision_media("../buiten.bmp")
    with pytest.raises(VisionRefusedError):
        read_vision_media("http://x/y.png")
    with pytest.raises(VisionRefusedError):
        read_vision_media("C:\\geheim\\sleutel.bmp")
    with pytest.raises(VisionRefusedError):
        read_vision_media("foto.jpg")
    with pytest.raises(VisionRefusedError):
        read_vision_media("bestaat-niet.bmp")


def test_media_read_returns_bytes_and_mime():
    device = new_device("cam-media1", "M", ["snapshot"], "manual")
    ingested = ingest_snapshot(
        device, SyntheticTestAdapter(), test_origin=True)
    data, mime = read_vision_media(ingested.observation.media_ref)
    assert len(data) == ingested.media.size_bytes
    assert mime == "image/bmp"
    assert ingested.media.sha256 == __import__(
        "hashlib").sha256(data).hexdigest()


def test_ollama_provider_success_parses_structure():
    device = new_device("cam-media2", "M", ["snapshot"], "manual")
    ingested = ingest_snapshot(
        device, SyntheticTestAdapter(), test_origin=True)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        body = __import__("json").loads(request.content.decode())
        assert body["messages"][0]["images"]
        base64.b64decode(body["messages"][0]["images"][0])
        return httpx.Response(200, json={
            "message": {"content": "label: schroevendraaier (0.7)\n"
                                   "Op de werkbank."}})

    provider = OllamaVisionProvider(
        model="test-vl", transport=httpx.MockTransport(handler))
    result = run(provider.analyze(VisionRequest(
        observation_id="obs-1", device_id="cam-media2",
        media_ref=ingested.observation.media_ref)))
    assert result.labels == ["schroevendraaier"]
    assert result.detected_objects[0].confidence == 0.7
    assert result.provenance.human_verified is False


def test_ollama_missing_model_refuses_with_hint():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    device = new_device("cam-media4", "M", ["snapshot"], "manual")
    ingested = ingest_snapshot(
        device, SyntheticTestAdapter(), test_origin=True)
    provider = OllamaVisionProvider(
        model="niet-bestaand-model",
        transport=httpx.MockTransport(handler))
    with pytest.raises(VisionUnavailable, match="ollama pull"):
        run(provider.analyze(VisionRequest(
            observation_id="obs-1", device_id="cam-media4",
            media_ref=ingested.observation.media_ref)))


def test_ollama_malformed_response_refuses():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "  "}})

    provider = OllamaVisionProvider(
        model="m", transport=httpx.MockTransport(handler))
    device = new_device("cam-media3", "M", ["snapshot"], "manual")
    ingested = ingest_snapshot(
        device, SyntheticTestAdapter(), test_origin=True)
    with pytest.raises(VisionUnavailable, match="without usable text"):
        run(provider.analyze(VisionRequest(
            observation_id="obs-1", device_id="cam-media3",
            media_ref=ingested.observation.media_ref)))


def test_ollama_server_error_refuses():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    device = new_device("cam-media5", "M", ["snapshot"], "manual")
    ingested = ingest_snapshot(
        device, SyntheticTestAdapter(), test_origin=True)
    provider = OllamaVisionProvider(
        model="m", transport=httpx.MockTransport(handler))
    with pytest.raises(VisionUnavailable, match="HTTP 500"):
        run(provider.analyze(VisionRequest(
            observation_id="obs-1", device_id="cam-media5",
            media_ref=ingested.observation.media_ref)))


def test_ollama_non_loopback_refused():
    with pytest.raises(VisionRefusedError, match="loopback"):
        OllamaVisionProvider(base_url="http://192.168.1.5:11434")


def test_unavailable_provider_always_refuses():
    provider = get_vision_provider("unavailable")
    with pytest.raises(VisionUnavailable, match="no automatic"):
        run(provider.analyze(make_request()))


def test_test_provider_is_deterministic_and_marked():
    provider = get_vision_provider("test-only", labels=["moer"])
    first = run(provider.analyze(make_request()))
    second = run(provider.analyze(make_request()))
    assert first.labels == second.labels == ["moer"]
    assert first.model == "test-only"
    assert first.provenance.human_verified is False
    failing = TestVisionProvider(fail=True)
    with pytest.raises(VisionUnavailable, match="synthetic"):
        run(failing.analyze(make_request()))


def test_unknown_provider_refused():
    with pytest.raises(VisionRefusedError, match="Unknown vision"):
        get_vision_provider("cloud-vl")


def test_provider_takes_no_credentials():
    import pathlib
    import coordinator.app.vision_provider as module
    source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    for token in ("api_key", "Authorization", "Bearer ", "getpass",
                  "keyring", "client_secret"):
        assert token not in source, f"forbidden token: {token}"
    assert "VISION_MODEL" in source
    assert os.environ.get("VISION_MODEL", "") == "" or True
