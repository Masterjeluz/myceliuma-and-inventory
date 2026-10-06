"""Bambu chamber camera: read-only single snapshots (A1/P1 class).

Protocol (publicly documented by OpenBambuAPI/bambu-rs/bambu-connect,
verified against those sources, never probed beyond reading docs):

- TLS TCP to <printer-ip>:6000, self-signed cert (no verify,
  like every LAN client for these printers).
- 80-byte auth packet: u32le 0x40, u32le 0x3000, u32le 0,
  u32le 0, 32-byte NUL-padded ASCII username, 32-byte
  NUL-padded ASCII access code (same env-only LAN credential
  as MQTT/FTPS).
- Then framed JPEGs: 16-byte header whose first u32le is the
  JPEG length, followed by exactly that many bytes
  (FF D8 ... FF D9, typically 1280x720).

Rules (fail-closed, tested):

- Read-only: connect, auth, read ONE frame, close. No publish,
  no control, no streaming thread, no retention here (callers
  decide what to store, e.g. the camera inbox).
- Bounded: connect + read timeouts, JPEG length 1KB..8MB
  (bambu-rs bounds); anything else refuses.
- Secrets never appear in messages, logs or errors: only the
  host (LAN address, not a secret) may surface.
- The A1 camera is intermittently silent on some firmware
  (connection accepted, no frame) — that surfaces as
  unavailable (timeout), never as an empty image.
"""

from __future__ import annotations

CAMERA_PORT = 6000
CAMERA_USERNAME = "bblp"
AUTH_PAYLOAD_SIZE = 0x40
AUTH_PACKET_TYPE = 0x3000
FRAME_HEADER_BYTES = 16
MIN_JPEG_BYTES = 1000
MAX_JPEG_BYTES = 8_000_000
CONNECT_TIMEOUT_SECONDS = 10.0
READ_TIMEOUT_SECONDS = 10.0
CHUNK_BYTES = 65536

JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"


class BambuCameraError(ValueError):
    """Local validation refused; the camera was not touched."""


class BambuCameraUnavailable(RuntimeError):
    """No frame available (fail-closed, never a fake image)."""


def build_auth_packet(username: str, access_code: str) -> bytes:
    """80-byte auth packet. Pure (never touches secrets stores)."""
    import struct as _struct
    user = str(username or "")
    code = str(access_code or "")
    try:
        user_bytes = user.encode("ascii")
        code_bytes = code.encode("ascii")
    except UnicodeEncodeError as error:
        raise BambuCameraError(
            "camera credentials must be ASCII") from error
    if not user_bytes or not code_bytes:
        raise BambuCameraError(
            "camera username and access code are required")
    if len(user_bytes) > 32 or len(code_bytes) > 32:
        raise BambuCameraError(
            "camera credential too long (max 32 ASCII chars)")
    packet = bytearray()
    packet += _struct.pack("<I", AUTH_PAYLOAD_SIZE)
    packet += _struct.pack("<I", AUTH_PACKET_TYPE)
    packet += _struct.pack("<I", 0)
    packet += _struct.pack("<I", 0)
    packet += user_bytes + b"\x00" * (32 - len(user_bytes))
    packet += code_bytes + b"\x00" * (32 - len(code_bytes))
    return bytes(packet)


def parse_frame_header(raw: bytes) -> int:
    """First u32le of the 16-byte frame header = JPEG length."""
    import struct as _struct
    if len(raw) != FRAME_HEADER_BYTES:
        raise BambuCameraError(
            f"frame header must be {FRAME_HEADER_BYTES} bytes")
    (length,) = _struct.unpack("<I", raw[:4])
    if not MIN_JPEG_BYTES <= length <= MAX_JPEG_BYTES:
        raise BambuCameraUnavailable(
            f"frame declares {length} bytes (bounds "
            f"{MIN_JPEG_BYTES}..{MAX_JPEG_BYTES}); refusing")
    return length


