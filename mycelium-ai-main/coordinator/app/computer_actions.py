"""Desktop-agent contract: capabilities and ComputerAction (Fase E/F).

The desktop agent looks, thinks, moves the mouse, clicks and types —
like a human. It never runs shell commands and never executes code:
ComputerAction is a closed set of typed actions with strictly
validated parameters. Unknown actions fail closed.

Capabilities (explicit, matched through the existing M6.2 machinery):

- agent:desktop — the agent itself
- desktop.screen.read — observe only
- desktop.mouse.move / desktop.mouse.click / desktop.mouse.scroll
- desktop.keyboard.type / desktop.keyboard.press

Approval policy (see agent_loop for enforcement):

- screenshot and wait are local, read-only/side-effect-free: they are
  auto-approved by policy and never leave the machine.
- every input action (mouse, keyboard) requires explicit human YES.

Validation rules (all tested, all fail-closed):

- action_type must be known; parameters must be an object; extra
  parameters are forbidden per type.
- coordinates are integers 0..16384; durations 0..30000 ms;
  scroll deltas -10000..10000; typed text 1..500 chars with no
  control characters except newline/tab.
- key_press allows exactly one key from KEY_ALLOW_LIST; hotkey allows
  2..4 keys from the same list. No free-form key strings.
- no command/path/code fields exist anywhere in this module.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ComputerActionType = Literal[
    "screenshot", "move_mouse", "click", "double_click", "type_text",
    "key_press", "hotkey", "scroll", "wait",
]

KNOWN_ACTION_TYPES = frozenset({
    "screenshot", "move_mouse", "click", "double_click", "type_text",
    "key_press", "hotkey", "scroll", "wait",
})

AGENT_DESKTOP = "agent:desktop"
SCREEN_READ = "desktop.screen.read"
MOUSE_MOVE = "desktop.mouse.move"
MOUSE_CLICK = "desktop.mouse.click"
MOUSE_SCROLL = "desktop.mouse.scroll"
KEYBOARD_TYPE = "desktop.keyboard.type"
KEYBOARD_PRESS = "desktop.keyboard.press"

ACTION_CAPABILITIES: dict[str, str | None] = {
    "screenshot": SCREEN_READ,
    "move_mouse": MOUSE_MOVE,
    "click": MOUSE_CLICK,
    "double_click": MOUSE_CLICK,
    "type_text": KEYBOARD_TYPE,
    "key_press": KEYBOARD_PRESS,
    "hotkey": KEYBOARD_PRESS,
    "scroll": MOUSE_SCROLL,
    "wait": None,
}

#: Input actions need explicit human approval; observation/wait do not.
APPROVAL_REQUIRED: dict[str, bool] = {
    "screenshot": False,
    "move_mouse": True,
    "click": True,
    "double_click": True,
    "type_text": True,
    "key_press": True,
    "hotkey": True,
    "scroll": True,
    "wait": False,
}

MAX_COORDINATE = 16384
MAX_WAIT_MS = 30000
MAX_TEXT_CHARS = 500
MAX_SCROLL_DELTA = 10000
MAX_BUTTON_LEN = 20

KEY_ALLOW_LIST = frozenset({
    "enter", "tab", "escape", "esc", "space", "backspace", "delete",
    "up", "down", "left", "right", "home", "end", "pageup", "pagedown",
    "insert", "printscreen", "pause",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10",
    "f11", "f12",
    "ctrl", "alt", "shift", "win", "cmd",
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
})

_TYPE_PARAMS: dict[str, frozenset[str]] = {
    "screenshot": frozenset(),
    "move_mouse": frozenset({"x", "y"}),
    "click": frozenset({"x", "y", "button"}),
    "double_click": frozenset({"x", "y", "button"}),
    "type_text": frozenset({"text"}),
    "key_press": frozenset({"key"}),
    "hotkey": frozenset({"keys"}),
    "scroll": frozenset({"dx", "dy"}),
    "wait": frozenset({"ms"}),
}

_MOUSE_BUTTONS = frozenset({"left", "right", "middle"})


def _check_coordinate(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Parameter '{name}' must be an integer")
    if not 0 <= value <= MAX_COORDINATE:
        raise ValueError(f"Parameter '{name}' must be 0..{MAX_COORDINATE}")
    return value


def _check_button(value: Any) -> str:
    if not isinstance(value, str) or value.lower() not in _MOUSE_BUTTONS:
        raise ValueError("Parameter 'button' must be left/right/middle")
    return value.lower()


def _check_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Parameter 'text' must be non-empty text")
    if len(value) > MAX_TEXT_CHARS:
        raise ValueError(f"Parameter 'text' exceeds {MAX_TEXT_CHARS} chars")
    for char in value:
        if ord(char) < 32 and char not in ("\n", "\t"):
            raise ValueError("Parameter 'text' has control characters")
    return value


def _check_key(value: Any) -> str:
    if not isinstance(value, str) or value.lower() not in KEY_ALLOW_LIST:
        raise ValueError(f"Unknown key {value!r}; refusing")
    return value.lower()


def _check_keys(value: Any) -> list[str]:
    if not isinstance(value, list) or not 2 <= len(value) <= 4:
        raise ValueError("Parameter 'keys' must hold 2..4 keys")
    return [_check_key(entry) for entry in value]


def _check_delta(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Parameter '{name}' must be an integer")
    if not -MAX_SCROLL_DELTA <= value <= MAX_SCROLL_DELTA:
        raise ValueError(f"Parameter '{name}' out of range")
    return value


def _check_wait(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Parameter 'ms' must be an integer")
    if not 0 <= value <= MAX_WAIT_MS:
        raise ValueError(f"Parameter 'ms' must be 0..{MAX_WAIT_MS}")
    return value


def validate_parameters(action_type: str,
                        parameters: dict) -> dict[str, Any]:
    """Strict per-type parameter check. Unknown types/params fail closed."""
    if action_type not in KNOWN_ACTION_TYPES:
        raise ValueError(f"Unknown computer action '{action_type}'")
    if not isinstance(parameters, dict):
        raise ValueError("Action parameters must be an object")
    allowed = _TYPE_PARAMS[action_type]
    for key in parameters:
        if key not in allowed:
            raise ValueError(
                f"Unknown parameter '{key}' for action '{action_type}'")
    checked: dict[str, Any] = {}
    if action_type == "move_mouse":
        checked["x"] = _check_coordinate("x", parameters.get("x"))
        checked["y"] = _check_coordinate("y", parameters.get("y"))
    elif action_type in ("click", "double_click"):
        if "x" not in parameters or "y" not in parameters:
            raise ValueError(f"Action '{action_type}' needs x and y")
        checked["x"] = _check_coordinate("x", parameters.get("x"))
        checked["y"] = _check_coordinate("y", parameters.get("y"))
        checked["button"] = _check_button(parameters.get("button", "left"))
    elif action_type == "type_text":
        checked["text"] = _check_text(parameters.get("text"))
    elif action_type == "key_press":
        checked["key"] = _check_key(parameters.get("key"))
    elif action_type == "hotkey":
        checked["keys"] = _check_keys(parameters.get("keys"))
    elif action_type == "scroll":
        checked["dx"] = _check_delta("dx", parameters.get("dx", 0))
        checked["dy"] = _check_delta("dy", parameters.get("dy", 0))
        if checked["dx"] == 0 and checked["dy"] == 0:
            raise ValueError("Scroll needs a non-zero delta")
    elif action_type == "wait":
        checked["ms"] = _check_wait(parameters.get("ms", 0))
    return checked


def capability_for(action_type: str) -> str | None:
    if action_type not in KNOWN_ACTION_TYPES:
        raise ValueError(f"Unknown computer action '{action_type}'")
    return ACTION_CAPABILITIES[action_type]


def approval_required_for(action_type: str) -> bool:
    if action_type not in KNOWN_ACTION_TYPES:
        raise ValueError(f"Unknown computer action '{action_type}'")
    return APPROVAL_REQUIRED[action_type]


class ComputerAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=3, max_length=80)
    action_type: str = Field(min_length=1, max_length=40)
    parameters: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = True
    created_at: str = ""


def new_action(action_id: str, action_type: str,
               parameters: dict | None = None) -> ComputerAction:
    """Build a validated action with the correct approval flag preset."""
    checked = validate_parameters(action_type, parameters or {})
    return ComputerAction(
        action_id=action_id,
        action_type=action_type,
        parameters=checked,
        requires_approval=approval_required_for(action_type),
    )
