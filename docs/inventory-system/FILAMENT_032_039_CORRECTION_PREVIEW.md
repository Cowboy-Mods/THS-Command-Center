# THS-FIL-000032 / THS-FIL-000039 Correction Preview

Status: **zero-write preview only — not authorized for application**

Inspection date: 2026-07-28

Production database: `C:\Users\Cowboy\Documents\THS-Command-Center-Data\inventory.sqlite3`

Production schema: 18 (`018_equipment_registry_v1.sql`)

Production SHA-256 before inspection:
`3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A`

The database was opened with SQLite `mode=ro&immutable=1` and
`PRAGMA query_only=ON`. `PRAGMA quick_check` returned `ok`; foreign-key
violations were zero. The checksum after inspection remained identical.

## Human-readable before and after

| Spool / slot | Production record before | Proposed record after |
|---|---|---|
| `THS-FIL-000032` | Bambu Lab PLA Basic Black; state `loaded`; condition `open`; location row 7; active assignment row 4 to AMS 2 Slot 1 (slot row 5); remaining quantity stored as `0.0`, explicitly documented as unknown/unweighed | State `open`; location Open-Spool Wall (row 3); assignment row 4 closed; permanent identity, catalog identity, condition, notes, and quantities unchanged |
| `THS-FIL-000039` | Overture PLA Black; state `loaded`; condition `new`; location row 12; active assignment row 7 to AMS 1 Slot 4 (slot row 4); stored remaining quantity `1000.0` | State remains `loaded`; location becomes row 7; assignment row 7 closed; new active assignment to AMS 2 Slot 1 (slot row 5); permanent identity, catalog identity, condition, opened timestamp, and quantities unchanged |
| AMS 2 Slot 1 | Database occupant: `THS-FIL-000032` | Proposed occupant: `THS-FIL-000039` |
| AMS 1 Slot 4 | Database occupant: `THS-FIL-000039` | Empty |

This is one atomic schema-19 operation:

- outgoing disposition: `storage`;
- outgoing destination: Open-Spool Wall, location row 3;
- incoming disposition: `open`;
- incoming source: AMS 1 Slot 4, slot row 4;
- incoming destination: AMS 2 Slot 1, slot row 5.

It is not an empty-spool operation. It does not open a sealed spool. It does
not change either permanent `THS-FIL` identity or either quantity.

## Current production records and history

### THS-FIL-000032

- Inventory instance row: 32.
- Catalog row: 20, Bambu Lab / PLA Basic Filament / PLA Basic / Black.
- Registered as pre-existing open inventory at `2026-07-26 14:00:14`.
- Notes explicitly say remaining quantity is unknown and has not been weighed.
- `original_quantity=0.0` and `remaining_quantity=0.0` are therefore not proof
  that the spool is empty.
- Action 13 (`819b14fb-d1f3-48fc-aa9f-6ddc4f1f95f5`) / transaction 7
  created the permanent instance as Open.
- Action 14 (`cab0655e-3c53-4ccc-8895-bd54641771f7`) / transaction 8
  loaded it into AMS 2 Slot 1.
- AMS assignment row 4 is active and has no unload transaction.
- No replacement-workflow parent row currently references this spool.

### THS-FIL-000039

- Inventory instance row: 39.
- Catalog row: 1, Overture / PLA Filament / PLA / Black.
- Action 31 (`12a485ea-b804-4d3a-8bce-2ac6050662a7`) / transaction 17
  created it as sealed at Sealed Filament Rack.
- Action 32 (`07bdaedf-d17c-49f3-87ee-52fb3b5cee02`) / transaction 18
  opened it with effective time
  `2026-07-27T20:27:00-04:00`.
- Action 33 (`44b66ea2-9f91-4d94-8003-f9807c43d04a`) / transaction 19
  loaded it into AMS 1 Slot 4 under request nonce
  `db4b2642556143f38d741f9842c5fc5d`.
- AMS assignment row 7 is active and has no unload transaction.
- No replacement-workflow parent row currently references this spool.
- The stored remaining quantity is `1000.0`; production history does not prove
  its present physical weight after opening or use.

Existing history is retained exactly. The proposed correction adds new history
and closes current assignments; it does not rewrite earlier actions,
transactions, or assignments.

## Known facts versus required physical confirmation

Database-proven facts:

- permanent identities 32 and 39 exist once each;
- their catalog manufacturer/product/color mappings are Bambu Lab PLA Basic
  Black and Overture PLA Black respectively;
- both records are active, verified, and currently recorded as `loaded`;
- the authoritative database assignments are AMS 2 Slot 1 for 32 and AMS 1
  Slot 4 for 39;
- Open-Spool Wall is active storage row 3;
- AMS 2 Slot 1 is slot row 5;
- neither spool has prior replacement-workflow history.

