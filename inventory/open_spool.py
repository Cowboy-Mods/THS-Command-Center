from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass

from .actions import ActionContext, InventoryActionError, InventoryActionService
from .db import connect


class RegisterOpenSpoolError(ValueError):
    """A legacy open-spool registration is invalid, stale, or already used."""


@dataclass(frozen=True)
class OpenSpoolReview:
    token: str
    values: dict


class RegisterExistingOpenSpoolWorkflow:
    MODULE = "register-existing-open-spool-ui"
    MAX_REVIEW_AGE_SECONDS = 30 * 60

    def __init__(self, database, secret: bytes | None = None):
        self.database = database
        self.secret = secret or secrets.token_bytes(32)

    def options(self) -> dict:
        with closing(connect(self.database)) as db:
            products = [dict(r) for r in db.execute(
                """SELECT ci.id,m.name manufacturer,ci.product_line,ci.variant color,
                MAX(CASE WHEN ad.name='material' THEN av.text_value END) material
                FROM catalog_items ci JOIN item_types it ON it.id=ci.item_type_id
                JOIN manufacturers m ON m.id=ci.manufacturer_id
                LEFT JOIN catalog_item_attribute_values av ON av.catalog_item_id=ci.id
                LEFT JOIN attribute_definitions ad ON ad.id=av.attribute_definition_id
                WHERE it.name='Filament' AND it.tracking_method='individual'
                GROUP BY ci.id HAVING material IS NOT NULL
                ORDER BY m.name,ci.product_line,ci.variant"""
            )]
            locations = [dict(r) for r in db.execute(
                """SELECT id,name FROM locations WHERE kind='storage' AND archived_at IS NULL
                ORDER BY name"""
            )]
            slots = [dict(r) for r in db.execute(
                """SELECT es.id,e.name equipment_name,es.slot_number
                FROM equipment_slots es JOIN equipment e ON e.id=es.equipment_id
                WHERE e.equipment_type='AMS' AND e.archived_at IS NULL
                AND NOT EXISTS (SELECT 1 FROM ams_assignments aa
                  WHERE aa.slot_id=es.id AND aa.unloaded_at IS NULL)
                ORDER BY e.name,es.slot_number"""
            )]
            return {"products": products, "locations": locations, "slots": slots}

    def review(self, form: dict[str, str]) -> OpenSpoolReview:
        if form.get("physical_spool_confirmed") != "yes":
            raise RegisterOpenSpoolError(
                "confirm this is one physical spool that is not already registered"
            )
        product_mode = self._text(form, "product_mode", 16)
        if product_mode not in {"existing", "new"}:
            raise RegisterOpenSpoolError("select an existing or new filament product")
        mode = self._text(form, "quantity_mode", 16)
        confidence = self._text(form, "quantity_confidence", 32)
        note = self._optional(form, "note", 1000)
        actor = self._text(form, "actor", 100)
        if mode not in {"exact", "estimated", "unknown"}:
            raise RegisterOpenSpoolError("select exact, estimated, or unknown remaining quantity")
        if mode == "exact":
            quantity = self._quantity(form)
            if confidence != "weighed":
                raise RegisterOpenSpoolError("exact grams require weighed confidence")
        elif mode == "estimated":
            quantity = self._quantity(form)
            if confidence not in {"manufacturer_estimate", "visual_estimate"}:
                raise RegisterOpenSpoolError(
                    "estimated grams require manufacturer or visual estimate confidence"
                )
            if not note:
                raise RegisterOpenSpoolError("estimated remaining quantity requires a note")
        else:
            quantity = None
            if confidence != "unknown":
                raise RegisterOpenSpoolError("unknown quantity requires unknown confidence")
            if not note:
                raise RegisterOpenSpoolError("unknown remaining quantity requires a note")
        location_type, location_id = self._location(form.get("initial_location", ""))
        with closing(connect(self.database)) as db:
            if product_mode == "existing":
                product_id = self._positive_int(
                    form, "catalog_item_id", "select a filament product"
                )
                product = self._product(db, product_id)
                if not product:
                    raise RegisterOpenSpoolError("selected filament product is unavailable")
            else:
                product = {
                    "id": None,
                    "manufacturer": self._text(form, "manufacturer", 120),
                    "product_line": self._text(form, "material", 120),
                    "material": self._text(form, "material", 120),
                    "color": self._text(form, "color", 120),
                }
            destination = self._destination(db, location_type, location_id)
            if not destination:
                raise RegisterOpenSpoolError("selected storage location or AMS slot is unavailable")
            duplicate_count = db.execute(
                """SELECT COUNT(*) FROM inventory_instances ii
                JOIN catalog_items ci ON ci.id=ii.catalog_item_id
                JOIN manufacturers m ON m.id=ci.manufacturer_id
                LEFT JOIN catalog_item_attribute_values av ON av.catalog_item_id=ci.id
                  AND av.attribute_definition_id=(
                    SELECT id FROM attribute_definitions WHERE name='material')
                WHERE lower(m.name)=lower(?) AND lower(ci.product_line)=lower(?)
                  AND lower(ci.variant)=lower(?) AND lower(av.text_value)=lower(?)
                  AND ii.archived_at IS NULL AND ii.state IN ('open','loaded')""",
                (
                    product["manufacturer"], product["product_line"],
                    product["color"], product["material"],
                ),
            ).fetchone()[0]
            duplicate_ack = form.get("duplicate_warning_ack") == "yes"
            if duplicate_count and not duplicate_ack:
                raise RegisterOpenSpoolError(
                    f"{duplicate_count} similar open or loaded spool(s) already exist; "
                    "review the warning and confirm this is a different physical spool"
                )
            filament = db.execute(
                "SELECT id,default_unit_id FROM item_types WHERE name='Filament' "
                "AND tracking_method='individual'"
            ).fetchone()
            service = InventoryActionService(
                db, ActionContext(actor, self.MODULE, "user")
            )
            values = {
                "version": 1, "reviewed_at": int(time.time()),
                "request_nonce": uuid.uuid4().hex, "module": self.MODULE,
                "actor": actor, "source": "pre_existing_inventory",
                "condition": "open", "product": product, "product_mode": product_mode,
                "item_type_id": filament["id"], "unit_id": filament["default_unit_id"],
                "permanent_id": service.preview_next_human_id(filament["id"]),
                "quantity_mode": mode, "remaining_quantity": quantity,
                "quantity_confidence": confidence, "note": note,
                "location_type": location_type, "destination": destination,
                "duplicate_warning_count": duplicate_count,
                "duplicate_warning_acknowledged": duplicate_ack,
            }
        return OpenSpoolReview(self._sign(values), values)

    def commit(self, token: str) -> dict:
        values = self._verify(token)
        db = connect(self.database)
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM open_spool_registrations WHERE request_nonce=?",
                (values["request_nonce"],),
            ).fetchone():
                raise RegisterOpenSpoolError("this registration preview was already used")
            product = (
                self._product(db, values["product"]["id"])
                if values["product_mode"] == "existing" else values["product"]
            )
            destination = self._destination(
                db, values["location_type"], values["destination"]["id"]
            )
            if product != values["product"] or destination != values["destination"]:
                raise RegisterOpenSpoolError(
                    "product or destination changed after preview; review again"
                )
            context = ActionContext(values["actor"], self.MODULE, "user")
            service = InventoryActionService(db, context)
            if service.preview_next_human_id(values["item_type_id"]) != values["permanent_id"]:
                raise RegisterOpenSpoolError(
                    "inventory changed after preview; review the current THS-FIL ID"
                )
            if values["product_mode"] == "existing":
                product_id = product["id"]
                product_created = False
            else:
                maker_id = service.ensure_manufacturer(product["manufacturer"])
                product_id, product_created = service.ensure_catalog_item(
                    values["item_type_id"], maker_id,
                    f'{product["material"]} Filament', product["product_line"],
                    product["color"], values["unit_id"],
                    notes="Catalog identity created for pre-existing open inventory; nominal weight unknown.",
                )
                service.ensure_catalog_item_attribute(
                    product_id, "material", product["material"]
                )
                service.ensure_catalog_item_attribute(
                    product_id, "manufacturer_color_name", product["color"]
                )
            stored_quantity = values["remaining_quantity"] or 0
            instance_id = service.add_individual_instance(
                product_id, state="open",
                location_id=(
                    values["destination"]["id"]
                    if values["location_type"] == "storage" else None
                ),
                original_quantity=stored_quantity, remaining_quantity=stored_quantity,
                unit_id=values["unit_id"], permanent_id=values["permanent_id"],
                condition="open", verified=True,
                reason="Pre-existing inventory",
                notes=self._instance_note(values),
            )
            load_action_id = None
            if values["location_type"] == "ams":
                load_action_id = service.load_instance_into_ams(
                    instance_id, values["destination"]["id"],
                    reason="Initial location for pre-existing inventory",
                )
            registration_id = db.execute(
                """INSERT INTO open_spool_registrations(
                registration_uuid,request_nonce,instance_id,catalog_item_id,quantity_mode,
                remaining_quantity,quantity_confidence,source,note,initial_location_type,
                initial_location_id,initial_slot_id,duplicate_warning_count,
                duplicate_warning_acknowledged,actor)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), values["request_nonce"], instance_id,
                    product_id, values["quantity_mode"],
                    values["remaining_quantity"], values["quantity_confidence"],
                    values["source"], values["note"], values["location_type"],
                    values["destination"]["id"] if values["location_type"] == "storage" else None,
                    values["destination"]["id"] if values["location_type"] == "ams" else None,
                    values["duplicate_warning_count"],
                    int(values["duplicate_warning_acknowledged"]), values["actor"],
                ),
            ).lastrowid
            add_action = db.execute(
                "SELECT id FROM inventory_actions WHERE affected_entity_id=? "
                "AND action_type='add_individual_instance' ORDER BY id DESC LIMIT 1",
                (instance_id,),
            ).fetchone()["id"]
            db.commit()
            return {
                **values, "instance_id": instance_id, "registration_id": registration_id,
                "catalog_item_id": product_id, "product_created": product_created,
                "add_action_id": add_action, "load_action_id": load_action_id,
            }
        except (InventoryActionError, sqlite3.IntegrityError) as exc:
            db.rollback()
            raise RegisterOpenSpoolError(str(exc)) from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _product(db, product_id: int) -> dict | None:
        row = db.execute(
            """SELECT ci.id,m.name manufacturer,ci.product_line,ci.variant color,
            MAX(CASE WHEN ad.name='material' THEN av.text_value END) material
            FROM catalog_items ci JOIN item_types it ON it.id=ci.item_type_id
            JOIN manufacturers m ON m.id=ci.manufacturer_id
            LEFT JOIN catalog_item_attribute_values av ON av.catalog_item_id=ci.id
            LEFT JOIN attribute_definitions ad ON ad.id=av.attribute_definition_id
            WHERE ci.id=? AND it.name='Filament' AND it.tracking_method='individual'
            GROUP BY ci.id HAVING material IS NOT NULL""", (product_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _destination(db, kind: str, row_id: int) -> dict | None:
        if kind == "storage":
            row = db.execute(
                "SELECT id,name FROM locations WHERE id=? AND kind='storage' "
                "AND archived_at IS NULL", (row_id,)
            ).fetchone()
            return dict(row) if row else None
        row = db.execute(
            """SELECT es.id,e.name equipment_name,es.slot_number
            FROM equipment_slots es JOIN equipment e ON e.id=es.equipment_id
            WHERE es.id=? AND e.equipment_type='AMS' AND e.archived_at IS NULL
            AND NOT EXISTS (SELECT 1 FROM ams_assignments aa
              WHERE aa.slot_id=es.id AND aa.unloaded_at IS NULL)""", (row_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _location(raw: str) -> tuple[str, int]:
        try:
            kind, text_id = str(raw).split(":", 1)
            row_id = int(text_id)
            if kind not in {"storage", "ams"} or row_id <= 0:
                raise ValueError
            return kind, row_id
        except (TypeError, ValueError) as exc:
            raise RegisterOpenSpoolError("select an initial storage location or AMS slot") from exc

    @staticmethod
    def _instance_note(values: dict) -> str:
        quantity = (
            "unknown" if values["remaining_quantity"] is None
            else f'{values["remaining_quantity"]:g} g'
        )
        parts = [
            "Registered as pre-existing open inventory.",
            f"Remaining quantity: {quantity} ({values['quantity_mode']}; "
            f"{values['quantity_confidence'].replace('_', ' ')}).",
        ]
        if values["note"]:
            parts.append(values["note"])
        return " ".join(parts)

    def _sign(self, values: dict) -> str:
        body = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self.secret, body, hashlib.sha256).digest()
        return self._b64(body) + "." + self._b64(signature)

    def _verify(self, token: str) -> dict:
        try:
            body_text, signature_text = token.split(".", 1)
            body = self._unb64(body_text)
            signature = self._unb64(signature_text)
            if not hmac.compare_digest(
                signature, hmac.new(self.secret, body, hashlib.sha256).digest()
            ):
                raise ValueError
            values = json.loads(body)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RegisterOpenSpoolError("registration preview is invalid; start again") from exc
        if values.get("version") != 1 or values.get("module") != self.MODULE:
            raise RegisterOpenSpoolError("registration preview is invalid; start again")
        if time.time() - values.get("reviewed_at", 0) > self.MAX_REVIEW_AGE_SECONDS:
            raise RegisterOpenSpoolError("registration preview expired; start again")
        return values

    @staticmethod
    def _quantity(form: dict[str, str]) -> float:
        try:
            value = float(form.get("remaining_quantity", ""))
            if value < 0:
                raise ValueError
            return value
        except (TypeError, ValueError) as exc:
            raise RegisterOpenSpoolError("remaining grams must be zero or greater") from exc

    @staticmethod
    def _text(form: dict[str, str], key: str, limit: int) -> str:
        value = str(form.get(key, "")).strip()
        if not value or len(value) > limit or any(ord(c) < 32 for c in value):
            raise RegisterOpenSpoolError(f"{key.replace('_', ' ')} is required or invalid")
        return value

    @classmethod
    def _optional(cls, form, key, limit):
        return cls._text(form, key, limit) if str(form.get(key, "")).strip() else None

    @staticmethod
    def _positive_int(form, key, message):
        try:
            value = int(form.get(key, ""))
            if value <= 0:
                raise ValueError
            return value
        except (TypeError, ValueError) as exc:
            raise RegisterOpenSpoolError(message) from exc

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    @staticmethod
    def _unb64(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
