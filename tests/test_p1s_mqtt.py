import json
import socket
import ssl
import unittest
from pathlib import Path

from inventory.p1s_mqtt import (
    SubscribeOnlyConnectionError,
    _connect_packet,
    _subscribe_packet,
    capture_one_report,
)
from inventory.telemetry import P1STelemetryConfig


ROOT = Path(__file__).resolve().parents[1]


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

    def version(self):
        return "TLSv1.2"

    def cipher(self):
        return ("SYNTHETIC-CIPHER", "TLSv1.2", 256)


class ByteFragmentedSocket(FakeSocket):
    def recv(self, length):
        return super().recv(min(length, 1))


class FakeContext:
    def __init__(self, stream):
        self.stream = stream

    def wrap_socket(self, raw, server_hostname):
        self.server_hostname = server_hostname
        return self.stream


class FailingContext:
    def wrap_socket(self, raw, server_hostname):
        raise ssl.SSLError("synthetic TLS failure")


def packet(kind, body, flags=0):
    return bytes([(kind << 4) | flags, len(body)]) + body


class P1SSubscribeOnlyTests(unittest.TestCase):
    def test_complete_connect_packet_matches_mqtt_311_vector(self):
        packet_bytes = _connect_packet("01P000000000000", "REDACTED")
        self.assertEqual(
            packet_bytes.hex(),
            "102f"
            "00044d515454"  # Protocol name: MQTT.
            "04"            # Protocol level: MQTT 3.1.1.
            "c2"            # Username, password, clean session; no will.
            "000f"          # Keepalive: 15 seconds.
            "00137468732d726561646f6e6c792d303030303030"
            "000462626c70"
            "00085245444143544544",
        )

    def test_complete_subscribe_packet_matches_mqtt_311_vector(self):
        topic = "device/01P000000000000/report"
        packet_bytes = _subscribe_packet(topic)
        self.assertEqual(
            packet_bytes.hex(),
            "8222"          # SUBSCRIBE fixed header and remaining length 34.
            "0001"          # Non-zero packet identifier 1.
            "001d"          # Topic length: 29 UTF-8 bytes.
            "6465766963652f3031503030303030303030303030302f7265706f7274"
            "00",           # Requested maximum QoS 0.
        )
        self.assertEqual(packet_bytes[6:-1], topic.encode("utf-8"))
        self.assertNotIn(b"\x00", packet_bytes[6:-1])
        self.assertNotIn(b"\r", packet_bytes[6:-1])
        self.assertNotIn(b"\n", packet_bytes[6:-1])
        self.assertNotIn(b"#", packet_bytes[6:-1])
        self.assertNotIn(b"+", packet_bytes[6:-1])

    def test_client_authenticates_subscribes_and_never_publishes(self):
        serial = "01P000000000000"
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
            diagnostics=(diagnostics := {}),
        )
        self.assertEqual(json.loads(result)["print"]["gcode_state"], "IDLE")
        packet_types = [item[0] >> 4 for item in stream.sent]
        self.assertEqual(packet_types, [1, 8, 14])
        self.assertIn(b"\x00\x04MQTT\x04", stream.sent[0])
        self.assertIn(b"\x00\x04bblp", stream.sent[0])
        self.assertNotIn(3, packet_types)
        self.assertIn(topic.encode(), stream.sent[1])
        self.assertNotIn(b"/request", b"".join(stream.sent))
        self.assertTrue(stream.closed)
        self.assertEqual(diagnostics["tcp_result"], "accepted")
        self.assertEqual(diagnostics["tls_result"], "established")
        self.assertEqual(diagnostics["tls_version"], "TLSv1.2")
        self.assertEqual(diagnostics["connack_result"], "accepted")
        self.assertEqual(diagnostics["suback_result"], "accepted")
        self.assertTrue(diagnostics["telemetry_received"])
        self.assertEqual(diagnostics["mqtt_publishes_sent"], 0)

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

    def config(self):
        return P1STelemetryConfig(
            enabled=True,
            host="192.168.4.99",
            serial="SYNTHETIC-SERIAL",
            access_code="FAKE-SECRET-ONLY",
        )

    def assert_category(self, expected, action):
        with self.assertRaises(SubscribeOnlyConnectionError) as caught:
            action()
        self.assertEqual(caught.exception.category, expected)
        self.assertNotIn("FAKE-SECRET-ONLY", json.dumps(caught.exception.safe_summary()))
        return caught.exception

    def test_connack_reasons_are_distinguished_without_secrets(self):
        expectations = {
            1: "unsupported_protocol_version",
            2: "client_identifier_rejected",
            3: "broker_unavailable",
            4: "rejected_username_password",
            5: "unauthorized_client",
        }
        for code, category in expectations.items():
            with self.subTest(code=code):
                stream = FakeSocket(packet(2, bytes([0, code])))
                error = self.assert_category(
                    category,
                    lambda stream=stream: capture_one_report(
                        self.config(),
                        connection_factory=lambda *args, **kwargs: stream,
                        tls_context_factory=lambda: FakeContext(stream),
                    ),
                )
                self.assertEqual(error.mqtt_code, code)

    def test_broker_unavailable_tls_failure_and_timeout_are_distinguished(self):
        self.assert_category(
            "broker_unavailable",
            lambda: capture_one_report(
                self.config(),
                connection_factory=lambda *args, **kwargs: (_ for _ in ()).throw(
                    ConnectionRefusedError("synthetic")
                ),
            ),
        )
        raw = FakeSocket(b"")
        self.assert_category(
            "tls_failure",
            lambda: capture_one_report(
                self.config(),
                connection_factory=lambda *args, **kwargs: raw,
                tls_context_factory=lambda: FailingContext(),
            ),
        )
        self.assert_category(
            "timeout",
            lambda: capture_one_report(
                self.config(),
                connection_factory=lambda *args, **kwargs: (_ for _ in ()).throw(
                    socket.timeout("synthetic")
                ),
            ),
        )

    def test_subscription_rejection_is_distinct_and_topic_is_exact(self):
        stream = FakeSocket(packet(2, b"\x00\x00") + packet(9, b"\x00\x01\x80"))
        self.assert_category(
            "subscription_rejected",
            lambda: capture_one_report(
                self.config(),
                connection_factory=lambda *args, **kwargs: stream,
                tls_context_factory=lambda: FakeContext(stream),
            ),
        )
        self.assertIn(b"device/SYNTHETIC-SERIAL/report", stream.sent[1])
        self.assertNotIn(b"/request", b"".join(stream.sent))

    def test_connection_loss_reports_exact_protocol_stage(self):
        stream = FakeSocket(packet(2, b"\x00\x00"))
        error = self.assert_category(
            "connection_lost",
            lambda: capture_one_report(
                self.config(),
                connection_factory=lambda *args, **kwargs: stream,
                tls_context_factory=lambda: FakeContext(stream),
            ),
        )
        self.assertEqual(error.stage, "suback_wait")

    def test_fragmented_tls_reads_are_reassembled_byte_by_byte(self):
        serial = "01P000000000000"
        topic = f"device/{serial}/report"
        payload = json.dumps({"print": {"gcode_state": "IDLE"}}).encode()
        publish_body = len(topic).to_bytes(2, "big") + topic.encode() + payload
        incoming = packet(2, b"\x00\x00") + packet(9, b"\x00\x01\x00") + packet(3, publish_body)
        stream = ByteFragmentedSocket(incoming)
        result = capture_one_report(
            P1STelemetryConfig(
                enabled=True,
                host="192.0.2.1",
                serial=serial,
                access_code="FAKE-SECRET-ONLY",
            ),
            connection_factory=lambda *args, **kwargs: stream,
            tls_context_factory=lambda: FakeContext(stream),
        )
        self.assertEqual(json.loads(result)["print"]["gcode_state"], "IDLE")
        self.assertEqual([item[0] >> 4 for item in stream.sent], [1, 8, 14])

    def test_diagnostic_cli_has_no_credential_argument_or_secret_output_path(self):
        script = (ROOT / "scripts" / "p1s_subscribe_once.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("exc.safe_summary()", script)
        self.assertNotIn("access_code", script)
        self.assertNotIn("load_p1s_access_code", script)


if __name__ == "__main__":
    unittest.main()
