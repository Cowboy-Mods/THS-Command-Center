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
from datetime import date, time as clock_time
from pathlib import Path

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
        physical_receipt_date = self._text(form, "physical_receipt_date", 10)
        try:
            date.fromisoformat(physical_receipt_date)
        except ValueError as exc:
            raise OrderReceiptError("physical receipt date must use YYYY-MM-DD") from exc
        precision = self._text(form, "receipt_time_precision", 20).lower()
        if precision not in {"exact", "estimated", "date_only", "unknown"}:
            raise OrderReceiptError("select a valid receipt-time precision")
        physical_receipt_time = self._optional(form, "physical_receipt_time", 8)
        if physical_receipt_time:
            try:
                clock_time.fromisoformat(physical_receipt_time)
            except ValueError as exc:
                raise OrderReceiptError("physical receipt time must use HH:MM[:SS]") from exc
            if len(physical_receipt_time) == 5:
                physical_receipt_time += ":00"
        if precision == "date_only" and physical_receipt_time:
            raise OrderReceiptError("date-only receipt must not supply a physical time")
        if precision in {"exact", "estimated"} and not physical_receipt_time:
            raise OrderReceiptError("exact or estimated receipt requires a physical time")
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
            outstanding = order["expected_quantity"] - order["received_quantity"]
            if outstanding <= 0:
                raise OrderReceiptError("selected order is already fully received")
            if actual_quantity != outstanding:
                raise OrderReceiptError(
                    f"verified quantity must equal the full outstanding quantity ({outstanding})"
                )
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
            evidence = self._delivery_evidence(db, order["id"])
            requested = form.get("evidence_uuids")
            if isinstance(requested, str):
                requested = [value.strip() for value in requested.split(",") if value.strip()]
            requested = requested or [row["evidence_uuid"] for row in evidence]
            selected = [row for row in evidence if row["evidence_uuid"] in requested]
            if len(selected) != len(set(requested)) or not selected:
                raise OrderReceiptError("select valid delivery evidence belonging to this order")
            for row in selected:
                digest, size = self._file_identity(Path(row["file_path"]))
                if digest != row["sha256"] or size != row["file_size"]:
                    raise OrderReceiptError(
                        "delivery evidence file is missing or changed; correct it before review"
                    )
            values = {
                "version": 2, "reviewed_at": int(time.time()), "nonce": nonce,
                "module": self.MODULE, "actor": actor, "reason": reason, "note": note,
                "order": dict(order), "location_id": location["id"],
                "location": location["name"], "actual_quantity": actual_quantity,
                "condition": condition, "permanent_ids": permanent_ids,
                "batch_uuid": str(uuid.uuid4()),
                "physical_receipt_date": physical_receipt_date,
                "physical_receipt_time": physical_receipt_time,
                "receipt_time_precision": precision,
                "evidence": selected,
                "evidence_links": [
                    {"link_uuid": str(uuid.uuid4()), "evidence_id": row["id"],
                     "evidence_uuid": row["evidence_uuid"]}
                    for row in selected
                ],
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
            if not current or dict(current) != values["order"]:
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
            evidence = self._delivery_evidence(db, current["id"])
            indexed = {row["evidence_uuid"]: row for row in evidence}
            for expected in values["evidence"]:
                current_evidence = indexed.get(expected["evidence_uuid"])
                if current_evidence != expected:
                    raise OrderReceiptError("delivery evidence changed after preview; review again")
                digest, size = self._file_identity(Path(expected["file_path"]))
                if digest != expected["sha256"] or size != expected["file_size"]:
                    raise OrderReceiptError(
                        "delivery evidence file is missing or changed; review again"
                    )
            result = service.receive_order(
                current["id"], actual_quantity=values["actual_quantity"],
                condition=values["condition"], location_id=values["location_id"],
                reason=values["reason"], note=values["note"],
                request_nonce=values["nonce"],
                batch_uuid=values["batch_uuid"], permanent_ids=values["permanent_ids"],
                physical_receipt_date=values["physical_receipt_date"],
                physical_receipt_time=values["physical_receipt_time"],
                receipt_time_precision=values["receipt_time_precision"],
                evidence_links=values["evidence_links"],
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
            """SELECT o.*,ci.item_type_id,ci.name product_name,ci.product_line,ci.variant,
            m.name manufacturer,
            MAX(CASE WHEN ad.name='nominal_weight_g' THEN av.numeric_value END) nominal_weight_g,
            MAX(CASE WHEN ad.name='material' THEN av.text_value END) material_name,
            MAX(CASE WHEN ad.name='manufacturer_color_name' THEN av.text_value END) color_name,
            MAX(CASE WHEN ad.name='diameter_mm' THEN av.numeric_value END) diameter_mm,
            MAX(CASE WHEN ad.name='filament_form' THEN av.text_value END) filament_form
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
            if self._b64(body) != body_text or self._b64(signature) != signature_text:
                raise ValueError
            if not hmac.compare_digest(
                signature, hmac.new(self.secret, body, hashlib.sha256).digest()
            ):
                raise ValueError
            values = json.loads(body)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise OrderReceiptError("receipt preview is invalid; start again") from exc
        if values.get("version") != 2 or values.get("module") != self.MODULE:
            raise OrderReceiptError("receipt preview is invalid; start again")
        if time.time() - values.get("reviewed_at", 0) > self.MAX_REVIEW_AGE_SECONDS:
            raise OrderReceiptError("receipt preview expired; start again")
        return values

    @staticmethod
    def _delivery_evidence(db, order_id):
        return [dict(row) for row in db.execute(
            """SELECT id,evidence_uuid,order_id,evidence_scope,evidence_type,file_path,
            sha256,file_size,caption,captured_at,actor,request_nonce,added_at
            FROM order_delivery_evidence
            WHERE order_id=? AND evidence_scope='delivery' ORDER BY id""", (order_id,)
        )]

    @staticmethod
    def _file_identity(path):
        if not path.is_file():
            raise OrderReceiptError("delivery evidence file is missing")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest(), path.stat().st_size

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

