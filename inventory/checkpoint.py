from __future__ import annotations

import argparse
import hashlib
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .db import connect, migrate


CORE_COUNTS = (
    "inventory_instances",
    "inventory_transactions",
    "inventory_actions",
    "ams_assignments",
    "orders",
)


class CheckpointError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(path.resolve().as_posix())}?mode=ro&immutable=1"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    return db


def verify_database(path: Path) -> dict:
    if not path.is_file():
        raise CheckpointError(f"database not found: {path}")
    with closing(readonly(path)) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise CheckpointError(f"database integrity check failed: {integrity}")
        tables = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        missing = [name for name in CORE_COUNTS if name not in tables]
        if missing:
            raise CheckpointError("database is missing core tables: " + ", ".join(missing))
        counts = {
            name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for name in CORE_COUNTS
        }
        migrations = db.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()[0]
    return {
        "sha256": sha256(path), "size": path.stat().st_size,
        "counts": counts, "migrations": migrations,
    }


def dry_run(database: Path) -> dict:
    before = verify_database(database)
    with tempfile.TemporaryDirectory(prefix="ths-stage2-") as folder:
        candidate = Path(folder) / database.name
        shutil.copy2(database, candidate)
        copied_hash = sha256(candidate)
        if copied_hash != before["sha256"]:
            raise CheckpointError("candidate copy hash does not match the source")
        db = connect(candidate)
        applied = migrate(db)
        db.close()
        after = verify_database(candidate)
        if after["counts"] != before["counts"]:
            raise CheckpointError("Stage 2 candidate migration changed existing operational counts")
        if (
            not {"009_print_registry_audit.sql", "010_print_completion_time_accuracy.sql"}
            .intersection(applied)
            and after["migrations"] < 10
        ):
            raise CheckpointError("Stage 2 migration was not applied to the candidate")
        with closing(readonly(candidate)) as db:
            stage2_tables = {
                r[0] for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND "
                    "name IN ('print_records','print_evidence','maintenance_events','audit_events')"
                )
            }
        if len(stage2_tables) != 4:
            raise CheckpointError("candidate is missing Stage 2 tables")
        return {"before": before, "candidate": after, "applied": applied}


def apply_checkpoint(database: Path, backup_directory: Path) -> dict:
    result = dry_run(database)
    backup_directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backup_directory / f"{database.stem}-pre-stage2-{stamp}{database.suffix}"
    shutil.copy2(database, backup)
    if sha256(backup) != result["before"]["sha256"]:
        raise CheckpointError("verified backup hash does not match the live database")
    db = connect(database)
    try:
        applied = migrate(db)
    finally:
        db.close()
    after = verify_database(database)
    if after["counts"] != result["before"]["counts"]:
        raise CheckpointError(
            "live migration completed but existing operational counts changed; preserve the backup"
        )
    return {"backup": str(backup), "applied": applied, "after": after}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Safely validate or apply the Stage 2 database checkpoint.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-directory", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.apply:
            if not args.backup_directory:
                parser.error("--backup-directory is required with --apply")
            result = apply_checkpoint(args.database, args.backup_directory)
            print(f"APPLIED: {', '.join(result['applied']) or 'already current'}")
            print(f"BACKUP: {result['backup']}")
            print(f"SHA256: {result['after']['sha256']}")
        else:
            result = dry_run(args.database)
            print(f"SAFE DRY RUN: {', '.join(result['applied']) or 'already current'}")
            print(f"SOURCE SHA256: {result['before']['sha256']}")
            print(f"CORE COUNTS: {result['before']['counts']}")
        return 0
    except (CheckpointError, sqlite3.DatabaseError, OSError) as exc:
        print(f"STOPPED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
