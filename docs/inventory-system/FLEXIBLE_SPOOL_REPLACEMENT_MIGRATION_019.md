# Migration 019 — Flexible Active-Spool Replacement Schema

Migration `019_flexible_spool_replacement.sql` is the schema-only foundation for
a later controlled flexible active-spool replacement workflow. It does not add
UI or service behavior and does not change any filament state.

## Design

SQLite cannot remove the legacy `NOT NULL` constraints with `ALTER TABLE`.
Migration 019 therefore rebuilds `inventory_workflow_transactions` inside one
transaction, copies every legacy column and row without reinterpretation, and
recreates the immutable update/delete triggers.

Legacy columns remain readable:

- `replacement_instance_id`
- `destination_slot_id`

They become nullable so a future no-replacement transaction does not need a fake
spool or slot. Existing sealed-replacement service writes remain valid with both
legacy columns populated and every new explicit field null.

## New explicit nullable columns

| Column | Meaning |
|---|---|
| `outgoing_disposition` | `empty`, `storage`, or `ams_slot` |
| `outgoing_destination_location_id` | Non-AMS storage location for the outgoing spool |
| `outgoing_destination_slot_id` | AMS destination for an outgoing spool move |
| `incoming_disposition` | `sealed`, `open`, or `none` |
| `incoming_source_location_id` | Incoming spool's prior non-AMS location |
| `incoming_source_slot_id` | Incoming spool's prior AMS slot, when applicable |
| `incoming_instance_id` | Permanent incoming spool identity |
| `incoming_destination_slot_id` | AMS destination for the incoming spool |

All identity and location fields use restrictive foreign keys.

## Compatibility modes

Legacy mode requires all eight new columns to be null. It accepts the original
sealed-replacement shape, including the legacy replacement and destination
columns.

Explicit mode requires both dispositions and requires the two legacy
replacement/destination columns to be null. Future service writes must use this
mode.

Existing rows are copied in legacy mode. No disposition backfill is performed
because that would invent facts not present in the original immutable record.

## Constraint behavior

- Outgoing `empty` requires no outgoing destination.
- Outgoing `storage` requires one storage location and no AMS slot.
- Outgoing `ams_slot` requires one AMS slot and no storage location.
- Incoming `none` requires no incoming spool, source, or destination.
- Incoming `sealed` or `open` requires one incoming spool, one destination AMS
  slot, and exactly one prior source: storage location or AMS slot.
- Current and incoming/replacement spool identities must differ.
- Outgoing and incoming destination slots cannot be the same.
- An incoming source slot cannot also be its destination slot.
- Existing partial unique indexes continue to enforce one active spool per AMS
  slot and one active AMS slot per spool.
- Workflow rows remain immutable through database triggers.

The schema permits a future atomic swap because an outgoing destination may be
the incoming spool's source slot. Service-layer validation must verify that all
occupied destinations are vacated by the same transaction before writing.

## Production-copy migration preview

Source production database:

`C:\Users\Cowboy\Documents\THS-Command-Center-Data\inventory.sqlite3`

| Check | Result |
|---|---|
| Production SHA-256 before and after | `3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A` |
| Candidate source-copy checksum | Exact production match |
| Candidate migrations | 18 → 19 |
| Only applied migration | `019_flexible_spool_replacement.sql` |
| Candidate SHA-256 after migration | `B7E5ACC653303D63D0FF88E6764EE69167D4E880C3E4547024B0780F5B94B0B4` |
| Existing protected tables fingerprinted | 75 |
| Existing tables with changed row content | 0 |
| SQLite integrity check | OK |
| SQLite quick check | OK |
| Foreign-key violations | 0 |
| Equipment Registry rows | 1, unchanged |
| Equipment telemetry rows | 0, unchanged |
| `THS-FIL-000032` | Unchanged |
| `THS-FIL-000039` | Unchanged |

Production currently has zero historical
`inventory_workflow_transactions` rows, so the production-copy comparison
preserved zero of zero. A migration test creates a genuine legacy transaction
with linked immutable actions before applying Migration 019, then proves every
legacy value, row ID, and action link survives unchanged with all new fields
null.

The disposable candidate was removed after validation.

## Rollback verification

A fresh schema-18 rollback copy matched the production SHA-256 exactly:

`3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A`

It retained 18 migrations, passed SQLite integrity checking, and had zero
foreign-key violations. No production rollback was performed because Migration
019 was not applied to production.

## Tests

- Migration/schema suite: 8 passed
- Focused filament workflow suites: 133 passed
- Full regression suite: 295 passed

## Next checkpoint

After separate authorization:

1. update the action service to write explicit dispositions;
2. implement the signed zero-write preview for all outgoing/incoming choices;
3. add atomic move, storage-return, open-replacement, and no-replacement logic;
4. update the guided UI and completion summary;
5. add the ten requested workflow-level scenarios;
6. validate against a schema-19 candidate;
7. produce—but do not apply—the `THS-FIL-000032`/`THS-FIL-000039`
   production correction preview.

Migration 019 production deployment must remain a separate authorized
checkpoint before any schema-19 production workflow can run.
