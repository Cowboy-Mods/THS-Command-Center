# Filament Manager v1 Implementation Plan

> **Architecture notice:** Filament is now the first module of the category-agnostic [THS Inventory System](../inventory-system/THS_INVENTORY_SYSTEM_ARCHITECTURE.md). See [Filament Module v1](../inventory-system/FILAMENT_MODULE_V1.md) for the verified checkpoint state. This historical plan is retained; its dashboard and previously listed AMS assignments are not part of the database checkpoint.

## Goal

Build the first working Maeve filament inventory module as a responsive web application that can be used from Cowboy's phone, Windows PC, and the future Maeve touchscreen unit.

## Delivery target

A local-first progressive web app backed by a single inventory database. The same interface must adapt to phone, desktop, and 7-inch landscape screens.

## Stage 1 â€” Foundation

1. Confirm the existing THS Command Center application stack.
2. Add a filament inventory module and navigation entry.
3. Add a SQLite database with migrations.
4. Add seed data for the verified sealed stock and create empty AMS slots; do not seed assignments until re-verified.
5. Build responsive read-only dashboard views.

## Stage 2 â€” Manual inventory actions

Add actions for:

- Add sealed spool
- Open sealed spool
- Load spool into AMS
- Unload spool to wall storage
- Move spool between locations
- Correct remaining grams
- Mark spool empty or retired
- Set emergency minimum and target stock

Every action must write an inventory transaction. Existing history must never be silently rewritten.

## Stage 3 â€” Print reservations and deductions

- Create project and plate usage reservations.
- Assign estimated grams to specific AMS spools.
- Complete a print and convert reservations into deductions.
- Flag failed or canceled prints for manual review.
- Display low-material warnings before a print begins.

## Stage 4 â€” PWA and device support

- Installable PWA manifest
- Responsive layouts for phone, PC, and 7-inch landscape display
- Local-network access
- Clear offline/error state
- Touch-friendly controls for Maeve

## Initial verified data

### Sealed stock

- Overture PLA Black refill Ã—6
- Elegoo PLA White Ã—2, marked use-up stock
- Bambu PLA Basic Pink Ã—1
- Bambu PLA Basic Orange Ã—2
- Bambu PLA Basic Cobalt Blue Ã—1
- Bambu PLA Basic Turquoise Ã—1
- Bambu PLA Basic Blue Ã—1
- Bambu PLA Basic Bambu Green Ã—2
- Bambu PLA Basic Dark Gray Ã—1
- Bambu PLA Basic Jade White Ã—1
- Bambu PLA Basic Brown Ã—4
- Bambu PLA Basic Gold Ã—3
- Bambu PLA Basic Gray Ã—1
- AMOLEN PLA Silk Dual Color mini spools, 200 g each:
  - Black/Red
  - Black/Purple
  - Black/Blue
  - Black/Green

### AMS 1

- Slot 1: Black
- Slot 2: Orange
- Slot 3: Empty
- Slot 4: Jade White

### AMS 2

- Slot 1: Bambu PLA Silk Black
- Slot 2: Empty
- Slot 3: Red
- Slot 4: Bambu PLA Silk Black

## Required data model

- filament_catalog
- physical_spools
- locations
- ams_slots
- stock_minimums
- print_jobs
- print_usage
- inventory_transactions

## Acceptance criteria

1. The dashboard works at phone, desktop, and 7-inch landscape widths.
2. Sealed, wall, and AMS stock are visibly separated.
3. Both AMS units show four slots each.
4. A spool can be added, opened, moved, loaded, unloaded, corrected, and retired.
5. Every inventory-changing action creates a transaction record.
6. Low-stock warnings update from minimum rules.
7. The seeded inventory matches the verified counts above.
8. No RFID, NFC, QR, or Bambu automation is required for this first version.

## First development checkpoint

The first checkpoint is complete when the repository contains:

- an agreed application stack
- database schema and migration
- seeded inventory data
- responsive dashboard shell
- automated tests for inventory counts and AMS slot uniqueness

