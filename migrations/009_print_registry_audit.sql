ALTER TABLE projects ADD COLUMN project_code TEXT;
ALTER TABLE projects ADD COLUMN progress_mode TEXT NOT NULL DEFAULT 'unknown'
  CHECK(progress_mode IN ('exact','estimated','stage','unknown'));
ALTER TABLE projects ADD COLUMN progress_percent REAL
  CHECK(progress_percent IS NULL OR progress_percent BETWEEN 0 AND 100);
ALTER TABLE projects ADD COLUMN progress_stage TEXT;
ALTER TABLE projects ADD COLUMN progress_note TEXT;
ALTER TABLE projects ADD COLUMN updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP;

CREATE UNIQUE INDEX projects_project_code
ON projects(project_code) WHERE project_code IS NOT NULL;

CREATE TABLE print_records (
  id INTEGER PRIMARY KEY,
  print_number TEXT NOT NULL UNIQUE,
  project_id INTEGER REFERENCES projects(id) ON DELETE RESTRICT,
  printer_id INTEGER REFERENCES printers(id) ON DELETE RESTRICT,
  job_name TEXT NOT NULL,
  plate_name TEXT,
  part_name TEXT NOT NULL,
  quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity>0),
  status TEXT NOT NULL CHECK(status IN ('planned','printing','completed','failed','cancelled')),
  inspection_status TEXT NOT NULL DEFAULT 'pending'
    CHECK(inspection_status IN ('pending','accepted','accepted_with_defect','rejected')),
  defect_notes TEXT,
  started_at TEXT,
  completed_at TEXT,
  operator TEXT NOT NULL,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK(status!='completed' OR completed_at IS NOT NULL),
  CHECK(inspection_status!='accepted_with_defect' OR
        (defect_notes IS NOT NULL AND length(trim(defect_notes))>0))
);

CREATE INDEX print_records_status_completed
ON print_records(status,completed_at DESC);

CREATE TABLE print_evidence (
  id INTEGER PRIMARY KEY,
  print_record_id INTEGER NOT NULL REFERENCES print_records(id) ON DELETE RESTRICT,
  evidence_type TEXT NOT NULL CHECK(evidence_type IN ('photo','video')),
  file_path TEXT NOT NULL,
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  caption TEXT,
  captured_at TEXT,
  added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  added_by TEXT NOT NULL,
  UNIQUE(print_record_id,file_path,sha256)
);

CREATE TABLE maintenance_events (
  id INTEGER PRIMARY KEY,
  event_number TEXT NOT NULL UNIQUE,
  printer_id INTEGER REFERENCES printers(id) ON DELETE RESTRICT,
  event_type TEXT NOT NULL,
  summary TEXT NOT NULL,
  details TEXT,
  severity TEXT NOT NULL CHECK(severity IN ('info','warning','critical')),
  occurred_at TEXT NOT NULL,
  resolved_at TEXT,
  actor TEXT NOT NULL,
  related_print_id INTEGER REFERENCES print_records(id) ON DELETE RESTRICT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX maintenance_events_occurred
ON maintenance_events(occurred_at DESC);

CREATE TABLE audit_events (
  id INTEGER PRIMARY KEY,
  event_uuid TEXT NOT NULL UNIQUE,
  occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actor TEXT NOT NULL,
  module TEXT NOT NULL,
  origin TEXT NOT NULL CHECK(origin IN ('user','maeve','importer','system','api','integration','project')),
  event_type TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id INTEGER,
  entity_human_id TEXT,
  summary TEXT NOT NULL,
  details TEXT CHECK(details IS NULL OR json_valid(details)),
  request_nonce TEXT UNIQUE
);

CREATE INDEX audit_events_entity
ON audit_events(entity_type,entity_id,occurred_at DESC);
CREATE INDEX audit_events_occurred
ON audit_events(occurred_at DESC);

CREATE TRIGGER print_records_immutable_identity
BEFORE UPDATE OF print_number ON print_records
BEGIN SELECT RAISE(ABORT,'print record identity is immutable'); END;
CREATE TRIGGER print_records_no_delete
BEFORE DELETE ON print_records
BEGIN SELECT RAISE(ABORT,'print registry history cannot be deleted'); END;
CREATE TRIGGER print_evidence_immutable_update
BEFORE UPDATE ON print_evidence
BEGIN SELECT RAISE(ABORT,'print evidence history is immutable'); END;
CREATE TRIGGER print_evidence_immutable_delete
BEFORE DELETE ON print_evidence
BEGIN SELECT RAISE(ABORT,'print evidence history is immutable'); END;
CREATE TRIGGER maintenance_events_immutable_update
BEFORE UPDATE ON maintenance_events
BEGIN SELECT RAISE(ABORT,'maintenance history is immutable'); END;
CREATE TRIGGER maintenance_events_immutable_delete
BEFORE DELETE ON maintenance_events
BEGIN SELECT RAISE(ABORT,'maintenance history is immutable'); END;
CREATE TRIGGER audit_events_immutable_update
BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT,'permanent audit history is immutable'); END;
CREATE TRIGGER audit_events_immutable_delete
BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT,'permanent audit history is immutable'); END;
