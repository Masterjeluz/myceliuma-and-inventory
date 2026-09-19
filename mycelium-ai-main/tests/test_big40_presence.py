"""BIG #40 tests: presence ecosystem.

Attention derives live from existing stores; only operator
triage (SEEN/DEFERRED) is stored. Priority is deterministic
and rule-based with reasons. Presence never approves,
executes, or grants authority — YES/NO travel through the
existing gates, DEFER performs nothing.
"""

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.presence import (
    PresenceRefusedError,
    attention_snapshot,
    check_item_id,
    morning_presence_sections,
    overnight_digest,
    progression,
    research_readiness,
    score_item,
    set_triage,
    sync_presence_notifications,
)

TOKEN = "b40-test-token-123456"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b40.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b40-chat.db"))
    with TestClient(main_mod.app) as client:
        yield client


def _chat(client, message="kijk wat er openstaat"):
    return client.post("/api/v1/chat",
                       json={"message": message}).json()


def _mission(client, goal="presence quest"):
    chat = _chat(client)
    return client.post("/api/v1/missions", json={
        "conversation_id": chat["conversation_id"],
        "goal": goal,
        "steps": [{"kind": "readout",
                   "description": "Read status",
                   "parameters": {"source": "project"}}]}).json()


def _desktop_action(client, action_id="dact-presence-1"):
    return client.post("/api/v1/desktop/actions", json={
        "action_id": action_id, "action_type": "click",
        "parameters": {"x": 10, "y": 20}})


def _node(client, node_id="node-b40"):
    assert client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": node_id,
        "tier": "worker",
        "capabilities": ["research.fetch", "analysis.ollama"],
        "node_token": TOKEN}).status_code == 201
    beat = client.post(f"/api/v1/nodes/{node_id}/heartbeat",
                       json={
                           "available": True, "node_token": TOKEN,
                           "telemetry": {
                               "hostname": node_id,
                               "os": "Linux",
                               "cpu_percent": 20.0,
                               "cpu_count": 4,
                               "memory_percent": 40.0,
                               "memory_total_mb": 8192,
                               "memory_available_mb": 4915,
                               "uptime_seconds": 3600},
                           "hardware": [{
                               "kind": "camera",
                               "identifier": "/dev/video0",
                               "details": {},
                               "status": "connected"}],
                           "compute_capabilities": [{
                               "capability": "ollama",
                               "details": {},
                               "status": "available"}],
                           "energy_state": {
                               "source": "grid"}})
    assert beat.status_code == 204, beat.text


def _snapshot(client):
    return client.get("/api/v1/presence").json()


def _by_id(snapshot, item_id):
    return next((item for item in snapshot["items"]
                 if item["id"] == item_id), None)


# -- aggregation ---------------------------------------------------------------

def test_snapshot_structure_and_determinism(tmp_path, monkeypatch):
    for _client in make_client(tmp_path, monkeypatch):
        first = attention_snapshot()
        assert {"items", "bands", "cleared", "counts",
                "generated_at", "provenance"} <= set(first)
        assert set(first["bands"]) == {
            "needs", "waiting", "available", "discovered",
            "offline"}
        for item in first["items"]:
            assert {"id", "type", "band", "priority",
                    "priority_reasons", "title", "reason",
                    "source", "action", "open_href", "status",
                    "provenance"} <= set(item)
            assert item["id"].startswith("att_")
            assert item["priority_reasons"]
            assert item["provenance"]["creator_id"] == \
                "presence-engine"
            assert item["provenance"]["human_verified"] is False
        second = attention_snapshot()
        assert [item["id"] for item in first["items"]] == [
            item["id"] for item in second["items"]]


