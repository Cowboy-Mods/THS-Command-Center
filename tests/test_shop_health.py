import tempfile
import unittest
from pathlib import Path

from inventory.db import connect, migrate
from inventory.health import ShopHealthEngine
from inventory.maintenance import MaintenanceWorkflow
from inventory.web import InventoryWebApp


class DashboardShopHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        self.asset_id = db.execute(
            "SELECT id FROM maintenance_assets WHERE display_name='THS Printer'"
        ).fetchone()[0]
        db.close()
        self.workflow = MaintenanceWorkflow(self.database, b"health-test-secret")
        self.app = InventoryWebApp(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def health(self):
        db = connect(self.database)
        try:
            return ShopHealthEngine.evaluate(db)
        finally:
            db.close()

    def page(self):
        return self.app.response("/")[2].decode()

    def fault(self, readiness, severity="high"):
        review = self.workflow.review("record_fault", {
            "asset_id": str(self.asset_id),
            "event_type": "fault_discovered",
            "initial_status": "in_progress",
            "severity": severity,
            "discovered_at": "2026-07-26T09:00:00-04:00",
            "due_at": "",
            "symptoms": "Test operational restriction.",
            "likely_cause": "Test-only cause.",
            "corrective_action": "Test-only corrective action.",
            "parts_required": "",
            "parts_used": "",
            "notes": "Temporary test database only.",
            "related_print_id": "",
            "readiness_state": readiness,
            "unattended_printing_allowed": "",
            "actor": "Cowboy",
        })
        return self.workflow.commit(review["token"])

    def test_01_normal_readiness_produces_green_shop_ready(self):
        health = self.health()
        self.assertEqual((health["signal"], health["label"]), ("green", "Shop Ready"))
        self.assertTrue(health["all_clear"])
        page = self.page()
        self.assertIn("Shop Ready", page)
        self.assertIn("All relevant equipment readiness states are normal", page)

    def test_02_no_unattended_printing_produces_yellow_attention(self):
        self.fault("no_unattended_printing")
        health = self.health()
        self.assertEqual(
            (health["signal"], health["label"]), ("yellow", "Attention Required")
        )
        self.assertFalse(health["all_clear"])

    def test_03_out_of_service_produces_red_operation_restricted(self):
        self.fault("out_of_service", severity="printer_unsafe")
        health = self.health()
        self.assertEqual(
            (health["signal"], health["label"]), ("red", "Operation Restricted")
        )

    def test_03a_printer_unsafe_severity_produces_red(self):
        self.fault("monitor_during_printing", severity="printer_unsafe")
        self.assertEqual(self.health()["signal"], "red")

    def test_04_green_all_clear_cannot_coexist_with_active_restriction(self):
        self.fault("monitor_during_printing", severity="medium")
        page = self.page()
        self.assertIn("Attention Required", page)
        self.assertNotIn("Shop Ready", page)
        self.assertNotIn("No critical shop warnings", page)
        self.assertNotIn("All relevant equipment readiness states are normal", page)

    def test_05_dashboard_surfaces_equipment_restriction_and_maintenance_details(self):
        record = self.fault("no_unattended_printing")
        page = self.page()
        self.assertIn("THS Printer", page)
        self.assertIn("No Unattended Printing", page)
        self.assertIn(record["event_number"], page)
        self.assertIn("Severity: High", page)
        self.assertIn("Status: In Progress", page)
        self.assertIn(f'/maintenance#maintenance-{record["record_id"]}', page)
        maintenance = self.app.response("/maintenance")[2].decode()
        self.assertIn(f'id="maintenance-{record["record_id"]}"', maintenance)

    def test_06_unrelated_dashboard_operational_content_remains(self):
        page = self.page()
        for expected in (
            "Active physical spools", "Printer status",
            "AMS occupancy and loaded filament", "Pending orders", "Recent activity",
        ):
            self.assertIn(expected, page)


if __name__ == "__main__":
    unittest.main()
