-- Preserve immutable procurement facts while allowing an audited, effective
-- inventory tracking policy to be selected before physical receiving.

BEGIN IMMEDIATE;

CREATE TABLE purchase_line_tracking_corrections (
  id INTEGER PRIMARY KEY,
  correction_uuid TEXT NOT NULL UNIQUE,
  request_nonce TEXT NOT NULL,
  purchase_order_line_id INTEGER NOT NULL UNIQUE
    REFERENCES purchase_order_lines(id) ON DELETE RESTRICT,
  original_tracking_policy TEXT NOT NULL CHECK(original_tracking_policy IN
    ('individual','quantity','lot','non_inventory')),
  effective_tracking_policy TEXT NOT NULL CHECK(effective_tracking_policy IN
    ('individual','quantity','lot','non_inventory')),
  reason TEXT NOT NULL CHECK(length(trim(reason))>0),
  actor TEXT NOT NULL CHECK(length(trim(actor))>0),
  module TEXT NOT NULL CHECK(length(trim(module))>0),
  origin TEXT NOT NULL CHECK(origin IN
    ('user','maeve','importer','system','api','integration','project')),
  provenance TEXT NOT NULL CHECK(length(trim(provenance))>0),
  payload_sha256 TEXT NOT NULL CHECK(
    length(payload_sha256)=64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
  ),
  corrected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK(original_tracking_policy<>effective_tracking_policy)
);

CREATE INDEX purchase_line_tracking_corrections_order
ON purchase_line_tracking_corrections(purchase_order_line_id,corrected_at,id);

CREATE INDEX purchase_line_tracking_corrections_nonce
ON purchase_line_tracking_corrections(request_nonce);

CREATE TRIGGER purchase_line_tracking_corrections_source_policy
BEFORE INSERT ON purchase_line_tracking_corrections
WHEN NEW.original_tracking_policy IS NOT
  (SELECT inventory_tracking_intent FROM purchase_order_lines
   WHERE id=NEW.purchase_order_line_id)
BEGIN
  SELECT RAISE(ABORT,'correction original policy must match immutable purchase line');
END;

CREATE TRIGGER purchase_line_tracking_corrections_before_receipt
BEFORE INSERT ON purchase_line_tracking_corrections
WHEN EXISTS (
  SELECT 1 FROM purchase_receipt_lines
  WHERE purchase_order_line_id=NEW.purchase_order_line_id
)
BEGIN
  SELECT RAISE(ABORT,'received purchase lines cannot be corrected');
END;

CREATE TRIGGER purchase_line_tracking_corrections_immutable_update
BEFORE UPDATE ON purchase_line_tracking_corrections
BEGIN
  SELECT RAISE(ABORT,'purchase line tracking corrections are append-only');
END;

CREATE TRIGGER purchase_line_tracking_corrections_immutable_delete
BEFORE DELETE ON purchase_line_tracking_corrections
BEGIN
  SELECT RAISE(ABORT,'purchase line tracking corrections are append-only');
END;

CREATE VIEW purchase_order_lines_effective AS
SELECT
  pol.*,
  COALESCE(pltc.effective_tracking_policy,pol.inventory_tracking_intent)
    AS effective_tracking_policy,
  pltc.id AS tracking_correction_id,
  pltc.correction_uuid AS tracking_correction_uuid,
  pltc.corrected_at AS tracking_corrected_at
FROM purchase_order_lines pol
LEFT JOIN purchase_line_tracking_corrections pltc
  ON pltc.purchase_order_line_id=pol.id;

-- Location creation remains controlled by InventoryActionService. This index
-- makes its parent/name idempotency rule enforceable under concurrent writes.
CREATE UNIQUE INDEX locations_active_parent_normalized_name
ON locations(COALESCE(parent_id,0),lower(trim(name)))
WHERE archived_at IS NULL;

COMMIT;
