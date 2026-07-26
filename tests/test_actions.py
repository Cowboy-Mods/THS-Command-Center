import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from inventory.actions import ActionContext, InventoryActionError, InventoryActionService
from inventory.db import connect, migrate
from inventory.importer import import_csv
from inventory.web import InventoryWebApp


class InventoryActionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        self.db = connect(self.database)
        migrate(self.db)
        self.actions = InventoryActionService(
            self.db,
            ActionContext(actor="Cowboy", module="service-test", origin="user"),
        )

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def scalar(self, sql, params=()):
        return self.db.execute(sql, params).fetchone()[0]

    def test_01_context_requires_actor_module_and_valid_origin(self):
        with self.assertRaises(InventoryActionError):
            ActionContext(actor="", module="test", origin="user")
        with self.assertRaises(InventoryActionError):
            ActionContext(actor="Cowboy", module="", origin="user")
        with self.assertRaises(InventoryActionError):
            ActionContext(actor="Cowboy", module="test", origin="unknown")

    def test_02_configuration_creation_is_centralized_and_audited(self):
        category = self.actions.ensure_category("Action Test")
        unit = self.scalar("SELECT id FROM units WHERE code='ea'")
        item_type = self.actions.ensure_item_type(category, "Action Asset", "individual", unit)
        maker = self.actions.ensure_manufacturer("Action Maker")
        product, created = self.actions.ensure_catalog_item(
            item_type, maker, "Action Asset", "", "Standard", unit
        )
        self.assertTrue(created)
        self.assertEqual(
            [r[0] for r in self.db.execute(
                "SELECT action_type FROM inventory_actions ORDER BY id"
            )],
            ["create_category","create_item_type","create_manufacturer","create_catalog_item"],
        )
        self.assertEqual(product, self.scalar("SELECT id FROM catalog_items WHERE name='Action Asset'"))

    def test_03_add_individual_instance_records_full_audit_and_transaction(self):
        product = self.scalar(
            "SELECT ci.id FROM catalog_items ci JOIN item_types it ON it.id=ci.item_type_id "
            "WHERE it.name='Filament' LIMIT 1"
        )
        location = self.scalar("SELECT id FROM locations WHERE name='Sealed Filament Rack'")
        unit = self.scalar("SELECT id FROM units WHERE code='g'")
        instance = self.actions.add_individual_instance(
            product, permanent_id="THS-FIL-900001", state="sealed", location_id=location,
            original_quantity=1000, remaining_quantity=1000, unit_id=unit,
            verified=True, reason="Service test spool",
        )
        action = self.db.execute(
            "SELECT * FROM inventory_actions WHERE affected_entity_id=? "
            "AND action_type='add_individual_instance'", (instance,)
        ).fetchone()
        self.assertEqual((action["actor"],action["module"],action["origin"]),
                         ("Cowboy","service-test","user"))
        self.assertEqual(action["reason"], "Service test spool")
        self.assertEqual(action["affected_human_id"], "THS-FIL-900001")
        self.assertIsNone(action["previous_state"])
        self.assertEqual(json.loads(action["new_state"])["state"], "sealed")
        self.assertEqual((action["reversible"],action["reverse_action"]),
                         (1,"archive_instance"))
        self.assertIsNotNone(action["transaction_id"])

    def test_04_tracking_policy_validation_rejects_cross_policy_stock(self):
        filament = self.scalar("SELECT catalog_item_id FROM inventory_instances LIMIT 1")
        location = self.scalar("SELECT id FROM locations WHERE name='Workshop'")
        grams = self.scalar("SELECT id FROM units WHERE code='g'")
        with self.assertRaises(InventoryActionError):
            self.actions.add_stock_lot(
                filament, location_id=location, quantity=100, unit_id=grams
            )
        category = self.actions.ensure_category("Bulk Test")
        each = self.scalar("SELECT id FROM units WHERE code='ea'")
        item_type = self.actions.ensure_item_type(category, "Bulk Test Item", "quantity", each)
        product, _ = self.actions.ensure_catalog_item(
            item_type, None, "Bulk Test Item", "", "", each
        )
        with self.assertRaises(InventoryActionError):
            self.actions.add_individual_instance(
                product, state="open", location_id=location, original_quantity=1,
                remaining_quantity=1, unit_id=each,
            )

    def test_05_add_lot_preserves_batch_condition_expiration_and_audit(self):
        product, unit, location = self._lot_product()
        lot = self.actions.add_stock_lot(
            product, location_id=location, quantity=125.5, unit_id=unit,
            lot_number="LOT-ACT-1", condition="opened", expires_at="2027-04-01",
            verified=True, reason="Received partial adhesive lot",
        )
        row = self.db.execute("SELECT * FROM stock_lots WHERE id=?", (lot,)).fetchone()
        self.assertEqual((row["quantity"],row["lot_number"],row["condition"],row["expires_at"]),
                         (125.5,"LOT-ACT-1","opened","2027-04-01"))
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM inventory_actions WHERE action_type='add_stock_lot' "
            "AND affected_entity_id=?", (lot,)
        ), 1)

    def test_06_move_captures_previous_new_state_and_transaction(self):
        instance = 1
        destination = self.scalar("SELECT id FROM locations WHERE name='Open-Spool Wall'")
        action_id = self.actions.move_instance(instance, destination, reason="Move to verified rack")
        action = self.db.execute("SELECT * FROM inventory_actions WHERE id=?", (action_id,)).fetchone()
        previous, new = json.loads(action["previous_state"]), json.loads(action["new_state"])
        self.assertNotEqual(previous["location_id"], new["location_id"])
        self.assertEqual(new["location_id"], destination)
        self.assertEqual(action["reverse_action"], "move_instance")
        self.assertEqual(
            self.scalar("SELECT transaction_type FROM inventory_transactions WHERE id=?",
                        (action["transaction_id"],)),
            "move",
        )

    def test_07_quantity_correction_validates_and_records_delta(self):
        with self.assertRaises(InventoryActionError):
            self.actions.correct_instance_remaining(1, -1)
        with self.assertRaises(InventoryActionError):
            self.actions.correct_instance_remaining(1, 1001)
        action_id = self.actions.correct_instance_remaining(1, 875, reason="Scale reading")
        self.assertEqual(
            self.scalar("SELECT remaining_quantity FROM inventory_instances WHERE id=1"), 875
        )
        tx = self.scalar("SELECT transaction_id FROM inventory_actions WHERE id=?", (action_id,))
        self.assertEqual(
            self.scalar("SELECT quantity_change FROM transaction_lines WHERE transaction_id=?", (tx,)),
            -125,
        )

    def test_08_reversal_restores_state_and_links_new_immutable_action(self):
        destination = self.scalar("SELECT id FROM locations WHERE name='Open-Spool Wall'")
        original = self.scalar("SELECT location_id FROM inventory_instances WHERE id=1")
        action_id = self.actions.move_instance(1, destination)
        reversal_id = self.actions.reverse_action(action_id, reason="Undo mistaken move")
        self.assertEqual(
            self.scalar("SELECT location_id FROM inventory_instances WHERE id=1"), original
        )
        reversal = self.db.execute(
            "SELECT reverses_action_id,reason FROM inventory_actions WHERE id=?", (reversal_id,)
        ).fetchone()
        self.assertEqual((reversal["reverses_action_id"],reversal["reason"]),
                         (action_id,"Undo mistaken move"))
        with self.assertRaises(InventoryActionError):
            self.actions.reverse_action(action_id)

    def test_09_action_history_is_database_immutable(self):
        destination = self.scalar("SELECT id FROM locations WHERE name='Open-Spool Wall'")
        action_id = self.actions.move_instance(1, destination)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            self.db.execute("UPDATE inventory_actions SET actor='Someone Else' WHERE id=?", (action_id,))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            self.db.execute("DELETE FROM inventory_actions WHERE id=?", (action_id,))

    def test_10_failed_action_rolls_back_inventory_transaction_and_audit(self):
        product = self.scalar("SELECT catalog_item_id FROM inventory_instances LIMIT 1")
        location = self.scalar("SELECT id FROM locations WHERE name='Workshop'")
        unit = self.scalar("SELECT id FROM units WHERE code='g'")
        before = (
            self.scalar("SELECT COUNT(*) FROM inventory_instances"),
            self.scalar("SELECT COUNT(*) FROM inventory_transactions"),
            self.scalar("SELECT COUNT(*) FROM inventory_actions"),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.actions.add_individual_instance(
                product, permanent_id="THS-FIL-000001", state="sealed",
                location_id=location, original_quantity=1000, remaining_quantity=1000,
                unit_id=unit,
            )
        after = (
            self.scalar("SELECT COUNT(*) FROM inventory_instances"),
            self.scalar("SELECT COUNT(*) FROM inventory_transactions"),
            self.scalar("SELECT COUNT(*) FROM inventory_actions"),
        )
        self.assertEqual(before, after)

    def test_11_state_change_and_irreversible_empty_action(self):
        open_action = self.actions.change_instance_state(1, "open", reason="Seal opened")
        self.assertEqual(self.scalar("SELECT state FROM inventory_instances WHERE id=1"), "open")
        self.assertEqual(
            self.scalar("SELECT reversible FROM inventory_actions WHERE id=?", (open_action,)), 1
        )
        empty_action = self.actions.change_instance_state(1, "empty", reason="Spool depleted")
        row = self.db.execute(
            "SELECT state,remaining_quantity,archived_at FROM inventory_instances WHERE id=1"
        ).fetchone()
        self.assertEqual((row["state"],row["remaining_quantity"]), ("empty",0))
        self.assertIsNotNone(row["archived_at"])
        self.assertEqual(
            self.scalar("SELECT reversible FROM inventory_actions WHERE id=?", (empty_action,)), 0
        )

    def test_12_reservation_and_release_are_audited_without_consumption(self):
        reservation = self.actions.create_instance_reservation(
            1, 150, project_ref="Yosemite Sam", reason="Planned print"
        )
        self.assertEqual(self.scalar("SELECT remaining_quantity FROM inventory_instances WHERE id=1"),1000)
        create_action = self.scalar(
            "SELECT id FROM inventory_actions WHERE action_type='create_reservation' "
            "AND affected_entity_id=?", (reservation,)
        )
        self.actions.reverse_action(create_action)
        self.assertEqual(
            self.scalar("SELECT status FROM reservations WHERE id=?", (reservation,)), "released"
        )
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM inventory_actions WHERE action_type='release_reservation' "
            "AND reverses_action_id=?", (create_action,)
        ), 1)

    def test_13_ams_load_unload_and_reversal_remain_consistent(self):
        slot = self.scalar("SELECT id FROM equipment_slots ORDER BY id LIMIT 1")
        wall = self.scalar("SELECT id FROM locations WHERE name='Open-Spool Wall'")
        self.actions.open_sealed_spool(1, reason="Verified opening")
        load_action = self.actions.load_instance_into_ams(1, slot, reason="Verified load")
        row = self.db.execute(
            "SELECT state,location_id FROM inventory_instances WHERE id=1"
        ).fetchone()
        self.assertEqual(row["state"], "loaded")
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM ams_assignments WHERE instance_id=1 AND unloaded_at IS NULL"
        ), 1)
        unload_action = self.actions.unload_instance_from_ams(1, wall)
        self.assertEqual(self.scalar("SELECT state FROM inventory_instances WHERE id=1"), "open")
        self.actions.reverse_action(unload_action)
        self.assertEqual(self.scalar("SELECT state FROM inventory_instances WHERE id=1"), "loaded")
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM ams_assignments WHERE instance_id=1 AND unloaded_at IS NULL"
        ), 1)
        self.assertEqual(self.scalar(
            "SELECT reverse_action FROM inventory_actions WHERE id=?", (load_action,)
        ), "unload_instance_from_ams")

    def test_14_importer_routes_applied_inventory_through_service(self):
        path = self._import_csv(verified="true", external_id="ACTION-IMPORT")
        result = import_csv(self.db, path, apply=True)
        self.assertEqual(result["rejected"], 0)
        actions = list(self.db.execute(
            "SELECT actor,module,origin,action_type FROM inventory_actions "
            "WHERE module='inventory-import' ORDER BY id"
        ))
        self.assertGreaterEqual(len(actions), 4)
        self.assertTrue(all(row["actor"].startswith("importer:") for row in actions))
        self.assertTrue(all(row["origin"] == "importer" for row in actions))
        self.assertIn("add_stock_lot", [row["action_type"] for row in actions])

    def test_15_rejected_import_rolls_back_service_actions(self):
        before = self.scalar("SELECT COUNT(*) FROM inventory_actions")
        result = import_csv(
            self.db, self._import_csv(verified="false", external_id="ACTION-REJECT"),
            apply=True,
        )
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_actions"), before)

    def test_16_dashboard_routes_create_no_actions(self):
        before = self.scalar("SELECT COUNT(*) FROM inventory_actions")
        app = InventoryWebApp(self.database)
        for path in ("/","/inventory/filament","/inventory/filament/ams"):
            self.assertEqual(app.response(path)[0], 200)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_actions"), before)

    def test_17_action_uuid_is_unique_and_audit_has_when_who_what_module(self):
        destination = self.scalar("SELECT id FROM locations WHERE name='Open-Spool Wall'")
        self.actions.move_instance(1, destination, reason="Audit completeness")
        action = self.db.execute("SELECT * FROM inventory_actions ORDER BY id DESC LIMIT 1").fetchone()
        self.assertTrue(action["action_uuid"])
        self.assertTrue(action["occurred_at"])
        self.assertEqual(action["actor"], "Cowboy")
        self.assertEqual(action["module"], "service-test")
        self.assertEqual(action["action_type"], "move_instance")
        self.assertEqual(action["reason"], "Audit completeness")

    def _lot_product(self):
        category = self.actions.ensure_category("Action Lots")
        unit = self.scalar("SELECT id FROM units WHERE code='ml'")
        item_type = self.actions.ensure_item_type(category, "Action Adhesive", "lot", unit)
        product, _ = self.actions.ensure_catalog_item(
            item_type, None, "Action Adhesive", "", "Clear", unit
        )
        location = self.scalar("SELECT id FROM locations WHERE name='Workshop'")
        return product, unit, location

    def _import_csv(self, *, verified: str, external_id: str):
        path = Path(self.temp.name) / f"{external_id}.csv"
        fields = [
            "category","item_type","manufacturer","product_name","product_line","variant",
            "unit","tracking_method","quantity","instance_count","state","location",
            "lot_number","condition","expiration_date","remaining_quantity","notes",
            "verified_status","external_id",
        ]
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerow({
                "category":"Hardware","item_type":"Action Import Bulk",
                "manufacturer":"Action Import Maker","product_name":"Action Import Part",
                "product_line":"","variant":"","unit":"ea","tracking_method":"quantity",
                "quantity":"10","instance_count":"0","state":"open","location":"Workshop",
                "lot_number":"","condition":"new","expiration_date":"",
                "remaining_quantity":"10","notes":"Action service import",
                "verified_status":verified,"external_id":external_id,
            })
        return path


if __name__ == "__main__":
    unittest.main()

