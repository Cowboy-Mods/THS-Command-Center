# Inventory Feature Merge Readiness

**Checkpoint date:** 2026-07-30

**Feature branch:** `feature/filament-manager-v1`

**Accepted production report commit:** `411a29c2073de0cc01a4961a111149ff0b395d32`

**Production writes during this checkpoint:** zero

**Main changes during this checkpoint:** zero

## Decision

The inventory feature is **source-ready for Cowboy's merge approval**, subject
to the exact merge procedure below. Production acceptance passed, both
supported migration paths passed, the complete test suite passed, and the
feature produces a conflict-free merge tree with the current remote Main.

This is not authorization to merge. Local `main` is one commit behind
`origin/main`; it must be updated to the remote tip before the later approved
merge. The feature will enter Main as a non-fast-forward merge because Main
contains one independent documentation commit.

## Production acceptance

Production was inspected through SQLite read-only URI mode with query-only
enabled. All connections were closed after inspection.

| Check | Accepted result |
|---|---|
| Database | `C:\Users\Cowboy\Documents\THS-Command-Center-Data\inventory.sqlite3` |
| Schema | 19; latest `019_flexible_spool_replacement.sql` |
| SHA-256 before/after inspection | `3A9992C0337A11092780AC9F1B5E43126C03509A1EE749CC21679360DF3CFD28` |
| Integrity check | `ok` |
| Quick check | `ok` |
| Foreign-key violations | 0 |
| Port 8787 | One verified production listener, PID 58064 at inspection time |
| Listener command | Isolated THS bootstrap, explicit external production database, loopback only |
| Route status | `/`, replacement, AMS, and maintenance routes all HTTP 200 |
| Route writes | zero; checksum unchanged |

### Accepted physical and registry state

- Eight existing AMS slots are present.
- Seven active assignments are present and unchanged:
  AMS 1 has `THS-FIL-000040`, empty A2, `THS-FIL-000042`, and
  `THS-FIL-000041`; AMS 2 has `THS-FIL-000039`, `THS-FIL-000023`,
  `THS-FIL-000033`, and `THS-FIL-000022`.
- `THS-EQP-000001` is the Bambu Lab P1S, serial `01P00C511401400`.
- `THS-EQP-000002` is AMS 1, serial `19C06A522002297`.
- `THS-EQP-000003` is AMS 2, serial `19C51A620400EWR`.
- Both AMS units have current `attached_to` relationships to the P1S.
- AMS 1 Slot 2 / A2 is empty, Out of service, and Do not load.
- `THS-MNT-000002` identifies Slot 2 / A2, its loud/locking feeder symptom,
  pending inspection/repair/function test, the candidate feeder, and the
  Slot 4 monitor-during-printing note. Slots 1, 3, and 4 remain usable.
- `THS-PART-000001` exists once: Bambu Lab AMS 2 Pro Feeder Unit,
  `SA403-V1`, UPC `6937285503237`, quantity 1. It remains new/boxed,
  uninstalled, unreserved, unissued, unconsumed, and has a null/unresolved
  storage location.

## Feature-to-Main comparison

At inspection:

- Remote Main: `65982383fc9dccc8f3f3982d7ea3151f70e99234`
- Local Main: `25b62ce448d1c86788dd0a55509afd3144526e68`
- Merge base: `25b62ce448d1c86788dd0a55509afd3144526e68`
- Feature-only commits before this readiness report: 136
- Remote-Main-only commits: 1
- First feature commit:
  `5bbe5ffa964c5bd1e3113ff8b168a488beb111f1`
- Accepted production-report tip:
  `411a29c2073de0cc01a4961a111149ff0b395d32`
- Tested merge-safety cleanup:
  `fe84b28b43e7163f1327a5bcf5eefd40c2590f62`
- Final candidate diff including this report: 123 files, 29,954 insertions,
  16 deletions.
- `git merge-tree --write-tree origin/main HEAD` completed without a conflict.

The exact merge range is the fixed merge base through the pushed feature tip:

```text
25b62ce448d1c86788dd0a55509afd3144526e68..feature/filament-manager-v1
```

