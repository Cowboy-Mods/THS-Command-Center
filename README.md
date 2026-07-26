# THS-Command-Center
Open-source smart workshop assistant for makers. Powered by Raspberry Pi, Home Assistant, and custom 3D-printed hardware.

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

## THS Inventory System

- [Extensible inventory architecture](docs/inventory-system/THS_INVENTORY_SYSTEM_ARCHITECTURE.md)
- [Filament Inventory module v1](docs/inventory-system/FILAMENT_MODULE_V1.md)
- [Read-only dashboard v1](docs/inventory-system/READ_ONLY_DASHBOARD_V1.md)
- [Original Maeve Filament Manager plan](docs/filament-manager/MAEVE_FILAMENT_MANAGER_V1.md)

## Run the local inventory dashboard

```powershell
py -3 -m inventory.cli migrate
py -3 -m inventory.cli serve
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787) in a browser.

Run all database and interface tests:

```powershell
py -3 -m unittest discover -v
```

