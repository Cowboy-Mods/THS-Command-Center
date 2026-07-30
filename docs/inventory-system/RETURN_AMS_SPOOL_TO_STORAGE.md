# Return AMS Spool to Storage

This controlled workflow records one physically verified unload from an AMS slot to an active non-AMS storage location.

## Safety contract

- Only an active Loaded spool with a current AMS assignment can be selected.
- Only active storage locations outside equipment slots are offered.
- The preview performs zero writes and shows the exact permanent ID, AMS source, destination, state transition, and preserved remaining weight.
- Explicit physical verification and final confirmation are required.
- Confirmation creates one unload transaction and immutable action record, closes the active AMS assignment, moves the spool, and changes its state from Loaded to Open.
- Remaining and original quantities are never changed.
- A request nonce rejects replayed confirmation.
- A changed spool, assignment, or destination invalidates the preview.
- Any failure rolls back the unload, move, transaction line, and audit record together.

## Implemented

- Dashboard and global Controlled Workflows navigation
- Responsive form, preview, completion, and safe error pages
- Signed, expiring, canonical preview tokens
- Atomic service integration through `InventoryActionService.unload_instance_from_ams`
- Automated coverage for validation, replay, stale previews, rollback, navigation, and weight preservation

## Deferred

- Moving an already-open wall spool between general storage locations
- Correcting remaining grams
- Setting stock minimums and targets
- Automated printer or AMS synchronization
