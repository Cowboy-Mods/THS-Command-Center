import tempfile
import unittest
from pathlib import Path

from inventory.checkpoint import apply_checkpoint, dry_run, sha256, verify_database
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


if __name__ == "__main__":
    unittest.main()
