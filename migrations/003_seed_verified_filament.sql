INSERT INTO manufacturers(name) VALUES ('Overture'),('Elegoo'),('Bambu Lab'),('AMOLEN');

INSERT INTO catalog_items(item_type_id,manufacturer_id,name,product_line,variant,base_unit_id,notes)
WITH products(manufacturer,name,product_line,variant,notes) AS (
 VALUES
 ('Overture','PLA Filament','PLA','Black','Standard 1 kg spool assumption; verify against packaging before physical labeling.'),
 ('Elegoo','PLA Filament','PLA','White','Use-up stock. Standard 1 kg spool assumption; verify against packaging.'),
 ('Bambu Lab','PLA Basic Filament','PLA Basic','Pink','1,000 g net filament assumption from standard PLA Basic packaging.'),
 ('Bambu Lab','PLA Basic Filament','PLA Basic','Orange','1,000 g net filament assumption from standard PLA Basic packaging.'),
 ('Bambu Lab','PLA Basic Filament','PLA Basic','Cobalt Blue','1,000 g net filament assumption from standard PLA Basic packaging.'),
 ('Bambu Lab','PLA Basic Filament','PLA Basic','Turquoise','1,000 g net filament assumption from standard PLA Basic packaging.'),
 ('Bambu Lab','PLA Basic Filament','PLA Basic','Blue','1,000 g net filament assumption from standard PLA Basic packaging.'),
 ('Bambu Lab','PLA Basic Filament','PLA Basic','Bambu Green','1,000 g net filament assumption from standard PLA Basic packaging.'),
 ('Bambu Lab','PLA Basic Filament','PLA Basic','Dark Gray','1,000 g net filament assumption from standard PLA Basic packaging.'),
 ('Bambu Lab','PLA Basic Filament','PLA Basic','Jade White','1,000 g net filament assumption from standard PLA Basic packaging.'),
 ('Bambu Lab','PLA Basic Filament','PLA Basic','Brown','1,000 g net filament assumption from standard PLA Basic packaging.'),
 ('Bambu Lab','PLA Basic Filament','PLA Basic','Gold','1,000 g net filament assumption from standard PLA Basic packaging.'),
 ('Bambu Lab','PLA Basic Filament','PLA Basic','Gray','1,000 g net filament assumption from standard PLA Basic packaging.'),
 ('AMOLEN','PLA Silk Dual Color','PLA Silk Dual Color 200 g Bundle','Black/Red','Verified 200 g bundle roll.'),
 ('AMOLEN','PLA Silk Dual Color','PLA Silk Dual Color 200 g Bundle','Black/Purple','Verified 200 g bundle roll.'),
 ('AMOLEN','PLA Silk Dual Color','PLA Silk Dual Color 200 g Bundle','Black/Blue','Verified 200 g bundle roll.'),
 ('AMOLEN','PLA Silk Dual Color','PLA Silk Dual Color 200 g Bundle','Black/Green','Verified 200 g bundle roll.')
)
SELECT (SELECT id FROM item_types WHERE name='Filament'),m.id,p.name,p.product_line,p.variant,
       (SELECT id FROM units WHERE code='g'),p.notes
FROM products p JOIN manufacturers m ON m.name=p.manufacturer;

INSERT INTO catalog_item_attribute_values(catalog_item_id,attribute_definition_id,text_value)
SELECT p.id,a.id,CASE WHEN a.name='material' THEN
 CASE WHEN p.product_line LIKE 'PLA Silk%' THEN 'PLA Silk' ELSE 'PLA' END
 ELSE p.variant END
FROM catalog_items p CROSS JOIN attribute_definitions a
WHERE p.item_type_id=(SELECT id FROM item_types WHERE name='Filament')
AND a.name IN ('material','manufacturer_color_name');
INSERT INTO catalog_item_attribute_values(catalog_item_id,attribute_definition_id,numeric_value)
SELECT p.id,a.id,CASE a.name WHEN 'diameter_mm' THEN 1.75
 WHEN 'nominal_weight_g' THEN CASE WHEN p.product_line LIKE '%200 g%' THEN 200 ELSE 1000 END END
FROM catalog_items p CROSS JOIN attribute_definitions a
WHERE p.item_type_id=(SELECT id FROM item_types WHERE name='Filament')
AND a.name IN ('diameter_mm','nominal_weight_g');

INSERT INTO inventory_instances(
 permanent_id,catalog_item_id,state,location_id,original_quantity,remaining_quantity,unit_id,verified,notes
)
WITH RECURSIVE stock(manufacturer,product_line,variant,spool_count,grams,notes) AS (
 VALUES ('Overture','PLA','Black',6,1000,NULL),
 ('Elegoo','PLA','White',2,1000,'Use-up stock.'),
 ('Bambu Lab','PLA Basic','Pink',1,1000,NULL),
 ('Bambu Lab','PLA Basic','Orange',2,1000,NULL),
 ('Bambu Lab','PLA Basic','Cobalt Blue',1,1000,NULL),
 ('Bambu Lab','PLA Basic','Turquoise',1,1000,NULL),
 ('Bambu Lab','PLA Basic','Blue',1,1000,NULL),
 ('Bambu Lab','PLA Basic','Bambu Green',2,1000,NULL),
 ('Bambu Lab','PLA Basic','Dark Gray',1,1000,NULL),
 ('Bambu Lab','PLA Basic','Jade White',1,1000,NULL),
 ('Bambu Lab','PLA Basic','Brown',4,1000,NULL),
 ('Bambu Lab','PLA Basic','Gold',3,1000,NULL),
 ('Bambu Lab','PLA Basic','Gray',1,1000,NULL),
 ('AMOLEN','PLA Silk Dual Color 200 g Bundle','Black/Red',1,200,NULL),
 ('AMOLEN','PLA Silk Dual Color 200 g Bundle','Black/Purple',1,200,NULL),
 ('AMOLEN','PLA Silk Dual Color 200 g Bundle','Black/Blue',1,200,NULL),
 ('AMOLEN','PLA Silk Dual Color 200 g Bundle','Black/Green',1,200,NULL)
), expanded(manufacturer,product_line,variant,grams,notes,n,spool_count) AS (
 SELECT manufacturer,product_line,variant,grams,notes,1,spool_count FROM stock
 UNION ALL SELECT manufacturer,product_line,variant,grams,notes,n+1,spool_count
 FROM expanded WHERE n<spool_count
), numbered AS (
 SELECT *,ROW_NUMBER() OVER (ORDER BY
 CASE manufacturer WHEN 'Overture' THEN 1 WHEN 'Elegoo' THEN 2 WHEN 'Bambu Lab' THEN 3 ELSE 4 END,
 product_line,variant,n) seq FROM expanded
)
SELECT printf('THS-FIL-%06d',seq),p.id,'sealed',
 (SELECT id FROM locations WHERE name='Sealed Filament Rack'),grams,grams,
 (SELECT id FROM units WHERE code='g'),1,numbered.notes
FROM numbered JOIN manufacturers m ON m.name=numbered.manufacturer
JOIN catalog_items p ON p.manufacturer_id=m.id AND p.product_line=numbered.product_line
 AND p.variant=numbered.variant;


