# THS-FIL-000032 / THS-FIL-000039 Production Correction

Status: **completed and validated**

Correction date: 2026-07-28 local / `2026-07-29 01:15:46` stored UTC

Authorized source checkpoint:
`68470a1616dc9fb261ea74efb8e89939c8767a30`

Branch: `feature/filament-manager-v1`

Production database:
`C:\Users\Cowboy\Documents\THS-Command-Center-Data\inventory.sqlite3`

## Authorized physical truth

Cowboy explicitly verified and authorized:

- `THS-FIL-000039` is physically loaded in AMS 2 Slot 1.
- `THS-FIL-000032` is removed and belongs at Open-Spool Wall.
- Both physical labels match their recorded products and colors.
- Neither spool is empty.
- AMS 1 Slot 4 is physically empty and should remain empty.
- Remaining weights must remain unchanged.

## Pre-correction safety gates

Every required precondition passed before the service transaction:

| Gate | Result |
|---|---|
| Repository HEAD | `68470a1616dc9fb261ea74efb8e89939c8767a30` |
| Repository clean/synchronized | Yes |
| Production schema | 19 |
| Latest migration | `019_flexible_spool_replacement.sql` |
| Required production SHA-256 | `5820C87D6812EB0699686CB958DBA1B2464C8E022A88F93E257179FEC51B0C52` |
| Actual production SHA-256 | Exact match |
| Integrity / quick check | `ok` / `ok` |
| Foreign-key violations | 0 |
| Port 8787 listener / THS process | None |
| WAL/SHM sidecars | None |
| Protected tables captured | 75 |
| Existing workflow rows | 0 |
| `THS-FIL-000032` | Loaded, assignment 4, AMS 2 Slot 1 / slot 5 |
| `THS-FIL-000039` | Loaded, assignment 7, AMS 1 Slot 4 / slot 4 |

The preserved schema-18 migration backup remained readable and clean:

`C:\Users\Cowboy\Documents\THS-Command-Center-Data\backups\migration-019-readiness\inventory-schema18-pre-migration019-20260728T173212-0400.sqlite3`

SHA-256:
`3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A`

## Fresh schema-19 correction backup

Created immediately before the correction:

`C:\Users\Cowboy\Documents\THS-Command-Center-Data\backups\spool-correction-032-039\inventory-schema19-pre-correction-20260728T211225-0400.sqlite3`

| Check | Result |
|---|---|
| Stored outside Git | Yes |
| Schema | 19 |
| SHA-256 | `5820C87D6812EB0699686CB958DBA1B2464C8E022A88F93E257179FEC51B0C52` |
| Exact byte/content match to production | Yes |
| Integrity / quick check | `ok` / `ok` |
| Foreign-key violations | 0 |
| Both target snapshots | Exact pre-correction match |

## Zero-write service preview

The real schema-19 service operation was executed inside an outer immediate
transaction and rolled back before confirmation. The production checksum
remained unchanged.

The preview required exactly:

1. unload `THS-FIL-000032` from AMS 2 Slot 1 to Open-Spool Wall;
2. unload `THS-FIL-000039` from AMS 1 Slot 4;
3. load `THS-FIL-000039` into AMS 2 Slot 1.

It bound:

- outgoing disposition `storage`, destination location 3;
- incoming disposition `open`, source slot 4, destination slot 5;
- no Empty action;
- no open-sealed action;
- no quantity change;
- actor `Cowboy`;
- module `filament-spool-replacement-ui`;
- origin `user`;
- reason `Correct authoritative AMS state to verified physical placement`;
- nonce `spool-correction-032-039-20260728T211225-0400`.

## Atomic service result

The exact previewed service call committed as one transaction. Any child
failure would have rolled back the parent and every child write.

### Parent workflow

| Field | Written value |
|---|---|
| ID | 1 |
| Workflow UUID | `38fb4bdf-8263-456c-aa64-ba1fa15d669a` |
| Review nonce | `spool-correction-032-039-20260728T211225-0400` |
| Workflow type | `replace_active_filament_spool` |
| Actor / module / origin | Cowboy / `filament-spool-replacement-ui` / `user` |
| Current instance | 32 |
| Legacy replacement/destination | null / null |
| Outgoing disposition | `storage` |
| Outgoing destination location | 3, Open-Spool Wall |
| Outgoing destination slot | null |
| Incoming disposition | `open` |
| Incoming source location | null |
| Incoming source slot | 4, AMS 1 Slot 4 |
| Incoming instance | 39 |
| Incoming destination slot | 5, AMS 2 Slot 1 |
| Print context fields | all null |

### Inventory transactions and lines

