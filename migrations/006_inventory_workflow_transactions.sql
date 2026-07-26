CREATE TABLE inventory_workflow_transactions (
  id INTEGER PRIMARY KEY,
  workflow_uuid TEXT NOT NULL UNIQUE,
  review_nonce TEXT NOT NULL UNIQUE,
  occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  workflow_type TEXT NOT NULL CHECK(workflow_type IN ('replace_active_filament_spool')),
  actor TEXT NOT NULL,
  module TEXT NOT NULL,
  origin TEXT NOT NULL CHECK(origin IN ('user','maeve','importer','system','api','integration','project')),
  reason TEXT,
  current_instance_id INTEGER NOT NULL REFERENCES inventory_instances(id) ON DELETE RESTRICT,
  replacement_instance_id INTEGER NOT NULL REFERENCES inventory_instances(id) ON DELETE RESTRICT,
  destination_slot_id INTEGER NOT NULL REFERENCES equipment_slots(id) ON DELETE RESTRICT,
  CHECK(current_instance_id <> replacement_instance_id)
);

ALTER TABLE inventory_actions
ADD COLUMN workflow_transaction_id INTEGER
REFERENCES inventory_workflow_transactions(id) ON DELETE RESTRICT;

CREATE INDEX inventory_actions_workflow_transaction
ON inventory_actions(workflow_transaction_id,id);

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