For review against the current remote Main, use:

```text
origin/main...feature/filament-manager-v1
```

### Migrations entering Main

All 19 migrations are additive, ordered, and tracked:

`001_inventory_core.sql`, `002_seed_inventory_configuration.sql`,
`003_seed_verified_filament.sql`, `004_enforce_tracking_policies.sql`,
`005_inventory_action_service.sql`, `006_inventory_workflow_transactions.sql`,
`007_verified_ams_initialization.sql`, `008_orders_printer_status.sql`,
`009_print_registry_audit.sql`, `010_print_completion_time_accuracy.sql`,
`011_register_existing_open_spool.sql`, `012_maintenance_registry.sql`,
`013_purchase_registry_foundation.sql`,
`014_purchase_evidence_maintenance_links.sql`,
`015_legacy_order_delivery_evidence.sql`,
`016_legacy_order_receiving_hardening.sql`,
`017_purchase_registry_receiving.sql`,
`018_equipment_registry_v1.sql`, and
`019_flexible_spool_replacement.sql`.

### Source and runtime support entering Main

- Inventory package:
  `actions.py`, `ams_onboarding.py`, `ams_onboarding_preview.py`,
  `catalog_correction.py`, `checkpoint.py`, `cli.py`,
  `correction_preview.py`, `db.py`, `equipment.py`, `health.py`,
  `importer.py`, `initialization.py`, `maintenance.py`, `navigation.py`,
  `open_spool.py`, `order_evidence.py`, `orders.py`, `production.py`,
  `purchase_receiving.py`, `purchases.py`, `queries.py`, `receiving.py`,
  `replacement.py`, `returning.py`, `web.py`, `static/app.js`, and
  `static/style.css`.
- Runtime launch support:
  `Start THS Dashboard.cmd`, `Stop THS Dashboard.cmd`,
  `scripts/ths-dashboard.ps1`, and `scripts/ths_dashboard_bootstrap.py`.
- Controlled rehearsal:
  `scripts/rehearse_ams_onboarding.py`.
- Import template:
  `data/inventory/inventory-import-template.csv`.
- Repository support:
  `.gitignore`, `README.md`, and `inventory/__init__.py`.

`inventory/health.py` and `tests/test_shop_health.py` are the inventory
dashboard's pre-existing shop-readiness projection in this feature history.
They were inspected and tested but not changed during this checkpoint. No
separate health-module data or new health work was mixed into this checkpoint.

### Tests entering Main

`test_actions.py`, `test_ams_onboarding_preview.py`,
`test_ams_onboarding_service.py`, `test_checkpoint.py`,
`test_correction_preview.py`, `test_equipment_registry.py`,
`test_flexible_replacement_service.py`, `test_flexible_replacement_ui.py`,
`test_initialize_ams.py`, `test_inventory.py`, `test_launchers.py`,
`test_legacy_receiving_hardening.py`, `test_maintenance.py`,
`test_migration_019.py`, `test_open_spool.py`,
`test_order_delivery_evidence.py`, `test_orders.py`, `test_production.py`,
`test_purchase_phase2a.py`, `test_purchase_receiving.py`,
`test_purchases.py`, `test_receive_spool.py`, `test_replace_spool.py`,
`test_return_spool.py`, `test_shop_health.py`, `test_web.py`, and
`tests/__init__.py`.

### Documentation entering Main

- Architecture and repository documents:
  `BUILD_LOG.md`, `MAEVE_CONSTITUTION.md`,
  `OPEN_SOURCE_PROJECT_PRINCIPLES.md`, `PRODUCT_ARCHITECTURE.md`,
  `SESSION_HANDOFF.md`, `filament-manager/IMPLEMENTATION_PLAN_V1.md`, and
  `filament-manager/MAEVE_FILAMENT_MANAGER_V1.md`.
