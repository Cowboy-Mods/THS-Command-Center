import hashlib
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from inventory.db import connect, migrate
from inventory.order_evidence import (
    OrderDeliveryEvidenceError,
    OrderDeliveryEvidenceService,
)
from inventory.purchases import PurchaseRegistryService
from inventory.queries import InventoryQueries
from inventory.web import InventoryWebApp


class LegacyOrderDeliveryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        db.close()
        self.service = OrderDeliveryEvidenceService(
            self.database, b"legacy-delivery-evidence-test"
        )
        self.first = self.root / "arrival-one.jpeg"
        self.second = self.root / "arrival-two.jpeg"
        self.first.write_bytes(b"arrival photo one")
        self.second.write_bytes(b"arrival photo two")

    def tearDown(self):
        self.temp.cleanup()

    def form(self, path=None, **changes):
        values = {
            "order_id": "1",
            "evidence_type": "photo",
            "file_path": str(path or self.first),
            "caption": "Four sealed White PLA refills visually verified.",
            "captured_at": "",
            "actor": "Cowboy",
        }
        values.update(changes)
        return values

    def scalar(self, sql, params=()):
        db = connect(self.database)
        try:
            return db.execute(sql, params).fetchone()[0]
        finally:
            db.close()

    def order_state(self):
        db = connect(self.database)
        try:
            return tuple(db.execute(
                """SELECT state,received_quantity,notes FROM orders
                WHERE order_number='THS-ORD-000001'"""
            ).fetchone())
        finally:
            db.close()

    def test_01_migration_applies_once_and_preserves_legacy_order(self):
        from inventory import db as db_module
        migrations = db_module.MIGRATIONS
        old = self.root / "pre015.sqlite3"
        pre015 = self.root / "pre015"
        pre015.mkdir()
        for source in sorted(migrations.glob("*.sql")):
            if source.name < "015_legacy_order_delivery_evidence.sql":
                (pre015 / source.name).write_bytes(source.read_bytes())
        db_module.MIGRATIONS = pre015
        try:
            db = connect(old)
            migrate(db)
            before = tuple(db.execute(
                "SELECT * FROM orders WHERE order_number='THS-ORD-000001'"
            ).fetchone())
            db.close()
        finally:
            db_module.MIGRATIONS = migrations
        through015 = self.root / "through015"
        through015.mkdir()
        for source in sorted(migrations.glob("*.sql")):
            if source.name <= "015_legacy_order_delivery_evidence.sql":
                (through015 / source.name).write_bytes(source.read_bytes())
        db_module.MIGRATIONS = through015
        try:
            db = connect(old)
            first = migrate(db)
            after = tuple(db.execute(
                "SELECT * FROM orders WHERE order_number='THS-ORD-000001'"
            ).fetchone())
            second = migrate(db)
            db.close()
        finally:
            db_module.MIGRATIONS = migrations
        self.assertEqual(first, ["015_legacy_order_delivery_evidence.sql"])
        self.assertEqual(second, [])
        self.assertEqual(before, after)

    def test_02_preview_is_signed_complete_and_zero_write(self):
        before = self.order_state()
        review = self.service.review(self.form())
        self.assertEqual(review["values"]["evidence_scope"], "delivery")
        self.assertEqual(len(review["values"]["evidence_uuid"]), 36)
        self.assertEqual(
            review["values"]["sha256"], hashlib.sha256(self.first.read_bytes()).hexdigest()
        )
        verified, _ = self.service._verify(review["token"])
        self.assertEqual(verified["evidence_uuid"], review["values"]["evidence_uuid"])
        with self.assertRaisesRegex(OrderDeliveryEvidenceError, "confirmation"):
            self.service.commit(review["token"], confirmed=False)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM order_delivery_evidence"), 0)
        self.assertEqual(before, self.order_state())

    def test_03_commit_uses_preview_uuid_and_two_photos_share_order(self):
        reviews = [self.service.review(self.form(path)) for path in (self.first, self.second)]
        results = [self.service.commit(review["token"], confirmed=True) for review in reviews]
        self.assertEqual(
            [result["evidence_uuid"] for result in results],
            [review["values"]["evidence_uuid"] for review in reviews],
        )
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM order_delivery_evidence"), 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM order_delivery_evidence_history"), 2)

    def test_04_changed_and_missing_files_are_rejected(self):
        changed = self.service.review(self.form())
        self.first.write_bytes(b"changed")
        with self.assertRaisesRegex(OrderDeliveryEvidenceError, "changed after preview"):
            self.service.commit(changed["token"], confirmed=True)
        missing = self.service.review(self.form(self.second))
        self.second.unlink()
        with self.assertRaisesRegex(OrderDeliveryEvidenceError, "missing"):
            self.service.commit(missing["token"], confirmed=True)
        with self.assertRaisesRegex(OrderDeliveryEvidenceError, "existing absolute"):
            self.service.review(self.form(self.root / "absent.jpeg"))

    def test_05_stale_tampered_replay_and_duplicate_are_rejected(self):
        review = self.service.review(self.form())
        values = dict(review["values"])
        values["reviewed_at"] = int(time.time()) - self.service.MAX_REVIEW_AGE_SECONDS - 1
        stale = self.service._sign_body(self.service._canonical(values))
        with self.assertRaisesRegex(OrderDeliveryEvidenceError, "expired"):
            self.service.commit(stale, confirmed=True)
        tampered = ("A" if review["token"][0] != "A" else "B") + review["token"][1:]
        with self.assertRaisesRegex(OrderDeliveryEvidenceError, "signature"):
            self.service.commit(tampered, confirmed=True)
        self.service.commit(review["token"], confirmed=True)
        with self.assertRaisesRegex(OrderDeliveryEvidenceError, "already used"):
            self.service.commit(review["token"], confirmed=True)
        with self.assertRaisesRegex(OrderDeliveryEvidenceError, "already registered"):
            self.service.review(self.form())
        duplicate_copy = self.root / "same-bytes-different-name.jpeg"
        duplicate_copy.write_bytes(self.first.read_bytes())
        with self.assertRaisesRegex(OrderDeliveryEvidenceError, "already registered"):
            self.service.review(self.form(duplicate_copy))

    def test_06_immutable_private_and_no_inventory_side_effects(self):
        before = {
            "order": self.order_state(),
            "inventory": self.scalar("SELECT COUNT(*) FROM inventory_instances"),
            "batches": self.scalar("SELECT COUNT(*) FROM receiving_batches"),
            "actions": self.scalar("SELECT COUNT(*) FROM inventory_actions"),
            "transactions": self.scalar("SELECT COUNT(*) FROM inventory_transactions"),
        }
        with self.assertRaisesRegex(OrderDeliveryEvidenceError, "private"):
            self.service.review(self.form(caption="Phone number 555-0100"))
        result = self.service.commit(
            self.service.review(self.form())["token"], confirmed=True
        )
        db = connect(self.database)
        for sql in (
            f"UPDATE order_delivery_evidence SET caption='changed' WHERE id={result['evidence_id']}",
            f"DELETE FROM order_delivery_evidence WHERE id={result['evidence_id']}",
            "UPDATE order_delivery_evidence_history SET actor='changed'",
        ):
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute(sql)
            db.rollback()
        db.close()
        self.assertEqual(before["order"], self.order_state())
        self.assertEqual(before["inventory"], self.scalar("SELECT COUNT(*) FROM inventory_instances"))
        self.assertEqual(before["batches"], self.scalar("SELECT COUNT(*) FROM receiving_batches"))
        self.assertEqual(before["actions"], self.scalar("SELECT COUNT(*) FROM inventory_actions"))
        self.assertEqual(
            before["transactions"], self.scalar("SELECT COUNT(*) FROM inventory_transactions")
        )

    def test_07_purchase_evidence_still_works_and_order_detail_displays_delivery(self):
        purchase_service = PurchaseRegistryService(self.database, b"purchase-secret")
        purchase = purchase_service.commit_create(
            purchase_service.review_create({
                "actor": "Cowboy", "vendor_name": "Test Vendor",
                "vendor_order_number": "T-1", "purchase_date": "2026-07-26",
                "currency_code": "USD", "subtotal_cents": 100,
                "tax_cents": 0, "shipping_cents": 0, "discount_cents": 0,
                "total_cents": 100, "notes": "", "reason": "Compatibility test",
                "lines": [{
                    "category_code": "miscellaneous", "description": "Test item",
                    "quantity_ordered": "1", "unit_label": "each",
                    "unit_price_cents": 100, "line_discount_cents": 0,
                    "line_total_cents": 100,
                    "inventory_tracking_intent": "non_inventory",
                }],
            })["token"], confirmed=True
        )
        purchase_service.commit_add_evidence(
            purchase_service.review_add_evidence({
                "purchase_id": purchase["purchase_id"], "evidence_scope": "purchase",
                "evidence_type": "photo", "file_path": str(self.second),
                "caption": "Purchase evidence", "actor": "Cowboy",
            })["token"], confirmed=True
        )
        self.service.commit(
            self.service.review(self.form())["token"], confirmed=True
        )
        detail = InventoryQueries(self.database).order_detail(1)
        self.assertEqual(detail["delivery_evidence"][0]["evidence_scope"], "delivery")
        status, _, body = InventoryWebApp(self.database).response("/orders/1")
        self.assertEqual(status, 200)
        self.assertIn("Four sealed White PLA refills", body.decode())
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_evidence"), 1)


if __name__ == "__main__":
    unittest.main()
