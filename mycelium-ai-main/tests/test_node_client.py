from node_client.main import execute_safe_task


def test_system_inventory_is_explicit_and_safe():
    success, result, error = execute_safe_task({"kind": "system_inventory"})
    assert success is True
    assert error is None
    assert result["cpu_cores"] >= 1


def test_unknown_task_is_not_executed():
    success, _, error = execute_safe_task({"kind": "run_shell_command"})
    assert success is False
    assert "No safe executor" in error


def test_desktop_input_never_auto_executes():
    for kind in ("desktop_click", "desktop_type", "desktop_key",
                 "desktop_mouse_move"):
        success, _, error = execute_safe_task({"kind": kind})
        assert success is False
        assert "approval" in error.lower()


def test_desktop_screenshot_returns_without_raising():
    success, result, error = execute_safe_task(
        {"kind": "desktop_screenshot"})
    assert isinstance(success, bool)
    if success:
        assert result["width"] >= 1 and error is None
    else:
        assert "Screenshot" in error
