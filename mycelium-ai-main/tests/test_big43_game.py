"""BIG #43 tests: living game layer.

Campaigns over real quests (fake quests refuse, deleted quests
mark MISSING, no XP), read-only game-state view (aggregates,
never approves), guide companion fields, mobile campaign
panel, morning campaign section + game headers, worldgraph
verified-hardware glow, symbiosis progression display. Every
security case fails closed; the game layer gains no execution
authority.
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN_A = "b43-test-token-aaaaaaaa"
TOKEN_B = "b43-test-token-bbbbbbbb"
OPERATOR = "b43-operator-key"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b43.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b43-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", OPERATOR)
    with TestClient(main_mod.app) as client:
        yield client


def _register(client, node_id, caps, token):
    response = client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": node_id, "tier": "worker",
        "capabilities": caps, "node_token": token})
    assert response.status_code == 201, response.text


def _beat(client, node_id, token, **extra):
    body = {"available": True, "node_token": token}
    body.update(extra)
    response = client.post(
        f"/api/v1/nodes/{node_id}/heartbeat", json=body)
    assert response.status_code == 204, response.text


def _pair(client):
    _register(client, "node-a", ["research.fetch"], TOKEN_A)
    _register(client, "node-b",
              ["research.fetch", "research.fetch_url"], TOKEN_B)
    _beat(client, "node-a", TOKEN_A)
    _beat(client, "node-b", TOKEN_B)


def _quest(client, **overrides):
    body = {"title": "Audit energy",
            "steps": [{"key": "s", "label": "Record",
                       "kind": "note", "ref": ""}]}
    body.update(overrides)
    response = client.post("/api/v1/quests", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _campaign(client, quest_ids, **overrides):
    body = {"title": "Solar Workshop",
            "description": "Grow the solar workshop.",
            "quest_ids": quest_ids}
    body.update(overrides)
    return client.post("/api/v1/campaigns", json=body)


# -- campaigns -----------------------------------------------------------

def test_campaign_lifecycle(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        first = _quest(client, title="Understand energy")
        second = _quest(client, title="Inspect hardware")
        created = _campaign(
            client, [first["quest_id"], second["quest_id"]])
        assert created.status_code == 201, created.text
        detail = created.json()
        assert detail["campaign_id"].startswith("cmp_")
        assert detail["total_count"] == 2
        assert detail["completed_count"] == 0
        assert detail["current_quest"]["quest_id"] == \
            first["quest_id"]
        assert detail["next_action"]["href"]
        assert len(detail["evidence"]) == 2
        campaign_id = detail["campaign_id"]
        fetched = client.get(
            f"/api/v1/campaigns/{campaign_id}").json()
        assert fetched["title"] == "Solar Workshop"
        refreshed = client.post(
            f"/api/v1/campaigns/{campaign_id}/refresh")
        assert refreshed.status_code == 200
        listed = client.get("/api/v1/campaigns").json()
        assert any(entry["campaign_id"] == campaign_id
                   for entry in listed["campaigns"])
        deleted = client.delete(
            f"/api/v1/campaigns/{campaign_id}")
        assert deleted.status_code == 200
        assert client.get(
            f"/api/v1/campaigns/{campaign_id}").status_code == 404


def test_campaign_refuses_fake_quests(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        real = _quest(client)
        fake = _campaign(client, ["qst_deadbeef1234"])
        assert fake.status_code == 422
        malformed = _campaign(client, ["../evil"])
        assert malformed.status_code == 422
        empty = _campaign(client, [])
        assert empty.status_code == 422
        duplicate = _campaign(
            client, [real["quest_id"], real["quest_id"]])
        assert duplicate.status_code == 422
        missing = client.get("/api/v1/campaigns/cmp_nope")
        assert missing.status_code == 404
        assert client.post(
            "/api/v1/campaigns/cmp_nope/refresh").status_code \
            == 404
        assert client.delete(
            "/api/v1/campaigns/cmp_nope").status_code == 404


def test_deleted_quest_marks_missing(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        quest = _quest(client)
        campaign_id = _campaign(
            client, [quest["quest_id"]]).json()["campaign_id"]
        assert client.delete(
            f"/api/v1/quests/{quest['quest_id']}").status_code \
            == 200
        detail = client.get(
            f"/api/v1/campaigns/{campaign_id}").json()
        assert detail["quests"][0]["state"] == "MISSING"
        assert detail["total_count"] == 1


def test_campaign_completion_derives(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        fin = client.post("/api/v1/finance/records", json={
            "kind": "budget", "title": "Pot",
            "amount_minor": 100}).json()
        quest = _quest(client, title="Fund it", steps=[{
            "key": "m", "label": "Budget", "kind": "finance",
            "ref": fin["record_id"]}])
        campaign_id = _campaign(
            client, [quest["quest_id"]]).json()["campaign_id"]
        before = client.get(
            f"/api/v1/campaigns/{campaign_id}").json()
        assert before["state"] == "WAITING"
        client.post(
            f"/api/v1/finance/records/{fin['record_id']}/status",
            json={"status": "CONFIRMED"})
        after = client.post(
            f"/api/v1/campaigns/{campaign_id}/refresh").json()
        assert after["completed_count"] == 1
        assert after["state"] == "COMPLETED"


# -- game state ----------------------------------------------------------

def test_game_state_is_readonly_view(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        quest = _quest(client)
        _campaign(client, [quest["quest_id"]])
        state = client.get("/api/v1/game/state")
        assert state.status_code == 200, state.text
        body = state.json()
        sections = body["sections"]
        for key in ("world", "campaigns", "current_quest",
                    "presence", "craft", "symbiosis", "nodes",
                    "energy", "workshop", "discoveries"):
            assert key in sections, f"game state misses {key}"
            assert "source" in sections[key]
        assert body["provenance"]["creator_id"] == \
            "living-game-layer"
        assert body["provenance"]["human_verified"] is False
        assert "No XP" in body["honesty"] or \
            "no database" in body["honesty"]
        assert body["sections"]["campaigns"]["data"][0][
            "campaign_id"]
        # Game state approves nothing: no POST route exists.
        assert client.post("/api/v1/game/state").status_code \
            == 405


def test_game_state_empty_graceful(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        body = client.get("/api/v1/game/state").json()
        assert body["sections"]["campaigns"]["data"] == []
        assert body["sections"]["current_quest"]["data"] == {}


def test_presence_stakes_keep_hrefs(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        from coordinator.app.game import presence_as_stakes
        stakes = presence_as_stakes(limit=60)
        assert set(stakes["labels"]) == {
            "needs", "waiting", "available", "discovered",
            "offline"}
        for band, items in stakes["bands"].items():
            for item in items:
                assert item["band"] == band
                assert item["href"]
                assert item["reads_as"]


def test_symbiosis_progression_shape(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        from coordinator.app.game import symbiosis_progression
        prog = symbiosis_progression(limit=5)
        assert "honesty" in prog
        for prop in prog["open"]:
            assert prop["state"] == "PROPOSED"
            assert prop["strength"] == "seedling"
            assert prop["href"]


# -- guide companion -----------------------------------------------------

def test_guide_companion_fields(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        _beat(client, "node-b", TOKEN_B, hardware=[{
            "kind": "gpu", "identifier": "gpu-0",
            "status": "connected"}],
            telemetry={"cpu_percent": 5.0})
        guide = client.get("/api/v1/guide").json()
        items = guide.get("items", [])
        hardware_items = [item for item in items
                          if item.get("kind") == "hardware"]
        assert hardware_items
        card = hardware_items[0]
        for field in ("blocked_by", "unlocks", "evidence"):
            assert field in card
        assert card["evidence"][0]["href"].endswith("/reality")


def test_guide_campaign_card(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        quest = _quest(client, title="Research solar",
                       steps=[{"key": "r", "label": "Research",
                               "kind": "entity",
                               "ref": "proj_solar"}])
        _campaign(client, [quest["quest_id"]])
        guide = client.get("/api/v1/guide").json()
        items = guide.get("items", [])
        campaign_cards = [
            item for item in items
            if item.get("glyph") == "🗺"]
        assert campaign_cards, \
            "guide should carry a campaign companion card"
        card = campaign_cards[0]
        assert card["unlocks"]
        assert card["evidence"]


# -- mobile + morning + pages --------------------------------------------

def test_mobile_campaign_panel(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        quest = _quest(client)
        _campaign(client, [quest["quest_id"]])
        dash = client.get(
            "/api/v1/mobile/dashboard").json()
        assert "campaigns" in dash
        assert dash["campaigns"]["href"] == "/campaigns"
        assert dash["campaigns"]["campaigns"][0][
            "next_href"]


def test_morning_campaign_section(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        morning = client.get("/api/v1/reports/morning").json()
        titles = [section["title"] for section in
                  morning.get("sections", [])]
        assert "Current campaign" not in titles
        quest = _quest(client)
        _campaign(client, [quest["quest_id"]])
        morning2 = client.get("/api/v1/reports/morning").json()
        titles2 = [section["title"] for section in
                   morning2.get("sections", [])]
        assert "Current campaign" in titles2
        page = client.get("/morning")
        assert page.status_code == 200
        assert "🎯 Current campaign" in page.text


def test_game_pages_render(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        quest = _quest(client)
        _campaign(client, [quest["quest_id"]])
        for path in ("/campaigns", "/game", "/quests",
                     "/craft", "/symbiosis", "/guide",
                     "/mobile", "/morning", "/world"):
            response = client.get(path)
            assert response.status_code == 200, path
        game_page = client.get("/game").text
        assert "Living game" in game_page
        assert "/api/v1/game/state" in game_page


# -- worldgraph verified glow --------------------------------------------

def test_worldgraph_verified_hardware(tmp_path, monkeypatch):
    from coordinator.app.hardware_links import (
        new_link, save_link, verify_link)
    from coordinator.app.worldgraph import _overlay_hardware
    link = new_link(human_ref="jelles", node_id="node-b",
                    device_ref="gpu-0", device_kind="gpu",
                    evidence="saw it")
    save_link(link)
    verify_link(link.link_id, verified_by="jelles")
    nodes: dict = {}
    edges: list = []
    _overlay_hardware(nodes, edges, [{
        "node_id": "node-b",
        "hardware": [{"kind": "gpu", "identifier": "gpu-0",
                      "status": "connected"},
                     {"kind": "camera",
                      "identifier": "cam-0",
                      "status": "connected"}]}])
    gpu = next(node for node in nodes.values()
               if node["metadata"]["identifier"] == "gpu-0")
    cam = next(node for node in nodes.values()
               if node["metadata"]["identifier"] == "cam-0")
    assert gpu["metadata"]["verified"] is True
    assert cam["metadata"]["verified"] is False
    gpu_edge = next(edge for edge in edges
                    if edge["to"] == gpu["id"])
    assert gpu_edge["provenance"]["human_verified"] is True


# -- security: game layer executes nothing -------------------------------

def test_game_layer_has_no_authority(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        # Traversal-ish campaign id.
        assert client.get(
            "/api/v1/campaigns/../secret").status_code in (
            404, 422)
        # Wildcard quest ref.
        assert _campaign(
            client, ["qst_*"]).status_code == 422
        # Campaign create with wrong types.
        bad = client.post("/api/v1/campaigns", json={
            "title": "x", "quest_ids": "not-a-list"})
        assert bad.status_code == 422
        # Too many quests.
        many = client.post("/api/v1/campaigns", json={
            "title": "x",
            "quest_ids": [f"qst_{index:08x}"
                          for index in range(20)]})
        assert many.status_code == 422
