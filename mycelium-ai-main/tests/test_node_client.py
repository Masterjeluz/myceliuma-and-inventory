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
