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


class PurchaseLineCorrectionError(ValueError):
    """A purchase-line correction preview or commit is invalid or stale."""


class PurchaseLineCorrectionService:
    MODULE = "purchase-line-tracking-correction"
    MAX_REVIEW_AGE_SECONDS = 30 * 60
    POLICIES = {"individual", "quantity", "lot", "non_inventory"}
    ORIGINS = {"user", "maeve", "importer", "system", "api", "integration", "project"}

    def __init__(self, database, secret: bytes | None = None):
        self.database = Path(database)
        self.secret = secret or secrets.token_bytes(32)

    def review(self, form: dict) -> dict:
        actor = self._text(form.get("actor"), "actor", 100)
        origin = self._text(form.get("origin", "user"), "origin", 20)
        if origin not in self.ORIGINS:
            raise PurchaseLineCorrectionError("invalid correction origin")
        reason = self._text(form.get("reason"), "reason", 2000)
        provenance = self._text(form.get("provenance"), "provenance", 2000)
        raw_lines = form.get("lines")
        if not isinstance(raw_lines, list) or not raw_lines:
            raise PurchaseLineCorrectionError("select at least one purchase line")
        with closing(connect(self.database)) as db:
            lines = self._review_lines(db, raw_lines)
        values = {
            "version": 1, "module": self.MODULE, "action": "correct_tracking_policy",
            "reviewed_at": int(time.time()), "request_nonce": uuid.uuid4().hex,
            "actor": actor, "origin": origin, "reason": reason,
            "provenance": provenance, "lines": lines,
        }
        body = self._canonical(values)
        return {"token": self._sign(body), "values": values,
                "payload_sha256": hashlib.sha256(body).hexdigest()}

    def commit(self, token: str, *, confirmed: bool) -> dict:
        if not confirmed:
            raise PurchaseLineCorrectionError("explicit confirmation is required")
        values, body = self._verify(token)
        if values.get("version") != 1 or values.get("module") != self.MODULE \
                or values.get("action") != "correct_tracking_policy":
            raise PurchaseLineCorrectionError("correction preview is invalid")
        nonce = values.get("request_nonce")
        if not isinstance(nonce, str) or len(nonce) != 32 \
                or any(character not in "0123456789abcdef" for character in nonce):
            raise PurchaseLineCorrectionError("correction preview nonce is invalid")
        payload_sha256 = hashlib.sha256(body).hexdigest()
        db = connect(self.database)
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM purchase_line_tracking_corrections WHERE request_nonce=?",
                          (values["request_nonce"],)).fetchone():
                raise PurchaseLineCorrectionError("this correction preview was already used")
            self._revalidate(db, values["lines"])
            ids = []
            for line in values["lines"]:
                row_id = db.execute(
                    """INSERT INTO purchase_line_tracking_corrections(
                    correction_uuid,request_nonce,purchase_order_line_id,
                    original_tracking_policy,effective_tracking_policy,reason,actor,
                    module,origin,provenance,payload_sha256)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (line["correction_uuid"], values["request_nonce"], line["id"],
                     line["original_tracking_policy"], line["effective_tracking_policy"],
                     values["reason"], values["actor"], self.MODULE, values["origin"],
                     values["provenance"], payload_sha256),
                ).lastrowid
                ids.append(row_id)
            db.commit()
            return {"correction_ids": ids, "line_count": len(ids),
                    "payload_sha256": payload_sha256}
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise PurchaseLineCorrectionError(str(exc)) from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _review_lines(self, db, raw_lines):
        seen = set()
        result = []
        for raw in raw_lines:
            if not isinstance(raw, dict):
                raise PurchaseLineCorrectionError("correction lines are invalid")
            try:
                line_id = int(raw.get("purchase_order_line_id"))
            except (TypeError, ValueError) as exc:
                raise PurchaseLineCorrectionError("purchase line is required") from exc
            if line_id <= 0 or line_id in seen:
                raise PurchaseLineCorrectionError("purchase lines must be unique positive IDs")
            seen.add(line_id)
            row = db.execute(
                """SELECT pol.id,pol.line_uuid,pol.purchase_order_id,pol.line_number,
                pol.inventory_tracking_intent,po.purchase_number,po.vendor_order_number
                FROM purchase_order_lines pol JOIN purchase_orders po
                  ON po.id=pol.purchase_order_id WHERE pol.id=?""", (line_id,)
            ).fetchone()
            if not row:
                raise PurchaseLineCorrectionError("purchase line was not found")
            if db.execute("SELECT 1 FROM purchase_line_tracking_corrections WHERE purchase_order_line_id=?",
                          (line_id,)).fetchone():
                raise PurchaseLineCorrectionError("purchase line already has an active correction")
            if db.execute("SELECT 1 FROM purchase_receipt_lines WHERE purchase_order_line_id=?",
                          (line_id,)).fetchone():
                raise PurchaseLineCorrectionError("received purchase lines cannot be corrected")
            effective = self._text(raw.get("effective_tracking_policy"), "effective policy", 20)
            if effective not in self.POLICIES:
                raise PurchaseLineCorrectionError("invalid effective tracking policy")
            if effective == row["inventory_tracking_intent"]:
                raise PurchaseLineCorrectionError("effective policy must correct the original policy")
            result.append({
                "id": row["id"], "line_uuid": row["line_uuid"],
                "purchase_order_id": row["purchase_order_id"],
                "purchase_number": row["purchase_number"],
                "vendor_order_number": row["vendor_order_number"],
                "line_number": row["line_number"],
                "original_tracking_policy": row["inventory_tracking_intent"],
                "effective_tracking_policy": effective,
                "correction_uuid": str(uuid.uuid4()),
            })
        return result

    def _revalidate(self, db, lines):
        for expected in lines:
            current = db.execute(
                """SELECT pol.id,pol.line_uuid,pol.purchase_order_id,pol.line_number,
                pol.inventory_tracking_intent,po.purchase_number,po.vendor_order_number
                FROM purchase_order_lines pol JOIN purchase_orders po
                  ON po.id=pol.purchase_order_id WHERE pol.id=?""", (expected["id"],)
            ).fetchone()
            if not current or any(current[key] != expected[key] for key in (
                "id", "line_uuid", "purchase_order_id", "line_number", "purchase_number",
                "vendor_order_number"
            )) or current["inventory_tracking_intent"] != expected["original_tracking_policy"]:
                raise PurchaseLineCorrectionError("purchase line changed after preview; review again")
            if db.execute("SELECT 1 FROM purchase_line_tracking_corrections WHERE purchase_order_line_id=?",
                          (expected["id"],)).fetchone():
                raise PurchaseLineCorrectionError("purchase line already has an active correction")
            if db.execute("SELECT 1 FROM purchase_receipt_lines WHERE purchase_order_line_id=?",
                          (expected["id"],)).fetchone():
                raise PurchaseLineCorrectionError("received purchase lines cannot be corrected")

    def _sign(self, body):
        signature = hmac.new(self.secret, body, hashlib.sha256).digest()
        return self._b64(body) + "." + self._b64(signature)

    def _verify(self, token):
        try:
            body_text, signature_text = token.split(".", 1)
            body, signature = self._unb64(body_text), self._unb64(signature_text)
            if self._b64(body) != body_text or not hmac.compare_digest(
                    signature, hmac.new(self.secret, body, hashlib.sha256).digest()):
                raise ValueError
            values = json.loads(body)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PurchaseLineCorrectionError("correction preview signature is invalid") from exc
        age = int(time.time()) - values.get("reviewed_at", 0)
        if age < -60 or age > self.MAX_REVIEW_AGE_SECONDS:
            raise PurchaseLineCorrectionError("correction preview expired; review again")
        return values, body

    @staticmethod
    def _canonical(values):
        return json.dumps(values, sort_keys=True, separators=(",", ":")).encode()

    @staticmethod
    def _b64(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    @staticmethod
    def _unb64(value):
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    @staticmethod
    def _text(value, label, maximum):
        text = str(value or "").strip()
        if not text:
            raise PurchaseLineCorrectionError(f"{label} is required")
        if len(text) > maximum:
            raise PurchaseLineCorrectionError(f"{label} is too long")
        return text
