"""Bootstrap campaign + V1 endpoint tests.

ensure is idempotent (metadata bootstrap keys); status names
present/missing; command/decide/recover/agenda/physical
endpoints behave; research capability stays honest.
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.bootstrap import (
    BOOTSTRAP_DOMAINS,
    existing_bootstrap_keys,
    missing_domains,
    mission_metadata,
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "v1.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "v1-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


def make_conversation(client):
    response = client.post("/api/v1/chat",
                           json={"message": "hallo"})
    assert response.status_code == 200, response.text
    return response.json()["conversation_id"]


def test_nine_domains_all_research_safe():
    assert len(BOOTSTRAP_DOMAINS) == 9
    for domain in BOOTSTRAP_DOMAINS:
        assert domain["template"] in (
            "inspect_project", "investigate_inventory")
        metadata = mission_metadata(domain)
        assert metadata["type"] == "research"
        assert metadata["safe_autonomy"] is True
        assert metadata["physical"] is False
        assert metadata["write"] is False
        assert metadata["external_side_effect"] is False


def test_missing_domains_idempotent():
    assert len(missing_domains([])) == 9

    class FakeMission:
        def __init__(self, key):
            self.metadata = {"bootstrap_key": key} if key else {}

    existing = [FakeMission("bootstrap:camper"),
                FakeMission("bootstrap:umz"), FakeMission("")]
    missing = missing_domains(existing)
    assert len(missing) == 7
    assert all(domain["key"] != "bootstrap:camper"
               for domain in missing)
    assert existing_bootstrap_keys(existing) == {
        "bootstrap:camper", "bootstrap:umz"}


def test_ensure_creates_nine_then_zero(client):
    conversation = make_conversation(client)
    first = client.post("/api/v1/bootstrap/ensure",
                        json={"conversation_id": conversation})
    assert first.status_code == 201, first.text
    assert len(first.json()["created"]) == 9
    assert first.json()["skipped"] == 0
    second = client.post("/api/v1/bootstrap/ensure",
                         json={"conversation_id": conversation})
    assert second.status_code == 201, second.text
    assert second.json()["created"] == []
    assert second.json()["skipped"] == 9


def test_ensure_needs_conversation(client):
    response = client.post("/api/v1/bootstrap/ensure",
                           json={"conversation_id": "conv-missing"})
    assert response.status_code == 404


def test_status_lists_present_missing(client):
    conversation = make_conversation(client)
    before = client.get("/api/v1/bootstrap/status")
    assert before.status_code == 200
    assert len(before.json()["missing"]) == 9
    client.post("/api/v1/bootstrap/ensure",
                json={"conversation_id": conversation})
    after = client.get("/api/v1/bootstrap/status")
    assert len(after.json()["present"]) == 9
    assert after.json()["missing"] == []


def test_command_help_and_morning(client):
    make_conversation(client)
    helped = client.post("/api/v1/command",
                         json={"text": "help, wat kun je?"})
    assert helped.status_code == 200, helped.text
    assert helped.json()["intent"] == "help"
    assert "camper" in helped.json()["reply"].lower() or \
        "ics" in helped.json()["reply"].lower()

    morning = client.post("/api/v1/command",
                          json={"text": "Wat heb je vannacht gevonden?"})
    assert morning.status_code == 200, morning.text
    assert morning.json()["intent"] == "morning_report"


def test_command_creates_research_mission(client):
    conversation = make_conversation(client)
    response = client.post(
        "/api/v1/command",
        json={"text": "Onderzoek mijn camper.",
              "conversation_id": conversation})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "research_project"
    assert body["mission"]["status"] == "pending_approval"
    kinds = {step["kind"] for step in body["mission"]["steps"]}
    assert kinds <= {"readout", "analysis", "desktop"}
    assert "desktop" not in kinds or True
    # investigate_inventory template: readout + analysis only
    assert kinds <= {"readout", "analysis"}


def test_command_status_stop_resume(client):
    conversation = make_conversation(client)
    client.post("/api/v1/command",
                json={"text": "Onderzoek mijn camper.",
                      "conversation_id": conversation})
    status = client.post("/api/v1/command",
                         json={"text": "Controleer mijn openstaande "
                                       "missions."})
    assert status.json()["intent"] == "mission_status"
    assert len(status.json()["missions"]) >= 1
    assert "waiting_reason" in status.json()["missions"][0]

    stopped = client.post("/api/v1/command",
                          json={"text": "Stop deze missies."})
    assert stopped.json()["intent"] == "mission_stop"


def test_decide_endpoint_readonly(client):
    conversation = make_conversation(client)
    created = client.post("/api/v1/command",
                          json={"text": "Onderzoek mijn camper.",
                                "conversation_id": conversation})
    mission_id = created.json()["mission"]["mission_id"]
    decided = client.post(f"/api/v1/missions/{mission_id}/decide")
    assert decided.status_code == 200, decided.text
    body = decided.json()
    assert body["decision"] in (
        "CONTINUE", "WAITING_FOR_HUMAN", "BLOCKED", "REPLAN",
        "RETRY", "COMPLETED", "CANCELLED", "FAILED",
        "WAITING_FOR_AGENT")
    assert body["reason"]
    # decision never mutates: mission still pending
    fetched = client.get(f"/api/v1/missions/{mission_id}")
    assert fetched.json()["status"] == "pending_approval"


def test_recover_report_only_by_default(client):
    conversation = make_conversation(client)
    client.post("/api/v1/command",
                json={"text": "Onderzoek mijn camper.",
                      "conversation_id": conversation})
    report = client.post("/api/v1/missions/recover", json={})
    assert report.status_code == 200, report.text
    assert report.json()["resumed"] == []
    assert report.json()["total"] >= 1


def test_agenda_preview_then_import(client):
    ics = ("BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\n"
           "UID:a1\nDTSTART:20260918T090000\n"
           "SUMMARY:Testles\nEND:VEVENT\nEND:VCALENDAR")
    preview = client.post("/api/v1/agenda/import",
                          json={"ics_text": ics,
                                "source_label": "test",
                                "preview_only": True})
    assert preview.status_code == 200, preview.text
    assert preview.json()["preview"] is True
    assert preview.json()["event_count"] == 1
    assert client.get("/api/v1/agenda/events").json() == []

    stored = client.post("/api/v1/agenda/import",
                         json={"ics_text": ics,
                               "source_label": "test",
                               "preview_only": False})
    assert stored.json()["inserted"] == 1
    events = client.get("/api/v1/agenda/events").json()
    assert len(events) == 1
    assert events[0]["title"] == "Testles"

    agenda_cmd = client.post(
        "/api/v1/command",
        json={"text": "Wat staat er vandaag op mijn agenda?"})
    assert agenda_cmd.json()["intent"] == "agenda_today"


def test_agenda_rejects_garbage(client):
    response = client.post("/api/v1/agenda/import",
                           json={"ics_text": "geen kalender",
                                 "preview_only": True})
    assert response.status_code == 422


def test_research_capability_honest(client):
    capability = client.get("/api/v1/research/capability")
    assert capability.status_code == 200, capability.text
    body = capability.json()
    assert body["available"] == "unprobed"
    assert "nooit" in body["note"] or "gefaket" in body["note"]


def test_physical_status_no_fake_live(client):
    status = client.get("/api/v1/physical/status")
    assert status.status_code == 200, status.text
    states = {item["status"]
              for item in status.json()["capabilities"]}
    assert "LIVE" not in states
    assert states <= {"SIMULATED", "HARDWARE_REQUIRED",
                      "UNAVAILABLE", "TEST",
                      "CONFIGURED-TRANSPORT"}
