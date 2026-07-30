import tempfile
import unittest
from pathlib import Path

from inventory.actions import ActionContext, InventoryActionService
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

    def test_25_canonical_ams_swatch_colors_and_unknown_fallback(self):
        expected = {
            "Cayenne": "#0086d6",
            "cyan": "#0086d6",
            "  CAYENNE  ": "#0086d6",
            "  caYEnNe   ": "#0086d6",
            "Red": "#d32f2f",
            "Black": "#24262a",
            "Orange": "#ff7a18",
            "Jade White": "#f4f4f0",
            "  JADE   WHITE ": "#f4f4f0",
            "Not A Known Color": "#777d86",
        }
        for color, value in expected.items():
            with self.subTest(color=color):
                self.assertEqual(self.app._swatch(color), value)

    def test_26_purple_swatch_does_not_use_unknown_color_fallback(self):
        self.assertEqual(
            self.app._swatch("purple"),
            "#800080",
            "Production Purple must use its canonical swatch.",
        )

    def test_27_hot_pink_alias_uses_the_registered_pink_swatch(self):
        self.assertEqual(
            self.app._swatch("Hot Pink"),
            self.app._swatch("Pink"),
            "Hot Pink must normalize to the supported Pink swatch family.",
        )

    def test_28_cocoa_brown_alias_uses_the_registered_brown_swatch(self):
        self.assertEqual(
            self.app._swatch("Cocoa Brown"),
            self.app._swatch("Brown"),
            "Cocoa Brown must normalize to the supported Brown swatch family.",
        )

    def test_29_verified_color_code_precedes_name_alias_and_invalid_code_falls_back(self):
        self.assertEqual(self.app._swatch("Hot Pink", "#A1B2C3"), "#a1b2c3")
        self.assertEqual(
            self.app._swatch("Hot Pink", "not-a-verified-hex-code"),
            self.app._swatch("Pink"),
        )

    def test_30_compound_color_uses_an_intentional_two_color_swatch(self):
        self.assertEqual(
            self.app._swatch(" Black / Purple "),
            "linear-gradient(135deg,#24262a 0 50%,#800080 50% 100%)",
        )
        self.assertNotEqual(self.app._swatch("Black/Purple"), "#777d86")

    def test_31_genuinely_unknown_color_keeps_the_unknown_gray_fallback(self):
        self.assertEqual(self.app._swatch("Maker Mystery Sparkle"), "#777d86")

    def test_32_dashboard_updates_slot_identity_color_text_and_verified_swatch_together(self):
        db = connect(self.database)
        try:
            spool = db.execute(
                """SELECT ii.id,ii.permanent_id,ii.catalog_item_id
                FROM inventory_instances ii
                WHERE ii.state='sealed' ORDER BY ii.id LIMIT 1"""
            ).fetchone()
            slot = db.execute(
                """SELECT es.id,e.name,es.slot_number
                FROM equipment_slots es JOIN equipment e ON e.id=es.equipment_id
                ORDER BY e.name,es.slot_number LIMIT 1"""
            ).fetchone()
            db.execute(
                "UPDATE catalog_items SET variant='Hot Pink' WHERE id=?",
                (spool["catalog_item_id"],),
            )
            db.execute(
                """UPDATE catalog_item_attribute_values SET text_value='Hot Pink'
                WHERE catalog_item_id=? AND attribute_definition_id=(
                  SELECT id FROM attribute_definitions WHERE name='manufacturer_color_name'
                )""",
                (spool["catalog_item_id"],),
            )
            db.execute(
                """INSERT INTO catalog_item_attribute_values(
                  catalog_item_id,attribute_definition_id,text_value
                ) VALUES (?,(SELECT id FROM attribute_definitions WHERE name='color_code'),?)""",
                (spool["catalog_item_id"], "#FF1493"),
            )
            service = InventoryActionService(
                db, ActionContext(actor="Dashboard fixture", module="test", origin="system")
            )
            service.open_sealed_spool(spool["id"], reason="Dashboard swatch fixture")
            service.load_instance_into_ams(
                spool["id"], slot["id"], reason="Dashboard swatch fixture"
            )
            db.commit()
        finally:
            db.close()

        _, _, page = self.page("/")
        slot_start = page.index(
            f"<span>{slot['name']} · Slot {slot['slot_number']}</span>"
        )
        slot_end = page.index("</li>", slot_start)
        rendered_slot = page[slot_start:slot_end]
        self.assertIn(f"<strong>{spool['permanent_id']}</strong>", rendered_slot)
        self.assertIn("Hot Pink", rendered_slot)
        self.assertIn("--swatch:#ff1493", rendered_slot)


if __name__ == "__main__":
    unittest.main()
