# AMS Atomic Onboarding Service — Source-Only Implementation and Rehearsal

Date: 2026-07-30  
Approved preview baseline:
`63cd0e0dc67bf9976b7c864bdaf2e98a3ed2584a`  
Branch: `feature/filament-manager-v1`  
Mode: source-only; production not modified

## Outcome

The narrow AMS onboarding service and controlled command are implemented.
They encode the approved plan as exactly 29 inserts, 2 updates, and 0 deletes
inside one SQLite `BEGIN IMMEDIATE` transaction.

The service validates the entire approved production state before its first
write, validates the resulting state before commit, and rolls back every child
write if an operation or postcondition fails.

No schema change, production backup, production write, application restart,
additional process termination, physical repair, part consumption, parts
reconciliation, health-module change, or Main change occurred.

## Source

| File | Purpose |
|---|---|
| `inventory/ams_onboarding.py` | Dedicated dry-run and atomic commit service |
| `inventory/cli.py` | Controlled `ams-onboard` command |
| `scripts/rehearse_ams_onboarding.py` | Disposable-copy 31-stage rollback rehearsal |
| `tests/test_ams_onboarding_service.py` | Service, command, rollback, replay, stale-state, duplicate, and protected-data tests |

## Controlled command

The command defaults to a zero-write dry-run:

```powershell
python -m inventory.cli --database <candidate.sqlite3> ams-onboard
```

Commit mode requires both `--commit` and this exact confirmation phrase:

```text
APPLY-AMS-ONBOARDING-29-2-0
```

Example for a disposable candidate only:

```powershell
python -m inventory.cli --database <candidate.sqlite3> ams-onboard --commit --confirm APPLY-AMS-ONBOARDING-29-2-0
```

A missing or incorrect confirmation phrase fails before any database write.
The command never runs migrations; the service requires schema 19 exactly.

## Exact write contract

### Inserts: 29

| Table | Count | Result |
|---|---:|---|
| `equipment_registry` | 2 | `THS-EQP-000002`, `THS-EQP-000003` |
| `equipment_history` | 3 | Two registrations and P1S fact update |
| `audit_events` | 10 | Seven equipment and three candidate-part events |
| `equipment_relationship_state` | 2 | Current `attached_to` relationships |
| `equipment_relationship_history` | 2 | Immutable attach history |
| `equipment_legacy_container_links` | 2 | Existing AMS 1/AMS 2 container bridges |
| `equipment_maintenance_asset_links` | 1 | AMS 1 Registry-to-maintenance link |
| `maintenance_records` | 1 | `THS-MNT-000002` |
| `maintenance_history` | 1 | Immutable `record_fault` action |
| `item_types` | 1 | `Printer Part`, prefix `THS-PART` |
| `catalog_items` | 1 | Bambu Lab AMS 2 Pro Feeder Unit |
| `inventory_instances` | 1 | `THS-PART-000001` |
| `inventory_transactions` | 1 | Immutable `add` transaction |
| `transaction_lines` | 1 | Quantity 1 candidate-part line |
| **Total** | **29** | |

### Updates: 2

Only these statements may affect existing rows:

1. `equipment_registry` row 1 / `THS-EQP-000001`
   - `manufacturer_serial_number`: null to `01P00C511401400`
   - `state_version`: 1 to 2
   - `updated_at`: exact pre-write value to commit time

2. `maintenance_assets` row 2 / legacy AMS 1
   - `readiness_state`: `normal` to `monitor_during_printing`
   - `updated_at`: exact pre-write value to commit time

Each update has a restrictive `WHERE` clause containing the expected current
identity and state. A changed value produces a stale-state failure and full
rollback.

### Deletes: 0

The service contains no delete operation.

## Approved resulting state

- `THS-EQP-000002`: Bambu Lab AMS 2 Pro - AMS 1, serial
  `19C06A522002297`, Installed, Degraded (user-facing Operational with
  restrictions), attached to `THS-EQP-000001`.
- `THS-EQP-000003`: Bambu Lab AMS 2 Pro - AMS 2, serial
  `19C51A620400EWR`, Installed, Operating, attached to
  `THS-EQP-000001`.
- AMS 1 links to maintenance asset 2 with
  `monitor_during_printing` readiness (user-facing Needs service).
