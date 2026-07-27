CREATE TABLE equipment_types (
  id INTEGER PRIMARY KEY,
  type_code TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL UNIQUE,
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  sort_order INTEGER NOT NULL DEFAULT 0
);

INSERT INTO equipment_types(type_code,display_name,sort_order) VALUES
  ('printer','3D Printer',10),
  ('ams_unit','AMS Unit',20),
  ('camera','External Camera',30),
  ('sensor_module','Sensor Module',40),
  ('console','Raspberry Pi / Console Assembly',50),
  ('network_equipment','Network Equipment',60),
  ('shop_machine','Other Shop Machine',70);

CREATE TABLE equipment_subtypes (
  id INTEGER PRIMARY KEY,
  equipment_type_id INTEGER NOT NULL REFERENCES equipment_types(id) ON DELETE RESTRICT,
  subtype_code TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
  sort_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE(equipment_type_id,display_name)
);

INSERT INTO equipment_subtypes(equipment_type_id,subtype_code,display_name,sort_order)
SELECT id,'fdm_printer','FDM Printer',10 FROM equipment_types WHERE type_code='printer';
INSERT INTO equipment_subtypes(equipment_type_id,subtype_code,display_name,sort_order)
SELECT id,'bambu_ams','Bambu AMS',10 FROM equipment_types WHERE type_code='ams_unit';
INSERT INTO equipment_subtypes(equipment_type_id,subtype_code,display_name,sort_order)
SELECT id,'printer_monitoring_camera','Printer-monitoring Camera',10 FROM equipment_types WHERE type_code='camera';
INSERT INTO equipment_subtypes(equipment_type_id,subtype_code,display_name,sort_order)
SELECT id,'room_overview_camera','Room Overview Camera',20 FROM equipment_types WHERE type_code='camera';
INSERT INTO equipment_subtypes(equipment_type_id,subtype_code,display_name,sort_order)
SELECT id,'environment_sensor','Environment Sensor',10 FROM equipment_types WHERE type_code='sensor_module';
INSERT INTO equipment_subtypes(equipment_type_id,subtype_code,display_name,sort_order)
SELECT id,'raspberry_pi_console','Raspberry Pi Console',10 FROM equipment_types WHERE type_code='console';
INSERT INTO equipment_subtypes(equipment_type_id,subtype_code,display_name,sort_order)
SELECT id,'network_switch','Network Switch',10 FROM equipment_types WHERE type_code='network_equipment';
INSERT INTO equipment_subtypes(equipment_type_id,subtype_code,display_name,sort_order)
SELECT id,'poe_switch','PoE Switch',20 FROM equipment_types WHERE type_code='network_equipment';
INSERT INTO equipment_subtypes(equipment_type_id,subtype_code,display_name,sort_order)
SELECT id,'general_shop_machine','General Shop Machine',10 FROM equipment_types WHERE type_code='shop_machine';

CREATE TABLE equipment_registry (
  id INTEGER PRIMARY KEY,
  equipment_uuid TEXT NOT NULL UNIQUE,
  equipment_number TEXT NOT NULL UNIQUE
    CHECK(equipment_number GLOB 'THS-EQP-[0-9][0-9][0-9][0-9][0-9][0-9]'),
  display_name TEXT NOT NULL,
  equipment_type_id INTEGER NOT NULL REFERENCES equipment_types(id) ON DELETE RESTRICT,
  equipment_subtype_id INTEGER REFERENCES equipment_subtypes(id) ON DELETE RESTRICT,
  manufacturer_id INTEGER REFERENCES manufacturers(id) ON DELETE RESTRICT,
  model TEXT,
  manufacturer_serial_number TEXT,
  ths_asset_identifier TEXT,
  current_location_id INTEGER REFERENCES locations(id) ON DELETE RESTRICT,
  lifecycle_state TEXT NOT NULL DEFAULT 'registered' CHECK(lifecycle_state IN
    ('registered','installed','commissioned','decommissioned','retired','disposed')),
  operational_status TEXT NOT NULL DEFAULT 'unknown' CHECK(operational_status IN
    ('unknown','offline','idle','operating','standby','degraded','faulted','maintenance')),
  installed_at TEXT,
  commissioned_at TEXT,
  retired_at TEXT,
  disposed_at TEXT,
  notes TEXT,
  state_version INTEGER NOT NULL DEFAULT 1 CHECK(state_version>0),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK(lifecycle_state NOT IN ('commissioned','decommissioned') OR commissioned_at IS NOT NULL),
  CHECK(lifecycle_state NOT IN ('retired','disposed') OR retired_at IS NOT NULL),
  CHECK(lifecycle_state!='disposed' OR disposed_at IS NOT NULL)
);

