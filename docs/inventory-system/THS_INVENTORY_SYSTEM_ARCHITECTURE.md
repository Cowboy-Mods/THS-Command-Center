# THS Inventory System Architecture

## Product vision

THS Inventory System is a local-first, auditable inventory platform for makers, workshops, and small operations. Filament is the first module, not the system boundary. The same core can represent electronics, RC components, leather, engraving supplies, tools, hardware, consumables, replacement parts, and future modules without adding trade-specific columns to one giant table.

Maeve is the assistant and interface that will query this system. Maeve is not the database name.

## Stack selected at this checkpoint

The repository contained documentation only. There was no application framework, language, package manager, database library, migration system, or test framework to extend. This checkpoint introduces:

- Python 3, standard library only
- SQLite with foreign keys enabled on every connection
- numbered SQL migrations
- `unittest`
- no ORM and no third-party package manager dependency

This is deliberately small and Raspberry Pi friendly. A later web framework may call this layer without replacing the schema.

## Read-only application interface

The first visible interface uses Python's standard-library HTTP server, server-rendered HTML, plain responsive CSS, and modest JavaScript for mobile navigation. No UI dependency or frontend build chain is required.

`inventory/queries.py` opens SQLite using read-only mode and provides reusable dashboard, grouped-product, product-detail, spool-detail, transaction-history, AMS, search, filter, and reorder queries. `inventory/navigation.py` defines module labels and routes as metadata so future user profiles can hide, rename, add, or reorganize modules.

The Dashboard is the human-facing navigation contract for controlled inventory actions. Available workflows appear as labeled launch cards on the Dashboard and in the global **Controlled workflows** menu; route paths remain internal implementation details. Future workflows are displayed only as disabled roadmap items until their service boundary, validation, confirmation, audit, and tests exist.

Functional routes are Dashboard, Filament Inventory, Filament Product Detail, Individual Spool Detail, and AMS Units. All other planned modules display an honest Coming Soon page. See [Read-Only Dashboard v1](READ_ONLY_DASHBOARD_V1.md) for startup, route, responsive, and testing details.

## Extensible core

`categories` organize broad work areas. `item_types` define a tracking policy, default unit, and optional permanent-ID prefix. Both are rows created by configuration; adding "Bearing," "Servo," or "Leather Sheet" does not require a migration.

`attribute_definitions` describes typed fields. `item_type_attributes` makes a definition required or optional for an item type. `catalog_item_attribute_values` stores one typed value per catalog product. The normalized core keeps relationships, stock, units, and audit history queryable; configurable typed attributes hold trade-specific specifications. JSON is limited to import audit payloads and choice metadata, not live inventory.

## Tracking modes

- `individual`: one row per physical asset in `inventory_instances`, suitable for filament spools, printers, Raspberry Pis, power tools, and serialized electronics.
- `quantity`: pooled count or measure in `stock_lots`, suitable for screws, bearings, connectors, magnets, and rivets. Individual IDs are not required.
- `lot`: partial measured stock in `stock_lots`, with optional batch number, condition, and expiration, suitable for resin, adhesives, paint, leather, and chemicals.

The policy is an explicit, required `item_types.tracking_method` value. SQLite limits it to `individual`, `quantity`, or `lot`; it is never inferred from which stock rows happen to exist.

Migration `004_enforce_tracking_policies.sql` enforces the storage choice:

- ordinary `inventory_instances` inserts require an `individual` item type;
- ordinary `stock_lots` inserts require a `quantity` or `lot` item type;
- changing an item type's policy is rejected when existing non-override stock conflicts;
- an exceptional cross-policy row requires `tracking_policy_override=1` on that exact row;
- imports cannot set the override and reject a row when its requested policy differs from an existing item type;
- individual imports require `instance_count >= 1`;
- quantity and lot imports require `instance_count = 0`.

An override is an emergency integration escape hatch, not a normal workflow. A future service/UI must restrict it and pair it with an audit transaction and reason. Partial quantities use the item type's compatible unit. A bulk item does not receive a THS asset ID. An individually tracked item may receive a permanent, unique, immutable ID.

Project availability combines active `inventory_instances` with `stock_lots`, so individual, quantity, and lot policies participate in the same BOM comparison. Tests cover all three policies, import enforcement, database rejection of cross-policy inserts, explicit overrides, conflicting policy changes, and mixed-policy BOM availability.

## Units

`units` records a code, dimension, and scale to a base unit. Seeded dimensions cover count, mass, length, volume, and area. Values use their declared unit; conversion is allowed only within a matching dimension. A full conversion service is a later milestone.

## Locations and equipment

`locations` is an arbitrary parent/child tree. Database triggers reject circular parenting. Equipment may own constrained slots that are also locations. AMS 1 and AMS 2 are equipment/location records; each owns four uniquely numbered slots. Other installations can create different shelves, cabinets, trailers, or racks.

Active partial unique indexes enforce one spool per AMS slot and one AMS slot per spool. `ams_assignments` preserves load/unload times and transaction references.

## Transactions and archive policy

`inventory_transactions` is the audit header; `transaction_lines` records the item, instance or lot, quantity/unit, and source/destination. Supported reasons include purchase, receive, move, consume, correct, reserve/release, damage/loss, mark empty, archive, reconciliation, project allocation/completion, and AMS load/unload.

Transaction headers and lines are immutable and use restrictive foreign keys. Normal operations append compensating transactions instead of editing history. Empty individual items are marked empty and archived; they retain their ID and history but disappear from active totals.

## Centralized Inventory Action Service

`inventory/actions.py` is the exclusive normal mutation boundary. Editable UI routes, APIs, Maeve, importers, printer integrations, project workflows, and future modules may not write inventory tables directly.

