import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from inventory.db import connect, migrate
from inventory.maeve_telemetry import AtomicTelemetryStore, FixtureProvider, OfflineProvider
from inventory.web import InventoryWebApp


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "maeve_print_watch_states.json"


class MaeveDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        db.close()
        self.state = Path(self.temp.name) / "maeve.json"

    def tearDown(self):
        self.temp.cleanup()

    def app(self):
        return InventoryWebApp(self.database, p1s_telemetry_enabled=True, telemetry_path=self.state)

    def test_offline_view_and_api_are_zero_write(self):
        AtomicTelemetryStore(self.state).write(OfflineProvider().observe())
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        status, _, body = self.app().response("/integrations/p1s")
        self.assertEqual(status, 200)
        self.assertIn("OFFLINE", body.decode())
        api_status, headers, api_body = self.app().response("/api/print-watch/status")
        self.assertEqual(api_status, 200)
        self.assertIn("application/json", dict(headers)["Content-Type"])
        self.assertFalse(json.loads(api_body)["control_capable"])
        self.assertEqual(before, hashlib.sha256(self.database.read_bytes()).hexdigest())

    def test_demo_view_is_unmistakably_test_data_and_unmatched(self):
        AtomicTelemetryStore(self.state).write(FixtureProvider(FIXTURES, "printing_normally").observe())
        body = self.app().response("/integrations/p1s")[2].decode()
        self.assertIn("DEMO / PRINTING NORMALLY / TEST DATA", body)
        self.assertIn("UNMATCHED", body)
        self.assertNotIn('action="/integrations/p1s', body.casefold())

    def test_api_and_page_are_disabled_by_default(self):
        app = InventoryWebApp(self.database, p1s_telemetry_enabled=False, telemetry_path=self.state)
        self.assertEqual(app.response("/integrations/p1s")[0], 404)
        self.assertEqual(app.response("/api/print-watch/status")[0], 404)


if __name__ == "__main__":
    unittest.main()
