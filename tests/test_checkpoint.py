import tempfile
import unittest
from pathlib import Path

from inventory.checkpoint import (
    apply_checkpoint, dry_run, purchase_foundation_dry_run,
    purchase_phase2a_dry_run, sha256, verify_database,
)
from inventory.db import connect, migrate


class StageTwoCheckpointSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "runtime" / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        db.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_01_dry_run_never_changes_source_bytes(self):
        before = sha256(self.database)
        result = dry_run(self.database)
        self.assertEqual(sha256(self.database), before)
        self.assertEqual(result["before"]["counts"], result["candidate"]["counts"])

    def test_02_apply_creates_hash_verified_backup_before_migration(self):
        # Simulate an older runtime database by removing Stage 2 from a fresh copy.
        old = self.root / "old.sqlite3"
        db = connect(old)
        original_migrate = migrate
        from inventory import db as db_module
        migrations = db_module.MIGRATIONS
        db_module.MIGRATIONS = self.root / "older-migrations"
        db_module.MIGRATIONS.mkdir()
        for source in sorted(migrations.glob("*.sql")):
            if source.name < "009_print_registry_audit.sql":
                (db_module.MIGRATIONS / source.name).write_bytes(source.read_bytes())
        try:
            original_migrate(db)
        finally:
            db.close()
            db_module.MIGRATIONS = migrations
        before = verify_database(old)
        result = apply_checkpoint(old, self.root / "backups")
        backup = Path(result["backup"])
        self.assertTrue(backup.is_file())
        self.assertEqual(sha256(backup), before["sha256"])
        self.assertIn("009_print_registry_audit.sql", result["applied"])
        self.assertEqual(result["after"]["counts"], before["counts"])

    def test_03_purchase_foundation_dry_run_preserves_protected_content(self):
        from inventory import db as db_module
        migrations = db_module.MIGRATIONS
        old = self.root / "purchase-pre013.sqlite3"
        db_module.MIGRATIONS = self.root / "pre013-migrations"
        db_module.MIGRATIONS.mkdir()
        for source in sorted(migrations.glob("*.sql")):
            if source.name < "013_purchase_registry_foundation.sql":
                (db_module.MIGRATIONS / source.name).write_bytes(source.read_bytes())
        try:
            db = connect(old)
            migrate(db)
            db.close()
        finally:
            db_module.MIGRATIONS = migrations
        through_013 = self.root / "through-013-migrations"
        through_013.mkdir()
        for source in sorted(migrations.glob("*.sql")):
            if source.name <= "013_purchase_registry_foundation.sql":
                (through_013 / source.name).write_bytes(source.read_bytes())
        db_module.MIGRATIONS = through_013
        try:
            result = purchase_foundation_dry_run(old)
        finally:
            db_module.MIGRATIONS = migrations
        self.assertEqual(result["applied"], ["013_purchase_registry_foundation.sql"])
        self.assertEqual(result["integrity"], "ok")
        self.assertEqual(result["migration_count"], 13)
        self.assertEqual(result["category_count"], 9)
        self.assertFalse(any(result["production_counts"].values()))

    def test_04_purchase_foundation_dry_run_is_idempotent(self):
        result = purchase_foundation_dry_run(self.database)
        self.assertEqual(result["applied"], [])
        self.assertEqual(result["integrity"], "ok")

    def test_05_purchase_phase2a_dry_run_preserves_all_existing_content(self):
        from inventory import db as db_module
        migrations = db_module.MIGRATIONS
        old = self.root / "purchase-pre014.sqlite3"
        db_module.MIGRATIONS = self.root / "pre014-migrations"
        db_module.MIGRATIONS.mkdir()
        for source in sorted(migrations.glob("*.sql")):
            if source.name < "014_purchase_evidence_maintenance_links.sql":
                (db_module.MIGRATIONS / source.name).write_bytes(source.read_bytes())
        try:
            db = connect(old)
            migrate(db)
            db.close()
        finally:
            db_module.MIGRATIONS = migrations
        through_014 = self.root / "through-014-migrations"
        through_014.mkdir()
        for source in sorted(migrations.glob("*.sql")):
            if source.name <= "014_purchase_evidence_maintenance_links.sql":
                (through_014 / source.name).write_bytes(source.read_bytes())
        db_module.MIGRATIONS = through_014
        try:
            result = purchase_phase2a_dry_run(old)
        finally:
            db_module.MIGRATIONS = migrations
        self.assertEqual(
            result["applied"], ["014_purchase_evidence_maintenance_links.sql"]
        )
        self.assertEqual(result["migration_count"], 14)
        self.assertEqual(result["integrity"], "ok")
        self.assertFalse(any(result["new_table_counts"].values()))

    def test_06_purchase_phase2a_dry_run_is_idempotent(self):
        result = purchase_phase2a_dry_run(self.database)
        self.assertEqual(result["applied"], [])
        self.assertEqual(result["integrity"], "ok")


if __name__ == "__main__":
    unittest.main()
