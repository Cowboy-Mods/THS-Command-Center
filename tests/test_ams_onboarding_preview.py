import tempfile
import unittest
from pathlib import Path

from inventory.actions import ActionContext, InventoryActionService
from inventory.ams_onboarding_preview import (
    AMSOnboardingPreview,
    AMSOnboardingPreviewError,
)
from inventory.db import connect, migrate
from inventory.equipment import EquipmentRegistryService


class AMSOnboardingPreviewTests(unittest.TestCase):
    AMS_1_SERIAL = "19C-06A-522-00-22-97"
    AMS_2_SERIAL = "19C-51A-6-204-00 EWR"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        manufacturer_id = db.execute(
            "SELECT id FROM manufacturers WHERE name='Bambu Lab'"
        ).fetchone()[0]
        db.close()
        registry = EquipmentRegistryService(
            self.database, secret=b"ams-onboarding-preview-test"
        )
        review = registry.review_register(
            {
                "actor": "Cowboy",
                "reason": "Temporary P1S preview fixture.",
                "display_name": "Bambu Lab P1S",
                "type_code": "printer",
                "subtype_code": "fdm_printer",
                "manufacturer_id": str(manufacturer_id),
                "model": "P1S",
                "lifecycle_state": "installed",
                "operational_status": "operating",
                "notes": "Temporary test fixture.",
                "capabilities": [],
            }
        )
        registry.commit_register(review["token"], confirmed=True)
        self.preview = AMSOnboardingPreview(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def build(self, **changes):
        values = {
            "ams_1_serial": self.AMS_1_SERIAL,
            "ams_2_serial": self.AMS_2_SERIAL,
        }
        values.update(changes)
        return self.preview.build(**values)

    def test_01_preview_is_zero_write_and_allocates_two_permanent_ids(self):
        before = self.database.read_bytes()
        result = self.build()
        self.assertEqual(before, self.database.read_bytes())
        self.assertTrue(result["database_unchanged"])
        self.assertEqual(
            [unit["registry_record"]["equipment_number"] for unit in result["units"]],
            ["THS-EQP-000002", "THS-EQP-000003"],
        )
        self.assertEqual(result["expected_row_changes"]["total_insert_rows"], 16)
        self.assertEqual(result["expected_row_changes"]["updates"], [])
        self.assertEqual(result["expected_row_changes"]["deletes"], [])

    def test_02_reported_serial_spacing_and_exact_names_are_preserved(self):
        result = self.build()
        self.assertEqual(
            result["units"][0]["registry_record"]["manufacturer_serial_number"],
            self.AMS_1_SERIAL,
        )
        self.assertEqual(
            result["units"][1]["registry_record"]["manufacturer_serial_number"],
            self.AMS_2_SERIAL,
        )
        self.assertTrue(
            result["units"][1]["registry_record"]["manufacturer_serial_number"].endswith(
                "00 EWR"
            )
        )
        self.assertEqual(
            [unit["registry_record"]["display_name"] for unit in result["units"]],
            [
                "Bambu Lab AMS 2 Pro - AMS 1",
                "Bambu Lab AMS 2 Pro - AMS 2",
            ],
        )

    def test_03_all_eight_slots_and_live_assignments_are_adopted_not_rewritten(self):
        db = connect(self.database)
        try:
            spool_id = db.execute(
                "SELECT id FROM inventory_instances WHERE state='sealed' ORDER BY id LIMIT 1"
            ).fetchone()[0]
            slot_id = db.execute(
                "SELECT id FROM equipment_slots ORDER BY id LIMIT 1"
            ).fetchone()[0]
            actions = InventoryActionService(
                db, ActionContext("Fixture", "ams-preview-test", "system")
            )
            actions.open_sealed_spool(spool_id, reason="Temporary preview fixture")
            actions.load_instance_into_ams(
                spool_id, slot_id, reason="Temporary preview fixture"
            )
            db.commit()
            assignment_before = dict(
                db.execute(
                    """
                    SELECT id,instance_id,slot_id,loaded_at,unloaded_at
                    FROM ams_assignments WHERE unloaded_at IS NULL
                    """
                ).fetchone()
            )
        finally:
            db.close()
        result = self.build()
        slots = [
            slot
            for unit in result["units"]
            for slot in unit["existing_slots_unchanged"]
        ]
        self.assertEqual(len(slots), 8)
        self.assertEqual(
            [slot["slot_number"] for slot in slots[:4]], [1, 2, 3, 4]
        )
        self.assertEqual(
            [slot["slot_number"] for slot in slots[4:]], [1, 2, 3, 4]
        )
        adopted = next(slot for slot in slots if slot["assignment_id"])
        self.assertEqual(adopted["assignment_id"], assignment_before["id"])
        self.assertEqual(adopted["instance_id"], assignment_before["instance_id"])
        self.assertEqual(result["expected_row_changes"]["slot_rows_created"], 0)
        self.assertEqual(result["expected_row_changes"]["slot_rows_changed"], 0)
        self.assertEqual(result["expected_row_changes"]["assignment_rows_changed"], 0)

    def test_04_duplicate_reported_or_registered_serial_is_rejected(self):
        with self.assertRaisesRegex(AMSOnboardingPreviewError, "serials are duplicates"):
            self.build(ams_2_serial=self.AMS_1_SERIAL.lower())
        db = connect(self.database)
        db.execute(
            """
            UPDATE equipment_registry SET manufacturer_serial_number=?
            WHERE equipment_number='THS-EQP-000001'
            """,
            (self.AMS_1_SERIAL,),
        )
        db.commit()
        db.close()
        with self.assertRaisesRegex(AMSOnboardingPreviewError, "already registered"):
            self.build()

    def test_05_missing_or_misnumbered_legacy_slot_is_rejected(self):
        db = connect(self.database)
        db.execute("DELETE FROM equipment_slots WHERE id=(SELECT MAX(id) FROM equipment_slots)")
        db.commit()
        db.close()
        with self.assertRaisesRegex(AMSOnboardingPreviewError, "unique slots 1 through 4"):
            self.build()

    def test_06_duplicate_legacy_container_link_is_rejected(self):
        db = connect(self.database)
        p1s_id = db.execute(
            "SELECT id FROM equipment_registry WHERE equipment_number='THS-EQP-000001'"
        ).fetchone()[0]
        ams_1_id = db.execute(
            "SELECT id FROM equipment WHERE name='AMS 1'"
        ).fetchone()[0]
        db.execute(
            """
            INSERT INTO equipment_legacy_container_links(
              equipment_id,legacy_equipment_id,linked_by
            ) VALUES (?,?,?)
            """,
            (p1s_id, ams_1_id, "Fixture"),
        )
        db.commit()
        db.close()
        with self.assertRaisesRegex(AMSOnboardingPreviewError, "already linked"):
            self.build()

    def test_07_operational_readiness_restriction_and_provenance_stay_separate(self):
        result = self.build()
        for unit in result["units"]:
            registry = unit["registry_record"]
            self.assertEqual(registry["operational_status"], "unknown")
            self.assertEqual(registry["lifecycle_state"], "installed")
            self.assertIsNone(registry["current_location_id"])
        self.assertIn("readiness remains null", result["design_notes"]["readiness"])
        self.assertIn("No purchase or receiving link", result["design_notes"]["provenance"])


if __name__ == "__main__":
    unittest.main()
