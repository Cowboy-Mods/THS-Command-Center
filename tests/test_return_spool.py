import tempfile
import unittest
from pathlib import Path

from inventory.actions import ActionContext, InventoryActionService
from inventory.db import connect, migrate
from inventory.returning import ReturnSpoolError
from inventory.web import InventoryWebApp


class ReturnSpoolToStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        self.spool = db.execute(
            """SELECT ii.id FROM inventory_instances ii
            JOIN catalog_items ci ON ci.id=ii.catalog_item_id
            JOIN manufacturers m ON m.id=ci.manufacturer_id
            WHERE m.name='Bambu Lab' AND ci.variant='Jade White'"""
        ).fetchone()[0]
        self.slot = db.execute(
            """SELECT es.id FROM equipment_slots es JOIN equipment e
            ON e.id=es.equipment_id WHERE e.name='AMS 1' AND es.slot_number=1"""
        ).fetchone()[0]
        self.wall = db.execute(
            "SELECT id FROM locations WHERE name='Open-Spool Wall'"
        ).fetchone()[0]
        service = InventoryActionService(
            db, ActionContext(actor="Fixture", module="test", origin="system")
        )
        service.open_sealed_spool(self.spool, reason="Fixture")
        service.load_instance_into_ams(self.spool, self.slot, reason="Fixture")
        db.commit()
        db.close()
        self.app = InventoryWebApp(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def form(self, **changes):
        values = {
            "instance_id": str(self.spool),
            "destination_location_id": str(self.wall),
            "actor": "Cowboy",
            "reason": "Verified physical return from AMS to storage",
            "physically_verified": "yes",
        }
        values.update(changes)
        return values

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
            self.scalar("SELECT COUNT(*) FROM inventory_actions"),
            self.scalar("SELECT COUNT(*) FROM inventory_transactions"),
            self.scalar("SELECT COUNT(*) FROM transaction_lines"),
            self.scalar("SELECT COUNT(*) FROM ams_assignments"),
        )

    def test_01_options_show_loaded_spools_and_non_ams_storage(self):
        options = self.app.returning.options()
        self.assertEqual([row["id"] for row in options["spools"]], [self.spool])
        self.assertEqual(options["locations"][0]["name"], "Open-Spool Wall")
        slot_locations = {
            row[0] for row in self._rows("SELECT location_id FROM equipment_slots")
        }
        self.assertTrue(
            all(row["id"] not in slot_locations for row in options["locations"])
        )

    def test_02_preview_performs_zero_writes_and_shows_exact_move(self):
        before = self.counts()
        status, _, body = self.app.response(
            "/inventory/filament/ams/return/review",
            method="POST", form=self.form(),
        )
        page = body.decode()
        self.assertEqual(status, 200)
        for expected in (
            "Preview only — zero writes", "Jade White", "AMS 1 Slot 1",
            "Open-Spool Wall", "State becomes Open", "Remaining weight stays 1,000 g",
        ):
            self.assertIn(expected, page)
        self.assertEqual(before, self.counts())

    def test_03_commit_unloads_moves_and_preserves_weight_atomically(self):
        before = self.row(
            "SELECT original_quantity,remaining_quantity FROM inventory_instances WHERE id=?",
            (self.spool,),
        )
        result = self.app.returning.commit(
            self.app.returning.review(self.form()).token
        )
        after = self.row(
            """SELECT state,location_id,original_quantity,remaining_quantity
            FROM inventory_instances WHERE id=?""", (self.spool,),
        )
        self.assertEqual(after["state"], "open")
        self.assertEqual(after["location_id"], self.wall)
        self.assertEqual(
            (after["original_quantity"], after["remaining_quantity"]),
            (before["original_quantity"], before["remaining_quantity"]),
        )
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM ams_assignments WHERE instance_id=? AND unloaded_at IS NULL",
            (self.spool,),
        ), 0)
        action = self.row(
            "SELECT * FROM inventory_actions WHERE id=?", (result["action_id"],)
        )
        self.assertEqual(action["action_type"], "unload_instance_from_ams")
        self.assertEqual(action["module"], "return-spool-to-storage-ui")
        self.assertEqual(action["request_nonce"], result["request_nonce"])
        self.assertEqual(self.scalar(
            "SELECT transaction_type FROM inventory_transactions WHERE id=?",
            (result["transaction_id"],),
        ), "unload")

    def test_04_physical_and_final_confirmation_are_required(self):
        status, _, _ = self.app.response(
            "/inventory/filament/ams/return/review",
            method="POST", form=self.form(physically_verified=""),
        )
        self.assertEqual(status, 422)
        review = self.app.returning.review(self.form())
        status, _, _ = self.app.response(
            "/inventory/filament/ams/return/confirm",
            method="POST", form={"review_token": review.token},
        )
        self.assertEqual(status, 422)
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM inventory_actions WHERE module=?",
                        ("return-spool-to-storage-ui",)), 0,
        )

    def test_05_tampered_expired_and_replayed_previews_are_rejected(self):
        review = self.app.returning.review(self.form())
        tampered = review.token[:-1] + ("A" if review.token[-1] != "A" else "B")
        with self.assertRaisesRegex(ReturnSpoolError, "preview is invalid"):
            self.app.returning.commit(tampered)
        expired = dict(review.values)
        expired["reviewed_at"] = 1
        with self.assertRaisesRegex(ReturnSpoolError, "expired"):
            self.app.returning.commit(self.app.returning._sign(expired))
        self.app.returning.commit(review.token)
        with self.assertRaisesRegex(ReturnSpoolError, "already used"):
            self.app.returning.commit(review.token)

    def test_06_stale_spool_preview_is_rejected(self):
        review = self.app.returning.review(self.form())
        db = connect(self.database)
        db.execute(
            "UPDATE inventory_instances SET remaining_quantity=900 WHERE id=?",
            (self.spool,),
        )
        db.commit()
        db.close()
        with self.assertRaisesRegex(ReturnSpoolError, "changed after preview"):
            self.app.returning.commit(review.token)

    def test_07_ams_slot_is_not_a_valid_storage_destination(self):
        slot_location = self.scalar(
            "SELECT location_id FROM equipment_slots WHERE id=?", (self.slot,)
        )
        with self.assertRaisesRegex(ReturnSpoolError, "active storage location"):
            self.app.returning.review(
                self.form(destination_location_id=str(slot_location))
            )

    def test_08_audit_failure_rolls_back_unload_move_and_transaction(self):
        review = self.app.returning.review(self.form())
        before = self.counts()
        db = connect(self.database)
        db.execute(
            """CREATE TRIGGER fail_return_audit BEFORE INSERT ON inventory_actions
            WHEN NEW.module='return-spool-to-storage-ui'
            BEGIN SELECT RAISE(ABORT,'simulated return failure'); END"""
        )
        db.commit()
        db.close()
        with self.assertRaisesRegex(ReturnSpoolError, "simulated return failure"):
            self.app.returning.commit(review.token)
        self.assertEqual(before, self.counts())
        self.assertEqual(
            self.scalar("SELECT state FROM inventory_instances WHERE id=?", (self.spool,)),
            "loaded",
        )
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM ams_assignments WHERE instance_id=? AND unloaded_at IS NULL",
            (self.spool,),
        ), 1)

    def test_09_dashboard_menu_and_success_page_expose_workflow(self):
        dashboard = self.app.response("/")[2].decode()
        self.assertIn("Return AMS Spool to Storage", dashboard)
        self.assertIn("/inventory/filament/ams/return", dashboard)
        result = self.app.returning.commit(
            self.app.returning.review(self.form()).token
        )
        page = self.app._return_spool_complete(result)
        for expected in (
            "Verified return completed", "Open-Spool Wall",
            "Weight changed", "No", "View AMS Units",
        ):
            self.assertIn(expected, page)

    def test_10_form_and_preview_use_responsive_existing_contract(self):
        form = self.app.response("/inventory/filament/ams/return")[2].decode()
        preview = self.app.response(
            "/inventory/filament/ams/return/review",
            method="POST", form=self.form(),
        )[2].decode()
        self.assertIn("receive-form", form)
        self.assertIn("return-preview", preview)
        css = self.app.response("/static/style.css")[2].decode()
        self.assertIn("@media (max-width: 58rem)", css)
        self.assertIn("@media (max-width: 42rem)", css)

    def _rows(self, sql, params=()):
        db = connect(self.database)
        try:
            return db.execute(sql, params).fetchall()
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
