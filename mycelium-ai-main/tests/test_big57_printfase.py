"""BIG57 printfase M0: omgevingsbewijs voor lokaal printen.

Proves the readiness probes are real and honest, never invented:
slicer binaries with CLI proof, MQTT transport presence, library
root reachability (probe never creates), spool registry state, and
the /3d readiness panel. No slicing, no hardware motion.
"""

import sys

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app import forge as forge_mod

OPERATOR = "b57-operator-key"


@pytest.fixture(autouse=True)
def isolated_dbs(tmp_path, monkeypatch):
    """Every test gets private DBs: nothing ever touches real or
    stray database files (AGENTS.md tmp-file discipline)."""
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b57.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b57-chat.db"))


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b57.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b57-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", OPERATOR)
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_slicer_probe_honest_states(tmp_path, monkeypatch):
    # Bogus binary: ABSENT, never green.
    missing = forge_mod.probe_local_slicers([{
        "id": "nope", "label": "Nope", "env_var": "B57_NOPE_BIN",
        "default": str(tmp_path / "nope.exe")}])
    assert missing[0]["state"] == "ABSENT"
    assert missing[0]["next"]
    # Real executable without slice flags: UNPROVEN, never CLI_OK.
    plain = forge_mod.probe_local_slicers([{
        "id": "plain", "label": "Plain", "env_var": "B57_PLAIN_BIN",
        "default": sys.executable}])
    assert plain[0]["state"] == "PRESENT_CLI_UNPROVEN", plain
    # Pure classifier: slice flags in output mean CLI_OK.
    state, _ = forge_mod._classify_smoke(
        0, "--export-gcode --slice model.stl")
    assert state == "CLI_OK"
    state, _ = forge_mod._classify_smoke(1, "wat")
    assert state == "CLI_FAILED"
    state, _ = forge_mod._classify_smoke(None, "")
    assert state == "CLI_FAILED"


def test_mqtt_probe_never_imports():
    probe = forge_mod.probe_mqtt()
    assert probe["state"] in ("AVAILABLE", "MISSING")
    assert probe["reason"] and probe["next"]
    assert "paho.mqtt.client" not in sys.modules or \
        probe["state"] == "AVAILABLE"


def test_library_probe_never_creates(tmp_path, monkeypatch):
    target = tmp_path / "lib-new"
    monkeypatch.setenv(forge_mod.LIBRARY_DIR_ENV_VAR, str(target))
    probe = forge_mod.probe_library()
    assert probe["state"] == "MISSING", probe
    assert not target.exists(), "probe must never create dirs"
    target.mkdir()
    probe = forge_mod.probe_library()
    assert probe["state"] == "OK", probe
    assert probe["root"] == str(target)


def test_readiness_shape(tmp_path, monkeypatch):
    monkeypatch.setenv(forge_mod.LIBRARY_DIR_ENV_VAR,
                       str(tmp_path / "lib-shape"))
    for test_client in api(tmp_path, monkeypatch):
        ready = forge_mod.print_workshop_readiness()
        assert set(("slicers", "mqtt", "library", "spools",
                    "printers")) <= set(ready)
        assert isinstance(ready["slicers"], list)
        assert ready["library"]["state"] == "MISSING"
        assert ready["spools"]["state"] in ("EMPTY", "OK")


