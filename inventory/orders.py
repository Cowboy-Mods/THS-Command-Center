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


class OrderReceiptError(ValueError):
    """An order receipt is incomplete, invalid, stale, or already used."""


@dataclass(frozen=True)
class OrderReceiptReview:
    token: str
    values: dict


class OrderReceiptWorkflow:
    MODULE = "order-receiving-ui"
    MAX_REVIEW_AGE_SECONDS = 30 * 60

    def __init__(self, database, secret: bytes | None = None):
        self.database = database
        self.secret = secret or secrets.token_bytes(32)

    def options(self) -> dict:
        with closing(self._connect()) as db:
            orders = db.execute(
                """SELECT o.*,m.name manufacturer,ci.product_line,ci.variant
                FROM orders o LEFT JOIN catalog_items ci ON ci.id=o.catalog_item_id
                LEFT JOIN manufacturers m ON m.id=ci.manufacturer_id
                WHERE o.state IN ('ordered','shipped','delivered')
                ORDER BY o.ordered_at,o.id"""
            ).fetchall()
            locations = db.execute(
                "SELECT id,name FROM locations WHERE kind='storage' AND archived_at IS NULL "
                "ORDER BY CASE name WHEN 'Sealed Filament Rack' THEN 0 ELSE 1 END,name"
            ).fetchall()
            return {
                "orders": [dict(row) for row in orders],
                "locations": [dict(row) for row in locations],
            }

    def review(self, form: dict[str, str]) -> OrderReceiptReview:
        if form.get("physically_verified") != "yes":
            raise OrderReceiptError("confirm the delivered quantity and condition were physically verified")
        order_id = self._positive_int(form, "order_id", "select a pending order")
        actual_quantity = self._positive_int(
            form, "actual_quantity", "verified received quantity must be positive"
        )
        condition = self._text(form, "condition", 20).lower()
        if condition not in {"new", "good", "damaged"}:
            raise OrderReceiptError("select the verified shipment condition")
        location_id = self._positive_int(form, "location_id", "select a receiving location")
        actor = self._text(form, "actor", 100)
        reason = self._optional(form, "reason", 500)
        note = self._optional(form, "note", 500)
        nonce = uuid.uuid4().hex

        with closing(self._connect()) as db:
            order = self._order(db, order_id)
            if not order or order["state"] not in {"ordered", "shipped", "delivered"}:
                raise OrderReceiptError("selected order is not pending receipt")
            location = db.execute(
                "SELECT id,name,kind FROM locations WHERE id=? AND archived_at IS NULL",
                (location_id,),
            ).fetchone()
            if not location or location["kind"] != "storage":
                raise OrderReceiptError("receiving location must be active storage")
            service = InventoryActionService(
                db, ActionContext(actor=actor, module=self.MODULE, origin="user")
            )
            first_id = service.preview_next_human_id(order["item_type_id"])
            prefix, number = first_id.rsplit("-", 1)
            permanent_ids = [
                f"{prefix}-{int(number) + offset:06d}" for offset in range(actual_quantity)
            ]
            values = {
                "version": 1, "reviewed_at": int(time.time()), "nonce": nonce,
                "module": self.MODULE, "actor": actor, "reason": reason, "note": note,
                "order": dict(order), "location_id": location["id"],
                "location": location["name"], "actual_quantity": actual_quantity,
                "condition": condition, "permanent_ids": permanent_ids,
            }
        return OrderReceiptReview(self._sign(values), values)

    def commit(self, token: str) -> dict:
        values = self._verify(token)
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM inventory_actions WHERE request_nonce=?",
                (values["nonce"],),
            ).fetchone():
                raise OrderReceiptError("this receipt preview was already used")
            current = self._order(db, values["order"]["id"])
            if not current or any(
                current[key] != values["order"][key]
                for key in ("state", "received_quantity", "catalog_item_id", "expected_quantity")
            ):
                raise OrderReceiptError("order changed after preview; review the receipt again")
            service = InventoryActionService(
                db, ActionContext(
                    actor=values["actor"], module=self.MODULE, origin="user"
                ),
            )
            if service.preview_next_human_id(current["item_type_id"]) != values["permanent_ids"][0]:
                raise OrderReceiptError(
                    "inventory changed after preview; review the generated THS-FIL IDs again"
                )
            result = service.receive_order(
                current["id"], actual_quantity=values["actual_quantity"],
                condition=values["condition"], location_id=values["location_id"],
                reason=values["reason"], note=values["note"],
                request_nonce=values["nonce"],
            )
            actual_ids = [
                row[0] for row in db.execute(
                    "SELECT permanent_id FROM inventory_instances WHERE id IN "
                    f"({','.join('?' for _ in result['instance_ids'])}) ORDER BY permanent_id",
                    result["instance_ids"],
                )
            ]
            if actual_ids != values["permanent_ids"]:
                raise OrderReceiptError("generated spool identities changed during receipt")
            db.commit()
            return {**result, **values, "permanent_ids": actual_ids}
        except (InventoryActionError, sqlite3.IntegrityError) as exc:
            db.rollback()
            raise OrderReceiptError(str(exc)) from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _order(self, db, order_id: int):
        return db.execute(
            """SELECT o.*,ci.item_type_id,ci.product_line,ci.variant,
            m.name manufacturer,
            MAX(CASE WHEN ad.name='nominal_weight_g' THEN av.numeric_value END) nominal_weight_g
            FROM orders o JOIN catalog_items ci ON ci.id=o.catalog_item_id
            JOIN item_types it ON it.id=ci.item_type_id AND it.tracking_method='individual'
            JOIN manufacturers m ON m.id=ci.manufacturer_id
            LEFT JOIN catalog_item_attribute_values av ON av.catalog_item_id=ci.id
            LEFT JOIN attribute_definitions ad ON ad.id=av.attribute_definition_id
            WHERE o.id=? GROUP BY o.id""",
            (order_id,),
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
            if not hmac.compare_digest(
                signature, hmac.new(self.secret, body, hashlib.sha256).digest()
            ):
                raise ValueError
            values = json.loads(body)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise OrderReceiptError("receipt preview is invalid; start again") from exc
        if values.get("version") != 1 or values.get("module") != self.MODULE:
            raise OrderReceiptError("receipt preview is invalid; start again")
        if time.time() - values.get("reviewed_at", 0) > self.MAX_REVIEW_AGE_SECONDS:
            raise OrderReceiptError("receipt preview expired; start again")
        return values

    def _connect(self):
        from .db import connect
        return connect(self.database)

    @staticmethod
    def _text(form: dict[str, str], key: str, limit: int) -> str:
        value = str(form.get(key, "")).strip()
        if not value or len(value) > limit or any(ord(char) < 32 for char in value):
            raise OrderReceiptError(f"{key.replace('_', ' ')} is required or invalid")
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
            raise OrderReceiptError(message) from exc

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    @staticmethod
    def _unb64(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

