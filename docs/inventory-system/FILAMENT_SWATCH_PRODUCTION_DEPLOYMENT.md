# Filament Swatch Production Deployment and Validation

Date: 2026-07-29  
Authorized source commit: `8ea3c5c58a7d366a32215065303f1d9e053e2b76`  
Branch: `feature/filament-manager-v1`  
Deployment type: source only; no database migration or production-data write

## Preflight and listener correction

The first deployment attempt stopped without deploying because port 8787 had
two listeners. Cowboy separately authorized stopping only the untracked
listener.

Immediately before that stop, both identities were rebound to their executable,
command line, parent PID, and start time:

| PID | Verified identity | Result |
|---:|---|---|
| 15960 | Untracked `python -m inventory.cli serve --host 127.0.0.1 --port 8787`, with no explicit database | Stopped without force |
| 37188 | Verified bootstrap with the explicit production database | Left running and undisturbed during cleanup |

PID 15960 terminated. Port 8787 then had exactly one listener, PID 37188.

The complete preflight was rerun:

- source HEAD and upstream:
  `8ea3c5c58a7d366a32215065303f1d9e053e2b76`;
- branch: `feature/filament-manager-v1`;
- working tree: clean;
- exact previous source commit:
  `1580d3b0961bce7449328ff4b7f0205a86bd2c4a`;
- schema: 19, latest migration `019_flexible_spool_replacement.sql`;
- SQLite quick check: `ok`;
- foreign-key violations: 0;
- production SHA-256:
  `2C5B3EF08BA222793B494E4B601C44FA88AA34C7CBA24331050C0BB70F90671C`;
- dashboard and guided replacement routes: HTTP 200;
- route-check database checksum: unchanged.

Every gate passed before deployment.

## Source-only deployment

The verified PID 37188 was stopped using the safety-checked production process
record. The approved permanent checkout was already at the authorized source
commit, so no source copying, branch movement, migration, or database mutation
was required.

The dashboard was restarted using the verified bootstrap and the explicit
production database:

```text
python -I scripts/ths_dashboard_bootstrap.py
  --database C:\Users\Cowboy\Documents\THS-Command-Center-Data\inventory.sqlite3
  serve --host 127.0.0.1 --port 8787
```

The migration command was deliberately skipped. The new sole production
listener is PID 58064. Its external process record identifies:

- project:
  `C:\Users\Cowboy\Documents\GitHub\THS-Command-Center`;
- database:
  `C:\Users\Cowboy\Documents\THS-Command-Center-Data\inventory.sqlite3`;
- application:
  `inventory\__init__.py`;
- source commit:
  `8ea3c5c58a7d366a32215065303f1d9e053e2b76`;
- deployment mode: `source-only-no-migration`.

## Live dashboard validation

The rendered production dashboard showed:

| AMS slot | THS identity | Displayed color | Rendered swatch |
|---|---|---|---|
| AMS 1 Slot 1 | THS-FIL-000040 | purple | `#800080` |
| AMS 1 Slot 3 | THS-FIL-000042 | Hot Pink | `#ef8cab` |
| AMS 1 Slot 4 | THS-FIL-000041 | Cocoa Brown | `#79533a` |

`Black/Purple` resolves to:

```text
linear-gradient(135deg,#24262a 0 50%,#800080 50% 100%)
```

Slot identities and displayed color text remained unchanged; only the swatch
resolution changed.

## Route and database validation

| Check | Result |
|---|---|
| Dashboard `/` | HTTP 200 |
| Guided replacement `/inventory/filament/replace` | HTTP 200 |
| Sole port 8787 listener | PID 58064 |
| Production schema | 19 |
| SQLite quick check | `ok` |
| Foreign-key violations | 0 |
| SHA-256 before deployment | `2C5B3EF08BA222793B494E4B601C44FA88AA34C7CBA24331050C0BB70F90671C` |
| SHA-256 after deployment and route checks | `2C5B3EF08BA222793B494E4B601C44FA88AA34C7CBA24331050C0BB70F90671C` |
| Production database writes | 0 |

No inventory records, assignments, weights, transactions, audit history,
equipment records, AMS onboarding state, health-module state, or schema objects
were modified.

## Test results

All automated tests used disposable temporary databases.

| Suite | Result |
|---|---:|
| Focused dashboard tests | 35 passed |
| Full regression suite | 328 passed |

## Exact rollback

The authorized swatch commit's direct parent is the exact previous deployed
source version:

`1580d3b0961bce7449328ff4b7f0205a86bd2c4a`

If rollback is authorized:

1. Reverify the production database checksum and current sole process identity.
2. Stop the verified dashboard through its external process record.
3. place the checkout at the exact previous commit above;
4. start only the verified bootstrap/server command with the explicit production
   database and no migration command;
5. verify both routes, the sole listener, schema 19, integrity, foreign keys,
   and the unchanged database checksum.

No database rollback is required because this deployment made zero database
changes.

## Boundary

The swatch source repair is deployed and validated. Main was not modified.
Work stops at the completed swatch-repair checkpoint.
