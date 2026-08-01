import json
import unittest

from inventory.p1s_mqtt import capture_one_report
from inventory.telemetry import P1STelemetryConfig


class FakeSocket:
    def __init__(self, incoming):
        self.incoming = bytearray(incoming)
        self.sent = []
        self.closed = False

    def sendall(self, value):
        self.sent.append(bytes(value))

    def recv(self, length):
        value = bytes(self.incoming[:length])
        del self.incoming[:length]
        return value

    def settimeout(self, value):
        self.timeout = value

    def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, stream):
        self.stream = stream

    def wrap_socket(self, raw, server_hostname):
        self.server_hostname = server_hostname
        return self.stream


def packet(kind, body, flags=0):
    return bytes([(kind << 4) | flags, len(body)]) + body


class P1SSubscribeOnlyTests(unittest.TestCase):
    def test_client_authenticates_subscribes_and_never_publishes(self):
        serial = "SYNTHETIC-SERIAL"
        topic = f"device/{serial}/report"
        payload = json.dumps({"print": {"gcode_state": "IDLE"}}).encode()
        publish_body = len(topic).to_bytes(2, "big") + topic.encode() + payload
        incoming = packet(2, b"\x00\x00") + packet(9, b"\x00\x01\x00") + packet(3, publish_body)
        stream = FakeSocket(incoming)
        context = FakeContext(stream)
        config = P1STelemetryConfig(
            enabled=True,
            host="192.168.4.99",
            serial=serial,
            access_code="FAKE-SECRET-ONLY",
        )
        result = capture_one_report(
            config,
            connection_factory=lambda *args, **kwargs: stream,
            tls_context_factory=lambda: context,
        )
        self.assertEqual(json.loads(result)["print"]["gcode_state"], "IDLE")
        packet_types = [item[0] >> 4 for item in stream.sent]
        self.assertEqual(packet_types, [1, 8, 14])
        self.assertNotIn(3, packet_types)
        self.assertIn(topic.encode(), stream.sent[1])
        self.assertNotIn(b"/request", b"".join(stream.sent))
        self.assertTrue(stream.closed)

    def test_error_text_never_contains_fake_credential(self):
        secret = "FAKE-SECRET-ONLY"
        stream = FakeSocket(packet(2, b"\x00\x05"))
        config = P1STelemetryConfig(
            enabled=True, host="192.168.4.99", serial="TEST", access_code=secret
        )
        with self.assertRaises(Exception) as caught:
            capture_one_report(
                config,
                connection_factory=lambda *args, **kwargs: stream,
                tls_context_factory=lambda: FakeContext(stream),
            )
        self.assertNotIn(secret, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
