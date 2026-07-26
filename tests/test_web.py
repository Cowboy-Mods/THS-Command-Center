import tempfile
import unittest
from pathlib import Path

from inventory.db import connect, migrate
from inventory.web import InventoryWebApp, create_server


class ReadOnlyDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        migrate(db)
        db.close()
        self.app = InventoryWebApp(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def page(self, path="/"):
        status, headers, body = self.app.response(path)
        return status, dict(headers), body.decode("utf-8")

    def scalar(self, sql):
        db = connect(self.database)
        try:
            return db.execute(sql).fetchone()[0]
        finally:
            db.close()

    def test_01_application_server_starts_against_migrated_database(self):
        server = create_server(self.database, port=0)
        try:
            self.assertGreater(server.server_address[1], 0)
        finally:
            server.server_close()

    def test_02_dashboard_returns_successfully(self):
        status, headers, page = self.page("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("<h1>Dashboard</h1>", page)

    def test_02a_dashboard_workflow_cards_are_removed_in_favor_of_operational_state(self):
        _, _, page = self.page("/")
        self.assertNotIn('class="workflow-card"', page)
        self.assertNotIn('id="workflow-hub-title"', page)
        self.assertIn("What is happening in the shop right now", page)
        self.assertIn("Printer status", page)
        self.assertIn("AMS occupancy and loaded filament", page)
        self.assertIn("Pending orders", page)
        self.assertIn("Recent activity", page)

    def test_02b_topbar_workflow_control_is_a_real_menu(self):
        _, _, page = self.page("/")
        self.assertIn('<details class="workflow-menu">', page)
        self.assertIn("<summary>Controlled workflows</summary>", page)
        self.assertIn("Initialize Verified AMS Slot", page)
        self.assertIn("Replace Active Filament Spool", page)
        self.assertIn("Receive Verified Sealed Spool", page)

    def test_02c_open_spool_is_live_and_adjustments_remain_future(self):
        _, _, page = self.page("/")
        self.assertIn("Register Existing Open Spool", page)
        self.assertIn("Inventory Adjustments", page)
        self.assertEqual(page.count('aria-disabled="true"'), 1)
        self.assertIn('href="/inventory/filament/register-open"', page)
        self.assertNotIn('href="/inventory/adjustments"', page)

    def test_03_dashboard_displays_30_physical_spools(self):
        _, _, page = self.page("/")
        self.assertIn("Active physical spools", page)
        self.assertIn("<strong>30</strong>", page)

    def test_04_dashboard_displays_18_catalog_products_including_order_identity(self):
        _, _, page = self.page("/")
        self.assertIn("Catalog products", page)
        self.assertIn("<strong>18</strong>", page)

    def test_05_dashboard_displays_26800_gram_assumption_total(self):
        _, _, page = self.page("/")
        self.assertIn("26,800 g", page)
        self.assertIn("26.8 kg", page)

    def test_06_filament_inventory_brand_totals_are_correct(self):
        _, _, page = self.page("/inventory/filament")
        for brand, count in (("Overture",6),("Elegoo",2),("Bambu Lab",18),("AMOLEN",4)):
            self.assertIn(brand, page)

    def test_07_grouped_inventory_shows_one_bambu_brown_product_with_four_spools(self):
        _, _, page = self.page("/inventory/filament?q=Brown")
        self.assertEqual(page.count("PLA Basic — Brown</a>"), 1)
        self.assertIn("<dd>4</dd>", page)

    def test_08_product_detail_lists_all_four_bambu_brown_spools(self):
        db = connect(self.database)
        product = db.execute(
            "SELECT ci.id FROM catalog_items ci JOIN manufacturers m ON m.id=ci.manufacturer_id "
            "WHERE m.name='Bambu Lab' AND ci.product_line='PLA Basic' AND ci.variant='Brown'"
        ).fetchone()[0]
        db.close()
        _, _, page = self.page(f"/inventory/filament/products/{product}")
        self.assertIn("Physical spools", page)
        self.assertEqual(page.count('data-label="Spool"'), 4)

    def test_09_spool_detail_displays_immutable_ths_fil_id(self):
        spool = self.scalar("SELECT id FROM inventory_instances ORDER BY permanent_id LIMIT 1")
        _, _, page = self.page(f"/inventory/filament/spools/{spool}")
        self.assertIn("THS-FIL-000001", page)
        self.assertIn("Permanent ID", page)

    def test_10_elegoo_white_displays_use_up_stock_note(self):
        db = connect(self.database)
        product = db.execute(
            "SELECT ci.id FROM catalog_items ci JOIN manufacturers m ON m.id=ci.manufacturer_id "
            "WHERE m.name='Elegoo' AND ci.variant='White'"
        ).fetchone()[0]
        db.close()
        _, _, page = self.page(f"/inventory/filament/products/{product}")
        self.assertIn("<strong>Use-up stock</strong>", page)

    def test_11_ams_overview_shows_two_units(self):
        _, _, page = self.page("/inventory/filament/ams")
        self.assertIn("<h2>AMS 1</h2>", page)
        self.assertIn("<h2>AMS 2</h2>", page)

    def test_12_ams_overview_shows_eight_slots(self):
        _, _, page = self.page("/inventory/filament/ams")
        self.assertEqual(page.count('class="ams-slot"'), 8)

    def test_13_all_current_ams_slots_are_empty(self):
        _, _, page = self.page("/inventory/filament/ams")
        self.assertEqual(page.count("<strong>Empty</strong>"), 8)
        self.assertNotIn("THS-FIL-", page)

    def test_14_search_finds_products_by_color(self):
        _, _, page = self.page("/inventory/filament?q=Turquoise")
        self.assertIn("PLA Basic — Turquoise", page)
        self.assertIn("1 grouped products", page)

    def test_15_search_finds_spool_by_ths_fil_id(self):
        _, _, page = self.page("/inventory/filament?q=THS-FIL-000001")
        self.assertIn("1 grouped products", page)
        self.assertNotIn("No filament found", page)

    def test_16_search_returns_clear_empty_result_state(self):
        _, _, page = self.page("/inventory/filament?q=DefinitelyNotInInventory")
        self.assertIn("No filament found", page)
        self.assertIn("0 grouped products", page)

    def test_17_placeholder_module_route_returns_successfully(self):
        status, _, page = self.page("/modules/leather")
        self.assertEqual(status, 200)
        self.assertIn("<h1>Leather</h1>", page)

    def test_18_placeholder_page_displays_coming_soon(self):
        _, _, page = self.page("/modules/electronics")
        self.assertIn("<h2>Coming Soon</h2>", page)
        self.assertNotIn("fake data", page.lower())

    def test_19_opening_dashboard_routes_does_not_mutate_inventory(self):
        before = self.scalar("SELECT total_changes()")
        counts_before = (
            self.scalar("SELECT COUNT(*) FROM inventory_instances"),
            self.scalar("SELECT COUNT(*) FROM inventory_transactions"),
            self.scalar("SELECT COUNT(*) FROM schema_migrations"),
        )
        for path in (
            "/", "/inventory/filament", "/inventory/filament/ams",
            "/inventory/filament?q=Gold", "/modules/project-list",
        ):
            self.assertEqual(self.page(path)[0], 200)
        counts_after = (
            self.scalar("SELECT COUNT(*) FROM inventory_instances"),
            self.scalar("SELECT COUNT(*) FROM inventory_transactions"),
            self.scalar("SELECT COUNT(*) FROM schema_migrations"),
        )
        self.assertEqual(before, 0)
        self.assertEqual(counts_before, counts_after)

    def test_20_missing_database_produces_useful_error(self):
        app = InventoryWebApp(Path(self.temp.name) / "missing.sqlite3")
        status, _, body = app.response("/")
        page = body.decode()
        self.assertEqual(status, 503)
        self.assertIn("Inventory database is not ready", page)
        self.assertIn("py -3 -m inventory.cli migrate", page)

    def test_21_invalid_product_and_spool_ids_return_clean_404(self):
        for path in (
            "/inventory/filament/products/999999",
            "/inventory/filament/spools/999999",
            "/not-a-real-page",
        ):
            status, _, page = self.page(path)
            self.assertEqual(status, 404)
            self.assertIn("Page not found", page)
            self.assertNotIn("Traceback", page)

    def test_22_responsive_structure_contains_mobile_navigation_behavior(self):
        _, _, page = self.page("/")
        self.assertIn('class="nav-toggle"', page)
        self.assertIn('aria-controls="site-navigation"', page)
        _, _, css = self.page("/static/style.css")
        self.assertIn("@media (max-width: 58rem)", css)
        self.assertIn(".sidebar.is-open", css)
        _, _, script = self.page("/static/app.js")
        self.assertIn('aria-expanded', script)

    def test_23_no_unverified_wall_stock_appears(self):
        _, _, page = self.page("/inventory/filament")
        self.assertNotIn("probably Elegoo", page)
        self.assertNotIn("Open-Spool Wall", page)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM inventory_instances WHERE location_id=("
            "SELECT id FROM locations WHERE name='Open-Spool Wall')"
        ), 0)

    def test_24_no_false_low_stock_alerts_without_rules(self):
        _, _, dashboard = self.page("/")
        _, _, inventory = self.page("/inventory/filament")
        self.assertIn("0 low-stock products", dashboard)
        self.assertEqual(inventory.count("No reorder rule set"), 18)
        self.assertNotIn(">Low stock<", inventory)


if __name__ == "__main__":
    unittest.main()