def test_3d_readiness_panel_markers(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        html = test_client.get("/3d").text
        for marker in ("Readiness", "Slicer:", "MQTT-transport",
                       "Bibliotheek", "Spoelen", "Printers",
                       "SIMULATED geldt nooit als uitvoering"):
            assert marker in html, marker


# -- M1: bibliotheek ----------------------------------------------------

KUBUS_SRC = ("C:/Users/Jelles/AppData/Local/Temp/opencode/"
             "kubus20.stl")


def use_library(tmp_path, monkeypatch, name="b57lib"):
    from coordinator.app import forge as forge_mod
    root = tmp_path / name
    (root / "bibliotheek").mkdir(parents=True)
    monkeypatch.setenv(forge_mod.LIBRARY_DIR_ENV_VAR, str(root))
    return root


def test_setup_library_idempotent(tmp_path, monkeypatch):
    from coordinator.app import forge as forge_mod
    from coordinator.app.workshop3d import setup_library
    root = tmp_path / "lib-setup"
    monkeypatch.setenv(forge_mod.LIBRARY_DIR_ENV_VAR, str(root))
    first = setup_library()
    assert set(first["created"]) == {"bibliotheek", "profielen",
                                     "gcode", "archief"}
    second = setup_library()
    assert second["created"] == []
    assert set(second["existing"]) == {"bibliotheek", "profielen",
                                       "gcode", "archief"}


def test_scan_registers_real_model(tmp_path, monkeypatch):
    import shutil
    from coordinator.app.workshop3d import library_models, scan_library
    root = use_library(tmp_path, monkeypatch)
    shutil.copy(KUBUS_SRC, root / "bibliotheek" / "kubus20.stl")
    (root / "bibliotheek" / "leeg.stl").write_bytes(b"geen mesh")
    (root / "bibliotheek" / "negeer.txt").write_text("tekst")
    summary = scan_library(actor="b57-test")
    assert summary["scanned"] >= 2, summary
    # kubus registreert (valid), rommel.stl registreert eerlijk als
    # invalid — registratie is geen goedkeuring; .txt weigert.
    assert len(summary["registered"]) == 2, summary
    by_name = {reg["filename"]: reg
               for reg in summary["registered"]}
    assert by_name["kubus20.stl"]["verdict"] == "valid", by_name
    assert by_name["leeg.stl"]["verdict"] == "invalid", by_name
    assert len(by_name["kubus20.stl"]["sha256"]) == 64
    assert any("negeer.txt" in str(item)
               for item in summary["refused"]), summary
    assert not any("negeer.txt" in str(item.get("filename", ""))
                   for item in summary["registered"]), summary
    # Herscan: geen duplicaat.
    again = scan_library(actor="b57-test")
    assert again["registered"] == [], again
    assert len(again["duplicates"]) == 2, again
    assert len(library_models(limit=10)) == 2


def test_library_traversal_refused(tmp_path, monkeypatch):
    from coordinator.app.workshop3d import (
        WorkshopRefusedError,
        register_library_model,
    )
    use_library(tmp_path, monkeypatch)
    for bad in ("../kubus.stl", "/abs/kubus.stl",
                "C:\\win\\kubus.stl", ".hidden.stl", "mal.exe",
                "sub/dir/kubus.stl"):
        try:
            register_library_model(bad)
        except WorkshopRefusedError:
            continue
        raise AssertionError(f"accepted: {bad}")


def test_library_file_fields_proposable(tmp_path, monkeypatch):
    import shutil
    from coordinator.app.inventory_writes import propose_inventory_write
    from coordinator.app.workshop3d import (
        get_model,
        library_file_fields,
        scan_library,
    )
    root = use_library(tmp_path, monkeypatch)
    shutil.copy(KUBUS_SRC, root / "bibliotheek" / "kubus20.stl")
    summary = scan_library(actor="b57-test")
    record = get_model(summary["registered"][0]["model_id"])
    fields = library_file_fields(record)
    assert fields["file_kind"] == "mesh"
    assert len(fields["sha256"]) == 64
    assert fields["metadata"]["workshop_model_id"] == \
        record["model_id"]
    proposal = propose_inventory_write(
        "wrt-b57test01", "create", "file", fields,
        actor="b57-test")
    assert proposal.mutation_type == "inventory.create"


def test_spool_assign_validates(tmp_path, monkeypatch):
    from coordinator.app.fabrication import (
        FabricationRefusedError,
        assign_spool_location,
        new_spool,
        save_spool,
    )
    for test_client in api(tmp_path, monkeypatch):
        spool = new_spool("PLA", 500.0, color="wit")
        save_spool(spool)
        sid = spool.spool_id
        try:
            assign_spool_location(sid, printer_id="prt_nope",
                                  slot="AMS-1")
            raise AssertionError("unknown printer accepted")
        except FabricationRefusedError:
            pass
        try:
            assign_spool_location(sid, slot="../x")
            raise AssertionError("bad slot accepted")
        except FabricationRefusedError:
            pass
        made = test_client.post("/api/v1/printers/register", json={
            "name": "Bambu Lab A1 Mini",
            "capabilities": ["printer.status",
                             "printer.telemetry"]}).json()
        assert "printer_id" in made, made
        pid = made["printer_id"]
        updated = assign_spool_location(
            sid, printer_id=pid, slot="AMS-2")
        assert updated.location == f"{pid}/AMS-2", updated.location


def test_3d_library_spool_markers(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        html = test_client.get("/3d").text
        for marker in ("Bibliotheek", "Map scannen", "Map inrichten",
                       "Spoelen", "Spoel toevoegen", "Toewijzen",
                       "Nog geen bibliotheekmodellen"):
            assert marker in html, marker


def test_verdict_oordeel_never_permission():
    from coordinator.app.workshop3d import verdict_oordeel
    assert "geen printgarantie" in verdict_oordeel("valid")
    assert "niet slicen" in verdict_oordeel("invalid")
    assert "Nog niet" in verdict_oordeel("UNKNOWN")
    for verdict in ("valid", "invalid", "inconclusive", "UNKNOWN",
                    "wat"):
        text = verdict_oordeel(verdict).lower()
        assert "toegestaan" not in text
        assert "goedgekeurd" not in text


# -- M2: echt lokaal slicen ------------------------------------------------

KUBUS_SHA = ("d06efa281a51c7b521b85ff19d62952cbe7efc9f1d02efefba03c"
             "37c0d53d340")


def test_bambu_argv_pure_no_execution(tmp_path):
    from coordinator.app.local_slicer import (
        LocalSlicerError,
        bambu_slice_argv,
    )
    mach = str(tmp_path / "m.json")
    proc = str(tmp_path / "p.json")
    fila = str(tmp_path / "f.json")
    stl = str(tmp_path / "kubus.stl")
    for path in (mach, proc, fila, stl):
        with open(path, "w") as handle:
            handle.write("{}")
    argv = bambu_slice_argv(
        binary="bambu-studio", stl_path=stl, machine_json=mach,
        process_json=proc, filament_json=fila,
        output_3mf="out.gcode.3mf",
        overrides={"--curr-bed-type": "Cool Plate"})
    assert argv[:3] == ["bambu-studio", "--orient", "--arrange"]
    assert "--slice" in argv and "out.gcode.3mf" in argv
    assert argv[-1] == stl
    assert "--curr-bed-type=Cool Plate" in argv
    try:
        bambu_slice_argv(
            binary="bambu-studio", stl_path=stl, machine_json=mach,
            process_json=proc, filament_json=str(tmp_path / "weg"),
            output_3mf="out.gcode.3mf")
        raise AssertionError("missing filament accepted")
    except LocalSlicerError:
        pass
    try:
        bambu_slice_argv(
            binary="bambu-studio", stl_path=stl, machine_json=mach,
            process_json=proc, filament_json=fila,
            output_3mf="out.gcode.3mf",
            overrides={"no-dashes": "x"})
        raise AssertionError("bad override accepted")
    except LocalSlicerError:
        pass


def test_console_bambu_refuses_unproven():
    from coordinator.app.local_slicer import ConsoleSlicer
    from coordinator.app.slicer3d import SlicerUnavailable
    try:
        ConsoleSlicer(engine="bambu")
        raise AssertionError("bambu engine accepted")
    except SlicerUnavailable as error:
        assert "UNPROVEN" in str(error)
    try:
        ConsoleSlicer(engine="nope")
        raise AssertionError("unknown engine accepted")
    except ValueError:
        pass


def test_resolve_library_vs_fab(tmp_path, monkeypatch):
    import shutil
    from coordinator.app import forge as forge_mod
    from coordinator.app.local_slicer import (
        LocalSlicerError,
        resolve_model_artifact,
    )
    from coordinator.app.workshop3d import scan_library
    root = tmp_path / "lib-resolve"
    (root / "bibliotheek").mkdir(parents=True)
    monkeypatch.setenv(forge_mod.LIBRARY_DIR_ENV_VAR, str(root))
    fab = tmp_path / "fab-resolve"
    fab.mkdir()
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR", str(fab))
    shutil.copy(KUBUS_SRC, root / "bibliotheek" / "kubus20.stl")
    scan_library(actor="b57-test")
    source, path, data = resolve_model_artifact("kubus20.stl")
    assert source == "library", source
    assert path.endswith("kubus20.stl")
    assert len(data) > 0
    try:
        resolve_model_artifact("bestaat-niet.stl")
        raise AssertionError("unknown model resolved")
    except LocalSlicerError:
        pass


def _printer(tmp_path, monkeypatch, test_client):
    made = test_client.post("/api/v1/printers/register", json={
        "name": "Bambu Lab A1 Mini",
        "capabilities": ["printer.status",
                         "printer.telemetry"]}).json()
    return made["printer_id"]


def _library_kubus(tmp_path, monkeypatch):
    import shutil
    from coordinator.app import forge as forge_mod
    from coordinator.app.workshop3d import scan_library
    root = tmp_path / "lib-slice"
    (root / "bibliotheek").mkdir(parents=True)
    monkeypatch.setenv(forge_mod.LIBRARY_DIR_ENV_VAR, str(root))
    fab = tmp_path / "fab-slice"
    fab.mkdir()
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR", str(fab))
    shutil.copy(KUBUS_SRC, root / "bibliotheek" / "kubus20.stl")
    summary = scan_library(actor="b57-test")
    assert len(summary["registered"]) == 1, summary
    return summary["registered"][0]["model_id"], root


def test_real_slice_prusa_console(tmp_path, monkeypatch):
    from coordinator.app.workshop3d import create_fabjob, get_fabjob
    for test_client in api(tmp_path, monkeypatch):
        pid = _printer(tmp_path, monkeypatch, test_client)
        mid, root = _library_kubus(tmp_path, monkeypatch)
        job = create_fabjob(mid, material_ref="PLA", printer_id=pid,
                            profile="fine-pla", actor="b57-test")
        jid = job["job_id"]
        prepared = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/prepare", json={}).json()
        assert prepared["stage"] == "prepared", prepared
        sliced = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/slice",
            json={"slicer": "prusa-console"}).json()
        assert sliced["stage"] == "gcode-ready", sliced
        assert sliced["slicer_engine"] == "prusa", sliced
        assert sliced["gcode_verdict"] in ("safe", "inconclusive"), \
            sliced
        assert len(sliced["gcode_sha256"]) == 64
        assert sliced["gcode_canonical_ref"].startswith("gcode/"), \
            sliced
        stored = get_fabjob(jid)
        assert stored["gcode_sha256"] == sliced["gcode_sha256"]
        # Canonical artifact echt op schijf, working copy ook.
        import os
        canon = os.path.join(str(root), sliced["gcode_canonical_ref"])
        assert os.path.isfile(canon), canon
        assert os.path.getsize(canon) > 10000, canon


def test_supports_profile_changes_output(tmp_path, monkeypatch):
    from coordinator.app.workshop3d import create_fabjob, get_fabjob
    for test_client in api(tmp_path, monkeypatch):
        pid = _printer(tmp_path, monkeypatch, test_client)
        mid, _ = _library_kubus(tmp_path, monkeypatch)
        plain = create_fabjob(mid, printer_id=pid,
                              profile="fine-pla", actor="b57-test")
        sup = create_fabjob(mid, printer_id=pid,
                            profile="fine-pla-supports",
                            actor="b57-test")
        for jid in (plain["job_id"], sup["job_id"]):
            test_client.post(
                f"/api/v1/workshop/fabjobs/{jid}/prepare", json={})
        plain_s = test_client.post(
            f"/api/v1/workshop/fabjobs/{plain['job_id']}/slice",
            json={"slicer": "prusa-console"}).json()
        sup_s = test_client.post(
            f"/api/v1/workshop/fabjobs/{sup['job_id']}/slice",
            json={"slicer": "prusa-console"}).json()
        assert plain_s["stage"] == "gcode-ready", plain_s
        assert sup_s["stage"] == "gcode-ready", sup_s
        assert plain_s["gcode_sha256"] != sup_s["gcode_sha256"], \
            "supports-profiel moet andere G-code geven"


def test_bambu_slice_route_refuses_honestly(tmp_path, monkeypatch):
    from coordinator.app.workshop3d import create_fabjob
    for test_client in api(tmp_path, monkeypatch):
        pid = _printer(tmp_path, monkeypatch, test_client)
        mid, _ = _library_kubus(tmp_path, monkeypatch)
        job = create_fabjob(mid, printer_id=pid, profile="fine-pla",
                            actor="b57-test")
        jid = job["job_id"]
        test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/prepare", json={})
        res = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/slice",
            json={"slicer": "bambu-studio"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["stage"] == "blocked", body


def test_3d_slice_markers(tmp_path, monkeypatch):
    from coordinator.app.workshop3d import create_fabjob
    for test_client in api(tmp_path, monkeypatch):
        pid = _printer(tmp_path, monkeypatch, test_client)
        mid, _ = _library_kubus(tmp_path, monkeypatch)
        job = create_fabjob(mid, printer_id=pid, profile="fine-pla",
                            actor="b57-test")
        test_client.post(
            f"/api/v1/workshop/fabjobs/{job['job_id']}/prepare",
            json={})
        html = test_client.get("/3d").text
        for marker in ("Slicen", "Slice (lokaal)", "Slice (TEST)",
                       'name="slicer"'):
            assert marker in html, marker


# -- M3: wachtrij ---------------------------------------------------------

def _spool(test_client, material="PLA", weight=500.0, color="wit",
           compatible=()):
    res = test_client.post("/api/v1/filament/spools", json={
        "material": material, "weight_g": weight, "color": color,
        "compatible_profiles": list(compatible)})
    assert res.status_code == 201, res.text
    return res.json()["spool_id"]


def _ready_job(test_client, tmp_path, monkeypatch, profile="fine-pla",
               spool_compat=(), spool_weight=500.0):
    from coordinator.app.workshop3d import create_fabjob
    pid = _printer(tmp_path, monkeypatch, test_client)
    mid, _ = _library_kubus(tmp_path, monkeypatch)
    sid = _spool(test_client, weight=spool_weight,
                 compatible=spool_compat)
    test_client.post(f"/api/v1/filament/spools/{sid}/assign", json={
        "printer_id": pid, "slot": "AMS-2"})
    job = create_fabjob(mid, material_ref="PLA", printer_id=pid,
                        profile=profile, spool_id=sid,
                        actor="b57-test")
    jid = job["job_id"]
    test_client.post(f"/api/v1/workshop/fabjobs/{jid}/prepare",
                     json={})
    sliced = test_client.post(
        f"/api/v1/workshop/fabjobs/{jid}/slice",
        json={"slicer": "prusa-console"}).json()
    assert sliced["stage"] == "gcode-ready", sliced
    return jid, pid, sid, mid


def _approve_proposal(test_client, proposal_id):
    res = test_client.post(
        f"/api/v1/writes/{proposal_id}/approve",
        json={"response": "YES", "decided_by": "b57-test"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "approved", res.text


def test_preflight_blockers(tmp_path, monkeypatch):
    from coordinator.app.workshop3d import create_fabjob
    for test_client in api(tmp_path, monkeypatch):
        pid = _printer(tmp_path, monkeypatch, test_client)
        mid, _ = _library_kubus(tmp_path, monkeypatch)
        # Zonder spoel: blokkade.
        bare = create_fabjob(mid, printer_id=pid, profile="fine-pla",
                             actor="b57-test")
        test_client.post(
            f"/api/v1/workshop/fabjobs/{bare['job_id']}/prepare",
            json={})
        test_client.post(
            f"/api/v1/workshop/fabjobs/{bare['job_id']}/slice",
            json={"slicer": "prusa-console"})
        gate = test_client.post(
            f"/api/v1/workshop/fabjobs/{bare['job_id']}/preflight",
            json={}).json()
        assert gate["ok"] is False, gate
        assert any("spoel" in blocker for blocker in
                   gate["blockers"]), gate
        # Verkeerd materiaal: blokkade.
        sid = _spool(test_client, material="ABS", weight=500.0)
        job = create_fabjob(mid, printer_id=pid, profile="fine-pla",
                            spool_id=sid, actor="b57-test")
        test_client.post(
            f"/api/v1/workshop/fabjobs/{job['job_id']}/prepare",
            json={})
        test_client.post(
            f"/api/v1/workshop/fabjobs/{job['job_id']}/slice",
            json={"slicer": "prusa-console"})
        gate = test_client.post(
            f"/api/v1/workshop/fabjobs/{job['job_id']}/preflight",
            json={}).json()
        assert gate["ok"] is False, gate
        assert any("ABS" in blocker or "PLA" in blocker
                   for blocker in gate["blockers"]), gate


def test_preflight_test_gcode_blocked(tmp_path, monkeypatch):
    from coordinator.app.workshop3d import create_fabjob
    for test_client in api(tmp_path, monkeypatch):
        pid = _printer(tmp_path, monkeypatch, test_client)
        mid, _ = _library_kubus(tmp_path, monkeypatch)
        sid = _spool(test_client)
        job = create_fabjob(mid, printer_id=pid, profile="fine-pla",
                            spool_id=sid, actor="b57-test")
        jid = job["job_id"]
        test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/prepare", json={})
        test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/slice",
            json={"slicer": "test-slicer"})
        gate = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/preflight",
            json={}).json()
        assert gate["ok"] is False, gate
        assert any("TEST" in blocker for blocker in
                   gate["blockers"]), gate


def test_enqueue_full_chain(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        jid, pid, sid, _ = _ready_job(
            test_client, tmp_path, monkeypatch,
            spool_compat=["fine-pla"])
        proposed = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/propose",
            json={"actor": "b57-test"}).json()
        assert proposed["stage"] == "proposed", proposed
        # Zonder YES: 409, geen taak.
        early = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/enqueue", json={})
        assert early.status_code == 409, early.text
        _approve_proposal(test_client, proposed["proposal_id"])
        gate = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/preflight",
            json={}).json()
        assert gate["ok"] is True, gate
        assert gate["estimate_g"] is not None and \
            gate["estimate_g"] > 0, gate
        queued = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/enqueue", json={}).json()
        assert queued["existing"] is False, queued
        task_id = queued["task_id"]
        tasks = test_client.get("/api/v1/tasks").json()
        mine = [task for task in tasks
                if task["id"] == task_id][0]
        assert mine["kind"] == "print.execute", mine
        assert mine["status"] == "queued", mine
        assert mine["required_capabilities"] == ["printer.start"], \
            mine
        assert mine["payload"]["print_job_id"] == jid, mine
        assert mine["payload"]["proposal_id"] == \
            proposed["proposal_id"], mine
        # Herhaald: zelfde taak, geen duplicaat.
        again = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/enqueue", json={}).json()
        assert again == {"task_id": task_id, "existing": True,
                        "job_id": jid}, again


def test_enqueue_stale_proposal_refused(tmp_path, monkeypatch):
    import os
    for test_client in api(tmp_path, monkeypatch):
        jid, pid, sid, _ = _ready_job(
            test_client, tmp_path, monkeypatch)
        proposed = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/propose",
            json={"actor": "b57-test"}).json()
        _approve_proposal(test_client, proposed["proposal_id"])
        # Saboteer de werk kopie: sha komt niet meer overeen.
        fab = os.environ.get("MYCELIUM_FABRICATION_DIR", "")
        hit = [name for name in os.listdir(fab)
               if name.endswith(".gcode")]
        assert hit, "werk kopie ontbreekt"
        with open(os.path.join(fab, hit[0]), "ab") as handle:
            handle.write(b"; sabotage\n")
        stale = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/enqueue", json={})
        assert stale.status_code == 422, stale.text
        gate = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/preflight",
            json={}).json()
        assert gate["ok"] is False, gate


