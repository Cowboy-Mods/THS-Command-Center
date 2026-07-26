import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from inventory.db import connect, migrate
from inventory.purchases import PurchaseError, PurchaseRegistryService


class PurchaseRegistryFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        db.close()
        self.service = PurchaseRegistryService(self.database, b"purchase-test-secret")

    def tearDown(self):
        self.temp.cleanup()

    def form(self, **changes):
        values = {
            "actor": "Cowboy",
            "vendor_name": "Bambu Lab",
            "vendor_order_number": "US123456",
            "purchase_date": "2026-07-26",
            "currency_code": "USD",
            "subtotal_cents": 5998,
            "tax_cents": 420,
            "shipping_cents": 0,
            "discount_cents": 500,
            "total_cents": 5918,
            "notes": "Purchase foundation test",
            "reason": "Verified shop purchase",
            "lines": [
                {
                    "category_code": "printer_parts",
                    "description": "Complete Purge Chute",
                    "quantity_ordered": "1",
                    "unit_label": "each",
                    "unit_price_cents": 3999,
                    "line_discount_cents": 0,
                    "line_total_cents": 3999,
                    "inventory_tracking_intent": "non_inventory",
                },
                {
                    "category_code": "maintenance_parts",
                    "description": "Nozzle Wiper",
                    "quantity_ordered": "2",
                    "unit_label": "each",
                    "unit_price_cents": 999,
                    "line_discount_cents": 0,
                    "line_total_cents": 1998,
                    "inventory_tracking_intent": "non_inventory",
                },
                {
                    "category_code": "consumables",
                    "description": "Shop consumable",
                    "quantity_ordered": "1",
                    "unit_label": "pack",
                    "unit_price_cents": 501,
                    "line_discount_cents": 500,
                    "line_total_cents": 1,
                    "inventory_tracking_intent": "non_inventory",
                },
            ],
        }
        values.update(changes)
        return values

    def scalar(self, sql, params=()):
        db = connect(self.database)
        try:
            return db.execute(sql, params).fetchone()[0]
        finally:
            db.close()

    def test_01_migration_adds_categories_and_does_not_convert_legacy_order(self):
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_categories"), 9)
        self.assertEqual(
            self.scalar("SELECT state FROM orders WHERE order_number='THS-ORD-000001'"),
            "ordered",
        )
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_orders"), 0)

    def test_02_preview_is_complete_and_zero_write(self):
        review = self.service.review_create(self.form())
        self.assertEqual(review["values"]["purchase_number"], "THS-PO-000001")
        self.assertEqual(review["values"]["status"], "ordered")
        self.assertEqual(review["values"]["total_cents"], 5918)
        self.assertEqual(len(review["payload_sha256"]), 64)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_vendors"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_orders"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_history"), 0)

    def test_03_confirmation_commits_vendor_order_lines_and_history_atomically(self):
        result = self.service.commit_create(
            self.service.review_create(self.form())["token"], confirmed=True
        )
        self.assertEqual(result["purchase_number"], "THS-PO-000001")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_vendors"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_orders"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_order_lines"), 3)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_history"), 1)
        self.assertEqual(
            self.scalar("SELECT payload_sha256 FROM purchase_history"),
            result["payload_sha256"],
        )

    def test_04_permanent_numbers_increment_and_existing_vendor_is_reused(self):
        first = self.service.commit_create(
            self.service.review_create(self.form())["token"], confirmed=True
        )
        second_form = self.form(
            vendor_id=str(first["vendor_id"]),
            vendor_name="",
            vendor_order_number="US123457",
        )
        second = self.service.commit_create(
            self.service.review_create(second_form)["token"], confirmed=True
        )
        self.assertEqual(second["purchase_number"], "THS-PO-000002")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_vendors"), 1)

    def test_05_explicit_confirmation_is_required(self):
        token = self.service.review_create(self.form())["token"]
        with self.assertRaisesRegex(PurchaseError, "confirmation"):
            self.service.commit_create(token, confirmed=False)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_orders"), 0)

    def test_06_tampered_token_is_rejected(self):
        token = self.service.review_create(self.form())["token"]
        tampered = ("A" if token[0] != "A" else "B") + token[1:]
        with self.assertRaisesRegex(PurchaseError, "signature"):
            self.service.commit_create(tampered, confirmed=True)

    def test_07_signed_payload_cannot_be_altered_between_preview_and_commit(self):
        review = self.service.review_create(self.form())
        body_text, signature = review["token"].split(".", 1)
        values = json.loads(self.service._unb64(body_text))
        values["total_cents"] = 1
        altered = self.service._b64(self.service._canonical(values)) + "." + signature
        with self.assertRaisesRegex(PurchaseError, "signature"):
            self.service.commit_create(altered, confirmed=True)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_orders"), 0)

    def test_08_expired_preview_is_rejected(self):
        review = self.service.review_create(self.form())
        values = dict(review["values"])
        values["reviewed_at"] = int(time.time()) - self.service.MAX_REVIEW_AGE_SECONDS - 1
        token = self.service._sign_body(self.service._canonical(values))
        with self.assertRaisesRegex(PurchaseError, "expired"):
            self.service.commit_create(token, confirmed=True)

    def test_09_replay_is_rejected(self):
        token = self.service.review_create(self.form())["token"]
        self.service.commit_create(token, confirmed=True)
        with self.assertRaisesRegex(PurchaseError, "already used"):
            self.service.commit_create(token, confirmed=True)

    def test_10_sequence_change_requires_new_preview(self):
        review = self.service.review_create(self.form())
        other = self.form(vendor_order_number="US999999")
        self.service.commit_create(
            self.service.review_create(other)["token"], confirmed=True
        )
        with self.assertRaisesRegex(PurchaseError, "changed after preview"):
            self.service.commit_create(review["token"], confirmed=True)

    def test_11_vendor_change_requires_new_preview(self):
        first = self.service.commit_create(
            self.service.review_create(self.form())["token"], confirmed=True
        )
        form = self.form(
            vendor_id=str(first["vendor_id"]), vendor_name="",
            vendor_order_number="US123457",
        )
        review = self.service.review_create(form)
        db = connect(self.database)
        db.execute(
            "UPDATE purchase_vendors SET website='https://changed.example' WHERE id=?",
            (first["vendor_id"],),
        )
        db.commit()
        db.close()
        with self.assertRaisesRegex(PurchaseError, "vendor changed"):
            self.service.commit_create(review["token"], confirmed=True)

    def test_12_totals_are_recalculated_and_must_be_integer_cents(self):
        with self.assertRaisesRegex(PurchaseError, "subtotal"):
            self.service.review_create(self.form(subtotal_cents=5999))
        with self.assertRaisesRegex(PurchaseError, "whole cents"):
            self.service.review_create(self.form(tax_cents="4.20"))
        bad_lines = self.form()["lines"]
        bad_lines[0] = {**bad_lines[0], "line_total_cents": 1}
        with self.assertRaisesRegex(PurchaseError, "line 1 total"):
            self.service.review_create(self.form(lines=bad_lines))

    def test_13_duplicate_vendor_order_number_is_scoped_to_vendor(self):
        self.service.commit_create(
            self.service.review_create(self.form())["token"], confirmed=True
        )
        duplicate = self.form(vendor_id="1", vendor_name="")
        with self.assertRaises(PurchaseError):
            self.service.commit_create(
                self.service.review_create(duplicate)["token"], confirmed=True
            )
        other = self.form(vendor_name="MatterHackers", vendor_order_number="US123456")
        result = self.service.commit_create(
            self.service.review_create(other)["token"], confirmed=True
        )
        self.assertEqual(result["purchase_number"], "THS-PO-000002")

    def test_14_atomic_failure_rolls_back_new_vendor_order_lines_and_history(self):
        db = connect(self.database)
        db.execute(
            """CREATE TRIGGER fail_purchase_history BEFORE INSERT ON purchase_history
            BEGIN SELECT RAISE(ABORT,'simulated history failure'); END"""
        )
        db.commit()
        db.close()
        with self.assertRaises(PurchaseError):
            self.service.commit_create(
                self.service.review_create(self.form())["token"], confirmed=True
            )
        for table in (
            "purchase_vendors", "purchase_orders", "purchase_order_lines", "purchase_history"
        ):
            self.assertEqual(self.scalar(f"SELECT COUNT(*) FROM {table}"), 0)

    def test_15_purchase_identity_lines_and_history_are_immutable(self):
        result = self.service.commit_create(
            self.service.review_create(self.form())["token"], confirmed=True
        )
        db = connect(self.database)
        statements = (
            ("UPDATE purchase_orders SET purchase_number='THS-PO-999999' WHERE id=?",
             (result["purchase_id"],)),
            ("DELETE FROM purchase_orders WHERE id=?", (result["purchase_id"],)),
            ("UPDATE purchase_orders SET status='canceled' WHERE id=?",
             (result["purchase_id"],)),
            ("UPDATE purchase_order_lines SET description='changed'", ()),
            ("DELETE FROM purchase_history", ()),
        )
        for sql, params in statements:
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute(sql, params)
            db.rollback()
        db.close()

    def test_16_read_only_queries_return_header_lines_and_history(self):
        result = self.service.commit_create(
            self.service.review_create(self.form())["token"], confirmed=True
        )
        self.assertEqual(len(self.service.purchases()), 1)
        detail = self.service.purchase(result["purchase_id"])
        self.assertEqual(detail["vendor_name"], "Bambu Lab")
        self.assertEqual(len(detail["lines"]), 3)
        self.assertEqual(len(detail["history"]), 1)

    def test_17_all_approved_categories_are_seeded(self):
        self.assertEqual(
            [row["category_code"] for row in self.service.categories()],
            [
                "filament", "maintenance_parts", "printer_parts", "tools",
                "electronics", "consumables", "shipping", "tax", "miscellaneous",
            ],
        )

    def test_18_catalog_tracking_mismatch_is_rejected(self):
        db = connect(self.database)
        filament_id = db.execute(
            """SELECT ci.id FROM catalog_items ci JOIN item_types it
            ON it.id=ci.item_type_id WHERE it.name='Filament' LIMIT 1"""
        ).fetchone()[0]
        db.close()
        lines = self.form()["lines"]
        lines[0] = {
            **lines[0], "catalog_item_id": filament_id,
            "inventory_tracking_intent": "quantity",
        }
        with self.assertRaisesRegex(PurchaseError, "tracking intent"):
            self.service.review_create(self.form(lines=lines))


if __name__ == "__main__":
    unittest.main()
