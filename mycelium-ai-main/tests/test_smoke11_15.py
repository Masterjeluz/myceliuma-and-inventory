"""SMOKE11_15: integrated BIG #11-15 walkthrough (41 steps).

Both apps run as TestClients on tmp DBs: INVENTory (real app,
real HTTP boundary on the coordinator side is unavailable in
this process, so world reads go straight to the INVENTory
client) and the coordinator. Every step asserts; the first
failure names its step.
"""

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "inventory"))

import coordinator.app.main as main_mod


@pytest.fixture()
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "smoke.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "smoke-chat.db"))
    monkeypatch.setenv("INVENTORY_DATABASE_PATH",
                       str(tmp_path / "smoke-inv.db"))
    import importlib
    import app.database as inv_db
    import app.main as inv_main
    importlib.reload(inv_db)
    importlib.reload(inv_main)
    with TestClient(inv_main.app) as inv:
        with TestClient(main_mod.app) as coord:
            yield inv, coord


def test_smoke11_15_integrated(clients, monkeypatch):
    inv, c = clients
    monkeypatch.setenv("MYCELIUM_GIT_WRITE_REPOS", str(ROOT))
    step = {"n": 0}

    def check(name, cond):
        step["n"] += 1
        assert cond, f"SMOKE11_15 step {step['n']} FAILED: {name}"

    # 1-2. Both apps start and answer.
    check("inventory starts", inv.get(
        "/api/v1/health").status_code == 200)
    check("coordinator starts", c.get(
        "/api/v1/health").status_code == 200)
    # 3. Register nodes.
    for node_id in ("smoke-seed", "smoke-worker"):
        response = c.post("/api/v1/nodes/register", json={
            "node_id": node_id, "hostname": "h",
            "capabilities": ["exec:system_inventory"],
            "coordinator_capable": True})
        check(f"register {node_id}", response.status_code == 201)
    # 4. Load world: object round-trip in INVENTory.
    obj = inv.post("/api/v1/objects",
                   json={"name": "Smoke bracket"}).json()
    check("world object", obj["id"].startswith("obj_"))
    # 5. Create project in INVENTory.
    proj = inv.post("/api/v1/projects",
                    json={"name": "Smoke arm",
                          "status": "planned"}).json()
    check("project created", proj["id"].startswith("proj_"))
    # 6. Create memory in Mycelium.
    mem = c.post("/api/v1/memory", json={
        "memory_type": "project", "title": "Smoke arm goal",
        "content": "3D printed robotic arm",
        "truth": "user_fact", "project_ref": proj["id"],
        "provenance": {"source_type": "user-created",
                       "creator_id": "smoke",
                       "human_verified": True,
                       "verified_by": "smoke"}}).json()
    check("memory created", mem["memory_id"].startswith("mem_"))
    # 7. Watcher detects an unfinished (stale) task.
    task = c.post("/api/v1/tasks", json={
        "kind": "system_inventory",
        "required_capabilities": [
            "exec:system_inventory"]}).json()
    from coordinator.app.database import connection
    with connection() as db:
        db.execute("UPDATE tasks SET created_at=?, status="
                   "'queued' WHERE id=?",
                   ("2020-01-01T00:00:00+00:00", task["id"]))
    findings = c.get("/api/v1/watcher/scan").json()["findings"]
    check("watcher finds stale task",
          any(item["kind"] == "stale_task"
              for item in findings))
    # 8-9. Research task → stored result with cited claim.
    research_task = c.post("/api/v1/tasks", json={
        "kind": "research",
        "required_capabilities": []}).json()
    check("research task", research_task["status"] == "queued")
    source = c.post("/api/v1/research/sources", json={
        "source_type": "web", "title": "PLA temps",
        "content": "PLA prints around 200C."}).json()
    c.post(f"/api/v1/research/sources/{source['source_id']}"
           "/advance", json={"to_stage": "proposed"})
    c.post(f"/api/v1/research/sources/{source['source_id']}"
           "/advance", json={"to_stage": "approved",
                             "approved_by": "smoke"})
    record = c.post("/api/v1/research/records", json={
        "question": "PLA temp?",
        "claims": [{"claim": "around 200C",
                    "source_ids": [source["source_id"]],
                    "evidence": "source states 200C"}],
        "synthesis": "Start at 200C per one source."}).json()
    check("research stored",
          record["record_id"].startswith("rsch_"))
    # 10-11. Skill candidate → accepted skill on the project.
    discovered = c.post("/api/v1/skills/discover", json={
        "project_text": "3D printed robotic arm with CAD",
        "project_ref": proj["id"]}).json()
    check("skill candidate",
          len(discovered["candidates"]) >= 1)
    skill = c.post(
        f"/api/v1/skills/candidates/"
        f"{discovered['candidates'][0]['candidate_id']}/accept",
        json={"accepted_by": "smoke"}).json()
    check("skill on project",
          proj["id"] in skill["project_refs"])
    # 12. Health data through the mock wearable path.
    imported = c.post("/api/v1/integrations/garmin/import",
                      json={"provider": "mock",
                            "limit": 6}).json()
    check("health imported", imported["imported"] == 6)
    # 13-14. Meal → daily totals.
    food = c.post("/api/v1/nutrition/foods", json={
        "name": "Havermout",
        "nutrients": {"calories": 389, "protein_g": 13},
        "vegan_status": "vegan",
        "vegan_evidence": "ingredients: oats"}).json()
    meal = c.post("/api/v1/nutrition/meals", json={
        "name": "Ontbijt",
        "items": [{"name": "Havermout",
                   "food_id": food["food_id"],
                   "portion_g": 80,
                   "nutrients": food["nutrients"],
                   "vegan_status": "vegan"}],
        "observed_at": "2026-09-16T08:00:00+00:00"}).json()
    check("meal created", meal["meal_id"].startswith("meal_"))
    daily = c.get("/api/v1/nutrition/daily",
                  params={"day": "2026-09-16"}).json()
    check("totals calculated",
          daily["totals"]["meals"] == 1
          and daily["totals"]["totals"]["calories"] > 0)
    # 15. Morning report generates.
    report = c.get("/api/v1/reports/morning").json()
    check("morning report",
          len(report["sections"]) >= 5)
    # 16. Living Workshop opens.
    check("workshop opens",
          c.get("/workshop").status_code == 200)
    # 17. Select a 3D object (generate test cube).
    generated = c.post("/api/v1/fab/generate", json={
        "generator": "procedural-test",
        "description": "smoke cube", "params": {}}).json()
    mesh_ref = generated["fabrication"]["mesh_ref"]
    check("3D object", mesh_ref.endswith(".stl"))
    # 18-20. Transform proposal → approval → derived mesh.
    proposal = c.post("/api/v1/fab/prompt-edit", json={
        "artifact_ref": mesh_ref,
        "text": "maak deze bracket 5mm langer"}).json()
    check("transform proposal",
          proposal["op"] == "extend"
          and proposal["executed"] is False)
    done = c.post("/api/v1/fab/prompt-edit", json={
        "artifact_ref": mesh_ref,
        "text": "maak deze bracket 5mm langer",
        "persist": True, "approved_by": "smoke"}).json()
    check("derived mesh",
          done["executed"] is True
          and done["validation"]["verdict"] == "valid")
    derived_ref = done["derived_ref"]
    # 21-22. Slice proposal + printer selection.
    c.post("/api/v1/printers/register", json={
        "printer_id": "prt-smoke", "name": "Smoke printer",
        "capabilities": ["printer.status", "printer.start"]})
    sliced = c.post("/api/v1/fab/slice", json={
        "artifact_ref": derived_ref, "profile": "draft-pla",
        "printer_id": "prt-smoke",
        "slicer": "test-slicer"}).json()
    check("slice proposal",
          sliced["slice"]["gcode_ref"].endswith(".gcode"))
    pick = c.post("/api/v1/fab/select-printer", json={
        "capabilities": ["printer.start"]}).json()
    check("printer selected",
          pick["printer_id"] == "prt-smoke")
    # 23. Physical execution remains gated.
    proposed = c.post("/api/v1/prints/propose", json={
        "printer_id": "prt-smoke",
        "gcode_ref": sliced["slice"]["gcode_ref"],
        "gcode_sha256": sliced["slice"]["sha256"],
        "profile": "draft-pla", "actor": "smoke"})
    if proposed.status_code == 201:
        check("print stays proposed",
              proposed.json()["status"] == "proposed")
    else:
        check("print refused safe",
              proposed.status_code == 422)
    # 24-25. Robot + familiar registered, capability visible.
    robot = c.post("/api/v1/robots", json={
        "name": "Smoke arm", "robot_type": "robotic_arm",
        "capabilities": ["robot.move", "robot.observe",
                         "robot.status"]}).json()
    check("robot registered",
          robot["robot_id"].startswith("rbt_"))
    familiar = c.post("/api/v1/familiars", json={
        "name": "Smoke arm familiar", "kind": "robot",
        "linked_id": robot["robot_id"]}).json()
    check("familiar registered",
          familiar["familiar_id"].startswith("fam_"))
    robots = c.get("/api/v1/robots").json()
    check("capability visible",
          any("robot.move" in item["capabilities"]
              for item in robots))
    # 26. Robot physical action remains gated.
    denied = c.post(
        f"/api/v1/robots/{robot['robot_id']}/propose",
        json={"action": "robot.grab"})
    check("robot capability enforced",
          denied.status_code == 422)
    move = c.post(
        f"/api/v1/robots/{robot['robot_id']}/propose",
        json={"action": "robot.move"}).json()
    check("robot approval gated",
          c.post(f"/api/v1/robots/{robot['robot_id']}/approve",
                 json={**move,
                       "approved_by": ""}).status_code == 422)
    # 27-28. Live opens with bounded context.
    session = c.post("/api/v1/live/sessions", json={
        "interface": "web", "actor": "smoke",
        "capabilities": ["project.read", "task.read",
                         "node.read", "memory.read",
                         "health.read", "research.read",
                         "skills.read", "workshop.read"],
        "context_scope": {"include_health": True}}).json()
    check("live opens",
          session["session_id"].startswith("live-"))
    package = c.post("/api/v1/live/context", json={
        "session_id": session["session_id"],
        "query": "arm", "budget": 8000}).json()
    check("bounded context",
          package["used"] <= 8000 and "tasks" in
          package["sections"])
    sections = package["sections"]
    # 29-34. Live inspects each domain.
    check("live project", "project" in sections)
    check("live memory", "memory" in sections)
    check("live health", "health" in sections)
    check("live research", "research" in sections)
    check("live skills", "skills" in sections)
    check("live workshop", "workshop" in sections)
    # 35-36. Live reads git; diff capability is grantable.
    git_session = c.post("/api/v1/live/sessions", json={
        "interface": "web", "actor": "smoke",
        "capabilities": ["git.read", "git.diff"],
        "context_scope": {"include_git": True}}).json()
    git_package = c.post("/api/v1/live/context", json={
        "session_id": git_session["session_id"]}).json()
    check("live git", "git" in git_package["sections"])
    # 37. git.commit works only through approval.
    commit_session = c.post("/api/v1/live/sessions", json={
        "interface": "web", "actor": "smoke",
        "capabilities": ["git.commit"]}).json()
    commit = c.post("/api/v1/live/propose", json={
        "session_id": commit_session["session_id"],
        "kind": "git_commit", "target": "repo",
        "payload": {"repository": str(ROOT),
                    "branch": "smoke-branch",
                    "expected_head": "0" * 40,
                    "message": "smoke proposal, never executed",
                    "files": ["mycelium-ai-main/README.md"],
                    "changeset_fingerprint": "ab" * 32}})
    check("commit via approval",
          commit.status_code == 201
          and commit.json()["status"] == "proposed")
    # 38. git.push remains separately gated.
    check("push never granted",
          c.post("/api/v1/live/sessions", json={
              "interface": "web", "actor": "smoke",
              "capabilities": ["git.push"]}).status_code == 422)
    check("push kind unavailable",
          c.post("/api/v1/live/propose", json={
              "session_id": commit_session["session_id"],
              "kind": "push", "target": "main",
              "payload": {}}).status_code == 422)
    # 39. Event log holds the chain (sync log + provenance).
    changes = c.get("/api/v1/sync/changes",
                    params={"after": 0, "limit": 5}).json()
    check("event chain", "latest" in changes)
    # 40. Sync round-trip stays functional.
    applied = c.post("/api/v1/sync/apply", json={"items": [{
        "event_id": "dsevt_smoke1115",
        "origin_node_id": "smoke-seed",
        "entity_id": obj["id"], "entity_type": "object",
        "entity_revision": "rev-1", "base_revision": "",
        "event_type": "entity.observed", "timestamp": "",
        "payload": {"note": "smoke"}, "provenance": {},
        "epoch": 0}]}).json()
    check("sync works", applied["applied"] == 1)
    # 41. Failover stays functional.
    campaign = c.post("/api/v1/coordinator/campaign",
                      json={"node_id": "smoke-seed"}).json()
    check("failover works", campaign["epoch"] == 1)
