import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from inventory.db import connect, migrate
from inventory.telemetry import (
    ACCESS_CODE_VARIABLE,
    FEATURE_FLAG,
    HOST_VARIABLE,
    SERIAL_VARIABLE,
    BoundedReconnectPolicy,
    P1STelemetryConfig,
    ReadOnlyPrinterAdapter,
    TelemetryConfigurationError,
    TelemetryPayloadError,
    disconnected_projection,
    parse_bambu_status,
    sanitize_for_log,
)
from inventory.web import InventoryWebApp


ROOT = Path(__file__).resolve().parents[1]


class P1SReadOnlyTelemetryTests(unittest.TestCase):
    def test_feature_is_disabled_without_configuration(self):
        config = P1STelemetryConfig.from_environment({})
        self.assertFalse(config.enabled)
        self.assertIsNone(config.host)
        self.assertIsNone(config.access_code)

    def test_enabled_configuration_requires_host_serial_and_access_code(self):
        with self.assertRaisesRegex(TelemetryConfigurationError, HOST_VARIABLE):
            P1STelemetryConfig.from_environment({FEATURE_FLAG: "true"})
        with self.assertRaisesRegex(TelemetryConfigurationError, SERIAL_VARIABLE):
            P1STelemetryConfig.from_environment(
                {FEATURE_FLAG: "true", HOST_VARIABLE: "192.168.4.20"}
            )
        with self.assertRaisesRegex(TelemetryConfigurationError, ACCESS_CODE_VARIABLE):
            P1STelemetryConfig.from_environment(
                {
                    FEATURE_FLAG: "true",
                    HOST_VARIABLE: "192.168.4.20",
                    SERIAL_VARIABLE: "TEST-SERIAL",
                }
            )

    def test_configuration_repr_and_summary_never_expose_access_code(self):
        secret = "fixture-access-code"
        config = P1STelemetryConfig.from_environment(
            {
                FEATURE_FLAG: "true",
                HOST_VARIABLE: "p1s.local",
                SERIAL_VARIABLE: "TEST-SERIAL",
                ACCESS_CODE_VARIABLE: secret,
            }
        )
        self.assertNotIn(secret, repr(config))
        self.assertNotIn(secret, json.dumps(config.safe_summary()))
        self.assertEqual(config.safe_summary()["mode"], "subscribe_only")

    def test_sanitized_logging_redacts_secret_keys_and_values(self):
        secret = "fixture-access-code"
        safe = sanitize_for_log(
            {
                "access_code": secret,
                "nested": {"password": "fixture-password"},
                "message": f"failed using {secret}",
            },
            secrets=(secret,),
        )
        text = json.dumps(safe)
        self.assertNotIn(secret, text)
        self.assertNotIn("fixture-password", text)
        self.assertEqual(safe["access_code"], "[REDACTED]")

    def test_fixture_parser_projects_read_only_status(self):
        payload = json.loads(
            (ROOT / "tests" / "fixtures" / "bambu_p1s_status.json").read_text(
                encoding="utf-8"
            )
        )
        observed = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
        status = parse_bambu_status(payload, received_at=observed)
        self.assertEqual(status.equipment_number, "THS-EQP-000001")
        self.assertEqual(status.online_state, "online")
        self.assertEqual(status.printer_state, "RUNNING")
        self.assertEqual(status.active_job_name, "Hamster House")
        self.assertEqual(status.progress_percent, 42)
        self.assertEqual(status.remaining_seconds, 2220)
        self.assertEqual((status.current_layer, status.total_layers), (84, 200))
        self.assertEqual((status.active_ams, status.active_slot), (2, 1))
        self.assertEqual((status.filament_type, status.filament_color), ("PLA", "000000FF"))
        self.assertEqual(status.errors, ())
        self.assertEqual(status.warnings, ("0300-1200-0002-0001",))
        self.assertEqual(
            status.as_dashboard_projection()["authority"],
            "live_device_observation_only",
        )

    def test_invalid_or_out_of_range_payload_is_rejected(self):
        with self.assertRaises(TelemetryPayloadError):
            parse_bambu_status("not-json")
        with self.assertRaisesRegex(TelemetryPayloadError, "progress"):
            parse_bambu_status({"print": {"mc_percent": 101}})

    def test_disconnect_is_unknown_without_history_then_offline_and_stale(self):
        now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
        unknown = disconnected_projection(None, observed_at=now)
        self.assertEqual(unknown.online_state, "unknown")
        self.assertTrue(unknown.stale)
        previous = parse_bambu_status({"print": {"gcode_state": "IDLE"}}, received_at=now)
        offline = disconnected_projection(
            previous, observed_at=now + timedelta(seconds=31), stale_after_seconds=30
        )
        self.assertEqual(offline.online_state, "offline")
        self.assertTrue(offline.stale)
        self.assertEqual(offline.last_successful_update_at, now)

    def test_reconnect_backoff_is_bounded(self):
        policy = BoundedReconnectPolicy()
        self.assertEqual([policy.delay(i) for i in range(1, 7)], [1, 2, 4, 8, 16, 30])
        self.assertEqual(policy.delay(20), 30)
        self.assertEqual(policy.delay(1000000), 30)

    def test_adapter_contract_has_observe_only(self):
        members = set(ReadOnlyPrinterAdapter.__dict__)
        self.assertIn("observe", members)
        for forbidden in ("start", "pause", "stop", "load", "unload", "calibrate", "publish"):
            self.assertNotIn(forbidden, members)

    def test_dashboard_placeholder_is_disabled_by_default_and_zero_write(self):
        with tempfile.TemporaryDirectory() as temp_name:
            database = Path(temp_name) / "inventory.sqlite3"
            db = connect(database)
            migrate(db)
            db.close()
            before = hashlib.sha256(database.read_bytes()).hexdigest()
            disabled = InventoryWebApp(database, p1s_telemetry_enabled=False)
            status, _, _ = disabled.response("/integrations/p1s")
            self.assertEqual(status, 404)
            enabled = InventoryWebApp(database, p1s_telemetry_enabled=True)
            status, _, body = enabled.response("/integrations/p1s")
            page = body.decode("utf-8")
            self.assertEqual(status, 200)
            self.assertIn("Offline / unknown", page)
            self.assertIn("connection has been configured or claimed", page)
            self.assertIn("P1S Live Status", enabled.response("/")[2].decode("utf-8"))
            self.assertEqual(before, hashlib.sha256(database.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
