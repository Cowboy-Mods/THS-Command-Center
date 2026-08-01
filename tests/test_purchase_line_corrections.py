import sqlite3
import tempfile
import unittest
from pathlib import Path

from inventory.actions import ActionContext, InventoryActionError, InventoryActionService
from inventory.db import MIGRATIONS, connect, migrate
from inventory.purchase_line_corrections import (
    PurchaseLineCorrectionError,
    PurchaseLineCorrectionService,
)
from inventory.purchase_receiving import PurchaseReceivingService
from inventory.purchases import PurchaseRegistryService


class PurchaseLineTrackingCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        category = db.execute("SELECT id FROM categories ORDER BY id LIMIT 1").fetchone()[0]
        each = db.execute("SELECT id FROM units WHERE code='ea'").fetchone()[0]
        maker = db.execute("INSERT INTO manufacturers(name) VALUES ('Correction Maker')").lastrowid
        individual = db.execute(
            """INSERT INTO item_types(category_id,name,tracking_method,id_prefix,default_unit_id)
            VALUES (?,'Correction Serialized','individual','THS-CORR',?)""",
            (category, each),
        ).lastrowid
        quantity = db.execute(
            """INSERT INTO item_types(category_id,name,tracking_method,default_unit_id)
            VALUES (?,'Correction Quantity','quantity',?)""", (category, each),
        ).lastrowid
        self.individual_item = db.execute(
            "INSERT INTO catalog_items(item_type_id,manufacturer_id,name,base_unit_id) VALUES (?,?,?,?)",
            (individual, maker, "Original serialized candidate", each),
        ).lastrowid
        self.quantity_item = db.execute(
            "INSERT INTO catalog_items(item_type_id,manufacturer_id,name,base_unit_id) VALUES (?,?,?,?)",
            (quantity, maker, "Corrected quantity stock", each),
        ).lastrowid
        self.location_id = db.execute(
            "SELECT id FROM locations WHERE kind='storage' ORDER BY id LIMIT 1"
        ).fetchone()[0]
        db.commit()
        db.close()
        purchase = PurchaseRegistryService(self.database, b"purchase" * 4)
        result = purchase.commit_create(purchase.review_create({
            "actor": "Cowboy", "vendor_name": "Correction Vendor",
            "vendor_order_number": "CORRECTION-ORDER", "purchase_date": "2026-08-01",
            "currency_code": "USD", "subtotal_cents": 2000, "tax_cents": 0,
            "shipping_cents": 0, "discount_cents": 0, "total_cents": 2000,
            "reason": "Capture original procurement facts.",
            "lines": [
                {"category_code": "filament", "description": "Refill one",
                 "quantity_ordered": "1", "unit_label": "each", "unit_price_cents": 1000,
                 "line_discount_cents": 0, "line_total_cents": 1000,
                 "inventory_tracking_intent": "individual", "catalog_item_id": self.individual_item},
                {"category_code": "printer_parts", "description": "Counted part",
                 "quantity_ordered": "1", "unit_label": "each", "unit_price_cents": 1000,
                 "line_discount_cents": 0, "line_total_cents": 1000,
                 "inventory_tracking_intent": "individual", "catalog_item_id": self.individual_item},
            ],
        })["token"], confirmed=True)
        self.purchase_id = result["purchase_id"]
        self.purchase_service = purchase
        self.line_ids = [r[0] for r in self._query(
            "SELECT id FROM purchase_order_lines WHERE purchase_order_id=? ORDER BY line_number",
            (self.purchase_id,),
        )]
        self.service = PurchaseLineCorrectionService(self.database, b"correction" * 4)

    def tearDown(self):
        self.temp.cleanup()

    def _query(self, sql, params=()):
        db = connect(self.database)
        try:
            return db.execute(sql, params).fetchall()
        finally:
            db.close()

    def form(self):
        return {"actor": "Cowboy", "origin": "user",
                "reason": "Verified nonserialized physical stock.",
                "provenance": "THS-PO-000001 pre-receiving review",
                "lines": [{"purchase_order_line_id": line_id,
                           "effective_tracking_policy": "quantity"}
                          for line_id in self.line_ids]}

    def test_preview_is_zero_write_and_commit_is_atomic_append_only(self):
        review = self.service.review(self.form())
        self.assertEqual(self._query("SELECT COUNT(*) FROM purchase_line_tracking_corrections")[0][0], 0)
        result = self.service.commit(review["token"], confirmed=True)
        self.assertEqual(result["line_count"], 2)
        rows = self._query(
            """SELECT pol.inventory_tracking_intent,pole.effective_tracking_policy,
            c.reason,c.actor,c.module,c.origin,c.provenance,c.payload_sha256
            FROM purchase_order_lines pol JOIN purchase_order_lines_effective pole ON pole.id=pol.id
            JOIN purchase_line_tracking_corrections c ON c.purchase_order_line_id=pol.id
            ORDER BY pol.id"""
        )
        self.assertEqual([(r[0], r[1]) for r in rows], [("individual", "quantity")] * 2)
        self.assertTrue(all(len(r[7]) == 64 for r in rows))
        db = connect(self.database)
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE purchase_line_tracking_corrections SET reason='rewrite'")
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("DELETE FROM purchase_line_tracking_corrections")
        db.close()

    def test_duplicate_contradictory_replay_stale_and_post_receipt_corrections_reject(self):
        duplicate = self.form()
        duplicate["lines"] = [dict(duplicate["lines"][0]), dict(duplicate["lines"][0])]
        with self.assertRaisesRegex(PurchaseLineCorrectionError, "unique"):
            self.service.review(duplicate)
        review = self.service.review(self.form())
        self.service.commit(review["token"], confirmed=True)
        with self.assertRaisesRegex(PurchaseLineCorrectionError, "already used"):
            self.service.commit(review["token"], confirmed=True)
        with self.assertRaisesRegex(PurchaseLineCorrectionError, "active correction"):
            self.service.review(self.form())

    def test_existing_purchase_behavior_is_unchanged_without_correction(self):
        snapshot = PurchaseReceivingService(self.database).receiving_status(self.purchase_id)
        self.assertTrue(all(line["effective_tracking_policy"] == "individual"
                            for line in snapshot["lines"]))
        self.assertTrue(all(line["tracking_correction_id"] is None
                            for line in snapshot["lines"]))

    def test_commit_failure_rolls_back_entire_correction_batch(self):
        db = connect(self.database)
        db.execute(f"""CREATE TRIGGER fail_second_correction
            BEFORE INSERT ON purchase_line_tracking_corrections
            WHEN NEW.purchase_order_line_id={self.line_ids[1]}
            BEGIN SELECT RAISE(ABORT,'simulated correction failure'); END""")
        db.commit()
        db.close()
        with self.assertRaises(PurchaseLineCorrectionError):
            self.service.commit(self.service.review(self.form())["token"], confirmed=True)
        self.assertEqual(self._query(
            "SELECT COUNT(*) FROM purchase_line_tracking_corrections"
        )[0][0], 0)

    def test_receiving_uses_effective_quantity_policy_without_permanent_ids(self):
        instances_before = self._query("SELECT COUNT(*) FROM inventory_instances")[0][0]
        self.service.commit(self.service.review(self.form())["token"], confirmed=True)
        evidence_path = Path(self.temp.name) / "delivery.jpg"
        evidence_path.write_bytes(b"temporary verified delivery fixture")
        evidence = self.purchase_service.commit_add_evidence(
            self.purchase_service.review_add_evidence({
                "purchase_id": self.purchase_id, "actor": "Cowboy",
                "evidence_scope": "delivery", "evidence_type": "photo",
                "file_path": str(evidence_path), "document_date": "2026-08-01",
                "caption": "Temporary delivery fixture", "reason": "Test evidence only.",
            })["token"], confirmed=True,
        )
        evidence_uuid = self._query(
            "SELECT evidence_uuid FROM purchase_evidence WHERE id=?", (evidence["evidence_id"],)
        )[0][0]
        receiving = PurchaseReceivingService(self.database, b"receiving" * 4)
        snapshot = receiving.receiving_status(self.purchase_id)
        self.assertTrue(all(line["inventory_tracking_intent"] == "individual" for line in snapshot["lines"]))
        self.assertTrue(all(line["effective_tracking_policy"] == "quantity" for line in snapshot["lines"]))
        receipt = receiving.review_receipt({
            "purchase_id": self.purchase_id, "actor": "Cowboy",
            "reason": "Temporary corrected-policy receipt fixture.",
            "physical_receipt_date": "2026-08-01", "physical_receipt_time": "",
            "receipt_time_precision": "date_only", "evidence_uuids": [evidence_uuid],
            "lines": [{"purchase_order_line_id": line_id, "quantity_received": "1",
                       "condition": "new", "catalog_item_id": self.quantity_item,
                       "location_id": self.location_id} for line_id in self.line_ids],
        })
        self.assertTrue(all(not line["inventory_identities"][0].get("permanent_id")
                            for line in receipt["values"]["lines"]))
        receiving.commit_receipt(receipt["token"], confirmed=True)
        self.assertEqual(self._query("SELECT COUNT(*) FROM stock_lots")[0][0], 2)
        self.assertEqual(self._query("SELECT COUNT(*) FROM inventory_instances")[0][0], instances_before)


class ControlledLocationServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        self.db = connect(self.database)
        migrate(self.db)
        self.actions = InventoryActionService(
            self.db, ActionContext(actor="Cowboy", module="location-test", origin="user")
        )

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_cabinet_tree_is_audited_idempotent_and_conflict_safe(self):
        workshop = self.db.execute("SELECT id FROM locations WHERE name='Workshop'").fetchone()[0]
        cabinet, created = self.actions.ensure_location("Parts Cabinet 1", parent_id=workshop)
        left, left_created = self.actions.ensure_location("PC1-L5", parent_id=cabinet)
        right, right_created = self.actions.ensure_location("PC1-R5", parent_id=cabinet)
        self.assertTrue(created and left_created and right_created)
        self.assertEqual(self.actions.ensure_location(" pc1-l5 ", parent_id=cabinet), (left, False))
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM inventory_actions WHERE action_type='create_location'"
        ).fetchone()[0], 3)
        with self.assertRaises(InventoryActionError):
            self.actions.ensure_location("PC1-L5", parent_id=cabinet, kind="equipment")
        self.assertNotEqual(left, right)


class PurchaseLineCorrectionMigrationTests(unittest.TestCase):
    def test_020_is_additive_atomic_idempotent_and_preserves_source_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "schema19.sqlite3"
            db = connect(database)
            db.execute("""CREATE TABLE schema_migrations(
                name TEXT PRIMARY KEY,applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            for migration in sorted(MIGRATIONS.glob("*.sql")):
                if migration.name == "020_purchase_line_tracking_corrections.sql":
                    break
                db.executescript(migration.read_text(encoding="utf-8"))
                db.execute("INSERT INTO schema_migrations(name) VALUES (?)", (migration.name,))
            before = db.execute("SELECT COUNT(*) FROM purchase_order_lines").fetchone()[0]
            db.commit()
            self.assertEqual(migrate(db), ["020_purchase_line_tracking_corrections.sql"])
            self.assertEqual(migrate(db), [])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM purchase_order_lines").fetchone()[0], before)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM purchase_line_tracking_corrections"
            ).fetchone()[0], 0)
            self.assertEqual(db.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())
            db.close()


if __name__ == "__main__":
    unittest.main()
