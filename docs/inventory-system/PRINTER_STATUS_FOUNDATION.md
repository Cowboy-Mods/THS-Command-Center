# Printer Status Foundation

The `printers` record supports:

- Offline, Idle, Printing, Paused, Error, and Maintenance;
- active job, progress, current and total layers;
- estimated finish, current plate, loaded AMS slots, and filament;
- status source, last update time, and warning/error message.

The seeded printer is **THS Printer**, a **Bambu Lab P1S**. Its source is Manual and its status is deliberately stale with no live active job asserted. `TweetyFixed` is stored only in the operational note as verified recent context because the system must not claim the print is still running.

Status updates use `InventoryActionService.update_printer_status`, validate all fields, and create immutable audit history. The Dashboard labels the source and freshness. Missing or older-than-15-minute timestamps are stale.

No Bambu credentials, cloud tokens, account data, or live integration are accessed. Local Bambu integration remains a future reviewed checkpoint.
