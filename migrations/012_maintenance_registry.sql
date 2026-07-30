CREATE TABLE maintenance_assets (
  id INTEGER PRIMARY KEY,
  asset_uuid TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL UNIQUE,
  asset_type TEXT NOT NULL CHECK(asset_type IN ('printer','shop_equipment')),
  printer_id INTEGER UNIQUE REFERENCES printers(id) ON DELETE RESTRICT,
  equipment_id INTEGER UNIQUE REFERENCES equipment(id) ON DELETE RESTRICT,
  readiness_state TEXT NOT NULL DEFAULT 'normal' CHECK(readiness_state IN
    ('normal','monitor_during_printing','no_unattended_printing','out_of_service')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK((asset_type='printer' AND printer_id IS NOT NULL AND equipment_id IS NULL)
     OR (asset_type='shop_equipment' AND printer_id IS NULL AND equipment_id IS NOT NULL))
);

INSERT INTO maintenance_assets(asset_uuid,display_name,asset_type,printer_id)
SELECT lower(hex(randomblob(16))),name,'printer',id FROM printers;

INSERT INTO maintenance_assets(asset_uuid,display_name,asset_type,equipment_id)
SELECT lower(hex(randomblob(16))),name,'shop_equipment',id FROM equipment;

CREATE TABLE maintenance_records (
  id INTEGER PRIMARY KEY,
  event_number TEXT NOT NULL UNIQUE,
  asset_id INTEGER NOT NULL REFERENCES maintenance_assets(id) ON DELETE RESTRICT,
  event_type TEXT NOT NULL CHECK(event_type IN
    ('inspection','cleaning','repair','preventive_maintenance','fault_discovered','part_replacement')),
  status TEXT NOT NULL CHECK(status IN
    ('pending','in_progress','blocked_waiting_for_part','completed','verified')),
  severity TEXT NOT NULL CHECK(severity IN
    ('informational','low','medium','high','printer_unsafe')),
  discovered_at TEXT NOT NULL,
  due_at TEXT,
  completed_at TEXT,
  symptoms TEXT NOT NULL,
  likely_cause TEXT,
  corrective_action TEXT,
  parts_required TEXT,
  parts_used TEXT,
  notes TEXT,
  related_print_id INTEGER REFERENCES print_records(id) ON DELETE RESTRICT,
  unattended_printing_allowed INTEGER NOT NULL CHECK(unattended_printing_allowed IN (0,1)),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK(status NOT IN ('completed','verified') OR completed_at IS NOT NULL)
);

CREATE INDEX maintenance_records_backlog
ON maintenance_records(status,due_at,severity);
CREATE INDEX maintenance_records_asset
ON maintenance_records(asset_id,discovered_at DESC);

CREATE TABLE maintenance_history (
  id INTEGER PRIMARY KEY,
  history_uuid TEXT NOT NULL UNIQUE,
  request_nonce TEXT NOT NULL UNIQUE,
  maintenance_record_id INTEGER NOT NULL REFERENCES maintenance_records(id) ON DELETE RESTRICT,
  action_type TEXT NOT NULL CHECK(action_type IN
    ('record_fault','create_task','mark_waiting_for_part','complete_maintenance',
     'verify_repair','reopen_task')),
  previous_status TEXT,
  new_status TEXT NOT NULL,
  previous_readiness_state TEXT,
  new_readiness_state TEXT NOT NULL,
  snapshot TEXT NOT NULL CHECK(json_valid(snapshot)),
  reason TEXT,
  actor TEXT NOT NULL,
  occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX maintenance_history_record
ON maintenance_history(maintenance_record_id,occurred_at,id);

CREATE TABLE maintenance_evidence (
  id INTEGER PRIMARY KEY,
  evidence_uuid TEXT NOT NULL UNIQUE,
  maintenance_record_id INTEGER NOT NULL REFERENCES maintenance_records(id) ON DELETE RESTRICT,
  evidence_type TEXT NOT NULL CHECK(evidence_type IN ('photo','video')),
  file_path TEXT NOT NULL,
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  caption TEXT,
  captured_at TEXT,
  added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  added_by TEXT NOT NULL,
  UNIQUE(maintenance_record_id,file_path,sha256)
);

CREATE TRIGGER maintenance_records_identity_immutable
BEFORE UPDATE OF event_number,asset_id,event_type,discovered_at,created_by,created_at
ON maintenance_records
BEGIN SELECT RAISE(ABORT,'maintenance record identity is immutable'); END;

CREATE TRIGGER maintenance_records_no_delete
BEFORE DELETE ON maintenance_records
BEGIN SELECT RAISE(ABORT,'maintenance registry history cannot be deleted'); END;

CREATE TRIGGER maintenance_completed_details_immutable
BEFORE UPDATE ON maintenance_records
WHEN OLD.status IN ('completed','verified') AND NEW.status=OLD.status
BEGIN SELECT RAISE(ABORT,'completed maintenance details require a controlled transition'); END;

CREATE TRIGGER maintenance_history_immutable_update
BEFORE UPDATE ON maintenance_history
BEGIN SELECT RAISE(ABORT,'maintenance audit history is immutable'); END;

CREATE TRIGGER maintenance_history_immutable_delete
BEFORE DELETE ON maintenance_history
BEGIN SELECT RAISE(ABORT,'maintenance audit history is immutable'); END;

CREATE TRIGGER maintenance_evidence_immutable_update
BEFORE UPDATE ON maintenance_evidence
BEGIN SELECT RAISE(ABORT,'maintenance evidence history is immutable'); END;

CREATE TRIGGER maintenance_evidence_immutable_delete
BEFORE DELETE ON maintenance_evidence
BEGIN SELECT RAISE(ABORT,'maintenance evidence history is immutable'); END;

CREATE TRIGGER maintenance_assets_no_delete
BEFORE DELETE ON maintenance_assets
BEGIN SELECT RAISE(ABORT,'maintenance equipment history cannot be deleted'); END;
