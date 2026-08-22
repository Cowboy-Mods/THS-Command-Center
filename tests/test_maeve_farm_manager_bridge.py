import unittest

from scripts.maeve_farm_manager_bridge import _handshake_accepted, _is_devices_response, _select_target, _target


class MaeveFarmManagerBridgeTests(unittest.TestCase):
    def test_websocket_handshake_acceptance_is_case_insensitive_for_bytes(self):
        expected = b"AbCdEf=="
        header = b"HTTP/1.1 101 Switching Protocols\r\nSec-WebSocket-Accept: abcdef==\r\n\r\n"
        self.assertTrue(_handshake_accepted(header, expected))
        self.assertFalse(_handshake_accepted(b"HTTP/1.1 403 Forbidden\r\n\r\n", expected))

    def test_devices2_match_is_exact_and_read_only(self):
        good = {"method": "Network.responseReceived", "params": {"response": {"url": "https://127.0.0.1:8888/devices2?use_lite=true", "status": 200}}}
        self.assertTrue(_is_devices_response(good))
        for url in ("https://127.0.0.1:8888/devices", "https://127.0.0.1:8888/devices2/write", "https://127.0.0.1:8888/tasks"):
            with self.subTest(url=url):
                changed = {"method": "Network.responseReceived", "params": {"response": {"url": url, "status": 200}}}
                self.assertFalse(_is_devices_response(changed))

    def test_discovery_rejects_non_loopback(self):
        for url in ("http://192.0.2.10:9223", "https://example.test:9223", "file:///tmp/debug"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    _target(url)

    def test_discovery_selects_printer_page_when_monitor_page_also_exists(self):
        targets = [
            {"type": "page", "url": "file:///app/index.html#/monitor", "webSocketDebuggerUrl": "ws://loopback/monitor"},
            {"type": "page", "url": "file:///app/index.html#/printers", "webSocketDebuggerUrl": "ws://loopback/printers"},
        ]
        self.assertEqual(_select_target(targets), "ws://loopback/printers")

    def test_discovery_rejects_ambiguous_pages_without_printer_page(self):
        targets = [
            {"type": "page", "url": "file:///app/index.html#/monitor", "webSocketDebuggerUrl": "ws://loopback/monitor"},
            {"type": "page", "url": "file:///app/index.html#/settings", "webSocketDebuggerUrl": "ws://loopback/settings"},
        ]
        with self.assertRaises(RuntimeError):
            _select_target(targets)


if __name__ == "__main__":
    unittest.main()
