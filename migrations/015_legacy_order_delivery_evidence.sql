CREATE TABLE order_delivery_evidence (
  id INTEGER PRIMARY KEY,
  evidence_uuid TEXT NOT NULL UNIQUE,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
  evidence_scope TEXT NOT NULL DEFAULT 'delivery' CHECK(evidence_scope='delivery'),
  evidence_type TEXT NOT NULL CHECK(evidence_type IN
    ('photo','screenshot','document','other')),
  file_path TEXT NOT NULL,
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  file_size INTEGER NOT NULL CHECK(file_size>=0),
  caption TEXT NOT NULL,
  captured_at TEXT,
  metadata_json TEXT CHECK(metadata_json IS NULL OR json_valid(metadata_json)),
  actor TEXT NOT NULL,
  request_nonce TEXT NOT NULL UNIQUE,
  added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(order_id,sha256)
);

CREATE INDEX order_delivery_evidence_order
ON order_delivery_evidence(order_id,added_at,id);

CREATE TABLE order_delivery_evidence_history (
  id INTEGER PRIMARY KEY,
  history_uuid TEXT NOT NULL UNIQUE,
  request_nonce TEXT NOT NULL UNIQUE,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
  evidence_id INTEGER NOT NULL REFERENCES order_delivery_evidence(id) ON DELETE RESTRICT,
  action_type TEXT NOT NULL CHECK(action_type='add_delivery_evidence'),
  snapshot TEXT NOT NULL CHECK(json_valid(snapshot)),
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
  actor TEXT NOT NULL,
  occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX order_delivery_evidence_history_order
ON order_delivery_evidence_history(order_id,occurred_at,id);

CREATE TRIGGER order_delivery_evidence_immutable_update
BEFORE UPDATE ON order_delivery_evidence
BEGIN SELECT RAISE(ABORT,'legacy order delivery evidence is immutable'); END;

CREATE TRIGGER order_delivery_evidence_immutable_delete
BEFORE DELETE ON order_delivery_evidence
BEGIN SELECT RAISE(ABORT,'legacy order delivery evidence is immutable'); END;

CREATE TRIGGER order_delivery_evidence_history_immutable_update
BEFORE UPDATE ON order_delivery_evidence_history
BEGIN SELECT RAISE(ABORT,'legacy order delivery evidence history is immutable'); END;

CREATE TRIGGER order_delivery_evidence_history_immutable_delete
BEFORE DELETE ON order_delivery_evidence_history
BEGIN SELECT RAISE(ABORT,'legacy order delivery evidence history is immutable'); END;
