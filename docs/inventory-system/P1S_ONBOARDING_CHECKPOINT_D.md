# Bambu Lab P1S Onboarding — Checkpoint D

Production Equipment Registry onboarding completed on 2026-07-27 through the
signed `EquipmentRegistryService` registration workflow.

## Permanent identity

- Equipment number: `THS-EQP-000001`
- Equipment UUID: `6e55b13d-25a2-4c89-87d6-8b905bf2589e`
- Display name: Bambu Lab P1S
- Type: 3D Printer
- Subtype: FDM Printer
- Manufacturer: Bambu Lab
- Model: P1S
- Lifecycle: Installed
- Operational status: Operating

Unknown manufacturer serial, THS asset identifier, installation timestamp,
commissioning timestamp, retirement, and disposal fields remain null.

The canonical location field remains null because no verified `THS print room`
location row existed and Checkpoint D authorized exactly one equipment record.
Verified ownership, purchase date, physical location, Wi-Fi support, AMS
support, and operational notes are preserved in the equipment notes.

## Built-in camera

The factory camera is capability `camera.builtin`, supported and physically
verified. It also has one embedded, non-independently-tracked component
installation under `THS-EQP-000001`.

It is not a second Equipment Registry record. External camera equipment count
remains zero.

## Deliberate exclusions

- No AMS equipment or parent/child relationships.
- No telemetry.
- No printer API, MQTT, or camera connection.
- No printer or maintenance bridge.
- No interface or current-connection rows.
- No purchase, receipt, inventory, filament, or AMS-assignment changes.

The existing legacy printer maintenance readiness remains separate and
unchanged. Equipment Registry readiness remains unknown until a later,
explicitly approved maintenance-bridge workflow.

## Audit identity

- Equipment history UUID: `4618bd1e-9bbf-43a4-b06d-cc332bb3d308`
- Audit event UUID: `6edd7763-ce18-44f3-a501-9bbd81b39efa`
- Request nonce: `58eb19129674496aafcb1997cb2141c8`
- Capability UUID: `d66c4767-82db-4b0c-bf37-1290148f3210`
- Embedded-component installation UUID:
  `20eb8aa8-1405-45cf-bc91-3e66355209a7`

## Rollback and correction

Pre-onboarding backup:

`C:\Users\Cowboy\Documents\THS-Command-Center-Data\backups\inventory-pre-p1s-onboarding-20260727-205731.sqlite3`

SHA-256:
`FBB23F2007D56EF61F7027AAB1052CEA117093D0D6E4218A24AE980FCEDBAA1C`

For an immediate authorized rollback before other production activity:

1. stop and verify the dashboard;
2. preserve the current production database separately;
3. restore the verified backup to the production path;
4. verify its SHA-256, schema 18, integrity, and foreign keys;
5. restart and validate the dashboard and protected content.

For a later factual correction, do not delete the equipment record or change its
permanent identity directly. Add a separately approved signed correction
workflow that increments `state_version`, appends immutable
`equipment_history`, and creates an audit event. The current service does not
yet expose general fact correction, so direct SQL correction is prohibited.

## Next boundary

Checkpoint E should separately onboard AMS 1 and AMS 2 only after physical fact
verification and individual signed previews. It must not infer parent/child
relationships merely from legacy names or current filament assignments.
