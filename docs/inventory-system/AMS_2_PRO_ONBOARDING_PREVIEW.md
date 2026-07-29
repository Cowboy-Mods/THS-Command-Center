# Bambu Lab AMS 2 Pro Onboarding — Revised Zero-Write Preview

Date: 2026-07-29  
Source baseline:
`cb42776192600ce8c0fab541a268cde33557aa54`
Production database:
`C:\Users\Cowboy\Documents\THS-Command-Center-Data\inventory.sqlite3`  
Mode: physically confirmed planning; no production write

## Outcome and stop boundary

The Equipment Registry and legacy AMS state were reinspected read-only using
Cowboy's confirmed serials, P1S relationship, Bambu Studio A/B designations,
slot layout, and maintenance facts.

The identity, bridge, relationship, lifecycle, and operational portions can be
previewed under schema 19. The complete onboarding is **not production-ready**
because schema 19 cannot truthfully store or enforce:

1. AMS 1 Slot 2 as `Out of service / Do not load`; or
2. maintenance readiness `Needs service` for AMS 1 and `Unknown` for AMS 2.

No migration, service change, equipment record, relationship, restriction,
maintenance record, slot change, assignment change, or production write was
performed.

## Production database safety

| Check | Result |
|---|---|
| Schema | 19 |
| Latest migration | `019_flexible_spool_replacement.sql` |
| SQLite quick check | `ok` |
| Foreign-key violations | 0 |
| SHA-256 before inspection | `2C5B3EF08BA222793B494E4B601C44FA88AA34C7CBA24331050C0BB70F90671C` |
| SHA-256 after inspection | `2C5B3EF08BA222793B494E4B601C44FA88AA34C7CBA24331050C0BB70F90671C` |
| Production writes | 0 |

The checksum matches the last verified value. No intervening production
database activity was detected.

## Current listeners — inspected, not changed

| PID | Identity | Status |
|---:|---|---|
| 58064 | Verified bootstrap, explicit production database, source deployment record present | Running |
| 57596 | Untracked `python -m inventory.cli serve --host 127.0.0.1 --port 8787`, no explicit database | Running |

Both processes and their parent/process identities remained unchanged. Neither
was stopped, restarted, signaled, or otherwise disturbed.

## Physically confirmed parent and serial correction

Current production P1S:

| Field | Current | Proposed |
|---|---|---|
| Equipment | `THS-EQP-000001` Bambu Lab P1S | Unchanged |
| Registry row | 1 | Unchanged |
| Manufacturer serial | null | `01P00C511401400` |
| State version | 1 | 2 |
| Lifecycle | Installed | Unchanged |
| Operational status | Operating | Unchanged |

The serial is confirmed from the P1S screen. A future controlled fact update
would update the P1S row, append immutable `equipment_history.update_facts`,
and add one `update_equipment_facts` audit event. The permanent identity,
manufacturer, model, lifecycle, and operational status remain unchanged.

## Proposed AMS Registry records

| Field | AMS 1 | AMS 2 |
|---|---|---|
| Permanent ID | `THS-EQP-000002` | `THS-EQP-000003` |
| Display name | Bambu Lab AMS 2 Pro - AMS 1 | Bambu Lab AMS 2 Pro - AMS 2 |
| Manufacturer | Bambu Lab | Bambu Lab |
| Model | AMS 2 Pro | AMS 2 Pro |
| Exact serial | `19C06A522002297` | `19C51A620400EWR` |
| Bambu Studio designation | A | B |
| Type / subtype | AMS Unit / Bambu AMS | AMS Unit / Bambu AMS |
| Lifecycle | Installed | Installed |
| Registry operational status | Degraded | Operating |
| User-facing operational meaning | Operational with restrictions | Operational |
| Current Registry location | null | null |
| Installation date | null | null |
| State version | 1 | 1 |

AMS 1's serial is confirmed on both the P1S screen and the physical label.
AMS 2's serial contains no spaces or hyphens, and `EWR` is part of the serial.

`degraded` is the existing Registry enum that truthfully represents AMS 1 as
operational with restrictions. It does not itself enforce the Slot 2 loading
restriction.

## Parent/child relationships

| Child | Parent | Type | Effective time |
|---|---|---|---|
| `THS-EQP-000002` | `THS-EQP-000001` | `attached_to` | Actual future onboarding commit time |
| `THS-EQP-000003` | `THS-EQP-000001` | `attached_to` | Actual future onboarding commit time |

No earlier installation date is invented. Each relationship would create one
current-state row and one immutable attach-history row. Later moves or
detachment append history rather than rewriting these events.

