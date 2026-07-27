-- Purchase Registry receiving is separate from the legacy orders workflow.
-- Receiving records verified physical arrival only. It does not install, open,
-- assign, load, use, or consume any item.

CREATE TABLE purchase_fulfillment_state (
  purchase_order_id INTEGER PRIMARY KEY
    REFERENCES purchase_orders(id) ON DELETE RESTRICT,
  transport_status TEXT NOT NULL CHECK(transport_status IN
    ('ordered','shipped','delivered','canceled')),
  state_version INTEGER NOT NULL DEFAULT 1 CHECK(state_version>0),
  last_transition_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO purchase_fulfillment_state(purchase_order_id,transport_status)
SELECT id,
  CASE status
    WHEN 'canceled' THEN 'canceled'
    ELSE 'ordered'
  END
FROM purchase_orders;

CREATE TABLE purchase_fulfillment_history (
  id INTEGER PRIMARY KEY,
  transition_uuid TEXT NOT NULL UNIQUE,
  request_nonce TEXT NOT NULL UNIQUE,
  purchase_order_id INTEGER NOT NULL
    REFERENCES purchase_orders(id) ON DELETE RESTRICT,
  action_type TEXT NOT NULL CHECK(action_type IN
    ('transition_status','receive_purchase')),
  previous_status TEXT NOT NULL CHECK(previous_status IN
    ('ordered','shipped','delivered','partially_received','received','canceled')),
  new_status TEXT NOT NULL CHECK(new_status IN
    ('ordered','shipped','delivered','partially_received','received','canceled')),
  previous_snapshot TEXT NOT NULL CHECK(json_valid(previous_snapshot)),
  new_snapshot TEXT NOT NULL CHECK(json_valid(new_snapshot)),
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
  reason TEXT NOT NULL,
  actor TEXT NOT NULL,
  physical_event_date TEXT
    CHECK(physical_event_date IS NULL OR physical_event_date GLOB '????-??-??'),
  physical_event_time TEXT
    CHECK(physical_event_time IS NULL OR physical_event_time GLOB '??:??:??'),
  event_time_precision TEXT NOT NULL DEFAULT 'unknown' CHECK(event_time_precision IN
    ('exact','estimated','date_only','unknown')),
  occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX purchase_fulfillment_history_order
ON purchase_fulfillment_history(purchase_order_id,occurred_at,id);

CREATE TABLE purchase_receipts (
  id INTEGER PRIMARY KEY,
  receipt_uuid TEXT NOT NULL UNIQUE,
  purchase_order_id INTEGER NOT NULL
    REFERENCES purchase_orders(id) ON DELETE RESTRICT,
  request_nonce TEXT NOT NULL UNIQUE,
  actor TEXT NOT NULL,
  physical_receipt_date TEXT NOT NULL
    CHECK(physical_receipt_date GLOB '????-??-??'),
  physical_receipt_time TEXT
    CHECK(physical_receipt_time IS NULL OR physical_receipt_time GLOB '??:??:??'),
  receipt_time_precision TEXT NOT NULL CHECK(receipt_time_precision IN
    ('exact','estimated','date_only')),
  note TEXT,
  recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK(
    (receipt_time_precision='date_only' AND physical_receipt_time IS NULL)
    OR
    (receipt_time_precision IN ('exact','estimated') AND physical_receipt_time IS NOT NULL)
  )
);

CREATE INDEX purchase_receipts_order
ON purchase_receipts(purchase_order_id,recorded_at,id);

CREATE TABLE purchase_receipt_lines (
  id INTEGER PRIMARY KEY,
  receipt_line_uuid TEXT NOT NULL UNIQUE,
  purchase_receipt_id INTEGER NOT NULL
    REFERENCES purchase_receipts(id) ON DELETE RESTRICT,
  purchase_order_line_id INTEGER NOT NULL
    REFERENCES purchase_order_lines(id) ON DELETE RESTRICT,
  quantity_received TEXT NOT NULL CHECK(CAST(quantity_received AS REAL)>0),
  unit_label TEXT NOT NULL,
  condition TEXT NOT NULL CHECK(condition IN ('new','good','damaged')),
  catalog_item_id INTEGER REFERENCES catalog_items(id) ON DELETE RESTRICT,
  tracking_policy TEXT NOT NULL CHECK(tracking_policy IN
    ('individual','quantity','lot','non_inventory')),
  location_id INTEGER REFERENCES locations(id) ON DELETE RESTRICT,
  lot_number TEXT,
  expiration_date TEXT
    CHECK(expiration_date IS NULL OR expiration_date GLOB '????-??-??'),
  note TEXT,
  UNIQUE(purchase_receipt_id,purchase_order_line_id),
  CHECK(
    (tracking_policy='non_inventory' AND catalog_item_id IS NULL AND location_id IS NULL)
    OR
    (tracking_policy<>'non_inventory' AND catalog_item_id IS NOT NULL AND location_id IS NOT NULL)
  )
);

CREATE INDEX purchase_receipt_lines_purchase_line
ON purchase_receipt_lines(purchase_order_line_id,purchase_receipt_id);

CREATE TABLE purchase_receipt_evidence (
  id INTEGER PRIMARY KEY,
  link_uuid TEXT NOT NULL UNIQUE,
  purchase_receipt_id INTEGER NOT NULL
    REFERENCES purchase_receipts(id) ON DELETE RESTRICT,
  purchase_receipt_line_id INTEGER
    REFERENCES purchase_receipt_lines(id) ON DELETE RESTRICT,
  purchase_evidence_id INTEGER NOT NULL
    REFERENCES purchase_evidence(id) ON DELETE RESTRICT,
  linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(purchase_receipt_id,purchase_receipt_line_id,purchase_evidence_id)
);

CREATE INDEX purchase_receipt_evidence_receipt
ON purchase_receipt_evidence(purchase_receipt_id,purchase_receipt_line_id,id);

CREATE TABLE purchase_receipt_inventory_links (
  id INTEGER PRIMARY KEY,
  link_uuid TEXT NOT NULL UNIQUE,
  purchase_receipt_line_id INTEGER NOT NULL
    REFERENCES purchase_receipt_lines(id) ON DELETE RESTRICT,
  inventory_instance_id INTEGER
    REFERENCES inventory_instances(id) ON DELETE RESTRICT,
  stock_lot_id INTEGER REFERENCES stock_lots(id) ON DELETE RESTRICT,
  represented_quantity TEXT NOT NULL CHECK(CAST(represented_quantity AS REAL)>0),
  linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK((inventory_instance_id IS NOT NULL)+(stock_lot_id IS NOT NULL)=1)
);

CREATE INDEX purchase_receipt_inventory_line
ON purchase_receipt_inventory_links(purchase_receipt_line_id,id);

CREATE TRIGGER purchase_receipt_evidence_same_purchase
BEFORE INSERT ON purchase_receipt_evidence
WHEN
  (SELECT purchase_order_id FROM purchase_receipts WHERE id=NEW.purchase_receipt_id)
  IS NOT
  (SELECT purchase_order_id FROM purchase_evidence WHERE id=NEW.purchase_evidence_id)
OR (
  NEW.purchase_receipt_line_id IS NOT NULL
  AND
  (SELECT purchase_receipt_id FROM purchase_receipt_lines
   WHERE id=NEW.purchase_receipt_line_id) IS NOT NEW.purchase_receipt_id
)
BEGIN SELECT RAISE(ABORT,'receipt evidence must belong to the same purchase and receipt'); END;

CREATE TRIGGER purchase_receipt_evidence_delivery_only
BEFORE INSERT ON purchase_receipt_evidence
WHEN (SELECT evidence_scope FROM purchase_evidence WHERE id=NEW.purchase_evidence_id)
  IS NOT 'delivery'
BEGIN SELECT RAISE(ABORT,'receiving requires delivery-scoped evidence'); END;

CREATE TRIGGER purchase_fulfillment_state_no_delete
BEFORE DELETE ON purchase_fulfillment_state
BEGIN SELECT RAISE(ABORT,'purchase fulfillment state cannot be deleted'); END;

CREATE TRIGGER purchase_fulfillment_history_immutable_update
BEFORE UPDATE ON purchase_fulfillment_history
BEGIN SELECT RAISE(ABORT,'purchase fulfillment history is immutable'); END;
CREATE TRIGGER purchase_fulfillment_history_immutable_delete
BEFORE DELETE ON purchase_fulfillment_history
BEGIN SELECT RAISE(ABORT,'purchase fulfillment history is immutable'); END;
CREATE TRIGGER purchase_receipts_immutable_update
BEFORE UPDATE ON purchase_receipts
BEGIN SELECT RAISE(ABORT,'purchase receipts are immutable'); END;
CREATE TRIGGER purchase_receipts_immutable_delete
BEFORE DELETE ON purchase_receipts
BEGIN SELECT RAISE(ABORT,'purchase receipts are immutable'); END;
CREATE TRIGGER purchase_receipt_lines_immutable_update
BEFORE UPDATE ON purchase_receipt_lines
BEGIN SELECT RAISE(ABORT,'purchase receipt lines are immutable'); END;
CREATE TRIGGER purchase_receipt_lines_immutable_delete
BEFORE DELETE ON purchase_receipt_lines
BEGIN SELECT RAISE(ABORT,'purchase receipt lines are immutable'); END;
CREATE TRIGGER purchase_receipt_evidence_immutable_update
BEFORE UPDATE ON purchase_receipt_evidence
BEGIN SELECT RAISE(ABORT,'purchase receipt evidence links are immutable'); END;
CREATE TRIGGER purchase_receipt_evidence_immutable_delete
BEFORE DELETE ON purchase_receipt_evidence
BEGIN SELECT RAISE(ABORT,'purchase receipt evidence links are immutable'); END;
CREATE TRIGGER purchase_receipt_inventory_links_immutable_update
BEFORE UPDATE ON purchase_receipt_inventory_links
BEGIN SELECT RAISE(ABORT,'purchase receipt inventory links are immutable'); END;
CREATE TRIGGER purchase_receipt_inventory_links_immutable_delete
BEFORE DELETE ON purchase_receipt_inventory_links
BEGIN SELECT RAISE(ABORT,'purchase receipt inventory links are immutable'); END;

CREATE VIEW purchase_line_receiving_status AS
SELECT
  pol.id AS purchase_order_line_id,
  pol.purchase_order_id,
  pol.line_number,
  pol.quantity_ordered,
  COALESCE((
    SELECT printf('%.3f',SUM(CAST(prl.quantity_received AS REAL)))
    FROM purchase_receipt_lines prl
    WHERE prl.purchase_order_line_id=pol.id
  ),'0') AS quantity_received,
  printf('%.3f',
    CAST(pol.quantity_ordered AS REAL)-COALESCE((
      SELECT SUM(CAST(prl.quantity_received AS REAL))
      FROM purchase_receipt_lines prl
      WHERE prl.purchase_order_line_id=pol.id
    ),0)
  ) AS quantity_outstanding
FROM purchase_order_lines pol;

CREATE VIEW purchase_order_receiving_status AS
SELECT
  po.id AS purchase_order_id,
  CASE
    WHEN pfs.transport_status='canceled' THEN 'canceled'
    WHEN NOT EXISTS (
      SELECT 1 FROM purchase_line_receiving_status plrs
      WHERE plrs.purchase_order_id=po.id
        AND CAST(plrs.quantity_received AS REAL)>0
    ) THEN pfs.transport_status
    WHEN NOT EXISTS (
      SELECT 1 FROM purchase_line_receiving_status plrs
      WHERE plrs.purchase_order_id=po.id
        AND CAST(plrs.quantity_outstanding AS REAL)>0.000001
    ) THEN 'received'
    ELSE 'partially_received'
  END AS status,
  pfs.transport_status,
  pfs.state_version
FROM purchase_orders po
JOIN purchase_fulfillment_state pfs ON pfs.purchase_order_id=po.id;
