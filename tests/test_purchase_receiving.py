import hashlib
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from inventory.checkpoint import purchase_receiving_dry_run
from inventory.db import MIGRATIONS, connect, migrate
from inventory.purchase_receiving import (
    PurchaseReceivingError,
    PurchaseReceivingService,
)
from inventory.purchases import PurchaseRegistryService


class PurchaseRegistryReceivingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        self._catalog(db)
        db.close()
        self.purchase_service = PurchaseRegistryService(
            self.database, b"purchase" * 4
        )
        created = self.purchase_service.commit_create(
            self.purchase_service.review_create(self.purchase_form())["token"],
            confirmed=True,
        )
        self.purchase_id = created["purchase_id"]
        self.evidence_path = Path(self.temp.name) / "delivery.jpg"
        self.evidence_path.write_bytes(b"verified delivered package")
        evidence = self.purchase_service.commit_add_evidence(
            self.purchase_service.review_add_evidence({
                "purchase_id": str(self.purchase_id),
                "actor": "Cowboy",
                "evidence_scope": "delivery",
                "evidence_type": "photo",
                "file_path": str(self.evidence_path),
                "caption": "Verified delivered mixed shipment",
                "document_date": "2026-07-27",
                "reason": "Register delivery proof without receiving inventory.",
            })["token"],
            confirmed=True,
        )
        self.evidence_uuid = self.scalar(
            "SELECT evidence_uuid FROM purchase_evidence WHERE id=?",
            (evidence["evidence_id"],),
        )
        self.service = PurchaseReceivingService(
            self.database, b"receiving" * 4
        )

    def tearDown(self):
        self.temp.cleanup()

    def _catalog(self, db):
        category = db.execute(
            "SELECT id FROM categories ORDER BY id LIMIT 1"
        ).fetchone()[0]
        each = db.execute(
            "SELECT id FROM units WHERE code='ea'"
        ).fetchone()[0]
        gram = db.execute(
            "SELECT id FROM units WHERE code='g'"
        ).fetchone()[0]
        manufacturer = db.execute(
            "INSERT INTO manufacturers(name) VALUES ('Receiving Test Maker')"
        ).lastrowid
        individual_type = db.execute(
            """INSERT INTO item_types(
            category_id,name,tracking_method,id_prefix,default_unit_id)
            VALUES (?,'Tracked Part','individual','THS-PART',?)""",
            (category, each),
        ).lastrowid
        quantity_type = db.execute(
            """INSERT INTO item_types(
            category_id,name,tracking_method,default_unit_id)
            VALUES (?,'Counted Supply','quantity',?)""",
            (category, each),
        ).lastrowid
        lot_type = db.execute(
            """INSERT INTO item_types(
            category_id,name,tracking_method,default_unit_id)
            VALUES (?,'Lot Supply','lot',?)""",
            (category, gram),
        ).lastrowid
        self.individual_item = db.execute(
            """INSERT INTO catalog_items(
            item_type_id,manufacturer_id,name,base_unit_id)
            VALUES (?,?,'Tracked replacement',?)""",
            (individual_type, manufacturer, each),
        ).lastrowid
        self.quantity_item = db.execute(
            """INSERT INTO catalog_items(
            item_type_id,manufacturer_id,name,base_unit_id)
            VALUES (?,?,'Cleaning pads',?)""",
            (quantity_type, manufacturer, each),
        ).lastrowid
        self.lot_item = db.execute(
            """INSERT INTO catalog_items(
            item_type_id,manufacturer_id,name,base_unit_id)
            VALUES (?,?,'Lubricant batch',?)""",
            (lot_type, manufacturer, gram),
        ).lastrowid
        self.location_id = db.execute(
            "SELECT id FROM locations WHERE kind='storage' ORDER BY id LIMIT 1"
        ).fetchone()[0]
        db.commit()

    def purchase_form(self):
        return {
            "actor": "Cowboy",
            "vendor_name": "Mixed Receiving Vendor",
            "vendor_order_number": "MIXED-1",
            "purchase_date": "2026-07-27",
            "currency_code": "USD",
            "subtotal_cents": 2700,
            "tax_cents": 100,
            "shipping_cents": 200,
            "discount_cents": 50,
            "total_cents": 2950,
            "notes": "Mixed-policy receipt test",
            "reason": "Register ordered facts only.",
            "lines": [
                {
                    "category_code": "printer_parts",
                    "description": "Tracked replacement",
                    "quantity_ordered": "2",
                    "unit_label": "each",
                    "unit_price_cents": 500,
                    "line_discount_cents": 0,
                    "line_total_cents": 1000,
                    "inventory_tracking_intent": "individual",
                    "catalog_item_id": self.individual_item,
                },
                {
                    "category_code": "consumables",
                    "description": "Cleaning pads",
                    "quantity_ordered": "5",
                    "unit_label": "each",
                    "unit_price_cents": 100,
                    "line_discount_cents": 0,
                    "line_total_cents": 500,
                    "inventory_tracking_intent": "quantity",
                    "catalog_item_id": self.quantity_item,
                },
                {
                    "category_code": "consumables",
                    "description": "Lubricant",
                    "quantity_ordered": "10",
                    "unit_label": "g",
                    "unit_price_cents": 100,
                    "line_discount_cents": 0,
                    "line_total_cents": 1000,
                    "inventory_tracking_intent": "lot",
                    "catalog_item_id": self.lot_item,
                },
                {
                    "category_code": "miscellaneous",
                    "description": "Non-inventory expense",
                    "quantity_ordered": "1",
                    "unit_label": "service",
                    "unit_price_cents": 250,
                    "line_discount_cents": 50,
                    "line_total_cents": 200,
                    "inventory_tracking_intent": "non_inventory",
                },
            ],
        }

    def receipt_form(self, quantities=("1", "2", "4", "1")):
        lines = self.rows(
            "SELECT id,line_number,inventory_tracking_intent,catalog_item_id "
            "FROM purchase_order_lines WHERE purchase_order_id=? ORDER BY line_number",
            (self.purchase_id,),
        )
        result = []
        for row, quantity in zip(lines, quantities):
            if quantity == "0":
                continue
            item = {
                "purchase_order_line_id": row["id"],
                "quantity_received": quantity,
                "condition": "new",
            }
            if row["inventory_tracking_intent"] != "non_inventory":
                item.update({
                    "catalog_item_id": row["catalog_item_id"],
                    "location_id": self.location_id,
                })
            if row["inventory_tracking_intent"] == "lot":
                item["lot_number"] = "LOT-VERIFIED"
            result.append(item)
        return {
            "purchase_id": self.purchase_id,
            "actor": "Cowboy",
            "reason": "Verified physical arrival only.",
            "physical_receipt_date": "2026-07-27",
            "physical_receipt_time": "",
            "receipt_time_precision": "date_only",
            "note": "No item was installed, opened, assigned, loaded, used, or consumed.",
            "evidence_uuids": [self.evidence_uuid],
            "lines": result,
        }

    def transition_form(self, status):
        return {
            "purchase_id": self.purchase_id,
            "actor": "Cowboy",
            "reason": f"Verified {status} status.",
            "new_status": status,
            "physical_event_date": "2026-07-27",
            "physical_event_time": "",
            "event_time_precision": "date_only",
        }

    def scalar(self, sql, params=()):
        db = connect(self.database)
        try:
            return db.execute(sql, params).fetchone()[0]
        finally:
            db.close()

    def rows(self, sql, params=()):
        db = connect(self.database)
        try:
            return [dict(row) for row in db.execute(sql, params)]
        finally:
            db.close()

    def test_01_migration_is_additive_immutable_and_initializes_projection(self):
        self.assertEqual(
            self.scalar(
                "SELECT status FROM purchase_order_receiving_status "
                "WHERE purchase_order_id=?",
                (self.purchase_id,),
            ),
            "ordered",
        )
        for table in (
            "purchase_fulfillment_history",
            "purchase_receipts",
            "purchase_receipt_lines",
            "purchase_receipt_evidence",
            "purchase_receipt_inventory_links",
        ):
            self.assertEqual(self.scalar(f"SELECT COUNT(*) FROM {table}"), 0)
        self.assertEqual(
            self.scalar(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' "
                "AND name='purchase_receipts_immutable_delete'"
            ),
            1,
        )

    def test_02_controlled_shipping_delivery_and_cancellation_rules(self):
        shipped = self.service.review_transition(self.transition_form("shipped"))
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM purchase_fulfillment_history"), 0)
        result = self.service.commit_transition(shipped["token"], confirmed=True)
        self.assertEqual(result["status"], "shipped")
        delivered = self.service.commit_transition(
            self.service.review_transition(
                self.transition_form("delivered")
            )["token"],
            confirmed=True,
        )
        self.assertEqual(delivered["status"], "delivered")
        with self.assertRaises(PurchaseReceivingError):
            self.service.review_transition(self.transition_form("shipped"))

        # A second purchase proves Ordered -> Delivered catch-up and cancellation.
        self.tearDown()
        self.setUp()
        direct = self.service.commit_transition(
            self.service.review_transition(
                self.transition_form("delivered")
            )["token"],
            confirmed=True,
        )
        self.assertEqual(direct["status"], "delivered")
        canceled = self.service.commit_transition(
            self.service.review_transition(
                self.transition_form("canceled")
            )["token"],
            confirmed=True,
        )
        self.assertEqual(canceled["status"], "canceled")

    def test_03_mixed_partial_receipt_is_zero_write_then_atomic(self):
        before = {
            table: self.scalar(f"SELECT COUNT(*) FROM {table}")
            for table in (
                "purchase_receipts", "inventory_instances", "stock_lots",
                "inventory_actions", "inventory_transactions",
            )
        }
        review = self.service.review_receipt(self.receipt_form())
        self.assertEqual(before, {
            table: self.scalar(f"SELECT COUNT(*) FROM {table}")
            for table in before
        })
        self.assertEqual(
            review["values"]["lines"][0]["inventory_identities"][0][
                "permanent_id"
            ],
            "THS-PART-000001",
        )
        result = self.service.commit_receipt(review["token"], confirmed=True)
        self.assertEqual(result["status"], "partially_received")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_receipts"), 1)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM purchase_receipt_lines"), 4)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM purchase_receipt_inventory_links"), 3)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM inventory_instances "
            "WHERE permanent_id='THS-PART-000001' AND state='sealed'"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM stock_lots"), 2)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM inventory_transactions"), 3)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM inventory_actions"), 3)

    def test_04_second_receipt_completes_and_preserves_separate_facts(self):
        self.service.commit_receipt(
            self.service.review_receipt(self.receipt_form())["token"],
            confirmed=True,
        )
        result = self.service.commit_receipt(
            self.service.review_receipt(
                self.receipt_form(("1", "3", "6", "0"))
            )["token"],
            confirmed=True,
        )
        self.assertEqual(result["status"], "received")
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM inventory_instances WHERE catalog_item_id=?",
            (self.individual_item,),
        ), 2)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM stock_lots"), 4)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM purchase_maintenance_links"), 0)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM ams_assignments"), 0)
        with self.assertRaisesRegex(PurchaseReceivingError, "received to canceled"):
            self.service.review_transition(self.transition_form("canceled"))

    def test_05_over_receipt_duplicate_noninventory_and_tracking_mismatch_reject(self):
        form = self.receipt_form(("3", "2", "4", "1"))
        with self.assertRaisesRegex(PurchaseReceivingError, "exceeds"):
            self.service.review_receipt(form)
        form = self.receipt_form()
        form["lines"].append(dict(form["lines"][0]))
        with self.assertRaisesRegex(PurchaseReceivingError, "twice"):
            self.service.review_receipt(form)
        form = self.receipt_form()
        form["lines"][3]["catalog_item_id"] = self.quantity_item
        form["lines"][3]["location_id"] = self.location_id
        with self.assertRaisesRegex(PurchaseReceivingError, "cannot create"):
            self.service.review_receipt(form)
        form = self.receipt_form()
        form["lines"][0]["catalog_item_id"] = self.quantity_item
        with self.assertRaisesRegex(PurchaseReceivingError, "does not match"):
            self.service.review_receipt(form)

    def test_06_tamper_expiry_replay_stale_sequence_and_changed_evidence_reject(self):
        review = self.service.review_receipt(self.receipt_form())
        with self.assertRaises(PurchaseReceivingError):
            self.service.commit_receipt(review["token"] + "x", confirmed=True)
        with patch("inventory.purchase_receiving.time.time", return_value=10**12):
            with self.assertRaisesRegex(PurchaseReceivingError, "expired"):
                self.service.commit_receipt(review["token"], confirmed=True)
        self.evidence_path.write_bytes(b"changed")
        with self.assertRaisesRegex(PurchaseReceivingError, "changed"):
            self.service.commit_receipt(review["token"], confirmed=True)
        self.evidence_path.write_bytes(b"verified delivered package")
        review = self.service.review_receipt(self.receipt_form())
        db = connect(self.database)
        db.execute(
            """INSERT INTO inventory_instances(
            permanent_id,catalog_item_id,state,location_id,original_quantity,
            remaining_quantity,unit_id)
            SELECT ?,ci.id,'sealed',?,1,1,ci.base_unit_id
            FROM catalog_items ci WHERE ci.id=?""",
            (
                review["values"]["lines"][0]["inventory_identities"][0][
                    "permanent_id"
                ],
                self.location_id,
                self.individual_item,
            ),
        )
        db.commit()
        db.close()
        with self.assertRaisesRegex(PurchaseReceivingError, "sequence"):
            self.service.commit_receipt(review["token"], confirmed=True)

        self.tearDown()
        self.setUp()
        review = self.service.review_receipt(self.receipt_form())
        self.service.commit_receipt(review["token"], confirmed=True)
        with self.assertRaisesRegex(PurchaseReceivingError, "already used"):
            self.service.commit_receipt(review["token"], confirmed=True)

    def test_07_atomic_failure_rolls_back_receipt_inventory_status_and_history(self):
        before = {
            table: self.scalar(f"SELECT COUNT(*) FROM {table}")
            for table in (
                "purchase_receipts", "purchase_receipt_lines",
                "purchase_receipt_inventory_links", "inventory_instances",
                "stock_lots", "inventory_actions", "inventory_transactions",
                "purchase_fulfillment_history",
            )
        }
        db = connect(self.database)
        db.execute(
            """CREATE TRIGGER fail_receipt_history
            BEFORE INSERT ON purchase_fulfillment_history
            BEGIN SELECT RAISE(ABORT,'simulated history failure'); END"""
        )
        db.commit()
        db.close()
        with self.assertRaises(PurchaseReceivingError):
            self.service.commit_receipt(
                self.service.review_receipt(self.receipt_form())["token"],
                confirmed=True,
            )
        for table, count in before.items():
            self.assertEqual(self.scalar(f"SELECT COUNT(*) FROM {table}"), count)
        self.assertEqual(self.service.receiving_status(self.purchase_id)["status"], "ordered")

    def test_08_receipts_never_copy_or_double_count_money(self):
        self.service.commit_receipt(
            self.service.review_receipt(self.receipt_form())["token"],
            confirmed=True,
        )
        receipt_columns = {
            row["name"] for row in self.rows("PRAGMA table_info(purchase_receipts)")
        }
        line_columns = {
            row["name"]
            for row in self.rows("PRAGMA table_info(purchase_receipt_lines)")
        }
        for column in (
            "subtotal_cents", "tax_cents", "shipping_cents",
            "discount_cents", "line_total_cents",
        ):
            self.assertNotIn(column, receipt_columns)
            self.assertNotIn(column, line_columns)
        self.assertEqual(self.scalar(
            "SELECT total_cents FROM purchase_orders WHERE id=?",
            (self.purchase_id,),
        ), 2950)


class PurchaseReceivingMigrationPreviewTests(unittest.TestCase):
    def test_017_preview_changes_only_temporary_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "schema16.sqlite3"
            db = connect(database)
            db.execute(
                "CREATE TABLE schema_migrations "
                "(name TEXT PRIMARY KEY,applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            for migration in sorted(MIGRATIONS.glob("*.sql")):
                if migration.name == "017_purchase_registry_receiving.sql":
                    break
                db.executescript(migration.read_text(encoding="utf-8"))
                db.execute(
                    "INSERT INTO schema_migrations(name) VALUES (?)",
                    (migration.name,),
                )
            db.commit()
            db.close()
            before = hashlib.sha256(database.read_bytes()).hexdigest()
            result = purchase_receiving_dry_run(database)
            after = hashlib.sha256(database.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertEqual(
                result["applied"], ["017_purchase_registry_receiving.sql"]
            )
            self.assertEqual(result["applied_again"], [])
            self.assertEqual(result["integrity"], "ok")
            self.assertEqual(result["quick_check"], "ok")
            self.assertEqual(result["foreign_key_violations"], 0)


if __name__ == "__main__":
    unittest.main()