- Inventory documentation:
  `AMS_2_PRO_ONBOARDING_PREVIEW.md`,
  `AMS_ATOMIC_ONBOARDING_SERVICE.md`,
  `AMS_PRODUCTION_ONBOARDING_REPORT.md`, `EQUIPMENT_REGISTRY_V1.md`,
  `FILAMENT_032_039_CORRECTION_PREVIEW.md`,
  `FILAMENT_032_039_PRODUCTION_CORRECTION.md`, `FILAMENT_MODULE_V1.md`,
  `FILAMENT_SWATCH_PRODUCTION_DEPLOYMENT.md`,
  `FILAMENT_SWATCH_SOURCE_REPAIR.md`,
  `FLEXIBLE_SPOOL_REPLACEMENT_MIGRATION_019.md`,
  `FLEXIBLE_SPOOL_REPLACEMENT_SERVICE.md`,
  `FLEXIBLE_SPOOL_REPLACEMENT_UI.md`,
  `INITIALIZE_VERIFIED_AMS_STATE.md`, `INVENTORY_ACTION_SERVICE.md`,
  `LEGACY_ORDER_DELIVERY_EVIDENCE.md`,
  `LEGACY_ORDER_RECEIVING_HARDENING.md`, `MAINTENANCE_REGISTRY.md`,
  `MIGRATION_019_PRODUCTION_DEPLOYMENT_READINESS.md`,
  `MIGRATION_019_PRODUCTION_VALIDATION.md`, `ORDERS_AND_RECEIVING.md`,
  `P1S_ONBOARDING_CHECKPOINT_D.md`, `PRINTER_STATUS_FOUNDATION.md`,
  `PRINT_REGISTRY_CHECKPOINT.md`, `PURCHASE_REGISTRY_FOUNDATION.md`,
  `PURCHASE_REGISTRY_PHASE2A.md`, `PURCHASE_REGISTRY_RECEIVING.md`,
  `READ_ONLY_DASHBOARD_V1.md`, `RECEIVE_VERIFIED_SEALED_SPOOL.md`,
  `REGISTER_EXISTING_OPEN_SPOOL.md`, `REPLACE_ACTIVE_FILAMENT_SPOOL.md`,
  `RETURN_AMS_SPOOL_TO_STORAGE.md`, `RUNTIME_DATA_AND_BACKUPS.md`, and
  `THS_INVENTORY_SYSTEM_ARCHITECTURE.md`.

Historical checkpoint reports are intentionally retained as immutable evidence.
They describe the state at their dated boundaries and are not current operating
instructions. `SESSION_HANDOFF.md` is the current-state entry point.

### Production-only records not stored in Git

Git contains schemas, services, tests, and reports—not the live database or its
rows. Production-only state includes:

- all live catalog, spool, location, assignment, transaction, audit, purchase,
  receipt, print, maintenance, equipment, relationship, restriction, bridge,
  part, and provenance rows;
- the P1S and two AMS registry records and their immutable relationships;
- the seven live filament assignments and empty A2 restriction;
- the feeder part and maintenance candidate-part reference;
- production database bytes, SQLite journals, external backups, launcher state,
  and production logs.

None of those runtime artifacts is tracked or copied into this branch.

## Migration compatibility

### Fresh installation

A disposable empty database applied migrations 001 through 019 in order:

- schema 19;
- latest migration 019;
- integrity and quick checks `ok`;
- zero foreign-key violations;
- zero equipment rows and zero telemetry rows.

### Supported production-style upgrade

The verified schema-18 rollback backup with SHA-256
`3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A`
was copied to a disposable location. The source checksum was verified before
copying. The candidate advanced exactly 18 to 19 by applying only Migration
019. Integrity and quick checks remained `ok`, foreign-key violations remained
zero, and all 75 pre-existing table rowsets were preserved on their pre-019
columns. The disposable copy was removed automatically.

## Merge-hygiene audit

### Passed

- No tracked SQLite databases, journals, caches, logs, environment files,
  backups, screenshots, temporary files, or compiled Python files.
- No detected GitHub/OpenAI/AWS keys, private keys, passwords, device access
  codes, or other live credentials in executable source.
- No executable hard-coded `C:\Users\Cowboy` path.
- Production paths use `%USERPROFILE%`, `$env:USERPROFILE`, explicit command
  arguments, or documentation placeholders.
