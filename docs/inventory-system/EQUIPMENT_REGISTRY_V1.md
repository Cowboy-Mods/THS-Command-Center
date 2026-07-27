# Equipment Registry v1

Migration `018_equipment_registry_v1.sql` adds the source-only Equipment Registry
foundation. It is additive and seeds reference vocabulary only. It creates no
real equipment, telemetry, relationship, connection, purchase-link, or
receipt-link rows.

## Permanent identity

Every registered physical asset receives an immutable UUID and permanent
`THS-EQP-######` number. Display names, locations, manufacturer serial numbers,
and THS builder identifiers are attributes; none replaces registry identity.
The legacy `equipment` and `equipment_slots` tables remain the authoritative AMS
slot structure until individually verified bridge records are approved.

Initial equipment types cover 3D printers, AMS units, external cameras, sensor
modules, Raspberry Pi/console assemblies, network equipment, and other shop
machines.

## Stable facts, telemetry, readiness, and restrictions

Stable equipment records contain manufacturer/model, serial attributes,
type/subtype, location, lifecycle, operational status, commissioning/retirement
facts, notes, and a state version.

These concepts remain separate:

- operational status is a controlled equipment projection;
- maintenance readiness remains on `maintenance_assets` and is joined through
  an explicit bridge;
- restrictions are derived from readiness;
- live telemetry is replaceable, freshness-aware integration state and cannot
  alter equipment, maintenance, production, inventory, or AMS assignment facts.

`BambuPrinterIntegrationService`, `CameraViewingGateway`, and
`PrintJobCorrelator` are protocol seams only. No Bambu API, MQTT, polling,
camera streaming, or credential persistence is implemented.

## Cameras and embedded capabilities

The P1S built-in camera is represented as `camera.builtin`, plus an embedded,
non-independently-tracked component installation under the printer. It receives
no separate equipment identity. Time-lapse, telemetry, and manufacturer
integration support are stable capability records.

External printer-monitoring cameras and room cameras are independent equipment
records. Stream availability is telemetry. Stream credentials and tokens are
forbidden from general capability metadata.

## Relationships and connections

One child may have one current physical/management parent in v1. Attach, move,
and detach operations update the current projection and append immutable
history. Self-parenting and cycles are rejected. Moving a child preserves its
identity and every previous relationship event.

Network support is normalized into:

- supported stable capabilities;
- physical, logical, or radio interfaces;
- actual current connection state;
- immutable connection history.

Ethernet data and PoE power roles remain distinct.

## Purchase and receiving provenance

Purchase and receipt links are immutable provenance only.

**Receiving represents verified physical arrival only. Receiving shall never
imply installation, opening, assignment, loading, usage, or consumption. Those
remain separate controlled workflows.**

Equipment provenance never implies arrival, installation, assignment,
commissioning, activation, operational status, readiness, or inventory state.

## Controlled writes

Future registration and parent/child changes use HMAC-signed, expiring,
zero-write previews. Permanent numbers, UUIDs, state snapshots, and request
nonces are preview-bound. Explicit confirmation opens `BEGIN IMMEDIATE` and
rejects stale state, tampering, replay, duplicates, cycles, and sequence
conflicts. Successful commits append immutable equipment-specific history and a
general audit event atomically.

## Read-only projections

`InventoryQueries` exposes:

- `equipment_list`;
- `equipment_detail`;
- `equipment_relationships`;
- `equipment_connections`.

These methods open the existing read-only SQLite connection. They do not poll
devices or perform equipment writes.

## Production boundary

Source development and tests use temporary databases. Before production:

1. stop the application and verify no writer remains;
2. capture the live path, size, SHA-256, schema list, integrity, foreign keys,
   protected counts, and protected content fingerprints;
3. create and verify a timestamped byte-preserving backup outside Git;
4. apply Migration 018 to a temporary byte copy and verify the full preview;
5. require Migration 018 to be the only pending migration;
6. obtain explicit Checkpoint C authorization;
7. apply only Migration 018;
8. verify schema 18, zero equipment/telemetry rows, unchanged protected
   fingerprints, application health, tests, and rollback readiness.

Schema migration does not authorize onboarding the P1S, AMS units, cameras,
sensors, consoles, network equipment, or any purchase.
