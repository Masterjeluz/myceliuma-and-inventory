"""Hermes all-NPC + durable history + opt-in screen summary tests.

Fake bridge and fake vision only: live Hermes/Ollama never needed.
Tmp databases via monkeypatch (no os.environ leaks).
"""

from fastapi.testclient import TestClient

import coordinator.app.hermes_npc as npc_mod
import coordinator.app.main as main_mod
from coordinator.app.hermes_bridge import HermesUnavailable

ALL_NPCS = ("mos", "oracle", "smid", "archivaris", "voorman",
            "seinwachter")


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "hall.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "hall-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", "hall-operator")
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")
    with TestClient(main_mod.app) as test_client:
        yield test_client


class _FakeBridge:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def send(self, session_key, message, max_tokens=500):
        self.calls.append((session_key, message, max_tokens))
        return {"session_key": session_key, "message_id": "m1",
                "model": "hermes-agent", "text": "Hallo, ik luister.",
                "finish_reason": "stop"}


def _fake_factory(store):
    def factory(*args, **kwargs):
        fake = _FakeBridge()
        store.append(fake)
        return fake
    return factory


def test_all_npcs_known_and_chat_200(tmp_path, monkeypatch):
    fakes = []
    monkeypatch.setattr(npc_mod, "HermesBridge", _fake_factory(fakes))
    for test_client in api(tmp_path, monkeypatch):
        for npc in ALL_NPCS:
            assert npc_mod.npc_session_key(npc, "play_x") == \
                f"npc-{npc}-play_x"
            res = test_client.post("/api/v1/hermes/chat", json={
                "npc_id": npc, "message": f"Hoi {npc}!",
                "session_id": "play_x"})
            assert res.status_code == 200, (npc, res.text)
            body = res.json()
            assert body["npc_id"] == npc
            assert body["npc_name"] == npc_mod.HERMES_NPCS[npc]["name"]
            assert body["session_key"] == f"npc-{npc}-play_x"
            assert body["conversation_id"].startswith("conv-hermes-")
        assert len(fakes) == len(ALL_NPCS)


def test_history_persists_across_turns(tmp_path, monkeypatch):
    fakes = []
    monkeypatch.setattr(npc_mod, "HermesBridge", _fake_factory(fakes))
    for test_client in api(tmp_path, monkeypatch):
        first = test_client.post("/api/v1/hermes/chat", json={
            "npc_id": "oracle", "message": "eerste vraag",
            "session_id": "play_hist"}).json()
        conv = first["conversation_id"]
        second = test_client.post("/api/v1/hermes/chat", json={
            "npc_id": "oracle", "message": "tweede vraag",
            "session_id": "play_hist"}).json()
        assert second["conversation_id"] == conv
        hist = test_client.get("/api/v1/hermes/history", params={
            "npc_id": "oracle", "session_id": "play_hist"})
        assert hist.status_code == 200, hist.text
        body = hist.json()
        assert body["conversation_id"] == conv
        assert body["session_key"] == "npc-oracle-play_hist"
        roles = [t["role"] for t in body["turns"]]
        assert roles == ["user", "agent", "user", "agent"]
        texts = [t["content"] for t in body["turns"]]
        assert "eerste vraag" in texts[0]
        assert "tweede vraag" in texts[2]
        # Other NPC, same play session: separate durable thread.
        other = test_client.post("/api/v1/hermes/chat", json={
            "npc_id": "smid", "message": "smid vraag",
            "session_id": "play_hist"}).json()
        assert other["conversation_id"] != conv


