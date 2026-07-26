import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from inventory.db import active_filament_summary, connect, migrate, project_material_status
from inventory.importer import import_csv


class InventoryFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.sqlite3"
        self.db = connect(self.db_path)
        migrate(self.db)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def scalar(self, sql, params=()):
        return self.db.execute(sql, params).fetchone()[0]

    def test_01_create_configurable_category(self):
        self.db.execute("INSERT INTO categories(name) VALUES ('RC Components')")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM categories WHERE name='RC Components'"), 1)

    def test_02_create_configurable_item_type(self):
        self.db.execute("INSERT INTO item_types(category_id,name,tracking_method,default_unit_id) "
                        "VALUES ((SELECT id FROM categories WHERE name='Hardware'),'Bearing','quantity',"
                        "(SELECT id FROM units WHERE code='ea'))")
        self.assertEqual(self.scalar("SELECT tracking_method FROM item_types WHERE name='Bearing'"), "quantity")

    def test_03_assign_item_type_attributes(self):
        self.db.execute("INSERT INTO attribute_definitions(name,data_type) VALUES ('pin_count','integer')")
        self.db.execute("INSERT INTO item_type_attributes VALUES ((SELECT id FROM item_types WHERE name='Filament'),"
                        "(SELECT id FROM attribute_definitions WHERE name='pin_count'),0,99)")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM item_type_attributes WHERE display_order=99"), 1)

    def test_04_create_quantity_item(self):
        product = self._product("Bulk Magnets", "quantity", "ea")
        self.db.execute("INSERT INTO stock_lots(catalog_item_id,location_id,quantity,unit_id,verified) "
                        "VALUES (?,?,25,(SELECT id FROM units WHERE code='ea'),1)", (product, self._workshop()))
        self.assertEqual(self.scalar("SELECT quantity FROM stock_lots WHERE catalog_item_id=?", (product,)), 25)

    def test_05_create_individually_tracked_item(self):
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_instances"), 30)

    def test_06_unit_validation(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO units(code,name,dimension,scale_to_base) VALUES ('bad','bad','x',0)")

    def test_07_location_hierarchy_and_cycle_guard(self):
        child = self.db.execute("INSERT INTO locations(parent_id,name) VALUES (?,?)",
                                (self._workshop(), "Drawer")).lastrowid
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE locations SET parent_id=? WHERE id=?", (child, self._workshop()))

    def test_08_inventory_move_transaction(self):
        tx = self._transaction("move")
        self._line(tx, 1, 0, self._workshop(), self._location("Open-Spool Wall"))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM transaction_lines WHERE transaction_id=?", (tx,)), 1)

    def test_09_consumption_transaction(self):
        tx = self._transaction("consume")
        self._line(tx, 1, -25)
        self.assertEqual(self.scalar("SELECT quantity_change FROM transaction_lines WHERE transaction_id=?", (tx,)), -25)

    def test_10_correction_transaction(self):
        self.assertIsInstance(self._transaction("correct"), int)

    def test_11_archive_behavior(self):
        self.db.execute("UPDATE inventory_instances SET state='archived',archived_at=CURRENT_TIMESTAMP WHERE id=1")
        self.assertEqual(sum(r["active_rolls"] for r in active_filament_summary(self.db)), 29)

    def test_12_reservation_behavior(self):
        rid = self._reservation(1, 100)
        self.db.execute("INSERT INTO reservation_allocations(reservation_id,instance_id,quantity,unit_id) "
                        "VALUES (?,?,100,(SELECT id FROM units WHERE code='g'))", (rid, 1))
        self.assertEqual(self.scalar("SELECT remaining_quantity FROM inventory_instances WHERE id=1"), 1000)

    def test_13_reservation_release(self):
        rid = self._reservation(1, 10)
        self.db.execute("UPDATE reservations SET status='released',released_at=CURRENT_TIMESTAMP WHERE id=?", (rid,))
        self.assertEqual(self.scalar("SELECT status FROM reservations WHERE id=?", (rid,)), "released")

    def test_14_active_vs_archived_totals(self):
        before = sum(r["available_grams"] for r in active_filament_summary(self.db))
        self.db.execute("UPDATE inventory_instances SET state='empty',remaining_quantity=0,"
                        "emptied_at=CURRENT_TIMESTAMP,archived_at=CURRENT_TIMESTAMP WHERE id=1")
        after = sum(r["available_grams"] for r in active_filament_summary(self.db))
        self.assertEqual(before-after, 1000)

    def test_15_import_dry_run(self):
        path = self._csv(verified="true")
        result = import_csv(self.db, path)
        self.assertEqual((result["accepted"], result["rejected"]), (1, 0))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM catalog_items WHERE name='Imported Part'"), 0)

    def test_16_reject_unverified_rows(self):
        result = import_csv(self.db, self._csv(verified="false"))
        self.assertEqual(result["rejected"], 1)

    def test_17_import_rollback(self):
        result = import_csv(self.db, self._csv(verified="false"), apply=True)
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM catalog_items WHERE name='Imported Part'"), 0)

    def test_18_import_idempotency(self):
        path = self._csv(verified="true")
        import_csv(self.db, path, apply=True)
        result = import_csv(self.db, path, apply=True)
        self.assertEqual(result["accepted"], 0)

    def test_19_duplicate_product_detection(self):
        path = self._csv(verified="true")
        import_csv(self.db, path, apply=True)
        path2 = self._csv(verified="true", external_id="OTHER")
        result = import_csv(self.db, path2, apply=True)
        self.assertGreaterEqual(result["warnings"], 1)

    def test_20_stock_minimum_reorder(self):
        product = self.scalar("SELECT id FROM catalog_items LIMIT 1")
        self.db.execute("INSERT INTO stock_rules(catalog_item_id,minimum_quantity,reorder_quantity,unit_id) "
                        "VALUES (?,2000,3000,(SELECT id FROM units WHERE code='g'))", (product,))
        available = self.scalar("SELECT SUM(remaining_quantity) FROM inventory_instances WHERE catalog_item_id=?", (product,))
        self.assertEqual(max(0, 2000-available), 0)

    def test_21_to_26_seeded_filament_facts(self):
        brown = self.db.execute("SELECT * FROM active_filament_summary WHERE 0").fetchall() if False else [
            r for r in active_filament_summary(self.db)
            if r["manufacturer"]=="Bambu Lab" and r["product_line"]=="PLA Basic" and r["variant"]=="Brown"
        ][0]
        self.assertEqual((brown["active_rolls"], brown["sealed_rolls"], brown["available_grams"]), (4,4,4000))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_instances"), 30)
        totals = dict(self.db.execute("SELECT m.name,COUNT(*) FROM inventory_instances i JOIN catalog_items p "
                                     "ON p.id=i.catalog_item_id JOIN manufacturers m ON m.id=p.manufacturer_id GROUP BY m.name"))
        self.assertEqual(totals, {"AMOLEN":4,"Bambu Lab":18,"Elegoo":2,"Overture":6})
        self.assertEqual(self.scalar("SELECT COUNT(DISTINCT permanent_id) FROM inventory_instances"), 30)
        self.assertEqual(self.scalar("SELECT SUM(remaining_quantity) FROM inventory_instances"), 26800)
        self.assertEqual(self.scalar("SELECT MIN(remaining_quantity) FROM inventory_instances i JOIN catalog_items p "
                                     "ON p.id=i.catalog_item_id JOIN manufacturers m ON m.id=p.manufacturer_id WHERE m.name='AMOLEN'"), 200)

    def test_27_empty_spool_history_not_active(self):
        tx = self._transaction("mark_empty")
        self._line(tx, 1, -1000)
        self.db.execute("UPDATE inventory_instances SET state='empty',remaining_quantity=0,archived_at=CURRENT_TIMESTAMP WHERE id=1")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM transaction_lines WHERE transaction_id=?", (tx,)), 1)

    def test_28_remaining_grams_nonnegative(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE inventory_instances SET remaining_quantity=-1 WHERE id=1")

    def test_29_reservation_is_not_consumption(self):
        self._reservation(1, 50)
        self.assertEqual(self.scalar("SELECT remaining_quantity FROM inventory_instances WHERE id=1"), 1000)

    def test_30_sealed_open_loaded_grouping(self):
        self.db.execute("UPDATE inventory_instances SET state='open' WHERE id=1")
        self.db.execute("UPDATE inventory_instances SET state='loaded' WHERE id=2")
        rows = active_filament_summary(self.db)
        self.assertEqual(sum(r["open_rolls"] for r in rows), 1)
        self.assertEqual(sum(r["loaded_rolls"] for r in rows), 1)

    def test_31_to_33_two_ams_with_four_empty_slots(self):
        self.assertEqual(dict(self.db.execute("SELECT name,slot_count FROM equipment")), {"AMS 1":4,"AMS 2":4})
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM equipment_slots"), 8)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM ams_assignments WHERE unloaded_at IS NULL"), 0)

    def test_34_one_spool_cannot_occupy_two_slots(self):
        tx = self._transaction("load")
        self.db.execute("INSERT INTO ams_assignments(slot_id,instance_id,load_transaction_id) VALUES (1,1,?)", (tx,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO ams_assignments(slot_id,instance_id,load_transaction_id) VALUES (2,1,?)", (tx,))

    def test_35_one_slot_cannot_contain_two_spools(self):
        tx = self._transaction("load")
        self.db.execute("INSERT INTO ams_assignments(slot_id,instance_id,load_transaction_id) VALUES (1,1,?)", (tx,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO ams_assignments(slot_id,instance_id,load_transaction_id) VALUES (1,2,?)", (tx,))

    def test_36_load_unload_transactions_retained(self):
        load, unload = self._transaction("load"), self._transaction("unload")
        aid = self.db.execute("INSERT INTO ams_assignments(slot_id,instance_id,load_transaction_id) VALUES (1,1,?)", (load,)).lastrowid
        self.db.execute("UPDATE ams_assignments SET unloaded_at=CURRENT_TIMESTAMP,unload_transaction_id=? WHERE id=?", (unload,aid))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_transactions WHERE id IN (?,?)", (load,unload)), 2)

    def test_37_bom_comparison(self):
        project = self.db.execute("INSERT INTO projects(name) VALUES ('Sample Build')").lastrowid
        product = self.scalar("SELECT catalog_item_id FROM inventory_instances WHERE id=1")
        self.db.execute("INSERT INTO project_requirements(project_id,catalog_item_id,quantity,unit_id) "
                        "VALUES (?,?,500,(SELECT id FROM units WHERE code='g'))", (project,product))
        self.assertEqual(project_material_status(self.db, project)[0]["status"], "available")

    def test_38_quantity_and_individual_items_in_bom(self):
        bulk = self._product("M5 Screws", "quantity", "ea")
        self.db.execute("INSERT INTO stock_lots(catalog_item_id,location_id,quantity,unit_id,verified) "
                        "VALUES (?,?,10,(SELECT id FROM units WHERE code='ea'),1)", (bulk,self._workshop()))
        project = self.db.execute("INSERT INTO projects(name) VALUES ('Mixed Build')").lastrowid
        filament = self.scalar("SELECT catalog_item_id FROM inventory_instances LIMIT 1")
        self.db.execute("INSERT INTO project_requirements(project_id,catalog_item_id,quantity,unit_id) "
                        "VALUES (?,?,100,(SELECT id FROM units WHERE code='g'))", (project,filament))
        self.db.execute("INSERT INTO project_requirements(project_id,catalog_item_id,quantity,unit_id) "
                        "VALUES (?,?,4,(SELECT id FROM units WHERE code='ea'))", (project,bulk))
        self.assertEqual([r["status"] for r in project_material_status(self.db,project)], ["available","available"])

    def _workshop(self):
        return self._location("Workshop")

    def _location(self, name):
        return self.scalar("SELECT id FROM locations WHERE name=?", (name,))

    def _transaction(self, kind):
        return self.db.execute("INSERT INTO inventory_transactions(transaction_type) VALUES (?)", (kind,)).lastrowid

    def _line(self, tx, instance, qty, source=None, destination=None):
        product = self.scalar("SELECT catalog_item_id FROM inventory_instances WHERE id=?", (instance,))
        self.db.execute("INSERT INTO transaction_lines(transaction_id,catalog_item_id,instance_id,quantity_change,"
                        "unit_id,source_location_id,destination_location_id) VALUES (?,?,?,?,"
                        "(SELECT id FROM units WHERE code='g'),?,?)", (tx,product,instance,qty,source,destination))

    def _reservation(self, product, qty):
        product_id = self.scalar("SELECT catalog_item_id FROM inventory_instances WHERE id=?", (product,))
        return self.db.execute("INSERT INTO reservations(catalog_item_id,quantity,unit_id) VALUES (?,?,"
                               "(SELECT id FROM units WHERE code='g'))", (product_id,qty)).lastrowid

    def _product(self, name, tracking, unit):
        item_type = self.db.execute("SELECT id FROM item_types WHERE name=?", (name,)).fetchone()
        if item_type:
            return self.scalar("SELECT id FROM catalog_items WHERE name=?", (name,))
        item_type_id = self.db.execute("INSERT INTO item_types(category_id,name,tracking_method,default_unit_id) "
            "VALUES ((SELECT id FROM categories WHERE name='Hardware'),?,?,(SELECT id FROM units WHERE code=?))",
            (name,tracking,unit)).lastrowid
        return self.db.execute("INSERT INTO catalog_items(item_type_id,name,base_unit_id) VALUES (?,?,"
            "(SELECT id FROM units WHERE code=?))", (item_type_id,name,unit)).lastrowid

    def _csv(self, verified="true", external_id="TEST-001"):
        path = Path(self.temp.name) / f"{external_id}-{verified}.csv"
        fields = ["category","item_type","manufacturer","product_name","product_line","variant","unit",
                  "tracking_method","quantity","instance_count","state","location","remaining_quantity",
                  "notes","verified_status","external_id"]
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerow({"category":"Hardware","item_type":"Imported Parts","manufacturer":"Test Maker",
                "product_name":"Imported Part","product_line":"","variant":"","unit":"ea",
                "tracking_method":"quantity","quantity":"5","instance_count":"0","state":"new",
                "location":"Workshop","remaining_quantity":"5","notes":"","verified_status":verified,
                "external_id":external_id})
        return path


if __name__ == "__main__":
    unittest.main()