def test_3d_queue_markers(tmp_path, monkeypatch):
    from coordinator.app.workshop3d import create_fabjob
    for test_client in api(tmp_path, monkeypatch):
        jid, pid, sid, mid = _ready_job(
            test_client, tmp_path, monkeypatch)
        proposed = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/propose",
            json={"actor": "b57-test"}).json()
        _approve_proposal(test_client, proposed["proposal_id"])
        test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/enqueue", json={})
        job2 = create_fabjob(mid, printer_id=pid, profile="fine-pla",
                             spool_id=sid, actor="b57-test")
        test_client.post(
            f"/api/v1/workshop/fabjobs/{job2['job_id']}/prepare",
            json={})
        test_client.post(
            f"/api/v1/workshop/fabjobs/{job2['job_id']}/slice",
            json={"slicer": "prusa-console"})
        prop2 = test_client.post(
            f"/api/v1/workshop/fabjobs/{job2['job_id']}/propose",
            json={"actor": "b57-test"}).json()
        gate2 = test_client.post(
            f"/api/v1/workshop/fabjobs/{job2['job_id']}/preflight",
            json={}).json()
        assert gate2["ok"] is True, gate2
        html = test_client.get("/3d").text
        assert "Wacht op exacte YES" in html, "YES-hint ontbreekt"
        _approve_proposal(test_client, prop2["proposal_id"])
        html = test_client.get("/3d").text
        assert "In wachtrij plaatsen" in html, \
            "enqueue-knop ontbreekt na YES"
        job3 = create_fabjob(mid, printer_id=pid, profile="fine-pla",
                             spool_id=sid, actor="b57-test")
        test_client.post(
            f"/api/v1/workshop/fabjobs/{job3['job_id']}/prepare",
            json={})
        test_client.post(
            f"/api/v1/workshop/fabjobs/{job3['job_id']}/slice",
            json={"slicer": "prusa-console"})
        html = test_client.get("/3d").text
        for marker in ("Wachtrij", "In wachtrij plaatsen",
                       "Pre-flight controleren", "Opnieuw controleren",
                       "Herstellen (sweep)", "print.execute",
                       "Volgorde = aanmaakvolgorde"):
            assert marker in html, marker


