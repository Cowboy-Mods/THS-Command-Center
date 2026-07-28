# THS Command Center Session Handoff

## Current workspace

- Repository: `C:\Users\Cowboy\Documents\GitHub\THS-Command-Center`
- Branch: `feature/filament-manager-v1`
- Live database: `C:\Users\Cowboy\Documents\THS-Command-Center-Data\inventory.sqlite3`
- Production schema: 17
- Equipment Registry source base: `4803bb29b4f251f1013c70d3f9c112dc66d8a11a`
- Full test baseline before Equipment Registry: 273 tests

## Equipment Registry v1 source checkpoint

### Checkpoint D production onboarding

- Production schema remains 18.
- `THS-EQP-000001` is Cowboy's Bambu Lab P1S.
- Equipment UUID: `6e55b13d-25a2-4c89-87d6-8b905bf2589e`.
- Lifecycle: installed; operational status: operating.
- Built-in camera is one embedded capability/component, not equipment.
- Equipment Registry contains exactly one equipment record, zero AMS equipment,
  zero external cameras, zero telemetry, and zero parent/child relationships.
- Manufacturer serial, THS asset identifier, and exact installation/
  commissioning timestamps remain unknown/null.
- Verified ownership, 2025-05-21 purchase date, THS print-room location, Wi-Fi,
  AMS support, and primary-production note are preserved in notes.
- Legacy maintenance readiness remains unchanged and unbridged.
- Pre-onboarding rollback backup:
  `C:\Users\Cowboy\Documents\THS-Command-Center-Data\backups\inventory-pre-p1s-onboarding-20260727-205731.sqlite3`.
- AMS 1 and AMS 2 remain separate future onboarding checkpoints.

- Migration 018 and `EquipmentRegistryService` exist on the feature branch only.
- Migration 018 seeds reference vocabulary and creates zero equipment and zero
  telemetry rows.
- Permanent identity uses immutable UUIDs and `THS-EQP-######` numbers.
- The legacy `equipment` table remains the AMS slot structure.
- Signed registration and relationship previews are expiring and zero-write;
  confirmation is atomic and rejects stale, tampered, replayed, duplicate, or
  sequence-conflicted submissions.
- Parent/child movement preserves immutable relationship history.
- Operational status, maintenance readiness, restrictions, stable capabilities,
  and telemetry remain separate.
- The P1S built-in camera is an embedded capability/component with no separate
  equipment identity. External cameras remain independent equipment records.
- Bambu, camera-viewing, and print-correlation types are future protocol seams
  only. No API, MQTT, polling, streaming, or credential storage exists.
- Migration 018 must not be applied to production without a separately approved
  Checkpoint C backup, preview, migration, validation, and rollback procedure.
- P1S, AMS, camera, sensor, console, network-equipment, purchase, receipt, and
  inventory onboarding remain unauthorized.

## Verified production state

- `THS-ORD-000001`: Received, four of four.
- Receiving batch: `29251fad-da91-4e08-9c43-87c85743e45b`.
- `THS-FIL-000034` through `THS-FIL-000037`: Overture High Speed PLA,
  White, refill coil, sealed, 1,000 g each, Sealed Filament Rack, no AMS.
- `THS-PO-000001`: Ordered; no purchase line received, installed, or consumed.
- `THS-MNT-000001`: In progress, High severity.
- THS Printer readiness: No unattended printing.

## Current source checkpoint

**Purchase Registry Receiving and Status Transitions — source foundation**

Boundaries:

- Migration 017 and controlled source services are implemented.
- Receiving means verified physical arrival only. It never implies installation,
  opening, assignment, loading, usage, or consumption.
- Do not apply migration 017 to production without a separate verified backup,
  zero-write migration preview, and explicit approval.
- Do not create inventory until a separately confirmed production receipt.
- Keep receipt, stock creation, maintenance relevance, installation, and
  consumption as distinct facts.
- Preserve signed expiring previews, explicit confirmation, replay protection,
  immutable history, atomic rollback, backups, and production migration gates.
- Do not alter the completed legacy Overture receipt.
- Do not begin historical purchase backfill inside this checkpoint.

## Known risks and unresolved decisions

- Production migration 017 remains unapplied.
- `THS-PO-000001` catalog resolution and physical receiving remain separate
  future approval checkpoints.
- Historical Bambu purchases require reconciliation to prevent duplicate current
  inventory.
- Secure Remote Dashboard is a Version 1 requirement but is not implemented;
  local port 8787 must not be exposed publicly.
- Remote analytics, Apple clients, and live Bambu integration remain future work.
