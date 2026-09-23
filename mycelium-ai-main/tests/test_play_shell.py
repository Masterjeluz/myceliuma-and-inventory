"""Fase 1 play-shell tests: /play is read-only en speelbaar.

Alleen korte foreground-checks: status, canvas, input-hooks,
collision- en interactielogica, Luma, HUD met live data.
Geen mutatie: quest-aantal voor/na is gelijk.
"""

import json
import os
import re

import pytest
from fastapi.testclient import TestClient

import coordinator.app.main as main_mod


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "play.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "play-chat.db"))
    with TestClient(main_mod.app) as client:
        yield client


def _page(tmp_path, monkeypatch) -> str:
    for client in make_client(tmp_path, monkeypatch):
        response = client.get("/play")
        assert response.status_code == 200, response.text
        return response.text
    raise AssertionError("no client")


def test_play_200_and_canvas(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    assert '<canvas id="stage"' in html
    assert 'role="img"' in html
    assert "/play" in html  # NAV-link aanwezig


def test_play_javascript_loads(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    assert "requestAnimationFrame" in html
    assert "addEventListener" in html
    assert "getContext" in html


def test_play_keys_bound(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    for key in ("ArrowUp", "ArrowDown", "ArrowLeft",
                "ArrowRight", '"a"', '"w"', '"s"', '"e"',
                '"E"', '"Escape"', "toLowerCase",
                'keys["arrowup"]', "preventDefault"):
        assert key in html, key


def test_play_collision_logic(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    assert "function collide" in html
    assert "circleHitsRect" in html
    assert "WALLS" in html
    assert "SOLIDS" in html
    match_w = re.search(r"WORLD_W = (\d+)", html)
    match_h = re.search(r"WORLD_H = (\d+)", html)
    assert match_w and match_h
    assert int(match_w.group(1)) > 960  # wereld > viewport
    assert int(match_h.group(1)) > 600


def test_play_interaction_and_luma(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    assert "function nearestNpc" in html
    assert "Luma" in html
    assert "[E] Praat met " in html
    assert "Hey Jelles. Er is hier nog veel te ontdekken." in html
    assert 'role="dialog"' in html
    assert "interactiezone" in html.lower() or "radius" in html
    assert "placeholder" in html  # eerlijk: geen fake AI


def test_play_hud_and_live_data(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    assert 'id="play-hud"' in html
    assert "PLAYDATA" in html
    match = re.search(r"const PLAYDATA = (\{.*?\});", html,
                      re.DOTALL)
    assert match, "PLAYDATA niet gevonden"
    data = json.loads(match.group(1))
    assert {"world", "quest", "counts"} <= set(data)
    assert "luma" in data and "reason" in data["luma"]


def test_play_dialog_choices(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    for choice in ("Bestanden bekijken", "Analyse starten",
                   "Missievoorstel", "Sluiten", "Bekijk",
                   "Wat kun je?", "Help mij iets te printen",
                   "Later"):
        assert choice in html, choice
    for view in ("panel", "files", "lumaflow", "candidates",
                 "candidate", "proposal", "worldchanged",
                 "mission", "print", "abilities", "later"):
        assert view in html, view
    assert 'id="dialog-body"' in html
    assert 'id="dialog-choices"' in html


def test_play_luma_flow_markers(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    for marker in ("Kandidaat bekijken", "Maak voorstel",
                   "YES — uitvoeren", "Controleren",
                   "Wereld veranderd", "Ververs wereld",
                   "APPROVAL REQUIRED", "Stap:",
                   "flow.steps", "renderCandidates",
                   "renderCandidateDetail", "renderProposal",
                   "renderWorldChanged", "renderFiles"):
        assert marker in html, marker


def test_play_inbox_facts_route(tmp_path, monkeypatch):
    import os as _os
    from coordinator.app.cameras import camera_dir
    name = "loop-facts-probe.jpg"
    path = _os.path.join(camera_dir(), name)
    try:
        with open(path, "wb") as handle:
            handle.write(b"\xff\xd8\xff\xe0" + bytes(2000))
        for client in make_client(tmp_path, monkeypatch):
            ok = client.get(f"/api/v1/inbox/{name}/facts",
                            params={"device_id": "cam-loop"})
            assert ok.status_code == 200, ok.text
            body = ok.json()
            assert body["media"]["sha256"]
            assert body["file_payload"]["sha256"] == \
                body["media"]["sha256"]
            missing = client.get("/api/v1/inbox/loop-niet.jpg/facts")
            assert missing.status_code == 422
            evil = client.get("/api/v1/inbox/../loop-facts-probe.jpg/facts")
            assert evil.status_code in (404, 422)
    finally:
        try:
            _os.remove(path)
        except OSError:
            pass


def test_play_forge_npc(tmp_path, monkeypatch):
    import json as _json
    import re as _re
    html = _page(tmp_path, monkeypatch)
    assert "Forge" in html
    assert "Fabrication" in html
    assert "NIET VERBONDEN" in html
    assert "print nooit automatisch" in html
    match = _re.search(r"const PLAYDATA = (\{.*?\});", html,
                      _re.DOTALL)
    npcs = _json.loads(match.group(1))["npcs"]
    assert {n["id"] for n in npcs} == {"luma", "forge"}
    forge = next(n for n in npcs if n["id"] == "forge")
    assert forge["panel"]["abilities"]
    assert forge["panel"]["tools"]
    assert "mission" in forge
    assert "familiar" in forge


def test_play_in_game_fetch_actions(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    for marker in ("fetch(", "/poll-inbox", "/describe",
                   "/prints/propose", "data-act=\"poll\"",
                   "data-act=\"describe\"",
                   "data-act=\"propose\""):
        assert marker in html, marker
    assert "zie /missions" not in html


def test_play_node_syntax(tmp_path, monkeypatch):
    import re as _re
    import shutil
    import subprocess
    import tempfile
    node = shutil.which("node")
    if node is None:
        pytest.skip("node niet beschikbaar")
    html = _page(tmp_path, monkeypatch)
    scripts = _re.findall(r"<script>(.*?)</script>", html,
                          _re.DOTALL)
    game = [s for s in scripts if "PLAYDATA" in s]
    assert len(game) == 1
    with tempfile.NamedTemporaryFile(
            "w", suffix=".js", delete=False,
            encoding="utf-8") as handle:
        handle.write(game[0])
        path = handle.name
    try:
        result = subprocess.run(
            [node, "--check", path], capture_output=True,
            timeout=60)
        assert result.returncode == 0, result.stderr.decode(
            "utf-8", "replace")[:500]
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def test_play_npc_panel_sections(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    for section in ("ABILITIES", "TOOLS", "MISSIONS", "EVIDENCE",
                    "STATUS", "Familiar-record"):
        assert section in html, section
    assert "Camera-inbox" in html
    assert "INVENTory" in html


def test_play_notification_center(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    assert 'id="notifs"' in html
    assert 'id="notifs-body"' in html
    assert '"n"' in html and '"N"' in html
    assert "Meldingen" in html
    assert "notif-open" in html


def test_play_guide_chip(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    assert 'id="guide-chip"' in html
    assert "Guide" in html


def test_play_world_structure(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    assert "Bosrand" in html
    assert "DIV_Y" in html
    assert "passable: true" in html
    assert "later: Verdant" in html
    assert "forge" in html.lower()
    match_h = re.search(r"WORLD_H = (\d+)", html)
    assert match_h and int(match_h.group(1)) > 1000


def test_play_luma_badge(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    assert 'id="npc-badge"' in html
    assert "luma" in html.lower()
    assert ".badge" in html or "badge" in html


def test_play_walk_feedback(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    assert "player.bob" in html
    assert "notifsOpen" in html


def test_fungi_derive_deterministic(tmp_path, monkeypatch):
    from coordinator.app.world import derive_fungi_network
    for _ in make_client(tmp_path, monkeypatch):
        first = derive_fungi_network(limit=120)
        assert first == derive_fungi_network(limit=120)
        assert first["provenance"]["source_type"] == "derived"
        assert first["nodes"][0]["id"] == "fungi-seed"
        assert first["total"] == len(first["nodes"])
        assert first["total"] <= 120


def test_fungi_derive_no_filler(tmp_path, monkeypatch):
    from coordinator.app.world import derive_fungi_network
    for _ in make_client(tmp_path, monkeypatch):
        net = derive_fungi_network(limit=120)
        assert net["total"] >= 1
        for node in net["nodes"]:
            assert set(node) == {"id", "branch", "glyph",
                                 "label", "href", "weight",
                                 "parent"}
            assert node["href"].startswith("/")


def test_play_fungi_panel(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    assert "Fungi-netwerk" in html
    assert "fungi-seed" in html or "Zaad" in html
    assert '"fungi"' in html  # PLAYDATA-sleutel


def test_play_js_has_no_escaped_quotes(tmp_path, monkeypatch):
    """Regressie: Python-escaped quotes (\\\") in het game-script
    breken de JS-parser en laten een leeg canvas achter."""
    import re as _re
    html = _page(tmp_path, monkeypatch)
    scripts = _re.findall(r"<script>(.*?)</script>", html,
                          _re.DOTALL)
    game = [s for s in scripts if "PLAYDATA" in s]
    assert len(game) == 1
    assert 'class=\\"' not in game[0]
    assert 'href=\\"' not in game[0]
    assert 'id=\\"' not in game[0]


def test_play_npc_familiars_exist(tmp_path, monkeypatch):
    from coordinator.app.familiars import (ensure_npc_familiars,
                                           familiar_can,
                                           list_familiars)
    for _ in make_client(tmp_path, monkeypatch):
        found = ensure_npc_familiars()
        assert set(found) == {"Luma", "Forge"}
        assert ensure_npc_familiars() == found
        by_name = {f.name: f for f in list_familiars()}
        assert by_name["Luma"].kind == "digital"
        assert by_name["Forge"].kind == "machine"
        assert by_name["Luma"].linked_id == ""
        # Soort-claims blijven eerlijk: geen snapshot voor Luma.
        assert familiar_can(by_name["Luma"],
                            "camera.snapshot") is False
        assert familiar_can(by_name["Forge"],
                            "machine.status") is True


def test_play_npc_panels_use_real_data(tmp_path, monkeypatch):
    import json as _json
    import re as _re
    from coordinator.app.campaigns import (
        ensure_fabrication_seeds,
        ensure_mission_seeds,
    )
    for client in make_client(tmp_path, monkeypatch):
        ensure_mission_seeds()
        ensure_fabrication_seeds()
        html = client.get("/play").text
        assert "placeholder in Fase" not in html
        match = _re.search(r"const PLAYDATA = (\{.*?\});", html,
                          _re.DOTALL)
        npcs = {n["id"]: n
                for n in _json.loads(match.group(1))["npcs"]}
        luma, forge = npcs["luma"], npcs["forge"]
        assert luma["familiar"]["id"].startswith("fam_")
        assert forge["familiar"]["id"].startswith("fam_")
        for ability in (luma["panel"]["abilities"]
                        + forge["panel"]["abilities"]):
            assert ability["type"] in ("DIGITAL", "PHYSICAL",
                                       "HYBRID")
            assert ability["available"]
            assert ability["via"]
        for tool in (luma["panel"]["tools"]
                     + forge["panel"]["tools"]):
            assert tool["state"]
            assert tool["detail"]
        luma_goals = [m["goal"] for m in
                      luma["panel"]["missions"]]
        assert "Documenteer één object" in luma_goals
        forge_goals = [m["goal"] for m in
                       forge["panel"]["missions"]]
        assert "Maak je eerste digitale prototype" in \
            forge_goals
        future = [m for m in luma["panel"]["missions"]
                  if "FUTURE" in m["goal"]]
        assert len(future) == 1
        assert future[0]["status"] == "draft"
        metas = [m.get("meta", m.get("status", ""))
                 for m in luma["mission"]["items"]]
        assert "beschikbaar" in metas


def test_play_is_read_only(tmp_path, monkeypatch):
    from coordinator.app.quests import list_quests
    for client in make_client(tmp_path, monkeypatch):
        before = len(list_quests(limit=100))
        assert client.get("/play").status_code == 200
        assert client.get("/play").status_code == 200
        assert len(list_quests(limit=100)) == before


# WORLD REPRESENTATION v1 ---------------------------------------------------


def _rep_records():
    return [
        {"entity_type": "hardware", "entity_id": "hw_a1",
         "title": "A1 Mini", "snippet": "printer",
         "provenance": {"source_type": "sensor-observed",
                        "creator_id": "seed-01",
                        "human_verified": False}},
        {"entity_type": "object", "entity_id": "obj_cube",
         "title": "Kubus", "snippet": "testobject",
         "provenance": {"source_type": "user",
                        "creator_id": "jelles",
                        "human_verified": True}},
        {"entity_type": "project", "entity_id": "proj_hydro",
         "title": "Hydro", "snippet": "",
         "provenance": {}},
        {"entity_type": "location", "entity_id": "loc_base",
         "title": "Homebase", "snippet": "",
         "provenance": {"source_type": "ai-generated",
                        "creator_id": "x",
                        "human_verified": False}},
    ]


def test_world_reps_from_real_records():
    from coordinator.app.world import derive_world_representations
    reps = derive_world_representations(_rep_records())
    assert len(reps) == 4
    by_source = {r["source_id"]: r for r in reps}
    # source_id bestaat en wijst terug naar het bronrecord.
    assert set(by_source) == {"hw_a1", "obj_cube", "proj_hydro",
                              "loc_base"}
    for rep in reps:
        assert rep["id"] == f"wrld-{rep['source_id']}"
        assert rep["source_type"] == "inventory"
        assert f"/world?entity_id={rep['source_id']}" == rep["href"]
        assert rep["interaction"] == "inspect"
        assert rep["zone"] == "homebase-workshop"
        assert set(rep) == {"id", "source_type", "source_id",
                            "entity_type", "kind", "zone", "x", "y",
                            "glyph", "label", "interaction", "href",
                            "status", "detail"}
    # Eerlijke statusafleiding uit provenance.
    assert by_source["hw_a1"]["status"] == "OBSERVED"
    assert by_source["hw_a1"]["kind"] == "MACHINE"
    assert by_source["obj_cube"]["status"] == "VERIFIED"
    assert by_source["obj_cube"]["kind"] == "OBJECT"
    assert by_source["proj_hydro"]["status"] == "REAL"
    assert by_source["proj_hydro"]["kind"] == "PROJECT"
    assert by_source["loc_base"]["status"] == "PROPOSED"
    assert by_source["loc_base"]["kind"] == "LOCATION"
    # Deterministisch: zelfde input, zelfde posities, binnen wereld.
    again = derive_world_representations(list(reversed(
        _rep_records())))
    assert [(r["x"], r["y"]) for r in again] == [
        (r["x"], r["y"]) for r in reps]
    for rep in reps:
        assert 40 <= rep["x"] <= 1600 - 40
        assert 40 <= rep["y"] <= 1000 - 20


def test_world_reps_refuse_and_dedupe():
    from coordinator.app.world import derive_world_representations
    assert derive_world_representations(None) == []
    assert derive_world_representations([]) == []
    recs = _rep_records() + [
        {"entity_type": "object", "entity_id": "obj_cube",
         "title": "DUPLICAAT", "snippet": "",
         "provenance": {}},
        {"entity_type": "drone", "entity_id": "drn_1",
         "title": "Niet op whitelist", "snippet": "",
         "provenance": {}},
        {"entity_type": "object", "entity_id": "zonderprefix",
         "title": "Geen prefix", "snippet": "",
         "provenance": {}},
        {"entity_type": "object", "entity_id": "xx_fake",
         "title": "Onbekend prefix", "snippet": "",
         "provenance": {}},
        "geen dict",
    ]
    reps = derive_world_representations(recs)
    assert len(reps) == 4
    assert [r["source_id"] for r in reps].count("obj_cube") == 1
    assert ("DUPLICAAT" not in
            [r["label"] for r in reps])


def test_world_reps_bounded():
    from coordinator.app.world import (REPR_SHELF,
                                       derive_world_representations)
    recs = [{"entity_type": "object",
             "entity_id": f"obj_{i:03d}", "title": f"ding {i}",
             "snippet": "", "provenance": {}}
            for i in range(30)]
    reps = derive_world_representations(recs)
    assert len(reps) == REPR_SHELF["max"]
    assert len({(r["x"], r["y"]) for r in reps}) == len(reps)


def test_play_world_reps_empty_without_inventory(tmp_path,
                                                 monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        html = client.get("/play").text
        assert '<canvas id="stage"' in html
        match = re.search(r"const PLAYDATA = (\{.*?\});", html,
                          re.DOTALL)
        data = json.loads(match.group(1))
        # INVENTory draait niet in tests: geen fake objecten.
        assert data["world_reps"] == []
        assert "worldReps" in html
        assert "Workshop-plank" in html


def test_play_npc_anchors_match_map(tmp_path, monkeypatch):
    from coordinator.app.world import npc_anchors
    anchors = npc_anchors()
    assert {a["id"] for a in anchors} == {"luma", "forge"}
    assert [a["x"] for a in anchors] == [1180, 1380]
    for client in make_client(tmp_path, monkeypatch):
        html = client.get("/play").text
        match = re.search(r"const PLAYDATA = (\{.*?\});", html,
                          re.DOTALL)
    data = json.loads(match.group(1))
    assert data["npc_anchors"] == anchors
    assert "NPC_FALLBACK" in html or "npc_anchors" in html


def test_play_world_object_panel_markers(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    for marker in ("renderWorldObj", "openWorldObj",
                   "worldrefresh", "Detail verversen",
                   "Bekijk bron", "nearestRep", "nearestTarget",
                   "[E] Bekijk ", "Vondsten en onderzoek",
                   "window.PLAYDATA = PLAYDATA"):
        assert marker in html, marker


def test_inventory_bridge_is_get_only():
    from coordinator.app.inventory_read import InventoryReader
    reader = InventoryReader.__dict__
    for verb in ("post", "put", "patch", "delete"):
        assert verb not in reader
        assert f"_{verb}" not in reader
    import inspect as _inspect
    source = _inspect.getsource(
        __import__("coordinator.app.inventory_read",
                   fromlist=["InventoryReader"]))
    assert "follow_redirects=False" in source


# GAMEPLAY LOOP v1 ------------------------------------------------------


def test_loop_playdata_keys(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        html = client.get("/play").text
        match = re.search(r"const PLAYDATA = (\{.*?\});", html,
                          re.DOTALL)
        data = json.loads(match.group(1))
        assert {"tracker", "questlines",
                "discoveries"} <= set(data)
        assert set(data["discoveries"]) == {"items",
                                            "research_open"}
        for entry in data["tracker"]:
            assert {"id", "goal", "status", "glyph", "needs",
                    "href"} <= set(entry)
        for entry in data["questlines"]:
            assert {"quest_id", "title", "state", "progress",
                    "glyph"} <= set(entry)


def test_loop_tracker_states_honest(tmp_path, monkeypatch):
    from coordinator.app.campaigns import (
        ensure_fabrication_seeds,
        ensure_mission_seeds,
    )
    for client in make_client(tmp_path, monkeypatch):
        ensure_mission_seeds()
        ensure_fabrication_seeds()
        html = client.get("/play").text
        match = re.search(r"const PLAYDATA = (\{.*?\});", html,
                          re.DOTALL)
        tracks = {t["goal"]: t for t in
                  json.loads(match.group(1))["tracker"]}
        first = tracks["Maak je eerste digitale prototype"]
        assert first["status"] == "draft"
        assert first["glyph"] == "○"
        assert "beschikbaar" in first["needs"]
        assert first["href"].startswith("/missions/")


def test_loop_mission_gates_in_game(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        chat = client.post("/api/v1/chat", json={
            "message": "hallo"})
        assert chat.status_code == 200, chat.text
        conversation = chat.json()["conversation_id"]
        made = client.post("/api/v1/missions/from-template", json={
            "template_id": "investigate_inventory",
            "conversation_id": conversation,
            "goal": "Verkenning vanuit de game"})
        assert made.status_code == 201, made.text
        mid = made.json()["mission_id"]
        assert made.json()["status"] == "pending_approval"
        wrong = client.post(f"/api/v1/missions/{mid}/approve",
                            json={"response": "ja misschien",
                                  "decided_by": "jelles"})
        assert wrong.status_code == 422
        ok = client.post(f"/api/v1/missions/{mid}/approve",
                         json={"response": "YES",
                               "decided_by": "jelles"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "approved"
        ticked = client.post(f"/api/v1/missions/{mid}/tick")
        assert ticked.status_code == 200, ticked.text
        # Tracker toont de echte toestand na refresh.
        listed = client.get("/api/v1/missions").json()
        assert isinstance(listed, list)
        states = {m["mission_id"]: m["status"] for m in listed}
        assert states[mid] in ("approved", "running",
                               "completed", "blocked",
                               "failed", "paused")
        html = client.get("/play").text
        match = re.search(r"const PLAYDATA = (\{.*?\});", html,
                          re.DOTALL)
        tracks = {t["id"]: t for t in
                  json.loads(match.group(1))["tracker"]}
        assert tracks[mid]["status"] == states[mid]
        assert tracks[mid]["glyph"] in ("○", "◷", "…", "⏸",
                                        "✓", "!")


def test_loop_discovery_markers(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    for marker in ("nearDiscovery", "discoveryCount",
                   "renderDiscovery", "openDiscovery",
                   "Ruïne — ontdekking", "Onderzoek de ruïne",
                   "Nog geen ontdekkingen beschikbaar",
                   "FUTURE/UNAVAILABLE",
                   "renderJourney", "journeyData", "trackerData",
                   "discoveryData", "trackGlyph", "trackNeeds",
                   "data-act=\"mtick\"", "data-act=\"myes\"",
                   "data-act=\"jrefresh\"",
                   "data-act=\"journey\"",
                   "🧭 Reis", "Homebase — Workshop",
                   "wereldgeheugen", "Omdat:"):
        assert marker in html, marker


def test_loop_questline_visible_change(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        title = "Gameplay-loop proefquest"
        created = client.post("/api/v1/quests", json={
            "title": title, "steps": [
                {"key": "proef", "label": "Proef",
                 "kind": "note", "ref": ""}]})
        assert created.status_code == 201, created.text
        html = client.get("/play").text
        match = re.search(r"const PLAYDATA = (\{.*?\});", html,
                          re.DOTALL)
        titles = [q["title"] for q in
                  json.loads(match.group(1))["questlines"]]
        assert title in titles


def test_loop_empty_world_no_fake_progress(tmp_path, monkeypatch):
    from coordinator.app.quests import list_quests
    for client in make_client(tmp_path, monkeypatch):
        before = len(list_quests(limit=100))
        html = client.get("/play").text
        assert len(list_quests(limit=100)) == before
        match = re.search(r"const PLAYDATA = (\{.*?\});", html,
                          re.DOTALL)
        data = json.loads(match.group(1))
        assert data["tracker"] == []
        assert data["questlines"] == []
        assert data["discoveries"] == {"items": [],
                                       "research_open": []}
        assert data["world_reps"] == []


# VERDANT v1 ------------------------------------------------------------


def test_verdant_dormant_without_data():
    from coordinator.app.world import verdant_state_from
    assert verdant_state_from(None)["state"] == "DORMANT"
    assert verdant_state_from({})["signals"] == []
    assert verdant_state_from(
        {"inventory": [], "solar": 0,
         "research": []})["count"] == 0


def test_verdant_awakened_with_real_signals():
    from coordinator.app.world import verdant_state_from
    state = verdant_state_from({
        "inventory": [
            {"entity_type": "project", "entity_id": "proj_hydro",
             "title": "Hydroponics-proef"}],
        "solar": 3,
        "research": [{"dossier_id": "dossier_1",
                      "title": "Compost-onderzoek"}]})
    assert state["state"] == "AWAKENED"
    assert state["count"] == 3
    hrefs = [s["href"] for s in state["signals"]]
    assert "/world?entity_id=proj_hydro" in hrefs
    assert "/energy" in hrefs
    assert "/research/dossier_1" in hrefs
    # Deterministisch en begrensd.
    again = verdant_state_from({
        "inventory": [
            {"entity_type": "project", "entity_id": "proj_hydro",
             "title": "Hydroponics-proef"}],
        "solar": 3,
        "research": [{"dossier_id": "dossier_1",
                      "title": "Compost-onderzoek"}]})
    assert again == state


def test_verdant_collect_empty_reader(tmp_path, monkeypatch):
    import asyncio as _asyncio
    from coordinator.app.world import (collect_verdant_signals,
                                       verdant_state_from)
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "v.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "v-chat.db"))

    class _Dead:
        async def search(self, q, type=None):
            raise RuntimeError("down")

    parts = _asyncio.run(collect_verdant_signals(_Dead()))
    assert parts == {"inventory": [], "solar": 0,
                     "research": []}
    assert verdant_state_from(parts)["state"] == "DORMANT"


def test_npc_activity_mapping():
    from coordinator.app.world import derive_npc_activity
    idle = derive_npc_activity({})
    assert idle["luma"]["state"] == "idle"
    assert idle["forge"]["state"] == "idle"
    needy = derive_npc_activity({"candidate_open": 2})
    assert needy["luma"]["state"] == "needs_attention"
    waiting = derive_npc_activity({"inbox_count": 1})
    assert waiting["luma"]["state"] == "waiting"
    busy = derive_npc_activity({"missions_active": True,
                                "fab_open": True})
    assert busy["luma"]["state"] == "processing"
    assert busy["forge"]["state"] == "processing"
    assert derive_npc_activity(
        {"fab_draft": True})["forge"]["state"] == "waiting"
    assert derive_npc_activity(
        {"quest_completed": True})["luma"]["state"] == \
        "completed"


def test_play_verdant_and_activity_markers(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        html = client.get("/play").text
        for marker in ("verdantData", "nearVerdant",
                       "renderVerdant", "openVerdant",
                       "Verdant — dormant", "Betreed Verdant",
                       "DORMANT", "AWAKENED",
                       "ACTIVITEIT", "afgeleid uit backend-state",
                       '"verdant"', '"npc_activity"'):
            assert marker in html, marker
        match = re.search(r"const PLAYDATA = (\{.*?\});", html,
                          re.DOTALL)
        data = json.loads(match.group(1))
        assert data["verdant"]["state"] == "DORMANT"
        assert data["verdant"]["signals"] == []
        assert set(data["npc_activity"]) == {"luma", "forge"}
        for npc in ("luma", "forge"):
            assert data["npc_activity"][npc]["state"] in (
                "idle", "waiting", "processing",
                "result_available", "needs_attention",
                "blocked", "completed")


def test_verdant_awakens_on_solar_record(tmp_path, monkeypatch):
    from coordinator.app.energy import (list_records, new_record,
                                        save_record)
    from coordinator.app.guide import guide_items
    for client in make_client(tmp_path, monkeypatch):
        save_record(new_record(source="solar", kind="state",
                               value=80.0, unit="%",
                               recorded_by="test"))
        assert len(list_records(source="solar", limit=50)) == 1
        kinds = [item["kind"] for item in guide_items(limit=20)]
        assert "energy" in kinds
        solar_items = [
            item for item in guide_items(limit=20)
            if item["kind"] == "energy"
            and "solar" in item["what"]]
        assert len(solar_items) == 1
        assert solar_items[0]["next"]["href"] == "/energy"
        html = client.get("/play").text
        match = re.search(r"const PLAYDATA = (\{.*?\});", html,
                          re.DOTALL)
        verdant = json.loads(match.group(1))["verdant"]
        assert verdant["state"] == "AWAKENED"
        assert any(s["kind"] == "energy"
                   for s in verdant["signals"])


def test_guide_verdant_empty_without_data(tmp_path, monkeypatch):
    from coordinator.app.guide import guide_items
    for client in make_client(tmp_path, monkeypatch):
        solar_items = [
            item for item in guide_items(limit=20)
            if item["kind"] == "energy"
            and "solar" in item["what"]]
        assert solar_items == []


def test_fungi_mission_parent_is_causal(tmp_path, monkeypatch):
    import types as _types
    import coordinator.app.campaigns as _camps
    import coordinator.app.missions as _missions
    from coordinator.app.world import derive_fungi_network
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "f.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "f-chat.db"))
    mission = _types.SimpleNamespace(
        mission_id="mission_verdant",
        goal="Hydroponics-verkenning", status="approved")
    quest_view = {"quest_id": "qst_verdant",
                  "title": "Missie: Hydroponics",
                  "state": "ACTIVE",
                  "href": "/quests/qst_verdant",
                  "steps": [{"kind": "mission",
                             "ref": "mission_verdant"}]}
    monkeypatch.setattr(
        _camps, "list_campaign_details",
        lambda limit=10: [{"campaign_id": "cmp_eco",
                           "title": "Eco",
                           "completed_count": 0,
                           "quests": [quest_view]}])
    monkeypatch.setattr(_missions, "list_missions",
                        lambda limit=50: [mission])
    net = derive_fungi_network(limit=120)
    by_id = {n["id"]: n for n in net["nodes"]}
    assert by_id["fungi-mission-mission_verdant"]["parent"] == \
        "fungi-quest-qst_verdant"
    assert by_id["fungi-quest-qst_verdant"]["parent"] == \
        "fungi-camp-cmp_eco"
    assert net == derive_fungi_network(limit=120)


# VERDANT DOORGAAN ----------------------------------------------------


def test_verdant_rep_from_signal():
    from coordinator.app.world import (VERDANT_RECT,
                                       verdant_rep_from)
    assert verdant_rep_from(None) is None
    assert verdant_rep_from([]) is None
    signals = [
        {"kind": "energy", "label": "2 solar-meting(en)",
         "href": "/energy", "detail": "energy_records"},
        {"kind": "inventory", "source_id": "proj_hydro",
         "entity_type": "project", "title": "Hydroponics",
         "label": "Hydroponics", "href": "/world?entity_id=",
         "detail": "project"}]
    rep = verdant_rep_from(signals)
    assert rep is not None
    assert rep["id"] == "wrld-proj_hydro"
    assert rep["source_id"] == "proj_hydro"
    assert rep["entity_type"] == "project"
    assert rep["kind"] == "PROJECT"
    assert rep["zone"] == "verdant"
    assert (rep["x"], rep["y"]) == (VERDANT_RECT["cx"],
                                    VERDANT_RECT["cy"])
    assert rep["href"] == "/world?entity_id=proj_hydro"
    assert rep["interaction"] == "inspect"
    # Geen dubbele als het record al op de plank staat.
    assert verdant_rep_from(signals,
                            shelf_ids={"proj_hydro"}) is None
    # Niet-whitelist-typen worden nooit een representatie.
    assert verdant_rep_from([{
        "kind": "inventory", "source_id": "idea_1",
        "entity_type": "idea", "label": "Idee",
        "href": "/world?entity_id=idea_1",
        "detail": "idea"}]) is None


def test_npc_activity_result_and_blocked():
    from coordinator.app.world import derive_npc_activity
    assert derive_npc_activity(
        {"supported_count": 3})["luma"]["state"] == \
        "result_available"
    # Review-aandacht wint van resultaat.
    assert derive_npc_activity(
        {"candidate_open": 1,
         "supported_count": 3})["luma"]["state"] == \
        "needs_attention"
    assert derive_npc_activity(
        {"fab_blocked": True})["forge"]["state"] == "blocked"
    # Blocked wint van bezig.
    assert derive_npc_activity(
        {"fab_blocked": True,
         "fab_open": True})["forge"]["state"] == "blocked"


def test_guide_missing_sensor_honest(tmp_path, monkeypatch):
    import coordinator.app.main as _main
    from coordinator.app.guide import _missing_sensor_item
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "s.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "s-chat.db"))
    monkeypatch.setattr(_main, "list_nodes", lambda: [])
    item = _missing_sensor_item()
    assert item is not None
    assert item["kind"] == "hardware"
    assert "FUTURE" in item["what"]
    assert item["next"]["href"] == "/hardware"
    monkeypatch.setattr(_main, "list_nodes", lambda: [{
        "node_id": "seed-01", "derived_status": "online",
        "hardware": [{"kind": "sensor", "status": "connected"}]}])
    assert _missing_sensor_item() is None


def test_fungi_verdant_quests_via_seeds(tmp_path, monkeypatch):
    from coordinator.app.campaigns import ensure_foundation_seeds
    from coordinator.app.world import derive_fungi_network
    for client in make_client(tmp_path, monkeypatch):
        ensure_foundation_seeds()
        net = derive_fungi_network(limit=120)
        by_id = {n["id"]: n for n in net["nodes"]}
        kweek = [key for key, node in by_id.items()
                 if node["branch"] == "quest"
                 and "kweek" in node["label"]]
        assert len(kweek) == 1
        assert net == derive_fungi_network(limit=120)


def test_play_verdant_rep_key_and_markers(tmp_path, monkeypatch):
    for client in make_client(tmp_path, monkeypatch):
        html = client.get("/play").text
        assert "Representatie in de bioom" in html
        match = re.search(r"const PLAYDATA = (\{.*?\});", html,
                          re.DOTALL)
        data = json.loads(match.group(1))
        assert data["verdant"]["rep"] is None
        assert data["verdant"]["mission"] is None
        assert data["verdant"]["quests"] == []
