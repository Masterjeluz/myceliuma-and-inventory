"""BIG #34 tests: camera ecosystem — sessions, VLM honesty,
candidates, matching, links, timeline, security, UI contracts.
"""

import os

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.camera_ecosystem import (
    EcosystemRefusedError,
    check_filenames,
    check_session_id,
    create_session,
    describe_observation,
    list_sessions,
    load_session,
    possible_matches,
    propose_candidates,
    run_session,
    suggest_link,
    timeline,
)


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b34.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b34-chat.db"))
    with TestClient(main_mod.app) as client:
        yield client


def _write_inbox(filename: str, seed: int = 0x10) -> str:
    from coordinator.app.cameras import camera_dir, write_bmp_24
    path = os.path.join(camera_dir(), filename)
    write_bmp_24(path, 8, 8,
                 bytes([(seed + index) % 256 for index in
                        range(64 * 3)]))
    return filename


def _register(client, name="B34 cam", source="insta360"):
    response = client.post("/api/v1/cameras/register", json={
        "name": name, "kinds": ["snapshot"], "source": source})
    assert response.status_code == 201, response.text
    return response.json()["device_id"]


# -- session validation --------------------------------------------------------

def test_session_id_rules():
    with pytest.raises(EcosystemRefusedError):
        check_session_id("")
    with pytest.raises(EcosystemRefusedError):
        check_session_id("obs-123")
    with pytest.raises(EcosystemRefusedError):
        check_session_id("cing_../x")
    assert check_session_id("cing_abc123").startswith("cing_")


def test_filenames_hostile(tmp_path, monkeypatch):
    for _ in make_client(tmp_path, monkeypatch):
        for bad in ([], ["../evil.png"], ["http://x/y.png"],
                    ["a.png"] * 9, [""], ["a.jpg"], ["a.png", "a.png"],
                    ["/abs.png"], ["..\\win.png"]):
            with pytest.raises(EcosystemRefusedError):
                check_filenames(bad)
        assert check_filenames(["a.png", "b.bmp"]) == ["a.png", "b.bmp"]


def test_session_unknown_device(tmp_path, monkeypatch):
    for _ in make_client(tmp_path, monkeypatch):
        with pytest.raises(EcosystemRefusedError):
            create_session("cam_missing", ["a.png"])


# -- multi-file ingest + dedupe --------------------------------------------------

