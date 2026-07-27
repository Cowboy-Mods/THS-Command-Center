from __future__ import annotations

import argparse
import hashlib
import json
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

PURCHASE_PROTECTED_TABLES = (
    "orders", "receiving_batches", "order_received_instances",
    "inventory_instances", "stock_lots", "inventory_transactions",
    "transaction_lines", "inventory_actions", "ams_assignments",
    "print_records", "print_evidence", "audit_events",
    "maintenance_records", "maintenance_history", "maintenance_evidence",
    "open_spool_registrations",
)
PURCHASE_PHASE2A_PROTECTED_TABLES = PURCHASE_PROTECTED_TABLES + (
    "purchase_vendors", "purchase_categories", "purchase_orders",
    "purchase_order_lines", "purchase_history",
)
RECEIVING_HARDENING_PROTECTED_TABLES = PURCHASE_PHASE2A_PROTECTED_TABLES + (
    "purchase_evidence", "purchase_maintenance_links",
    "order_delivery_evidence", "order_delivery_evidence_history",
)
PURCHASE_RECEIVING_PROTECTED_TABLES = RECEIVING_HARDENING_PROTECTED_TABLES + (
    "catalog_item_history", "receiving_batch_delivery_evidence",
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


def table_fingerprint(db: sqlite3.Connection, table: str) -> dict:
    quoted = '"' + table.replace('"', '""') + '"'
    rows = [
        list(row) for row in db.execute(f"SELECT * FROM {quoted} ORDER BY rowid")
    ]
    body = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode()
    return {"count": len(rows), "sha256": hashlib.sha256(body).hexdigest()}


def table_fingerprint_columns(
    db: sqlite3.Connection, table: str, excluded: set[str] | None = None,
) -> dict:
    excluded = excluded or set()
    columns = [
        row[1] for row in db.execute(f'PRAGMA table_info("{table}")')
        if row[1] not in excluded
    ]
    quoted = ",".join('"' + name.replace('"', '""') + '"' for name in columns)
    rows = [list(row) for row in db.execute(
        f'SELECT {quoted} FROM "{table}" ORDER BY rowid'
    )]
    body = json.dumps(rows, separators=(",", ":"), default=str).encode()
    return {"count": len(rows), "sha256": hashlib.sha256(body).hexdigest()}


def purchase_foundation_dry_run(database: Path) -> dict:
    """Verify migration 013 on a copy while fingerprinting all protected history."""
    before = verify_database(database)
    with closing(readonly(database)) as db:
        protected_before = {
            table: table_fingerprint(db, table) for table in PURCHASE_PROTECTED_TABLES
        }
    with tempfile.TemporaryDirectory(prefix="ths-purchase-foundation-") as folder:
        candidate = Path(folder) / database.name
        shutil.copy2(database, candidate)
        if sha256(candidate) != before["sha256"]:
            raise CheckpointError("purchase candidate copy hash does not match the source")
        db = connect(candidate)
        try:
            applied = migrate(db)
        finally:
            db.close()
        unexpected = [name for name in applied if name != "013_purchase_registry_foundation.sql"]
        if unexpected:
            raise CheckpointError(
                "purchase checkpoint found unexpected pending migrations: "
                + ", ".join(unexpected)
            )
        with closing(readonly(candidate)) as db:
            protected_after = {
                table: table_fingerprint(db, table) for table in PURCHASE_PROTECTED_TABLES
            }
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            required = {
                "purchase_vendors", "purchase_categories", "purchase_orders",
                "purchase_order_lines", "purchase_history",
            }
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            migration_count = db.execute(
                "SELECT COUNT(*) FROM schema_migrations"
            ).fetchone()[0]
            category_count = db.execute(
                "SELECT COUNT(*) FROM purchase_categories"
            ).fetchone()[0]
            production_counts = {
                table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "purchase_vendors", "purchase_orders",
                    "purchase_order_lines", "purchase_history",
                )
            }
        if protected_after != protected_before:
            raise CheckpointError("purchase migration changed protected operational content")
        if not required.issubset(tables):
            raise CheckpointError("purchase candidate is missing foundation tables")
        if integrity != "ok":
            raise CheckpointError(f"purchase candidate integrity failed: {integrity}")
        if category_count != 9:
            raise CheckpointError("purchase candidate does not contain nine categories")
        if any(production_counts.values()):
            raise CheckpointError("purchase migration unexpectedly created production records")
        if applied and migration_count != before["migrations"] + 1:
            raise CheckpointError("purchase migration did not advance exactly one version")
        return {
            "before": before,
            "applied": applied,
            "migration_count": migration_count,
            "integrity": integrity,
            "category_count": category_count,
            "production_counts": production_counts,
            "protected": protected_after,
        }


