from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .db import DEFAULT_DB
from .health import ShopHealthEngine


class DatabaseNotReady(RuntimeError):
    """Raised when the read-only application database is missing or unmigrated."""


class InventoryQueries:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        if not self.path.is_file():
            raise DatabaseNotReady(
                f"Inventory database not found at {self.path}. Run: py -3 -m inventory.cli migrate"
            )
        try:
            db = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
            db.row_factory = sqlite3.Row
            db.execute("SELECT 1 FROM schema_migrations LIMIT 1").fetchone()
            db.execute("SELECT 1 FROM item_types WHERE tracking_method='individual' LIMIT 1").fetchone()
            return db
        except sqlite3.Error as exc:
            raise DatabaseNotReady(
                "Inventory database exists but is not ready. Run: py -3 -m inventory.cli migrate"
            ) from exc

    def dashboard(self) -> dict[str, Any]:
        with closing(self.connect()) as db:
            totals = dict(
                db.execute(
                    """
                    SELECT
                      COUNT(ii.id) physical_spools,
                      COALESCE(SUM(ii.state='sealed' AND ii.archived_at IS NULL),0) sealed_spools,
                      COALESCE(SUM(ii.state='open' AND ii.archived_at IS NULL),0) open_spools,
                      COALESCE(SUM(ii.state='loaded' AND ii.archived_at IS NULL),0) loaded_spools,
                      COALESCE(SUM(ii.state IN ('empty','archived') OR ii.archived_at IS NOT NULL),0) archived_spools,
                      COALESCE(SUM(ii.original_quantity),0) nominal_grams,
                      COALESCE(SUM(CASE WHEN ii.archived_at IS NULL AND ii.state NOT IN ('empty','archived')
                        THEN ii.remaining_quantity ELSE 0 END),0) remaining_grams
                    FROM inventory_instances ii
                    JOIN catalog_items ci ON ci.id=ii.catalog_item_id
                    JOIN item_types it ON it.id=ci.item_type_id
                    WHERE it.name='Filament'
                    """
                ).fetchone()
            )
            totals["reserved_grams"] = db.execute(
                """
                SELECT COALESCE(SUM(r.quantity),0) FROM reservations r
                JOIN catalog_items ci ON ci.id=r.catalog_item_id
                JOIN item_types it ON it.id=ci.item_type_id
                WHERE it.name='Filament' AND r.status='active'
                """
            ).fetchone()[0]
            totals["available_grams"] = max(
                0, totals["remaining_grams"] - totals["reserved_grams"]
            )
            totals["catalog_products"] = db.execute(
                """
                SELECT COUNT(*) FROM catalog_items ci
                JOIN item_types it ON it.id=ci.item_type_id
                WHERE it.name='Filament' AND ci.archived_at IS NULL
                """
            ).fetchone()[0]
            ams = dict(
                db.execute(
                    """
                    SELECT COUNT(DISTINCT e.id) ams_units, COUNT(es.id) total_slots,
                      COALESCE(SUM(aa.id IS NOT NULL),0) occupied_slots
                    FROM equipment e
                    LEFT JOIN equipment_slots es ON es.equipment_id=e.id
                    LEFT JOIN ams_assignments aa ON aa.slot_id=es.id AND aa.unloaded_at IS NULL
                    WHERE e.equipment_type='AMS' AND e.archived_at IS NULL
                    """
                ).fetchone()
            )
            totals.update(ams)
            totals["empty_slots"] = totals["total_slots"] - totals["occupied_slots"]
            totals["low_stock_products"] = self._low_stock_count(db)
            totals["brand_totals"] = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT m.name manufacturer,COUNT(ii.id) spool_count
                    FROM inventory_instances ii
                    JOIN catalog_items ci ON ci.id=ii.catalog_item_id
                    JOIN item_types it ON it.id=ci.item_type_id
                    JOIN manufacturers m ON m.id=ci.manufacturer_id
                    WHERE it.name='Filament'
                    GROUP BY m.id ORDER BY m.name
                    """
                )
            ]
            totals["printer"] = self._printer_status(db)
            totals["pending_orders"] = [
                dict(row) for row in db.execute(
                    """SELECT id,order_number,supplier,description,expected_quantity,
                    received_quantity,unit_label,material,color,state,ordered_at,updated_at
                    FROM orders WHERE state IN ('ordered','shipped','delivered')
                    ORDER BY updated_at DESC,id DESC LIMIT 4"""
                )
            ]
            totals["recent_activity"] = [
                dict(row) for row in db.execute(
                    """SELECT occurred_at,actor,action_type,affected_human_id,reason
                    FROM inventory_actions
                    WHERE action_type IN (
                      'load_instance_into_ams','open_sealed_spool','mark_spool_empty',
                      'add_individual_instance','receive_order_batch','transition_order')
                    ORDER BY occurred_at DESC,id DESC LIMIT 6"""
                )
            ]
            totals["ams_details"] = [
                dict(row) for row in db.execute(
                    """SELECT e.name equipment,es.slot_number,ii.permanent_id,
                    m.name manufacturer,ci.product_line,ci.variant color,
                    cc.text_value color_code,ii.remaining_quantity
                    FROM equipment e JOIN equipment_slots es ON es.equipment_id=e.id
                    LEFT JOIN ams_assignments aa
                      ON aa.slot_id=es.id AND aa.unloaded_at IS NULL
                    LEFT JOIN inventory_instances ii ON ii.id=aa.instance_id
                    LEFT JOIN catalog_items ci ON ci.id=ii.catalog_item_id
                    LEFT JOIN manufacturers m ON m.id=ci.manufacturer_id
                    LEFT JOIN catalog_item_attribute_values cc
                      ON cc.catalog_item_id=ci.id
                     AND cc.attribute_definition_id=(
                       SELECT id FROM attribute_definitions WHERE name='color_code'
                     )
                    WHERE e.equipment_type='AMS' AND e.archived_at IS NULL
                    ORDER BY e.name,es.slot_number"""
                )
            ]
            totals["shop_health"] = ShopHealthEngine.evaluate(db)
            totals["warnings"] = [
                item.get("message")
                or f'{item["equipment"]}: {item["readiness_label"]}'
                for item in totals["shop_health"]["restrictions"]
            ]
            return totals

    def orders(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as db:
            return [
                dict(row) for row in db.execute(
                    """SELECT o.*,m.name manufacturer,ci.product_line,ci.variant
                    FROM orders o LEFT JOIN catalog_items ci ON ci.id=o.catalog_item_id
                    LEFT JOIN manufacturers m ON m.id=ci.manufacturer_id
                    ORDER BY CASE o.state WHEN 'delivered' THEN 0 WHEN 'shipped' THEN 1
                      WHEN 'ordered' THEN 2 ELSE 3 END,o.updated_at DESC,o.id DESC"""
                )
            ]

    def order_detail(self, order_id: int) -> dict[str, Any] | None:
        with closing(self.connect()) as db:
            row = db.execute(
                """SELECT o.*,m.name manufacturer,ci.product_line,ci.variant
                FROM orders o LEFT JOIN catalog_items ci ON ci.id=o.catalog_item_id
                LEFT JOIN manufacturers m ON m.id=ci.manufacturer_id WHERE o.id=?""",
                (order_id,),
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["batches"] = [
                dict(batch) for batch in db.execute(
                    """SELECT rb.*,COUNT(ori.instance_id) instance_count
                    FROM receiving_batches rb LEFT JOIN order_received_instances ori
                      ON ori.receiving_batch_id=rb.id
                    WHERE rb.order_id=? GROUP BY rb.id ORDER BY rb.received_at DESC,rb.id DESC""",
                    (order_id,),
                )
            ]
            result["delivery_evidence"] = [
                dict(evidence) for evidence in db.execute(
                    """SELECT * FROM order_delivery_evidence
                    WHERE order_id=? ORDER BY added_at DESC,id DESC""",
                    (order_id,),
                )
            ]
            return result

    @staticmethod
    def _printer_status(db: sqlite3.Connection) -> dict[str, Any] | None:
        row = db.execute(
            """SELECT *,
            CASE WHEN last_update_at IS NULL OR
              julianday('now')-julianday(last_update_at) > (15.0/1440.0)
              THEN 1 ELSE 0 END status_stale
            FROM printers ORDER BY id LIMIT 1"""
        ).fetchone()
        return dict(row) if row else None

    def grouped_filament(
        self,
        *,
        search: str = "",
        state: str = "",
        manufacturer: str = "",
        material: str = "",
        low_stock: bool = False,
        sort: str = "manufacturer",
    ) -> dict[str, Any]:
        conditions = ["it.name='Filament'", "ci.archived_at IS NULL"]
        params: list[Any] = []
        if search:
            like = f"%{search.strip()}%"
            conditions.append(
                """(m.name LIKE ? OR ci.product_line LIKE ? OR ci.variant LIKE ?
                OR ci.notes LIKE ? OR mat.text_value LIKE ?
                OR EXISTS(SELECT 1 FROM inventory_instances sx
                  WHERE sx.catalog_item_id=ci.id AND
                  (sx.permanent_id LIKE ? OR sx.notes LIKE ?)))"""
            )
            params.extend([like] * 7)
        if manufacturer:
            conditions.append("m.name=?")
            params.append(manufacturer)
        if material:
            conditions.append("mat.text_value=?")
            params.append(material)
        if state:
            if state == "archived":
                conditions.append(
                    """EXISTS(SELECT 1 FROM inventory_instances fs
                    WHERE fs.catalog_item_id=ci.id AND
                    (fs.archived_at IS NOT NULL OR fs.state='archived'))"""
                )
            else:
                conditions.append(
                    """EXISTS(SELECT 1 FROM inventory_instances fs
                    WHERE fs.catalog_item_id=ci.id AND fs.state=? AND fs.archived_at IS NULL)"""
                )
                params.append(state)
        if low_stock:
            conditions.append(
                """EXISTS(SELECT 1 FROM stock_rules sr WHERE sr.catalog_item_id=ci.id
                AND COALESCE((SELECT SUM(x.remaining_quantity) FROM inventory_instances x
                  WHERE x.catalog_item_id=ci.id AND x.archived_at IS NULL
                    AND x.state NOT IN ('empty','archived')),0) < sr.minimum_quantity)"""
            )
        order = {
            "manufacturer": "m.name,ci.product_line,ci.variant",
            "material": "mat.text_value,m.name,ci.variant",
            "color": "ci.variant,m.name",
            "spools": "physical_spools DESC,m.name,ci.variant",
            "available": "available_grams DESC,m.name,ci.variant",
            "low_stock": "has_low_stock DESC,m.name,ci.variant",
        }.get(sort, "m.name,ci.product_line,ci.variant")
        sql = f"""
            SELECT ci.id,m.name manufacturer,ci.product_line,ci.variant color,
              COALESCE(mat.text_value,'Unknown') material,
              COUNT(ii.id) physical_spools,
              COALESCE(SUM(ii.state='sealed' AND ii.archived_at IS NULL),0) sealed_spools,
              COALESCE(SUM(ii.state='open' AND ii.archived_at IS NULL),0) open_spools,
              COALESCE(SUM(ii.state='loaded' AND ii.archived_at IS NULL),0) loaded_spools,
              COALESCE(SUM(ii.state IN ('empty','archived') OR ii.archived_at IS NOT NULL),0)
                empty_archived_spools,
              COALESCE(SUM(ii.original_quantity),0) nominal_grams,
              COALESCE(SUM(CASE WHEN ii.archived_at IS NULL AND ii.state NOT IN ('empty','archived')
                THEN ii.remaining_quantity ELSE 0 END),0) remaining_grams,
              COALESCE((SELECT SUM(r.quantity) FROM reservations r
                WHERE r.catalog_item_id=ci.id AND r.status='active'),0) reserved_grams,
              MAX(0,COALESCE(SUM(CASE WHEN ii.archived_at IS NULL
                AND ii.state NOT IN ('empty','archived') THEN ii.remaining_quantity ELSE 0 END),0)
                - COALESCE((SELECT SUM(r.quantity) FROM reservations r
                  WHERE r.catalog_item_id=ci.id AND r.status='active'),0)) available_grams,
              sr.minimum_quantity,sr.reorder_quantity,
              CASE WHEN sr.id IS NOT NULL AND
                COALESCE(SUM(CASE WHEN ii.archived_at IS NULL
                  AND ii.state NOT IN ('empty','archived') THEN ii.remaining_quantity ELSE 0 END),0)
                  < sr.minimum_quantity THEN 1 ELSE 0 END has_low_stock
            FROM catalog_items ci
            JOIN item_types it ON it.id=ci.item_type_id
            JOIN manufacturers m ON m.id=ci.manufacturer_id
            LEFT JOIN inventory_instances ii ON ii.catalog_item_id=ci.id
            LEFT JOIN stock_rules sr ON sr.catalog_item_id=ci.id
            LEFT JOIN catalog_item_attribute_values mat ON mat.catalog_item_id=ci.id
              AND mat.attribute_definition_id=(
                SELECT id FROM attribute_definitions WHERE name='material')
            WHERE {' AND '.join(conditions)}
            GROUP BY ci.id ORDER BY {order}
        """
        with closing(self.connect()) as db:
            rows = [dict(row) for row in db.execute(sql, params)]
            return {
                "products": rows,
                "manufacturers": [
                    row[0]
                    for row in db.execute(
                        """SELECT DISTINCT m.name FROM manufacturers m
                        JOIN catalog_items ci ON ci.manufacturer_id=m.id
                        JOIN item_types it ON it.id=ci.item_type_id
                        WHERE it.name='Filament' ORDER BY m.name"""
                    )
                ],
                "materials": [
                    row[0]
                    for row in db.execute(
                        """SELECT DISTINCT v.text_value FROM catalog_item_attribute_values v
                        JOIN attribute_definitions a ON a.id=v.attribute_definition_id
                        JOIN catalog_items ci ON ci.id=v.catalog_item_id
                        JOIN item_types it ON it.id=ci.item_type_id
                        WHERE a.name='material' AND it.name='Filament'
                        ORDER BY v.text_value"""
                    )
                ],
            }

    def product_detail(self, product_id: int) -> dict[str, Any] | None:
        with closing(self.connect()) as db:
            product = db.execute(
                """
                SELECT ci.*,m.name manufacturer,
                  MAX(CASE WHEN ad.name='material' THEN av.text_value END) material,
                  MAX(CASE WHEN ad.name='manufacturer_color_name' THEN av.text_value END) color,
                  MAX(CASE WHEN ad.name='color_code' THEN av.text_value END) color_code,
                  MAX(CASE WHEN ad.name='diameter_mm' THEN av.numeric_value END) diameter_mm,
                  MAX(CASE WHEN ad.name='nominal_weight_g' THEN av.numeric_value END) nominal_weight_g
                FROM catalog_items ci
                JOIN item_types it ON it.id=ci.item_type_id AND it.name='Filament'
                JOIN manufacturers m ON m.id=ci.manufacturer_id
                LEFT JOIN catalog_item_attribute_values av ON av.catalog_item_id=ci.id
                LEFT JOIN attribute_definitions ad ON ad.id=av.attribute_definition_id
                WHERE ci.id=? GROUP BY ci.id
                """,
                (product_id,),
            ).fetchone()
            if not product:
                return None
            spools = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT ii.*,l.name location_name,
                      COALESCE((SELECT SUM(ra.quantity) FROM reservation_allocations ra
                        JOIN reservations r ON r.id=ra.reservation_id
                        WHERE ra.instance_id=ii.id AND r.status='active'),0) reserved_grams
                    FROM inventory_instances ii
                    LEFT JOIN locations l ON l.id=ii.location_id
                    WHERE ii.catalog_item_id=? ORDER BY ii.permanent_id
                    """,
                    (product_id,),
                )
            ]
            reserved = db.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM reservations "
                "WHERE catalog_item_id=? AND status='active'",
                (product_id,),
            ).fetchone()[0]
            rule = db.execute(
                "SELECT minimum_quantity,reorder_quantity FROM stock_rules WHERE catalog_item_id=?",
                (product_id,),
            ).fetchone()
            result = dict(product)
            result["spools"] = spools
            result["physical_spools"] = len(spools)
            result["nominal_total_grams"] = sum(s["original_quantity"] for s in spools)
            result["remaining_grams"] = sum(
                s["remaining_quantity"]
                for s in spools
                if not s["archived_at"] and s["state"] not in {"empty", "archived"}
            )
            result["reserved_grams"] = reserved
            result["available_grams"] = max(0, result["remaining_grams"] - reserved)
            result["stock_rule"] = dict(rule) if rule else None
            result["use_up_stock"] = "use-up stock" in (result["notes"] or "").lower()
            return result

    def spool_detail(self, spool_id: int) -> dict[str, Any] | None:
        with closing(self.connect()) as db:
            spool = db.execute(
                """
                SELECT ii.*,ci.product_line,ci.variant color,ci.notes product_notes,
                  m.name manufacturer,l.name location_name,
                  osr.quantity_mode,osr.remaining_quantity registered_remaining_quantity,
                  osr.quantity_confidence,osr.source registration_source,
                  osr.note registration_note,
                  MAX(CASE WHEN ad.name='material' THEN av.text_value END) material,
                  MAX(CASE WHEN ad.name='diameter_mm' THEN av.numeric_value END) diameter_mm,
                  COALESCE((SELECT SUM(ra.quantity) FROM reservation_allocations ra
                    JOIN reservations r ON r.id=ra.reservation_id
                    WHERE ra.instance_id=ii.id AND r.status='active'),0) reserved_grams
                FROM inventory_instances ii
                JOIN catalog_items ci ON ci.id=ii.catalog_item_id
                JOIN item_types it ON it.id=ci.item_type_id AND it.name='Filament'
                JOIN manufacturers m ON m.id=ci.manufacturer_id
                LEFT JOIN locations l ON l.id=ii.location_id
                LEFT JOIN open_spool_registrations osr ON osr.instance_id=ii.id
                LEFT JOIN catalog_item_attribute_values av ON av.catalog_item_id=ci.id
                LEFT JOIN attribute_definitions ad ON ad.id=av.attribute_definition_id
                WHERE ii.id=? GROUP BY ii.id
                """,
                (spool_id,),
            ).fetchone()
            if not spool:
                return None
            result = dict(spool)
            result["available_grams"] = max(
                0, result["remaining_quantity"] - result["reserved_grams"]
            )
            result["transactions"] = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT t.occurred_at,t.transaction_type,tl.quantity_change,u.code unit,
                      src.name source_location,dst.name destination_location,t.reason,t.notes,t.origin
                    FROM transaction_lines tl
                    JOIN inventory_transactions t ON t.id=tl.transaction_id
                    JOIN units u ON u.id=tl.unit_id
                    LEFT JOIN locations src ON src.id=tl.source_location_id
                    LEFT JOIN locations dst ON dst.id=tl.destination_location_id
                    WHERE tl.instance_id=? ORDER BY t.occurred_at DESC,t.id DESC
                    """,
                    (spool_id,),
                )
            ]
            return result

    def ams_status(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as db:
            units: list[dict[str, Any]] = []
            for equipment in db.execute(
                "SELECT id,name FROM equipment WHERE equipment_type='AMS' "
                "AND archived_at IS NULL ORDER BY name"
            ):
                unit = dict(equipment)
                unit["slots"] = [
                    dict(row)
                    for row in db.execute(
                        """
                        SELECT es.slot_number,aa.id assignment_id,ii.id spool_id,ii.permanent_id,
                          ii.remaining_quantity,m.name manufacturer,ci.variant color,
                          mat.text_value material,osr.quantity_mode,
                          osr.remaining_quantity registered_remaining_quantity
                        FROM equipment_slots es
                        LEFT JOIN ams_assignments aa ON aa.slot_id=es.id AND aa.unloaded_at IS NULL
                        LEFT JOIN inventory_instances ii ON ii.id=aa.instance_id
                        LEFT JOIN open_spool_registrations osr ON osr.instance_id=ii.id
                        LEFT JOIN catalog_items ci ON ci.id=ii.catalog_item_id
                        LEFT JOIN manufacturers m ON m.id=ci.manufacturer_id
                        LEFT JOIN catalog_item_attribute_values mat ON mat.catalog_item_id=ci.id
                          AND mat.attribute_definition_id=(
                            SELECT id FROM attribute_definitions WHERE name='material')
                        WHERE es.equipment_id=? ORDER BY es.slot_number
                        """,
                        (equipment["id"],),
                    )
                ]
                units.append(unit)
            return units

    def equipment_list(self) -> list[dict[str, Any]]:
        """Return stable equipment facts with separate readiness/restriction projections."""
        with closing(self.connect()) as db:
            return [
                dict(row) for row in db.execute(
                    """SELECT er.id,er.equipment_uuid,er.equipment_number,
                    er.display_name,et.type_code,et.display_name type_name,
                    es.subtype_code,es.display_name subtype_name,m.name manufacturer,
                    er.model,er.lifecycle_state,er.operational_status,
                    l.name current_location,err.readiness_state,
                    err.derived_restriction,er.state_version,er.updated_at
                    FROM equipment_registry er
                    JOIN equipment_types et ON et.id=er.equipment_type_id
                    LEFT JOIN equipment_subtypes es ON es.id=er.equipment_subtype_id
                    LEFT JOIN manufacturers m ON m.id=er.manufacturer_id
                    LEFT JOIN locations l ON l.id=er.current_location_id
                    LEFT JOIN equipment_registry_readiness err ON err.equipment_id=er.id
                    ORDER BY lower(er.display_name),er.id"""
                )
            ]

    def equipment_detail(self, equipment_id: int) -> dict[str, Any] | None:
        """Return one equipment record without reading or changing live devices."""
        with closing(self.connect()) as db:
            row = db.execute(
                """SELECT er.*,et.type_code,et.display_name type_name,
                es.subtype_code,es.display_name subtype_name,m.name manufacturer,
                l.name current_location,err.readiness_state,err.derived_restriction
                FROM equipment_registry er
                JOIN equipment_types et ON et.id=er.equipment_type_id
                LEFT JOIN equipment_subtypes es ON es.id=er.equipment_subtype_id
                LEFT JOIN manufacturers m ON m.id=er.manufacturer_id
                LEFT JOIN locations l ON l.id=er.current_location_id
                LEFT JOIN equipment_registry_readiness err ON err.equipment_id=er.id
                WHERE er.id=?""", (equipment_id,)
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["capabilities"] = [
                dict(item) for item in db.execute(
                    """SELECT ect.capability_code,ect.display_name,
                    ec.support_state,ec.source,ec.configuration_metadata,
                    ec.verified_at,ec.verified_by
                    FROM equipment_capabilities ec
                    JOIN equipment_capability_types ect
                      ON ect.id=ec.capability_type_id
                    WHERE ec.equipment_id=? ORDER BY ect.capability_code""",
                    (equipment_id,),
                )
            ]
            result["children"] = [
                dict(item) for item in db.execute(
                    """SELECT * FROM equipment_current_relationships
                    WHERE parent_equipment_id=? ORDER BY lower(child_name)""",
                    (equipment_id,),
                )
            ]
            result["parent"] = next(iter([
                dict(item) for item in db.execute(
                    """SELECT * FROM equipment_current_relationships
                    WHERE child_equipment_id=?""", (equipment_id,)
                )
            ]), None)
            result["connections"] = [
                dict(item) for item in db.execute(
                    """SELECT * FROM equipment_current_connections
                    WHERE source_equipment_id=? OR target_equipment_id=?
                    ORDER BY id""", (equipment_id, equipment_id)
                )
            ]
            telemetry = db.execute(
                """SELECT *,CASE WHEN expires_at<=CURRENT_TIMESTAMP THEN 1 ELSE 0 END
                AS stale FROM equipment_telemetry_state WHERE equipment_id=?""",
                (equipment_id,),
            ).fetchone()
            result["telemetry"] = dict(telemetry) if telemetry else None
            return result

    def equipment_relationships(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute(
                """SELECT * FROM equipment_current_relationships
                ORDER BY lower(parent_name),lower(child_name)"""
            )]

    def equipment_connections(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM equipment_current_connections ORDER BY id"
            )]

    @staticmethod
    def _low_stock_count(db: sqlite3.Connection) -> int:
        return db.execute(
            """
            SELECT COUNT(*) FROM stock_rules sr
            JOIN catalog_items ci ON ci.id=sr.catalog_item_id
            JOIN item_types it ON it.id=ci.item_type_id
            WHERE it.name='Filament' AND COALESCE((
              SELECT SUM(ii.remaining_quantity) FROM inventory_instances ii
              WHERE ii.catalog_item_id=ci.id AND ii.archived_at IS NULL
                AND ii.state NOT IN ('empty','archived')),0) < sr.minimum_quantity
            """
        ).fetchone()[0]
