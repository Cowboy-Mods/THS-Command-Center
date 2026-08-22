from __future__ import annotations

import socket
import ssl
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


CAMERA_PORT = 6000
MAX_FRAME_BYTES = 10_000_000


class CameraValidationError(RuntimeError):
    def __init__(self, category: str, stage: str):
        super().__init__(category)
        self.category = category
        self.stage = stage


@dataclass(frozen=True)
class CameraFrame:
    jpeg: bytes
    width: int
    height: int
    tls_version: str
    tls_cipher: str


class CameraSession:
    """One authenticated P1/A1 camera connection with no command surface."""

    def __init__(
        self,
        host: str,
        access_code: str,
        *,
        connection_factory: Callable[..., socket.socket] = socket.create_connection,
        tls_context_factory: Callable[[], ssl.SSLContext] | None = None,
    ):
        self.host = host
        self._access_code = access_code
        self._connection_factory = connection_factory
        self._tls_context_factory = tls_context_factory
        self._raw = None
        self._secure = None

    def open(self, timeout_seconds: float = 5.0) -> None:
        if self._secure is not None:
            raise CameraValidationError("duplicate_connection", "configuration")
        try:
            self._raw = self._connection_factory((self.host, CAMERA_PORT), timeout=timeout_seconds)
            context = self._tls_context_factory() if self._tls_context_factory else _camera_tls_context()
            self._secure = context.wrap_socket(self._raw, server_hostname=self.host)
            self._secure.settimeout(timeout_seconds)
            self._secure.sendall(authentication_record(self._access_code))
            self._access_code = ""
        except ssl.SSLError as exc:
            self.close()
            raise CameraValidationError("tls_failed", "tls") from exc
        except OSError as exc:
            self.close()
            raise CameraValidationError("connection_failed", "tcp") from exc

    def read_frame(self, timeout_seconds: float = 5.0) -> CameraFrame:
        if self._secure is None:
            raise CameraValidationError("connection_not_open", "configuration")
        deadline = time.monotonic() + timeout_seconds
        header = _receive_exact(self._secure, 16, deadline)
        payload_size, track, flags, reserved = struct.unpack("<IIII", header)
        if not 4 <= payload_size <= MAX_FRAME_BYTES:
            raise CameraValidationError("invalid_frame_size", "frame_header")
        if track != 0 or flags != 1 or reserved != 0:
            raise CameraValidationError("invalid_frame_header", "frame_header")
        jpeg = _receive_exact(self._secure, payload_size, deadline)
        width, height = jpeg_dimensions(jpeg)
        cipher = self._secure.cipher()
        return CameraFrame(
            jpeg=jpeg,
            width=width,
            height=height,
            tls_version=self._secure.version() or "unknown",
            tls_cipher=(cipher[0] if cipher else "unknown"),
        )

    def close(self) -> None:
        secure, raw = self._secure, self._raw
        self._secure = None
        self._raw = None
        self._access_code = ""
        if secure is not None:
            try:
                secure.shutdown(socket.SHUT_RDWR)
            except (AttributeError, OSError):
                pass
            secure.close()
        elif raw is not None:
            raw.close()


def authentication_record(access_code: str) -> bytes:
    try:
        secret = access_code.strip().encode("ascii")
    except UnicodeEncodeError as exc:
        raise CameraValidationError("invalid_credential_format", "credential") from exc
    if not secret or len(secret) > 32:
        raise CameraValidationError("invalid_credential_format", "credential")
    return (
        struct.pack("<IIII", 0x40, 0x3000, 0, 0)
        + b"bblp".ljust(32, b"\0")
        + secret.ljust(32, b"\0")
    )


def capture_one_frame(
    host: str,
    access_code: str,
    *,
    timeout_seconds: float = 20.0,
    connection_factory: Callable[..., socket.socket] = socket.create_connection,
    tls_context_factory: Callable[[], ssl.SSLContext] | None = None,
) -> CameraFrame:
    if timeout_seconds <= 0 or timeout_seconds > 20:
        raise CameraValidationError("invalid_timeout", "configuration")
    session = CameraSession(
        host,
        access_code,
        connection_factory=connection_factory,
        tls_context_factory=tls_context_factory,
    )
    try:
        session.open(timeout_seconds=min(5.0, timeout_seconds))
        return session.read_frame(timeout_seconds=timeout_seconds)
    except CameraValidationError:
        raise
    except (TimeoutError, socket.timeout) as exc:
        raise CameraValidationError("timeout", "camera_capture") from exc
    finally:
        session.close()


def jpeg_dimensions(jpeg: bytes) -> tuple[int, int]:
    if len(jpeg) < 4 or not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        raise CameraValidationError("invalid_jpeg_signature", "jpeg_validation")
    index = 2
    while index + 4 <= len(jpeg):
        if jpeg[index] != 0xFF:
            index += 1
            continue
        while index < len(jpeg) and jpeg[index] == 0xFF:
            index += 1
        if index >= len(jpeg):
            break
        marker = jpeg[index]
        index += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(jpeg):
            break
        segment_length = int.from_bytes(jpeg[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > len(jpeg):
            break
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if segment_length < 7:
                break
            height = int.from_bytes(jpeg[index + 3 : index + 5], "big")
            width = int.from_bytes(jpeg[index + 5 : index + 7], "big")
            if width > 0 and height > 0:
                return width, height
            break
        index += segment_length
    raise CameraValidationError("jpeg_dimensions_unavailable", "jpeg_validation")


def write_validated_frame(path: Path, frame: CameraFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(frame.jpeg)
    temporary.replace(path)


def _camera_tls_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _receive_exact(stream, size: int, deadline: float) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        stream.settimeout(_remaining(deadline))
        chunk = stream.recv(size - len(chunks))
        if not chunk:
            raise CameraValidationError("connection_closed", "camera_capture")
        chunks.extend(chunk)
    return bytes(chunks)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CameraValidationError("timeout", "camera_capture")
    return remaining
