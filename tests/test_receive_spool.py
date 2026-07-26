import tempfile
import unittest
from pathlib import Path

from inventory.db import connect, migrate
from inventory.receiving import ReceiveSpoolError
from inventory.web import InventoryWebApp


class ReceiveVerifiedSealedSpoolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        db.close()
        self.app = InventoryWebApp(self.database)
        db = connect(self.database)
        self.orange = db.execute(
            "SELECT ci.id FROM catalog_items ci JOIN manufacturers m ON m.id=ci.manufacturer_id "
            "WHERE m.name='Bambu Lab' AND ci.product_line='PLA Basic' AND ci.variant='Orange'"
        ).fetchone()[0]
        self.rack = db.execute(
            "SELECT id FROM locations WHERE name='Sealed Filament Rack'"
        ).fetchone()[0]
        db.close()

    def tearDown(self):
        self.temp.cleanup()

    def scalar(self, sql, params=()):
        db = connect(self.database)
        try:
            return db.execute(sql, params).fetchone()[0]
        finally:
            db.close()

    def post(self, path, form):
        status, headers, body = self.app.response(path, method="POST", form=form)
        return status, dict(headers), body.decode()

    def existing_form(self, **changes):
        values = {
            "product_mode": "existing",
            "catalog_item_id": str(self.orange),
            "location_id": str(self.rack),
            "actor": "Cowboy",
            "reason": "Verified delivery",
        }
        values.update(changes)
        return values

    def new_form(self, **changes):
        values = {
            "product_mode": "new",
            "manufacturer": "Polymaker",
            "product_line": "PolyLite PLA",
            "material": "PLA",
            "color": "Army Beige",
            "diameter_mm": "1.75",
            "nominal_weight_g": "1000",
            "location_id": str(self.rack),
            "actor": "Cowboy",
            "reason": "Packaging verified",
        }
        values.update(changes)
        return values

    def test_01_receive_form_is_the_only_narrow_editable_inventory_workflow(self):
        status, _, body = self.app.response("/inventory/filament/receive")
        page = body.decode()
        self.assertEqual(status, 200)
        self.assertIn("Receive a Verified Sealed Spool", page)
        self.assertIn("cannot edit existing inventory", page)
        self.assertNotIn("quantity correction", page.lower())
        self.assertNotIn("AMS editing", page)

    def test_02_receive_form_lists_existing_products_and_storage_locations(self):
        _, _, body = self.app.response("/inventory/filament/receive")
        page = body.decode()
        self.assertIn("Bambu Lab â€” PLA Basic â€” Orange", page)
        self.assertIn("Sealed Filament Rack", page)
        self.assertNotIn(">AMS 1</option>", page)

    def test_03_review_displays_every_required_value_without_writing(self):
        before = self._counts()
        status, _, page = self.post(
            "/inventory/filament/receive/review", self.existing_form()
        )
        self.assertEqual(status, 200)
        for value in (
            "Bambu Lab", "PLA Basic", "PLA", "Orange", "1.75 mm", "1,000 g",
            "Sealed", "Sealed Filament Rack", "THS-FIL-000031", "Cowboy",
            "filament-receiving-ui", "Verified delivery",
        ):
            self.assertIn(value, page)
        self.assertIn("Nothing has been written yet", page)
        self.assertEqual(before, self._counts())

    def test_04_review_requires_complete_verified_input(self):
        for changes in (
            {"catalog_item_id": ""},
            {"location_id": ""},
            {"actor": ""},
            {"product_mode": "wrong"},
        ):
            status, _, page = self.post(
                "/inventory/filament/receive/review", self.existing_form(**changes)
            )
            self.assertEqual(status, 422)
            self.assertIn("Spool was not added", page)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_instances"), 30)

    def test_05_new_product_values_are_strictly_validated(self):
        for changes in (
            {"manufacturer": ""},
            {"diameter_mm": "0"},
            {"diameter_mm": "nan"},
            {"nominal_weight_g": "-1"},
            {"nominal_weight_g": "infinity"},
        ):
            status, _, _ = self.post(
                "/inventory/filament/receive/review", self.new_form(**changes)
            )
            self.assertEqual(status, 422)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM catalog_items"), 17)

    def test_06_review_requires_explicit_confirmation(self):
        review = self.app.receiving.review(self.existing_form())
        status, _, page = self.post(
            "/inventory/filament/receive/confirm",
            {"review_token": review.token},
        )
        self.assertEqual(status, 422)
        self.assertIn("explicit confirmation is required", page)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_instances"), 30)

    def test_07_tampered_review_is_rejected_without_writes(self):
        review = self.app.receiving.review(self.existing_form())
        token = review.token[:-1] + ("A" if review.token[-1] != "A" else "B")
        status, _, page = self.post(
            "/inventory/filament/receive/confirm",
            {"review_token": token, "confirm": "receive"},
        )
        self.assertEqual(status, 422)
        self.assertIn("review confirmation is invalid", page)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_instances"), 30)

    def test_08_confirm_existing_product_creates_one_verified_sealed_spool(self):
        review = self.app.receiving.review(self.existing_form())
        result = self.app.receiving.commit(review.token)
        row = self._row(
            "SELECT * FROM inventory_instances WHERE id=?", (result["instance_id"],)
        )
        self.assertEqual(row["permanent_id"], "THS-FIL-000031")
        self.assertEqual(row["catalog_item_id"], self.orange)
        self.assertEqual(row["state"], "sealed")
        self.assertEqual(row["condition"], "new")
        self.assertEqual(row["location_id"], self.rack)
        self.assertEqual(row["original_quantity"], 1000)
        self.assertEqual(row["remaining_quantity"], 1000)
        self.assertEqual(row["verified"], 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_instances"), 31)

    def test_09_confirm_creates_transaction_line_and_immutable_audit(self):
        result = self.app.receiving.commit(
            self.app.receiving.review(self.existing_form()).token
        )
        action = self._row(
            "SELECT * FROM inventory_actions WHERE id=?", (result["action_id"],)
        )
        self.assertEqual(action["actor"], "Cowboy")
        self.assertEqual(action["module"], "filament-receiving-ui")
        self.assertEqual(action["origin"], "user")
        self.assertEqual(action["action_type"], "add_individual_instance")
        self.assertEqual(action["affected_human_id"], "THS-FIL-000031")
        self.assertEqual(action["reason"], "Verified delivery")
        self.assertEqual(action["transaction_id"], result["transaction_id"])
        line = self._row(
            "SELECT * FROM transaction_lines WHERE transaction_id=?",
            (result["transaction_id"],),
        )
        self.assertEqual(line["instance_id"], result["instance_id"])
        self.assertEqual(line["quantity_change"], 1000)
        db = connect(self.database)
        with self.assertRaises(Exception):
            db.execute(
                "UPDATE inventory_actions SET reason='changed' WHERE id=?",
                (result["action_id"],),
            )
        db.close()

    def test_10_confirmation_page_summarizes_completed_action(self):
        review = self.app.receiving.review(self.existing_form())
        status, _, page = self.post(
            "/inventory/filament/receive/confirm",
            {"review_token": review.token, "confirm": "receive"},
        )
        self.assertEqual(status, 201)
        self.assertIn("THS-FIL-000031 was received", page)
        self.assertIn("Inventory transaction", page)
        self.assertIn("Immutable audit action", page)
        self.assertIn("View THS-FIL-000031", page)

    def test_11_new_verified_product_and_attributes_flow_through_action_service(self):
        result = self.app.receiving.commit(
            self.app.receiving.review(self.new_form()).token
        )
        self.assertTrue(result["product_created"])
        product = self._row(
            "SELECT ci.*,m.name manufacturer FROM catalog_items ci "
            "JOIN manufacturers m ON m.id=ci.manufacturer_id WHERE ci.id=?",
            (result["catalog_item_id"],),
        )
        self.assertEqual(product["manufacturer"], "Polymaker")
        self.assertEqual(product["product_line"], "PolyLite PLA")
        self.assertEqual(product["variant"], "Army Beige")
        self.assertEqual(
            self.scalar(
                "SELECT COUNT(*) FROM catalog_item_attribute_values WHERE catalog_item_id=?",
                (result["catalog_item_id"],),
            ),
            4,
        )
        actions = [
            row[0] for row in self._rows(
                "SELECT action_type FROM inventory_actions ORDER BY id"
            )
        ]
        self.assertIn("create_manufacturer", actions)
        self.assertIn("create_catalog_item", actions)
        self.assertEqual(actions.count("create_catalog_item_attribute"), 4)
        self.assertEqual(actions[-1], "add_individual_instance")

    def test_12_stale_preview_is_rejected_instead_of_changing_permanent_id(self):
        first = self.app.receiving.review(self.existing_form())
        stale = self.app.receiving.review(self.existing_form(reason="Stale review"))
        self.app.receiving.commit(first.token)
        with self.assertRaisesRegex(ReceiveSpoolError, "inventory changed after preview"):
            self.app.receiving.commit(stale.token)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_instances"), 31)

    def test_13_existing_spools_remain_unchanged(self):
        before = self._rows(
            "SELECT id,permanent_id,state,location_id,remaining_quantity "
            "FROM inventory_instances ORDER BY id"
        )
        self.app.receiving.commit(
            self.app.receiving.review(self.existing_form()).token
        )
        after = self._rows(
            "SELECT id,permanent_id,state,location_id,remaining_quantity "
            "FROM inventory_instances WHERE id<=30 ORDER BY id"
        )
        self.assertEqual(before, after)
        self.assertEqual(
            self.scalar(
                "SELECT COUNT(*) FROM inventory_instances i JOIN catalog_items ci "
                "ON ci.id=i.catalog_item_id JOIN manufacturers m ON m.id=ci.manufacturer_id "
                "WHERE m.name='Bambu Lab' AND ci.variant='Orange' AND i.state='sealed'"
            ),
            3,
        )

    def test_14_get_cannot_commit_and_post_cannot_use_read_routes(self):
        status, _, _ = self.app.response("/inventory/filament/receive/confirm")
        self.assertEqual(status, 404)
        status, _, _ = self.post("/", {})
        self.assertEqual(status, 405)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_instances"), 30)

    def _counts(self):
        return (
            self.scalar("SELECT COUNT(*) FROM catalog_items"),
            self.scalar("SELECT COUNT(*) FROM inventory_instances"),
            self.scalar("SELECT COUNT(*) FROM inventory_transactions"),
            self.scalar("SELECT COUNT(*) FROM inventory_actions"),
        )

    def _row(self, sql, params=()):
        db = connect(self.database)
        try:
            row = db.execute(sql, params).fetchone()
            return dict(row) if row else None
        finally:
            db.close()

    def _rows(self, sql, params=()):
        db = connect(self.database)
        try:
            return [tuple(row) for row in db.execute(sql, params).fetchall()]
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()

