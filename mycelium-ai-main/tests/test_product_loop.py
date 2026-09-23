"""Product loop tests: "Documenteer één object".

Poll → ingest → observation → VLM → candidates → IN_APP review,
JPG allowlist, write/verify gates (bestaand, onaangeroerd),
task-based Quest 1, campaign seeds, pure level derive.
"""

import os

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod

TOKEN = "loop-test-token-aaaaaaaa"


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "loop.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "loop-chat.db"))
    with TestClient(main_mod.app) as client:
        yield client


def _register_node(client, node_id="loop-node"):
    response = client.post("/api/v1/nodes/register", json={
        "node_id": node_id, "hostname": node_id, "tier": "seed",
        "capabilities": ["system_inventory"], "node_token": TOKEN})
    assert response.status_code == 201, response.text
    return node_id


def _register_cam(client, name="Loop cam"):
    response = client.post("/api/v1/cameras/register", json={
        "name": name, "kinds": ["snapshot"], "source": "phone"})
    assert response.status_code == 201, response.text
    return response.json()["device_id"]


def _write_inbox(filename: str, payload: bytes) -> str:
    from coordinator.app.cameras import camera_dir
    path = os.path.join(camera_dir(), filename)
    with open(path, "wb") as handle:
        handle.write(payload)
    return filename


def _bmp_bytes(seed: int = 0x20) -> bytes:
    from coordinator.app.cameras import camera_dir, write_bmp_24
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "loop-probe.bmp")
    write_bmp_24(tmp, 8, 8,
                 bytes([(seed + index) % 256 for index in
                        range(8 * 8 * 3)]))
    with open(tmp, "rb") as handle:
        return handle.read()


def _clean_inbox(*filenames: str) -> None:
    from coordinator.app.cameras import camera_dir
    for filename in filenames:
        try:
            os.remove(os.path.join(camera_dir(), filename))
        except OSError:
            pass


def _stash_foreign_inbox() -> str:
    """Move non-loop inbox files aside (shared temp dir): poll
    counts stay deterministic without ever deleting another
    operator's files. Returns the backup dir."""
    import os as _os
    import shutil as _shutil
    import tempfile as _tempfile
    from coordinator.app.cameras import camera_dir
    from coordinator.app.vision_ingest import MEDIA_SUFFIXES
    backup = _tempfile.mkdtemp(prefix="loop-inbox-stash-")
    try:
        entries = _os.listdir(camera_dir())
    except OSError:
        return backup
    for entry in entries:
        if entry.lower().endswith(MEDIA_SUFFIXES) \
                and not entry.startswith("loop-"):
            try:
                _shutil.move(_os.path.join(camera_dir(), entry),
                             _os.path.join(backup, entry))
            except OSError:
                pass
    return backup


def _restore_foreign_inbox(backup: str) -> None:
    """Move stashed foreign inbox files back. Best-effort."""
    import os as _os
    import shutil as _shutil
    from coordinator.app.cameras import camera_dir
    try:
        entries = _os.listdir(backup)
    except OSError:
        return
    for entry in entries:
        try:
            _shutil.move(_os.path.join(backup, entry),
                         _os.path.join(camera_dir(), entry))
        except OSError:
            pass
    try:
        _os.rmdir(backup)
    except OSError:
        pass


def _link_quest_task(quest_id: str, task_id: int) -> None:
    """Link a quest's first step to a real task (empty refs stay
    MISSING until then). save_quest path: no fake progress."""
    from coordinator.app.quests import get_quest, save_quest
    quest = get_quest(quest_id)
    assert quest is not None
    quest.steps[0].ref = str(task_id)
    save_quest(quest)


# -- POLL ---------------------------------------------------------------

