# Dashboard Listener and Desktop Shortcut Repair

Date: 2026-07-31
Branch: `feature/p1s-read-only-telemetry`
Production application PID: `<PRODUCTION_DASHBOARD_PID>`

## Outcome

The obsolete checkout-local dashboard was stopped through its own verified stop
mechanism. Its PowerShell and CMD parents then exited naturally, and its stale
PID marker was removed. PID `<PRODUCTION_DASHBOARD_PID>` remained uninterrupted and became the sole
listener on `127.0.0.1:8787`.

The two Desktop shortcuts now resolve only to the permanent checkout:

- `<REPOSITORY_ROOT>/Start THS Dashboard.cmd`
- `<REPOSITORY_ROOT>/Stop THS Dashboard.cmd`

Neither replacement shortcut was launched during this checkpoint.

## Process revalidation and cleanup

Immediately before termination, the verified chain was:

| PID | Identity | Parent | Database / purpose |
| --- | --- | --- | --- |
| `<OBSOLETE_SERVER_PID>` | `python.exe -m inventory.cli serve --host 127.0.0.1 --port 8787` | `<OBSOLETE_LAUNCHER_PID>` | obsolete worktree `var\inventory.sqlite3`, schema 8 |
| `<OBSOLETE_LAUNCHER_PID>` | obsolete PowerShell launcher | `<OBSOLETE_CMD_PID>` | waited for the obsolete server and managed its PID marker |
| `<OBSOLETE_CMD_PID>` | obsolete `Start THS Dashboard.cmd` | `<PARENT_PID>` | launched by the old Desktop shortcut |
| `<PRODUCTION_DASHBOARD_PID>` | isolated permanent-checkout bootstrap with explicit `--database` | `<PRODUCTION_PARENT_PID>` | production schema-19 database |

Both Python processes were independently proven to have listener handles for
port 8787. The obsolete server was stopped only after executable, command line,
parent chain, worktree, database, PID, and recorded process start time matched.
The obsolete launcher and command processes exited naturally. Production PID
`<PRODUCTION_DASHBOARD_PID>` was never
stopped, restarted, or signaled.

The recurring launch source was the obsolete Desktop Start shortcut. The prior
read-only inspection found no matching Windows service, scheduled task, Run-key
entry, or other automatic startup source.

## Recoverable shortcut backup

The original shortcut bytes were copied and hash-verified before replacement:

`<LOCAL_APP_DATA>/shortcut-backups/listener-repair-<TIMESTAMP>`

| Shortcut | Original and backup SHA-256 |
| --- | --- |
| Start | `<START_SHORTCUT_SHA256>` |
| Stop | `<STOP_SHORTCUT_SHA256>` |

Restore by copying those two backed-up `.lnk` files to the Desktop only if the
obsolete launcher is intentionally needed for forensic review. Do not launch
them on production port 8787.

## Source protections

The production launcher continues to require the absolute production database
path supplied by its permanent-checkout CMD wrapper. It refuses an occupied
port before launch. Its Stop action now verifies all of the following before it
can terminate a process:

- PID and process start time;
- executable and permanent project path;
- actual command line, including bootstrap path and absolute database path;
- expected application path;
- ownership of `127.0.0.1:8787`.

The Python HTTP server now uses Windows exclusive-address binding, preventing a
second THS process from sharing the same host and port even if a launch-time
race occurs.

Development use is reserved for port `8788`. Run it only with a disposable,
explicit database:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\ths-dashboard-development.ps1 -DatabasePath C:\absolute\path\to\development.sqlite3
```

The development launcher rejects the production database, rejects missing or
implicit database paths, identifies itself as development, and never uses port
8787.

## Production validation

- database: `<LOCAL_APP_DATA>/inventory.sqlite3`
- schema: 19 (`019_flexible_spool_replacement.sql`)
- integrity check: `ok`
- quick check: `ok`
- foreign-key violations: 0
- SHA-256 before route checks:
  `<PRODUCTION_DATABASE_SHA256>`
- SHA-256 after route checks: identical
- sole listener: PID `<PRODUCTION_DASHBOARD_PID>`, `127.0.0.1:8787`
- HTTP 200: dashboard, guided replacement, AMS, and maintenance routes
- focused launcher/dashboard tests: 46 passed
- complete regression suite: 367 passed in 706.018 seconds

No production database, schema, inventory, equipment, AMS, maintenance, parts,
printer, router, Financial Headquarters, health-module, or Main change was made.

## Rollback

Source rollback is a normal Git revert of this checkpoint commit on the feature
branch. Desktop shortcut rollback uses the verified backup above. The obsolete
schema-8 database and worktree were deliberately preserved. Production requires
no database rollback because its checksum did not change.
