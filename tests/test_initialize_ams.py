import tempfile
import unittest
from pathlib import Path

from inventory.actions import ActionContext, InventoryActionService
from inventory.db import connect, migrate
from inventory.initialization import InitializeAMSError
from inventory.web import InventoryWebApp


class InitializeVerifiedAMSStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        self.jade = self._spool(db, "Bambu Lab", "Jade White")
        self.orange = self._spools(db, "Bambu Lab", "Orange")[0]
        self.slot1 = self._slot(db, "AMS 1", 1)
        self.slot2 = self._slot(db, "AMS 1", 2)
        db.close()
        self.app = InventoryWebApp(self.database)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _spool(db, maker, color):
        return InitializeVerifiedAMSStateTests._spools(db, maker, color)[0]

    @staticmethod
    def _spools(db, maker, color):
        return [
            row[0] for row in db.execute(
                """SELECT ii.id FROM inventory_instances ii
                JOIN catalog_items ci ON ci.id=ii.catalog_item_id
                JOIN manufacturers m ON m.id=ci.manufacturer_id
                WHERE m.name=? AND ci.variant=? ORDER BY ii.permanent_id""",
                (maker, color),
            )
        ]

    @staticmethod
    def _slot(db, equipment, number):
        return db.execute(
            """SELECT es.id FROM equipment_slots es
            JOIN equipment e ON e.id=es.equipment_id
            WHERE e.name=? AND es.slot_number=?""",
            (equipment, number),
        ).fetchone()[0]

    def form(self, **changes):
        values = {
            "instance_id": str(self.jade),
            "slot_id": str(self.slot1),
            "effective_at": "2026-07-25T20:15",
            "actor": "Cowboy",
            "reason": "Verified after physical loading",
            "confirm_verified": "yes",
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
            self.scalar("SELECT COUNT(*) FROM inventory_instances"),
            self.scalar("SELECT COUNT(*) FROM ams_assignments"),
            self.scalar("SELECT COUNT(*) FROM inventory_transactions"),
            self.scalar("SELECT COUNT(*) FROM transaction_lines"),
            self.scalar("SELECT COUNT(*) FROM inventory_actions"),
        )

    def test_01_form_is_narrow_and_exposes_no_general_ams_editing(self):
        status, _, body = self.app.response("/inventory/filament/ams/initialize")
        page = body.decode()
        self.assertEqual(status, 200)
        self.assertIn("Initialize Verified AMS State", page)
        self.assertIn("does not create inventory", page)
        self.assertNotIn("Delete", page)
        self.assertNotIn("Edit slot", page)
        self.assertNotIn("remaining weight", page.lower())

    def test_02_preview_performs_zero_writes_and_shows_verified_values(self):
        before = self.counts()
        status, _, body = self.app.response(
            "/inventory/filament/ams/initialize/review",
            method="POST", form=self.form(),
        )
        page = body.decode()
        self.assertEqual(status, 200)
        for expected in (
            "Preview only — zero writes", "Jade White", "Sealed → Open → Loaded",
            "AMS 1 Slot 1", "No spool weight change", "2026-07-25",
        ):
            self.assertIn(expected, page)
        self.assertEqual(before, self.counts())

    def test_03_signed_preview_expiry_is_rejected(self):
        review = self.app.initialization.review(self.form())
        expired = dict(review.values)
        expired["reviewed_at"] = 1
        token = self.app.initialization._sign(expired)
        with self.assertRaisesRegex(InitializeAMSError, "expired"):
            self.app.initialization.commit(token)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM ams_assignments"), 0)

    def test_04_tampered_preview_is_rejected(self):
        review = self.app.initialization.review(self.form())
        token = review.token[:-1] + ("A" if review.token[-1] != "A" else "B")
        with self.assertRaisesRegex(InitializeAMSError, "preview is invalid"):
            self.app.initialization.commit(token)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM ams_assignments"), 0)

    def test_05_replay_is_rejected(self):
        review = self.app.initialization.review(self.form())
        self.app.initialization.commit(review.token)
        with self.assertRaises(InitializeAMSError):
            self.app.initialization.commit(review.token)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM ams_assignments WHERE unloaded_at IS NULL"
        ), 1)

    def test_06_occupied_slot_is_rejected(self):
        db = connect(self.database)
        service = InventoryActionService(
            db, ActionContext(actor="Fixture", module="test", origin="system")
        )
        service.open_sealed_spool(self.orange, reason="Fixture")
        service.load_instance_into_ams(self.orange, self.slot1, reason="Fixture")
        db.commit()
        db.close()
        with self.assertRaisesRegex(InitializeAMSError, "already occupied"):
            self.app.initialization.review(self.form())

    def test_07_duplicate_active_assignment_is_rejected(self):
        first = self.app.initialization.review(self.form())
        self.app.initialization.commit(first.token)
        with self.assertRaisesRegex(InitializeAMSError, "without an AMS assignment"):
            self.app.initialization.review(self.form(slot_id=str(self.slot2)))

    def test_08_sealed_spool_transitions_open_then_loaded(self):
        result = self.app.initialization.commit(
            self.app.initialization.review(self.form()).token
        )
        self.assertIsNotNone(result["open_action_id"])
        actions = [
            row[0] for row in self._rows(
                "SELECT action_type FROM inventory_actions WHERE module=? ORDER BY id",
                ("verified-ams-initialization-ui",),
            )
        ]
        self.assertEqual(actions, ["open_sealed_spool", "load_instance_into_ams"])
        self.assertEqual(self.scalar(
            "SELECT state FROM inventory_instances WHERE id=?", (self.jade,)
        ), "loaded")

    def test_09_open_spool_transitions_directly_to_loaded(self):
        db = connect(self.database)
        service = InventoryActionService(
            db, ActionContext(actor="Fixture", module="test", origin="system")
        )
        service.open_sealed_spool(self.jade, reason="Already physically open")
        db.commit()
        db.close()
        result = self.app.initialization.commit(
            self.app.initialization.review(self.form()).token
        )
        self.assertIsNone(result["open_action_id"])
        self.assertEqual(self.scalar(
            "SELECT state FROM inventory_instances WHERE id=?", (self.jade,)
        ), "loaded")

    def test_10_empty_archived_and_loaded_states_are_ineligible(self):
        for state in ("empty", "archived", "loaded"):
            with self.subTest(state=state):
                db = connect(self.database)
                db.execute(
                    "UPDATE inventory_instances SET state=?,archived_at="
                    "CASE WHEN ? IN ('empty','archived') THEN CURRENT_TIMESTAMP ELSE NULL END "
                    "WHERE id=?",
                    (state, state, self.jade),
                )
                db.commit()
                db.close()
                with self.assertRaisesRegex(InitializeAMSError, "sealed or open"):
                    self.app.initialization.review(self.form())
                db = connect(self.database)
                db.execute(
                    "UPDATE inventory_instances SET state='sealed',archived_at=NULL WHERE id=?",
                    (self.jade,),
                )
                db.commit()
                db.close()

    def test_11_verified_backdated_timestamp_reaches_assignment_transaction_and_audit(self):
        result = self.app.initialization.commit(
            self.app.initialization.review(self.form()).token
        )
        expected = "2026-07-25T20:15:00-04:00"
        self.assertEqual(result["assignment"]["loaded_at"], expected)
        load_action = self.row(
            "SELECT occurred_at,transaction_id FROM inventory_actions WHERE id=?",
            (result["load_action_id"],),
        )
        self.assertEqual(load_action["occurred_at"], expected)
        self.assertEqual(self.scalar(
            "SELECT occurred_at FROM inventory_transactions WHERE id=?",
            (load_action["transaction_id"],),
        ), expected)

    def test_12_weight_is_never_changed(self):
        before = self.row(
            "SELECT original_quantity,remaining_quantity FROM inventory_instances WHERE id=?",
            (self.jade,),
        )
        self.app.initialization.commit(self.app.initialization.review(self.form()).token)
        after = self.row(
            "SELECT original_quantity,remaining_quantity FROM inventory_instances WHERE id=?",
            (self.jade,),
        )
        self.assertEqual(before, after)

    def test_13_service_creates_assignment_transaction_line_and_immutable_audit(self):
        result = self.app.initialization.commit(
            self.app.initialization.review(self.form()).token
        )
        action = self.row(
            "SELECT * FROM inventory_actions WHERE id=?", (result["load_action_id"],)
        )
        self.assertEqual(action["module"], "verified-ams-initialization-ui")
        self.assertEqual(action["action_type"], "load_instance_into_ams")
        self.assertEqual(action["request_nonce"], result["request_nonce"])
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM transaction_lines WHERE transaction_id=? AND instance_id=?",
            (action["transaction_id"], self.jade),
        ), 1)
        db = connect(self.database)
        with self.assertRaises(Exception):
            db.execute(
                "UPDATE inventory_actions SET reason='changed' WHERE id=?",
                (result["load_action_id"],),
            )
        db.close()

    def test_14_atomic_failure_rolls_back_open_load_transaction_line_and_audit(self):
        review = self.app.initialization.review(self.form())
        before = self.counts()
        db = connect(self.database)
        db.execute(
            """CREATE TRIGGER fail_initialization_load_audit
            BEFORE INSERT ON inventory_actions
            WHEN NEW.action_type='load_instance_into_ams'
            BEGIN SELECT RAISE(ABORT,'simulated initialization failure'); END"""
        )
        db.commit()
        db.close()
        with self.assertRaisesRegex(InitializeAMSError, "simulated initialization failure"):
            self.app.initialization.commit(review.token)
        self.assertEqual(before, self.counts())
        self.assertEqual(self.scalar(
            "SELECT state FROM inventory_instances WHERE id=?", (self.jade,)
        ), "sealed")

    def test_15_confirmation_and_responsive_structure_are_present(self):
        review = self.app.initialization.review(self.form())
        status, _, page = self.app.response(
            "/inventory/filament/ams/initialize/confirm", method="POST",
            form={"review_token": review.token},
        )
        self.assertEqual(status, 422)
        _, _, css = self.app.response("/static/style.css")
        stylesheet = css.decode()
        self.assertIn("@media (max-width: 58rem)", stylesheet)
        self.assertIn("@media (max-width: 42rem)", stylesheet)
        self.assertIn("initialization-preview", self.app.response(
            "/inventory/filament/ams/initialize/review",
            method="POST", form=self.form(),
        )[2].decode())

    def test_16_initialization_never_creates_new_filament_inventory(self):
        before = self.scalar("SELECT COUNT(*) FROM inventory_instances")
        self.app.initialization.commit(self.app.initialization.review(self.form()).token)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_instances"), before)

    def _rows(self, sql, params=()):
        db = connect(self.database)
        try:
            return db.execute(sql, params).fetchall()
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