def test_history_route_validation(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        assert test_client.get("/api/v1/hermes/history", params={
            "npc_id": "dragon", "session_id": "x"}).status_code == 422
        empty = test_client.get("/api/v1/hermes/history", params={
            "npc_id": "mos", "session_id": "nooit-gezien"})
        assert empty.status_code == 200
        assert empty.json()["turns"] == []


def test_include_screen_without_rows_is_200(tmp_path, monkeypatch):
    fakes = []
    monkeypatch.setattr(npc_mod, "HermesBridge", _fake_factory(fakes))
    for test_client in api(tmp_path, monkeypatch):
        res = test_client.post("/api/v1/hermes/chat", json={
            "npc_id": "mos", "message": "Hoi", "session_id": "play_s",
            "include_screen": True})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["conversation_id"].startswith("conv-hermes-")
        assert body["screen_vlm"]["state"] == "UNAVAILABLE"
        assert "geen schermwaarneming" in body["screen_vlm"]["reason"].lower()


def test_include_screen_vlm_text_only(tmp_path, monkeypatch):
    from coordinator.app import vision_provider as vp_mod
    from coordinator.app.vision_provider import VisionResult

    seen = {}

    class _FakeVision:
        async def analyze(self, request):
            seen["media_ref"] = request.media_ref
            seen["device_id"] = request.device_id
            return VisionResult(
                analysis_id="a-screen-1",
                observation_id=request.observation_id,
                device_id=request.device_id,
                labels=["venster", "teksteditor"],
                detected_objects=[],
                description="Een donker venster met een teksteditor.",
                ocr_text="", uncertainty="", raw_text="",
                model="fake-vlm", observed_at="2026-01-01T00:00:00")

    monkeypatch.setattr(vp_mod, "get_vision_provider",
                        lambda *a, **k: _FakeVision())
    fakes = []
    monkeypatch.setattr(npc_mod, "HermesBridge", _fake_factory(fakes))
    for test_client in api(tmp_path, monkeypatch):
        made = test_client.post("/api/v1/world/observations", json={
            "node_id": "node-desk", "source": "screen",
            "note": "werkblad", "media_ref": "shot-9.png",
            "provenance": {"window": "Editor"}}).json()
        assert made["obs_id"].startswith("wobs_")
        res = test_client.post("/api/v1/hermes/chat", json={
            "npc_id": "mos", "message": "Wat zie je op mijn scherm?",
            "session_id": "play_v", "include_screen": True})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["screen_vlm"]["state"] == "REAL"
        assert body["screen_vlm"]["model"] == "fake-vlm"
        assert "Een donker venster" in body["screen_vlm"]["summary"]
        assert seen.get("media_ref") == "shot-9.png"
        prompt = fakes[-1].calls[-1][1]
        assert "Schermsamenvatting (VLM-tekst, opt-in, REAL)" in prompt
        assert "venster" in prompt
        assert "Een donker venster met een teksteditor." in prompt
        # The pre-existing metadata line keeps the filename reference;
        # pixel bytes never enter the prompt (the vision layer only
        # returns labels + description text, asserted above).
        assert "Schermstatus (alleen lezen, nooit handelen)" in prompt


def test_screen_vlm_unavailable_reason_is_returned(tmp_path, monkeypatch):
    from coordinator.app import vision_provider as vp_mod

    class _VisionDown:
        async def analyze(self, request):
            raise vp_mod.VisionUnavailable("Vision model timed out")

    monkeypatch.setattr(vp_mod, "get_vision_provider",
                        lambda *a, **k: _VisionDown())
    fakes = []
    monkeypatch.setattr(npc_mod, "HermesBridge", _fake_factory(fakes))
    for test_client in api(tmp_path, monkeypatch):
        made = test_client.post("/api/v1/world/observations", json={
            "node_id": "node-down", "source": "screen",
            "media_ref": "shot-down.png"})
        assert made.status_code == 201, made.text
        res = test_client.post("/api/v1/hermes/chat", json={
            "npc_id": "mos", "message": "Wat zie je?",
            "session_id": "play_vlm_down", "include_screen": True})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["screen_vlm"]["state"] == "UNAVAILABLE"
        assert "Vision model timed out" in body["screen_vlm"]["reason"]
        assert body["screen_vlm"]["summary"] == ""
        assert "Schermsamenvatting" not in fakes[-1].calls[-1][1]


def test_include_screen_vlm_down_degrades(tmp_path, monkeypatch):
    class _Down:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, *args, **kwargs):
            raise HermesUnavailable("down")

    monkeypatch.setattr(npc_mod, "HermesBridge", _Down)
    for test_client in api(tmp_path, monkeypatch):
        res = test_client.post("/api/v1/hermes/chat", json={
            "npc_id": "voorman", "message": "status?",
            "session_id": "play_d", "include_screen": True})
        # Hermes down still maps to 502 even with opt-in screen on.
        assert res.status_code == 502, res.text


def test_side_has_npc_chat_markers(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        html = test_client.get("/side").text
        for marker in ("mostalk", "mossend", "mospropose",
                       "echte agent", "hermes/chat", "Missie 0",
                       "/approvals", "npctalk", "npcscreen",
                       "hermes/history"):
            assert marker in html, marker
