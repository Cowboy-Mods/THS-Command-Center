from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .db import connect


class AMSOnboardingError(ValueError):
    """The controlled AMS onboarding plan is invalid, stale, or already applied."""


class AMSOnboardingService:
    """Apply Cowboy's approved AMS onboarding as one exact atomic transaction."""

    REQUIRED_SCHEMA = "020_purchase_line_tracking_corrections.sql"
    CONFIRMATION_PHRASE = "APPLY-AMS-ONBOARDING-29-2-0"
    ACTOR = "Cowboy"
    P1S_NUMBER = "THS-EQP-000001"
    P1S_SERIAL = "01P00C511401400"
    AMS_ROWS = (
        {
            "equipment_number": "THS-EQP-000002",
            "display_name": "Bambu Lab AMS 2 Pro - AMS 1",
            "serial": "19C06A522002297",
            "legacy_id": 1,
            "legacy_name": "AMS 1",
            "operational_status": "degraded",
            "designation": "A",
        },
        {
            "equipment_number": "THS-EQP-000003",
            "display_name": "Bambu Lab AMS 2 Pro - AMS 2",
            "serial": "19C51A620400EWR",
            "legacy_id": 2,
            "legacy_name": "AMS 2",
            "operational_status": "operating",
            "designation": "B",
        },
    )
    PART_NUMBER = "THS-PART-000001"
    PART_NAME = "Bambu Lab AMS 2 Pro Feeder Unit"
    PART_MODEL = "SA403-V1"
    PART_UPC = "6937285503237"
    MAINTENANCE_NUMBER = "THS-MNT-000002"
    EXPECTED_ASSIGNMENTS = {
        ("AMS 1", 1): ("THS-FIL-000040", "purple"),
        ("AMS 1", 3): ("THS-FIL-000042", "Hot Pink"),
        ("AMS 1", 4): ("THS-FIL-000041", "Cocoa Brown"),
        ("AMS 2", 1): ("THS-FIL-000039", "Black"),
        ("AMS 2", 2): ("THS-FIL-000023", "Orange"),
        ("AMS 2", 3): ("THS-FIL-000033", "cyan"),
        ("AMS 2", 4): ("THS-FIL-000022", "Jade White"),
    }
    ALLOWED_CHANGED_TABLES = {
        "equipment_registry",
        "equipment_history",
        "audit_events",
        "equipment_relationship_state",
        "equipment_relationship_history",
        "equipment_legacy_container_links",
        "equipment_maintenance_asset_links",
        "maintenance_assets",
        "maintenance_records",
        "maintenance_history",
        "item_types",
        "catalog_items",
        "inventory_instances",
        "inventory_transactions",
        "transaction_lines",
    }

    def __init__(self, database: Path | str):
        self.database = Path(database)

    def preview(self) -> dict:
        if not self.database.is_file():
            raise AMSOnboardingError("database was not found")
        before = self._sha256()
        uri = f"{self.database.resolve().as_uri()}?mode=ro"
        db = sqlite3.connect(uri, uri=True)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        try:
            state = self._validate_preconditions(db)
            result = self._preview_result(state)
        finally:
            db.close()
        after = self._sha256()
        if before != after:
            raise AMSOnboardingError("database changed during dry-run")
        result["sha256_before"] = before
        result["sha256_after"] = after
        result["database_unchanged"] = True
        return result

    def commit(
        self,
        *,
        confirmation: str,
        _fail_after_write: int | None = None,
        _fail_postcondition: bool = False,
    ) -> dict:
        if confirmation != self.CONFIRMATION_PHRASE:
            raise AMSOnboardingError(
                f"explicit confirmation phrase {self.CONFIRMATION_PHRASE!r} is required"
            )
        if not self.database.is_file():
            raise AMSOnboardingError("database was not found")
        with closing(connect(self.database)) as db:
            inserted: list[dict] = []
            updated: list[dict] = []
            write_count = 0

            def write(sql: str, parameters=(), *, result: dict):
                nonlocal write_count
                cursor = db.execute(sql, parameters)
                write_count += 1
                if result["operation"] == "insert":
                    item = dict(result)
                    item["row_id"] = cursor.lastrowid
                    inserted.append(item)
                else:
                    if cursor.rowcount != 1:
                        raise AMSOnboardingError(
                            f"stale update target for {result['table']}"
                        )
                    updated.append(dict(result))
                if _fail_after_write == write_count:
                    raise AMSOnboardingError(
                        f"injected rollback after write {write_count}"
                    )
                return cursor

            try:
                db.execute("BEGIN IMMEDIATE")
                state = self._validate_preconditions(db)
                protected_before = self._table_fingerprints(db)
                existing_rows = self._existing_row_snapshots(db)
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                plan_uuid = uuid.uuid4().hex
                equipment_ids: dict[str, int] = {}

                for ams in self.AMS_ROWS:
                    cursor = write(
                        """INSERT INTO equipment_registry(
                        equipment_uuid,equipment_number,display_name,equipment_type_id,
                        equipment_subtype_id,manufacturer_id,model,
                        manufacturer_serial_number,ths_asset_identifier,current_location_id,
                        lifecycle_state,operational_status,installed_at,commissioned_at,
                        retired_at,disposed_at,notes,state_version,created_by,created_at,updated_at)
                        VALUES (?,?,?,?,?,?,?,?,NULL,NULL,'installed',?,NULL,NULL,NULL,NULL,?,1,?,?,?)""",
                        (
                            str(uuid.uuid4()),
                            ams["equipment_number"],
                            ams["display_name"],
                            state["ams_type_id"],
                            state["ams_subtype_id"],
                            state["manufacturer_id"],
                            "AMS 2 Pro",
                            ams["serial"],
                            ams["operational_status"],
                            (
                                f"Bambu Studio designation {ams['designation']}. "
                                f"Linked to existing {ams['legacy_name']} container; "
                                "slot and filament assignment history preserved."
                            ),
                            self.ACTOR,
                            now,
                            now,
                        ),
                        result={
                            "operation": "insert",
                            "table": "equipment_registry",
                            "human_id": ams["equipment_number"],
                        },
                    )
                    equipment_id = cursor.lastrowid
                    equipment_ids[ams["equipment_number"]] = equipment_id
                    register_nonce = f"{plan_uuid}-{ams['equipment_number']}-register"
                    write(
                        """INSERT INTO equipment_history(
                        history_uuid,request_nonce,equipment_id,action_type,
                        previous_state_version,new_state_version,snapshot,actor,reason,occurred_at)
                        VALUES (?,?,?,'register',NULL,1,?,?,?,?)""",
                        (
                            str(uuid.uuid4()),
                            register_nonce,
                            equipment_id,
                            self._json(
                                {
                                    "equipment_number": ams["equipment_number"],
                                    "display_name": ams["display_name"],
                                    "manufacturer": "Bambu Lab",
                                    "model": "AMS 2 Pro",
                                    "manufacturer_serial_number": ams["serial"],
                                    "lifecycle_state": "installed",
                                    "operational_status": ams["operational_status"],
                                }
                            ),
                            self.ACTOR,
                            "Physically verified AMS onboarding.",
                            now,
                        ),
                        result={
                            "operation": "insert",
                            "table": "equipment_history",
                            "human_id": ams["equipment_number"],
                            "action": "register",
                        },
                    )
                    self._insert_audit(
                        write,
                        now,
                        module="equipment-registry",
                        event_type="register_equipment",
                        entity_type="equipment",
                        entity_id=equipment_id,
                        human_id=ams["equipment_number"],
                        summary="Register Equipment",
                        nonce=f"{plan_uuid}-{ams['equipment_number']}-register-audit",
                    )
                    relationship_nonce = (
                        f"{plan_uuid}-{ams['equipment_number']}-relationship"
                    )
                    write(
                        """INSERT INTO equipment_relationship_state(
                        child_equipment_id,parent_equipment_id,relationship_type,
                        state_version,effective_at,updated_at)
                        VALUES (?,?,'attached_to',1,?,?)""",
                        (equipment_id, state["parent"]["id"], now, now),
                        result={
                            "operation": "insert",
                            "table": "equipment_relationship_state",
                            "human_id": ams["equipment_number"],
                        },
                    )
                    write(
                        """INSERT INTO equipment_relationship_history(
                        history_uuid,request_nonce,child_equipment_id,
                        previous_parent_equipment_id,new_parent_equipment_id,
                        previous_relationship_type,new_relationship_type,action_type,
                        previous_state_version,new_state_version,effective_at,actor,reason,
                        snapshot,occurred_at)
                        VALUES (?,?,?,NULL,?,NULL,'attached_to','attach',NULL,1,?,?,?,?,?)""",
                        (
                            str(uuid.uuid4()),
                            relationship_nonce,
                            equipment_id,
                            state["parent"]["id"],
                            now,
                            self.ACTOR,
                            "Physically verified attachment to P1S.",
                            self._json(
                                {
                                    "child": ams["equipment_number"],
                                    "parent": self.P1S_NUMBER,
                                    "relationship_type": "attached_to",
                                }
                            ),
                            now,
                        ),
                        result={
                            "operation": "insert",
                            "table": "equipment_relationship_history",
                            "human_id": ams["equipment_number"],
                            "action": "attach",
                        },
                    )
                    self._insert_audit(
                        write,
                        now,
                        module="equipment-registry",
                        event_type="attach_equipment_relationship",
                        entity_type="equipment",
                        entity_id=equipment_id,
                        human_id=ams["equipment_number"],
                        summary="Attach Equipment Relationship",
                        nonce=f"{plan_uuid}-{ams['equipment_number']}-relationship-audit",
                    )
                    write(
                        """INSERT INTO equipment_legacy_container_links(
                        equipment_id,legacy_equipment_id,linked_by,linked_at)
                        VALUES (?,?,?,?)""",
                        (equipment_id, ams["legacy_id"], self.ACTOR, now),
                        result={
                            "operation": "insert",
                            "table": "equipment_legacy_container_links",
                            "human_id": ams["equipment_number"],
                            "legacy_equipment_id": ams["legacy_id"],
                        },
                    )
                    self._insert_audit(
                        write,
                        now,
                        module="equipment-registry",
                        event_type="link_legacy_equipment_container",
                        entity_type="equipment",
                        entity_id=equipment_id,
                        human_id=ams["equipment_number"],
                        summary="Link Legacy Equipment Container",
                        nonce=f"{plan_uuid}-{ams['equipment_number']}-legacy-audit",
                    )

                parent_nonce = f"{plan_uuid}-p1s-facts"
                write(
                    """INSERT INTO equipment_history(
                    history_uuid,request_nonce,equipment_id,action_type,
                    previous_state_version,new_state_version,snapshot,actor,reason,occurred_at)
                    VALUES (?,?,?,'update_facts',1,2,?,?,?,?)""",
                    (
                        str(uuid.uuid4()),
                        parent_nonce,
                        state["parent"]["id"],
                        self._json(
                            {
                                "equipment_number": self.P1S_NUMBER,
                                "manufacturer_serial_number_before": None,
                                "manufacturer_serial_number_after": self.P1S_SERIAL,
                            }
                        ),
                        self.ACTOR,
                        "Physically verified P1S screen serial.",
                        now,
                    ),
                    result={
                        "operation": "insert",
                        "table": "equipment_history",
                        "human_id": self.P1S_NUMBER,
                        "action": "update_facts",
                    },
                )
                self._insert_audit(
                    write,
                    now,
                    module="equipment-registry",
                    event_type="update_equipment_facts",
                    entity_type="equipment",
                    entity_id=state["parent"]["id"],
                    human_id=self.P1S_NUMBER,
                    summary="Update Equipment Facts",
                    nonce=f"{parent_nonce}-audit",
                )

                ams_1_id = equipment_ids["THS-EQP-000002"]
                write(
                    """INSERT INTO equipment_maintenance_asset_links(
                    equipment_id,maintenance_asset_id,linked_by,linked_at)
                    VALUES (?,?,?,?)""",
                    (ams_1_id, 2, self.ACTOR, now),
                    result={
                        "operation": "insert",
                        "table": "equipment_maintenance_asset_links",
                        "human_id": "THS-EQP-000002",
                        "maintenance_asset_id": 2,
                    },
                )
                maintenance_cursor = write(
                    """INSERT INTO maintenance_records(
                    event_number,asset_id,event_type,status,severity,discovered_at,
                    due_at,completed_at,symptoms,likely_cause,corrective_action,
                    parts_required,parts_used,notes,related_print_id,
                    unattended_printing_allowed,created_by,created_at,updated_at)
                    VALUES (?,2,'fault_discovered','in_progress','high',?,NULL,NULL,?,
                    NULL,?,?,NULL,?,NULL,1,?,?,?)""",
                    (
                        self.MAINTENANCE_NUMBER,
                        now,
                        (
                            "Affected component: Slot 2 / A2. Reported symptom: "
                            "the feeder/roller becomes loud and may lock."
                        ),
                        (
                            "Inspect Slot 2 / A2, replace the feeder if appropriate, "
                            "and function-test it before returning the slot to service."
                        ),
                        (
                            f"Available candidate part: {self.PART_NUMBER} {self.PART_NAME}, "
                            f"model {self.PART_MODEL}, UPC {self.PART_UPC}. Not reserved, "
                            "issued, consumed, or installed."
                        ),
                        (
                            "Restriction: Slot 2 / A2 is Out of service - do not load "
                            "filament. Slots 1, 3, and 4 remain usable. Slot 4 / A4 "
                            "remains in service; it has historically rewound faster than "
                            "the spool and should be monitored."
                        ),
                        self.ACTOR,
                        now,
                        now,
                    ),
                    result={
                        "operation": "insert",
                        "table": "maintenance_records",
                        "human_id": self.MAINTENANCE_NUMBER,
                    },
                )
                maintenance_id = maintenance_cursor.lastrowid
                write(
                    """INSERT INTO maintenance_history(
                    history_uuid,request_nonce,maintenance_record_id,action_type,
                    previous_status,new_status,previous_readiness_state,
                    new_readiness_state,snapshot,reason,actor,occurred_at)
                    VALUES (?,? ,?,'record_fault',NULL,'in_progress','normal',
                    'monitor_during_printing',?,?,?,?)""",
                    (
                        str(uuid.uuid4()),
                        f"{plan_uuid}-maintenance",
                        maintenance_id,
                        self._json(
                            {
                                "event_number": self.MAINTENANCE_NUMBER,
                                "affected_component": "Slot 2 / A2",
                                "restriction": "Out of service - do not load",
                                "candidate_part": self.PART_NUMBER,
                            }
                        ),
                        "Physically verified mechanical fault.",
                        self.ACTOR,
                        now,
                    ),
                    result={
                        "operation": "insert",
                        "table": "maintenance_history",
                        "human_id": self.MAINTENANCE_NUMBER,
                        "action": "record_fault",
                    },
                )

                item_type_cursor = write(
                    """INSERT INTO item_types(
                    category_id,name,tracking_method,id_prefix,default_unit_id)
                    VALUES (?,'Printer Part','individual','THS-PART',?)""",
                    (state["printing_category_id"], state["each_unit_id"]),
                    result={
                        "operation": "insert",
                        "table": "item_types",
                        "human_id": "Printer Part",
                    },
                )
                item_type_id = item_type_cursor.lastrowid
                self._insert_audit(
                    write,
                    now,
                    module="inventory",
                    event_type="create_item_type",
                    entity_type="item_type",
                    entity_id=item_type_id,
                    human_id="Printer Part",
                    summary="Create Printer Part Item Type",
                    nonce=f"{plan_uuid}-part-type",
                )
                catalog_cursor = write(
                    """INSERT INTO catalog_items(
                    item_type_id,manufacturer_id,name,product_line,variant,
                    manufacturer_sku,base_unit_id,notes)
                    VALUES (?,?,?,'AMS 2 Pro',?,?,?,?)""",
                    (
                        item_type_id,
                        state["manufacturer_id"],
                        self.PART_NAME,
                        self.PART_MODEL,
                        self.PART_MODEL,
                        state["each_unit_id"],
                        f"UPC {self.PART_UPC}. Candidate maintenance part.",
                    ),
                    result={
                        "operation": "insert",
                        "table": "catalog_items",
                        "human_id": self.PART_NAME,
                    },
                )
                catalog_id = catalog_cursor.lastrowid
                self._insert_audit(
                    write,
                    now,
                    module="inventory",
                    event_type="create_catalog_item",
                    entity_type="catalog_item",
                    entity_id=catalog_id,
                    human_id=self.PART_NAME,
                    summary="Create Feeder Catalog Item",
                    nonce=f"{plan_uuid}-part-catalog",
                )
                instance_cursor = write(
                    """INSERT INTO inventory_instances(
                    permanent_id,catalog_item_id,state,condition,serial_number,
                    lot_number,location_id,original_quantity,remaining_quantity,
                    unit_id,purchase_date,opened_at,emptied_at,expires_at,archived_at,
                    notes,verified,created_at,updated_at)
                    VALUES (?,?, 'sealed','new/boxed',NULL,NULL,NULL,1,1,?,
                    NULL,NULL,NULL,NULL,NULL,?,1,?,?)""",
                    (
                        self.PART_NUMBER,
                        catalog_id,
                        state["each_unit_id"],
                        (
                            f"UPC {self.PART_UPC}. Available candidate for AMS 1 Slot 2 / "
                            "A2 feeder repair. Storage unresolved. Not installed, reserved, "
                            "issued, or consumed."
                        ),
                        now,
                        now,
                    ),
                    result={
                        "operation": "insert",
                        "table": "inventory_instances",
                        "human_id": self.PART_NUMBER,
                    },
                )
                instance_id = instance_cursor.lastrowid
                transaction_cursor = write(
                    """INSERT INTO inventory_transactions(
                    transaction_type,occurred_at,reason,notes,origin,actor)
                    VALUES ('add',?,?,?,'manual',?)""",
                    (
                        now,
                        "Physically verified boxed feeder candidate.",
                        "Storage location intentionally unresolved.",
                        self.ACTOR,
                    ),
                    result={
                        "operation": "insert",
                        "table": "inventory_transactions",
                        "human_id": self.PART_NUMBER,
                        "transaction_type": "add",
                    },
                )
                transaction_id = transaction_cursor.lastrowid
                write(
                    """INSERT INTO transaction_lines(
                    transaction_id,catalog_item_id,instance_id,stock_lot_id,
                    quantity_change,unit_id,source_location_id,destination_location_id)
                    VALUES (?,?,?,NULL,1,?,NULL,NULL)""",
                    (
                        transaction_id,
                        catalog_id,
                        instance_id,
                        state["each_unit_id"],
                    ),
                    result={
                        "operation": "insert",
                        "table": "transaction_lines",
                        "human_id": self.PART_NUMBER,
                    },
                )
                self._insert_audit(
                    write,
                    now,
                    module="inventory",
                    event_type="add_individual_instance",
                    entity_type="inventory_instance",
                    entity_id=instance_id,
                    human_id=self.PART_NUMBER,
                    summary="Add Verified Feeder Candidate",
                    nonce=f"{plan_uuid}-part-instance",
                )

                write(
                    """UPDATE equipment_registry
                    SET manufacturer_serial_number=?,state_version=2,updated_at=?
                    WHERE id=1 AND equipment_number=? AND manufacturer_serial_number IS NULL
                      AND state_version=1""",
                    (self.P1S_SERIAL, now, self.P1S_NUMBER),
                    result={
                        "operation": "update",
                        "table": "equipment_registry",
                        "row_id": 1,
                        "human_id": self.P1S_NUMBER,
                        "fields": {
                            "manufacturer_serial_number": {
                                "before": None,
                                "after": self.P1S_SERIAL,
                            },
                            "state_version": {"before": 1, "after": 2},
                            "updated_at": {"before": state["parent"]["updated_at"], "after": now},
                        },
                    },
                )
                write(
                    """UPDATE maintenance_assets
                    SET readiness_state='monitor_during_printing',updated_at=?
                    WHERE id=2 AND readiness_state='normal' AND equipment_id=1""",
                    (now,),
                    result={
                        "operation": "update",
                        "table": "maintenance_assets",
                        "row_id": 2,
                        "human_id": "AMS 1",
                        "fields": {
                            "readiness_state": {
                                "before": "normal",
                                "after": "monitor_during_printing",
                            },
                            "updated_at": {
                                "before": state["maintenance_asset"]["updated_at"],
                                "after": now,
                            },
                        },
                    },
                )

                if len(inserted) != 29 or len(updated) != 2 or write_count != 31:
                    raise AMSOnboardingError("atomic write count differs from 29/2/0")
                if _fail_postcondition:
                    raise AMSOnboardingError("injected postcondition failure")
                self._validate_postconditions(
                    db,
                    existing_rows=existing_rows,
                    protected_before=protected_before,
                )
                db.commit()
                return {
                    "mode": "committed",
                    "insert_count": len(inserted),
                    "update_count": len(updated),
                    "delete_count": 0,
                    "inserted": inserted,
                    "updated": updated,
                    "equipment": equipment_ids,
                    "maintenance_record": self.MAINTENANCE_NUMBER,
                    "part": self.PART_NUMBER,
                    "committed_at": now,
                }
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise AMSOnboardingError(
                    f"onboarding conflicts with current data: {exc}"
                ) from exc
            except Exception:
                db.rollback()
                raise

    def _validate_preconditions(self, db) -> dict:
        migrations = db.execute(
            "SELECT name FROM schema_migrations ORDER BY name"
        ).fetchall()
        if len(migrations) != 20 or migrations[-1][0] != self.REQUIRED_SCHEMA:
            raise AMSOnboardingError("database schema is not exactly 20")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise AMSOnboardingError("database integrity check failed")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise AMSOnboardingError("database has foreign-key violations")
        parent = db.execute(
            """SELECT id,equipment_number,manufacturer_serial_number,state_version,
            updated_at FROM equipment_registry WHERE id=1"""
        ).fetchone()
        if not parent or dict(parent) != {
            "id": 1,
            "equipment_number": self.P1S_NUMBER,
            "manufacturer_serial_number": None,
            "state_version": 1,
            "updated_at": parent["updated_at"] if parent else None,
        }:
            raise AMSOnboardingError("P1S update precondition is stale")
        maintenance_asset = db.execute(
            """SELECT id,equipment_id,readiness_state,updated_at
            FROM maintenance_assets WHERE id=2"""
        ).fetchone()
        if (
            not maintenance_asset
            or maintenance_asset["equipment_id"] != 1
            or maintenance_asset["readiness_state"] != "normal"
        ):
            raise AMSOnboardingError("AMS 1 maintenance update precondition is stale")
        if db.execute(
            "SELECT 1 FROM equipment_registry WHERE equipment_number IN (?,?)",
            tuple(row["equipment_number"] for row in self.AMS_ROWS),
        ).fetchone():
            raise AMSOnboardingError("AMS equipment IDs already exist; replay rejected")
        serials = [self.P1S_SERIAL, *(row["serial"] for row in self.AMS_ROWS)]
        placeholders = ",".join("?" for _ in serials)
        if db.execute(
            f"""SELECT 1 FROM equipment_registry
            WHERE lower(trim(manufacturer_serial_number)) IN ({placeholders})""",
            tuple(value.casefold() for value in serials),
        ).fetchone():
            raise AMSOnboardingError("approved equipment serial already exists")
        if db.execute(
            """SELECT 1 FROM equipment_registry
            WHERE lower(trim(display_name)) IN (lower(trim(?)),lower(trim(?)))""",
            tuple(row["display_name"] for row in self.AMS_ROWS),
        ).fetchone():
            raise AMSOnboardingError("approved AMS display name already exists")
        if db.execute(
            "SELECT 1 FROM equipment_legacy_container_links WHERE legacy_equipment_id IN (1,2)"
        ).fetchone():
            raise AMSOnboardingError("legacy AMS bridge already exists")
        if db.execute(
            "SELECT 1 FROM maintenance_records WHERE event_number=?",
            (self.MAINTENANCE_NUMBER,),
        ).fetchone():
            raise AMSOnboardingError("maintenance record already exists")
        if db.execute(
            "SELECT 1 FROM inventory_instances WHERE permanent_id=?",
            (self.PART_NUMBER,),
        ).fetchone():
            raise AMSOnboardingError("feeder permanent ID already exists")
        if db.execute(
            """SELECT 1 FROM catalog_items ci
            LEFT JOIN catalog_item_attribute_values av ON av.catalog_item_id=ci.id
            WHERE lower(trim(ci.name))=lower(trim(?))
               OR lower(trim(COALESCE(ci.manufacturer_sku,'')))=lower(trim(?))
               OR lower(trim(COALESCE(ci.variant,'')))=lower(trim(?))
               OR instr(lower(COALESCE(ci.notes,'')),lower(?))>0
               OR instr(lower(COALESCE(av.text_value,'')),lower(?))>0""",
            (
                self.PART_NAME,
                self.PART_MODEL,
                self.PART_MODEL,
                self.PART_UPC,
                self.PART_UPC,
            ),
        ).fetchone():
            raise AMSOnboardingError("matching feeder catalog identity already exists")
        if db.execute(
            """SELECT 1 FROM inventory_instances
            WHERE instr(lower(COALESCE(notes,'')),lower(?))>0""",
            (self.PART_UPC,),
        ).fetchone():
            raise AMSOnboardingError("matching feeder inventory identity already exists")
        if db.execute(
            "SELECT 1 FROM item_types WHERE name='Printer Part' OR id_prefix='THS-PART'"
        ).fetchone():
            raise AMSOnboardingError("Printer Part item type or prefix already exists")
        if db.execute(
            "SELECT 1 FROM equipment_maintenance_asset_links WHERE maintenance_asset_id=2"
        ).fetchone():
            raise AMSOnboardingError("AMS 1 maintenance asset is already linked")
        slot_rows = self._slot_assignment_snapshot(db)
        if len(slot_rows) != 8:
            raise AMSOnboardingError("the existing AMS slot set is not exactly eight rows")
        actual_assignments = {}
        for row in slot_rows:
            key = (row["equipment_name"], row["slot_number"])
            if row["permanent_id"]:
                actual_assignments[key] = (row["permanent_id"], row["color"])
        if actual_assignments != self.EXPECTED_ASSIGNMENTS:
            raise AMSOnboardingError("active AMS assignments differ from approved truth")
        a2 = next(
            row
            for row in slot_rows
            if row["equipment_name"] == "AMS 1" and row["slot_number"] == 2
        )
        if a2["assignment_id"] is not None:
            raise AMSOnboardingError("AMS 1 Slot 2 / A2 must remain empty")
        manufacturer = db.execute(
            "SELECT id FROM manufacturers WHERE name='Bambu Lab' AND archived_at IS NULL"
        ).fetchone()
        equipment_type = db.execute(
            "SELECT id FROM equipment_types WHERE type_code='ams_unit' AND active=1"
        ).fetchone()
        subtype = db.execute(
            """SELECT es.id FROM equipment_subtypes es
            JOIN equipment_types et ON et.id=es.equipment_type_id
            WHERE et.type_code='ams_unit' AND es.subtype_code='bambu_ams' AND es.active=1"""
        ).fetchone()
        category = db.execute(
            "SELECT id FROM categories WHERE name='3D Printing' AND archived_at IS NULL"
        ).fetchone()
        unit = db.execute("SELECT id FROM units WHERE code='ea'").fetchone()
        legacy = [
            tuple(row)
            for row in db.execute(
                "SELECT id,name FROM equipment WHERE id IN (1,2) ORDER BY id"
            )
        ]
        if (
            not manufacturer
            or not equipment_type
            or not subtype
            or not category
            or not unit
            or legacy != [(1, "AMS 1"), (2, "AMS 2")]
        ):
            raise AMSOnboardingError("required authoritative configuration is unavailable")
        return {
            "parent": dict(parent),
            "maintenance_asset": dict(maintenance_asset),
            "manufacturer_id": manufacturer["id"],
            "ams_type_id": equipment_type["id"],
            "ams_subtype_id": subtype["id"],
            "printing_category_id": category["id"],
            "each_unit_id": unit["id"],
            "slots": slot_rows,
        }

    def _validate_postconditions(self, db, *, existing_rows, protected_before):
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise AMSOnboardingError("post-write foreign-key validation failed")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise AMSOnboardingError("post-write integrity validation failed")
        for number, serial, status in (
            ("THS-EQP-000002", "19C06A522002297", "degraded"),
            ("THS-EQP-000003", "19C51A620400EWR", "operating"),
        ):
            row = db.execute(
                """SELECT equipment_number,manufacturer_serial_number,lifecycle_state,
                operational_status FROM equipment_registry WHERE equipment_number=?""",
                (number,),
            ).fetchone()
            if not row or tuple(row) != (number, serial, "installed", status):
                raise AMSOnboardingError(f"postcondition failed for {number}")
        relationships = [
            tuple(row)
            for row in db.execute(
                """SELECT child.equipment_number,parent.equipment_number,
                ers.relationship_type FROM equipment_relationship_state ers
                JOIN equipment_registry child ON child.id=ers.child_equipment_id
                JOIN equipment_registry parent ON parent.id=ers.parent_equipment_id
                WHERE child.equipment_number IN ('THS-EQP-000002','THS-EQP-000003')
                ORDER BY child.equipment_number"""
            )
        ]
        if relationships != [
            ("THS-EQP-000002", self.P1S_NUMBER, "attached_to"),
            ("THS-EQP-000003", self.P1S_NUMBER, "attached_to"),
        ]:
            raise AMSOnboardingError("AMS relationship postcondition failed")
        part = db.execute(
            """SELECT ii.permanent_id,ci.name,ci.variant,ci.manufacturer_sku,
            ii.state,ii.condition,ii.location_id,ii.original_quantity,
            ii.remaining_quantity,ii.notes
            FROM inventory_instances ii JOIN catalog_items ci ON ci.id=ii.catalog_item_id
            WHERE ii.permanent_id=?""",
            (self.PART_NUMBER,),
        ).fetchone()
        if (
            not part
            or part["permanent_id"] != self.PART_NUMBER
            or part["name"] != self.PART_NAME
            or part["variant"] != self.PART_MODEL
            or part["manufacturer_sku"] != self.PART_MODEL
            or part["state"] != "sealed"
            or part["condition"] != "new/boxed"
            or part["location_id"] is not None
            or part["original_quantity"] != 1
            or part["remaining_quantity"] != 1
            or self.PART_UPC not in part["notes"]
        ):
            raise AMSOnboardingError("feeder candidate postcondition failed")
        maintenance = db.execute(
            """SELECT mr.event_number,mr.asset_id,mr.status,mr.parts_required,mr.notes,
            ma.readiness_state FROM maintenance_records mr
            JOIN maintenance_assets ma ON ma.id=mr.asset_id
            WHERE mr.event_number=?""",
            (self.MAINTENANCE_NUMBER,),
        ).fetchone()
        if (
            not maintenance
            or maintenance["asset_id"] != 2
            or maintenance["status"] != "in_progress"
            or self.PART_NUMBER not in maintenance["parts_required"]
            or "Slot 2 / A2 is Out of service" not in maintenance["notes"]
            or maintenance["readiness_state"] != "monitor_during_printing"
        ):
            raise AMSOnboardingError("maintenance postcondition failed")
        if self._slot_assignment_snapshot(db) != existing_rows["slot_assignments"]:
            raise AMSOnboardingError("slot or filament assignment changed during onboarding")
        self._assert_existing_rows_unchanged(db, existing_rows)
        protected_after = self._table_fingerprints(db)
        for table, fingerprint in protected_before.items():
            if table not in self.ALLOWED_CHANGED_TABLES:
                if protected_after[table] != fingerprint:
                    raise AMSOnboardingError(
                        f"unrelated protected table changed: {table}"
                    )

    def _existing_row_snapshots(self, db):
        return {
            "slot_assignments": self._slot_assignment_snapshot(db),
            "inventory_instances": [
                tuple(row)
                for row in db.execute(
                    "SELECT * FROM inventory_instances ORDER BY id"
                )
            ],
            "catalog_items": [
                tuple(row) for row in db.execute("SELECT * FROM catalog_items ORDER BY id")
            ],
            "equipment_registry": [
                tuple(row)
                for row in db.execute(
                    "SELECT * FROM equipment_registry WHERE id<>1 ORDER BY id"
                )
            ],
        }

    def _assert_existing_rows_unchanged(self, db, before):
        instances = [
            tuple(row)
            for row in db.execute(
                "SELECT * FROM inventory_instances WHERE permanent_id<>? ORDER BY id",
                (self.PART_NUMBER,),
            )
        ]
        if instances != before["inventory_instances"]:
            raise AMSOnboardingError("existing inventory instances changed")
        catalog = [
            tuple(row)
            for row in db.execute(
                "SELECT * FROM catalog_items WHERE name<>? ORDER BY id",
                (self.PART_NAME,),
            )
        ]
        if catalog != before["catalog_items"]:
            raise AMSOnboardingError("existing catalog items changed")
        registry = [
            tuple(row)
            for row in db.execute(
                "SELECT * FROM equipment_registry WHERE id<>1 AND equipment_number NOT IN (?,?) ORDER BY id",
                tuple(row["equipment_number"] for row in self.AMS_ROWS),
            )
        ]
        if registry != before["equipment_registry"]:
            raise AMSOnboardingError("existing equipment records changed")

    def _preview_result(self, state):
        return {
            "mode": "dry-run",
            "production_ready": True,
            "schema": 19,
            "insert_count": 29,
            "update_count": 2,
            "delete_count": 0,
            "confirmation_phrase": self.CONFIRMATION_PHRASE,
            "equipment": [
                {
                    "equipment_number": row["equipment_number"],
                    "display_name": row["display_name"],
                    "serial": row["serial"],
                    "lifecycle_state": "installed",
                    "operational_status": row["operational_status"],
                    "parent": self.P1S_NUMBER,
                }
                for row in self.AMS_ROWS
            ],
            "part": {
                "permanent_id": self.PART_NUMBER,
                "product": self.PART_NAME,
                "model": self.PART_MODEL,
                "upc": self.PART_UPC,
                "quantity": 1,
                "condition": "new/boxed",
                "location_id": None,
                "installed": False,
                "reserved": False,
                "issued": False,
                "consumed": False,
            },
            "maintenance_record": self.MAINTENANCE_NUMBER,
            "updates": [
                {
                    "table": "equipment_registry",
                    "row_id": 1,
                    "human_id": self.P1S_NUMBER,
                    "fields": {
                        "manufacturer_serial_number": [None, self.P1S_SERIAL],
                        "state_version": [1, 2],
                        "updated_at": [state["parent"]["updated_at"], "<commit time>"],
                    },
                },
                {
                    "table": "maintenance_assets",
                    "row_id": 2,
                    "human_id": "AMS 1",
                    "fields": {
                        "readiness_state": ["normal", "monitor_during_printing"],
                        "updated_at": [
                            state["maintenance_asset"]["updated_at"],
                            "<commit time>",
                        ],
                    },
                },
            ],
            "slot_count": 8,
            "active_assignment_count": 7,
            "a2_empty": True,
        }

    @staticmethod
    def _insert_audit(
        write,
        occurred_at,
        *,
        module,
        event_type,
        entity_type,
        entity_id,
        human_id,
        summary,
        nonce,
    ):
        write(
            """INSERT INTO audit_events(
            event_uuid,occurred_at,actor,module,origin,event_type,entity_type,
            entity_id,entity_human_id,summary,details,request_nonce)
            VALUES (?,?,?,?,'user',?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()),
                occurred_at,
                AMSOnboardingService.ACTOR,
                module,
                event_type,
                entity_type,
                entity_id,
                human_id,
                summary,
                AMSOnboardingService._json({"controlled_onboarding": True}),
                nonce,
            ),
            result={
                "operation": "insert",
                "table": "audit_events",
                "human_id": human_id,
                "action": event_type,
            },
        )

    @staticmethod
    def _slot_assignment_snapshot(db):
        return [
            dict(row)
            for row in db.execute(
                """SELECT es.id slot_id,e.name equipment_name,es.slot_number,
                es.location_id,aa.id assignment_id,aa.instance_id,aa.loaded_at,
                aa.unloaded_at,aa.load_transaction_id,aa.unload_transaction_id,
                ii.permanent_id,ii.state,ii.remaining_quantity,ci.variant color
                FROM equipment_slots es JOIN equipment e ON e.id=es.equipment_id
                LEFT JOIN ams_assignments aa
                  ON aa.slot_id=es.id AND aa.unloaded_at IS NULL
                LEFT JOIN inventory_instances ii ON ii.id=aa.instance_id
                LEFT JOIN catalog_items ci ON ci.id=ii.catalog_item_id
                WHERE e.id IN (1,2) ORDER BY e.id,es.slot_number"""
            )
        ]

    @staticmethod
    def _table_fingerprints(db):
        result = {}
        tables = [
            row[0]
            for row in db.execute(
                """SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"""
            )
        ]
        for table in tables:
            rows = [tuple(row) for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
            result[table] = hashlib.sha256(repr(rows).encode()).hexdigest()
        return result

    def _sha256(self):
        return hashlib.sha256(self.database.read_bytes()).hexdigest().upper()

    @staticmethod
    def _json(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