CREATE UNIQUE INDEX equipment_registry_display_name
ON equipment_registry(lower(trim(display_name)));
CREATE UNIQUE INDEX equipment_registry_ths_asset_identifier
ON equipment_registry(lower(trim(ths_asset_identifier)))
WHERE ths_asset_identifier IS NOT NULL;
CREATE UNIQUE INDEX equipment_registry_manufacturer_serial
ON equipment_registry(manufacturer_id,lower(trim(manufacturer_serial_number)))
WHERE manufacturer_id IS NOT NULL AND manufacturer_serial_number IS NOT NULL;

CREATE TRIGGER equipment_registry_identity_immutable
BEFORE UPDATE OF equipment_uuid,equipment_number ON equipment_registry
WHEN OLD.equipment_uuid IS NOT NEW.equipment_uuid
  OR OLD.equipment_number IS NOT NEW.equipment_number
BEGIN SELECT RAISE(ABORT,'equipment identity is permanent'); END;
CREATE TRIGGER equipment_registry_no_delete
BEFORE DELETE ON equipment_registry
BEGIN SELECT RAISE(ABORT,'equipment registry records cannot be deleted'); END;
CREATE TRIGGER equipment_registry_subtype_matches
BEFORE INSERT ON equipment_registry
WHEN NEW.equipment_subtype_id IS NOT NULL AND
  (SELECT equipment_type_id FROM equipment_subtypes WHERE id=NEW.equipment_subtype_id)
  IS NOT NEW.equipment_type_id
BEGIN SELECT RAISE(ABORT,'equipment subtype must belong to equipment type'); END;
CREATE TRIGGER equipment_registry_subtype_matches_update
BEFORE UPDATE OF equipment_type_id,equipment_subtype_id ON equipment_registry
WHEN NEW.equipment_subtype_id IS NOT NULL AND
  (SELECT equipment_type_id FROM equipment_subtypes WHERE id=NEW.equipment_subtype_id)
  IS NOT NEW.equipment_type_id
BEGIN SELECT RAISE(ABORT,'equipment subtype must belong to equipment type'); END;

