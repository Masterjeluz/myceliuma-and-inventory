"""Seed a tmp demo world for BIG #33 screenshots (real records only)."""

import os
import sys

tmp = os.environ.get("B33_SHOT_TMP", "")
assert tmp, "B33_SHOT_TMP required"
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(tmp, "shots.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    tmp, "shots-chat.db")

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

with TestClient(main_mod.app) as client:
    node = client.post("/api/v1/nodes/register", json={
        "node_id": "workshop-laptop", "hostname": "workshop-laptop",
        "tier": "worker",
        "capabilities": ["research.fetch_url",
                         "analysis.summarize", "inventory.read"],
        "node_token": "screenshot-token-abcdef-123456"})
    print("node:", node.status_code)
    node2 = client.post("/api/v1/nodes/register", json={
        "node_id": "seed-pi", "hostname": "seed-pi",
        "tier": "seed", "capabilities": ["inventory.read"],
        "node_token": "screenshot-token-abcdef-123456"})
    print("node2:", node2.status_code)
    cand = client.post("/api/v1/candidates", json={
        "title": "Camper solar upgrade als eerste project",
        "candidate_type": "idea",
        "summary": "Zonnepaneel plus accu koppelen aan de camper"})
    print("candidate:", cand.status_code)
    conn = client.post("/api/v1/candidates", json={
        "title": "Camper versterkt solar-project",
        "candidate_type": "connection",
        "summary": "Mogelijke symbiose tussen camper en panelen",
        "entity_refs": ["proj_camper", "obj_panel"]})
    print("connection:", conn.status_code)
    imp = client.post("/api/v1/conversations/import", json={
        "title": "Camper verduurzamen",
        "content": ("Jelles: idee om de camper duurzamer te maken met "
                    "zonnepanelen, TODO uitwerken.\nClaude: voorstel: meet "
                    "eerst het verbruik, claim: een 400W paneel dekt de "
                    "koelkast."),
        "format": "plain", "source_platform": "claude"})
    print("import:", imp.status_code, imp.text[:120])
    try:
        conv_id = imp.json()["conversation_id"]
        analyzed = client.post(
            "/api/v1/conversations/" + conv_id + "/analyze")
        print("analyze:", analyzed.status_code)
    except Exception as exc:
        print("analyze skipped:", exc)
    chat = client.post("/api/v1/chat",
                       json={"message": "kijk wat er openstaat"})
    print("chat:", chat.status_code)
    try:
        mission = client.post("/api/v1/missions/from-template", json={
            "template_id": "research_topic",
            "goal": "Solar upgrade onderzoeken",
            "conversation_id": chat.json()["conversation_id"]})
        print("mission:", mission.status_code, mission.text[:160])
    except Exception as exc:
        print("mission skipped:", exc)
    cam = client.post("/api/v1/cameras/register", json={
        "name": "Insta360 X4", "kinds": ["snapshot"],
        "source": "insta360"})
    print("camera:", cam.status_code, cam.text[:120])
    research = client.post("/api/v1/research/queue", json={
        "question": "Welk zonnepaneel past op een camperdak?"})
    print("research:", research.status_code,
          research.text[:160])
    print("seed done")
    sys.exit(0)
