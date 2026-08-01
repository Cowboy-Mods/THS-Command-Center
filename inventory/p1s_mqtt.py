from __future__ import annotations

import socket
import ssl
import struct
import time
from typing import Callable

from .telemetry import P1STelemetryConfig


class SubscribeOnlyConnectionError(RuntimeError):
    """A bounded subscribe-only observation could not be completed."""


def capture_one_report(
    config: P1STelemetryConfig,
    *,
    timeout_seconds: float = 20.0,
    connection_factory: Callable[..., socket.socket] = socket.create_connection,
    tls_context_factory: Callable[[], ssl.SSLContext] | None = None,
) -> str:
    """Authenticate, subscribe to one report topic, and never publish a message."""
    if not config.enabled or not config.host or not config.serial or not config.access_code:
        raise SubscribeOnlyConnectionError("complete protected configuration is required")
    if timeout_seconds <= 0 or timeout_seconds > 60:
        raise SubscribeOnlyConnectionError("capture timeout must be between 0 and 60 seconds")
    topic = f"device/{config.serial}/report"
    deadline = time.monotonic() + timeout_seconds
    raw = tls = None
    try:
        raw = connection_factory((config.host, config.port), timeout=min(5, timeout_seconds))
        context = (tls_context_factory or _local_tls_context)()
        tls = context.wrap_socket(raw, server_hostname=config.host)
        _send(tls, _connect_packet(config.serial, config.access_code))
        packet_type, _, body = _read_packet(tls, deadline)
        if packet_type != 2 or len(body) != 2 or body[1] != 0:
            raise SubscribeOnlyConnectionError("printer rejected the protected MQTT session")
        _send(tls, _subscribe_packet(topic))
        subscribed = False
        while True:
            packet_type, flags, body = _read_packet(tls, deadline)
            if packet_type == 9:
                if len(body) < 3 or body[:2] != b"\x00\x01" or body[2] == 0x80:
                    raise SubscribeOnlyConnectionError("printer rejected the report subscription")
                subscribed = True
                continue
            if packet_type == 3 and subscribed:
                received_topic, payload = _publish_contents(flags, body)
                if received_topic == topic:
                    return payload.decode("utf-8")
    except SubscribeOnlyConnectionError:
        raise
    except (OSError, ssl.SSLError, UnicodeDecodeError) as exc:
        raise SubscribeOnlyConnectionError(
            "bounded encrypted subscribe-only connection failed"
        ) from exc
    finally:
        if tls is not None:
            try:
                _send(tls, b"\xe0\x00")
            except OSError:
                pass
            try:
                tls.close()
            except OSError:
                pass
        elif raw is not None:
            try:
                raw.close()
            except OSError:
                pass


def _local_tls_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _connect_packet(serial: str, access_code: str) -> bytes:
    client_id = f"ths-readonly-{serial[-6:]}"
    variable = _text("MQTT") + b"\x04\xc2" + struct.pack("!H", 15)
    payload = _text(client_id) + _text("bblp") + _text(access_code)
    return b"\x10" + _remaining(len(variable) + len(payload)) + variable + payload


def _subscribe_packet(topic: str) -> bytes:
    body = b"\x00\x01" + _text(topic) + b"\x00"
    return b"\x82" + _remaining(len(body)) + body


def _send(stream, packet: bytes) -> None:
    stream.sendall(packet)


def _read_packet(stream, deadline: float) -> tuple[int, int, bytes]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SubscribeOnlyConnectionError("subscribe-only capture timed out")
    stream.settimeout(remaining)
    first = _receive_exact(stream, 1)[0]
    length = 0
    multiplier = 1
    for _ in range(4):
        encoded = _receive_exact(stream, 1)[0]
        length += (encoded & 127) * multiplier
        if not encoded & 128:
            break
        multiplier *= 128
    else:
        raise SubscribeOnlyConnectionError("printer returned an invalid MQTT packet")
    return first >> 4, first & 0x0F, _receive_exact(stream, length)


def _receive_exact(stream, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = stream.recv(length - len(chunks))
        if not chunk:
            raise SubscribeOnlyConnectionError("printer closed the subscribe-only session")
        chunks.extend(chunk)
    return bytes(chunks)


def _publish_contents(flags: int, body: bytes) -> tuple[str, bytes]:
    if len(body) < 2:
        raise SubscribeOnlyConnectionError("printer returned an invalid report")
    topic_length = struct.unpack("!H", body[:2])[0]
    offset = 2 + topic_length
    if len(body) < offset:
        raise SubscribeOnlyConnectionError("printer returned an invalid report topic")
    topic = body[2:offset].decode("utf-8")
    if (flags >> 1) & 0x03:
        offset += 2
    return topic, body[offset:]


def _text(value: str) -> bytes:
    encoded = value.encode("utf-8")
    if len(encoded) > 65535:
        raise SubscribeOnlyConnectionError("MQTT text field is too long")
    return struct.pack("!H", len(encoded)) + encoded


def _remaining(value: int) -> bytes:
    encoded = bytearray()
    while True:
        digit = value % 128
        value //= 128
        if value:
            digit |= 128
        encoded.append(digit)
        if not value:
            return bytes(encoded)
