import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from inventory.maeve_telemetry import (
    AtomicTelemetryStore,
    FixtureProvider,
    MaeveTelemetry,
    OfflineProvider,
    compare_reported_slot,
    rainmeter_line,
    sanitize_telemetry_payload,
    write_rainmeter_feed,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "maeve_print_watch_states.json"


class MaeveTelemetryTests(unittest.TestCase):
    def test_offline_provider_fails_closed(self):
        status = OfflineProvider().observe()
        self.assertEqual(status.display_mode, "OFFLINE")
        self.assertTrue(status.offline)
        self.assertFalse(status.control_capable)

    def test_every_fixture_is_visible_demo_and_valid(self):
        names = json.loads(FIXTURES.read_text(encoding="utf-8"))
        for name in names:
            with self.subTest(name=name):
                status = FixtureProvider(FIXTURES, name).observe()
                self.assertEqual(status.display_mode, "DEMO")
                self.assertIn("TEST DATA", status.demo_label)
                self.assertFalse(status.control_capable)

    def test_stale_logic(self):
        old = datetime.now(timezone.utc) - timedelta(minutes=5)
        status = MaeveTelemetry(connection_state="online", printer_state="printing", last_source_update=old.isoformat())
        self.assertEqual(status.with_freshness(stale_after_seconds=30).display_mode, "STALE")

    def test_atomic_state_and_feed(self):
        with tempfile.TemporaryDirectory() as name:
            state = Path(name) / "state.json"
            feed = Path(name) / "feed.txt"
            status = FixtureProvider(FIXTURES, "printing_normally").observe()
            AtomicTelemetryStore(state).write(status)
            write_rainmeter_feed(feed, status)
            self.assertEqual(AtomicTelemetryStore(state).read().current_job_name, "DEMO BENCHY")
            self.assertIn("DEMO", feed.read_text(encoding="utf-8"))
            self.assertFalse(list(Path(name).glob("*.tmp")))

    def test_invalid_or_missing_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "missing.json"
            self.assertEqual(AtomicTelemetryStore(path).read().display_mode, "OFFLINE")
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(AtomicTelemetryStore(path).read().display_mode, "OFFLINE")

    def test_rainmeter_feed_has_no_raw_json_or_secret_fields(self):
        line = rainmeter_line(FixtureProvider(FIXTURES, "printing_normally").observe())
        self.assertNotIn("{", line)
        self.assertNotIn("access_code", line.casefold())
        self.assertEqual(line.count("|"), 13)

    def test_inventory_comparison_never_guesses(self):
        status = FixtureProvider(FIXTURES, "filament_runout").observe()
        unmatched = compare_reported_slot(status, maintenance_restricted=True)
        self.assertEqual(unmatched["match_confidence"], "unmatched")
        self.assertEqual(unmatched["mismatch_warning"], "UNMATCHED")
        self.assertTrue(unmatched["maintenance_restriction"])

    def test_ingestion_allowlist_accepts_monitoring_and_camera_status(self):
        status = sanitize_telemetry_payload({
            "connection_state": "online",
            "printer_state": "printing",
            "current_job_name": "TEST PART",
            "progress_percent": 25,
            "remaining_seconds": 600,
            "current_layer": 4,
            "total_layers": 20,
            "nozzle_actual_c": 220,
            "bed_actual_c": 55,
            "active_ams_unit": 1,
            "active_ams_slot": 2,
            "filament_type": "PLA",
            "warning_text": None,
            "camera_available": True,
            "camera_status": "available",
        })
        self.assertTrue(status.camera_available)
        self.assertEqual(status.camera_status, "available")
        self.assertFalse(status.control_capable)

    def test_ingestion_rejects_secrets_raw_config_and_controls(self):
        for prohibited in (
            "access_code",
            "serial_number",
            "account_token",
            "mqtt_password",
            "raw_configuration",
            "command_payload",
            "pause",
            "resume",
            "cancel",
            "light_control",
            "file_upload",
            "print_start",
            "gcode",
        ):
            with self.subTest(field=prohibited):
                with self.assertRaises(ValueError):
                    sanitize_telemetry_payload({prohibited: "blocked"})


if __name__ == "__main__":
    unittest.main()
