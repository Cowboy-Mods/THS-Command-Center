# Purchase-Line Tracking Corrections

## Boundary

Purchase orders and purchase-order lines remain immutable procurement history.
Their original `inventory_tracking_intent`, descriptions, quantities, prices,
tax, and vendor facts are never rewritten by receiving setup.

Migration `020_purchase_line_tracking_corrections.sql` adds an append-only
correction record for the narrow case where a verified physical item needs a
different inventory tracking policy than the original purchase line recorded.
The correction stores both policies, the reason, actor, module, origin,
provenance, signed-preview payload hash, and database timestamp.

One purchase line can have at most one correction. Database uniqueness and
immutable update/delete triggers prevent duplicate, contradictory, or rewritten
correction history. A line that already has a receipt cannot be corrected.

## Effective policy

`purchase_order_lines_effective` exposes the immutable source intent, corrected
effective policy, and correction identity/timestamp. Purchases without
corrections behave exactly as before.

Receiving snapshots and revalidation use the effective policy. The selected
catalog item must use that same policy, so an effective `quantity` line creates
a `stock_lots` record and never creates a permanent inventory-instance ID.

Corrections use `PurchaseLineCorrectionService.review()` followed by
`commit(..., confirmed=True)`. Review is signed, expiring, replay-protected and
zero-write. Commit revalidates every source line and applies the whole batch
inside `BEGIN IMMEDIATE`; any failure rolls back every correction.

## THS-PO-000001 planned correction

Order `THS-PO-000001`, vendor order `us757917111581409281`, requires all nine
lines to have effective policy `quantity` before receiving: four Bambu Lab 1 kg
sealed filament refills plus FAC224, FAC023, LGL001, FAZ031, and FAW001.

This migration does not insert those corrections and does not touch production.
A later production checkpoint must generate an exact nine-line zero-write
preview against the verified live database and require explicit approval before
commit.

The four refills are nonserialized sealed stock. They must create quantity stock
lots at the existing `Sealed Filament Rack`, not `THS-FIL-######` inventory
instances and not AMS assignments. When mounted later, the separate
spool-replacement workflow associates the material with an existing permanent
spool identity and moves it to the existing `Open-Spool Wall`.

## Cabinet locations

`InventoryActionService.ensure_location()` is the controlled, audited,
idempotent location write boundary. Create `Parts Cabinet 1` under `Workshop`,
then create `PC1-L5` and `PC1-R5` beneath that cabinet. The active parent/name
uniqueness constraint prevents equivalent duplicates and rejects conflicts.

## Receiving prerequisites

Correction is not delivery proof and does not receive inventory. Before this
order can be received, a separate external delivery-evidence file must be
registered with `evidence_scope='delivery'`. Review and commit bind and
revalidate its absolute path, SHA-256, and byte size.

Production also requires exact quantity-tracked catalog records for all nine
SKUs, the cabinet locations, a fresh checksum and integrity preflight, a verified
backup, exact zero-write correction and receipt previews, and separate explicit
approvals.