# -- M5: dossiers ---------------------------------------------------------

def test_enqueue_links_task_on_job(tmp_path, monkeypatch):
    from coordinator.app.workshop3d import get_fabjob
    for test_client in api(tmp_path, monkeypatch):
        jid, pid, sid, _ = _ready_job(
            test_client, tmp_path, monkeypatch)
        proposed = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/propose",
            json={"actor": "b57-test"}).json()
        _approve_proposal(test_client, proposed["proposal_id"])
        queued = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/enqueue", json={}).json()
        stored = get_fabjob(jid)
        assert stored["queue_task_id"] == queued["task_id"], stored
        assert stored["stage"] == "queued", stored


def test_dossier_complete_and_honest(tmp_path, monkeypatch):
    from coordinator.app.workshop3d import get_fabjob
    for test_client in api(tmp_path, monkeypatch):
        jid, pid, sid, mid = _ready_job(
            test_client, tmp_path, monkeypatch)
        proposed = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/propose",
            json={"actor": "b57-test"}).json()
        _approve_proposal(test_client, proposed["proposal_id"])
        test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/enqueue", json={})
        job = get_fabjob(jid)
        dossier = {
            "job_id": job["job_id"],
            "stage": job["stage"],
            "model_id": job["model_id"],
            "profile": job["profile"],
            "spool_id": job["spool_id"],
            "printer_id": job["printer_id"],
            "gcode_ref": job["gcode_ref"],
            "gcode_sha256": job["gcode_sha256"],
            "gcode_verdict": job["gcode_verdict"],
            "slicer_engine": job["slicer_engine"],
            "proposal_id": job["proposal_id"],
            "queue_task_id": job["queue_task_id"],
            "history": job["history"],
        }
        assert dossier["model_id"] == mid
        assert dossier["profile"] == "fine-pla"
        assert dossier["spool_id"] == sid
        assert dossier["printer_id"] == pid
        assert len(dossier["gcode_sha256"]) == 64
        assert dossier["gcode_verdict"] in ("safe", "inconclusive")
        assert dossier["slicer_engine"] == "prusa"
        assert dossier["proposal_id"] == proposed["proposal_id"]
        assert dossier["queue_task_id"] > 0
        assert len(dossier["history"]) >= 5, dossier["history"]
        stages = [entry["stage"] for entry in dossier["history"]]
        for expected in ("designed", "prepared", "sliced",
                         "gcode-ready", "proposed", "queued"):
            assert expected in stages, stages
        html = test_client.get("/3d").text
        for marker in ("Geschiedenis", "reconstrueerbaar",
                       str(dossier["queue_task_id"]),
                       dossier["gcode_sha256"][:12]):
            assert marker in html, marker


