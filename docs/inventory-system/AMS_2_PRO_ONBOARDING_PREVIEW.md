# Bambu Lab AMS 2 Pro Onboarding — Revised Zero-Write Preview

Date: 2026-07-29  
Source baseline:
`29dedef5f9b57978402e41dfe44b1617ca1fff2e`
Production database:
`C:\Users\Cowboy\Documents\THS-Command-Center-Data\inventory.sqlite3`  
Mode: physically confirmed planning; no production write

## Outcome and stop boundary

The Equipment Registry and legacy AMS state were reinspected read-only using
Cowboy's confirmed serials, P1S relationship, Bambu Studio A/B designations,
slot layout, and maintenance facts.

The complete write set now uses the existing maintenance architecture. AMS 1
Slot 2 remains a slot, not independent equipment. Its restriction is scoped
inside an AMS 1 maintenance fault record. AMS 1 remains operational with
restrictions; the whole unit is not marked unavailable.

The prior 21-insert atomic plan is stale and must be regenerated. The preview
is not production-ready until a narrow atomic onboarding service can commit
every proposed row, including the feeder inventory, and rollback every child
action together.

No migration, service change, equipment record, relationship, restriction,
maintenance record, slot change, assignment change, or production write was
performed.

## Production database safety

| Check | Result |
|---|---|
| Schema | 19 |
| Latest migration | `019_flexible_spool_replacement.sql` |
| SQLite quick check | `ok` |
| Foreign-key violations | 0 |
| SHA-256 before inspection | `2C5B3EF08BA222793B494E4B601C44FA88AA34C7CBA24331050C0BB70F90671C` |
| SHA-256 after inspection | `2C5B3EF08BA222793B494E4B601C44FA88AA34C7CBA24331050C0BB70F90671C` |
| Production writes | 0 |

The checksum matches the last verified value. No intervening production
database activity was detected.

Temporary-data validation:

- focused equipment, inventory, AMS, maintenance, and replacement suites:
  **135 passed**;
- full regression suite: **339 passed**.

## Current listeners — inspected, not changed

| PID | Identity | Status |
|---:|---|---|
| 58064 | Verified bootstrap, explicit production database, source deployment record present | Running |
| 57596 | Untracked `python -m inventory.cli serve --host 127.0.0.1 --port 8787`, no explicit database | Running |

Both processes and their parent/process identities remained unchanged. Neither
was stopped, restarted, signaled, or otherwise disturbed.

## Physically confirmed parent and serial correction

Current production P1S:

| Field | Current | Proposed |
|---|---|---|
| Equipment | `THS-EQP-000001` Bambu Lab P1S | Unchanged |
| Registry row | 1 | Unchanged |
| Manufacturer serial | null | `01P00C511401400` |
| State version | 1 | 2 |
| Lifecycle | Installed | Unchanged |
| Operational status | Operating | Unchanged |

The serial is confirmed from the P1S screen. A future controlled fact update
would update the P1S row, append immutable `equipment_history.update_facts`,
and add one `update_equipment_facts` audit event. The permanent identity,
manufacturer, model, lifecycle, and operational status remain unchanged.

## Proposed AMS Registry records

| Field | AMS 1 | AMS 2 |
|---|---|---|
| Permanent ID | `THS-EQP-000002` | `THS-EQP-000003` |
| Display name | Bambu Lab AMS 2 Pro - AMS 1 | Bambu Lab AMS 2 Pro - AMS 2 |
| Manufacturer | Bambu Lab | Bambu Lab |
| Model | AMS 2 Pro | AMS 2 Pro |
| Exact serial | `19C06A522002297` | `19C51A620400EWR` |
| Bambu Studio designation | A | B |
| Type / subtype | AMS Unit / Bambu AMS | AMS Unit / Bambu AMS |
| Lifecycle | Installed | Installed |
| Registry operational status | Degraded | Operating |
| User-facing operational meaning | Operational with restrictions | Operational |
| Current Registry location | null | null |
| Installation date | null | null |
| State version | 1 | 1 |

AMS 1's serial is confirmed on both the P1S screen and the physical label.
AMS 2's serial contains no spaces or hyphens, and `EWR` is part of the serial.

`degraded` is the existing Registry enum that truthfully represents AMS 1 as
operational with restrictions. It does not itself enforce the Slot 2 loading
restriction.

## Parent/child relationships

