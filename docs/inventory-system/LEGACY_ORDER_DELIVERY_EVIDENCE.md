# Legacy Order Delivery Evidence

Migration `015_legacy_order_delivery_evidence.sql` adds immutable external-file
evidence for the original `orders` workflow without converting those records
into the newer Purchase Registry.

## Boundary

Delivery evidence proves what physically arrived. It does not:

- change an order state or received quantity;
- create a receiving batch or inventory;
- create inventory actions or transactions;
- mark an item stored, opened, loaded, installed, used, or consumed.

Evidence bytes remain outside SQLite and Git. The registry stores an absolute
path, SHA-256, byte size, caption, optional captured time and privacy-safe JSON
metadata.

## Controlled transaction

Review requires an existing absolute path and calculates SHA-256 and size without
writing. The signed preview contains the permanent evidence UUID, order snapshot,
file identity, unique nonce, actor, and expiration time.

Commit requires explicit confirmation, revalidates the order, rehashes the file,
rejects duplicates and replay, and atomically inserts both evidence and immutable
history. Update and delete triggers protect both tables.

Multiple distinct evidence files may belong to one legacy order. Foreign keys to
the legacy order and evidence record use restrictive deletion behavior.

## Privacy

Shipping labels may remain visible only inside the unchanged protected image.
Captions and optional metadata reject common address, telephone, email, and
tracking-number labels. The workflow never changes ordinary legacy order notes.

## Production procedure

Production use requires a separate schema-14 backup, migration-015 dry run,
protected-table fingerprint comparison, explicit live-migration approval, and
then separate signed previews for each evidence file.