Migration `005_inventory_action_service.sql` adds the immutable `inventory_actions` ledger. Every successful action records who acted, when, what happened, the initiating module, optional reason, affected entity/human ID, complete previous and new state JSON, reversibility, named reverse action, related inventory transaction, and reversal linkage.

The service owns validation, business rules, savepoint-based atomicity, inventory transaction creation, action logging, and supported reversal dispatch. Undo appends a new action and never edits the original record. The CSV importer now routes catalog and stock changes through this service. Numbered migrations and verified seed migrations remain the explicit database-bootstrap exception.

See [Inventory Action Service](INVENTORY_ACTION_SERVICE.md) for the required integration contract and supported methods.

## Reservations

`reservations` records planned demand without reducing physical remaining quantity. `reservation_allocations` ties demand to an instance or lot. A database trigger rejects an individual allocation above available quantity unless the reservation explicitly sets its shortage override. Release and final consumption remain separate operations.

## Bills of materials

`projects`, `project_requirements`, and `project_requirement_substitutes` prepare the BOM path. A requirement can target an exact catalog product or a configurable item type, specify a preferred product, unit, quantity, substitutes, and optional status. `project_material_status()` demonstrates available-versus-shortage comparison across both individual instances and quantity stock. Future allocation rows connect requirements to reservations; completion converts allocations to auditable consumption.

## Identity policy

SQLite integer primary keys are internal relationships. Human IDs such as `THS-FIL-000001` are unique and immutable. IDs are never reused. Item types can define future prefixes such as `THS-TOOL`, `THS-ELEC`, or `THS-ASSET`; quantity stock does not require one.

## Database relationships

Category â†’ item type â†’ catalog product â†’ individual instance or stock lot. Attribute definitions are attached to item types, then valued on products. Locations contain locations and equipment slots. Transactions point to stock through lines. Reservations allocate stock. Projects contain requirements and substitutes.

## Setup, migrations, and tests

From the repository root in PowerShell:

```powershell
py -3 -m inventory.cli migrate
py -3 -m unittest discover -v
```

Use another database safely:

```powershell
py -3 -m inventory.cli --database .\var\inventory-test.sqlite3 migrate
```

Active SQLite files, journals, caches, and secrets are ignored by Git.

## Import workflow

Copy `data/inventory/inventory-import-template.csv`, remove the example, and add verified rows. Attribute pairs use `name=value;name=value`. The core template supports any category.

Dry run:

```powershell
py -3 -m inventory.cli import .\data\inventory\my-verified-import.csv
```

Apply after reviewing accepted/rejected/warning totals:

```powershell
py -3 -m inventory.cli import .\data\inventory\my-verified-import.csv --apply
```

Unverified rows are rejected by default. `--allow-unverified` is the explicit override and should be used only for clearly labeled staging. Units, locations, tracking modes, quantities, remaining amounts, external IDs, and verification state are validated. Any rejected row rolls back the stock changes. Content hashes prevent an applied batch from adding inventory twice. Import batches remain auditable.

Approximate filament inputs should map to estimated grams only after nominal weight is known: Full 100%, 3/4 75%, 1/2 50%, 1/4 25%, Nearly Empty 10%. The result must be labeled estimated. Exact grams always win.

## Known limitations

- No polished dashboard or phone interface.
- No authentication/actor integration yet.
- Unit conversion metadata exists, but there is no complete conversion engine.
- Generic import attributes are recorded in the template but full attribute upsert mapping is a later importer enhancement.
- Reservation shortage enforcement is strongest for individual allocations; pooled-lot concurrency needs a service transaction.
- Tracking-policy overrides are database-explicit but do not yet have a permissioned UI; normal imports never set them.
- SQLite cannot absolutely prevent a privileged operator from dropping triggers or manually rewriting the file.
- Standard 1,000 g Overture, Elegoo, and Bambu values remain documented packaging assumptions pending physical label verification.

## Next milestones

1. Perform and review the first live Replace Active Filament Spool operation.
2. Confirm the selected Orange permanent IDs and AMS slot immediately before the Tweety Bird THS-hat replacement.
3. Verify open-wall colors, grams, and rack positions through a staged import.
4. Add remaining consume/reconcile/project-completion service methods before exposing those actions.
5. Add project allocation and completion services, then optional Bambu integration.

Before the first live replacement, use [Initialize Verified AMS State](INITIALIZE_VERIFIED_AMS_STATE.md) only for positively identified current physical assignments. Do not reconstruct historical White or Orange outgoing spools without verified permanent IDs and slots.

## Filament identity versus AMS-reported identity

THS Inventory is the source of truth for manufacturer, product, material, color, physical spool status, and usage. AMS-reported data may supplement a record but must never overwrite verified THS identity.

Keep RFID handling deliberately simple:

- an original Bambu RFID tag may be stored as an optional external identifier for the Bambu spool it originally accompanied;
- do not design workflows around moving or reusing Bambu RFID tags on other brands;
- enter non-Bambu filament manually in Bambu Studio and track it under its true identity in THS Inventory;
- no custom THS RFID system is required at this stage;
- barcode, QR, or RFID tagging for non-Bambu inventory remains a future optional enhancement.

Cowboy temporarily transferred a Bambu RFID tag in a pinch, but that is historical operational contextâ€”not a supported inventory pattern. Future design should not require manual-override, transferred-tag-source, or cross-brand RFID modeling solely for that exception.

Cowboy has ordered one bulk box expected to contain four Overture White refill rolls. Nothing is received until arrival, quantity, and condition are physically verified. If four acceptable refills arrive, receiving must create four individually tracked physical instances linked to one purchase or receiving batch. Purchase/receiving-batch modeling is a future requirement and is not added by the verified-AMS checkpoint.

