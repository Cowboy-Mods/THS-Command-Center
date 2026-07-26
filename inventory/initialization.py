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
from datetime import datetime
from zoneinfo import ZoneInfo

from .actions import ActionContext, InventoryActionError, InventoryActionService
from .db import connect


class InitializeAMSError(ValueError):
    """A verified AMS initialization request is invalid or no longer current."""


@dataclass(frozen=True)
class InitializationReview:
    token: str
    values: dict


class InitializeVerifiedAMSStateWorkflow:
    MODULE = "verified-ams-initialization-ui"
    MAX_REVIEW_AGE_SECONDS = 30 * 60
    WORKSHOP_TIMEZONE = ZoneInfo("America/Indiana/Indianapolis")

    def __init__(self, database, secret: bytes | None = None):
        self.database = database
        self.secret = secret or secrets.token_bytes(32)

    def default_effective_local(self) -> str:
        return datetime.now(self.WORKSHOP_TIMEZONE).strftime("%Y-%m-%dT%H:%M")

    def options(self) -> dict:
        with closing(connect(self.database)) as db:
            spools = [
                dict(row) for row in db.execute(
                    """SELECT ii.id,ii.permanent_id,ii.state,m.name manufacturer,
                    ci.product_line,ci.variant color,mat.text_value material
                    FROM inventory_instances ii
                    JOIN catalog_items ci ON ci.id=ii.catalog_item_id
                    JOIN item_types it ON it.id=ci.item_type_id
                    JOIN manufacturers m ON m.id=ci.manufacturer_id
                    LEFT JOIN catalog_item_attribute_values mat ON mat.catalog_item_id=ci.id
                      AND mat.attribute_definition_id=(
                        SELECT id FROM attribute_definitions WHERE name='material')
                    WHERE it.name='Filament' AND ii.state IN ('sealed','open')
                      AND ii.archived_at IS NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM ams_assignments aa
                        WHERE aa.instance_id=ii.id AND aa.unloaded_at IS NULL)
                    ORDER BY m.name,ci.product_line,ci.variant,ii.permanent_id"""
                )
            ]
            slots = [
                dict(row) for row in db.execute(
                    """SELECT es.id,e.name equipment_name,es.slot_number,
                    aa.instance_id occupant_instance_id,ii.permanent_id occupant_permanent_id
                    FROM equipment_slots es JOIN equipment e ON e.id=es.equipment_id
                    LEFT JOIN ams_assignments aa ON aa.slot_id=es.id AND aa.unloaded_at IS NULL
                    LEFT JOIN inventory_instances ii ON ii.id=aa.instance_id
                    WHERE e.equipment_type='AMS' AND e.archived_at IS NULL
                    ORDER BY e.name,es.slot_number"""
                )
            ]
        return {"spools": spools, "slots": slots}

    def review(self, form: dict[str, str]) -> InitializationReview:
        if form.get("confirm_verified") != "yes":
            raise InitializeAMSError(
                "confirm that the physical spool and AMS slot were verified"
            )
        instance_id = self._positive_int(form, "instance_id", "select a physical spool")
        slot_id = self._positive_int(form, "slot_id", "select a verified AMS slot")
        actor = self._text(form, "actor", 100)
        reason = self._optional(form, "reason", 500)
        effective_at, effective_local = self._effective_timestamp(
            str(form.get("effective_at", "")).strip()
        )
        with closing(connect(self.database)) as db:
            spool = self._eligible_spool(db, instance_id)
            if not spool:
                raise InitializeAMSError(
                    "only active sealed or open spools without an AMS assignment are eligible"
                )
            slot = self._slot(db, slot_id)
            if not slot:
                raise InitializeAMSError("verified AMS slot does not exist")
            if slot["occupant_instance_id"] is not None:
                raise InitializeAMSError("verified AMS slot is already occupied")
            slot = dict(slot)
            values = {
                "version": 1,
                "reviewed_at": int(time.time()),
                "request_nonce": uuid.uuid4().hex,
                "module": self.MODULE,
                "actor": actor,
                "reason": reason,
                "effective_at": effective_at,
                "effective_local": effective_local,
                "spool": spool,
                "slot": slot,
            }
        return InitializationReview(self._sign(values), values)

    def commit(self, token: str) -> dict:
        values = self._verify(token)
        db = connect(self.database)
        try:
            db.execute("BEGIN IMMEDIATE")
            spool = self._eligible_spool(db, values["spool"]["id"])
            slot = self._slot(db, values["slot"]["id"])
            if spool != values["spool"]:
                raise InitializeAMSError("spool changed after preview; start again")
            if not slot or dict(slot) != values["slot"]:
                raise InitializeAMSError("AMS slot changed after preview; start again")
            service = InventoryActionService(
                db, ActionContext(
                    actor=values["actor"], module=self.MODULE, origin="user"
                ),
            )
            result = service.initialize_verified_ams_state(
                spool["id"], slot["id"], reason=values["reason"],
                effective_at=values["effective_at"],
                request_nonce=values["request_nonce"],
            )
            assignment = db.execute(
                "SELECT id,loaded_at,load_transaction_id FROM ams_assignments "
                "WHERE instance_id=? AND unloaded_at IS NULL",
                (spool["id"],),
            ).fetchone()
            db.commit()
            return {**values, **result, "assignment": dict(assignment)}
        except (InventoryActionError, sqlite3.IntegrityError) as exc:
            db.rollback()
            message = (
                "this preview was already used; start a new initialization"
                if "request_nonce" in str(exc) or "UNIQUE constraint failed" in str(exc)
                else str(exc)
            )
            raise InitializeAMSError(message) from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _eligible_spool(db, instance_id: int) -> dict | None:
        row = db.execute(
            """SELECT ii.id,ii.permanent_id,ii.state,m.name manufacturer,
            ci.product_line,ci.variant color,mat.text_value material
            FROM inventory_instances ii
            JOIN catalog_items ci ON ci.id=ii.catalog_item_id
            JOIN item_types it ON it.id=ci.item_type_id
            JOIN manufacturers m ON m.id=ci.manufacturer_id
            LEFT JOIN catalog_item_attribute_values mat ON mat.catalog_item_id=ci.id
              AND mat.attribute_definition_id=(
                SELECT id FROM attribute_definitions WHERE name='material')
            WHERE ii.id=? AND it.name='Filament' AND ii.state IN ('sealed','open')
              AND ii.archived_at IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM ams_assignments aa
                WHERE aa.instance_id=ii.id AND aa.unloaded_at IS NULL)""",
            (instance_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _slot(db, slot_id: int):
        return db.execute(
            """SELECT es.id,e.name equipment_name,es.slot_number,
            aa.instance_id occupant_instance_id,ii.permanent_id occupant_permanent_id
            FROM equipment_slots es JOIN equipment e ON e.id=es.equipment_id
            LEFT JOIN ams_assignments aa ON aa.slot_id=es.id AND aa.unloaded_at IS NULL
            LEFT JOIN inventory_instances ii ON ii.id=aa.instance_id
            WHERE es.id=? AND e.equipment_type='AMS' AND e.archived_at IS NULL""",
            (slot_id,),
        ).fetchone()

    def _effective_timestamp(self, raw: str) -> tuple[str, str]:
        if not raw:
            raise InitializeAMSError("verified effective timestamp is required")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise InitializeAMSError("effective timestamp is invalid") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=self.WORKSHOP_TIMEZONE)
        local = parsed.astimezone(self.WORKSHOP_TIMEZONE)
        value = local.isoformat(timespec="seconds")
        try:
            InventoryActionService._validate_effective_at(value)
        except InventoryActionError as exc:
            raise InitializeAMSError(str(exc)) from exc
        return value, local.strftime("%Y-%m-%d %I:%M %p %Z")

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
            raise InitializeAMSError("initialization preview is invalid; start again") from exc
        if values.get("version") != 1 or values.get("module") != self.MODULE:
            raise InitializeAMSError("initialization preview is invalid; start again")
        if time.time() - values.get("reviewed_at", 0) > self.MAX_REVIEW_AGE_SECONDS:
            raise InitializeAMSError("initialization preview expired; start again")
        return values

    @staticmethod
    def _text(form: dict[str, str], key: str, limit: int) -> str:
        value = str(form.get(key, "")).strip()
        if not value:
            raise InitializeAMSError(f"{key.replace('_', ' ')} is required")
        if len(value) > limit or any(ord(char) < 32 for char in value):
            raise InitializeAMSError(f"{key.replace('_', ' ')} is invalid")
        return value

    @classmethod
    def _optional(cls, form: dict[str, str], key: str, limit: int) -> str | None:
        value = str(form.get(key, "")).strip()
        return cls._text(form, key, limit) if value else None

    @staticmethod
    def _positive_int(form: dict[str, str], key: str, message: str) -> int:
        try:
            value = int(form.get(key, ""))
            if value <= 0:
                raise ValueError
            return value
        except (TypeError, ValueError) as exc:
            raise InitializeAMSError(message) from exc

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    @staticmethod
    def _unb64(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

