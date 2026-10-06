"""BIG56 (M1) drive tests: mission control from the /side Journal.

Proves, without fakes and without new execution power, that an
operator can drive the EXISTING mission loop from the game Journal:

- journal exposes tick + dispatch + linked automation-drive as
  action descriptors on existing routes (singular ``action`` kept
  for backwards compatibility);
- dispatch refuses before exact YES (409), works after YES, and is
  idempotent on repeat (same task, no duplicate);
- the full chain quest -> mission -> YES -> dispatch -> node claim
  -> complete -> tick -> mission completed -> quest COMPLETED is
  reachable purely through journal action paths;
- waiting entries never carry drive/dispatch actions;
- liveness reports real, current probe states (REAL vs
  PROCES-ONLY vs UNAVAILABLE vs KEY-MISSING), never invented
  green;
- /side renders the Journal drive controls.

No background threads, no auto-approval, no new task kinds: every
step goes through the existing gates (the tests assert the gates
refuse where they must).
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN = "b56-test-token-12345678"
OPERATOR = "b56-operator-key"


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b56.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b56-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", OPERATOR)
    with TestClient(main_mod.app) as test_client:
        yield test_client


def register_code_node(test_client, node_id="b56-code-01"):
    res = test_client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": "b56host", "tier": "worker",
        "capabilities": ["code.review"], "executors": ["exec:code"],
        "node_token": TOKEN})
    assert res.status_code == 201, res.text
    beat = test_client.post(f"/api/v1/nodes/{node_id}/heartbeat",
                            json={"available": True,
                                  "node_token": TOKEN})
    assert beat.status_code == 204, beat.text


def claim(test_client, node_id="b56-code-01"):
    return test_client.post(
        f"/api/v1/tasks/claim/{node_id}?node_token={TOKEN}", json={})


def complete(test_client, task_id, node_id="b56-code-01"):
    return test_client.post(f"/api/v1/tasks/{task_id}/complete", json={
        "node_id": node_id, "success": True,
        "result": {"summary": "B56 drive review done",
                   "files_changed": []}})


def make_mission(test_client, goal="B56 drive the loop"):
    made = test_client.post("/api/v1/play/mission",
                            json={"goal": goal}).json()
    return made["mission_id"], made["step_id"], made["quest_id"]


def journal(test_client):
    res = test_client.get("/api/v1/play/journal")
    assert res.status_code == 200, res.text
    return res.json()


def test_journal_exposes_drive_actions_after_yes(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        mid, sid, _ = make_mission(test_client)
        test_client.post(f"/api/v1/missions/{mid}/approve",
                         json={"response": "YES", "decided_by": "speler"})
        body = journal(test_client)
        active = body["active"]
        assert active["id"] == mid
        # Singular action kept (tick) for backwards compatibility.
        assert active["action"]["path"].endswith("/tick")
        assert active["step"]["step_id"] == sid
        paths = [item["path"] for item in active["actions"]]
        assert active["actions"][0]["path"].endswith("/tick")
        dispatch = [item for item in active["actions"]
                    if item["path"].endswith("/dispatch")]
        assert len(dispatch) == 1, paths
        assert dispatch[0]["method"] == "POST"
        assert dispatch[0]["body"] == {"step_id": sid}


def test_journal_links_automation_drive(tmp_path, monkeypatch):
    from coordinator.app.automation import create_run
    for test_client in api(tmp_path, monkeypatch):
        mid, _, _ = make_mission(test_client,
                                 goal="B56 linked automation drive")
        test_client.post(f"/api/v1/missions/{mid}/approve",
                         json={"response": "YES", "decided_by": "speler"})
        run = create_run("B56 observe only",
                         [{"kind": "observe",
                           "params": {"source": "missions"}}],
                         mission_id=mid, actor="b56-test")
        body = journal(test_client)
        drives = [item for item in body["active"]["actions"]
                  if item["path"].endswith("/drive")]
        assert len(drives) == 1, body["active"]["actions"]
        assert drives[0]["path"] == \
            f"/api/v1/automation/runs/{run.run_id}/drive"
        assert drives[0]["body"] == {"budget_steps": 10}


def test_waiting_entries_never_carry_drive(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        make_mission(test_client, goal="B56 still waiting")
        body = journal(test_client)
        assert body["active"] is None
        assert len(body["waiting"]) == 1
        waiting = body["waiting"][0]
        assert waiting["action"]["path"].endswith("/approve")
        assert "actions" not in waiting
        assert "dispatch" not in waiting["action"]["path"]
        assert "drive" not in waiting["action"]["path"]


def test_dispatch_refused_before_yes(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        mid, sid, _ = make_mission(test_client,
                                   goal="B56 no drive before YES")
        refused = test_client.post(f"/api/v1/missions/{mid}/dispatch",
                                   json={"step_id": sid})
        assert refused.status_code == 409, refused.text


def test_full_drive_chain_via_journal_paths(tmp_path, monkeypatch):
    """quest -> play mission -> YES -> dispatch -> claim -> complete
    -> tick -> mission completed -> quest COMPLETED, every drive
    step taken from the journal action descriptors."""
    for test_client in api(tmp_path, monkeypatch):
        register_code_node(test_client)
        mid, sid, qid = make_mission(test_client,
                                     goal="B56 full drive chain")

        body = journal(test_client)
        waiting = [item for item in body["waiting"]
                   if item["id"] == mid][0]
        yes = test_client.post(waiting["action"]["path"],
                               json={"response": "YES",
                                     "decided_by": "speler"})
        assert yes.status_code == 200, yes.text

        body = journal(test_client)
        dispatch = [item for item in body["active"]["actions"]
                    if item["path"].endswith("/dispatch")][0]
        first = test_client.post(dispatch["path"],
                                 json=dispatch["body"])
        assert first.status_code == 200, first.text
        assert first.json()["task_ids"]
        task_id = first.json()["task_ids"][0]

        # Repeated Drive is idempotent: same task, no duplicate.
        second = test_client.post(dispatch["path"],
                                  json=dispatch["body"])
        assert second.status_code == 200, second.text
        assert second.json()["task_ids"] == [task_id]

        claimed = claim(test_client)
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["id"] == task_id
        done = complete(test_client, task_id)
        assert done.status_code == 204, done.text

        body = journal(test_client)
        tick = [item for item in body["active"]["actions"]
                if item["path"].endswith("/tick")][0]
        ticked = test_client.post(tick["path"], json={})
        assert ticked.status_code == 200, ticked.text
        mission = test_client.get(
            f"/api/v1/missions/{mid}").json()
        assert mission["status"] == "completed"

        quests = test_client.get("/api/v1/quests?limit=20").json()
        mine = [quest for quest in quests["quests"]
                if quest["quest_id"] == qid][0]
        assert mine["state"] == "COMPLETED"
        assert mine["progress"] == "1/1"

        snap = test_client.get("/api/v1/play/status").json()
        assert snap["tasks"]["counts"]["completed"] == 1
        mine2 = [item for item in snap["missions"]["items"]
                 if item["id"] == mid]
        assert mine2 and mine2[0]["status"] == "completed"


def test_liveness_honest_when_everything_offline(tmp_path, monkeypatch):
    """Closed loopback ports + no Hermes key: nothing may report
    green, and process availability is never confused with model
    availability."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("HERMES_API_KEY", raising=False)
    for test_client in api(tmp_path, monkeypatch):
        live = test_client.get("/api/v1/play/status").json()["liveness"]
        assert set(("ollama", "inventory", "hermes",
                    "nodes")) <= set(live)
        assert live["ollama"]["state"].startswith("UNAVAILABLE"), live
        assert "model" in live["ollama"]
        assert live["inventory"]["state"] == "UNAVAILABLE", live
        assert live["hermes"]["state"] == "KEY-MISSING", live
        # The env var NAME may appear as a setup hint; key MATERIAL
        # must never appear as a field.
        assert "api_key" not in [str(key).lower()
                                 for key in live["hermes"]], live
        assert live["hermes"]["detail"].startswith(
            "zet HERMES_API_KEY"), live
        assert live["nodes"]["live"] == 0
        assert live["nodes"]["total"] == 0


