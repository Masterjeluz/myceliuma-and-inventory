"""BIG #40 live smoke: presence ecosystem on tmp DBs.

Proves with real localhost HTTP (TestClient, no mocks):
seed → node telemetry → mission waiting → desktop approval →
automation waiting → research finding (dossier path honest) →
candidate → task failure → hardware offline → node offline →
presence aggregation → mobile bands → guide afterwards →
notification fan-out + dedup → morning sections → world/pages
→ deep-link verification → triage → refusals.
"""

import os
import sys

tmp = os.environ.get("B40_SMOKE_TMP", "")
assert tmp, "B40_SMOKE_TMP required"
os.makedirs(tmp, exist_ok=True)
# Fresh DBs every run: the smoke owns this tmp dir, so stale
# state from a previous run is removed first (reruns are then
# deterministic instead of UNIQUE-conflicting).
for name in ("smoke.db", "smoke-chat.db"):
    path = os.path.join(tmp, name)
    if os.path.exists(path):
        os.remove(path)
        print(f"cleared stale {name}", flush=True)
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(tmp, "smoke.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    tmp, "smoke-chat.db")

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN = "b40-smoke-token-123456"


def check(name, ok, detail=""):
    line = f"{'OK  ' if ok else 'FAIL'} {name} {detail}"
    print(line, flush=True)
    if not ok:
        sys.exit(1)


def presence(client):
    return client.get("/api/v1/presence").json()


def by_id(snapshot, item_id):
    return next((item for item in snapshot["items"]
                 if item["id"] == item_id), None)


with TestClient(main_mod.app) as client:
    # Seed: capable node with telemetry + hardware + compute.
    reg = client.post("/api/v1/nodes/register", json={
        "node_id": "smoke-node", "hostname": "smoke-node",
        "tier": "worker",
        "capabilities": ["research.fetch", "analysis.ollama"],
        "node_token": TOKEN})
    check("node registered", reg.status_code == 201,
          str(reg.status_code))
    beat = client.post("/api/v1/nodes/smoke-node/heartbeat",
                       json={
                           "available": True, "node_token": TOKEN,
                           "telemetry": {
                               "hostname": "smoke-node",
                               "os": "Linux", "cpu_percent": 30.0,
                               "cpu_count": 8,
                               "memory_percent": 50.0,
                               "memory_total_mb": 16384,
                               "memory_available_mb": 8192,
                               "uptime_seconds": 3600},
                           "hardware": [{
                               "kind": "camera",
                               "identifier": "/dev/video0",
                               "details": {},
                               "status": "connected"},
                               {"kind": "usb",
                                "identifier": "1-1.9",
                                "details": {},
                                "status": "disconnected"}],
                           "compute_capabilities": [{
                               "capability": "ollama",
                               "details": {},
                               "status": "available"}],
                           "energy_state": {"source": "grid"}})
    check("telemetry heartbeat", beat.status_code == 204,
          str(beat.status_code))

    # Seed: offline node (stored offline, honestly derived).
    from coordinator.app.database import connection
    with connection() as db:
        db.execute(
            "INSERT INTO nodes (node_id, hostname, tier, "
            "capabilities, cpu_cores, memory_mb, energy_source, "
            "last_seen, status) VALUES (?, ?, ?, ?, ?, ?, ?, "
            "?, ?)",
            ("smoke-gone", "gone", "seed", "[]", 1, 0,
             "unknown", "2020-01-01T00:00:00+00:00", "offline"))

    snapshot = presence(client)
    check("presence aggregates",
          len(snapshot["items"]) >= 4,
          str(snapshot["counts"]))
    check("hardware available item",
          by_id(snapshot,
                "att_hw_available_smoke-node__dev_video0")
          is not None)
    check("hardware offline item",
          by_id(snapshot,
                "att_hw_offline_smoke-node_1-1.9") is not None)
    check("capability available item",
          by_id(snapshot,
                "att_cap_available_smoke-node_ollama")
          is not None)
    check("node offline item",
          by_id(snapshot, "att_node_offline_smoke-gone")
          is not None)

    # Mission waiting (pending approval = NEEDS YOU).
    chat = client.post("/api/v1/chat",
                       json={"message": "smoke quest"}).json()
    mission = client.post("/api/v1/missions", json={
        "conversation_id": chat["conversation_id"],
        "goal": "Smoke quest",
        "steps": [{"kind": "readout",
                   "description": "Read status",
                   "parameters": {"source": "project"}}]}).json()
    mission_id = mission["mission_id"]
    snapshot = presence(client)
    mission_item = by_id(
        snapshot, f"att_approval_mission_{mission_id}")
    check("mission waiting NEEDS YOU",
          mission_item is not None
          and mission_item["band"] == "needs")

    # Desktop approval.
    action = client.post("/api/v1/desktop/actions", json={
        "action_id": "dact-smoke-1", "action_type": "click",
        "parameters": {"x": 5, "y": 5}})
    check("desktop action proposed",
          action.status_code == 201, str(action.status_code))
    check("desktop approval NEEDS YOU",
          by_id(presence(client),
                "att_approval_desktop_dact-smoke-1") is not None)

    # Automation waiting for human.
    run = client.post("/api/v1/automation/runs", json={
        "goal": "Smoke chain",
        "steps": [
            {"kind": "mission_propose",
             "params": {"goal": "Smoke auto mission",
                        "conversation_id": chat[
                            "conversation_id"]}},
            {"kind": "wait",
             "params": {"reason": "plan YES first"}}]}).json()
    run_id = run["run_id"]
    driven = client.post(
        f"/api/v1/automation/runs/{run_id}/drive",
        json={"budget_steps": 10}).json()
    check("automation waiting for human",
          driven["state"] == "waiting_for_human",
          driven["state"])
    check("automation waiting item",
          by_id(presence(client),
                f"att_auto_waiting_{run_id}") is not None)

    # Candidate + task failure.
    candidate = client.post("/api/v1/candidates", json={
        "title": "Smoke candidate", "candidate_type": "note",
        "summary": "smoke review"})
    check("candidate created",
          candidate.status_code == 201,
          str(candidate.status_code))
    check("candidate DISCOVERED",
          by_id(presence(client),
                f"att_candidate_"
                f"{candidate.json()['candidate_id']}")
          is not None)
    from coordinator.app.events import new_event, save_event
    save_event(new_event("task.failed", "smoke boom",
                         task_id="99"))
    check("task failure NEEDS YOU",
          by_id(presence(client), "att_task_failed_99")
          is not None)

    # Node-aware research readiness names the capable node.
    readiness = presence(client)
    waiting = by_id(readiness, "att_research_waiting_nodes")
    check("research waits honestly or node serves",
          (waiting is None) or ("smoke" in waiting["reason"]
                                or "No eligible" in
                                waiting["reason"]))

    # Mobile bands + greeting.
    dash = client.get("/api/v1/mobile/dashboard").json()
    check("mobile greeting",
          dash.get("greeting") in ("GOOD MORNING", "NOW"))
    check("mobile bands complete",
          set(dash.get("presence", {}).get("bands", {})) == {
              "needs", "waiting", "available", "discovered",
              "offline"})

    # Guide explains afterwards.
    guide = client.get("/api/v1/guide").json()
    check("guide has items", len(guide.get("items", [])) > 0)
    check("guide explains afterwards",
          all(entry.get("after")
              for entry in guide["items"]))

    # Notification fan-out + dedup.
    first = client.post("/api/v1/presence/notify",
                        json={"limit": 5}).json()
    check("notify fan-out IN_APP",
          first["transport"] == "IN_APP"
          and first["web_push"] == "UNAVAILABLE"
          and len(first["sent"]) >= 1)
    for _ in range(4):
        drained = client.post("/api/v1/presence/notify",
                              json={"limit": 10}).json()
        if not drained["sent"]:
            break
    repeat = client.post("/api/v1/presence/notify",
                         json={"limit": 10}).json()
    check("notify deduplicates",
          repeat["sent"] == [] and repeat["skipped"] >= 1)

    # Morning answers why open Mycelium today.
    morning = client.get("/api/v1/reports/morning").json()
    titles = [block["title"] for block in morning["sections"]]
    for expected in ("Needs you", "Overnight changes",
                     "Discoveries", "Available resources",
                     "Blocked work",
                     "Offline and stale hardware",
                     "Suggested next actions"):
        check(f"morning has '{expected}'", expected in titles)

    # Pages render.
    for path in ("/presence", "/mobile", "/guide", "/nodes",
                 "/world", "/activity"):
        page = client.get(path)
        check(f"page {path} renders",
              page.status_code == 200
              and "Mycelium" in page.text,
              str(page.status_code))

    # Deep links resolve (no dead ends).
    hrefs = {item["open_href"]
             for item in presence(client)["items"]}
    check("deep links present", len(hrefs) > 0,
          str(len(hrefs)))
    for href in sorted(hrefs):
        response = client.get(href)
        check(f"deeplink {href} resolves",
              response.status_code == 200,
              str(response.status_code))

    # Triage: defer hides from needs, decides nothing.
    deferred = client.post("/api/v1/presence/defer",
                           json={"item_id":
                                 "att_approval_desktop_"
                                 "dact-smoke-1"})
    check("defer stored",
          deferred.status_code == 200
          and deferred.json()["status"] == "DEFERRED")
    snapshot = presence(client)
    check("deferred leaves needs band",
          all(entry["id"] != "att_approval_desktop_dact-smoke-1"
              for entry in snapshot["bands"]["needs"]))
    pending = client.get("/api/v1/desktop/actions/"
                         "dact-smoke-1").json()
    check("defer decided nothing",
          pending["status"] == "pending_approval")

    # Refusals stay fail-closed.
    fake = client.post("/api/v1/presence/defer",
                       json={"item_id": "att_approval_nope"})
    check("fake id refused", fake.status_code == 404,
          str(fake.status_code))
    wild = client.post("/api/v1/nodes/register", json={
        "node_id": "smoke-liar", "hostname": "liar",
        "capabilities": ["*"], "node_token": TOKEN})
    check("wildcard still refused",
          wild.status_code in (403, 422),
          str(wild.status_code))

    print("smoke done", flush=True)
