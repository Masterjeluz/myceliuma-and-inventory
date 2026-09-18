"""BIG #35 smoke: model → verified object on tmp DBs.

Proves via real localhost HTTP (TestClient, no user data):
register → inspect → material → fabjob → prepare → slice →
propose → YES → execute (simulated) → sync → observe →
verify → presence → packet → pages. Prints one line/step.
"""

import os
import struct
import sys

tmp = os.environ.get("B35_SMOKE_TMP", "")
assert tmp, "B35_SMOKE_TMP required"
os.environ["MYCELIUM_DATABASE_PATH"] = os.path.join(tmp, "smoke.db")
os.environ["MYCELIUM_CHAT_DATABASE_PATH"] = os.path.join(
    tmp, "smoke-chat.db")
os.environ["MYCELIUM_FABRICATION_DIR"] = os.path.join(
    tmp, "smoke-fab")

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app.printer3d import (
    SimulatedPrinterAdapter, clear_printers, new_printer,
    register_printer as register_device)


def check(name, ok, detail=""):
    print(f"{'OK  ' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        sys.exit(1)


clear_printers()
with TestClient(main_mod.app) as client:
    from coordinator.app.mesh3d import fabrication_dir
    os.makedirs(fabrication_dir(), exist_ok=True)
    with open(os.path.join(fabrication_dir(), "smoke.stl"),
              "wb") as handle:
        handle.write(b"\x00" * 80)
        handle.write(struct.pack("<I", 1))
        handle.write(struct.pack("<12fH", 0, 0, 1, 0, 0, 0,
                                 10, 0, 0, 0, 10, 0, 0))
    model = client.post("/api/v1/workshop/models",
                        json={"filename": "smoke.stl"}).json()
    check("model registered", model["model_id"].startswith("mdl_"),
          model["model_id"])
    inspected = client.post(
        f"/api/v1/workshop/models/{model['model_id']}/inspect"
    ).json()
    check("model inspected",
          inspected["inspection"]["triangles"] == 1
          and inspected["inspection"]["manifold"] == "UNKNOWN")

    material = client.post("/api/v1/workshop/materials", json={
        "name": "PLA smoke", "kind": "filament",
        "state": "known"}).json()
    check("material known", material["state"] == "known")

    client.post("/api/v1/printers/register", json={
        "printer_id": "prt-smoke", "name": "Smoke",
        "capabilities": ["printer.status", "printer.start",
                         "printer.cancel"]})
    register_device(new_printer(
        "prt-smoke", "Smoke",
        ["printer.status", "printer.start", "printer.cancel"]),
        SimulatedPrinterAdapter())
    job = client.post("/api/v1/workshop/fabjobs", json={
        "model_id": model["model_id"], "material_ref": "PLA smoke",
        "printer_id": "prt-smoke",
        "profile": "draft-pla"}).json()
    job_id = job["job_id"]
    check("fabjob designed", job["stage"] == "designed", job_id)
    assert client.post(
        f"/api/v1/workshop/fabjobs/{job_id}/prepare",
        json={}).json()["stage"] == "prepared"
    sliced = client.post(
        f"/api/v1/workshop/fabjobs/{job_id}/slice",
        json={"slicer": "test-slicer"}).json()
    check("sliced TEST", sliced["stage"] == "gcode-ready"
          and sliced["slicer"] == "test-slicer")
    proposed = client.post(
        f"/api/v1/workshop/fabjobs/{job_id}/propose",
        json={}).json()
    check("print proposed (inert)",
          proposed["stage"] == "proposed", proposed["proposal_id"])
    pid = proposed["proposal_id"]
    assert client.post(f"/api/v1/writes/{pid}/execute"
                       ).status_code == 409
    check("execute-before-YES refuses", True)
    assert client.post(f"/api/v1/writes/{pid}/approve",
                       json={"response": "YES"}).status_code == 200
    executed = client.post(f"/api/v1/writes/{pid}/execute")
    check("executed SIMULATED", executed.status_code == 200)
    synced = client.post(
        f"/api/v1/workshop/fabjobs/{job_id}/sync",
        json={}).json()
    check("printed-simulated", synced["stage"] ==
          "printed-simulated")

    device = client.post("/api/v1/cameras/register", json={
        "name": "Smoke cam", "kinds": ["snapshot"],
        "source": "usb"}).json()["device_id"]
    from coordinator.app.cameras import camera_dir, write_bmp_24
    shot = os.path.join(camera_dir(), "b35-smoke.png")
    write_bmp_24(shot, 8, 8, b"\x10\x20\x30" * 64)
    ingested = client.post(f"/api/v1/cameras/{device}/ingest-file",
                           json={"filename": "b35-smoke.png"})
    observation_id = ingested.json()["observation"][
        "observation_id"]
    observed = client.post(
        f"/api/v1/workshop/fabjobs/{job_id}/observe",
        json={"observation_id": observation_id}).json()
    check("observed", observed["stage"] == "observed")
    verified = client.post(
        f"/api/v1/workshop/fabjobs/{job_id}/verify",
        json={"verified_by": "Jelles"}).json()
    check("verified by human", verified["stage"] == "verified"
          and verified["verified_by"] == "Jelles")

    client.post("/api/v1/workshop/links", json={
        "workshop_id": model["model_id"], "entity_id": "proj_demo",
        "predicate": "used_in"})
    presence = client.get("/api/v1/workshop/presence",
                          params={"entity_id": "proj_demo"}).json()
    check("presence checklist", presence["done"] >= 1,
          f"{presence['done']}/{presence['total']}")
    packet = client.get("/api/v1/workshop/packet",
                        params={"project_id": "proj_demo"}).json()
    check("continuation packet",
          packet["packet"] == "mycelium-3d-workshop/1")
    for page in ("/3d", "/craft", "/symbiosis", "/guide",
                 "/world", "/mobile", "/fabrication"):
        check(f"{page} renders",
              client.get(page).status_code == 200)
    print("smoke done")
clear_printers()