def test_poll_new_file_ingested_once(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _stash = _stash_foreign_inbox()
        _register_node(client)
        device_id = _register_cam(client)
        name = "loop-once.jpg"
        _write_inbox(name, b"\xff\xd8\xff\xe0" + bytes(2000))
        try:
            first = client.post(
                f"/api/v1/cameras/{device_id}/poll-inbox")
            assert first.status_code == 200, first.text
            body = first.json()
            assert body["session_id"]
            assert len(body["ingested"]) == 1
            assert body["ingested"][0]["filename"] == name
            assert body["ingested"][0]["observation_id"]
            obs = client.get(
                f"/api/v1/cameras/{device_id}/observations").json()
            assert any(item["observation_id"] ==
                       body["ingested"][0]["observation_id"]
                       for item in obs)
            second = client.post(
                f"/api/v1/cameras/{device_id}/poll-inbox")
            assert second.status_code == 200, second.text
            again = second.json()
            assert again["ingested"] == []
            assert again["session_id"] == ""
            assert name in again["duplicates"]
        finally:
            _restore_foreign_inbox(_stash)
            _clean_inbox(name)


def test_poll_duplicate_sha_across_names_skipped(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _stash = _stash_foreign_inbox()
        _register_node(client)
        device_id = _register_cam(client)
        blob = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 8
        first_name, second_name = "loop-dup-a.jpg", "loop-dup-b.jpg"
        _write_inbox(first_name, blob)
        try:
            one = client.post(
                f"/api/v1/cameras/{device_id}/poll-inbox").json()
            assert len(one["ingested"]) == 1
            _write_inbox(second_name, blob)
            two = client.post(
                f"/api/v1/cameras/{device_id}/poll-inbox").json()
            assert two["ingested"] == []
            assert second_name in two["duplicates"]
        finally:
            _restore_foreign_inbox(_stash)
            _clean_inbox(first_name, second_name)


def test_poll_caps_at_eight(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _stash = _stash_foreign_inbox()
        _register_node(client)
        device_id = _register_cam(client)
        names = [f"loop-cap-{index}.jpg" for index in range(9)]
        try:
            for index, name in enumerate(names):
                _write_inbox(name, b"\xff\xd8\xff" + bytes([index]) * 3000)
            body = client.post(
                f"/api/v1/cameras/{device_id}/poll-inbox").json()
            assert len(body["ingested"]) == 8
            rest = client.post(
                f"/api/v1/cameras/{device_id}/poll-inbox").json()
            assert len(rest["ingested"]) == 1
        finally:
            _restore_foreign_inbox(_stash)
            _clean_inbox(*names)


def test_poll_multiple_files_and_unknown_device(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        _stash = _stash_foreign_inbox()
        _register_node(client)
        device_id = _register_cam(client)
        names = ["loop-multi-a.jpg", "loop-multi-b.png"]
        try:
            _write_inbox(names[0], b"\xff\xd8\xff" + bytes(2000))
            _write_inbox(names[1], _bmp_bytes(seed=0x31))
            body = client.post(
                f"/api/v1/cameras/{device_id}/poll-inbox").json()
            assert {item["filename"] for item in body["ingested"]} == \
                set(names)
            missing = client.post("/api/v1/cameras/cam-missing/poll-inbox")
            assert missing.status_code == 404
        finally:
            _restore_foreign_inbox(_stash)
            _clean_inbox(*names)


def test_poll_refused_file_never_proposes(tmp_path, monkeypatch):
    from coordinator.app.knowledge import list_candidates
    for client in make_client(tmp_path, monkeypatch):
        _stash = _stash_foreign_inbox()
        _register_node(client)
        device_id = _register_cam(client)
        name = "loop-huge.jpg"
        try:
            _write_inbox(name, b"\xff" * (10 * 1024 * 1024 + 8))
            before = len(list_candidates(limit=200))
            body = client.post(
                f"/api/v1/cameras/{device_id}/poll-inbox").json()
            assert body["ingested"] == []
            assert body["refused"]
            assert len(list_candidates(limit=200)) == before
            again = client.post(
                f"/api/v1/cameras/{device_id}/poll-inbox").json()
            assert again["ingested"] == []
        finally:
            _restore_foreign_inbox(_stash)
            _clean_inbox(name)


def test_poll_malformed_jpg_fails_closed(tmp_path, monkeypatch):
    from coordinator.app.camera_ecosystem import propose_candidates
    from coordinator.app.knowledge import list_candidates
    for client in make_client(tmp_path, monkeypatch):
        _stash = _stash_foreign_inbox()
        _register_node(client)
        device_id = _register_cam(client)
        name = "loop-broken.jpg"
        try:
            _write_inbox(name, b"dit is geen jpeg, alleen tekst")
            body = client.post(
                f"/api/v1/cameras/{device_id}/poll-inbox").json()
            assert len(body["ingested"]) == 1
            observation_id = body["ingested"][0]["observation_id"]
            before = len(list_candidates(limit=200))
            created = propose_candidates(observation_id)
            assert created == []
            assert len(list_candidates(limit=200)) == before
        finally:
            _restore_foreign_inbox(_stash)
            _clean_inbox(name)


def test_poll_real_analysis_yields_in_app_review(tmp_path, monkeypatch):
    from coordinator.app.vision_flow import (
        VisionAnalysisRecord,
        save_analysis,
    )
    from coordinator.app.vision_provider import VisionRequest, build_result
    for client in make_client(tmp_path, monkeypatch):
        _stash = _stash_foreign_inbox()
        node_id = _register_node(client)
        device_id = _register_cam(client)
        name = "loop-real.jpg"
        try:
            _write_inbox(name, b"\xff\xd8\xff\xe0" + bytes(2000))
            body = client.post(
                f"/api/v1/cameras/{device_id}/poll-inbox").json()
            observation_id = body["ingested"][0]["observation_id"]
            request = VisionRequest(
                observation_id=observation_id, device_id=device_id,
                media_ref=name, question="Wat zie je?")
            result = build_result(
                request, "label: moer (0.8)\nEen metalen moer.",
                "test-only")
            save_analysis(VisionAnalysisRecord(
                analysis_id=result.analysis_id,
                observation_id=observation_id, device_id=device_id,
                result=result.model_dump(mode="json"),
                created_at=result.observed_at))
            proposed = client.post(
                f"/api/v1/observations/{observation_id}/propose-candidates")
            assert proposed.status_code == 201, proposed.text
            assert proposed.json()["candidates"]
            notes = client.get("/api/v1/notifications",
                               params={"node_id": node_id}).json()
            # Bestaand contract: de kind reist in titel/body, type
            # is de severity (approval_required voor
            # candidate_waiting). IN_APP is het kanaal.
            assert any("candidate" in note["title"].lower()
                       for note in notes)
            assert any(note["type"] == "approval_required"
                       for note in notes)
        finally:
            _restore_foreign_inbox(_stash)
            _clean_inbox(name)


# -- MEDIA --------------------------------------------------------------

def test_media_allowlist_and_mime():
    from coordinator.app.observations import check_image_ref
    from coordinator.app.vision_ingest import MEDIA_SUFFIXES, _mime_for
    for accepted in ("a.bmp", "a.png", "a.jpg", "a.jpeg",
                     "FOTO.JPG", "scan.JPEG"):
        assert check_image_ref(accepted) == accepted.strip()
    assert set(MEDIA_SUFFIXES) == {".bmp", ".png", ".jpg", ".jpeg"}
    assert _mime_for("a.jpg") == "image/jpeg"
    assert _mime_for("a.jpeg") == "image/jpeg"
    assert _mime_for("a.png") == "image/png"
    assert _mime_for("a.bmp") == "image/bmp"
    for rejected in ("a.heic", "a.mp4", "a.mov", "a.stl", "a.exe",
                     "a.png.exe", "../x.jpg", "/abs/x.jpg",
                     "C:\\w\\x.jpg", "sub/dir/x.jpg", "x",
                     "http://x/y.jpg"):
        with pytest.raises(ValueError):
            check_image_ref(rejected)


def test_media_vision_mime_and_gates(tmp_path, monkeypatch):
    from coordinator.app.vision_ingest import MAX_MEDIA_BYTES, media_facts
    from coordinator.app.vision_provider import read_vision_media
    for _ in make_client(tmp_path, monkeypatch):
        from coordinator.app.cameras import camera_dir
        jpg = os.path.join(camera_dir(), "loop-mime.jpg")
        with open(jpg, "wb") as handle:
            handle.write(b"\xff\xd8\xff\xe0" + bytes(500))
        try:
            assert media_facts("loop-mime.jpg").mime_type == \
                "image/jpeg"
            _, mime = read_vision_media("loop-mime.jpg")
            assert mime == "image/jpeg"
            for evil in ("../loop-mime.jpg", "/abs/loop-mime.jpg",
                         "C:\\w\\loop-mime.jpg", "sub/x.jpg"):
                with pytest.raises(Exception):
                    media_facts(evil)
            big = os.path.join(camera_dir(), "loop-big.jpg")
            with open(big, "wb") as handle:
                handle.write(b"\xff" * (MAX_MEDIA_BYTES + 8))
            try:
                with pytest.raises(Exception):
                    media_facts("loop-big.jpg")
            finally:
                try:
                    os.remove(big)
                except OSError:
                    pass
        finally:
            try:
                os.remove(jpg)
            except OSError:
                pass


# -- SECURITY (bestaande gates, onaangeroerd) -----------------------------

def _ai_provenance():
    from coordinator.app.inventory_read import Provenance
    return Provenance(source_type="ai-generated", creator_id="qwen",
                      human_verified=False)


def test_security_exact_yes_and_fingerprint():
    from coordinator.app.controlled_writes import (
        decide_write,
        revalidate,
        request_write_approval,
    )
    from coordinator.app.inventory_writes import propose_inventory_write
    proposal = propose_inventory_write(
        "wrt-loop-obj", "create", "object", {"name": "moer"})
    request = request_write_approval(proposal)
    approved = decide_write(request, proposal, "YES",
                            decided_by="jelles")
    assert approved.approved is True
    for response in ("yes", "Yes", "NO", "JA", "", "OK"):
        denied = decide_write(
            request_write_approval(proposal), proposal, response)
        assert denied.approved is False
    tampered = proposal.model_copy(
        update={"payload": dict(proposal.payload, extra=True)})
    with pytest.raises(ValueError):
        revalidate(tampered, approved)
    with pytest.raises(ValueError):
        revalidate(proposal, approved.model_copy(
            update={"fingerprint": "0" * 64}))


def test_security_ttl_and_revalidate_required():
    import asyncio
    from datetime import datetime, timedelta, timezone
    from coordinator.app.controlled_writes import (
        decide_write,
        is_stale,
        revalidate,
        request_write_approval,
    )
    from coordinator.app.inventory_writes import (
        InventoryWriteRefusedError,
        execute_inventory_write,
        propose_inventory_write,
    )
    proposal = propose_inventory_write(
        "wrt-loop-ttl", "create", "object", {"name": "moer"})
    assert is_stale(proposal) is False
    future = (datetime.now(timezone.utc)
              + timedelta(seconds=7200)).isoformat()
    assert is_stale(proposal, future) is True
    with pytest.raises(ValueError):
        decide_write(request_write_approval(proposal), proposal,
                     "YES", now_str=future)
    rejected = decide_write(request_write_approval(proposal),
                            proposal, "NO")
    with pytest.raises(ValueError):
        revalidate(proposal, rejected)
    with pytest.raises((ValueError, InventoryWriteRefusedError,
                        TypeError)):
        asyncio.run(execute_inventory_write(
            proposal, rejected, reader=None, writer=None))


def test_security_object_file_independent():
    from coordinator.app.controlled_writes import (
        decide_write,
        revalidate,
        request_write_approval,
    )
    from coordinator.app.inventory_writes import propose_inventory_write
    obj = propose_inventory_write(
        "wrt-loop-o", "create", "object", {"name": "moer"})
    fil = propose_inventory_write(
        "wrt-loop-f", "create", "file",
        {"name": "moer.jpg", "file_kind": "image",
         "mime_type": "image/jpeg", "sha256": "a" * 64,
         "size_bytes": 12})
    obj_ok = decide_write(request_write_approval(obj), obj, "YES")
    fil_ok = decide_write(request_write_approval(fil), fil, "YES")
    assert revalidate(obj, obj_ok)
    assert revalidate(fil, fil_ok)
    with pytest.raises(ValueError):
        revalidate(obj, fil_ok)
    with pytest.raises(ValueError):
        revalidate(fil, obj_ok)


def test_security_verification_needs_readback():
    from coordinator.app.vision_flow import verify_observation
    from coordinator.app.verification import is_verified
    from coordinator.app.vision_flow import (
        new_observation_verification_request,
    )
    from coordinator.app.cameras import new_observation
    observation = new_observation(
        "obs-loop1", "cam-loop1", "snapshot", media_ref="a.jpg")
    request = new_observation_verification_request(
        "wrt-loop1", "f" * 64, observation)
    missing = verify_observation(request, None, media_exists=False)
    assert missing.outcome == "inconclusive"
    assert is_verified(missing) is False
    gone = verify_observation(request, observation, media_exists=False)
    assert gone.outcome == "failed"
    assert is_verified(gone) is False
    passed = verify_observation(request, observation, media_exists=True)
    assert passed.outcome == "passed"
    assert is_verified(passed) is True


def test_security_ai_generated_stays_unverified():
    from coordinator.app.inventory_writes import build_create_payload
    body = build_create_payload("object", {"name": "moer"})
    assert body["provenance"]["human_verified"] is False
    from coordinator.app.controlled_writes import propose_write
    from coordinator.app.inventory_read import Provenance
    with pytest.raises(ValueError):
        propose_write("wrt-loop-bad", "inventory.create",
                      "inventory:object", {}, actor="x",
                      provenance=Provenance(
                          source_type="ai-generated", creator_id="x",
                          human_verified=True))
    from coordinator.app.vision_flow import vision_to_object_proposal
    from coordinator.app.vision_provider import VisionRequest, build_result
    request = VisionRequest(observation_id="obs-loop9",
                            device_id="cam-loop9", media_ref="a.jpg")
    empty = build_result(request, "alleen wat tekst", "test-only")
    with pytest.raises(ValueError):
        vision_to_object_proposal(empty, None,
                                  proposal_id="wrt-loop9")


# -- QUEST / CAMPAIGN ----------------------------------------------------

def _complete_task(client, kind="documenteer-object"):
    created = client.post("/api/v1/tasks", json={
        "kind": kind, "payload": {}}).json()
    task_id = created["id"]
    from coordinator.app.database import connection
    with connection() as db:
        db.execute("UPDATE tasks SET status='completed', "
                   "completed_at='2026-01-01T00:00:00+00:00' "
                   "WHERE id=?", (task_id,))
    return task_id


def test_quest_task_completes_entity_waits(tmp_path, monkeypatch):
    from coordinator.app.quests import (
        derive_step_state,
        get_quest,
        new_quest,
        quest_detail,
        save_quest,
    )
    for client in make_client(tmp_path, monkeypatch):
        task_id = _complete_task(client)
        quest = new_quest("Q taak", [{
            "key": "doc", "label": "Documenteer", "kind": "task",
            "ref": ""}])
        save_quest(quest)
        _link_quest_task(quest.quest_id, task_id)
        detail = quest_detail(get_quest(quest.quest_id))
        assert detail["state"] == "COMPLETED"
        entity = new_quest("Q entity", [{
            "key": "link", "label": "Koppel obj_x", "kind": "entity",
            "ref": "obj_demo"}])
        save_quest(entity)
        step = derive_step_state(entity.steps[0])
        assert step["state"] == "WAITING"


def test_campaign_chain_quest2_ready_after_quest1(tmp_path, monkeypatch):
    from coordinator.app.campaigns import (
        campaign_detail,
        ensure_foundation_seeds,
        get_campaign,
    )
    from coordinator.app.guide import guide_items
    from coordinator.app.quests import get_quest, quest_detail, save_quest
    for client in make_client(tmp_path, monkeypatch):
        seeds = ensure_foundation_seeds()
        assert set(seeds["campaigns"]) == {
            "🌱 Solar Punk Foundation", "👁 Observation Inbox",
            "🧠 Improve Mycelium D–H"}
        assert len(seeds["quests"]) == 10
        again = ensure_foundation_seeds()
        assert again == seeds
        q1_id = seeds["quests"]["Documenteer één object"]
        q2_id = seeds["quests"][
            "Repareer/hergebruik iets + foto-bewijs"]
        task_id = _complete_task(client)
        _link_quest_task(q1_id, task_id)
        assert quest_detail(get_quest(q1_id))["state"] == "COMPLETED"
        campaign = get_campaign(
            seeds["campaigns"]["🌱 Solar Punk Foundation"])
        detail = campaign_detail(campaign)
        assert detail["current_quest"]["quest_id"] == q2_id
        assert detail["next_action"]["quest_id"] == q2_id
        assert detail["next_action"]["href"].startswith("/")
        items = guide_items(limit=20)
        for item in items:
            assert item["next"]["href"].startswith("/")


def test_campaign_deleted_quest_missing(tmp_path, monkeypatch):
    from coordinator.app.campaigns import campaign_detail, get_campaign
    from coordinator.app.quests import delete_quest, get_quest
    for client in make_client(tmp_path, monkeypatch):
        from coordinator.app.campaigns import ensure_foundation_seeds
        seeds = ensure_foundation_seeds()
        victim = seeds["quests"]["Inbox legen via poll"]
        assert delete_quest(victim) is True
        assert get_quest(victim) is None
        campaign = get_campaign(
            seeds["campaigns"]["👁 Observation Inbox"])
        detail = campaign_detail(campaign)
        states = [view["state"] for view in detail["quests"]]
        assert "MISSING" in states


# -- MISSION SEEDS (data-only, geen voortgang) ------------------------------

def test_mission_seeds_draft_and_waiting(tmp_path, monkeypatch):
    from coordinator.app.campaigns import ensure_mission_seeds
    from coordinator.app.missions import load_mission
    from coordinator.app.quests import get_quest, quest_detail
    for _ in make_client(tmp_path, monkeypatch):
        seeds = ensure_mission_seeds()
        assert len(seeds["missions"]) == 6
        assert len(seeds["quests"]) == 6
        assert len(seeds["campaigns"]) == 1
        assert ensure_mission_seeds() == seeds
        for mid in seeds["missions"].values():
            assert load_mission(mid).status == "draft"
        for qid in seeds["quests"].values():
            assert quest_detail(get_quest(qid))["state"] == \
                "WAITING"


def test_mission_seeds_future_honest(tmp_path, monkeypatch):
    from coordinator.app.campaigns import ensure_mission_seeds
    from coordinator.app.missions import load_mission
    for _ in make_client(tmp_path, monkeypatch):
        seeds = ensure_mission_seeds()
        future = [mid for title, mid in
                  seeds["missions"].items()
                  if "FUTURE" in title]
        assert len(future) == 1
        mission = load_mission(future[0])
        assert mission.status == "draft"
        assert "FUTURE" in (mission.context_records[0].get(
            "note", "") + mission.goal)


def test_mission_seeds_grow_fungi(tmp_path, monkeypatch):
    from coordinator.app.campaigns import ensure_mission_seeds
    from coordinator.app.world import derive_fungi_network
    for _ in make_client(tmp_path, monkeypatch):
        before = derive_fungi_network(limit=120)["total"]
        seeds = ensure_mission_seeds()
        after = derive_fungi_network(limit=120)
        assert after["total"] > before
        assert after["counts"]["quest"] >= 6
        assert after["counts"]["campaign"] >= 1
        ids = {node["id"] for node in after["nodes"]}
        for qid in seeds["quests"].values():
            assert f"fungi-quest-{qid}" in ids


# -- FABRICATION SEEDS (data-only, geen voortgang) -------------------------

def test_fabrication_seeds_draft_and_waiting(tmp_path, monkeypatch):
    from coordinator.app.campaigns import (
        ensure_fabrication_seeds,
        ensure_mission_seeds,
    )
    from coordinator.app.missions import load_mission
    from coordinator.app.quests import get_quest, quest_detail
    for _ in make_client(tmp_path, monkeypatch):
        seeds = ensure_fabrication_seeds()
        assert len(seeds["missions"]) == 4
        assert len(seeds["quests"]) == 4
        assert len(seeds["campaigns"]) == 1
        assert ensure_fabrication_seeds() == seeds
        for mid in seeds["missions"].values():
            mission = load_mission(mid)
            assert mission.status == "draft"
            assert len(mission.steps) >= 1
        for qid in seeds["quests"].values():
            assert quest_detail(get_quest(qid))["state"] == \
                "WAITING"
        other = ensure_mission_seeds()
        assert len(other["missions"]) == 6
        assert set(seeds["missions"].values()).isdisjoint(
            set(other["missions"].values()))


def test_fabrication_seeds_grow_fungi(tmp_path, monkeypatch):
    from coordinator.app.campaigns import ensure_fabrication_seeds
    from coordinator.app.world import derive_fungi_network
    for _ in make_client(tmp_path, monkeypatch):
        before = derive_fungi_network(limit=200)["total"]
        seeds = ensure_fabrication_seeds()
        after = derive_fungi_network(limit=200)
        assert after == derive_fungi_network(limit=200)
        assert after["total"] > before
        assert after["counts"]["quest"] >= 4
        assert after["counts"]["campaign"] >= 1
        ids = {node["id"] for node in after["nodes"]}
        for qid in seeds["quests"].values():
            assert f"fungi-quest-{qid}" in ids


# -- LEVEL -----------------------------------------------------------------

def test_level_pure_deterministic_unknown():
    from coordinator.app.game import derive_level
    first = derive_level(verified_objects=1, verified_files=1,
                         completed_quests=0)
    assert first == derive_level(verified_objects=1,
                                 verified_files=1,
                                 completed_quests=0)
    assert first["level"] == "ROOTED"
    assert first["provenance"] == "derived"
    assert derive_level()["level"] == "SEEDLING"
    grove = derive_level(verified_objects=5, verified_files=5,
                         completed_quests=2)
    assert grove["level"] == "GROVE"
    unknown = derive_level(verified_objects=None,
                           verified_files=0, completed_quests=0)
    assert unknown["level"] == "SEEDLING"
    assert any("UNKNOWN" in line for line in unknown["evidence"])
    zero = derive_level(verified_objects=0, verified_files=0,
                        completed_quests=0)
    assert zero["level"] == "SEEDLING"
    assert zero["evidence"] != unknown["evidence"]


def test_level_has_no_side_effects(tmp_path, monkeypatch):
    from coordinator.app.game import derive_level
    from coordinator.app.quests import list_quests
    for _ in make_client(tmp_path, monkeypatch):
        before = len(list_quests(limit=100))
        derive_level(verified_objects=3, verified_files=3,
                     completed_quests=1)
        derive_level(verified_objects=None)
        assert len(list_quests(limit=100)) == before
