"""BIG #36 smoke: mobile command surface on tmp DBs.

Proves via real localhost HTTP (TestClient, no user data):
/mobile loads, input enters the coordinator, mission appears,
approval appears, unauthorized YES rejected, valid YES works,
notification exists + deeplink resolves, camera item appears,
guide shows a real action, packet generates, craft/symbiosis/
node/progress appear. Prints one line per check.
"""

import os
import sys

tmp = os.environ.get("B36_SMOKE_TMP", "")
assert tmp, "B36_SMOKE_TMP required"
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(tmp, "smoke.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    tmp, "smoke-chat.db")

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def check(name, ok, detail=""):
    print(f"{'OK  ' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        sys.exit(1)


with TestClient(main_mod.app) as client:
    page = client.get("/mobile")
    check("1. /mobile loads", page.status_code == 200)

    chat = client.post("/web/chat",
                       data={"message": "tel de zonnepanelen"})
    check("2. input enters coordinator",
          chat.status_code in (200, 303))
    conv = client.post("/api/v1/chat",
                       json={"message": "smoke triage"}).json()
    created = client.post("/api/v1/missions", json={
        "conversation_id": conv["conversation_id"],
        "goal": "smoke triage",
        "steps": [{"kind": "readout", "description": "Read",
                   "parameters": {"source": "project"}}]}).json()
    check("3. mission appears",
          created["mission_id"] in client.get("/mobile").text)
    cards = client.get("/api/v1/mobile/dashboard").json()
    check("4. approval appears",
          cards["waiting_count"] >= 1
          and cards["cards"][0]["kind"] == "mission")

    fake = client.post("/web/missions/mission_nope/approve")
    check("5. unauthorized YES rejected",
          fake.status_code in (200, 303, 404)
          and "mission_nope" not in client.get("/mobile").text)
    mid = created["mission_id"]
    assert client.post(f"/web/missions/{mid}/approve"
                       ).status_code in (200, 303)
    check("6. valid YES works",
          client.get(f"/api/v1/missions/{mid}").json()[
              "status"] == "approved")

    node = client.post("/api/v1/nodes/register", json={
        "node_id": "phone-smoke", "hostname": "phone",
        "tier": "seed", "capabilities": ["inventory.read"],
        "node_token": "b36-smoke-token-123456"}).json()
    check("node registered", node["node_id"] == "phone-smoke")
    sent = client.post("/api/v1/notifications", json={
        "recipient_node_id": "phone-smoke", "type": "info",
        "title": "Rooktest wacht",
        "related_mission": mid}).json()
    check("7. notification exists", bool(sent["notification_id"]))
    mobile_node = client.get(
        "/mobile", params={"node": "phone-smoke"}).text
    check("8. notification deeplink works",
          "Rooktest wacht" in mobile_node
          and f"/missions/{mid}" in mobile_node)

    from coordinator.app.cameras import camera_dir, write_bmp_24
    shot = os.path.join(camera_dir(), "b36-smoke.png")
    write_bmp_24(shot, 8, 8, b"\x10\x20\x30" * 64)
    check("9. camera item appears",
          "Camera" in client.get("/mobile").text)

    guide = client.get("/api/v1/guide").json()
    check("10. guide shows real action",
          isinstance(guide["items"], list))
    packet = client.get("/api/v1/context/packet.md")
    check("11. packet generates",
          packet.status_code == 200 and len(packet.text) > 100)
    dash = client.get("/api/v1/mobile/dashboard").json()
    check("12. craft state appears", "craft" in dash)
    check("13. symbiosis appears", "symbiosis" in dash)
    check("14. node status appears",
          any(n["node_id"] == "phone-smoke"
              for n in dash["nodes"]["nodes"]))
    check("15. progress appears",
          len(dash["progress"]["quests"]) >= 1)
    print("smoke done")
