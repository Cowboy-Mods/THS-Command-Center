from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
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
            )
            self._audit(
                "add_individual_instance", "inventory_instance", row_id, human_id,
                None, self._row("inventory_instances", row_id), True,
                reverse_action="archive_instance", reason=reason, transaction_id=tx,
            )
            return row_id

        return self._atomic(work)

    def add_stock_lot(
        self, catalog_item_id: int, *, location_id: int, quantity: float, unit_id: int,
        lot_number: str | None = None, condition: str = "new", expires_at: str | None = None,
        verified: bool = False, reason: str | None = None,
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
        if previous["archived_at"] or previous["state"] in {"empty", "archived"}:
            raise InventoryActionError("archived or empty inventory cannot be loaded")
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
            )
            self.db.execute(
                "INSERT INTO ams_assignments(slot_id,instance_id,load_transaction_id) VALUES (?,?,?)",
                (slot_id, instance_id, tx),
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
            )

        return self._atomic(work)

    def unload_instance_from_ams(
        self, instance_id: int, destination_location_id: int, *,
        reason: str | None = None, reverses_action_id: int | None = None,
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
    ) -> int:
        return self.db.execute(
            """INSERT INTO inventory_actions(action_uuid,actor,module,origin,action_type,reason,
            reversible,reverse_action,affected_entity_type,affected_entity_id,affected_human_id,
            previous_state,new_state,transaction_id,reverses_action_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()), self.context.actor, self.context.module, self.context.origin,
                action_type, reason, int(reversible), reverse_action, entity_type, entity_id,
                human_id, self._json(previous), self._json(new), transaction_id,
                reverses_action_id,
            ),
        ).lastrowid

    def _transaction(
        self, transaction_type: str, reason: str | None, catalog_item_id: int,
        unit_id: int, quantity_change: float, *, instance_id: int | None = None,
        stock_lot_id: int | None = None, source_location_id: int | None = None,
        destination_location_id: int | None = None,
    ) -> int:
        tx = self.db.execute(
            "INSERT INTO inventory_transactions(transaction_type,reason,origin,actor) "
            "VALUES (?,?,?,?)",
            (transaction_type, reason, self._transaction_origin(), self.context.actor),
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

