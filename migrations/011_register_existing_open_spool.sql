CREATE TABLE open_spool_registrations (
  id INTEGER PRIMARY KEY,
  registration_uuid TEXT NOT NULL UNIQUE,
  request_nonce TEXT NOT NULL UNIQUE,
  instance_id INTEGER NOT NULL UNIQUE REFERENCES inventory_instances(id) ON DELETE RESTRICT,
  catalog_item_id INTEGER NOT NULL REFERENCES catalog_items(id) ON DELETE RESTRICT,
  quantity_mode TEXT NOT NULL CHECK(quantity_mode IN ('exact','estimated','unknown')),
  remaining_quantity REAL CHECK(remaining_quantity IS NULL OR remaining_quantity>=0),
  quantity_confidence TEXT NOT NULL CHECK(quantity_confidence IN
    ('weighed','manufacturer_estimate','visual_estimate','unknown')),
  source TEXT NOT NULL CHECK(source='pre_existing_inventory'),
  note TEXT,
  initial_location_type TEXT NOT NULL CHECK(initial_location_type IN ('storage','ams')),
  initial_location_id INTEGER REFERENCES locations(id) ON DELETE RESTRICT,
  initial_slot_id INTEGER REFERENCES equipment_slots(id) ON DELETE RESTRICT,
  duplicate_warning_count INTEGER NOT NULL DEFAULT 0 CHECK(duplicate_warning_count>=0),
  duplicate_warning_acknowledged INTEGER NOT NULL CHECK(duplicate_warning_acknowledged IN (0,1)),
  actor TEXT NOT NULL,
  registered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK(
    (quantity_mode='exact' AND remaining_quantity IS NOT NULL AND quantity_confidence='weighed')
    OR
    (quantity_mode='estimated' AND remaining_quantity IS NOT NULL
      AND quantity_confidence IN ('manufacturer_estimate','visual_estimate')
      AND note IS NOT NULL AND length(trim(note))>0)
    OR
    (quantity_mode='unknown' AND remaining_quantity IS NULL
      AND quantity_confidence='unknown'
      AND note IS NOT NULL AND length(trim(note))>0)
  ),
  CHECK(
    (initial_location_type='storage' AND initial_location_id IS NOT NULL AND initial_slot_id IS NULL)
    OR
    (initial_location_type='ams' AND initial_location_id IS NULL AND initial_slot_id IS NOT NULL)
  )
);

CREATE TRIGGER open_spool_registrations_immutable_update
BEFORE UPDATE ON open_spool_registrations
BEGIN SELECT RAISE(ABORT,'open spool registration history is immutable'); END;

CREATE TRIGGER open_spool_registrations_immutable_delete
BEFORE DELETE ON open_spool_registrations
BEGIN SELECT RAISE(ABORT,'open spool registration history is immutable'); END;
