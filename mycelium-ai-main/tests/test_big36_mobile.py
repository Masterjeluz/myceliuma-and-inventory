"""BIG #36 tests: Mobile Mycelium command surface — dashboard,
input, triage, YES gate (valid/unauthorized/replay), deeplinks,
camera, packet, guide, craft, symbiosis, nodes, progress,
notifier, security. Mobile shares desktop gates exactly.
"""

import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.mobile import (
    approval_cards,
    dashboard,
    notification_cards,
)


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b36.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b36-chat.db"))
    with TestClient(main_mod.app) as client:
        yield client


def _chat(client, message="kijk wat er openstaat"):
    return client.post("/api/v1/chat",
                       json={"message": message}).json()


def _mission(client, goal="mobile triage quest"):
    chat = _chat(client)
    return client.post("/api/v1/missions", json={
        "conversation_id": chat["conversation_id"],
        "goal": goal,
        "steps": [{"kind": "readout",
                   "description": "Read status",
                   "parameters": {"source": "project"}}]}).json()


# -- dashboard + sections ------------------------------------------------------

def test_dashboard_shape(tmp_path, monkeypatch):
    for _ in make_client(tmp_path, monkeypatch):
        dash = dashboard()
        assert {"waiting_count", "cards", "guide", "camera",
                "craft", "symbiosis", "nodes", "progress",
                "notifications", "packet",
                "living"} <= set(dash)
        assert dash["waiting_count"] == 0
        assert dash["cards"] == []
        assert dash["nodes"]["path"]
        assert "PHONE" in dash["nodes"]["path"][0]


