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
- [Original Maeve Filament Manager plan](docs/filament-manager/MAEVE_FILAMENT_MANAGER_V1.md)

Database checkpoint commands:

```powershell
py -3 -m inventory.cli migrate
py -3 -m unittest discover -v
```

