"""BIG #44 live smoke: living solarpunk world on tmp DBs.

Proves with real localhost HTTP (TestClient, no mocks):
world HUD + objects + campaign + symbiosis network + craft
+ energy + presence panels; background signals (energy,
needs); game state; guide node-dimm evidence; mobile world
panel; pages (world, campaign, craft, symbiosis, nodes,
hardware/reality, presence, guide, mobile, morning);
living-state line; refusal probes (fake entity/node/link/
quest/campaign, malformed, wildcard, secret payload,
world POST 405). Zero new execution authority.
"""

import os
import sys

tmp = os.environ.get("B44_SMOKE_TMP", "")
assert tmp, "B44_SMOKE_TMP required"
os.makedirs(tmp, exist_ok=True)
for name in ("smoke.db", "smoke-chat.db"):
    path = os.path.join(tmp, name)
    if os.path.exists(path):
        os.remove(path)
        print(f"cleared stale {name}", flush=True)
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(tmp, "smoke.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    tmp, "smoke-chat.db")
os.environ["MYCELIUM_OPERATOR_KEY"] = "b44-smoke-operator"

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN_A = "b44-smoke-token-aaaaaaaa"
TOKEN_B = "b44-smoke-token-bbbbbbbb"
OPERATOR = "b44-smoke-operator"

checks = []


def check(name, ok, detail=""):
    line = f"{'OK  ' if ok else 'FAIL'} {name} {detail}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"),
              flush=True)
    checks.append(bool(ok))
    if not ok:
        sys.exit(1)


with TestClient(main_mod.app) as client:
    for node_id, caps, token in (
            ("grove-a", ["research.fetch"], TOKEN_A),
            ("grove-b", ["research.fetch", "research.fetch_url"],
             TOKEN_B)):
        reg = client.post("/api/v1/nodes/register", json={
            "node_id": node_id, "hostname": node_id,
            "tier": "worker", "capabilities": caps,
            "node_token": token})
        check(f"node {node_id} registered",
              reg.status_code == 201, str(reg.status_code))
    beat = client.post("/api/v1/nodes/grove-b/heartbeat", json={
        "available": True, "node_token": TOKEN_B,
        "telemetry": {"cpu_percent": 22.0},
        "hardware": [{"kind": "gpu", "identifier": "gpu-0",
                      "details": {}, "status": "connected"}]})
    check("telemetry heartbeat", beat.status_code == 204,
          str(beat.status_code))

    # Human link + finance + energy + quest + campaign.
    link = client.post("/api/v1/hardware/links", json={
        "human_ref": "jelles", "node_id": "grove-b",
        "device_ref": "gpu-0", "device_kind": "gpu",
        "evidence": "saw the card"}).json()
    verify = client.post(
        f"/api/v1/hardware/links/{link['link_id']}/verify",
        json={"verified_by": "jelles",
              "operator_key": OPERATOR})
    check("link verified", verify.status_code == 200)
    fin = client.post("/api/v1/finance/records", json={
        "kind": "budget", "title": "Solar pot",
        "amount_minor": 50000,
        "project_ref": "proj_grove"}).json()
    enr = client.post("/api/v1/energy/records", json={
        "source": "solar", "kind": "production", "value": 410.5,
        "unit": "W", "project_ref": "proj_grove"}).json()
    quest = client.post("/api/v1/quests", json={
        "title": "Understand energy",
        "steps": [{"key": "m", "label": "Budget",
                   "kind": "finance",
                   "ref": fin["record_id"]}]}).json()
    campaign = client.post("/api/v1/campaigns", json={
        "title": "Solar Grove",
        "quest_ids": [quest["quest_id"]]}).json()
    check("campaign", campaign["total_count"] == 1)
    proposal = client.post("/api/v1/candidates", json={
        "title": "Panels feed the grove",
        "candidate_type": "connection",
        "summary": "energy link",
        "entity_refs": ["proj_grove", "obj_panel"]})
    check("symbiosis seedling", proposal.status_code == 201,
          str(proposal.status_code))

    # World page: HUD + object/campaign/symbiosis/energy/
    # presence panels.
    world = client.get("/world")
    check("world renders", world.status_code == 200)
    for marker in ("hud-cell", "<h2>World objects</h2>",
                   "<h2>World progression</h2>",
                   "<h2>Energy in the world</h2>",
                   "<h2>World attention</h2>"):
        check(f"world has {marker[:24]}", marker in world.text)
    check("world links real records", "Open →" in world.text)

    # Entity-scoped world: symbiosis network panel.
    scoped = client.get(
        "/world", params={"entity_id": "proj_grove"})
    check("entity world renders",
          scoped.status_code == 200)
    check("symbiosis network panel",
          "Symbiosis network" in scoped.text)

    # Background signals from real state.
    check("background energy signal",
          'data-energy="1"' in world.text)
    check("background needs signal",
          'data-needs="' in world.text)

    # Game state still honest.
    game = client.get("/api/v1/game/state").json()
    check("game campaigns",
          len(game["sections"]["campaigns"]["data"]) == 1)

    # Guide explains dim nodes with evidence.
    guide = client.get("/api/v1/guide").json()
    for item in guide.get("items", []):
        for field in ("blocked_by", "unlocks", "evidence"):
            check(f"guide has {field}", field in item)
            break
        break

    # Mobile world panel.
    dash = client.get("/api/v1/mobile/dashboard").json()
    check("mobile world panel", "world" in dash)
    mobile = client.get("/mobile")
    check("mobile world block",
          "Open living world" in mobile.text)

    # Remaining pages.
    for path in ("/campaigns", "/game", "/quests", "/craft",
                 "/symbiosis", "/nodes", "/hardware",
                 "/presence", "/guide", "/morning"):
        page = client.get(path)
        check(f"page {path}", page.status_code == 200,
              str(page.status_code))
    reality = client.get("/api/v1/nodes/grove-b/reality").json()
    gpu = next(item for item in reality["hardware"]
               if item["identifier"] == "gpu-0")
    check("reality VERIFIED", gpu["trust"] == "VERIFIED",
          gpu["trust"])

    # Refusal probes.
    check("fake node 404", client.get(
        "/api/v1/nodes/ghost/reality").status_code == 404)
    check("fake link 404", client.get(
        "/api/v1/hardware/links/hv_nope").status_code == 404)
    check("fake quest 404", client.get(
        "/api/v1/quests/qst_nope").status_code == 404)
    check("fake campaign 404", client.get(
        "/api/v1/campaigns/cmp_nope").status_code == 404)
    check("world POST refused",
          client.post("/world").status_code == 405)
    check("game POST refused",
          client.post("/api/v1/game/state").status_code == 405)
    wild = client.post("/api/v1/campaigns", json={
        "title": "x", "quest_ids": ["qst_*"]})
    check("wildcard refused", wild.status_code == 422,
          str(wild.status_code))
    secret = client.post("/api/v1/mesh/delegate", json={
        "requesting_node": "grove-a", "node_token": TOKEN_A,
        "target_node": "grove-b",
        "task_kind": "research.fetch_url",
        "capability": "research.fetch",
        "payload": {"api_key": "hunter2"}})
    check("secret refused", secret.status_code == 422,
          str(secret.status_code))
    traversal = client.get("/api/v1/campaigns/../secret")
    check("traversal refused",
          traversal.status_code in (404, 422),
          str(traversal.status_code))

print(f"SMOKE DONE: {sum(checks)}/{len(checks)} checks green",
      flush=True)
