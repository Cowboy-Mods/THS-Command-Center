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
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .db import connect


class PurchaseError(ValueError):
    """A purchase preview or commit is invalid, stale, or already used."""


class PurchaseRegistryService:
    MODULE = "purchase-registry"
    MAX_REVIEW_AGE_SECONDS = 30 * 60
    TRACKING_INTENTS = {"individual", "lot", "quantity", "non_inventory"}
    EVIDENCE_SCOPES = {"purchase", "delivery"}
    EVIDENCE_TYPES = {"screenshot", "invoice", "receipt", "photo", "document", "other"}
    MAINTENANCE_RELATIONSHIPS = {
        "required_part", "corrective_replacement", "spare_stock", "maintenance_supply",
    }

    def __init__(self, database, secret: bytes | None = None):
        self.database = Path(database)
        self.secret = secret or secrets.token_bytes(32)

    def vendors(self) -> list[dict]:
        with closing(connect(self.database)) as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM purchase_vendors ORDER BY lower(name),id"
            )]

    def categories(self) -> list[dict]:
        with closing(connect(self.database)) as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM purchase_categories WHERE active=1 ORDER BY sort_order"
            )]

    def purchases(self) -> list[dict]:
        with closing(connect(self.database)) as db:
            rows = [dict(row) for row in db.execute(
                """SELECT po.*,pv.name vendor_name,
                (SELECT COUNT(*) FROM purchase_order_lines pol
                  WHERE pol.purchase_order_id=po.id) line_count
                FROM purchase_orders po JOIN purchase_vendors pv ON pv.id=po.vendor_id
                ORDER BY po.purchase_date DESC,po.id DESC"""
            )]
            return rows

    def purchase(self, purchase_id: int) -> dict | None:
        with closing(connect(self.database)) as db:
            header = db.execute(
                """SELECT po.*,pv.name vendor_name,pv.vendor_code
                FROM purchase_orders po JOIN purchase_vendors pv ON pv.id=po.vendor_id
                WHERE po.id=?""", (purchase_id,)
            ).fetchone()
            if not header:
                return None
            result = dict(header)
            result["lines"] = [dict(row) for row in db.execute(
                """SELECT pol.*,pc.category_code,pc.display_name category_name
                FROM purchase_order_lines pol
                JOIN purchase_categories pc ON pc.id=pol.category_id
                WHERE pol.purchase_order_id=? ORDER BY pol.line_number""",
                (purchase_id,),
            )]
            result["history"] = [dict(row) for row in db.execute(
                "SELECT * FROM purchase_history WHERE purchase_order_id=? ORDER BY id",
                (purchase_id,),
            )]
            result["evidence"] = [dict(row) for row in db.execute(
                "SELECT * FROM purchase_evidence WHERE purchase_order_id=? ORDER BY id",
                (purchase_id,),
            )]
            result["maintenance_links"] = [dict(row) for row in db.execute(
                """SELECT pml.*,mr.event_number,pol.description line_description
                FROM purchase_maintenance_links pml
                JOIN maintenance_records mr ON mr.id=pml.maintenance_record_id
                LEFT JOIN purchase_order_lines pol ON pol.id=pml.purchase_order_line_id
                WHERE pml.purchase_order_id=? ORDER BY pml.id""", (purchase_id,)
            )]
            return result

    def review_add_evidence(self, form: dict) -> dict:
        actor = self._text(form.get("actor"), "actor", 100)
        purchase_id = self._optional_positive_int(form.get("purchase_id"), "purchase")
        scope = self._text(form.get("evidence_scope"), "evidence scope", 20)
        evidence_type = self._text(form.get("evidence_type"), "evidence type", 20)
        if scope not in self.EVIDENCE_SCOPES:
            raise PurchaseError("evidence scope must be purchase or delivery")
        if evidence_type not in self.EVIDENCE_TYPES:
            raise PurchaseError("select a valid purchase evidence type")
        path = Path(self._text(form.get("file_path"), "evidence file path", 2000))
        if not path.is_absolute() or not path.is_file():
            raise PurchaseError("evidence must be an existing absolute file path")
        document_date = self._optional_text(form.get("document_date"), 10)
        if document_date:
            try:
                date.fromisoformat(document_date)
            except ValueError as exc:
                raise PurchaseError("document date must use YYYY-MM-DD") from exc
        with closing(connect(self.database)) as db:
            purchase = self._purchase_snapshot(db, purchase_id)
        sha256, file_size = self._file_identity(path)
        values = self._action_values("add_evidence", actor, purchase)
        values.update({
            "evidence_scope": scope, "evidence_type": evidence_type,
            "file_path": str(path), "sha256": sha256, "file_size": file_size,
            "caption": self._optional_text(form.get("caption"), 1000),
            "document_date": document_date,
            "reason": self._optional_text(form.get("reason"), 2000),
        })
        return self._review_result(values)

    def commit_add_evidence(self, token: str, *, confirmed: bool) -> dict:
        return self._commit_phase2a(token, confirmed, "add_evidence")

    def review_link_maintenance(self, form: dict) -> dict:
        actor = self._text(form.get("actor"), "actor", 100)
        purchase_id = self._optional_positive_int(form.get("purchase_id"), "purchase")
        maintenance_id = self._optional_positive_int(
            form.get("maintenance_record_id"), "maintenance record"
        )
        line_id = self._optional_positive_int(form.get("purchase_order_line_id"), "line")
        relationship = self._text(
            form.get("relationship_type"), "maintenance relationship", 40
        )
        if relationship not in self.MAINTENANCE_RELATIONSHIPS:
            raise PurchaseError("select a valid maintenance relationship")
        with closing(connect(self.database)) as db:
            purchase = self._purchase_snapshot(db, purchase_id)
            maintenance = db.execute(
                "SELECT id,event_number,status FROM maintenance_records WHERE id=?",
                (maintenance_id,),
            ).fetchone()
            if not maintenance:
                raise PurchaseError("maintenance record not found")
            line = None
            if line_id:
                line = db.execute(
                    """SELECT id,purchase_order_id,line_number,description
                    FROM purchase_order_lines WHERE id=?""", (line_id,)
                ).fetchone()
                if not line or line["purchase_order_id"] != purchase_id:
                    raise PurchaseError("selected line does not belong to this purchase")
        values = self._action_values("link_maintenance", actor, purchase)
        values.update({
            "maintenance_record": dict(maintenance),
            "purchase_line": dict(line) if line else None,
            "relationship_type": relationship,
            "note": self._optional_text(form.get("note"), 1000),
            "reason": self._optional_text(form.get("reason"), 2000),
        })
        return self._review_result(values)

    def commit_link_maintenance(self, token: str, *, confirmed: bool) -> dict:
        return self._commit_phase2a(token, confirmed, "link_maintenance")

    def review_create(self, form: dict) -> dict:
        actor = self._text(form.get("actor"), "actor", 100)
        vendor_id = self._optional_positive_int(form.get("vendor_id"), "vendor")
        vendor_name = self._optional_text(form.get("vendor_name"), 200)
        with closing(connect(self.database)) as db:
            vendor = None
            if vendor_id:
                vendor = db.execute(
                    "SELECT * FROM purchase_vendors WHERE id=? AND active=1", (vendor_id,)
                ).fetchone()
                if not vendor:
                    raise PurchaseError("selected vendor is unavailable")
                if vendor_name and vendor_name.casefold() != vendor["name"].strip().casefold():
                    raise PurchaseError("vendor name does not match the selected vendor")
            else:
                if not vendor_name:
                    raise PurchaseError("select a vendor or provide a new vendor name")
                vendor = db.execute(
                    "SELECT * FROM purchase_vendors WHERE lower(trim(name))=lower(trim(?))",
                    (vendor_name,),
                ).fetchone()
                if vendor:
                    vendor_id = vendor["id"]
            purchase_date = self._text(form.get("purchase_date"), "purchase date", 10)
            try:
                date.fromisoformat(purchase_date)
            except ValueError as exc:
                raise PurchaseError("purchase date must use YYYY-MM-DD") from exc
            currency = self._text(form.get("currency_code", "USD"), "currency", 3).upper()
            if len(currency) != 3 or not currency.isalpha():
                raise PurchaseError("currency must be a three-letter code")
            lines = self._review_lines(db, form.get("lines"))
            subtotal = sum(line["line_total_cents"] for line in lines)
            supplied_subtotal = self._cents(form.get("subtotal_cents"), "subtotal")
            tax = self._cents(form.get("tax_cents", 0), "tax")
            shipping = self._cents(form.get("shipping_cents", 0), "shipping")
            discount = self._cents(form.get("discount_cents", 0), "discount")
            supplied_total = self._cents(form.get("total_cents"), "total")
            calculated_total = subtotal + tax + shipping - discount
            if subtotal != supplied_subtotal:
                raise PurchaseError("subtotal does not match the reviewed line totals")
            if calculated_total < 0 or calculated_total != supplied_total:
                raise PurchaseError("total does not match subtotal, tax, shipping, and discount")
            values = {
                "version": 1,
                "module": self.MODULE,
                "action": "create_purchase",
                "reviewed_at": int(time.time()),
                "request_nonce": uuid.uuid4().hex,
                "actor": actor,
                "purchase_number": self._next_number(db),
                "purchase_date": purchase_date,
                "status": "ordered",
                "currency_code": currency,
                "vendor_id": vendor_id,
                "vendor_name": vendor["name"] if vendor else vendor_name,
                "vendor_existing_snapshot": dict(vendor) if vendor else None,
                "vendor_order_number": self._optional_text(
                    form.get("vendor_order_number"), 200
                ),
                "subtotal_cents": subtotal,
                "tax_cents": tax,
                "shipping_cents": shipping,
                "discount_cents": discount,
                "total_cents": calculated_total,
                "notes": self._optional_text(form.get("notes"), 4000),
                "reason": self._optional_text(form.get("reason"), 2000),
                "lines": lines,
            }
        body = self._canonical(values)
        return {
            "token": self._sign_body(body),
            "values": values,
            "payload_sha256": hashlib.sha256(body).hexdigest(),
        }

    def commit_create(self, token: str, *, confirmed: bool) -> dict:
        if not confirmed:
            raise PurchaseError("explicit confirmation is required")
        values, body = self._verify(token)
        if values.get("module") != self.MODULE or values.get("action") != "create_purchase":
            raise PurchaseError("purchase preview is invalid")
        required = {
            "version", "reviewed_at", "request_nonce", "actor", "purchase_number",
            "purchase_date", "status", "currency_code", "vendor_id", "vendor_name",
            "vendor_existing_snapshot", "vendor_order_number", "subtotal_cents",
            "tax_cents", "shipping_cents", "discount_cents", "total_cents",
            "notes", "reason", "lines",
        }
        if values.get("version") != 1 or not required.issubset(values):
            raise PurchaseError("purchase preview payload is unsupported or incomplete")
        nonce = values.get("request_nonce")
        if (
            not isinstance(nonce, str) or len(nonce) != 32
            or any(character not in "0123456789abcdef" for character in nonce)
        ):
            raise PurchaseError("purchase preview nonce is invalid")
        db = connect(self.database)
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM purchase_history WHERE request_nonce=?",
                (values["request_nonce"],),
            ).fetchone():
                raise PurchaseError("this purchase preview was already used")
            if values.get("status") != "ordered":
                raise PurchaseError("new purchases must begin in ordered status")
            if self._next_number(db) != values.get("purchase_number"):
                raise PurchaseError("purchase registry changed after preview; review again")
            self._revalidate_totals(values)
            vendor_id = self._commit_vendor(db, values)
            self._revalidate_lines(db, values["lines"])
            purchase_id = db.execute(
                """INSERT INTO purchase_orders(
                purchase_uuid,purchase_number,vendor_id,vendor_order_number,status,
                purchase_date,currency_code,subtotal_cents,tax_cents,shipping_cents,
                discount_cents,total_cents,notes,created_by)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), values["purchase_number"], vendor_id,
                    values["vendor_order_number"], "ordered", values["purchase_date"],
                    values["currency_code"], values["subtotal_cents"], values["tax_cents"],
                    values["shipping_cents"], values["discount_cents"],
                    values["total_cents"], values["notes"], values["actor"],
                ),
            ).lastrowid
            for line in values["lines"]:
                db.execute(
                    """INSERT INTO purchase_order_lines(
                    line_uuid,purchase_order_id,line_number,category_id,description,
                    vendor_sku,catalog_item_id,quantity_ordered,unit_label,unit_price_cents,
                    line_discount_cents,line_total_cents,inventory_tracking_intent,notes)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        str(uuid.uuid4()), purchase_id, line["line_number"],
                        line["category_id"], line["description"], line["vendor_sku"],
                        line["catalog_item_id"], line["quantity_ordered"], line["unit_label"],
                        line["unit_price_cents"], line["line_discount_cents"],
                        line["line_total_cents"], line["inventory_tracking_intent"],
                        line["notes"],
                    ),
                )
            snapshot = self._snapshot(db, purchase_id)
            payload_sha256 = hashlib.sha256(body).hexdigest()
            history_id = db.execute(
                """INSERT INTO purchase_history(
                history_uuid,request_nonce,purchase_order_id,action_type,previous_status,
                new_status,snapshot,payload_sha256,reason,actor)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), values["request_nonce"], purchase_id,
                    "create_purchase", None, "ordered",
                    json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
                    payload_sha256, values["reason"], values["actor"],
                ),
            ).lastrowid
            db.commit()
            return {
                "purchase_id": purchase_id,
                "purchase_number": values["purchase_number"],
                "vendor_id": vendor_id,
                "history_id": history_id,
                "status": "ordered",
                "payload_sha256": payload_sha256,
            }
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise PurchaseError(str(exc)) from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _commit_phase2a(self, token, confirmed, expected_action):
        if not confirmed:
            raise PurchaseError("explicit confirmation is required")
        values, body = self._verify(token)
        if (
            values.get("version") != 1 or values.get("module") != self.MODULE
            or values.get("action") != expected_action
        ):
            raise PurchaseError("purchase action preview is invalid")
        nonce = values.get("request_nonce")
        if (
            not isinstance(nonce, str) or len(nonce) != 32
            or any(character not in "0123456789abcdef" for character in nonce)
        ):
            raise PurchaseError("purchase preview nonce is invalid")
        db = connect(self.database)
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM purchase_history WHERE request_nonce=?",
                (values["request_nonce"],),
            ).fetchone():
                raise PurchaseError("this purchase preview was already used")
            current = self._purchase_snapshot(db, values["purchase"]["id"])
            if current != values["purchase"]:
                raise PurchaseError("purchase changed after preview; review again")
            if expected_action == "add_evidence":
                result = self._commit_evidence(db, values)
            else:
                result = self._commit_maintenance_link(db, values)
            history_id = self._phase2a_history(
                db, values, body, result["snapshot"]
            )
            db.commit()
            return {**result, "history_id": history_id}
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise PurchaseError(str(exc)) from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _commit_evidence(self, db, values):
        path = Path(values["file_path"])
        sha256, file_size = self._file_identity(path)
        if sha256 != values["sha256"] or file_size != values["file_size"]:
            raise PurchaseError("evidence file changed after preview; review again")
        evidence_id = db.execute(
            """INSERT INTO purchase_evidence(
            evidence_uuid,purchase_order_id,evidence_scope,evidence_type,file_path,
            sha256,file_size,caption,document_date,added_by)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()), values["purchase"]["id"], values["evidence_scope"],
                values["evidence_type"], values["file_path"], sha256, file_size,
                values["caption"], values["document_date"], values["actor"],
            ),
        ).lastrowid
        snapshot = dict(db.execute(
            "SELECT * FROM purchase_evidence WHERE id=?", (evidence_id,)
        ).fetchone())
        return {
            "purchase_id": values["purchase"]["id"],
            "purchase_number": values["purchase"]["purchase_number"],
            "evidence_id": evidence_id, "sha256": sha256,
            "evidence_scope": values["evidence_scope"], "snapshot": snapshot,
        }

    def _commit_maintenance_link(self, db, values):
        maintenance = db.execute(
            "SELECT id,event_number,status FROM maintenance_records WHERE id=?",
            (values["maintenance_record"]["id"],),
        ).fetchone()
        if not maintenance or dict(maintenance) != values["maintenance_record"]:
            raise PurchaseError("maintenance record changed after preview; review again")
        line = values["purchase_line"]
        if line:
            current_line = db.execute(
                """SELECT id,purchase_order_id,line_number,description
                FROM purchase_order_lines WHERE id=?""", (line["id"],)
            ).fetchone()
            if not current_line or dict(current_line) != line:
                raise PurchaseError("purchase line changed after preview; review again")
        link_id = db.execute(
            """INSERT INTO purchase_maintenance_links(
            link_uuid,purchase_order_id,purchase_order_line_id,maintenance_record_id,
            relationship_type,note,linked_by) VALUES (?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()), values["purchase"]["id"],
                line["id"] if line else None, maintenance["id"],
                values["relationship_type"], values["note"], values["actor"],
            ),
        ).lastrowid
        snapshot = dict(db.execute(
            "SELECT * FROM purchase_maintenance_links WHERE id=?", (link_id,)
        ).fetchone())
        return {
            "purchase_id": values["purchase"]["id"],
            "purchase_number": values["purchase"]["purchase_number"],
            "link_id": link_id, "maintenance_number": maintenance["event_number"],
            "relationship_type": values["relationship_type"], "snapshot": snapshot,
        }

    def _phase2a_history(self, db, values, body, snapshot):
        return db.execute(
            """INSERT INTO purchase_history(
            history_uuid,request_nonce,purchase_order_id,action_type,previous_status,
            new_status,snapshot,payload_sha256,reason,actor)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()), values["request_nonce"], values["purchase"]["id"],
                values["action"], values["purchase"]["status"],
                values["purchase"]["status"],
                json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
                hashlib.sha256(body).hexdigest(), values.get("reason"), values["actor"],
            ),
        ).lastrowid

    def _purchase_snapshot(self, db, purchase_id):
        row = db.execute(
            """SELECT id,purchase_number,status,updated_at,total_cents
            FROM purchase_orders WHERE id=?""", (purchase_id,)
        ).fetchone()
        if not row:
            raise PurchaseError("purchase not found")
        return dict(row)

    def _action_values(self, action, actor, purchase):
        return {
            "version": 1, "module": self.MODULE, "action": action,
            "reviewed_at": int(time.time()), "request_nonce": uuid.uuid4().hex,
            "actor": actor, "purchase": purchase,
        }

    def _review_result(self, values):
        body = self._canonical(values)
        return {
            "token": self._sign_body(body), "values": values,
            "payload_sha256": hashlib.sha256(body).hexdigest(),
        }

    @staticmethod
    def _file_identity(path):
        if not path.is_file():
            raise PurchaseError("evidence file no longer exists")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest(), path.stat().st_size

    def _review_lines(self, db, source) -> list[dict]:
        if not isinstance(source, list) or not source:
            raise PurchaseError("at least one purchase line is required")
        result = []
        for index, raw in enumerate(source, 1):
            if not isinstance(raw, dict):
                raise PurchaseError("purchase lines are invalid")
            code = self._text(raw.get("category_code"), "line category", 60)
            category = db.execute(
                "SELECT id,category_code FROM purchase_categories "
                "WHERE category_code=? AND active=1", (code,)
            ).fetchone()
            if not category:
                raise PurchaseError(f"line {index} has an invalid category")
            quantity = self._quantity(raw.get("quantity_ordered"), index)
            unit_price = self._cents(raw.get("unit_price_cents"), f"line {index} unit price")
            line_discount = self._cents(
                raw.get("line_discount_cents", 0), f"line {index} discount"
            )
            exact_total = Decimal(quantity) * unit_price - line_discount
            if exact_total != exact_total.to_integral_value() or exact_total < 0:
                raise PurchaseError(f"line {index} total must resolve to whole cents")
            supplied_total = self._cents(
                raw.get("line_total_cents"), f"line {index} total"
            )
            if supplied_total != int(exact_total):
                raise PurchaseError(f"line {index} total does not match quantity and price")
            tracking = self._text(
                raw.get("inventory_tracking_intent", "non_inventory"),
                f"line {index} tracking intent", 30,
            )
            if tracking not in self.TRACKING_INTENTS:
                raise PurchaseError(f"line {index} has an invalid tracking intent")
            catalog_item_id = self._optional_positive_int(
                raw.get("catalog_item_id"), f"line {index} catalog item"
            )
            if catalog_item_id:
                item = db.execute(
                    """SELECT ci.id,it.tracking_method FROM catalog_items ci
                    JOIN item_types it ON it.id=ci.item_type_id WHERE ci.id=?""",
                    (catalog_item_id,),
                ).fetchone()
                if not item:
                    raise PurchaseError(f"line {index} catalog item was not found")
                if tracking != item["tracking_method"]:
                    raise PurchaseError(
                        f"line {index} tracking intent does not match its catalog item"
                    )
            result.append({
                "line_number": index,
                "category_id": category["id"],
                "category_code": category["category_code"],
                "description": self._text(raw.get("description"), f"line {index} description", 500),
                "vendor_sku": self._optional_text(raw.get("vendor_sku"), 200),
                "catalog_item_id": catalog_item_id,
                "quantity_ordered": quantity,
                "unit_label": self._text(raw.get("unit_label"), f"line {index} unit", 50),
                "unit_price_cents": unit_price,
                "line_discount_cents": line_discount,
                "line_total_cents": supplied_total,
                "inventory_tracking_intent": tracking,
                "notes": self._optional_text(raw.get("notes"), 1000),
            })
        return result

    def _commit_vendor(self, db, values) -> int:
        if values["vendor_id"]:
            current = db.execute(
                "SELECT * FROM purchase_vendors WHERE id=? AND active=1",
                (values["vendor_id"],),
            ).fetchone()
            if not current or dict(current) != values["vendor_existing_snapshot"]:
                raise PurchaseError("vendor changed after preview; review again")
            return current["id"]
        duplicate = db.execute(
            "SELECT id FROM purchase_vendors WHERE lower(trim(name))=lower(trim(?))",
            (values["vendor_name"],),
        ).fetchone()
        if duplicate:
            raise PurchaseError("vendor registry changed after preview; review again")
        return db.execute(
            "INSERT INTO purchase_vendors(vendor_uuid,name) VALUES (?,?)",
            (str(uuid.uuid4()), values["vendor_name"]),
        ).lastrowid

    def _revalidate_lines(self, db, lines):
        for line in lines:
            category = db.execute(
                "SELECT category_code FROM purchase_categories WHERE id=? AND active=1",
                (line["category_id"],),
            ).fetchone()
            if not category or category["category_code"] != line["category_code"]:
                raise PurchaseError("purchase categories changed after preview; review again")
            if line["catalog_item_id"]:
                item = db.execute(
                    """SELECT it.tracking_method FROM catalog_items ci
                    JOIN item_types it ON it.id=ci.item_type_id WHERE ci.id=?""",
                    (line["catalog_item_id"],),
                ).fetchone()
                if not item or item["tracking_method"] != line["inventory_tracking_intent"]:
                    raise PurchaseError("catalog tracking changed after preview; review again")

    @staticmethod
    def _revalidate_totals(values):
        subtotal = 0
        for line in values["lines"]:
            exact = (
                Decimal(line["quantity_ordered"]) * line["unit_price_cents"]
                - line["line_discount_cents"]
            )
            if exact != exact.to_integral_value() or int(exact) != line["line_total_cents"]:
                raise PurchaseError("signed purchase line totals are inconsistent")
            subtotal += line["line_total_cents"]
        total = (
            subtotal + values["tax_cents"] + values["shipping_cents"]
            - values["discount_cents"]
        )
        if subtotal != values["subtotal_cents"] or total != values["total_cents"]:
            raise PurchaseError("signed purchase totals are inconsistent")

    @staticmethod
    def _snapshot(db, purchase_id):
        order = dict(db.execute(
            "SELECT * FROM purchase_orders WHERE id=?", (purchase_id,)
        ).fetchone())
        lines = [dict(row) for row in db.execute(
            "SELECT * FROM purchase_order_lines WHERE purchase_order_id=? ORDER BY line_number",
            (purchase_id,),
        )]
        return {"purchase": order, "lines": lines}

    @staticmethod
    def _next_number(db):
        maximum = db.execute(
            """SELECT MAX(CAST(SUBSTR(purchase_number,LENGTH('THS-PO')+2) AS INTEGER))
            FROM purchase_orders WHERE purchase_number LIKE 'THS-PO-%'"""
        ).fetchone()[0] or 0
        return f"THS-PO-{maximum + 1:06d}"

    def _sign_body(self, body):
        signature = hmac.new(self.secret, body, hashlib.sha256).digest()
        return self._b64(body) + "." + self._b64(signature)

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
            raise PurchaseError("purchase preview signature is invalid") from exc
        age = int(time.time()) - values.get("reviewed_at", 0)
        if age < -60 or age > self.MAX_REVIEW_AGE_SECONDS:
            raise PurchaseError("purchase preview expired; review it again")
        return values, body

    @staticmethod
    def _canonical(values):
        return json.dumps(values, sort_keys=True, separators=(",", ":")).encode()

    @staticmethod
    def _b64(value):
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    @staticmethod
    def _unb64(value):
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    @staticmethod
    def _text(value, label, maximum):
        value = str(value or "").strip()
        if not value:
            raise PurchaseError(f"{label} is required")
        if len(value) > maximum:
            raise PurchaseError(f"{label} is too long")
        return value

    @staticmethod
    def _optional_text(value, maximum):
        value = str(value or "").strip()
        if not value:
            return None
        if len(value) > maximum:
            raise PurchaseError("optional purchase text is too long")
        return value

    @staticmethod
    def _optional_positive_int(value, label):
        if value in (None, ""):
            return None
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise PurchaseError(f"{label} is invalid") from exc
        if value <= 0:
            raise PurchaseError(f"{label} is invalid")
        return value

    @staticmethod
    def _cents(value, label):
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise PurchaseError(f"{label} must be whole cents") from exc
        if value < 0:
            raise PurchaseError(f"{label} cannot be negative")
        return value

    @staticmethod
    def _quantity(value, line_number):
        try:
            quantity = Decimal(str(value))
        except (InvalidOperation, TypeError) as exc:
            raise PurchaseError(f"line {line_number} quantity is invalid") from exc
        if not quantity.is_finite() or quantity <= 0 or quantity.as_tuple().exponent < -3:
            raise PurchaseError(
                f"line {line_number} quantity must be positive with at most three decimals"
            )
        return format(quantity.normalize(), "f")
