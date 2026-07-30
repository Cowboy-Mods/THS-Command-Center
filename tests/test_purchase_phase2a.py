import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from inventory.db import connect, migrate
from inventory.maintenance import MaintenanceWorkflow
from inventory.purchases import PurchaseError, PurchaseRegistryService


class PurchaseEvidenceAndMaintenanceLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        db.close()
        self.service = PurchaseRegistryService(self.database, b"phase2a-secret")
        created = self.service.commit_create(
            self.service.review_create(self.purchase_form())["token"], confirmed=True
        )
        self.purchase_id = created["purchase_id"]
        detail = self.service.purchase(self.purchase_id)
        self.line_id = detail["lines"][0]["id"]
        self.maintenance_id = self.create_maintenance()
        self.evidence = self.root / "invoice.png"
        self.evidence.write_bytes(b"immutable purchase invoice bytes")

    def tearDown(self):
        self.temp.cleanup()

    def purchase_form(self):
        return {
            "actor": "Cowboy", "vendor_name": "Bambu Lab",
            "vendor_order_number": "", "purchase_date": "2026-07-26",
            "currency_code": "USD", "subtotal_cents": 1000,
            "tax_cents": 70, "shipping_cents": 0, "discount_cents": 0,
            "total_cents": 1070, "notes": "Test purchase", "reason": "Test",
            "lines": [{
                "category_code": "printer_parts", "description": "Purge Chute",
                "quantity_ordered": "1", "unit_label": "each",
                "unit_price_cents": 1000, "line_discount_cents": 0,
                "line_total_cents": 1000,
                "inventory_tracking_intent": "non_inventory",
            }],
        }

    def create_maintenance(self):
        db = connect(self.database)
        asset_id = db.execute(
            "SELECT id FROM maintenance_assets WHERE display_name='THS Printer'"
        ).fetchone()[0]
        db.close()
        workflow = MaintenanceWorkflow(self.database, b"maintenance-secret")
        review = workflow.review("record_fault", {
            "asset_id": str(asset_id), "event_type": "fault_discovered",
            "initial_status": "in_progress", "severity": "high",
            "discovered_at": "2026-07-26T09:00:00-04:00", "due_at": "",
            "symptoms": "Purge chute fault.", "likely_cause": "",
            "corrective_action": "", "parts_required": "Purge Chute",
            "parts_used": "", "notes": "", "related_print_id": "",
            "readiness_state": "no_unattended_printing",
            "unattended_printing_allowed": "", "actor": "Cowboy",
        })
        return workflow.commit(review["token"])["record_id"]

    def evidence_form(self, **changes):
        values = {
            "purchase_id": str(self.purchase_id), "evidence_scope": "purchase",
            "evidence_type": "invoice", "file_path": str(self.evidence),
            "caption": "Order invoice; not delivery evidence.",
            "document_date": "2026-07-26", "reason": "Verified invoice",
            "actor": "Cowboy",
        }
        values.update(changes)
        return values

    def link_form(self, **changes):
        values = {
            "purchase_id": str(self.purchase_id),
            "purchase_order_line_id": str(self.line_id),
            "maintenance_record_id": str(self.maintenance_id),
            "relationship_type": "corrective_replacement",
            "note": "Required replacement; not received or installed.",
            "reason": "Link ordered part", "actor": "Cowboy",
        }
        values.update(changes)
        return values

    def scalar(self, sql):
        db = connect(self.database)
        try:
            return db.execute(sql).fetchone()[0]
        finally:
            db.close()

    def test_01_evidence_preview_is_signed_complete_and_zero_write(self):
        before = (self.scalar("SELECT COUNT(*) FROM purchase_evidence"),
                  self.scalar("SELECT COUNT(*) FROM purchase_history"))
        review = self.service.review_add_evidence(self.evidence_form())
        self.assertEqual(review["values"]["evidence_scope"], "purchase")
        self.assertEqual(len(review["values"]["evidence_uuid"]), 36)
        self.assertEqual(len(review["values"]["sha256"]), 64)
        self.assertEqual(before, (
            self.scalar("SELECT COUNT(*) FROM purchase_evidence"),
            self.scalar("SELECT COUNT(*) FROM purchase_history"),
        ))

    def test_02_purchase_and_delivery_evidence_are_distinct(self):
        purchase_review = self.service.review_add_evidence(self.evidence_form())
        purchase = self.service.commit_add_evidence(
            purchase_review["token"],
            confirmed=True,
        )
        delivery = self.service.commit_add_evidence(
            self.service.review_add_evidence(
                self.evidence_form(evidence_scope="delivery", evidence_type="photo")
            )["token"], confirmed=True,
        )
        self.assertEqual(
            purchase["snapshot"]["evidence_uuid"],
            purchase_review["values"]["evidence_uuid"],
        )
        self.assertEqual((purchase["evidence_scope"], delivery["evidence_scope"]),
                         ("purchase", "delivery"))

    def test_03_explicit_confirmation_tampering_expiry_and_replay_are_rejected(self):
        review = self.service.review_add_evidence(self.evidence_form())
        with self.assertRaisesRegex(PurchaseError, "confirmation"):
            self.service.commit_add_evidence(review["token"], confirmed=False)
        tampered = ("A" if review["token"][0] != "A" else "B") + review["token"][1:]
        with self.assertRaisesRegex(PurchaseError, "signature"):
            self.service.commit_add_evidence(tampered, confirmed=True)
        values = dict(review["values"])
        values["reviewed_at"] = int(time.time()) - self.service.MAX_REVIEW_AGE_SECONDS - 1
        expired = self.service._sign_body(self.service._canonical(values))
        with self.assertRaisesRegex(PurchaseError, "expired"):
            self.service.commit_add_evidence(expired, confirmed=True)
        self.service.commit_add_evidence(review["token"], confirmed=True)
        with self.assertRaisesRegex(PurchaseError, "already used"):
            self.service.commit_add_evidence(review["token"], confirmed=True)

    def test_04_evidence_sha_is_revalidated_at_commit(self):
        review = self.service.review_add_evidence(self.evidence_form())
        self.evidence.write_bytes(b"changed after preview")
        with self.assertRaisesRegex(PurchaseError, "changed after preview"):
            self.service.commit_add_evidence(review["token"], confirmed=True)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_evidence"), 0)

    def test_05_maintenance_link_preview_and_commit_preserve_meaning(self):
        review = self.service.review_link_maintenance(self.link_form())
        self.assertEqual(review["values"]["relationship_type"], "corrective_replacement")
        self.assertEqual(len(review["values"]["link_uuid"]), 36)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_maintenance_links"), 0)
        result = self.service.commit_link_maintenance(review["token"], confirmed=True)
        self.assertEqual(result["maintenance_number"], "THS-MNT-000001")
        self.assertEqual(result["snapshot"]["link_uuid"], review["values"]["link_uuid"])
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_maintenance_links"), 1)

    def test_06_wrong_purchase_line_is_rejected(self):
        second = self.service.commit_create(
            self.service.review_create({
                **self.purchase_form(), "vendor_order_number": "SECOND",
            })["token"], confirmed=True
        )
        other_line = self.service.purchase(second["purchase_id"])["lines"][0]["id"]
        with self.assertRaisesRegex(PurchaseError, "does not belong"):
            self.service.review_link_maintenance(
                self.link_form(purchase_order_line_id=str(other_line))
            )

    def test_07_evidence_link_and_history_are_immutable(self):
        evidence = self.service.commit_add_evidence(
            self.service.review_add_evidence(self.evidence_form())["token"], confirmed=True
        )
        link = self.service.commit_link_maintenance(
            self.service.review_link_maintenance(self.link_form())["token"], confirmed=True
        )
        db = connect(self.database)
        for sql in (
            f"UPDATE purchase_evidence SET caption='changed' WHERE id={evidence['evidence_id']}",
            f"DELETE FROM purchase_maintenance_links WHERE id={link['link_id']}",
            "UPDATE purchase_history SET reason='changed'",
        ):
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute(sql)
            db.rollback()
        db.close()

    def test_08_history_failure_rolls_back_evidence_atomically(self):
        db = connect(self.database)
        db.execute("""CREATE TRIGGER fail_phase2a_history BEFORE INSERT ON purchase_history
        BEGIN SELECT RAISE(ABORT,'simulated history failure'); END""")
        db.commit()
        db.close()
        with self.assertRaises(PurchaseError):
            self.service.commit_add_evidence(
                self.service.review_add_evidence(self.evidence_form())["token"],
                confirmed=True,
            )
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM purchase_evidence"), 0)

    def test_09_phase2a_never_receives_or_changes_inventory(self):
        before = (
            self.scalar("SELECT COUNT(*) FROM inventory_instances"),
            self.scalar("SELECT COUNT(*) FROM receiving_batches"),
            self.scalar("SELECT received_quantity FROM orders WHERE order_number='THS-ORD-000001'"),
        )
        self.service.commit_link_maintenance(
            self.service.review_link_maintenance(self.link_form())["token"], confirmed=True
        )
        self.assertEqual(before, (
            self.scalar("SELECT COUNT(*) FROM inventory_instances"),
            self.scalar("SELECT COUNT(*) FROM receiving_batches"),
            self.scalar("SELECT received_quantity FROM orders WHERE order_number='THS-ORD-000001'"),
        ))

    def test_10_read_only_detail_includes_evidence_and_links(self):
        self.service.commit_add_evidence(
            self.service.review_add_evidence(self.evidence_form())["token"], confirmed=True
        )
        self.service.commit_link_maintenance(
            self.service.review_link_maintenance(self.link_form())["token"], confirmed=True
        )
        detail = self.service.purchase(self.purchase_id)
        self.assertEqual(len(detail["evidence"]), 1)
        self.assertEqual(len(detail["maintenance_links"]), 1)


if __name__ == "__main__":
    unittest.main()
