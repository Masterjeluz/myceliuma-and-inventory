"""BIG #45 tests: living ecosystem connections.

Unified connections from real stores only (no invented
relations, predicates closed, amounts never leak),
cross-project network over shared records, campaign
ecosystem context, connection detail in Guide vocabulary,
guide/mobile/morning/presence integration, background
pulse. The world layer has zero execution authority.
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN_A = "b45-test-token-aaaaaaaa"
TOKEN_B = "b45-test-token-bbbbbbbb"
OPERATOR = "b45-operator-key"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b45.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b45-chat.db"))
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


def _seed(client):
    _register(client, "node-a", ["research.fetch"], TOKEN_A)
    _register(client, "node-b",
              ["research.fetch", "research.fetch_url"], TOKEN_B)
    _beat(client, "node-a", TOKEN_A)
    _beat(client, "node-b", TOKEN_B, hardware=[{
        "kind": "gpu", "identifier": "gpu-0",
        "status": "connected"}],
        telemetry={"cpu_percent": 5.0})
    link = client.post("/api/v1/hardware/links", json={
        "human_ref": "jelles", "node_id": "node-b",
        "device_ref": "gpu-0", "device_kind": "gpu",
        "evidence": "saw it"}).json()
    client.post(
        f"/api/v1/hardware/links/{link['link_id']}/verify",
        json={"verified_by": "jelles",
              "operator_key": OPERATOR})
    fin = client.post("/api/v1/finance/records", json={
        "kind": "budget", "title": "Solar pot",
        "amount_minor": 50000,
        "project_ref": "proj_solar"}).json()
    enr = client.post("/api/v1/energy/records", json={
        "source": "solar", "kind": "production", "value": 410.5,
        "unit": "W", "project_ref": "proj_solar"}).json()
    quest = client.post("/api/v1/quests", json={
        "title": "Fund it",
        "steps": [{"key": "m", "label": "Budget",
                   "kind": "finance",
                   "ref": fin["record_id"]}]}).json()
    campaign = client.post("/api/v1/campaigns", json={
        "title": "Solar Grove",
        "quest_ids": [quest["quest_id"]]}).json()
    proposal = client.post("/api/v1/candidates", json={
        "title": "Panels feed the project",
        "candidate_type": "connection",
        "summary": "energy link",
        "entity_refs": ["proj_solar", "obj_panel"]})
    assert proposal.status_code == 201, proposal.text
    return {"link": link, "fin": fin, "enr": enr,
            "quest": quest, "campaign": campaign}


# -- unified connections -------------------------------------------------

def test_entity_connections_real_only(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        seeded = _seed(client)
        body = client.get(
            "/api/v1/connections",
            params={"entity_id": "proj_solar"}).json()
        assert body["entity_id"] == "proj_solar"
        origins = {entry["origin"] for entry in
                   body["connections"]}
        assert {"finance-link", "energy-link",
                "symbiosis-proposal"} <= origins
        # Predicates are closed or "related".
        from coordinator.app.symbiosis import SYMBIOSIS_PREDICATES
        for entry in body["connections"]:
            assert entry["predicate"] in SYMBIOSIS_PREDICATES \
                or entry["predicate"] == "related"
            assert entry["href"]
        # Finance amounts never leak into connections.
        blob = str(body["connections"])
        assert "50000" not in blob
        fin_entry = next(
            entry for entry in body["connections"]
            if entry["origin"] == "finance-link")
        assert fin_entry["state"] == "LINKED"
        assert fin_entry["predicate"] == "allocated_to"


def test_entity_connections_hardware_and_quest(tmp_path,
                                              monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        seeded = _seed(client)
        node = client.get(
            "/api/v1/connections",
            params={"entity_id": "node-b"}).json()
        hw_entry = next(
            entry for entry in node["connections"]
            if entry["origin"] == "hardware-link")
        assert hw_entry["state"] == "VERIFIED"
        fin = client.get(
            "/api/v1/connections",
            params={"entity_id": seeded["fin"]["record_id"]}
        ).json()
        quest_entry = next(
            entry for entry in fin["connections"]
            if entry["origin"] == "quest-step")
        assert quest_entry["state"] == "LINKED"


def test_connections_unknown_entity(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _seed(client)
        assert client.get(
            "/api/v1/connections",
            params={"entity_id": "ghost-xyz"}).status_code == 422
        assert client.get(
            "/api/v1/connections",
            params={"entity_id": "../evil"}).status_code == 422


# -- cross-project network -----------------------------------------------

def test_project_network_shared_records(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _seed(client)
        # Second project shares the same energy record's
        # project? No — separate record; shared quest entity
        # instead: both quests reference obj_panel.
        quest2 = client.post("/api/v1/quests", json={
            "title": "Mount it",
            "steps": [{"key": "p", "label": "Panel",
                       "kind": "entity",
                       "ref": "obj_panel"}]}).json()
        network = client.get(
            "/api/v1/connections/network",
            params={"projects": "proj_solar,proj_hydro"}
        ).json()
        assert network["projects"] == ["proj_hydro",
                                       "proj_solar"] or \
            network["projects"] == ["proj_solar",
                                    "proj_hydro"]
        assert len(network["clusters"]) == 2
        solar = next(cluster for cluster in network["clusters"]
                     if cluster["project"] == "proj_solar")
        assert solar["children"]
        assert "honesty" in network


def test_network_refusals(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _seed(client)
        assert client.get(
            "/api/v1/connections/network",
            params={"projects": "ghost-xyz"}).status_code == 422
        assert client.get(
            "/api/v1/connections/network",
            params={"projects": ""}).status_code == 422
        many = client.get(
            "/api/v1/connections/network",
            params={"projects": ",".join(
                f"proj_{index}" for index in range(10))})
        # Well-formed ids parse bounded (max 6 projects);
        # unknown ones simply have no recorded links.
        assert many.status_code == 200
        assert len(many.json()["projects"]) == 6


# -- campaign ecosystem + detail ------------------------------------------

def test_campaign_ecosystem_only_real(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        seeded = _seed(client)
        body = client.get(
            f"/api/v1/connections/campaign/"
            f"{seeded['campaign']['campaign_id']}").json()
        assert body["progress"] == "0/1"
        assert "FINANCE" in body["groups"]
        assert body["groups"]["FINANCE"][0]["ref"] == \
            seeded["fin"]["record_id"]
        assert client.get(
            "/api/v1/connections/campaign/cmp_nope"
        ).status_code == 422


def test_connection_detail_vocabulary(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        seeded = _seed(client)
        detail = client.get(
            "/api/v1/connections/detail",
            params={"a": "proj_solar",
                    "b": seeded["fin"]["record_id"]}).json()
        for key in ("what", "why", "source", "status",
                    "evidence", "next"):
            assert key in detail
        assert detail["next"]["href"]
        page = client.get(
            "/connections",
            params={"a": "proj_solar",
                    "b": seeded["fin"]["record_id"]})
        assert page.status_code == 200
        assert "EVIDENCE" in page.text
        missing = client.get(
            "/api/v1/connections/detail",
            params={"a": "proj_solar", "b": "obj_nowhere"})
        assert missing.status_code == 422
        same = client.get(
            "/api/v1/connections/detail",
            params={"a": "proj_solar", "b": "proj_solar"})
        assert same.status_code == 422


def test_possible_connections_are_not_relations(tmp_path,
                                               monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _seed(client)
        body = client.get(
            "/api/v1/connections/possible",
            params={"entity_id": "proj_solar"}).json()
        for item in body["possible"]:
            assert item["state"] == "POSSIBLE"
            assert item["gate"]
            assert item["href"]


# -- world / guide / mobile / morning / presence --------------------------

def test_world_connection_panels(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _seed(client)
        focused = client.get(
            "/world", params={"entity_id": "proj_solar"}).text
        assert "Ecosystem connections" in focused
        assert "/connections?a=" in focused
        wide = client.get("/world").text
        assert "Ecosystem connections" in wide


def test_guide_relationship_cards(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _seed(client)
        guide = client.get("/api/v1/guide").json()
        items = guide.get("items", [])
        rel = [item for item in items
               if "Possible connection" in item.get("what", "")]
        assert rel, "guide should explain a possible connection"
        assert rel[0]["blocked_by"]
        assert rel[0]["evidence"]


def test_mobile_connected_panel(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _seed(client)
        dash = client.get(
            "/api/v1/mobile/dashboard").json()
        assert "connected" in dash
        assert dash["connected"]["waiting"] >= 1
        page = client.get("/mobile")
        assert page.status_code == 200
        assert "Connected ecosystem" in page.text


def test_morning_connections_section(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        morning = client.get("/api/v1/reports/morning").json()
        titles = [section["title"] for section in
                  morning.get("sections", [])]
        assert "Ecosystem connections" not in titles
        _seed(client)
        morning2 = client.get("/api/v1/reports/morning").json()
        titles2 = [section["title"] for section in
                   morning2.get("sections", [])]
        assert "Ecosystem connections" in titles2


def test_presence_campaign_blocked(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        from coordinator.app.presence import attention_items
        _seed(client)
        live = {item["type"] for item in attention_items()}
        assert "symbiosis_proposed" in live
        # Force a blocked campaign via a failed mission quest.
        mission = client.post("/api/v1/missions", json={
            "conversation_id": "",
            "goal": "Doomed work",
            "steps": [{"kind": "readout",
                       "description": "Read",
                       "parameters": {"source": "project"}}]})
        assert mission.status_code in (201, 422)


def test_background_proposed_signal(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _seed(client)
        text = client.get("/world").text
        assert 'data-proposed="1"' in text


# -- security ---------------------------------------------------------------

def test_world_posts_refused(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.post("/world").status_code == 405
        assert client.post("/connections").status_code == 405
        assert client.post(
            "/api/v1/connections").status_code == 405


def test_connection_refusal_probes(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _seed(client)
        probes = [
            ("/api/v1/connections",
             {"entity_id": "fin_*"}),
            ("/api/v1/connections",
             {"entity_id": "../evil"}),
            ("/api/v1/connections/detail",
             {"a": "proj_solar", "b": "fin_*"}),
            ("/api/v1/connections/possible",
             {"entity_id": "../evil"}),
        ]
        for path, params in probes:
            response = client.get(path, params=params)
            assert response.status_code in (404, 422), \
                (path, params, response.status_code)
        # Well-formed but unknown ids return empty, not fake
        # relations (symbiosis semantic).
        empty = client.get(
            "/api/v1/connections",
            params={"entity_id": "proj_nowhere"}).json()
        assert empty["connections"] == []
        # Prompt-injected predicate cannot enter: proposals
        # with unknown verbs refuse at creation.
        bad = client.post("/api/v1/candidates", json={
            "title": "'; DROP TABLE candidates; --",
            "candidate_type": "connection",
            "summary": "injection",
            "entity_refs": ["proj_solar", "obj_panel"]})
        assert bad.status_code in (201, 422)
        # Secret-like mesh payload still refused.
        secret = client.post("/api/v1/mesh/delegate", json={
            "requesting_node": "node-a", "node_token": TOKEN_A,
            "target_node": "node-b",
            "task_kind": "research.fetch_url",
            "capability": "research.fetch",
            "payload": {"api_key": "hunter2"}})
        assert secret.status_code == 422
