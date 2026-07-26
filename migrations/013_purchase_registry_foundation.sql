CREATE TABLE purchase_vendors (
  id INTEGER PRIMARY KEY,
  vendor_uuid TEXT NOT NULL UNIQUE,
  vendor_code TEXT UNIQUE,
  name TEXT NOT NULL,
  website TEXT,
  notes TEXT,
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX purchase_vendors_normalized_name
ON purchase_vendors(lower(trim(name)));

CREATE TABLE purchase_categories (
  id INTEGER PRIMARY KEY,
  category_code TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL UNIQUE,
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  sort_order INTEGER NOT NULL UNIQUE
);

INSERT INTO purchase_categories(category_code,display_name,sort_order) VALUES
  ('filament','Filament',10),
  ('maintenance_parts','Maintenance Parts',20),
  ('printer_parts','Printer Parts',30),
  ('tools','Tools',40),
  ('electronics','Electronics',50),
  ('consumables','Consumables',60),
  ('shipping','Shipping',70),
  ('tax','Tax',80),
  ('miscellaneous','Miscellaneous',90);

CREATE TABLE purchase_orders (
  id INTEGER PRIMARY KEY,
  purchase_uuid TEXT NOT NULL UNIQUE,
  purchase_number TEXT NOT NULL UNIQUE,
  vendor_id INTEGER NOT NULL REFERENCES purchase_vendors(id) ON DELETE RESTRICT,
  vendor_order_number TEXT,
  status TEXT NOT NULL CHECK(status IN
    ('ordered','partially_received','received','canceled')),
  purchase_date TEXT NOT NULL,
  currency_code TEXT NOT NULL DEFAULT 'USD'
    CHECK(length(currency_code)=3 AND currency_code=upper(currency_code)),
  subtotal_cents INTEGER NOT NULL CHECK(subtotal_cents>=0),
  tax_cents INTEGER NOT NULL DEFAULT 0 CHECK(tax_cents>=0),
  shipping_cents INTEGER NOT NULL DEFAULT 0 CHECK(shipping_cents>=0),
  discount_cents INTEGER NOT NULL DEFAULT 0 CHECK(discount_cents>=0),
  total_cents INTEGER NOT NULL CHECK(total_cents>=0),
  notes TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK(total_cents=subtotal_cents+tax_cents+shipping_cents-discount_cents)
);

CREATE UNIQUE INDEX purchase_orders_vendor_order_number
ON purchase_orders(vendor_id,lower(trim(vendor_order_number)))
WHERE vendor_order_number IS NOT NULL AND trim(vendor_order_number)<>'';

CREATE INDEX purchase_orders_status_date
ON purchase_orders(status,purchase_date DESC,id DESC);

CREATE TABLE purchase_order_lines (
  id INTEGER PRIMARY KEY,
  line_uuid TEXT NOT NULL UNIQUE,
  purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE RESTRICT,
  line_number INTEGER NOT NULL CHECK(line_number>0),
  category_id INTEGER NOT NULL REFERENCES purchase_categories(id) ON DELETE RESTRICT,
  description TEXT NOT NULL,
  vendor_sku TEXT,
  catalog_item_id INTEGER REFERENCES catalog_items(id) ON DELETE RESTRICT,
  quantity_ordered TEXT NOT NULL
    CHECK(CAST(quantity_ordered AS REAL)>0),
  unit_label TEXT NOT NULL,
  unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents>=0),
  line_discount_cents INTEGER NOT NULL DEFAULT 0 CHECK(line_discount_cents>=0),
  line_total_cents INTEGER NOT NULL CHECK(line_total_cents>=0),
  inventory_tracking_intent TEXT NOT NULL CHECK(inventory_tracking_intent IN
    ('individual','lot','quantity','non_inventory')),
  notes TEXT,
  UNIQUE(purchase_order_id,line_number)
);

CREATE INDEX purchase_order_lines_purchase
ON purchase_order_lines(purchase_order_id,line_number);

CREATE TABLE purchase_history (
  id INTEGER PRIMARY KEY,
  history_uuid TEXT NOT NULL UNIQUE,
  request_nonce TEXT NOT NULL UNIQUE,
  purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE RESTRICT,
  action_type TEXT NOT NULL CHECK(action_type IN
    ('create_purchase','cancel_purchase','receive_purchase','add_evidence')),
  previous_status TEXT,
  new_status TEXT NOT NULL CHECK(new_status IN
    ('ordered','partially_received','received','canceled')),
  snapshot TEXT NOT NULL CHECK(json_valid(snapshot)),
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
  reason TEXT,
  actor TEXT NOT NULL,
  occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX purchase_history_order
ON purchase_history(purchase_order_id,occurred_at,id);

CREATE TRIGGER purchase_vendors_no_delete
BEFORE DELETE ON purchase_vendors
BEGIN SELECT RAISE(ABORT,'purchase vendors with permanent history cannot be deleted'); END;

CREATE TRIGGER purchase_orders_identity_immutable
BEFORE UPDATE OF purchase_uuid,purchase_number,vendor_id,purchase_date,created_by,created_at
ON purchase_orders
BEGIN SELECT RAISE(ABORT,'purchase identity is immutable'); END;

CREATE TRIGGER purchase_orders_phase1_details_immutable
BEFORE UPDATE OF vendor_order_number,status,currency_code,subtotal_cents,tax_cents,
  shipping_cents,discount_cents,total_cents,notes
ON purchase_orders
BEGIN SELECT RAISE(ABORT,'purchase changes require a controlled history transition'); END;

CREATE TRIGGER purchase_orders_no_delete
BEFORE DELETE ON purchase_orders
BEGIN SELECT RAISE(ABORT,'purchase registry history cannot be deleted'); END;

CREATE TRIGGER purchase_order_lines_immutable_update
BEFORE UPDATE ON purchase_order_lines
BEGIN SELECT RAISE(ABORT,'purchase line history is immutable'); END;

CREATE TRIGGER purchase_order_lines_immutable_delete
BEFORE DELETE ON purchase_order_lines
BEGIN SELECT RAISE(ABORT,'purchase line history is immutable'); END;

CREATE TRIGGER purchase_history_immutable_update
BEFORE UPDATE ON purchase_history
BEGIN SELECT RAISE(ABORT,'purchase history is immutable'); END;

CREATE TRIGGER purchase_history_immutable_delete
BEFORE DELETE ON purchase_history
BEGIN SELECT RAISE(ABORT,'purchase history is immutable'); END;

CREATE TRIGGER purchase_categories_no_delete
BEFORE DELETE ON purchase_categories
BEGIN SELECT RAISE(ABORT,'purchase categories referenced by history cannot be deleted'); END;
