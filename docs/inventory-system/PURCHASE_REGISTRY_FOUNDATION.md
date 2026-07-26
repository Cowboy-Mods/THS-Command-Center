# Purchase Registry Foundation

## Design contract

Purchase Registry Phase 1 is an additive purchasing ledger. It does not replace or
convert the legacy `orders`, `receiving_batches`, or `order_received_instances`
workflow. In particular, `THS-ORD-000001` remains the pending Overture filament
order and keeps its existing behavior.

Migration `013_purchase_registry_foundation.sql` adds:

- `purchase_vendors`;
- extensible `purchase_categories`;
- `purchase_orders` with permanent `THS-PO-######` identity;
- immutable `purchase_order_lines`;
- immutable `purchase_history`.

The seeded categories are Filament, Maintenance Parts, Printer Parts, Tools,
Electronics, Consumables, Shipping, Tax, and Miscellaneous. Categories are data,
not a closed SQL enum, so future shops can extend them without changing the core
model.

Money is stored only as integer cents. A purchase starts in `ordered` status.
`partially_received`, `received`, and `canceled` are reserved for later controlled
workflows. Phase 1 does not implement evidence, receipts, inventory receiving,
maintenance linkage, dashboards, analytics, reorder logic, or cost accounting.

## Controlled create workflow

`PurchaseRegistryService.review_create` validates the vendor, date, currency,
categories, tracking intent, quantities, line arithmetic, subtotal, tax, shipping,
discount, and total. It proposes the next permanent number and returns an expiring
HMAC-signed preview with a unique request nonce. Review performs zero writes.

`commit_create` requires explicit confirmation and opens `BEGIN IMMEDIATE`. It
verifies the signature and age, rejects a used nonce, rechecks the permanent-number
sequence, existing-vendor snapshot, category and catalog tracking state, and all
signed arithmetic. The vendor, purchase, lines, and immutable history snapshot are
then committed atomically. Any failure rolls back the entire operation.

Read-only list and detail queries expose purchase headers, vendors, categorized
lines, and immutable history for verification without adding a dashboard.

## Migration safety checklist

Before migration 013 is ever applied to production:

1. Stop the dashboard and verify no process has the database open for writes.
2. Record the source path, size, SHA-256, migration count, and SQLite integrity.
3. Create a timestamped byte-preserving backup outside Git and verify its SHA-256.
4. Run `purchase_foundation_dry_run` against the live database. It migrates only a
   temporary copy.
5. Require migration 013 to be the only pending migration.
6. Compare row counts and canonical content hashes for legacy orders, receiving,
   inventory, AMS, print, maintenance, open-spool, and audit tables.
7. Require exactly five purchase tables, nine seeded categories, and integrity
   result `ok`.
8. Apply only after a separate explicit production approval.
9. Verify the schema advances exactly one migration and a second attempt reports
   already current.
10. Repeat protected-table fingerprints and SQLite integrity after application.
11. Confirm no purchase, vendor, line, or purchase-history production row was
   created by the migration.
12. Keep the live database, backups, screenshots, and evidence outside Git.

## Phase 2 boundary

The next proposed phase is immutable SHA-256 purchase evidence with its own signed
preview and explicit confirmation. Purchase receiving and inventory integration
remain separate later checkpoints.