# -- M3.5: cancel / stock / compat / slot / UI ----------------------------

TOKEN35 = "b575-test-token-12345678"


def _printer_node(test_client, node_id, capabilities):
    res = test_client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": "b575host", "tier": "worker",
        "capabilities": capabilities, "executors": ["exec:print"],
        "node_token": TOKEN35})
    assert res.status_code == 201, res.text
    beat = test_client.post(f"/api/v1/nodes/{node_id}/heartbeat",
                            json={"available": True,
                                  "node_token": TOKEN35})
    assert beat.status_code == 204, beat.text


def _queued_print(test_client, tmp_path, monkeypatch):
    jid, pid, sid, _ = _ready_job(
        test_client, tmp_path, monkeypatch)
    proposed = test_client.post(
        f"/api/v1/workshop/fabjobs/{jid}/propose",
        json={"actor": "b575-test"}).json()
    _approve_proposal(test_client, proposed["proposal_id"])
    queued = test_client.post(
        f"/api/v1/workshop/fabjobs/{jid}/enqueue", json={}).json()
    assert queued["existing"] is False, queued
    return jid, queued["task_id"]


def test_task_cancel_queued_idempotent_missing(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        jid, tid = _queued_print(test_client, tmp_path, monkeypatch)
        first = test_client.post(f"/api/v1/tasks/{tid}/cancel",
                                 json={"reason": "b575-test"})
        assert first.status_code == 200, first.text
        assert first.json() == {"id": tid, "status": "cancelled",
                                "existing": False}, first.text
        again = test_client.post(f"/api/v1/tasks/{tid}/cancel",
                                 json={})
        assert again.status_code == 200, again.text
        assert again.json()["existing"] is True, again.text
        missing = test_client.post("/api/v1/tasks/424242/cancel",
                                   json={})
        assert missing.status_code == 404, missing.text


def test_cancelled_task_not_claimable(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        jid, tid = _queued_print(test_client, tmp_path, monkeypatch)
        test_client.post(f"/api/v1/tasks/{tid}/cancel", json={})
        _printer_node(test_client, "b575-printer-01",
                      ["printer.start"])
        claimed = test_client.post(
            "/api/v1/tasks/claim/b575-printer-01"
            f"?node_token={TOKEN35}", json={})
        assert claimed.status_code == 200, claimed.text
        assert claimed.json() is None, claimed.text


def test_cancel_assigned_refused_terminal_refused(tmp_path,
                                                  monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        jid, tid = _queued_print(test_client, tmp_path, monkeypatch)
        _printer_node(test_client, "b575-printer-02",
                      ["printer.start"])
        claimed = test_client.post(
            "/api/v1/tasks/claim/b575-printer-02"
            f"?node_token={TOKEN35}", json={}).json()
        assert claimed["id"] == tid, claimed
        refused = test_client.post(f"/api/v1/tasks/{tid}/cancel",
                                   json={})
        assert refused.status_code == 409, refused.text
        done = test_client.post(
            f"/api/v1/tasks/{tid}/complete", json={
                "node_id": "b575-printer-02", "success": True,
                "result": {"summary": "b575 dry telemetry"}})
        assert done.status_code == 204, done.text
        terminal = test_client.post(f"/api/v1/tasks/{tid}/cancel",
                                    json={})
        assert terminal.status_code == 409, terminal.text


def test_job_cancel_syncs_task(tmp_path, monkeypatch):
    from coordinator.app.workshop3d import get_fabjob
    for test_client in api(tmp_path, monkeypatch):
        jid, tid = _queued_print(test_client, tmp_path, monkeypatch)
        cancelled = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/cancel",
            json={"reason": "b575-test"})
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["stage"] == "cancelled", cancelled
        task = test_client.get(f"/api/v1/tasks/by-id/{tid}").json()
        assert task["status"] == "cancelled", task
        # Idempotent: opnieuw annuleren lukt.
        again = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/cancel",
            json={"reason": "b575-test"})
        assert again.status_code == 200, again.text
        stored = get_fabjob(jid)
        assert stored["stage"] == "cancelled", stored


def test_job_cancel_refused_when_assigned(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        jid, tid = _queued_print(test_client, tmp_path, monkeypatch)
        _printer_node(test_client, "b575-printer-03",
                      ["printer.start"])
        claimed = test_client.post(
            "/api/v1/tasks/claim/b575-printer-03"
            f"?node_token={TOKEN35}", json={}).json()
        assert claimed["id"] == tid, claimed
        refused = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/cancel",
            json={"reason": "b575-test"})
        assert refused.status_code == 422, refused.text
        assert "houdt de job vast" in refused.text, refused.text


def test_queue_propose_never_deducts(tmp_path, monkeypatch):
    from coordinator.app.fabrication import list_spools
    for test_client in api(tmp_path, monkeypatch):
        jid, pid, sid, _ = _ready_job(
            test_client, tmp_path, monkeypatch)
        before = [spool for spool in list_spools()
                  if spool.spool_id == sid][0].weight_remaining_g
        proposed = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/propose",
            json={"actor": "b575-test"}).json()
        _approve_proposal(test_client, proposed["proposal_id"])
        test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/enqueue", json={})
        test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/cancel",
            json={"reason": "b575-test"})
        after = [spool for spool in list_spools()
                 if spool.spool_id == sid][0].weight_remaining_g
        assert after == before, (before, after)


