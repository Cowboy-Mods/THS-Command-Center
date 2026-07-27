# THS Command Center Session Handoff

## Current workspace

- Repository: `C:\Users\Cowboy\Documents\GitHub\THS-Command-Center`
- Branch: `feature/filament-manager-v1`
- Live database: `C:\Users\Cowboy\Documents\THS-Command-Center-Data\inventory.sqlite3`
- Schema: 16
- Source base before receiving checkpoint: `b2893fddcfedf38f25e30d6d9a0d1b78f7a42b3a`
- Full test baseline: 273 tests

## Verified production state

- `THS-ORD-000001`: Received, four of four.
- Receiving batch: `29251fad-da91-4e08-9c43-87c85743e45b`.
- `THS-FIL-000034` through `THS-FIL-000037`: Overture High Speed PLA,
  White, refill coil, sealed, 1,000 g each, Sealed Filament Rack, no AMS.
- `THS-PO-000001`: Ordered; no purchase line received, installed, or consumed.
- `THS-MNT-000001`: In progress, High severity.
- THS Printer readiness: No unattended printing.

## Current source checkpoint

**Purchase Registry Receiving and Status Transitions — source foundation**

Boundaries:

- Migration 017 and controlled source services are implemented.
- Receiving means verified physical arrival only. It never implies installation,
  opening, assignment, loading, usage, or consumption.
- Do not apply migration 017 to production without a separate verified backup,
  zero-write migration preview, and explicit approval.
- Do not create inventory until a separately confirmed production receipt.
- Keep receipt, stock creation, maintenance relevance, installation, and
  consumption as distinct facts.
- Preserve signed expiring previews, explicit confirmation, replay protection,
  immutable history, atomic rollback, backups, and production migration gates.
- Do not alter the completed legacy Overture receipt.
- Do not begin historical purchase backfill inside this checkpoint.

## Known risks and unresolved decisions

- Production migration 017 remains unapplied.
- `THS-PO-000001` catalog resolution and physical receiving remain separate
  future approval checkpoints.
- Historical Bambu purchases require reconciliation to prevent duplicate current
  inventory.
- Secure Remote Dashboard is a Version 1 requirement but is not implemented;
  local port 8787 must not be exposed publicly.
- Remote analytics, Apple clients, and live Bambu integration remain future work.
