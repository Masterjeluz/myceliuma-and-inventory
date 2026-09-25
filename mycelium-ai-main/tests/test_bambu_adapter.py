import json
import subprocess
import sys

import pytest
from unittest.mock import MagicMock, patch

import coordinator.app.printer3d as printer3d_mod
from coordinator.app.printer3d import (
    BambuPrinterAdapter, PrinterDevice, PrintJob, PrinterRefusedError,
    PrinterUnavailable, new_printer, new_job,
    TERMINAL_JOB_STATUSES)
from coordinator.app.inventory_read import Provenance


@pytest.fixture
def mock_mqtt_client():
    """Mock voor paho.mqtt.client.Client."""
    with patch("paho.mqtt.client.Client") as mock:
        yield mock


def make_adapter(**overrides):
    params = {"mqtt_host": "192.168.1.100", "mqtt_port": 8883,
              "mqtt_username": None, "mqtt_password": None,
              "printer_serial": "ABC123", "printer_token": "tok"}
    params.update(overrides)
    return BambuPrinterAdapter(**params)


@pytest.fixture
def bambu_adapter():
    """BambuPrinterAdapter instantie voor tests."""
    return make_adapter()


@pytest.fixture
def test_printer_device():
    """Test PrinterDevice object."""
    return new_printer(
        printer_id="prt-bambu-test-01",
        name="Test Bambu A1 Mini",
        capabilities=["printer.status", "printer.telemetry"],
        inventory_hardware_id="hw_bambu_a1_mini_001",
        notes="Test printer voor Bambu adapter"
    )


@pytest.fixture
def test_print_job():
    """Test PrintJob object."""
    return new_job(
        job_id="job_test_001",
        printer_id="prt-bambu-test-01",
        gcode_ref="file_test_gcode_001.gcode",
        gcode_sha256="a" * 64,
        profile="standard",
        actor="test_user",
        proposal_id="prop_test_001"
    )


def test_bambu_adapter_init_requires_host_and_serial():
    """Verifieer dat BambuPrinterAdapter host en serial vereist bij initialisatie."""
    with pytest.raises(PrinterRefusedError, match="needs mqtt_host and printer_serial"):
        make_adapter(mqtt_host="")
    with pytest.raises(PrinterRefusedError, match="needs mqtt_host and printer_serial"):
        make_adapter(printer_serial="  ")


def test_bambu_adapter_status_raises_unavailable(bambu_adapter, test_printer_device):
    """Verifieer dat status PrinterUnavailable raist zolang er geen verbinding is."""
    with pytest.raises(PrinterUnavailable, match="Bambu printer is offline"):
        bambu_adapter.status(test_printer_device)


def test_bambu_adapter_execute_raises_unavailable(bambu_adapter, test_printer_device, test_print_job):
    """Verifieer dat execute PrinterUnavailable raist zolang er geen verbinding is."""
    with pytest.raises(PrinterUnavailable, match="Bambu printer is offline"):
        bambu_adapter.execute(test_printer_device, test_print_job)


def test_bambu_adapter_cancel_raises_unavailable(bambu_adapter, test_printer_device, test_print_job):
    """Verifieer dat cancel PrinterUnavailable raist zolang er geen verbinding is."""
    with pytest.raises(PrinterUnavailable, match="Bambu printer is offline"):
        bambu_adapter.cancel(test_printer_device, test_print_job)


def test_bambu_adapter_requirements():
    """Verifieer dat de requirements methode de juiste string retourneert."""
    expected_requirements = ("Bambu Lab printer requires MQTT connection details (host, port, "
                            "username, password) and printer-specific credentials "
                            "(serial, token).")
    assert BambuPrinterAdapter.requirements() == expected_requirements


def test_bambu_connect_uses_mock_mqtt(mock_mqtt_client, bambu_adapter):
    """Met gemockte paho-client verbindt de adapter zonder echt netwerk."""
    bambu_adapter._connect_mqtt()
    assert mock_mqtt_client.called
    assert bambu_adapter.client is not None


def test_bambu_unavailable_without_dependency(monkeypatch, bambu_adapter,
                                             test_printer_device):
    """Zonder paho-mqtt meldt Bambu eerlijk unavailable i.p.v. te crashen."""
    monkeypatch.setattr(printer3d_mod, "mqtt", None)
    monkeypatch.setattr(printer3d_mod, "PAHO_MQTT_AVAILABLE", False)
    with pytest.raises(PrinterUnavailable, match="paho-mqtt is not installed"):
        bambu_adapter._connect_mqtt()
    # status blijft fail-closed offline (geen beweging, geen telemetrie)
    with pytest.raises(PrinterUnavailable, match="Bambu printer is offline"):
        bambu_adapter.status(test_printer_device)


def test_coordinator_imports_without_paho():
    """Coordinator importeert veilig als paho-mqtt ontbreekt (subproces)."""
    code = "\n".join([
        "import sys",
        "sys.modules['paho.mqtt.client'] = None",
        "from coordinator.app import printer3d",
        "assert printer3d.PAHO_MQTT_AVAILABLE is False",
        "assert printer3d.mqtt is None",
        "import coordinator.app.main as m",
        "dev = printer3d.new_printer('prt-nopaho', 'NoPaho', [])",
        "ad = printer3d.BambuPrinterAdapter("
        "mqtt_host='h', mqtt_port=8883, mqtt_username=None, "
        "mqtt_password=None, printer_serial='S', printer_token='T')",
        "try:",
        "    ad.status(dev)",
        "except printer3d.PrinterUnavailable as e:",
        "    assert 'offline' in str(e) or 'paho-mqtt' in str(e), str(e)",
        "else:",
        "    raise AssertionError("
        "'status should refuse without transport')",
        "print('IMPORT_OK')",
    ])
    done = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=120)
    assert "IMPORT_OK" in done.stdout, done.stderr[-2000:]
