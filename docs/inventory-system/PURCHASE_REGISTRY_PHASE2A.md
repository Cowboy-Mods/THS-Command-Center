# Purchase Registry Phase 2A

Phase 2A adds immutable purchase evidence and controlled maintenance linkage. It
does not create purchases, receive orders, create inventory, record delivery,
or mark parts installed or consumed.

## Evidence boundary

`purchase_evidence` stores an external file's absolute path, SHA-256, byte size,
type, and immutable metadata. `evidence_scope` is mandatory:

- `purchase` proves ordering, price, or payment;
- `delivery` proves arrival or physical condition.

Neither scope receives inventory. A delivery photo is still only evidence until a
separate receiving workflow commits physical inventory.

Evidence review hashes the existing file and performs zero writes. The signed
preview expires and contains a unique nonce. Explicit confirmation opens an
immediate transaction, revalidates the purchase state, recomputes SHA-256 and file
size, inserts immutable evidence, and appends immutable purchase history. Changed,
missing, stale, tampered, expired, or replayed previews fail.

## Maintenance linkage boundary

`purchase_maintenance_links` records a controlled relationship between a purchase,
an optional purchase line, and a permanent maintenance record. Relationship types
are required part, corrective replacement, spare stock, and maintenance supply.

A link means only that the purchase is relevant to maintenance. It does not mean
the item arrived, entered inventory, was installed, or was consumed. The signed
preview and explicit-confirmation rules match evidence registration.

## Migration safety

Migration `014_purchase_evidence_maintenance_links.sql` adds the two immutable
tables and extends `purchase_history` to include `link_maintenance`. Its dry run:

1. migrates only a temporary copy;
2. requires migration 014 to be the only pending migration;
3. verifies SQLite integrity and exactly one schema advancement;
4. fingerprints all legacy operational and Purchase Registry Phase 1 tables;
5. requires all fingerprints to remain unchanged;
6. requires zero evidence and maintenance-link rows;
7. verifies a second attempt reports already current.

The live migration requires a separate timestamped backup, preview, and explicit
approval.

## Production state and deferred work

- Bambu purchase `THS-PO-000001` is created and remains Ordered.
- Its immutable purchase evidence and two maintenance relationships are recorded.
- Receiving any Bambu item
- Creating inventory from a purchase
- Recording installation or consumption
- Purchase Registry Receiving and Status Transitions
- Historical purchase backfill and reconciliation
