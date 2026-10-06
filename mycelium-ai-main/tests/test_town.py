"""Town fase 3 (gesprekken) + fase 4 (geheugen).

Bestaande chat-tabellen worden hergebruikt; NPC-antwoorden hebben
geen model in tests (HERMES_API_KEY afwezig) dus eerlijke
system-noot. Geen netwerk, geen hardware.
"""
from contextlib import contextmanager

import coordinator.app.main as main_mod


@contextmanager
def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "queue.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "chat.db"))
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR",
                       str(tmp_path / "fab"))
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("HERMES_API_KEY", raising=False)
    # Ollama expres dood: fallback-gedrag deterministisch, geen lokaal
    # model nodig in pytest (live bewijs staat los hiervan).
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")
    with TestClient(main_mod.app) as client:
        yield client


def _open(client, title="Plein", participants=None):
    res = client.post("/api/v1/town/conversations", json={
        "title": title, "participants": participants or ["you"]})
    assert res.status_code == 201, res.text
    return res.json()


def test_town_open_and_validation(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        convo = _open(client)
        assert convo["conversation_id"].startswith("town_")
        assert convo["participants"] == ["you"]
        empty = client.post("/api/v1/town/conversations", json={
            "title": "x", "participants": []})
        assert empty.status_code == 422
        missing = client.get(
            "/api/v1/town/conversations/nope/messages")
        assert missing.status_code == 404


def test_town_round_robin_with_honest_npc(tmp_path, monkeypatch):
    """Mensbericht -> hooguit één NPC-beurt; zonder model een
    system-noot (nooit stilte, nooit verzinsel); beurt roteert."""
    with _client(tmp_path, monkeypatch) as client:
        convo = _open(client)
        cid = convo["conversation_id"]
        first = client.post(
            f"/api/v1/town/conversations/{cid}/messages", json={
                "speaker": "you", "role": "human",
                "text": "Hallo stad!"})
        assert first.status_code == 201, first.text
        turn = first.json()["npc_turn"]
        assert turn is not None
        assert turn["role"] in ("npc:mos", "system")
        second = client.post(
            f"/api/v1/town/conversations/{cid}/messages", json={
                "speaker": "you", "role": "human",
                "text": "Wie is er nog meer?"})
        turn2 = second.json()["npc_turn"]
        assert turn2 is not None
        assert turn2["role"] in ("npc:oracle", "system")
        assert turn2["role"] != turn["role"] or \
            turn["role"] == "system"
        history = client.get(
            f"/api/v1/town/conversations/{cid}/messages").json()
        assert len(history) == 4
        assert history[0]["content"] == "Hallo stad!"
        bad_role = client.post(
            f"/api/v1/town/conversations/{cid}/messages", json={
                "speaker": "you", "role": "vogel",
                "text": "x"})
        assert bad_role.status_code == 422
        empty_text = client.post(
            f"/api/v1/town/conversations/{cid}/messages", json={
                "speaker": "you", "role": "human", "text": "  "})
        assert empty_text.status_code == 422


def test_town_memory_record_recall_and_reflect(tmp_path, monkeypatch):
    from coordinator.app.town_memory import (
        TownRefusedError,
        recall_memories,
        record_memory,
    )
    record_memory("tester", "klein feit", 0.2)
    record_memory("tester", "groot feit", 0.9)
    record_memory("ander", "elders", 1.0)
    recalled = recall_memories("tester")
    assert [m["text"] for m in recalled] == ["groot feit", "klein feit"]
    assert recalled[0]["importance"] == 0.9
    try:
        record_memory("", "x")
    except TownRefusedError:
        pass
    else:
        raise AssertionError("lege agent geweigerd verwacht")
    try:
        record_memory("tester", "x", 0.5, kind="droom")
    except TownRefusedError:
        pass
    else:
        raise AssertionError("onbekende kind geweigerd verwacht")
    with _client(tmp_path, monkeypatch) as client:
        res = client.post("/api/v1/town/reflect",
                          json={"agent": "tester"})
        assert res.status_code == 409
        assert "model" in res.json()["detail"].lower()


def test_solarpunk_town_panel_present(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        res = client.get("/solarpunk")
        assert res.status_code == 200
        assert 'id="spc-town"' in res.text
        assert 'id="spc-town-send"' in res.text


def test_ollama_fallback_replies_as_npc(tmp_path, monkeypatch):
    """Hermes dood + Ollama gemockt -> echte npc-beurt, geen noot."""
    import httpx as _httpx
    from types import SimpleNamespace

    def fake_post(url, json=None, timeout=None):
        assert url == "http://127.0.0.1:9/api/chat"
        assert json["model"]
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"message": {"content": "Hallo van Ollama"}})
    monkeypatch.setattr(_httpx, "post", fake_post)
    with _client(tmp_path, monkeypatch) as client:
        convo = _open(client)
        cid = convo["conversation_id"]
        res = client.post(
            f"/api/v1/town/conversations/{cid}/messages", json={
                "speaker": "you", "role": "human",
                "text": "Hallo?"})
        assert res.status_code == 201, res.text
        turn = res.json()["npc_turn"]
        assert turn["role"] == "npc:mos"
        assert turn["content"] == "Hallo van Ollama"


def test_ollama_validation_needs_no_network(monkeypatch):
    from coordinator.app.ollama_chat import (
        OllamaRefusedError,
        base_url,
        model_name,
        ollama_say,
    )
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    assert base_url() == "http://127.0.0.1:11434"
    for bad in ("http://example.com", "https://127.0.0.1:11434",
                "http://127.0.0.1:11434 evil", "ftp://127.0.0.1/x"):
        monkeypatch.setenv("OLLAMA_BASE_URL", bad)
        try:
            base_url()
        except OllamaRefusedError:
            pass
        else:
            raise AssertionError(f"bad url accepted: {bad}")
    monkeypatch.setenv("OLLAMA_CHAT_MODEL", "phi4-mini")
    assert model_name() == "phi4-mini"
    for bad_model in ("", "a" * 81, "evil;rm", "met spatie"):
        monkeypatch.setenv("OLLAMA_CHAT_MODEL", bad_model)
        try:
            model_name()
        except OllamaRefusedError:
            pass
        else:
            raise AssertionError(f"bad model accepted: {bad_model}")
    monkeypatch.setenv("OLLAMA_CHAT_MODEL", "phi4-mini")
    for npc, msg in (("nope", "hi"), ("mos", "  ")):
        try:
            ollama_say(npc, msg)
        except OllamaRefusedError:
            pass
        else:
            raise AssertionError(f"bad input accepted: {npc}/{msg!r}")


def test_residents_awake_chip_with_key(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        monkeypatch.setenv("HERMES_API_KEY", "test-key")
        res = client.get("/solarpunk")
        assert "wakker" in res.text
