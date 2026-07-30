import sqlite3
import tempfile
import unittest
from pathlib import Path

from inventory.actions import ActionContext
from inventory.db import connect, migrate
from inventory.production import ProductionError, ProductionService
from inventory.web import InventoryWebApp


class PrintRegistryCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        self.printer_id = db.execute("SELECT id FROM printers").fetchone()[0]
        self.project_id = db.execute(
            "INSERT INTO projects(name,project_code) VALUES ('Tweety','THS-PRJ-000001')"
        ).lastrowid
        db.commit()
        db.close()
        self.service = ProductionService(
            self.database, ActionContext("Cowboy", "print-registry-test", "user")
        )

    def tearDown(self):
        self.temp.cleanup()

    def scalar(self, sql, values=()):
        db = connect(self.database)
        try:
            return db.execute(sql, values).fetchone()[0]
        finally:
            db.close()

    def complete(self, **overrides):
        values = {
            "job_name": "Tweety Plate 1", "plate_name": "Plate 1",
            "part_name": "Orange Hat", "inspection_status": "accepted_with_defect",
            "defect_notes": "Minor visible flaw accepted for shop use.",
            "completed_at": "2026-07-26T09:00:00-04:00",
            "completion_time_accuracy": "estimated",
            "printer_id": self.printer_id, "project_id": self.project_id,
            "request_nonce": "tweety-plate-1-orange-hat",
        }
        values.update(overrides)
        return self.service.complete_print(**values)

    def test_01_migration_adds_all_stage_two_registry_tables(self):
        db = connect(self.database)
        names = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        db.close()
        self.assertTrue({
            "print_records", "print_evidence", "maintenance_events", "audit_events"
        }.issubset(names))

    def test_02_tweety_first_record_gets_permanent_identity_and_audit(self):
        result = self.complete()
        self.assertEqual(result["print_number"], "THS-PRT-000001")
        self.assertEqual(result["inspection_status"], "accepted_with_defect")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM print_records"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit_events"), 1)
        self.assertEqual(
            self.scalar("SELECT completion_time_accuracy FROM print_records"),
            "estimated",
        )

    def test_03_accepted_with_defect_requires_notes(self):
        with self.assertRaisesRegex(ProductionError, "require defect notes"):
            self.complete(defect_notes=None, request_nonce="different")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM print_records"), 0)

    def test_04_replay_is_rejected_without_duplicate_production_record(self):
        self.complete()
        with self.assertRaisesRegex(ProductionError, "already recorded"):
            self.complete()
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM print_records"), 1)

    def test_05_photo_and_video_evidence_references_are_hashed_and_immutable(self):
        record = self.complete()
        photo = Path(self.temp.name) / "tweety.jpg"
        photo.write_bytes(b"verified photo bytes")
        result = self.service.add_evidence(
            record["id"], evidence_type="photo", file_path=str(photo),
            caption="Orange Hat inspection",
        )
        self.assertEqual(len(result["sha256"]), 64)
        db = connect(self.database)
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE print_evidence SET caption='changed' WHERE id=?", (result["id"],))
        db.close()

    def test_06_poof_chute_backup_is_a_permanent_maintenance_event(self):
        record = self.complete()
        event = self.service.log_maintenance(
            event_type="poop_chute_backup", summary="Poop chute backed up",
            details="Cleared accumulated purge waste and verified free movement.",
            severity="warning", occurred_at="2026-07-26T09:15:00-04:00",
            printer_id=self.printer_id, related_print_id=record["id"],
        )
        self.assertEqual(event["event_number"], "THS-MNT-000001")
        db = connect(self.database)
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("DELETE FROM maintenance_events WHERE id=?", (event["id"],))
        db.close()

    def test_07_progress_never_invents_percentage_for_stage_or_unknown(self):
        self.service.update_project_progress(
            self.project_id, mode="stage", stage="Plate 1 inspected",
            note="Orange Hat accepted with defect.",
        )
        self.assertEqual(
            self.scalar("SELECT progress_stage FROM projects WHERE id=?", (self.project_id,)),
            "Plate 1 inspected",
        )
        with self.assertRaisesRegex(ProductionError, "cannot claim"):
            self.service.update_project_progress(
                self.project_id, mode="unknown", percent=50
            )

    def test_08_audit_mode_is_read_only_and_history_is_database_immutable(self):
        self.complete()
        before = self.scalar("SELECT COUNT(*) FROM audit_events")
        history = ProductionService.audit_history(self.database)
        self.assertEqual(len(history), before)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM audit_events"), before)
        db = connect(self.database)
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("DELETE FROM audit_events")
        db.close()

    def test_09_registry_completion_maintenance_projects_and_audit_are_real_routes(self):
        app = InventoryWebApp(self.database)
        for path, text in (
            ("/prints", "Print Registry"),
            ("/prints/complete", "Record Print Completion"),
            ("/maintenance", "Maintenance Backlog"),
            ("/projects", "Project Progress"),
            ("/audit", "Audit Mode"),
        ):
            status, _, body = app.response(path)
            self.assertEqual(status, 200)
            self.assertIn(text, body.decode())

    def test_10_completion_route_records_tweety_with_explicit_confirmation(self):
        app = InventoryWebApp(self.database)
        status, _, page = app.response(
            "/prints/complete", method="POST", form={
                "job_name": "Tweety Plate 1", "plate_name": "Plate 1",
                "part_name": "Orange Hat", "quantity": "1",
                "printer_id": str(self.printer_id), "project_id": str(self.project_id),
                "completed_at": "2026-07-26T09:00:00-04:00",
                "inspection_status": "accepted_with_defect",
                "defect_notes": "Minor visible flaw accepted for shop use.",
                "actor": "Cowboy", "confirm": "complete-print",
            },
        )
        self.assertEqual(status, 201)
        self.assertIn("THS-PRT-000001", page.decode())


if __name__ == "__main__":
    unittest.main()
