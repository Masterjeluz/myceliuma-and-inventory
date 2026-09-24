import json
import pytest
from unittest.mock import MagicMock, patch

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


@pytest.fixture
def bambu_adapter():
    """BambuPrinterAdapter instantie voor tests."""
    # De adapter valideert init parameters, dus geef geldige stubs door
    return BambuPrinterAdapter(host="192.168.1.100", access_code="12345678")


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


def test_bambu_adapter_init_requires_host_and_code():
    """Verifieer dat BambuPrinterAdapter host en access_code vereist bij initialisatie."""
    with pytest.raises(PrinterRefusedError, match="Bambu adapter needs host and access_code"):
        BambuPrinterAdapter(host="", access_code="12345678")
    with pytest.raises(PrinterRefusedError, match="Bambu adapter needs host and access_code"):
        BambuPrinterAdapter(host="192.168.1.100", access_code="")


def test_bambu_adapter_status_raises_unavailable(bambu_adapter, test_printer_device):
    """Verifieer dat status altijd PrinterUnavailable raist totdat de API is geïmplementeerd."""
    with pytest.raises(PrinterUnavailable, match="actual API interaction not yet implemented"):
        bambu_adapter.status(test_printer_device)


def test_bambu_adapter_execute_raises_unavailable(bambu_adapter, test_printer_device, test_print_job):
    """Verifieer dat execute altijd PrinterUnavailable raist totdat de API is geïmplementeerd."""
    with pytest.raises(PrinterUnavailable, match="actual API interaction not yet implemented"):
        bambu_adapter.execute(test_printer_device, test_print_job)


def test_bambu_adapter_cancel_raises_unavailable(bambu_adapter, test_printer_device, test_print_job):
    """Verifieer dat cancel altijd PrinterUnavailable raist totdat de API is geïmplementeerd."""
    with pytest.raises(PrinterUnavailable, match="actual API interaction not yet implemented"):
        bambu_adapter.cancel(test_printer_device, test_print_job)


def test_bambu_adapter_requirements():
    """Verifieer dat de requirements methode de juiste string retourneert."""
    expected_requirements = ("Bambu Lab A1 Mini (AMS) requires network access to the printer "
                             "via its API, using a host and access code. The actual "
                             "API client and interaction logic are pending implementation.")
    assert BambuPrinterAdapter.requirements() == expected_requirements


# TODO: Implementeer daadwerkelijke tests wanneer de MQTT-communicatie is toegevoegd
# Deze tests zullen dan daadwerkelijk de mock_mqtt_client gebruiken om berichten te verzenden/ontvangen
# en de status/uitvoering van de printer te simuleren.
