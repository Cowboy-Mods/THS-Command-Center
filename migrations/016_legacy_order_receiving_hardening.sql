-- Legacy receiving keeps receiving_batches.received_at as the historical
-- system-write timestamp. Physical receipt facts are stored separately.
ALTER TABLE receiving_batches ADD COLUMN physical_receipt_date TEXT
  CHECK(physical_receipt_date IS NULL OR physical_receipt_date GLOB '????-??-??');
ALTER TABLE receiving_batches ADD COLUMN physical_receipt_time TEXT
  CHECK(physical_receipt_time IS NULL OR physical_receipt_time GLOB '??:??:??');
ALTER TABLE receiving_batches ADD COLUMN receipt_time_precision TEXT NOT NULL DEFAULT 'unknown'
  CHECK(receipt_time_precision IN ('exact','estimated','date_only','unknown'));
ALTER TABLE receiving_batches ADD COLUMN recorded_at TEXT;

ALTER TABLE orders ADD COLUMN physical_received_date TEXT
  CHECK(physical_received_date IS NULL OR physical_received_date GLOB '????-??-??');
ALTER TABLE orders ADD COLUMN physical_received_time TEXT
  CHECK(physical_received_time IS NULL OR physical_received_time GLOB '??:??:??');
ALTER TABLE orders ADD COLUMN receipt_time_precision TEXT
  CHECK(receipt_time_precision IS NULL OR receipt_time_precision IN
    ('exact','estimated','date_only','unknown'));

CREATE TABLE catalog_item_history (
  id INTEGER PRIMARY KEY,
  history_uuid TEXT NOT NULL UNIQUE,
  request_nonce TEXT NOT NULL UNIQUE,
  catalog_item_id INTEGER NOT NULL REFERENCES catalog_items(id) ON DELETE RESTRICT,
  action_type TEXT NOT NULL CHECK(action_type='correct_catalog_identity'),
  previous_snapshot TEXT NOT NULL CHECK(json_valid(previous_snapshot)),
  new_snapshot TEXT NOT NULL CHECK(json_valid(new_snapshot)),
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
  actor TEXT NOT NULL,
  reason TEXT NOT NULL,
  recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX catalog_item_history_item
ON catalog_item_history(catalog_item_id,recorded_at,id);

CREATE TRIGGER catalog_item_history_immutable_update
BEFORE UPDATE ON catalog_item_history
BEGIN SELECT RAISE(ABORT,'catalog item history is immutable'); END;
CREATE TRIGGER catalog_item_history_immutable_delete
BEFORE DELETE ON catalog_item_history
BEGIN SELECT RAISE(ABORT,'catalog item history is immutable'); END;

CREATE TABLE receiving_batch_delivery_evidence (
  id INTEGER PRIMARY KEY,
  link_uuid TEXT NOT NULL UNIQUE,
  receiving_batch_id INTEGER NOT NULL REFERENCES receiving_batches(id) ON DELETE RESTRICT,
  evidence_id INTEGER NOT NULL REFERENCES order_delivery_evidence(id) ON DELETE RESTRICT,
  linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(receiving_batch_id,evidence_id)
);

CREATE INDEX receiving_batch_delivery_evidence_batch
ON receiving_batch_delivery_evidence(receiving_batch_id,id);

CREATE TRIGGER receiving_batch_delivery_evidence_same_order
BEFORE INSERT ON receiving_batch_delivery_evidence
WHEN (SELECT order_id FROM receiving_batches WHERE id=NEW.receiving_batch_id)
  IS NOT (SELECT order_id FROM order_delivery_evidence WHERE id=NEW.evidence_id)
BEGIN SELECT RAISE(ABORT,'delivery evidence belongs to a different order'); END;
CREATE TRIGGER receiving_batch_delivery_evidence_immutable_update
BEFORE UPDATE ON receiving_batch_delivery_evidence
BEGIN SELECT RAISE(ABORT,'receiving evidence linkage is immutable'); END;
CREATE TRIGGER receiving_batch_delivery_evidence_immutable_delete
BEFORE DELETE ON receiving_batch_delivery_evidence
BEGIN SELECT RAISE(ABORT,'receiving evidence linkage is immutable'); END;

INSERT OR IGNORE INTO attribute_definitions(name,data_type,unit_dimension)
VALUES ('filament_form','text',NULL);
INSERT OR IGNORE INTO item_type_attributes(
  item_type_id,attribute_definition_id,required,display_order
)
SELECT it.id,ad.id,0,50 FROM item_types it,attribute_definitions ad
WHERE it.name='Filament' AND ad.name='filament_form';
