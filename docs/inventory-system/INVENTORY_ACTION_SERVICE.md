# Inventory Action Service

## Purpose

`inventory/actions.py` is the single normal write boundary for the THS Inventory System. Future editable UI routes, APIs, Maeve tools, importers, printer integrations, project workflows, and other modules must call `InventoryActionService`. They must not issue direct SQL against catalog, inventory, reservation, AMS, or transaction tables.

Numbered migrations and verified seed migrations are the explicit database-bootstrap exception. Import batch/row records are importer execution metadata; the importer routes every catalog and stock mutation through the action service.

SQLite cannot stop a privileged operator from opening the database manually or dropping triggers. Exclusivity is therefore enforced by the application architecture, service API, tests, code review, read-only query connections, and immutable database triggers.

## Action context

Every service instance requires `ActionContext`:

- `actor` â€” who initiated the change, such as Cowboy, Maeve, an importer filename, or a system job;
- `module` â€” the initiating module, such as `inventory-import`, `filament-manual`, or `project-allocation`;
- `origin` â€” one of `user`, `maeve`, `importer`, `system`, `api`, `integration`, or `project`.

Blank actors/modules and unknown origins are rejected before mutation.

## Immutable action ledger

Migration `005_inventory_action_service.sql` adds `inventory_actions`. Each successful action records:

- immutable UUID and timestamp;
- actor, module, and origin;
- action type and optional reason;
- whether the action is reversible;
- named reverse action when reversible;
- affected entity type and internal ID;
- affected permanent/human ID when available;
- previous state as validated JSON;
- new state as validated JSON;
- related inventory transaction;
- the original action ID when this action is a reversal.

Database triggers reject updates and deletes from this ledger. Undo never rewrites history. It appends a new action whose `reverses_action_id` points to the original.

## Service responsibilities

The service centralizes:

- required actor/module/origin context;
- catalog and tracking-policy validation;
- quantity bounds and unchanged-value rejection;
- location and unit validation;
- active/archive/state rules;
- reservation availability;
- AMS slot occupancy and one-slot-per-instance rules;
- atomic inventory mutation;
- `inventory_transactions` and `transaction_lines`;
- before/after snapshots;
- immutable action logging;
- supported reversal dispatch.

Each method uses a SQLite savepoint. A failed validation, duplicate ID, constraint failure, transaction failure, or audit failure rolls back the complete action. When called inside an import batch transaction, the action participates in the outer batch rollback.

Composite shop operations use an immutable parent workflow transaction. The first is [Replace Active Filament Spool](REPLACE_ACTIVE_FILAMENT_SPOOL.md). Its three child actions retain individual transactions and audit snapshots while sharing `workflow_transaction_id`.

## Supported actions

Configuration and receiving:

- `ensure_category`
- `ensure_item_type`
- `ensure_manufacturer`
- `ensure_catalog_item`
- `ensure_catalog_item_attribute`
- `preview_next_human_id`
- `add_individual_instance`
- `add_stock_lot`

Inventory operations:

- `move_instance`
- `correct_instance_remaining`
- `change_instance_state`
- `archive_stock_lot`
- `create_instance_reservation`
- `release_reservation`
- `load_instance_into_ams`
- `unload_instance_from_ams`
- `mark_loaded_spool_empty`
- `open_sealed_spool`
- `replace_active_filament_spool`
- `reverse_action`

Additional workflows must be added as service methods before any caller exposes them.

## Reversal behavior

Reversible actions record a concrete reverse action. Automated reversal currently covers:

- move â†’ move back to the previous location;
- remaining-quantity correction â†’ restore the previous amount;
- reversible state change â†’ restore the previous state;
- newly added individual instance â†’ archive the instance;
- newly added stock lot â†’ archive the lot;
- reservation creation â†’ release the reservation;
- AMS load â†’ unload to the previous location;
- AMS unload â†’ reload into the previous slot.

Empty/archive actions and reservation release are intentionally irreversible through automated undo. A reversal can happen once. The reversal itself is a separate immutable audit record.

## Importer integration

The CSV importer creates an action context with:

- actor: `importer:<filename>`;
- module: `inventory-import`;
- origin: `importer`.

Applied catalog setup and stock rows flow through the service. Rejected or transaction-rolled-back batches leave no stock action records. Import-batch validation evidence remains in `import_batches` and `import_rows`.

## Integration contract

Future code must:

1. Open a normal foreign-key-enabled connection.
2. Construct an explicit `ActionContext`.
3. Call an `InventoryActionService` method.
4. Return the resulting entity/action identifiers to its caller.
5. Read audit history rather than editing it.

Future code must not:

- directly insert/update/delete catalog or stock rows;
- create inventory transactions independently;
- create an audit record without the corresponding mutation;
- update or delete historical action records;
- claim an action is reversible without a concrete reverse action.

All dashboard queries remain read-only. The single receive-spool commit path opens a normal connection only inside the dedicated workflow and writes exclusively through this service.

## Verification

Run:

```powershell
py -3 -m unittest discover -v
```

Dedicated service tests cover context validation, catalog setup and attributes, individual/quantity/lot policies, complete audit fields, immutable history, atomic rollback, moves, corrections, state changes, reservation/release, AMS load/unload, automated reversals, double-reversal rejection, importer integration, rejected-import rollback, read-only routes, and the confirmed receive-spool workflow.

## Next checkpoint

The receive workflow and first composite shop workflow are complete:

- [Receive a Verified Sealed Spool](RECEIVE_VERIFIED_SEALED_SPOOL.md)
- [Replace Active Filament Spool](REPLACE_ACTIVE_FILAMENT_SPOOL.md)