| Transaction / line | Operation | Instance | Source | Destination | Quantity change |
|---|---|---|---|---|---|
| 23 / 23 | Unload | 32 | location 7, AMS 2 Slot 1 | location 3, Open-Spool Wall | `0.0` |
| 24 / 24 | Unload | 39 | location 12, AMS 1 Slot 4 | location 7, AMS 2 Slot 1 | `0.0` |
| 25 / 25 | Load | 39 | location 7 | location 7, AMS 2 Slot 1 | `0.0` |

All three transactions record actor Cowboy, origin `manual`, the approved
reason, and no project/order/print reference.

### Linked audit actions

| Action | UUID | Type | Instance | Transaction |
|---|---|---|---|---|
| 40 | `211e26ac-6af9-4b68-b159-b76fa68ea63f` | `unload_instance_from_ams` | 32 | 23 |
| 41 | `0178b403-5908-4bc5-9a6c-5ea76ffbe744` | `unload_instance_from_ams` | 39 | 24 |
| 42 | `52e39aea-78b2-451e-be89-79ba31a8f220` | `load_instance_into_ams` | 39 | 25 |

All three actions link to parent workflow 1 and preserve immutable before/after
JSON.

### Assignment history

| Assignment | Result |
|---|---|
| 4 | 32's AMS 2 Slot 1 assignment closed; unload transaction 23 |
| 7 | 39's AMS 1 Slot 4 assignment closed; unload transaction 24 |
| 9 | New active assignment: instance 39 to AMS 2 Slot 1; load transaction 25 |

### Exact row-count changes

| Table | Delta |
|---|---|
| `inventory_workflow_transactions` | +1 |
| `inventory_transactions` | +3 |
| `transaction_lines` | +3 |
| `inventory_actions` | +3 |
| `ams_assignments` | +1, plus two existing assignment closures |
| `inventory_instances` | 0 rows added or removed; two controlled updates |

## Before and after state

| Item | Before | After |
|---|---|---|
| `THS-FIL-000032` | Loaded in AMS 2 Slot 1 | Open at Open-Spool Wall |
| `THS-FIL-000039` | Loaded in AMS 1 Slot 4 | Loaded in AMS 2 Slot 1 |
| AMS 1 Slot 4 | Recorded occupant 39 | Empty |
| AMS 2 Slot 1 | Recorded occupant 32 | Recorded occupant 39 |

Preserved for both spools:

- permanent IDs;
- catalog item IDs;
- manufacturers, products, product lines, and colors;
- conditions;
- notes;
- original and remaining quantities;
- unit IDs;
- purchase/open/empty/archive timestamps other than normal `updated_at`;
- verified flags and tracking-policy settings.

`THS-FIL-000032` remains `original_quantity=0.0` and
`remaining_quantity=0.0`, with notes explicitly preserving the
unknown/unweighed meaning. `THS-FIL-000039` remains
`original_quantity=1000.0` and `remaining_quantity=1000.0`. Neither spool was
marked Empty.

## Validation

| Check | Result |
|---|---|
| Production schema | 19 |
| Integrity / quick check | `ok` / `ok` |
| Foreign-key violations | 0 |
| Unrelated protected tables compared | 69 |
| Unrelated protected tables changed | 0 |
| 32 active AMS assignment | None |
| 32 location/state | Open-Spool Wall / Open |
| 39 active AMS assignment | Assignment 9, AMS 2 Slot 1 |
| AMS 1 Slot 4 | Empty |
| Equipment/telemetry and unrelated workflows | Unchanged |

Checksums:

- before correction:
  `5820C87D6812EB0699686CB958DBA1B2464C8E022A88F93E257179FEC51B0C52`;
- after correction:
  `D50AA7C4F437FE7717F04DFF5F34448EB38C209C7BA2C23F8D0B2CB1DB637091`;
- schema-19 backup:
  `5820C87D6812EB0699686CB958DBA1B2464C8E022A88F93E257179FEC51B0C52`.

Test results:

- focused Migration 019/service/UI/correction-preview suites:
  34 passed in 65.917 seconds;
- full regression suite: 321 passed in 628.728 seconds.

Read-only route validation:

- dashboard HTTP 200;
- guided replacement route HTTP 200;
- schema-19 flexible controls enabled;
- database checksum identical before/after route checks;
- zero route-check writes.

## Rollback readiness

The fresh schema-19 backup is the correction rollback source. While no later
production writes have occurred, an authorized emergency rollback may:

1. stop the application and preserve the corrected production file under a
   unique incident name with its checksum;
2. re-hash the fresh schema-19 backup and require the exact pre-correction hash;
3. validate a new restore candidate at schema 19 with clean integrity, foreign
   keys, protected fingerprints, and pre-correction spool snapshots;
4. replace production only after those checks;
5. revalidate routes and document the rollback.

After later production writes, restoring this backup would discard immutable
history and is prohibited. Any later logical correction must use another
audited workflow.

## Completed boundary

The authoritative database now matches Cowboy's verified physical spool state.
No purple-color logic, AMS onboarding, Main, purchase, receiving, equipment, or
telemetry work was performed.
