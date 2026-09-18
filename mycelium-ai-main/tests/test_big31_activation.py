"""BIG #31 tests: activation — context engine, living state, search,
packet v2, command traces, archaeology depth, file ingest, writes
inbox, node roles, overnight mode + research queue, morning.
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b31.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b31-chat.db"))
    with TestClient(main_mod.app) as client:
        yield client


SAMPLE = """Jelles: Ik wil mijn camper isoleren. Idee: schapenwol gebruiken?
ChatGPT: Goed idee. Voorstel: meet eerst de wanden. TODO: offertes opvragen.
Jelles: Besloten: we gaan meten. Werkt 3D printen voor de beugels?
"""


def import_sample(client, title="Sample chat", content=None):
    response = client.post("/api/v1/conversations/import", json={
        "title": title, "content": content or SAMPLE, "format": "plain",
        "source_platform": "chatgpt"})
    assert response.status_code == 200, response.text
    conv_id = response.json()["conversation_id"]
    analyzed = client.post(f"/api/v1/conversations/{conv_id}/analyze")
    assert analyzed.status_code == 200, analyzed.text
    return conv_id


# -- context engine ----------------------------------------------------------

def test_compose_bounded_traceable(tmp_path, monkeypatch):
    from coordinator.app.context_engine import compose
    for _c in make_client(tmp_path, monkeypatch):
        context = compose("camper solar isolatie")
        assert context["engine"].startswith("mycelium-context-engine")
        assert context["health_scoped_out"] is True
        assert context["keywords"]
        assert context["total_items"] <= 100
        for section, items in context["sections"].items():
            assert len(items) <= 8, section
            for item in items:
                assert {"source", "id", "title", "why"} <= set(item)
        assert "inventory" in context["sections"]
        assert "memories" in context["sections"]
        assert "agenda" in context["sections"]


def test_compose_api_and_search(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        response = client.get("/api/v1/context/compose",
                              params={"intent": "camper"})
        assert response.status_code == 200
        assert "sections" in response.json()
        search = client.get("/api/v1/search", params={"query": "camper"})
        assert search.status_code == 200
        assert search.json()["query"] == "camper"
        assert client.get("/api/v1/search").status_code == 422
        page = client.get("/search", params={"query": "camper"})
        assert page.status_code == 200
        assert "Search the ecosystem" in page.text
        assert client.get("/search").status_code == 200


def test_traces_and_last_flow(tmp_path, monkeypatch):
    from coordinator.app.context_engine import record_trace, recent_traces
    for client in make_client(tmp_path, monkeypatch):
        assert recent_traces() == []
        record_trace("test intent", [{"stage": "INTENT", "detail": "x"}],
                     {"landing": "/chat"})
        assert len(recent_traces()) == 1
        assert client.get("/api/v1/command/traces").json()["traces"]
        client.post("/web/command", data={"message": "help"})
        world = client.get("/world").text
        assert "Last flow" in world


# -- living state --------------------------------------------------------------

def test_living_state_quiet_then_waiting(tmp_path, monkeypatch):
    from coordinator.app.living_state import current_state
    for client in make_client(tmp_path, monkeypatch):
        assert current_state()["state"] == "QUIET"
        assert client.get("/api/v1/state").json()["glyph"]
        chat = client.post("/api/v1/chat",
                           json={"message": "hi"}).json()
        mission = client.post("/api/v1/missions", json={
            "conversation_id": chat["conversation_id"],
            "goal": "waiting mission",
            "steps": [{"kind": "readout", "description": "Read",
                       "parameters": {"source": "project"}}]}).json()
        assert mission["mission_id"]
        assert current_state()["state"] == "WAITING"
        assert "wacht" in current_state()["line"]
        for page in ("/world", "/mobile", "/missions"):
            assert 'role="status"' in client.get(page).text, page


def test_ui_growth_helpers():
    from coordinator.app.ui import growth_class, mission_glyph
    assert mission_glyph("running") == "🟢"
    assert mission_glyph("pending_approval") == "🟡"
    assert growth_class("completed") == "growth-bloom"
    assert growth_class("failed") == "growth-seed"
    assert growth_class("running") == "growth-sprout"
    assert growth_class("approved", 1, 3) == "growth-grown"


# -- packet v2 -------------------------------------------------------------------

def test_packet_v2_schema_and_download(tmp_path, monkeypatch):
    from coordinator.app.context_packet import (
        build_packet_v2, render_packet_v2_markdown)
    for client in make_client(tmp_path, monkeypatch):
        conv_id = import_sample(client)
        packet = build_packet_v2(
            task="camper isolatie", intent="onderzoek isolatie",
            conversation_id=conv_id)
        assert packet["packet"] == "mycelium-context-packet/2"
        for key in ("task", "intent", "current_state", "entities",
                    "memories", "observations", "research",
                    "unresolved_questions", "constraints",
                    "suggested_next_actions", "provenance",
                    "timestamps", "source_references", "mycelium_state",
                    "continuation_instructions"):
            assert key in packet, key
        assert packet["provenance"]["health_scoped_out"] is True
        markdown = render_packet_v2_markdown(packet)
        assert "MYCELIUM CONTEXT PACKET (v2)" in markdown
        assert "MYCELIUM-PACKET-V2-JSON" in markdown
        api = client.get("/api/v1/context/packet2",
                         params={"task": "x"}).json()
        assert api["packet"] == "mycelium-context-packet/2"
        md = client.get("/api/v1/context/packet.md")
        assert md.status_code == 200
        assert "attachment" in md.headers["content-disposition"]
        md2 = client.get("/api/v1/context/packet2",
                         params={"task": "x", "format": "markdown"})
        assert md2.status_code == 200


# -- archaeology depth -------------------------------------------------------------

def test_compare_relevance_markdown(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        first = import_sample(client, "First chat")
        second = import_sample(
            client, "Second chat",
            content=SAMPLE.replace("schapenwol", "hennepvezel"))
        compared = client.get("/api/v1/imports-compare").json()
        assert compared["imports_compared"] == 2
        assert compared["repeated_across_imports"]
        for item in compared["repeated_across_imports"]:
            assert len({occ["conversation_id"]
                        for occ in item["occurrences"]}) >= 2
        relevance = client.get(
            f"/api/v1/conversation-imports/{first}/relevance")
        assert relevance.status_code == 200
        assert "candidates" in relevance.json()
        markdown = client.get(
            f"/api/v1/conversation-imports/{first}/markdown")
        assert markdown.status_code == 200
        assert "never fact" in markdown.text
        assert client.get(
            "/api/v1/conversation-imports/conv_missing/markdown"
        ).status_code == 404
        discoveries = client.get("/api/v1/discoveries").json()
        assert discoveries["imports_considered"] == 2
        assert discoveries["items"]
        convos = client.get("/conversations").text
        assert "Te tonen aan Jelles" in convos


# -- file ingest ---------------------------------------------------------------------

def _write_inbox_bmp(filename: str = "inbox-shot.png") -> str:
    from coordinator.app.cameras import camera_dir, write_bmp_24
    import os
    path = os.path.join(camera_dir(), filename)
    write_bmp_24(path, 8, 8, b"\x10\x20\x30" * 64)
    return filename


def test_file_ingest_honest(tmp_path, monkeypatch):
    from coordinator.app.vision_ingest import (
        FileIngestAdapter, IngestRefusedError, list_inbox_files)
    for client in make_client(tmp_path, monkeypatch):
        name = _write_inbox_bmp()
        assert any(entry["filename"] == name
                   for entry in list_inbox_files())
        assert client.get("/api/v1/camera-inbox").json()["inbox"]
        with pytest.raises(IngestRefusedError):
            FileIngestAdapter("../evil.png")
        with pytest.raises(IngestRefusedError):
            FileIngestAdapter("http://x/y.png")
        with pytest.raises(IngestRefusedError):
            FileIngestAdapter("missing-file.png")
        device = client.post("/api/v1/cameras/register", json={
            "name": "Insta360 file", "kinds": ["snapshot"],
            "source": "insta360"}).json()
        device_id = device["device_id"]
        ingested = client.post(
            f"/api/v1/cameras/{device_id}/ingest-file",
            json={"filename": name})
        assert ingested.status_code == 201, ingested.text
        body = ingested.json()
        assert "file-ingest" in body["observation"]["provenance"]["notes"]
        assert body["file_payload"]["file_kind"] == "image"
        refused = client.post(
            f"/api/v1/cameras/{device_id}/ingest-file",
            json={"filename": "../evil.png"})
        assert refused.status_code == 422
        detail = client.get(f"/cameras/{device_id}")
        assert detail.status_code == 200
        assert "file-ingest" in detail.text or "File ingest" in \
            detail.text or "ingest" in detail.text.lower()
        assert client.get("/cameras/cam_missing").status_code == 404
        web = client.post(f"/web/cameras/{device_id}/ingest-file",
                          data={"filename": name})
        assert web.status_code in (200, 303)


# -- writes inbox + propose-link -------------------------------------------------------

def test_writes_inbox_and_propose_link(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.get("/writes").status_code == 200
        assert "Propose a link" in client.get("/writes").text
        bad = client.post("/web/links/propose", data={
            "from_id": "obj_1", "predicate": "hack_the_planet",
            "to_id": "proj_2"})
        assert bad.status_code in (200, 303)
        assert client.get("/api/v1/writes/wrt_missing").status_code \
            == 404
        good = client.post("/web/links/propose", data={
            "from_id": "obj_camper", "predicate": "part_of",
            "to_id": "proj_camper"})
        assert good.status_code in (200, 303)
        inbox = client.get("/writes").text
        assert "inventory.create_relationship" in inbox
        obj = client.post("/web/objects/propose", data={
            "name": "Camper accu", "description": "12V"})
        assert obj.status_code in (200, 303)
        assert "inventory.create" in client.get("/writes").text
        import re
        found = re.findall(r"/web/writes/(wrt-[a-z0-9]+)/approve",
                           client.get("/writes").text)
        assert len(found) >= 2
        decided = client.post(f"/web/writes/{found[0]}/approve",
                              data={"response": "maybe"})
        assert decided.status_code in (200, 303)
        record = client.get(f"/api/v1/writes/{found[0]}").json()
        assert record["status"] == "rejected"
        approved = client.post(f"/web/writes/{found[1]}/approve",
                               data={"response": "YES"})
        assert approved.status_code in (200, 303)
        assert client.get(
            f"/api/v1/writes/{found[1]}").json()["status"] == \
            "approved"


# -- node roles + bootstrap --------------------------------------------------------------

def test_node_roles_and_bootstrap(tmp_path, monkeypatch):
    from coordinator.app.ecosystem import node_roles
    assert node_roles({"capabilities": []}) == ["GENERAL"]
    assert "RESEARCH" in node_roles(
        {"capabilities": ["research.search"]})
    assert "CAMERA" in node_roles(
        {"capabilities": ["camera.snapshot"]})
    for client in make_client(tmp_path, monkeypatch):
        client.post("/api/v1/nodes/register", json={
            "node_id": "node-research-1", "hostname": "r1",
            "tier": "worker", "capabilities": ["research.search"],
            "node_token": "roles-token-abcdef-123456"})
        roles = client.get("/api/v1/node-roles").json()["roles"]
        assert "RESEARCH" in roles["node-research-1"]
        assert "WHAT IT CAN DO" in client.get("/nodes").text
    from node_client.bootstrap import (build_run_command,
                                       build_systemd_unit)
    command = build_run_command(
        repo_dir="~/x", coordinator="http://127.0.0.1:8000",
        node_id="n1", capabilities=["inventory.read"])
    assert "--capability inventory.read" in command
    assert "MYCELIUM_NODE_TOKEN" in command
    unit = build_systemd_unit(
        repo_dir="/home/u/x", coordinator="http://127.0.0.1:8000",
        node_id="n1")
    assert "NoNewPrivileges=true" in unit
    with pytest.raises(Exception):
        build_run_command(
            repo_dir="~/x", coordinator="http://127.0.0.1:8000",
            node_id="n1", capabilities=["shell"])


# -- overnight mode + research queue -------------------------------------------------------

def test_mode_and_queue(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert client.get("/api/v1/mode").json()["mode"] == "DAY"
        assert client.post("/api/v1/mode",
                           json={"mode": "PARTY"}).status_code == 422
        client.post("/api/v1/mode", json={"mode": "OVERNIGHT"})
        assert client.get("/api/v1/mode").json()["mode"] == "OVERNIGHT"
        assert client.post("/web/mode",
                           data={"mode": "DAY"}).status_code in (200, 303)
        assert client.get("/api/v1/research/queue").json()["queued"] \
            == []
        assert client.post("/api/v1/research/queue",
                           json={"question": ""}).status_code == 422
        added = client.post("/api/v1/research/queue", json={
            "question": "Is schapenwol geschikt voor camperisolatie?",
            "priority": "HIGH", "provider": "unavailable"})
        assert added.status_code == 201
        queued = client.get("/api/v1/research/queue").json()
        assert len(queued["queued"]) == 1
        assert queued["queued"][0]["priority"] == "HIGH"
        ran = client.post("/api/v1/research/queue/run-once")
        assert ran.status_code == 200
        assert "ran" in ran.json()
        morning = client.get("/morning").text
        assert "Good morning" in morning
        assert "Overnight" in morning


# -- mobile + e2e ---------------------------------------------------------------------------------

def test_mobile_waiting_approve(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        chat = client.post("/api/v1/chat",
                           json={"message": "hi"}).json()
        mission = client.post("/api/v1/missions", json={
            "conversation_id": chat["conversation_id"],
            "goal": "mobile approval flow",
            "steps": [{"kind": "readout", "description": "Read",
                       "parameters": {"source": "project"}}]}).json()
        mobile = client.get("/mobile").text
        assert "mobile approval flow" in mobile
        assert "YES, doorgaan" in mobile
        assert "Review writes" in mobile
        assert "Copy context" in mobile
        approved = client.post(
            f"/web/missions/{mission['mission_id']}/approve")
        assert approved.status_code in (200, 303)


def test_e2e_command_to_mission_flow(tmp_path, monkeypatch):
    """Acceptance 1 (core): chat/command -> context -> mission ->
    approval -> activity -> morning. Research transport honest."""
    for client in make_client(tmp_path, monkeypatch):
        chat = client.post("/api/v1/chat", json={
            "message": "Onderzoek hoe ik mijn camper kan isoleren"}
        ).json()
        assert chat["conversation_id"]
        mission = client.post("/api/v1/missions", json={
            "conversation_id": chat["conversation_id"],
            "goal": "camper isolatie overzicht",
            "steps": [{"kind": "readout", "description": "Read status",
                       "parameters": {"source": "project"}}]}).json()
        assert mission["mission_id"]
        client.post("/web/command",
                    data={"message": "wat wacht er op mij"})
        traces = client.get("/api/v1/command/traces").json()["traces"]
        assert traces
        assert "Last flow" in client.get("/world").text
        activity = client.get("/activity").text
        assert "camper isolatie overzicht" in activity
        assert "Good morning" in client.get("/morning").text
        state = client.get("/api/v1/state").json()
        assert state["state"] == "WAITING"


def test_e2e_import_to_packet_loop(tmp_path, monkeypatch):
    """Acceptance 2+8: import -> analyse -> missed -> relevance ->
    packet v2 -> markdown -> (re-import elsewhere)."""
    for client in make_client(tmp_path, monkeypatch):
        conv_id = import_sample(client)
        relevance = client.get(
            f"/api/v1/conversation-imports/{conv_id}/relevance")
        assert relevance.status_code == 200
        packet = client.get("/api/v1/context/packet2", params={
            "task": "isoleer de camper", "conversation_id": conv_id}
        ).json()
        assert packet["packet"] == "mycelium-context-packet/2"
        assert packet["unresolved_questions"]
        markdown = client.get(
            f"/api/v1/conversation-imports/{conv_id}/markdown").text
        reimport = client.post("/api/v1/conversations/import", json={
            "title": "Answer import", "content": markdown[:5000],
            "format": "markdown", "source_platform": "claude"})
        assert reimport.status_code == 200


def test_e2e_camera_file_to_observation(tmp_path, monkeypatch):
    """Acceptance 5: register -> UNAVAILABLE direct -> file ingest ->
    observation -> analysis advice path exists."""
    for client in make_client(tmp_path, monkeypatch):
        device = client.post("/api/v1/cameras/register", json={
            "name": "Insta360 X4", "kinds": ["snapshot"],
            "source": "insta360"}).json()
        device_id = device["device_id"]
        availability = client.get(
            f"/api/v1/cameras/{device_id}/availability").json()
        assert availability["capturable"] is False
        name = _write_inbox_bmp("e2e-shot.png")
        ingested = client.post(
            f"/api/v1/cameras/{device_id}/ingest-file",
            json={"filename": name}).json()
        assert "file-ingest" in ingested["observation"]["provenance"][
            "notes"]
        observations = client.get(
            f"/api/v1/cameras/{device_id}/observations").json()
        assert observations
        assert "OBSERVATION" in client.get(
            f"/cameras/{device_id}").text or "Observation" in \
            client.get(f"/cameras/{device_id}").text


def test_e2e_model_link_proposal(tmp_path, monkeypatch):
    """Acceptance 6 (safe part): propose model->project link, YES,
    approved — never auto-executed, never verified by approval."""
    for client in make_client(tmp_path, monkeypatch):
        client.post("/web/links/propose", data={
            "from_id": "mod_camper_haak", "predicate": "used_in",
            "to_id": "proj_camper"})
        import re
        match = re.search(r"/web/writes/(wrt-[a-z0-9]+)/approve",
                          client.get("/writes").text)
        assert match
        proposal_id = match.group(1)
        client.post(f"/web/writes/{proposal_id}/approve",
                    data={"response": "YES"})
        record = client.get(f"/api/v1/writes/{proposal_id}").json()
        assert record["status"] == "approved"
        assert record["verification"] in (None, {})
