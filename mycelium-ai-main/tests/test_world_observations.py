"""World observations: multi-node perception without ownership.
Create/list/validation, confidence bounds, prefix refusal, two
nodes sharing one entity, observations in Hermes context, spatial
z, screen observations."""

from fastapi.testclient import TestClient

import coordinator.app.hermes_npc as npc_mod
import coordinator.app.main as main_mod


def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "wobs.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "wobs-chat.db"))
    monkeypatch.setenv("MYCELIUM_OPERATOR_KEY", "wobs-operator")
    monkeypatch.setenv("INVENTORY_BASE_URL", "http://127.0.0.1:9")
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_create_and_list(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        made = test_client.post("/api/v1/world/observations", json={
            "node_id": "seed-01", "source": "camera",
            "entity_ref": "obj_abc123", "x": 100.5, "y": 200.0,
            "confidence": 0.8, "note": "soldeerbout op werkbank",
            "provenance": {"by": "mos"}})
        assert made.status_code == 201, made.text
        body = made.json()
        assert body["obs_id"].startswith("wobs_")
        assert body["node_id"] == "seed-01"
        assert body["entity_ref"] == "obj_abc123"
        assert body["confidence"] == 0.8
        listed = test_client.get(
            "/api/v1/world/observations").json()
        assert listed["total"] == 1
        assert listed["observations"][0]["obs_id"] == body["obs_id"]


def test_validation(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        base = {"node_id": "seed-01", "source": "camera"}
        assert test_client.post(
            "/api/v1/world/observations",
            json={**base}).status_code == 201  # minimal ok
        assert test_client.post(
            "/api/v1/world/observations",
            json={"source": "camera"}).status_code == 422  # no node
        assert test_client.post(
            "/api/v1/world/observations",
            json={"node_id": "seed-01"}).status_code == 422  # no source
        assert test_client.post(
            "/api/v1/world/observations",
            json={**base, "source": "telepathy"}).status_code == 422
        assert test_client.post(
            "/api/v1/world/observations",
            json={**base, "confidence": 1.5}).status_code == 422
        assert test_client.post(
            "/api/v1/world/observations",
            json={**base, "confidence": -0.1}).status_code == 422
        assert test_client.post(
            "/api/v1/world/observations",
            json={**base, "x": 1}).status_code == 422  # half position
        assert test_client.post(
            "/api/v1/world/observations",
            json={**base, "note": "x" * 501}).status_code == 422
        assert test_client.post(
            "/api/v1/world/observations", json="nope").status_code == 422


def test_invalid_entity_prefix_refused_unknown_allowed(tmp_path,
                                                       monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        bad = test_client.post("/api/v1/world/observations", json={
            "node_id": "seed-01", "source": "node",
            "entity_ref": "dragon-9"})
        assert bad.status_code == 422
        # unknown but well-formed ref is fine: the world is
        # bigger than our records
        ok = test_client.post("/api/v1/world/observations", json={
            "node_id": "seed-01", "source": "node",
            "entity_ref": "obj_nonexistent000"})
        assert ok.status_code == 201, ok.text


def test_two_nodes_share_one_entity_no_ownership(tmp_path,
                                                 monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        first = test_client.post("/api/v1/world/observations",
                                 json={"node_id": "seed-01",
                                       "source": "camera",
                                       "entity_ref": "obj_shared1",
                                       "confidence": 0.6}).json()
        second = test_client.post("/api/v1/world/observations",
                                  json={"node_id": "seed-02",
                                        "source": "screen",
                                        "entity_ref": "obj_shared1",
                                        "confidence": 0.9}).json()
        assert first["obs_id"] != second["obs_id"]
        shared = test_client.get(
            "/api/v1/world/observations",
            params={"entity_ref": "obj_shared1"}).json()
        assert shared["total"] == 2
        nodes = {row["node_id"] for row in shared["observations"]}
        assert nodes == {"seed-01", "seed-02"}
        # no owner field anywhere
        for row in shared["observations"]:
            assert "owner" not in row
        only_one = test_client.get(
            "/api/v1/world/observations",
            params={"node_id": "seed-02"}).json()
        assert only_one["total"] == 1


def test_observations_appear_in_hermes_context(tmp_path,
                                               monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        test_client.post("/api/v1/world/observations", json={
            "node_id": "seed-01", "source": "camera",
            "entity_ref": "obj_ctx1", "confidence": 0.7})
        text = npc_mod.build_npc_context("play_nope")
        assert "Waarnemingen" in text
        assert "obj_ctx1" in text
        assert "seed-01" in text


def test_spatial_z_optional_but_needs_xy(tmp_path, monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        ok = test_client.post("/api/v1/world/observations", json={
            "node_id": "seed-01", "source": "node",
            "entity_ref": "obj_room1", "x": 1.5, "y": 2.5,
            "z": 0.75})
        assert ok.status_code == 201, ok.text
        assert ok.json()["z"] == 0.75
        lonely = test_client.post("/api/v1/world/observations",
                                  json={"node_id": "seed-01",
                                        "source": "node", "z": 1.0})
        assert lonely.status_code == 422
        bad = test_client.post("/api/v1/world/observations", json={
            "node_id": "seed-01", "source": "node",
            "x": 1.0, "y": 2.0, "z": "hoog"})
        assert bad.status_code == 422


def test_screen_observation_uses_existing_image_rule(tmp_path,
                                                     monkeypatch):
    for test_client in api(tmp_path, monkeypatch):
        ok = test_client.post("/api/v1/world/observations/screen",
                              json={"node_id": "laptop-01",
                                    "width": 1920, "height": 1080,
                                    "image_ref": "obs-abc.bmp",
                                    "active_window": "editor",
                                    "entity_ref": "obj_desk1",
                                    "confidence": 0.6,
                                    "note": "soldering station"})
        assert ok.status_code == 201, ok.text
        body = ok.json()
        assert body["source"] == "screen"
        assert body["media_ref"] == "obs-abc.bmp"
        assert body["provenance"]["active_window"] == "editor"
        # no pixels uploaded: paths, URLs and schemes refuse
        for bad_ref in ("../evil.bmp", "http://x/y.png",
                        "C:\\win\\a.bmp", "shot.tiff", ""):
            bad = test_client.post(
                "/api/v1/world/observations/screen",
                json={"node_id": "laptop-01", "width": 10,
                      "height": 10, "image_ref": bad_ref})
            assert bad.status_code == 422, bad_ref
        # width/height must be real integers
        bad_dims = test_client.post(
            "/api/v1/world/observations/screen",
            json={"node_id": "laptop-01", "width": "veel",
                  "height": 10, "image_ref": "obs-abc.bmp"})
        assert bad_dims.status_code == 422
        # screen rows list through the same endpoint
        listed = test_client.get(
            "/api/v1/world/observations",
            params={"node_id": "laptop-01"}).json()
        assert listed["total"] >= 1
        assert listed["observations"][0]["source"] == "screen"
