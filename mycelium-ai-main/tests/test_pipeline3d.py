"""3D-pipeline contract tests (Fase O/Q).

Stage validation, feasibility advice, generation requests with the
local-only method rule. Anything cloud/printer/gcode-shaped is
refused; no geometry is ever produced here.
"""

import pytest

from coordinator.app.pipeline3d import (
    new_feasibility,
    new_generation_request,
    new_stage_record,
)


def test_stage_lifecycle_records():
    record = new_stage_record("r3d-1", "photo_import", "done",
                              references={"file_id": "file_abc"})
    assert record.stage == "photo_import"
    assert record.provenance.human_verified is False
    with pytest.raises(ValueError):
        new_stage_record("r3d-2", "teleport", "done")
    with pytest.raises(ValueError):
        new_stage_record("r3d-3", "preview", "shipped")


def test_feasibility_is_advice_not_release():
    feasible = new_feasibility("obj_abc", True, concerns=["overhang"])
    assert feasible.printable is True
    assert feasible.concerns == ["overhang"]
    assert feasible.provenance.human_verified is False


def test_generation_local_only():
    request = new_generation_request("req-1", "obj_abc", "local-template")
    assert request.method == "local-template"


def test_physical_methods_refused():
    for method in ("cloud", "printer", "gcode", "direct-print", "auto",
                   "remote", "quantum-print"):
        with pytest.raises(ValueError):
            new_generation_request("req-1", "obj_abc", method)


def test_physical_parameters_refused():
    for banned in ("gcode", "printer", "port", "device", "execute",
                   "auto_print", "cloud_key"):
        with pytest.raises(ValueError):
            new_generation_request("req-1", "obj_abc", "local-template",
                                   parameters={banned: "x"})


def test_extra_fields_forbidden():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        from coordinator.app.pipeline3d import Generation3DRequest
        Generation3DRequest(request_id="req-1", object_id="obj_abc",
                            method="local-template", parameters={},
                            cloud_key="x")


def test_no_geometry_or_hardware_in_module():
    import coordinator.app.pipeline3d as module
    source = open(module.__file__, encoding="utf-8").read().lower()
    for token in ("subprocess", "socket", "import serial", "from serial",
                  "import numpy", "import trimesh", "import PIL",
                  "from PIL", "printer_ip", "serial_port"):
        assert token not in source
