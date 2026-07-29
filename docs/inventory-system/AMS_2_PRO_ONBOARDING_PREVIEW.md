# Bambu Lab AMS 2 Pro Onboarding — Zero-Write Preview

Date: 2026-07-29  
Branch baseline: `feature/filament-manager-v1` at
`03537f02cd55bee1fc4eca7d01cbc1aaa9947e72`  
Production database:
`C:\Users\Cowboy\Documents\THS-Command-Center-Data\inventory.sqlite3`  
Mode: read-only inspection and source-only preview

## Stop boundary

This report is not authorization to onboard equipment. It creates no
Equipment Registry records, relationships, legacy-container links, slots,
assignments, telemetry, or audit rows.

The reported serials below must be verified character-for-character against
the physical labels before any production write:

- AMS 1 reported serial: `19C-06A-522-00-22-97`
- AMS 2 reported serial: `19C-51A-6-204-00 EWR`

The space before `EWR` is preserved exactly as reported. It is not assumed to
be correct.

## Production safety result

| Check | Result |
|---|---|
| Schema | 19 |
| Latest migration | `019_flexible_spool_replacement.sql` |
| SQLite quick check | `ok` |
| Foreign-key violations | 0 |
| SHA-256 before preview | `2C5B3EF08BA222793B494E4B601C44FA88AA34C7CBA24331050C0BB70F90671C` |
| SHA-256 after preview and tests | `2C5B3EF08BA222793B494E4B601C44FA88AA34C7CBA24331050C0BB70F90671C` |
| Production writes | 0 |

## Existing parent

| Field | Current production value |
|---|---|
| Registry row | 1 |
| Permanent ID | `THS-EQP-000001` |
| UUID | `6e55b13d-25a2-4c89-87d6-8b905bf2589e` |
| Name | Bambu Lab P1S |
| Manufacturer / model | Bambu Lab / P1S |
| Manufacturer serial | null |
| Lifecycle | Installed |
| Operational status | Operating |
| Readiness | null |
| Derived restriction | Unknown |
| State version | 1 |

The P1S record is not changed by this proposal. Its currently null
manufacturer serial is outside this checkpoint.

## Proposed Equipment Registry records

These permanent IDs are the next two values in the current production
sequence. UUIDs and row IDs are deliberately not generated until a future
signed, confirmation-bound review.

| Field | AMS 1 proposal | AMS 2 proposal |
|---|---|---|
| Permanent ID | `THS-EQP-000002` | `THS-EQP-000003` |
| Display name | Bambu Lab AMS 2 Pro - AMS 1 | Bambu Lab AMS 2 Pro - AMS 2 |
| Type / subtype | AMS Unit / Bambu AMS | AMS Unit / Bambu AMS |
| Manufacturer / model | Bambu Lab / AMS 2 Pro | Bambu Lab / AMS 2 Pro |
| Reported manufacturer serial | `19C-06A-522-00-22-97` | `19C-51A-6-204-00 EWR` |
| THS asset identifier | null | null |
| Current Registry location | null | null |
| Lifecycle | Installed | Installed |
| Operational status | Unknown | Unknown |
| Installed / commissioned times | null / null | null / null |
| Retirement / disposal | null | null |
| State version | 1 | 1 |
| Creator | Cowboy | Cowboy |

The canonical Registry location remains null because production has no
verified `THS print room` location row. The legacy AMS location hierarchy is
preserved and is not substituted for that missing physical-area fact.

Operational status, maintenance readiness, and restrictions remain separate.
No maintenance bridge is proposed, so readiness remains null and the derived
restriction remains Unknown.

## Proposed parent/child relationships

| Child | Parent | Type | Version | Effective time |
|---|---|---|---:|---|
| `THS-EQP-000002` | `THS-EQP-000001` P1S | `attached_to` | 1 | Requires Cowboy confirmation |
| `THS-EQP-000003` | `THS-EQP-000001` P1S | `attached_to` | 1 | Requires Cowboy confirmation |

Each relationship creates one current-state row and one immutable attach
history row. Later movement uses `move` or `detach`; it never rewrites the
initial history.

## Existing eight slots — adopted, not recreated

Migration 018 intentionally preserved `equipment` and `equipment_slots` as the
authoritative AMS container and slot structures. Production already has all
eight required slot records, protected by:

- `UNIQUE(equipment_id, slot_number)`;
- unique slot-location IDs;
- one active spool per slot;
- one active slot per spool.

Creating eight additional slots would duplicate authoritative state. The
correct Equipment Registry action is one one-to-one
`equipment_legacy_container_links` row per new AMS record.

| Registry AMS | Legacy container | Existing slot ID | Number | Current assignment |
|---|---|---:|---:|---|
| `THS-EQP-000002` | AMS 1, row 1 | 1 | 1 | Assignment 8 — `THS-FIL-000040`, purple |
| `THS-EQP-000002` | AMS 1, row 1 | 2 | 2 | Empty |
| `THS-EQP-000002` | AMS 1, row 1 | 3 | 3 | Assignment 11 — `THS-FIL-000042`, Hot Pink |
| `THS-EQP-000002` | AMS 1, row 1 | 4 | 4 | Assignment 10 — `THS-FIL-000041`, Cocoa Brown |
| `THS-EQP-000003` | AMS 2, row 2 | 5 | 1 | Assignment 9 — `THS-FIL-000039`, Black |
| `THS-EQP-000003` | AMS 2, row 2 | 6 | 2 | Assignment 2 — `THS-FIL-000023`, Orange |
| `THS-EQP-000003` | AMS 2, row 2 | 7 | 3 | Assignment 5 — `THS-FIL-000033`, cyan |
| `THS-EQP-000003` | AMS 2, row 2 | 8 | 4 | Assignment 1 — `THS-FIL-000022`, Jade White |