Facts the database cannot prove and Cowboy must confirm immediately before any
application:

1. The physical spool now in AMS 2 Slot 1 is permanent identity
   `THS-FIL-000039`.
2. `THS-FIL-000032` is physically removed from AMS 2 Slot 1 and its intended
   controlled storage destination is Open-Spool Wall.
3. The labels on those two physical spools match the catalog identities:
   Overture PLA Black for 39 and Bambu Lab PLA Basic Black for 32.
4. Neither spool is physically empty; both should remain truthfully Open/Loaded
   rather than Empty.
5. AMS 1 Slot 4 should be left empty after correcting the authoritative state.
6. No quantity correction is requested. The correction will preserve 32's
   unknown/unweighed `0.0` sentinel and 39's stored `1000.0`; an actual weight
   requires a separate verified weighing workflow.

## Exact rows and fields proposed to change

Migration 019 must first be separately deployed and production must be schema
19. Applying this correction through the flexible replacement service would
perform the following as one transaction.

### Parent workflow row — insert one

Table: `inventory_workflow_transactions`

| Field | Proposed value |
|---|---|
| `workflow_type` | `replace_active_filament_spool` |
| `current_instance_id` | 32 |
| `replacement_instance_id` | null (legacy field) |
| `destination_slot_id` | null (legacy field) |
| `outgoing_disposition` | `storage` |
| `outgoing_destination_location_id` | 3 |
| `outgoing_destination_slot_id` | null |
| `incoming_disposition` | `open` |
| `incoming_source_location_id` | null |
| `incoming_source_slot_id` | 4 |
| `incoming_instance_id` | 39 |
| `incoming_destination_slot_id` | 5 |

The row ID, workflow UUID, review nonce, occurrence time, actor, module, origin,
and reason are generated or bound by the later signed preview/application.
All optional print-context fields remain null unless Cowboy separately supplies
and approves a truthful print-event note. Proposed controlled metadata is
`actor=Cowboy`, `module=filament-spool-replacement-ui`, `origin=user`, and
`reason=Correct authoritative AMS state to verified physical placement`.

### Existing rows — update

| Table / row | Field | Before | After |
|---|---|---|---|
| `inventory_instances` 32 | `state` | `loaded` | `open` |
| `inventory_instances` 32 | `location_id` | 7 | 3 |
| `inventory_instances` 32 | `updated_at` | `2026-07-26 14:00:14` | application time |
| `ams_assignments` 4 | `unloaded_at` | null | application time |
| `ams_assignments` 4 | `unload_transaction_id` | null | generated transaction ID |
| `inventory_instances` 39 | `state` | `loaded` | `open`, then atomically back to `loaded` |
| `inventory_instances` 39 | `location_id` | 12 | 7 |
| `inventory_instances` 39 | `updated_at` | `2026-07-28 00:28:29` | application time |
| `ams_assignments` 7 | `unloaded_at` | null | application time |
| `ams_assignments` 7 | `unload_transaction_id` | null | generated transaction ID |

The intermediate Open state for row 39 exists only inside the same transaction;
its committed final state is Loaded in AMS 2 Slot 1.

### New child rows — insert

- One new active `ams_assignments` row:
  `slot_id=5`, `instance_id=39`, `loaded_at=application time`,
  `load_transaction_id=generated`, unload fields null.
- Three immutable `inventory_transactions` rows, in order:
  unload 32, unload 39, load 39.
- Three immutable `transaction_lines` rows, one for each transaction.
- Three immutable `inventory_actions` rows with before/after JSON and the same
  parent workflow ID:
  `unload_instance_from_ams` for 32,
  `unload_instance_from_ams` for 39,
  `load_instance_into_ams` for 39.

The three `inventory_transactions` rows have these complete field projections:

| Operation | `transaction_type` | `occurred_at` | `reason` | `notes` | `origin` | `actor` | `project_ref` | `order_ref` | `print_job_ref` |
|---|---|---|---|---|---|---|---|---|---|
| Unload 32 | `unload` | application time | approved reason above | null | `manual` | Cowboy | null | null | null |
| Unload 39 | `unload` | application time | approved reason above | null | `manual` | Cowboy | null | null | null |
| Load 39 | `load` | application time | approved reason above | null | `manual` | Cowboy | null | null | null |

Each row also receives one generated integer `id`.

The three `transaction_lines` rows have these complete field projections:

| Operation | `transaction_id` | `catalog_item_id` | `instance_id` | `stock_lot_id` | `quantity_change` | `unit_id` | `source_location_id` | `destination_location_id` |
|---|---|---|---|---|---|---|---|---|
| Unload 32 | generated unload-32 ID | 20 | 32 | null | `0` | 3 | 7 | 3 |
| Unload 39 | generated unload-39 ID | 1 | 39 | null | `0` | 3 | 12 | 7 |
| Load 39 | generated load-39 ID | 1 | 39 | null | `0` | 3 | 7 | 7 |