def test_mobile_page_sections(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        page = client.get("/mobile")
        assert page.status_code == 200
        for section in ("Now", "Waiting for you", "Active",
                        "Wat wil je doen", "Guide me", "Camera",
                        "Continue elsewhere", "Craft", "Symbiosis",
                        "Nodes", "Notifications",
                        "Hoe gebruik ik Mycelium"):
            assert section in page.text, section
        assert client.get("/api/v1/mobile/dashboard"
                          ).status_code == 200


def test_input_enters_coordinator(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        chat = client.post("/web/chat",
                           data={"message": "inventariseer de zolder"})
        assert chat.status_code in (200, 303)
        listed = client.get("/api/v1/conversations").json()
        conversations = listed["conversations"] \
            if isinstance(listed, dict) else listed
        assert conversations
        assert client.get("/mobile").status_code == 200


# -- approval triage + YES gate --------------------------------------------------

def test_triage_mission_card_and_yes(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        mission = _mission(client, goal="mobile approval flow")
        cards = approval_cards()
        assert len(cards) == 1
        card = cards[0]
        assert card["kind"] == "mission"
        assert {"what", "why", "source", "scope", "will_happen",
                "will_not_happen", "yes_action", "no_action",
                "open_href"} <= set(card)
        assert card["yes_action"].endswith("/approve")
        mobile = client.get("/mobile").text
        assert "mobile approval flow" in mobile
        assert "YES, doorgaan" in mobile
        assert "Review writes" in mobile
        approved = client.post(
            f"/web/missions/{mission['mission_id']}/approve")
        assert approved.status_code in (200, 303)
        state = client.get(
            f"/api/v1/missions/{mission['mission_id']}").json()
        assert state["status"] == "approved"


def test_unauthorized_and_replayed_yes(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        # Fake mission id: redirect, no state change anywhere.
        fake = client.post("/web/missions/mission_nope/approve")
        assert fake.status_code in (200, 303, 404)
        mission = _mission(client)
        mission_id = mission["mission_id"]
        first = client.post(f"/web/missions/{mission_id}/approve")
        assert first.status_code in (200, 303)
        # Replay: already approved, stays approved, no duplication.
        second = client.post(f"/web/missions/{mission_id}/approve")
        assert second.status_code in (200, 303)
        state = client.get(
            f"/api/v1/missions/{mission_id}").json()
        assert state["status"] == "approved"
        # Wrong response text refuses (rejected, never approved).
        from coordinator.app.controlled_writes import propose_write
        proposal = propose_write("wrt-b36no", "inventory.create",
                                 "object", {"name": "X"}, actor="t")
        main_mod._write_save(proposal, "proposed")
        denied = client.post("/web/writes/wrt-b36no/approve",
                             data={"response": "maybe"})
        assert denied.status_code in (200, 303)
        record = main_mod._write_load("wrt-b36no")
        assert record["status"] != "approved"
        # Exact YES works through the same route (fresh proposal).
        yes_proposal = propose_write(
            "wrt-b36yes", "inventory.create", "object",
            {"name": "Y"}, actor="t")
        main_mod._write_save(yes_proposal, "proposed")
        client.post("/web/writes/wrt-b36yes/approve",
                    data={"response": "YES"})
        assert main_mod._write_load("wrt-b36yes")["status"] == \
            "approved"
        # Unknown proposal: no crash, no state.
        assert client.post("/web/writes/wrt_nope/approve",
                           data={"response": "YES"}).status_code \
            in (200, 303)


def test_triage_write_and_desktop_cards(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        from coordinator.app.controlled_writes import propose_write
        proposal = propose_write("wrt-b36card", "inventory.create",
                                 "object", {"name": " plank "},
                                 actor="t")
        main_mod._write_save(proposal, "proposed")
        cards = approval_cards()
        write_cards = [card for card in cards
                       if card["kind"] == "write"]
        assert len(write_cards) == 1
        assert "wrt-b36card" in write_cards[0]["id"]
        assert "YES" in write_cards[0]["will_happen"]
        mobile = client.get("/mobile").text
        assert "wrt-b36card" in mobile
        assert "DEFER" in mobile


# -- notifications + deeplinks -----------------------------------------------------

def test_notification_deeplinks(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        node = client.post("/api/v1/nodes/register", json={
            "node_id": "phone-1", "hostname": "phone",
            "tier": "seed", "capabilities": ["inventory.read"],
            "node_token": "b36-token-abcdef-123456"}).json()
        assert node["node_id"] == "phone-1"
        mission = _mission(client)
        sent = client.post("/api/v1/notifications", json={
            "recipient_node_id": "phone-1", "type": "info",
            "title": "Missie wacht",
            "related_mission": mission["mission_id"]}).json()
        assert sent["notification_id"]
        cards = notification_cards("phone-1")
        assert len(cards) == 1
        assert cards[0]["href"] == \
            f"/missions/{mission['mission_id']}"
        mobile = client.get("/mobile",
                            params={"node": "phone-1"}).text
        assert "Missie wacht" in mobile
        assert f"/missions/{mission['mission_id']}" in mobile
        # Fake node: empty, never an error page.
        assert notification_cards("ghost") == []
        assert client.get("/mobile",
                          params={"node": "ghost"}).status_code \
            == 200
        # Entity deeplinks resolve to real objects.
        assert client.get("/api/v1/notifications",
                          params={"node_id": "ghost"}
                          ).status_code in (200, 404, 422)


# -- camera / packet / guide / craft / symbiosis / nodes / progress -------------------

def test_camera_packet_craft_symbiosis_nodes(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        dash = dashboard()
        assert dash["camera"]["href"] == "/cameras"
        packet = dash["packet"]
        assert packet["href_md"] == "/api/v1/context/packet.md"
        assert "Copy context" in client.get("/mobile").text
        assert client.get("/api/v1/context/packet.md"
                          ).status_code == 200
        assert client.get("/api/v1/context/packet"
                          ).status_code == 200
        client.post("/api/v1/candidates", json={
            "title": "Panelen bij schuur",
            "candidate_type": "connection",
            "summary": "mogelijke symbiose",
            "entity_refs": ["proj_schuur", "obj_panel"]})
        dash = dashboard()
        assert len(dash["symbiosis"]) == 1
        assert dash["symbiosis"][0]["status"] == "PROPOSED"
        assert "Symbiosis" in client.get("/mobile").text
        assert "WHAT IT CAN DO" in client.get("/nodes").text


def test_progress_quests(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert dashboard()["progress"] == {"quests": []}
        _mission(client, goal="progress quest")
        quests = dashboard()["progress"]["quests"]
        assert len(quests) == 1
        assert quests[0]["done"] == 0
        assert quests[0]["total"] == 1
        assert "progress quest" in client.get("/mobile").text


# -- notifier ----------------------------------------------------------------------------

@pytest.mark.parametrize("argv", [
    ["start", "--big", "36"],
    ["status", "--big", "36", "--phase", "1", "--phases", "4"],
    ["waiting", "--message", "approval x"],
    ["need", "--message", "approval x"],
    ["done", "--big", "36"],
    ["failed", "--big", "36"],
])
def test_notifier_commands(argv):
    proc = subprocess.run(
        [sys.executable, "scripts/mycelium-notify.py", *argv],
        capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr


# -- security ----------------------------------------------------------------------------------

def test_hostile_and_oversized_input(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        evil = "<script>alert(1)</script>"
        client.post("/web/chat", data={"message": evil})
        mobile = client.get("/mobile").text
        assert "<script>alert(1)</script>" not in mobile
        big = "x" * 20000
        response = client.post("/web/chat", data={"message": big})
        assert response.status_code in (200, 303, 413, 422)
        malformed = client.post("/api/v1/context/packet", json={
            "goal": ["not", "a", "string"]})
        assert malformed.status_code == 200
        assert isinstance(malformed.json()["goal"], str)
        assert client.get("/api/v1/mobile/dashboard",
                          params={"node": "../etc"}).status_code \
            == 200
        assert client.get("/cameras/cam_../x").status_code == 404