| Child | Parent | Type | Effective time |
|---|---|---|---|
| `THS-EQP-000002` | `THS-EQP-000001` | `attached_to` | Actual future onboarding commit time |
| `THS-EQP-000003` | `THS-EQP-000001` | `attached_to` | Actual future onboarding commit time |

No earlier installation date is invented. Each relationship would create one
current-state row and one immutable attach-history row. Later moves or
detachment append history rather than rewriting these events.

## Legacy-container bridges

| Registry equipment | Legacy container | Bridge |
|---|---:|---|
| `THS-EQP-000002` | row 1, AMS 1 | one-to-one `equipment_legacy_container_links` insert |
| `THS-EQP-000003` | row 2, AMS 2 | one-to-one `equipment_legacy_container_links` insert |

These bridges adopt the existing eight slot rows. They do not create,
renumber, delete, or rewrite slots.

## Stored assignments versus confirmed physical truth

Exactly seven production slots are occupied. AMS 1 Slot 2/A2 is empty.

| Slot | Stored assignment | Confirmed physical truth | Result |
|---|---|---|---|
| AMS 1 Slot 1 / A1 | `THS-FIL-000040`, `purple` | Purple | Match |
| AMS 1 Slot 2 / A2 | Empty | Empty; unavailable; do not load | Occupancy match |
| AMS 1 Slot 3 / A3 | `THS-FIL-000042`, Hot Pink | Hot Pink | Match |
| AMS 1 Slot 4 / A4 | `THS-FIL-000041`, Cocoa Brown | Cocoa Brown | Match |
| AMS 2 Slot 1 / B1 | `THS-FIL-000039`, Black | Black | Match |
| AMS 2 Slot 2 / B2 | `THS-FIL-000023`, Orange | Orange | Match |
| AMS 2 Slot 3 / B3 | `THS-FIL-000033`, `cyan` | Blue | Compatible stored color family |
| AMS 2 Slot 4 / B4 | `THS-FIL-000022`, `Jade White` | White | Compatible stored color family |

The physical shorthand Blue and White does not contradict the stored catalog
names `cyan` and `Jade White`. Those permanent spool and catalog identities
remain unchanged as required.

Assignment IDs, spool identities, catalog identities, color text, load times,
states, weights, quantities, inventory transactions, transaction lines, and
audit history remain untouched.

## AMS 1 maintenance truth

Confirmed Slot 2 facts:

- the slot becomes loud and can lock up;
- its feeder/roller mechanism requires inspection and repair;
- it is Out of service / Do not load;
- it must reject future filament loading.

Confirmed Slot 4 facts:

- it has historically rewound faster than the spool;
- it is currently loaded with Cocoa Brown and functioning;
- it requires a monitoring note;
- it must not be marked out of service without new evidence.

Confirmed equipment-level readiness:

- AMS 1: Needs service;
- AMS 2: Unknown until formally inspected.

## Existing maintenance representation

Production already contains legacy maintenance assets:

| Asset | ID | Current readiness |
|---|---:|---|
| AMS 1 | 2 | Normal |
| AMS 2 | 3 | Normal |

Only AMS 1 is linked to its existing maintenance asset. Its readiness changes
from Normal to `monitor_during_printing`, which keeps the unit and Slots 1, 3,
and 4 available while communicating an active restriction.

AMS 2 is not linked to maintenance asset 3 during onboarding. Its Registry
readiness therefore remains null / Unknown until a formal inspection.

### Proposed AMS 1 maintenance link

| Field | Value |
|---|---|
| Registry equipment | `THS-EQP-000002` |
| Existing maintenance asset | ID 2, AMS 1 |
| Linked by | Cowboy |
| Linked at | Actual onboarding commit time |

### Proposed maintenance fault

| Field | Proposed value |
|---|---|
| Event number | `THS-MNT-000002` |
| Asset | AMS 1, maintenance asset 2 |
| Event type | `fault_discovered` |
| Status | `in_progress` |
| Severity | High |
| Discovered at | Actual future onboarding time; no earlier date invented |
| Affected component / symptoms | `Affected component: Slot 2 / A2. Reported symptom: the feeder/roller becomes loud and may lock.` |
| Likely cause | null; inspection has not proven a cause |
| Corrective action | `Required resolution: inspect, repair, and function-test Slot 2 / A2 before returning it to service.` |
| Restriction note | `Slot 2 / A2 is Out of service — do not load filament.` |
| Slot 4 note | Slot 4/A4 remains in service; historically rewound faster than the spool; currently loaded with Cocoa Brown and functioning |
| Whole-unit readiness | Normal to `monitor_during_printing` |
| Whole-unit unavailable | No |

