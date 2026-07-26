import sqlite3
import tempfile
import unittest
from pathlib import Path

from inventory.db import connect, migrate
from inventory.maintenance import MaintenanceError, MaintenanceWorkflow
from inventory.production import ProductionService
from inventory.actions import ActionContext
from inventory.web import InventoryWebApp


class MaintenanceRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        self.asset_id = db.execute(
            """SELECT ma.id FROM maintenance_assets ma JOIN printers p ON p.id=ma.printer_id
            WHERE p.model='P1S'"""
        ).fetchone()[0]
        printer_id = db.execute("SELECT id FROM printers WHERE model='P1S'").fetchone()[0]
        db.commit()
        db.close()
        production = ProductionService(
            self.database, ActionContext("Cowboy", "maintenance-test", "user")
        )
        self.print_id = production.complete_print(
            job_name="Test print", plate_name="Plate 1", part_name="Test part",
            inspection_status="accepted_with_defect", defect_notes="Layer shift.",
            completed_at="2026-07-26T09:00:00-04:00", printer_id=printer_id,
        )["id"]
        self.workflow = MaintenanceWorkflow(
            self.database, secret=b"maintenance-test-secret"
        )

    def tearDown(self):
        self.temp.cleanup()

    def form(self, **changes):
        values = {
            "asset_id": str(self.asset_id),
            "event_type": "repair",
            "severity": "high",
            "discovered_at": "2026-07-26T09:05:00-04:00",
            "due_at": "2026-07-27T09:05:00-04:00",
            "symptoms": "Nozzle wiping failed and purge waste backed up.",
            "likely_cause": "Wiper assembly detached.",
            "corrective_action": "Inspect, reinstall, clean, and test.",
            "parts_required": "Rubber or PTFE wiping piece",
            "parts_used": "",
            "notes": "Development test data only.",
            "related_print_id": str(self.print_id),
            "readiness_state": "no_unattended_printing",
            "unattended_printing_allowed": "",
            "actor": "Cowboy",
        }
        values.update(changes)
        return values

    def transition(self, record_id, **changes):
        values = {
            "record_id": str(record_id),
            "reason": "Controlled state transition.",
            "readiness_state": "no_unattended_printing",
            "unattended_printing_allowed": "",
            "parts_required": "",
            "parts_used": "",
            "corrective_action": "",
            "completed_at": "",
            "actor": "Cowboy",
        }
        values.update(changes)
        return values

    def scalar(self, sql, values=()):
        db = connect(self.database)
        try:
            return db.execute(sql, values).fetchone()[0]
        finally:
            db.close()

    def create(self, action="create_task", **changes):
        review = self.workflow.review(action, self.form(**changes))
        return self.workflow.commit(review["token"])

    def test_01_pending_repair_preview_is_zero_write_and_commit_is_audited(self):
        before = self.scalar("SELECT COUNT(*) FROM maintenance_records")
        review = self.workflow.review("create_task", self.form())
        self.assertEqual(before, self.scalar("SELECT COUNT(*) FROM maintenance_records"))
        self.assertEqual(review["values"]["status"], "pending")
        result = self.workflow.commit(review["token"])
        self.assertRegex(result["event_number"], r"^THS-MNT-\d{6}$")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM maintenance_history"), 1)

    def test_02_missing_part_is_recorded_and_blocked_waiting_for_part(self):
        record = self.create()
        review = self.workflow.review(
            "mark_waiting_for_part",
            self.transition(record["record_id"], parts_required="Replacement wiper"),
        )
        result = self.workflow.commit(review["token"])
        self.assertEqual(result["status"], "blocked_waiting_for_part")
        self.assertEqual(
            self.scalar("SELECT status FROM maintenance_records WHERE id=?",
                        (record["record_id"],)),
            "blocked_waiting_for_part",
        )

    def test_03_blocked_requires_a_missing_or_required_part(self):
        record = self.create(parts_required="")
        with self.assertRaisesRegex(MaintenanceError, "requires the missing"):
            self.workflow.review(
                "mark_waiting_for_part", self.transition(record["record_id"])
            )

    def test_04_completed_repair_records_parts_action_and_time(self):
        record = self.create()
        result = self.workflow.commit(self.workflow.review(
            "complete_maintenance",
            self.transition(
                record["record_id"], parts_used="Replacement wiper",
                corrective_action="Installed wiper and cleaned chute.",
                completed_at="2026-07-26T12:00:00-04:00",
            ),
        )["token"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            self.scalar("SELECT parts_used FROM maintenance_records WHERE id=?",
                        (record["record_id"],)),
            "Replacement wiper",
        )

    def test_05_verification_sets_verified_and_can_restore_normal_readiness(self):
        record = self.create()
        self.workflow.commit(self.workflow.review(
            "complete_maintenance",
            self.transition(
                record["record_id"], completed_at="2026-07-26T12:00:00-04:00"
            ),
        )["token"])
        result = self.workflow.commit(self.workflow.review(
            "verify_repair",
            self.transition(
                record["record_id"], reason="Supervised verification print passed.",
                readiness_state="normal", unattended_printing_allowed="yes",
                completed_at="2026-07-26T13:00:00-04:00",
            ),
        )["token"])
        self.assertEqual(result["status"], "verified")
        self.assertEqual(
            self.scalar("SELECT readiness_state FROM maintenance_assets WHERE id=?",
                        (self.asset_id,)),
            "normal",
        )

    def test_06_reopen_after_failed_verification_preserves_history(self):
        record = self.create()
        self.workflow.commit(self.workflow.review(
            "complete_maintenance",
            self.transition(
                record["record_id"], completed_at="2026-07-26T12:00:00-04:00"
            ),
        )["token"])
        result = self.workflow.commit(self.workflow.review(
            "reopen_task",
            self.transition(
                record["record_id"], reason="Verification print failed.",
                readiness_state="out_of_service",
            ),
        )["token"])
        self.assertEqual(result["status"], "pending")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM maintenance_history"), 3)

    def test_07_fault_links_to_affected_print_and_disables_unattended_use(self):
        result = self.create(
            action="record_fault", event_type="fault_discovered",
            readiness_state="no_unattended_printing",
        )
        db = connect(self.database)
        try:
            row = db.execute(
                "SELECT related_print_id,unattended_printing_allowed FROM maintenance_records"
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(row["related_print_id"], self.print_id)
        self.assertEqual(row["unattended_printing_allowed"], 0)
        self.assertEqual(result["action"], "record_fault")

    def test_08_history_identity_and_evidence_are_immutable(self):
        record = self.create()
        photo = Path(self.temp.name) / "wiper.jpg"
        photo.write_bytes(b"maintenance evidence")
        evidence = self.workflow.add_evidence(
            record["record_id"], evidence_type="photo", file_path=str(photo),
            actor="Cowboy", caption="Detached wiper",
        )
        self.assertEqual(len(evidence["sha256"]), 64)
        db = connect(self.database)
        for sql in (
            "DELETE FROM maintenance_records",
            "UPDATE maintenance_history SET reason='changed'",
            "DELETE FROM maintenance_history",
            "UPDATE maintenance_evidence SET caption='changed'",
            "DELETE FROM maintenance_evidence",
        ):
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute(sql)
            db.rollback()
        db.close()

    def test_09_completed_details_cannot_be_silently_edited(self):
        record = self.create()
        self.workflow.commit(self.workflow.review(
            "complete_maintenance",
            self.transition(
                record["record_id"], completed_at="2026-07-26T12:00:00-04:00"
            ),
        )["token"])
        db = connect(self.database)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "controlled transition"):
            db.execute(
                "UPDATE maintenance_records SET symptoms='silently changed' WHERE id=?",
                (record["record_id"],),
            )
        db.close()

    def test_10_replay_protection_prevents_duplicate_write(self):
        review = self.workflow.review("create_task", self.form())
        self.workflow.commit(review["token"])
        with self.assertRaisesRegex(MaintenanceError, "already used"):
            self.workflow.commit(review["token"])
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM maintenance_records"), 1)

    def test_11_backlog_and_all_controlled_workflow_pages_are_available(self):
        self.create(due_at="2020-01-01T00:00:00-05:00")
        backlog = MaintenanceWorkflow.backlog(self.database)
        self.assertEqual(len(backlog["open"]), 1)
        self.assertEqual(len(backlog["overdue"]), 1)
        app = InventoryWebApp(self.database)
        status, _, body = app.response("/maintenance")
        self.assertEqual(status, 200)
        page = body.decode()
        for text in (
            "Maintenance Backlog", "Open tasks", "Blocked tasks", "Overdue tasks",
            "Completed history", "Equipment status", "Record Fault Discovered",
            "Create Maintenance Task",
        ):
            self.assertIn(text, page)
        for action in MaintenanceWorkflow.ACTION_TARGETS:
            status, _, body = app.response(
                f"/maintenance/action?action={action}&id=1"
            )
            self.assertEqual(status, 200)
            self.assertIn("Controlled workflow", body.decode())

    def test_12_web_review_requires_explicit_confirmation(self):
        app = InventoryWebApp(self.database)
        values = self.form(event_type="fault_discovered")
        values["action"] = "record_fault"
        status, _, preview = app.response(
            "/maintenance/review", method="POST", form=values
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM maintenance_records"), 0)
        token = preview.decode().split(
            'name="review_token" value="', 1
        )[1].split('"', 1)[0]
        status, _, _ = app.response(
            "/maintenance/confirm", method="POST",
            form={"review_token": token, "confirm": ""},
        )
        self.assertEqual(status, 422)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM maintenance_records"), 0)


if __name__ == "__main__":
    unittest.main()
