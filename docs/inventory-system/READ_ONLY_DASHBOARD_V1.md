# THS Inventory System Read-Only Dashboard v1

## Checkpoint purpose

This is the first visible THS Inventory System interface. It reads the real local SQLite database and does not expose inventory-changing controls. Filament is the first working module; the application shell is designed for future maker, workshop, and small-business modules.

## UI architecture

The dashboard uses Python 3's standard-library `http.server`, server-rendered HTML, plain CSS, and a small navigation script. No third-party framework or package dependency was added.

This approach was selected because the repository already uses dependency-free Python, SQLite, and `unittest`. It keeps Raspberry Pi installation small, uses the existing query layer directly, and avoids a frontend build chain before the product needs one.

`inventory/navigation.py` holds module labels and routes as configuration metadata. Future profiles may hide, rename, add, or reorganize modules without redesigning the shell.

## Prepare the environment

Install Python 3 if Windows does not already have the `py` launcher. Verify it from PowerShell:

```powershell
py -3 --version
```

No package installation command is required.

## Initialize or migrate the database

From the repository root:

```powershell
py -3 -m inventory.cli migrate
```

This explicit command applies migrations and seeds the verified starting inventory. Starting or browsing the web application does not apply migrations and does not mutate inventory.

## Start the application

```powershell
py -3 -m inventory.cli serve
```

Open:

```text
http://127.0.0.1:8787
```

Press `Ctrl+C` in PowerShell to stop the application.

To use another already-migrated database:

```powershell
py -3 -m inventory.cli --database .\var\inventory-test.sqlite3 serve
```

## Functional routes

- `/` â€” dashboard totals
- `/inventory/filament` â€” grouped inventory, search, filters, and sorting
- `/inventory/filament/products/<id>` â€” catalog product and physical spools
- `/inventory/filament/spools/<id>` â€” individual spool and transaction history
- `/inventory/filament/ams` â€” AMS equipment and slot status
- `/modules/<module-key>` â€” consistent Coming Soon page for planned modules

Missing products/spools and unknown paths return a clean 404 page. A missing or unmigrated database returns a useful startup/checkpoint error without a browser stack trace.

## Dashboard data

All totals are live SQLite queries. The current verified seed displays:

- 30 active physical spools
- 30 sealed, zero open, zero loaded, zero empty/archived
- 17 catalog products
- 26,800 g nominal and estimated remaining
- zero reserved and 26,800 g available
- two AMS units, eight empty slots
- zero low-stock products because no reorder rules are configured

The grouped page represents Bambu Lab PLA Basic Brown once with four physical spool records behind it. Elegoo White visibly carries its use-up-stock note.

## Search and filtering

Search covers manufacturer, material, color, product line, THS-FIL ID, and notes. Filters cover state, manufacturer, material, and configured low-stock status. Sorting covers manufacturer, material, color, spool count, available grams, and low-stock state.

No-results pages state that no filament was found. The application does not invent reorder thresholds.

## Responsive and accessibility behavior

The shell uses a persistent desktop navigation and a keyboard-accessible collapsible mobile navigation. Touch controls are at least approximately 44 pixels high. Tables become labeled stacked records on phone widths.

Verified browser viewports:

- Windows desktop: 1440 Ã— 900
- phone: 390 Ã— 844
- Maeve seven-inch landscape target: 1024 Ã— 600

All checked pages avoided horizontal document scrolling at those normal viewports. The interface includes semantic headings, a skip link, visible focus styles, labeled controls, table headers, text status labels, accessible contrast, Escape-to-close navigation, and reduced-motion support.

## Read-only boundary and one controlled write path

Normal dashboard, inventory, product, spool, AMS, search, filter, and placeholder routes remain read-only. They do not add, edit, import, reserve, consume, move, load, unload, archive, correct, or delete inventory.

The only mutation routes are the purpose-built [Receive a Verified Sealed Spool](RECEIVE_VERIFIED_SEALED_SPOOL.md) and [Replace Active Filament Spool](REPLACE_ACTIVE_FILAMENT_SPOOL.md) confirmations. Their signed previews and explicit confirmations call the centralized [Inventory Action Service](INVENTORY_ACTION_SERVICE.md). No dashboard route has direct SQL write access.

## Tests

```powershell
py -3 -m unittest discover -v
```

The interface suite covers the 24 original dashboard acceptance scenarios, 14 receive-workflow scenarios, and 16 replacement-workflow scenarios in addition to the inventory/database and action-service suites.

## Placeholder modules

Planned materials, components, tools, consumables, projects, purchasing, locations, maintenance, reports, imports, integrations, and settings destinations display Coming Soon with no fake data. Future user/workshop profiles may control which modules are visible.

## Known limitations

- Local development server only; no authentication, permissions, TLS, or external hosting.
- Two narrow workflows exist: receive one verified sealed spool and replace one active loaded spool.
- No general editing, remaining-weight editing, inventory correction, arbitrary AMS editing, or broad product management.
- No live refresh or push notifications.
- No Bambu, Maeve voice, RFID, NFC, barcode, or QR integration.
- Product-level search returns the grouped product that owns a matching THS-FIL ID; spool details are selected from that product.
- The seeded 1,000 g values remain documented packaging assumptions where physical labels have not yet been verified.

## Next checkpoint

Review the first live shop use of Replace Active Filament Spool. Add another operation only after its physical steps and audit output are verified in the shop.