## Legacy-container bridges

| Registry equipment | Legacy container | Bridge |
|---|---:|---|
| `THS-EQP-000002` | row 1, AMS 1 | one-to-one `equipment_legacy_container_links` insert |
| `THS-EQP-000003` | row 2, AMS 2 | one-to-one `equipment_legacy_container_links` insert |

These bridges adopt the existing eight slot rows. They do not create,
renumber, delete, or rewrite slots.

## Stored assignments versus confirmed physical truth

Exactly seven production slots are occupied. AMS 1 Slot 2/A2 is empty.

| Slot | Stored assignment | Confirmed physical truth | Result |
|---|---|---|---|
| AMS 1 Slot 1 / A1 | `THS-FIL-000040`, `purple` | Purple | Match |
| AMS 1 Slot 2 / A2 | Empty | Empty; unavailable; do not load | Occupancy match |
| AMS 1 Slot 3 / A3 | `THS-FIL-000042`, Hot Pink | Hot Pink | Match |
| AMS 1 Slot 4 / A4 | `THS-FIL-000041`, Cocoa Brown | Cocoa Brown | Match |
| AMS 2 Slot 1 / B1 | `THS-FIL-000039`, Black | Black | Match |
| AMS 2 Slot 2 / B2 | `THS-FIL-000023`, Orange | Orange | Match |
| AMS 2 Slot 3 / B3 | `THS-FIL-000033`, `cyan` | Blue | Compatible stored color family |
| AMS 2 Slot 4 / B4 | `THS-FIL-000022`, `Jade White` | White | Compatible stored color family |

The physical shorthand Blue and White does not contradict the stored catalog
names `cyan` and `Jade White`. Those permanent spool and catalog identities
remain unchanged as required.

Assignment IDs, spool identities, catalog identities, color text, load times,
states, weights, quantities, inventory transactions, transaction lines, and
audit history remain untouched.

## AMS 1 maintenance truth

Confirmed Slot 2 facts:

- the slot becomes loud and can lock up;
- its feeder/roller mechanism requires inspection and repair;
- it is Out of service / Do not load;
- it must reject future filament loading.

Confirmed Slot 4 facts:

- it has historically rewound faster than the spool;
- it is currently loaded with Cocoa Brown and functioning;
- it requires a monitoring note;
- it must not be marked out of service without new evidence.

Confirmed equipment-level readiness:

- AMS 1: Needs service;
- AMS 2: Unknown until formally inspected.

## Current schema conflict

Production already contains legacy maintenance assets:

| Asset | ID | Current readiness |
|---|---:|---|
| AMS 1 | 2 | Normal |
| AMS 2 | 3 | Normal |

Linking these assets now would falsely project Normal for both new Registry
records. Existing readiness values are limited to:

- Normal;
- Monitor during printing;
- No unattended printing;
- Out of service.

There is no `Needs service` or `Unknown` value. The readiness is asset-wide,
so setting AMS 1 to Out of service would incorrectly disable usable Slots 1,
3, and 4.

Schema 19 also has no slot-level operational-state, restriction, monitoring,
or immutable restriction-history structure. Notes alone would not enforce
`Do not load`, so storing only prose would be unsafe.

The complete write set therefore cannot yet include a truthful Slot 2
restriction or maintenance-readiness record. No row count is invented for
tables that do not exist.

## Required future schema/service design

A separately authorized source/schema checkpoint must provide:

### Slot 2 current state and history

- slot ID 2 / A2;
- operational state `out_of_service`;
- restriction `do_not_load`;
- required reason and actor;
- state version and effective time;
- immutable history;
- service-layer validation that rejects every load or replacement targeting
  the restricted slot;
- atomic stale-state, duplicate, tamper, and replay protection.

### Slot 4 monitoring state and history

- slot ID 4 / A4;
- operational state remains operational;
- monitoring note for the rewind behavior;
- no load restriction;
- immutable history and audit.

### Equipment maintenance readiness

- AMS 1 `needs_service`;
- AMS 2 `unknown`;
- no conversion to misleading legacy readiness values;
- separate projection from operational status and derived restrictions.

### Atomic onboarding orchestrator

One signed commit must bind:

- P1S fact update;
- both AMS registrations;
- both parent relationships;
- both legacy bridges;
- equipment-level readiness;
- Slot 2 restriction;
- Slot 4 monitoring note;
- maintenance record and all audit/history rows.

Direct production SQL is not approved.

## Revised currently representable write set

Under the existing schema, the non-maintenance portion contains:

