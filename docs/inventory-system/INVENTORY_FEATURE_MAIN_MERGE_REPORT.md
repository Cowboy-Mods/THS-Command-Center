# Inventory Feature Main Merge Report

**Date:** 2026-07-30

**Result:** Inventory feature merged into Main; production unchanged

## Commit record

- Main before update:
  `25b62ce448d1c86788dd0a55509afd3144526e68`
- Remote Main incorporated by fast-forward:
  `65982383fc9dccc8f3f3982d7ea3151f70e99234`
- Remote-only commit inspected:
  `6598238 Update THS_Command_Center_Design_Book.md`
- Approved feature tip:
  `840a05abfdb89608f93f71a2240fd8416b5b7d08`
- Merge commit:
  `874625f549a83d8beb22040ea1e7479e0b64c66f`
- Merge parents, in order:
  `65982383fc9dccc8f3f3982d7ea3151f70e99234` and
  `840a05abfdb89608f93f71a2240fd8416b5b7d08`

The report-publication commit follows the merge commit and changes only this
file. The final pushed Main tip is recorded in the completion response and
remote Git history.

## Updated-Main gate

The one remote-only Main commit changed only
`docs/THS_Command_Center_Design_Book.md`. It added builder-personalization
language and strengthened the requirement that operational restrictions remain
visible. The inventory feature did not modify that file. The commit was
expected, compatible, and incorporated into local Main using fast-forward only.

After the fast-forward:

- local Main and `origin/main` both pointed to `65982383...`;
- the merge base remained
  `25b62ce448d1c86788dd0a55509afd3144526e68`;
- the feature contained 137 commits not in updated Main;
- updated Main contained one independent commit not in the feature;
- the fresh merge-tree check completed without conflicts.

## Exact included feature range

```text
25b62ce448d1c86788dd0a55509afd3144526e68..840a05abfdb89608f93f71a2240fd8416b5b7d08
```

The merge used a normal `--no-ff` merge commit. No commits were squashed,
rebased, amended, force-pushed, or otherwise rewritten. The feature branch was
not deleted.

The merge added the reviewed 123-file inventory candidate: migrations 001
through 019, inventory services and UI, launch support, tests, documentation,
and the final readiness report. It contained 29,954 insertions and 16
deletions relative to the updated Main merge base.

## Pre-merge validation

| Gate | Result |
|---|---|
| Feature tip | Exact approved `840a05a...` |
| Feature synchronization | Clean and equal to `origin/feature/filament-manager-v1` |
| Merge conflict check | Passed |
| Focused inventory suite | 113 passed in 212.012 seconds |
| Complete regression suite | 352 passed in 697.295 seconds |
| Fresh schema migration | 001 through 019; schema 19 |
| Fresh integrity / quick / FK | `ok` / `ok` / 0 |
| Fresh equipment / telemetry rows | 0 / 0 |
| Production-style migration | Exactly schema 18 to 19; only Migration 019 |
| Existing production-style rowsets | 75 of 75 preserved |
| Schema-18 source checksum | `3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A` |

## Post-merge validation on Main

| Gate | Result |
|---|---|
| Complete regression suite | 352 passed in 700.481 seconds |
| Launcher and Migration 019 guard suite | 14 passed in 16.150 seconds |
| Fresh schema migration | 001 through 019; schema 19 |
| Fresh integrity / quick / FK | `ok` / `ok` / 0 |
| Production-style migration | Exactly schema 18 to 19; only Migration 019 |
| Existing production-style rowsets | 75 of 75 preserved |
| `serve` without `--database` | Rejected by tested CLI guard |
| `ams-onboard` without `--database` | Rejected by tested CLI guard |
| Tracked databases/backups/runtime files | 0 |
| Executable secret or credential hits | 0 |
| Executable hard-coded `C:\Users\Cowboy` paths | 0 |

Ignored local test artifacts were limited to `__pycache__` directories and
`var/`; all are excluded from Git. Historical audit and operating documents
intentionally retain 22 occurrences of the verified external production or
backup paths across 14 documentation files. They are evidence and instructions,
not executable hard-coded paths, and were part of the approved readiness diff.

No unexpected files appeared during the merge. No source or data from the
broader health work was edited during this merge procedure. The already
reviewed inventory shop-readiness projection entered Main as part of the
approved feature history.

## Production protection

Production was never opened for write, migrated, restarted, or served by a new
process during the merge.

- Production schema assumption: 19
- Required production SHA-256:
  `3A9992C0337A11092780AC9F1B5E43126C03509A1EE749CC21679360DF3CFD28`
- SHA-256 before merge: exact match
- SHA-256 after local merge and validation: exact match

No inventory, slot, assignment, equipment, maintenance, part, quantity,
transaction, audit, or telemetry record changed.

## Rollback

This was a source-history merge only. No database rollback is required or
authorized.

If a problem is found after the push:

1. Do not force-push or reset shared Main.
2. Revert this report-publication commit if the report should be removed.
3. Revert the merge with a new commit using merge parent 1:

   ```powershell
   git switch main
   git pull --ff-only origin main
   git revert -m 1 874625f549a83d8beb22040ea1e7479e0b64c66f
   ```

4. Run both migration rehearsals and the complete regression suite.
5. Confirm the production checksum remains unchanged.
6. Push the revert normally only after those checks pass.

The feature branch remains available as the immutable reviewed source history.

## Boundary

This merge does not authorize source deployment, a production migration,
physical feeder repair, returning A2 to service, feeder-location invention,
parts reconciliation, printer networking, Maeve telemetry, or any production
data change.
