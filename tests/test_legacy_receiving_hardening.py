import base64
import hashlib
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from inventory.catalog_correction import CatalogCorrectionError, CatalogCorrectionWorkflow
from inventory.db import connect, migrate
from inventory.orders import OrderReceiptError, OrderReceiptWorkflow


class LegacyReceivingHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        self.order_id = db.execute(
            "SELECT id FROM orders WHERE order_number='THS-ORD-000001'"
        ).fetchone()[0]
        self.item_id = db.execute(
            "SELECT catalog_item_id FROM orders WHERE id=?", (self.order_id,)
        ).fetchone()[0]
        self.location_id = db.execute(
            "SELECT id FROM locations WHERE name='Sealed Filament Rack'"
        ).fetchone()[0]
        self.files = []
        self.evidence_uuids = []
        for number, contents in enumerate((b"arrival proof", b"package proof"), 1):
            path = Path(self.temp.name) / f"proof-{number}.jpg"
            path.write_bytes(contents)
            evidence_uuid = str(uuid.uuid4())
            db.execute(
                """INSERT INTO order_delivery_evidence(
                evidence_uuid,order_id,evidence_scope,evidence_type,file_path,sha256,
                file_size,caption,actor,request_nonce) VALUES
                (?,?,'delivery','photo',?,?,?,?,?,?)""",
                (evidence_uuid, self.order_id, str(path),
                 hashlib.sha256(contents).hexdigest(), len(contents),
                 f"Proof {number}", "Cowboy", uuid.uuid4().hex),
            )
            self.files.append(path)
            self.evidence_uuids.append(evidence_uuid)
        db.commit()
        db.close()
        self.receiving = OrderReceiptWorkflow(self.database, secret=b"r" * 32)
        self.catalog = CatalogCorrectionWorkflow(self.database, secret=b"c" * 32)

    def tearDown(self):
        self.temp.cleanup()

    def receipt_form(self, **changes):
        form = {
            "order_id": str(self.order_id), "actual_quantity": "4",
            "condition": "new", "location_id": str(self.location_id),
            "actor": "Cowboy", "reason": "Verified full shipment",
            "note": "Four sealed refill coils", "physically_verified": "yes",
            "physical_receipt_date": "2026-07-26", "physical_receipt_time": "",
            "receipt_time_precision": "date_only",
            "evidence_uuids": ",".join(self.evidence_uuids),
        }
        form.update(changes)
        return form

    def correction_form(self, **changes):
        form = {
            "catalog_item_id": str(self.item_id), "actor": "Cowboy",
            "reason": "Correct pre-receipt catalog identity using verified delivered-product information.",
            "name": "High Speed PLA Filament Refill",
            "product_line": "High Speed PLA", "variant": "White",
            "filament_form": "Refill coil",
        }
        form.update(changes)
        return form

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

    def test_date_only_receipt_keeps_physical_time_null_and_commit_time_separate(self):
        result = self.receiving.commit(self.receiving.review(self.receipt_form()).token)
        batch = self.row("SELECT * FROM receiving_batches WHERE id=?", (result["batch_id"],))
        self.assertEqual(batch["physical_receipt_date"], "2026-07-26")
        self.assertIsNone(batch["physical_receipt_time"])
        self.assertEqual(batch["receipt_time_precision"], "date_only")
        self.assertIsNotNone(batch["recorded_at"])
        self.assertEqual(batch["recorded_at"], batch["received_at"])
        self.assertNotIn("physical_receipt_time", batch["recorded_at"])

    def test_exact_physical_receipt_time_is_supported(self):
        review = self.receiving.review(self.receipt_form(
            physical_receipt_time="09:15", receipt_time_precision="exact"
        ))
        result = self.receiving.commit(review.token)
        batch = self.row("SELECT * FROM receiving_batches WHERE id=?", (result["batch_id"],))
        self.assertEqual(batch["physical_receipt_time"], "09:15:00")
        self.assertEqual(batch["receipt_time_precision"], "exact")

    def test_catalog_preview_is_zero_write_and_commit_preserves_identity_and_order(self):
        before = self.row("SELECT * FROM catalog_items WHERE id=?", (self.item_id,))
        review = self.catalog.review(self.correction_form())
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM catalog_item_history"), 0)
        self.assertEqual(self.row("SELECT * FROM catalog_items WHERE id=?", (self.item_id,)), before)
        result = self.catalog.commit(review["token"], confirmed=True)
        self.assertEqual(result["catalog_item_id"], self.item_id)
        self.assertEqual(self.scalar(
            "SELECT catalog_item_id FROM orders WHERE id=?", (self.order_id,)), self.item_id)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM catalog_item_history"), 1)
        db = connect(self.database)
        with self.assertRaises(Exception):
            db.execute("DELETE FROM catalog_item_history")
        db.close()

    def test_catalog_tamper_expiration_stale_state_and_replay_are_rejected(self):
        review = self.catalog.review(self.correction_form())
        with self.assertRaises(CatalogCorrectionError):
            self.catalog.commit(review["token"] + "x", confirmed=True)
        with patch("inventory.catalog_correction.time.time", return_value=10**12):
            with self.assertRaisesRegex(CatalogCorrectionError, "expired"):
                self.catalog.commit(review["token"], confirmed=True)
        db = connect(self.database)
        db.execute("UPDATE catalog_items SET notes='state changed' WHERE id=?", (self.item_id,))
        db.commit()
        db.close()
        with self.assertRaisesRegex(CatalogCorrectionError, "changed after preview"):
            self.catalog.commit(review["token"], confirmed=True)
        fresh = self.catalog.review(self.correction_form())
        self.catalog.commit(fresh["token"], confirmed=True)
        with self.assertRaisesRegex(CatalogCorrectionError, "already used"):
            self.catalog.commit(fresh["token"], confirmed=True)

    def test_catalog_preview_signs_exact_order_and_evidence_dependencies(self):
        before = self.scalar("SELECT COUNT(*) FROM catalog_item_history")
        review = self.catalog.review(self.correction_form())
        verified, _ = self.catalog._verify(review["token"])
        self.assertEqual(verified["current"]["dependent_orders"], [{
            "id": self.order_id, "order_number": "THS-ORD-000001",
            "catalog_item_id": self.item_id, "state": "ordered",
            "expected_quantity": 4, "received_quantity": 0,
        }])
        self.assertEqual(
            [row["evidence_uuid"] for row in verified["current"]["delivery_evidence"]],
            self.evidence_uuids,
        )
        for row in verified["current"]["delivery_evidence"]:
            self.assertEqual(
                set(row), {"id", "evidence_uuid", "order_id", "evidence_scope",
                           "evidence_type", "file_path", "sha256", "file_size"}
            )
        self.assertEqual(before, self.scalar("SELECT COUNT(*) FROM catalog_item_history"))

    def test_replaced_or_added_order_dependency_rejects_same_count_and_more(self):
        review = self.catalog.review(self.correction_form())
        db = connect(self.database)
        db.execute("UPDATE orders SET catalog_item_id=NULL WHERE id=?", (self.order_id,))
        db.execute(
            """INSERT INTO orders(order_number,supplier,description,catalog_item_id,
            expected_quantity,unit_label,state) VALUES
            ('THS-ORD-999998','Other','Replacement dependency',?,4,'rolls','ordered')""",
            (self.item_id,),
        )
        db.commit()
        db.close()
        with self.assertRaisesRegex(CatalogCorrectionError, "changed after preview"):
            self.catalog.commit(review["token"], confirmed=True)

        db = connect(self.database)
        db.execute("DELETE FROM orders WHERE order_number='THS-ORD-999998'")
        db.execute("UPDATE orders SET catalog_item_id=? WHERE id=?", (self.item_id, self.order_id))
        db.commit()
        db.close()
        review = self.catalog.review(self.correction_form())
        db = connect(self.database)
        db.execute(
            """INSERT INTO orders(order_number,supplier,description,catalog_item_id,
            expected_quantity,unit_label,state) VALUES
            ('THS-ORD-999999','Other','Additional dependency',?,1,'roll','ordered')""",
            (self.item_id,),
        )
        db.commit()
        db.close()
        with self.assertRaisesRegex(CatalogCorrectionError, "changed after preview"):
            self.catalog.commit(review["token"], confirmed=True)

    def test_order_state_or_quantity_change_rejects_catalog_commit(self):
        for statement in (
            "UPDATE orders SET state='shipped' WHERE id=?",
            "UPDATE orders SET expected_quantity=5 WHERE id=?",
            "UPDATE orders SET received_quantity=1 WHERE id=?",
        ):
            review = self.catalog.review(self.correction_form())
            db = connect(self.database)
            original = dict(db.execute("SELECT * FROM orders WHERE id=?",
                                       (self.order_id,)).fetchone())
            db.execute(statement, (self.order_id,))
            db.commit()
            db.close()
            with self.assertRaisesRegex(CatalogCorrectionError, "changed after preview"):
                self.catalog.commit(review["token"], confirmed=True)
            db = connect(self.database)
            db.execute(
                "UPDATE orders SET state=?,expected_quantity=?,received_quantity=? WHERE id=?",
                (original["state"], original["expected_quantity"],
                 original["received_quantity"], self.order_id),
            )
            db.commit()
            db.close()

    def test_evidence_substitution_missing_and_changed_file_are_rejected(self):
        review = self.catalog.review(self.correction_form())
        db = connect(self.database)
        db.execute("DROP TRIGGER order_delivery_evidence_immutable_delete")
        db.execute("DROP TRIGGER order_delivery_evidence_history_immutable_delete")
        db.execute("DELETE FROM order_delivery_evidence_history")
        db.execute("DELETE FROM order_delivery_evidence WHERE evidence_uuid=?",
                   (self.evidence_uuids[0],))
        replacement = Path(self.temp.name) / "replacement.jpg"
        replacement.write_bytes(b"substituted evidence")
        db.execute(
            """INSERT INTO order_delivery_evidence(
            evidence_uuid,order_id,evidence_scope,evidence_type,file_path,sha256,
            file_size,caption,actor,request_nonce) VALUES
            (?,?, 'delivery','photo',?,?,?,?,?,?)""",
            (str(uuid.uuid4()), self.order_id, str(replacement),
             hashlib.sha256(replacement.read_bytes()).hexdigest(),
             replacement.stat().st_size, "Replacement", "Cowboy", uuid.uuid4().hex),
        )
        db.commit()
        db.close()
        with self.assertRaisesRegex(CatalogCorrectionError, "changed after preview"):
            self.catalog.commit(review["token"], confirmed=True)

        self.tearDown()
        self.setUp()
        review = self.catalog.review(self.correction_form())
        db = connect(self.database)
        db.execute("DROP TRIGGER order_delivery_evidence_immutable_delete")
        db.execute("DROP TRIGGER order_delivery_evidence_history_immutable_delete")
        db.execute("DELETE FROM order_delivery_evidence_history")
        db.execute("DELETE FROM order_delivery_evidence WHERE evidence_uuid=?",
                   (self.evidence_uuids[0],))
        db.commit()
        db.close()
        with self.assertRaisesRegex(CatalogCorrectionError, "changed after preview"):
            self.catalog.commit(review["token"], confirmed=True)

        self.tearDown()
        self.setUp()
        review = self.catalog.review(self.correction_form())
        self.files[0].write_bytes(b"changed external evidence")
        with self.assertRaisesRegex(CatalogCorrectionError, "file changed"):
            self.catalog.commit(review["token"], confirmed=True)

    def test_filament_form_is_canonical_and_arbitrary_or_missing_values_reject(self):
        review = self.catalog.review(self.correction_form(filament_form="  rEfIlL   CoIl "))
        self.assertEqual(review["values"]["proposed"]["filament_form"], "Refill coil")
        self.assertEqual(
            review["values"]["proposed_snapshot"]["filament_form"], "Refill coil"
        )
        for value in ("", "Reusable spool", "anything"):
            with self.assertRaisesRegex(CatalogCorrectionError, "Refill coil"):
                self.catalog.review(self.correction_form(filament_form=value))

    def test_identity_conflict_detected_during_preview_and_after_preview(self):
        def add_conflict():
            db = connect(self.database)
            db.execute(
                """INSERT INTO catalog_items(item_type_id,manufacturer_id,name,
                product_line,variant,base_unit_id) SELECT item_type_id,manufacturer_id,
                '  high speed pla filament refill  ','HIGH SPEED PLA',' white ',
                base_unit_id FROM catalog_items WHERE id=?""", (self.item_id,)
            )
            db.commit()
            db.close()

        add_conflict()
        with self.assertRaisesRegex(CatalogCorrectionError, "conflicts"):
            self.catalog.review(self.correction_form())

        self.tearDown()
        self.setUp()
        review = self.catalog.review(self.correction_form())
        add_conflict()
        with self.assertRaisesRegex(CatalogCorrectionError, "conflicts"):
            self.catalog.commit(review["token"], confirmed=True)

    def test_history_uuid_is_preview_bound_and_atomic_failure_rolls_back(self):
        review = self.catalog.review(self.correction_form())
        history_uuid = review["values"]["history_uuid"]
        result = self.catalog.commit(review["token"], confirmed=True)
        self.assertEqual(result["history_uuid"], history_uuid)
        self.assertEqual(
            self.scalar("SELECT history_uuid FROM catalog_item_history"), history_uuid
        )

        self.tearDown()
        self.setUp()
        before = self.row("SELECT * FROM catalog_items WHERE id=?", (self.item_id,))
        review = self.catalog.review(self.correction_form())
        db = connect(self.database)
        db.execute(
            """CREATE TRIGGER fail_catalog_history BEFORE INSERT ON catalog_item_history
            BEGIN SELECT RAISE(ABORT,'simulated catalog history failure'); END"""
        )
        db.commit()
        db.close()
        with self.assertRaises(CatalogCorrectionError):
            self.catalog.commit(review["token"], confirmed=True)
        self.assertEqual(self.row(
            "SELECT * FROM catalog_items WHERE id=?", (self.item_id,)), before)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM catalog_item_history"), 0)

    def test_receipt_preview_binds_batch_spools_evidence_and_link_uuids_without_writes(self):
        before = tuple(self.scalar(f"SELECT COUNT(*) FROM {table}") for table in (
            "receiving_batches", "inventory_instances",
            "receiving_batch_delivery_evidence", "inventory_actions"))
        review = self.receiving.review(self.receipt_form())
        values = review.values
        self.assertEqual(len(values["permanent_ids"]), 4)
        self.assertEqual(len(values["evidence"]), 2)
        self.assertEqual(len(values["evidence_links"]), 2)
        uuid.UUID(values["batch_uuid"])
        for link in values["evidence_links"]:
            uuid.UUID(link["link_uuid"])
        self.assertEqual(before, tuple(self.scalar(f"SELECT COUNT(*) FROM {table}") for table in (
            "receiving_batches", "inventory_instances",
            "receiving_batch_delivery_evidence", "inventory_actions")))

    def test_wrong_order_missing_or_changed_evidence_is_rejected(self):
        db = connect(self.database)
        other = db.execute(
            """INSERT INTO orders(order_number,supplier,description,expected_quantity,
            unit_label,state) VALUES ('THS-ORD-999999','Other','Other',1,'item','ordered')"""
        ).lastrowid
        other_path = Path(self.temp.name) / "other.jpg"
        other_path.write_bytes(b"other")
        other_uuid = str(uuid.uuid4())
        db.execute(
            """INSERT INTO order_delivery_evidence(
            evidence_uuid,order_id,evidence_type,file_path,sha256,file_size,caption,
            actor,request_nonce) VALUES (?,?,?,?,?,?,?,?,?)""",
            (other_uuid, other, "photo", str(other_path),
             hashlib.sha256(b"other").hexdigest(), 5, "Other", "Cowboy", uuid.uuid4().hex),
        )
        db.commit()
        db.close()
        with self.assertRaisesRegex(OrderReceiptError, "belonging"):
            self.receiving.review(self.receipt_form(evidence_uuids=other_uuid))
        review = self.receiving.review(self.receipt_form())
        self.files[0].unlink()
        with self.assertRaisesRegex(OrderReceiptError, "missing"):
            self.receiving.commit(review.token)

    def test_quantity_and_already_received_rules(self):
        for quantity in ("0", "3", "5"):
            with self.assertRaises(OrderReceiptError):
                self.receiving.review(self.receipt_form(actual_quantity=quantity))
        token = self.receiving.review(self.receipt_form()).token
        self.receiving.commit(token)
        with self.assertRaises(OrderReceiptError):
            self.receiving.review(self.receipt_form())
        with self.assertRaises(OrderReceiptError):
            self.receiving.commit(token)

    def test_preview_bound_ids_commit_unchanged_and_sequence_conflict_rejects(self):
        review = self.receiving.review(self.receipt_form())
        result = self.receiving.commit(review.token)
        self.assertEqual(result["batch_uuid"], review.values["batch_uuid"])
        self.assertEqual(result["permanent_ids"], review.values["permanent_ids"])
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM receiving_batch_delivery_evidence"), 2)

        # A separate database proves an intervening sequence claim rejects safely.
        self.tearDown()
        self.setUp()
        review = self.receiving.review(self.receipt_form())
        db = connect(self.database)
        order = db.execute("SELECT catalog_item_id FROM orders WHERE id=?",
                           (self.order_id,)).fetchone()
        unit = db.execute("SELECT base_unit_id FROM catalog_items WHERE id=?",
                          (order[0],)).fetchone()[0]
        db.execute(
            """INSERT INTO inventory_instances(permanent_id,catalog_item_id,state,location_id,
            original_quantity,remaining_quantity,unit_id) VALUES (?,?, 'sealed',?,1000,1000,?)""",
            (review.values["permanent_ids"][0], order[0], self.location_id, unit),
        )
        db.commit()
        db.close()
        with self.assertRaisesRegex(OrderReceiptError, "inventory changed"):
            self.receiving.commit(review.token)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM receiving_batches"), 0)

    def test_atomic_failure_rolls_back_every_receipt_row_and_final_state_is_derived(self):
        db = connect(self.database)
        db.execute(
            """CREATE TRIGGER fail_second_link BEFORE INSERT ON receiving_batch_delivery_evidence
            WHEN (SELECT COUNT(*) FROM receiving_batch_delivery_evidence)=1
            BEGIN SELECT RAISE(ABORT,'simulated evidence link failure'); END"""
        )
        db.commit()
        db.close()
        with self.assertRaises(OrderReceiptError):
            self.receiving.commit(self.receiving.review(self.receipt_form()).token)
        for table in ("receiving_batches", "receiving_batch_delivery_evidence",
                      "order_received_instances"):
            self.assertEqual(self.scalar(f"SELECT COUNT(*) FROM {table}"), 0)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM inventory_instances WHERE catalog_item_id=?", (self.item_id,)), 0)
        order = self.row("SELECT state,received_quantity FROM orders WHERE id=?", (self.order_id,))
        self.assertEqual(order, {"state": "ordered", "received_quantity": 0})

    def test_received_refills_are_sealed_full_weight_storage_only(self):
        self.receiving.commit(self.receiving.review(self.receipt_form()).token)
        rows = []
        db = connect(self.database)
        rows = [dict(row) for row in db.execute(
            """SELECT state,condition,location_id,original_quantity,remaining_quantity,
            opened_at FROM inventory_instances WHERE catalog_item_id=?""", (self.item_id,))]
        db.close()
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(
            (r["state"], r["condition"], r["location_id"], r["original_quantity"],
             r["remaining_quantity"], r["opened_at"])
            == ("sealed", "new", self.location_id, 1000, 1000, None) for r in rows
        ))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM ams_assignments"), 0)
        self.assertEqual(self.row(
            "SELECT state,received_quantity FROM orders WHERE id=?", (self.order_id,)),
            {"state": "received", "received_quantity": 4})

    def test_duplicate_evidence_link_is_rejected_by_schema(self):
        result = self.receiving.commit(self.receiving.review(self.receipt_form()).token)
        link = self.row("SELECT * FROM receiving_batch_delivery_evidence LIMIT 1")
        db = connect(self.database)
        with self.assertRaises(Exception):
            db.execute(
                """INSERT INTO receiving_batch_delivery_evidence(
                link_uuid,receiving_batch_id,evidence_id) VALUES (?,?,?)""",
                (str(uuid.uuid4()), result["batch_id"], link["evidence_id"]),
            )
        db.close()


if __name__ == "__main__":
    unittest.main()
