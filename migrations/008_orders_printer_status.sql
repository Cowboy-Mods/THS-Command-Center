CREATE TABLE orders (
  id INTEGER PRIMARY KEY,
  order_number TEXT NOT NULL UNIQUE,
  supplier TEXT NOT NULL,
  description TEXT NOT NULL,
  catalog_item_id INTEGER REFERENCES catalog_items(id) ON DELETE RESTRICT,
  expected_quantity INTEGER NOT NULL CHECK(expected_quantity>0),
  received_quantity INTEGER NOT NULL DEFAULT 0 CHECK(received_quantity>=0),
  unit_label TEXT NOT NULL,
  material TEXT,
  color TEXT,
  state TEXT NOT NULL CHECK(state IN ('ordered','shipped','delivered','received','cancelled')),
  ordered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  shipped_at TEXT,
  delivered_at TEXT,
  received_at TEXT,
  cancelled_at TEXT,
  notes TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX orders_state_updated ON orders(state,updated_at DESC);

CREATE TABLE receiving_batches (
  id INTEGER PRIMARY KEY,
  batch_uuid TEXT NOT NULL UNIQUE,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
  received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actor TEXT NOT NULL,
  actual_quantity INTEGER NOT NULL CHECK(actual_quantity>0),
  condition TEXT NOT NULL CHECK(condition IN ('new','good','damaged')),
  note TEXT
);

CREATE TABLE order_received_instances (
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
  receiving_batch_id INTEGER NOT NULL REFERENCES receiving_batches(id) ON DELETE RESTRICT,
  instance_id INTEGER NOT NULL UNIQUE REFERENCES inventory_instances(id) ON DELETE RESTRICT,
  PRIMARY KEY(receiving_batch_id,instance_id)
);

CREATE TRIGGER receiving_batches_immutable_update
BEFORE UPDATE ON receiving_batches BEGIN
  SELECT RAISE(ABORT,'receiving batch history is immutable');
END;
CREATE TRIGGER receiving_batches_immutable_delete
BEFORE DELETE ON receiving_batches BEGIN
  SELECT RAISE(ABORT,'receiving batch history is immutable');
END;
CREATE TRIGGER order_received_instances_immutable_update
BEFORE UPDATE ON order_received_instances BEGIN
  SELECT RAISE(ABORT,'order receipt linkage is immutable');
END;
CREATE TRIGGER order_received_instances_immutable_delete
BEFORE DELETE ON order_received_instances BEGIN
  SELECT RAISE(ABORT,'order receipt linkage is immutable');
END;

CREATE TABLE printers (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  manufacturer TEXT NOT NULL,
  model TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('offline','idle','printing','paused','error','maintenance')),
  active_job_name TEXT,
  progress_percent REAL CHECK(progress_percent IS NULL OR progress_percent BETWEEN 0 AND 100),
  current_layer INTEGER CHECK(current_layer IS NULL OR current_layer>=0),
  total_layers INTEGER CHECK(total_layers IS NULL OR total_layers>0),
  estimated_finish_at TEXT,
  current_plate TEXT,
  loaded_ams_slots TEXT,
  current_filament TEXT,
  status_source TEXT NOT NULL CHECK(status_source IN ('manual','import','bambu_local','system')),
  last_update_at TEXT,
  warning_message TEXT,
  operational_note TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO catalog_items(
  item_type_id,manufacturer_id,name,product_line,variant,base_unit_id,notes
)
SELECT it.id,m.id,'PLA Filament','PLA Refill','White',u.id,
  'Verified catalog identity for ordered Overture White refill rolls; no physical inventory received yet.'
FROM item_types it,manufacturers m,units u
WHERE it.name='Filament' AND m.name='Overture' AND u.code='g'
  AND NOT EXISTS (
    SELECT 1 FROM catalog_items ci
    WHERE ci.item_type_id=it.id AND ci.manufacturer_id=m.id
      AND ci.product_line='PLA Refill' AND ci.variant='White'
  );

INSERT OR IGNORE INTO catalog_item_attribute_values(
  catalog_item_id,attribute_definition_id,text_value
)
SELECT ci.id,ad.id,v.value
FROM catalog_items ci
JOIN manufacturers m ON m.id=ci.manufacturer_id AND m.name='Overture'
JOIN (SELECT 'material' name,'PLA' value
      UNION ALL SELECT 'manufacturer_color_name','White') v
JOIN attribute_definitions ad ON ad.name=v.name
WHERE ci.product_line='PLA Refill' AND ci.variant='White';

INSERT OR IGNORE INTO catalog_item_attribute_values(
  catalog_item_id,attribute_definition_id,numeric_value
)
SELECT ci.id,ad.id,v.value
FROM catalog_items ci
JOIN manufacturers m ON m.id=ci.manufacturer_id AND m.name='Overture'
JOIN (SELECT 'diameter_mm' name,1.75 value
      UNION ALL SELECT 'nominal_weight_g',1000) v
JOIN attribute_definitions ad ON ad.name=v.name
WHERE ci.product_line='PLA Refill' AND ci.variant='White';

INSERT INTO orders(
  order_number,supplier,description,catalog_item_id,expected_quantity,unit_label,
  material,color,state,notes
)
SELECT 'THS-ORD-000001','Overture','White filament bulk refill box',ci.id,4,
  'refill rolls','PLA','White','ordered',
  'Expected contents only. Do not create physical inventory until arrival, count, and condition are verified.'
FROM catalog_items ci
JOIN manufacturers m ON m.id=ci.manufacturer_id
WHERE m.name='Overture' AND ci.product_line='PLA Refill' AND ci.variant='White';

INSERT INTO printers(
  name,manufacturer,model,status,status_source,last_update_at,operational_note
) VALUES (
  'THS Printer','Bambu Lab','P1S','offline','manual',NULL,
  'TweetyFixed is verified recent job context. No live status is asserted after the print.'
);

