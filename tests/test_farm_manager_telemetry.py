import unittest
from datetime import datetime, timezone

from inventory.farm_manager_telemetry import sanitize_farm_manager_devices


NOW = datetime(2026, 8, 22, 2, 45, tzinfo=timezone.utc)


def response(state="IDLE", *, online=True):
    return {
        "devices": [{
            "dev_id": "REDACTED-DEVICE-ID",
            "dev_ip": "192.0.2.10",
            "online": online,
            "liveview_stream_status": "available",
            "report_status": {
                "gcode_state": state,
                "subtask_name": "THS TEST PANEL" if state == "RUNNING" else "",
                "mc_percent": 42 if state == "RUNNING" else 0,
                "mc_remaining_time": 12 if state == "RUNNING" else 0,
                "layer_num": 21 if state == "RUNNING" else 0,
                "total_layer_num": 50 if state == "RUNNING" else 0,
                "nozzle_temper": 219.5 if state == "RUNNING" else 24,
                "nozzle_target_temper": 220 if state == "RUNNING" else 0,
                "bed_temper": 55,
                "bed_target_temper": 55 if state == "RUNNING" else 0,
                "chamber_temper": 31,
                "hms": [],
                "ip_cam": {"ipcam_dev": "1"},
                "ams": {"ams": [{"id": "0", "humidity": 18, "tray": [
                    {"id": "0", "tray_type": "PLA", "tray_color": "000000FF", "remain": -1},
                    {"id": "1", "tray_type": "PLA", "tray_color": "FF6A13FF", "remain": 42},
                ]}]},
            },
        }]
    }


class FarmManagerTelemetryTests(unittest.TestCase):
    def test_idle_response_becomes_live_monitoring_only_snapshot(self):
        snapshot = sanitize_farm_manager_devices(response(), observed_at=NOW)
        self.assertEqual(snapshot.display_mode, "LIVE")
        self.assertEqual(snapshot.printer_state, "idle")
        self.assertFalse(snapshot.control_capable)
        self.assertNotIn("dev_id", snapshot.as_dict())
        self.assertNotIn("dev_ip", snapshot.as_dict())

    def test_printing_fields_are_sanitized_and_remaining_minutes_become_seconds(self):
        snapshot = sanitize_farm_manager_devices(response("RUNNING"), observed_at=NOW)
        self.assertEqual(snapshot.current_job_name, "THS TEST PANEL")
        self.assertEqual(snapshot.progress_percent, 42)
        self.assertEqual(snapshot.remaining_seconds, 720)
        self.assertEqual((snapshot.current_layer, snapshot.total_layers), (21, 50))
        self.assertEqual(snapshot.nozzle_target_c, 220)
        self.assertEqual(snapshot.ams_slots[0]["filament_color"], "#000000")
        self.assertIsNone(snapshot.ams_slots[0]["remaining_percent"])
        self.assertEqual(snapshot.ams_slots[1]["remaining_percent"], 42)
        self.assertEqual(snapshot.ams_1_humidity, 18)

    def test_offline_fails_closed(self):
        snapshot = sanitize_farm_manager_devices(response(online=False), observed_at=NOW)
        self.assertEqual(snapshot.display_mode, "OFFLINE")
        self.assertEqual(snapshot.printer_state, "offline")

    def test_rejects_missing_or_multiple_printers(self):
        for payload in ({}, {"devices": []}, {"devices": [response()["devices"][0]] * 2}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    sanitize_farm_manager_devices(payload, observed_at=NOW)


if __name__ == "__main__":
    unittest.main()
