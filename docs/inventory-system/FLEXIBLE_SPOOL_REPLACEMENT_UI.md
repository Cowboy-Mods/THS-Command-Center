# Flexible Active-Spool Replacement — Guided UI

The guided replacement route now uses Migration 019's explicit disposition
model and the flexible replacement service. Production use remains disabled
until Migration 019 is separately authorized and deployed.

## Guided choices

The form presents three controlled sections.

### 1. Outgoing active spool

Select one authoritative loaded spool and one result:

- **Empty** — remove it from the AMS and mark it Empty.
- **Return to storage** — unload it, preserve Open status and quantity, and
  select an active open-spool storage location.
- **Move to another AMS slot** — unload it and select a different AMS slot.

Only the destination appropriate to the selected disposition may be supplied.

### 2. Incoming outcome

Select:

- **Sealed** — choose the permanent spool identity and its current storage
  source; the service opens and loads it.
- **Open** — choose the permanent spool identity and exactly one authoritative
  storage or AMS source.
- **None** — leave identity, source, and incoming destination null.

### 3. Destination and context

An incoming spool defaults to the outgoing spool's prior slot. Another AMS slot
may be selected. An occupied destination is rejected unless its current spool is
vacated by the same atomic workflow, enabling a verified two-slot swap.

Actor is required. Reason and print-event context remain optional.

## Zero-write final review

The workflow controller does not reimplement inventory rules. It asks
`InventoryActionService.preview_flexible_spool_replacement` to execute the exact
service operation inside an outer savepoint, captures the stable plan, and rolls
the savepoint back.

The signed version-2 review binds:

- outgoing permanent identity and authoritative AMS assignment;
- outgoing disposition and destination;
- incoming permanent identity, state, source, and assignment;
- incoming disposition and destination;
- the ordered child-action plan;
- actor, reason, print context, nonce, and review time.

Confirmation begins an immediate transaction, rejects an already-used nonce,
regenerates the zero-write service plan, compares it with the signed plan, and
only then calls the real atomic service. Changed, tampered, expired, or replayed
state produces a friendly 422 page and no partial writes.

## Compatibility and safety

- Version-1 signed reviews and the original sealed-only form contract remain
  readable and committable.
- Version-1 commits continue using the legacy sealed-replacement service and
  legacy workflow columns.
- Version-2 commits use only explicit Migration 019 fields.
- A schema-18 database shows a safe “Migration 019 required” page without
  exposing the flexible form.
- Permanent `THS-FIL` identities are never changed.
- Business validation and transaction ordering remain in the action service.

## Test evidence

`tests/test_flexible_replacement_ui.py` adds 12 focused scenarios:

1. all outgoing/incoming/source/destination controls render;
2. no-replacement final review is clear and zero-write;
3. validation errors are friendly and zero-write;
4. sealed incoming defaults to the outgoing source slot;
5. open incoming source and load;
6. outgoing AMS move;
7. successful two-slot swap;
8. stale review rejection;
9. tamper, replay, and explicit-confirmation protection;
10. complete rollback after a child failure;
11. legacy form/review/completion compatibility;
12. schema-18 production safety gate.

Results:

- Focused guided UI: 12 passed
- Wider UI/filament suites: 183 passed
- Full regression suite: 318 passed

## Checkpoint boundary

Migration 019 was not applied to production. No production spool, assignment,
equipment, telemetry, purchase, or receiving data was changed.

The next checkpoint should be the separately controlled production deployment
of Migration 019. A correction preview for `THS-FIL-000032` and
`THS-FIL-000039` must remain a later zero-write checkpoint requiring explicit
approval before commit.
