import json
import tempfile
import unittest
from pathlib import Path

from inventory.maeve_push import ProtectedWebPushService, PushConfigurationError, _is_base64url


class TestPushService(ProtectedWebPushService):
    def __init__(self, root):
        super().__init__(root)
        self.delivered = []

    def _store_protected(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    def _send(self, alert):
        self.delivered.append(alert["kind"])


class MaevePushTests(unittest.TestCase):
    def test_subscription_validation_rejects_non_https_and_bad_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = TestPushService(Path(temporary))
            with self.assertRaises(PushConfigurationError):
                service.save_subscription({"endpoint": "http://example.test", "keys": {}})
            with self.assertRaises(PushConfigurationError):
                service.save_subscription({"endpoint": "https://example.test", "keys": {"p256dh": "bad key", "auth": "also bad"}})

    def test_pending_alerts_send_once_without_printer_control(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = TestPushService(Path(temporary))
            service.save_subscription({"endpoint": "https://example.test/push", "keys": {"p256dh": "A" * 32, "auth": "B" * 24}})
            alerts = [{"id": "one", "kind": "complete"}, {"id": "two", "kind": "offline"}]
            self.assertEqual(service.send_pending(alerts), 2)
            self.assertEqual(service.send_pending(alerts), 0)
            self.assertEqual(service.delivered, ["offline", "complete"])

    def test_key_alphabet_is_restricted(self):
        self.assertTrue(_is_base64url("ABC_def-012="))
        self.assertFalse(_is_base64url("ABC def"))

    def test_milestone_kinds_are_allowed_without_job_details(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = TestPushService(Path(temporary))
            service.save_subscription({"endpoint": "https://example.test/push", "keys": {"p256dh": "A" * 32, "auth": "B" * 24}})
            self.assertEqual(service.send_pending([{"id": "m50", "kind": "milestone-50"}]), 1)
            self.assertEqual(service.delivered, ["milestone-50"])
            self.assertEqual(service.send_pending([{"id": "layer1", "kind": "first-layer-complete"}]), 1)
            self.assertEqual(service.delivered, ["milestone-50", "first-layer-complete"])


if __name__ == "__main__":
    unittest.main()
