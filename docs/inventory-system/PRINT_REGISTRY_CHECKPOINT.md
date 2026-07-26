# Print Registry / Print Completion Checkpoint

Stage 2 adds a shop-first production record without coupling the shared core to
Cowboy's printer, project names, or evidence folders.

## Included

- Permanent `THS-PRT-######` print identities.
- Completed-print inspection results: Accepted, Accepted with Defect, and Rejected.
- Required defect notes for Accepted with Defect.
- Honest completion-time accuracy: Exact, Estimated, or Unknown.
- Photo and video evidence references with SHA-256 byte identity.
- Permanent `THS-MNT-######` maintenance events, including poop-chute backups.
- Honest project progress modes: Exact, Estimated, Stage, or Unknown.
- Read-only Audit Mode backed by database-immutable audit history.

Evidence files remain outside SQLite. The registry stores an absolute path,
media type, caption, capture time, and SHA-256 so moved or altered evidence can
be detected.

## Live database safety checkpoint

Do not run a normal migration first. From the permanent checkout, validate a
copy of the runtime database:

```powershell
py -3 -m inventory.checkpoint --database "$env:USERPROFILE\Documents\THS-Command-Center-Data\inventory.sqlite3"
```

The dry run opens the source immutably, runs SQLite integrity checks, copies the
database to a temporary directory, verifies the copy hash, applies migrations
only to that candidate, and proves existing operational row counts did not
change.

Only after the dry run reports `SAFE DRY RUN`, apply the checkpoint:

```powershell
py -3 -m inventory.checkpoint `
  --database "$env:USERPROFILE\Documents\THS-Command-Center-Data\inventory.sqlite3" `
  --backup-directory "$env:USERPROFILE\Documents\THS-Command-Center-Data\backups" `
  --apply
```

Apply mode repeats the dry run, creates a hash-verified pre-Stage-2 backup, then
migrates the runtime database and verifies integrity and protected row counts.
