import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from inventory.ams_onboarding import AMSOnboardingError, AMSOnboardingService
from inventory.db import connect, migrate
from inventory.equipment import EquipmentRegistryService
from scripts.rehearse_ams_onboarding import rehearse


class AMSOnboardingServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.baseline = self.root / "baseline.sqlite3"
        self._build_production_like_fixture(self.baseline)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def sha256(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()

    def copy(self, name):
        target = self.root / name
        shutil.copy2(self.baseline, target)
        return target

    @staticmethod
    def _build_production_like_fixture(path):
        db = connect(path)
        migrate(db)
        manufacturer_id = db.execute(
            "SELECT id FROM manufacturers WHERE name='Bambu Lab'"
        ).fetchone()[0]
        db.close()
        registry = EquipmentRegistryService(path, secret=b"ams-atomic-fixture")
        review = registry.review_register(
            {
                "actor": "Cowboy",
                "reason": "Production-like atomic onboarding fixture.",
                "display_name": "Bambu Lab P1S",
                "type_code": "printer",
                "subtype_code": "fdm_printer",
                "manufacturer_id": str(manufacturer_id),
                "model": "P1S",
                "lifecycle_state": "installed",
                "operational_status": "operating",
                "notes": "Temporary test fixture.",
                "capabilities": [],
            }
        )
        registry.commit_register(review["token"], confirmed=True)
        db = connect(path)
        try:
            filament_type = db.execute(
                "SELECT id,default_unit_id FROM item_types WHERE name='Filament'"
            ).fetchone()
            assignments = AMSOnboardingService.EXPECTED_ASSIGNMENTS
            for index, ((equipment_name, slot_number), (permanent_id, color)) in enumerate(
                assignments.items(), start=1
            ):
                catalog_id = db.execute(
                    """INSERT INTO catalog_items(
                    item_type_id,manufacturer_id,name,product_line,variant,base_unit_id)
                    VALUES (?,?,?,'PLA Basic',?,?)""",
                    (
                        filament_type["id"],
                        manufacturer_id,
                        f"Atomic Fixture {index}",
                        color,
                        filament_type["default_unit_id"],
                    ),
                ).lastrowid
                existing = db.execute(
                    "SELECT id FROM inventory_instances WHERE permanent_id=?",
                    (permanent_id,),
                ).fetchone()
                slot = db.execute(
                    """SELECT es.id,es.location_id FROM equipment_slots es
                    JOIN equipment e ON e.id=es.equipment_id
                    WHERE e.name=? AND es.slot_number=?""",
                    (equipment_name, slot_number),
                ).fetchone()
                if existing:
                    instance_id = existing["id"]
                    db.execute(
                        """UPDATE inventory_instances SET catalog_item_id=?,state='loaded',
                        condition='open',location_id=?,remaining_quantity=500,
                        original_quantity=1000,unit_id=? WHERE id=?""",
                        (
                            catalog_id,
                            slot["location_id"],
                            filament_type["default_unit_id"],
                            instance_id,
                        ),
                    )
                else:
                    instance_id = db.execute(
                        """INSERT INTO inventory_instances(
                        permanent_id,catalog_item_id,state,condition,location_id,
                        original_quantity,remaining_quantity,unit_id,verified)
                        VALUES (?,?,'loaded','open',?,1000,500,?,1)""",
                        (
                            permanent_id,
                            catalog_id,
                            slot["location_id"],
                            filament_type["default_unit_id"],
                        ),
                    ).lastrowid
                transaction_id = db.execute(
                    """INSERT INTO inventory_transactions(
                    transaction_type,reason,origin,actor)
                    VALUES ('load','Production-like fixture','system','Fixture')"""
                ).lastrowid
                db.execute(
                    """INSERT INTO transaction_lines(
                    transaction_id,catalog_item_id,instance_id,quantity_change,
                    unit_id,destination_location_id)
                    VALUES (?,?,?,0,?,?)""",
                    (
                        transaction_id,
                        catalog_id,
                        instance_id,
                        filament_type["default_unit_id"],
                        slot["location_id"],
                    ),
                )
                db.execute(
                    """INSERT INTO ams_assignments(
                    slot_id,instance_id,load_transaction_id)
                    VALUES (?,?,?)""",
                    (slot["id"], instance_id, transaction_id),
                )
            db.commit()
        finally:
            db.close()

    def test_01_dry_run_is_zero_write_and_exact_29_2_0(self):
        path = self.copy("dry-run.sqlite3")
        before = self.sha256(path)
        result = AMSOnboardingService(path).preview()
        self.assertEqual(before, self.sha256(path))
        self.assertTrue(result["database_unchanged"])
        self.assertTrue(result["production_ready"])
        self.assertEqual(
            (result["insert_count"], result["update_count"], result["delete_count"]),
            (29, 2, 0),
        )
        self.assertEqual(result["slot_count"], 8)
        self.assertEqual(result["active_assignment_count"], 7)
        self.assertTrue(result["a2_empty"])
        self.assertIsNone(result["part"]["location_id"])

    def test_02_commit_returns_complete_exact_structured_result(self):
        path = self.copy("commit.sqlite3")
        service = AMSOnboardingService(path)
        result = service.commit(confirmation=service.CONFIRMATION_PHRASE)
        self.assertEqual(
            (result["insert_count"], result["update_count"], result["delete_count"]),
            (29, 2, 0),
        )
        self.assertEqual(len(result["inserted"]), 29)
        self.assertEqual(len(result["updated"]), 2)
        self.assertEqual(
            {(row["table"], row["row_id"]) for row in result["updated"]},
            {("equipment_registry", 1), ("maintenance_assets", 2)},
        )
        self.assertEqual(
            {row["table"] for row in result["inserted"]},
            {
                "equipment_registry",
                "equipment_history",
                "audit_events",
                "equipment_relationship_state",
                "equipment_relationship_history",
                "equipment_legacy_container_links",
                "equipment_maintenance_asset_links",
                "maintenance_records",
                "maintenance_history",
                "item_types",
                "catalog_items",
                "inventory_instances",
                "inventory_transactions",
                "transaction_lines",
            },
        )

    def test_03_every_one_of_31_write_stages_rolls_back_to_original_checksum(self):
        original = self.sha256(self.baseline)
        for stage in range(1, 32):
            with self.subTest(stage=stage):
                path = self.copy(f"rollback-{stage:02d}.sqlite3")
                service = AMSOnboardingService(path)
                with self.assertRaisesRegex(
                    AMSOnboardingError, f"injected rollback after write {stage}"
                ):
                    service.commit(
                        confirmation=service.CONFIRMATION_PHRASE,
                        _fail_after_write=stage,
                    )
                self.assertEqual(self.sha256(path), original)
                preview = service.preview()
                self.assertEqual(preview["insert_count"], 29)

    def test_04_replay_is_rejected_without_additional_writes(self):
        path = self.copy("replay.sqlite3")
        service = AMSOnboardingService(path)
        service.commit(confirmation=service.CONFIRMATION_PHRASE)
        committed_hash = self.sha256(path)
        with self.assertRaisesRegex(
            AMSOnboardingError, "stale|already exist|replay"
        ):
            service.commit(confirmation=service.CONFIRMATION_PHRASE)
        self.assertEqual(self.sha256(path), committed_hash)

    def test_04b_postcondition_failure_rolls_back_complete_transaction(self):
        path = self.copy("postcondition-rollback.sqlite3")
        before = self.sha256(path)
        service = AMSOnboardingService(path)
        with self.assertRaisesRegex(
            AMSOnboardingError, "injected postcondition failure"
        ):
            service.commit(
                confirmation=service.CONFIRMATION_PHRASE,
                _fail_postcondition=True,
            )
        self.assertEqual(self.sha256(path), before)
        self.assertEqual(service.preview()["insert_count"], 29)

    def test_05_stale_update_preconditions_are_rejected_without_service_writes(self):
        mutations = (
            (
                "parent",
                "UPDATE equipment_registry SET manufacturer_serial_number='STALE' WHERE id=1",
                "P1S update precondition is stale",
            ),
            (
                "maintenance",
                """UPDATE maintenance_assets SET readiness_state='out_of_service'
                WHERE id=2""",
                "maintenance update precondition is stale",
            ),
        )
        for name, sql, message in mutations:
            with self.subTest(name=name):
                path = self.copy(f"stale-{name}.sqlite3")
                db = connect(path)
                db.execute(sql)
                db.commit()
                db.close()
                before = self.sha256(path)
                with self.assertRaisesRegex(AMSOnboardingError, message):
                    AMSOnboardingService(path).commit(
                        confirmation=AMSOnboardingService.CONFIRMATION_PHRASE
                    )
                self.assertEqual(self.sha256(path), before)

    def test_06_duplicate_identity_guards_reject_without_service_writes(self):
        mutators = {
            "equipment_id": lambda db: db.execute(
                """INSERT INTO equipment_registry(
                equipment_uuid,equipment_number,display_name,equipment_type_id,
                equipment_subtype_id,manufacturer_id,model,manufacturer_serial_number,
                lifecycle_state,operational_status,created_by)
                SELECT 'duplicate-equipment','THS-EQP-000002','Duplicate AMS',
                equipment_type_id,equipment_subtype_id,manufacturer_id,'Other','OTHER',
                'installed','unknown','Fixture' FROM equipment_registry WHERE id=1"""
            ),
            "serial": lambda db: db.execute(
                """INSERT INTO equipment_registry(
                equipment_uuid,equipment_number,display_name,equipment_type_id,
                equipment_subtype_id,manufacturer_id,model,manufacturer_serial_number,
                lifecycle_state,operational_status,created_by)
                SELECT 'duplicate-serial','THS-EQP-999999','Duplicate Serial',
                (SELECT id FROM equipment_types WHERE type_code='ams_unit'),
                (SELECT id FROM equipment_subtypes WHERE subtype_code='bambu_ams'),
                manufacturer_id,'AMS 2 Pro','19C06A522002297',
                'installed','unknown','Fixture' FROM equipment_registry WHERE id=1"""
            ),
            "part_id": lambda db: db.execute(
                """INSERT INTO inventory_instances(
                permanent_id,catalog_item_id,state,condition,original_quantity,
                remaining_quantity,unit_id,verified)
                SELECT 'THS-PART-000001',catalog_item_id,'sealed','new',1,1,unit_id,1
                FROM inventory_instances ORDER BY id LIMIT 1"""
            ),
            "model_upc": lambda db: db.execute(
                """INSERT INTO catalog_items(
                item_type_id,manufacturer_id,name,product_line,variant,
                manufacturer_sku,base_unit_id,notes)
                SELECT item_type_id,manufacturer_id,'Existing Feeder','AMS 2 Pro',
                'SA403-V1','SA403-V1',base_unit_id,'UPC 6937285503237'
                FROM catalog_items ORDER BY id LIMIT 1"""
            ),
            "maintenance": lambda db: db.execute(
                """INSERT INTO maintenance_records(
                event_number,asset_id,event_type,status,severity,discovered_at,
                symptoms,unattended_printing_allowed,created_by)
                VALUES ('THS-MNT-000002',2,'fault_discovered','pending','high',
                CURRENT_TIMESTAMP,'Duplicate',1,'Fixture')"""
            ),
            "relationship": lambda db: (
                db.execute(
                    """INSERT INTO equipment_registry(
                    equipment_uuid,equipment_number,display_name,equipment_type_id,
                    equipment_subtype_id,manufacturer_id,model,
                    manufacturer_serial_number,lifecycle_state,operational_status,
                    created_by)
                    VALUES ('relationship-child','THS-EQP-000002',
                    'Bambu Lab AMS 2 Pro - AMS 1',
                    (SELECT id FROM equipment_types WHERE type_code='ams_unit'),
                    (SELECT id FROM equipment_subtypes WHERE subtype_code='bambu_ams'),
                    (SELECT id FROM manufacturers WHERE name='Bambu Lab'),
                    'AMS 2 Pro','19C06A522002297','installed','degraded','Fixture')"""
                ),
                db.execute(
                    """INSERT INTO equipment_relationship_state(
                    child_equipment_id,parent_equipment_id,relationship_type,
                    state_version,effective_at)
                    VALUES ((SELECT id FROM equipment_registry
                    WHERE equipment_number='THS-EQP-000002'),1,'attached_to',1,
                    CURRENT_TIMESTAMP)"""
                ),
            ),
            "legacy_bridge": lambda db: db.execute(
                """INSERT INTO equipment_legacy_container_links(
                equipment_id,legacy_equipment_id,linked_by)
                VALUES (1,1,'Fixture')"""
            ),
        }
        for name, mutate in mutators.items():
            with self.subTest(name=name):
                path = self.copy(f"duplicate-{name}.sqlite3")
                db = connect(path)
                mutate(db)
                db.commit()
                db.close()
                before = self.sha256(path)
                with self.assertRaises(AMSOnboardingError):
                    AMSOnboardingService(path).commit(
                        confirmation=AMSOnboardingService.CONFIRMATION_PHRASE
                    )
                self.assertEqual(self.sha256(path), before)

    def test_07_slots_assignments_and_existing_inventory_are_byte_for_byte_preserved(self):
        path = self.copy("protected.sqlite3")
        db = connect(path)
        before_slots = [
            tuple(row) for row in db.execute("SELECT * FROM equipment_slots ORDER BY id")
        ]
        before_assignments = [
            tuple(row) for row in db.execute("SELECT * FROM ams_assignments ORDER BY id")
        ]
        before_instances = {
            row["permanent_id"]: tuple(row)
            for row in db.execute("SELECT * FROM inventory_instances ORDER BY id")
        }
        db.close()
        service = AMSOnboardingService(path)
        service.commit(confirmation=service.CONFIRMATION_PHRASE)
        db = connect(path)
        self.assertEqual(
            before_slots,
            [tuple(row) for row in db.execute("SELECT * FROM equipment_slots ORDER BY id")],
        )
        self.assertEqual(
            before_assignments,
            [tuple(row) for row in db.execute("SELECT * FROM ams_assignments ORDER BY id")],
        )
        after_existing = {
            row["permanent_id"]: tuple(row)
            for row in db.execute(
                "SELECT * FROM inventory_instances WHERE permanent_id<>? ORDER BY id",
                (service.PART_NUMBER,),
            )
        }
        self.assertEqual(before_instances, after_existing)
        a2 = db.execute(
            """SELECT aa.id FROM equipment_slots es
            JOIN equipment e ON e.id=es.equipment_id
            LEFT JOIN ams_assignments aa
              ON aa.slot_id=es.id AND aa.unloaded_at IS NULL
            WHERE e.name='AMS 1' AND es.slot_number=2"""
        ).fetchone()
        self.assertIsNone(a2["id"])
        db.close()

    def test_08_resulting_equipment_maintenance_part_and_audits_are_exact(self):
        path = self.copy("result.sqlite3")
        service = AMSOnboardingService(path)
        service.commit(confirmation=service.CONFIRMATION_PHRASE)
        db = connect(path)
        self.assertEqual(
            [
                tuple(row)
                for row in db.execute(
                    """SELECT equipment_number,manufacturer_serial_number,
                    lifecycle_state,operational_status FROM equipment_registry
                    WHERE equipment_number IN ('THS-EQP-000002','THS-EQP-000003')
                    ORDER BY equipment_number"""
                )
            ],
            [
                ("THS-EQP-000002", "19C06A522002297", "installed", "degraded"),
                ("THS-EQP-000003", "19C51A620400EWR", "installed", "operating"),
            ],
        )
        maintenance = db.execute(
            """SELECT mr.event_number,mr.parts_required,mr.parts_used,mr.notes,
            ma.readiness_state FROM maintenance_records mr
            JOIN maintenance_assets ma ON ma.id=mr.asset_id
            WHERE mr.event_number='THS-MNT-000002'"""
        ).fetchone()
        self.assertIn("THS-PART-000001", maintenance["parts_required"])
        self.assertIsNone(maintenance["parts_used"])
        self.assertIn("Slot 2 / A2 is Out of service", maintenance["notes"])
        self.assertIn("Slots 1, 3, and 4 remain usable", maintenance["notes"])
        self.assertEqual(maintenance["readiness_state"], "monitor_during_printing")
        part = db.execute(
            """SELECT ii.state,ii.condition,ii.location_id,ii.original_quantity,
            ii.remaining_quantity,ci.name,ci.variant,ci.manufacturer_sku,ii.notes
            FROM inventory_instances ii JOIN catalog_items ci ON ci.id=ii.catalog_item_id
            WHERE ii.permanent_id='THS-PART-000001'"""
        ).fetchone()
        self.assertEqual(part["state"], "sealed")
        self.assertEqual(part["condition"], "new/boxed")
        self.assertIsNone(part["location_id"])
        self.assertEqual((part["original_quantity"], part["remaining_quantity"]), (1, 1))
        self.assertEqual(part["name"], "Bambu Lab AMS 2 Pro Feeder Unit")
        self.assertEqual((part["variant"], part["manufacturer_sku"]), ("SA403-V1", "SA403-V1"))
        self.assertIn("Not installed, reserved, issued, or consumed", part["notes"])
        audit_actions = [
            row[0]
            for row in db.execute(
                """SELECT event_type FROM audit_events
                WHERE request_nonce LIKE '%-%' ORDER BY id"""
            )
        ]
        for action in (
            "register_equipment",
            "attach_equipment_relationship",
            "link_legacy_equipment_container",
            "update_equipment_facts",
            "create_item_type",
            "create_catalog_item",
            "add_individual_instance",
        ):
            self.assertIn(action, audit_actions)
        db.close()

    def test_09_command_defaults_to_dry_run_and_requires_exact_commit_phrase(self):
        path = self.copy("cli.sqlite3")
        before = self.sha256(path)
        dry = subprocess.run(
            [
                sys.executable,
                "-m",
                "inventory.cli",
                "--database",
                str(path),
                "ams-onboard",
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertEqual(json.loads(dry.stdout)["mode"], "dry-run")
        self.assertEqual(before, self.sha256(path))
        rejected = subprocess.run(
            [
                sys.executable,
                "-m",
                "inventory.cli",
                "--database",
                str(path),
                "ams-onboard",
                "--commit",
                "--confirm",
                "WRONG",
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(before, self.sha256(path))
        committed = subprocess.run(
            [
                sys.executable,
                "-m",
                "inventory.cli",
                "--database",
                str(path),
                "ams-onboard",
                "--commit",
                "--confirm",
                AMSOnboardingService.CONFIRMATION_PHRASE,
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(committed.returncode, 0, committed.stderr)
        self.assertEqual(json.loads(committed.stdout)["mode"], "committed")

    def test_10_rehearsal_runner_restores_all_31_candidate_checksums(self):
        result = rehearse(self.baseline)
        self.assertEqual(result["rollback_stage_count"], 31)
        self.assertTrue(result["all_rollback_checksums_restored"])
        self.assertTrue(result["temporary_copies_removed"])
        self.assertEqual(
            (
                result["success"]["insert_count"],
                result["success"]["update_count"],
                result["success"]["delete_count"],
            ),
            (29, 2, 0),
        )
        self.assertEqual(result["success"]["integrity"], "ok")
        self.assertEqual(result["success"]["foreign_key_violations"], 0)


if __name__ == "__main__":
    unittest.main()
