# AMS Production Onboarding Report

Date: 2026-07-30  
Authorized source commit:
`5461fe83346fb785fcca5933f9a875bc2717b4c7`  
Branch: `feature/filament-manager-v1`  
Production schema: 19

## Outcome

The controlled atomic service onboarded both Bambu Lab AMS 2 Pro units and
the verified boxed Slot 2 feeder candidate into production.

The committed operation was exactly:

- 29 inserted rows;
- 2 updated rows;
- 0 deleted rows.

The service returned success after its internal postconditions passed. SQLite
integrity is `ok`, foreign-key violations are zero, all unrelated protected
tables are unchanged, and the eight legacy slots and seven active filament
assignments are byte-for-byte identical to the verified pre-onboarding backup.

No physical repair, A2 return-to-service action, feeder consumption,
reservation, issue, installation, storage-location creation, second-feeder
order, parts reconciliation, schema change, health-module change, or Main
change occurred.

## Preflight

| Gate | Result |
|---|---|
| Repository | Clean and synchronized |
| Source commit | `5461fe83346fb785fcca5933f9a875bc2717b4c7` |
| Port 8787 listeners | Exactly one |
| Listener | PID 58064, verified isolated production bootstrap |
| Database argument | Explicit production path |
| Schema | Exactly 19 |
| Latest migration | `019_flexible_spool_replacement.sql` |
| Integrity | `ok` |
| Foreign-key violations | 0 |
| Pre-onboarding SHA-256 | `2C5B3EF08BA222793B494E4B601C44FA88AA34C7CBA24331050C0BB70F90671C` |
| Dry-run | 29 inserts, 2 updates, 0 deletes |
| Dry-run writes | 0 |
| Existing slots | 8 |
| Active assignments | 7 |
| A2 | Empty |
| Service readiness | `production_ready: true` |

The listener was identified from current operating-system state and its live
command line, not a previously recorded PID. No untracked or duplicate server
was present. No process was stopped or restarted.

## Fresh rollback backup

Path:

`C:\Users\Cowboy\Documents\THS-Command-Center-Data\backups\ams-onboarding\inventory-schema19-pre-ams-onboarding-20260730T041902-0400.sqlite3`

Verification:

- SHA-256:
  `2C5B3EF08BA222793B494E4B601C44FA88AA34C7CBA24331050C0BB70F90671C`;
- byte-identical to pre-onboarding production;
- schema 19;
- latest migration `019_flexible_spool_replacement.sql`;
- integrity `ok`;
- foreign-key violations 0;
- opened successfully in read-only mode.

An initial filename containing a colon was rejected by Windows before any file
copy occurred. The successful backup uses a Windows-safe `-0400` offset.

## Commit command

The controlled command used the exact required phrase:

```text
APPLY-AMS-ONBOARDING-29-2-0
```

Commit time recorded by the service:

`2026-07-30T08:19:48Z`

## Exact inserted rows

| # | Table | Row ID | Human identity / action |
|---:|---|---:|---|
| 1 | `equipment_registry` | 2 | `THS-EQP-000002` |
| 2 | `equipment_history` | 2 | `THS-EQP-000002` / register |
| 3 | `audit_events` | 3 | `THS-EQP-000002` / register equipment |
| 4 | `equipment_relationship_state` | 2 | `THS-EQP-000002` attached to P1S |
| 5 | `equipment_relationship_history` | 1 | `THS-EQP-000002` / attach |
| 6 | `audit_events` | 4 | `THS-EQP-000002` / attach relationship |
| 7 | `equipment_legacy_container_links` | 2 | `THS-EQP-000002` to legacy AMS 1 |
| 8 | `audit_events` | 5 | `THS-EQP-000002` / legacy bridge |
| 9 | `equipment_registry` | 3 | `THS-EQP-000003` |
| 10 | `equipment_history` | 3 | `THS-EQP-000003` / register |
| 11 | `audit_events` | 6 | `THS-EQP-000003` / register equipment |
| 12 | `equipment_relationship_state` | 3 | `THS-EQP-000003` attached to P1S |
| 13 | `equipment_relationship_history` | 2 | `THS-EQP-000003` / attach |
| 14 | `audit_events` | 7 | `THS-EQP-000003` / attach relationship |
| 15 | `equipment_legacy_container_links` | 3 | `THS-EQP-000003` to legacy AMS 2 |
| 16 | `audit_events` | 8 | `THS-EQP-000003` / legacy bridge |
| 17 | `equipment_history` | 4 | `THS-EQP-000001` / update facts |
| 18 | `audit_events` | 9 | `THS-EQP-000001` / update equipment facts |
| 19 | `equipment_maintenance_asset_links` | 2 | `THS-EQP-000002` to maintenance asset 2 |
| 20 | `maintenance_records` | 2 | `THS-MNT-000002` |
| 21 | `maintenance_history` | 2 | `THS-MNT-000002` / record fault |
| 22 | `item_types` | 2 | Printer Part / `THS-PART` |
| 23 | `audit_events` | 10 | Create Printer Part item type |
| 24 | `catalog_items` | 26 | Bambu Lab AMS 2 Pro Feeder Unit |
| 25 | `audit_events` | 11 | Create feeder catalog item |
| 26 | `inventory_instances` | 43 | `THS-PART-000001` |
| 27 | `inventory_transactions` | 31 | `THS-PART-000001` / add |
| 28 | `transaction_lines` | 31 | `THS-PART-000001`, quantity 1 |
| 29 | `audit_events` | 12 | `THS-PART-000001` / add individual instance |

The independent backup comparison confirmed these table-count increases total
exactly 29.

## Exact updated rows