No `equipment_slots` or `ams_assignments` row changes. Existing assignment IDs,
slot IDs, spool IDs, load times, states, and remaining quantities stay exactly
as recorded.

## Before-and-after counts

| Table or projection | Before | Proposed after | Change |
|---|---:|---:|---:|
| `equipment_registry` | 1 | 3 | +2 |
| `equipment_history` | 1 | 3 | +2 |
| `equipment_relationship_state` | 0 | 2 | +2 |
| `equipment_relationship_history` | 0 | 2 | +2 |
| `equipment_legacy_container_links` | 0 | 2 | +2 |
| Equipment Registry audit events | 1 | 7 | +6 |
| `equipment_slots` | 8 | 8 | 0 |
| All `ams_assignments` | 11 | 11 | 0 |
| Active `ams_assignments` | 7 | 7 | 0 |
| Equipment telemetry rows | 0 | 0 | 0 |

## Exact proposed write set

The future atomic commit would create 16 rows and update or delete none.

For each AMS:

1. `equipment_registry`: one permanent equipment record.
2. `equipment_history`: one immutable `register` event, state null to 1.
3. `audit_events`: one `register_equipment` event.
4. `equipment_relationship_state`: one current `attached_to` projection.
5. `equipment_relationship_history`: one immutable `attach` event.
6. `audit_events`: one `attach_equipment_relationship` event.
7. `equipment_legacy_container_links`: one one-to-one bridge to legacy AMS 1
   or AMS 2.
8. `audit_events`: one `link_legacy_equipment_container` event.

Generated UUIDs, request nonces, row IDs, snapshots, and system commit
timestamps must be bound into a new signed review after physical confirmation.
They are intentionally not invented in this zero-write report.

No capabilities, interfaces, connections, telemetry, maintenance links,
purchase links, receipt links, component installations, printer links, slot
rows, filament transactions, or assignment changes are proposed.

## Duplicate and stale-state protection

Before a future commit:

- both permanent numbers must still be next in sequence;
- serials are compared after case and whitespace normalization;
- the database unique index additionally protects manufacturer plus
  `lower(trim(manufacturer_serial_number))`;
- display names are normalized and protected by a unique index;
- each legacy container may have only one Registry link;
- each Registry equipment row may have only one legacy-container link;
- each legacy AMS must still have exactly unique slots 1–4;
- active-slot and active-spool uniqueness must remain valid;
- the P1S and both legacy containers must match the signed snapshot;
- request nonces, signatures, age, replay, sequence, and relationship-cycle
  checks must pass.

Any mismatch must roll back the whole transaction.

## Audit and immutable history

Expected per-unit audit sequence:

1. register equipment;
2. attach equipment relationship;
3. link legacy equipment container.

Registration snapshots preserve the serial, model, lifecycle, operational
status, and permanent identity. Relationship snapshots preserve the P1S
parent, `attached_to` type, state version, actor, reason, and confirmed
effective time.

## Rollback and post-onboarding verification plan

Before any authorized write:

1. stop and verify the production service;
2. recheck exact schema, checksum, integrity, foreign keys, sequence, parent,
   legacy units, slots, assignments, and serial/name duplicates;
3. create and hash-verify a fresh external schema-19 backup;
4. create a fresh signed preview containing the physically confirmed facts;
5. rehearse the exact atomic commit on a verified production copy;
6. require explicit production authorization.

The production commit must be one transaction. Any failed registration,
relationship, bridge, or audit insert rolls back every child action.

Post-onboarding:

- verify exactly three Registry equipment records;
- verify `THS-EQP-000002` and `THS-EQP-000003` identities and serials;
- verify two current P1S child relationships and two immutable attach histories;
- verify two one-to-one legacy links;
- verify the same eight slot rows and seven active assignment rows;
- fingerprint all filament, transaction, slot, and assignment tables;
- verify zero telemetry and no new provenance or maintenance links;
- run integrity, foreign keys, focused tests, full regression, and HTTP routes.

For immediate authorized rollback before any later production activity, restore
the verified pre-onboarding backup. For later correction, do not delete
permanent equipment or rewrite history; use separately approved corrective
state and relationship workflows.

## Required Cowboy confirmations

1. Does the AMS 1 label read exactly `19C-06A-522-00-22-97`?
2. Does the AMS 2 label read exactly `19C-51A-6-204-00 EWR`, including the
   space and `EWR` suffix?
3. Which physical serial maps to the legacy `AMS 1` and `AMS 2` names?
4. Approve the exact display names:
   - `Bambu Lab AMS 2 Pro - AMS 1`
   - `Bambu Lab AMS 2 Pro - AMS 2`
5. Confirm both physical units are currently attached to the P1S.
6. Confirm each physical unit's slots are numbered 1–4 consistently with the
   existing legacy slot mapping.
7. Confirm the model label is exactly `AMS 2 Pro`.
8. Provide or approve an effective attachment time for immutable history.
9. Confirm lifecycle `Installed`, operational status `Unknown`, readiness null,
   and restriction Unknown are truthful.

## Implementation boundary before a future write

The current Equipment Registry service signs individual registration and
relationship operations, but it does not yet provide one atomic two-unit
registration/relationship/legacy-bridge commit. The next authorized source
checkpoint should add that narrow orchestrator and its rollback tests. Direct
production SQL is not approved.

Stop for Cowboy's physical confirmation and explicit authorization.
