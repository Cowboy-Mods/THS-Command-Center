CREATE TABLE inventory_actions (
  id INTEGER PRIMARY KEY,
  action_uuid TEXT NOT NULL UNIQUE,
  occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actor TEXT NOT NULL,
  module TEXT NOT NULL,
  origin TEXT NOT NULL CHECK(origin IN ('user','maeve','importer','system','api','integration','project')),
  action_type TEXT NOT NULL,
  reason TEXT,
  reversible INTEGER NOT NULL CHECK(reversible IN (0,1)),
  reverse_action TEXT,
  affected_entity_type TEXT NOT NULL,
  affected_entity_id INTEGER,
  affected_human_id TEXT,
  previous_state TEXT CHECK(previous_state IS NULL OR json_valid(previous_state)),
  new_state TEXT CHECK(new_state IS NULL OR json_valid(new_state)),
  transaction_id INTEGER REFERENCES inventory_transactions(id) ON DELETE RESTRICT,
  reverses_action_id INTEGER REFERENCES inventory_actions(id) ON DELETE RESTRICT,
  CHECK((reversible=1 AND reverse_action IS NOT NULL) OR
        (reversible=0 AND reverse_action IS NULL))
);

CREATE INDEX inventory_actions_affected_entity
ON inventory_actions(affected_entity_type,affected_entity_id,occurred_at);

CREATE INDEX inventory_actions_human_id
ON inventory_actions(affected_human_id,occurred_at);

CREATE TRIGGER inventory_actions_immutable_update
BEFORE UPDATE ON inventory_actions
BEGIN
  SELECT RAISE(ABORT,'inventory action history is immutable');
END;

CREATE TRIGGER inventory_actions_immutable_delete
BEFORE DELETE ON inventory_actions
BEGIN
  SELECT RAISE(ABORT,'inventory action history is immutable');
END;