- **18 inserted rows**;
- **1 updated row**;
- **0 deleted rows**;
- **0 slot rows created or changed**;
- **0 assignment rows changed**.

The 18 currently representable inserts are:

| Table | Count | Purpose |
|---|---:|---|
| `equipment_registry` | 2 | AMS 1 and AMS 2 permanent records |
| `equipment_history` | 3 | Two registrations plus P1S fact update |
| `equipment_relationship_state` | 2 | Current P1S child relationships |
| `equipment_relationship_history` | 2 | Immutable attach events |
| `equipment_legacy_container_links` | 2 | Registry-to-legacy bridges |
| `audit_events` | 7 | P1S update plus three events per AMS |
| **Total** | **18** | |

The one currently representable update is:

- `equipment_registry` row 1 / `THS-EQP-000001`:
  `manufacturer_serial_number` null to `01P00C511401400`,
  `state_version` 1 to 2, and `updated_at` to commit time.

The complete required inserted-row count is intentionally **not finalized**
until the slot-restriction and readiness schema is approved. Claiming a final
count now would omit required safety records or invent nonexistent tables.

## Expected audit records

Current-schema portion:

1. `THS-EQP-000001` — `update_equipment_facts`;
2. `THS-EQP-000002` — `register_equipment`;
3. `THS-EQP-000002` — `attach_equipment_relationship`;
4. `THS-EQP-000002` — `link_legacy_equipment_container`;
5. `THS-EQP-000003` — `register_equipment`;
6. `THS-EQP-000003` — `attach_equipment_relationship`;
7. `THS-EQP-000003` — `link_legacy_equipment_container`.

The later schema checkpoint must add explicit restriction, monitoring,
maintenance-readiness, and maintenance-record audit events.

## Duplicate and stale-state protections

A future commit must reject:

- permanent IDs other than the still-next `THS-EQP-000002` and
  `THS-EQP-000003`;
- any existing or concurrently created equipment using those IDs;
- duplicate P1S or AMS serials after case/whitespace normalization;
- display-name duplicates;
- duplicate current child relationships;
- self-parenting and relationship cycles;
- duplicate Registry-to-legacy-container bridges;
- anything other than unique slot numbers 1–4 per legacy AMS;
- any duplicate active spool in a slot or duplicate active slot for a spool;
- any load into restricted Slot 2/A2;
- stale P1S, AMS, maintenance, slot, assignment, or sequence snapshots;
- expired, tampered, replayed, or reused previews.

Database uniqueness remains the final defense, while service validation must
produce friendly errors before commit.

## Atomic transaction and rollback

The final production write must use one transaction. If any P1S update, AMS
registration, relationship, bridge, readiness, restriction, maintenance,
history, or audit action fails, every child action rolls back.

Before future production authorization:

1. resolve the duplicate untracked listener under separate authorization;
2. reverify branch, source commit, schema, checksum, integrity, foreign keys,
   P1S state, next equipment IDs, legacy containers, slots, assignments, and
   maintenance assets;
3. create and hash-verify a fresh external backup;
4. build a fresh signed preview using the actual future onboarding time;
5. rehearse the complete atomic workflow on a verified production copy;
6. fingerprint every protected equipment, slot, assignment, inventory,
   transaction, maintenance, and audit table;
7. obtain explicit production authorization.

For immediate rollback before later activity, stop the verified application
and restore the verified backup. For later corrections, permanent IDs and
immutable history must remain; use controlled fact, relationship, restriction,
and maintenance transitions.

## Before-and-after validation plan

After a later authorized commit:

- Registry equipment count must be exactly 3;
- `THS-EQP-000001` must contain the confirmed P1S serial and state version 2;
- `THS-EQP-000002` and `THS-EQP-000003` must match exact names, models, and
  serials;
- both AMS units must be current `attached_to` children of the P1S;
- both immutable attach histories and both legacy bridges must exist;
- AMS 1 must project Degraded / Needs service;
- AMS 2 must project Operating / Unknown readiness;
- Slot 2/A2 must be empty, Out of service, and reject loading;
- Slot 4/A4 must remain loaded and operational with its monitoring note;
- the same eight slot IDs and seven active assignment IDs must remain;
- all spool identities, catalog identities, colors, weights, quantities,
  transactions, and prior audit rows must fingerprint unchanged;
- telemetry and provenance counts must remain unchanged;
- integrity, foreign keys, focused tests, full regression, and HTTP routes
  must pass.

## Boundary

All physical facts are recorded in the revised preview. Production onboarding
is blocked on a separately approved slot-restriction/readiness schema and
atomic service checkpoint. Stop for explicit authorization.