def purchase_phase2a_dry_run(database: Path) -> dict:
    """Verify migration 014 on a copy without altering existing operational data."""
    before = verify_database(database)
    with closing(readonly(database)) as db:
        protected_before = {
            table: table_fingerprint(db, table)
            for table in PURCHASE_PHASE2A_PROTECTED_TABLES
        }
    with tempfile.TemporaryDirectory(prefix="ths-purchase-phase2a-") as folder:
        candidate = Path(folder) / database.name
        shutil.copy2(database, candidate)
        if sha256(candidate) != before["sha256"]:
            raise CheckpointError("Phase 2A candidate hash does not match the source")
        db = connect(candidate)
        try:
            applied = migrate(db)
        finally:
            db.close()
        unexpected = [
            name for name in applied
            if name != "014_purchase_evidence_maintenance_links.sql"
        ]
        if unexpected:
            raise CheckpointError(
                "Phase 2A checkpoint found unexpected pending migrations: "
                + ", ".join(unexpected)
            )
        with closing(readonly(candidate)) as db:
            protected_after = {
                table: table_fingerprint(db, table)
                for table in PURCHASE_PHASE2A_PROTECTED_TABLES
            }
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            counts = {
                table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("purchase_evidence", "purchase_maintenance_links")
            }
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            migration_count = db.execute(
                "SELECT COUNT(*) FROM schema_migrations"
            ).fetchone()[0]
        if protected_after != protected_before:
            raise CheckpointError("Phase 2A migration changed protected content")
        if not {"purchase_evidence", "purchase_maintenance_links"}.issubset(tables):
            raise CheckpointError("Phase 2A candidate is missing required tables")
        if any(counts.values()):
            raise CheckpointError("Phase 2A migration created production records")
        if integrity != "ok":
            raise CheckpointError(f"Phase 2A integrity failed: {integrity}")
        if applied and migration_count != before["migrations"] + 1:
            raise CheckpointError("Phase 2A migration did not advance exactly one version")
        return {
            "before": before, "applied": applied,
            "migration_count": migration_count, "integrity": integrity,
            "protected": protected_after, "new_table_counts": counts,
        }


def receiving_hardening_dry_run(database: Path) -> dict:
    """Verify migration 016 on a copy without changing production row content."""
    before = verify_database(database)
    with closing(readonly(database)) as db:
        protected_before = {
            table: table_fingerprint(db, table)
            for table in RECEIVING_HARDENING_PROTECTED_TABLES
            if table not in {"orders", "receiving_batches"}
        }
        order_before = table_fingerprint(db, "orders")
        batch_before = table_fingerprint(db, "receiving_batches")
    with tempfile.TemporaryDirectory(prefix="ths-receiving-hardening-") as folder:
        candidate = Path(folder) / database.name
        shutil.copy2(database, candidate)
        if sha256(candidate) != before["sha256"]:
            raise CheckpointError("receiving-hardening copy hash does not match source")
        db = connect(candidate)
        try:
            applied = migrate(db)
            applied_again = migrate(db)
        finally:
            db.close()
        if any(name != "016_legacy_order_receiving_hardening.sql" for name in applied):
            raise CheckpointError("unexpected pending migration in receiving checkpoint")
        with closing(readonly(candidate)) as db:
            protected_after = {
                table: table_fingerprint(db, table)
                for table in RECEIVING_HARDENING_PROTECTED_TABLES
                if table not in {"orders", "receiving_batches"}
            }
            order_after = table_fingerprint_columns(db, "orders", {
                    "physical_received_date", "physical_received_time",
                    "receipt_time_precision",
                })
            batch_after = table_fingerprint_columns(db, "receiving_batches", {
                "physical_receipt_date", "physical_receipt_time",
                "receipt_time_precision", "recorded_at",
            })
            new_counts = {
                table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("catalog_item_history", "receiving_batch_delivery_evidence")
            }
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
            migration_count = db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        if protected_before != protected_after or order_before != order_after:
            raise CheckpointError("receiving hardening changed protected row content")
        if batch_before != batch_after or any(new_counts.values()):
            raise CheckpointError("receiving hardening created production records")
        if integrity != "ok" or foreign_keys:
            raise CheckpointError("receiving-hardening integrity verification failed")
        if applied and migration_count != before["migrations"] + 1:
            raise CheckpointError("receiving hardening did not advance exactly one version")
        return {
            "before": before, "applied": applied, "applied_again": applied_again,
            "migration_count": migration_count, "integrity": integrity,
            "foreign_key_violations": len(foreign_keys),
            "protected": protected_after, "new_table_counts": new_counts,
        }


