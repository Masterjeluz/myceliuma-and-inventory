"""Desktop contracts tests (Fase E/F/H/J/Q).

ComputerAction validation, unknown-action rejection, capability
mapping, screen observations and action results. Side-effect-free:
no backend is constructed here.
"""

import pytest

from coordinator.app.agent_results import new_result
from coordinator.app.computer_actions import (
    KEYBOARD_PRESS,
    KEYBOARD_TYPE,
    MOUSE_CLICK,
    MOUSE_MOVE,
    MOUSE_SCROLL,
    SCREEN_READ,
    approval_required_for,
    capability_for,
    new_action,
    validate_parameters,
)
from coordinator.app.observations import new_observation


def test_all_action_types_validate():
    assert validate_parameters("screenshot", {}) == {}
    assert validate_parameters("move_mouse", {"x": 10, "y": 20}) == {
        "x": 10, "y": 20}
    assert validate_parameters("click", {"x": 1, "y": 2})["button"] == "left"
    assert validate_parameters("double_click",
                               {"x": 1, "y": 2, "button": "RIGHT"}) == {
                                   "x": 1, "y": 2, "button": "right"}
    assert validate_parameters("type_text", {"text": "hallo"}) == {
        "text": "hallo"}
    assert validate_parameters("key_press", {"key": "Enter"}) == {
        "key": "enter"}
    assert validate_parameters("hotkey", {"keys": ["ctrl", "S"]}) == {
        "keys": ["ctrl", "s"]}
    assert validate_parameters("scroll", {"dy": -120}) == {"dx": 0,
                                                           "dy": -120}
    assert validate_parameters("wait", {"ms": 500}) == {"ms": 500}


def test_unknown_action_rejected():
    with pytest.raises(ValueError):
        validate_parameters("run_shell", {"cmd": "whoami"})
    with pytest.raises(ValueError):
        validate_parameters("exec_python", {"code": "1+1"})
    with pytest.raises(ValueError):
        new_action("dact-1", "open_url", {})


def test_unknown_parameter_rejected():
    with pytest.raises(ValueError):
        validate_parameters("click", {"x": 1, "y": 2, "cmd": "evil"})
    with pytest.raises(ValueError):
        validate_parameters("screenshot", {"path": "/tmp/x"})


def test_coordinates_bounded():
    with pytest.raises(ValueError):
        validate_parameters("move_mouse", {"x": -1, "y": 0})
    with pytest.raises(ValueError):
        validate_parameters("move_mouse", {"x": 99999, "y": 0})
    with pytest.raises(ValueError):
        validate_parameters("move_mouse", {"x": True, "y": 0})
    with pytest.raises(ValueError):
        validate_parameters("click", {"x": 1})


def test_text_strict():
    with pytest.raises(ValueError):
        validate_parameters("type_text", {"text": "   "})
    with pytest.raises(ValueError):
        validate_parameters("type_text", {"text": "x" * 501})
    with pytest.raises(ValueError):
        validate_parameters("type_text", {"text": "a\x07b"})


def test_keys_allow_listed_only():
    with pytest.raises(ValueError):
        validate_parameters("key_press", {"key": "rm -rf"})
    with pytest.raises(ValueError):
        validate_parameters("hotkey", {"keys": ["ctrl"]})
    with pytest.raises(ValueError):
        validate_parameters("hotkey", {"keys": ["a", "b", "c", "d", "e"]})


def test_scroll_and_wait_bounded():
    with pytest.raises(ValueError):
        validate_parameters("scroll", {"dx": 0, "dy": 0})
    with pytest.raises(ValueError):
        validate_parameters("wait", {"ms": 999999})


def test_capability_mapping():
    assert capability_for("screenshot") == SCREEN_READ
    assert capability_for("move_mouse") == MOUSE_MOVE
    assert capability_for("click") == MOUSE_CLICK
    assert capability_for("double_click") == MOUSE_CLICK
    assert capability_for("type_text") == KEYBOARD_TYPE
    assert capability_for("key_press") == KEYBOARD_PRESS
    assert capability_for("hotkey") == KEYBOARD_PRESS
    assert capability_for("scroll") == MOUSE_SCROLL
    assert capability_for("wait") is None
    with pytest.raises(ValueError):
        capability_for("run_shell")


def test_approval_policy_input_needs_yes():
    assert approval_required_for("click") is True
    assert approval_required_for("type_text") is True
    assert approval_required_for("key_press") is True
    assert approval_required_for("screenshot") is False
    assert approval_required_for("wait") is False
    assert new_action("dact-1", "click",
                      {"x": 1, "y": 1}).requires_approval is True
    assert new_action("dact-2", "screenshot", {}).requires_approval is False


def test_observation_contract():
    observation = new_observation("obs-1", 1920, 1080,
                                  image_ref="obs-1.bmp",
                                  active_window="Mycelium")
    assert observation.width == 1920
    assert observation.provenance.human_verified is False
    with pytest.raises(ValueError):
        new_observation("obs-2", 0, 1080)
    with pytest.raises(ValueError):
        new_observation("obs-3", 100, 100,
                        image_ref="http://x/y.png")
    with pytest.raises(ValueError):
        new_observation("obs-4", 100, 100, image_ref="../x.bmp")
    with pytest.raises(ValueError):
        new_observation("obs-5", 100, 100, image_ref="C:\\x.bmp")


def test_no_shell_or_code_surface():
    import coordinator.app.computer_actions as module
    source = open(module.__file__, encoding="utf-8").read().lower()
    for token in ("subprocess", "os.system", "shell=true", "eval(",
                  "exec(", "socket", "urllib"):
        assert token not in source


def test_result_contract():
    done = new_result("dact-1", "completed")
    assert done.status == "completed" and done.error == ""
    failed = new_result("dact-1", "failed", error="knop niet gevonden")
    assert failed.status == "failed"
    with pytest.raises(ValueError):
        new_result("dact-1", "verified")
    with pytest.raises(ValueError):
        new_result("dact-1", "failed")
    with pytest.raises(ValueError):
        new_result("dact-1", "completed", error="te veel")
    assert new_result("dact-1", "blocked",
                      error="x").provenance.human_verified is False
    with pytest.raises(ValueError):
        new_result("dact-1", "failed", error="x",
                   observation_reference="not-an-obs")
