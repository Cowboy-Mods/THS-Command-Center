# Migration 019 Production Deployment Readiness

Status: **ready for explicit deployment authorization — not deployed**

Prepared: 2026-07-28

Source checkpoint:
`3db8e14aa1296692b6985510beead7500e395004`

Branch: `feature/filament-manager-v1`

## Authorized physical truth retained for the later correction

Cowboy physically verified:

- `THS-FIL-000039` is in AMS 2 Slot 1.
- `THS-FIL-000032` is removed and belongs at Open-Spool Wall.
- Both physical labels match their recorded products and colors.
- Neither spool is empty.
- AMS 1 Slot 4 is physically empty and should remain empty.
- Remaining weights must remain unchanged.

These confirmations authorize preparation only. Migration 019 does not change
either spool, and the spool correction remains a separate post-migration
checkpoint.

## Production read-only baseline

Database:
`C:\Users\Cowboy\Documents\THS-Command-Center-Data\inventory.sqlite3`

| Check | Verified result |
|---|---|
| File size | 1,077,248 bytes |
| SHA-256 | `3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A` |
| Migration count | 18 |
| Latest migration | `018_equipment_registry_v1.sql` |
| Integrity check | `ok` |
| Quick check | `ok` |
| Foreign-key violations | 0 |
| Flexible workflow rows | 0 |
| Equipment Registry rows | 1 |
| Equipment telemetry rows | 0 |
| Port 8787 listener | None |
| SQLite WAL/SHM sidecars | None |

Production was inspected with SQLite immutable/read-only access and
`PRAGMA query_only=ON`. Its checksum remained unchanged.

The only source migration not recorded in production is:
`019_flexible_spool_replacement.sql`.

Migration file evidence:

- file length: 5,366 bytes;
- SHA-256:
  `B6B142B45B61B302B76B1BF6574FA8E5E28CFD54F1221274A4C21482831E0FFF`;
- Git blob:
  `3bd5730b4fccd32b9441084c35459ab7425f56a2`.

## Verified rollback backup

External backup:

`C:\Users\Cowboy\Documents\THS-Command-Center-Data\backups\migration-019-readiness\inventory-schema18-pre-migration019-20260728T173212-0400.sqlite3`

| Check | Result |
|---|---|
| Stored outside Git | Yes |
| File size | 1,077,248 bytes |
| SHA-256 | `3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A` |
| Byte-match to production baseline | Yes |
| Schema | 18 |
| Latest migration | `018_equipment_registry_v1.sql` |
| Integrity / quick check | `ok` / `ok` |
| Foreign-key violations | 0 |
| Protected fingerprints | Exact production-baseline match |

This backup is valid only while the production checksum remains the baseline
hash above. If production changes before deployment, stop: this readiness
checkpoint is stale and a new backup and rehearsal are required.

## Production-copy migration rehearsal

Disposable candidate source copy SHA-256:
`3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A`

The candidate was an exact byte copy of the production baseline. Migration 019
was applied to the candidate only.

| Check | Candidate result |
|---|---|
| Pending before | Only `019_flexible_spool_replacement.sql` |
| Pending after | None |
| Migration count | 19 |
| Latest migration | `019_flexible_spool_replacement.sql` |
| Candidate after SHA-256 | `D8E2F7FEA567481CEF6E49DB23B7020515AFBC1138EC8A140893F02744827261` |
| Candidate after size | 1,097,728 bytes |
| Integrity / quick check | `ok` / `ok` |
| Foreign-key violations | 0 |
| Protected tables fingerprinted | 75 |
| Protected tables with changed row content | 0 |
| Existing workflow rows | 0, unchanged |
| Equipment Registry rows | 1, unchanged |
| Equipment telemetry rows | 0, unchanged |
| `THS-FIL-000032` | Entire record and assignment unchanged |
| `THS-FIL-000039` | Entire record and assignment unchanged |

The candidate after-hash is rehearsal evidence, not a required production
after-hash. SQLite timestamps and file-layout details can make a valid migrated
file hash differ. Production acceptance is based on the exact migration list,
schema, integrity, protected-content fingerprints, and expected schema-only
changes.

The disposable candidate and restore-rehearsal copies were securely removed
from the working output area after validation. The verified external rollback
backup was preserved.

## Rollback rehearsal

A new restore target was created from the external backup after the candidate
migration rehearsal.

| Check | Restored result |
|---|---|
| SHA-256 | `3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A` |
| Exact baseline byte-match | Yes |
| Schema | 18 |
| Latest migration | `018_equipment_registry_v1.sql` |
| Integrity / quick check | `ok` / `ok` |
| Foreign-key violations | 0 |
| Protected fingerprints | Exact baseline match |
| Equipment / telemetry rows | 1 / 0 |
| Workflow rows | 0 |

This proves the stored backup is readable and can reproduce the verified
pre-migration database without changing production.

