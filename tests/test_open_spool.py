import sqlite3
import tempfile
import unittest
from pathlib import Path

from inventory.db import connect, migrate
from inventory.open_spool import (
    RegisterExistingOpenSpoolWorkflow,
    RegisterOpenSpoolError,
)
from inventory.receiving import ReceiveSpoolWorkflow
from inventory.web import InventoryWebApp


class RegisterExistingOpenSpoolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        self.red = db.execute(
            """SELECT ci.id FROM catalog_items ci JOIN manufacturers m ON m.id=ci.manufacturer_id
            WHERE m.name='Bambu Lab' AND ci.product_line='PLA Basic' AND ci.variant='Orange'"""
        ).fetchone()[0]
        self.storage = db.execute(
            "SELECT id FROM locations WHERE kind='storage' ORDER BY id LIMIT 1"
        ).fetchone()[0]
        self.slot = db.execute(
            """SELECT es.id FROM equipment_slots es JOIN equipment e ON e.id=es.equipment_id
            WHERE e.name='AMS 1' AND es.slot_number=3"""
        ).fetchone()[0]
        db.close()
        self.workflow = RegisterExistingOpenSpoolWorkflow(
            self.database, secret=b"open-spool-test-secret"
        )

    def tearDown(self):
        self.temp.cleanup()

    def form(self, **changes):
        values = {
            "catalog_item_id": str(self.red),
            "product_mode": "existing",
            "quantity_mode": "exact",
            "remaining_quantity": "643",
            "quantity_confidence": "weighed",
            "note": "",
            "initial_location": f"storage:{self.storage}",
            "actor": "Cowboy",
            "physical_spool_confirmed": "yes",
        }
        values.update(changes)
        return values

    def scalar(self, sql, values=()):
        db = connect(self.database)
        try:
            return db.execute(sql, values).fetchone()[0]
        finally:
            db.close()

    def test_01_preview_is_zero_write_and_shows_permanent_identity(self):
        before = (
            self.scalar("SELECT COUNT(*) FROM inventory_instances"),
            self.scalar("SELECT COUNT(*) FROM inventory_actions"),
            self.scalar("SELECT COUNT(*) FROM open_spool_registrations"),
        )
        review = self.workflow.review(self.form())
        self.assertRegex(review.values["permanent_id"], r"^THS-FIL-\d{6}$")
        self.assertEqual(review.values["condition"], "open")
        self.assertEqual(review.values["source"], "pre_existing_inventory")
        self.assertEqual(
            before,
            (
                self.scalar("SELECT COUNT(*) FROM inventory_instances"),
                self.scalar("SELECT COUNT(*) FROM inventory_actions"),
                self.scalar("SELECT COUNT(*) FROM open_spool_registrations"),
            ),
        )

    def test_02_exact_grams_require_weighed_and_commit_one_open_spool(self):
        with self.assertRaisesRegex(RegisterOpenSpoolError, "require weighed"):
            self.workflow.review(self.form(quantity_confidence="visual_estimate"))
        result = self.workflow.commit(self.workflow.review(self.form()).token)
        self.assertEqual(
            self.scalar("SELECT remaining_quantity FROM inventory_instances WHERE id=?",
                        (result["instance_id"],)), 643
        )
        self.assertEqual(
            self.scalar("SELECT quantity_mode FROM open_spool_registrations"), "exact"
        )
        self.assertEqual(
            self.scalar("SELECT quantity_confidence FROM open_spool_registrations"), "weighed"
        )

    def test_03_estimated_grams_require_note_and_explicit_confidence(self):
        form = self.form(
            quantity_mode="estimated", remaining_quantity="275",
            quantity_confidence="visual_estimate", note="Looks roughly one quarter full.",
        )
        result = self.workflow.commit(self.workflow.review(form).token)
        self.assertEqual(
            self.scalar("SELECT remaining_quantity FROM open_spool_registrations"), 275
        )
        self.assertEqual(
            self.scalar("SELECT quantity_confidence FROM open_spool_registrations"),
            "visual_estimate",
        )
        with self.assertRaisesRegex(RegisterOpenSpoolError, "requires a note"):
            self.workflow.review({**form, "note": ""})

    def test_04_unknown_never_defaults_to_1000_and_can_start_in_ams(self):
        form = self.form(
            product_mode="new", catalog_item_id="", manufacturer="Bambu Lab",
            material="PLA Basic", color="Black", quantity_mode="unknown",
            remaining_quantity="", quantity_confidence="unknown",
            note="Visually low; no trustworthy gram measurement available.",
            initial_location=f"ams:{self.slot}",
        )
        result = self.workflow.commit(self.workflow.review(form).token)
        self.assertIsNone(
            self.scalar("SELECT remaining_quantity FROM open_spool_registrations")
        )
        self.assertEqual(
            self.scalar("SELECT remaining_quantity FROM inventory_instances WHERE id=?",
                        (result["instance_id"],)), 0
        )
        self.assertEqual(
            self.scalar("SELECT state FROM inventory_instances WHERE id=?",
                        (result["instance_id"],)), "loaded"
        )
        self.assertEqual(
            self.scalar("SELECT slot_id FROM ams_assignments WHERE instance_id=?",
                        (result["instance_id"],)), self.slot
        )
        self.assertTrue(result["product_created"])

    def test_05_unknown_requires_note_and_unknown_confidence(self):
        with self.assertRaisesRegex(RegisterOpenSpoolError, "requires a note"):
            self.workflow.review(self.form(
                quantity_mode="unknown", remaining_quantity="",
                quantity_confidence="unknown", note="",
            ))
        with self.assertRaisesRegex(RegisterOpenSpoolError, "requires unknown confidence"):
            self.workflow.review(self.form(
                quantity_mode="unknown", remaining_quantity="",
                quantity_confidence="visual_estimate", note="Quantity unknown.",
            ))

    def test_06_duplicate_warning_requires_ack_but_allows_distinct_same_product(self):
        self.workflow.commit(self.workflow.review(self.form()).token)
        second = self.form(
            remaining_quantity="501", note="Different physical spool confirmed."
        )
        with self.assertRaisesRegex(RegisterOpenSpoolError, "similar open or loaded spool"):
            self.workflow.review(second)
        second["duplicate_warning_ack"] = "yes"
        result = self.workflow.commit(self.workflow.review(second).token)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM inventory_instances WHERE catalog_item_id=? "
            "AND state='open'", (self.red,)
        ), 2)
        self.assertEqual(result["duplicate_warning_count"], 1)

    def test_07_physical_spool_confirmation_is_required(self):
        with self.assertRaisesRegex(RegisterOpenSpoolError, "one physical spool"):
            self.workflow.review(self.form(physical_spool_confirmed=""))

    def test_08_replay_is_rejected(self):
        review = self.workflow.review(self.form())
        self.workflow.commit(review.token)
        with self.assertRaisesRegex(RegisterOpenSpoolError, "already used"):
            self.workflow.commit(review.token)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM open_spool_registrations"), 1)

    def test_09_failure_rolls_back_instance_actions_assignment_and_registration(self):
        db = connect(self.database)
        db.execute(
            """CREATE TRIGGER fail_open_registration BEFORE INSERT ON open_spool_registrations
            BEGIN SELECT RAISE(ABORT,'simulated registration failure'); END"""
        )
        db.commit()
        db.close()
        before = (
            self.scalar("SELECT COUNT(*) FROM inventory_instances"),
            self.scalar("SELECT COUNT(*) FROM inventory_actions"),
        )
        form = self.form(initial_location=f"ams:{self.slot}")
        with self.assertRaisesRegex(RegisterOpenSpoolError, "simulated registration failure"):
            self.workflow.commit(self.workflow.review(form).token)
        self.assertEqual(before, (
            self.scalar("SELECT COUNT(*) FROM inventory_instances"),
            self.scalar("SELECT COUNT(*) FROM inventory_actions"),
        ))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM ams_assignments"), 0)

    def test_10_registration_history_is_database_immutable(self):
        self.workflow.commit(self.workflow.review(self.form()).token)
        db = connect(self.database)
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE open_spool_registrations SET note='changed'")
        db.rollback()
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("DELETE FROM open_spool_registrations")
        db.close()

    def test_11_existing_sealed_receiving_contract_is_unchanged(self):
        receiving = ReceiveSpoolWorkflow(self.database, secret=b"sealed-secret")
        page = InventoryWebApp(self.database).response("/inventory/filament/receive")[2].decode()
        self.assertIn("Receive Verified Sealed Spool", page)
        self.assertIn("Status: Sealed", page)
        self.assertNotIn("Pre-existing inventory", page)
        self.assertTrue(receiving.options()["products"])

    def test_12_dashboard_navigation_and_form_expose_controlled_workflow(self):
        app = InventoryWebApp(self.database)
        dashboard = app.response("/")[2].decode()
        form = app.response("/inventory/filament/register-open")[2].decode()
        self.assertIn('href="/inventory/filament/register-open"', dashboard)
        self.assertIn("Register Existing Open Spool", dashboard)
        for text in (
            "Manufacturer", "Material / type", "Color", "Condition: Open",
            "Pre-existing inventory", "Exact grams", "Estimated grams",
            "Unknown", "Weighed", "Manufacturer estimate", "Visual estimate",
            "Select storage or an empty AMS slot",
        ):
            self.assertIn(text, form)

    def test_13_web_preview_is_zero_write_and_confirmation_commits(self):
        app = InventoryWebApp(self.database)
        before = self.scalar("SELECT COUNT(*) FROM inventory_instances")
        status, _, preview = app.response(
            "/inventory/filament/register-open/review",
            method="POST", form=self.form(),
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_instances"), before)
        page = preview.decode()
        self.assertIn("Review Open Spool Registration", page)
        token = page.split('name="review_token" value="', 1)[1].split('"', 1)[0]
        status, _, complete = app.response(
            "/inventory/filament/register-open/confirm",
            method="POST", form={
                "review_token": token, "confirm": "register-open-spool"
            },
        )
        self.assertEqual(status, 201)
        self.assertIn("THS-FIL-", complete.decode())

    def test_14_unknown_quantity_displays_as_unknown_not_zero_or_1000(self):
        form = self.form(
            product_mode="new", catalog_item_id="", manufacturer="Bambu Lab",
            material="PLA Basic", color="Black", quantity_mode="unknown",
            remaining_quantity="", quantity_confidence="unknown",
            note="Visually low; grams unknown.", initial_location=f"ams:{self.slot}",
        )
        result = self.workflow.commit(self.workflow.review(form).token)
        app = InventoryWebApp(self.database)
        detail = app.response(
            f'/inventory/filament/spools/{result["instance_id"]}'
        )[2].decode()
        ams = app.response("/inventory/filament/ams")[2].decode()
        self.assertIn("<dd>Unknown</dd>", detail)
        self.assertIn("Unknown remaining", ams)
        self.assertNotIn("<dd>1,000 g</dd>", detail)


if __name__ == "__main__":
    unittest.main()
