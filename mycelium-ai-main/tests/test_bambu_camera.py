"""Bambu chamber camera tests: auth packet, framing, bounds,
fail-closed reads. Fake transport only; the one live check runs
against scripted bytes, never the network."""

import struct

import pytest

from coordinator.app.bambu_camera import (
    BambuCameraError,
    BambuCameraUnavailable,
    build_auth_packet,
    check_jpeg,
    grab_snapshot,
    parse_frame_header,
)


def _jpeg(size: int = 1200) -> bytes:
    assert size >= 4
    return b"\xff\xd8" + b"\x00" * (size - 4) + b"\xff\xd9"


class FakeSock:
    """Scripted TLS-socket stand-in (sendall/recv/close)."""

    def __init__(self, stream: bytes):
        self.sent = bytearray()
        self.stream = bytearray(stream)
        self.closed = False

    def sendall(self, data):
        self.sent += data

    def recv(self, count):
        # Small uneven chunks, like the real stream, but never
        # more than asked (socket contract).
        piece = bytes(self.stream[:min(count, 7)])
        del self.stream[:min(count, 7)]
        return piece

    def close(self):
        self.closed = True


def _frame_stream(jpeg: bytes) -> bytes:
    return struct.pack("<I", len(jpeg)) + b"\x00" * 12 + jpeg


def test_auth_packet_layout():
    packet = build_auth_packet("bblp", "ABC123")
    assert len(packet) == 80
    assert struct.unpack("<I", packet[0:4])[0] == 0x40
    assert struct.unpack("<I", packet[4:8])[0] == 0x3000
    assert packet[16:20] == b"bblp"
    assert packet[16:48] == b"bblp" + b"\x00" * 28
    assert packet[48:54] == b"ABC123"
    assert packet[54:80] == b"\x00" * 26
    with pytest.raises(BambuCameraError):
        build_auth_packet("bblp", "")
    with pytest.raises(BambuCameraError):
        build_auth_packet("", "ABC123")


def test_frame_header_bounds():
    assert parse_frame_header(
        struct.pack("<I", 5000) + b"\x00" * 12) == 5000
    with pytest.raises(BambuCameraUnavailable):
        parse_frame_header(struct.pack("<I", 10) + b"\x00" * 12)
    with pytest.raises(BambuCameraUnavailable):
        parse_frame_header(
            struct.pack("<I", 9_000_000) + b"\x00" * 12)
    with pytest.raises(BambuCameraError):
        parse_frame_header(b"\x00" * 8)


def test_jpeg_checks():
    assert check_jpeg(_jpeg()) == _jpeg()
    with pytest.raises(BambuCameraUnavailable):
        check_jpeg(b"\xff\xd8" + b"\x00" * 2000)
    with pytest.raises(BambuCameraUnavailable):
        check_jpeg(b"\x00" * 1200)
    with pytest.raises(BambuCameraUnavailable):
        check_jpeg(b"\xff\xd8\xff\xd9")


def test_grab_snapshot_happy_path():
    jpeg = _jpeg(2500)
    sock = FakeSock(_frame_stream(jpeg))
    seen = {}

    def _factory(host, port, timeout):
        seen.update(host=host, port=port, timeout=timeout)
        return sock

    result = grab_snapshot("192.168.1.50", access_code="code-1",
                           transport_factory=_factory)
    assert result == jpeg
    assert seen == {"host": "192.168.1.50", "port": 6000,
                    "timeout": 10.0}
    assert sock.sent[:80] == build_auth_packet("bblp", "code-1")
    assert sock.closed is True


def test_grab_snapshot_rejects_and_never_leaks():
    with pytest.raises(BambuCameraError):
        grab_snapshot("", access_code="code-1")
    with pytest.raises(BambuCameraError):
        grab_snapshot("https://192.168.1.50", access_code="c")
    with pytest.raises(BambuCameraError):
        grab_snapshot("user@192.168.1.50", access_code="c")

    def _refusing(host, port, timeout):
        raise OSError("no route")

    with pytest.raises(BambuCameraUnavailable) as caught:
        grab_snapshot("192.168.1.50", access_code="SECRET-XYZ",
                      transport_factory=_refusing)
    assert "SECRET-XYZ" not in str(caught.value)

    bad = FakeSock(b"\x00" * 16 + _jpeg())
    with pytest.raises(BambuCameraUnavailable):
        grab_snapshot("192.168.1.50", access_code="SECRET-XYZ",
                      transport_factory=lambda h, p, t: bad)
