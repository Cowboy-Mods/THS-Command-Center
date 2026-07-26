# Register Existing Open Spool

This controlled workflow registers one physical filament spool that was already
open before THS inventory tracking began. It does not replace or modify the
sealed-spool receiving workflows.

## Safety contract

- Preview performs zero writes.
- Final confirmation creates one permanent `THS-FIL-######` identity.
- The inventory instance, transaction, inventory action, optional AMS load, and
  immutable registration ledger commit atomically.
- A signed preview expires and cannot be replayed.
- Similar active spools produce a duplicate warning. The workflow still permits
  a second legitimate same-brand, same-material, same-color physical spool after
  explicit acknowledgement.
- Registration history cannot be updated or deleted in SQLite.

## Quantity rules

| Mode | Stored remaining quantity | Required confidence | Note |
|---|---:|---|---|
| Exact | Verified grams | Weighed | Optional |
| Estimated | Estimated grams | Manufacturer estimate or visual estimate | Required |
| Unknown | `NULL` in the registration ledger | Unknown | Required |

The legacy inventory instance table requires a non-null numeric quantity.
Unknown legacy spools therefore use `0` only as a non-counting compatibility
placeholder. The registration ledger, spool detail, and AMS display remain
authoritative and show **Unknown**, never zero grams or an assumed 1,000 g.

## Initial location

The user may register the spool directly into an empty AMS slot. The workflow
creates the open spool and the AMS load within the same transaction. The user
may instead choose active storage and load the spool later using the existing
verified AMS workflow.