def test_deduct_exactly_once(tmp_path, monkeypatch):
    from coordinator.app.fabrication import (
        FabricationRefusedError,
        deduct_spool,
        list_spools,
        new_spool,
        save_spool,
    )
    for test_client in api(tmp_path, monkeypatch):
        spool = new_spool("PLA", 500.0)
        save_spool(spool)
        sid = spool.spool_id
        first = deduct_spool(sid, 4.45, reason="print:task-1",
                             usage_key="print:1")
        assert first["deducted"] is True, first
        assert first["remaining_g"] == 495.55, first
        replay = deduct_spool(sid, 4.45, reason="print:task-1",
                              usage_key="print:1")
        assert replay["deducted"] is False, replay
        weight = [item for item in list_spools()
                  if item.spool_id == sid][0].weight_remaining_g
        assert weight == 495.55, weight
        second = deduct_spool(sid, 1.0, reason="print:task-2",
                              usage_key="print:2")
        assert second["deducted"] is True, second
        for bad in (0, -1, 100000):
            try:
                deduct_spool(sid, bad, reason="x", usage_key="k-bad")
                raise AssertionError(f"accepted {bad}")
            except FabricationRefusedError:
                pass
        try:
            deduct_spool(sid, 99999, reason="x", usage_key="k-huge")
            raise AssertionError("overdraft accepted")
        except FabricationRefusedError:
            pass