CREATE TABLE equipment_history (
  id INTEGER PRIMARY KEY,
  history_uuid TEXT NOT NULL UNIQUE,
  request_nonce TEXT NOT NULL UNIQUE,
  equipment_id INTEGER NOT NULL REFERENCES equipment_registry(id) ON DELETE RESTRICT,
  action_type TEXT NOT NULL CHECK(action_type IN
    ('register','update_facts','change_lifecycle','change_operational_status',
     'move_location','link_purchase','link_receipt','link_maintenance',
     'install_component','remove_component','retire','dispose')),
  previous_state_version INTEGER,
  new_state_version INTEGER NOT NULL,
  snapshot TEXT NOT NULL CHECK(json_valid(snapshot)),
  actor TEXT NOT NULL,
  reason TEXT,
  occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX equipment_history_equipment
ON equipment_history(equipment_id,occurred_at,id);
CREATE TRIGGER equipment_history_immutable_update BEFORE UPDATE ON equipment_history
BEGIN SELECT RAISE(ABORT,'equipment history is immutable'); END;
CREATE TRIGGER equipment_history_immutable_delete BEFORE DELETE ON equipment_history
BEGIN SELECT RAISE(ABORT,'equipment history is immutable'); END;

CREATE TABLE equipment_relationship_state (
  child_equipment_id INTEGER PRIMARY KEY REFERENCES equipment_registry(id) ON DELETE RESTRICT,
  parent_equipment_id INTEGER NOT NULL REFERENCES equipment_registry(id) ON DELETE RESTRICT,
  relationship_type TEXT NOT NULL CHECK(relationship_type IN
    ('attached_to','installed_in','managed_by')),
  state_version INTEGER NOT NULL DEFAULT 1 CHECK(state_version>0),
  effective_at TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK(child_equipment_id<>parent_equipment_id)
);
CREATE INDEX equipment_relationship_parent
ON equipment_relationship_state(parent_equipment_id,child_equipment_id);

CREATE TABLE equipment_relationship_history (
  id INTEGER PRIMARY KEY,
  history_uuid TEXT NOT NULL UNIQUE,
  request_nonce TEXT NOT NULL UNIQUE,
  child_equipment_id INTEGER NOT NULL REFERENCES equipment_registry(id) ON DELETE RESTRICT,
  previous_parent_equipment_id INTEGER REFERENCES equipment_registry(id) ON DELETE RESTRICT,
  new_parent_equipment_id INTEGER REFERENCES equipment_registry(id) ON DELETE RESTRICT,
  previous_relationship_type TEXT,
  new_relationship_type TEXT,
  action_type TEXT NOT NULL CHECK(action_type IN ('attach','move','detach')),
  previous_state_version INTEGER,
  new_state_version INTEGER NOT NULL,
  effective_at TEXT NOT NULL,
  actor TEXT NOT NULL,
  reason TEXT,
  snapshot TEXT NOT NULL CHECK(json_valid(snapshot)),
  occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK(previous_parent_equipment_id IS NOT NULL OR new_parent_equipment_id IS NOT NULL)
);
CREATE INDEX equipment_relationship_history_child
ON equipment_relationship_history(child_equipment_id,occurred_at,id);
CREATE TRIGGER equipment_relationship_history_immutable_update
BEFORE UPDATE ON equipment_relationship_history
BEGIN SELECT RAISE(ABORT,'equipment relationship history is immutable'); END;
CREATE TRIGGER equipment_relationship_history_immutable_delete
BEFORE DELETE ON equipment_relationship_history
BEGIN SELECT RAISE(ABORT,'equipment relationship history is immutable'); END;

CREATE TABLE equipment_capability_types (
  id INTEGER PRIMARY KEY,
  capability_code TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL UNIQUE,
  capability_group TEXT NOT NULL CHECK(capability_group IN
    ('embedded_component','media','telemetry','integration','network','other'))
);
INSERT INTO equipment_capability_types(capability_code,display_name,capability_group) VALUES
  ('camera.builtin','Built-in Camera','embedded_component'),
  ('camera.timelapse','Time-lapse Capable','media'),
  ('telemetry.device_status','Device-status Telemetry','telemetry'),
  ('telemetry.print_job','Print-job Telemetry','telemetry'),
  ('telemetry.temperature','Temperature Telemetry','telemetry'),
  ('telemetry.material_system','Material-system Telemetry','telemetry'),
  ('integration.manufacturer_local','Manufacturer Local Integration','integration'),
  ('integration.manufacturer_cloud','Manufacturer Cloud Integration','integration');

CREATE TABLE equipment_capabilities (
  id INTEGER PRIMARY KEY,
  capability_uuid TEXT NOT NULL UNIQUE,
  equipment_id INTEGER NOT NULL REFERENCES equipment_registry(id) ON DELETE RESTRICT,
  capability_type_id INTEGER NOT NULL REFERENCES equipment_capability_types(id) ON DELETE RESTRICT,
  support_state TEXT NOT NULL CHECK(support_state IN ('supported','unsupported','unknown')),
  source TEXT NOT NULL CHECK(source IN
    ('manufacturer_specification','physical_verification','manual_configuration',
     'integration_discovery')),
  configuration_metadata TEXT CHECK(configuration_metadata IS NULL OR json_valid(configuration_metadata)),
  verified_at TEXT,
  verified_by TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(equipment_id,capability_type_id)
);
CREATE TRIGGER equipment_capabilities_no_secrets_insert
BEFORE INSERT ON equipment_capabilities
WHEN lower(COALESCE(NEW.configuration_metadata,'')) GLOB '*password*'
  OR lower(COALESCE(NEW.configuration_metadata,'')) GLOB '*token*'
  OR lower(COALESCE(NEW.configuration_metadata,'')) GLOB '*secret*'
  OR lower(COALESCE(NEW.configuration_metadata,'')) GLOB '*credential*'
BEGIN SELECT RAISE(ABORT,'equipment capability metadata cannot contain credentials'); END;
CREATE TRIGGER equipment_capabilities_no_secrets_update
BEFORE UPDATE OF configuration_metadata ON equipment_capabilities
WHEN lower(COALESCE(NEW.configuration_metadata,'')) GLOB '*password*'
  OR lower(COALESCE(NEW.configuration_metadata,'')) GLOB '*token*'
  OR lower(COALESCE(NEW.configuration_metadata,'')) GLOB '*secret*'
  OR lower(COALESCE(NEW.configuration_metadata,'')) GLOB '*credential*'
BEGIN SELECT RAISE(ABORT,'equipment capability metadata cannot contain credentials'); END;
CREATE TRIGGER equipment_builtin_camera_requires_printer
BEFORE INSERT ON equipment_capabilities
WHEN (SELECT capability_code FROM equipment_capability_types
      WHERE id=NEW.capability_type_id)='camera.builtin'
  AND (SELECT et.type_code FROM equipment_registry er
       JOIN equipment_types et ON et.id=er.equipment_type_id
       WHERE er.id=NEW.equipment_id)<>'printer'
BEGIN SELECT RAISE(ABORT,'built-in camera capability requires printer equipment'); END;

CREATE TABLE equipment_component_installations (
  id INTEGER PRIMARY KEY,
  installation_uuid TEXT NOT NULL UNIQUE,
  host_equipment_id INTEGER NOT NULL REFERENCES equipment_registry(id) ON DELETE RESTRICT,
  component_equipment_id INTEGER REFERENCES equipment_registry(id) ON DELETE RESTRICT,
  inventory_instance_id INTEGER REFERENCES inventory_instances(id) ON DELETE RESTRICT,
  catalog_item_id INTEGER REFERENCES catalog_items(id) ON DELETE RESTRICT,
  component_role TEXT NOT NULL,
  embedded INTEGER NOT NULL DEFAULT 0 CHECK(embedded IN (0,1)),
  independently_tracked INTEGER NOT NULL DEFAULT 0 CHECK(independently_tracked IN (0,1)),
  installed_at TEXT NOT NULL,
  removed_at TEXT,
  installed_by TEXT NOT NULL,
  notes TEXT,
  CHECK((component_equipment_id IS NOT NULL)+(inventory_instance_id IS NOT NULL)+
        (catalog_item_id IS NOT NULL)<=1),
  CHECK(component_equipment_id IS NULL OR component_equipment_id<>host_equipment_id),
  CHECK(NOT(embedded=1 AND independently_tracked=1))
);
CREATE UNIQUE INDEX equipment_component_active_role
ON equipment_component_installations(host_equipment_id,component_role)
WHERE removed_at IS NULL;

CREATE TABLE equipment_interface_types (
  id INTEGER PRIMARY KEY,
  interface_code TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL UNIQUE,
  medium TEXT NOT NULL CHECK(medium IN ('data','power','data_and_power','control','other'))
);
INSERT INTO equipment_interface_types(interface_code,display_name,medium) VALUES
  ('ethernet','Ethernet','data'),
  ('wifi','Wi-Fi','data'),
  ('poe_power_input','PoE Power Input','power'),
  ('poe_power_output','PoE Power Output','power'),
  ('usb','USB','data_and_power'),
  ('gpio','GPIO','control'),
  ('zigbee','Zigbee','data'),
  ('thread','Thread','data'),
  ('bluetooth','Bluetooth','data'),
  ('serial','Serial','data'),
  ('other','Other Interface','other');

CREATE TABLE equipment_interfaces (
  id INTEGER PRIMARY KEY,
  interface_uuid TEXT NOT NULL UNIQUE,
  equipment_id INTEGER NOT NULL REFERENCES equipment_registry(id) ON DELETE RESTRICT,
  interface_type_id INTEGER NOT NULL REFERENCES equipment_interface_types(id) ON DELETE RESTRICT,
  interface_name TEXT NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('input','output','bidirectional')),
  physicality TEXT NOT NULL CHECK(physicality IN ('physical','logical','radio')),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
  hardware_address TEXT,
  notes TEXT,
  state_version INTEGER NOT NULL DEFAULT 1 CHECK(state_version>0),
  UNIQUE(equipment_id,interface_name)
);

