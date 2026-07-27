# THS-Command-Center
Open-source smart workshop assistant for makers. Powered by Raspberry Pi, Home Assistant, and custom 3D-printed hardware.

> **Built for my shop first, but not trapped inside my shop.**

Cowboy's THS installation can be deeply customized, while the shared core stays shop-neutral and self-hostable. Branding, equipment, terminology, alerts, workflows, and layouts are configuration goals rather than required THS hard-coding. See the [Open-Source Project Principles](docs/OPEN_SOURCE_PROJECT_PRINCIPLES.md) for implemented, planned, and deferred boundaries.

THS COMMAND CENTER

Smart Workshop Assistant

Status:
ðŸš§ Under Development

Features

âœ” Raspberry Pi 5
âœ” Home Assistant
âœ” Apple Home Integration
âœ” Voice Assistant (Maeve)
âœ” Printer Monitoring
âœ” Camera System
âœ” Workshop Dashboard
âœ” Open Source

## Project Logs

- [Maeve and THS Command Center Build Log](docs/BUILD_LOG.md)
- [Open-Source Project Principles](docs/OPEN_SOURCE_PROJECT_PRINCIPLES.md)

## THS Inventory System

- [Extensible inventory architecture](docs/inventory-system/THS_INVENTORY_SYSTEM_ARCHITECTURE.md)
- [Centralized Inventory Action Service](docs/inventory-system/INVENTORY_ACTION_SERVICE.md)
- [Receive a Verified Sealed Spool](docs/inventory-system/RECEIVE_VERIFIED_SEALED_SPOOL.md)
- [Replace Active Filament Spool](docs/inventory-system/REPLACE_ACTIVE_FILAMENT_SPOOL.md)
- [Initialize Verified AMS State](docs/inventory-system/INITIALIZE_VERIFIED_AMS_STATE.md)
- [Return AMS Spool to Storage](docs/inventory-system/RETURN_AMS_SPOOL_TO_STORAGE.md)
- [Filament Inventory module v1](docs/inventory-system/FILAMENT_MODULE_V1.md)
- [Read-only dashboard v1](docs/inventory-system/READ_ONLY_DASHBOARD_V1.md)
- [Print Registry and Stage 2 safety checkpoint](docs/inventory-system/PRINT_REGISTRY_CHECKPOINT.md)
- [Register Existing Open Spool](docs/inventory-system/REGISTER_EXISTING_OPEN_SPOOL.md)
- [Printer Maintenance Registry and Backlog](docs/inventory-system/MAINTENANCE_REGISTRY.md)
- [Runtime data, backups, and Git safety boundary](docs/inventory-system/RUNTIME_DATA_AND_BACKUPS.md)
- [Purchase Registry Receiving and Status Transitions](docs/inventory-system/PURCHASE_REGISTRY_RECEIVING.md)
- [Original Maeve Filament Manager plan](docs/filament-manager/MAEVE_FILAMENT_MANAGER_V1.md)

## Run the local inventory dashboard

On Windows, double-click `Start THS Dashboard.cmd` in the permanent checkout. The launcher runs the source code from that Git checkout, explicitly opens `C:\Users\<you>\Documents\THS-Command-Center-Data\inventory.sqlite3`, migrates it, opens the dashboard, and records the exact server process outside Git. Double-click `Stop THS Dashboard.cmd` to stop only that verified process.

Live data and backups do not belong in a Git checkout. See [Runtime data and backups](docs/inventory-system/RUNTIME_DATA_AND_BACKUPS.md) before relocating, restoring, or backing up the database.

The command-line equivalent is:

```powershell
$database = "$env:USERPROFILE\Documents\THS-Command-Center-Data\inventory.sqlite3"
py -3 -m inventory.cli --database $database migrate
py -3 -m inventory.cli --database $database serve
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787) in a browser.

Run all database and interface tests:

```powershell
py -3 -m unittest discover -v
```

