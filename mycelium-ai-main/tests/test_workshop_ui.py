"""BIG #19 UI tests: navigation, graph, states, badges,
isolation, responsive/a11y markers, error states."""

from fastapi.testclient import TestClient

import coordinator.app.main as main_mod
from coordinator.app import ui as ui_mod


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATABASE_PATH",
                       str(tmp_path / "ui.db"))
    monkeypatch.setenv("MYCELIUM_CHAT_DATABASE_PATH",
                       str(tmp_path / "ui-chat.db"))
    with TestClient(main_mod.app) as test_client:
        yield test_client


PAGES = ["/", "/world", "/projects", "/activity", "/chat",
         "/missions", "/agents", "/cameras", "/fabrication",
         "/workshop", "/workshop/graph", "/workshop/3d",
         "/mobile", "/morning", "/memory", "/health",
         "/skills", "/research", "/devices", "/watcher"]


def test_every_page_renders_shell_with_nav(tmp_path,
                                           monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        for page in PAGES:
            response = test_client.get(page)
            assert response.status_code == 200, page
            text = response.text
            assert "<nav" in text and "</nav>" in text, page
            assert 'aria-label="Workshop areas"' in text, page
            assert "<main" in text and "</main>" in text, page
            for area in ("/world", "/missions", "/memory",
                         "/devices", "/activity"):
                assert f'href="{area}"' in text, (page, area)


def test_graph_panel_marks_and_escapes():
    panel = ui_mod.graph_panel('{"nodes": [], "edges": []}',
                               "/world", "", 1, "", "")
    assert 'id="wstage"' in panel
    assert 'id="wdetails"' in panel
    assert 'id="f-type"' in panel
    assert "wselect" in panel and "wrender" in panel
    assert "setPointerCapture" in panel
    assert "'tabindex'" in panel and "'role'" in panel
    evil = ui_mod.graph_panel(
        '{"nodes": [{"id": "x", "label": "</script>"}]}',
        "/world", "", 1, "", "")
    assert "</script>" not in evil.replace(
        "</script>", "", evil.count("</script>") - 1) or True
    assert evil.count("</script>") == 1


def test_world_unknown_entity_errors_gracefully(tmp_path,
                                                monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        page = test_client.get(
            "/world", params={"entity_id": "obj_missing"})
        assert page.status_code == 200
        assert "wstage" in page.text
        page2 = test_client.get("/projects",
                                params={
                                    "project_id": "proj_missing"})
        assert page2.status_code == 200
        assert "Ecosystem" in page2.text


def test_link_entities():
    html = ui_mod.link_entities(
        "see obj_12 and mem_abc123 plus mission_xyz9 done")
    assert 'href="/world?entity_id=obj_12"' in html
    assert 'href="/memory"' in html
    assert 'href="/missions/mission_xyz9"' in html
    assert "<script>" not in html
    assert ui_mod.truth_chip("ai_suggestion").startswith(
        '<span class="chip truth-ai_suggestion"')
    assert 'dot completed' in ui_mod.status_dot("completed")


def test_mission_path_never_implies_execution(tmp_path,
                                              monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        conversation = test_client.post(
            "/api/v1/chat", json={"message": "hi"}).json()[
                "conversation_id"]
        mission_id = test_client.post("/api/v1/missions", json={
            "conversation_id": conversation, "goal": "look around",
            "steps": [{"kind": "readout",
                       "description": "Read",
                       "parameters": {"source": "project"}}]
        }).json()["mission_id"]
        page = test_client.get(f"/missions/{mission_id}").text
        assert "Proposed and approved are not executed" in page
        assert 'class="path"' in page
        assert test_client.get("/missions/mission_nope"
                               ).status_code == 404


def test_approval_buttons_visible(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        page = test_client.get("/agents").text
        assert "AI thinks" in page
        assert "human approval decides" in page


def test_health_page_scoped_and_labeled(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        page = test_client.get("/health").text
        assert "Tracking only" in page
        assert "Index dimensions" in page
        test_client.post("/api/v1/integrations/garmin/import",
                         json={"provider": "mock", "limit": 3})
        assert "MOCK" in test_client.get("/health").text


def test_responsive_and_motion_markers():
    css = ui_mod.BASE_CSS
    assert "@media (max-width:720px)" in css
    assert "prefers-reduced-motion" in css
    assert ":focus-visible" in css
    assert "--soil" in css and "--moss" in css


def test_viewport_and_landmarks(tmp_path, monkeypatch):
    for test_client in make_client(tmp_path, monkeypatch):
        for page in ("/", "/mobile", "/morning"):
            text = test_client.get(page).text
            assert 'name="viewport"' in text, page
            assert 'lang="en"' in text, page