def test_no_caller_deducts_outside_execution():
    import pathlib
    app = pathlib.Path(__file__).resolve().parent.parent / \
        "coordinator" / "app"
    for path in app.glob("*.py"):
        if path.name == "fabrication.py":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        current_def = ""
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("def "):
                current_def = stripped[4:].split("(")[0]
            if "deduct_spool(" in line:
                assert current_def == "finalize_print_task", \
                    f"{path.name}:{lineno} buiten finalize"


def test_compat_profile_printer_enforced(tmp_path, monkeypatch):
    import coordinator.app.slicer3d as slicer_mod
    from coordinator.app.workshop3d import create_fabjob
    profiles = {
        name: dict(settings)
        for name, settings in slicer_mod.SLICER_PROFILES.items()}
    profiles["fine-pla"] = dict(profiles["fine-pla"])
    profiles["fine-pla"]["printers"] = ["Other Printer"]
    monkeypatch.setattr(slicer_mod, "SLICER_PROFILES", profiles)
    for test_client in api(tmp_path, monkeypatch):
        made = test_client.post("/api/v1/printers/register", json={
            "name": "Bambu Lab A1 Mini", "model": "A1 mini",
            "capabilities": ["printer.status"]}).json()
        assert made["model"] == "A1 mini", made
        pid = made["printer_id"]
        mid, _ = _library_kubus(tmp_path, monkeypatch)
        sid = _spool(test_client)
        job = create_fabjob(mid, printer_id=pid, profile="fine-pla",
                            spool_id=sid, actor="b575-test")
        test_client.post(
            f"/api/v1/workshop/fabjobs/{job['job_id']}/prepare",
            json={})
        test_client.post(
            f"/api/v1/workshop/fabjobs/{job['job_id']}/slice",
            json={"slicer": "prusa-console"})
        gate = test_client.post(
            f"/api/v1/workshop/fabjobs/{job['job_id']}/preflight",
            json={}).json()
        assert gate["ok"] is False, gate
        assert any("ondersteunt" in blocker
                   for blocker in gate["blockers"]), gate