CREATE TABLE equipment_connection_state (
  id INTEGER PRIMARY KEY,
  connection_uuid TEXT NOT NULL UNIQUE,
  source_interface_id INTEGER NOT NULL REFERENCES equipment_interfaces(id) ON DELETE RESTRICT,
  target_interface_id INTEGER REFERENCES equipment_interfaces(id) ON DELETE RESTRICT,
  external_endpoint_label TEXT,
  connection_status TEXT NOT NULL CHECK(connection_status IN ('connected','degraded','unknown')),
  state_version INTEGER NOT NULL DEFAULT 1 CHECK(state_version>0),
  connected_at TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK((target_interface_id IS NOT NULL)+(external_endpoint_label IS NOT NULL)=1),
  CHECK(target_interface_id IS NULL OR target_interface_id<>source_interface_id)
);

CREATE TABLE equipment_connection_history (
  id INTEGER PRIMARY KEY,
  history_uuid TEXT NOT NULL UNIQUE,
  request_nonce TEXT NOT NULL UNIQUE,
  connection_uuid TEXT NOT NULL,
  action_type TEXT NOT NULL CHECK(action_type IN ('connect','change_status','disconnect')),
  source_interface_id INTEGER NOT NULL REFERENCES equipment_interfaces(id) ON DELETE RESTRICT,
  target_interface_id INTEGER REFERENCES equipment_interfaces(id) ON DELETE RESTRICT,
  external_endpoint_label TEXT,
  previous_status TEXT,
  new_status TEXT,
  previous_state_version INTEGER,
  new_state_version INTEGER NOT NULL,
  effective_at TEXT NOT NULL,
  actor TEXT NOT NULL,
  reason TEXT,
  snapshot TEXT NOT NULL CHECK(json_valid(snapshot)),
  occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TRIGGER equipment_connection_history_immutable_update
BEFORE UPDATE ON equipment_connection_history
BEGIN SELECT RAISE(ABORT,'equipment connection history is immutable'); END;
CREATE TRIGGER equipment_connection_history_immutable_delete
BEFORE DELETE ON equipment_connection_history
BEGIN SELECT RAISE(ABORT,'equipment connection history is immutable'); END;

CREATE TABLE equipment_purchase_links (
  id INTEGER PRIMARY KEY,
  link_uuid TEXT NOT NULL UNIQUE,
  equipment_id INTEGER NOT NULL REFERENCES equipment_registry(id) ON DELETE RESTRICT,
  purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE RESTRICT,
  purchase_order_line_id INTEGER REFERENCES purchase_order_lines(id) ON DELETE RESTRICT,
  relationship_type TEXT NOT NULL CHECK(relationship_type IN
    ('purchased_as','purchased_for','replacement_for')),
  linked_by TEXT NOT NULL,
  linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  note TEXT,
  UNIQUE(equipment_id,purchase_order_id,purchase_order_line_id,relationship_type)
);
CREATE TRIGGER equipment_purchase_link_same_order
BEFORE INSERT ON equipment_purchase_links
WHEN NEW.purchase_order_line_id IS NOT NULL AND
  (SELECT purchase_order_id FROM purchase_order_lines WHERE id=NEW.purchase_order_line_id)
  IS NOT NEW.purchase_order_id
BEGIN SELECT RAISE(ABORT,'equipment purchase line must belong to purchase'); END;
CREATE TRIGGER equipment_purchase_links_immutable_update
BEFORE UPDATE ON equipment_purchase_links
BEGIN SELECT RAISE(ABORT,'equipment purchase provenance is immutable'); END;
CREATE TRIGGER equipment_purchase_links_immutable_delete
BEFORE DELETE ON equipment_purchase_links
BEGIN SELECT RAISE(ABORT,'equipment purchase provenance is immutable'); END;

CREATE TABLE equipment_receipt_links (
  id INTEGER PRIMARY KEY,
  link_uuid TEXT NOT NULL UNIQUE,
  equipment_id INTEGER NOT NULL REFERENCES equipment_registry(id) ON DELETE RESTRICT,
  purchase_receipt_id INTEGER NOT NULL REFERENCES purchase_receipts(id) ON DELETE RESTRICT,
  purchase_receipt_line_id INTEGER REFERENCES purchase_receipt_lines(id) ON DELETE RESTRICT,
  linked_by TEXT NOT NULL,
  linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  note TEXT,
  UNIQUE(equipment_id,purchase_receipt_id,purchase_receipt_line_id)
);
CREATE TRIGGER equipment_receipt_link_same_receipt
BEFORE INSERT ON equipment_receipt_links
WHEN NEW.purchase_receipt_line_id IS NOT NULL AND
  (SELECT purchase_receipt_id FROM purchase_receipt_lines WHERE id=NEW.purchase_receipt_line_id)
  IS NOT NEW.purchase_receipt_id
BEGIN SELECT RAISE(ABORT,'equipment receipt line must belong to receipt'); END;
CREATE TRIGGER equipment_receipt_links_immutable_update
BEFORE UPDATE ON equipment_receipt_links
BEGIN SELECT RAISE(ABORT,'equipment receipt provenance is immutable'); END;
CREATE TRIGGER equipment_receipt_links_immutable_delete
BEFORE DELETE ON equipment_receipt_links
BEGIN SELECT RAISE(ABORT,'equipment receipt provenance is immutable'); END;

CREATE TABLE equipment_maintenance_asset_links (
  equipment_id INTEGER PRIMARY KEY REFERENCES equipment_registry(id) ON DELETE RESTRICT,
  maintenance_asset_id INTEGER NOT NULL UNIQUE REFERENCES maintenance_assets(id) ON DELETE RESTRICT,
  linked_by TEXT NOT NULL,
  linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE equipment_printer_links (
  equipment_id INTEGER PRIMARY KEY REFERENCES equipment_registry(id) ON DELETE RESTRICT,
  printer_id INTEGER NOT NULL UNIQUE REFERENCES printers(id) ON DELETE RESTRICT,
  linked_by TEXT NOT NULL,
  linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE equipment_legacy_container_links (
  equipment_id INTEGER PRIMARY KEY REFERENCES equipment_registry(id) ON DELETE RESTRICT,
  legacy_equipment_id INTEGER NOT NULL UNIQUE REFERENCES equipment(id) ON DELETE RESTRICT,
  linked_by TEXT NOT NULL,
  linked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE equipment_telemetry_state (
  equipment_id INTEGER PRIMARY KEY REFERENCES equipment_registry(id) ON DELETE RESTRICT,
  integration_type TEXT NOT NULL,
  source_device_time TEXT,
  received_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  online_state TEXT NOT NULL CHECK(online_state IN ('online','offline','unknown')),
  print_status TEXT,
  current_job TEXT,
  progress_percent REAL CHECK(progress_percent IS NULL OR progress_percent BETWEEN 0 AND 100),
  estimated_seconds_remaining INTEGER CHECK(estimated_seconds_remaining IS NULL OR estimated_seconds_remaining>=0),
  temperatures_json TEXT CHECK(temperatures_json IS NULL OR json_valid(temperatures_json)),
  ams_observation_json TEXT CHECK(ams_observation_json IS NULL OR json_valid(ams_observation_json)),
  errors_json TEXT CHECK(errors_json IS NULL OR json_valid(errors_json)),
  warnings_json TEXT CHECK(warnings_json IS NULL OR json_valid(warnings_json)),
  camera_stream_available INTEGER CHECK(camera_stream_available IS NULL OR camera_stream_available IN (0,1)),
  source_correlation_id TEXT,
  state_version INTEGER NOT NULL DEFAULT 1 CHECK(state_version>0)
);

CREATE VIEW equipment_registry_readiness AS
SELECT er.id equipment_id,
       ma.readiness_state,
       CASE ma.readiness_state
         WHEN 'normal' THEN 'none'
         WHEN 'monitor_during_printing' THEN 'monitor_during_printing'
         WHEN 'no_unattended_printing' THEN 'no_unattended_printing'
         WHEN 'out_of_service' THEN 'out_of_service'
         ELSE 'unknown'
       END derived_restriction
FROM equipment_registry er
LEFT JOIN equipment_maintenance_asset_links emal ON emal.equipment_id=er.id
LEFT JOIN maintenance_assets ma ON ma.id=emal.maintenance_asset_id;

CREATE VIEW equipment_current_relationships AS
SELECT ers.child_equipment_id,child.equipment_number child_equipment_number,
       child.display_name child_name,ers.parent_equipment_id,
       parent.equipment_number parent_equipment_number,parent.display_name parent_name,
       ers.relationship_type,ers.state_version,ers.effective_at
FROM equipment_relationship_state ers
JOIN equipment_registry child ON child.id=ers.child_equipment_id
JOIN equipment_registry parent ON parent.id=ers.parent_equipment_id;

CREATE VIEW equipment_current_connections AS
SELECT ecs.id,ecs.connection_uuid,ecs.source_interface_id,
       source_equipment.id source_equipment_id,
       source_equipment.equipment_number source_equipment_number,
       source_interface.interface_name source_interface_name,
       ecs.target_interface_id,target_equipment.id target_equipment_id,
       target_equipment.equipment_number target_equipment_number,
       target_interface.interface_name target_interface_name,
       ecs.external_endpoint_label,ecs.connection_status,
       ecs.state_version,ecs.connected_at,ecs.updated_at
FROM equipment_connection_state ecs
JOIN equipment_interfaces source_interface ON source_interface.id=ecs.source_interface_id
JOIN equipment_registry source_equipment ON source_equipment.id=source_interface.equipment_id
LEFT JOIN equipment_interfaces target_interface ON target_interface.id=ecs.target_interface_id
LEFT JOIN equipment_registry target_equipment ON target_equipment.id=target_interface.equipment_id;
