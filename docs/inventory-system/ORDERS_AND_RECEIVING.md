# Orders and Receiving

Orders describe expected incoming stock. They never increase physical inventory.

## States

`Ordered`, `Shipped`, `Delivered`, `Received`, and `Cancelled` are stored as validated order states. Runtime creation and state changes flow through `InventoryActionService`. An order becomes `Received` only through the controlled receipt service after the verified received total reaches or exceeds the expected quantity.

## Verified Overture order

`THS-ORD-000001` records one ordered Overture White filament bulk refill box:

- expected: four refill rolls;
- material: PLA;
- color: White;
- state: Ordered;
- physical inventory impact: zero.

The Overture White catalog identity exists so the order can reference the real product without pretending the shipment has arrived.

## Controlled receipt

The receipt page requires Cowboy to verify actual accepted quantity, condition, and receiving location. Its signed preview displays the permanent `THS-FIL` IDs and performs zero writes. Confirmation calls `InventoryActionService.receive_order`.

One atomic transaction creates:

- one immutable receiving batch;
- one individual physical inventory instance per accepted refill;
- one immutable order/batch/instance link per refill;
- normal inventory transactions and immutable audit records;
- one immutable batch receipt audit record;
- the updated cumulative received quantity and order state.

If any instance, transaction, link, or audit insert fails, the complete receipt rolls back. Partial receipts create only the verified count, keep the order in Delivered state, and allow another verified batch later.

All created instances retain Overture as manufacturer. No Bambu or RFID identity is assumed.

## Limitations

This checkpoint provides the verified seeded order and controlled receipt path. It does not add supplier editing, purchasing automation, invoices, shipping tracking, returns, or a general order editor.