Each line also receives one generated integer `id`.

The three `inventory_actions` rows have the same complete field pattern:

- generated `id`, `action_uuid`, and `occurred_at`;
- `actor=Cowboy`, `module=filament-spool-replacement-ui`, `origin=user`;
- `reason` equal to the approved reason above;
- `affected_entity_type=inventory_instance`;
- the action type and affected identity in the order listed above;
- `reversible=1`;
- `reverse_action=load_instance_into_ams` for both unloads and
  `reverse_action=unload_instance_from_ams` for the load;
- `affected_entity_id` 32, 39, and 39 respectively;
- `affected_human_id` `THS-FIL-000032`, `THS-FIL-000039`, and
  `THS-FIL-000039` respectively;
- immutable `previous_state` and `new_state` JSON matching the instance and
  assignment transitions in this report;
- the matching generated `transaction_id`;
- `reverses_action_id=null`;
- all three rows linked to the generated parent `workflow_transaction_id`;
- child `request_nonce=null` (the unique review nonce is stored on the parent
  workflow).

No catalog, purchase, receiving, equipment-registry, telemetry, reservation, or
unrelated inventory row is part of the proposal.

## Required preconditions before application

All checks must pass against a fresh production read immediately before a new
signed preview is issued:

1. Cowboy explicitly confirms all six physical questions above.
2. Production schema is exactly 19 and only approved Migration 019 caused the
   schema change.
3. A verified rollback backup exists outside Git and matches its recorded hash.
4. Production integrity is `ok`; foreign-key violations are zero.
5. Instance 32 still exists once, is active, state `loaded`, and has exactly one
   active assignment: row 4 / slot 5 / AMS 2 Slot 1.
6. Instance 39 still exists once, is active, state `loaded`, and has exactly one
   active assignment: row 7 / slot 4 / AMS 1 Slot 4.
7. AMS 2 Slot 1 has no occupant other than 32, and AMS 1 Slot 4 has no occupant
   other than 39.
8. Open-Spool Wall row 3 remains active and valid for an Open spool.
9. Permanent IDs, catalog IDs, colors, states, locations, quantities,
   assignment rows, and relevant latest action IDs match this preview.
10. No prior workflow uses the new confirmation nonce.
11. A fresh service-generated zero-write preview passes and its signed plan
    matches the reviewed correction exactly.
12. A before-correction checksum and protected-table snapshots are recorded.

Any mismatch makes this preview stale and must stop the operation without
writes.

## Rollback and correction safety

- Validation or child-action failure: the service transaction rolls back all
  parent, instance, assignment, transaction-line, and audit writes together.
- Failure before commit: no database restore is needed; verify checksum/state
  and investigate.
- Emergency database failure after commit and before any later production
  activity: stop the application, preserve the failed database, verify the
  pre-correction backup hash, and restore only that exact backup under a
  separately authorized recovery procedure.
- Logical mistake discovered after a successful commit: do not delete or edit
  immutable history. Use a new controlled, audited inverse correction after a
  fresh physical inspection and preview.

## Required post-correction verification

- schema remains 19;
- integrity check `ok`;
- foreign-key violations zero;
- exactly one active assignment for 39 at AMS 2 Slot 1;
- no active assignment for 32;
- no active assignment at AMS 1 Slot 4;
- 32 is Open at Open-Spool Wall;
- 39 is Loaded at AMS 2 Slot 1;
- quantities, permanent IDs, catalog identities, notes, and opened timestamps
  remain unchanged;
- exactly one parent workflow and the expected three child actions were added;
- all before/after action JSON and transaction lines match the signed plan;
- purchases, receiving, equipment, telemetry, reservations, and unrelated
  inventory remain unchanged;
- dashboard and core routes remain healthy;
- focused filament tests and full regression suite pass;
- after-checksum is recorded and its change is explained by only the approved
  correction;
- Git remains clean and synchronized.

## Source and test evidence

- `inventory/correction_preview.py` performs only SELECT/PRAGMA inspection,
  rejects missing or contradictory authoritative assignments, projects the
  exact schema-19 rows and fields, and asserts its connection change count did
  not increase.
- `tests/test_correction_preview.py` covers zero-write behavior, exact atomic
  row planning, identity/quantity/history preservation, and stale-precondition
  rejection.
- Focused correction/service/UI tests: 26 passed in 57.636 seconds.
- Full regression suite: 321 passed in 653.556 seconds.
- Final production checksum:
  `3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A`
  (identical to the before checksum).

## Checkpoint boundary

Migration 019 was not applied. No production record was changed. This document
is not authorization to deploy the migration or apply the correction.
