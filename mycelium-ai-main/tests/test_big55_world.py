"""BIG55 world backend: chests, NPC settlement, flags, clock.
Game-owned state only; ownership and bounds enforced; nothing
touches INVENTory or backend records."""

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "b55.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "b55-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", "b55-operator")
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://127.0.0.1:9")
    with TestClient(main_mod.app) as test_client:
        yield test_client


def _session(test_client):
    return test_client.post("/api/v1/play/session", json={}).json()[
        "session_id"]


def _rich(test_client, sid):
    for node in ("stump-1", "stump-2", "stump-3", "stump-4",
                 "fiber-1", "rock-1"):
        test_client.post("/api/v1/play/gather", json={
            "session_id": sid, "node_id": node})


def test_flags_roundtrip(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        sid = _session(test_client)
        empty = test_client.get(
            "/api/v1/play/flags",
            params={"session_id": sid}).json()
        assert empty["flags"] == []
        assert test_client.get(
            "/api/v1/play/flags",
            params={"session_id": "play_nope"}).status_code == 404
        set1 = test_client.post("/api/v1/play/flags", json={
            "session_id": sid, "flag": "housed"}).json()
        assert set1["set"] is True
        again = test_client.post("/api/v1/play/flags", json={
            "session_id": sid, "flag": "housed"}).json()
        assert again["set"] is True
        bad = test_client.post("/api/v1/play/flags", json={
            "session_id": sid, "flag": "rm -rf"})
        assert bad.status_code == 422
        unknown = test_client.post("/api/v1/play/flags", json={
            "session_id": sid, "flag": "fly"})
        assert unknown.status_code == 422
        listed = test_client.get(
            "/api/v1/play/flags",
            params={"session_id": sid}).json()["flags"]
        assert listed == ["housed"]


def test_chest_deposit_withdraw_ownership(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        sid = _session(test_client)
        other = _session(test_client)
        for node in ("stump-1", "stump-2", "stump-3", "stump-4",
                     "stump-5", "stump-6", "stump-7", "stump-8",
                     "fiber-1", "rock-1", "rock-2"):
            test_client.post("/api/v1/play/gather", json={
                "session_id": sid, "node_id": node})
        made = test_client.post("/api/v1/play/craft", json={
            "session_id": sid, "recipe": "chest"})
        assert made.status_code == 200, made.text
        placed = test_client.post("/api/v1/play/place", json={
            "session_id": sid, "kind": "chest", "x": 300,
            "y": 452}).json()
        cid = placed["build_id"]
        assert test_client.get(
            "/api/v1/play/chest",
            params={"session_id": other,
                    "chest_id": cid}).status_code == 404
        empty = test_client.get(
            "/api/v1/play/chest",
            params={"session_id": sid, "chest_id": cid}).json()
        assert empty["items"] == {}
        dep = test_client.post("/api/v1/play/chest/deposit",
                               json={"session_id": sid,
                                     "chest_id": cid,
                                     "item": "wood", "qty": 2}).json()
        assert dep["deposited"] is True
        over = test_client.post("/api/v1/play/chest/deposit",
                                json={"session_id": sid,
                                      "chest_id": cid,
                                      "item": "wood", "qty": 99})
        assert over.status_code == 422
        out = test_client.post("/api/v1/play/chest/withdraw",
                               json={"session_id": sid,
                                     "chest_id": cid, "item": "wood",
                                     "qty": 5})
        assert out.status_code == 422
        back = test_client.post("/api/v1/play/chest/withdraw",
                                json={"session_id": sid,
                                      "chest_id": cid, "item": "wood",
                                      "qty": 1}).json()
        assert back["withdrawn"] is True
        final = test_client.get(
            "/api/v1/play/chest",
            params={"session_id": sid, "chest_id": cid}).json()
        assert final["items"] == {"wood": 1}


def test_npc_assign_validation(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        sid = _session(test_client)
        for node in ("stump-1", "stump-2", "stump-3", "stump-4",
                     "stump-5", "stump-6", "stump-7", "stump-8",
                     "stump-9", "stump-10", "fiber-1", "rock-1",
                     "rock-2"):
            res = test_client.post("/api/v1/play/gather", json={
                "session_id": sid, "node_id": node})
            assert res.status_code == 200, res.text
        assert test_client.post("/api/v1/play/npc/assign", json={
            "session_id": sid, "npc_id": "dragon",
            "house_build_id": "bld_x"}).status_code == 422
        no_room = test_client.post("/api/v1/play/npc/assign",
                                   json={"session_id": sid,
                                         "npc_id": "smid",
                                         "house_build_id": "bld_x"})
        assert no_room.status_code == 422
        for recipe in ("plank", "plank", "fence", "fence",
                       "room"):
            made = test_client.post("/api/v1/play/craft", json={
                "session_id": sid, "recipe": recipe})
            assert made.status_code == 200, made.text
        room = test_client.post("/api/v1/play/place", json={
            "session_id": sid, "kind": "room", "x": 300,
            "y": 420})
        assert room.status_code == 200, room.text
        hid = room.json()["build_id"]
        done = test_client.post("/api/v1/play/npc/assign", json={
            "session_id": sid, "npc_id": "smid",
            "house_build_id": hid}).json()
        assert done["settled"] is True
        clash = test_client.post("/api/v1/play/npc/assign", json={
            "session_id": sid, "npc_id": "mos",
            "house_build_id": hid})
        assert clash.status_code == 422
        listed = test_client.get(
            "/api/v1/play/npc",
            params={"session_id": sid}).json()["npc"]
        assert [n for n in listed if n["npc_id"] == "smid"]


def test_clock_tick_and_phase(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        sid = _session(test_client)
        first = test_client.post("/api/v1/play/clock/tick",
                                 json={
                                     "session_id": sid}).json()
        assert (first["day"], first["minute"]) == (1, 480)
        assert first["phase"] == "day"
        assert first["advanced"] is False
        second = test_client.post("/api/v1/play/clock/tick",
                                  json={
                                      "session_id": sid}).json()
        assert second["advanced"] is False
        assert (second["day"], second["minute"]) == (1, 480)
        assert test_client.post(
            "/api/v1/play/clock/tick",
            json={"session_id": "play_nope"}).status_code == 404


def test_notes_roundtrip(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        sid = _session(test_client)
        assert test_client.post("/api/v1/play/notes", json={
            "session_id": sid, "key": "hydro_q",
            "text": "Water eerst.", "priority": True}).json()[
                "saved"] is True
        notes = test_client.get(
            "/api/v1/play/notes",
            params={"session_id": sid}).json()["notes"]
        assert notes[0]["key"] == "hydro_q"
        assert notes[0]["priority"] == 1
        bad = test_client.post("/api/v1/play/notes", json={
            "session_id": sid, "key": "BAD KEY!",
            "text": "x"})
        assert bad.status_code == 422
        assert test_client.get(
            "/api/v1/play/notes",
            params={"session_id": "play_nope"}).status_code == 404


def test_mast_and_new_items(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        sid = _session(test_client)
        for node in ("scrap-1", "scrap-2", "crystal-9",
                     "fiber-9", "reed-1", "rock-9"):
            res = test_client.post("/api/v1/play/gather", json={
                "session_id": sid, "node_id": node})
            assert res.status_code in (200, 422), res.text
        made = test_client.post("/api/v1/play/craft", json={
            "session_id": sid, "recipe": "mast"})
        assert made.status_code == 200, made.text
        placed = test_client.post("/api/v1/play/place", json={
            "session_id": sid, "kind": "mast", "x": 2500,
            "y": 452}).json()
        assert placed["placed"] is True
        lamp = test_client.post("/api/v1/play/craft", json={
            "session_id": sid, "recipe": "lamp"})
        assert lamp.status_code == 422  # crystal verbruikt


def test_side_big55_markers(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        html = test_client.get("/side").text
        for marker in ("play/chest", "play/npc", "play/flags",
                       "play/clock", "play/notes", "REGIONS",
                       "NPCS", "ENCOUNTERS", "EVENTS",
                       "worldClock", "openChest", "hotbar",
                       "invOverlay", "Undergrove", "Moeraslab",
                       "Outpost", "questBoard", "RUIN_MACHINE",
                       "MODDERHART", "activeEvents",
                       "npcComputer", "npc/assign"):
            assert marker in html, marker
