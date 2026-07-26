import tempfile
import unittest
from pathlib import Path

from inventory.actions import ActionContext, InventoryActionError, InventoryActionService
from inventory.db import connect, migrate
from inventory.orders import OrderReceiptError
from inventory.web import InventoryWebApp


class OrdersAndPrinterFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        self.order_id = db.execute(
            "SELECT id FROM orders WHERE order_number='THS-ORD-000001'"
        ).fetchone()[0]
        self.location_id = db.execute(
            "SELECT id FROM locations WHERE name='Sealed Filament Rack'"
        ).fetchone()[0]
        db.close()
        self.app = InventoryWebApp(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def form(self, quantity="4", **changes):
        values = {
            "order_id": str(self.order_id), "actual_quantity": quantity,
            "condition": "new", "location_id": str(self.location_id),
            "actor": "Cowboy", "reason": "Verified delivered refills",
            "note": "Box and refill rolls inspected", "physically_verified": "yes",
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

    def test_01_seeded_overture_order_is_pending_without_inventory(self):
        order = self.row("SELECT * FROM orders WHERE id=?", (self.order_id,))
        self.assertEqual(
            (order["supplier"], order["expected_quantity"], order["material"],
             order["color"], order["state"], order["received_quantity"]),
            ("Overture", 4, "PLA", "White", "ordered", 0),
        )
        self.assertEqual(
            self.scalar(
                """SELECT COUNT(*) FROM inventory_instances ii JOIN catalog_items ci
                ON ci.id=ii.catalog_item_id JOIN manufacturers m ON m.id=ci.manufacturer_id
                WHERE m.name='Overture' AND ci.variant='White'"""
            ), 0,
        )

    def test_02_order_creation_and_state_transitions_are_service_controlled(self):
        db = connect(self.database)
        service = InventoryActionService(
            db, ActionContext("Cowboy", "orders-test", "user")
        )
        new_id = service.create_order(
            supplier="Test Supplier", description="Test order",
            expected_quantity=2, unit_label="rolls",
        )
        service.transition_order(new_id, "shipped")
        service.transition_order(new_id, "delivered")
        db.commit()
        self.assertEqual(
            db.execute("SELECT state FROM orders WHERE id=?", (new_id,)).fetchone()[0],
            "delivered",
        )
        with self.assertRaises(InventoryActionError):
            service.transition_order(new_id, "ordered")
        db.close()

    def test_03_pending_order_appears_on_dashboard_and_orders_page(self):
        dashboard = self.app.response("/")[2].decode()
        orders = self.app.response("/orders")[2].decode()
        for page in (dashboard, orders):
            self.assertIn("White filament bulk refill box", page)
            self.assertIn("Overture", page)
        self.assertIn("Expected stock is not physical inventory", dashboard)

    def test_04_receiving_preview_performs_zero_writes(self):
        before = (
            self.scalar("SELECT COUNT(*) FROM inventory_instances"),
            self.scalar("SELECT COUNT(*) FROM receiving_batches"),
            self.scalar("SELECT COUNT(*) FROM inventory_actions"),
        )
        review = self.app.order_receiving.review(self.form())
        self.assertEqual(len(review.values["permanent_ids"]), 4)
        self.assertEqual(before, (
            self.scalar("SELECT COUNT(*) FROM inventory_instances"),
            self.scalar("SELECT COUNT(*) FROM receiving_batches"),
            self.scalar("SELECT COUNT(*) FROM inventory_actions"),
        ))

    def test_05_exact_quantity_creates_four_individual_overture_instances(self):
        result = self.app.order_receiving.commit(
            self.app.order_receiving.review(self.form()).token
        )
        self.assertEqual(len(result["instance_ids"]), 4)
        self.assertEqual(result["state"], "received")
        self.assertEqual(
            self.scalar(
                """SELECT COUNT(*) FROM inventory_instances ii JOIN catalog_items ci
                ON ci.id=ii.catalog_item_id JOIN manufacturers m ON m.id=ci.manufacturer_id
                WHERE m.name='Overture' AND ci.variant='White'"""
            ), 4,
        )
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM order_received_instances WHERE order_id=?",
                        (self.order_id,)), 4,
        )

    def test_06_partial_receipt_keeps_order_delivered_and_remaining_open(self):
        result = self.app.order_receiving.commit(
            self.app.order_receiving.review(self.form("2")).token
        )
        self.assertEqual((result["state"], result["remaining_quantity"]), ("delivered", 2))
        order = self.row("SELECT state,received_quantity FROM orders WHERE id=?", (self.order_id,))
        self.assertEqual((order["state"], order["received_quantity"]), ("delivered", 2))

    def test_07_two_partial_batches_complete_the_order(self):
        first = self.app.order_receiving.commit(
            self.app.order_receiving.review(self.form("2")).token
        )
        second = self.app.order_receiving.commit(
            self.app.order_receiving.review(self.form("2")).token
        )
        self.assertNotEqual(first["batch_id"], second["batch_id"])
        self.assertEqual(second["state"], "received")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM receiving_batches"), 2)

    def test_08_receipt_is_atomic_when_instance_linkage_fails(self):
        db = connect(self.database)
        db.execute(
            """CREATE TRIGGER fail_order_link BEFORE INSERT ON order_received_instances
            BEGIN SELECT RAISE(ABORT,'simulated linkage failure'); END"""
        )
        db.commit()
        db.close()
        review = self.app.order_receiving.review(self.form())
        with self.assertRaises(OrderReceiptError):
            self.app.order_receiving.commit(review.token)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM receiving_batches"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM order_received_instances"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM inventory_instances"), 30)

    def test_09_receiving_batch_and_linkage_are_immutable(self):
        result = self.app.order_receiving.commit(
            self.app.order_receiving.review(self.form()).token
        )
        db = connect(self.database)
        with self.assertRaises(Exception):
            db.execute("UPDATE receiving_batches SET note='changed' WHERE id=?",
                       (result["batch_id"],))
        db.rollback()
        with self.assertRaises(Exception):
            db.execute("DELETE FROM order_received_instances WHERE receiving_batch_id=?",
                       (result["batch_id"],))
        db.close()

    def test_10_receipt_preview_replay_is_rejected(self):
        review = self.app.order_receiving.review(self.form())
        self.app.order_receiving.commit(review.token)
        with self.assertRaises(OrderReceiptError):
            self.app.order_receiving.commit(review.token)

    def test_11_printer_foundation_renders_stale_manual_status(self):
        page = self.app.response("/")[2].decode()
        for text in ("THS Printer", "Bambu Lab P1S", "Offline",
                     "Stale", "Manual", "TweetyFixed", "No live job asserted"):
            self.assertIn(text, page)

    def test_12_printer_warning_and_error_render_on_dashboard(self):
        db = connect(self.database)
        service = InventoryActionService(
            db, ActionContext("Cowboy", "printer-status-test", "user")
        )
        printer_id = db.execute("SELECT id FROM printers").fetchone()[0]
        service.update_printer_status(
            printer_id, status="error", source="manual",
            warning_message="Nozzle inspection required",
        )
        db.commit()
        db.close()
        page = self.app.response("/")[2].decode()
        self.assertIn("Nozzle inspection required", page)
        self.assertIn("reports an Error state", page)

    def test_13_recent_activity_shows_useful_immutable_actions(self):
        self.app.order_receiving.commit(
            self.app.order_receiving.review(self.form("1")).token
        )
        page = self.app.response("/")[2].decode()
        self.assertIn("Order receipt committed", page)
        self.assertIn("Physical spool received", page)
        self.assertLessEqual(page.count("<li><div><strong>"), 6)

    def test_14_receipt_pages_and_responsive_contract_exist(self):
        orders = self.app.response("/orders")[2].decode()
        form = self.app.response(f"/orders/{self.order_id}/receive")[2].decode()
        css = self.app.response("/static/style.css")[2].decode()
        self.assertIn("Review receipt", orders)
        self.assertIn("I physically verified", form)
        self.assertIn("@media (max-width: 42rem)", css)
        self.assertIn(".dashboard-slots { grid-template-columns: 1fr; }", css)

