from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .actions import ActionContext, InventoryActionError, InventoryActionService
from .db import DEFAULT_DB, connect


class ReturnSpoolError(ValueError):
    """A controlled return-to-storage preview or commit is invalid."""


@dataclass(frozen=True)
class ReturnSpoolReview:
    token: str
    values: dict


class ReturnSpoolToStorageWorkflow:
    MODULE = "return-spool-to-storage-ui"
    MAX_REVIEW_AGE_SECONDS = 900

    def __init__(self, database: str | Path = DEFAULT_DB, secret: bytes | None = None):
        self.database = Path(database)
        self.secret = secret or secrets.token_bytes(32)

    def options(self) -> dict:
        db = connect(self.database)
        try:
            spools = [
                dict(row) for row in db.execute(
                    """SELECT ii.id,ii.permanent_id,ii.remaining_quantity,
                    m.name manufacturer,ci.product_line,ci.variant color,
                    mat.text_value material,e.name equipment_name,es.slot_number
                    FROM inventory_instances ii
                    JOIN catalog_items ci ON ci.id=ii.catalog_item_id
                    JOIN manufacturers m ON m.id=ci.manufacturer_id
                    LEFT JOIN catalog_item_attribute_values mat
                      ON mat.catalog_item_id=ci.id
                      AND mat.attribute_definition_id=(
                        SELECT id FROM attribute_definitions WHERE name='material')
                    JOIN ams_assignments aa
                      ON aa.instance_id=ii.id AND aa.unloaded_at IS NULL
                    JOIN equipment_slots es ON es.id=aa.slot_id
                    JOIN equipment e ON e.id=es.equipment_id
                    WHERE ii.state='loaded' AND ii.archived_at IS NULL
                    ORDER BY e.name,es.slot_number"""
                )
            ]
            locations = [
                dict(row) for row in db.execute(
                    """SELECT l.id,l.name,l.kind FROM locations l
                    WHERE l.archived_at IS NULL AND l.kind='storage'
                      AND NOT EXISTS (
                        SELECT 1 FROM equipment_slots es WHERE es.location_id=l.id)
                    ORDER BY CASE l.name WHEN 'Open-Spool Wall' THEN 0 ELSE 1 END,l.name"""
                )
            ]
            return {"spools": spools, "locations": locations}
        finally:
            db.close()

    def review(self, form: dict[str, str]) -> ReturnSpoolReview:
        instance_id = self._positive_int(
            form, "instance_id", "select a currently loaded spool"
        )
        destination_id = self._positive_int(
            form, "destination_location_id", "select a storage destination"
        )
        if form.get("physically_verified") != "yes":
            raise ReturnSpoolError(
                "physically verify the spool, AMS slot, and destination"
            )
        actor = self._text(form, "actor", 100)
        reason = self._optional(form, "reason", 500)
        options = self.options()
        spool = next((row for row in options["spools"] if row["id"] == instance_id), None)
        if not spool:
            raise ReturnSpoolError("spool must be actively loaded in an AMS")
        destination = next(
            (row for row in options["locations"] if row["id"] == destination_id), None
        )
        if not destination:
            raise ReturnSpoolError("destination must be an active storage location")
        values = {
            "version": 1,
            "reviewed_at": int(time.time()),
            "request_nonce": uuid.uuid4().hex,
            "actor": actor,
            "reason": reason,
            "spool": spool,
            "destination": destination,
        }
        return ReturnSpoolReview(self._sign(values), values)

    def commit(self, token: str) -> dict:
        values = self._verify(token)
        db = connect(self.database)
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM inventory_actions WHERE request_nonce=?",
                (values["request_nonce"],),
            ).fetchone():
                raise ReturnSpoolError("this preview was already used; start a new return")
            spool = self._loaded_spool(db, values["spool"]["id"])
            destination = self._storage_location(db, values["destination"]["id"])
            if spool != values["spool"]:
                raise ReturnSpoolError("spool or AMS assignment changed after preview")
            if destination != values["destination"]:
                raise ReturnSpoolError("storage destination changed after preview")
            service = InventoryActionService(
                db,
                ActionContext(
                    actor=values["actor"], module=self.MODULE, origin="user"
                ),
            )
            action_id = service.unload_instance_from_ams(
                spool["id"], destination["id"], reason=values["reason"],
                request_nonce=values["request_nonce"],
            )
            action = db.execute(
                "SELECT transaction_id FROM inventory_actions WHERE id=?", (action_id,)
            ).fetchone()
            db.commit()
            return {
                **values,
                "action_id": action_id,
                "transaction_id": action["transaction_id"],
                "remaining_quantity": spool["remaining_quantity"],
            }
        except (InventoryActionError, sqlite3.IntegrityError) as exc:
            db.rollback()
            message = (
                "this preview was already used; start a new return"
                if "request_nonce" in str(exc) or "UNIQUE constraint failed" in str(exc)
                else str(exc)
            )
            raise ReturnSpoolError(message) from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _loaded_spool(db, instance_id: int) -> dict | None:
        row = db.execute(
            """SELECT ii.id,ii.permanent_id,ii.remaining_quantity,
            m.name manufacturer,ci.product_line,ci.variant color,
            mat.text_value material,e.name equipment_name,es.slot_number
            FROM inventory_instances ii
            JOIN catalog_items ci ON ci.id=ii.catalog_item_id
            JOIN manufacturers m ON m.id=ci.manufacturer_id
            LEFT JOIN catalog_item_attribute_values mat
              ON mat.catalog_item_id=ci.id
              AND mat.attribute_definition_id=(
                SELECT id FROM attribute_definitions WHERE name='material')
            JOIN ams_assignments aa
              ON aa.instance_id=ii.id AND aa.unloaded_at IS NULL
            JOIN equipment_slots es ON es.id=aa.slot_id
            JOIN equipment e ON e.id=es.equipment_id
            WHERE ii.id=? AND ii.state='loaded' AND ii.archived_at IS NULL""",
            (instance_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _storage_location(db, location_id: int) -> dict | None:
        row = db.execute(
            """SELECT l.id,l.name,l.kind FROM locations l
            WHERE l.id=? AND l.archived_at IS NULL AND l.kind='storage'
              AND NOT EXISTS (
                SELECT 1 FROM equipment_slots es WHERE es.location_id=l.id)""",
            (location_id,),
        ).fetchone()
        return dict(row) if row else None

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
            expected = hmac.new(self.secret, body, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            values = json.loads(body)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ReturnSpoolError("return preview is invalid; start again") from exc
        if values.get("version") != 1:
            raise ReturnSpoolError("return preview is invalid; start again")
        if time.time() - values.get("reviewed_at", 0) > self.MAX_REVIEW_AGE_SECONDS:
            raise ReturnSpoolError("return preview expired; start again")
        return values

    @staticmethod
    def _text(form: dict[str, str], key: str, limit: int) -> str:
        value = str(form.get(key, "")).strip()
        if not value or len(value) > limit or any(ord(char) < 32 for char in value):
            raise ReturnSpoolError(f"{key.replace('_', ' ')} is required or invalid")
        return value

    @classmethod
    def _optional(cls, form: dict[str, str], key: str, limit: int) -> str | None:
        return cls._text(form, key, limit) if str(form.get(key, "")).strip() else None

    @staticmethod
    def _positive_int(form: dict[str, str], key: str, message: str) -> int:
        try:
            value = int(form.get(key, ""))
            if value <= 0:
                raise ValueError
            return value
        except (TypeError, ValueError) as exc:
            raise ReturnSpoolError(message) from exc

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    @staticmethod
    def _unb64(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
