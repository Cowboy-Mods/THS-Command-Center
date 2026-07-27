# Purchase Registry Receiving and Status Transitions

## Design rule

**Receiving represents verified physical arrival only. Receiving shall never
imply installation, opening, assignment, loading, usage, or consumption. Those
remain separate controlled workflows.**

Purchase, shipment, delivery, receiving, inventory creation, maintenance
relevance, installation, usage, and consumption remain separate facts.
Delivery-scoped evidence proves an event but never performs an inventory change
by itself.

## Source-only checkpoint

Migration `017_purchase_registry_receiving.sql` adds Purchase Registry receiving
without modifying the legacy `orders`, `receiving_batches`, or completed
`THS-ORD-000001` workflow.

The migration adds:

- a controlled fulfillment projection and immutable transition history;
- immutable purchase receipt headers and line-specific receipt rows;
- immutable delivery-evidence links;
- immutable receipt-to-inventory links;
- derived per-line received and outstanding quantities;
- a derived purchase status view.

Receipt tables contain no subtotal, tax, shipping, discount, or line-total
columns. Money remains on the immutable purchase header and lines, preventing
receipt processing from counting it twice.

## Status model

Before receiving, controlled transport transitions are:

- Ordered to Shipped;
- Ordered to Delivered when delivery is verified but shipment timing remains
  unknown;
- Shipped to Delivered;
- Ordered, Shipped, or Delivered to Canceled only when no quantity was received.

Partially Received and Received are derived from immutable receipt-line totals.
A partially or fully received purchase cannot be canceled by this workflow.
Line cancellation, short shipment, returns, corrections, installation, and
consumption require separate future designs.

## Line-specific receiving

Every signed preview binds the exact purchase snapshot, line snapshots,
outstanding quantities, delivery evidence, catalog tracking policies, locations,
permanent UUIDs, THS IDs, and current sequences. Preview performs zero writes.

Commit revalidates every bound fact inside one `BEGIN IMMEDIATE` transaction.
Zero, duplicate, excess, stale, tampered, expired, replayed, and
sequence-conflicted receipts fail without partial writes.

Tracking behavior is explicit:

- `individual` creates one permanent inventory instance per accepted unit;
- `quantity` creates verified pooled stock without THS asset IDs;
- `lot` creates a distinct verified stock lot;
- `non_inventory` records physical completion without creating stock.

All inventory creation passes through `InventoryActionService`. A failed
receipt, evidence link, inventory action, history entry, or status projection
rolls back the entire commit.

## Evidence and maintenance

Receiving requires existing delivery-scoped Purchase Registry evidence. The
external file path, SHA-256, and byte size are signed during review and
revalidated immediately before commit. Purchase-only evidence cannot prove
physical arrival.

Existing purchase-maintenance links remain relevance links. Receiving a linked
part does not change maintenance status and does not mark the part installed or
used.

## Production boundary

Source development and tests use temporary databases only.
`THS-PO-000001` and production inventory must remain unchanged.

Before production migration:

1. stop and verify the dashboard process;
2. record the live database path, size, SHA-256, migrations, counts, and
   integrity;
3. create and verify a timestamped byte-preserving backup outside Git;
4. run the purchase-receiving preview against a temporary copy;
5. require migration 017 to be the only pending migration;
6. verify protected content fingerprints are unchanged;
7. verify receipt, link, and history tables remain empty;
8. obtain separate explicit approval before applying migration 017.

Schema migration does not authorize catalog setup or receiving. Catalog
resolution and any real `THS-PO-000001` receipt each require their own signed
preview and explicit approval.
