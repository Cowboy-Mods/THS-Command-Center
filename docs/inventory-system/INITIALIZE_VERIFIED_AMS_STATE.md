# Initialize Verified AMS State

## Purpose

This narrow operational-readiness workflow establishes one positively identified physical filament spool in one existing, physically verified AMS slot before normal replacement workflows are used.

It is not a general AMS editor. It cannot create inventory, rename equipment, invent slots, edit weight, remove assignments, or change arbitrary spool fields.

Route: `/inventory/filament/ams/initialize`

## Eligibility

The workflow lists only active individual filament spools that:

- have a permanent `THS-FIL` ID;
- are currently Sealed or Open;
- are not archived;
- do not already have an active AMS assignment.

Empty, Archived, Loaded, inactive, and already-assigned spools are rejected. AMS names and slot numbers come only from configured active `equipment` and `equipment_slots` records.

## Controlled state transitions

- Sealed spool: `Sealed â†’ Open â†’ Loaded`
- Open spool: `Open â†’ Loaded`

`load_instance_into_ams` now requires an active Open spool. A sealed spool cannot be falsely loaded without a separate immutable Open action first.

The workflow never changes original or remaining filament weight.

## Preview and confirmation

The preview shows:

- permanent `THS-FIL` ID;
- manufacturer, product line, material, and color;
- current spool state;
- controlled state transition;
- configured AMS unit and slot;
- effective workshop timestamp;
- actor, module, and optional reason;
- explicit statement that weight is unchanged.

Preview performs zero writes. A second explicit checkbox is required to commit.

Review data is signed, expires after 30 minutes, and contains a unique request nonce. Tampered, expired, stale, duplicate, occupied-slot, and replayed submissions are rejected.

## Effective timestamp

The user may enter when the physical load actually occurred. The browser field is interpreted in `America/Indiana/Indianapolis` unless an explicit offset is supplied.

The validated RFC3339 timestamp is written consistently to:

- `ams_assignments.loaded_at`;
- the load `inventory_transactions.occurred_at`;
- the load `inventory_actions.occurred_at`;
- the Open transaction and audit when a sealed spool must be opened first.

Future timestamps and timestamps before year 2000 are rejected. The timestamp records operational occurrence; it does not fabricate identity or slot information.

## Atomic service behavior

`InventoryActionService.initialize_verified_ams_state` owns the operation.

For a sealed spool it creates:

1. immutable `open_sealed_spool` action and transaction;
2. immutable `load_instance_into_ams` action and transaction;
3. transaction lines;
4. active AMS assignment.

For an already Open spool, only the load action, transaction, line, and assignment are created.

All work is enclosed by one outer transaction with nested service savepoints. If any assignment, transaction, line, audit, timestamp, or constraint step fails, everything rolls back.

Migration `007_verified_ams_initialization.sql` adds a unique optional request nonce to `inventory_actions` for replay prevention. It also adds optional print-event metadata fields to replacement workflow parents.

## Historical replacement readiness

The two physical replacement events cannot yet be entered as full historical replacement workflows unless Cowboy positively identifies:

- the outgoing White and Orange `THS-FIL` records;
- the exact AMS unit and slot for each event;
- the Jade White and Orange replacement `THS-FIL` records.

No identity or slot may be guessed.

If only the currently loaded Jade White and Orange replacements can be positively identified, this workflow can accurately establish their present AMS assignments with verified effective timestamps. That does not reconstruct the unidentified outgoing spool history.

The Orange replacement is verified as having occurred at layer 283. One of the two Bambu Lab PLA Basic Orange spools is now physically opened and loaded, leaving one sealed reserve after the controlled workflow is committed. Permanent spool identity and the exact AMS slot must still be verified rather than inferred. The one-spool sealed reserve is a future shopping/reorder-list requirement, not an authorization for this initialization workflow to create a reorder rule.

The ordered Overture White bulk box is not inventory. Receive it only after arrival and verification of actual count and condition. If it contains four acceptable refills, a future receiving workflow must create four individual physical instances linked to one purchase or receiving batch. Enter non-Bambu filament manually in Bambu Studio and preserve its verified identity in THS Inventory; do not design this workflow around transferred Bambu RFID tags.

## Testing

`tests/test_initialize_ams.py` covers zero-write preview, expiry, tampering, replay, occupied slots, duplicate assignments, both state paths, invalid states, backdated time, unchanged weight, service-created assignment/transaction/line/audit records, immutability, atomic rollback, responsive structure, confirmation, and proof that no filament inventory is created.

The complete suite contains 125 passing tests.

