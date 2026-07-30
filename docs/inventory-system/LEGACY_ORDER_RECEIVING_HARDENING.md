# Legacy Order Receiving Hardening

Migration `016_legacy_order_receiving_hardening.sql` prepares the existing
full-order receiving workflow for truthful, evidence-backed receipts. It is
additive and does not receive an order or modify catalog data when applied.

## Receipt time semantics

`receiving_batches.received_at` remains the legacy system-write timestamp for
backward compatibility. New receipts separately store the physical receipt
date, nullable physical time, precision (`exact`, `estimated`, `date_only`, or
`unknown`), and system `recorded_at` commit timestamp.

A `date_only` receipt requires a date and a NULL time. Commit time, file
timestamps, and server time are never substituted for an unknown physical time.

## Controlled catalog correction

`CatalogCorrectionWorkflow` produces a signed, expiring, zero-write preview
containing the current snapshot, proposed identity, actor, reason, nonce, and
permanent history UUID. Commit revalidates the current snapshot, preserves the
catalog item ID and dependencies, updates the approved identity in place, and
appends immutable `catalog_item_history`. Tampered, expired, stale, or replayed
previews fail.

The signed current and proposed snapshots include the complete exact dependent
order set rather than only a count. Each order ID, order number, catalog link,
state, expected quantity, and received quantity must remain unchanged.

Supporting legacy delivery evidence is also bound into the signed snapshot by
internal ID, UUID, order, scope, type, external path, stored SHA-256, and stored
size. Preview and commit both re-hash the external files. A missing, substituted,
reassigned, or changed record invalidates the correction.

The optional `filament_form` attribute distinguishes a refill coil from a
reusable spool without creating a duplicate catalog item. This controlled
workflow currently accepts only the canonical `Refill coil` value, with safe
case and whitespace normalization.

Normalized catalog identity conflicts are queried during preview and commit,
excluding the item being corrected. This provides a clear controlled-workflow
error before the database uniqueness boundary.

## Delivery evidence linkage

`receiving_batch_delivery_evidence` links a batch to one or more existing
legacy delivery-evidence rows. Restrictive foreign keys, same-order validation,
uniqueness, and immutable triggers protect the relationship.

The signed receipt includes evidence snapshots and preview-generated link UUIDs.
Commit revalidates the rows and immediately recalculates each external file's
size and SHA-256. Missing or changed proof rejects the whole receipt.

## Full-order and atomic rules

This workflow receives exactly the outstanding quantity. Partial, excess, zero,
repeated, and already-completed receipts are rejected. Partial receiving remains
out of scope and requires a separate future design.

The preview generates the batch UUID, permanent THS-FIL IDs, and evidence-link
UUIDs. Commit revalidates state and sequence and uses those identities unchanged.
One immediate transaction creates the batch, sealed instances, transactions,
lines, actions, order-instance links, evidence links, audit, and final order
update. Any failure rolls back everything. No AMS or reusable-spool assignment
is created.

Production migration, catalog correction, and actual receipt remain three
separate approval checkpoints.
