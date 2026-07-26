# Maeve Filament Manager v1

> **Architecture notice:** This page is the original product plan for the first Filament Inventory module inside the broader, category-agnostic [THS Inventory System](../inventory-system/THS_INVENTORY_SYSTEM_ARCHITECTURE.md). The inventory database is not named Maeve and is not filament-only. Where this early plan conflicts with the verified database checkpoint, the architecture and [Filament Module v1](../inventory-system/FILAMENT_MODULE_V1.md) pages control.

## Purpose

Maeve Filament Manager is the THS Command Center source of truth for filament stock, physical spools, AMS locations, print reservations, usage deductions, emergency minimums, and reorder warnings.

Bambu Studio remains an input for RFID-recognized filament and printer/AMS status. Maeve owns the complete inventory because the shop also contains sealed stock, open wall stock, Overture, Elegoo, AMOLEN, and other non-Bambu filament.

## v1 Goals

1. Record every sealed and open spool.
2. Track each spool by brand, material, product line, color, remaining grams, and physical location.
3. Represent both AMS 2 Pro units and all eight slots.
4. Reserve estimated filament when a plate is prepared.
5. Deduct estimated use after a successful print.
6. Flag failed or canceled prints for review instead of deducting the full estimate automatically.
7. Maintain emergency minimums and generate a reorder list.
8. Keep a transaction history so corrections are auditable.

## Inventory Areas

- Sealed stock
- Open wall stock
- AMS 1 slots 1â€“4
- AMS 2 slots 1â€“4
- In use / active print
- Empty / retired

## Core Records

### Filament Catalog

Defines a reusable filament product and color.

- Brand
- Product line
- Material
- Official color name
- Color code when known
- Nominal spool weight
- Refill or complete spool
- Preferred / use-up / discontinued status

### Physical Spool

Represents one real spool or refill in the workshop.

- THS spool ID
- Catalog item
- Starting grams
- Remaining grams
- Sealed or opened
- Location
- AMS unit and slot when loaded
- Available, reserved, active, empty, or retired
- Notes

### Stock Minimum

- Material
- Color
- Preferred brand
- Minimum sealed quantity
- Target sealed quantity
- Current sealed quantity
- Reorder quantity

### Print Job

- Project name
- Plate name
- Printer
- Started time
- Completed time
- Completed, failed, canceled, or printing
- Bambu job identifier when available

### Print Usage

- Print job
- Physical spool
- AMS slot
- Estimated grams
- Deducted grams
- Reservation status

### Inventory Transaction

- Timestamp
- Transaction type
- Spool
- Gram change
- Quantity change
- Print job when applicable
- Reason
- Manual or automatic source

## Deduction Rules

1. Slicing or planning creates a reservation only.
2. A completed print converts the reservation into a usage deduction.
3. A failed or canceled print is flagged for review.
4. Purge, supports, and model material are included when supplied by the slicer estimate.
5. A manual correction creates a new transaction; history is never silently overwritten.
6. Maeve warns when the assigned spool does not have enough remaining material before printing.

## Dashboard v1

- Total sealed rolls
- Total open spools
- AMS 1 and AMS 2 slot cards
- Low-stock and critical-stock warnings
- Current print and reserved filament
- Search by brand, material, color, and location
- Add spool
- Open sealed spool
- Load into AMS
- Return to wall
- Mark empty
- Correct remaining grams

## Initial AMS State

> Historical planning note only. These assignments were not re-verified for the database checkpoint and have **not** been seeded. AMS 1 and AMS 2 currently seed as four empty, assignable slots each.

### AMS 1

- Slot 1: Black
- Slot 2: Orange
- Slot 3: Empty
- Slot 4: Jade White

### AMS 2

- Slot 1: Bambu PLA Silk Black, visually dark gray
- Slot 2: Empty
- Slot 3: Red
- Slot 4: Bambu PLA Silk Black, visually dark gray

## Initial Automation Roadmap

### Phase A â€” Foundation

- SQLite database
- Seed current inventory
- Dashboard read view
- Manual stock and location actions
- Emergency minimum settings

### Phase B â€” Print Transactions

- Enter slicer usage by project, plate, material, and AMS slot
- Reserve stock
- Complete print and deduct stock
- Review failed/canceled jobs

### Phase C â€” Bambu Integration

- Read printer state over the local network
- Read AMS slot assignments
- Detect print start, completion, cancellation, and failure
- Import sliced filament estimates when technically available
- Automatically create and complete usage transactions

### Phase D â€” Optional Tags

Do not require NFC or QR tags for v1. Add them later only where they reduce work for third-party, loose, or frequently moved spools. Bambu RFID remains useful for compatible Bambu filament.

### Reused RFID tags and true filament identity

Maeve must preserve verified physical filament identity independently from AMS-reported or RFID-reported identity. A reused Bambu RFID tag on an Overture refill may help the AMS select a profile, but it must not relabel the Overture inventory record as Bambu.

Future records should distinguish the verified inventory manufacturer/product/material/color from the AMS-reported profile, RFID/tag identity, identification method, manual override status, original tag source, and mismatch warnings.

One bulk box of Overture White is currently on order and is expected, but not guaranteed, to contain four refill rolls. Do not receive it before Cowboy verifies the delivered quantity and condition. If four refills are verified, represent them as four individually tracked physical instances linked to one purchase or receiving batch.

Bambu Lab PLA Basic Orange now has one opened/loaded spool and one sealed reserve after the verified layer-283 replacement. Add Orange to a future shopping/reorder list because the sealed reserve has reached one; do not invent a reorder rule or mutate inventory outside the controlled workflow.

## Success Criteria

A normal completed print should require no manual gram calculation. Maeve should know which AMS spool was used, deduct the recorded slicer estimate, update remaining stock, and warn when sealed emergency stock falls below its minimum.

