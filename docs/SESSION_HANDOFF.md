# THS Command Center Session Handoff

## Current workspace

- Repository: `C:\Users\Cowboy\Documents\GitHub\THS-Command-Center`
- Feature branch: `feature/filament-manager-v1`
- Production database:
  `C:\Users\Cowboy\Documents\THS-Command-Center-Data\inventory.sqlite3`
- Production schema: 19
- Last accepted production SHA-256:
  `3A9992C0337A11092780AC9F1B5E43126C03509A1EE749CC21679360DF3CFD28`
- AMS production-onboarding report commit:
  `411a29c2073de0cc01a4961a111149ff0b395d32`
- Main remains untouched. The feature branch must not be merged without
  Cowboy's separate approval.

The final merge-readiness evidence and current test counts are maintained in
[`inventory-system/INVENTORY_FEATURE_MERGE_READINESS.md`](inventory-system/INVENTORY_FEATURE_MERGE_READINESS.md).

## Accepted production state

- Migrations 001 through 019 are applied.
- Migration 019 flexible spool replacement, the physically verified
  `THS-FIL-000032`/`THS-FIL-000039` correction, and the filament swatch repair
  are complete.
- `THS-EQP-000001` is the Bambu Lab P1S, manufacturer serial
  `01P00C511401400`.
- `THS-EQP-000002` is Bambu Lab AMS 2 Pro - AMS 1, serial
  `19C06A522002297`.
- `THS-EQP-000003` is Bambu Lab AMS 2 Pro - AMS 2, serial
  `19C51A620400EWR`.
- Both AMS units are attached to the P1S. The eight legacy slot rows were
  preserved and bridged to their registry equipment.
- Seven slots are assigned. AMS 1 Slot 2 / A2 remains empty, Out of service,
  and Do not load.
- `THS-MNT-000002` tracks the AMS 1 Slot 2 feeder/roller issue.
- `THS-PART-000001` is one new/boxed Bambu Lab AMS 2 Pro Feeder Unit,
  model `SA403-V1`, UPC `6937285503237`. It remains uninstalled, unreserved,
  unissued, and unconsumed. Its storage location remains unresolved/null.

## Safety boundaries

- Do not repair AMS 1 Slot 2, return it to service, consume the feeder, or
  invent a feeder storage location without a separately approved maintenance
  workflow.
- Do not reconcile broader parts, configure printer networking, begin Maeve
  telemetry, or mix in broader health-module work.
- Do not write production without a fresh checksum, integrity and foreign-key
  preflight, verified external backup, exact zero-write preview, and explicit
  Cowboy approval.
- Receiving means verified physical arrival only. It never implies
  installation, opening, assignment, loading, usage, or consumption.
- Use `Start THS Dashboard.cmd` for production. Direct `serve` and controlled
  AMS-onboarding commands require an explicit `--database` path.

## Current checkpoint

The active task is final inventory acceptance and merge readiness. It is
read-only against production and source-only in Git. Any cleanup must be
narrowly justified, tested, committed, and pushed to
`feature/filament-manager-v1`. Stop for Cowboy's approval before any merge or
production action.
