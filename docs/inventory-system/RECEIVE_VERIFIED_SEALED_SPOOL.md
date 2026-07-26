# Receive a Verified Sealed Spool

## Scope

This is the first and only editable dashboard workflow. It receives exactly one new verified sealed filament spool. It does not edit existing inventory, correct quantities, manage AMS assignments, open spools, or provide general product management.

Route: `/inventory/filament/receive`

## Workflow

1. Select an existing complete filament catalog product, or enter all required verified specifications for a new product.
2. Select an active storage location, identify the actor, and optionally record a reason.
3. Review every value before any write occurs.
4. Preview the next permanent `THS-FIL` ID.
5. Explicitly confirm that the values were checked against the physical spool.
6. Commit the product setup, physical instance, inventory transaction, transaction line, and immutable action history atomically through `InventoryActionService`.
7. Display the completed permanent ID, product, status, location, transaction ID, audit action ID, actor, module, timestamp, and reason.

The review page shows manufacturer, product line, material, color, diameter, nominal weight, sealed status, location, permanent ID, actor, module, and optional reason.

## Validation and safety

- Only the individual-tracked `Filament` item type is accepted.
- Existing products must have material, manufacturer color, diameter, and nominal weight.
- New products require all those verified fields.
- Diameter must be finite and between 1 and 10 mm.
- Nominal filament weight must be finite and between 1 and 100,000 g.
- Only active storage locations are accepted.
- Actor is required; module is fixed to `filament-receiving-ui`.
- Status is fixed to `sealed`, condition to `new`, and verified to true.
- Review data is signed by the running application and expires after 30 minutes.
- Tampered, expired, incomplete, or stale reviews are rejected without writes.
- Confirmation requires an explicit checkbox.
- The commit begins an immediate SQLite transaction and verifies that the previewed permanent ID is still next. If inventory changed, the user must review again.
- Existing spools are never updated by this workflow.

New manufacturers, catalog products, and catalog attributes are created only through the Inventory Action Service. The physical spool is created with `add_individual_instance`, which also creates the inventory transaction, transaction line, and immutable audit action.

## Verification

`tests/test_receive_spool.py` covers the form boundary, complete preview, zero-write review, strict fields, confirmation requirement, tamper rejection, stale preview rejection, existing-product receiving, new-product creation, catalog attribute auditing, transaction/audit linkage, audit immutability, completion summary, HTTP method restrictions, and proof that existing spools do not change.

The full suite contains 93 passing tests.

## Next checkpoint

Implement **Open Existing Sealed Spool** as a second narrow confirmed workflow.

The real-world first target is one of the two seeded Bambu Lab PLA Basic Orange spools for the modified Tweety Bird hat with an orange THS logo. The future workflow must select one specific `THS-FIL` ID, preview the change, record the project or reason, change only that spool from sealed to open through the Inventory Action Service, and leave the second seeded Orange spool sealed.

