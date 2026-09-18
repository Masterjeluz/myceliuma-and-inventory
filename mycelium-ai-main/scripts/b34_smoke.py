"""BIG #34 smoke: camera/file → world chain on tmp DBs.

Proves (all real localhost HTTP via TestClient, no user data):
session → observations → VLM fallback (UNAVAILABLE) →
REAL mock analysis → candidates → entity link proposal (YES
path left to the operator) → symbiosis PROPOSED → timeline →
guide → world/activity presence. Prints one line per step.
"""

import os
import sys

tmp = os.environ.get("B34_SMOKE_TMP", "")
assert tmp, "B34_SMOKE_TMP required"
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(tmp, "smoke.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    tmp, "smoke-chat.db")

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.cameras import camera_dir, write_bmp_24


def check(name, ok, detail=""):
    print(f"{'OK  ' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        sys.exit(1)


with TestClient(main_mod.app) as client:
    device = client.post("/api/v1/cameras/register", json={
        "name": "Insta360 X4", "kinds": ["snapshot"],
        "source": "insta360"}).json()
    device_id = device["device_id"]
    check("camera registered (REAL)", device_id.startswith("cam-"),
          device_id)

    for index, name in enumerate(("smoke-a.png", "smoke-b.png")):
        path = os.path.join(camera_dir(), name)
        write_bmp_24(path, 8, 8, bytes(
            [(index * 80 + pos) % 256 for pos in range(192)]))
    session = client.post("/api/v1/camera-sessions", json={
        "device_id": device_id,
        "filenames": ["smoke-a.png", "smoke-b.png"]}).json()
    check("session created", session["session_id"].startswith("cing_"),
          session["session_id"])

    ran = client.post(
        f"/api/v1/camera-sessions/{session['session_id']}/run").json()
    observations = ran["observations"]
    check("2 observations", len(observations) == 2,
          str([item["state"] for item in
               ran["session"]["items"]]))
    observation_id = observations[0]["observation_id"]

    described = client.post(
        f"/api/v1/observations/{observation_id}/describe",
        json={}).json()
    check("VLM fallback UNAVAILABLE",
          described["vlm_state"] == "UNAVAILABLE"
          and described["analysis"]["labels"] == [],
          described.get("reason", "")[:60])

    from coordinator.app.vision_flow import (VisionAnalysisRecord,
                                             save_analysis)
    save_analysis(VisionAnalysisRecord(
        analysis_id="an_smoke", observation_id=observation_id,
        device_id=device_id,
        result={"analysis_id": "an_smoke",
                "observation_id": observation_id,
                "device_id": device_id,
                "labels": ["zonnepaneel"],
                "detected_objects": [
                    {"label": "zonnepaneel", "confidence": 0.8}],
                "description": "smoke", "ocr_text": "",
                "uncertainty": "", "raw_text": "smoke",
                "model": "smoke-mock",
                "observed_at": "2026-01-01T00:00:00+00:00",
                "provenance": {}},
        created_at="2026-01-01T00:00:00+00:00"))
    proposed = client.post(
        f"/api/v1/observations/{observation_id}/propose-candidates"
    ).json()
    check("candidate proposed",
          len(proposed["candidates"]) == 1
          and proposed["candidates"][0]["label"] == "zonnepaneel")

    matches = client.get("/api/v1/camera-match",
                         params={"q": "zonnepaneel"}).json()
    check("match endpoint honest", isinstance(matches["matches"], list))

    link = client.post("/api/v1/camera-suggest-link", json={
        "observation_id": observation_id, "entity_id": "proj_demo",
        "predicate": "supports"}).json()
    check("link PROPOSED", link["state"] == "PROPOSED",
          link["candidate_id"])

    from coordinator.app.symbiosis import proposed
    check("symbiosis PROPOSED visible",
          any(link["candidate_id"] == item["candidate_id"]
              for item in proposed(limit=20)))

    line = client.get("/api/v1/camera-timeline",
                      params={"device_id": device_id}).json()
    check("timeline from shared bus", len(line["timeline"]) >= 1,
          f"{len(line['timeline'])} item(s)")

    guide = client.get("/api/v1/guide").json()
    check("guide alive", isinstance(guide["items"], list))

    activity = client.get("/activity")
    check("activity renders", activity.status_code == 200)
    world = client.get("/world")
    check("world renders", world.status_code == 200)

    transport = client.get(
        f"/api/v1/cameras/{device_id}/availability").json()
    check("Insta360 transport UNAVAILABLE",
          transport.get("state") in ("registered", "detected")
          and transport.get("capturable") is False,
          str(transport.get("state")))
    print("smoke done")