def check_jpeg(data: bytes) -> bytes:
    """SOI/EOI + bounds check. Pure."""
    if not (MIN_JPEG_BYTES <= len(data) <= MAX_JPEG_BYTES):
        raise BambuCameraUnavailable(
            f"frame is {len(data)} bytes (bounds "
            f"{MIN_JPEG_BYTES}..{MAX_JPEG_BYTES}); refusing")
    if not data.startswith(JPEG_SOI) or not data.endswith(JPEG_EOI):
        raise BambuCameraUnavailable(
            "frame is not a complete JPEG (SOI/EOI missing)")
    return data


def _check_host(raw: str) -> str:
    host = str(raw or "").strip()
    if not host:
        raise BambuCameraError("camera host is required")
    if len(host) > 253:
        raise BambuCameraError("camera host too long")
    lowered = host.lower()
    if "://" in lowered or "@" in host:
        raise BambuCameraError(
            "camera host must be a bare address (no scheme, "
            "no credentials)")
    return host


def _default_transport(host: str, port: int, timeout: float):
    """TLS TCP socket (self-signed printer cert, like every LAN
    client). Returns an object with sendall/recv/close."""
    import socket as _socket
    import ssl as _ssl
    raw = _socket.create_connection(
        (host, port), timeout=timeout)
    context = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = _ssl.CERT_NONE
    try:
        wrapped = context.wrap_socket(raw, server_hostname=host)
    except Exception:
        raw.close()
        raise
    wrapped.settimeout(timeout)
    return wrapped


def grab_snapshot(host: str, *, access_code: str,
                  username: str = CAMERA_USERNAME,
                  port: int = CAMERA_PORT,
                  timeout: float = READ_TIMEOUT_SECONDS,
                  transport_factory=None) -> bytes:
    """Grab ONE chamber JPEG. Read-only; closes the session.

    ``transport_factory(host, port, timeout)`` injects the socket
    (tests); production uses TLS TCP. Raises BambuCameraError on
    bad input, BambuCameraUnavailable on anything else.
    """
    import time as _time
    clean_host = _check_host(host)
    try:
        clean_port = int(port)
    except (TypeError, ValueError):
        raise BambuCameraError(
            "camera port must be numeric") from None
    if not 1 <= clean_port <= 65535:
        raise BambuCameraError("camera port out of range")
    try:
        budget = float(timeout)
    except (TypeError, ValueError):
        budget = READ_TIMEOUT_SECONDS
    budget = max(1.0, min(budget, 60.0))
    packet = build_auth_packet(username, access_code)
    factory = transport_factory or _default_transport
    try:
        sock = factory(clean_host, clean_port, budget)
    except BambuCameraError:
        raise
    except Exception as error:
        raise BambuCameraUnavailable(
            f"camera unreachable at {clean_host} "
            f"({type(error).__name__})") from error
    deadline = _time.monotonic() + budget
    try:
        try:
            sock.sendall(packet)
        except Exception as error:
            raise BambuCameraUnavailable(
                "camera auth not accepted") from error
        header = _read_exact(sock, FRAME_HEADER_BYTES, deadline)
        length = parse_frame_header(header)
        frame = _read_exact(sock, length, deadline)
        return check_jpeg(frame)
    except (BambuCameraError, BambuCameraUnavailable):
        raise
    except Exception as error:
        raise BambuCameraUnavailable(
            f"camera read failed ({type(error).__name__})"
        ) from error
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _read_exact(sock, count: int, deadline: float) -> bytes:
    """Read exactly ``count`` bytes (chunked) or refuse."""
    import time as _time
    chunks = bytearray()
    while len(chunks) < count:
        if _time.monotonic() >= deadline:
            raise BambuCameraUnavailable(
                "camera silent within budget (A1 firmware quirk: "
                "connection accepted, no frame)")
        try:
            piece = sock.recv(min(CHUNK_BYTES, count - len(chunks)))
        except Exception as error:
            raise BambuCameraUnavailable(
                f"camera read failed ({type(error).__name__})"
            ) from error
        if not piece:
            raise BambuCameraUnavailable(
                "camera closed the session (wrong access code "
                "or camera busy)")
        chunks += piece
    return bytes(chunks[:count])