## Exact production deployment plan

No step below is authorized by this document. After explicit deployment
authorization:

1. Stop the THS Command Center process and confirm no listener owns port 8787.
2. Confirm no process holds the production database and no WAL/SHM sidecar
   exists.
3. Reopen production read-only and record:
   file size, SHA-256, migration list, integrity, quick check, foreign keys,
   all 75 protected fingerprints, target-spool snapshots, and protected counts.
4. Require the production SHA-256 to remain
   `3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A`.
   Any mismatch stops deployment and requires a refreshed readiness checkpoint.
5. Re-hash and revalidate the external rollback backup. Its hash must exactly
   match the production pre-deployment hash.
6. Create a fresh disposable production copy, confirm its hash, and repeat the
   Migration 019 rehearsal. Any difference stops deployment.
7. Confirm the repository is on `feature/filament-manager-v1`, clean,
   synchronized, and contains the approved Migration 019 file hash above.
8. Open the production database through the official migration boundary with
   foreign-key enforcement enabled.
9. Verify the only pending migration is
   `019_flexible_spool_replacement.sql`.
10. Apply exactly Migration 019. Do not invoke any equipment, receiving,
    replacement, correction, or inventory action.
11. Record `019_flexible_spool_replacement.sql` in `schema_migrations` through
    the official migrator and close the connection.
12. Do not start the spool-correction workflow during this checkpoint.

## Exact post-deployment validation plan

Before the application is returned to normal use:

1. Record the production after-checksum and size.
2. Confirm migration count 19 and latest migration
   `019_flexible_spool_replacement.sql`.
3. Confirm no other migration was applied and no migration remains pending.
4. Confirm `PRAGMA integrity_check` and `PRAGMA quick_check` return `ok`.
5. Confirm `PRAGMA foreign_key_check` returns zero rows.
6. Confirm the rebuilt `inventory_workflow_transactions` table contains:
   all legacy fields; nullable legacy replacement/destination fields; all eight
   explicit disposition/source/destination fields; restrictive foreign keys;
   contradictory-combination checks; and immutable update/delete triggers.
7. Compare all 75 protected table fingerprints to the pre-deployment baseline.
   Expected changed row content: none.
8. Confirm all pre-existing workflow rows and action links remain byte-for-byte
   equivalent in their legacy fields. Current production expectation is zero
   workflow rows.
9. Confirm zero new workflow, transaction, transaction-line, action,
   assignment, equipment, or telemetry rows.
10. Confirm every field and active assignment for `THS-FIL-000032` and
    `THS-FIL-000039` remains unchanged.
11. Confirm purchases, receiving, inventory, equipment, maintenance,
    production, and dashboard source data remain unchanged.
12. Run the focused Migration 019, flexible-service, guided-UI, and correction
    preview suites.
13. Run the full regression suite.
14. Start the normal application, then verify dashboard and core workflow
    routes return HTTP 200 without performing writes.
15. Confirm production remains schema 19, integrity remains `ok`, foreign keys
    remain clean, and Git remains clean and synchronized.
16. Produce the Production Migration 019 Validation Report and stop. The
    spool correction still requires its separately authorized application
    checkpoint.

## Rollback procedure if deployment validation fails

Rollback is safe only before the spool correction or any later production write.

1. Stop the application and keep port 8787 closed.
2. Do not delete the failed migrated database. Move it to a uniquely named
   incident-evidence path outside Git and record its checksum.
3. Re-hash the rollback backup and require
   `3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A`.
4. Copy that exact backup to a new restore candidate.
5. Validate the restore candidate read-only: schema 18, latest Migration 018,
   integrity and quick check `ok`, zero foreign-key violations, exact protected
   fingerprints, and exact target-spool snapshots.
6. Only after those checks, replace the stopped production database with the
   verified restore candidate.
7. Reopen restored production read-only and repeat the same checks.
8. Start the application and verify dashboard/core-route health.
9. Preserve the failed migrated file and produce an incident/rollback report.

Do not use this schema-18 backup after any successful schema-19 inventory write;
doing so would discard later immutable history. A logical correction after
later writes must use a new audited workflow rather than restoring this backup.

## Test gate

The readiness checkpoint requires:

- Migration 019 schema tests;
- flexible replacement service tests;
- guided flexible replacement UI tests;
- spool-correction preview tests;
- full regression suite.

Final results are recorded in the checkpoint commit after all runs complete.

Verified results:

- focused Migration 019/service/UI/correction-preview gate:
  34 passed in 65.170 seconds;
- full regression suite: 321 passed in 632.539 seconds;
- final production and rollback-backup SHA-256 remained identical at
  `3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A`.

## Boundary

Migration 019 was not applied to production. No spool correction was applied.
Production remains schema 18. Main, purple-color logic, and AMS onboarding were
not touched.