- `THS-MNT-000002` scopes the fault and Do-not-load restriction to Slot 2/A2.
- Slot 2/A2 stays empty. Slots 1, 3, and 4 remain usable.
- Slot 4 retains its historical rewind-monitoring note.
- AMS 2 has no new maintenance link, so Registry readiness remains Unknown.
- `THS-PART-000001` represents one new/boxed `SA403-V1`, UPC
  `6937285503237`.
- The feeder remains sealed/uninstalled, unreserved, unissued, and unconsumed.
- Its `location_id` is null and its notes state that storage is unresolved.
- No cabinet or other location is created or inferred.

## Preconditions and duplicate protection

Before writes, the service requires:

- exactly schema 19, integrity `ok`, and zero foreign-key violations;
- P1S Registry row 1 with null serial and state version 1;
- maintenance asset row 2 with readiness `normal` and legacy equipment ID 1;
- next permanent equipment IDs `THS-EQP-000002` and `THS-EQP-000003`;
- exact Bambu Lab manufacturer, AMS type/subtype, 3D Printing category, and
  `ea` unit configuration;
- exact existing legacy AMS 1 and AMS 2 containers;
- exactly eight existing slots;
- exactly the seven approved active filament assignments;
- AMS 1 Slot 2/A2 empty.

It rejects:

- duplicate equipment permanent IDs, display names, and serials;
- duplicate relationships and replays;
- duplicate legacy bridges;
- duplicate `THS-MNT-000002`;
- duplicate `THS-PART-000001`;
- any existing feeder match by product name, `SA403-V1`, or UPC;
- duplicate `Printer Part` / `THS-PART` item-type identity;
- an existing AMS 1 maintenance-asset link;
- stale parent, maintenance, slot, or assignment state.

## Atomicity and idempotency

All 31 row operations—29 inserts followed by the two approved updates—run in
one transaction. The service:

1. acquires an immediate write transaction;
2. revalidates every precondition inside that transaction;
3. records every inserted and updated row in a structured result;
4. verifies the exact 29/2/0 count;
5. runs final relationship, maintenance, part, slot, assignment, existing-row,
   protected-table, integrity, and foreign-key checks;
6. commits only if every check passes.

Any exception rolls back. A replay encounters the changed P1S state and
permanent identities and is rejected without adding rows.

## Production-copy rehearsal

Source database inspected read-only:

`C:\Users\Cowboy\Documents\THS-Command-Center-Data\inventory.sqlite3`

Source SHA-256:

`2C5B3EF08BA222793B494E4B601C44FA88AA34C7CBA24331050C0BB70F90671C`

Rehearsal results:

- dry-run candidate: 29 inserts, 2 updates, 0 deletes proposed;
- dry-run checksum unchanged;
- injected failure after each write stage 1 through 31;
- all 31 candidate checksums restored exactly to the source SHA-256;
- injected postcondition failure also restored the original checksum;
- successful disposable candidate: 29 inserts, 2 updates, 0 deletes;
- successful candidate integrity: `ok`;
- successful candidate foreign-key violations: 0;
- all disposable rehearsal copies removed.

The production database was never opened for write by the rehearsal.

## Tests

- Dedicated atomic service and command tests: 11 passed.
- Focused equipment, maintenance, inventory, service, command, preview, and
  legacy AMS suites: 123 passed.
- Full regression suite: 350 passed.

Coverage includes:

- zero-write dry-run;
- exact structured 29/2/0 result;
- all 31 child-stage rollback points;
- postcondition rollback;
- duplicate and replay rejection;
- stale P1S and maintenance update rejection;
- duplicate equipment, serial, relationship, bridge, maintenance, part-ID,
  model, and UPC protection;
- eight unchanged slot rows;
- seven unchanged active assignment rows;
- A2 unchanged empty;
- existing spool/catalog records unchanged;
- final equipment, relationship, maintenance, part, transaction, and audit
  validation;
- CLI default dry-run and exact confirmation gate;
- reusable disposable-copy rehearsal.

## Production boundary

This checkpoint does not authorize production onboarding. Before a later
production commit, reverify the feature commit, clean repository, sole intended
production listener, schema, checksum, integrity, foreign keys, exact preview,
both update targets, all protected fingerprints, and a fresh verified backup.
Then obtain separate explicit production-onboarding authorization.