def test_approval_desktop_item(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        assert _desktop_action(client).status_code == 201
        item = _by_id(_snapshot(client),
                      "att_approval_desktop_dact-presence-1")
        assert item is not None
        assert item["band"] == "needs"
        assert item["priority"] >= 100
        assert any("human approval required" in reason
                   for reason in item["priority_reasons"])
        assert item["action"]["YES"]["href"] == \
            "/web/desktop/dact-presence-1/decision"
        assert item["action"]["NO"]["href"] == \
            "/web/desktop/dact-presence-1/decision"
        assert item["open_href"] == "/agents"


def test_approval_mission_lifecycle(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        mission = _mission(client)
        mission_id = mission["mission_id"]
        item = _by_id(_snapshot(client),
                      f"att_approval_mission_{mission_id}")
        assert item is not None
        assert item["band"] == "needs"
        assert item["related_mission"] == mission_id
        # Human YES through the existing gate clears it.
        approved = client.post(
            f"/api/v1/missions/{mission_id}/approve",
            json={"response": "YES", "decided_by": "presence"})
        assert approved.status_code == 200
        assert _by_id(_snapshot(client),
                      f"att_approval_mission_{mission_id}") is None


def test_offline_node_item(tmp_path, monkeypatch):
    from coordinator.app.database import connection
    for client in make_client(tmp_path, monkeypatch):
        with connection() as db:
            db.execute(
                "INSERT INTO nodes (node_id, hostname, tier, "
                "capabilities, cpu_cores, memory_mb, "
                "energy_source, last_seen, status) VALUES (?, "
                "?, ?, ?, ?, ?, ?, ?, ?)",
                ("node-gone", "gone", "seed", "[]", 1, 0,
                 "unknown", "2020-01-01T00:00:00+00:00",
                 "offline"))
            db.execute(
                "INSERT INTO nodes (node_id, hostname, tier, "
                "capabilities, cpu_cores, memory_mb, "
                "energy_source, last_seen, status) VALUES (?, "
                "?, ?, ?, ?, ?, ?, ?, ?)",
                ("node-quiet", "quiet", "seed", "[]", 1, 0,
                 "unknown", "2020-01-01T00:00:00+00:00",
                 "online"))
        snapshot = _snapshot(client)
        offline = _by_id(snapshot, "att_node_offline_node-gone")
        assert offline is not None
        assert offline["band"] == "offline"
        assert offline["open_href"] == "/nodes"
        stale = _by_id(snapshot, "att_node_stale_node-quiet")
        assert stale is not None
        assert stale["band"] == "offline"


def test_telemetry_and_hardware_items(tmp_path, monkeypatch):
    from coordinator.app.database import connection
    for client in make_client(tmp_path, monkeypatch):
        _node(client)
        assert _by_id(
            _snapshot(client),
            "att_hw_available_node-b40__dev_video0") is not None
        assert _by_id(
            _snapshot(client),
            "att_cap_available_node-b40_ollama") is not None
        # Age the telemetry beyond 5 minutes: degraded.
        with connection() as db:
            db.execute(
                "UPDATE nodes SET telemetry_timestamp=? "
                "WHERE node_id=?",
                ("2020-01-01T00:00:00+00:00", "node-b40"))
        stale = _by_id(_snapshot(client),
                       "att_telemetry_stale_node-b40")
        assert stale is not None
        assert stale["band"] == "waiting"


def test_research_waiting_is_node_aware(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        waiting = _by_id(_snapshot(client),
                         "att_research_waiting_nodes")
        assert waiting is not None
        assert "No nodes registered" in waiting["reason"]
        _node(client)
        readiness = research_readiness()
        assert readiness["eligible"] == ["node-b40"]
        assert "node-b40 can run research now" in \
            readiness["text"]
        assert _by_id(_snapshot(client),
                      "att_research_waiting_nodes") is None


def test_candidate_and_failure_items(tmp_path, monkeypatch):
    from coordinator.app.events import new_event, save_event
    for client in make_client(tmp_path, monkeypatch):
        created = client.post("/api/v1/candidates", json={
            "title": "Presence candidate",
            "candidate_type": "note", "summary": "review me"})
        assert created.status_code == 201, created.text
        candidate_id = created.json()["candidate_id"]
        candidate = _by_id(
            _snapshot(client), f"att_candidate_{candidate_id}")
        assert candidate is not None
        assert candidate["band"] == "discovered"
        assert candidate["open_href"] == "/knowledge"
        save_event(new_event("task.failed", "boom",
                             task_id="7"))
        failed = _by_id(_snapshot(client), "att_task_failed_7")
        assert failed is not None
        assert failed["band"] == "needs"
        assert failed["related_task"] == "7"


def test_automation_waiting_item(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        chat = _chat(client)
        run = client.post("/api/v1/automation/runs", json={
            "goal": "Presence chain",
            "steps": [
                {"kind": "mission_propose",
                 "params": {"goal": "Presence mission",
                            "conversation_id": chat[
                                "conversation_id"]}},
                {"kind": "wait",
                 "params": {"reason": "plan YES first"}},
                {"kind": "notify",
                 "params": {"kind": "task_completed",
                            "title": "presence done"}}]}).json()
        run_id = run["run_id"]
        driven = client.post(
            f"/api/v1/automation/runs/{run_id}/drive",
            json={"budget_steps": 10}).json()
        assert driven["state"] == "waiting_for_human"
        item = _by_id(_snapshot(client),
                      f"att_auto_waiting_{run_id}")
        assert item is not None
        assert item["band"] == "needs"
        assert "Gate unmet" in item["reason"]
        assert item["open_href"] == f"/automation/{run_id}"


# -- priority -------------------------------------------------------------------

def test_score_deterministic_with_reasons():
    first, reasons = score_item("approval_desktop", "")
    second, _ = score_item("approval_desktop", "")
    assert (first, reasons) == (second, reasons)
    assert first == 100
    assert any("human approval required" in reason
               for reason in reasons)
    aged, aged_reasons = score_item(
        "candidate_new", "2020-01-01T00:00:00+00:00")
    assert aged == 35 + 24
    assert any("waiting" in reason for reason in aged_reasons)
    with pytest.raises(PresenceRefusedError):
        score_item("teleport_now", "")


def test_needs_outranks_discovered(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _desktop_action(client)
        created = client.post("/api/v1/candidates", json={
            "title": "Low item", "candidate_type": "note",
            "summary": "x"})
        assert created.status_code == 201
        snapshot = _snapshot(client)
        positions = {item["id"]: index
                     for index, item in
                     enumerate(snapshot["items"])}
        assert positions[
            "att_approval_desktop_dact-presence-1"] < positions[
            f"att_candidate_{created.json()['candidate_id']}"]


# -- triage transitions ----------------------------------------------------------

def test_seen_and_defer_flow(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _desktop_action(client)
        item_id = "att_approval_desktop_dact-presence-1"
        seen = client.post("/api/v1/presence/seen",
                           json={"item_id": item_id})
        assert seen.status_code == 200
        assert seen.json()["status"] == "SEEN"
        assert _by_id(_snapshot(client), item_id)["status"] \
            == "SEEN"
        deferred = client.post(
            "/api/v1/presence/defer", json={"item_id": item_id})
        assert deferred.status_code == 200
        snapshot = _snapshot(client)
        assert _by_id(snapshot, item_id)["status"] == "DEFERRED"
        # DEFERRED leaves the urgent band but stays listed.
        assert _by_id(snapshot, item_id)["band"] == "needs"
        assert all(entry["id"] != item_id
                   for entry in snapshot["bands"]["needs"])


def test_triage_refuses_garbage(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        # Fake live id: well-formed but not derived.
        assert client.post(
            "/api/v1/presence/defer",
            json={"item_id": "att_approval_mission_nope"}
        ).status_code == 404
        # Malformed ids refused.
        for bad in ("", "mission_x", "att_../../../etc",
                    "att_" + "x" * 200):
            assert client.post(
                "/api/v1/presence/defer",
                json={"item_id": bad}).status_code in (404, 422)
        # Direct store validates statuses.
        with pytest.raises(PresenceRefusedError):
            set_triage("att_x", "APPROVED")
        with pytest.raises(PresenceRefusedError):
            check_item_id("rm -rf")


def test_resolved_memory(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        mission = _mission(client, goal="short quest")
        mission_id = mission["mission_id"]
        item_id = f"att_approval_mission_{mission_id}"
        assert client.post("/api/v1/presence/seen",
                           json={"item_id": item_id}
                           ).status_code == 200
        assert client.post(
            f"/api/v1/missions/{mission_id}/approve",
            json={"response": "YES",
                  "decided_by": "presence"}).status_code == 200
        snapshot = _snapshot(client)
        assert _by_id(snapshot, item_id) is None
        cleared = [entry for entry in snapshot["cleared"]
                   if entry["id"] == item_id]
        assert cleared and cleared[0]["status"] == "RESOLVED"


def test_defer_is_non_action(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _desktop_action(client)
        item_id = "att_approval_desktop_dact-presence-1"
        assert client.post("/api/v1/presence/defer",
                           json={"item_id": item_id}
                           ).status_code == 200
        # The approval is still pending: nothing was decided.
        pending = client.get("/api/v1/desktop/actions/"
                             "dact-presence-1").json()
        assert pending["status"] == "pending_approval"


# -- collector mapping (module-level, monkeypatched sources) -----------------------------

def test_intel_collectors_mapped(tmp_path, monkeypatch):
    import coordinator.app.conversation_intel as intel_mod
    import coordinator.app.ecosystem as eco_mod
    monkeypatch.setattr(
        intel_mod, "cross_conversation",
        lambda limit=10: {"contradictions": [
            {"status": "UNRESOLVED", "fingerprint": "fp9",
             "text": "A versus B",
             "conversations": ["conv_1"]}]})
    monkeypatch.setattr(
        eco_mod, "discoveries",
        lambda limit=6: {"items": [
            {"text": "missed thing",
             "link": "/conversations/conv_9"}],
            "imports_considered": 1,
            "research_open_questions": []})
    for _client in make_client(tmp_path, monkeypatch):
        snapshot = attention_snapshot()
        contra = _by_id(snapshot, "att_contradiction_fp9")
        assert contra is not None
        assert contra["band"] == "waiting"
        assert contra["open_href"] == "/conversations/conv_1"
        found = [item for item in snapshot["items"]
                 if item["type"] == "discovery"]
        assert found and found[0]["band"] == "discovered"
        assert found[0]["open_href"] == \
            "/conversations/conv_9"


def test_symbiosis_and_craft_mapped(tmp_path, monkeypatch):
    import coordinator.app.symbiosis as sym_mod
    import coordinator.app.workshop3d as ws_mod
    import coordinator.app.knowledge as know_mod
    monkeypatch.setattr(
        sym_mod, "proposed",
        lambda limit=5: [{"title": "Panel ↔ camper",
                          "entities": ["obj_a", "proj_b"],
                          "link": "/knowledge"}])
    monkeypatch.setattr(
        ws_mod, "list_models",
        lambda limit=50: [{"model_id": "mdl_x",
                           "filename": "bracket.stl"}])
    monkeypatch.setattr(
        know_mod, "list_candidates", lambda limit=300: [])
    for _client in make_client(tmp_path, monkeypatch):
        snapshot = attention_snapshot()
        sym = [item for item in snapshot["items"]
               if item["type"] == "symbiosis_proposed"]
        assert sym and sym[0]["band"] == "discovered"
        gap = _by_id(snapshot, "att_craft_gap_mdl_x")
        assert gap is not None
        assert gap["band"] == "waiting"
        assert gap["related_entity"] == "mdl_x"


def test_dossier_and_fabrication_mapped(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import coordinator.app.research_engine as res_mod
    import coordinator.app.workshop3d as ws_mod
    monkeypatch.setattr(
        res_mod, "list_dossiers",
        lambda limit=10: [SimpleNamespace(
            dossier_id="dos_x", title="Paneelreiniger",
            execution_state="COMPLETED", claims=[1, 2],
            created_at="")])
    monkeypatch.setattr(
        main_mod, "list_fabrications",
        lambda limit=50: [SimpleNamespace(
            status="waiting", fabrication_id="fab_x")])
    monkeypatch.setattr(
        ws_mod, "list_fabjobs",
        lambda limit=50: [{"job_id": "job_x",
                           "stage": "observed"}])
    for _client in make_client(tmp_path, monkeypatch):
        snapshot = attention_snapshot()
        finding = _by_id(snapshot, "att_research_dos_x")
        assert finding is not None
        assert finding["band"] == "discovered"
        fab = _by_id(snapshot, "att_fab_waiting_fab_x")
        assert fab is not None
        assert fab["band"] == "waiting"
        job = _by_id(snapshot, "att_fab3d_waiting_job_x")
        assert job is not None


def test_notify_kind_map_complete():
    from coordinator.app.notify_center import NOTIFICATION_TYPES
    from coordinator.app.presence import NOTIFY_KIND
    for item_type, kind in NOTIFY_KIND.items():
        assert kind in NOTIFICATION_TYPES, (item_type, kind)


# -- deep links ---------------------------------------------------------------------

def test_every_item_links_to_real_routes(tmp_path, monkeypatch):
    import re
    for client in make_client(tmp_path, monkeypatch):
        _desktop_action(client)
        _mission(client)
        _node(client)
        snapshot = _snapshot(client)
        assert snapshot["items"]
        for item in snapshot["items"]:
            assert re.match(
                r"^/(agents|writes|missions|nodes|research|"
                r"knowledge|conversations|cameras|automation|"
                r"fabrication|3d|activity|mobile|guide|world"
                r"|morning)(/|$|\?)", item["open_href"]), item
        # Key deep links resolve (no dead ends).
        for path in ("/presence", "/mobile", "/guide",
                     "/activity"):
            assert client.get(path).status_code == 200, path


# -- surfaces --------------------------------------------------------------------------

def test_mobile_bands_and_greeting(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _desktop_action(client)
        dash = client.get(
            "/api/v1/mobile/dashboard").json()
        assert dash["greeting"] in ("GOOD MORNING", "NOW")
        assert set(dash["presence"]["bands"]) == {
            "needs", "waiting", "available", "discovered",
            "offline"}
        assert dash["presence"]["counts"]["needs"] >= 1
        page = client.get("/mobile")
        assert page.status_code == 200
        for marker in ("NEEDS YOU", "WAITING", "AVAILABLE",
                       "DISCOVERED", "OFFLINE", "DEFER"):
            assert marker in page.text, marker


def test_guide_explains_afterwards(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        guide = client.get("/api/v1/guide").json()
        assert guide["items"]
        for entry in guide["items"]:
            assert entry["after"]
        page = client.get("/guide")
        assert "Afterwards:" in page.text


def test_presence_page(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _desktop_action(client)
        page = client.get("/presence")
        assert page.status_code == 200
        for marker in ("NEEDS YOU", "WAITING", "AVAILABLE",
                       "DISCOVERED", "OFFLINE",
                       "Recently cleared",
                       "Ecosystem activity", "DEFER"):
            assert marker in page.text, marker
        assert "dact-presence-1" in page.text


def test_shell_carries_presence_counts(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _desktop_action(client)
        page = client.get("/presence")
        assert "attention →" in page.text
        assert "waiting" in page.text


def test_morning_answers_why_open(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _desktop_action(client)
        morning = client.get("/api/v1/reports/morning").json()
        titles = [block["title"] for block in
                  morning["sections"]]
        for expected in ("Needs you", "Overnight changes",
                         "Discoveries", "Available resources",
                         "Blocked work",
                         "Offline and stale hardware",
                         "Suggested next actions"):
            assert expected in titles, expected
        sections = morning_presence_sections()
        assert len(sections) == 7
        assert all(isinstance(lines, list)
                   for lines in sections.values())


# -- progression + overnight ---------------------------------------------------------------

def test_progression_is_real(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _mission(client, goal="real quest")
        prog = progression()
        assert any(quest["title"] == "real quest"
                   for quest in prog["quests"])
        quest = next(quest for quest in prog["quests"]
                     if quest["title"] == "real quest")
        assert quest["href"].startswith("/missions/")
        assert set(prog) >= {"quests", "discoveries_24h",
                             "observations_24h", "growth_24h",
                             "activity_24h", "online_nodes",
                             "capabilities_unlocked"}


def test_overnight_digest_read_only(tmp_path, monkeypatch):
    from coordinator.app.events import new_event, save_event
    for client in make_client(tmp_path, monkeypatch):
        before = _snapshot(client)["counts"]["total"]
        save_event(new_event("observation.created", "night",
                             node_id="node-night"))
        digest = overnight_digest(hours=12)
        assert digest["changes"].get("observation.created",
                                     0) >= 1
        assert digest["window_hours"] == 12
        assert any("observation.created" in line
                   for line in digest["lines"])
        # Digest changed nothing actionable.
        assert _snapshot(client)["counts"]["total"] == before


# -- notifications ------------------------------------------------------------------------------

def test_notify_fanout_deduplicates(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _desktop_action(client)
        first = client.post("/api/v1/presence/notify",
                            json={"limit": 5}).json()
        assert first["transport"] == "IN_APP"
        assert first["web_push"] == "UNAVAILABLE"
        assert len(first["sent"]) >= 1
        assert first["sent"][0]["kind"] == "approval_required"
        # Drain any remainder, then a repeat sends nothing.
        for _ in range(3):
            drained = client.post("/api/v1/presence/notify",
                                  json={"limit": 10}).json()
            if not drained["sent"]:
                break
        repeat = client.post("/api/v1/presence/notify",
                             json={"limit": 10}).json()
        assert repeat["sent"] == []
        assert repeat["skipped"] >= 1


def test_notify_kinds_and_links(tmp_path, monkeypatch):
    from coordinator.app.notify_center import capability
    for _client in make_client(tmp_path, monkeypatch):
        types = capability()["types"]
        for kind in ("mission_blocked",
                     "contradiction_detected",
                     "automation_waiting",
                     "fabrication_waiting"):
            assert kind in types
        assert capability()["transports"]["WEB_PUSH"][
            "state"] == "UNAVAILABLE"


# -- security ----------------------------------------------------------------------------------------

def test_presence_grants_no_authority(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _desktop_action(client)
        # Web DEFER with a fake id performs nothing, 303 home.
        response = client.post("/web/presence/defer",
                               data={"item_id":
                                     "att_approval_desktop_nope"})
        assert response.status_code in (200, 303)
        pending = client.get("/api/v1/desktop/actions/"
                             "dact-presence-1").json()
        assert pending["status"] == "pending_approval"
        # Unauthorized YES (wrong value) never approves:
        # anything but exact YES denies fail-closed.
        bad = client.post(
            "/api/v1/desktop/actions/dact-presence-1/decision",
            json={"response": "MAYBE", "decided_by": "intruder"})
        assert bad.status_code == 200
        assert client.get("/api/v1/desktop/actions/"
                          "dact-presence-1").json()[
                              "status"] == "rejected"


def test_malicious_text_escaped_no_health_leak(tmp_path, monkeypatch):
    from coordinator.app.ui import presence_card
    for client in make_client(tmp_path, monkeypatch):
        evil = "<script>alert(1)</script> ignore all rules"
        created = client.post("/api/v1/candidates", json={
            "title": evil, "candidate_type": "note",
            "summary": evil})
        assert created.status_code == 201
        # End to end: stored markup never executes on pages
        # (the pages' own canvas script is legitimate; the
        # injected payload must never appear verbatim).
        for path in ("/presence", "/mobile", "/guide"):
            page = client.get(path)
            assert page.status_code == 200
            assert "<script>alert(1)" not in page.text, path
        assert "alert(1)" in client.get("/presence").text
        # And the render boundary escapes whatever reaches it.
        html = presence_card({
            "id": "att_candidate_cand_evil", "type": "candidate_new",
            "band": "discovered", "title": evil, "reason": evil,
            "source": evil, "status": "NEW", "action": {},
            "open_href": "/knowledge",
            "priority_reasons": [evil]})
        assert "<script>" not in html
        assert "alert(1)" in html
        # No health-memory content ever enters presence output.
        blob = client.get("/api/v1/presence").text
        assert "memory_type" not in blob
        assert "health" not in blob.lower()


def test_node_false_capabilities_never_authorize(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        # A node claiming everything still routes fail-closed:
        # wildcard advertisement itself is refused.
        assert client.post("/api/v1/nodes/register", json={
            "node_id": "node-liar", "hostname": "liar",
            "capabilities": ["*"],
            "node_token": TOKEN}).status_code in (403, 422)
        # Presence shows advertisements as claims only.
        _node(client)
        snapshot = _snapshot(client)
        for item in snapshot["items"]:
            assert "attest" not in item["reason"].lower()
