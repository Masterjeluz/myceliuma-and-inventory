"""Printer device + execution tests (BIG #7).

Registration, capability filtering, unavailable honesty,
simulated execution, cancel semantics, and the physical
approval gate: mission YES never starts the machine.
"""

import pytest

from coordinator.app.controlled_writes import (
    decide_write,
    request_write_approval,
    revalidate,
)
from coordinator.app.fab_flow import (
    PrintRefusedError,
    execute_print,
    propose_print,
)
from coordinator.app.mesh3d import ProceduralTestGenerator
from coordinator.app.printer3d import (
    PrinterRefusedError,
    PrinterUnavailable,
    SimulatedPrinterAdapter,
    UnavailablePrinterAdapter,
    adapter_capabilities,
    adapter_for_printer,
    clear_printers,
    get_printer,
    list_printers,
    new_job as make_job,
    new_printer,
    register_printer,
    unregister_printer,
)
from coordinator.app.slicer3d import (
    TestSlicer,
    check_slicer_request,
    validate_gcode,
)


def make_gcode() -> tuple[str, str]:
    mesh = ProceduralTestGenerator().generate("kubus", {}).artifact_ref
    request = check_slicer_request(mesh, "draft-pla", "prt-test1")
    result = TestSlicer().slice(request)
    return result.gcode_ref, result.sha256


def make_device(printer_id="prt-test1"):
    return new_printer(printer_id, "Testprinter",
                       ["printer.status", "printer.start",
                        "printer.cancel"])


def approved(proposal):
    return decide_write(request_write_approval(proposal), proposal,
                        "YES", decided_by="jelles")


def test_registration_and_prefix():
    device = make_device()
    assert device.printer_id == "prt-test1"
    assert device.status == "registered"
    with pytest.raises(PrinterRefusedError, match="prt-"):
        new_printer("printer-1", "X", [])
    with pytest.raises(PrinterRefusedError, match="hw_"):
        new_printer("prt-2", "X", [],
                    inventory_hardware_id="obj_x")
    twin = new_printer("prt-3", "X", [], inventory_hardware_id="hw_x")
    assert twin.inventory_hardware_id == "hw_x"
    with pytest.raises(PrinterRefusedError, match="Unknown printer"):
        new_printer("prt-4", "X", ["printer.fly"])


def test_capability_spoofing_filtered():
    adapter = SimulatedPrinterAdapter()
    caps = adapter_capabilities(adapter)
    assert "printer.start" in caps
    assert "printer.upload" in caps

    class Spoof(SimulatedPrinterAdapter):
        capabilities = ["printer.start", "printer.launch-missiles",
                        "exec:anything"]

    assert adapter_capabilities(Spoof()) == ["printer.start"]


def test_unavailable_printer_refuses():
    device = make_device()
    adapter = UnavailablePrinterAdapter()
    with pytest.raises(PrinterUnavailable,
                       match="refusing instead of moving"):
        adapter.execute(device, make_job(
            "pjob-1", "prt-test1", "fab-x.gcode", "0" * 64,
            "draft-pla", "t"))
    assert "reviewed" in UnavailablePrinterAdapter.requirements()


def test_registry():
    clear_printers()
    device = make_device()
    adapter = SimulatedPrinterAdapter()
    register_printer(device, adapter)
    assert get_printer("prt-test1") is device
    assert adapter_for_printer("prt-test1") is adapter
    assert len(list_printers()) == 1
    unregister_printer("prt-test1")
    assert get_printer("prt-test1") is None
    with pytest.raises(PrinterRefusedError):
        register_printer(object())
    clear_printers()


def test_simulated_execution_completes():
    gcode_ref, sha = make_gcode()
    device = make_device()
    adapter = SimulatedPrinterAdapter()
    job = make_job("pjob-sim1", "prt-test1", gcode_ref, sha,
                   "draft-pla", "tester")
    proposal = propose_print("wrt-print1", job, safety_verdict="safe",
                             actor="tester")
    assert proposal.mutation_type == "printer.execute"
    assert proposal.capability() == "printer.execute"
    assert proposal.provenance.human_verified is False
    result = execute_print(proposal, approved(proposal),
                           device=device, adapter=adapter,
                           safety_verdict="safe")
    assert result.outcome == "executed"
    assert result.after["print_result"]["status"] == "completed"
    assert result.after["print_result"]["gcode_sha256"] == sha
    assert result.provenance.human_verified is False


