from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import select
import shutil
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inventory.farm_manager_telemetry import sanitize_farm_manager_devices
from inventory.maeve_telemetry import AtomicTelemetryStore, OfflineProvider, write_rainmeter_feed


def _handshake_accepted(header: bytes, expected: bytes) -> bool:
    return header.startswith(b"HTTP/1.1 101 ") and expected.lower() in header.lower()


class LocalCdpSocket:
    """Minimal loopback-only CDP transport; it has no printer protocol methods."""

    def __init__(self, url: str, timeout: float = 70.0):
        parsed = urlsplit(url)
        if parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("CDP endpoint must be loopback WebSocket")
        self.socket = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=timeout)
        self.socket.settimeout(timeout)
        self._deadline = time.monotonic() + timeout
        self._buffer = bytearray()
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {parsed.path} HTTP/1.1\r\nHost: {parsed.hostname}:{parsed.port or 80}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        self.socket.sendall(request)
        header = self._receive_until(b"\r\n\r\n", 16384)
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest())
        if not _handshake_accepted(header, expected):
            self.close()
            raise RuntimeError("CDP WebSocket handshake was rejected")

    def close(self) -> None:
        try:
            self.socket.close()
        except OSError:
            pass

    def send_json(self, value: dict) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
        mask = os.urandom(4)
        length = len(payload)
        header = bytearray([0x81])
        if length < 126:
            header.append(0x80 | length)
        elif length <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.socket.sendall(bytes(header) + mask + masked)

    def receive_json(self) -> dict:
        while True:
            if time.monotonic() >= self._deadline:
                raise TimeoutError("CDP receive deadline expired")
            first, second = self._receive_exact(2)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._receive_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._receive_exact(8))[0]
            mask = self._receive_exact(4) if masked else b""
            payload = self._receive_exact(length)
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 0x8:
                raise ConnectionError("CDP WebSocket closed")
            if opcode == 0x9:
                self._send_control(0xA, payload)
                continue
            if opcode != 0x1:
                continue
        return json.loads(payload.decode("utf-8"))

    def set_timeout(self, seconds: float) -> None:
        seconds = max(0.1, seconds)
        self._deadline = time.monotonic() + seconds
        self.socket.settimeout(seconds)

    def _send_control(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.socket.sendall(bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + masked)

    def _receive_exact(self, length: int) -> bytes:
        chunks = bytearray()
        if self._buffer:
            take = min(length, len(self._buffer))
            chunks.extend(self._buffer[:take])
            del self._buffer[:take]
        while len(chunks) < length:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.socket], [], [], remaining)[0]:
                raise TimeoutError("CDP receive deadline expired")
            piece = self.socket.recv(length - len(chunks))
            if not piece:
                raise ConnectionError("CDP socket closed")
            chunks.extend(piece)
        return bytes(chunks)

    def _receive_until(self, marker: bytes, maximum: int) -> bytes:
        chunks = bytearray()
        while marker not in chunks:
            if len(chunks) >= maximum:
                raise RuntimeError("CDP handshake exceeded limit")
            chunks.extend(self.socket.recv(1024))
        end = chunks.index(marker) + len(marker)
        self._buffer.extend(chunks[end:])
        return bytes(chunks[:end])


def _select_target(targets: list[dict]) -> str:
    pages = [item for item in targets if item.get("type") == "page" and item.get("webSocketDebuggerUrl")]
    printer_pages = [item for item in pages if urlsplit(str(item.get("url", ""))).fragment == "/printers"]
    if len(printer_pages) == 1:
        return str(printer_pages[0]["webSocketDebuggerUrl"])
    if len(pages) == 1:
        return str(pages[0]["webSocketDebuggerUrl"])
    raise RuntimeError("exactly one Farm Manager printer page target is required")


def _target(debug_url: str) -> str:
    parsed = urlsplit(debug_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("debug discovery must use loopback HTTP")
    with urlopen(debug_url.rstrip("/") + "/json/list", timeout=3) as response:
        targets = json.load(response)
    return _select_target(targets)


def _is_devices_response(message: dict) -> bool:
    if message.get("method") != "Network.responseReceived":
        return False
    response = message.get("params", {}).get("response", {})
    path = urlsplit(str(response.get("url", ""))).path
    return path == "/devices2" and int(response.get("status", 0)) == 200


def capture_once(debug_url: str, timeout: float = 70.0) -> dict:
    node_helper = Path(__file__).with_name("maeve_farm_manager_cdp_once.js")
    bundled_node = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
    node = str(bundled_node) if bundled_node.is_file() else shutil.which("node.exe")
    if not node:
        raise RuntimeError("verified local Node runtime was not found")
    completed = subprocess.run(
        [node, str(node_helper), debug_url, str(int(timeout * 1000))],
        capture_output=True,
        text=True,
        timeout=timeout + 5,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise TimeoutError("Farm Manager capture did not complete")
    return json.loads(completed.stdout)


def capture_once_legacy(debug_url: str, timeout: float = 70.0) -> dict:
    client = LocalCdpSocket(_target(debug_url), timeout=timeout)
    sequence = 1
    try:
        client.send_json({"id": sequence, "method": "Network.enable", "params": {}})
        sequence += 1
        client.send_json({"id": sequence, "method": "Page.reload", "params": {"ignoreCache": True}})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            client.set_timeout(deadline - time.monotonic())
            message = client.receive_json()
            if not _is_devices_response(message):
                continue
            sequence += 1
            request_id = message["params"]["requestId"]
            client.send_json({"id": sequence, "method": "Network.getResponseBody", "params": {"requestId": request_id}})
            while time.monotonic() < deadline:
                client.set_timeout(deadline - time.monotonic())
                body_message = client.receive_json()
                if body_message.get("id") != sequence:
                    continue
                body = body_message.get("result", {}).get("body")
                if not isinstance(body, str):
                    raise RuntimeError("Farm Manager response body was unavailable")
                return json.loads(body)
        raise TimeoutError("no current Farm Manager telemetry arrived")
    finally:
        client.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Maeve bridge for the official Farm Manager Client")
    parser.add_argument("--debug-url", default="http://127.0.0.1:9223")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--rainmeter-feed", type=Path)
    parser.add_argument("--timeout", type=float, default=70.0)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--stop-signal", type=Path)
    args = parser.parse_args(argv)
    if args.stop_signal:
        args.stop_signal.unlink(missing_ok=True)
    first = True
    while True:
        try:
            raw = capture_once(args.debug_url, timeout=args.timeout)
            snapshot = sanitize_farm_manager_devices(raw)
            result = 0
        except Exception as error:
            snapshot = OfflineProvider().observe()
            result = 1
            category = type(error).__name__
        AtomicTelemetryStore(args.state).write(snapshot)
        if args.rainmeter_feed:
            write_rainmeter_feed(args.rainmeter_feed, snapshot)
        if first or not args.watch:
            report = {"result": snapshot.display_mode, "printer_state": snapshot.printer_state, "control_capable": False}
            if result:
                report["category"] = category
            print(json.dumps(report), flush=True)
            first = False
        if not args.watch:
            return result
        if args.stop_signal and args.stop_signal.exists():
            args.stop_signal.unlink(missing_ok=True)
            return 0
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
