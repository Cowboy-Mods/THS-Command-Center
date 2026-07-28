import tempfile
import unittest
from pathlib import Path

from inventory.actions import ActionContext, InventoryActionService
from inventory.correction_preview import (
    CorrectionPreviewError,
    build_spool_correction_preview,
)
from inventory.db import connect, migrate


class CorrectionPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        self.db = connect(self.database)
        migrate(self.db)
        self.service = InventoryActionService(
            self.db,
            ActionContext(actor="Cowboy", module="correction-preview-test", origin="user"),
        )
        self.wall = self.db.execute(
            "SELECT id FROM locations WHERE name='Open-Spool Wall'"
        ).fetchone()[0]
        self.slots = [
            row[0] for row in self.db.execute(
                """
                SELECT es.id FROM equipment_slots es
                JOIN equipment e ON e.id=es.equipment_id
                WHERE e.name='AMS 1' ORDER BY es.slot_number
                """
            )
        ]
        self.spools = [
            row for row in self.db.execute(
                """
                SELECT ii.id,ii.permanent_id FROM inventory_instances ii
                JOIN catalog_items ci ON ci.id=ii.catalog_item_id
                JOIN item_types it ON it.id=ci.item_type_id
                WHERE it.name='Filament' AND ii.state='sealed'
                ORDER BY ii.id LIMIT 2
                """
            )
        ]
        for spool, slot in zip(self.spools, self.slots):
            self.service.open_sealed_spool(spool["id"], reason="Preview fixture")
            self.service.load_instance_into_ams(
                spool["id"], slot, reason="Preview fixture"
            )

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def counts(self):
        return {
            table: self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "inventory_instances",
                "ams_assignments",
                "inventory_transactions",
                "transaction_lines",
                "inventory_actions",
                "inventory_workflow_transactions",
            )
        }

    def preview(self):
        return build_spool_correction_preview(
            self.db,
            outgoing_permanent_id=self.spools[0]["permanent_id"],
            incoming_permanent_id=self.spools[1]["permanent_id"],
            outgoing_storage_location_name="Open-Spool Wall",
            incoming_destination_equipment="AMS 1",
            incoming_destination_slot_number=1,
        )

    def test_preview_is_zero_write_and_lists_exact_atomic_row_changes(self):
        before_counts = self.counts()
        before_changes = self.db.total_changes
        plan = self.preview()

        self.assertEqual(before_counts, self.counts())
        self.assertEqual(before_changes, self.db.total_changes)
        self.assertEqual(plan["mode"], "zero_write_correction_preview")
        self.assertEqual(plan["proposed"]["outgoing_disposition"], "storage")
        self.assertEqual(plan["proposed"]["incoming_disposition"], "open")
        self.assertTrue(plan["proposed"]["leave_incoming_source_slot_empty"])
        self.assertEqual(
            [change["operation"] for change in plan["row_changes"]],
            [
                "INSERT", "UPDATE", "UPDATE", "UPDATE", "UPDATE",
                "UPDATE", "INSERT", "INSERT", "INSERT", "INSERT",
            ],
        )
        self.assertEqual(
            plan["row_changes"][0]["fields"]["incoming_source_slot_id"],
            self.slots[1],
        )
        self.assertEqual(
            plan["row_changes"][0]["fields"]["incoming_destination_slot_id"],
            self.slots[0],
        )
        self.assertEqual(
            [action["action_type"] for action in plan["expected_audit_actions"]],
            [
                "unload_instance_from_ams",
                "unload_instance_from_ams",
                "load_instance_into_ams",
            ],
        )

    def test_preview_preserves_ids_quantities_and_captures_history(self):
        plan = self.preview()
        current = plan["current"]
        self.assertEqual(
            current["outgoing"]["permanent_id"], self.spools[0]["permanent_id"]
        )
        self.assertEqual(
            current["incoming"]["permanent_id"], self.spools[1]["permanent_id"]
        )
        self.assertTrue(plan["proposed"]["preserve_permanent_ids"])
        self.assertTrue(plan["proposed"]["preserve_quantities"])
        self.assertEqual(len(plan["history"]["outgoing"]["actions"]), 2)
        self.assertEqual(len(plan["history"]["incoming"]["actions"]), 2)
        self.assertEqual(len(plan["history"]["outgoing"]["assignments"]), 1)
        self.assertEqual(len(plan["history"]["incoming"]["assignments"]), 1)

    def test_preview_rejects_stale_or_contradictory_preconditions_without_writes(self):
        before_counts = self.counts()
        self.db.execute(
            "UPDATE ams_assignments SET unloaded_at=CURRENT_TIMESTAMP "
            "WHERE instance_id=? AND unloaded_at IS NULL",
            (self.spools[1]["id"],),
        )
        self.db.commit()
        changed_counts = self.counts()

        with self.assertRaisesRegex(
            CorrectionPreviewError, "incoming spool is not actively assigned"
        ):
            self.preview()

        self.assertEqual(before_counts, changed_counts)
        self.assertEqual(changed_counts, self.counts())


if __name__ == "__main__":
    unittest.main()
