# Replace Active Filament Spool

## Purpose and scope

This is the first operational THS shop workflow. It replaces three separate actions with one guided, atomic operation:

1. remove the currently loaded spool from its AMS assignment and mark it Empty;
2. open one existing sealed replacement spool;
3. load that replacement into a selected AMS slot.

The user experiences one confirmed process. The Inventory Action Service creates three separate immutable action records and three corresponding inventory transactions. Migration `006_inventory_workflow_transactions.sql` adds one immutable parent workflow transaction linking those actions.

The workflow is product-agnostic. Colors, manufacturers, product lines, and specific spool IDs come from the database.

Route: `/inventory/filament/replace`

## Guided process

### Step 1: current spool

Only active, loaded AMS spools are selectable. The page shows permanent `THS-FIL` ID, manufacturer, product line, color, AMS unit, and slot. The user must explicitly confirm: **This spool is now empty.**

### Step 2: replacement

Only active physical spools in `sealed` state are selectable. Replacement filtering supports permanent `THS-FIL` ID, manufacturer, material, and color.

### Step 3: destination

Leaving destination blank means the same AMS unit and slot as the outgoing spool. Another active AMS slot may be selected when the replacement was physically installed elsewhere. A slot occupied by any other spool is rejected.

### Step 4: zero-write preview

The review page displays the actual database IDs and operation:

```text
Unload and mark Empty THS-FIL-xxxxxx
â†“
Open sealed replacement THS-FIL-yyyyyy
â†“
Load replacement into AMS n Slot n
```

Preview creates no inventory, assignment, transaction, audit, or workflow rows.

### Step 5: explicit confirmation

The signed review includes a unique nonce and expires after 30 minutes. Tampered, expired, stale, and replayed submissions fail. The commit re-reads the active spool, sealed replacement, and destination slot under an immediate transaction before calling the action service.

### Step 6: atomic commit

`InventoryActionService.replace_active_filament_spool` validates the complete operation, creates the immutable parent workflow transaction, and calls:

- `mark_loaded_spool_empty`
- `open_sealed_spool`
- `load_instance_into_ams`

The Mark Empty action closes the outgoing active AMS assignment, records the empty transaction, sets remaining quantity to zero, and archives the physical spool as Empty. The Open action records the replacement's transition from Sealed to Open. The Load action creates the new AMS assignment and records the replacement's final Loaded state.

Nested savepoints remain inside one outer transaction. Any state, AMS, transaction, line, audit, or parent-link failure rolls back the complete operation.

## Real verified shop scenarios

The workflow tests and documentation cover these events without hard-coding product rules:

### Jade White replacement

- outgoing: White filament, now Empty;
- replacement: existing sealed Bambu Lab PLA Basic Jade White;
- operation: open and install the replacement into the same AMS slot.

This shop event already occurred physically. The automated scenario proves the workflow without silently rewriting the seeded production database.

### Orange Tweety Bird replacement

- outgoing: Orange filament, nearly empty, approximately ten minutes of expected print time remaining;
- replacement: one of the two existing sealed Bambu Lab PLA Basic Orange spools;
- purpose: modified Tweety Bird hat with an orange THS logo;
- operation: open and install the selected replacement in the outgoing spool's AMS slot.

Remaining-weight editing is intentionally outside this checkpoint. The descriptive reason may record the approximately ten-minute observation.

## Database changes

Migration 006 adds immutable `inventory_workflow_transactions`, unique workflow UUID and review nonce, actor/module/origin/reason context, current and replacement spool references, destination slot, `inventory_actions.workflow_transaction_id`, an action lookup index, and update/delete prevention triggers.

## Verification

`tests/test_replace_spool.py` adds 16 scenarios covering eligibility, filters, zero-write preview, both confirmations, Jade White, Orange/Tweety Bird, same-slot and alternate-slot loading, occupied-slot rejection, stale and tampered previews, replay attempts, three linked actions, transaction linkage, database immutability, completion output, and simulated-failure rollback.

The complete suite contains 109 passing tests.

## Still out of scope

- general spool editing;
- remaining-weight editing;
- inventory corrections;
- barcode or QR scanning;
- Bambu Studio synchronization;
- reservation changes;
- deletion or bulk operations;
- project creation.

