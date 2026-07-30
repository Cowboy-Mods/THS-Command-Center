INSERT INTO units(code,name,dimension,scale_to_base) VALUES
 ('ea','each','count',1),('pack','pack','count',1),('g','grams','mass',1),('kg','kilograms','mass',1000),
 ('mm','millimeters','length',1),('m','meters','length',1000),('ft','feet','length',304.8),('in','inches','length',25.4),
 ('ml','milliliters','volume',1),('l','liters','volume',1000),('sq_ft','square feet','area',1),
 ('sheet','sheets','count',1),('roll','rolls','count',1);
INSERT INTO categories(name,description) VALUES
 ('3D Printing','Filament, resin, printer parts, and consumables'),
 ('Electronics','Boards, sensors, motors, connectors, and wiring'),
 ('Tools','Individually tracked shop tools'),('Hardware','Bulk fasteners and components'),
 ('Leatherwork','Leather, dyes, hardware, and tools'),('Engraving','Blanks, bits, fixtures, and supplies');
INSERT INTO item_types(category_id,name,tracking_method,id_prefix,default_unit_id)
VALUES ((SELECT id FROM categories WHERE name='3D Printing'),'Filament','individual','THS-FIL',(SELECT id FROM units WHERE code='g'));
INSERT INTO attribute_definitions(name,data_type,unit_dimension) VALUES
 ('material','text',NULL),('manufacturer_color_name','text',NULL),('color_code','text',NULL),
 ('diameter_mm','decimal','length'),('nominal_weight_g','decimal','mass'),('packaging_weight_g','decimal','mass');
INSERT INTO item_type_attributes
SELECT (SELECT id FROM item_types WHERE name='Filament'),id,
 CASE WHEN name IN ('material','manufacturer_color_name','diameter_mm','nominal_weight_g') THEN 1 ELSE 0 END,id
FROM attribute_definitions;
INSERT INTO locations(name,kind) VALUES ('Workshop','site');
INSERT INTO locations(parent_id,name,kind) VALUES
 ((SELECT id FROM locations WHERE name='Workshop'),'Sealed Filament Rack','storage'),
 ((SELECT id FROM locations WHERE name='Workshop'),'Open-Spool Wall','storage'),
 ((SELECT id FROM locations WHERE name='Workshop'),'AMS 1','equipment'),
 ((SELECT id FROM locations WHERE name='Workshop'),'AMS 2','equipment');
INSERT INTO locations(parent_id,name,kind,slot_number)
SELECT p.id,'Slot '||n,'ams_slot',n FROM locations p,
 (SELECT 1 n UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4)
WHERE p.name IN ('AMS 1','AMS 2');
INSERT INTO equipment(name,equipment_type,location_id,slot_count)
SELECT name,'AMS',id,4 FROM locations WHERE name IN ('AMS 1','AMS 2');
INSERT INTO equipment_slots(equipment_id,location_id,slot_number)
SELECT e.id,l.id,l.slot_number FROM equipment e JOIN locations parent ON parent.id=e.location_id
JOIN locations l ON l.parent_id=parent.id;


