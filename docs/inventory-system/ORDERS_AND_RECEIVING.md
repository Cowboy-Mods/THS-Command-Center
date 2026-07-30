# Orders and Receiving

Orders describe expected incoming stock. They never increase physical inventory.

## States

`Ordered`, `Shipped`, `Delivered`, `Received`, and `Cancelled` are stored as validated order states. Runtime creation and state changes flow through `InventoryActionService`. The current legacy full-order workflow derives `Received` only after the verified quantity exactly equals the complete outstanding quantity.

## Verified Overture order

`THS-ORD-000001` records one received Overture White filament bulk refill box:

- expected: four refill rolls;
- material: PLA;
- color: White;
- state: Received;
- received: four of four;
- physical inventory: `THS-FIL-000034` through `THS-FIL-000037`.

Catalog item 18 is the corrected Overture High Speed PLA, White, refill-coil
identity. Both committed delivery photos are linked immutably to receiving batch
`29251fad-da91-4e08-9c43-87c85743e45b`.

## Controlled receipt

The receipt page requires Cowboy to verify actual accepted quantity, condition, and receiving location. Its signed preview displays the permanent `THS-FIL` IDs and performs zero writes. Confirmation calls `InventoryActionService.receive_order`.

One atomic transaction creates:

- one immutable receiving batch;
- one individual physical inventory instance per accepted refill;
- one immutable order/batch/instance link per refill;
- normal inventory transactions and immutable audit records;
- one immutable batch receipt audit record;
- the final received quantity and order state.

If any instance, transaction, link, or audit insert fails, the complete receipt
rolls back. The current legacy workflow rejects any quantity other than the
exact outstanding quantity. Partial receipt requires separate future design and
approval.

All created instances retain Overture as manufacturer. No Bambu or RFID identity is assumed.

## Limitations

This checkpoint provides the verified seeded order and controlled receipt path. It does not add supplier editing, purchasing automation, invoices, shipping tracking, returns, or a general order editor.
