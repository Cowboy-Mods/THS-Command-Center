# Filament Inventory Module v1

## Module boundary

Filament is the first configured THS Inventory System category. A catalog product describes a reusable product/color; each real spool is an individual inventory instance. Four Bambu Lab PLA Basic Brown spools therefore share one product row and have four permanent `THS-FIL` IDs.

The normal grouped query reports roll counts by state, available grams, reserved grams, and later reorder state. Detailed views expose individual spools.

## Verified sealed inventory seed

| Brand | Products/colors | Spools | Seed grams |
|---|---|---:|---:|
| Overture | PLA Black | 6 | 6,000 |
| Elegoo | PLA White; use-up stock | 2 | 2,000 |
| Bambu Lab | PLA Basic: Pink, Orange, Cobalt Blue, Turquoise, Blue, Bambu Green, Dark Gray, Jade White, Brown, Gold, Gray | 18 | 18,000 |
| AMOLEN | PLA Silk Dual Color: Black/Red, Black/Purple, Black/Blue, Black/Green | 4 | 800 |
| **Total** | **17 catalog products** | **30** | **26,800** |

AMOLEN weights are verified at 200 g each. Bambu, Overture, and Elegoo use a documented 1,000 g standard-spool assumption. No manufacturer SKU or color code was invented.

## Filament fields

The item-type template requires material, manufacturer color name, 1.75 mm diameter, and nominal grams. Optional attributes include color code and packaging/spool weight. Catalog products also store manufacturer, product line, variant, optional SKU, and notes.

Instances support permanent ID, product, original/remaining grams, sealed/open/loaded/empty/archive state, condition, location, purchase/open/empty/archive dates, notes, verification, and timestamps.

## AMS configuration

AMS 1 and AMS 2 each contain four numbered location slots. Empty is valid. Partial unique indexes prevent a spool from occupying two active slots and a slot from holding two active spools. Assignment rows reference immutable load and unload transactions.

No current spool assignment was seeded. Earlier filament planning listed proposed/observed colors, but this checkpoint's instruction says not to invent current assignments. Those observations must be re-verified before import.

## Open-wall status

No uncertain wall stock is confirmed. The known black Bambu TPU and probably-Elegoo red PLA remain outside active inventory until brand, product, amount, and location are verified. Approximate amounts may later be entered as Full, 3/4, 1/2, 1/4, or Nearly Empty and converted to clearly labeled estimates.

## Import

Use `data/inventory/inventory-import-template.csv`. Dry-run first; unverified rows reject by default. For real filament imports, put specifications in `attributes`, for example:

```text
material=TPU;manufacturer_color_name=Black;diameter_mm=1.75;nominal_weight_g=1000
```

## Acceptance coverage

Automated tests cover 30 spools, brand totals, 26,800 g, four Brown spools grouped under one product, 200 g AMOLEN rolls, unique permanent IDs, state grouping, nonnegative remaining grams, archive history, reservations, two four-slot AMS units, active assignment uniqueness, and load/unload history.

## Read-only dashboard

The first visible Filament Inventory interface is complete. It reads the migrated SQLite database and provides:

- live dashboard totals;
- 17 grouped filament products;
- product pages with physical spool lists;
- individual spool pages with transaction history;
- two AMS units with eight verified-empty slots;
- search by manufacturer, material, color, product line, THS-FIL ID, and notes;
- state, manufacturer, material, and low-stock filters;
- honest no-results and no-reorder-rule states.

No inventory-changing controls or routes exist. Setup, startup, responsive behavior, routes, and current limitations are documented in [Read-Only Dashboard v1](READ_ONLY_DASHBOARD_V1.md).

Future filament mutations must use the centralized [Inventory Action Service](INVENTORY_ACTION_SERVICE.md). It already supports receiving individual spools, moves, corrections, state changes, reservations, AMS load/unload, immutable before/after auditing, and supported reversals. No editable filament UI is exposed yet.