def purchase_receiving_dry_run(database: Path) -> dict:
    """Verify migration 017 on a copy without receiving or changing production."""
    before = verify_database(database)
    with closing(readonly(database)) as db:
        protected_before = {
            table: table_fingerprint(db, table)
            for table in PURCHASE_RECEIVING_PROTECTED_TABLES
        }
        purchase_count = db.execute(
            "SELECT COUNT(*) FROM purchase_orders"
        ).fetchone()[0]
    with tempfile.TemporaryDirectory(prefix="ths-purchase-receiving-") as folder:
        candidate = Path(folder) / database.name
        shutil.copy2(database, candidate)
        if sha256(candidate) != before["sha256"]:
            raise CheckpointError(
                "purchase-receiving candidate hash does not match source"
            )
        db = connect(candidate)
        try:
            applied = migrate(db)
            applied_again = migrate(db)
        finally:
            db.close()
        if any(name != "017_purchase_registry_receiving.sql" for name in applied):
            raise CheckpointError(
                "unexpected pending migration in purchase-receiving checkpoint"
            )
        with closing(readonly(candidate)) as db:
            protected_after = {
                table: table_fingerprint(db, table)
                for table in PURCHASE_RECEIVING_PROTECTED_TABLES
            }
            tables = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            required = {
                "purchase_fulfillment_state",
                "purchase_fulfillment_history",
                "purchase_receipts",
                "purchase_receipt_lines",
                "purchase_receipt_evidence",
                "purchase_receipt_inventory_links",
            }
            new_counts = {
                table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in required
            }
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            quick = db.execute("PRAGMA quick_check").fetchone()[0]
            foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
            migration_count = db.execute(
                "SELECT COUNT(*) FROM schema_migrations"
            ).fetchone()[0]
        if protected_before != protected_after:
            raise CheckpointError(
                "purchase-receiving migration changed protected content"
            )
        if not required.issubset(tables):
            raise CheckpointError(
                "purchase-receiving candidate is missing required tables"
            )
        if new_counts["purchase_fulfillment_state"] != purchase_count:
            raise CheckpointError(
                "purchase-receiving projection count does not match purchases"
            )
        receipt_tables = set(required) - {"purchase_fulfillment_state"}
        if any(new_counts[table] for table in receipt_tables):
            raise CheckpointError(
                "purchase-receiving migration created receipt or history records"
            )
        if integrity != "ok" or quick != "ok" or foreign_keys:
            raise CheckpointError(
                "purchase-receiving candidate integrity verification failed"
            )
        if applied and migration_count != before["migrations"] + 1:
            raise CheckpointError(
                "purchase-receiving migration did not advance exactly one version"
            )
        return {
            "before": before,
            "applied": applied,
            "applied_again": applied_again,
            "migration_count": migration_count,
            "integrity": integrity,
            "quick_check": quick,
            "foreign_key_violations": len(foreign_keys),
            "protected": protected_after,
            "new_table_counts": new_counts,
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
    parser.add_argument(
        "--purchase-receiving-preview", action="store_true",
        help="validate only migration 017 against a temporary copy",
    )
    args = parser.parse_args(argv)
    try:
        if args.purchase_receiving_preview:
            if args.apply:
                parser.error("--purchase-receiving-preview cannot be combined with --apply")
            result = purchase_receiving_dry_run(args.database)
            print(
                "SAFE PURCHASE RECEIVING PREVIEW: "
                + (", ".join(result["applied"]) or "already current")
            )
            print(f"SOURCE SHA256: {result['before']['sha256']}")
            print(f"MIGRATIONS: {result['before']['migrations']} -> {result['migration_count']}")
            print(f"NEW TABLE COUNTS: {result['new_table_counts']}")
        elif args.apply:
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
