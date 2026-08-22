import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from inventory.maeve_telemetry import AtomicTelemetryStore, OfflineProvider
from scripts.maeve_telemetry_gateway import LoopbackServer, handler


class MaeveGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = AtomicTelemetryStore(Path(self.temp.name) / "state.json")
        self.store.write(OfflineProvider().observe())
        self.server = LoopbackServer(("127.0.0.1", 0), handler(self.store))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def test_get_only_endpoints(self):
        health = json.load(urllib.request.urlopen(self.base + "/health"))
        self.assertFalse(health["control_capable"])
        status = json.load(urllib.request.urlopen(self.base + "/status"))
        self.assertEqual(status["display_mode"], "OFFLINE")
        self.assertIn("OFFLINE", urllib.request.urlopen(self.base + "/rainmeter").read().decode())
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method), self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(self.base + "/status", method=method))
            self.assertEqual(error.exception.code, 405)

    def test_non_loopback_bind_is_refused(self):
        with self.assertRaises(RuntimeError):
            LoopbackServer(("0.0.0.0", 0), handler(self.store))


if __name__ == "__main__":
    unittest.main()
