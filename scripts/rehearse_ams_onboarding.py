from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from inventory.ams_onboarding import AMSOnboardingError, AMSOnboardingService


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def rehearse(source: Path) -> dict:
    if not source.is_file():
        raise ValueError("source database was not found")
    source_hash = sha256(source)
    rollback_results = []
    with tempfile.TemporaryDirectory(prefix="ths-ams-onboarding-rehearsal-") as temp:
        root = Path(temp)
        dry_run_copy = root / "dry-run.sqlite3"
        shutil.copy2(source, dry_run_copy)
        preview = AMSOnboardingService(dry_run_copy).preview()
        if sha256(dry_run_copy) != source_hash:
            raise AssertionError("dry-run changed its disposable database")

        for stage in range(1, 32):
            candidate = root / f"rollback-{stage:02d}.sqlite3"
            shutil.copy2(source, candidate)
            service = AMSOnboardingService(candidate)
            try:
                service.commit(
                    confirmation=service.CONFIRMATION_PHRASE,
                    _fail_after_write=stage,
                )
            except AMSOnboardingError as exc:
                if f"write {stage}" not in str(exc):
                    raise
            else:
                raise AssertionError(f"rollback stage {stage} did not fail")
            restored = sha256(candidate)
            if restored != source_hash:
                raise AssertionError(
                    f"rollback stage {stage} checksum differs from source"
                )
            rollback_results.append({"stage": stage, "sha256": restored})

        success_copy = root / "success.sqlite3"
        shutil.copy2(source, success_copy)
        result = AMSOnboardingService(success_copy).commit(
            confirmation=AMSOnboardingService.CONFIRMATION_PHRASE
        )
        db = sqlite3.connect(success_copy)
        integrity = db.execute("PRAGMA quick_check").fetchone()[0]
        foreign_keys = len(db.execute("PRAGMA foreign_key_check").fetchall())
        db.close()

    return {
        "source": str(source.resolve()),
        "source_sha256": source_hash,
        "dry_run": {
            "insert_count": preview["insert_count"],
            "update_count": preview["update_count"],
            "delete_count": preview["delete_count"],
            "sha256": preview["sha256_after"],
        },
        "rollback_stage_count": len(rollback_results),
        "rollback_first_stage": rollback_results[0],
        "rollback_last_stage": rollback_results[-1],
        "all_rollback_checksums_restored": all(
            row["sha256"] == source_hash for row in rollback_results
        ),
        "success": {
            "insert_count": result["insert_count"],
            "update_count": result["update_count"],
            "delete_count": result["delete_count"],
            "integrity": integrity,
            "foreign_key_violations": foreign_keys,
        },
        "temporary_copies_removed": True,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Rehearse the atomic AMS onboarding on disposable copies."
    )
    parser.add_argument("source_database", type=Path)
    args = parser.parse_args()
    print(json.dumps(rehearse(args.source_database), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