One immutable `maintenance_history.record_fault` row records status null to
In progress and readiness Normal to Monitor during printing.

## Physically verified candidate repair part

Cowboy physically verified the following boxed part:

| Field | Confirmed value |
|---|---|
| Product | Bambu Lab AMS 2 Pro Feeder Unit |
| Model | `SA403-V1` |
| UPC | `6937285503237` |
| Quantity | 1 |
| Condition | New/boxed |
| Intended use | AMS 1 Slot 2/A2 feeder repair |
| Installed | No |

Production catalog items, attributes, inventory instances, stock lots,
purchase lines, and notes were searched read-only by exact product name,
model, and UPC. No matching part exists. The preview therefore proposes one
individually tracked candidate part, `THS-PART-000001`, plus the minimum
catalog configuration and immutable add transaction needed to represent it.

The part remains available only. It is not reserved, issued, consumed,
installed, or treated as a completed repair. The maintenance record's
`parts_required` field identifies it as the available candidate for
`THS-MNT-000002`.

Production has no location named `THS Bambu Maintenance Cabinet`. No location
row is proposed, and the candidate instance's `location_id` remains null in
this preview. Cowboy must confirm the part's current physical storage before
a production plan can be approved. The cabinet name will not be invented.

After Slot 2 is repaired and function-tested, a separate decision will
determine whether to buy one additional `SA403-V1` as a sealed shelf spare.
This preview does not order or record a second feeder.

The current schema has no dedicated `affected_component` or `restriction`
columns. The maintenance record therefore identifies those labels explicitly
inside `symptoms`, `corrective_action`, and `notes`, as authorized. No new
slot-equipment model or migration is proposed.

This text is an authoritative maintenance issue but is not automatically
interpreted by the current filament-loading service. Until a separately
authorized enforcement change exists, the operational control is the signed
onboarding precondition that A2 remains empty and the recorded `Do not load`
restriction.

## Required atomic onboarding service

One signed commit must bind:

- P1S fact update;
- both AMS registrations;
- both parent relationships;
- both legacy bridges;
- the AMS 1 maintenance-asset link;
- AMS 1 readiness update;
- the Slot 2-scoped maintenance record;
- the Slot 4 monitoring note inside that record;
- one verified candidate feeder part with catalog and immutable add history;
- maintenance history and all equipment audit/history rows.

Direct production SQL is not approved.

## Revised proposed write set

Under the existing schema, the complete proposal contains:

- **29 inserted rows**;
- **2 updated rows**;
- **0 deleted rows**;
- **0 slot rows created or changed**;
- **0 assignment rows changed**.

The 29 proposed inserts are:

| Table | Count | Purpose |
|---|---:|---|
| `equipment_registry` | 2 | AMS 1 and AMS 2 permanent records |
| `equipment_history` | 3 | Two registrations plus P1S fact update |
| `equipment_relationship_state` | 2 | Current P1S child relationships |
| `equipment_relationship_history` | 2 | Immutable attach events |
| `equipment_legacy_container_links` | 2 | Registry-to-legacy bridges |
| `audit_events` | 7 | P1S update plus three events per AMS |
| `equipment_maintenance_asset_links` | 1 | Link `THS-EQP-000002` to existing AMS 1 maintenance asset |
| `maintenance_records` | 1 | Slot 2/A2-scoped fault and Slot 4 monitoring note |
| `maintenance_history` | 1 | Immutable `record_fault` event |
| `item_types` | 1 | Individually tracked Printer Part type using `THS-PART` |
| `catalog_items` | 1 | Exact Bambu feeder product, model, and UPC |
| `inventory_instances` | 1 | `THS-PART-000001`, new/boxed, quantity 1 |
| `inventory_transactions` | 1 | Immutable `add` transaction |
| `transaction_lines` | 1 | Quantity 1 for the candidate instance |
| `audit_events` | 3 | Item type, catalog item, and instance creation |
| **Total** | **29** | |

The two proposed updates are:

- `equipment_registry` row 1 / `THS-EQP-000001`:
  `manufacturer_serial_number` null to `01P00C511401400`,
  `state_version` 1 to 2, and `updated_at` to commit time.
- `maintenance_assets` row 2 / AMS 1: readiness Normal to
  `monitor_during_printing` and `updated_at` to commit time.

## Expected audit records

