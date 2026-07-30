import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from inventory.actions import ActionContext, InventoryActionError, InventoryActionService
from inventory.db import connect, migrate


class FlexibleReplacementServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        self.db = connect(self.database)
        migrate(self.db)
        self.service = InventoryActionService(
            self.db,
            ActionContext(actor="Cowboy", module="flexible-replacement-test", origin="user"),
        )
        self.wall = self.scalar(
            "SELECT id FROM locations WHERE name='Open-Spool Wall'"
        )
        self.slots = [
            row[0] for row in self.db.execute(
                """SELECT es.id FROM equipment_slots es
                JOIN equipment e ON e.id=es.equipment_id
                WHERE e.name='AMS 1' ORDER BY es.slot_number"""
            )
        ]
        self.spools = [
            row[0] for row in self.db.execute(
                """SELECT ii.id FROM inventory_instances ii
                JOIN catalog_items ci ON ci.id=ii.catalog_item_id
                JOIN item_types it ON it.id=ci.item_type_id
                WHERE it.name='Filament' AND ii.state='sealed'
                ORDER BY ii.id LIMIT 8"""
            )
        ]
        self.current = self.spools[0]
        self._load(self.current, self.slots[0])

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def scalar(self, sql, params=()):
        return self.db.execute(sql, params).fetchone()[0]

    def row(self, sql, params=()):
        found = self.db.execute(sql, params).fetchone()
        return dict(found) if found else None

    def _load(self, instance_id, slot_id):
        state = self.scalar(
            "SELECT state FROM inventory_instances WHERE id=?", (instance_id,)
        )
        if state == "sealed":
            self.service.open_sealed_spool(instance_id, reason="Fixture opening")
        self.service.load_instance_into_ams(instance_id, slot_id, reason="Fixture load")

    def _open(self, instance_id):
        self.service.open_sealed_spool(instance_id, reason="Fixture opening")

    def _location(self, instance_id):
        return self.scalar(
            "SELECT location_id FROM inventory_instances WHERE id=?", (instance_id,)
        )

    def _counts(self):
        return {
            "workflows": self.scalar(
                "SELECT COUNT(*) FROM inventory_workflow_transactions"
            ),
            "actions": self.scalar("SELECT COUNT(*) FROM inventory_actions"),
            "transactions": self.scalar("SELECT COUNT(*) FROM inventory_transactions"),
            "assignments": self.scalar("SELECT COUNT(*) FROM ams_assignments"),
        }

    def _replace(self, suffix, **changes):
        values = {
            "current_instance_id": self.current,
            "outgoing_disposition": "storage",
            "outgoing_destination_location_id": self.wall,
            "incoming_disposition": "none",
            "reason": "Flexible replacement service test",
            "review_nonce": f"flexible-service-{suffix}",
        }
        values.update(changes)
        return self.service.flexibly_replace_active_filament_spool(**values)

    def test_01_empty_outgoing_and_sealed_incoming(self):
        incoming = self.spools[1]
        result = self._replace(
            "empty-sealed",
            outgoing_disposition="empty",
            outgoing_destination_location_id=None,
            incoming_disposition="sealed",
            incoming_instance_id=incoming,
            incoming_source_location_id=self._location(incoming),
            incoming_destination_slot_id=self.slots[0],
        )
        self.assertEqual(
            self.row(
                "SELECT state,remaining_quantity,archived_at "
                "FROM inventory_instances WHERE id=?",
                (self.current,),
            )["state"],
            "empty",
        )
        self.assertEqual(
            self.scalar("SELECT state FROM inventory_instances WHERE id=?", (incoming,)),
            "loaded",
        )
        self.assertEqual(len(result["outgoing_action_ids"]), 1)
        self.assertEqual(len(result["incoming_action_ids"]), 2)

    def test_02_partially_used_to_storage_and_sealed_incoming(self):
        incoming = self.spools[1]
        before_quantity = self.scalar(
            "SELECT remaining_quantity FROM inventory_instances WHERE id=?",
            (self.current,),
        )
        result = self._replace(
            "storage-sealed",
            incoming_disposition="sealed",
            incoming_instance_id=incoming,
            incoming_source_location_id=self._location(incoming),
            incoming_destination_slot_id=self.slots[0],
        )
        outgoing = self.row(
            "SELECT state,location_id,remaining_quantity FROM inventory_instances WHERE id=?",
            (self.current,),
        )
        self.assertEqual(
            outgoing,
            {
                "state": "open",
                "location_id": self.wall,
                "remaining_quantity": before_quantity,
            },
        )
        self.assertEqual(
            self.scalar(
                "SELECT slot_id FROM ams_assignments "
                "WHERE instance_id=? AND unloaded_at IS NULL",
                (incoming,),
            ),
            self.slots[0],
        )
        self.assertEqual(result["outgoing_disposition"], "storage")

    def test_03_partially_used_to_storage_and_open_incoming(self):
        incoming = self.spools[1]
        self._open(incoming)
        incoming_source = self._location(incoming)
        self._replace(
            "storage-open",
            incoming_disposition="open",
            incoming_instance_id=incoming,
            incoming_source_location_id=incoming_source,
            incoming_destination_slot_id=self.slots[0],
        )
        self.assertEqual(
            self.scalar("SELECT state FROM inventory_instances WHERE id=?", (incoming,)),
            "loaded",
        )
        workflow = self.row(
            "SELECT * FROM inventory_workflow_transactions ORDER BY id DESC LIMIT 1"
        )
        self.assertEqual(workflow["incoming_disposition"], "open")
        self.assertEqual(workflow["incoming_source_location_id"], incoming_source)
        self.assertIsNone(workflow["replacement_instance_id"])

    def test_04_partially_used_moves_to_another_ams_slot(self):
        result = self._replace(
            "move-slot",
            outgoing_disposition="ams_slot",
            outgoing_destination_location_id=None,
            outgoing_destination_slot_id=self.slots[1],
        )
        self.assertEqual(
            self.scalar(
                "SELECT slot_id FROM ams_assignments "
                "WHERE instance_id=? AND unloaded_at IS NULL",
                (self.current,),
            ),
            self.slots[1],
        )
        self.assertEqual(len(result["outgoing_action_ids"]), 2)
        self.assertEqual(result["incoming_action_ids"], [])

    def test_05_no_replacement_leaves_source_slot_empty(self):
        self._replace("no-replacement")
        self.assertEqual(
            self.scalar(
                "SELECT COUNT(*) FROM ams_assignments "
                "WHERE slot_id=? AND unloaded_at IS NULL",
                (self.slots[0],),
            ),
            0,
        )
        workflow = self.row(
            "SELECT * FROM inventory_workflow_transactions ORDER BY id DESC LIMIT 1"
        )
        self.assertEqual(workflow["incoming_disposition"], "none")
        self.assertIsNone(workflow["incoming_instance_id"])
        self.assertIsNone(workflow["incoming_destination_slot_id"])

    def test_06_unrelated_occupied_destination_is_rejected_before_writes(self):
        occupant = self.spools[1]
        self._load(occupant, self.slots[1])
        before = self._counts()
        with self.assertRaisesRegex(
            InventoryActionError, "occupied by another spool"
        ):
            self._replace(
                "occupied",
                outgoing_disposition="ams_slot",
                outgoing_destination_location_id=None,
                outgoing_destination_slot_id=self.slots[1],
            )
        self.assertEqual(before, self._counts())
        self.assertEqual(
            self.scalar(
                "SELECT slot_id FROM ams_assignments "
                "WHERE instance_id=? AND unloaded_at IS NULL",
                (self.current,),
            ),
            self.slots[0],
        )

    def test_07_incoming_source_mismatch_and_duplicate_identity_are_rejected(self):
        incoming = self.spools[1]
        self._open(incoming)
        before = self._counts()
        with self.assertRaisesRegex(InventoryActionError, "not at the stated source"):
            self._replace(
                "wrong-source",
                incoming_disposition="open",
                incoming_instance_id=incoming,
                incoming_source_location_id=self.wall,
                incoming_destination_slot_id=self.slots[0],
            )
        with self.assertRaisesRegex(InventoryActionError, "must be different"):
            self._replace(
                "same-spool",
                incoming_disposition="open",
                incoming_instance_id=self.current,
                incoming_source_slot_id=self.slots[0],
                incoming_destination_slot_id=self.slots[1],
            )
        self.assertEqual(before, self._counts())

    def test_08_any_failed_child_action_rolls_back_the_complete_workflow(self):
        incoming = self.spools[1]
        source = self._location(incoming)
        before = self._counts()
        self.db.execute(
            """CREATE TRIGGER fail_flexible_incoming_load
            BEFORE INSERT ON inventory_actions
            WHEN NEW.action_type='load_instance_into_ams'
            BEGIN SELECT RAISE(ABORT,'simulated flexible load failure'); END"""
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "simulated flexible"):
            self._replace(
                "rollback",
                incoming_disposition="sealed",
                incoming_instance_id=incoming,
                incoming_source_location_id=source,
                incoming_destination_slot_id=self.slots[0],
            )
        self.assertEqual(before, self._counts())
        self.assertEqual(
            self.scalar("SELECT state FROM inventory_instances WHERE id=?", (self.current,)),
            "loaded",
        )
        self.assertEqual(
            self.scalar("SELECT state FROM inventory_instances WHERE id=?", (incoming,)),
            "sealed",
        )

    def test_09_parent_and_child_audits_capture_both_dispositions_and_locations(self):
        incoming = self.spools[1]
        self._open(incoming)
        incoming_source = self._location(incoming)
        result = self._replace(
            "audit",
            incoming_disposition="open",
            incoming_instance_id=incoming,
            incoming_source_location_id=incoming_source,
            incoming_destination_slot_id=self.slots[0],
        )
        parent = self.row(
            "SELECT * FROM inventory_workflow_transactions WHERE id=?",
            (result["workflow_transaction_id"],),
        )
        self.assertEqual(
            (
                parent["outgoing_disposition"],
                parent["outgoing_destination_location_id"],
                parent["incoming_disposition"],
                parent["incoming_source_location_id"],
                parent["incoming_instance_id"],
                parent["incoming_destination_slot_id"],
            ),
            ("storage", self.wall, "open", incoming_source, incoming, self.slots[0]),
        )
        actions = [
            dict(row) for row in self.db.execute(
                """SELECT action_type,affected_entity_id,previous_state,new_state
                FROM inventory_actions WHERE workflow_transaction_id=? ORDER BY id""",
                (result["workflow_transaction_id"],),
            )
        ]
        self.assertEqual(
            [(row["action_type"], row["affected_entity_id"]) for row in actions],
            [
                ("unload_instance_from_ams", self.current),
                ("load_instance_into_ams", incoming),
            ],
        )
        outgoing_before = json.loads(actions[0]["previous_state"])
        outgoing_after = json.loads(actions[0]["new_state"])
        incoming_before = json.loads(actions[1]["previous_state"])
        incoming_after = json.loads(actions[1]["new_state"])
        self.assertEqual(outgoing_before["location_id"], self._slot_location(self.slots[0]))
        self.assertEqual(outgoing_after["location_id"], self.wall)
        self.assertEqual(incoming_before["location_id"], incoming_source)
        self.assertEqual(incoming_after["location_id"], self._slot_location(self.slots[0]))

    def test_10_atomic_swap_may_use_slots_vacated_by_the_same_workflow(self):
        incoming = self.spools[1]
        self._load(incoming, self.slots[1])
        self._replace(
            "swap",
            outgoing_disposition="ams_slot",
            outgoing_destination_location_id=None,
            outgoing_destination_slot_id=self.slots[1],
            incoming_disposition="open",
            incoming_instance_id=incoming,
            incoming_source_slot_id=self.slots[1],
            incoming_destination_slot_id=self.slots[0],
        )
        active = {
            row["instance_id"]: row["slot_id"] for row in self.db.execute(
                "SELECT instance_id,slot_id FROM ams_assignments WHERE unloaded_at IS NULL"
            )
        }
        self.assertEqual(active[self.current], self.slots[1])
        self.assertEqual(active[incoming], self.slots[0])

    def test_11_legacy_sealed_replacement_contract_remains_unchanged(self):
        incoming = self.spools[1]
        result = self.service.replace_active_filament_spool(
            self.current,
            incoming,
            self.slots[0],
            reason="Legacy compatibility",
            review_nonce="legacy-after-schema-19",
        )
        row = self.row(
            "SELECT * FROM inventory_workflow_transactions WHERE id=?",
            (result["workflow_transaction_id"],),
        )
        self.assertEqual(row["replacement_instance_id"], incoming)
        self.assertEqual(row["destination_slot_id"], self.slots[0])
        self.assertIsNone(row["outgoing_disposition"])
        self.assertIsNone(row["incoming_disposition"])

    def _slot_location(self, slot_id):
        return self.scalar(
            "SELECT location_id FROM equipment_slots WHERE id=?", (slot_id,)
        )


if __name__ == "__main__":
    unittest.main()
