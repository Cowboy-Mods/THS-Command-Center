import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from inventory.db import connect, migrate
from inventory.equipment import EquipmentError, EquipmentRegistryService
from inventory.queries import InventoryQueries


class EquipmentRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "inventory.sqlite3"
        db = connect(self.database)
        self.applied = migrate(db)
        self.manufacturer_id = db.execute(
            "SELECT id FROM manufacturers WHERE name='Bambu Lab'"
        ).fetchone()[0]
        self.location_id = db.execute(
            "SELECT id FROM locations ORDER BY id LIMIT 1"
        ).fetchone()[0]
        db.close()
        self.service = EquipmentRegistryService(
            self.database, secret=b"equipment-registry-test-secret"
        )

    def tearDown(self):
        self.temp.cleanup()

    def scalar(self, sql, params=()):
        db = connect(self.database)
        try:
            return db.execute(sql, params).fetchone()[0]
        finally:
            db.close()

    def form(self, name="Test Printer", **changes):
        values = {
            "actor": "Cowboy",
            "reason": "Verified equipment onboarding test.",
            "display_name": name,
            "type_code": "printer",
            "subtype_code": "fdm_printer",
            "manufacturer_id": str(self.manufacturer_id),
            "model": "Test Model",
            "manufacturer_serial_number": "MFG-TEST-001",
            "ths_asset_identifier": "THS-ASSET-TEST-001",
            "current_location_id": str(self.location_id),
            "lifecycle_state": "registered",
            "operational_status": "unknown",
            "notes": "Temporary test equipment only.",
            "capabilities": [
                {"capability_code": "camera.builtin"},
                {"capability_code": "camera.timelapse"},
                {"capability_code": "telemetry.device_status"},
                {"capability_code": "integration.manufacturer_local"},
            ],
        }
        values.update(changes)
        return values

    def register(self, name, **changes):
        review = self.service.review_register(self.form(name, **changes))
        return self.service.commit_register(review["token"], confirmed=True)

    def relationship_form(self, child_id, parent_id=None, action="attach", **changes):
        values = {
            "actor": "Cowboy",
            "reason": "Verified physical relationship.",
            "action": action,
            "child_equipment_id": str(child_id),
            "parent_equipment_id": str(parent_id or ""),
            "relationship_type": "attached_to",
            "effective_at": "2026-07-27T18:00:00-04:00",
        }
        values.update(changes)
        return values

    def test_01_migration_is_additive_and_seeds_no_equipment_or_telemetry(self):
        self.assertIn("018_equipment_registry_v1.sql", self.applied)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM equipment_registry"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM equipment_telemetry_state"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM equipment_types"), 7)
        self.assertGreaterEqual(self.scalar("SELECT COUNT(*) FROM equipment_subtypes"), 9)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM equipment"), 2)

    def test_02_registration_preview_is_zero_write_and_identity_is_permanent(self):
        review = self.service.review_register(self.form())
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM equipment_registry"), 0)
        self.assertEqual(review["values"]["equipment_number"], "THS-EQP-000001")
        result = self.service.commit_register(review["token"], confirmed=True)
        self.assertEqual(result["equipment_number"], "THS-EQP-000001")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM equipment_history"), 1)
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM audit_events WHERE module='equipment-registry'"),
            1,
        )
        db = connect(self.database)
        with self.assertRaisesRegex(Exception, "identity is permanent"):
            db.execute(
                "UPDATE equipment_registry SET equipment_number='THS-EQP-999999' WHERE id=?",
                (result["id"],),
            )
        db.close()

    def test_03_builtin_camera_is_embedded_not_independent_equipment(self):
        result = self.register("Camera-capable Printer")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM equipment_registry"), 1)
        self.assertEqual(
            self.scalar(
                """SELECT COUNT(*) FROM equipment_component_installations
                WHERE host_equipment_id=? AND component_role='built_in_camera'
                AND embedded=1 AND independently_tracked=0""", (result["id"],)
            ),
            1,
        )
        self.assertEqual(
            self.scalar(
                """SELECT COUNT(*) FROM equipment_capabilities ec
                JOIN equipment_capability_types ect ON ect.id=ec.capability_type_id
                WHERE ec.equipment_id=? AND ect.capability_code='camera.builtin'""",
                (result["id"],),
            ),
            1,
        )

    def test_04_external_camera_is_an_independent_equipment_record(self):
        printer = self.register("Printer Without Extra Identity")
        camera = self.register(
            "External Printer Camera",
            type_code="camera",
            subtype_code="printer_monitoring_camera",
            manufacturer_serial_number="CAM-001",
            ths_asset_identifier="THS-CAM-001",
            capabilities=[],
        )
        self.assertNotEqual(printer["equipment_uuid"], camera["equipment_uuid"])
        self.assertEqual(camera["equipment_number"], "THS-EQP-000002")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM equipment_registry"), 2)

    def test_05_builtin_camera_rejected_for_non_printer(self):
        with self.assertRaisesRegex(EquipmentError, "belongs to a printer"):
            self.service.review_register(self.form(
                "Invalid Camera Host", type_code="camera",
                subtype_code="room_overview_camera"
            ))

    def test_06_confirmation_tamper_replay_duplicate_and_sequence_are_rejected(self):
        review = self.service.review_register(self.form())
        with self.assertRaisesRegex(EquipmentError, "signature"):
            self.service.commit_register(review["token"] + "x", confirmed=True)
        with self.assertRaisesRegex(EquipmentError, "confirmation"):
            self.service.commit_register(review["token"], confirmed=False)
        result = self.service.commit_register(review["token"], confirmed=True)
        with self.assertRaisesRegex(EquipmentError, "already used"):
            self.service.commit_register(review["token"], confirmed=True)
        with self.assertRaisesRegex(EquipmentError, "already registered"):
            self.service.review_register(self.form())
        stale = self.service.review_register(self.form(
            "Sequence Candidate",
            manufacturer_serial_number="MFG-002",
            ths_asset_identifier="THS-ASSET-002",
        ))
        self.register(
            "Sequence Competitor",
            manufacturer_serial_number="MFG-003",
            ths_asset_identifier="THS-ASSET-003",
        )
        with self.assertRaisesRegex(EquipmentError, "sequence changed"):
            self.service.commit_register(stale["token"], confirmed=True)
        self.assertEqual(result["equipment_number"], "THS-EQP-000001")

    def test_07_expired_preview_is_rejected(self):
        review = self.service.review_register(self.form())
        body, signature = review["token"].split(".")
        values = json.loads(self.service._unb64(body))
        values["reviewed_at"] = int(time.time()) - self.service.MAX_REVIEW_AGE_SECONDS - 1
        expired = self.service._sign(values)
        with self.assertRaisesRegex(EquipmentError, "expired"):
            self.service.commit_register(expired, confirmed=True)

    def test_08_parent_move_preserves_immutable_history(self):
        first_parent = self.register(
            "Parent One", manufacturer_serial_number="PARENT-1",
            ths_asset_identifier="ASSET-PARENT-1", capabilities=[]
        )
        second_parent = self.register(
            "Parent Two", manufacturer_serial_number="PARENT-2",
            ths_asset_identifier="ASSET-PARENT-2", capabilities=[]
        )
        child = self.register(
            "Movable Child", manufacturer_serial_number="CHILD-1",
            ths_asset_identifier="ASSET-CHILD-1", capabilities=[]
        )
        attach = self.service.review_relationship(
            self.relationship_form(child["id"], first_parent["id"])
        )
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM equipment_relationship_state"), 0)
        self.service.commit_relationship(attach["token"], confirmed=True)
        move = self.service.review_relationship(
            self.relationship_form(
                child["id"], second_parent["id"], action="move",
                effective_at="2026-07-27T19:00:00-04:00",
            )
        )
        self.service.commit_relationship(move["token"], confirmed=True)
        self.assertEqual(
            self.scalar(
                "SELECT parent_equipment_id FROM equipment_relationship_state WHERE child_equipment_id=?",
                (child["id"],),
            ),
            second_parent["id"],
        )
        self.assertEqual(
            self.scalar(
                "SELECT COUNT(*) FROM equipment_relationship_history WHERE child_equipment_id=?",
                (child["id"],),
            ),
            2,
        )
        db = connect(self.database)
        with self.assertRaisesRegex(Exception, "history is immutable"):
            db.execute("DELETE FROM equipment_relationship_history")
        db.close()

    def test_09_relationship_cycles_and_stale_previews_are_rejected(self):
        parent = self.register(
            "Cycle Parent", manufacturer_serial_number="CP-1",
            ths_asset_identifier="CPA-1", capabilities=[]
        )
        child = self.register(
            "Cycle Child", manufacturer_serial_number="CC-1",
            ths_asset_identifier="CCA-1", capabilities=[]
        )
        grandchild = self.register(
            "Cycle Grandchild", manufacturer_serial_number="CG-1",
            ths_asset_identifier="CGA-1", capabilities=[]
        )
        self.service.commit_relationship(
            self.service.review_relationship(
                self.relationship_form(child["id"], parent["id"])
            )["token"], confirmed=True
        )
        stale = self.service.review_relationship(
            self.relationship_form(grandchild["id"], child["id"])
        )
        self.service.commit_relationship(stale["token"], confirmed=True)
        with self.assertRaisesRegex(EquipmentError, "cycle"):
            self.service.review_relationship(
                self.relationship_form(parent["id"], grandchild["id"])
            )
        detach = self.service.review_relationship(
            self.relationship_form(grandchild["id"], action="detach")
        )
        second_detach = self.service.review_relationship(
            self.relationship_form(grandchild["id"], action="detach")
        )
        self.service.commit_relationship(detach["token"], confirmed=True)
        with self.assertRaisesRegex(EquipmentError, "changed after preview"):
            self.service.commit_relationship(second_detach["token"], confirmed=True)

    def test_10_purchase_and_receipt_links_are_inert_provenance(self):
        equipment = self.register("Provenance Test")
        db = connect(self.database)
        try:
            vendor_id = db.execute(
                """INSERT INTO purchase_vendors(
                vendor_uuid,vendor_code,name)
                VALUES (?,?,?)""",
                (str(uuid.uuid4()), "TEST-EQP", "Equipment Test Vendor"),
            ).lastrowid
            purchase_id = db.execute(
                """INSERT INTO purchase_orders(
                purchase_uuid,purchase_number,vendor_id,status,purchase_date,
                subtotal_cents,total_cents,created_by)
                VALUES (?,? ,?,'ordered','2026-07-27',100,100,'Cowboy')""",
                (str(uuid.uuid4()), "THS-PO-999999", vendor_id),
            ).lastrowid
            category_id = db.execute(
                "SELECT id FROM purchase_categories ORDER BY id LIMIT 1"
            ).fetchone()[0]
            line_id = db.execute(
                """INSERT INTO purchase_order_lines(
                line_uuid,purchase_order_id,line_number,category_id,description,
                quantity_ordered,unit_label,unit_price_cents,line_total_cents,
                inventory_tracking_intent)
                VALUES (?,?,1,?,'Test equipment','1','each',100,100,'non_inventory')""",
                (str(uuid.uuid4()), purchase_id, category_id),
            ).lastrowid
            before = dict(db.execute(
                """SELECT lifecycle_state,operational_status,state_version
                FROM equipment_registry WHERE id=?""", (equipment["id"],)
            ).fetchone())
            db.execute(
                """INSERT INTO equipment_purchase_links(
                link_uuid,equipment_id,purchase_order_id,purchase_order_line_id,
                relationship_type,linked_by,note) VALUES (?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), equipment["id"], purchase_id, line_id,
                    "purchased_for", "Cowboy", "Provenance only.",
                ),
            )
            db.commit()
            after = dict(db.execute(
                """SELECT lifecycle_state,operational_status,state_version
                FROM equipment_registry WHERE id=?""", (equipment["id"],)
            ).fetchone())
            current_purchase = dict(db.execute(
                "SELECT status FROM purchase_orders WHERE id=?", (purchase_id,)
            ).fetchone())
        finally:
            db.close()
        self.assertEqual(before, after)
        self.assertEqual(current_purchase["status"], "ordered")

    def test_11_operational_readiness_restriction_and_telemetry_are_separate(self):
        equipment = self.register("Separation Test")
        db = connect(self.database)
        assignments_before = db.execute("SELECT COUNT(*) FROM ams_assignments").fetchone()[0]
        readiness = db.execute(
            "SELECT * FROM equipment_registry_readiness WHERE equipment_id=?",
            (equipment["id"],),
        ).fetchone()
        self.assertIsNone(readiness["readiness_state"])
        db.execute(
            """INSERT INTO equipment_telemetry_state(
            equipment_id,integration_type,received_at,expires_at,online_state,
            print_status,current_job,progress_percent,camera_stream_available)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                equipment["id"], "test-adapter", "2026-07-27 18:00:00",
                "2026-07-27 18:01:00", "online", "printing", "Test Job", 50, 1,
            ),
        )
        db.commit()
        stable = dict(db.execute(
            "SELECT operational_status,lifecycle_state FROM equipment_registry WHERE id=?",
            (equipment["id"],),
        ).fetchone())
        db.close()
        self.assertEqual(stable, {
            "operational_status": "unknown", "lifecycle_state": "registered"
        })
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM ams_assignments"), assignments_before
        )

    def test_12_read_only_projections_return_equipment_relationships_and_connections(self):
        parent = self.register(
            "Projection Parent", manufacturer_serial_number="PP-1",
            ths_asset_identifier="PPA-1", capabilities=[]
        )
        child = self.register(
            "Projection Child", manufacturer_serial_number="PC-1",
            ths_asset_identifier="PCA-1", capabilities=[]
        )
        self.service.commit_relationship(
            self.service.review_relationship(
                self.relationship_form(child["id"], parent["id"])
            )["token"], confirmed=True
        )
        before = self.database.read_bytes()
        queries = InventoryQueries(self.database)
        self.assertEqual(len(queries.equipment_list()), 2)
        detail = queries.equipment_detail(parent["id"])
        self.assertEqual(detail["equipment_number"], parent["equipment_number"])
        self.assertEqual(len(detail["children"]), 1)
        self.assertEqual(len(queries.equipment_relationships()), 1)
        self.assertEqual(queries.equipment_connections(), [])
        self.assertEqual(before, self.database.read_bytes())

    def test_13_credentials_are_rejected_from_capability_metadata(self):
        bad = self.form(capabilities=[{
            "capability_code": "integration.manufacturer_local",
            "configuration_metadata": {"password": "do-not-store"},
        }])
        with self.assertRaisesRegex(EquipmentError, "credentials"):
            self.service.review_register(bad)

    def test_14_manufacturer_serial_is_not_the_equipment_identity(self):
        first = self.register("Identity One")
        second = self.register(
            "Identity Two",
            manufacturer_id="",
            manufacturer_serial_number="MFG-TEST-001",
            ths_asset_identifier="THS-ASSET-TEST-002",
            capabilities=[],
        )
        self.assertNotEqual(first["equipment_uuid"], second["equipment_uuid"])
        self.assertNotEqual(first["equipment_number"], second["equipment_number"])


if __name__ == "__main__":
    unittest.main()
