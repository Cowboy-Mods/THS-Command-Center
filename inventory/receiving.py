from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import secrets
import sqlite3
import time
from dataclasses import dataclass
from contextlib import closing

from .actions import ActionContext, InventoryActionError, InventoryActionService


class ReceiveSpoolError(ValueError):
    """A receive-spool request is incomplete, invalid, or no longer current."""


@dataclass(frozen=True)
class ReceiveReview:
    token: str
    values: dict


class ReceiveSpoolWorkflow:
    MODULE = "filament-receiving-ui"
    MAX_REVIEW_AGE_SECONDS = 30 * 60

    def __init__(self, database, secret: bytes | None = None):
        self.database = database
        self.secret = secret or secrets.token_bytes(32)

    def options(self) -> dict:
        with closing(self._connect()) as db:
            products = db.execute(
                """SELECT ci.id,m.name manufacturer,ci.product_line,ci.variant color,
                MAX(CASE WHEN ad.name='material' THEN av.text_value END) material,
                MAX(CASE WHEN ad.name='diameter_mm' THEN av.numeric_value END) diameter_mm,
                MAX(CASE WHEN ad.name='nominal_weight_g' THEN av.numeric_value END) nominal_weight_g
                FROM catalog_items ci
                JOIN item_types it ON it.id=ci.item_type_id
                JOIN manufacturers m ON m.id=ci.manufacturer_id
                LEFT JOIN catalog_item_attribute_values av ON av.catalog_item_id=ci.id
                LEFT JOIN attribute_definitions ad ON ad.id=av.attribute_definition_id
                WHERE it.name='Filament' AND it.tracking_method='individual'
                GROUP BY ci.id ORDER BY m.name,ci.product_line,ci.variant"""
            ).fetchall()
            locations = db.execute(
                "SELECT id,name FROM locations WHERE kind='storage' AND archived_at IS NULL "
                "ORDER BY CASE name WHEN 'Sealed Filament Rack' THEN 0 ELSE 1 END,name"
            ).fetchall()
            return {
                "products": [dict(row) for row in products],
                "locations": [dict(row) for row in locations],
            }

    def review(self, form: dict[str, str]) -> ReceiveReview:
        mode = self._text(form, "product_mode", 16).lower()
        if mode not in {"existing", "new"}:
            raise ReceiveSpoolError("select an existing product or create a verified product")
        actor = self._text(form, "actor", 100)
        reason = self._optional(form, "reason", 500)
        location_id = self._positive_int(form, "location_id", "select an initial location")

        with closing(self._connect()) as db:
            location = db.execute(
                "SELECT id,name,kind FROM locations WHERE id=? AND archived_at IS NULL",
                (location_id,),
            ).fetchone()
            if not location or location["kind"] != "storage":
                raise ReceiveSpoolError("initial location must be an active storage location")
            filament = db.execute(
                "SELECT id,default_unit_id FROM item_types "
                "WHERE name='Filament' AND tracking_method='individual'"
            ).fetchone()
            if not filament:
                raise ReceiveSpoolError("the individual-tracked Filament item type is unavailable")
            action = InventoryActionService(
                db, ActionContext(actor=actor, module=self.MODULE, origin="user")
            )
            permanent_id = action.preview_next_human_id(filament["id"])
            if mode == "existing":
                product_id = self._positive_int(
                    form, "catalog_item_id", "select a catalog product"
                )
                product = self._product(db, product_id)
                if not product:
                    raise ReceiveSpoolError(
                        "catalog product is not a complete individual-tracked filament product"
                    )
                product_values = dict(product)
            else:
                product_values = {
                    "id": None,
                    "manufacturer": self._text(form, "manufacturer", 120),
                    "product_line": self._text(form, "product_line", 120),
                    "material": self._text(form, "material", 80),
                    "color": self._text(form, "color", 120),
                    "diameter_mm": self._decimal(form, "diameter_mm", 1, 10, "diameter"),
                    "nominal_weight_g": self._decimal(
                        form, "nominal_weight_g", 1, 100000, "nominal weight"
                    ),
                }
            values = {
                "version": 1,
                "reviewed_at": int(time.time()),
                "product_mode": mode,
                **product_values,
                "item_type_id": filament["id"],
                "unit_id": filament["default_unit_id"],
                "location_id": location["id"],
                "location": location["name"],
                "state": "sealed",
                "condition": "new",
                "permanent_id": permanent_id,
                "actor": actor,
                "module": self.MODULE,
                "reason": reason,
            }
        return ReceiveReview(self._sign(values), values)

    def commit(self, token: str) -> dict:
        values = self._verify(token)
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            context = ActionContext(
                actor=values["actor"], module=self.MODULE, origin="user"
            )
            actions = InventoryActionService(db, context)
            if actions.preview_next_human_id(values["item_type_id"]) != values["permanent_id"]:
                raise ReceiveSpoolError(
                    "inventory changed after preview; review again for the current THS-FIL ID"
                )
            if values["product_mode"] == "existing":
                current = self._product(db, values["id"])
                if not current or any(
                    current[key] != values[key]
                    for key in (
                        "manufacturer", "product_line", "material", "color",
                        "diameter_mm", "nominal_weight_g",
                    )
                ):
                    raise ReceiveSpoolError(
                        "catalog product changed after preview; review it again"
                    )
                product_id = values["id"]
                product_created = False
            else:
                maker_id = actions.ensure_manufacturer(values["manufacturer"])
                product_id, product_created = actions.ensure_catalog_item(
                    values["item_type_id"], maker_id,
                    f'{values["material"]} Filament', values["product_line"],
                    values["color"], values["unit_id"],
                )
                for name in (
                    "material", "manufacturer_color_name", "diameter_mm", "nominal_weight_g"
                ):
                    key = "color" if name == "manufacturer_color_name" else name
                    actions.ensure_catalog_item_attribute(product_id, name, values[key])
            instance_id = actions.add_individual_instance(
                product_id,
                state="sealed",
                location_id=values["location_id"],
                original_quantity=values["nominal_weight_g"],
                remaining_quantity=values["nominal_weight_g"],
                unit_id=values["unit_id"],
                permanent_id=values["permanent_id"],
                condition="new",
                verified=True,
                reason=values["reason"],
            )
            action = db.execute(
                "SELECT * FROM inventory_actions WHERE affected_entity_type='inventory_instance' "
                "AND affected_entity_id=? ORDER BY id DESC LIMIT 1",
                (instance_id,),
            ).fetchone()
            db.commit()
            return {
                **values,
                "catalog_item_id": product_id,
                "product_created": product_created,
                "instance_id": instance_id,
                "action_id": action["id"],
                "transaction_id": action["transaction_id"],
                "occurred_at": action["occurred_at"],
            }
        except (InventoryActionError, sqlite3.IntegrityError) as exc:
            db.rollback()
            raise ReceiveSpoolError(str(exc)) from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _product(self, db, product_id: int):
        return db.execute(
            """SELECT ci.id,m.name manufacturer,ci.product_line,ci.variant color,
            MAX(CASE WHEN ad.name='material' THEN av.text_value END) material,
            MAX(CASE WHEN ad.name='diameter_mm' THEN av.numeric_value END) diameter_mm,
            MAX(CASE WHEN ad.name='nominal_weight_g' THEN av.numeric_value END) nominal_weight_g
            FROM catalog_items ci
            JOIN item_types it ON it.id=ci.item_type_id
            JOIN manufacturers m ON m.id=ci.manufacturer_id
            LEFT JOIN catalog_item_attribute_values av ON av.catalog_item_id=ci.id
            LEFT JOIN attribute_definitions ad ON ad.id=av.attribute_definition_id
            WHERE ci.id=? AND it.name='Filament' AND it.tracking_method='individual'
            GROUP BY ci.id
            HAVING material IS NOT NULL AND diameter_mm IS NOT NULL
              AND nominal_weight_g IS NOT NULL""",
            (product_id,),
        ).fetchone()

    def _sign(self, values: dict) -> str:
        body = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self.secret, body, hashlib.sha256).digest()
        return self._b64(body) + "." + self._b64(signature)

    def _verify(self, token: str) -> dict:
        try:
            body_text, signature_text = token.split(".", 1)
            body = self._unb64(body_text)
            signature = self._unb64(signature_text)
            expected = hmac.new(self.secret, body, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            values = json.loads(body)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ReceiveSpoolError("review confirmation is invalid; start again") from exc
        if values.get("version") != 1 or values.get("module") != self.MODULE:
            raise ReceiveSpoolError("review confirmation is invalid; start again")
        if time.time() - values.get("reviewed_at", 0) > self.MAX_REVIEW_AGE_SECONDS:
            raise ReceiveSpoolError("review expired; review the spool again")
        return values

    def _connect(self):
        from .db import connect
        return connect(self.database)

    @staticmethod
    def _text(form: dict[str, str], key: str, limit: int) -> str:
        value = str(form.get(key, "")).strip()
        if not value:
            raise ReceiveSpoolError(f"{key.replace('_', ' ')} is required")
        if len(value) > limit or any(ord(char) < 32 for char in value):
            raise ReceiveSpoolError(f"{key.replace('_', ' ')} is invalid")
        return value

    @classmethod
    def _optional(cls, form: dict[str, str], key: str, limit: int) -> str | None:
        value = str(form.get(key, "")).strip()
        if not value:
            return None
        return cls._text(form, key, limit)

    @staticmethod
    def _positive_int(form: dict[str, str], key: str, message: str) -> int:
        try:
            value = int(form.get(key, ""))
            if value <= 0:
                raise ValueError
            return value
        except (TypeError, ValueError) as exc:
            raise ReceiveSpoolError(message) from exc

    @staticmethod
    def _decimal(
        form: dict[str, str], key: str, minimum: float, maximum: float, label: str
    ) -> float:
        try:
            value = float(form.get(key, ""))
            if not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError
            return value
        except (TypeError, ValueError) as exc:
            raise ReceiveSpoolError(
                f"{label} must be between {minimum:g} and {maximum:g}"
            ) from exc

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    @staticmethod
    def _unb64(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

