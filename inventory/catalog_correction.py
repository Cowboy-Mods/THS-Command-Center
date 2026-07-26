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
from pathlib import Path

from .db import connect


class CatalogCorrectionError(ValueError):
    """A catalog correction preview is invalid, stale, or already used."""


class CatalogCorrectionWorkflow:
    MODULE = "catalog-correction"
    MAX_REVIEW_AGE_SECONDS = 30 * 60

    def __init__(self, database, secret: bytes | None = None):
        self.database = Path(database)
        self.secret = secret or secrets.token_bytes(32)

    def review(self, form: dict) -> dict:
        item_id = self._positive_int(form.get("catalog_item_id"))
        actor = self._text(form.get("actor"), "actor", 100)
        reason = self._text(form.get("reason"), "reason", 500)
        proposed = {
            "name": self._text(form.get("name"), "product name", 200),
            "product_line": self._text(form.get("product_line"), "product line", 200),
            "variant": self._text(form.get("variant"), "variant", 200),
            "filament_form": self._text(form.get("filament_form"), "filament form", 100),
        }
        with closing(connect(self.database)) as db:
            current = self._snapshot(db, item_id)
            if not current:
                raise CatalogCorrectionError("catalog item not found")
            if proposed == {key: current[key] for key in proposed}:
                raise CatalogCorrectionError("catalog correction does not change anything")
        values = {
            "version": 1, "module": self.MODULE, "action": "correct_catalog_identity",
            "reviewed_at": int(time.time()), "request_nonce": uuid.uuid4().hex,
            "history_uuid": str(uuid.uuid4()), "actor": actor, "reason": reason,
            "current": current, "proposed": proposed,
        }
        body = self._canonical(values)
        return {"token": self._sign(body), "values": values,
                "payload_sha256": hashlib.sha256(body).hexdigest()}

    def commit(self, token: str, *, confirmed: bool) -> dict:
        if not confirmed:
            raise CatalogCorrectionError("explicit confirmation is required")
        values, body = self._verify(token)
        db = connect(self.database)
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM catalog_item_history WHERE request_nonce=?",
                          (values["request_nonce"],)).fetchone():
                raise CatalogCorrectionError("this catalog correction preview was already used")
            current = self._snapshot(db, values["current"]["id"])
            if current != values["current"]:
                raise CatalogCorrectionError("catalog item changed after preview; review again")
            proposed = values["proposed"]
            db.execute(
                "UPDATE catalog_items SET name=?,product_line=?,variant=? WHERE id=?",
                (proposed["name"], proposed["product_line"], proposed["variant"], current["id"]),
            )
            definition = db.execute(
                "SELECT id FROM attribute_definitions WHERE name='filament_form'"
            ).fetchone()
            db.execute(
                """INSERT INTO catalog_item_attribute_values(
                catalog_item_id,attribute_definition_id,text_value)
                VALUES (?,?,?) ON CONFLICT(catalog_item_id,attribute_definition_id)
                DO UPDATE SET text_value=excluded.text_value,numeric_value=NULL,boolean_value=NULL""",
                (current["id"], definition["id"], proposed["filament_form"]),
            )
            new = self._snapshot(db, current["id"])
            db.execute(
                """INSERT INTO catalog_item_history(
                history_uuid,request_nonce,catalog_item_id,action_type,previous_snapshot,
                new_snapshot,payload_sha256,actor,reason) VALUES (?,?,?,?,?,?,?,?,?)""",
                (values["history_uuid"], values["request_nonce"], current["id"],
                 "correct_catalog_identity", self._json(current), self._json(new),
                 hashlib.sha256(body).hexdigest(), values["actor"], values["reason"]),
            )
            db.commit()
            return {"catalog_item_id": current["id"], "history_uuid": values["history_uuid"],
                    "previous": current, "current": new}
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise CatalogCorrectionError(str(exc)) from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _snapshot(db, item_id):
        row = db.execute(
            """SELECT ci.id,ci.item_type_id,ci.manufacturer_id,m.name manufacturer,
            ci.name,ci.product_line,ci.variant,ci.manufacturer_sku,ci.base_unit_id,
            ci.notes,ci.archived_at,
            MAX(CASE WHEN ad.name='material' THEN av.text_value END) material,
            MAX(CASE WHEN ad.name='manufacturer_color_name' THEN av.text_value END) color,
            MAX(CASE WHEN ad.name='diameter_mm' THEN av.numeric_value END) diameter_mm,
            MAX(CASE WHEN ad.name='nominal_weight_g' THEN av.numeric_value END) nominal_weight_g,
            MAX(CASE WHEN ad.name='filament_form' THEN av.text_value END) filament_form,
            (SELECT COUNT(*) FROM orders o WHERE o.catalog_item_id=ci.id) order_dependencies,
            (SELECT COUNT(*) FROM inventory_instances ii WHERE ii.catalog_item_id=ci.id)
              inventory_dependencies
            FROM catalog_items ci LEFT JOIN manufacturers m ON m.id=ci.manufacturer_id
            LEFT JOIN catalog_item_attribute_values av ON av.catalog_item_id=ci.id
            LEFT JOIN attribute_definitions ad ON ad.id=av.attribute_definition_id
            WHERE ci.id=? GROUP BY ci.id""", (item_id,)
        ).fetchone()
        if not row:
            return None
        snapshot = dict(row)
        snapshot["attributes"] = [
            dict(attribute) for attribute in db.execute(
                """SELECT ad.name,ad.data_type,av.text_value,av.numeric_value,
                av.boolean_value FROM catalog_item_attribute_values av
                JOIN attribute_definitions ad ON ad.id=av.attribute_definition_id
                WHERE av.catalog_item_id=? ORDER BY ad.name""", (item_id,)
            )
        ]
        return snapshot

    def _verify(self, token):
        try:
            body_text, signature_text = token.split(".", 1)
            body = self._unb64(body_text)
            signature = self._unb64(signature_text)
            if self._b64(body) != body_text or not hmac.compare_digest(
                signature, hmac.new(self.secret, body, hashlib.sha256).digest()
            ):
                raise ValueError
            values = json.loads(body)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise CatalogCorrectionError("catalog correction preview is invalid") from exc
        age = int(time.time()) - values.get("reviewed_at", 0)
        if age < -60 or age > self.MAX_REVIEW_AGE_SECONDS:
            raise CatalogCorrectionError("catalog correction preview expired; review again")
        if values.get("version") != 1 or values.get("module") != self.MODULE:
            raise CatalogCorrectionError("catalog correction preview is invalid")
        return values, body

    def _sign(self, body):
        return self._b64(body) + "." + self._b64(
            hmac.new(self.secret, body, hashlib.sha256).digest())

    @staticmethod
    def _canonical(values):
        return json.dumps(values, sort_keys=True, separators=(",", ":")).encode()

    @staticmethod
    def _json(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _text(value, label, maximum):
        value = str(value or "").strip()
        if not value or len(value) > maximum or any(ord(c) < 32 for c in value):
            raise CatalogCorrectionError(f"{label} is required or invalid")
        return value

    @staticmethod
    def _positive_int(value):
        try:
            value = int(value)
            if value <= 0:
                raise ValueError
            return value
        except (TypeError, ValueError) as exc:
            raise CatalogCorrectionError("catalog item is required") from exc

    @staticmethod
    def _b64(value):
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    @staticmethod
    def _unb64(value):
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