def test_compat_spool_list_enforced(tmp_path, monkeypatch):
    from coordinator.app.workshop3d import create_fabjob
    for test_client in api(tmp_path, monkeypatch):
        pid = _printer(tmp_path, monkeypatch, test_client)
        mid, _ = _library_kubus(tmp_path, monkeypatch)
        sid = _spool(test_client, compatible=["draft-pla"])
        job = create_fabjob(mid, printer_id=pid, profile="fine-pla",
                            spool_id=sid, actor="b575-test")
        test_client.post(
            f"/api/v1/workshop/fabjobs/{job['job_id']}/prepare",
            json={})
        test_client.post(
            f"/api/v1/workshop/fabjobs/{job['job_id']}/slice",
            json={"slicer": "prusa-console"})
        gate = test_client.post(
            f"/api/v1/workshop/fabjobs/{job['job_id']}/preflight",
            json={}).json()
        assert gate["ok"] is False, gate
        assert any("compatibele" in blocker
                   for blocker in gate["blockers"]), gate


def test_duplicate_slot_refused(tmp_path, monkeypatch):
    from coordinator.app.fabrication import (
        FabricationRefusedError,
        assign_spool_location,
        new_spool,
        save_spool,
    )
    for test_client in api(tmp_path, monkeypatch):
        pid = _printer(tmp_path, monkeypatch, test_client)
        first = new_spool("PLA", 500.0)
        save_spool(first)
        second = new_spool("PLA", 500.0)
        save_spool(second)
        assign_spool_location(first.spool_id, printer_id=pid,
                              slot="AMS-1")
        try:
            assign_spool_location(second.spool_id, printer_id=pid,
                                  slot="AMS-1")
            raise AssertionError("duplicate slot accepted")
        except FabricationRefusedError as error:
            assert "bevat al" in str(error), error
        assign_spool_location(second.spool_id, printer_id=pid,
                              slot="AMS-2")


def test_slot_snapshot_in_payload(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        jid, pid, sid, _ = _ready_job(
            test_client, tmp_path, monkeypatch)
        proposed = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/propose",
            json={"actor": "b575-test"}).json()
        _approve_proposal(test_client, proposed["proposal_id"])
        queued = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/enqueue", json={}).json()
        tasks = test_client.get("/api/v1/tasks").json()
        mine = [task for task in tasks
                if task["id"] == queued["task_id"]][0]
        assert mine["payload"]["slot"] == "AMS-2", mine["payload"]
        assert mine["payload"]["spool_material"] == "PLA", \
            mine["payload"]
        # Spoel verhuizen ná enqueue: snapshot blijft staan.
        test_client.post(f"/api/v1/filament/spools/{sid}/assign",
                         json={"printer_id": pid, "slot": "AMS-3"})
        tasks = test_client.get("/api/v1/tasks").json()
        mine = [task for task in tasks
                if task["id"] == queued["task_id"]][0]
        assert mine["payload"]["slot"] == "AMS-2", mine["payload"]
        html = test_client.get("/3d").text
        assert "AMS-2" in html, "slot ontbreekt in UI"


def test_3d_final_markers(tmp_path, monkeypatch):
    from coordinator.app.workshop3d import create_fabjob
    for test_client in api(tmp_path, monkeypatch):
        jid, pid, sid, mid = _ready_job(
            test_client, tmp_path, monkeypatch)
        proposed = test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/propose",
            json={"actor": "b575-test"}).json()
        _approve_proposal(test_client, proposed["proposal_id"])
        test_client.post(
            f"/api/v1/workshop/fabjobs/{jid}/enqueue", json={})
        job2 = create_fabjob(mid, printer_id=pid, profile="fine-pla",
                             spool_id=sid, actor="b575-test")
        test_client.post(
            f"/api/v1/workshop/fabjobs/{job2['job_id']}/prepare",
            json={})
        test_client.post(
            f"/api/v1/workshop/fabjobs/{job2['job_id']}/slice",
            json={"slicer": "prusa-console"})
        test_client.post(
            f"/api/v1/workshop/fabjobs/{job2['job_id']}/propose",
            json={"actor": "b575-test"})
        test_client.post(
            f"/api/v1/workshop/fabjobs/{job2['job_id']}/preflight",
            json={})
        html = test_client.get("/3d").text
        for marker in ("Printer registreren", "profiel…",
                       "spoel…", "Compatibele profielen",
                       "werkplaatsbenodigdheden", "Annuleren",
                       "slot", "Wacht op exacte YES"):
            assert marker in html, marker
        assert "Slice (Bambu)" not in html, \
            "onbewezen Bambu-knop wordt aangeboden"
