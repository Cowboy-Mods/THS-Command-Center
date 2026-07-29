# Migration 019 Production Validation Report

Status: **deployed and validated — spool correction not applied**

Deployment date: 2026-07-28

Authorized source checkpoint:
`93e59de7f37343e38d7cbead5af01049ec9531fa`

Branch: `feature/filament-manager-v1`

Production database:
`C:\Users\Cowboy\Documents\THS-Command-Center-Data\inventory.sqlite3`

## Authorization boundary

Cowboy explicitly authorized only production deployment of Migration 019 after
requiring exact preflight agreement with the readiness report.

Not authorized or performed:

- the approved physical-state correction for `THS-FIL-000032` and
  `THS-FIL-000039`;
- purple-color changes;
- AMS equipment onboarding;
- Main changes;
- any purchase, receiving, inventory, equipment, or telemetry workflow.

## Pre-deployment safety gates

Every required gate passed before the production connection was opened for
write:

| Gate | Result |
|---|---|
| Repository HEAD | `93e59de7f37343e38d7cbead5af01049ec9531fa` |
| Branch | `feature/filament-manager-v1` |
| Repository clean and synchronized | Yes |
| Production schema | 18 |
| Latest migration | `018_equipment_registry_v1.sql` |
| Required production SHA-256 | `3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A` |
| Actual production SHA-256 | Exact match |
| Production integrity / quick check | `ok` / `ok` |
| Production foreign-key violations | 0 |
| Port 8787 listener | None |
| THS process holding production | None found |
| WAL/SHM sidecars | None |
| Pending migrations | Only `019_flexible_spool_replacement.sql` |
| Protected tables captured | 75 |
| Existing workflow rows | 0 |
| Equipment / telemetry rows | 1 / 0 |

Verified external rollback backup:

`C:\Users\Cowboy\Documents\THS-Command-Center-Data\backups\migration-019-readiness\inventory-schema18-pre-migration019-20260728T173212-0400.sqlite3`

The backup was present, readable, schema 18, integrity `ok`, foreign-key clean,
and an exact byte/content match to the production baseline:

`3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A`

Migration 019 source SHA-256 was also reverified:

`B6B142B45B61B302B76B1BF6574FA8E5E28CFD54F1221274A4C21482831E0FFF`

## Deployment result

Exactly one migration was applied:

`019_flexible_spool_replacement.sql`

| Check | Before | After |
|---|---|---|
| Migration count | 18 | 19 |
| Latest migration | `018_equipment_registry_v1.sql` | `019_flexible_spool_replacement.sql` |
| File size | 1,077,248 bytes | 1,097,728 bytes |
| SHA-256 | `3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A` | `5820C87D6812EB0699686CB958DBA1B2464C8E022A88F93E257179FEC51B0C52` |
| Integrity check | `ok` | `ok` |
| Quick check | `ok` | `ok` |
| Foreign-key violations | 0 | 0 |

No other migration was applied and none remains pending.

## Schema verification

The rebuilt `inventory_workflow_transactions` table contains all eight required
explicit nullable fields:

- `outgoing_disposition`;
- `outgoing_destination_location_id`;
- `outgoing_destination_slot_id`;
- `incoming_disposition`;
- `incoming_source_location_id`;
- `incoming_source_slot_id`;
- `incoming_instance_id`;
- `incoming_destination_slot_id`.

Legacy replacement/destination fields remain readable and nullable. The
immutable update and delete triggers were verified:

- `inventory_workflow_transactions_immutable_update`;
- `inventory_workflow_transactions_immutable_delete`.

Migration/schema tests separately verify disposition constraints, foreign keys,
no-replacement rows, storage/slot mutual validity, legacy compatibility, and
immutable history.

## Protected-data verification

All 75 protected table content fingerprints matched the pre-deployment
baseline. Expected changed row content was zero; observed changed row content
was zero.

| Protected record group | Before | After |
|---|---|---|
| Workflow rows | 0 | 0 |
| Equipment Registry rows | 1 | 1 |
| Equipment telemetry rows | 0 | 0 |
| `THS-FIL-000032` inventory fields | Baseline snapshot | Exact match |
| `THS-FIL-000032` active assignment | AMS 2 Slot 1 | Unchanged |
| `THS-FIL-000039` inventory fields | Baseline snapshot | Exact match |
| `THS-FIL-000039` active assignment | AMS 1 Slot 4 | Unchanged |

The last two database assignments intentionally remain different from Cowboy's
verified physical truth. Migration 019 was schema-only. Correcting those
assignments remains the next separately authorized audited workflow.

No new inventory workflow, inventory transaction, transaction-line, action,
AMS assignment, equipment, or telemetry row was created.

## Service, UI, and regression validation

Focused post-deployment gate:

- Migration 019 schema tests;
- flexible replacement service tests;
- guided flexible replacement UI tests;
- correction-preview tests;
- result: 34 passed in 67.984 seconds.

Full regression suite:

- result: 321 passed in 652.684 seconds.

Read-only production route checks:

| Route/check | Result |
|---|---|
| Dashboard | HTTP 200 |
| Guided flexible replacement route | HTTP 200 |
| Schema-19 flexible controls visible | Yes |
| Pre-Migration-019 safety gate absent | Yes |
| Database checksum before/after route reads | Identical |
| Route-check writes | Zero |

The production checksum before and after route validation remained:

`5820C87D6812EB0699686CB958DBA1B2464C8E022A88F93E257179FEC51B0C52`

## Rollback readiness

The verified schema-18 backup remains preserved outside Git. It is appropriate
only for an immediate migration rollback before any schema-19 workflow write.

If rollback becomes necessary before later writes:

1. stop the application and keep port 8787 closed;
2. preserve the schema-19 production file under a unique incident name and
   record its checksum;
3. re-hash the schema-18 backup and require the exact baseline checksum;
4. restore to a new candidate and validate schema, integrity, foreign keys,
   protected fingerprints, and target-spool snapshots;
5. only then replace the stopped production file;
6. validate routes and produce a rollback report.

After any successful schema-19 workflow, restoring this schema-18 backup would
discard immutable history and is prohibited. A later logical error must be
corrected with a new audited workflow.

## Final boundary

Production is now schema 19 and Migration 019 is validated. The approved spool
correction has not been applied. Main, purple-color logic, and AMS onboarding
remain untouched.
