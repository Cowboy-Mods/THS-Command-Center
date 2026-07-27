from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


class InventoryActionError(ValueError):
    """A requested inventory mutation violates inventory business rules."""


@dataclass(frozen=True)
class ActionContext:
    actor: str
    module: str
    origin: str

    def __post_init__(self):
        if not self.actor.strip():
            raise InventoryActionError("actor is required")
        if not self.module.strip():
            raise InventoryActionError("module is required")
        if self.origin not in {
            "user", "maeve", "importer", "system", "api", "integration", "project"
        }:
            raise InventoryActionError("invalid action origin")


class InventoryActionService:
    """The sole normal write boundary for inventory and catalog mutations."""

    def __init__(self, db: sqlite3.Connection, context: ActionContext):
        self.db = db
        self.context = context

    def ensure_category(self, name: str, description: str | None = None) -> int:
        existing = self.db.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()
        if existing:
            return existing["id"]

        def work():
            row_id = self.db.execute(
                "INSERT INTO categories(name,description) VALUES (?,?)", (name, description)
            ).lastrowid
            new = self._row("categories", row_id)
            self._audit("create_category", "category", row_id, name, None, new, False)
            return row_id

        return self._atomic(work)

    def ensure_item_type(
        self, category_id: int, name: str, tracking_method: str, default_unit_id: int,
        id_prefix: str | None = None,
    ) -> int:
        existing = self.db.execute(
            "SELECT id,tracking_method FROM item_types WHERE name=?", (name,)
        ).fetchone()
        if existing:
            if existing["tracking_method"] != tracking_method:
                raise InventoryActionError(
                    f"item type {name} uses {existing['tracking_method']} tracking"
                )
            return existing["id"]
        if tracking_method not in {"individual", "quantity", "lot"}:
            raise InventoryActionError("invalid tracking method")
        self._require("categories", category_id, "category")
        self._require("units", default_unit_id, "unit")

        def work():
            row_id = self.db.execute(
                "INSERT INTO item_types(category_id,name,tracking_method,id_prefix,default_unit_id) "
                "VALUES (?,?,?,?,?)",
                (category_id, name, tracking_method, id_prefix, default_unit_id),
            ).lastrowid
            self._audit(
                "create_item_type", "item_type", row_id, name, None,
                self._row("item_types", row_id), False,
            )
            return row_id

        return self._atomic(work)

    def ensure_manufacturer(self, name: str) -> int:
        existing = self.db.execute("SELECT id FROM manufacturers WHERE name=?", (name,)).fetchone()
        if existing:
            return existing["id"]

        def work():
            row_id = self.db.execute(
                "INSERT INTO manufacturers(name) VALUES (?)", (name,)
            ).lastrowid
            self._audit(
                "create_manufacturer", "manufacturer", row_id, name, None,
                self._row("manufacturers", row_id), False,
            )
            return row_id

        return self._atomic(work)

    def ensure_catalog_item(
        self, item_type_id: int, manufacturer_id: int | None, name: str,
        product_line: str, variant: str, base_unit_id: int, notes: str | None = None,
    ) -> tuple[int, bool]:
        existing = self.db.execute(
            "SELECT id FROM catalog_items WHERE item_type_id=? AND manufacturer_id IS ? "
            "AND name=? AND product_line=? AND variant=?",
            (item_type_id, manufacturer_id, name, product_line, variant),
        ).fetchone()
        if existing:
            return existing["id"], False
        self._require("item_types", item_type_id, "item type")
        self._require("units", base_unit_id, "unit")

        def work():
            row_id = self.db.execute(
                "INSERT INTO catalog_items(item_type_id,manufacturer_id,name,product_line,variant,"
                "base_unit_id,notes) VALUES (?,?,?,?,?,?,?)",
                (item_type_id, manufacturer_id, name, product_line, variant, base_unit_id, notes),
            ).lastrowid
            human = " ".join(part for part in (name, product_line, variant) if part)
            self._audit(
                "create_catalog_item", "catalog_item", row_id, human, None,
                self._row("catalog_items", row_id), False,
            )
            return row_id, True

        return self._atomic(work)

    def ensure_catalog_item_attribute(
        self, catalog_item_id: int, attribute_name: str, value: str | float,
    ) -> int:
        definition = self.db.execute(
            """SELECT ad.id,ad.data_type FROM attribute_definitions ad
            JOIN item_type_attributes ita ON ita.attribute_definition_id=ad.id
            JOIN catalog_items ci ON ci.item_type_id=ita.item_type_id
            WHERE ci.id=? AND ad.name=?""",
            (catalog_item_id, attribute_name),
        ).fetchone()
        if not definition:
            raise InventoryActionError("attribute is not configured for this catalog item type")
        column = "numeric_value" if definition["data_type"] == "decimal" else "text_value"
        normalized = float(value) if column == "numeric_value" else str(value).strip()
        if column == "text_value" and not normalized:
            raise InventoryActionError(f"{attribute_name} is required")
        existing = self.db.execute(
            "SELECT text_value,numeric_value FROM catalog_item_attribute_values "
            "WHERE catalog_item_id=? AND attribute_definition_id=?",
            (catalog_item_id, definition["id"]),
        ).fetchone()
        if existing:
            current = existing[column]
            if current != normalized:
                raise InventoryActionError(
                    f"existing catalog product has a different {attribute_name}"
                )
            return definition["id"]

        def work():
            self.db.execute(
                f"INSERT INTO catalog_item_attribute_values"
                f"(catalog_item_id,attribute_definition_id,{column}) VALUES (?,?,?)",
                (catalog_item_id, definition["id"], normalized),
            )
            new = {
                "catalog_item_id": catalog_item_id,
                "attribute_definition_id": definition["id"],
                "attribute_name": attribute_name, column: normalized,
            }
            self._audit(
                "create_catalog_item_attribute", "catalog_item", catalog_item_id,
                str(catalog_item_id), None, new, False,
            )
            return definition["id"]

        return self._atomic(work)

    def preview_next_human_id(self, item_type_id: int) -> str:
        row = self.db.execute(
            "SELECT id_prefix FROM item_types WHERE id=?", (item_type_id,)
        ).fetchone()
        if not row or not row["id_prefix"]:
            raise InventoryActionError("item type does not generate permanent IDs")
        return self._next_id_for_prefix(row["id_prefix"])

    def add_individual_instance(
        self, catalog_item_id: int, *, state: str, location_id: int | None,
        original_quantity: float, remaining_quantity: float, unit_id: int,
        permanent_id: str | None = None, serial_number: str | None = None,
        lot_number: str | None = None, condition: str = "new", expires_at: str | None = None,
        notes: str | None = None, verified: bool = False, reason: str | None = None,
        order_ref: str | None = None, action_uuid: str | None = None,
    ) -> int:
        self._require_tracking(catalog_item_id, "individual")
        self._validate_quantities(original_quantity, remaining_quantity)
        if location_id is not None:
            self._require("locations", location_id, "location")
        self._require("units", unit_id, "unit")

        def work():
            human_id = permanent_id or self._next_human_id(catalog_item_id)
            row_id = self.db.execute(
                "INSERT INTO inventory_instances(permanent_id,catalog_item_id,state,condition,"
                "serial_number,lot_number,location_id,original_quantity,remaining_quantity,unit_id,"
                "expires_at,notes,verified) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    human_id, catalog_item_id, state, condition, serial_number, lot_number,
                    location_id, original_quantity, remaining_quantity, unit_id, expires_at,
                    notes, int(verified),
                ),
            ).lastrowid
            tx = self._transaction(
                "add", reason, catalog_item_id, unit_id, original_quantity,
                instance_id=row_id, destination_location_id=location_id,
                order_ref=order_ref,
            )
            self._audit(
                "add_individual_instance", "inventory_instance", row_id, human_id,
                None, self._row("inventory_instances", row_id), True,
                reverse_action="archive_instance", reason=reason, transaction_id=tx,
                action_uuid=action_uuid,
            )
            return row_id

        return self._atomic(work)

    def create_order(
        self, *, supplier: str, description: str, expected_quantity: int,
        unit_label: str, state: str = "ordered", catalog_item_id: int | None = None,
        material: str | None = None, color: str | None = None,
        notes: str | None = None, reason: str | None = None,
    ) -> int:
        if state != "ordered":
            raise InventoryActionError("new orders must begin in Ordered state")
        if expected_quantity <= 0:
            raise InventoryActionError("expected quantity must be positive")
        if not supplier.strip() or not description.strip() or not unit_label.strip():
            raise InventoryActionError("supplier, description, and unit label are required")
        if catalog_item_id is not None:
            self._tracking(catalog_item_id)

        def work():
            maximum = self.db.execute(
                "SELECT MAX(CAST(SUBSTR(order_number,9) AS INTEGER)) FROM orders "
                "WHERE order_number LIKE 'THS-ORD-%'"
            ).fetchone()[0] or 0
            order_number = f"THS-ORD-{maximum + 1:06d}"
            order_id = self.db.execute(
                """INSERT INTO orders(order_number,supplier,description,catalog_item_id,
                expected_quantity,unit_label,material,color,state,notes)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    order_number, supplier.strip(), description.strip(), catalog_item_id,
                    expected_quantity, unit_label.strip(), material, color, state, notes,
                ),
            ).lastrowid
            self._audit(
                "create_order", "order", order_id, order_number, None,
                self._row("orders", order_id), False, reason=reason,
            )
            return order_id

        return self._atomic(work)

    def transition_order(
        self, order_id: int, new_state: str, *, reason: str | None = None,
    ) -> int:
        previous = self._row("orders", order_id)
        if not previous:
            raise InventoryActionError("order not found")
        allowed = {
            "ordered": {"shipped", "cancelled"},
            "shipped": {"delivered", "cancelled"},
            "delivered": set(),
            "received": set(),
            "cancelled": set(),
        }
        if new_state not in allowed[previous["state"]]:
            raise InventoryActionError(
                f"order cannot transition from {previous['state']} to {new_state}"
            )
        timestamp_column = {
            "shipped": "shipped_at", "delivered": "delivered_at",
            "cancelled": "cancelled_at",
        }[new_state]

        def work():
            self.db.execute(
                f"UPDATE orders SET state=?,{timestamp_column}=CURRENT_TIMESTAMP,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_state, order_id),
            )
            return self._audit(
                "transition_order", "order", order_id, previous["order_number"],
                previous, self._row("orders", order_id), False, reason=reason,
            )

        return self._atomic(work)

    def receive_order(
        self, order_id: int, *, actual_quantity: int, condition: str,
        location_id: int, reason: str | None = None, note: str | None = None,
        request_nonce: str | None = None, batch_uuid: str | None = None,
        permanent_ids: list[str] | None = None,
        physical_receipt_date: str | None = None,
        physical_receipt_time: str | None = None,
        receipt_time_precision: str = "unknown",
        evidence_links: list[dict] | None = None,
    ) -> dict:
        order = self._row("orders", order_id)
        if not order or order["state"] not in {"ordered", "shipped", "delivered"}:
            raise InventoryActionError("only an active pending order can be received")
        if actual_quantity <= 0:
            raise InventoryActionError("verified received quantity must be positive")
        outstanding = order["expected_quantity"] - order["received_quantity"]
        if outstanding <= 0:
            raise InventoryActionError("order is already fully received")
        if actual_quantity != outstanding:
            raise InventoryActionError(
                "full-order receipt quantity must exactly equal the outstanding quantity"
            )
        if not batch_uuid or not request_nonce:
            raise InventoryActionError("preview-bound receipt identities are required")
        if not permanent_ids or len(permanent_ids) != actual_quantity:
            raise InventoryActionError("preview-bound permanent IDs are required")
        if receipt_time_precision not in {"exact", "estimated", "date_only", "unknown"}:
            raise InventoryActionError("receipt-time precision is invalid")
        if receipt_time_precision == "date_only" and (
            not physical_receipt_date or physical_receipt_time is not None
        ):
            raise InventoryActionError("date-only receipt requires a date and no physical time")
        if receipt_time_precision in {"exact", "estimated"} and (
            not physical_receipt_date or not physical_receipt_time
        ):
            raise InventoryActionError("timed receipt requires physical date and time")
        evidence_links = evidence_links or []
        if not evidence_links:
            raise InventoryActionError("delivery evidence is required")
        if condition not in {"new", "good", "damaged"}:
            raise InventoryActionError("verified condition is invalid")
        if not order["catalog_item_id"]:
            raise InventoryActionError("order is not linked to a catalog product")
        self._require_tracking(order["catalog_item_id"], "individual")
        self._require("locations", location_id, "location")
        product = self.db.execute(
            """SELECT ci.id,ci.base_unit_id,m.name manufacturer,
            MAX(CASE WHEN ad.name='nominal_weight_g' THEN av.numeric_value END) nominal_weight_g
            FROM catalog_items ci JOIN manufacturers m ON m.id=ci.manufacturer_id
            LEFT JOIN catalog_item_attribute_values av ON av.catalog_item_id=ci.id
            LEFT JOIN attribute_definitions ad ON ad.id=av.attribute_definition_id
            WHERE ci.id=? GROUP BY ci.id""",
            (order["catalog_item_id"],),
        ).fetchone()
        if not product or not product["nominal_weight_g"]:
            raise InventoryActionError("ordered filament product lacks nominal weight")

        def work():
            batch_id = self.db.execute(
                """INSERT INTO receiving_batches(
                batch_uuid,order_id,actor,actual_quantity,condition,note,
                physical_receipt_date,physical_receipt_time,receipt_time_precision,recorded_at)
                VALUES (?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                (
                    batch_uuid, order_id, self.context.actor, actual_quantity, condition, note,
                    physical_receipt_date, physical_receipt_time, receipt_time_precision,
                ),
            ).lastrowid
            instance_ids = []
            action_ids = []
            for permanent_id in permanent_ids:
                instance_id = self.add_individual_instance(
                    order["catalog_item_id"], state="sealed", location_id=location_id,
                    original_quantity=product["nominal_weight_g"],
                    remaining_quantity=product["nominal_weight_g"],
                    unit_id=product["base_unit_id"], condition=condition,
                    permanent_id=permanent_id,
                    verified=True, reason=reason or f"Receive {order['order_number']}",
                    order_ref=order["order_number"],
                )
                self.db.execute(
                    """INSERT INTO order_received_instances(
                    order_id,receiving_batch_id,instance_id) VALUES (?,?,?)""",
                    (order_id, batch_id, instance_id),
                )
                action = self.db.execute(
                    "SELECT id FROM inventory_actions WHERE affected_entity_type="
                    "'inventory_instance' AND affected_entity_id=? ORDER BY id DESC LIMIT 1",
                    (instance_id,),
                ).fetchone()
                instance_ids.append(instance_id)
                action_ids.append(action["id"])
            evidence_link_ids = []
            for link in evidence_links:
                evidence_link_ids.append(self.db.execute(
                    """INSERT INTO receiving_batch_delivery_evidence(
                    link_uuid,receiving_batch_id,evidence_id) VALUES (?,?,?)""",
                    (link["link_uuid"], batch_id, link["evidence_id"]),
                ).lastrowid)
            total_received = order["received_quantity"] + actual_quantity
            self.db.execute(
                """UPDATE orders SET received_quantity=?,state=?,
                received_at=CURRENT_TIMESTAMP,
                physical_received_date=?,physical_received_time=?,receipt_time_precision=?,
                updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (total_received, "received", physical_receipt_date,
                 physical_receipt_time, receipt_time_precision, order_id),
            )
            batch = self._row("receiving_batches", batch_id)
            batch_action_id = self._audit(
                "receive_order_batch", "order", order_id, order["order_number"],
                order, {"order": self._row("orders", order_id), "batch": batch},
                False, reason=reason, request_nonce=request_nonce,
            )
            return {
                "order_id": order_id, "order_number": order["order_number"],
                "batch_id": batch_id, "batch_uuid": batch["batch_uuid"],
                "instance_ids": instance_ids, "instance_action_ids": action_ids,
                "evidence_link_ids": evidence_link_ids,
                "batch_action_id": batch_action_id,
                "actual_quantity": actual_quantity, "total_received": total_received,
                "remaining_quantity": 0, "state": "received",
                "manufacturer": product["manufacturer"],
            }

        return self._atomic(work)

    def update_printer_status(
        self, printer_id: int, *, status: str, source: str,
        active_job_name: str | None = None, progress_percent: float | None = None,
        current_layer: int | None = None, total_layers: int | None = None,
        estimated_finish_at: str | None = None, current_plate: str | None = None,
        loaded_ams_slots: str | None = None, current_filament: str | None = None,
        warning_message: str | None = None, reason: str | None = None,
    ) -> int:
        previous = self._row("printers", printer_id)
        if not previous:
            raise InventoryActionError("printer not found")
        if status not in {"offline", "idle", "printing", "paused", "error", "maintenance"}:
            raise InventoryActionError("invalid printer status")
        if source not in {"manual", "import", "bambu_local", "system"}:
            raise InventoryActionError("invalid printer status source")
        if progress_percent is not None and not 0 <= progress_percent <= 100:
            raise InventoryActionError("printer progress must be between 0 and 100")
        if current_layer is not None and current_layer < 0:
            raise InventoryActionError("current layer cannot be negative")
        if total_layers is not None and total_layers <= 0:
            raise InventoryActionError("total layers must be positive")

        def work():
            self.db.execute(
                """UPDATE printers SET status=?,active_job_name=?,progress_percent=?,
                current_layer=?,total_layers=?,estimated_finish_at=?,current_plate=?,
                loaded_ams_slots=?,current_filament=?,status_source=?,
                last_update_at=CURRENT_TIMESTAMP,warning_message=?,
                updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (
                    status, active_job_name, progress_percent, current_layer, total_layers,
                    estimated_finish_at, current_plate, loaded_ams_slots, current_filament,
                    source, warning_message, printer_id,
                ),
            )
            return self._audit(
                "update_printer_status", "printer", printer_id, previous["name"],
                previous, self._row("printers", printer_id), False, reason=reason,
            )

        return self._atomic(work)

    def add_stock_lot(
        self, catalog_item_id: int, *, location_id: int, quantity: float, unit_id: int,
        lot_number: str | None = None, condition: str = "new", expires_at: str | None = None,
        verified: bool = False, reason: str | None = None,
        action_uuid: str | None = None,
    ) -> int:
        policy = self._tracking(catalog_item_id)
        if policy not in {"quantity", "lot"}:
            raise InventoryActionError("item type requires individual inventory instances")
        if quantity < 0:
            raise InventoryActionError("quantity cannot be negative")
        self._require("locations", location_id, "location")
        self._require("units", unit_id, "unit")

        def work():
            row_id = self.db.execute(
                "INSERT INTO stock_lots(catalog_item_id,location_id,lot_number,quantity,unit_id,"
                "condition,expires_at,verified) VALUES (?,?,?,?,?,?,?,?)",
                (
                    catalog_item_id, location_id, lot_number, quantity, unit_id,
                    condition, expires_at, int(verified),
                ),
            ).lastrowid
            tx = self._transaction(
                "add", reason, catalog_item_id, unit_id, quantity,
                stock_lot_id=row_id, destination_location_id=location_id,
            )
            self._audit(
                "add_stock_lot", "stock_lot", row_id, lot_number, None,
                self._row("stock_lots", row_id), True, reverse_action="archive_stock_lot",
                reason=reason, transaction_id=tx,
                action_uuid=action_uuid,
            )
            return row_id

        return self._atomic(work)

    def move_instance(
        self, instance_id: int, destination_location_id: int, *,
        reason: str | None = None, reverses_action_id: int | None = None,
    ) -> int:
        previous = self._instance(instance_id)
        self._require("locations", destination_location_id, "location")
        if previous["archived_at"] or previous["state"] in {"empty", "archived"}:
            raise InventoryActionError("archived or empty inventory cannot be moved")
        if previous["location_id"] == destination_location_id:
            raise InventoryActionError("inventory is already at that location")

        def work():
            self.db.execute(
                "UPDATE inventory_instances SET location_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (destination_location_id, instance_id),
            )
            new = self._instance(instance_id)
            tx = self._transaction(
                "move", reason, previous["catalog_item_id"], previous["unit_id"], 0,
                instance_id=instance_id, source_location_id=previous["location_id"],
                destination_location_id=destination_location_id,
            )
            return self._audit(
                "move_instance", "inventory_instance", instance_id, previous["permanent_id"],
                previous, new, True, reverse_action="move_instance", reason=reason,
                transaction_id=tx, reverses_action_id=reverses_action_id,
            )

        return self._atomic(work)

    def correct_instance_remaining(
        self, instance_id: int, new_quantity: float, *, reason: str | None = None,
        reverses_action_id: int | None = None,
    ) -> int:
        previous = self._instance(instance_id)
        self._validate_quantities(previous["original_quantity"], new_quantity)
        if new_quantity == previous["remaining_quantity"]:
            raise InventoryActionError("remaining quantity is unchanged")

        def work():
            self.db.execute(
                "UPDATE inventory_instances SET remaining_quantity=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE id=?", (new_quantity, instance_id),
            )
            new = self._instance(instance_id)
            tx = self._transaction(
                "correct", reason, previous["catalog_item_id"], previous["unit_id"],
                new_quantity - previous["remaining_quantity"], instance_id=instance_id,
                source_location_id=previous["location_id"],
                destination_location_id=previous["location_id"],
            )
            return self._audit(
                "correct_instance_remaining", "inventory_instance", instance_id,
                previous["permanent_id"], previous, new, True,
                reverse_action="correct_instance_remaining", reason=reason,
                transaction_id=tx, reverses_action_id=reverses_action_id,
            )

        return self._atomic(work)

    def change_instance_state(
        self, instance_id: int, new_state: str, *, reason: str | None = None,
        reverses_action_id: int | None = None,
    ) -> int:
        allowed = {"sealed", "open", "loaded", "empty", "archived", "maintenance", "damaged"}
        if new_state not in allowed:
            raise InventoryActionError("invalid inventory state")
        previous = self._instance(instance_id)
        if previous["state"] == new_state:
            raise InventoryActionError("inventory state is unchanged")

        def work():
            opened = "COALESCE(opened_at,CURRENT_TIMESTAMP)" if new_state == "open" else "opened_at"
            emptied = "CURRENT_TIMESTAMP" if new_state == "empty" else "emptied_at"
            archived = "CURRENT_TIMESTAMP" if new_state in {"empty", "archived"} else "archived_at"
            remaining = "0" if new_state == "empty" else "remaining_quantity"
            self.db.execute(
                f"UPDATE inventory_instances SET state=?,opened_at={opened},emptied_at={emptied},"
                f"archived_at={archived},remaining_quantity={remaining},updated_at=CURRENT_TIMESTAMP "
                "WHERE id=?", (new_state, instance_id),
            )
            new = self._instance(instance_id)
            tx_type = "mark_empty" if new_state == "empty" else (
                "archive" if new_state == "archived" else "correct"
            )
            tx = self._transaction(
                tx_type, reason, previous["catalog_item_id"], previous["unit_id"],
                new["remaining_quantity"] - previous["remaining_quantity"],
                instance_id=instance_id, source_location_id=previous["location_id"],
                destination_location_id=new["location_id"],
            )
            reversible = new_state not in {"empty", "archived"}
            return self._audit(
                "change_instance_state", "inventory_instance", instance_id,
                previous["permanent_id"], previous, new, reversible,
                reverse_action="change_instance_state" if reversible else None,
                reason=reason, transaction_id=tx, reverses_action_id=reverses_action_id,
            )

        return self._atomic(work)

    def mark_loaded_spool_empty(
        self, instance_id: int, *, reason: str | None = None,
        workflow_transaction_id: int | None = None,
    ) -> int:
        previous = self._instance(instance_id)
        assignment = self.db.execute(
            """SELECT aa.id,aa.slot_id,es.location_id FROM ams_assignments aa
            JOIN equipment_slots es ON es.id=aa.slot_id
            WHERE aa.instance_id=? AND aa.unloaded_at IS NULL""",
            (instance_id,),
        ).fetchone()
        if previous["state"] != "loaded" or previous["archived_at"] or not assignment:
            raise InventoryActionError("current spool must be actively loaded in an AMS")

        def work():
            tx = self._transaction(
                "mark_empty", reason, previous["catalog_item_id"], previous["unit_id"],
                -previous["remaining_quantity"], instance_id=instance_id,
                source_location_id=assignment["location_id"],
            )
            self.db.execute(
                "UPDATE ams_assignments SET unloaded_at=CURRENT_TIMESTAMP,unload_transaction_id=? "
                "WHERE id=?", (tx, assignment["id"]),
            )
            self.db.execute(
                """UPDATE inventory_instances SET state='empty',remaining_quantity=0,
                emptied_at=CURRENT_TIMESTAMP,archived_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (instance_id,),
            )
            new = self._instance(instance_id)
            new["_vacated_ams_slot_id"] = assignment["slot_id"]
            return self._audit(
                "mark_spool_empty", "inventory_instance", instance_id,
                previous["permanent_id"], previous, new, False, reason=reason,
                transaction_id=tx, workflow_transaction_id=workflow_transaction_id,
            )

        return self._atomic(work)

    def open_sealed_spool(
        self, instance_id: int, *, reason: str | None = None,
        workflow_transaction_id: int | None = None,
        effective_at: str | None = None,
    ) -> int:
        previous = self._instance(instance_id)
        if previous["state"] != "sealed" or previous["archived_at"]:
            raise InventoryActionError("replacement spool must be sealed and active")
        if self.db.execute(
            "SELECT 1 FROM ams_assignments WHERE instance_id=? AND unloaded_at IS NULL",
            (instance_id,),
        ).fetchone():
            raise InventoryActionError("sealed replacement cannot already occupy an AMS slot")

        def work():
            self.db.execute(
                "UPDATE inventory_instances SET state='open',opened_at=COALESCE(?,CURRENT_TIMESTAMP),"
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (effective_at, instance_id),
            )
            new = self._instance(instance_id)
            tx = self._transaction(
                "correct", reason, previous["catalog_item_id"], previous["unit_id"], 0,
                instance_id=instance_id, source_location_id=previous["location_id"],
                destination_location_id=previous["location_id"],
                effective_at=effective_at,
            )
            return self._audit(
                "open_sealed_spool", "inventory_instance", instance_id,
                previous["permanent_id"], previous, new, True,
                reverse_action="change_instance_state", reason=reason,
                transaction_id=tx, workflow_transaction_id=workflow_transaction_id,
                effective_at=effective_at,
            )

        return self._atomic(work)

    def replace_active_filament_spool(
        self, current_instance_id: int, replacement_instance_id: int,
        destination_slot_id: int, *, reason: str | None, review_nonce: str,
        print_job_name: str | None = None, approximate_layer: int | None = None,
        printer: str | None = None, plate: str | None = None,
        operational_note: str | None = None,
    ) -> dict:
        if current_instance_id == replacement_instance_id:
            raise InventoryActionError("current and replacement spools must be different")
        if not review_nonce.strip():
            raise InventoryActionError("review nonce is required")
        current = self._instance(current_instance_id)
        replacement = self._instance(replacement_instance_id)
        assignment = self.db.execute(
            """SELECT aa.slot_id,e.name equipment_name,es.slot_number
            FROM ams_assignments aa
            JOIN equipment_slots es ON es.id=aa.slot_id
            JOIN equipment e ON e.id=es.equipment_id
            WHERE aa.instance_id=? AND aa.unloaded_at IS NULL""",
            (current_instance_id,),
        ).fetchone()
        if current["state"] != "loaded" or current["archived_at"] or not assignment:
            raise InventoryActionError("current spool must be actively loaded in an AMS")
        if replacement["state"] != "sealed" or replacement["archived_at"]:
            raise InventoryActionError("replacement spool must be sealed and active")
        if self.db.execute(
            "SELECT 1 FROM ams_assignments WHERE instance_id=? AND unloaded_at IS NULL",
            (replacement_instance_id,),
        ).fetchone():
            raise InventoryActionError("replacement spool already occupies an AMS slot")
        slot = self.db.execute(
            """SELECT es.id,e.name equipment_name,es.slot_number
            FROM equipment_slots es JOIN equipment e ON e.id=es.equipment_id
            WHERE es.id=? AND e.equipment_type='AMS' AND e.archived_at IS NULL""",
            (destination_slot_id,),
        ).fetchone()
        if not slot:
            raise InventoryActionError("destination AMS slot not found")
        occupant = self.db.execute(
            "SELECT instance_id FROM ams_assignments WHERE slot_id=? AND unloaded_at IS NULL",
            (destination_slot_id,),
        ).fetchone()
        if occupant and occupant["instance_id"] != current_instance_id:
            raise InventoryActionError("destination AMS slot is occupied by another spool")

        def work():
            workflow_id = self.db.execute(
                """INSERT INTO inventory_workflow_transactions(
                workflow_uuid,review_nonce,workflow_type,actor,module,origin,reason,
                current_instance_id,replacement_instance_id,destination_slot_id,
                print_job_name,approximate_layer,printer,plate,operational_note)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), review_nonce, "replace_active_filament_spool",
                    self.context.actor, self.context.module, self.context.origin, reason,
                    current_instance_id, replacement_instance_id, destination_slot_id,
                    print_job_name, approximate_layer, printer, plate, operational_note,
                ),
            ).lastrowid
            empty_action = self.mark_loaded_spool_empty(
                current_instance_id, reason=reason,
                workflow_transaction_id=workflow_id,
            )
            open_action = self.open_sealed_spool(
                replacement_instance_id, reason=reason,
                workflow_transaction_id=workflow_id,
            )
            load_action = self.load_instance_into_ams(
                replacement_instance_id, destination_slot_id, reason=reason,
                workflow_transaction_id=workflow_id,
            )
            return {
                "workflow_transaction_id": workflow_id,
                "empty_action_id": empty_action,
                "open_action_id": open_action,
                "load_action_id": load_action,
                "source_slot_id": assignment["slot_id"],
                "destination_slot_id": destination_slot_id,
                "destination_equipment": slot["equipment_name"],
                "destination_slot_number": slot["slot_number"],
            }

        return self._atomic(work)

    def initialize_verified_ams_state(
        self, instance_id: int, slot_id: int, *, reason: str | None,
        effective_at: str, request_nonce: str,
    ) -> dict:
        self._validate_effective_at(effective_at)
        if not request_nonce.strip():
            raise InventoryActionError("request nonce is required")
        instance = self._instance(instance_id)
        if instance["archived_at"] or instance["state"] not in {"sealed", "open"}:
            raise InventoryActionError(
                "only active sealed or open spools can initialize AMS state"
            )
        if self.db.execute(
            "SELECT 1 FROM ams_assignments WHERE instance_id=? AND unloaded_at IS NULL",
            (instance_id,),
        ).fetchone():
            raise InventoryActionError("spool already has an active AMS assignment")
        slot = self.db.execute(
            """SELECT es.id FROM equipment_slots es
            JOIN equipment e ON e.id=es.equipment_id
            WHERE es.id=? AND e.equipment_type='AMS' AND e.archived_at IS NULL""",
            (slot_id,),
        ).fetchone()
        if not slot:
            raise InventoryActionError("AMS slot not found")
        if self.db.execute(
            "SELECT 1 FROM ams_assignments WHERE slot_id=? AND unloaded_at IS NULL",
            (slot_id,),
        ).fetchone():
            raise InventoryActionError("AMS slot is occupied")

        def work():
            open_action_id = None
            if instance["state"] == "sealed":
                open_action_id = self.open_sealed_spool(
                    instance_id, reason=reason, effective_at=effective_at,
                )
            load_action_id = self.load_instance_into_ams(
                instance_id, slot_id, reason=reason, effective_at=effective_at,
                request_nonce=request_nonce,
            )
            return {
                "open_action_id": open_action_id,
                "load_action_id": load_action_id,
            }

        return self._atomic(work)

    def create_instance_reservation(
        self, instance_id: int, quantity: float, *, project_ref: str | None = None,
        reason: str | None = None,
    ) -> int:
        instance = self._instance(instance_id)
        if quantity <= 0:
            raise InventoryActionError("reservation quantity must be positive")
        active = self.db.execute(
            """SELECT COALESCE(SUM(ra.quantity),0) FROM reservation_allocations ra
            JOIN reservations r ON r.id=ra.reservation_id
            WHERE ra.instance_id=? AND r.status='active'""", (instance_id,)
        ).fetchone()[0]
        if quantity + active > instance["remaining_quantity"]:
            raise InventoryActionError("reservation exceeds available inventory")

        def work():
            reservation_id = self.db.execute(
                "INSERT INTO reservations(catalog_item_id,quantity,unit_id,project_ref) "
                "VALUES (?,?,?,?)",
                (instance["catalog_item_id"], quantity, instance["unit_id"], project_ref),
            ).lastrowid
            self.db.execute(
                "INSERT INTO reservation_allocations(reservation_id,instance_id,quantity,unit_id) "
                "VALUES (?,?,?,?)",
                (reservation_id, instance_id, quantity, instance["unit_id"]),
            )
            tx = self._transaction(
                "reserve", reason, instance["catalog_item_id"], instance["unit_id"], 0,
                instance_id=instance_id, source_location_id=instance["location_id"],
            )
            self._audit(
                "create_reservation", "reservation", reservation_id, instance["permanent_id"],
                None, self._row("reservations", reservation_id), True,
                reverse_action="release_reservation", reason=reason, transaction_id=tx,
            )
            return reservation_id

        return self._atomic(work)

    def load_instance_into_ams(
        self, instance_id: int, slot_id: int, *, reason: str | None = None,
        reverses_action_id: int | None = None,
        workflow_transaction_id: int | None = None,
        effective_at: str | None = None, request_nonce: str | None = None,
    ) -> int:
        previous = self._instance(instance_id)
        slot = self.db.execute(
            """SELECT es.id,es.location_id FROM equipment_slots es
            JOIN equipment e ON e.id=es.equipment_id
            WHERE es.id=? AND e.equipment_type='AMS' AND e.archived_at IS NULL""",
            (slot_id,),
        ).fetchone()
        if not slot:
            raise InventoryActionError("AMS slot not found")
        if previous["archived_at"] or previous["state"] != "open":
            raise InventoryActionError("only an active open spool can be loaded")
        if self.db.execute(
            "SELECT 1 FROM ams_assignments WHERE slot_id=? AND unloaded_at IS NULL", (slot_id,)
        ).fetchone():
            raise InventoryActionError("AMS slot is occupied")
        if self.db.execute(
            "SELECT 1 FROM ams_assignments WHERE instance_id=? AND unloaded_at IS NULL",
            (instance_id,),
        ).fetchone():
            raise InventoryActionError("inventory instance is already loaded in an AMS")

        def work():
            tx = self._transaction(
                "load", reason, previous["catalog_item_id"], previous["unit_id"], 0,
                instance_id=instance_id, source_location_id=previous["location_id"],
                destination_location_id=slot["location_id"],
                effective_at=effective_at,
            )
            self.db.execute(
                "INSERT INTO ams_assignments(slot_id,instance_id,loaded_at,load_transaction_id) "
                "VALUES (?,?,COALESCE(?,CURRENT_TIMESTAMP),?)",
                (slot_id, instance_id, effective_at, tx),
            )
            self.db.execute(
                "UPDATE inventory_instances SET state='loaded',location_id=?,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (slot["location_id"], instance_id),
            )
            new = self._instance(instance_id)
            new["_ams_slot_id"] = slot_id
            return self._audit(
                "load_instance_into_ams", "inventory_instance", instance_id,
                previous["permanent_id"], previous, new, True,
                reverse_action="unload_instance_from_ams", reason=reason,
                transaction_id=tx, reverses_action_id=reverses_action_id,
                workflow_transaction_id=workflow_transaction_id,
                effective_at=effective_at, request_nonce=request_nonce,
            )

        return self._atomic(work)

    def unload_instance_from_ams(
        self, instance_id: int, destination_location_id: int, *,
        reason: str | None = None, reverses_action_id: int | None = None,
        request_nonce: str | None = None,
    ) -> int:
        previous = self._instance(instance_id)
        assignment = self.db.execute(
            "SELECT id,slot_id FROM ams_assignments WHERE instance_id=? AND unloaded_at IS NULL",
            (instance_id,),
        ).fetchone()
        if not assignment:
            raise InventoryActionError("inventory instance is not loaded in an AMS")
        self._require("locations", destination_location_id, "location")
        previous["_ams_slot_id"] = assignment["slot_id"]

        def work():
            tx = self._transaction(
                "unload", reason, previous["catalog_item_id"], previous["unit_id"], 0,
                instance_id=instance_id, source_location_id=previous["location_id"],
                destination_location_id=destination_location_id,
            )
            self.db.execute(
                "UPDATE ams_assignments SET unloaded_at=CURRENT_TIMESTAMP,unload_transaction_id=? "
                "WHERE id=?", (tx, assignment["id"]),
            )
            self.db.execute(
                "UPDATE inventory_instances SET state='open',location_id=?,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (destination_location_id, instance_id),
            )
            new = self._instance(instance_id)
            return self._audit(
                "unload_instance_from_ams", "inventory_instance", instance_id,
                previous["permanent_id"], previous, new, True,
                reverse_action="load_instance_into_ams", reason=reason,
                transaction_id=tx, reverses_action_id=reverses_action_id,
                request_nonce=request_nonce,
            )

        return self._atomic(work)

    def archive_stock_lot(
        self, stock_lot_id: int, *, reason: str | None = None,
        reverses_action_id: int | None = None,
    ) -> int:
        previous = self._row("stock_lots", stock_lot_id)
        if not previous:
            raise InventoryActionError("stock lot not found")
        if previous["archived_at"]:
            raise InventoryActionError("stock lot is already archived")

        def work():
            self.db.execute(
                "UPDATE stock_lots SET archived_at=CURRENT_TIMESTAMP WHERE id=?", (stock_lot_id,)
            )
            new = self._row("stock_lots", stock_lot_id)
            tx = self._transaction(
                "archive", reason, previous["catalog_item_id"], previous["unit_id"], 0,
                stock_lot_id=stock_lot_id, source_location_id=previous["location_id"],
            )
            return self._audit(
                "archive_stock_lot", "stock_lot", stock_lot_id, previous["lot_number"],
                previous, new, False, reason=reason, transaction_id=tx,
                reverses_action_id=reverses_action_id,
            )

        return self._atomic(work)

    def release_reservation(
        self, reservation_id: int, *, reason: str | None = None,
        reverses_action_id: int | None = None,
    ) -> int:
        previous = self._row("reservations", reservation_id)
        if not previous:
            raise InventoryActionError("reservation not found")
        if previous["status"] != "active":
            raise InventoryActionError("only active reservations can be released")
        allocation = self.db.execute(
            "SELECT instance_id,stock_lot_id FROM reservation_allocations WHERE reservation_id=? "
            "ORDER BY id LIMIT 1", (reservation_id,)
        ).fetchone()

        def work():
            self.db.execute(
                "UPDATE reservations SET status='released',released_at=CURRENT_TIMESTAMP WHERE id=?",
                (reservation_id,),
            )
            tx = self.db.execute(
                "INSERT INTO inventory_transactions(transaction_type,reason,origin,actor,project_ref) "
                "VALUES ('release',?,?,?,?)",
                (reason, self._transaction_origin(), self.context.actor, previous["project_ref"]),
            ).lastrowid
            return self._audit(
                "release_reservation", "reservation", reservation_id, None, previous,
                self._row("reservations", reservation_id), False, reason=reason,
                transaction_id=tx, reverses_action_id=reverses_action_id,
            )

        return self._atomic(work)

    def reverse_action(self, action_id: int, *, reason: str | None = None) -> int:
        action = self._row("inventory_actions", action_id)
        if not action:
            raise InventoryActionError("action not found")
        if not action["reversible"]:
            raise InventoryActionError("action is not reversible")
        if self.db.execute(
            "SELECT 1 FROM inventory_actions WHERE reverses_action_id=?", (action_id,)
        ).fetchone():
            raise InventoryActionError("action has already been reversed")
        previous = json.loads(action["previous_state"]) if action["previous_state"] else None
        if action["reverse_action"] == "move_instance":
            return self.move_instance(
                action["affected_entity_id"], previous["location_id"],
                reason=reason or f"Reverse action {action_id}", reverses_action_id=action_id,
            )
        if action["reverse_action"] == "correct_instance_remaining":
            return self.correct_instance_remaining(
                action["affected_entity_id"], previous["remaining_quantity"],
                reason=reason or f"Reverse action {action_id}", reverses_action_id=action_id,
            )
        if action["reverse_action"] == "change_instance_state":
            return self.change_instance_state(
                action["affected_entity_id"], previous["state"],
                reason=reason or f"Reverse action {action_id}", reverses_action_id=action_id,
            )
        if action["reverse_action"] == "archive_instance":
            return self.change_instance_state(
                action["affected_entity_id"], "archived",
                reason=reason or f"Reverse action {action_id}", reverses_action_id=action_id,
            )
        if action["reverse_action"] == "archive_stock_lot":
            return self.archive_stock_lot(
                action["affected_entity_id"],
                reason=reason or f"Reverse action {action_id}", reverses_action_id=action_id,
            )
        if action["reverse_action"] == "release_reservation":
            return self.release_reservation(
                action["affected_entity_id"],
                reason=reason or f"Reverse action {action_id}", reverses_action_id=action_id,
            )
        if action["reverse_action"] == "unload_instance_from_ams":
            return self.unload_instance_from_ams(
                action["affected_entity_id"], previous["location_id"],
                reason=reason or f"Reverse action {action_id}", reverses_action_id=action_id,
            )
        if action["reverse_action"] == "load_instance_into_ams":
            return self.load_instance_into_ams(
                action["affected_entity_id"], previous["_ams_slot_id"],
                reason=reason or f"Reverse action {action_id}", reverses_action_id=action_id,
            )
        raise InventoryActionError(
            f"reverse action {action['reverse_action']} is recorded but not automated yet"
        )

    def _atomic(self, work: Callable[[], Any]):
        savepoint = f"inventory_action_{uuid.uuid4().hex}"
        self.db.execute(f"SAVEPOINT {savepoint}")
        try:
            result = work()
            self.db.execute(f"RELEASE {savepoint}")
            return result
        except Exception:
            self.db.execute(f"ROLLBACK TO {savepoint}")
            self.db.execute(f"RELEASE {savepoint}")
            raise

    def _audit(
        self, action_type: str, entity_type: str, entity_id: int | None,
        human_id: str | None, previous: dict | None, new: dict | None, reversible: bool,
        *, reverse_action: str | None = None, reason: str | None = None,
        transaction_id: int | None = None, reverses_action_id: int | None = None,
        workflow_transaction_id: int | None = None,
        effective_at: str | None = None, request_nonce: str | None = None,
        action_uuid: str | None = None,
    ) -> int:
        return self.db.execute(
            """INSERT INTO inventory_actions(action_uuid,occurred_at,actor,module,origin,action_type,reason,
            reversible,reverse_action,affected_entity_type,affected_entity_id,affected_human_id,
            previous_state,new_state,transaction_id,reverses_action_id,workflow_transaction_id,
            request_nonce)
            VALUES (?,COALESCE(?,CURRENT_TIMESTAMP),?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                action_uuid or str(uuid.uuid4()), effective_at, self.context.actor, self.context.module,
                self.context.origin,
                action_type, reason, int(reversible), reverse_action, entity_type, entity_id,
                human_id, self._json(previous), self._json(new), transaction_id,
                reverses_action_id, workflow_transaction_id, request_nonce,
            ),
        ).lastrowid

    def _transaction(
        self, transaction_type: str, reason: str | None, catalog_item_id: int,
        unit_id: int, quantity_change: float, *, instance_id: int | None = None,
        stock_lot_id: int | None = None, source_location_id: int | None = None,
        destination_location_id: int | None = None,
        effective_at: str | None = None, order_ref: str | None = None,
    ) -> int:
        tx = self.db.execute(
            "INSERT INTO inventory_transactions("
            "transaction_type,occurred_at,reason,origin,actor,order_ref) "
            "VALUES (?,COALESCE(?,CURRENT_TIMESTAMP),?,?,?,?)",
            (
                transaction_type, effective_at, reason,
                self._transaction_origin(), self.context.actor, order_ref,
            ),
        ).lastrowid
        self.db.execute(
            """INSERT INTO transaction_lines(transaction_id,catalog_item_id,instance_id,stock_lot_id,
            quantity_change,unit_id,source_location_id,destination_location_id)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                tx, catalog_item_id, instance_id, stock_lot_id, quantity_change, unit_id,
                source_location_id, destination_location_id,
            ),
        )
        return tx

    def _tracking(self, catalog_item_id: int) -> str:
        row = self.db.execute(
            "SELECT it.tracking_method FROM catalog_items ci "
            "JOIN item_types it ON it.id=ci.item_type_id WHERE ci.id=?",
            (catalog_item_id,),
        ).fetchone()
        if not row:
            raise InventoryActionError("catalog item not found")
        return row["tracking_method"]

    def _require_tracking(self, catalog_item_id: int, expected: str) -> None:
        actual = self._tracking(catalog_item_id)
        if actual != expected:
            raise InventoryActionError(
                f"catalog item uses {actual} tracking; {expected} tracking is required"
            )

    def _instance(self, instance_id: int) -> dict:
        row = self._row("inventory_instances", instance_id)
        if not row:
            raise InventoryActionError("inventory instance not found")
        return row

    def _require(self, table: str, row_id: int, label: str) -> None:
        if table not in {"categories", "units", "locations", "item_types"}:
            raise RuntimeError("unsupported validation table")
        if not self.db.execute(f"SELECT 1 FROM {table} WHERE id=?", (row_id,)).fetchone():
            raise InventoryActionError(f"{label} not found")

    def _row(self, table: str, row_id: int) -> dict | None:
        if table not in {
            "categories", "item_types", "manufacturers", "catalog_items",
            "inventory_instances", "stock_lots", "reservations", "inventory_actions",
            "orders", "receiving_batches", "printers",
        }:
            raise RuntimeError("unsupported snapshot table")
        row = self.db.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
        return dict(row) if row else None

    def _next_human_id(self, catalog_item_id: int) -> str | None:
        prefix = self.db.execute(
            "SELECT it.id_prefix FROM catalog_items ci JOIN item_types it ON it.id=ci.item_type_id "
            "WHERE ci.id=?", (catalog_item_id,)
        ).fetchone()[0]
        if not prefix:
            return None
        return self._next_id_for_prefix(prefix)

    def _next_id_for_prefix(self, prefix: str) -> str:
        maximum = self.db.execute(
            "SELECT MAX(CAST(SUBSTR(permanent_id,LENGTH(?)+2) AS INTEGER)) "
            "FROM inventory_instances WHERE permanent_id LIKE ?",
            (prefix, f"{prefix}-%"),
        ).fetchone()[0] or 0
        return f"{prefix}-{maximum + 1:06d}"

    @staticmethod
    def _validate_quantities(original: float, remaining: float) -> None:
        if original < 0 or remaining < 0:
            raise InventoryActionError("quantities cannot be negative")
        if remaining > original:
            raise InventoryActionError("remaining quantity cannot exceed original quantity")

    @staticmethod
    def _json(value: dict | None) -> str | None:
        return json.dumps(value, sort_keys=True, separators=(",", ":")) if value is not None else None

    def _transaction_origin(self) -> str:
        return {
            "importer": "import", "project": "project", "integration": "system",
            "api": "system", "maeve": "system", "user": "manual", "system": "system",
        }[self.context.origin]

    @staticmethod
    def _validate_effective_at(value: str) -> None:
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise InventoryActionError("effective timestamp must be valid RFC3339") from exc
        if parsed.tzinfo is None:
            raise InventoryActionError("effective timestamp must include a UTC offset")
        now = datetime.now(timezone.utc)
        if parsed.astimezone(timezone.utc) > now + timedelta(minutes=5):
            raise InventoryActionError("effective timestamp cannot be in the future")
        if parsed.year < 2000:
            raise InventoryActionError("effective timestamp is unreasonably old")
