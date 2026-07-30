# Flexible Active-Spool Replacement Service

This checkpoint adds the schema-19 service boundary for flexible active-spool
replacement. It does not change the guided UI and cannot be reached through a
dashboard route yet.

## Service contract

`InventoryActionService.flexibly_replace_active_filament_spool` accepts:

- one actively loaded outgoing spool;
- outgoing disposition `empty`, `storage`, or `ams_slot`;
- an optional outgoing storage or AMS destination appropriate to that
  disposition;
- incoming disposition `sealed`, `open`, or `none`;
- a nullable incoming permanent inventory-instance identity;
- exactly one incoming source location or AMS slot when an incoming spool
  exists;
- a nullable incoming destination slot for the truthful no-replacement case;
- actor/module/origin context, a unique review nonce, and optional operational
  notes.

The existing `replace_active_filament_spool` method remains unchanged. Legacy
sealed-only callers continue to populate `replacement_instance_id` and
`destination_slot_id` while leaving all Migration 019 fields null.

## Validation

The service validates the full intended final layout before writing:

- the outgoing spool is active and loaded in one AMS slot;
- an empty spool has no destination;
- storage return targets an active `storage` location;
- an AMS move targets a different active AMS slot;
- no replacement has no incoming identity, source, or destination;
- sealed incoming spools are active, sealed, and at their stated location;
- open incoming spools are either open at their stated location or loaded in
  their stated AMS source slot;
- outgoing and incoming identities differ;
- each incoming source matches current authoritative state;
- final outgoing/incoming destination slots are distinct;
- an occupied destination is accepted only when its occupant is vacated by the
  same workflow.

The existing partial unique indexes remain the final database enforcement for
one active spool per AMS slot and one active AMS slot per spool.

## Atomic behavior

One parent `inventory_workflow_transactions` row is written with only the
explicit Migration 019 disposition fields. All child actions carry the parent
`workflow_transaction_id`.

The service then performs the required child actions inside the same nested
savepoint:

1. empty or unload the outgoing spool;
2. unload an incoming spool when it originates in another AMS slot;
3. load the outgoing spool when it moves to another slot;
4. open a sealed incoming spool;
5. load the incoming spool when one exists.

This ordering permits an intentional two-slot swap while rejecting unrelated
occupied destinations. Any validation, transaction, assignment, or audit
failure rolls back the parent workflow, every child action, every transaction
line, every state change, and every AMS assignment.

## Audit behavior

The parent record separately preserves:

- outgoing disposition and destination;
- incoming disposition, permanent identity, source, and destination;
- actor, module, origin, reason, review nonce, and optional print context.

Child actions independently preserve each spool's before/after state and
location:

- `mark_spool_empty`;
- `unload_instance_from_ams`;
- `open_sealed_spool`;
- `load_instance_into_ams`.

Permanent `THS-FIL` identities are never changed, deleted, or recreated.

## Focused validation

`tests/test_flexible_replacement_service.py` covers:

1. empty outgoing plus sealed incoming;
2. partial outgoing to storage plus sealed incoming;
3. partial outgoing to storage plus already-open incoming;
4. partial outgoing moved to another AMS slot;
5. no replacement with the source slot left empty;
6. unrelated occupied-destination rejection;
7. incoming source mismatch and duplicate-identity rejection;
8. rollback when a child audit fails;
9. separate parent and child audit capture for both spools and locations;
10. an atomic two-slot swap;
11. unchanged legacy sealed-replacement behavior.

Results:

- New focused service tests: 11 passed
- Wider filament/service suites: 144 passed
- Full regression suite: 306 passed

## Production boundary

Production remains at schema 18. Migration 019 was not applied, the new method
was not called against production, and no UI route calls it.

`THS-FIL-000032` and `THS-FIL-000039` remain unchanged. Their real-world
correction is not part of this checkpoint.

## Next checkpoint

The guided UI checkpoint should add:

- schema-19 availability gating;
- a signed, zero-write preview that binds every current state and destination;
- outgoing and incoming disposition controls;
- eligibility-filtered storage, spool, and AMS-slot choices;
- stale-state, tamper, replay, and sequence protection;
- a final confirmation page showing every child action;
- the requested workflow-level and HTTP tests.

Only after the UI and preview are validated should the system produce a
zero-write production correction preview. Production migration and correction
must remain separately authorized actions.
