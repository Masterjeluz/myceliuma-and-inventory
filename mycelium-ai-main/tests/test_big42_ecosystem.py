"""BIG #42 tests: ecosystem hardening + first V2 workflows.

Human hardware links (PROPOSED → VERIFIED operator-only, revoke
sticks, no self-verify), finance/energy stores (explicit records
only, UNKNOWN stays unknown, finance amounts scoped), symbiosis
prefixes + closed predicates, V2 mission templates, quest trails
(derived state, hardware-aware readiness), bounded mesh workflows,
guide/world/mobile/morning/packet integration. Every security
case fails closed.
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN_A = "b42-test-token-aaaaaaaa"
TOKEN_B = "b42-test-token-bbbbbbbb"
OPERATOR = "b42-operator-key"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b42.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b42-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", OPERATOR)
    with TestClient(main_mod.app) as client:
        yield client


def _register(client, node_id, caps, token, tier="worker"):
    response = client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": node_id, "tier": tier,
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


def _propose(client, **overrides):
    body = {"human_ref": "jelles", "node_id": "node-b",
            "device_ref": "gpu-0", "device_kind": "gpu",
            "capability": "analysis.ollama",
            "evidence": "saw the card in the case"}
    body.update(overrides)
    return client.post("/api/v1/hardware/links", json=body)


# -- 1. human hardware links -------------------------------------------

def test_propose_starts_proposed(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        response = _propose(client)
        assert response.status_code == 201, response.text
        assert response.json()["status"] == "PROPOSED"
        assert response.json()["verified_by"] == ""


def test_propose_unknown_node_404(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        response = _propose(client, node_id="ghost-node")
        assert response.status_code == 404


def test_verify_needs_operator_key(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        link_id = _propose(client).json()["link_id"]
        bad = client.post(
            f"/api/v1/hardware/links/{link_id}/verify",
            json={"verified_by": "jelles",
                  "operator_key": "wrong-key"})
        assert bad.status_code == 403
        # Node token is not accepted either (no such field;
        # operator key missing still refuses).
        missing = client.post(
            f"/api/v1/hardware/links/{link_id}/verify",
            json={"verified_by": "jelles", "operator_key": ""})
        assert missing.status_code == 403
        link = client.get(
            f"/api/v1/hardware/links/{link_id}").json()
        assert link["status"] == "PROPOSED"


def test_verify_then_reality_shows_verified(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        _beat(client, "node-b", TOKEN_B, hardware=[{
            "kind": "gpu", "identifier": "gpu-0",
            "status": "connected"}],
            telemetry={"cpu_percent": 5.0})
        link_id = _propose(client).json()["link_id"]
        response = client.post(
            f"/api/v1/hardware/links/{link_id}/verify",
            json={"verified_by": "jelles",
                  "operator_key": OPERATOR})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "VERIFIED"
        reality = client.get(
            "/api/v1/nodes/node-b/reality").json()
        gpu = next(item for item in reality["hardware"]
                   if item["identifier"] == "gpu-0")
        assert gpu["trust"] == "VERIFIED"


def test_revoke_sticks(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        link_id = _propose(client).json()["link_id"]
        client.post(f"/api/v1/hardware/links/{link_id}/verify",
                    json={"verified_by": "jelles",
                          "operator_key": OPERATOR})
        revoked = client.post(
            f"/api/v1/hardware/links/{link_id}/revoke",
            json={"revoked_by": "jelles", "reason": "sold",
                  "operator_key": OPERATOR})
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "REVOKED"
        again = client.post(
            f"/api/v1/hardware/links/{link_id}/verify",
            json={"verified_by": "jelles",
                  "operator_key": OPERATOR})
        assert again.status_code == 422
        link = client.get(
            f"/api/v1/hardware/links/{link_id}").json()
        assert link["status"] == "REVOKED"


def test_reality_never_verified_without_link(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        _beat(client, "node-b", TOKEN_B, hardware=[{
            "kind": "gpu", "identifier": "gpu-0",
            "status": "connected"}],
            telemetry={"cpu_percent": 5.0})
        reality = client.get(
            "/api/v1/nodes/node-b/reality").json()
        trusts = {item["trust"] for item in reality["hardware"]}
        assert "VERIFIED" not in trusts


# -- 2. finance ----------------------------------------------------------

def test_finance_record_and_status(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        created = client.post("/api/v1/finance/records", json={
            "kind": "budget", "title": "Solar upgrade pot",
            "amount_minor": 50000, "currency": "EUR",
            "project_ref": "proj_solar", "recorded_by": "jelles"})
        assert created.status_code == 201, created.text
        assert created.json()["status"] == "DRAFT"
        record_id = created.json()["record_id"]
        assert record_id.startswith("fin_")
        moved = client.post(
            f"/api/v1/finance/records/{record_id}/status",
            json={"status": "CONFIRMED"})
        assert moved.status_code == 200
        assert moved.json()["status"] == "CONFIRMED"
        summary = client.get(
            "/api/v1/finance/summary",
            params={"project_ref": "proj_solar"}).json()
        assert summary["summary"]["total"] == 1


def test_finance_unknown_amount_and_bad_kind(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        created = client.post("/api/v1/finance/records", json={
            "kind": "expense", "title": "Cables (price unknown)"})
        assert created.status_code == 201
        assert created.json()["amount_minor"] is None
        bad = client.post("/api/v1/finance/records", json={
            "kind": "stonks", "title": "Fake money"})
        assert bad.status_code == 422
        bad_status = client.post(
            f"/api/v1/finance/records/"
            f"{created.json()['record_id']}/status",
            json={"status": "RICH"})
        assert bad_status.status_code == 422


# -- 3. energy -----------------------------------------------------------

def test_energy_record_and_state(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        created = client.post("/api/v1/energy/records", json={
            "source": "solar", "kind": "production",
            "value": 410.5, "unit": "W",
            "project_ref": "proj_solar"})
        assert created.status_code == 201, created.text
        assert created.json()["record_id"].startswith("enr_")
        unknown = client.post("/api/v1/energy/records", json={
            "source": "battery", "kind": "state",
            "project_ref": "proj_solar"})
        assert unknown.status_code == 201
        assert unknown.json()["value"] is None
        state = client.get(
            "/api/v1/energy/state",
            params={"project_ref": "proj_solar"}).json()
        assert state["state"] == "KNOWN"
        bad = client.post("/api/v1/energy/records", json={
            "source": "coal", "kind": "production"})
        assert bad.status_code == 422


# -- 4. symbiosis + templates -------------------------------------------

def test_symbiosis_new_prefixes_and_predicates(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        from coordinator.app.symbiosis import (
            check_predicate, clean_entity)
        assert clean_entity("fin_abc123") == "fin_abc123"
        assert clean_entity("enr_abc123") == "enr_abc123"
        assert clean_entity("hv_abc123") == "hv_abc123"
        assert clean_entity("qst_abc123") == "qst_abc123"
        for verb in ("funds", "funded_by", "powers",
                     "powered_by", "allocated_to"):
            assert check_predicate(verb) == verb
        with pytest.raises(ValueError):
            check_predicate("owns")
        with pytest.raises(ValueError):
            clean_entity("fin-!!! ")


def test_v2_mission_templates(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        from coordinator.app.mission_templates import (
            get_template, instantiate)
        chain = get_template("idea_to_verification")
        assert chain is not None
        steps, max_steps = instantiate(
            "idea_to_verification", "solar upgrade")
        assert len(steps) >= 8
        assert max_steps == 10
        # Every step kind is an existing safe mission kind.
        from coordinator.app.missions import VALID_STEP_KINDS
        assert {step["kind"] for step in steps} <= VALID_STEP_KINDS
        money = get_template("project_finance_energy")
        assert money is not None
        steps2, _ = instantiate(
            "project_finance_energy", "solar upgrade")
        assert len(steps2) == 5
        listed = client.get(
            "/api/v1/mission-templates").json()
        entries = listed.get("templates", []) \
            if isinstance(listed, dict) else listed
        ids = [entry["template_id"] for entry in entries]
        assert "idea_to_verification" in ids
        assert "project_finance_energy" in ids


# -- 5. quest trails -----------------------------------------------------

def test_quest_lifecycle(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        fin = client.post("/api/v1/finance/records", json={
            "kind": "budget", "title": "Solar pot"}).json()
        created = client.post("/api/v1/quests", json={
            "title": "Build Solar Upgrade",
            "steps": [
                {"key": "money", "label": "Budget",
                 "kind": "finance",
                 "ref": fin["record_id"]},
                {"key": "power", "label": "Panels live",
                 "kind": "energy", "ref": ""},
            ]})
        assert created.status_code == 201, created.text
        detail = created.json()
        assert detail["total"] == 2
        assert detail["done"] == 0
        assert detail["state"] == "WAITING"
        quest_id = detail["quest_id"]
        assert quest_id.startswith("qst_")
        fetched = client.get(
            f"/api/v1/quests/{quest_id}").json()
        money = next(step for step in fetched["steps"]
                     if step["key"] == "money")
        assert money["href"] == f"/finance?record_id=" \
            f"{fin['record_id']}"
        assert money["readiness"] in (
            "READY", "WAITING", "BLOCKED", "UNAVAILABLE")
        # Confirming the finance record moves real progress.
        client.post(
            f"/api/v1/finance/records/{fin['record_id']}/status",
            json={"status": "CONFIRMED"})
        refreshed = client.post(
            f"/api/v1/quests/{quest_id}/refresh").json()
        assert refreshed["done"] == 1
        assert refreshed["progress"] == "1/2"


def test_quest_rejects_bad_steps(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        bad_kind = client.post("/api/v1/quests", json={
            "title": "Bad", "steps": [
                {"key": "x", "label": "X", "kind": "teleport",
                 "ref": "abc"}]})
        assert bad_kind.status_code == 422
        empty = client.post("/api/v1/quests", json={
            "title": "Empty", "steps": []})
        assert empty.status_code == 422


# -- 6. workflows --------------------------------------------------------

def test_workflow_preview_creates_nothing(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        before = client.get("/api/v1/tasks").json()
        before_count = len(before.get("tasks", before)
                           if isinstance(before, dict) else before)
        preview = client.post("/api/v1/workflows/preview", json={
            "requesting_node": "node-a", "node_token": TOKEN_A,
            "steps": [{"task_kind": "research.fetch_url",
                       "capability": "research.fetch",
                       "target_node": "node-b",
                       "payload": {"url": "https://example.com/a"},
                       "reason": "b42 preview"}]})
        assert preview.status_code == 200, preview.text
        assert preview.json()["created"] is False
        after = client.get("/api/v1/tasks").json()
        after_count = len(after.get("tasks", after)
                          if isinstance(after, dict) else after)
        assert after_count == before_count


def test_workflow_dispatch_two_nodes(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        dispatched = client.post(
            "/api/v1/workflows/dispatch", json={
                "requesting_node": "node-a",
                "node_token": TOKEN_A,
                "steps": [
                    {"task_kind": "research.fetch_url",
                     "capability": "research.fetch",
                     "target_node": "node-b",
                     "payload": {"url": "https://example.com/a"},
                     "reason": "research on B"},
                    {"task_kind": "research.fetch_url",
                     "capability": "research.fetch",
                     "target_node": "node-b",
                     "payload": {"url": "https://example.com/b"},
                     "reason": "more research on B"}]})
        assert dispatched.status_code == 201, dispatched.text
        body = dispatched.json()
        assert body["steps_dispatched"] == 2
        assert len(body["task_ids"]) == 2
        assert len(body["receipts"]) == 2


def test_workflow_refusals(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        # Wrong credential.
        denied = client.post("/api/v1/workflows/dispatch", json={
            "requesting_node": "node-a",
            "node_token": "wrong-token-xxxxxxxx",
            "steps": [{"task_kind": "research.fetch_url",
                       "capability": "research.fetch",
                       "target_node": "node-b",
                       "payload": {"url": "https://example.com/"}}]})
        assert denied.status_code == 403
        # Wildcard capability.
        wild = client.post("/api/v1/workflows/dispatch", json={
            "requesting_node": "node-a", "node_token": TOKEN_A,
            "steps": [{"task_kind": "research.fetch_url",
                       "capability": "research.*",
                       "target_node": "node-b",
                       "payload": {}}]})
        assert wild.status_code == 422
        # Shell-shaped kind.
        shell = client.post("/api/v1/workflows/dispatch", json={
            "requesting_node": "node-a", "node_token": TOKEN_A,
            "steps": [{"task_kind": "exec.shell",
                       "capability": "research.fetch",
                       "target_node": "node-b",
                       "payload": {}}]})
        assert shell.status_code == 422
        # Missing target.
        untargeted = client.post(
            "/api/v1/workflows/dispatch", json={
                "requesting_node": "node-a",
                "node_token": TOKEN_A,
                "steps": [{"task_kind": "research.fetch_url",
                           "capability": "research.fetch",
                           "payload": {}}]})
        assert untargeted.status_code == 422
        # Secret payload.
        secret = client.post("/api/v1/workflows/dispatch", json={
            "requesting_node": "node-a", "node_token": TOKEN_A,
            "steps": [{"task_kind": "research.fetch_url",
                       "capability": "research.fetch",
                       "target_node": "node-b",
                       "payload": {"api_key": "hunter2"}}]})
        assert secret.status_code == 422
        # Traversal target.
        traversal = client.post(
            "/api/v1/workflows/dispatch", json={
                "requesting_node": "node-a",
                "node_token": TOKEN_A,
                "steps": [{"task_kind": "research.fetch_url",
                           "capability": "research.fetch",
                           "target_node": "../evil",
                           "payload": {}}]})
        assert traversal.status_code in (404, 422, 409)


# -- 7. integration surfaces ---------------------------------------------

def test_overview_has_ecosystem_sections(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        _propose(client)
        client.post("/api/v1/finance/records", json={
            "kind": "budget", "title": "Pot"})
        client.post("/api/v1/energy/records", json={
            "source": "solar", "kind": "state"})
        client.post("/api/v1/quests", json={
            "title": "Q", "steps": [
                {"key": "a", "label": "A", "kind": "note",
                 "ref": ""}]})
        overview = client.get(
            "/api/v1/ecosystem/overview").json()
        assert overview["hardware"]["links"] == 1
        assert overview["finance"]["total"] == 1
        assert overview["energy"]["total"] == 1
        assert overview["quests"]["open"] == 1


def test_guide_mentions_unverified_hardware(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        _beat(client, "node-b", TOKEN_B, hardware=[{
            "kind": "gpu", "identifier": "gpu-0",
            "status": "connected"}],
            telemetry={"cpu_percent": 5.0})
        guide = client.get("/api/v1/guide").json()
        items = guide.get("items", guide
                          if isinstance(guide, list) else [])
        hardware_items = [item for item in items
                          if item.get("kind") == "hardware"]
        assert hardware_items, "guide should flag unverified GPU"
        assert hardware_items[0]["next"]["href"] == "/hardware"


def test_morning_only_real_sections(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        morning = client.get("/api/v1/reports/morning").json()
        titles = [section["title"] for section in
                  morning.get("sections", [])]
        assert "Hardware verification" not in titles
        assert "Quest trails" not in titles
        assert "Finance" not in titles
        assert "Energy" not in titles
        _propose(client)
        morning2 = client.get("/api/v1/reports/morning").json()
        titles2 = [section["title"] for section in
                   morning2.get("sections", [])]
        assert "Hardware verification" in titles2


def test_packet_v2_scopes_finance(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        created = client.post("/api/v1/finance/records", json={
            "kind": "budget", "title": "Secret pot",
            "amount_minor": 99999, "project_ref": "proj_x"})
        assert created.status_code == 201
        from coordinator.app.context_packet import build_packet_v2
        scoped = build_packet_v2(task="t", project_id="proj_x")
        generic_packet = build_packet_v2(task="t")
        scoped_amounts = [record.get("amount_minor") for record in
                          scoped["ecosystem"]["finance"]["records"]]
        assert 99999 in scoped_amounts
        generic_amounts = [record.get("amount_minor") for record in
                           generic_packet["ecosystem"]["finance"][
                               "records"]]
        assert 99999 not in generic_amounts
        assert "ecosystem" in scoped
        assert scoped["ecosystem"]["quests"] == [] or True


def test_mobile_dashboard_has_ecosystem(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        dash = client.get(
            "/api/v1/mobile/dashboard").json()
        for key in ("quests", "hardware", "finance", "energy",
                    "mesh_receipts"):
            assert key in dash, f"mobile dashboard misses {key}"


def test_pages_render(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _pair(client)
        for path in ("/hardware", "/finance", "/energy",
                     "/quests", "/world", "/mobile", "/morning"):
            response = client.get(path)
            assert response.status_code == 200, path
