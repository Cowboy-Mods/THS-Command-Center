# Printer Maintenance Registry and Backlog

Migration `012_maintenance_registry.sql` adds a permanent maintenance registry
without changing or deleting the earlier Stage 2 maintenance-event history.

## Controlled write model

Every workflow begins with a zero-write, signed preview. The user must explicitly
confirm before the service opens one atomic database transaction. Each committed
transition appends an immutable `maintenance_history` snapshot with a unique
request nonce, preventing replay and preserving the state before and after the
change.

Supported workflows:

- Record Fault Discovered
- Create Maintenance Task
- Mark Waiting for Part
- Complete Maintenance
- Verify Repair
- Reopen Maintenance Task

`maintenance_records` contains the current controlled projection used by the
backlog. Identity fields cannot change, records cannot be deleted, and every
allowed status/readiness update is represented permanently in
`maintenance_history`.

## Equipment and readiness

`maintenance_assets` provides a common registry for printers and related shop
equipment. Existing `printers` and `equipment` rows are linked during migration.
Readiness is one of normal, monitor during printing, no unattended printing, or
out of service.

## Evidence

Photos and videos use the Print Registry approach: an absolute source path plus
SHA-256 digest is stored. Evidence rows are immutable and cannot be deleted.

## Production checkpoint

Development and tests use temporary databases only. Before migration 012 is
applied to the live runtime database, create and verify a timestamped backup,
capture protected before/after counts, apply only the pending migration, and
verify SQLite integrity. The real P1S event must not be entered until Cowboy
explicitly approves that separate checkpoint.
