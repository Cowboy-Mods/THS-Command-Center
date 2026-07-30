# Runtime data and backups

THS Command Center keeps application code and live workshop data separate.

## Permanent locations

- Source code lives in the permanent Git checkout.
- The live inventory database lives at `C:\Users\<you>\Documents\THS-Command-Center-Data\inventory.sqlite3`.
- Timestamped database backups live under `C:\Users\<you>\Documents\THS-Command-Center-Data\backups`.
- The dashboard process record lives under `C:\Users\<you>\Documents\THS-Command-Center-Data\runtime`.

`Start THS Dashboard.cmd` and `Stop THS Dashboard.cmd` explicitly pass the stable database path to the launcher. The dashboard must never fall back to a checkout-relative `var\inventory.sqlite3` for normal operation.

## Safety boundary

Temporary Codex checkouts, snapshots, worktrees, and attachment folders are disposable working areas. They must never be used as permanent runtime storage. A Git pull, branch cleanup, worktree removal, or temporary-folder cleanup can remove them without preserving live inventory history.

Never commit the live database, its backups, SQLite sidecar files, or runtime process records. Before any recovery or relocation:

1. Stop the dashboard.
2. Record the source and destination hashes, sizes, modified times, migration levels, integrity results, and business-record counts.
3. Create timestamped byte-preserving backups.
4. Copy rather than move the verified source.
5. Verify the copied hash and database state before changing a launcher.
6. Keep every source database until the recovery is independently approved.

Inventory actions and transactions are historical records. Recovery must preserve their existing IDs and rows; it must not recreate, edit, or replace them.