- Tests use temporary directories and disposable databases.
- Ignored working artifacts are limited to Python caches and `var/`.
- The verified launcher pins the checkout, application module, external
  database, PID identity, and sole loopback listener.
- Route acceptance caused zero production writes.
- The feature-wide whitespace scan reports historical blank lines at end of
  file and Markdown hard-line-break spaces. These are non-functional and span
  older checkpoint files; they were not mechanically rewritten in this
  readiness checkpoint because that would create broad, low-value churn.

### Narrow cleanup made in this checkpoint

1. Direct `serve` and `ams-onboard` commands now refuse to run without an
   explicit `--database` path. This closes the accidental checkout-local server
   path that previously allowed duplicate port-8787 processes.
2. Launcher tests prove both controlled commands reject an implicit database.
3. `READ_ONLY_DASHBOARD_V1.md` now uses an explicit disposable development
   database and directs production use to the verified launcher.
4. The stale schema-17/18 session handoff was replaced with the accepted
   schema-19 post-AMS state and current safety boundaries.

No other cleanup was justified. Ignored `__pycache__` directories and `var/`
are generated local artifacts and remain excluded. Historical reports remain
valuable audit evidence and should not be deleted.

## Test results

- Focused launcher, Migration 019, AMS onboarding, Equipment Registry,
  maintenance, flexible-replacement service/UI, and dashboard suite:
  **113 passed**.
- Complete regression suite: **352 passed** in 718.347 seconds.
- Test databases were disposable. Production was not supplied to the tests.

## Exact merge plan

After Cowboy explicitly approves:

1. Reverify production schema 19, integrity, quick check, zero foreign-key
   violations, and exact accepted checksum. Stop on any difference.
2. Confirm `feature/filament-manager-v1` is clean and synchronized at the
   readiness-report commit.
3. Fetch and verify `origin/main`; update local Main to
   `65982383fc9dccc8f3f3982d7ea3151f70e99234` without rewriting history.
4. Re-run the conflict-free merge-tree check against the then-current remote
   Main. Stop if Main moved or any conflict appears.
5. Create a normal merge commit from
   `feature/filament-manager-v1` into Main. Do not squash the checkpoint and
   production-audit history.
6. Run the focused and full suites before pushing Main.
7. Inspect the merge diff and confirm no database/runtime artifacts entered.
8. Push Main only after all gates pass.

## Rollback plan

The merge is source-only and must not migrate or write production.

- Before push: abort the uncommitted merge if any validation fails.
- After push but before deployment: revert the merge commit with a new revert
  commit; do not rewrite shared history.
- If a later source deployment fails: restore the exact previously deployed
  source revision and restart only the verified production launcher. Confirm
  the database checksum did not change.
- Database restoration is not expected for a source-only merge. If a later,
  separately authorized database operation occurs, use its fresh verified
  external backup and that operation's own rollback checkpoint.

## Post-merge validation plan

1. Confirm Main contains the expected merge commit and is clean/synchronized.
2. Repeat fresh-install and schema-18-to-19 disposable migration checks.
3. Run the focused suite and complete regression suite.
4. Re-scan the merged tree for runtime databases, local paths, credentials, and
   generated artifacts.
5. Reverify production read-only: schema, integrity, quick check, foreign keys,
   checksum, eight slots, seven assignments, AMS identities/relationships, A2
   restriction, maintenance record, and feeder state.
6. Check dashboard, replacement, AMS, and maintenance routes; prove all route
   checks are zero-write by matching production checksums before and after.
7. Do not deploy new source or run any production migration merely because the
   Git merge completed. Deployment remains a separate explicit authorization.

## Deferred work

- Physical feeder repair and function test for AMS 1 Slot 2 / A2.
- Any decision to return A2 to service.
- Feeder storage-location confirmation.
- Broader parts reconciliation or a second shelf-spare purchase.
- Printer networking, permanent IP work, Maeve telemetry, and broader health
  work.

Those items are outside this merge checkpoint and remain unauthorized.