1. `THS-EQP-000001` — `update_equipment_facts`;
2. `THS-EQP-000002` — `register_equipment`;
3. `THS-EQP-000002` — `attach_equipment_relationship`;
4. `THS-EQP-000002` — `link_legacy_equipment_container`;
5. `THS-EQP-000003` — `register_equipment`;
6. `THS-EQP-000003` — `attach_equipment_relationship`;
7. `THS-EQP-000003` — `link_legacy_equipment_container`.

Additional immutable maintenance audit:

8. `THS-MNT-000002` — `maintenance_history.record_fault`, previous readiness
   Normal, new readiness Monitor during printing.

Additional candidate-part audit:

9. `Printer Part` - `create_item_type`;
10. Bambu Lab AMS 2 Pro Feeder Unit - `create_catalog_item`;
11. `THS-PART-000001` - `add_individual_instance`, linked to one immutable
    `inventory_transactions.add` row and one transaction line.

## Duplicate and stale-state protections

A future commit must reject:

- permanent IDs other than the still-next `THS-EQP-000002` and
  `THS-EQP-000003`;
- any existing or concurrently created equipment using those IDs;
- duplicate P1S or AMS serials after case/whitespace normalization;
- display-name duplicates;
- duplicate current child relationships;
- self-parenting and relationship cycles;
- duplicate Registry-to-legacy-container bridges;
- anything other than unique slot numbers 1–4 per legacy AMS;
- any duplicate active spool in a slot or duplicate active slot for a spool;
- any onboarding state in which Slot 2/A2 is not empty;
- any existing match for the product name, `SA403-V1`, or UPC
  `6937285503237`;
- a changed next `THS-PART` permanent-ID sequence;
- candidate-part state that says consumed, issued, installed, or reserved;
- any unconfirmed or invented storage location;
- stale P1S, AMS, maintenance, slot, assignment, or sequence snapshots;
- expired, tampered, replayed, or reused previews.

Database uniqueness remains the final defense, while service validation must
produce friendly errors before commit.

## Atomic transaction and rollback

The final production write must use one transaction. If any P1S update, AMS
registration, relationship, bridge, readiness, restriction, maintenance,
candidate-part catalog/inventory, history, or audit action fails, every child
action rolls back.

Before future production authorization:

1. resolve the duplicate untracked listener under separate authorization;
2. reverify branch, source commit, schema, checksum, integrity, foreign keys,
   P1S state, next equipment IDs, legacy containers, slots, assignments, and
   maintenance assets, then repeat the exact feeder duplicate search;
3. create and hash-verify a fresh external backup;
4. build a fresh signed preview using the actual future onboarding time;
5. rehearse the complete atomic workflow on a verified production copy;
6. fingerprint every protected equipment, slot, assignment, inventory,
   transaction, maintenance, and audit table;
7. obtain explicit production authorization.

For immediate rollback before later activity, stop the verified application
and restore the verified backup. For later corrections, permanent IDs and
immutable history must remain; use controlled fact, relationship, restriction,
and maintenance transitions.

## Before-and-after validation plan

After a later authorized commit:

- Registry equipment count must be exactly 3;
- `THS-EQP-000001` must contain the confirmed P1S serial and state version 2;
- `THS-EQP-000002` and `THS-EQP-000003` must match exact names, models, and
  serials;
- both AMS units must be current `attached_to` children of the P1S;
- both immutable attach histories and both legacy bridges must exist;
- AMS 1 must project Degraded with an in-progress Slot 2 maintenance fault and
  Monitor during printing readiness;
- AMS 2 must project Operating / Unknown readiness;
- Slot 2/A2 must be empty, Out of service, and reject loading;
- Slot 4/A4 must remain loaded and operational with its monitoring note;
- exactly one `SA403-V1` / UPC `6937285503237` candidate part must exist;
- that part must remain new/boxed, quantity 1, uninstalled, unreserved,
  unissued, and unconsumed;
- no second feeder or invented cabinet location may exist;
- the same eight slot IDs and seven active assignment IDs must remain;
- all spool identities, catalog identities, colors, weights, quantities,
  transactions, and prior audit rows must fingerprint unchanged;
- telemetry and provenance counts must remain unchanged;
- integrity, foreign keys, focused tests, full regression, and HTTP routes
  must pass.

## Boundary

The AMS operational correction is preserved, and the verified feeder evidence
has been added. No new schema or slot-equipment model is required. The prior
atomic plan must be regenerated because the write set changed from 21 to 29
inserts. Production onboarding also remains blocked on confirmation of the
part's current storage location and a separately approved atomic service
checkpoint. Stop for explicit authorization.
