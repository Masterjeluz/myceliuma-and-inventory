"""Push-off sweep tests: bounds, travel-only output, safe
verdict through the real validator. Local artifacts only."""

import pytest

from coordinator.app.push_off import (
    PushOffRefusedError,
    build_push_sweep,
    store_push_gcode,
)


def test_builder_defaults_kubus():
    text = build_push_sweep()
    assert "G28" in text
    assert "M84" in text
    assert "F300" in text


def test_builder_refuses_out_of_bounds():
    with pytest.raises(PushOffRefusedError):
        build_push_sweep(part_x=5.0)
    with pytest.raises(PushOffRefusedError):
        build_push_sweep(part_y=200.0)
    with pytest.raises(PushOffRefusedError):
        build_push_sweep(push_z=1.0)
    with pytest.raises(PushOffRefusedError):
        build_push_sweep(push_z=25.0, part_h=20.0)
    with pytest.raises(PushOffRefusedError):
        build_push_sweep(direction="up")


def test_output_is_travel_only():
    text = build_push_sweep()
    assert "M104" not in text
    assert "M109" not in text
    assert "M140" not in text
    assert "M190" not in text
    for line in text.splitlines():
        stripped = line.split(";")[0]
        assert " E" not in f" {stripped} "


def test_prime_variant_stays_bounded_and_safe(tmp_path,
                                              monkeypatch):
    from coordinator.app.slicer3d import validate_gcode
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR", str(tmp_path))
    text = build_push_sweep(prime=True)
    assert "M104 S170" in text
    assert "M140" not in text
    reference, _ = store_push_gcode(
        "fab-push-prime-test.gcode", text)
    assessment = validate_gcode(reference)
    assert assessment.verdict == "safe", assessment.findings
    with pytest.raises(PushOffRefusedError):
        build_push_sweep(prime=True, prime_temp_c=250.0)


def test_stored_sweep_validates_safe(tmp_path, monkeypatch):
    from coordinator.app.slicer3d import validate_gcode
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR", str(tmp_path))
    reference, data = store_push_gcode(
        "fab-push-test.gcode", build_push_sweep())
    assert reference == "fab-push-test.gcode"
    assessment = validate_gcode(reference)
    assert assessment.verdict == "safe", assessment.findings


def test_store_refuses_non_gcode(tmp_path, monkeypatch):
    from coordinator.app.slicer3d import SlicerRefusedError
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR", str(tmp_path))
    with pytest.raises(Exception):
        store_push_gcode("push.txt", build_push_sweep())
    with pytest.raises(SlicerRefusedError):
        store_push_gcode("fab-push-test.gcode", "")


def test_push_tail_waits_then_pushes(tmp_path, monkeypatch):
    from coordinator.app.push_off import (
        PushOffRefusedError,
        build_push_tail,
    )
    from coordinator.app.slicer3d import validate_gcode
    monkeypatch.setenv("MYCELIUM_FABRICATION_DIR", str(tmp_path))
    tail = build_push_tail()
    assert "M190 R35" in tail
    assert "M104" not in tail
    assert "M140" not in tail
    lines = [line.split(";")[0] for line in tail.splitlines()]
    assert not any(" E" in f" {line} " for line in lines if line)
    first_moves = [line.strip() for line in tail.splitlines()
                   if line.strip().startswith("G1")]
    assert first_moves[0].startswith("G1 Z25.0")
    reference, _ = store_push_gcode("fab-push-tail-test.gcode",
                                    tail)
    assessment = validate_gcode(reference)
    assert assessment.verdict == "safe", assessment.findings
    with pytest.raises(PushOffRefusedError):
        build_push_tail(wait_bed_c=80.0)
    with pytest.raises(PushOffRefusedError):
        build_push_tail(push_z=1.0)
