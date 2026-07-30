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
    P1S_SERIAL = "01P00C511401400"
    AMS_1_SERIAL = "19C06A522002297"
    AMS_2_SERIAL = "19C51A620400EWR"

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
            "parent_serial": self.P1S_SERIAL,
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
        self.assertEqual(result["expected_row_changes"]["total_insert_rows"], 29)
        self.assertEqual(len(result["expected_row_changes"]["updates"]), 2)
        self.assertEqual(
            result["parent_serial_correction"]["manufacturer_serial_number_after"],
            self.P1S_SERIAL,
        )
        self.assertEqual(result["expected_row_changes"]["deletes"], [])
        self.assertFalse(result["production_ready"])

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
        self.assertNotIn(" ", result["units"][1]["registry_record"]["manufacturer_serial_number"])
        self.assertNotIn("-", result["units"][1]["registry_record"]["manufacturer_serial_number"])
        self.assertTrue(
            result["units"][1]["registry_record"]["manufacturer_serial_number"].endswith("EWR")
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
        self.assertEqual(slots[1]["bambu_designation"], "A2")
        self.assertEqual(
            slots[1]["confirmed_availability"], "empty_out_of_service_do_not_load"
        )
        self.assertEqual(slots[3]["confirmed_availability"], "usable_monitor")
        self.assertTrue(self.preview._slot_matches("cyan", "Blue"))
        self.assertTrue(self.preview._slot_matches("Jade White", "White"))
        self.assertFalse(self.preview._slot_matches("Orange", "Blue"))

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
        with self.assertRaisesRegex(AMSOnboardingPreviewError, "conflicts|already registered"):
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
        self.assertEqual(
            [unit["registry_record"]["operational_status"] for unit in result["units"]],
            ["degraded", "operating"],
        )
        for unit in result["units"]:
            self.assertEqual(unit["registry_record"]["lifecycle_state"], "installed")
            self.assertIsNone(unit["registry_record"]["current_location_id"])
            self.assertEqual(unit["existing_maintenance_asset"]["readiness_state"], "normal")
        self.assertTrue(result["units"][0]["maintenance_link_proposed"])
        self.assertFalse(result["units"][1]["maintenance_link_proposed"])
        issue = result["maintenance_representation"]
        self.assertEqual(
            issue["maintenance_record"]["event_type"], "fault_discovered"
        )
        self.assertEqual(issue["maintenance_record"]["status"], "in_progress")
        self.assertIn("Affected component: Slot 2 / A2", issue["maintenance_record"]["symptoms"])
        self.assertIn(
            "Restriction: Slot 2 / A2 is Out of service",
            issue["maintenance_record"]["notes"],
        )
        self.assertIn("Slot 4 / A4 remains in service", issue["maintenance_record"]["notes"])
        self.assertEqual(
            issue["maintenance_asset_update"]["readiness_state_after"],
            "monitor_during_printing",
        )
        self.assertTrue(issue["slot_2_assignment_precondition"]["must_be_empty"])
        self.assertFalse(issue["slot_2_assignment_precondition"]["create_assignment"])
        self.assertEqual(len(result["architecture_blockers"]), 2)
        self.assertIn("No purchase or receiving link", result["design_notes"]["provenance"])

    def test_08_slot_2_issue_does_not_create_slot_equipment_or_disable_whole_ams(self):
        result = self.build()
        unit = result["units"][0]
        self.assertEqual(unit["registry_record"]["equipment_number"], "THS-EQP-000002")
        self.assertEqual(unit["registry_record"]["operational_status"], "degraded")
        self.assertEqual(
            unit["maintenance_issue"]["maintenance_asset_update"]["readiness_state_after"],
            "monitor_during_printing",
        )
        self.assertNotEqual(
            unit["maintenance_issue"]["maintenance_asset_update"]["readiness_state_after"],
            "out_of_service",
        )
        self.assertEqual(result["expected_row_changes"]["slot_rows_created"], 0)
        self.assertEqual(
            sum(
                1
                for row in result["expected_row_changes"]["inserts"]
                if row["table"] == "equipment_registry"
            ),
            2,
        )

    def test_09_conflicting_parent_serial_is_rejected_without_writes(self):
        db = connect(self.database)
        db.execute(
            """
            UPDATE equipment_registry SET manufacturer_serial_number='DIFFERENT-P1S'
            WHERE equipment_number='THS-EQP-000001'
            """
        )
        db.commit()
        db.close()
        before = self.database.read_bytes()
        with self.assertRaisesRegex(AMSOnboardingPreviewError, "conflicts"):
            self.build()
        self.assertEqual(before, self.database.read_bytes())

    def test_10_verified_feeder_is_previewed_once_without_install_or_consumption(self):
        result = self.build()
        part = result["repair_part"]
        self.assertFalse(part["matching_part_found"])
        self.assertEqual(part["product_name"], "Bambu Lab AMS 2 Pro Feeder Unit")
        self.assertEqual(part["model"], "SA403-V1")
        self.assertEqual(part["upc"], "6937285503237")
        self.assertEqual(part["quantity"], 1)
        self.assertEqual(part["condition"], "New/boxed")
        self.assertEqual(part["proposed_instance"]["permanent_id"], "THS-PART-000001")
        self.assertIsNone(part["proposed_instance"]["location_id"])
        self.assertTrue(part["storage_confirmation_required"])
        self.assertFalse(part["proposed_instance"]["installed"])
        self.assertFalse(part["proposed_instance"]["reserved"])
        self.assertFalse(part["proposed_instance"]["issued"])
        self.assertFalse(part["proposed_instance"]["consumed"])
        self.assertIn(
            "THS-PART-000001",
            result["maintenance_representation"]["maintenance_record"]["parts_required"],
        )
        part_rows = [
            row
            for row in result["expected_row_changes"]["inserts"]
            if row["table"]
            in {
                "item_types",
                "catalog_items",
                "inventory_instances",
                "inventory_transactions",
                "transaction_lines",
            }
        ]
        self.assertEqual(len(part_rows), 5)

    def test_11_existing_exact_feeder_match_blocks_duplicate_part_creation(self):
        db = connect(self.database)
        try:
            category_id = db.execute(
                "SELECT id FROM categories WHERE name='3D Printing'"
            ).fetchone()[0]
            unit_id = db.execute(
                "SELECT id FROM units WHERE code='ea'"
            ).fetchone()[0]
            manufacturer_id = db.execute(
                "SELECT id FROM manufacturers WHERE name='Bambu Lab'"
            ).fetchone()[0]
            actions = InventoryActionService(
                db, ActionContext("Fixture", "ams-preview-test", "system")
            )
            item_type_id = actions.ensure_item_type(
                category_id,
                "Printer Part",
                "individual",
                unit_id,
                id_prefix="THS-PART",
            )
            catalog_id, _ = actions.ensure_catalog_item(
                item_type_id,
                manufacturer_id,
                "Bambu Lab AMS 2 Pro Feeder Unit",
                "AMS 2 Pro",
                "SA403-V1",
                unit_id,
                notes="UPC 6937285503237.",
            )
            instance_id = actions.add_individual_instance(
                catalog_id,
                state="sealed",
                location_id=None,
                original_quantity=1,
                remaining_quantity=1,
                unit_id=unit_id,
                permanent_id="THS-PART-000001",
                condition="new/boxed",
                notes="UPC 6937285503237.",
                verified=True,
            )
            db.commit()
        finally:
            db.close()
        result = self.build()
        self.assertTrue(result["repair_part"]["matching_part_found"])
        self.assertEqual(
            result["repair_part"]["catalog_or_inventory_matches"][0]["instance_id"],
            instance_id,
        )
        self.assertIsNone(result["repair_part"]["proposed_instance"])
        self.assertEqual(result["expected_row_changes"]["total_insert_rows"], 21)
        self.assertFalse(
            any(
                row["table"]
                in {
                    "item_types",
                    "catalog_items",
                    "inventory_instances",
                    "inventory_transactions",
                    "transaction_lines",
                }
                for row in result["expected_row_changes"]["inserts"]
            )
        )


if __name__ == "__main__":
    unittest.main()
