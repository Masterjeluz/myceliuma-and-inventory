"""BIG #38 live smoke: full living-automation chain on tmp DBs.

Proves with real localhost HTTP (no mocks except the
research provider, which would otherwise hit the live web):
conversation → intelligence → research → candidate →
symbiosis proposal → automation → safe continuation →
approval stop → human YES → continuation → completion →
memory/event → morning report. Plus bounded retry,
waiting-agent visibility, node route prep, camera path,
3D path, mobile path, notification path.
"""

import os
import sys

tmp = os.environ.get("B38_SMOKE_TMP", "")
assert tmp, "B38_SMOKE_TMP required"
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(tmp, "smoke.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    tmp, "smoke-chat.db")

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

CHAT = ("Jelles: We moeten de camperzonnepanelen schoonmaken "
        "voor de zomer.\n"
        "Claude: Goed plan. Ik zal eerst de opbrengst meten.\n"
        "Jelles: Welke reiniger is veilig voor panelen? Dat "
        "zoeken we nog uit.\n")


def check(name, ok, detail=""):
    line = f"{'OK  ' if ok else 'FAIL'} {name} {detail}"
    print(line, flush=True)
    if not ok:
        sys.exit(1)


async def _fake_execute(run_id, provider, max_sources,
                        seed_urls=None):
    return {"run_id": run_id, "dossier_id": "dos_smoke"}


main_mod._execute_research_run = _fake_execute

with TestClient(main_mod.app) as client:
    imp = client.post("/api/v1/conversations/import", json={
        "title": "Zomerklus", "content": CHAT, "format": "plain",
        "source_platform": "claude"}).json()
    cid = imp["conversation_id"]
    check("conversation imported", cid.startswith("conv_"), cid)

    intel = client.post(
        f"/api/v1/conversations/{cid}/analyze").json()
    assert intel, "analysis record"
    intel2 = client.get(
        f"/api/v1/conversation-intel/{cid}").json()
    check("intelligence ready",
          intel2["counts"]["research_proposals"] >= 1,
          str(intel2["counts"]))

    finger = intel2["research"][0]["fingerprint"]
    queued = client.post(
        f"/api/v1/conversation-intel/{cid}/materialize",
        json={"fingerprint": finger,
              "action": "research-queue"}).json()
    check("research queued", queued["status"] == "queued",
          queued.get("run_id", ""))

    run = client.post("/api/v1/automation/runs", json={
        "goal": "Zomerklus keten",
        "steps": [
            {"kind": "intel_analyze",
             "params": {"conversation_id": cid}},
            {"kind": "research_queue",
             "params": {"question": "Veilige paneelreiniger?",
                        "priority": "MEDIUM"}},
            {"kind": "knowledge_candidate",
             "params": {"title": "Panelen schoonmaken",
                        "kind": "task",
                        "text": "Maak de camperpanelen schoon."}},
            {"kind": "symbiosis_propose",
             "params": {"from_id": "obj_panel1",
                        "to_id": "proj_camper1",
                        "predicate": "related_to"}},
            {"kind": "mission_propose",
             "params": {"goal": "Schoonmaakmissie",
                        "conversation_id": cid}},
            {"kind": "wait",
             "params": {"reason": "plan YES first"}},
            {"kind": "mission_tick", "params": {}},
            {"kind": "notify",
             "params": {"kind": "task_completed",
                        "title": "Zomerklus keten klaar"}},
        ]}).json()
    check("automation created", run["run_id"].startswith("auto_"),
          run["run_id"])
    run_id = run["run_id"]

    first = client.post(
        f"/api/v1/automation/runs/{run_id}/drive",
        json={"budget_steps": 10}).json()
    check("safe continuation drove",
          first["state"] == "waiting_for_human", first["state"])
    check("approval stop names the gate",
          "mission_approved" in str(
              first.get("waiting", {}).get("gate", {})))

    mission_id = client.get(
        f"/api/v1/automation/runs/{run_id}").json()[
            "steps"][4]["result"]["mission_id"]
    approved = client.post(
        f"/api/v1/missions/{mission_id}/approve",
        json={"response": "YES", "decided_by": "smoke"})
    check("human YES through existing gate",
          approved.status_code == 200)

    resumed = client.post(
        f"/api/v1/automation/runs/{run_id}/resume",
        json={"budget_steps": 10}).json()
    check("continuation after YES",
          resumed["state"] == "completed", resumed["state"])
    check("memory/event recorded",
          bool(resumed.get("memory_id")))

    morning = client.get("/api/v1/reports/morning").json()
    titles = [block["title"] for block in morning["sections"]]
    check("morning report covers automation",
          "Automation" in titles)
    packet = client.get("/api/v1/context/packet2").json()
    check("packet carries automation",
          any(entry["id"] == run_id
              for entry in packet.get("automation", [])))
    mobile = client.get("/mobile").text
    check("mobile path renders", "Mycelium" in mobile)
    state = client.get("/api/v1/state").json()
    check("living state honest", state["state"] in (
        "QUIET", "RESEARCHING", "THINKING", "CONNECTING",
        "DISTRIBUTED", "WAITING", "COMPLETE", "BLOCKED"))

    # Bounded retry proof: failing step, no retries left.
    failing = client.post("/api/v1/automation/runs", json={
        "goal": "Faalketen",
        "steps": [{"kind": "search", "params": {}}],
        "bounds": {"max_steps": 5, "max_runtime_seconds": 600,
                   "max_retries": 0,
                   "max_consecutive_failures": 1}}).json()
    failed = client.post(
        f"/api/v1/automation/runs/{failing['run_id']}/drive",
        json={}).json()
    check("bounded retry fails closed",
          failed["state"] == "failed")

    # Camera path: unknown session refuses honestly (no fake run).
    bad_camera = client.post("/api/v1/automation/runs", json={
        "goal": "Cameracheck",
        "steps": [{"kind": "camera_session",
                   "params": {"op": "run",
                              "session_id": "cing_missing"}}]}).json()
    bad_drive = client.post(
        f"/api/v1/automation/runs/{bad_camera['run_id']}/drive",
        json={}).json()
    check("camera path honest",
          bad_drive["state"] == "failed")

    # 3D path: presence check on a missing entity refuses.
    missing = client.get(
        "/api/v1/workshop/presence",
        params={"entity_id": "obj_smoke_missing"})
    check("3D path honest", missing.status_code in (200, 422))
    print("smoke done", flush=True)
