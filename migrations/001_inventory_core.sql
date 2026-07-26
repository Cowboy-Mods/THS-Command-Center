PRAGMA foreign_keys = ON;

CREATE TABLE categories (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT,
  archived_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE units (
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  dimension TEXT NOT NULL, scale_to_base REAL NOT NULL DEFAULT 1 CHECK(scale_to_base>0)
);
CREATE TABLE item_types (
  id INTEGER PRIMARY KEY, category_id INTEGER NOT NULL REFERENCES categories(id),
  name TEXT NOT NULL UNIQUE, tracking_method TEXT NOT NULL CHECK(tracking_method IN ('quantity','individual','lot')),
  id_prefix TEXT UNIQUE, default_unit_id INTEGER NOT NULL REFERENCES units(id), archived_at TEXT
);
CREATE TABLE attribute_definitions (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
  data_type TEXT NOT NULL CHECK(data_type IN ('text','integer','decimal','boolean','date','choice')),
  unit_dimension TEXT, choices TEXT, validation_pattern TEXT
);
CREATE TABLE item_type_attributes (
  item_type_id INTEGER NOT NULL REFERENCES item_types(id),
  attribute_definition_id INTEGER NOT NULL REFERENCES attribute_definitions(id),
  required INTEGER NOT NULL DEFAULT 0 CHECK(required IN (0,1)), display_order INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(item_type_id,attribute_definition_id)
);
CREATE TABLE manufacturers (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, website TEXT, archived_at TEXT
);
CREATE TABLE catalog_items (
  id INTEGER PRIMARY KEY, item_type_id INTEGER NOT NULL REFERENCES item_types(id),
  manufacturer_id INTEGER REFERENCES manufacturers(id) ON DELETE RESTRICT,
  name TEXT NOT NULL, product_line TEXT NOT NULL DEFAULT '', variant TEXT NOT NULL DEFAULT '',
  manufacturer_sku TEXT, base_unit_id INTEGER NOT NULL REFERENCES units(id),
  notes TEXT, archived_at TEXT,
  UNIQUE(item_type_id,manufacturer_id,name,product_line,variant)
);
CREATE TABLE catalog_item_attribute_values (
  catalog_item_id INTEGER NOT NULL REFERENCES catalog_items(id) ON DELETE CASCADE,
  attribute_definition_id INTEGER NOT NULL REFERENCES attribute_definitions(id),
  text_value TEXT, numeric_value REAL, boolean_value INTEGER CHECK(boolean_value IN (0,1)),
  PRIMARY KEY(catalog_item_id,attribute_definition_id),
  CHECK((text_value IS NOT NULL)+(numeric_value IS NOT NULL)+(boolean_value IS NOT NULL)=1)
);
CREATE TABLE locations (
  id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES locations(id) ON DELETE RESTRICT,
  name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'storage',
  slot_number INTEGER, archived_at TEXT, UNIQUE(parent_id,name), UNIQUE(parent_id,slot_number)
);
CREATE TRIGGER locations_no_cycle_insert BEFORE INSERT ON locations
WHEN NEW.parent_id=NEW.id BEGIN SELECT RAISE(ABORT,'location cycle'); END;
CREATE TRIGGER locations_no_cycle_update BEFORE UPDATE OF parent_id ON locations
BEGIN
  SELECT CASE WHEN NEW.parent_id=NEW.id OR EXISTS(
    WITH RECURSIVE descendants(id) AS (
      SELECT id FROM locations WHERE parent_id=NEW.id
      UNION ALL SELECT l.id FROM locations l JOIN descendants d ON l.parent_id=d.id
    ) SELECT 1 FROM descendants WHERE id=NEW.parent_id
  ) THEN RAISE(ABORT,'location cycle') END;
END;
CREATE TABLE inventory_instances (
  id INTEGER PRIMARY KEY, permanent_id TEXT UNIQUE,
  catalog_item_id INTEGER NOT NULL REFERENCES catalog_items(id),
  state TEXT NOT NULL CHECK(state IN ('sealed','open','loaded','empty','archived','maintenance','damaged')),
  condition TEXT NOT NULL DEFAULT 'new', serial_number TEXT UNIQUE,
  lot_number TEXT, location_id INTEGER REFERENCES locations(id),
  original_quantity REAL NOT NULL CHECK(original_quantity>=0),
  remaining_quantity REAL NOT NULL CHECK(remaining_quantity>=0 AND remaining_quantity<=original_quantity),
  unit_id INTEGER NOT NULL REFERENCES units(id), purchase_date TEXT, opened_at TEXT, emptied_at TEXT,
  expires_at TEXT, archived_at TEXT, notes TEXT, verified INTEGER NOT NULL DEFAULT 0 CHECK(verified IN (0,1)),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE stock_lots (
  id INTEGER PRIMARY KEY, catalog_item_id INTEGER NOT NULL REFERENCES catalog_items(id),
  location_id INTEGER NOT NULL REFERENCES locations(id), lot_number TEXT, quantity REAL NOT NULL CHECK(quantity>=0),
  unit_id INTEGER NOT NULL REFERENCES units(id), condition TEXT NOT NULL DEFAULT 'new',
  expires_at TEXT, archived_at TEXT, verified INTEGER NOT NULL DEFAULT 0 CHECK(verified IN (0,1))
);
CREATE TABLE inventory_transactions (
  id INTEGER PRIMARY KEY, transaction_type TEXT NOT NULL CHECK(transaction_type IN
   ('purchase','add','receive','move','consume','correct','reserve','release','return','damage','loss',
    'mark_empty','archive','reconcile','project_allocate','project_complete','load','unload')),
  occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, reason TEXT, notes TEXT,
  origin TEXT NOT NULL DEFAULT 'manual' CHECK(origin IN ('manual','import','printer','system','project')),
  actor TEXT, project_ref TEXT, order_ref TEXT, print_job_ref TEXT
);
CREATE TABLE transaction_lines (
  id INTEGER PRIMARY KEY, transaction_id INTEGER NOT NULL REFERENCES inventory_transactions(id) ON DELETE RESTRICT,
  catalog_item_id INTEGER NOT NULL REFERENCES catalog_items(id), instance_id INTEGER REFERENCES inventory_instances(id),
  stock_lot_id INTEGER REFERENCES stock_lots(id), quantity_change REAL NOT NULL,
  unit_id INTEGER NOT NULL REFERENCES units(id), source_location_id INTEGER REFERENCES locations(id),
  destination_location_id INTEGER REFERENCES locations(id),
  CHECK(instance_id IS NOT NULL OR stock_lot_id IS NOT NULL)
);
CREATE TRIGGER transaction_history_immutable_update BEFORE UPDATE ON inventory_transactions
BEGIN SELECT RAISE(ABORT,'transaction history is immutable'); END;
CREATE TRIGGER transaction_history_immutable_delete BEFORE DELETE ON inventory_transactions
BEGIN SELECT RAISE(ABORT,'transaction history is immutable'); END;
CREATE TRIGGER transaction_lines_immutable_update BEFORE UPDATE ON transaction_lines
BEGIN SELECT RAISE(ABORT,'transaction history is immutable'); END;
CREATE TRIGGER transaction_lines_immutable_delete BEFORE DELETE ON transaction_lines
BEGIN SELECT RAISE(ABORT,'transaction history is immutable'); END;
CREATE TRIGGER permanent_id_immutable BEFORE UPDATE OF permanent_id ON inventory_instances
WHEN OLD.permanent_id IS NOT NEW.permanent_id BEGIN SELECT RAISE(ABORT,'permanent ID is immutable'); END;
CREATE TABLE equipment (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, equipment_type TEXT NOT NULL,
  location_id INTEGER REFERENCES locations(id), slot_count INTEGER CHECK(slot_count>=0), archived_at TEXT
);
CREATE TABLE equipment_slots (
  id INTEGER PRIMARY KEY, equipment_id INTEGER NOT NULL REFERENCES equipment(id) ON DELETE RESTRICT,
  location_id INTEGER NOT NULL UNIQUE REFERENCES locations(id), slot_number INTEGER NOT NULL,
  UNIQUE(equipment_id,slot_number)
);
CREATE TABLE ams_assignments (
  id INTEGER PRIMARY KEY, slot_id INTEGER NOT NULL REFERENCES equipment_slots(id),
  instance_id INTEGER NOT NULL REFERENCES inventory_instances(id),
  loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, unloaded_at TEXT,
  load_transaction_id INTEGER NOT NULL REFERENCES inventory_transactions(id),
  unload_transaction_id INTEGER REFERENCES inventory_transactions(id)
);
CREATE UNIQUE INDEX one_active_spool_per_ams_slot ON ams_assignments(slot_id) WHERE unloaded_at IS NULL;
CREATE UNIQUE INDEX one_active_ams_slot_per_spool ON ams_assignments(instance_id) WHERE unloaded_at IS NULL;
CREATE TABLE stock_rules (
  id INTEGER PRIMARY KEY, catalog_item_id INTEGER REFERENCES catalog_items(id),
  item_type_id INTEGER REFERENCES item_types(id), location_id INTEGER REFERENCES locations(id),
  minimum_quantity REAL NOT NULL CHECK(minimum_quantity>=0), reorder_quantity REAL NOT NULL CHECK(reorder_quantity>=0),
  unit_id INTEGER NOT NULL REFERENCES units(id), CHECK(catalog_item_id IS NOT NULL OR item_type_id IS NOT NULL)
);
CREATE TABLE reservations (
  id INTEGER PRIMARY KEY, catalog_item_id INTEGER NOT NULL REFERENCES catalog_items(id),
  quantity REAL NOT NULL CHECK(quantity>0), unit_id INTEGER NOT NULL REFERENCES units(id),
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','released','consumed','cancelled')),
  project_ref TEXT, override_shortage INTEGER NOT NULL DEFAULT 0 CHECK(override_shortage IN (0,1)),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, released_at TEXT
);
CREATE TABLE reservation_allocations (
  id INTEGER PRIMARY KEY, reservation_id INTEGER NOT NULL REFERENCES reservations(id) ON DELETE RESTRICT,
  instance_id INTEGER REFERENCES inventory_instances(id), stock_lot_id INTEGER REFERENCES stock_lots(id),
  quantity REAL NOT NULL CHECK(quantity>0), unit_id INTEGER NOT NULL REFERENCES units(id),
  CHECK((instance_id IS NOT NULL)+(stock_lot_id IS NOT NULL)=1)
);
CREATE TRIGGER reservation_instance_available BEFORE INSERT ON reservation_allocations
WHEN NEW.instance_id IS NOT NULL AND
 (SELECT remaining_quantity FROM inventory_instances WHERE id=NEW.instance_id) <
 NEW.quantity + COALESCE((SELECT SUM(ra.quantity) FROM reservation_allocations ra
 JOIN reservations r ON r.id=ra.reservation_id WHERE ra.instance_id=NEW.instance_id AND r.status='active'),0)
 AND (SELECT override_shortage FROM reservations WHERE id=NEW.reservation_id)=0
BEGIN SELECT RAISE(ABORT,'reservation exceeds available inventory'); END;
CREATE TABLE import_batches (
  id INTEGER PRIMARY KEY, filename TEXT NOT NULL, content_hash TEXT NOT NULL,
  status TEXT NOT NULL, dry_run INTEGER NOT NULL, accepted_count INTEGER NOT NULL DEFAULT 0,
  rejected_count INTEGER NOT NULL DEFAULT 0, warning_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, completed_at TEXT
);
CREATE UNIQUE INDEX one_applied_import_per_hash ON import_batches(content_hash) WHERE status='applied';
CREATE TABLE import_rows (
  id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES import_batches(id) ON DELETE RESTRICT,
  row_number INTEGER NOT NULL, external_id TEXT, status TEXT NOT NULL, message TEXT, raw_data TEXT NOT NULL
);
CREATE UNIQUE INDEX accepted_external_import_id ON import_rows(external_id)
WHERE external_id IS NOT NULL AND status='accepted';
CREATE TABLE projects (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'planned', archived_at TEXT
);
CREATE TABLE project_requirements (
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
  catalog_item_id INTEGER REFERENCES catalog_items(id), item_type_id INTEGER REFERENCES item_types(id),
  preferred_catalog_item_id INTEGER REFERENCES catalog_items(id), quantity REAL NOT NULL CHECK(quantity>0),
  unit_id INTEGER NOT NULL REFERENCES units(id), optional INTEGER NOT NULL DEFAULT 0 CHECK(optional IN (0,1)),
  CHECK(catalog_item_id IS NOT NULL OR item_type_id IS NOT NULL)
);
CREATE TABLE project_requirement_substitutes (
  requirement_id INTEGER NOT NULL REFERENCES project_requirements(id) ON DELETE RESTRICT,
  catalog_item_id INTEGER NOT NULL REFERENCES catalog_items(id),
  priority INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(requirement_id,catalog_item_id)
);