### `equipment_registry` row 1 — `THS-EQP-000001`

| Field | Before | After |
|---|---|---|
| `manufacturer_serial_number` | null | `01P00C511401400` |
| `state_version` | 1 | 2 |
| `updated_at` | `2026-07-28 00:57:50` | `2026-07-30T08:19:48Z` |

### `maintenance_assets` row 2 — AMS 1

| Field | Before | After |
|---|---|---|
| `readiness_state` | `normal` | `monitor_during_printing` |
| `updated_at` | `2026-07-26 14:54:11` | `2026-07-30T08:19:48Z` |

No other existing row or field changed.

## Final Equipment Registry state

| Equipment | Serial | Lifecycle | Operational state | Parent |
|---|---|---|---|---|
| `THS-EQP-000001` Bambu Lab P1S | `01P00C511401400` | Installed | Operating | None |
| `THS-EQP-000002` Bambu Lab AMS 2 Pro - AMS 1 | `19C06A522002297` | Installed | Degraded / Operational with restrictions | `THS-EQP-000001`, `attached_to` |
| `THS-EQP-000003` Bambu Lab AMS 2 Pro - AMS 2 | `19C51A620400EWR` | Installed | Operating | `THS-EQP-000001`, `attached_to` |

Both relationship state rows are version 1 and have immutable attach-history
rows. Both Registry AMS records bridge to their existing legacy containers.
AMS 2 has no maintenance link, so its Registry readiness remains Unknown.

## Slots and filament assignments

All eight existing `equipment_slots` rows are unchanged. All seven existing
`ams_assignments` rows are unchanged.

| Slot | Assignment after onboarding |
|---|---|
| AMS 1 Slot 1 / A1 | `THS-FIL-000040` |
| AMS 1 Slot 2 / A2 | Empty |
| AMS 1 Slot 3 / A3 | `THS-FIL-000042` |
| AMS 1 Slot 4 / A4 | `THS-FIL-000041` |
| AMS 2 Slot 1 / B1 | `THS-FIL-000039` |
| AMS 2 Slot 2 / B2 | `THS-FIL-000023` |
| AMS 2 Slot 3 / B3 | `THS-FIL-000033` |
| AMS 2 Slot 4 / B4 | `THS-FIL-000022` |

A2 remains empty. No slot was created, deleted, renumbered, or updated. No
filament identity, assignment, color, weight, quantity, or prior transaction
was changed.

## AMS 1 maintenance state

`THS-MNT-000002` is in progress with High severity.

- affected component: Slot 2/A2;
- symptom: feeder/roller becomes loud and may lock;
- restriction: Out of service — do not load filament;
- required action: inspect, replace feeder if appropriate, and function-test
  before returning A2 to service;
- Slots 1, 3, and 4 remain usable;
- Slot 4 remains in service with its historical fast-rewind monitoring note;
- readiness: `monitor_during_printing` / user-facing Needs service;
- `parts_used`: null.

## Feeder candidate

Exactly one `THS-PART-000001` exists:

| Field | Value |
|---|---|
| Product | Bambu Lab AMS 2 Pro Feeder Unit |
| Model / manufacturer SKU | `SA403-V1` |
| UPC | `6937285503237` |
| Quantity | 1 |
| Remaining quantity | 1 |
| Condition | New/boxed |
| State | Sealed / uninstalled |
| Storage location | null / unresolved |
| Reserved | No |
| Issued | No |
| Consumed | No |
| Installed | No |

`THS-MNT-000002.parts_required` references this permanent part identity as the
available candidate. `parts_used` remains null.

## Database validation

| Check | Result |
|---|---|
| Inserts | 29 |
| Updates | 2 |
| Deletes | 0 |
| Integrity | `ok` |
| Foreign-key violations | 0 |
| Unrelated changed tables | None |
| Existing slots unchanged | Yes |
| Existing assignments unchanged | Yes |
| Before SHA-256 | `2C5B3EF08BA222793B494E4B601C44FA88AA34C7CBA24331050C0BB70F90671C` |
| After SHA-256 | `3A9992C0337A11092780AC9F1B5E43126C03509A1EE749CC21679360DF3CFD28` |

The after checksum remained unchanged through route checks and both test
suites.

## Route validation

All checks were HTTP GET requests:

| Route | Status |
|---|---:|
| `/` | 200 |
| `/inventory/filament/replace` | 200 |
| `/inventory/filament/ams` | 200 |
| `/maintenance` | 200 |

Production SHA-256 immediately before and after route verification:

`3A9992C0337A11092780AC9F1B5E43126C03509A1EE749CC21679360DF3CFD28`

Route verification caused zero database writes.

## Tests

- Focused equipment, maintenance, inventory, service, command, preview, and
  legacy AMS suites: 123 passed.
- Full regression suite: 350 passed.

All tests used temporary data. Production was not used as a test fixture.

## Rollback

If immediate restoration were required before later legitimate production
activity:

1. stop only the verified production launcher under separate authorization;
2. preserve the current failed/diagnostic database;
3. restore the verified external backup;
4. verify the restored SHA-256 equals
   `2C5B3EF08BA222793B494E4B601C44FA88AA34C7CBA24331050C0BB70F90671C`;
5. verify schema 19, integrity `ok`, zero foreign-key violations, routes, and
   service identity before restart.

After later legitimate activity, do not restore the old backup over newer
history. Use controlled corrective workflows instead.

## Stop boundary

AMS production onboarding is complete. The physical repair, A2 return to
service, feeder consumption/installation, storage-location resolution,
second-feeder decision, and maintenance-parts reconciliation remain separate
future checkpoints.