class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/api/tags":
            payload = {"models": [{"name": "qwen3.5:4b"}]}
        elif self.path == "/api/v1/health":
            payload = {"status": "ok"}
        else:
            self.send_response(404)
            self.end_headers()
            return
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def test_liveness_real_probes_against_stub(tmp_path, monkeypatch):
    """A stub dependency answering the real probe endpoints over a
    real loopback round-trip must read REAL/OK; a reachable process
    without the configured model must read PROCES-ONLY."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("OLLAMA_BASE_URL",
                           f"http://127.0.0.1:{port}")
        monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:4b")
        monkeypatch.setenv("INVENTORY_BASE_URL",
                           f"http://127.0.0.1:{port}")
        for test_client in api(tmp_path, monkeypatch):
            live = test_client.get(
                "/api/v1/play/status").json()["liveness"]
            assert live["ollama"]["state"].startswith("REAL"), live
            assert live["inventory"]["state"] == "OK", live

        monkeypatch.setenv("OLLAMA_MODEL", "qwen3-missing:99b")
        for test_client in api(tmp_path, monkeypatch):
            live = test_client.get(
                "/api/v1/play/status").json()["liveness"]
            assert live["ollama"]["state"].startswith(
                "PROCES-ONLY"), live
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_side_journal_drive_markers(tmp_path, monkeypatch):
    """Drive controls + readiness render in /side (static markers;
    behavior is covered by the API tests above)."""
    for test_client in api(tmp_path, monkeypatch):
        html = test_client.get("/side").text
        for marker in ("renderJournal", "renderReadiness",
                       "renderDriveButtons", "jdrive",
                       "Gereedheid (live controles)",
                       "data-body", "jtick", "jyes"):
            assert marker in html, marker