def test_session_ingest_and_dedupe(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        device_id = _register(client)
        first = _write_inbox("b34-first.png", seed=0x10)
        second = _write_inbox("b34-second.png", seed=0x90)
        created = client.post("/api/v1/camera-sessions", json={
            "device_id": device_id,
            "filenames": [first, second]}).json()
        assert created["session_id"].startswith("cing_")
        assert created["state"] == "open"
        ran = client.post(
            f"/api/v1/camera-sessions/{created['session_id']}/run"
        ).json()
        assert ran["session"]["state"] == "complete"
        assert len(ran["observations"]) == 2
        assert {item["state"] for item in
                ran["session"]["items"]} == {"observed"}
        # Replay: same bytes refuse as duplicates, no new observations.
        replay = client.post("/api/v1/camera-sessions", json={
            "device_id": device_id, "filenames": [first]}).json()
        rerun = client.post(
            f"/api/v1/camera-sessions/{replay['session_id']}/run"
        ).json()
        assert rerun["session"]["items"][0]["state"] == "duplicate"
        assert rerun["observations"] == []
        # Session detail + listing.
        fetched = client.get(
            f"/api/v1/camera-sessions/{created['session_id']}")
        assert fetched.status_code == 200
        assert len(fetched.json()["observations"]) == 2
        listed = client.get("/api/v1/camera-sessions",
                            params={"device_id": device_id}).json()
        assert len(listed["sessions"]) == 2
        assert client.get("/api/v1/camera-sessions/cing_nope"
                          ).status_code == 404
        assert client.get("/api/v1/camera-sessions/nope"
                          ).status_code == 422


def test_session_missing_file_refuses(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        device_id = _register(client)
        created = client.post("/api/v1/camera-sessions", json={
            "device_id": device_id,
            "filenames": ["b34-ghost.png"]}).json()
        ran = client.post(
            f"/api/v1/camera-sessions/{created['session_id']}/run"
        ).json()
        assert ran["session"]["items"][0]["state"] == "refused"
        assert ran["observations"] == []


# -- VLM honesty -------------------------------------------------------------------

def test_describe_fallback_unavailable(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        device_id = _register(client)
        name = _write_inbox("b34-vlm.png")
        created = client.post("/api/v1/camera-sessions", json={
            "device_id": device_id, "filenames": [name]}).json()
        ran = client.post(
            f"/api/v1/camera-sessions/{created['session_id']}/run"
        ).json()
        observation_id = ran["observations"][0]["observation_id"]
        # No Ollama here: honest UNAVAILABLE fallback, no labels.
        described = client.post(
            f"/api/v1/observations/{observation_id}/describe",
            json={}).json()
        assert described["vlm_state"] == "UNAVAILABLE"
        assert described["analysis"]["labels"] == []
        assert described["analysis"]["detected_objects"] == []
        assert described["analysis"]["model"] == ""
        assert "VLM" in described["analysis"]["uncertainty"]
        assert client.post("/api/v1/observations/obs_missing/describe",
                           json={}).status_code == 422
        # Fallback yields no candidates — nothing invented.
        proposed = client.post(
            f"/api/v1/observations/{observation_id}/propose-candidates"
        ).json()
        assert proposed["candidates"] == []


def test_describe_real_with_mock_transport(tmp_path, monkeypatch):
    import json as _json
    import httpx
    from coordinator.app.vision_provider import OllamaVisionProvider
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        payload = {"message": {"content": (
            "label: zonnepaneel (0.82)\n"
            "label: kabel (0.41)\n"
            "Een paneel met een kabel ernaast.")}}
        return httpx.Response(200, json=payload)

    provider = OllamaVisionProvider(
        transport=httpx.MockTransport(handler))
    from coordinator.app.cameras import camera_dir
    from coordinator.app.vision_provider import VisionRequest
    name = _write_inbox("b34-mock.png")
    import anyio
    result = anyio.run(
        provider.analyze,
        VisionRequest(observation_id="obs-test", device_id="cam-x",
                      media_ref=name, question="Wat zie je?"))
    assert result.model == "qwen3-vl:4b"
    assert "zonnepaneel" in result.labels
    assert seen["url"].startswith("http://127.0.0.1:11434")
    assert camera_dir()


# -- candidates: REAL labels only, idempotent -----------------------------------------

def test_propose_candidates_idempotent(tmp_path, monkeypatch):
    from coordinator.app.vision_flow import (VisionAnalysisRecord,
                                             save_analysis)
    for client in make_client(tmp_path, monkeypatch):
        device_id = _register(client)
        name = _write_inbox("b34-cand.png")
        created = client.post("/api/v1/camera-sessions", json={
            "device_id": device_id, "filenames": [name]}).json()
        ran = client.post(
            f"/api/v1/camera-sessions/{created['session_id']}/run"
        ).json()
        observation_id = ran["observations"][0]["observation_id"]
        save_analysis(VisionAnalysisRecord(
            analysis_id="an_b34test", observation_id=observation_id,
            device_id=device_id,
            result={"analysis_id": "an_b34test",
                    "observation_id": observation_id,
                    "device_id": device_id, "labels": ["zonnepaneel"],
                    "detected_objects": [
                        {"label": "zonnepaneel", "confidence": 0.8}],
                    "description": "test", "ocr_text": "",
                    "uncertainty": "", "raw_text": "test",
                    "model": "test-mock",
                    "observed_at": "2026-01-01T00:00:00+00:00",
                    "provenance": {}},
            created_at="2026-01-01T00:00:00+00:00"))
        first = client.post(
            f"/api/v1/observations/{observation_id}/propose-candidates"
        ).json()
        assert len(first["candidates"]) == 1
        assert first["candidates"][0]["label"] == "zonnepaneel"
        candidate_id = client.get("/api/v1/candidates").json()[
            "candidates"][0]["candidate_id"]
        assert candidate_id.startswith("cand_")
        # Replay: idempotent, no second candidate.
        second = client.post(
            f"/api/v1/observations/{observation_id}/propose-candidates"
        ).json()
        assert second["candidates"] == []
        assert len(client.get("/api/v1/candidates").json()[
            "candidates"]) == 1


# -- matching + links ------------------------------------------------------------------

def test_match_validation_and_shape(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        with pytest.raises(EcosystemRefusedError):
            possible_matches("")
        with pytest.raises(EcosystemRefusedError):
            possible_matches("a b")
        matches = possible_matches("zonnepaneel camper", limit=3)
        assert isinstance(matches, list) and len(matches) <= 3
        assert client.get("/api/v1/camera-match",
                          params={"q": ""}).status_code == 422


def test_match_api_and_suggest_link(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.get("/api/v1/camera-match",
                          params={"q": ""}).status_code == 422
        device_id = _register(client)
        name = _write_inbox("b34-link.png")
        created = client.post("/api/v1/camera-sessions", json={
            "device_id": device_id, "filenames": [name]}).json()
        ran = client.post(
            f"/api/v1/camera-sessions/{created['session_id']}/run"
        ).json()
        observation_id = ran["observations"][0]["observation_id"]
        bad = client.post("/api/v1/camera-suggest-link", json={
            "observation_id": observation_id, "entity_id": "xxx_1",
            "predicate": "used_in"})
        assert bad.status_code == 422
        bad_pred = client.post("/api/v1/camera-suggest-link", json={
            "observation_id": observation_id,
            "entity_id": "proj_demo", "predicate": "owns"})
        assert bad_pred.status_code == 422
        linked = client.post("/api/v1/camera-suggest-link", json={
            "observation_id": observation_id,
            "entity_id": "proj_demo", "predicate": "supports"})
        assert linked.status_code == 201, linked.text
        body = linked.json()
        assert body["state"] == "PROPOSED"
        # Visible as PROPOSED symbiosis via entity_refs.
        from coordinator.app.symbiosis import proposed
        assert any(body["candidate_id"] ==
                   item["candidate_id"] for item in proposed(limit=20))


# -- timeline ----------------------------------------------------------------------------

def test_timeline_needs_scope_and_lists_session(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.get("/api/v1/camera-timeline"
                          ).status_code == 422
        device_id = _register(client)
        name = _write_inbox("b34-time.png")
        created = client.post("/api/v1/camera-sessions", json={
            "device_id": device_id, "filenames": [name]}).json()
        client.post(
            f"/api/v1/camera-sessions/{created['session_id']}/run")
        line = client.get("/api/v1/camera-timeline",
                          params={"device_id": device_id}).json()
        assert any(device_id in item["text"] or "Session" in
                   item["text"] for item in line["timeline"])
        assert timeline(device_id=device_id)


# -- UI contracts --------------------------------------------------------------------------

def test_camera_pages(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        page = client.get("/cameras")
        assert page.status_code == 200
        assert "Camera Lab" in page.text
        assert "UNAVAILABLE" in page.text
        assert "WHAT EXISTS" in page.text
        assert "Camera Guide" in page.text
        device_id = _register(client)
        detail = client.get(f"/cameras/{device_id}")
        assert detail.status_code == 200
        assert "Multi-file ingest session" in detail.text
        assert "Timeline" in detail.text
        assert "Suggest a link" in detail.text
        assert client.get("/cameras/cam_missing").status_code == 404
        mobile = client.get("/mobile").text
        assert "Camera Lab" in mobile
        guide = client.get("/api/v1/guide").json()
        assert "items" in guide


def test_web_session_flow(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        device_id = _register(client)
        name = _write_inbox("b34-web.png")
        response = client.post("/web/camera-sessions", data={
            "device_id": device_id, "filenames": name})
        assert response.status_code in (200, 303)
        detail = client.get(f"/cameras/{device_id}").text
        assert "complete" in detail or "observed" in detail or \
            "b34-web" in detail
