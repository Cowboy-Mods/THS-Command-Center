import json
import tempfile
import unittest
from pathlib import Path

from inventory.actions import ActionContext, InventoryActionService
from inventory.db import connect, migrate
from inventory.replacement import ReplaceSpoolError
from inventory.web import InventoryWebApp


class ReplaceActiveFilamentSpoolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        self.slot1 = db.execute(
            """SELECT es.id FROM equipment_slots es JOIN equipment e ON e.id=es.equipment_id
            WHERE e.name='AMS 1' AND es.slot_number=1"""
        ).fetchone()[0]
        self.slot2 = db.execute(
            """SELECT es.id FROM equipment_slots es JOIN equipment e ON e.id=es.equipment_id
            WHERE e.name='AMS 1' AND es.slot_number=2"""
        ).fetchone()[0]
        self.white = self._find(db, "Elegoo", "White")[0]
        self.jade = self._find(db, "Bambu Lab", "Jade White")[0]
        self.orange = self._find(db, "Bambu Lab", "Orange")
        self._load(db, self.white, self.slot1)
        db.commit()
        db.close()
        self.app = InventoryWebApp(self.database)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _find(db, manufacturer, color):
        return [
            row[0] for row in db.execute(
                """SELECT ii.id FROM inventory_instances ii
                JOIN catalog_items ci ON ci.id=ii.catalog_item_id
                JOIN manufacturers m ON m.id=ci.manufacturer_id
                WHERE m.name=? AND ci.variant=? ORDER BY ii.permanent_id""",
                (manufacturer, color),
            )
        ]

    @staticmethod
    def _load(db, instance_id, slot_id):
        service = InventoryActionService(
            db, ActionContext(actor="Test setup", module="test-fixture", origin="system")
        )
        service.open_sealed_spool(instance_id, reason="Test setup")
        service.load_instance_into_ams(instance_id, slot_id, reason="Test setup")

    def form(self, **changes):
        values = {
            "current_instance_id": str(self.white),
            "replacement_instance_id": str(self.jade),
            "destination_slot_id": "",
            "confirm_empty": "yes",
            "actor": "Cowboy",
            "reason": "White replacement already performed",
        }
        values.update(changes)
        return values

    def scalar(self, sql, params=()):
        db = connect(self.database)
        try:
            return db.execute(sql, params).fetchone()[0]
        finally:
            db.close()

    def row(self, sql, params=()):
        db = connect(self.database)
        try:
            found = db.execute(sql, params).fetchone()
            return dict(found) if found else None
        finally:
            db.close()

    def counts(self):
        return (
            self.scalar("SELECT COUNT(*) FROM inventory_workflow_transactions"),
            self.scalar("SELECT COUNT(*) FROM inventory_actions"),
            self.scalar("SELECT COUNT(*) FROM inventory_transactions"),
            self.scalar("SELECT COUNT(*) FROM transaction_lines"),
            self.scalar("SELECT COUNT(*) FROM ams_assignments"),
        )

    def test_01_form_shows_only_active_current_and_sealed_replacements(self):
        data = self.app.replacement.options()
        self.assertEqual([s["id"] for s in data["current_spools"]], [self.white])
        replacement_ids = {s["id"] for s in data["replacement_spools"]}
        self.assertIn(self.jade, replacement_ids)
        self.assertNotIn(self.white, replacement_ids)
        self.assertTrue(all(s["state"] == "sealed" for s in data["replacement_spools"]))

    def test_02_replacement_filter_supports_id_manufacturer_material_and_color(self):
        jade_id = self.row(
            "SELECT permanent_id FROM inventory_instances WHERE id=?", (self.jade,)
        )["permanent_id"]
        for filters in (
            {"q": jade_id},
            {"manufacturer": "Bambu Lab"},
            {"material": "PLA"},
            {"color": "Jade White"},
        ):
            results = self.app.replacement.options(filters)["replacement_spools"]
            self.assertIn(self.jade, {row["id"] for row in results})
        orange = self.app.replacement.options({"color": "Orange"})["replacement_spools"]
        self.assertEqual({row["id"] for row in orange}, set(self.orange))

    def test_03_preview_shows_actual_ids_slot_and_performs_zero_writes(self):
        before = self.counts()
        status, _, page = self.app.response(
            "/inventory/filament/replace/review", method="POST", form=self.form()
        )
        text = page.decode()
        current_id = self.row(
            "SELECT permanent_id FROM inventory_instances WHERE id=?", (self.white,)
        )["permanent_id"]
        jade_id = self.row(
            "SELECT permanent_id FROM inventory_instances WHERE id=?", (self.jade,)
        )["permanent_id"]
        self.assertEqual(status, 200)
        for expected in (
            current_id, jade_id, "Unload and mark Empty", "Open sealed replacement",
            "Load replacement", "AMS 1 Slot 1", "Preview only â€” zero inventory writes",
        ):
            self.assertIn(expected, text)
        self.assertEqual(before, self.counts())

    def test_04_explicit_empty_and_final_confirmation_are_required(self):
        status, _, _ = self.app.response(
            "/inventory/filament/replace/review",
            method="POST", form=self.form(confirm_empty=""),
        )
        self.assertEqual(status, 422)
        review = self.app.replacement.review(self.form())
        status, _, _ = self.app.response(
            "/inventory/filament/replace/confirm", method="POST",
            form={"review_token": review.token},
        )
        self.assertEqual(status, 422)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_workflow_transactions"), 0)

    def test_05_only_sealed_spools_can_be_replacements(self):
        db = connect(self.database)
        service = InventoryActionService(
            db, ActionContext(actor="Test", module="test", origin="system")
        )
        service.open_sealed_spool(self.jade, reason="No longer sealed")
        db.commit()
        db.close()
        with self.assertRaisesRegex(ReplaceSpoolError, "sealed and active"):
            self.app.replacement.review(self.form())

    def test_06_jade_white_scenario_commits_three_linked_actions(self):
        result = self.app.replacement.commit(
            self.app.replacement.review(self.form()).token
        )
        self.assertEqual(self.scalar(
            "SELECT state FROM inventory_instances WHERE id=?", (self.white,)
        ), "empty")
        self.assertEqual(self.scalar(
            "SELECT state FROM inventory_instances WHERE id=?", (self.jade,)
        ), "loaded")
        actions = [
            dict(row) for row in self._rows(
                "SELECT * FROM inventory_actions WHERE workflow_transaction_id=? ORDER BY id",
                (result["workflow_transaction_id"],),
            )
        ]
        self.assertEqual(
            [a["action_type"] for a in actions],
            ["mark_spool_empty", "open_sealed_spool", "load_instance_into_ams"],
        )
        self.assertEqual(len({a["transaction_id"] for a in actions}), 3)
        opened = json.loads(actions[1]["new_state"])
        self.assertEqual(opened["state"], "open")
        self.assertTrue(all(a["actor"] == "Cowboy" for a in actions))

    def test_07_original_is_removed_and_replacement_occupies_same_slot(self):
        self.app.replacement.commit(self.app.replacement.review(self.form()).token)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM ams_assignments WHERE instance_id=? AND unloaded_at IS NULL",
            (self.white,),
        ), 0)
        active = self.row(
            "SELECT instance_id,slot_id FROM ams_assignments "
            "WHERE unloaded_at IS NULL AND instance_id=?",
            (self.jade,),
        )
        self.assertEqual(active, {"instance_id": self.jade, "slot_id": self.slot1})

    def test_08_destination_can_change_to_an_empty_slot(self):
        result = self.app.replacement.commit(
            self.app.replacement.review(
                self.form(destination_slot_id=str(self.slot2))
            ).token
        )
        self.assertEqual(result["destination_slot_id"], self.slot2)
        self.assertEqual(self.scalar(
            "SELECT slot_id FROM ams_assignments WHERE instance_id=? AND unloaded_at IS NULL",
            (self.jade,),
        ), self.slot2)

    def test_09_occupied_other_destination_is_rejected(self):
        other = self.orange[0]
        db = connect(self.database)
        self._load(db, other, self.slot2)
        db.commit()
        db.close()
        with self.assertRaisesRegex(ReplaceSpoolError, "occupied by another spool"):
            self.app.replacement.review(
                self.form(destination_slot_id=str(self.slot2))
            )

    def test_10_stale_preview_fails_without_partial_workflow(self):
        review = self.app.replacement.review(self.form())
        db = connect(self.database)
        service = InventoryActionService(
            db, ActionContext(actor="Other action", module="test", origin="system")
        )
        service.open_sealed_spool(self.jade, reason="State changed")
        db.commit()
        db.close()
        before = self.counts()
        with self.assertRaisesRegex(ReplaceSpoolError, "replacement spool changed"):
            self.app.replacement.commit(review.token)
        self.assertEqual(before, self.counts())
        self.assertEqual(self.scalar(
            "SELECT state FROM inventory_instances WHERE id=?", (self.white,)
        ), "loaded")

    def test_11_tampered_preview_fails(self):
        review = self.app.replacement.review(self.form())
        token = review.token[:-1] + ("A" if review.token[-1] != "A" else "B")
        with self.assertRaisesRegex(ReplaceSpoolError, "preview is invalid"):
            self.app.replacement.commit(token)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_workflow_transactions"), 0)

    def test_12_replayed_preview_fails(self):
        review = self.app.replacement.review(self.form())
        self.app.replacement.commit(review.token)
        with self.assertRaises(ReplaceSpoolError):
            self.app.replacement.commit(review.token)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_workflow_transactions"), 1)

    def test_13_failure_rolls_back_states_assignments_transactions_and_audits(self):
        review = self.app.replacement.review(self.form())
        before_counts = self.counts()
        db = connect(self.database)
        db.execute(
            """CREATE TRIGGER fail_replacement_load_audit
            BEFORE INSERT ON inventory_actions
            WHEN NEW.action_type='load_instance_into_ams'
            BEGIN SELECT RAISE(ABORT,'simulated load audit failure'); END"""
        )
        db.commit()
        db.close()
        with self.assertRaisesRegex(ReplaceSpoolError, "simulated load audit failure"):
            self.app.replacement.commit(review.token)
        self.assertEqual(before_counts, self.counts())
        self.assertEqual(self.scalar(
            "SELECT state FROM inventory_instances WHERE id=?", (self.white,)
        ), "loaded")
        self.assertEqual(self.scalar(
            "SELECT state FROM inventory_instances WHERE id=?", (self.jade,)
        ), "sealed")
        self.assertEqual(self.scalar(
            "SELECT instance_id FROM ams_assignments WHERE slot_id=? AND unloaded_at IS NULL",
            (self.slot1,),
        ), self.white)

    def test_14_parent_workflow_and_actions_are_database_immutable(self):
        result = self.app.replacement.commit(
            self.app.replacement.review(self.form()).token
        )
        db = connect(self.database)
        with self.assertRaises(Exception):
            db.execute(
                "UPDATE inventory_workflow_transactions SET reason='changed' WHERE id=?",
                (result["workflow_transaction_id"],),
            )
        with self.assertRaises(Exception):
            db.execute(
                "DELETE FROM inventory_actions WHERE workflow_transaction_id=?",
                (result["workflow_transaction_id"],),
            )
        db.close()

    def test_15_orange_tweety_scenario_works_without_hard_coded_product_rules(self):
        db = connect(self.database)
        # Return the white fixture to a non-active state, then load one Orange spool.
        service = InventoryActionService(
            db, ActionContext(actor="Test setup", module="test-fixture", origin="system")
        )
        service.unload_instance_from_ams(self.white, self.scalar(
            "SELECT id FROM locations WHERE name='Open-Spool Wall'"
        ), reason="Switch fixture")
        self._load(db, self.orange[0], self.slot1)
        db.commit()
        db.close()
        orange_form = self.form(
            current_instance_id=str(self.orange[0]),
            replacement_instance_id=str(self.orange[1]),
            reason="Modified Tweety Bird THS orange hat; about 10 minutes remaining",
        )
        result = self.app.replacement.commit(
            self.app.replacement.review(orange_form).token
        )
        self.assertEqual(self.scalar(
            "SELECT state FROM inventory_instances WHERE id=?", (self.orange[0],)
        ), "empty")
        self.assertEqual(self.scalar(
            "SELECT state FROM inventory_instances WHERE id=?", (self.orange[1],)
        ), "loaded")
        self.assertEqual(result["destination_slot_id"], self.slot1)
        self.assertIn("Tweety Bird", result["reason"])

    def test_16_completion_page_summarizes_parent_and_three_actions(self):
        review = self.app.replacement.review(self.form())
        status, _, body = self.app.response(
            "/inventory/filament/replace/confirm", method="POST",
            form={"review_token": review.token, "confirm": "replace"},
        )
        page = body.decode()
        self.assertEqual(status, 201)
        for text in (
            "Atomic workflow completed", "Parent workflow transaction",
            "Mark Empty action", "Open Sealed action", "Load AMS action",
        ):
            self.assertIn(text, page)

    def _rows(self, sql, params=()):
        db = connect(self.database)
        try:
            return db.execute(sql, params).fetchall()
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()

