"""Chat API tests (Fase A/N/Q).

Conversation persistence, INVENTory context integration, source
preservation, provider fallback honesty, and the chat UI pages.
World reads and providers are faked; nothing reaches INVENTory or
a real model.
"""

import os

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.inventory_read import Provenance, SearchResult
from coordinator.app.ollama_advisor import AdviceResponse


class FakeReader:
    def __init__(self, results=None, error=None):
        self._results = results or []
        self._error = error

    async def search(self, q, type=None):
        if self._error:
            raise self._error
        from coordinator.app.inventory_read import SearchResponse
        return SearchResponse(query=q, results=self._results,
                              total=len(self._results))

    async def browse(self, type=None):
        return await self.search("", type)


class FakeProvider:
    def __init__(self, advice="Gebruik je Arduino en sensor.",
                 fail=None):
        self._advice = advice
        self._fail = fail
        self.seen = []

    async def advise(self, question, records):
        if self._fail:
            raise self._fail
        self.seen.append((question, records))
        return AdviceResponse(
            question=question, advice=self._advice, model="fake-local",
            records_used=len(records), sources=[])


def make_result(entity_id="obj_abc123", title="Arduino Uno"):
    return SearchResult(
        entity_type="object", entity_id=entity_id, title=title,
        snippet="bordje in lade 3",
        provenance=Provenance(source_type="user-created",
                              creator_id="jelles", human_verified=True),
        details={})


def client(tmp_path, monkeypatch, reader=None, provider=None):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH", str(tmp_path / "chat.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH", str(
        tmp_path / "chat-state.db"))
    monkeypatch.setattr(main_mod, "_world_reader",
                        lambda: reader or FakeReader(
                            [make_result()]))
    monkeypatch.setattr(main_mod, "get_provider",
                        lambda name=None, **k: provider or FakeProvider())
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_chat_turn_stores_conversation_and_sources(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        response = test_client.post("/api/v1/chat", json={
            "message": "Wat kan ik maken met mijn onderdelen?"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["conversation_id"].startswith("conv-")
        assert body["records_used"] == 1
        assert body["sources"][0]["entity_id"] == "obj_abc123"
        assert body["model"] == "fake-local"
        assert body["provider_error"] is None

        detail = test_client.get(
            f"/api/v1/conversations/{body['conversation_id']}")
        assert detail.status_code == 200
        roles = [msg["role"] for msg in detail.json()["messages"]]
        assert roles == ["user", "assistant"]


def test_chat_second_turn_keeps_conversation(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        first = test_client.post("/api/v1/chat", json={"message": "hoi"})
        conversation = first.json()["conversation_id"]
        second = test_client.post("/api/v1/chat", json={
            "conversation_id": conversation, "message": "en nu?"})
        assert second.json()["conversation_id"] == conversation
        detail = test_client.get(f"/api/v1/conversations/{conversation}")
        assert len(detail.json()["messages"]) == 4


def test_chat_without_model_is_honest_not_fabricated(tmp_path, monkeypatch):
    from coordinator.app.providers import ProviderUnavailable
    failing = FakeProvider(fail=ProviderUnavailable("Ollama down"))
    for test_client in client(tmp_path, monkeypatch, provider=failing):
        response = test_client.post("/api/v1/chat", json={
            "message": "Wat kan ik maken?"})
        assert response.status_code == 200
        body = response.json()
        assert body["provider_error"] is not None
        assert "onbereikbaar" in body["reply"]
        assert "geen AI-advies" in body["reply"]
        assert body["model"] == ""


def test_chat_without_inventory_still_answers(tmp_path, monkeypatch):
    from coordinator.app.inventory_read import InventoryUnavailable
    reader = FakeReader(error=InventoryUnavailable("down"))
    for test_client in client(tmp_path, monkeypatch, reader=reader):
        response = test_client.post("/api/v1/chat", json={
            "message": "hallo"})
        assert response.status_code == 200
        body = response.json()
        assert "INVENTory" in (body["provider_error"] or "")


def test_chat_unknown_provider_refused(tmp_path, monkeypatch):
    from coordinator.app.providers import ProviderRefusedError

    def bad_provider(name=None, **kwargs):
        raise ProviderRefusedError("Unknown AI provider")

    monkeypatch.setenv("MYCELIUM_DATABASE_PATH", str(tmp_path / "chat.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH", str(
        tmp_path / "chat-state.db"))
    monkeypatch.setattr(main_mod, "get_provider", bad_provider)
    with TestClient(main_mod.app) as test_client:
        response = test_client.post("/api/v1/chat", json={
            "message": "hallo"})
        assert response.status_code == 422


def test_chat_extracts_proposal_best_effort(tmp_path, monkeypatch):
    advice = ('Plan: ```json {"proposed_action": "Soldeer de sensor", '
              '"expected_output": "werkende meting", "risks": []}```')
    for test_client in client(tmp_path, monkeypatch,
                              provider=FakeProvider(advice=advice)):
        body = test_client.post("/api/v1/chat", json={
            "message": "maak een plan"}).json()
        assert body["proposal"] is not None
        assert body["proposal"]["requires_approval"] is True


def test_chat_requires_post_only(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        assert test_client.get("/api/v1/chat").status_code == 405


def test_conversation_pages_and_nav(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        home = test_client.get("/")
        assert home.status_code == 200
        assert "/chat" in home.text and "/agents" in home.text
        assert "Nodes" in home.text and "Tasks" in home.text
        chat_page = test_client.get("/chat")
        assert chat_page.status_code == 200
        assert "Mycelium Chat" in chat_page.text
        agents_page = test_client.get("/agents")
        assert agents_page.status_code == 200
        assert "approval" in agents_page.text.lower()


def test_web_chat_form_roundtrip(tmp_path, monkeypatch):
    for test_client in client(tmp_path, monkeypatch):
        response = test_client.post(
            "/web/chat", content="message=hallo+daar",
            headers={"Content-Type":
                     "application/x-www-form-urlencoded"})
        assert response.history[0].status_code == 303
        assert response.history[0].headers["location"].startswith(
            "/chat?id=conv-")
