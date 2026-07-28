PRAGMA foreign_keys=OFF;

BEGIN IMMEDIATE;

CREATE TABLE inventory_workflow_transactions_v19 (
  id INTEGER PRIMARY KEY,
  workflow_uuid TEXT NOT NULL UNIQUE,
  review_nonce TEXT NOT NULL UNIQUE,
  occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  workflow_type TEXT NOT NULL CHECK(workflow_type IN ('replace_active_filament_spool')),
  actor TEXT NOT NULL,
  module TEXT NOT NULL,
  origin TEXT NOT NULL CHECK(origin IN (
    'user','maeve','importer','system','api','integration','project'
  )),
  reason TEXT,
  current_instance_id INTEGER NOT NULL
    REFERENCES inventory_instances(id) ON DELETE RESTRICT,
  replacement_instance_id INTEGER
    REFERENCES inventory_instances(id) ON DELETE RESTRICT,
  destination_slot_id INTEGER
    REFERENCES equipment_slots(id) ON DELETE RESTRICT,
  print_job_name TEXT,
  approximate_layer INTEGER
    CHECK(approximate_layer IS NULL OR approximate_layer>=0),
  printer TEXT,
  plate TEXT,
  operational_note TEXT,
  outgoing_disposition TEXT
    CHECK(outgoing_disposition IS NULL OR outgoing_disposition IN (
      'empty','storage','ams_slot'
    )),
  outgoing_destination_location_id INTEGER
    REFERENCES locations(id) ON DELETE RESTRICT,
  outgoing_destination_slot_id INTEGER
    REFERENCES equipment_slots(id) ON DELETE RESTRICT,
  incoming_disposition TEXT
    CHECK(incoming_disposition IS NULL OR incoming_disposition IN (
      'sealed','open','none'
    )),
  incoming_source_location_id INTEGER
    REFERENCES locations(id) ON DELETE RESTRICT,
  incoming_source_slot_id INTEGER
    REFERENCES equipment_slots(id) ON DELETE RESTRICT,
  incoming_instance_id INTEGER
    REFERENCES inventory_instances(id) ON DELETE RESTRICT,
  incoming_destination_slot_id INTEGER
    REFERENCES equipment_slots(id) ON DELETE RESTRICT,

  CHECK(
    replacement_instance_id IS NULL
    OR current_instance_id <> replacement_instance_id
  ),
  CHECK(
    incoming_instance_id IS NULL
    OR current_instance_id <> incoming_instance_id
  ),
  CHECK(
    (
      outgoing_disposition IS NULL
      AND outgoing_destination_location_id IS NULL
      AND outgoing_destination_slot_id IS NULL
      AND incoming_disposition IS NULL
      AND incoming_source_location_id IS NULL
      AND incoming_source_slot_id IS NULL
      AND incoming_instance_id IS NULL
      AND incoming_destination_slot_id IS NULL
    )
    OR
    (
      outgoing_disposition IS NOT NULL
      AND incoming_disposition IS NOT NULL
      AND replacement_instance_id IS NULL
      AND destination_slot_id IS NULL
    )
  ),
  CHECK(
    outgoing_disposition IS NULL
    OR (
      outgoing_disposition='empty'
      AND outgoing_destination_location_id IS NULL
      AND outgoing_destination_slot_id IS NULL
    )
    OR (
      outgoing_disposition='storage'
      AND outgoing_destination_location_id IS NOT NULL
      AND outgoing_destination_slot_id IS NULL
    )
    OR (
      outgoing_disposition='ams_slot'
      AND outgoing_destination_location_id IS NULL
      AND outgoing_destination_slot_id IS NOT NULL
    )
  ),
  CHECK(
    incoming_disposition IS NULL
    OR (
      incoming_disposition='none'
      AND incoming_source_location_id IS NULL
      AND incoming_source_slot_id IS NULL
      AND incoming_instance_id IS NULL
      AND incoming_destination_slot_id IS NULL
    )
    OR (
      incoming_disposition IN ('sealed','open')
      AND incoming_instance_id IS NOT NULL
      AND incoming_destination_slot_id IS NOT NULL
      AND (
        (incoming_source_location_id IS NOT NULL AND incoming_source_slot_id IS NULL)
        OR
        (incoming_source_location_id IS NULL AND incoming_source_slot_id IS NOT NULL)
      )
    )
  ),
  CHECK(
    outgoing_destination_slot_id IS NULL
    OR incoming_destination_slot_id IS NULL
    OR outgoing_destination_slot_id <> incoming_destination_slot_id
  ),
  CHECK(
    incoming_source_slot_id IS NULL
    OR incoming_destination_slot_id IS NULL
    OR incoming_source_slot_id <> incoming_destination_slot_id
  )
);

INSERT INTO inventory_workflow_transactions_v19(
  id,workflow_uuid,review_nonce,occurred_at,workflow_type,actor,module,origin,
  reason,current_instance_id,replacement_instance_id,destination_slot_id,
  print_job_name,approximate_layer,printer,plate,operational_note,
  outgoing_disposition,outgoing_destination_location_id,
  outgoing_destination_slot_id,incoming_disposition,
  incoming_source_location_id,incoming_source_slot_id,incoming_instance_id,
  incoming_destination_slot_id
)
SELECT
  id,workflow_uuid,review_nonce,occurred_at,workflow_type,actor,module,origin,
  reason,current_instance_id,replacement_instance_id,destination_slot_id,
  print_job_name,approximate_layer,printer,plate,operational_note,
  NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL
FROM inventory_workflow_transactions;

DROP TABLE inventory_workflow_transactions;
ALTER TABLE inventory_workflow_transactions_v19
RENAME TO inventory_workflow_transactions;

CREATE TRIGGER inventory_workflow_transactions_immutable_update
BEFORE UPDATE ON inventory_workflow_transactions
BEGIN
  SELECT RAISE(ABORT,'inventory workflow transaction history is immutable');
END;

CREATE TRIGGER inventory_workflow_transactions_immutable_delete
BEFORE DELETE ON inventory_workflow_transactions
BEGIN
  SELECT RAISE(ABORT,'inventory workflow transaction history is immutable');
END;

COMMIT;

PRAGMA foreign_keys=ON;
