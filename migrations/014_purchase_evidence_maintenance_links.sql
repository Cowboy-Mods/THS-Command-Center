CREATE TABLE purchase_evidence (
  id INTEGER PRIMARY KEY,
  evidence_uuid TEXT NOT NULL UNIQUE,
  purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE RESTRICT,
  evidence_scope TEXT NOT NULL CHECK(evidence_scope IN ('purchase','delivery')),
  evidence_type TEXT NOT NULL CHECK(evidence_type IN
    ('screenshot','invoice','receipt','photo','document','other')),
  file_path TEXT NOT NULL,
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  file_size INTEGER NOT NULL CHECK(file_size>=0),
  caption TEXT,
  document_date TEXT,
  added_by TEXT NOT NULL,
  added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(purchase_order_id,evidence_scope,file_path,sha256)
);

CREATE INDEX purchase_evidence_order
ON purchase_evidence(purchase_order_id,evidence_scope,added_at,id);

CREATE TABLE purchase_maintenance_links (
  id INTEGER PRIMARY KEY,
  link_uuid TEXT NOT NULL UNIQUE,
  purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE RESTRICT,
  purchase_order_line_id INTEGER REFERENCES purchase_order_lines(id) ON DELETE RESTRICT,
  maintenance_record_id INTEGER NOT NULL REFERENCES maintenance_records(id) ON DELETE RESTRICT,
  relationship_type TEXT NOT NULL CHECK(relationship_type IN
    ('required_part','corrective_replacement','spare_stock','maintenance_supply')),
  note TEXT,
  linked_by TEXT NOT NULL,
  linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(purchase_order_id,purchase_order_line_id,maintenance_record_id,relationship_type)
);

CREATE INDEX purchase_maintenance_links_purchase
ON purchase_maintenance_links(purchase_order_id,maintenance_record_id);

CREATE UNIQUE INDEX purchase_maintenance_links_unique_order
ON purchase_maintenance_links(purchase_order_id,maintenance_record_id,relationship_type)
WHERE purchase_order_line_id IS NULL;

CREATE UNIQUE INDEX purchase_maintenance_links_unique_line
ON purchase_maintenance_links(
  purchase_order_id,purchase_order_line_id,maintenance_record_id,relationship_type
)
WHERE purchase_order_line_id IS NOT NULL;

DROP TRIGGER purchase_history_immutable_update;
DROP TRIGGER purchase_history_immutable_delete;
DROP INDEX purchase_history_order;

ALTER TABLE purchase_history RENAME TO purchase_history_phase1;

CREATE TABLE purchase_history (
  id INTEGER PRIMARY KEY,
  history_uuid TEXT NOT NULL UNIQUE,
  request_nonce TEXT NOT NULL UNIQUE,
  purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE RESTRICT,
  action_type TEXT NOT NULL CHECK(action_type IN
    ('create_purchase','cancel_purchase','receive_purchase','add_evidence',
     'link_maintenance')),
  previous_status TEXT,
  new_status TEXT NOT NULL CHECK(new_status IN
    ('ordered','partially_received','received','canceled')),
  snapshot TEXT NOT NULL CHECK(json_valid(snapshot)),
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
  reason TEXT,
  actor TEXT NOT NULL,
  occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO purchase_history(
  id,history_uuid,request_nonce,purchase_order_id,action_type,previous_status,
  new_status,snapshot,payload_sha256,reason,actor,occurred_at
)
SELECT id,history_uuid,request_nonce,purchase_order_id,action_type,previous_status,
  new_status,snapshot,payload_sha256,reason,actor,occurred_at
FROM purchase_history_phase1;

DROP TABLE purchase_history_phase1;

CREATE INDEX purchase_history_order
ON purchase_history(purchase_order_id,occurred_at,id);

CREATE TRIGGER purchase_history_immutable_update
BEFORE UPDATE ON purchase_history
BEGIN SELECT RAISE(ABORT,'purchase history is immutable'); END;

CREATE TRIGGER purchase_history_immutable_delete
BEFORE DELETE ON purchase_history
BEGIN SELECT RAISE(ABORT,'purchase history is immutable'); END;

CREATE TRIGGER purchase_evidence_immutable_update
BEFORE UPDATE ON purchase_evidence
BEGIN SELECT RAISE(ABORT,'purchase evidence is immutable'); END;

CREATE TRIGGER purchase_evidence_immutable_delete
BEFORE DELETE ON purchase_evidence
BEGIN SELECT RAISE(ABORT,'purchase evidence is immutable'); END;

CREATE TRIGGER purchase_maintenance_links_immutable_update
BEFORE UPDATE ON purchase_maintenance_links
BEGIN SELECT RAISE(ABORT,'purchase maintenance linkage is immutable'); END;

CREATE TRIGGER purchase_maintenance_links_immutable_delete
BEFORE DELETE ON purchase_maintenance_links
BEGIN SELECT RAISE(ABORT,'purchase maintenance linkage is immutable'); END;