def test_unsafe_safety_never_proposes_nor_executes():
    gcode_ref, sha = make_gcode()
    job = make_job("pjob-unsafe", "prt-test1", gcode_ref, sha,
                   "draft-pla", "tester")
    with pytest.raises(PrintRefusedError, match="never becomes"):
        propose_print("wrt-unsafe", job, safety_verdict="unsafe",
                      actor="tester")
    proposal = propose_print("wrt-unsafe2", job,
                             safety_verdict="safe", actor="tester")
    device = make_device()
    blocked = execute_print(proposal, approved(proposal),
                            device=device,
                            adapter=SimulatedPrinterAdapter(),
                            safety_verdict="unsafe")
    assert blocked.outcome == "blocked"


def test_changed_gcode_blocked():
    gcode_ref, sha = make_gcode()
    job = make_job("pjob-change", "prt-test1", gcode_ref, sha,
                   "draft-pla", "tester")
    proposal = propose_print("wrt-change", job,
                             safety_verdict="safe", actor="tester")
    approval = approved(proposal)
    # Tamper with the stored artifact after approval.
    import os
    from coordinator.app.mesh3d import artifact_path
    with open(artifact_path(gcode_ref), "a",
              encoding="utf-8") as handle:
        handle.write("G1 X999\n")
    device = make_device()
    blocked = execute_print(proposal, approval, device=device,
                            adapter=SimulatedPrinterAdapter(),
                            safety_verdict="safe")
    assert blocked.outcome == "blocked"
    assert "fingerprint mismatch" in blocked.error


def test_no_adapter_blocked_not_failed():
    gcode_ref, sha = make_gcode()
    job = make_job("pjob-noad", "prt-test1", gcode_ref, sha,
                   "draft-pla", "tester")
    proposal = propose_print("wrt-noad", job, safety_verdict="safe",
                             actor="tester")
    blocked = execute_print(proposal, approved(proposal),
                            device=make_device(), adapter=None,
                            safety_verdict="safe")
    assert blocked.outcome == "blocked"
    assert "no printer adapter" in blocked.error


def test_mission_yes_never_starts_machine():
    """A rejected (non-approved) proposal refuses at revalidation:
    plan-level approval lives elsewhere and cannot substitute."""
    gcode_ref, sha = make_gcode()
    job = make_job("pjob-noperm", "prt-test1", gcode_ref, sha,
                   "draft-pla", "tester")
    proposal = propose_print("wrt-noperm", job,
                             safety_verdict="safe", actor="tester")
    request = request_write_approval(proposal)
    rejected = decide_write(request, proposal, "NO")
    with pytest.raises(ValueError, match="Only an approved"):
        revalidate(proposal, rejected)


def test_cancel_semantics():
    device = make_device()
    adapter = SimulatedPrinterAdapter()
    adapter.request_cancel("pjob-cancel1")
    job = make_job("pjob-cancel1", "prt-test1", "fab-x.gcode",
                   "0" * 64, "draft-pla", "tester")
    cancelled = adapter.cancel(device, job)
    assert cancelled.status == "cancelled"
    assert "NOT a physical emergency stop" in (
        cancelled.error + cancelled.estop_note)


def test_simulated_failure_is_failed():
    gcode_ref, sha = make_gcode()
    job = make_job("pjob-fail", "prt-test1", gcode_ref, sha,
                   "draft-pla", "tester")
    proposal = propose_print("wrt-fail", job, safety_verdict="safe",
                             actor="tester")
    result = execute_print(proposal, approved(proposal),
                           device=make_device(),
                           adapter=SimulatedPrinterAdapter(fail=True),
                           safety_verdict="safe")
    assert result.outcome == "failed"
    assert "simulated" in result.error
