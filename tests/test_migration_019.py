import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from inventory import db as db_module
from inventory.actions import ActionContext, InventoryActionService


class FlexibleReplacementMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        self.pre019 = Path(self.temp.name) / "pre019"
        self.pre019.mkdir()
        for migration in sorted(db_module.MIGRATIONS.glob("*.sql")):
            if migration.name == "019_flexible_spool_replacement.sql":
                continue
            shutil.copy2(migration, self.pre019 / migration.name)

        original = db_module.MIGRATIONS
        db_module.MIGRATIONS = self.pre019
        try:
            db = db_module.connect(self.database)
            db_module.migrate(db)
            self._create_legacy_workflow(db)
            db.commit()
            self.before = dict(
                db.execute(
                    "SELECT * FROM inventory_workflow_transactions"
                ).fetchone()
            )
            self.before_action_link = db.execute(
                "SELECT workflow_transaction_id FROM inventory_actions "
                "WHERE workflow_transaction_id IS NOT NULL LIMIT 1"
            ).fetchone()[0]
            db.close()
        finally:
            db_module.MIGRATIONS = original

        self.db = db_module.connect(self.database)
        applied = db_module.migrate(self.db)
        self.assertEqual(applied, ["019_flexible_spool_replacement.sql"])

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    @staticmethod
    def _create_legacy_workflow(db):
        slot = db.execute(
            """SELECT es.id FROM equipment_slots es
            JOIN equipment e ON e.id=es.equipment_id
            WHERE e.name='AMS 1' AND es.slot_number=1"""
        ).fetchone()[0]
        spools = [
            row[0] for row in db.execute(
                """SELECT ii.id FROM inventory_instances ii
                JOIN catalog_items ci ON ci.id=ii.catalog_item_id
                JOIN manufacturers m ON m.id=ci.manufacturer_id
                WHERE m.name='Bambu Lab' AND ii.state='sealed'
                ORDER BY ii.id LIMIT 2"""
            )
        ]
        service = InventoryActionService(
            db,
            ActionContext(actor="Migration test", module="test", origin="system"),
        )
        service.open_sealed_spool(spools[0], reason="Fixture")
        service.load_instance_into_ams(spools[0], slot, reason="Fixture")
        service.replace_active_filament_spool(
            spools[0],
            spools[1],
            slot,
            reason="Legacy fixture",
            review_nonce="migration-019-legacy-fixture",
        )

    def _base_explicit(self):
        instance_ids = [
            row[0] for row in self.db.execute(
                "SELECT id FROM inventory_instances ORDER BY id LIMIT 3"
            )
        ]
        location_id = self.db.execute(
            "SELECT id FROM locations ORDER BY id LIMIT 1"
        ).fetchone()[0]
        slot_ids = [
            row[0] for row in self.db.execute(
                "SELECT id FROM equipment_slots ORDER BY id LIMIT 3"
            )
        ]
        return {
            "current": instance_ids[0],
            "incoming": instance_ids[1],
            "location": location_id,
            "source_slot": slot_ids[1],
            "destination_slot": slot_ids[2],
        }

    def _insert_explicit(self, suffix, **changes):
        values = self._base_explicit()
        values.update(
            outgoing_disposition="storage",
            outgoing_destination_location_id=values["location"],
            outgoing_destination_slot_id=None,
            incoming_disposition="open",
            incoming_source_location_id=values["location"],
            incoming_source_slot_id=None,
            incoming_instance_id=values["incoming"],
            incoming_destination_slot_id=values["destination_slot"],
        )
        values.update(changes)
        self.db.execute(
            """INSERT INTO inventory_workflow_transactions(
            workflow_uuid,review_nonce,workflow_type,actor,module,origin,
            current_instance_id,replacement_instance_id,destination_slot_id,
            outgoing_disposition,outgoing_destination_location_id,
            outgoing_destination_slot_id,incoming_disposition,
            incoming_source_location_id,incoming_source_slot_id,
            incoming_instance_id,incoming_destination_slot_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f"explicit-{suffix}",
                f"nonce-{suffix}",
                "replace_active_filament_spool",
                "Migration test",
                "test",
                "system",
                values["current"],
                None,
                None,
                values["outgoing_disposition"],
                values["outgoing_destination_location_id"],
                values["outgoing_destination_slot_id"],
                values["incoming_disposition"],
                values["incoming_source_location_id"],
                values["incoming_source_slot_id"],
                values["incoming_instance_id"],
                values["incoming_destination_slot_id"],
            ),
        )

    def test_01_legacy_row_and_action_link_are_preserved_exactly(self):
        after = dict(
            self.db.execute(
                """SELECT id,workflow_uuid,review_nonce,occurred_at,workflow_type,
                actor,module,origin,reason,current_instance_id,
                replacement_instance_id,destination_slot_id,print_job_name,
                approximate_layer,printer,plate,operational_note
                FROM inventory_workflow_transactions WHERE id=?""",
                (self.before["id"],),
            ).fetchone()
        )
        expected = {key: self.before[key] for key in after}
        self.assertEqual(after, expected)
        self.assertEqual(
            self.db.execute(
                "SELECT workflow_transaction_id FROM inventory_actions "
                "WHERE workflow_transaction_id IS NOT NULL LIMIT 1"
            ).fetchone()[0],
            self.before_action_link,
        )
        explicit = self.db.execute(
            """SELECT outgoing_disposition,incoming_disposition,
            incoming_instance_id,incoming_destination_slot_id
            FROM inventory_workflow_transactions WHERE id=?""",
            (self.before["id"],),
        ).fetchone()
        self.assertEqual(tuple(explicit), (None, None, None, None))

    def test_02_schema_has_nullable_explicit_columns_and_foreign_keys(self):
        columns = {
            row["name"]: row for row in self.db.execute(
                "PRAGMA table_info(inventory_workflow_transactions)"
            )
        }
        expected = {
            "outgoing_disposition",
            "outgoing_destination_location_id",
            "outgoing_destination_slot_id",
            "incoming_disposition",
            "incoming_source_location_id",
            "incoming_source_slot_id",
            "incoming_instance_id",
            "incoming_destination_slot_id",
        }
        self.assertTrue(expected.issubset(columns))
        self.assertEqual(columns["replacement_instance_id"]["notnull"], 0)
        self.assertEqual(columns["destination_slot_id"]["notnull"], 0)
        self.assertTrue(all(columns[name]["notnull"] == 0 for name in expected))
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_03_no_replacement_and_all_outgoing_dispositions_are_valid(self):
        location = self._base_explicit()["location"]
        slot = self._base_explicit()["destination_slot"]
        for suffix, disposition, destination_location, destination_slot in (
            ("empty-none", "empty", None, None),
            ("storage-none", "storage", location, None),
            ("slot-none", "ams_slot", None, slot),
        ):
            self._insert_explicit(
                suffix,
                outgoing_disposition=disposition,
                outgoing_destination_location_id=destination_location,
                outgoing_destination_slot_id=destination_slot,
                incoming_disposition="none",
                incoming_source_location_id=None,
                incoming_source_slot_id=None,
                incoming_instance_id=None,
                incoming_destination_slot_id=None,
            )

    def test_04_sealed_and_open_incoming_sources_are_valid(self):
        self._insert_explicit("sealed", incoming_disposition="sealed")
        self._insert_explicit(
            "open-from-slot",
            incoming_disposition="open",
            incoming_source_location_id=None,
            incoming_source_slot_id=self._base_explicit()["source_slot"],
        )

    def test_05_contradictory_combinations_are_rejected(self):
        invalid = (
            {
                "outgoing_disposition": "empty",
                "outgoing_destination_location_id": self._base_explicit()["location"],
            },
            {
                "outgoing_disposition": "storage",
                "outgoing_destination_location_id": None,
            },
            {
                "incoming_disposition": "none",
                "incoming_instance_id": self._base_explicit()["incoming"],
                "incoming_source_location_id": None,
                "incoming_destination_slot_id": None,
            },
            {
                "incoming_disposition": "open",
                "incoming_source_location_id": None,
                "incoming_source_slot_id": None,
            },
            {
                "outgoing_disposition": "ams_slot",
                "outgoing_destination_location_id": None,
                "outgoing_destination_slot_id": self._base_explicit()["destination_slot"],
                "incoming_destination_slot_id": self._base_explicit()["destination_slot"],
            },
        )
        for index, changes in enumerate(invalid):
            with self.assertRaises(sqlite3.IntegrityError):
                self._insert_explicit(f"invalid-{index}", **changes)

    def test_06_legacy_service_remains_backward_compatible(self):
        row = self.db.execute(
            "SELECT * FROM inventory_workflow_transactions WHERE id=?",
            (self.before["id"],),
        ).fetchone()
        self.assertIsNotNone(row["replacement_instance_id"])
        self.assertIsNotNone(row["destination_slot_id"])
        self.assertIsNone(row["outgoing_disposition"])
        self.assertIsNone(row["incoming_disposition"])

    def test_07_workflow_history_remains_immutable(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "UPDATE inventory_workflow_transactions SET reason='changed' "
                "WHERE id=?",
                (self.before["id"],),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "DELETE FROM inventory_workflow_transactions WHERE id=?",
                (self.before["id"],),
            )

    def test_08_integrity_and_active_assignment_uniqueness_hold(self):
        self.assertEqual(self.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        slot = self.db.execute(
            "SELECT slot_id FROM ams_assignments WHERE unloaded_at IS NULL LIMIT 1"
        ).fetchone()[0]
        instance = self.db.execute(
            "SELECT instance_id FROM ams_assignments WHERE unloaded_at IS NULL LIMIT 1"
        ).fetchone()[0]
        transaction = self.db.execute(
            "SELECT id FROM inventory_transactions LIMIT 1"
        ).fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                """INSERT INTO ams_assignments(
                slot_id,instance_id,load_transaction_id) VALUES (?,?,?)""",
                (slot, instance + 1, transaction),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                """INSERT INTO ams_assignments(
                slot_id,instance_id,load_transaction_id) VALUES (?,?,?)""",
                (slot + 1, instance, transaction),
            )


if __name__ == "__main__":
    unittest.main()
