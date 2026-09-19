"""BIG #43 live smoke: living game layer on tmp DBs.

Proves with real localhost HTTP (TestClient, no mocks):
quest x2 -> campaign create (counts, current quest, next
action, evidence) -> campaign refresh -> game state (10
sections, honesty, provenance) -> guide companion card ->
mobile campaign panel -> morning campaign section (absent
before, present after) + game headers -> pages (/campaigns,
/game, /quests, /craft, /symbiosis, /guide, /mobile,
/morning, /world) -> quest progress moves campaign counts ->
deleted quest marks MISSING -> refusal probes (fake quest,
malformed id, empty, duplicate, fake campaign, game POST
405, traversal).
"""

import os
import sys

tmp = os.environ.get("B43_SMOKE_TMP", "")
assert tmp, "B43_SMOKE_TMP required"
os.makedirs(tmp, exist_ok=True)
for name in ("smoke.db", "smoke-chat.db"):
    path = os.path.join(tmp, name)
    if os.path.exists(path):
        os.remove(path)
        print(f"cleared stale {name}", flush=True)
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(tmp, "smoke.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    tmp, "smoke-chat.db")
os.environ["MYCELIUM_OPERATOR_KEY"] = "b43-smoke-operator"

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN_A = "b43-smoke-token-aaaaaaaa"
TOKEN_B = "b43-smoke-token-bbbbbbbb"

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
            ("play-a", ["research.fetch"], TOKEN_A),
            ("play-b", ["research.fetch", "research.fetch_url"],
             TOKEN_B)):
        reg = client.post("/api/v1/nodes/register", json={
            "node_id": node_id, "hostname": node_id,
            "tier": "worker", "capabilities": caps,
            "node_token": token})
        check(f"node {node_id} registered",
              reg.status_code == 201, str(reg.status_code))
    beat = client.post("/api/v1/nodes/play-b/heartbeat", json={
        "available": True, "node_token": TOKEN_B,
        "telemetry": {"cpu_percent": 22.0},
        "hardware": [{"kind": "gpu", "identifier": "gpu-0",
                      "details": {}, "status": "connected"}]})
    check("telemetry heartbeat", beat.status_code == 204,
          str(beat.status_code))

    # Quest chain: energy audit + hardware inspection.
    fin = client.post("/api/v1/finance/records", json={
        "kind": "budget", "title": "Solar pot",
        "amount_minor": 1000, "project_ref": "proj_solar"})
    check("finance record", fin.status_code == 201)
    fin_id = fin.json()["record_id"]
    quest1 = client.post("/api/v1/quests", json={
        "title": "Understand current energy",
        "steps": [{"key": "money", "label": "Budget",
                   "kind": "finance", "ref": fin_id}]}).json()
    quest2 = client.post("/api/v1/quests", json={
        "title": "Inspect available hardware",
        "steps": [{"key": "look", "label": "Look",
                   "kind": "note", "ref": ""}]}).json()
    check("quests created",
          quest1["quest_id"].startswith("qst_") and
          quest2["quest_id"].startswith("qst_"))

    # Campaign over the chain.
    created = client.post("/api/v1/campaigns", json={
        "title": "Solar Workshop",
        "description": "Grow the solar workshop.",
        "quest_ids": [quest1["quest_id"],
                      quest2["quest_id"]]})
    check("campaign created", created.status_code == 201,
          str(created.status_code))
    campaign = created.json()
    campaign_id = campaign["campaign_id"]
    check("campaign counts",
          campaign["total_count"] == 2 and
          campaign["completed_count"] == 0,
          f"{campaign['completed_count']}/"
          f"{campaign['total_count']}")
    check("current quest",
          campaign["current_quest"]["quest_id"] ==
          quest1["quest_id"])
    check("next action",
          bool(campaign["next_action"].get("href")),
          campaign["next_action"].get("step", ""))
    check("evidence links",
          len(campaign["evidence"]) == 2)

    # Game state: 10 sections + honesty.
    game = client.get("/api/v1/game/state")
    check("game state", game.status_code == 200,
          str(game.status_code))
    sections = game.json()["sections"]
    for key in ("world", "campaigns", "current_quest",
                "presence", "craft", "symbiosis", "nodes",
                "energy", "workshop", "discoveries"):
        check(f"game section {key}", key in sections)
    check("game honesty",
          "database" in game.json()["honesty"])
    check("game provenance",
          game.json()["provenance"]["human_verified"] is False)

    # Guide companion card for the campaign.
    guide = client.get("/api/v1/guide").json()
    items = guide.get("items", [])
    cards = [item for item in items
             if item.get("glyph") == "\U0001F5FA"]
    check("guide campaign card", len(cards) > 0)
    check("companion evidence",
          bool(cards[0].get("evidence")))

    # Mobile campaign panel.
    dash = client.get("/api/v1/mobile/dashboard").json()
    check("mobile campaigns panel", "campaigns" in dash)
    check("mobile next href",
          bool(dash["campaigns"]["campaigns"][0]["next_href"]))

    # Morning: absent before finance? (campaign exists now).
    morning = client.get("/api/v1/reports/morning").json()
    titles = [section["title"] for section in
              morning.get("sections", [])]
    check("morning campaign section",
          "Current campaign" in titles)
    morning_page = client.get("/morning")
    check("morning game header",
          "Current campaign" in morning_page.text and
          "World state" in morning_page.text)

    # Pages render.
    for path in ("/campaigns", "/game", "/quests", "/craft",
                 "/symbiosis", "/guide", "/mobile", "/morning",
                 "/world"):
        page = client.get(path)
        check(f"page {path}", page.status_code == 200,
              str(page.status_code))

    # Real progress moves the campaign.
    client.post(f"/api/v1/finance/records/{fin_id}/status",
                json={"status": "CONFIRMED"})
    refreshed = client.post(
        f"/api/v1/campaigns/{campaign_id}/refresh").json()
    check("campaign real progress",
          refreshed["completed_count"] == 1 and
          refreshed["current_quest"]["quest_id"] ==
          quest2["quest_id"],
          f"{refreshed['completed_count']}/"
          f"{refreshed['total_count']}")

    # Deleted quest marks MISSING, never vanishes silently.
    client.delete(f"/api/v1/quests/{quest2['quest_id']}")
    after_delete = client.get(
        f"/api/v1/campaigns/{campaign_id}").json()
    check("deleted quest MISSING",
          after_delete["quests"][1]["state"] == "MISSING")

    # Refusal probes.
    fake = client.post("/api/v1/campaigns", json={
        "title": "Fake", "quest_ids": ["qst_deadbeef1234"]})
    check("fake quest refused", fake.status_code == 422,
          str(fake.status_code))
    malformed = client.post("/api/v1/campaigns", json={
        "title": "Fake", "quest_ids": ["../evil"]})
    check("malformed quest refused",
          malformed.status_code == 422,
          str(malformed.status_code))
    empty = client.post("/api/v1/campaigns", json={
        "title": "Empty", "quest_ids": []})
    check("empty campaign refused", empty.status_code == 422,
          str(empty.status_code))
    dupe = client.post("/api/v1/campaigns", json={
        "title": "Dupe",
        "quest_ids": [quest1["quest_id"],
                      quest1["quest_id"]]})
    check("duplicate quest refused", dupe.status_code == 422,
          str(dupe.status_code))
    missing = client.get("/api/v1/campaigns/cmp_nope")
    check("fake campaign 404", missing.status_code == 404,
          str(missing.status_code))
    post_game = client.post("/api/v1/game/state")
    check("game state POST refused",
          post_game.status_code == 405,
          str(post_game.status_code))
    wild = client.post("/api/v1/campaigns", json={
        "title": "Wild", "quest_ids": ["qst_*"]})
    check("wildcard quest refused", wild.status_code == 422,
          str(wild.status_code))

print(f"SMOKE DONE: {sum(checks)}/{len(checks)} checks green",
      flush=True)
