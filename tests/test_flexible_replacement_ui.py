import tempfile
import unittest
from pathlib import Path

from inventory.actions import ActionContext, InventoryActionService
from inventory.db import connect, migrate
from inventory.web import InventoryWebApp


class FlexibleReplacementUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        self.slots = [
            row[0] for row in db.execute(
                """SELECT es.id FROM equipment_slots es
                JOIN equipment e ON e.id=es.equipment_id
                WHERE e.name='AMS 1' ORDER BY es.slot_number"""
            )
        ]
        self.wall = db.execute(
            "SELECT id FROM locations WHERE name='Open-Spool Wall'"
        ).fetchone()[0]
        self.spools = [
            row[0] for row in db.execute(
                """SELECT ii.id FROM inventory_instances ii
                JOIN catalog_items ci ON ci.id=ii.catalog_item_id
                JOIN item_types it ON it.id=ci.item_type_id
                WHERE it.name='Filament' AND ii.state='sealed'
                ORDER BY ii.id LIMIT 8"""
            )
        ]
        self.current = self.spools[0]
        service = InventoryActionService(
            db, ActionContext(actor="UI fixture", module="test", origin="system")
        )
        service.open_sealed_spool(self.current, reason="Fixture")
        service.load_instance_into_ams(self.current, self.slots[0], reason="Fixture")
        db.commit()
        db.close()
        self.app = InventoryWebApp(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def scalar(self, sql, params=()):
        db = connect(self.database)
        try:
            return db.execute(sql, params).fetchone()[0]
        finally:
            db.close()

    def row(self, sql, params=()):
        db = connect(self.database)
        try:
            found = db.execute(sql, params).fetchone()
            return dict(found) if found else None
        finally:
            db.close()

    def counts(self):
        return (
            self.scalar("SELECT COUNT(*) FROM inventory_workflow_transactions"),
            self.scalar("SELECT COUNT(*) FROM inventory_actions"),
            self.scalar("SELECT COUNT(*) FROM inventory_transactions"),
            self.scalar("SELECT COUNT(*) FROM ams_assignments"),
        )

    def location(self, instance_id):
        return self.scalar(
            "SELECT location_id FROM inventory_instances WHERE id=?", (instance_id,)
        )

    def form(self, **changes):
        values = {
            "current_instance_id": str(self.current),
            "outgoing_disposition": "storage",
            "outgoing_destination_location_id": str(self.wall),
            "outgoing_destination_slot_id": "",
            "incoming_disposition": "none",
            "incoming_instance_id": "",
            "incoming_source_location_id": "",
            "incoming_source_slot_id": "",
            "incoming_destination_slot_id": "",
            "actor": "Cowboy",
            "reason": "Guided UI test",
        }
        values.update(changes)
        return values

    def load(self, instance_id, slot_id):
        db = connect(self.database)
        service = InventoryActionService(
            db, ActionContext(actor="UI fixture", module="test", origin="system")
        )
        state = db.execute(
            "SELECT state FROM inventory_instances WHERE id=?", (instance_id,)
        ).fetchone()[0]
        if state == "sealed":
            service.open_sealed_spool(instance_id, reason="Fixture")
        service.load_instance_into_ams(instance_id, slot_id, reason="Fixture")
        db.commit()
        db.close()

    def open(self, instance_id):
        db = connect(self.database)
        InventoryActionService(
            db, ActionContext(actor="UI fixture", module="test", origin="system")
        ).open_sealed_spool(instance_id, reason="Fixture")
        db.commit()
        db.close()

    def test_01_form_exposes_all_guided_dispositions_sources_and_destinations(self):
        status, _, body = self.app.response("/inventory/filament/replace")
        page = body.decode()
        self.assertEqual(status, 200)
        for expected in (
            'name="outgoing_disposition"',
            "Empty — remove and mark Empty",
            "return Open to storage",
            "move Open to another AMS slot",
            'name="incoming_disposition"',
            "A sealed spool",
            "An already-open spool",
            "No replacement",
            'name="incoming_source_location_id"',
            'name="incoming_source_slot_id"',
            'name="incoming_destination_slot_id"',
            "Open-Spool Wall",
            "two-slot swap",
        ):
            self.assertIn(expected, page)

    def test_02_no_replacement_review_is_clear_and_zero_write(self):
        before = self.counts()
        status, _, body = self.app.response(
            "/inventory/filament/replace/review",
            method="POST",
            form=self.form(),
        )
        page = body.decode()
        self.assertEqual(status, 200)
        for expected in (
            "Final review — zero inventory writes",
            "No replacement",
            "Return Open to Open-Spool Wall",
            "All listed actions succeed together",
            "Perform this exact flexible spool operation",
        ):
            self.assertIn(expected, page)
        self.assertEqual(before, self.counts())

    def test_03_friendly_validation_error_has_no_partial_writes(self):
        before = self.counts()
        status, _, body = self.app.response(
            "/inventory/filament/replace/review",
            method="POST",
            form=self.form(outgoing_destination_location_id=""),
        )
        page = body.decode()
        self.assertEqual(status, 422)
        self.assertIn("storage disposition requires one storage location", page)
        self.assertIn("No changes saved", page)
        self.assertEqual(before, self.counts())

    def test_04_sealed_incoming_defaults_to_the_outgoing_source_slot(self):
        incoming = self.spools[1]
        review = self.app.replacement.review(
            self.form(
                outgoing_disposition="empty",
                outgoing_destination_location_id="",
                incoming_disposition="sealed",
                incoming_instance_id=str(incoming),
                incoming_source_location_id=str(self.location(incoming)),
            )
        )
        self.assertEqual(
            review.values["incoming_destination_slot_id"], self.slots[0]
        )
        status, _, body = self.app.response(
            "/inventory/filament/replace/confirm",
            method="POST",
            form={"review_token": review.token, "confirm": "replace"},
        )
        self.assertEqual(status, 201)
        self.assertIn("Flexible spool operation saved", body.decode())
        self.assertEqual(
            self.scalar("SELECT state FROM inventory_instances WHERE id=?", (incoming,)),
            "loaded",
        )

    def test_05_already_open_incoming_is_reviewed_and_loaded(self):
        incoming = self.spools[1]
        self.open(incoming)
        source = self.location(incoming)
        review = self.app.replacement.review(
            self.form(
                incoming_disposition="open",
                incoming_instance_id=str(incoming),
                incoming_source_location_id=str(source),
            )
        )
        page = self.app._replacement_review(review)
        self.assertIn("Open incoming spool", page)
        self.assertIn("Open-Spool Wall", page)
        result = self.app.replacement.commit(review.token)
        self.assertEqual(result["incoming_disposition"], "open")
        self.assertEqual(
            self.scalar("SELECT state FROM inventory_instances WHERE id=?", (incoming,)),
            "loaded",
        )

    def test_06_outgoing_spool_can_move_to_another_ams_slot(self):
        review = self.app.replacement.review(
            self.form(
                outgoing_disposition="ams_slot",
                outgoing_destination_location_id="",
                outgoing_destination_slot_id=str(self.slots[1]),
            )
        )
        self.assertIn("Move Open to AMS 1 Slot 2", self.app._replacement_review(review))
        self.app.replacement.commit(review.token)
        self.assertEqual(
            self.scalar(
                "SELECT slot_id FROM ams_assignments "
                "WHERE instance_id=? AND unloaded_at IS NULL",
                (self.current,),
            ),
            self.slots[1],
        )

    def test_07_two_slot_swap_succeeds_through_the_guided_ui(self):
        incoming = self.spools[1]
        self.load(incoming, self.slots[1])
        review = self.app.replacement.review(
            self.form(
                outgoing_disposition="ams_slot",
                outgoing_destination_location_id="",
                outgoing_destination_slot_id=str(self.slots[1]),
                incoming_disposition="open",
                incoming_instance_id=str(incoming),
                incoming_source_slot_id=str(self.slots[1]),
                incoming_destination_slot_id=str(self.slots[0]),
            )
        )
        status, _, _ = self.app.response(
            "/inventory/filament/replace/confirm",
            method="POST",
            form={"review_token": review.token, "confirm": "replace"},
        )
        self.assertEqual(status, 201)
        active = {
            row["instance_id"]: row["slot_id"]
            for row in self._rows(
                "SELECT instance_id,slot_id FROM ams_assignments "
                "WHERE unloaded_at IS NULL"
            )
        }
        self.assertEqual(active[self.current], self.slots[1])
        self.assertEqual(active[incoming], self.slots[0])

    def test_08_stale_review_is_rejected_without_partial_writes(self):
        review = self.app.replacement.review(self.form())
        before = self.counts()
        db = connect(self.database)
        db.execute(
            "UPDATE inventory_instances SET remaining_quantity=remaining_quantity-1 "
            "WHERE id=?",
            (self.current,),
        )
        db.commit()
        db.close()
        changed = self.counts()
        with self.assertRaisesRegex(Exception, "changed after preview"):
            self.app.replacement.commit(review.token)
        self.assertEqual(changed, self.counts())
        self.assertEqual(before[0], self.counts()[0])

    def test_09_tamper_replay_and_missing_confirmation_are_friendly(self):
        review = self.app.replacement.review(self.form())
        tampered = review.token[:-1] + ("A" if review.token[-1] != "A" else "B")
        status, _, body = self.app.response(
            "/inventory/filament/replace/confirm",
            method="POST",
            form={"review_token": tampered, "confirm": "replace"},
        )
        self.assertEqual(status, 422)
        self.assertIn("preview is invalid", body.decode())
        status, _, _ = self.app.response(
            "/inventory/filament/replace/confirm",
            method="POST",
            form={"review_token": review.token},
        )
        self.assertEqual(status, 422)
        self.app.replacement.commit(review.token)
        with self.assertRaisesRegex(Exception, "already used"):
            self.app.replacement.commit(review.token)

    def test_10_child_failure_returns_error_and_rolls_back_everything(self):
        incoming = self.spools[1]
        review = self.app.replacement.review(
            self.form(
                outgoing_disposition="empty",
                outgoing_destination_location_id="",
                incoming_disposition="sealed",
                incoming_instance_id=str(incoming),
                incoming_source_location_id=str(self.location(incoming)),
            )
        )
        before = self.counts()
        db = connect(self.database)
        db.execute(
            """CREATE TRIGGER fail_guided_ui_load
            BEFORE INSERT ON inventory_actions
            WHEN NEW.action_type='load_instance_into_ams'
            BEGIN SELECT RAISE(ABORT,'simulated guided UI failure'); END"""
        )
        db.commit()
        db.close()
        status, _, body = self.app.response(
            "/inventory/filament/replace/confirm",
            method="POST",
            form={"review_token": review.token, "confirm": "replace"},
        )
        self.assertEqual(status, 422)
        self.assertIn("simulated guided UI failure", body.decode())
        self.assertEqual(before, self.counts())
        self.assertEqual(
            self.scalar("SELECT state FROM inventory_instances WHERE id=?", (self.current,)),
            "loaded",
        )

    def test_11_legacy_form_review_and_completion_remain_compatible(self):
        incoming = self.spools[1]
        legacy = {
            "current_instance_id": str(self.current),
            "replacement_instance_id": str(incoming),
            "destination_slot_id": "",
            "confirm_empty": "yes",
            "actor": "Cowboy",
            "reason": "Legacy UI compatibility",
        }
        review = self.app.replacement.review(legacy)
        self.assertEqual(review.values["version"], 1)
        page = self.app._replacement_review(review)
        self.assertIn("Open sealed replacement", page)
        result = self.app.replacement.commit(review.token)
        self.assertIn("Mark Empty action", self.app._replacement_complete(result))
        parent = self.row(
            "SELECT * FROM inventory_workflow_transactions WHERE id=?",
            (result["workflow_transaction_id"],),
        )
        self.assertEqual(parent["replacement_instance_id"], incoming)
        self.assertIsNone(parent["incoming_disposition"])

    def test_12_schema_18_database_shows_safe_migration_gate(self):
        db = connect(self.database)
        db.execute(
            "DELETE FROM schema_migrations "
            "WHERE name='019_flexible_spool_replacement.sql'"
        )
        db.commit()
        db.close()
        status, _, body = self.app.response("/inventory/filament/replace")
        page = body.decode()
        self.assertEqual(status, 200)
        self.assertIn("Flexible replacement is not enabled yet", page)
        self.assertIn("Migration 019", page)
        self.assertNotIn('name="outgoing_disposition"', page)

    def _rows(self, sql, params=()):
        db = connect(self.database)
        try:
            return db.execute(sql, params).fetchall()
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
